"""Cross-artefact consistency checks, tested against the defects they exist for.

A check that passes on corrected data proves nothing. Each test here rebuilds
the artefact as it actually was when the defect was live and asserts the check
fails on it, then asserts it passes on the corrected shape. The defects are the
ones found by reading the eleven generated reports end to end; every one was
invisible to the rest of the suite because each was a disagreement between two
artefacts that no code compared.
"""

from __future__ import annotations

import datetime as dt

import polars as pl
import pytest

from tariff_incidence.quality import consistency


def _write(tmp_path, name: str, df: pl.DataFrame):
    df.write_parquet(tmp_path / f"{name}.parquet")


@pytest.fixture
def results(tmp_path):
    (tmp_path / "results").mkdir()
    (tmp_path / "normalized").mkdir()
    return tmp_path / "results"


def _totals() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "treated_total": [-2_073_786_984.0],
            "alternative_total": [720_472_276.0],
            "pre_treated_value": [6_629_075_528.0],
        }
    )


def test_partition_check_catches_the_fan_out_that_inflated_it_3x(results):
    """The heterogeneity split summed to 3.16x the totals it partitions.

    `pretreatment_treated_country_share` is a 10-digit attribute and `.unique()`
    over (hs6, share) kept one row per distinct share, so the join multiplied
    each heading. The percentage columns were exactly right throughout, because
    numerator and denominator inflate together -- which is why only a comparison
    against the totals could find it.
    """
    _write(results, "diversion_totals", _totals())

    inflated = pl.DataFrame(
        {
            "dependence_group": ["low_dependence", "high_dependence"],
            "treated_change": [-1_952_314_606.0, -3_698_639_861.0],
            "alternative_change": [946_665_403.0, 633_262_647.0],
            "pre_treated_value": [6_959_404_501.0, 13_977_402_505.0],
        }
    )
    _write(results, "diversion_heterogeneity_by_dependence", inflated)
    bad = consistency.check_diversion_partition_sums(results)
    assert bad.passed is False
    assert "treated_change" in bad.detail

    corrected = pl.DataFrame(
        {
            "dependence_group": ["low_dependence", "high_dependence"],
            "treated_change": [-467_550_000.0, -1_606_238_281.0],
            "alternative_change": [327_510_000.0, 392_962_276.0],
            "pre_treated_value": [1_433_700_000.0, 5_195_375_528.0],
        }
    )
    _write(results, "diversion_heterogeneity_by_dependence", corrected)
    assert consistency.check_diversion_partition_sums(results).passed is True


def test_partition_check_tolerates_a_documented_exclusion(results):
    """Five headings with no pre-window imports are legitimately dropped.

    The tolerance has to admit that without admitting a fan-out, which multiplies
    rather than shaves.
    """
    _write(results, "diversion_totals", _totals())
    _write(
        results,
        "diversion_heterogeneity_by_dependence",
        pl.DataFrame(
            {
                "dependence_group": ["low", "high"],
                "treated_change": [-467_550_000.0, -1_606_236_984.0],  # short by $1,297
                "alternative_change": [327_510_000.0, 392_962_276.0],
                "pre_treated_value": [1_433_700_000.0, 5_195_375_528.0],
            }
        ),
    )
    assert consistency.check_diversion_partition_sums(results).passed is True


def test_country_gains_must_sum_to_the_alternative_total(results):
    _write(results, "diversion_totals", _totals())
    _write(
        results,
        "diversion_country_gains",
        pl.DataFrame(
            {
                "country_code": ["2010", "5800", "5700"],
                "change": [412_964_472.0, 307_507_804.0, -2_073_786_984.0],
                "is_treated_country": [False, False, True],
            }
        ),
    )
    assert consistency.check_country_gains_sum(results).passed is True

    _write(
        results,
        "diversion_country_gains",
        pl.DataFrame(
            {
                "country_code": ["2010", "5700"],
                "change": [1.0, -2_073_786_984.0],
                "is_treated_country": [False, True],
            }
        ),
    )
    assert consistency.check_country_gains_sum(results).passed is False


