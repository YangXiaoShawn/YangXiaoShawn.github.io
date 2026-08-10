import hashlib
import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from casuallab.benchmark import BenchmarkConfig
from casuallab.config import DesignConfig, DesignName, SimulationConfig, TreatmentVersion
from casuallab.dashboard import (
    DashboardControls,
    _recommended_design_caveat,
    _source_tree_sha256,
    artifact_decision,
    build_simulation_config,
    evidence_layer_rows,
    load_benchmark_artifact,
    load_calibration_template,
    load_evidence_layers,
    match_benchmark_artifact,
    run_scenario_benchmark,
)
from casuallab.marketplace_benchmark import SensitivityScenario, run_marketplace_benchmark


def _small_controls(**overrides: object) -> DashboardControls:
    values: dict[str, object] = {
        "experiment_duration": 12,
        "n_clusters": 4,
        "treatment_duration": 3,
        "washout_periods": 1,
        "budget": 800.0,
        "replications": 2,
        "seed": 71,
    }
    values.update(overrides)
    return DashboardControls(**values)


def _write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _hashed_entry(path: Path, rendered_path: str, **extra: object) -> dict[str, object]:
    return {
        "path": rendered_path,
        "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        **extra,
    }


def _evidence_layer_fixture(root: Path) -> dict[str, Path]:
    source = root / "src/example.py"
    source.parent.mkdir(parents=True)
    source.write_text("VALUE = 1\n", encoding="utf-8")
    manifests: dict[str, Path] = {}

    for key, directory_name, artifact_type, evidence in (
        (
            "nyc_informed",
            "nyc_informed",
            "nyc_informed_marketplace_benchmark",
            "semi_synthetic_nyc_informed_known_truth_monte_carlo",
        ),
        (
            "nyc_graph",
            "nyc_graph",
            "nyc_graph_interference_benchmark",
            "semi_synthetic_known_truth_on_descriptive_nyc_graph",
        ),
    ):
        directory = root / f"artifacts/benchmarks/{directory_name}"
        directory.mkdir(parents=True)
        input_directory = root / f"artifacts/upstream/{directory_name}"
        input_directory.mkdir(parents=True)
        if key == "nyc_informed":
            input_specs = (
                ("anchor", "anchor.json", "semi_synthetic_descriptive_anchor"),
                (
                    "anchor_manifest",
                    "anchor_manifest.json",
                    "semi_synthetic_descriptive_anchor",
                ),
            )
        else:
            input_specs = (
                ("calibration_manifest", "manifest.json", "descriptive_real_data"),
                ("exposure_mapping", "exposure_mapping_edges.csv", "descriptive_real_data"),
            )
        input_entries = []
        for role, filename, input_evidence in input_specs:
            input_path = input_directory / filename
            input_path.write_text(f"{role}\n", encoding="utf-8")
            input_entries.append(
                _hashed_entry(
                    input_path,
                    str(input_path.relative_to(root)),
                    role=role,
                    evidence_types=[input_evidence],
                )
            )
        table_paths: dict[str, Path] = {}
        for role in ("records", "summary", "fit_ledger", "failures"):
            table_evidence = (
                "semi_synthetic_nyc_graph_known_truth_monte_carlo"
                if key == "nyc_graph" and role == "summary"
                else evidence
            )
            table = pd.DataFrame({"evidence_type": [table_evidence], "value": [1.0]})
            table_paths[role] = directory / f"{role}.csv"
            table.to_csv(table_paths[role], index=False)
        metadata: dict[str, object] = {
            "evidence_type": evidence,
            "causal_claim_from_nyc_data": False,
            "artifact_bundle": {
                "schema_version": "1.0.0",
                "artifact_type": artifact_type,
                "evidence_type": evidence,
                "inputs": input_entries,
            },
        }
        if key == "nyc_informed":
            metadata.update(
                {"nyc_empirical_causal_effect": False, "simulator_known_truth": True}
            )
        else:
            metadata["input_graph_evidence_label"] = "descriptive_real_data"
        metadata_path = _write_json(directory / "metadata.json", metadata)
        entries = []
        for role, path in table_paths.items():
            entry_evidence = (
                "semi_synthetic_nyc_graph_known_truth_monte_carlo"
                if key == "nyc_graph" and role == "summary"
                else evidence
            )
            entries.append(
                _hashed_entry(
                    path,
                    path.name,
                    role=role,
                    evidence_types=[entry_evidence],
                    rows=1,
                )
            )
        entries.append(
            _hashed_entry(
                metadata_path,
                metadata_path.name,
                role="metadata",
                evidence_types=[evidence],
            )
        )
        manifest: dict[str, object] = {
            "schema_version": "1.0.0",
            "artifact_type": artifact_type,
            "evidence_type": evidence,
            "causal_claim": False,
            "causal_claim_from_nyc_data": False,
            "portable_paths": True,
            "metadata_file": "metadata.json",
            "files": entries,
            "inputs": input_entries,
        }
        if key == "nyc_informed":
            manifest["simulator_known_truth"] = True
        else:
            manifest["input_graph_evidence_label"] = "descriptive_real_data"
        manifests[key] = _write_json(directory / "manifest.json", manifest)

    equilibrium_dir = root / "artifacts/benchmarks/equilibrium"
    equilibrium_dir.mkdir(parents=True)
    equilibrium_summary = _write_json(
        equilibrium_dir / "summary.json",
        {
            "schema_version": 1,
            "evidence_type": "theoretical_simulation_known_ground_truth",
            "common_random_numbers": True,
            "is_nyc_structural_estimate": False,
            "equations": {
                "rider_demand": "declared",
                "driver_supply": "declared",
                "wait_fixed_point": "declared",
            },
        },
    )
    equilibrium_zone = equilibrium_dir / "zone_effects.csv"
    equilibrium_ledger = equilibrium_dir / "ledger.csv"
    pd.DataFrame(
        {"zone_id": [0], "evidence_type": ["theoretical_simulation_known_ground_truth"]}
    ).to_csv(equilibrium_zone, index=False)
    pd.DataFrame({"scenario": ["control"], "total_welfare": [1.0]}).to_csv(
        equilibrium_ledger, index=False
    )
    equilibrium_files = [equilibrium_summary, equilibrium_zone, equilibrium_ledger]
    equilibrium_entries = [
        _hashed_entry(path, str(path.relative_to(root))) for path in equilibrium_files
    ]
    equilibrium_checks = {
        "control_equilibrium_converged": True,
        "treatment_equilibrium_converged": True,
        "residuals_within_tolerance": True,
        "sufficient_uniqueness_condition_satisfied": True,
        "common_random_numbers_verified": True,
        "budget_feasible": True,
        "welfare_accounting_balanced": True,
        "ground_truth_recomputed": True,
        "hashes_recomputed": True,
    }
    manifests["equilibrium"] = _write_json(
        equilibrium_dir / "manifest.json",
        {
            "schema_version": 1,
            "bundle_type": "two_sided_fixed_point_equilibrium_benchmark",
            "evidence_type": "theoretical_simulation_known_ground_truth",
            "causal_scope": "within_declared_equilibrium_model_only",
            "empirical_calibration_status": "not_an_empirical_or_nyc_structural_estimate",
            "is_nyc_structural_estimate": False,
            "portable_paths": True,
            "files": equilibrium_entries,
            "declared_file_set_sha256": hashlib.sha256(
                json.dumps(
                    equilibrium_entries, sort_keys=True, separators=(",", ":")
                ).encode()
            ).hexdigest(),
            "checks": equilibrium_checks,
        },
    )

    weather_dir = root / "artifacts/nyc_full/weather"
    weather_dir.mkdir(parents=True)
    weather_summary = _write_json(
        weather_dir / "weather_associations.json",
        {
            "schema_version": "1.0.0",
            "evidence_label": "descriptive_observed_external_weather",
            "causal_claim": False,
            "scope": {
                "city": "New York City",
                "pickup_month": "2024-01",
                "population_claim": False,
            },
        },
    )
    weather_daily = weather_dir / "weather_daily.csv"
    weather_hourly = weather_dir / "weather_hourly_contrasts.csv"
    pd.DataFrame({"date": ["2024-01-01"]}).to_csv(weather_daily, index=False)
    pd.DataFrame({"hour": [0]}).to_csv(weather_hourly, index=False)
    weather_files = [weather_summary, weather_daily, weather_hourly]
    weather_entries = [
        _hashed_entry(path, str(path.relative_to(root))) for path in weather_files
    ]
    manifests["weather"] = _write_json(
        weather_dir / "manifest.json",
        {
            "schema_version": "1.0.0",
            "evidence_label": "descriptive_observed_external_weather",
            "causal_claim": False,
            "portable_paths": True,
            "files": weather_entries,
            "declared_file_set_sha256": hashlib.sha256(
                json.dumps(
                    weather_entries, sort_keys=True, separators=(",", ":")
                ).encode()
            ).hexdigest(),
            "checks": {
                "noaa_raw_hash_matches": True,
                "calendar_complete": True,
                "nyc_source_manifest_valid": True,
                "trip_conservation": True,
            },
        },
    )

    panel_path = root / "data/nyc_full/panel/zone_time/part.parquet"
    panel_path.parent.mkdir(parents=True)
    panel_path.write_bytes(b"verified-panel")
    source_manifest = _write_json(
        root / "data/nyc_full/manifest.json",
        {
            "config": {"source": "nyc_hvfhv", "mode": "full"},
            "metadata": {
                "evidence_label": "descriptive_real_data",
                "causal_claim": False,
                "full_month_processing": {
                    "row_conservation": {"zone_time_trip_sum": 1_000}
                },
            },
            "files": [
                _hashed_entry(panel_path, str(panel_path.relative_to(root)))
            ],
        },
    )

    events_dir = root / "artifacts/nyc_full/events"
    events_dir.mkdir(parents=True)
    event_evidence = "descriptive_observed_external_calendar_events"
    event_summary = _write_json(
        events_dir / "event_associations.json",
        {
            "schema_version": "1.0.0",
            "evidence_label": event_evidence,
            "causal_claim": False,
            "scope": {
                "city": "New York City",
                "event_signal_spatial_granularity": "citywide",
                "event_signal_temporal_granularity": "service_date",
                "population_claim": False,
            },
            "coverage": {
                "source_permit_rows": 10,
                "source_unique_event_ids": 8,
                "invalid_interval_rows_retained_but_not_expanded": 1,
                "zero_duration_interval_rows_retained_but_not_expanded": 2,
                "all_nonpositive_interval_rows_retained_but_not_expanded": 3,
                "valid_interval_rows": 7,
                "valid_unique_event_ids": 7,
                "expanded_unique_event_days": 8,
                "weekend_days": 2,
                "above_median_permit_intensity_weekend_days": 2,
                "at_or_below_median_permit_intensity_weekend_days": 0,
            },
            "associations": {
                "above_vs_at_or_below_median_permit_intensity_weekdays_only": {
                    "exposed_days": 2,
                    "comparison_days": 3,
                }
            },
            "identification_checks": {
                "causal_effect_identified": False,
                "major_event_contrast_separately_identifies_event_effect": False,
                "all_weekend_days_are_above_median_permit_intensity": True,
            },
            "conservation": {
                "passes": True,
                "daily_trip_sum": 1_000,
                "zone_time_trip_sum": 1_000,
            },
        },
    )
    event_files: list[dict[str, object]] = []
    for role, filename in (
        ("normalized_daily_calendar", "calendar.csv"),
        ("normalized_permit_records", "events.csv"),
        ("daily_permit_type_counts", "event_types.csv"),
        ("joined_daily_trip_panel", "daily.csv"),
        ("descriptive_hourly_profiles", "hourly.csv"),
    ):
        path = events_dir / filename
        pd.DataFrame(
            {"evidence_label": [event_evidence], "causal_claim": [False]}
        ).to_csv(path, index=False)
        event_files.append(
            _hashed_entry(path, str(path.relative_to(root)), role=role)
        )
    event_files.append(
        _hashed_entry(
            event_summary,
            str(event_summary.relative_to(root)),
            role="descriptive_summary",
        )
    )
    event_inputs: list[dict[str, object]] = []
    for role, path in (
        (
            "official_holiday_snapshot",
            root / "data/nyc_events/raw/holidays.csv",
        ),
        (
            "official_nyc_permitted_events_snapshot",
            root / "data/nyc_events/raw/events.csv",
        ),
        ("nyc_full_data_manifest", source_manifest),
        ("nyc_full_zone_time_panel", panel_path),
    ):
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"{role}\n", encoding="utf-8")
        event_inputs.append(
            _hashed_entry(path, str(path.relative_to(root)), role=role)
        )
    event_checks = {
        "holiday_snapshot_hash_matches": True,
        "event_snapshot_hash_matches": True,
        "calendar_complete": True,
        "holiday_schedule_coverage_complete": True,
        "event_source_rows_verified": True,
        "event_source_unique_ids_verified": True,
        "invalid_source_intervals_retained_and_excluded": True,
        "zero_duration_source_intervals_retained_and_excluded": True,
        "daily_signal_is_citywide_not_zone_exposure": True,
        "hourly_profiles_repeat_daily_signal_not_event_hour_exposure": True,
        "major_event_is_researcher_defined": True,
        "major_event_contrast_separately_identified": False,
        "nyc_source_manifest_valid": True,
        "trip_conservation": True,
        "causal_claim_is_false": True,
        "panel_files_verified": 1,
    }
    manifests["events"] = _write_json(
        events_dir / "manifest.json",
        {
            "schema_version": "1.0.0",
            "evidence_label": event_evidence,
            "causal_claim": False,
            "portable_paths": True,
            "files": event_files,
            "inputs": event_inputs,
            "declared_file_set_sha256": hashlib.sha256(
                json.dumps(event_files, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
            "declared_input_set_sha256": hashlib.sha256(
                json.dumps(event_inputs, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
            "checks": event_checks,
        },
    )

    income_dir = root / "artifacts/nyc_full/income"
    income_dir.mkdir(parents=True)
    income_evidence = "descriptive_observed_external_neighborhood_income"
    income_summary = _write_json(
        income_dir / "income_associations.json",
        {
            "schema_version": "1.0.0",
            "evidence_label": income_evidence,
            "causal_claim": False,
            "scope": {
                "city": "New York City",
                "population_claim": False,
                "individual_income_claim": False,
            },
            "coverage": {
                "published_completed_trips": 1_000,
                "classified_published_completed_trips": 990,
                "unclassified_published_completed_trips": 10,
                "classified_trip_coverage": 0.99,
                "classified_panel_zones": 2,
                "panel_zone_rows": 3,
            },
            "associations": {
                "mean_published_completed_trips_per_zone_hour_high_income_area": 11.0,
                "mean_published_completed_trips_per_zone_hour_low_income_area": 10.0,
                "high_minus_low_mean_published_completed_trips_per_zone_hour": 1.0,
                "high_to_low_mean_published_completed_trips_per_zone_hour_ratio": 1.1,
            },
            "conservation": {
                "passes": True,
                "zone_trip_sum": 1_000,
                "daily_group_trip_sum": 1_000,
                "monthly_group_trip_sum": 1_000,
                "primary_classified_plus_unclassified_trip_sum": 1_000,
                "primary_nonresidential_classified_zones": 0,
                "sensitivity_group_trip_sum": 1_000,
            },
            "spatial_mapping": {"equal_area_crs": "EPSG:6933"},
            "acs_aggregation": {"median_of_medians_used": False},
            "zone_allocation": {
                "all_sixteen_bins_conserved": True,
                "households_conserved": True,
                "minimum_allocated_households": 1.0,
                "minimum_residential_taxi_zone_area_share": 0.5,
                "residential_nta_type_codes": ["0"],
                "classified_zone_rows": 2,
                "high_income_zone_rows": 1,
                "low_income_zone_rows": 1,
            },
            "primary_classification": {
                "primary_result": True,
                "minimum_allocated_households": 1.0,
                "minimum_residential_taxi_zone_area_share": 0.5,
                "residential_nta_type_codes": ["0"],
                "groups": {
                    "high_income_area": {
                        "panel_zones": 1,
                        "published_completed_trips": 550,
                        "mean_published_completed_trips_per_zone_hour": 11.0,
                    },
                    "low_income_area": {
                        "panel_zones": 1,
                        "published_completed_trips": 440,
                        "mean_published_completed_trips_per_zone_hour": 10.0,
                    },
                    "unclassified": {
                        "panel_zones": 1,
                        "published_completed_trips": 10,
                        "mean_published_completed_trips_per_zone_hour": 1.0,
                    },
                },
            },
            "classification_uncertainty": {
                "nta_b19001_margins_of_error_retained": True,
                "zone_grouped_medians_are_point_estimates": True,
                "zone_level_margin_of_error_propagated": False,
                "interpretation": "Threshold proximity is not a confidence interval",
                "threshold_proximity": {
                    "within_1000_usd": {
                        "primary_eligible_panel_zones": 0,
                        "published_completed_trips": 0,
                        "share_of_primary_classified_trips": 0.0,
                    },
                    "within_2500_usd": {
                        "primary_eligible_panel_zones": 1,
                        "published_completed_trips": 100,
                        "share_of_primary_classified_trips": 100 / 990,
                    },
                    "within_5000_usd": {
                        "primary_eligible_panel_zones": 1,
                        "published_completed_trips": 100,
                        "share_of_primary_classified_trips": 100 / 990,
                    },
                    "within_10000_usd": {
                        "primary_eligible_panel_zones": 2,
                        "published_completed_trips": 990,
                        "share_of_primary_classified_trips": 1.0,
                    },
                },
            },
            "sensitivity": {
                "all_zone_area_allocation": {
                    "primary_result": False,
                    "ignored_primary_residential_taxi_zone_area_share_threshold": 0.5,
                    "classified_panel_zones": 2,
                    "classified_published_completed_trips": 990,
                    "classified_trip_coverage": 0.99,
                    "mean_published_completed_trips_per_zone_hour_high_income_area": 11.0,
                    "mean_published_completed_trips_per_zone_hour_low_income_area": 10.0,
                    "high_minus_low_mean_published_completed_trips_per_zone_hour": 1.0,
                    "high_to_low_mean_published_completed_trips_per_zone_hour_ratio": 1.1,
                    "groups": {
                        "high_income_area": {
                            "panel_zones": 1,
                            "published_completed_trips": 550,
                            "mean_published_completed_trips_per_zone_hour": 11.0,
                        },
                        "low_income_area": {
                            "panel_zones": 1,
                            "published_completed_trips": 440,
                            "mean_published_completed_trips_per_zone_hour": 10.0,
                        },
                        "unclassified": {
                            "panel_zones": 1,
                            "published_completed_trips": 10,
                            "mean_published_completed_trips_per_zone_hour": 1.0,
                        },
                    },
                }
            },
        },
    )
    income_files: list[dict[str, object]] = []
    for role, filename in (
        ("taxi_zone_nta_crosswalk", "crosswalk.csv"),
        ("nta_b19001_distribution_summary", "nta.csv"),
        ("taxi_zone_income_and_trip_summary", "zones.csv"),
        ("daily_income_group_description", "daily.csv"),
        ("monthly_income_group_description", "monthly.csv"),
    ):
        path = income_dir / filename
        pd.DataFrame(
            {"evidence_label": [income_evidence], "causal_claim": [False]}
        ).to_csv(path, index=False)
        income_files.append(
            _hashed_entry(
                path,
                str(path.relative_to(root)),
                role=role,
                evidence_label=income_evidence,
                causal_claim=False,
            )
        )
    income_files.append(
        _hashed_entry(
            income_summary,
            str(income_summary.relative_to(root)),
            role="income_association_summary",
            evidence_label=income_evidence,
            causal_claim=False,
        )
    )
    income_input_specs = (
        (
            "official_tlc_taxi_zone_geometry",
            "official_observed_geometry",
            root / "data/nyc_income/raw/taxi.zip",
        ),
        (
            "official_nyc_nta2020_geometry",
            "official_observed_geometry",
            root / "data/nyc_income/raw/nta.geojson",
        ),
        (
            "official_nyc_tract2020_to_nta2020_mapping",
            "official_observed_crosswalk",
            root / "data/nyc_income/raw/tract.csv",
        ),
        (
            "official_census_acs_2022_5yr_b19001_nyc_tract_slice",
            "official_observed_estimates",
            root / "data/nyc_income/raw/acs.dat",
        ),
        (
            "verified_nyc_full_data_manifest",
            "descriptive_real_data_lineage",
            source_manifest,
        ),
        (
            "nyc_full_zone_time_panel",
            "descriptive_real_data_panel",
            panel_path,
        ),
    )
    income_inputs: list[dict[str, object]] = []
    for role, source_type, path in income_input_specs:
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"{role}\n", encoding="utf-8")
        income_inputs.append(
            _hashed_entry(
                path,
                str(path.relative_to(root)),
                role=role,
                source_type=source_type,
            )
        )
    manifests["income"] = _write_json(
        income_dir / "manifest.json",
        {
            "schema_version": "1.0.0",
            "artifact_type": "nyc_income_descriptive_bundle",
            "evidence_label": income_evidence,
            "causal_claim": False,
            "portable_paths": True,
            "files": income_files,
            "inputs": income_inputs,
            "declared_file_set_sha256": hashlib.sha256(
                json.dumps(income_files, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
            "declared_input_set_sha256": hashlib.sha256(
                json.dumps(income_inputs, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
            "checks": {
                "official_source_hashes_match": True,
                "taxi_location_ids_unique_and_complete": True,
                "tract_b19001_totals_equal_sixteen_bins": True,
                "household_distribution_conserved": True,
                "published_trip_conservation": True,
                "ecological_noncausal_contract": True,
                "dominant_nonresidential_primary_unclassified": True,
                "all_zone_classification_is_sensitivity_only": True,
                "median_of_medians_used": False,
                "equal_area_crs": "EPSG:6933",
                "dominant_nonresidential_primary_classified_zones": 0,
                "minimum_allocated_households": 1.0,
                "minimum_residential_taxi_zone_area_share": 0.5,
                "residential_nta_type_codes": ["0"],
                "zone_grouped_medians_are_point_estimates": True,
                "zone_level_margin_of_error_propagated": False,
                "panel_files_verified": 1,
            },
        },
    )

    reproduce = {
        "files": [
            _hashed_entry(path, str(path.relative_to(root)))
            for path in manifests.values()
        ],
        "metadata": {"source_tree_sha256": _source_tree_sha256(root)},
    }
    manifests["top"] = _write_json(
        root / "artifacts/reproduce_manifest.json", reproduce
    )
    manifests["source"] = source
    return manifests


def _refresh_top_manifest_entry(root: Path, path: Path) -> None:
    top = root / "artifacts/reproduce_manifest.json"
    payload = json.loads(top.read_text(encoding="utf-8"))
    rendered = str(path.relative_to(root))
    for entry in payload["files"]:
        if entry["path"] == rendered:
            entry.update(_hashed_entry(path, rendered))
            break
    _write_json(top, payload)


def _rewrite_child_json_role(
    root: Path,
    manifest_path: Path,
    role: str,
    payload: dict[str, object],
) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entry = next(item for item in manifest["files"] if item["role"] == role)
    child_path = root / entry["path"]
    _write_json(child_path, payload)
    entry.update(
        _hashed_entry(
            child_path,
            str(child_path.relative_to(root)),
            role=role,
            **{
                key: entry[key]
                for key in ("evidence_label", "causal_claim")
                if key in entry
            },
        )
    )
    manifest["declared_file_set_sha256"] = hashlib.sha256(
        json.dumps(manifest["files"], sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    _write_json(manifest_path, manifest)
    _refresh_top_manifest_entry(root, manifest_path)


def test_defaults_match_a_precomputed_sensitivity_cell() -> None:
    controls = DashboardControls()
    assert controls.n_clusters == 8
    assert controls.spillover_strength == 0.0
    assert controls.persistence == 0.0
    assert controls.washout_periods == 0
    assert controls.budget == 10_000.0
    assert controls.replications == 5


def test_controls_map_to_typed_config_and_washout_only_switches() -> None:
    controls = _small_controls(
        spillover_strength=0.35,
        persistence=0.4,
        incentive_size=3.25,
        treatment_saturation=0.7,
        treatment_version="driver_incentive",
    )
    static = build_simulation_config(controls, design=DesignName.GEO_CLUSTER, seed=99)
    switching = build_simulation_config(controls, design=DesignName.SWITCHBACK, seed=99)

    assert static.n_periods == 12
    assert static.n_zones == 8
    assert static.design.n_clusters == 4
    assert static.spillover_strength == 0.35
    assert static.persistence == 0.4
    assert static.incentive_per_driver == 3.25
    assert static.effective_budget == 800.0
    assert static.design.treatment_saturation == 0.7
    assert static.treatment_version is TreatmentVersion.DRIVER_INCENTIVE
    assert static.design.washout_periods == 0
    assert switching.design.washout_periods == 1
    assert switching.seed == 99
    assert switching.design.seed == 100


def test_on_demand_scenario_keeps_structural_truth_separate_from_assignment_diagnostic() -> None:
    controls = _small_controls()
    first = run_scenario_benchmark(controls)
    second = run_scenario_benchmark(controls)

    pd.testing.assert_frame_equal(first.records, second.records)
    pd.testing.assert_frame_equal(first.summary, second.summary)
    row = first.selected
    assert row["target_alignment"] == "target_mismatch_assignment_diagnostic"
    assert "bias" not in first.summary.columns
    assert "power" not in first.summary.columns
    assert np.isclose(
        row["budget_efficiency"],
        row["expected_incremental_outcome"] / row["mean_full_policy_spend"],
    )
    assert np.isclose(
        row["modeled_welfare_per_dollar"],
        row["modeled_incremental_welfare"] / row["mean_full_policy_spend"],
    )
    assert set(first.records["evidence_type"]) == {"semi_synthetic_structural_known_truth"}
    assert set(first.records["treatment_version"]) == {"bundled"}
    assert (first.records["full_policy_spend"] <= controls.budget + 1e-7).all()


def test_artifact_recommendation_excludes_incompatible_low_rmse_row(tmp_path: Path) -> None:
    controls = _small_controls()
    frame = pd.DataFrame(
        {
            "design": ["individual", "switchback", "geo_cluster", "time_block"],
            "estimator": ["regression_adjustment", "cluster_robust"] * 2,
            "target_estimand": ["market_total_effect"] * 4,
            "scenario": ["test"] * 4,
            "declared_scenario_set": ['["test"]'] * 4,
            "declared_scenario_count": [1] * 4,
            "treatment_version": [controls.treatment_version] * 4,
            "spillover_strength": [controls.spillover_strength] * 4,
            "persistence": [controls.persistence] * 4,
            "treatment_duration": [controls.treatment_duration] * 4,
            "washout_periods": [0, controls.washout_periods, 0, controls.washout_periods],
            "treatment_saturation": [controls.treatment_saturation] * 4,
            "treatment_probability": [controls.treatment_probability] * 4,
            "configured_geo_clusters": [np.nan, np.nan, controls.n_clusters, np.nan],
            "n_zones": [max(4, controls.n_clusters * 2)] * 4,
            "n_periods": [controls.experiment_duration] * 4,
            "budget": [controls.budget] * 4,
            "incentive_per_driver": [controls.incentive_size] * 4,
            "bias": [0.01, 0.2, 0.01, 0.01],
            "bias_mcse": [0.01] * 4,
            "rmse": [0.01, 0.3, 0.01, 0.01],
            "coverage": [0.95] * 4,
            "coverage_mcse": [0.02] * 4,
            "power": [0.99, 0.8, 0.99, 0.99],
            "mean_std_error": [0.01, 0.2, 0.01, 0.01],
            "identified": [True] * 4,
            "inference_valid": [True, True, False, True],
            "fit_complete": [True, True, True, False],
            "applicable": [True] * 4,
            "attempted_fits": [40] * 4,
            "successful_fits": [40, 40, 40, 39],
            "evidence_type": ["semi_synthetic_causal_monte_carlo"] * 4,
        }
    )
    path = tmp_path / "benchmark_results.csv"
    frame.to_csv(path, index=False)

    artifact = load_benchmark_artifact(path)
    assert artifact is not None
    decision = artifact_decision(artifact, controls)
    assert decision is not None
    # The low-RMSE individual row is estimand-incompatible, geo inference is invalid,
    # and time-block fitting is incomplete. None may outrank the valid switchback.
    assert decision.recommendation["design"] == "switchback"
    caveat = _recommended_design_caveat(decision)
    assert "switchback" in caveat.lower()
    assert "washout" in caveat

    artifact.summary["declared_scenario_set"] = '["stress","test"]'
    artifact.summary["declared_scenario_count"] = 2
    assert artifact_decision(artifact, controls) is None
    artifact.summary["declared_scenario_set"] = '["test"]'
    artifact.summary["declared_scenario_count"] = 1

    artifact.summary.loc[artifact.summary["design"] == "switchback", "power"] = np.nan
    assert artifact_decision(artifact, controls) is None

    mismatched = artifact_decision(
        artifact,
        _small_controls(treatment_probability=0.7),
    )
    assert mismatched is None


def test_actual_recovery_schema_fails_closed_for_unconstrained_budget(tmp_path: Path) -> None:
    controls = _small_controls(
        spillover_strength=0.0,
        persistence=0.0,
        washout_periods=0,
        treatment_probability=0.5,
    )
    frame = pd.DataFrame(
        {
            "scenario": ["no_interference"],
            "declared_scenario_set": ['["no_interference"]'],
            "declared_scenario_count": [1],
            "treatment_version": [controls.treatment_version],
            "design": ["switchback"],
            "estimator": ["cluster_robust"],
            "target_estimand": ["market_total_effect"],
            "spillover_strength": [0.0],
            "persistence": [0.0],
            "treatment_duration": [controls.treatment_duration],
            "washout_periods": [0],
            "treatment_saturation": [1.0],
            "treatment_probability": [0.5],
            "configured_geo_clusters": [np.nan],
            "n_periods": [controls.experiment_duration],
            "budget_scope": ["unconstrained estimator-recovery simulation"],
            "identified": [True],
            "inference_valid": [True],
            "fit_complete": [True],
            "applicable": [True],
            "attempted_fits": [40],
            "successful_fits": [40],
            "bias": [0.1],
            "rmse": [0.2],
            "coverage": [0.95],
            "power": [0.8],
            "evidence_type": ["semi_synthetic_causal_monte_carlo"],
        }
    )
    path = tmp_path / "benchmark_results.csv"
    frame.to_csv(path, index=False)
    artifact = load_benchmark_artifact(path)
    assert artifact is not None
    _, missing = match_benchmark_artifact(artifact, controls)
    assert "budget" in missing
    assert "incentive_size" in missing
    assert artifact_decision(artifact, controls) is None


def test_mixed_budget_grid_matches_capped_or_certified_unconstrained_rows(
    tmp_path: Path,
) -> None:
    controls = _small_controls(
        randomization_unit="time_block",
        spillover_strength=0.0,
        persistence=0.0,
        washout_periods=0,
        budget=800.0,
    )
    declarations = '["baseline","shared_budget_low"]'
    frame = pd.DataFrame(
        {
            "scenario": ["baseline", "shared_budget_low"],
            "declared_scenario_set": [declarations] * 2,
            "declared_scenario_count": [2] * 2,
            "treatment_version": ["bundled"] * 2,
            "design": ["time_block"] * 2,
            "estimator": ["cluster_robust"] * 2,
            "target_estimand": ["market_total_effect"] * 2,
            "spillover_strength": [0.0] * 2,
            "persistence": [0.0] * 2,
            "treatment_duration": [controls.treatment_duration] * 2,
            "washout_periods": [0] * 2,
            "treatment_saturation": [1.0] * 2,
            "treatment_probability": [0.5] * 2,
            "configured_geo_clusters": [np.nan] * 2,
            "n_zones": [8] * 2,
            "n_periods": [12] * 2,
            "incentive_per_driver": [1.5] * 2,
            "budget": [np.nan, 100.0],
            "budget_scope": [
                "unconstrained estimator-recovery simulation",
                "shared treatment budget",
            ],
            "nonbinding_budget_threshold": [700.0] * 2,
            "identified": [True, False],
            "inference_valid": [True, True],
            "fit_complete": [True, True],
            "applicable": [True, True],
            "attempted_fits": [40, 40],
            "successful_fits": [40, 40],
            "bias": [0.1, np.nan],
            "rmse": [0.2, np.nan],
            "coverage": [0.95, np.nan],
            "power": [0.8, np.nan],
            "evidence_type": ["semi_synthetic_causal_monte_carlo"] * 2,
        }
    )
    path = tmp_path / "benchmark_results.csv"
    frame.to_csv(path, index=False)
    artifact = load_benchmark_artifact(path)
    assert artifact is not None

    uncapped_rows, missing = match_benchmark_artifact(artifact, controls)
    assert missing == ()
    assert uncapped_rows["scenario"].tolist() == ["baseline"]
    # Conditional subset ranking is withheld without top-manifest lineage.
    assert artifact_decision(artifact, controls) is None
    conditional = artifact_decision(replace(artifact, lineage_validated=True), controls)
    assert conditional is not None
    assert conditional.recommendation_scope == "selected_scenario_conditional"
    assert conditional.matched_scenarios == ("baseline",)
    assert conditional.unmatched_scenarios == ("shared_budget_low",)

    capped_rows, capped_missing = match_benchmark_artifact(
        artifact,
        replace(controls, budget=100.0),
    )
    assert capped_missing == ()
    assert capped_rows["scenario"].tolist() == ["shared_budget_low"]
    no_match, no_match_missing = match_benchmark_artifact(
        artifact,
        replace(controls, budget=650.0),
    )
    assert no_match.empty
    assert no_match_missing == ()


def test_generated_recovery_matches_only_above_nonbinding_spend_threshold(
    tmp_path: Path,
) -> None:
    simulation = SimulationConfig(
        n_periods=32,
        incentive_per_driver=2.25,
        design=DesignConfig(
            treatment_duration=4,
            washout_periods=0,
            treatment_probability=0.5,
            treatment_saturation=1.0,
        ),
    )
    generated = run_marketplace_benchmark(
        BenchmarkConfig(
            replications=8,
            seed=404,
            designs=("time_block",),
            estimators=("cluster_robust",),
        ),
        simulation,
        scenarios=(SensitivityScenario("no_interference", 0.0, 0.0),),
    )
    path = tmp_path / "benchmark_results.csv"
    generated.summary.to_csv(path, index=False)
    artifact = load_benchmark_artifact(path)
    assert artifact is not None
    threshold = float(generated.summary["nonbinding_budget_threshold"].iloc[0])
    controls = DashboardControls(
        randomization_unit="time_block",
        experiment_duration=32,
        n_clusters=4,
        spillover_strength=0.0,
        persistence=0.0,
        incentive_size=2.25,
        budget=threshold + 1.0,
        treatment_duration=4,
        washout_periods=0,
        treatment_saturation=1.0,
        treatment_probability=0.5,
        replications=2,
        seed=71,
    )
    decision = artifact_decision(artifact, controls)
    assert decision is not None
    assert decision.recommendation["design"] == "time_block"
    assert artifact_decision(artifact, replace(controls, budget=threshold - 1.0)) is None
    assert artifact_decision(artifact, replace(controls, incentive_size=2.50)) is None
    assert (
        artifact_decision(
            artifact,
            replace(controls, treatment_version="rider_discount"),
        )
        is None
    )


def test_artifact_rejects_empirical_association_as_causal_benchmark(tmp_path: Path) -> None:
    path = tmp_path / "benchmark_results.csv"
    pd.DataFrame(
        {
            "design": ["switchback"],
            "scenario": ["test"],
            "declared_scenario_set": ['["test"]'],
            "declared_scenario_count": [1],
            "estimator": ["cluster_robust"],
            "target_estimand": ["market_total_effect"],
            "bias": [0.0],
            "rmse": [0.1],
            "coverage": [0.95],
            "power": [0.8],
            "identified": [True],
            "inference_valid": [True],
            "fit_complete": [True],
            "applicable": [True],
            "attempted_fits": [10],
            "successful_fits": [10],
            "evidence_type": ["empirical_association"],
        }
    ).to_csv(path, index=False)
    with pytest.raises(ValueError, match="semi-synthetic"):
        load_benchmark_artifact(path)


def test_default_artifact_discovery_requires_complete_manifest_lineage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    benchmark_dir = tmp_path / "artifacts" / "benchmarks"
    benchmark_dir.mkdir(parents=True)
    path = benchmark_dir / "benchmark_results.csv"
    pd.DataFrame(
        {
            "design": ["switchback"],
            "scenario": ["test"],
            "declared_scenario_set": ['["test"]'],
            "declared_scenario_count": [1],
            "estimator": ["cluster_robust"],
            "target_estimand": ["market_total_effect"],
            "bias": [0.0],
            "rmse": [0.1],
            "coverage": [0.95],
            "power": [0.8],
            "identified": [True],
            "inference_valid": [True],
            "fit_complete": [True],
            "applicable": [True],
            "attempted_fits": [10],
            "successful_fits": [10],
            "evidence_type": ["semi_synthetic_causal_monte_carlo"],
        }
    ).to_csv(path, index=False)
    monkeypatch.setattr("casuallab.dashboard._project_root", lambda: tmp_path)

    with pytest.raises(ValueError, match="reproduce_manifest"):
        load_benchmark_artifact()

    source_dir = tmp_path / "src"
    source_dir.mkdir()
    source_input = source_dir / "example.py"
    source_input.write_text("VALUE = 1\n", encoding="utf-8")
    payload = {
        "files": [
            {
                "path": "artifacts/benchmarks/benchmark_results.csv",
                "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        ],
        "metadata": {"source_tree_sha256": _source_tree_sha256(tmp_path)},
    }
    (tmp_path / "artifacts" / "reproduce_manifest.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )
    assert load_benchmark_artifact() is not None

    (tmp_path / "artifacts" / "REPRODUCE_INCOMPLETE.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="marked incomplete"):
        load_benchmark_artifact()
    (tmp_path / "artifacts" / "REPRODUCE_INCOMPLETE.json").unlink()

    source_input.write_text("VALUE = 2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="source/config tree"):
        load_benchmark_artifact()
    source_input.write_text("VALUE = 1\n", encoding="utf-8")
    assert load_benchmark_artifact() is not None

    path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="byte count"):
        load_benchmark_artifact()


def test_evidence_layers_require_top_and_child_lineage_and_preserve_labels(
    tmp_path: Path,
) -> None:
    paths = _evidence_layer_fixture(tmp_path)

    statuses = load_evidence_layers(tmp_path)

    assert [status.key for status in statuses] == [
        "nyc_informed",
        "nyc_graph",
        "equilibrium",
        "weather",
        "events",
        "income",
    ]
    assert all(status.available for status in statuses)
    assert all(
        status.manifest_sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
        for status, path in zip(
            statuses,
            (
                paths["nyc_informed"],
                paths["nyc_graph"],
                paths["equilibrium"],
                paths["weather"],
                paths["events"],
                paths["income"],
            ),
            strict=True,
        )
    )
    rows = evidence_layer_rows(statuses)
    assert {row["Status"] for row in rows} == {"Available"}
    assert [row["Classification"] for row in rows] == [
        "Semi-synthetic known truth",
        "Semi-synthetic known truth",
        "Theoretical equilibrium known truth",
        "Descriptive observed data — non-causal",
        "Descriptive observed data — non-causal",
        "Descriptive ecological data — non-causal",
    ]
    assert "not NYC causal estimates" in rows[0]["Interpretation"]
    assert "exposure geometry only" in rows[1]["Interpretation"]
    assert "not an NYC structural estimate" in rows[2]["Interpretation"]
    assert "descriptive associations only" in rows[3]["Interpretation"]
    assert "not attendance" in rows[4]["Interpretation"]
    assert "not rider or driver income" in rows[5]["Interpretation"]


def test_evidence_layer_is_unavailable_when_child_file_hash_is_stale(
    tmp_path: Path,
) -> None:
    paths = _evidence_layer_fixture(tmp_path)
    summary = paths["nyc_informed"].parent / "summary.csv"
    summary.write_text(summary.read_text(encoding="utf-8") + "tamper\n", encoding="utf-8")

    statuses = {status.key: status for status in load_evidence_layers(tmp_path)}

    assert statuses["nyc_informed"].available is False
    assert "byte count mismatch" in statuses["nyc_informed"].detail
    assert all(
        statuses[key].available
        for key in ("nyc_graph", "equilibrium", "weather", "events", "income")
    )


def test_evidence_layer_is_unavailable_when_upstream_input_is_tampered(
    tmp_path: Path,
) -> None:
    paths = _evidence_layer_fixture(tmp_path)
    manifest = json.loads(paths["nyc_informed"].read_text(encoding="utf-8"))
    anchor = tmp_path / manifest["inputs"][0]["path"]
    anchor.write_text(anchor.read_text(encoding="utf-8") + "tamper\n", encoding="utf-8")

    statuses = {status.key: status for status in load_evidence_layers(tmp_path)}

    assert statuses["nyc_informed"].available is False
    assert "input byte count mismatch" in statuses["nyc_informed"].detail
    assert statuses["nyc_graph"].available is True


def test_new_enrichment_layers_fail_closed_for_tamper_partial_and_causal_label(
    tmp_path: Path,
) -> None:
    paths = _evidence_layer_fixture(tmp_path)
    event_payload = json.loads(paths["events"].read_text(encoding="utf-8"))
    holiday_entry = next(
        entry
        for entry in event_payload["inputs"]
        if entry["role"] == "official_holiday_snapshot"
    )
    holiday_path = tmp_path / holiday_entry["path"]
    original_holiday = holiday_path.read_bytes()
    holiday_path.write_bytes(original_holiday + b"tamper")

    statuses = {status.key: status for status in load_evidence_layers(tmp_path)}
    assert statuses["events"].available is False
    assert "input byte count mismatch" in statuses["events"].detail
    assert statuses["income"].available is True
    holiday_path.write_bytes(original_holiday)

    income_payload = json.loads(paths["income"].read_text(encoding="utf-8"))
    income_payload["inputs"] = [
        entry
        for entry in income_payload["inputs"]
        if entry["role"] != "official_nyc_nta2020_geometry"
    ]
    income_payload["declared_input_set_sha256"] = hashlib.sha256(
        json.dumps(
            income_payload["inputs"], sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    _write_json(paths["income"], income_payload)
    _refresh_top_manifest_entry(tmp_path, paths["income"])
    statuses = {status.key: status for status in load_evidence_layers(tmp_path)}
    assert statuses["income"].available is False
    assert "incomplete input-role set" in statuses["income"].detail
    assert statuses["events"].available is True

    event_payload["causal_claim"] = True
    _write_json(paths["events"], event_payload)
    _refresh_top_manifest_entry(tmp_path, paths["events"])
    statuses = {status.key: status for status in load_evidence_layers(tmp_path)}
    assert statuses["events"].available is False
    assert "invalid descriptive evidence schema" in statuses["events"].detail


def test_income_layer_rejects_primary_gate_type_code_and_sensitivity_tamper(
    tmp_path: Path,
) -> None:
    paths = _evidence_layer_fixture(tmp_path)
    manifest_path = paths["income"]
    original_manifest = manifest_path.read_bytes()

    payload = json.loads(original_manifest)
    payload["checks"]["dominant_nonresidential_primary_unclassified"] = False
    _write_json(manifest_path, payload)
    _refresh_top_manifest_entry(tmp_path, manifest_path)
    status = {item.key: item for item in load_evidence_layers(tmp_path)}["income"]
    assert status.available is False
    assert "invalid ecological evidence schema" in status.detail

    manifest_path.write_bytes(original_manifest)
    _refresh_top_manifest_entry(tmp_path, manifest_path)
    payload = json.loads(original_manifest)
    payload["checks"]["residential_nta_type_codes"] = ["9"]
    _write_json(manifest_path, payload)
    _refresh_top_manifest_entry(tmp_path, manifest_path)
    status = {item.key: item for item in load_evidence_layers(tmp_path)}["income"]
    assert status.available is False
    assert "invalid ecological evidence schema" in status.detail

    manifest_path.write_bytes(original_manifest)
    _refresh_top_manifest_entry(tmp_path, manifest_path)
    manifest = json.loads(original_manifest)
    summary_entry = next(
        entry
        for entry in manifest["files"]
        if entry["role"] == "income_association_summary"
    )
    summary = json.loads((tmp_path / summary_entry["path"]).read_text(encoding="utf-8"))
    summary["sensitivity"]["all_zone_area_allocation"]["primary_result"] = True
    _rewrite_child_json_role(
        tmp_path,
        manifest_path,
        "income_association_summary",
        summary,
    )
    status = {item.key: item for item in load_evidence_layers(tmp_path)}["income"]
    assert status.available is False
    assert "inconsistent sensitivity arithmetic" in status.detail


def test_event_layer_rejects_zero_duration_gate_and_count_tamper(
    tmp_path: Path,
) -> None:
    paths = _evidence_layer_fixture(tmp_path)
    manifest_path = paths["events"]
    original_manifest = manifest_path.read_bytes()
    payload = json.loads(original_manifest)
    payload["checks"]["zero_duration_source_intervals_retained_and_excluded"] = False
    _write_json(manifest_path, payload)
    _refresh_top_manifest_entry(tmp_path, manifest_path)
    status = {item.key: item for item in load_evidence_layers(tmp_path)}["events"]
    assert status.available is False
    assert "invalid descriptive evidence schema" in status.detail

    manifest_path.write_bytes(original_manifest)
    _refresh_top_manifest_entry(tmp_path, manifest_path)
    manifest = json.loads(original_manifest)
    summary_entry = next(
        entry for entry in manifest["files"] if entry["role"] == "descriptive_summary"
    )
    summary = json.loads((tmp_path / summary_entry["path"]).read_text(encoding="utf-8"))
    summary["coverage"][
        "zero_duration_interval_rows_retained_but_not_expanded"
    ] += 1
    _rewrite_child_json_role(
        tmp_path,
        manifest_path,
        "descriptive_summary",
        summary,
    )
    status = {item.key: item for item in load_evidence_layers(tmp_path)}["events"]
    assert status.available is False
    assert "inconsistent interval counts" in status.detail


@pytest.mark.parametrize("invalid_path", ["../anchor.json", "/tmp/anchor.json"])
def test_evidence_layer_rejects_nonportable_upstream_input_paths(
    tmp_path: Path,
    invalid_path: str,
) -> None:
    paths = _evidence_layer_fixture(tmp_path)
    manifest_path = paths["nyc_informed"]
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["inputs"][0]["path"] = invalid_path
    _write_json(manifest_path, payload)
    _refresh_top_manifest_entry(tmp_path, manifest_path)

    status = {item.key: item for item in load_evidence_layers(tmp_path)}["nyc_informed"]

    assert status.available is False
    assert "project-root relative and traversal-free" in status.detail


def test_evidence_layer_rejects_duplicate_upstream_inputs(tmp_path: Path) -> None:
    paths = _evidence_layer_fixture(tmp_path)
    manifest_path = paths["nyc_informed"]
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["inputs"][1]["path"] = payload["inputs"][0]["path"]
    _write_json(manifest_path, payload)
    _refresh_top_manifest_entry(tmp_path, manifest_path)

    status = {item.key: item for item in load_evidence_layers(tmp_path)}["nyc_informed"]

    assert status.available is False
    assert "input paths" in status.detail


def test_evidence_layer_is_unavailable_when_scientific_schema_is_mislabeled(
    tmp_path: Path,
) -> None:
    paths = _evidence_layer_fixture(tmp_path)
    equilibrium_manifest = paths["equilibrium"]
    payload = json.loads(equilibrium_manifest.read_text(encoding="utf-8"))
    payload["is_nyc_structural_estimate"] = True
    _write_json(equilibrium_manifest, payload)
    _refresh_top_manifest_entry(tmp_path, equilibrium_manifest)

    statuses = {status.key: status for status in load_evidence_layers(tmp_path)}

    assert statuses["equilibrium"].available is False
    assert "invalid theoretical evidence schema" in statuses["equilibrium"].detail
    assert statuses["nyc_informed"].available is True


def test_evidence_layers_fail_closed_for_stale_source_or_top_entry(tmp_path: Path) -> None:
    paths = _evidence_layer_fixture(tmp_path)
    paths["source"].write_text("VALUE = 2\n", encoding="utf-8")

    stale_source = load_evidence_layers(tmp_path)
    assert all(not status.available for status in stale_source)
    assert all("source/config tree" in status.detail for status in stale_source)

    paths["source"].write_text("VALUE = 1\n", encoding="utf-8")
    paths["weather"].write_text(
        paths["weather"].read_text(encoding="utf-8") + "\n", encoding="utf-8"
    )
    stale_entry = {status.key: status for status in load_evidence_layers(tmp_path)}
    assert stale_entry["weather"].available is False
    assert "byte count" in stale_entry["weather"].detail
    assert stale_entry["nyc_graph"].available is True


def test_absent_evidence_manifests_are_reported_unavailable(tmp_path: Path) -> None:
    statuses = load_evidence_layers(tmp_path)

    assert len(statuses) == 6
    assert all(not status.available for status in statuses)
    assert all(status.detail == "unavailable: manifest is absent" for status in statuses)


def test_loader_accepts_current_descriptive_calibration_label(tmp_path: Path) -> None:
    path = tmp_path / "calibration.json"
    path.write_text(
        json.dumps(
            {
                "evidence_type": "illustrative_empirical_scale_anchor",
                "simulation_config": SimulationConfig().to_dict(),
            }
        ),
        encoding="utf-8",
    )
    template = load_calibration_template(path)
    assert template is not None
    assert template.evidence_type == "illustrative_empirical_scale_anchor"
    assert template.config == SimulationConfig()
    assert len(template.sha256) == 64


def test_streamlit_renders_six_read_only_evidence_layers() -> None:
    streamlit_testing = pytest.importorskip("streamlit.testing.v1")
    app_path = Path(__file__).parents[1] / "src" / "casuallab" / "dashboard.py"
    app = streamlit_testing.AppTest.from_file(str(app_path), default_timeout=90).run()

    assert not app.exception
    assert "Evidence layers" in [item.value for item in app.subheader]
    evidence_tables = [
        item.value
        for item in app.dataframe
        if "Evidence layer" in item.value.columns
    ]
    assert len(evidence_tables) == 1
    evidence = evidence_tables[0]
    assert len(evidence) == 6
    assert set(evidence["Status"]).issubset({"Available", "Unavailable"})
    assert evidence["Classification"].tolist() == [
        "Semi-synthetic known truth",
        "Semi-synthetic known truth",
        "Theoretical equilibrium known truth",
        "Descriptive observed data — non-causal",
        "Descriptive observed data — non-causal",
        "Descriptive ecological data — non-causal",
    ]
    assert any("not an NYC structural estimate" in text for text in evidence["Interpretation"])
    assert any("descriptive associations only" in text for text in evidence["Interpretation"])
    assert any("not attendance" in text for text in evidence["Interpretation"])
    assert any("not rider or driver income" in text for text in evidence["Interpretation"])


def test_streamlit_hides_cached_results_after_treatment_control_changes() -> None:
    streamlit_testing = pytest.importorskip("streamlit.testing.v1")
    app_path = Path(__file__).parents[1] / "src" / "casuallab" / "dashboard.py"
    app = streamlit_testing.AppTest.from_file(str(app_path), default_timeout=90).run()

    app.button[0].click().run(timeout=90)
    assert not app.exception
    assert len(app.metric) > 0
    app.run(timeout=90)
    assert len(app.metric) > 0
    app.selectbox[1].select("rider_discount").run(timeout=90)

    assert not app.exception
    assert not app.metric
    assert any("hidden until you rerun" in warning.value for warning in app.warning)
