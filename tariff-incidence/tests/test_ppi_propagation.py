"""BLS PPI adapter and wild cluster bootstrap tests."""

from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from tariff_incidence.adapters.bls_ppi import (
    BEA_TO_NAICS,
    PPILoad,
    PPIMatchQuality,
    series_id,
    to_bea_panel,
)
from tariff_incidence.econ.hdfe import wild_cluster_bootstrap


def test_series_id_pads_to_the_bls_convention():
    assert series_id("325") == "PCU325---325---"
    assert series_id("3361") == "PCU3361--3361--"
    assert len(series_id("339")) == len(series_id("3364"))


def test_every_bea_industry_maps_to_naics_components():
    """The map must agree with the one used on the trade side."""
    from tariff_incidence.adapters.census_concordance import _BEA_COMPOSITES, _BEA_DIRECT

    for bea in list(_BEA_COMPOSITES) + list(_BEA_DIRECT):
        assert bea in BEA_TO_NAICS, f"{bea} missing from the PPI mapping"
    assert BEA_TO_NAICS["3361MV"] == ("3361", "3362", "3363")
    assert BEA_TO_NAICS["315AL"] == ("315", "316")


def _load(match_rows: list[dict], obs: list[dict]) -> PPILoad:
    return PPILoad(
        observations=pl.DataFrame(obs),
        industry_match=pl.DataFrame(match_rows),
        n_series_requested=len(match_rows),
        n_series_returned=len(obs),
    )


def test_bea_panel_averages_only_the_matched_components():
    import datetime as dt

    load = _load(
        [
            {
                "bea_industry": "315AL", "naics_components": "315|316",
                "matched_components": "315", "n_components": 2, "n_matched": 1,
                "match_quality": PPIMatchQuality.PARTIAL_COMPOSITE.value,
            }
        ],
        [
            {"series_id": "PCU315---315---", "naics": "315", "year": 2019, "month": 1,
             "month_date": dt.date(2019, 1, 1), "index_value": 120.0},
        ],
    )
    panel = to_bea_panel(load)
    assert panel.height == 1
    r = panel.row(0, named=True)
    assert r["ppi_index"] == pytest.approx(120.0)
    assert r["n_component_series"] == 1
    assert r["ppi_match_quality"] == "PARTIAL_COMPOSITE"


def test_unmatched_industries_do_not_appear_in_the_panel():
    """An industry with no series must be absent, not carry a substituted value."""
    load = _load(
        [
            {
                "bea_industry": "111CA", "naics_components": "111|112",
                "matched_components": "", "n_components": 2, "n_matched": 0,
                "match_quality": PPIMatchQuality.NONE.value,
            }
        ],
        [],
    )
    assert to_bea_panel(load).height == 0


# --------------------------------------------------------------------- #
# wild cluster bootstrap
# --------------------------------------------------------------------- #


