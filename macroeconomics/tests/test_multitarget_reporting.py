from __future__ import annotations

import json
from pathlib import Path

import polars as pl
import pytest

from macro_nowcast.multitarget_reporting import (
    dm_diagnostic_summary,
    load_multitarget_artifacts,
    render_multitarget_policy_brief,
    render_multitarget_report,
    write_multitarget_policy_briefs,
    write_multitarget_report,
)


def _manifest() -> dict[str, object]:
    return {
        "artifact_stage": "multitarget_backtest_complete",
        "status": "complete",
        "fixture_label": "synthetic_fixture",
        "empirical_findings_supported": False,
        "timing_violations": {"features": 0, "targets": 0},
        "target_definitions": [
            {
                "target_series_id": "PAYEMS",
                "target_name": "payems_change_mom_thousands",
                "target_frequency": "monthly",
                "target_units": "thousands_of_persons_change_mom",
            },
            {
                "target_series_id": "CPILFESL",
                "target_name": "core_cpi_pct_change_mom",
                "target_frequency": "monthly",
                "target_units": "percent_change_mom_nonannualized",
            },
            {
                "target_series_id": "GDPC1",
                "target_name": "real_gdp_pct_change_qoq_saar",
                "target_frequency": "quarterly",
                "target_units": "percent_change_qoq_saar",
            },
        ],
    }


def _metrics() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "target_series_id": ["PAYEMS", "CPILFESL", "GDPC1"],
            "target_name": [
                "payems_change_mom_thousands",
                "core_cpi_pct_change_mom",
                "real_gdp_pct_change_qoq_saar",
            ],
            "target_frequency": ["monthly", "monthly", "quarterly"],
            "target_units": [
                "thousands_of_persons_change_mom",
                "percent_change_mom_nonannualized",
                "percent_change_qoq_saar",
            ],
            "model_id": ["ar1", "elastic_net", "historical_mean"],
            "data_mode": ["vintage_aware"] * 3,
            "feature_mode": ["as_of"] * 3,
            "target_mode": ["first_release"] * 3,
            "n_forecasts": [24, 24, 8],
            "rmse": [1.2, 0.3, 2.1],
            "mae": [1.0, 0.2, 1.8],
            "bias": [0.1, -0.1, 0.2],
        }
    )


def _dm() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "target_series_id": ["PAYEMS", "GDPC1"],
            "baseline_model": ["historical_mean", "historical_mean"],
            "comparison_model": ["elastic_net", "elastic_net"],
            "statistic": [0.4, None],
            "p_value": [0.7, None],
            "n_obs": [24, 8],
            "valid": [True, False],
            "status": ["ok", "insufficient_observations"],
            "reason": [None, "fewer than 12 loss differences"],
        }
    )


def _revisions() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "target_series_id": ["PAYEMS", "CPILFESL", "GDPC1"],
            "target_name": [
                "payems_change_mom_thousands",
                "core_cpi_pct_change_mom",
                "real_gdp_pct_change_qoq_saar",
            ],
            "model_id": ["ar1", "elastic_net", "historical_mean"],
            "n_forecasts": [24, 24, 8],
            "mean_target_revision": [0.2, 0.01, -0.1],
            "mean_abs_target_revision": [0.4, 0.02, 0.3],
        }
    )


def test_report_is_structured_synthetic_and_never_declares_a_winner() -> None:
    report = render_multitarget_report(_manifest(), _metrics(), _dm(), _revisions())

    assert "SYNTHETIC FIXTURE DEMONSTRATION — NO EMPIRICAL FINDINGS" in report
    assert "payems_change_mom_thousands" in report
    assert "core_cpi_pct_change_mom" in report
    assert "real_gdp_pct_change_qoq_saar" in report
    assert "current_level - prior_level" in report
    assert "100 * (current_level / prior_level - 1)" in report
    assert "100 * ((current_level / prior_level) ** 4 - 1)" in report
    assert "insufficient_observations" in report
    assert "Quarterly GDP has a small evaluation sample" in report
    assert "do not establish model superiority" in report
    assert "Revision rows" in report
    assert "is the best model" not in report
    assert "outperforms all" not in report