def test_spec_register_level_check_catches_a_stale_aggregation_level(results):
    """The register said hs6 for four sessions after the panel moved to hs10."""
    panel = pl.DataFrame({"hs10": ["1234567890"], "hs6": ["123456"]})
    _write(
        results,
        "specification_register",
        pl.DataFrame({"aggregation_level": ["hs6 x country x month"] * 3}),
    )
    stale = consistency.check_specification_level_matches_panel(results, panel)
    assert stale.passed is False
    assert "hs10" in stale.detail

    _write(
        results,
        "specification_register",
        pl.DataFrame({"aggregation_level": ["hs10 x country x month"] * 3}),
    )
    assert consistency.check_specification_level_matches_panel(results, panel).passed is True


def test_incidence_headline_must_be_selectable_not_positional(results):
    """Without control_definition the headline design is selectable only by row order.

    That is the state in which the report could not read the numbers at all, and
    so carried them as literals that drifted.
    """
    without = pl.DataFrame(
        {
            "term": ["stacked_mean_post_effect"] * 2,
            "outcome": ["log_landed_unit_value", "log_customs_unit_value"],
            "estimate": [0.1544, 0.0253],
        }
    )
    _write(results, "incidence_estimates", without)
    r = consistency.check_reported_incidence_matches_estimates(results)
    assert r.passed is False
    assert "row order" in r.detail

    with_col = without.with_columns(pl.lit("never_treated_products").alias("control_definition"))
    _write(results, "incidence_estimates", with_col)
    assert consistency.check_reported_incidence_matches_estimates(results).passed is True


def test_incidence_check_catches_an_ambiguous_headline_row(results):
    """Two rows for one outcome under one control definition is not selectable either."""
    dupes = pl.DataFrame(
        {
            "term": ["stacked_mean_post_effect"] * 3,
            "outcome": [
                "log_landed_unit_value",
                "log_landed_unit_value",
                "log_customs_unit_value",
            ],
            "estimate": [0.1544, 0.1499, 0.0253],
            "control_definition": ["never_treated_products"] * 3,
        }
    )
    _write(results, "incidence_estimates", dupes)
    assert consistency.check_reported_incidence_matches_estimates(results).passed is False


def test_exclusion_bound_must_not_start_before_any_duty_existed(results):
    """Six pre-tariff months in the denominator halved the baseline.

    A month before the first action cannot contain a flow falling short of a
    Section 301 duty, so its presence proves the population was conditioned on
    something else -- it was the total rate, which includes baseline MFN.
    """
    (results.parent / "normalized" / "tariff_schedule.parquet").parent.mkdir(exist_ok=True)
    pl.DataFrame({"effective_date": [dt.date(2018, 7, 6), dt.date(2018, 8, 23)]}).write_parquet(
        results.parent / "normalized" / "tariff_schedule.parquet"
    )

    diluted = pl.DataFrame(
        {
            "month_date": [dt.date(2018, 1, 1), dt.date(2018, 7, 1), dt.date(2019, 1, 1)],
            "customs_value": [7.5e9, 1.0e9, 1.0e9],
        }
    )
    _write(results, "exclusion_itt_bound_by_month", diluted)
    bad = consistency.check_exclusion_bound_population(results)
    assert bad.passed is False
    assert bad.n_flagged == 1

    _write(results, "exclusion_itt_bound_by_month", diluted.tail(2))
    assert consistency.check_exclusion_bound_population(results).passed is True


def test_missing_artefacts_are_skipped_rather_than_failed(results):
    """A partial pipeline run must not be reported as an inconsistency."""
    out = consistency.run_all(results, panel=None)
    assert out
    assert all(r.passed is None for r in out)