def _few_cluster_panel(effect: float, seed: int, n_clusters: int = 22, n_periods: int = 48):
    rng = np.random.default_rng(seed)
    g = np.repeat(np.arange(n_clusters), n_periods)
    t = np.tile(np.arange(n_periods), n_clusters)
    exposure = rng.uniform(0, 1, n_clusters)[g]
    post = (t >= n_periods // 2).astype(float)
    x = exposure * post
    y = rng.normal(0, 1.0, n_clusters)[g] + effect * x + rng.normal(0, 0.25, g.size)
    return y, x[:, None], g, t


def test_bootstrap_does_not_reject_when_there_is_no_effect():
    y, X, g, t = _few_cluster_panel(effect=0.0, seed=3)
    r = wild_cluster_bootstrap(y, X, ["x"], {"g": g, "t": t}, g, n_boot=299)
    assert r["bootstrap_p_value"] > 0.10
    assert r["n_clusters"] == 22


def test_bootstrap_rejects_a_large_true_effect():
    y, X, g, t = _few_cluster_panel(effect=2.0, seed=5)
    r = wild_cluster_bootstrap(y, X, ["x"], {"g": g, "t": t}, g, n_boot=299)
    assert r["bootstrap_p_value"] < 0.05
    assert r["estimate"] == pytest.approx(2.0, abs=0.15)


def test_bootstrap_reports_both_p_values_so_they_can_be_compared():
    y, X, g, t = _few_cluster_panel(effect=0.5, seed=7)
    r = wild_cluster_bootstrap(y, X, ["x"], {"g": g, "t": t}, g, n_boot=299)
    for k in ("analytic_p_value", "bootstrap_p_value", "n_clusters", "n_boot"):
        assert k in r
    assert 0.0 <= r["bootstrap_p_value"] <= 1.0
    assert "over-reject" in r["caveat"]


def test_bootstrap_tests_the_requested_coefficient():
    """With two regressors the test index must select the right one."""
    rng = np.random.default_rng(11)
    y, X1, g, t = _few_cluster_panel(effect=0.0, seed=13)
    x2 = rng.normal(size=y.size)
    y = y + 3.0 * x2
    X = np.column_stack([X1[:, 0], x2])
    r0 = wild_cluster_bootstrap(y, X, ["a", "b"], {"g": g, "t": t}, g, test_index=0, n_boot=299)
    r1 = wild_cluster_bootstrap(y, X, ["a", "b"], {"g": g, "t": t}, g, test_index=1, n_boot=299)
    assert r0["coefficient"] == "a"
    assert r1["coefficient"] == "b"
    assert r0["bootstrap_p_value"] > 0.10
    assert r1["bootstrap_p_value"] < 0.05


def test_series_cache_splits_and_rejoins_by_year(tmp_path, monkeypatch):
    """A window already held in part must not cost a fresh request.

    BLS allows only a handful of requests per address per day. Caching whole
    request payloads meant that asking for 2017-2019 after having fetched 2019
    re-requested everything; per-year files make the cost proportional to what
    is actually missing.
    """
    from tariff_incidence.adapters import base, bls_ppi

    monkeypatch.setattr(base, "RAW", tmp_path)
    sid = "PCU325---325---"
    payload = {
        "seriesID": sid,
        "data": [
            {"year": "2019", "period": "M01", "value": "110.0"},
            {"year": "2018", "period": "M01", "value": "105.0"},
            {"year": "2017", "period": "M01", "value": "100.0"},
        ],
    }
    bls_ppi._write_cached_series(sid, 2017, 2019, payload)

    have, missing = bls_ppi._load_cached_series([sid], 2017, 2019)
    assert missing == []
    assert {o["year"] for o in have[sid]["data"]} == {"2017", "2018", "2019"}

    # A window extending past what was cached is still a miss, not a partial.
    have, missing = bls_ppi._load_cached_series([sid], 2017, 2020)
    assert missing == [sid]
    assert have == {}


def test_year_with_no_observations_is_remembered_as_empty(tmp_path, monkeypatch):
    """"This series does not cover 2017" is an answer worth caching."""
    from tariff_incidence.adapters import base, bls_ppi

    monkeypatch.setattr(base, "RAW", tmp_path)
    sid = "PCU333911333911"
    bls_ppi._write_cached_series(
        sid, 2017, 2019, {"seriesID": sid, "data": [{"year": "2019", "period": "M01", "value": "1"}]}
    )
    have, missing = bls_ppi._load_cached_series([sid], 2017, 2019)
    assert missing == []
    assert len(have[sid]["data"]) == 1


def test_seeding_from_raw_responses_costs_no_requests(tmp_path, monkeypatch):
    """Raw bodies are kept for provenance; reading them back is free."""
    import json

    from tariff_incidence.adapters import base, bls_ppi

    monkeypatch.setattr(base, "RAW", tmp_path)
    (tmp_path / "bls").mkdir(parents=True)
    (tmp_path / "bls" / "bls_ppi_2017_2019_abc123.json").write_text(
        json.dumps(
            {
                "status": "REQUEST_SUCCEEDED",
                "Results": {
                    "series": [
                        {
                            "seriesID": "PCU326---326---",
                            "data": [{"year": "2018", "period": "M03", "value": "99.9"}],
                        }
                    ]
                },
            }
        )
    )
    assert bls_ppi.seed_series_cache_from_raw_responses() == 1
    have, missing = bls_ppi._load_cached_series(["PCU326---326---"], 2017, 2019)
    assert missing == []
    assert have["PCU326---326---"]["data"][0]["value"] == "99.9"
