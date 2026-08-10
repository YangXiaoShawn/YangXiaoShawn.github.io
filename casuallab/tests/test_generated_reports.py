from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest
from test_equilibrium import _config as _equilibrium_config
from test_nyc_benchmark import _laptop_config, _verified_anchor_artifacts
from test_nyc_events import _data_manifest as _event_data_manifest
from test_nyc_events import _panel as _event_panel
from test_nyc_events import _snapshots as _event_snapshots
from test_nyc_graph_benchmark import _synthetic_bundle
from test_nyc_income import _fixture as _income_fixture
from test_nyc_simulation import write_nyc_calibration_test_bundle
from test_nyc_weather import _data_manifest, _panel, _raw_weather

from casuallab.cli import write_nyc_simulation_anchor_output
from casuallab.config import SimulationConfig
from casuallab.equilibrium import (
    run_equilibrium_benchmark,
    write_equilibrium_artifacts,
)
from casuallab.generated_reports import generate_report_bundle
from casuallab.interference_benchmark import (
    InterferenceBenchmarkConfig,
    run_interference_benchmark,
)
from casuallab.nyc_benchmark import (
    run_nyc_informed_marketplace_benchmark,
    write_nyc_benchmark_artifacts,
)
from casuallab.nyc_events import write_nyc_events_bundle
from casuallab.nyc_graph_benchmark import (
    NYCGraphBenchmarkConfig,
    run_nyc_graph_benchmark,
    write_nyc_graph_benchmark_artifacts,
)
from casuallab.nyc_income import write_nyc_income_bundle
from casuallab.nyc_simulation import (
    NYCSimulationAnchorSettings,
    build_nyc_simulation_anchor,
)
from casuallab.nyc_weather import write_nyc_weather_bundle


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rewrite_bundle_json_role(
    manifest_path: Path,
    role: str,
    payload: dict[str, object],
) -> Path:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entry = next(item for item in manifest["files"] if item["role"] == role)
    declared = Path(entry["path"])
    artifact_path = next(
        parent / declared
        for parent in manifest_path.parents
        if (parent / declared).is_file()
    )
    artifact_path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    entry["bytes"] = artifact_path.stat().st_size
    entry["sha256"] = _sha256(artifact_path)
    manifest["declared_file_set_sha256"] = hashlib.sha256(
        json.dumps(manifest["files"], sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    return artifact_path


def _write_verified_nyc_full_evidence(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "nyc_evidence"
    validation_path = root / "artifacts/nyc_full/validation.json"
    data_manifest_path = root / "data/nyc_full/manifest.json"
    analysis_manifest_path = root / "artifacts/nyc_full/manifest.json"
    validation_path.parent.mkdir(parents=True)
    data_manifest_path.parent.mkdir(parents=True)
    raw_sha = "9" * 64
    config = {
        "source": "nyc_hvfhv",
        "mode": "full",
        "nyc_year": 2024,
        "nyc_months": [1],
        "nyc_expected_rows": 19_663_930,
        "nyc_expected_bytes": 472_757_547,
        "nyc_expected_sha256": raw_sha,
        "manifest_path": "data/nyc_full/manifest.json",
    }
    data_manifest_path.write_text(
        json.dumps(
            {
                "config": config,
                "files": [],
                "metadata": {
                    "causal_claim": False,
                    "evidence_label": "descriptive_real_data",
                },
            }
        ),
        encoding="utf-8",
    )
    data_manifest_sha = _sha256(data_manifest_path)
    validation_path.write_text(
        json.dumps(
            {
                "evidence_label": "descriptive_real_data",
                "causal_claim": False,
                "validation_passed": True,
                "checks": {
                    "raw_equals_clean": True,
                    "zone_conserves_clean": True,
                    "od_conserves_clean": True,
                    "calendar_complete": True,
                    "manifest_files_valid": True,
                    "manifest_scope_valid": True,
                    "resource_limit_passed": True,
                },
                "scope": {
                    "source": "nyc_hvfhv",
                    "pickup_month": "2024-01",
                    "unit": "published_completed_trip_record",
                    "population_claim": False,
                },
                "coverage": {
                    "clean_rows": 19_663_930,
                    "service_dates": 31,
                    "hours_of_day": 24,
                    "date_hours": 744,
                },
                "conservation": {
                    "raw_rows": 19_663_930,
                    "zone_time_rows": 194_928,
                    "od_rows": 6_877_734,
                    "zone_trip_sum": 19_663_930,
                    "od_trip_sum": 19_663_930,
                },
                "provenance": {
                    "data_manifest": "data/nyc_full/manifest.json",
                    "data_manifest_sha256": data_manifest_sha,
                    "sha256": [raw_sha],
                },
                "resources": {
                    "elapsed_seconds": 55.18,
                    "max_rss_bytes": 3_839_901_696,
                    "peak_memory_footprint_bytes": 6_313_925_232,
                    "memory_limit_bytes": 16 * 1024**3,
                },
                "limitations": [
                    "Published completed-trip records exclude latent and unserved demand.",
                    "Observed fare-demand relationships are endogenous associations, not elasticities.",
                    "No treatment assignment exists; no causal intervention effect is estimated.",
                ],
            }
        ),
        encoding="utf-8",
    )
    files = []
    for path in (validation_path, data_manifest_path):
        files.append(
            {
                "path": str(path.relative_to(root)),
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    analysis_manifest_path.write_text(
        json.dumps(
            {
                "config": config,
                "files": files,
                "metadata": {
                    "evidence_label": "descriptive_real_data",
                    "causal_claim": False,
                    "validation_passed": True,
                    "source_data_manifest_sha256": data_manifest_sha,
                },
            }
        ),
        encoding="utf-8",
    )
    return validation_path, analysis_manifest_path


def _write_treatment_version_policy_evidence(
    tmp_path: Path, bundled_policy_path: Path
) -> tuple[Path, Path]:
    root = tmp_path / "version_policy_evidence"
    summary_path = root / "artifacts/benchmarks/treatment_version_policy_results.csv"
    ledger_path = (
        root / "artifacts/benchmarks/treatment_version_policy_market_ledger.csv"
    )
    manifest_path = (
        root / "artifacts/benchmarks/treatment_version_policy_manifest.json"
    )
    summary_path.parent.mkdir(parents=True)
    base = pd.read_csv(bundled_policy_path)
    versions = ("rider_discount", "driver_incentive", "bundled")
    frames = []
    ledger_rows = []
    pairing = "common training/holdout market seeds across intervention versions"
    for version in versions:
        frame = base.copy()
        frame["treatment_version"] = version
        frame["version_pairing"] = pairing
        frame["version_evidence_scope"] = (
            "semi-synthetic response-function sensitivity; not an empirical dose response"
        )
        frame["simulation_config"] = json.dumps(
            {"n_zones": 4, "treatment_version": version}, sort_keys=True
        )
        frames.append(frame)
        for policy in frame["policy"]:
            for seed in (3, 4):
                ledger_rows.append(
                    {
                        "policy": policy,
                        "treatment_version": version,
                        "version_pairing": pairing,
                        "holdout_market_seed": seed,
                        "evidence_type": "semi_synthetic_policy_holdout_market",
                    }
                )
    pd.concat(frames, ignore_index=True).to_csv(summary_path, index=False)
    pd.DataFrame(ledger_rows).to_csv(ledger_path, index=False)
    files = [
        {
            "path": str(path.relative_to(root)),
            "bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }
        for path in (summary_path, ledger_path)
    ]
    manifest_path.write_text(
        json.dumps(
            {
                "files": files,
                "metadata": {
                    "evidence_type": (
                        "semi_synthetic_treatment_version_policy_sensitivity"
                    ),
                    "treatment_versions": list(versions),
                    "version_pairing": pairing,
                },
            }
        ),
        encoding="utf-8",
    )
    return summary_path, manifest_path


def _write_interference_evidence(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "interference_evidence"
    output = root / "artifacts/benchmarks"
    output.mkdir(parents=True)
    result = run_interference_benchmark(
        InterferenceBenchmarkConfig(
            replications=4,
            n_zones=8,
            n_clusters=8,
            n_periods=12,
            seed=777,
        )
    )
    paths = {
        "interference_records.csv": result.records,
        "interference_summary.csv": result.summary,
        "interference_failures.csv": result.failures,
        "interference_fit_ledger.csv": result.fit_ledger,
    }
    for name, frame in paths.items():
        frame.to_csv(output / name, index=False)
    metadata_path = output / "interference_metadata.json"
    metadata_path.write_text(json.dumps(result.metadata, sort_keys=True), encoding="utf-8")
    files = [
        {
            "path": str(path.relative_to(root)),
            "bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }
        for path in sorted(output.glob("interference_*.csv"))
    ]
    files.append(
        {
            "path": str(metadata_path.relative_to(root)),
            "bytes": metadata_path.stat().st_size,
            "sha256": _sha256(metadata_path),
        }
    )
    manifest_path = output / "interference_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "files": files,
                "metadata": {
                    "evidence_type": result.metadata["evidence_type"],
                    "benchmark_config": result.metadata["config"],
                    "known_estimands": result.metadata["known_estimands"],
                    "controlled_exposure_not_market_total": True,
                },
            }
        ),
        encoding="utf-8",
    )
    return output / "interference_summary.csv", manifest_path


def _write_nyc_simulation_anchor_evidence(
    tmp_path: Path,
) -> tuple[Path, Path, dict[str, Path]]:
    root = tmp_path / "nyc_anchor_evidence"
    calibration_bundle = write_nyc_calibration_test_bundle(root)
    simulation_config = SimulationConfig(
        base_demand=80.0,
        base_supply=40.0,
        direct_demand_effect=0.31,
        direct_supply_effect=0.27,
        spillover_strength=0.19,
        persistence=0.41,
        rider_substitution=0.17,
        driver_mobility=0.23,
    )
    simulation_config_path = root / "configs/simulation.yaml"
    simulation_config_path.parent.mkdir(parents=True)
    simulation_config_path.write_text(
        json.dumps(simulation_config.to_dict(), sort_keys=True), encoding="utf-8"
    )
    anchor = build_nyc_simulation_anchor(
        calibration_bundle["calibration"],
        project_root=root,
        manifest_path=calibration_bundle["bundle_manifest"],
        settings=NYCSimulationAnchorSettings(
            target_n_zones=2,
            target_n_periods=168,
            seed=99,
        ),
        assumption_template=simulation_config,
    )
    outputs = write_nyc_simulation_anchor_output(
        anchor,
        root / "artifacts/nyc_full/simulation_anchor",
        calibration_path=calibration_bundle["calibration"],
        calibration_manifest_path=calibration_bundle["bundle_manifest"],
        simulation_config_path=simulation_config_path,
        project_root=root,
    )
    return outputs["anchor"], outputs["manifest"], calibration_bundle


def _write_six_new_evidence_manifests(tmp_path: Path) -> dict[str, Path]:
    nyc_root = tmp_path / "nyc_benchmark_project"
    nyc_root.mkdir()
    anchor = _verified_anchor_artifacts(nyc_root)
    nyc_result = run_nyc_informed_marketplace_benchmark(
        anchor["anchor_path"],
        anchor["anchor_manifest_path"],
        config=_laptop_config(),
        project_root=nyc_root,
    )
    nyc_paths = write_nyc_benchmark_artifacts(
        nyc_result,
        "artifacts/benchmarks/nyc_informed",
        project_root=nyc_root,
    )

    graph_root = tmp_path / "nyc_graph_project"
    graph_root.mkdir()
    calibration_bundle = _synthetic_bundle(graph_root)
    graph_result = run_nyc_graph_benchmark(
        calibration_bundle,
        NYCGraphBenchmarkConfig(
            replications=2,
            n_zones=12,
            n_periods=12,
            seed=904,
        ),
    )
    graph_paths = write_nyc_graph_benchmark_artifacts(
        graph_result,
        "artifacts/benchmarks/nyc_graph",
        project_root=graph_root,
    )

    equilibrium_root = tmp_path / "equilibrium_project"
    equilibrium_root.mkdir()
    equilibrium_paths = write_equilibrium_artifacts(
        run_equilibrium_benchmark(_equilibrium_config(budget=100.0)),
        equilibrium_root / "artifacts/benchmarks/equilibrium",
        equilibrium_root,
    )

    weather_root = tmp_path / "weather_project"
    weather_root.mkdir()
    raw_weather = weather_root / "data/nyc_weather/raw/noaa.csv"
    raw_weather.parent.mkdir(parents=True)
    weather_config = _raw_weather(raw_weather)
    panel_directory = weather_root / "data/nyc_full/panel/zone_time"
    panel_directory.mkdir(parents=True)
    panel_path = panel_directory / "part.parquet"
    panel = _panel(panel_path)
    data_manifest = _data_manifest(
        weather_root,
        panel_path,
        int(panel["trip_count"].sum()),
    )
    weather_paths = write_nyc_weather_bundle(
        raw_weather,
        panel_directory,
        data_manifest,
        weather_root / "artifacts/nyc_full/weather",
        project_root=weather_root,
        config=weather_config,
    )

    events_root = tmp_path / "events_project"
    events_root.mkdir()
    holiday_path, event_path, events_config = _event_snapshots(events_root)
    event_panel_directory = events_root / "data/nyc_full/panel/zone_time"
    event_panel_directory.mkdir(parents=True)
    event_panel_path = event_panel_directory / "part.parquet"
    event_panel = _event_panel(event_panel_path)
    event_data_manifest = _event_data_manifest(
        events_root,
        event_panel_path,
        int(event_panel["trip_count"].sum()),
    )
    events_paths = write_nyc_events_bundle(
        holiday_path,
        event_path,
        event_panel_directory,
        event_data_manifest,
        events_root / "artifacts/nyc_full/events",
        project_root=events_root,
        config=events_config,
    )

    income_root = tmp_path / "income_project"
    income_root.mkdir()
    income_inputs, income_config = _income_fixture(income_root)
    income_paths = write_nyc_income_bundle(
        income_inputs["taxi"],
        income_inputs["nta"],
        income_inputs["tract"],
        income_inputs["acs"],
        income_inputs["panel_dir"],
        income_inputs["manifest"],
        income_root / "artifacts/nyc_full/income",
        project_root=income_root,
        config=income_config,
    )
    return {
        "nyc": nyc_paths["manifest"],
        "graph": graph_paths["manifest"],
        "equilibrium": equilibrium_paths.manifest_path,
        "weather": weather_paths.manifest_path,
        "events": events_paths.manifest_path,
        "income": income_paths.manifest_path,
    }


def test_report_bundle_generates_technical_executive_and_appendix(tmp_path: Path) -> None:
    benchmark_path = tmp_path / "benchmark.csv"
    policy_path = tmp_path / "policy.csv"
    descriptive_path = tmp_path / "descriptive.json"
    hte_summary_path = tmp_path / "hte_recovery.json"
    hte_calibration_path = tmp_path / "hte_calibration.csv"
    hte_stability_path = tmp_path / "hte_stability.csv"
    nyc_validation_path, nyc_manifest_path = _write_verified_nyc_full_evidence(
        tmp_path
    )
    rows = []
    for scenario, rmse in (("none", 0.2), ("adverse", 0.4)):
        rows.append(
            {
                "scenario": scenario,
                "declared_scenario_set": '["adverse", "none"]',
                "declared_scenario_count": 2,
                "spillover_strength": 0.0,
                "persistence": 0.0,
                "design": "geo_cluster",
                "estimator": "cluster_robust",
                "target_estimand": "market_total_effect",
                "identified": True,
                "inference_valid": True,
                "fit_complete": True,
                "applicable": True,
                "attempted_fits": 10,
                "successful_fits": 10,
                "failed_fits": 0,
                "bias": 0.1,
                "rmse": rmse,
                "coverage": 0.95,
                "power": 0.8,
                "confidence_level": 0.95,
                "evidence_type": "semi_synthetic_causal_monte_carlo",
            }
        )
    pd.DataFrame(rows).to_csv(benchmark_path, index=False)
    policies = ["no_treatment", "random", "uniform", "rule_based", "model_based"]
    policy_rows = len(policies)
    pd.DataFrame(
        {
            "policy": policies,
            "expected_incremental_outcome": [0.0, 2.0, 2.3, 2.6, 3.0],
            "incremental_outcome_se": [0.0, 0.2, 0.2, 0.25, 0.3],
            "incremental_outcome_p10": [0.0, 1.5, 1.7, 2.0, 2.4],
            "incremental_outcome_vs_random": [-2.0, 0.0, 0.3, 0.6, 1.0],
            "paired_difference_se_vs_random": [0.1, 0.0, 0.1, 0.1, 0.1],
            "budget_spent": [0.0, 10.0, 10.0, 10.0, 10.0],
            "budget_efficiency": [float("nan"), 0.2, 0.23, 0.26, 0.3],
            "budget_feasible": [True] * policy_rows,
            "evaluation_complete": [True] * policy_rows,
            "policy_eligible": [True] * policy_rows,
            "mean_model_instability": [0.0, 0.0, 0.0, 0.0, 0.1],
            "decision_instability": [0.0, 0.0, 0.0, 0.0, 0.05],
            "training_market_seeds": ["[1, 2]"] * policy_rows,
            "holdout_market_seeds": ["[3, 4]"] * policy_rows,
            "training_markets": [2] * policy_rows,
            "holdout_markets": [2] * policy_rows,
            "training_signal": [
                "randomized observed outcomes; no structural truth columns"
            ]
            * policy_rows,
            "evaluation_engine": [
                "full marketplace simulator rerun per policy and seed"
            ]
            * policy_rows,
            "planning_cost_basis": [
                "pre-treatment features; no treated holdout counterfactual"
            ]
            * policy_rows,
            "target_estimand": ["full_horizon_incremental_trips"] * policy_rows,
            "target_population_id": ["paired_market_total"] * policy_rows,
            "n_zones": [4] * policy_rows,
            "n_periods": [12] * policy_rows,
            "weighting": ["paired mean"] * policy_rows,
            "simulation_config": ['{"n_zones":4}'] * policy_rows,
            "policy_config": ['{"budget":10}'] * policy_rows,
            "evidence_type": ["semi_synthetic_policy_holdout"] * policy_rows,
        }
    ).to_csv(policy_path, index=False)
    version_policy_path, version_policy_manifest_path = (
        _write_treatment_version_policy_evidence(tmp_path, policy_path)
    )
    interference_summary_path, interference_manifest_path = (
        _write_interference_evidence(tmp_path)
    )
    nyc_anchor_path, nyc_anchor_manifest_path, nyc_anchor_bundle = (
        _write_nyc_simulation_anchor_evidence(tmp_path)
    )
    descriptive_path.write_text(
        '{"evidence_type":"empirical_association","panel_rows":170,'
        '"total_observed_trips":300}',
        encoding="utf-8",
    )
    hte_summary_path.write_text(
        json.dumps(
            {
                "evidence_type": "semi_synthetic_hte_known_truth_recovery",
                "target_estimand": "controlled_zone_direct_effect",
                "rows": 32,
                "bias": 0.02,
                "rmse": 0.15,
                "fold_mean_cate_sd": 0.03,
                "known_truth_sd": 0.10,
                "oracle_constant_effect_rmse": 0.10,
                "predicted_truth_correlation": 0.20,
                "predicted_truth_rank_correlation": 0.15,
                "hte_beats_oracle_constant": False,
                "recovery_gate": "rmse_below_oracle_constant_effect_rmse",
                "crossfit_group": "geographic_randomization_cluster",
                "interference": 0.0,
                "persistence": 0.0,
            }
        ),
        encoding="utf-8",
    )
    pd.DataFrame(
        {
            "score_bin": ["low", "high"],
            "mean_predicted_cate": [0.2, 0.7],
            "mean_known_truth": [0.1, 0.8],
            "mean_error": [0.1, -0.1],
            "rmse": [0.12, 0.14],
            "rows": [16, 16],
        }
    ).to_csv(hte_calibration_path, index=False)
    pd.DataFrame(
        {
            "crossfit_fold": [0, 1],
            "mean_predicted_cate": [0.4, 0.5],
            "mean_known_truth": [0.42, 0.48],
            "mean_error": [-0.02, 0.02],
            "rmse": [0.11, 0.12],
            "rows": [16, 16],
        }
    ).to_csv(hte_stability_path, index=False)

    paths = generate_report_bundle(
        benchmark_path,
        output_directory=tmp_path / "reports",
        policy_path=policy_path,
        descriptive_path=descriptive_path,
        hte_summary_path=hte_summary_path,
        hte_calibration_path=hte_calibration_path,
        hte_stability_path=hte_stability_path,
        nyc_full_validation_path=nyc_validation_path,
        nyc_full_manifest_path=nyc_manifest_path,
        treatment_version_policy_path=version_policy_path,
        treatment_version_policy_manifest_path=version_policy_manifest_path,
        interference_summary_path=interference_summary_path,
        interference_manifest_path=interference_manifest_path,
        nyc_simulation_anchor_path=nyc_anchor_path,
        nyc_simulation_anchor_manifest_path=nyc_anchor_manifest_path,
        target_estimand="market_total_effect",
    )

    assert set(paths) == {"technical", "executive", "appendix"}
    assert all(path.is_file() for path in paths.values())
    technical = paths["technical"].read_text(encoding="utf-8")
    executive = paths["executive"].read_text(encoding="utf-8")
    assert "0.4000" in technical
    assert "300 trips" in technical
    assert "Input hashes" not in technical
    assert "Reproducibility inputs" in executive
    assert "geo_cluster" in executive
    assert "controlled_zone_direct_effect" in technical
    assert "does not beat the oracle constant-effect baseline" in technical
    assert "not decision-ready" in executive
    assert "HTE recovery summary SHA-256" in technical
    assert "Heterogeneity evidence" in executive
    assert "No unique policy winner is issued" in executive
    assert "19,663,930 published completed-trip records" in technical
    assert "55.18 seconds" in technical
    assert "3,839,901,696 bytes (3.58 GiB)" in technical
    assert "6,313,925,232 bytes (5.88 GiB)" in executive
    assert "NYC full validation SHA-256" in technical
    assert "has not been verified below" not in technical
    assert "same 2 training and 2 holdout market seeds" in executive
    assert "Treatment-version policy summary SHA-256" in technical
    assert "not an empirical dose response" in executive
    assert "two-stage geographic saturation" in technical
    assert "market-total bias, RMSE" in executive
    assert "Interference summary SHA-256" in technical
    assert "NYC-informed semi-synthetic scale anchor" in technical
    assert "7,440 published January 2024 completed trips" in technical
    assert "Treatment response, supply response" in executive
    assert "NYC simulation anchor SHA-256" in technical
    assert "NYC anchor assumption template SHA-256" in technical

    source_file = nyc_anchor_bundle["source_file"]
    original_source = source_file.read_text(encoding="utf-8")
    source_file.write_text(original_source + "tampered", encoding="utf-8")
    with pytest.raises(ValueError, match="NYC source-data manifest byte mismatch"):
        generate_report_bundle(
            benchmark_path,
            output_directory=tmp_path / "stale_nyc_anchor_reports",
            nyc_simulation_anchor_path=nyc_anchor_path,
            nyc_simulation_anchor_manifest_path=nyc_anchor_manifest_path,
            target_estimand="market_total_effect",
        )
    source_file.write_text(original_source, encoding="utf-8")

    original_anchor = nyc_anchor_path.read_text(encoding="utf-8")
    original_anchor_manifest = nyc_anchor_manifest_path.read_text(encoding="utf-8")
    tampered_anchor = json.loads(original_anchor)
    tampered_anchor["simulation_config"]["persistence"] = 0.99
    tampered_anchor["field_provenance"]["explicit_assumptions"]["persistence"][
        "value"
    ] = 0.99
    nyc_anchor_path.write_text(json.dumps(tampered_anchor), encoding="utf-8")
    tampered_manifest = json.loads(original_anchor_manifest)
    anchor_entry = next(
        entry
        for entry in tampered_manifest["files"]
        if entry["path"].endswith("nyc_simulation_anchor.json")
    )
    anchor_entry["bytes"] = nyc_anchor_path.stat().st_size
    anchor_entry["sha256"] = _sha256(nyc_anchor_path)
    nyc_anchor_manifest_path.write_text(
        json.dumps(tampered_manifest), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="causal assumptions disagree"):
        generate_report_bundle(
            benchmark_path,
            output_directory=tmp_path / "unsafe_nyc_anchor_reports",
            nyc_simulation_anchor_path=nyc_anchor_path,
            nyc_simulation_anchor_manifest_path=nyc_anchor_manifest_path,
            target_estimand="market_total_effect",
        )
    nyc_anchor_path.write_text(original_anchor, encoding="utf-8")
    nyc_anchor_manifest_path.write_text(original_anchor_manifest, encoding="utf-8")

    original_interference = interference_summary_path.read_text(encoding="utf-8")
    interference_summary_path.write_text(
        original_interference + "\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="interference benchmark manifest byte mismatch"):
        generate_report_bundle(
            benchmark_path,
            output_directory=tmp_path / "stale_interference_reports",
            interference_summary_path=interference_summary_path,
            interference_manifest_path=interference_manifest_path,
            target_estimand="market_total_effect",
        )
    interference_summary_path.write_text(original_interference, encoding="utf-8")

    original_validation = nyc_validation_path.read_text(encoding="utf-8")
    failed_validation = json.loads(original_validation)
    failed_validation["checks"]["calendar_complete"] = False
    nyc_validation_path.write_text(json.dumps(failed_validation), encoding="utf-8")
    with pytest.raises(ValueError, match="checks did not all pass"):
        generate_report_bundle(
            benchmark_path,
            output_directory=tmp_path / "failed_nyc_reports",
            policy_path=policy_path,
            descriptive_path=descriptive_path,
            hte_summary_path=hte_summary_path,
            hte_calibration_path=hte_calibration_path,
            hte_stability_path=hte_stability_path,
            nyc_full_validation_path=nyc_validation_path,
            nyc_full_manifest_path=nyc_manifest_path,
            treatment_version_policy_path=version_policy_path,
            treatment_version_policy_manifest_path=version_policy_manifest_path,
            target_estimand="market_total_effect",
        )
    nyc_validation_path.write_text(original_validation, encoding="utf-8")

    tampered_validation = json.loads(original_validation)
    tampered_validation["resources"]["max_rss_bytes"] += 1
    nyc_validation_path.write_text(json.dumps(tampered_validation), encoding="utf-8")
    with pytest.raises(ValueError, match="manifest SHA-256 mismatch"):
        generate_report_bundle(
            benchmark_path,
            output_directory=tmp_path / "stale_nyc_reports",
            policy_path=policy_path,
            descriptive_path=descriptive_path,
            hte_summary_path=hte_summary_path,
            hte_calibration_path=hte_calibration_path,
            hte_stability_path=hte_stability_path,
            nyc_full_validation_path=nyc_validation_path,
            nyc_full_manifest_path=nyc_manifest_path,
            treatment_version_policy_path=version_policy_path,
            treatment_version_policy_manifest_path=version_policy_manifest_path,
            target_estimand="market_total_effect",
        )
    nyc_validation_path.write_text(original_validation, encoding="utf-8")

    original_version_policy = version_policy_path.read_text(encoding="utf-8")
    version_policy_path.write_text(original_version_policy + "\n", encoding="utf-8")
    with pytest.raises(
        ValueError, match="treatment-version policy manifest byte mismatch"
    ):
        generate_report_bundle(
            benchmark_path,
            output_directory=tmp_path / "stale_version_policy_reports",
            policy_path=policy_path,
            descriptive_path=descriptive_path,
            hte_summary_path=hte_summary_path,
            hte_calibration_path=hte_calibration_path,
            hte_stability_path=hte_stability_path,
            nyc_full_validation_path=nyc_validation_path,
            nyc_full_manifest_path=nyc_manifest_path,
            treatment_version_policy_path=version_policy_path,
            treatment_version_policy_manifest_path=version_policy_manifest_path,
            target_estimand="market_total_effect",
        )
    version_policy_path.write_text(original_version_policy, encoding="utf-8")

    invalid_hte = json.loads(hte_summary_path.read_text(encoding="utf-8"))
    invalid_hte["interference"] = 0.2
    hte_summary_path.write_text(json.dumps(invalid_hte), encoding="utf-8")
    with pytest.raises(ValueError, match="interference and persistence disabled"):
        generate_report_bundle(
            benchmark_path,
            output_directory=tmp_path / "unsafe_reports",
            policy_path=policy_path,
            descriptive_path=descriptive_path,
            hte_summary_path=hte_summary_path,
            hte_calibration_path=hte_calibration_path,
            hte_stability_path=hte_stability_path,
            nyc_full_validation_path=nyc_validation_path,
            nyc_full_manifest_path=nyc_manifest_path,
            treatment_version_policy_path=version_policy_path,
            treatment_version_policy_manifest_path=version_policy_manifest_path,
            target_estimand="market_total_effect",
        )


def test_report_bundle_withholds_recommendation_if_scenario_is_unidentified(
    tmp_path: Path,
) -> None:
    benchmark_path = tmp_path / "benchmark.csv"
    pd.DataFrame(
        {
            "scenario": ["none", "spillover"],
            "declared_scenario_set": ['["none", "spillover"]'] * 2,
            "declared_scenario_count": [2, 2],
            "design": ["geo_cluster", "geo_cluster"],
            "estimator": ["cluster_robust", "cluster_robust"],
            "target_estimand": ["market_total_effect"] * 2,
            "identified": [True, False],
            "inference_valid": [True, True],
            "fit_complete": [True, True],
            "applicable": [True, True],
            "attempted_fits": [10, 10],
            "successful_fits": [10, 10],
            "rmse": [0.2, 0.3],
            "coverage": [0.95, 0.95],
            "power": [0.8, 0.8],
            "bias": [0.1, float("nan")],
            "evidence_type": ["semi_synthetic_causal_monte_carlo"] * 2,
        }
    ).to_csv(benchmark_path, index=False)

    paths = generate_report_bundle(
        benchmark_path,
        output_directory=tmp_path / "reports",
    )

    executive = paths["executive"].read_text(encoding="utf-8")
    technical = paths["technical"].read_text(encoding="utf-8")
    assert "No robust design recommendation is issued" in executive
    assert "no robust rollout recommendation" in executive
    assert "Verified NYC full-month artifacts were not supplied" in technical
    assert "has not been verified below" not in technical


def test_report_bundle_validates_six_new_evidence_layers_and_fails_closed(
    tmp_path: Path,
) -> None:
    benchmark_path = tmp_path / "benchmark.csv"
    pd.DataFrame(
        {
            "scenario": ["none", "spillover"],
            "declared_scenario_set": ['["none", "spillover"]'] * 2,
            "declared_scenario_count": [2, 2],
            "design": ["geo_cluster", "geo_cluster"],
            "estimator": ["cluster_robust", "cluster_robust"],
            "target_estimand": ["market_total_effect"] * 2,
            "identified": [True, True],
            "inference_valid": [True, True],
            "fit_complete": [True, True],
            "applicable": [True, True],
            "attempted_fits": [10, 10],
            "successful_fits": [10, 10],
            "rmse": [0.2, 0.3],
            "coverage": [0.95, 0.90],
            "power": [0.8, 0.75],
            "bias": [0.01, 0.02],
            "evidence_type": ["semi_synthetic_causal_monte_carlo"] * 2,
        }
    ).to_csv(benchmark_path, index=False)
    manifests = _write_six_new_evidence_manifests(tmp_path)
    report_arguments = {
        "nyc_benchmark_manifest_path": manifests["nyc"],
        "nyc_graph_benchmark_manifest_path": manifests["graph"],
        "equilibrium_manifest_path": manifests["equilibrium"],
        "nyc_weather_manifest_path": manifests["weather"],
        "nyc_events_manifest_path": manifests["events"],
        "nyc_income_manifest_path": manifests["income"],
    }

    paths = generate_report_bundle(
        benchmark_path,
        output_directory=tmp_path / "reports",
        **report_arguments,
    )

    technical = paths["technical"].read_text(encoding="utf-8")
    executive = paths["executive"].read_text(encoding="utf-8")
    appendix = paths["appendix"].read_text(encoding="utf-8")
    for body in (technical, executive, appendix):
        assert "NYC-informed known-truth" in body
        assert "NYC OD-graph" in body or "NYC graph" in body
        assert "equilibrium" in body.lower()
        assert "NYC NOAA weather" in body
        assert "calendar" in body.lower() and "permitted-event" in body.lower()
        assert "neighborhood-income" in body.lower()
    assert "not a treatment effect estimated from NYC trips" in technical
    assert "not an NYC structural estimate" in technical
    assert "not a causal weather effect" in technical
    assert "all 0 weekend days" in technical
    assert "not rider or driver income" in technical
    assert "does not identify a causal income effect" in technical
    assert "dominant-nonresidential zones" in technical
    assert "it is not the primary result" in technical

    events_manifest = json.loads(manifests["events"].read_text(encoding="utf-8"))
    holiday_entry = next(
        entry
        for entry in events_manifest["inputs"]
        if entry["role"] == "official_holiday_snapshot"
    )
    holiday_path = next(
        parent / holiday_entry["path"]
        for parent in manifests["events"].parents
        if (parent / holiday_entry["path"]).is_file()
    )
    original_holiday = holiday_path.read_bytes()
    holiday_path.write_bytes(original_holiday + b"\n")
    with pytest.raises(ValueError, match="input manifest byte mismatch"):
        generate_report_bundle(
            benchmark_path,
            output_directory=tmp_path / "tampered_events_report",
            nyc_events_manifest_path=manifests["events"],
        )
    holiday_path.write_bytes(original_holiday)

    original_events_manifest = manifests["events"].read_bytes()
    unsafe_events = json.loads(original_events_manifest)
    unsafe_events["checks"][
        "zero_duration_source_intervals_retained_and_excluded"
    ] = False
    manifests["events"].write_text(json.dumps(unsafe_events), encoding="utf-8")
    with pytest.raises(ValueError, match="unsafe evidence schema"):
        generate_report_bundle(
            benchmark_path,
            output_directory=tmp_path / "unsafe_event_interval_report",
            nyc_events_manifest_path=manifests["events"],
        )
    manifests["events"].write_bytes(original_events_manifest)

    events_payload = json.loads(original_events_manifest)
    events_summary_entry = next(
        entry for entry in events_payload["files"] if entry["role"] == "descriptive_summary"
    )
    events_summary_path = next(
        parent / events_summary_entry["path"]
        for parent in manifests["events"].parents
        if (parent / events_summary_entry["path"]).is_file()
    )
    original_events_summary = events_summary_path.read_bytes()
    unsafe_events_summary = json.loads(original_events_summary)
    unsafe_events_summary["coverage"][
        "zero_duration_interval_rows_retained_but_not_expanded"
    ] += 1
    _rewrite_bundle_json_role(
        manifests["events"], "descriptive_summary", unsafe_events_summary
    )
    with pytest.raises(ValueError, match="coverage is inconsistent"):
        generate_report_bundle(
            benchmark_path,
            output_directory=tmp_path / "unsafe_event_count_report",
            nyc_events_manifest_path=manifests["events"],
        )
    events_summary_path.write_bytes(original_events_summary)
    manifests["events"].write_bytes(original_events_manifest)

    original_income_manifest = manifests["income"].read_bytes()
    unsafe_income = json.loads(original_income_manifest)
    unsafe_income["causal_claim"] = True
    manifests["income"].write_text(json.dumps(unsafe_income), encoding="utf-8")
    with pytest.raises(ValueError, match="unsafe evidence schema"):
        generate_report_bundle(
            benchmark_path,
            output_directory=tmp_path / "unsafe_income_report",
            nyc_income_manifest_path=manifests["income"],
        )
    manifests["income"].write_bytes(original_income_manifest)

    unsafe_income = json.loads(original_income_manifest)
    unsafe_income["checks"]["dominant_nonresidential_primary_unclassified"] = False
    manifests["income"].write_text(json.dumps(unsafe_income), encoding="utf-8")
    with pytest.raises(ValueError, match="unsafe evidence schema"):
        generate_report_bundle(
            benchmark_path,
            output_directory=tmp_path / "unsafe_income_classification_report",
            nyc_income_manifest_path=manifests["income"],
        )
    manifests["income"].write_bytes(original_income_manifest)

    income_payload = json.loads(original_income_manifest)
    income_summary_entry = next(
        entry
        for entry in income_payload["files"]
        if entry["role"] == "income_association_summary"
    )
    income_summary_path = next(
        parent / income_summary_entry["path"]
        for parent in manifests["income"].parents
        if (parent / income_summary_entry["path"]).is_file()
    )
    original_income_summary = income_summary_path.read_bytes()
    unsafe_income_summary = json.loads(original_income_summary)
    unsafe_income_summary["classification_uncertainty"][
        "zone_level_margin_of_error_propagated"
    ] = True
    _rewrite_bundle_json_role(
        manifests["income"], "income_association_summary", unsafe_income_summary
    )
    with pytest.raises(ValueError, match="violates its ecological scope"):
        generate_report_bundle(
            benchmark_path,
            output_directory=tmp_path / "unsafe_income_uncertainty_report",
            nyc_income_manifest_path=manifests["income"],
        )
    income_summary_path.write_bytes(original_income_summary)
    manifests["income"].write_bytes(original_income_manifest)

    unsafe_income_summary = json.loads(original_income_summary)
    unsafe_income_summary["sensitivity"]["all_zone_area_allocation"][
        "primary_result"
    ] = True
    _rewrite_bundle_json_role(
        manifests["income"], "income_association_summary", unsafe_income_summary
    )
    with pytest.raises(ValueError, match="sensitivity arithmetic is inconsistent"):
        generate_report_bundle(
            benchmark_path,
            output_directory=tmp_path / "unsafe_income_sensitivity_report",
            nyc_income_manifest_path=manifests["income"],
        )
    income_summary_path.write_bytes(original_income_summary)
    manifests["income"].write_bytes(original_income_manifest)

    with pytest.raises(FileNotFoundError, match="manifest is required"):
        generate_report_bundle(
            benchmark_path,
            output_directory=tmp_path / "partial_events_report",
            nyc_events_manifest_path=tmp_path / "missing-events-manifest.json",
        )

    nyc_manifest = json.loads(manifests["nyc"].read_text(encoding="utf-8"))
    nyc_summary_entry = next(
        entry for entry in nyc_manifest["files"] if entry["role"] == "summary"
    )
    nyc_summary_path = manifests["nyc"].parent / nyc_summary_entry["path"]
    original_nyc_summary = nyc_summary_path.read_bytes()
    nyc_summary_path.write_bytes(original_nyc_summary + b"\n")
    with pytest.raises(ValueError, match="manifest byte mismatch"):
        generate_report_bundle(
            benchmark_path,
            output_directory=tmp_path / "tampered_nyc_report",
            nyc_benchmark_manifest_path=manifests["nyc"],
        )
    nyc_summary_path.write_bytes(original_nyc_summary)

    graph_manifest = json.loads(manifests["graph"].read_text(encoding="utf-8"))
    mapping_entry = next(
        entry
        for entry in graph_manifest["inputs"]
        if entry["role"] == "exposure_mapping"
    )
    mapping_path = next(
        parent / mapping_entry["path"]
        for parent in manifests["graph"].parents
        if (parent / mapping_entry["path"]).is_file()
    )
    original_mapping = mapping_path.read_bytes()
    mapping_path.write_bytes(original_mapping + b"\n")
    with pytest.raises(ValueError, match="input manifest byte mismatch"):
        generate_report_bundle(
            benchmark_path,
            output_directory=tmp_path / "tampered_graph_report",
            nyc_graph_benchmark_manifest_path=manifests["graph"],
        )
    mapping_path.write_bytes(original_mapping)

    original_weather_manifest = manifests["weather"].read_bytes()
    unsafe_weather = json.loads(original_weather_manifest)
    unsafe_weather["causal_claim"] = True
    manifests["weather"].write_text(json.dumps(unsafe_weather), encoding="utf-8")
    with pytest.raises(ValueError, match="manifest checks did not all pass"):
        generate_report_bundle(
            benchmark_path,
            output_directory=tmp_path / "unsafe_weather_report",
            nyc_weather_manifest_path=manifests["weather"],
        )
    manifests["weather"].write_bytes(original_weather_manifest)

    original_equilibrium_manifest = manifests["equilibrium"].read_bytes()
    unsafe_equilibrium = json.loads(original_equilibrium_manifest)
    unsafe_equilibrium["is_nyc_structural_estimate"] = True
    manifests["equilibrium"].write_text(
        json.dumps(unsafe_equilibrium), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="manifest metadata is incompatible"):
        generate_report_bundle(
            benchmark_path,
            output_directory=tmp_path / "unsafe_equilibrium_report",
            equilibrium_manifest_path=manifests["equilibrium"],
        )
    manifests["equilibrium"].write_bytes(original_equilibrium_manifest)