def test_run_all_invokes_every_check_defined_in_the_module():
    """A check that exists but is not wired into run_all protects nothing.

    Asserting a literal count here would just need bumping; asserting against
    the module's own check functions makes an omission fail instead.
    """
    defined = {
        name for name in dir(consistency)
        if name.startswith("check_") and callable(getattr(consistency, name))
    }
    import inspect

    source = inspect.getsource(consistency.run_all)
    missing = sorted(n for n in defined if n not in source)
    assert not missing, f"defined but never run: {missing}"


def test_placebo_coverage_check_catches_an_outcome_tested_only_one_way(results, tmp_path):
    """The date placebo ran on log_quantity alone and named no outcome.

    So the report carried a placebo reporting a significant effect with nothing
    saying what it applied to, while the two price outcomes the incidence claim
    rests on were never date-placebo-tested at all. An outcome licensed by one
    test and untested by the other is a gap a reader cannot see.
    """
    import json

    def _ident(placebo_outcomes):
        return {
            "pretrend_tests": {
                f"pretrend_stacked_{o}_never_treated_products": {"verdict": "CLEAN"}
                for o in ("log_customs_unit_value", "log_landed_unit_value", "log_quantity")
            },
            "checks": [
                {"check": "placebo_treatment_date_minus_12m", "outcome": o}
                for o in placebo_outcomes
            ],
        }

    (results / "identification_checks.json").write_text(json.dumps(_ident(["log_quantity"])))
    bad = consistency.check_placebo_covers_every_verdicted_outcome(results)
    assert bad.passed is False
    assert "log_customs_unit_value" in bad.detail
    assert "log_landed_unit_value" in bad.detail

    (results / "identification_checks.json").write_text(
        json.dumps(
            _ident(["log_customs_unit_value", "log_landed_unit_value", "log_quantity"])
        )
    )
    assert consistency.check_placebo_covers_every_verdicted_outcome(results).passed is True


def test_placebo_coverage_check_rejects_an_unnamed_placebo(results):
    """A placebo row with no outcome field covers nothing, whatever it ran on."""
    import json

    (results / "identification_checks.json").write_text(
        json.dumps(
            {
                "pretrend_tests": {
                    "pretrend_stacked_log_quantity_never_treated_products": {"verdict": "CLEAN"}
                },
                "checks": [{"check": "placebo_treatment_date_minus_12m"}],
            }
        )
    )
    assert consistency.check_placebo_covers_every_verdicted_outcome(results).passed is False


def test_headline_check_catches_a_robustness_variant_promoted_to_headline(results):
    """A robustness run wrote the same term under the same control definition.

    The stable-code variant re-estimates the headline design on a subsample, so
    it legitimately carries `term=stacked_mean_post_effect` and
    `control_definition=never_treated_products`. Selecting on that pair alone
    matched six rows instead of three, and the report promoted the robustness
    figures to the headline -- printing +0.1362 and +0.0058 in place of +0.1544
    and +0.0253. The rung distinguishes them.
    """
    both = pl.DataFrame(
        {
            "term": ["stacked_mean_post_effect"] * 4,
            "outcome": [
                "log_landed_unit_value",
                "log_customs_unit_value",
                "log_landed_unit_value",
                "log_customs_unit_value",
            ],
            "estimate": [0.1544, 0.0253, 0.1362, 0.0058],
            "control_definition": ["never_treated_products"] * 4,
            "rung": ["4_stacked", "4_stacked", "4_stacked_stable_codes",
                     "4_stacked_stable_codes"],
        }
    )
    _write(results, "incidence_estimates", both)
    # With the rung distinguishing them the headline is unambiguous again.
    assert consistency.check_reported_incidence_matches_estimates(results).passed is True

    # Drop the rung and the same rows become an ambiguous headline.
    _write(results, "incidence_estimates", both.drop("rung"))
    assert consistency.check_reported_incidence_matches_estimates(results).passed is False
