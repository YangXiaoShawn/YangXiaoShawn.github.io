from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import duckdb
import polars as pl
import pytest

from macro_nowcast import multitarget_pipeline
from macro_nowcast.sample_data import build_multitarget_synthetic_fixture
from macro_nowcast.targets import assert_target_audit


def _short_config(source: Path, destination: Path) -> Path:
    current_target = ""
    output: list[str] = []
    for line in source.read_text().splitlines():
        if line.startswith('series_id = "') and current_target == "":
            current_target = line.split('"')[1]
        if line.startswith("start = "):
            line = 'start = "2020-01-01"'
        elif line.startswith("end = "):
            line = 'end = "2020-07-01"' if current_target == "GDPC1" else 'end = "2020-11-01"'
        elif line.startswith("latest_vintage = "):
            line = 'latest_vintage = "2020-12-31"'
        elif line.startswith("minimum_train_periods = "):
            line = (
                "minimum_train_periods = 3"
                if current_target == "GDPC1"
                else "minimum_train_periods = 8"
            )
        output.append(line)
        if line.startswith("[[targets]]"):
            current_target = ""
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n".join(output) + "\n")
    return destination


def test_multitarget_reproduction_is_audited_and_reproducible(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = Path(__file__).resolve().parents[1]
    config = _short_config(
        root / "config" / "targets.toml",
        tmp_path / "config" / "targets.toml",
    )

    def short_fixture():
        return build_multitarget_synthetic_fixture(
            start=date(2019, 1, 1),
            end=date(2020, 12, 1),
        )

    monkeypatch.setattr(
        multitarget_pipeline,
        "build_multitarget_synthetic_fixture",
        short_fixture,
    )
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_result = multitarget_pipeline.reproduce_multitarget(
        config,
        output_dir=first_root,
    )
    second_result = multitarget_pipeline.reproduce_multitarget(
        config,
        output_dir=second_root,
    )

    assert first_result["artifact_stage"] == "multitarget_backtest_complete"
    assert first_result["fixture_label"] == "synthetic_fixture"
    assert first_result["network_used"] is False
    assert first_result["targets"] == 3
    assert first_result["models"] == 6
    assert first_result["forecasts"] > 0
    assert first_result["timing_violations"] == 0
    assert first_result["naive_leakage_cells"] > 0
    assert first_result["release_updates"] == 3
    assert first_result["policy_briefs"] == 3
    assert {**first_result, "output": None} == {**second_result, "output": None}

    first_manifest = json.loads((first_root / "run_manifest.json").read_text())
    second_manifest = json.loads((second_root / "run_manifest.json").read_text())
    assert first_manifest["artifact_sha256"] == second_manifest["artifact_sha256"]
    assert first_manifest["target_series_ids"] == ["PAYEMS", "CPILFESL", "GDPC1"]
    assert first_manifest["api_txt_read"] is False
    assert first_manifest["empirical_findings_supported"] is False
    assert first_manifest["feature_modes"] == [
        "as_of",
        "latest_values_same_eligibility_mask",
        "naive_latest_revised",
    ]
    assert first_manifest["release_update_count"] == 3
    assert first_manifest["policy_brief_count"] == 3

    features = pl.read_parquet(first_root / "features_long.parquet")
    assert features.filter(
        (pl.col("information_set_mode") == "as_of")
        & (pl.col("max_source_availability") > pl.col("as_of_timestamp"))
    ).is_empty()
    assert features.filter(
        (pl.col("information_set_mode") == "latest_values_same_eligibility_mask")
        & (pl.col("max_eligibility_availability") > pl.col("as_of_timestamp"))
    ).is_empty()
    assert not features.filter(
        (pl.col("information_set_mode") == "naive_latest_revised")
        & (pl.col("max_eligibility_availability") > pl.col("as_of_timestamp"))
    ).is_empty()
    gdp_monthly = features.filter(
        (pl.col("target_series_id") == "GDPC1") & (pl.col("source_series_id") == "INDPRO")
    )
    assert set(gdp_monthly["expected_period_observation_count"].unique()) == {3}
    assert gdp_monthly["coverage_ratio"].max() <= 1.0

    targets = pl.read_parquet(first_root / "targets.parquet")
    assert_target_audit(targets)
    assert set(targets["target_series_id"].unique()) == {
        "PAYEMS",
        "CPILFESL",
        "GDPC1",
    }
    gdp_targets = targets.filter(pl.col("target_series_id") == "GDPC1")
    assert set(gdp_targets["target_name"].unique()) == {"real_gdp_pct_change_qoq_saar"}
    assert set(gdp_targets["annualization_factor"].drop_nulls().unique()) == {4}

    predictions = pl.read_parquet(first_root / "predictions.parquet")
    assert set(predictions["target_series_id"].unique()) == {
        "PAYEMS",
        "CPILFESL",
        "GDPC1",
    }
    assert set(predictions["data_mode"].unique()) == {
        "vintage_aware",
        "latest_values_same_eligibility_mask",
        "naive_latest_revised",
    }
    assert predictions["model_id"].n_unique() == 6
    assert set(predictions["fixture_label"].unique()) == {"synthetic_fixture"}

    dm = pl.read_parquet(first_root / "dm_comparisons.parquet")
    gdp_dm = dm.filter(pl.col("target_series_id") == "GDPC1")
    assert not gdp_dm.is_empty()
    assert gdp_dm.filter(pl.col("valid")).is_empty()
    assert set(gdp_dm["status"].unique()) == {"insufficient_or_invalid"}

    leakage = pl.read_parquet(first_root / "feature_leakage_audit.parquet")
    strict = leakage.filter(
        pl.col("information_set_mode").is_in(
            ["as_of", "latest_values_same_eligibility_mask"]
        )
    )
    assert strict["first_eligibility_after_origin_cells"].sum() == 0
    naive = leakage.filter(pl.col("information_set_mode") == "naive_latest_revised")
    assert naive["first_eligibility_after_origin_cells"].sum() > 0

    stability = pl.read_parquet(first_root / "model_stability.parquet")
    assert set(stability["target_series_id"].unique()) == {
        "PAYEMS",
        "CPILFESL",
        "GDPC1",
    }
    assert set(stability["comparison_mode"].unique()) == {
        "latest_values_same_eligibility_mask",
        "naive_latest_revised",
    }

    news = json.loads((first_root / "news_updates.json").read_text())
    assert {update["target_series_id"] for update in news["updates"]} == {
        "PAYEMS",
        "CPILFESL",
        "GDPC1",
    }
    for update in news["updates"]:
        assert update["attribution_label"] == "exact"
        assert update["empirical_finding"] is False
        assert update["release_series_frequency"] in {"monthly", "quarterly"}
        assert update["changed_features"]
        contribution_sum = sum(
            item["contribution"] for item in update["contributions"]
        )
        assert contribution_sum == pytest.approx(update["forecast_revision"])
        brief = first_root / "policy_briefs" / f"{update['target_series_id']}_policy_brief.md"
        assert brief.is_file()
        brief_text = brief.read_text()
        assert "SYNTHETIC FIXTURE DEMONSTRATION" in brief_text
        assert "What evidence would change the conclusion" in brief_text

    releases = pl.read_parquet(first_root / "release_calendar.parquet")
    assert set(releases["release_type"].unique()) == {"initial", "revision"}

    with duckdb.connect(str(first_root / "macro_nowcast.duckdb"), read_only=True) as connection:
        counts = connection.execute(
            "SELECT target_series_id, count(*) FROM predictions GROUP BY 1 ORDER BY 1"
        ).fetchall()
    assert {row[0] for row in counts} == {"PAYEMS", "CPILFESL", "GDPC1"}

    report = (first_root / "multitarget_report.md").read_text()
    assert "SYNTHETIC FIXTURE DEMONSTRATION" in report
    assert "NO EMPIRICAL FINDINGS" in report
    assert "naive_latest_revised" in report
    assert "Model stability across vintage modes" in report