def test_dm_summary_handles_empty_and_unvalidated_frames_honestly() -> None:
    assert "no model-ranking inference" in dm_diagnostic_summary(pl.DataFrame())
    missing_validity = pl.DataFrame(
        {"target_series_id": ["PAYEMS"], "statistic": [1.0]}
    )
    assert "required validity flag" in dm_diagnostic_summary(missing_validity)
    assert "not interpreted" in dm_diagnostic_summary(missing_validity)


def test_report_handles_empty_analytical_frames_without_inventing_results() -> None:
    report = render_multitarget_report(
        _manifest(),
        pl.DataFrame(),
        pl.DataFrame(),
        pl.DataFrame(),
    )

    assert report.count("No rows were produced.") >= 3
    assert "no model-ranking inference is available" in report
    assert "supports no empirical finding" in report


def test_writer_and_contract_loader_round_trip(tmp_path: Path) -> None:
    artifact_root = tmp_path / "multitarget"
    artifact_root.mkdir()
    (artifact_root / "run_manifest.json").write_text(json.dumps(_manifest()))
    _metrics().write_parquet(artifact_root / "metrics.parquet")
    _dm().write_parquet(artifact_root / "dm_comparisons.parquet")
    _revisions().write_parquet(artifact_root / "target_revision_summary.parquet")

    manifest, metrics, dm, revisions = load_multitarget_artifacts(artifact_root)
    destination = tmp_path / "reports" / "multitarget.md"
    result = write_multitarget_report(manifest, metrics, dm, revisions, destination)

    assert result == destination
    assert destination.exists()
    assert "Synthetic Multi-Target" in destination.read_text()


def test_loader_rejects_incomplete_manifest(tmp_path: Path) -> None:
    artifact_root = tmp_path / "multitarget"
    artifact_root.mkdir()
    manifest = _manifest()
    manifest["artifact_stage"] = "building"
    (artifact_root / "run_manifest.json").write_text(json.dumps(manifest))

    with pytest.raises(ValueError, match="not marked backtest complete"):
        load_multitarget_artifacts(artifact_root)


def test_target_policy_brief_contains_required_interpretation_guardrails(
    tmp_path: Path,
) -> None:
    news = {
        "target_series_id": "CPILFESL",
        "target_name": "core_cpi_pct_change_mom",
        "target_formula": "100 * (current_level / prior_level - 1)",
        "target_frequency": "monthly",
        "target_units": "percent_change_mom_nonannualized",
        "horizon": 0,
        "data_mode": "vintage_aware",
        "model_id": "elastic_net",
        "release_name": "Synthetic PAYEMS initial release",
        "release_ts": "2025-01-03T13:30:00+00:00",
        "release_observation_date": "2024-12-01",
        "changed_features": ["payems_change"],
        "previous_nowcast": 0.2,
        "updated_nowcast": 0.25,
        "forecast_revision": 0.05,
        "assessment": "The synthetic nowcast increased.",
        "attribution_label": "exact",
        "contributions": [
            {
                "feature": "payems_change",
                "contribution": 0.05,
                "previous_value": 100.0,
                "updated_value": 110.0,
            }
        ],
        "interval": {
            "coverage": 0.8,
            "lower": 0.1,
            "upper": 0.4,
            "residual_count": 24,
        },
        "historical_comparison": {
            "percentile": 60.0,
            "n_comparisons": 23,
            "median_absolute_movement": 0.03,
        },
    }

    rendered = render_multitarget_policy_brief(news, _manifest())
    assert "SYNTHETIC FIXTURE DEMONSTRATION — NO EMPIRICAL FINDINGS" in rendered
    assert "What changed relative to the prior information set" in rendered
    assert "Forecast uncertainty" in rendered
    assert "Historical comparison" in rendered
    assert "What evidence would change the conclusion" in rendered
    assert "No monetary-policy, investment" in rendered

    paths = write_multitarget_policy_briefs([news], _manifest(), tmp_path)
    assert paths == [tmp_path / "CPILFESL_policy_brief.md"]
    assert paths[0].read_text() == rendered
