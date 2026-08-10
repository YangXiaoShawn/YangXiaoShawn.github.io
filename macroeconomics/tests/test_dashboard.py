from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import polars as pl

from macro_nowcast.dashboard import (
    MULTITARGET_COMPLETE_STAGE,
    OFFICIAL_PILOT_COMPLETE_STAGE,
    available_dashboard_contexts,
    available_target_ids,
    detect_dashboard_artifacts,
    dm_status_message,
    filter_frame_for_target,
    news_update_for_target,
    target_caption,
)


def _write_manifest(path: Path, **values: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(values))


def test_dashboard_selects_only_a_completed_multitarget_artifact_root(tmp_path: Path) -> None:
    generated = tmp_path / "generated"
    _write_manifest(generated / "run_manifest.json", artifact_stage="legacy_complete")
    multi = generated / "multitarget"
    _write_manifest(multi / "run_manifest.json", artifact_stage=MULTITARGET_COMPLETE_STAGE)

    partial = detect_dashboard_artifacts(generated)
    assert partial.root == generated.resolve()
    assert partial.is_multitarget is False

    (multi / "predictions.parquet").touch()
    (multi / "metrics.parquet").touch()
    complete = detect_dashboard_artifacts(generated)
    assert complete.root == multi.resolve()
    assert complete.is_multitarget is True
    assert complete.manifest["artifact_stage"] == MULTITARGET_COMPLETE_STAGE


def test_dashboard_rejects_wrong_stage_even_when_combined_files_exist(tmp_path: Path) -> None:
    generated = tmp_path / "generated"
    multi = generated / "multitarget"
    _write_manifest(multi / "run_manifest.json", artifact_stage="building")
    (multi / "predictions.parquet").touch()
    (multi / "metrics.parquet").touch()

    context = detect_dashboard_artifacts(generated)

    assert context.is_multitarget is False
    assert context.root == generated.resolve()


def test_dashboard_exposes_official_and_synthetic_as_separate_evidence_tiers(
    tmp_path: Path,
) -> None:
    generated = tmp_path / "generated"
    official = generated / "official_pilot"
    _write_manifest(
        official / "run_manifest.json",
        artifact_stage=OFFICIAL_PILOT_COMPLETE_STAGE,
        data_provenance="official_agency_archive",
    )
    for name in (
        "predictions.parquet",
        "metrics.parquet",
        "metrics_by_regime_horizon.parquet",
        "final_evaluation_metrics.parquet",
        "hyperparameter_tuning.parquet",
        "feature_leakage_audit.parquet",
        "model_stability.parquet",
        "target_revision_summary.parquet",
        "news_updates.json",
    ):
        (official / name).touch()
    multi = generated / "multitarget"
    _write_manifest(multi / "run_manifest.json", artifact_stage=MULTITARGET_COMPLETE_STAGE)
    (multi / "predictions.parquet").touch()
    (multi / "metrics.parquet").touch()

    contexts = available_dashboard_contexts(generated)

    assert [context.evidence_tier for context in contexts] == [
        "official_archive_pilot",
        "synthetic_multitarget",
    ]
    assert contexts[0].is_official is True
    assert contexts[1].is_official is False


def test_target_discovery_filtering_and_caption_are_pure() -> None:
    manifest = {
        "fixture_label": "synthetic_fixture",
        "target_definitions": [
            {
                "target_series_id": "GDPC1",
                "target_name": "real_gdp_pct_change_qoq_saar",
                "target_frequency": "quarterly",
                "target_units": "percent_change_qoq_saar",
                "target_formula": "100 * ((current_level / prior_level) ** 4 - 1)",
                "evaluation_start": "2021-01-01",
                "evaluation_end": "2024-10-01",
            }
        ],
    }
    combined = pl.DataFrame(
        {
            "target_series_id": ["PAYEMS", "CPILFESL", "GDPC1", "GDPC1"],
            "target_period": [
                date(2024, 1, 1),
                date(2024, 1, 1),
                date(2024, 1, 1),
                date(2024, 10, 1),
            ],
            "value": [1.0, 2.0, 3.0, 4.0],
        }
    )

    assert available_target_ids(manifest, [combined]) == ["PAYEMS", "CPILFESL", "GDPC1"]
    selected = filter_frame_for_target(combined, "GDPC1")
    assert selected is not None
    assert selected.height == 2
    caption = target_caption(manifest, "GDPC1", selected)
    assert "real_gdp_pct_change_qoq_saar" in caption
    assert "formula: 100 * ((current_level / prior_level) ** 4 - 1)" in caption
    assert "frequency: quarterly" in caption
    assert "units: percent_change_qoq_saar" in caption
    assert "sample: 2024-01-01 to 2024-10-01" in caption

    unkeyed = pl.DataFrame({"series_id": ["GDPC1", "PAYEMS"]})
    assert filter_frame_for_target(unkeyed, "GDPC1") is unkeyed


def test_dm_status_reports_small_sample_gdp_without_inference() -> None:
    dm = pl.DataFrame(
        {
            "target_series_id": ["GDPC1", "PAYEMS"],
            "valid": [False, True],
            "status": ["insufficient_observations", "ok"],
            "reason": ["fewer than 12 loss differences", None],
        }
    )

    gdp_message = dm_status_message(dm, "GDPC1")
    payroll_message = dm_status_message(dm, "PAYEMS")

    assert "No valid DM inference" in gdp_message
    assert "insufficient_observations" in gdp_message
    assert "quarterly GDP" in gdp_message
    assert "do not establish model superiority" in payroll_message

    official = pl.DataFrame(
        {
            "target_series_id": ["PAYEMS"],
            "valid": [True],
            "reason": [None],
            "data_provenance": ["official_agency_archive"],
        }
    )
    assert "scoped official-pilot diagnostics" in dm_status_message(official, "PAYEMS")


def test_target_discovery_can_expose_all_defaults_before_rows_exist() -> None:
    assert available_target_ids({}, include_multitarget_defaults=True) == [
        "PAYEMS",
        "CPILFESL",
        "GDPC1",
    ]


def test_news_update_selection_supports_multitarget_and_legacy_payloads() -> None:
    payload = {
        "updates": [
            {"target_series_id": "PAYEMS", "forecast_revision": 1.0},
            {"target_series_id": "GDPC1", "forecast_revision": 2.0},
        ]
    }

    assert news_update_for_target(payload, "gdpc1")["forecast_revision"] == 2.0
    assert news_update_for_target(payload, "CPILFESL") == {}
    legacy = {"release_series_id": "UMCSENT", "forecast_revision": 3.0}
    assert news_update_for_target(legacy, "PAYEMS") == legacy
