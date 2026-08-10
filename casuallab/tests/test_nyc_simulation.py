from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from casuallab import nyc_simulation as nyc_simulation_module
from casuallab.config import SimulationConfig
from casuallab.data import sha256_file
from casuallab.nyc_simulation import (
    ANCHOR_EVIDENCE_LABEL,
    CAUSAL_ASSUMPTION_FIELDS,
    NYCSimulationAnchorSettings,
    build_nyc_simulation_anchor,
)
from casuallab.simulator import simulate_market


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _entry(path: Path, root: Path) -> dict[str, object]:
    return {
        "path": str(path.relative_to(root)),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def _declared_digest(entries: list[dict[str, object]]) -> str:
    canonical = json.dumps(
        [
            {
                "path": str(entry["path"]),
                "bytes": int(entry["bytes"]),
                "sha256": str(entry["sha256"]),
            }
            for entry in entries
        ],
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def write_nyc_calibration_test_bundle(
    tmp_path: Path, *, calibration_schema: str = "1.0.0"
) -> dict[str, Path]:
    source_file = tmp_path / "data" / "completed_trip_input.txt"
    source_file.parent.mkdir(parents=True)
    source_file.write_text("immutable-source\n", encoding="utf-8")
    source_entries = [_entry(source_file, tmp_path)]
    source_manifest = tmp_path / "data" / "manifest.json"
    _write_json(
        source_manifest,
        {
            "schema_version": "1.0.0",
            "config": {
                "source": "nyc_hvfhv",
                "mode": "full",
                "project_root": ".",
                "manifest_path": "data/manifest.json",
                "panel_frequency": "1h",
                "complete_panel_grid": True,
                "nyc_year": 2024,
                "nyc_months": [1],
            },
            "metadata": {
                "evidence_label": "descriptive_real_data",
                "causal_claim": False,
                "full_month_processing": {
                    "complete_calendar_coverage": True,
                    "configured_date_hours": 744,
                    "observed_date_hours": 744,
                    "row_conservation": {"passes": True},
                },
            },
            "files": source_entries,
        },
    )
    lineage = {
        "path": "data/manifest.json",
        "sha256": sha256_file(source_manifest),
        "entries": len(source_entries),
        "declared_file_set_sha256": _declared_digest(source_entries),
        "hashes_recomputed": True,
        "queried_files_listed": True,
        "scope_is_full_nyc_descriptive": True,
        "mismatches": [],
        "all_valid": True,
    }

    output = tmp_path / "artifacts" / "calibration_network"
    output.mkdir(parents=True)
    temporal = output / "temporal_autocorrelation.csv"
    temporal.write_text(
        (
            "lag_hours,exact_lag_support_pairs,support_share,"
            "pooled_trip_count_correlation,within_zone_centered_correlation,"
            "evidence_label,interpretation_warning\n"
            "1,1486,1.0,0.8,0.7,descriptive_real_data,"
            "Observed exact-lag association; not a causal persistence parameter.\n"
            "24,1440,1.0,0.6,0.5,descriptive_real_data,"
            "Observed exact-lag association; not a causal persistence parameter.\n"
        ),
        encoding="utf-8",
    )
    calibration = output / "calibration.json"
    checks = {
        "graph_conserves_od": True,
        "od_conserves_clean": True,
        "od_counts_positive": True,
        "od_keys_unique": True,
        "raw_equals_clean": True,
        "raw_rows_declared": True,
        "source_manifest_valid": True,
        "variance_trip_sum_conserves": True,
        "zone_conserves_clean": True,
        "zone_keys_unique": True,
    }
    _write_json(
        calibration,
        {
            "schema_version": calibration_schema,
            "bundle_valid": True,
            "evidence_label": "descriptive_real_data",
            "causal_claim": False,
            "scope": {
                "source": "nyc_hvfhv",
                "population_claim": False,
                "unit": "published_completed_trip_record_and_pickup_zone_hour",
                "pickup_min": "2024-01-01T00:00:00",
                "pickup_max": "2024-01-31T23:59:59",
            },
            "checks": checks,
            "conservation": {
                "raw_rows_declared": 7440,
                "clean_rows": 7440,
                "zone_trip_sum": 7440,
                "od_trip_sum": 7440,
                "zones": 2,
                "periods": 744,
                "zone_rows": 1488,
            },
            "trip_level_descriptive_moments": {
                "trip_rows": 7440,
                "fare": {
                    "mean": 20.0,
                    "evidence_label": "descriptive_real_data",
                },
                "request_to_pickup_wait_minutes": {
                    "available": True,
                    "mean": 4.5,
                    "p50": 4.0,
                    "evidence_label": "descriptive_real_data",
                },
            },
            "zone_hour_variance_decomposition": {
                "evidence_label": "descriptive_real_data",
                "zones": 2,
                "periods": 744,
                "panel_cells": 1488,
                "occupied_cells": 1400,
                "total_completed_trips": 7440,
                "mean_completed_trips_per_zone_hour": 5.0,
                "between_zone_component": 4.0,
                "between_hour_of_day_component": 1.0,
                "total_cell_variance": 10.0,
                "icc_like_between_zone_share": 0.4,
                "between_hour_of_day_share": 0.1,
            },
            "temporal_associations": {
                "evidence_label": "descriptive_real_data",
                "file": "temporal_autocorrelation.csv",
                "lags_hours": [1, 24],
            },
            "provenance": {"source_data_manifest": lineage},
        },
    )
    bundle_manifest = output / "manifest.json"
    _write_json(
        bundle_manifest,
        {
            "schema_version": "1.0.0",
            "evidence_label": "descriptive_real_data",
            "causal_claim": False,
            "portable_paths": True,
            "source_data_manifest": lineage,
            "files": [
                _entry(calibration, output),
                _entry(temporal, output),
            ],
        },
    )
    return {
        "root": tmp_path,
        "source_file": source_file,
        "source_manifest": source_manifest,
        "calibration": calibration,
        "bundle_manifest": bundle_manifest,
    }


def test_derives_only_observable_initializers_and_preserves_assumptions(
    tmp_path: Path,
) -> None:
    paths = write_nyc_calibration_test_bundle(tmp_path)
    template = SimulationConfig(
        base_demand=80.0,
        base_supply=40.0,
        direct_demand_effect=0.31,
        direct_supply_effect=0.27,
        spillover_strength=0.19,
        persistence=0.41,
        rider_substitution=0.17,
        driver_mobility=0.23,
        rider_value=35.0,
        operating_cost_per_trip=11.0,
        wait_disutility_per_minute=0.8,
    )
    anchor = build_nyc_simulation_anchor(
        paths["calibration"],
        project_root=tmp_path,
        settings=NYCSimulationAnchorSettings(
            target_n_zones=2,
            target_n_periods=168,
            seed=99,
        ),
        assumption_template=template,
    )

    config = anchor["simulation_config"]
    assert anchor["evidence_label"] == ANCHOR_EVIDENCE_LABEL
    assert anchor["causal_claim"] is False
    assert anchor["integrity"]["all_valid"] is True
    assert anchor["integrity"]["bundle_files_verified"] == 2
    assert anchor["integrity"]["source_files_verified"] == 1
    assert anchor["target_panel"]["observed"]["panel_cells"] == 1488
    assert anchor["target_panel"]["simulation"]["panel_cells"] == 336
    assert anchor["target_panel"]["sample_scaling"]["cell_fraction"] == pytest.approx(
        336 / 1488
    )
    assert anchor["target_panel"]["sample_scaling"]["selection_performed"] is False

    assert config["n_zones"] == 2
    assert config["n_periods"] == 168
    assert config["periods_per_day"] == 24
    assert config["base_demand"] > 5.0
    assert config["base_supply"] / config["base_demand"] == pytest.approx(0.5)
    assert config["base_fare"] == pytest.approx(20.0)
    assert config["base_wait_minutes"] > 0
    assert config["zone_heterogeneity_sd"] >= 0
    assert config["time_pattern_strength"] >= 0
    assert config["seed"] == 99
    assert config["design"]["seed"] == 100
    control_validation = anchor["control_path_scale_validation"]
    assert control_validation[
        "target_mean_published_completed_trips_per_zone_hour"
    ] == pytest.approx(5.0)
    assert control_validation[
        "achieved_simulated_control_completed_trips"
    ] == pytest.approx(5.0)
    assert control_validation["calibration_error"] == pytest.approx(0.0, abs=1e-10)
    assert control_validation[
        "achieved_simulated_control_mean_wait_minutes"
    ] == pytest.approx(4.5)
    assert control_validation["wait_calibration_error"] == pytest.approx(0.0, abs=1e-10)
    assert control_validation["achieved_between_zone_variance_share"] == pytest.approx(
        0.4, abs=0.01
    )
    assert control_validation[
        "achieved_between_hour_of_day_variance_share"
    ] == pytest.approx(0.1, abs=0.01)
    assert control_validation["broad_moment_match_passed"] is True
    assert control_validation["causal_claim"] is False

    for field in CAUSAL_ASSUMPTION_FIELDS:
        assert config[field] == template.to_dict()[field]
        assert anchor["field_provenance"]["explicit_assumptions"][field][
            "evidence_label"
        ] == "explicit_assumption"
    assert anchor["field_provenance"]["partition_complete"] is True
    assert anchor["field_provenance"]["explicit_assumptions"]["seed"]["source"] == (
        "NYCSimulationAnchorSettings.seed"
    )
    assert "NYCSimulationAnchorSettings.seed" in anchor["field_provenance"][
        "explicit_assumptions"
    ]["design"]["source"]
    assert anchor["observable_anchor"]["temporal_associations"][0][
        "assigned_to_simulator_persistence"
    ] is False
    json.dumps(anchor, allow_nan=False)


def test_rejects_calibration_tampering_before_derivation(tmp_path: Path) -> None:
    paths = write_nyc_calibration_test_bundle(tmp_path)
    original = paths["calibration"].read_text(encoding="utf-8")
    tampered = original.replace('"mean": 20.0', '"mean": 21.0', 1)
    assert len(tampered.encode()) == len(original.encode())
    paths["calibration"].write_text(tampered, encoding="utf-8")

    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        build_nyc_simulation_anchor(paths["calibration"], project_root=tmp_path)


def test_rejects_unsupported_schema_even_when_manifest_hash_matches(
    tmp_path: Path,
) -> None:
    paths = write_nyc_calibration_test_bundle(
        tmp_path, calibration_schema="2.0.0"
    )

    with pytest.raises(ValueError, match="unsupported schema_version"):
        build_nyc_simulation_anchor(paths["calibration"], project_root=tmp_path)


def test_rejects_source_file_tampering_through_full_hash_chain(tmp_path: Path) -> None:
    paths = write_nyc_calibration_test_bundle(tmp_path)
    tampered = bytearray(paths["source_file"].read_bytes())
    tampered[0] ^= 1
    paths["source_file"].write_bytes(tampered)

    with pytest.raises(ValueError, match="source-data manifest SHA-256 mismatch"):
        build_nyc_simulation_anchor(paths["calibration"], project_root=tmp_path)


def test_control_path_broad_moment_gate_fails_closed(tmp_path: Path) -> None:
    paths = write_nyc_calibration_test_bundle(tmp_path)

    with pytest.raises(ValueError, match="control-path broad-moment gate failed"):
        build_nyc_simulation_anchor(
            paths["calibration"],
            project_root=tmp_path,
            settings=NYCSimulationAnchorSettings(
                target_n_zones=1,
                target_n_periods=168,
            ),
        )


def test_fast_control_specialization_matches_public_simulator_control() -> None:
    config = SimulationConfig(n_zones=3, n_periods=48, seed=3811)
    actual = nyc_simulation_module._simulated_control_moments(config)
    control = simulate_market(config).counterfactuals["control"]
    trips = control["trips"].astype(float)
    grand_mean = float(trips.mean())
    total_variance = float(trips.var(ddof=0))

    def share(group: str) -> float:
        grouped = control.groupby(group, observed=True)["trips"].agg(["size", "mean"])
        component = float(
            (grouped["size"] * (grouped["mean"] - grand_mean) ** 2).sum()
            / len(control)
        )
        return component / total_variance

    assert actual == pytest.approx(
        {
            "mean_completed_trips": grand_mean,
            "mean_wait_minutes": float(control["wait_minutes"].mean()),
            "between_zone_share": share("zone_id"),
            "between_hour_of_day_share": share("hour"),
        },
        rel=1e-12,
        abs=1e-12,
    )


def test_causal_fields_never_appear_as_empirically_derived(tmp_path: Path) -> None:
    paths = write_nyc_calibration_test_bundle(tmp_path)
    anchor = build_nyc_simulation_anchor(paths["calibration"], project_root=tmp_path)

    derived = anchor["field_provenance"]["derived_initializers"]
    assumptions = anchor["field_provenance"]["explicit_assumptions"]
    assert set(CAUSAL_ASSUMPTION_FIELDS).isdisjoint(derived)
    assert set(CAUSAL_ASSUMPTION_FIELDS).issubset(assumptions)
    assert (
        anchor["causal_parameter_assumptions"]["status"]
        == "explicit_assumptions_not_estimated_from_nyc_trip_records"
    )
    assert anchor["causal_parameter_assumptions"][
        "calibration_embedded_template_assumptions_used"
    ] is False
    assert anchor["simulation_config"]["persistence"] == SimulationConfig().persistence
    assert "do not identify treatment response" in anchor["warnings"][0]
