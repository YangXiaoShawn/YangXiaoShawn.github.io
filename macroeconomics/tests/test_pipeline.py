from __future__ import annotations

import json
from pathlib import Path

import polars as pl

from macro_nowcast.pipeline import reproduce_sample

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_offline_reproduction_is_labeled_and_leakage_checked(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config_text = (PROJECT_ROOT / "config" / "sample.toml").read_text()
    config_text = config_text.replace('fixture_end = "2025-03-01"', 'fixture_end = "2020-12-01"')
    config_text = config_text.replace("minimum_train_periods = 36", "minimum_train_periods = 24")
    config_text = config_text.replace(
        'evaluation_start = "2021-02-01"', 'evaluation_start = "2019-07-01"'
    )
    config_text = config_text.replace(
        'evaluation_end = "2024-12-01"', 'evaluation_end = "2020-10-01"'
    )
    config_text = config_text.replace(
        'latest_evaluation_date = "2025-03-31"',
        'latest_evaluation_date = "2021-03-31"',
    )
    config_path = config_dir / "sample.toml"
    config_path.write_text(config_text)

    result = reproduce_sample(config_path)

    assert result["fixture_label"] == "synthetic_fixture"
    assert result["network_used"] is False
    assert result["series"] == 10
    assert result["asof_violations"] == 0
    assert int(result["forecasts"]) > 0

    generated = tmp_path / "data" / "generated"
    manifest = json.loads((generated / "run_manifest.json").read_text())
    assert manifest["empirical_findings_supported"] is False
    assert manifest["fred_api_accessed"] is False
    assert manifest["feature_modes"] == [
        "as_of",
        "latest_values_same_eligibility_mask",
    ]

    features = pl.read_parquet(generated / "features_long.parquet")
    valid_violations = features.filter(
        (pl.col("information_set_mode") == "as_of")
        & (pl.col("max_source_availability") > pl.col("as_of_timestamp"))
    )
    counterfactual_violations = features.filter(
        (pl.col("information_set_mode") == "latest_values_same_eligibility_mask")
        & (pl.col("max_eligibility_availability") > pl.col("as_of_timestamp"))
    )
    assert valid_violations.is_empty()
    assert counterfactual_violations.is_empty()

    predictions = pl.read_parquet(generated / "predictions.parquet")
    assert predictions.schema["origin_ts"] == pl.Datetime("us", "UTC")
    assert set(predictions["data_mode"].unique()) == {
        "vintage_aware",
        "latest_values_same_eligibility_mask",
    }
    brief = (tmp_path / "reports" / "sample_policy_brief.md").read_text()
    assert "Synthetic fixture demonstration" in brief
    assert "not empirical" in brief
