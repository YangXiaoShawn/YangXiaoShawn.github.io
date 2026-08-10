"""Command-line entry points for the reproducible Causal Marketplace Lab workflow."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np
import pandas as pd
import yaml

from casuallab.analysis import write_descriptive_artifacts
from casuallab.benchmark import BenchmarkConfig
from casuallab.calibration import calibrate_simulation, write_calibration
from casuallab.config import DesignConfig, DesignName, SimulationConfig, load_simulation_config
from casuallab.data import (
    download_sample,
    load_data_config,
    nyc_hvfhv_urls,
    read_partitioned_parquet,
    run_data_pipeline,
    sha256_file,
)
from casuallab.equilibrium import (
    EquilibriumConfig,
    run_equilibrium_benchmark,
    write_equilibrium_artifacts,
)
from casuallab.generated_reports import generate_report_bundle
from casuallab.heterogeneity import cross_fitted_s_learner, subgroup_effect_summary
from casuallab.interference_benchmark import (
    InterferenceBenchmarkConfig,
    InterferenceBenchmarkResult,
    run_interference_benchmark,
)
from casuallab.marketplace_benchmark import run_marketplace_benchmark
from casuallab.nyc_benchmark import (
    NYCBenchmarkConfig,
    run_nyc_informed_marketplace_benchmark,
    write_nyc_benchmark_artifacts,
)
from casuallab.nyc_calibration import write_nyc_calibration_bundle
from casuallab.nyc_events import (
    download_nyc_permitted_events_snapshot,
    write_nyc_events_bundle,
)
from casuallab.nyc_full_analysis import write_nyc_full_analysis
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
from casuallab.nyc_weather import (
    download_noaa_daily_weather,
    write_nyc_weather_bundle,
)
from casuallab.simulator import SimulationResult, simulate_market

_REPRODUCTION_PACKAGES = (
    "duckdb",
    "numpy",
    "pandas",
    "polars",
    "pyarrow",
    "pyproj",
    "pyshp",
    "PyYAML",
    "scikit-learn",
    "scipy",
    "shapely",
    "statsmodels",
    "streamlit",
)


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (np.integer, np.floating)):
        value = value.item()
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def _write_json(payload: Mapping[str, Any], path: str | Path) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(_json_safe(payload), indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return destination


def _artifact_manifest(
    files: Sequence[str | Path],
    destination: str | Path,
    *,
    metadata: Mapping[str, Any],
    root: str | Path | None = None,
) -> Path:
    target = Path(destination)
    project_root = Path(__file__).resolve().parents[2]
    if root is not None:
        manifest_root = Path(root).resolve()
    else:
        try:
            target.resolve().relative_to(project_root)
            manifest_root = project_root
        except ValueError:
            manifest_root = target.parent.resolve()
    entries: list[dict[str, Any]] = []
    for raw_path in sorted({Path(path).resolve() for path in files}):
        if not raw_path.is_file():
            raise FileNotFoundError(raw_path)
        try:
            rendered = str(raw_path.relative_to(manifest_root))
        except ValueError as exc:
            if root is not None:
                raise ValueError(
                    f"manifest input is outside the declared root: {raw_path}"
                ) from exc
            rendered = str(raw_path)
        entries.append(
            {
                "path": rendered,
                "bytes": raw_path.stat().st_size,
                "sha256": sha256_file(raw_path),
            }
        )
    return _write_json(
        {
            "generated_at_utc": datetime.now(UTC).isoformat(),
            "files": entries,
            "metadata": metadata,
        },
        target,
    )


def _source_tree_sha256(project_root: Path) -> str:
    digest = hashlib.sha256()
    candidates = [
        *project_root.joinpath("src").rglob("*.py"),
        *project_root.joinpath("configs").rglob("*.yaml"),
        project_root / "pyproject.toml",
        project_root / "constraints.txt",
        project_root / "Makefile",
    ]
    for path in sorted({item for item in candidates if item.is_file()}):
        digest.update(str(path.relative_to(project_root)).encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _runtime_environment() -> dict[str, Any]:
    packages: dict[str, str | None] = {}
    for package in _REPRODUCTION_PACKAGES:
        try:
            packages[package] = version(package)
        except PackageNotFoundError:
            packages[package] = None
    return {
        "python": sys.version.split()[0],
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "packages": packages,
    }


def write_simulation_outputs(
    result: SimulationResult,
    output_directory: str | Path,
) -> dict[str, Path]:
    """Persist a simulation without serializing unavailable estimands as JSON NaN."""

    directory = Path(output_directory)
    directory.mkdir(parents=True, exist_ok=True)
    panel_path = directory / "simulated_panel.parquet"
    assignment_path = directory / "assignment.csv"
    truth_path = directory / "ground_truth_unit_effects.parquet"
    metadata_path = directory / "simulation_metadata.json"
    result.panel.to_parquet(panel_path, index=False)
    result.assignment.to_csv(assignment_path, index=False)
    result.ground_truth.unit_effects.to_parquet(truth_path, index=False)
    _write_json(dict(result.metadata), metadata_path)
    manifest_path = _artifact_manifest(
        [panel_path, assignment_path, truth_path, metadata_path],
        directory / "manifest.json",
        metadata={
            "evidence_type": "semi_synthetic_known_ground_truth",
            "simulation_seed": result.metadata["simulation_seed"],
            "assignment_seed": result.metadata["assignment_seed"],
            "target_population_id": result.metadata["target_population_id"],
        },
    )
    return {
        "panel": panel_path,
        "assignment": assignment_path,
        "truth": truth_path,
        "metadata": metadata_path,
        "manifest": manifest_path,
    }


def write_marketplace_benchmark_outputs(
    records: pd.DataFrame,
    summary: pd.DataFrame,
    failures: pd.DataFrame,
    fit_ledger: pd.DataFrame,
    output_directory: str | Path,
    *,
    benchmark_config: BenchmarkConfig,
    benchmark_config_path: str | Path,
    simulation_config: SimulationConfig,
    simulation_config_path: str | Path,
    additional_input_paths: Sequence[str | Path] = (),
) -> dict[str, Path]:
    directory = Path(output_directory)
    directory.mkdir(parents=True, exist_ok=True)
    records_path = directory / "monte_carlo_records.csv"
    summary_path = directory / "benchmark_results.csv"
    failures_path = directory / "benchmark_failures.csv"
    fit_ledger_path = directory / "benchmark_fit_ledger.csv"
    records.to_csv(records_path, index=False)
    summary.to_csv(summary_path, index=False)
    failures.to_csv(failures_path, index=False)
    fit_ledger.to_csv(fit_ledger_path, index=False)
    manifest_path = _artifact_manifest(
        [
            records_path,
            summary_path,
            failures_path,
            fit_ledger_path,
            benchmark_config_path,
            simulation_config_path,
            *additional_input_paths,
        ],
        directory / "manifest.json",
        metadata={
            "evidence_type": "semi_synthetic_causal_monte_carlo",
            "benchmark_config": {
                "replications": benchmark_config.replications,
                "seed": benchmark_config.seed,
                "confidence_level": benchmark_config.confidence_level,
                "designs": list(benchmark_config.designs),
                "estimators": list(benchmark_config.estimators),
                "target_estimand": benchmark_config.target_estimand,
            },
            "base_simulation_config_before_benchmark_overrides": (
                simulation_config.to_dict()
            ),
            "effective_scenario_plan": summary[
                [
                    column
                    for column in (
                        "scenario",
                        "declared_scenario_set",
                        "declared_scenario_count",
                        "varied_dimension",
                        "scenario_role",
                        "spillover_strength",
                        "persistence",
                        "treatment_duration",
                        "washout_periods",
                        "treatment_saturation",
                        "treatment_probability",
                        "configured_geo_clusters",
                        "cluster_size",
                        "budget",
                        "budget_scope",
                        "shared_budget_coupling",
                        "budget_binding_rate",
                        "treatment_version",
                        "n_zones",
                        "n_periods",
                    )
                    if column in summary
                ]
            ]
            .drop_duplicates()
            .to_dict(orient="records"),
        },
    )
    return {
        "records": records_path,
        "summary": summary_path,
        "failures": failures_path,
        "fit_ledger": fit_ledger_path,
        "manifest": manifest_path,
    }


def write_interference_benchmark_outputs(
    result: InterferenceBenchmarkResult,
    output_directory: str | Path,
) -> dict[str, Path]:
    """Persist the known-truth mapped-exposure benchmark and its audit ledger."""

    directory = Path(output_directory)
    directory.mkdir(parents=True, exist_ok=True)
    records_path = directory / "interference_records.csv"
    summary_path = directory / "interference_summary.csv"
    failures_path = directory / "interference_failures.csv"
    fit_ledger_path = directory / "interference_fit_ledger.csv"
    metadata_path = directory / "interference_metadata.json"
    result.records.to_csv(records_path, index=False)
    result.summary.to_csv(summary_path, index=False)
    result.failures.to_csv(failures_path, index=False)
    result.fit_ledger.to_csv(fit_ledger_path, index=False)
    _write_json(dict(result.metadata), metadata_path)
    manifest_path = _artifact_manifest(
        [records_path, summary_path, failures_path, fit_ledger_path, metadata_path],
        directory / "interference_manifest.json",
        metadata={
            "evidence_type": result.metadata["evidence_type"],
            "benchmark_config": result.metadata["config"],
            "known_estimands": result.metadata["known_estimands"],
            "controlled_exposure_not_market_total": True,
        },
    )
    return {
        "records": records_path,
        "summary": summary_path,
        "failures": failures_path,
        "fit_ledger": fit_ledger_path,
        "metadata": metadata_path,
        "manifest": manifest_path,
    }


def write_nyc_simulation_anchor_output(
    anchor: Mapping[str, Any],
    output_directory: str | Path,
    *,
    calibration_path: str | Path,
    calibration_manifest_path: str | Path,
    simulation_config_path: str | Path,
    project_root: str | Path | None = None,
) -> dict[str, Path]:
    """Persist one validated, explicitly noncausal NYC simulation anchor."""

    directory = Path(output_directory)
    directory.mkdir(parents=True, exist_ok=True)
    anchor_path = _write_json(anchor, directory / "nyc_simulation_anchor.json")
    manifest_path = _artifact_manifest(
        [
            anchor_path,
            calibration_path,
            calibration_manifest_path,
            simulation_config_path,
        ],
        directory / "manifest.json",
        metadata={
            "evidence_label": anchor["evidence_label"],
            "causal_claim": anchor["causal_claim"],
            "status": anchor["status"],
            "calibration_sha256": sha256_file(calibration_path),
            "calibration_manifest_sha256": sha256_file(calibration_manifest_path),
            "simulation_config_sha256": sha256_file(simulation_config_path),
            "source_data_manifest_sha256": anchor["integrity"][
                "source_data_manifest_sha256"
            ],
        },
        root=project_root,
    )
    return {"anchor": anchor_path, "manifest": manifest_path}


def _load_policy_yaml(path: str | Path) -> tuple[dict[str, Any], int, int]:
    source = Path(path)
    payload = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, Mapping):
        raise ValueError("policy configuration must be a mapping")
    section = payload.get("policy", payload)
    if not isinstance(section, Mapping):
        raise ValueError("policy configuration section must be a mapping")
    values = dict(section)
    n_train = int(values.pop("n_train", 12))
    n_holdout = int(values.pop("n_holdout", 8))
    return values, n_train, n_holdout


def _write_hte_artifacts(
    simulation: SimulationConfig,
    output_directory: str | Path,
) -> dict[str, Path]:
    # A geo-time experiment supplies binary variation across zones and periods. The
    # benchmark removes interference/carryover so the conditional assignment
    # contrast matches the simulator's controlled-zone truth, and entire geographic
    # randomization clusters are held out in every nuisance fold.
    n_zones = max(8, simulation.n_zones)
    design = DesignConfig(
        name=DesignName.GEO_TIME,
        treatment_probability=0.5,
        treatment_saturation=1.0,
        n_clusters=4,
        cluster_size=max(1, n_zones // 4),
        treatment_duration=max(4, simulation.design.treatment_duration),
        washout_periods=0,
        budget=None,
        seed=simulation.seed + 71,
    )
    hte_config = replace(
        simulation,
        n_zones=n_zones,
        budget=None,
        spillover_strength=0.0,
        persistence=0.0,
        rider_substitution=0.0,
        driver_mobility=0.0,
        design=design,
    )
    generated = simulate_market(hte_config)
    hte = cross_fitted_s_learner(
        generated.panel,
        group="cluster_id",
        folds=4,
        trees=80,
        seed=simulation.seed + 72,
        evidence_type=(
            "model_based_controlled_zone_heterogeneity_conditional_on_randomized_design"
        ),
    )
    predictions = hte.predictions.copy()
    predictions["known_controlled_zone_truth"] = generated.panel[
        "true_controlled_zone_direct_effect"
    ].to_numpy(dtype=float)
    predictions["prediction_error"] = (
        predictions["estimated_cate"] - predictions["known_controlled_zone_truth"]
    )
    known_truth = predictions["known_controlled_zone_truth"].to_numpy(dtype=float)
    estimated_cate = predictions["estimated_cate"].to_numpy(dtype=float)
    oracle_constant = float(np.mean(known_truth))
    constant_effect_baseline_rmse = float(
        np.sqrt(np.mean((known_truth - oracle_constant) ** 2))
    )
    hte_rmse = float(np.sqrt(np.mean(predictions["prediction_error"] ** 2)))
    predicted_truth_correlation = float(
        pd.Series(estimated_cate).corr(pd.Series(known_truth), method="pearson")
    )
    predicted_truth_rank_correlation = float(
        pd.Series(estimated_cate).corr(pd.Series(known_truth), method="spearman")
    )
    subgroup = subgroup_effect_summary(
        generated.panel,
        predictions["estimated_cate"],
        modifier="market_tightness",
    )
    calibration_frame = predictions[
        ["estimated_cate", "known_controlled_zone_truth", "prediction_error"]
    ].copy()
    calibration_frame["score_bin"] = pd.qcut(
        calibration_frame["estimated_cate"],
        q=5,
        duplicates="drop",
    ).astype(str)
    calibration = (
        calibration_frame.groupby("score_bin", observed=True)
        .agg(
            mean_predicted_cate=("estimated_cate", "mean"),
            mean_known_truth=("known_controlled_zone_truth", "mean"),
            mean_error=("prediction_error", "mean"),
            rmse=("prediction_error", lambda value: float(np.sqrt(np.mean(value**2)))),
            rows=("prediction_error", "size"),
        )
        .reset_index()
    )
    subgroup_recovery_frame = pd.DataFrame(
        {
            "market_tightness": generated.panel["market_tightness"].to_numpy(dtype=float),
            "estimated_cate": predictions["estimated_cate"],
            "known_truth": predictions["known_controlled_zone_truth"],
            "prediction_error": predictions["prediction_error"],
        }
    )
    subgroup_recovery_frame["market_tightness_bin"] = pd.qcut(
        subgroup_recovery_frame["market_tightness"],
        q=4,
        duplicates="drop",
    ).astype(str)
    subgroup_recovery = (
        subgroup_recovery_frame.groupby("market_tightness_bin", observed=True)
        .agg(
            mean_market_tightness=("market_tightness", "mean"),
            mean_predicted_cate=("estimated_cate", "mean"),
            mean_known_truth=("known_truth", "mean"),
            mean_error=("prediction_error", "mean"),
            rows=("prediction_error", "size"),
        )
        .reset_index()
    )
    fold_stability = (
        predictions.groupby("crossfit_fold", observed=True)
        .agg(
            mean_predicted_cate=("estimated_cate", "mean"),
            mean_known_truth=("known_controlled_zone_truth", "mean"),
            mean_error=("prediction_error", "mean"),
            rmse=("prediction_error", lambda value: float(np.sqrt(np.mean(value**2)))),
            rows=("prediction_error", "size"),
        )
        .reset_index()
    )
    directory = Path(output_directory)
    directory.mkdir(parents=True, exist_ok=True)
    predictions_path = directory / "hte_predictions.csv"
    importance_path = directory / "hte_feature_importance.csv"
    subgroup_path = directory / "hte_subgroups.csv"
    calibration_path = directory / "hte_calibration_by_score.csv"
    subgroup_recovery_path = directory / "hte_subgroup_recovery.csv"
    fold_stability_path = directory / "hte_fold_stability.csv"
    calibration_chart_path = directory / "hte_calibration_chart.html"
    summary_path = directory / "hte_recovery.json"
    predictions.to_csv(predictions_path, index=False)
    hte.feature_importance.to_csv(importance_path, index=False)
    subgroup.to_csv(subgroup_path, index=False)
    calibration.to_csv(calibration_path, index=False)
    subgroup_recovery.to_csv(subgroup_recovery_path, index=False)
    fold_stability.to_csv(fold_stability_path, index=False)
    import altair as alt  # noqa: PLC0415

    calibration_chart = (
        alt.Chart(calibration)
        .mark_line(point=True)
        .encode(
            x=alt.X("mean_known_truth:Q", title="Mean known controlled-zone truth"),
            y=alt.Y("mean_predicted_cate:Q", title="Mean cross-fitted predicted CATE"),
            tooltip=[
                "score_bin:N",
                "rows:Q",
                "mean_known_truth:Q",
                "mean_predicted_cate:Q",
                "mean_error:Q",
            ],
        )
        .properties(title="CATE calibration by held-out score bin")
    )
    calibration_chart.save(calibration_chart_path)
    _write_json(
        {
            "evidence_type": "semi_synthetic_hte_known_truth_recovery",
            "target_estimand": "controlled_zone_direct_effect",
            "crossfit_group": "geographic_randomization_cluster",
            "interference": 0.0,
            "persistence": 0.0,
            "rows": len(predictions),
            "bias": float(predictions["prediction_error"].mean()),
            "rmse": hte_rmse,
            "known_truth_sd": float(np.std(known_truth, ddof=0)),
            "oracle_constant_effect_rmse": constant_effect_baseline_rmse,
            "predicted_truth_correlation": predicted_truth_correlation,
            "predicted_truth_rank_correlation": predicted_truth_rank_correlation,
            "hte_beats_oracle_constant": hte_rmse < constant_effect_baseline_rmse,
            "recovery_gate": "rmse_below_oracle_constant_effect_rmse",
            "fold_mean_cate_sd": float(
                fold_stability["mean_predicted_cate"].std(ddof=1)
            ),
            "fold_bias_sd": float(fold_stability["mean_error"].std(ddof=1)),
            "calibration_bins": len(calibration),
            "simulation_seed": hte_config.seed,
            "assignment_seed": design.seed,
        },
        summary_path,
    )
    manifest_path = _artifact_manifest(
        [
            predictions_path,
            importance_path,
            subgroup_path,
            calibration_path,
            subgroup_recovery_path,
            fold_stability_path,
            calibration_chart_path,
            summary_path,
        ],
        directory / "manifest.json",
        metadata={
            "target_estimand": "controlled_zone_direct_effect",
            "evidence_type": "semi_synthetic_hte_known_truth_recovery",
            "simulation_config": hte_config.to_dict(),
        },
    )
    return {
        "predictions": predictions_path,
        "importance": importance_path,
        "subgroups": subgroup_path,
        "calibration": calibration_path,
        "subgroup_recovery": subgroup_recovery_path,
        "fold_stability": fold_stability_path,
        "calibration_chart": calibration_chart_path,
        "summary": summary_path,
        "manifest": manifest_path,
    }


def _run_download_sample(args: argparse.Namespace) -> list[Path]:
    config = load_data_config(args.config)
    if config.mode != "sample":
        raise ValueError("download-sample requires a data config with mode: sample")
    return [download_sample(config, refresh=args.refresh)]


def _run_build_panel(args: argparse.Namespace) -> list[Path]:
    config = load_data_config(args.config)
    if config.mode == "full" and not getattr(args, "allow_full_download", False):
        raise ValueError(
            "full-data ingestion requires explicit --allow-full-download; "
            "sample_rows does not bound full mode"
        )
    artifacts = run_data_pipeline(config, refresh=args.refresh)
    return [
        *artifacts.raw_files,
        *artifacts.clean_files,
        *artifacts.panel_files,
        *artifacts.od_flow_files,
        artifacts.diagnostics_path,
        artifacts.manifest_path,
    ]


def _run_validate_nyc_full(args: argparse.Namespace) -> list[Path]:
    """Build and validate one explicitly authorized NYC full-month extract."""

    config = load_data_config(args.config)
    if config.source != "nyc_hvfhv" or config.mode != "full":
        raise ValueError("validate-nyc-full requires a NYC mode: full config")
    if not getattr(args, "allow_full_download", False):
        raise ValueError("validate-nyc-full requires explicit --allow-full-download")
    raw_paths = tuple(config.raw_dir / Path(url).name for url in nyc_hvfhv_urls(config))
    raw_cached = all(path.is_file() for path in raw_paths)
    started = perf_counter()
    data_artifacts = run_data_pipeline(config, refresh=args.refresh)
    analysis = write_nyc_full_analysis(
        config,
        args.output_dir,
        started_at_monotonic=started,
        raw_cached=raw_cached,
        command=(
            ".venv/bin/python -m casuallab validate-nyc-full "
            f"--config {args.config} --allow-full-download"
        ),
    )
    calibration = write_nyc_calibration_bundle(
        config,
        Path(args.output_dir) / "calibration_network",
    )
    return [
        *data_artifacts.raw_files,
        data_artifacts.diagnostics_path,
        data_artifacts.manifest_path,
        *analysis.paths(),
        *calibration.paths(),
    ]


def _run_simulate(args: argparse.Namespace) -> list[Path]:
    config = load_simulation_config(args.config)
    outputs = write_simulation_outputs(simulate_market(config), args.output_dir)
    return list(outputs.values())


def _run_benchmark(args: argparse.Namespace) -> list[Path]:
    benchmark = BenchmarkConfig.from_yaml(args.config)
    simulation = load_simulation_config(args.simulation_config)
    result = run_marketplace_benchmark(benchmark, simulation)
    outputs = write_marketplace_benchmark_outputs(
        result.records,
        result.summary,
        result.failures,
        result.fit_ledger,
        args.output_dir,
        benchmark_config=benchmark,
        benchmark_config_path=args.config,
        simulation_config=simulation,
        simulation_config_path=args.simulation_config,
    )
    return list(outputs.values())


def _run_interference_benchmark(args: argparse.Namespace) -> list[Path]:
    config = InterferenceBenchmarkConfig(
        replications=args.replications,
        seed=args.seed,
    )
    outputs = write_interference_benchmark_outputs(
        run_interference_benchmark(config),
        args.output_dir,
    )
    return list(outputs.values())


def _run_nyc_simulation_anchor(args: argparse.Namespace) -> list[Path]:
    project_root = Path(__file__).resolve().parents[2]
    anchor = build_nyc_simulation_anchor(
        args.calibration,
        project_root=project_root,
        manifest_path=args.calibration_manifest,
        settings=NYCSimulationAnchorSettings(
            target_n_zones=args.n_zones,
            target_n_periods=args.n_periods,
            seed=args.seed,
        ),
        assumption_template=load_simulation_config(args.simulation_config),
    )
    outputs = write_nyc_simulation_anchor_output(
        anchor,
        args.output_dir,
        calibration_path=args.calibration,
        calibration_manifest_path=args.calibration_manifest,
        simulation_config_path=args.simulation_config,
        project_root=project_root,
    )
    return list(outputs.values())


def _run_nyc_weather(args: argparse.Namespace) -> list[Path]:
    """Validate the pinned NOAA response and join it to the full NYC panel."""

    project_root = Path(__file__).resolve().parents[2]
    raw_path = download_noaa_daily_weather(args.raw, refresh=args.refresh)
    artifacts = write_nyc_weather_bundle(
        raw_path,
        args.panel_dir,
        args.data_manifest,
        args.output_dir,
        project_root=project_root,
    )
    return list(artifacts.paths())


def _run_nyc_events(args: argparse.Namespace) -> list[Path]:
    """Validate cached official calendars and publish descriptive event evidence."""

    project_root = Path(__file__).resolve().parents[2]
    event_path = download_nyc_permitted_events_snapshot(
        args.events,
        refresh=args.refresh,
    )
    artifacts = write_nyc_events_bundle(
        args.holidays,
        event_path,
        args.panel_dir,
        args.data_manifest,
        args.output_dir,
        project_root=project_root,
    )
    return list(artifacts.paths())


def _run_nyc_income(args: argparse.Namespace) -> list[Path]:
    """Publish ecological, non-causal NYC high/low-income trip descriptions."""

    project_root = Path(__file__).resolve().parents[2]
    artifacts = write_nyc_income_bundle(
        args.taxi_zones,
        args.nta,
        args.tract_to_nta,
        args.acs_b19001,
        args.panel_dir,
        args.data_manifest,
        args.output_dir,
        project_root=project_root,
    )
    return list(artifacts.paths())


def _run_nyc_benchmark(args: argparse.Namespace) -> list[Path]:
    """Run the known-truth marketplace benchmark from the validated NYC anchor."""

    project_root = Path(__file__).resolve().parents[2]
    result = run_nyc_informed_marketplace_benchmark(
        args.anchor,
        args.anchor_manifest,
        config=NYCBenchmarkConfig(
            replications=args.replications,
            seed=args.seed,
            n_zones=args.n_zones,
            n_periods=args.n_periods,
        ),
        project_root=project_root,
    )
    outputs = write_nyc_benchmark_artifacts(
        result,
        args.output_dir,
        project_root=project_root,
    )
    return [path for key, path in outputs.items() if key != "output_directory"]


def _run_nyc_graph_benchmark(args: argparse.Namespace) -> list[Path]:
    """Run the known-truth interference benchmark on the validated NYC OD graph."""

    project_root = Path(__file__).resolve().parents[2]
    result = run_nyc_graph_benchmark(
        args.bundle,
        NYCGraphBenchmarkConfig(
            replications=args.replications,
            seed=args.seed,
            n_zones=args.n_zones,
            n_periods=args.n_periods,
        ),
    )
    outputs = write_nyc_graph_benchmark_artifacts(
        result,
        args.output_dir,
        project_root=project_root,
    )
    return [path for key, path in outputs.items() if key != "output_directory"]


def _run_equilibrium_benchmark(args: argparse.Namespace) -> list[Path]:
    """Solve and persist a transparent two-sided fixed-point benchmark."""

    project_root = Path(__file__).resolve().parents[2]
    result = run_equilibrium_benchmark(
        EquilibriumConfig(
            n_zones=args.n_zones,
            seed=args.seed,
            treatment_version=args.treatment_version,
            budget=args.budget,
        ),
        planned_treatment_intensity=args.treatment_intensity,
    )
    return list(
        write_equilibrium_artifacts(
            result,
            args.output_dir,
            project_root,
        ).paths()
    )


def _optional_nyc_full_evidence_paths(
    args: argparse.Namespace,
) -> tuple[Path | None, Path | None]:
    """Return a complete cached NYC evidence pair or preserve a partial pair to fail closed."""

    validation_value = getattr(args, "nyc_full_validation", None)
    manifest_value = getattr(args, "nyc_full_manifest", None)
    if not validation_value and not manifest_value:
        return None, None
    validation = Path(validation_value) if validation_value else None
    manifest = Path(manifest_value) if manifest_value else None
    if (
        validation is not None
        and manifest is not None
        and not validation.exists()
        and not manifest.exists()
    ):
        return None, None
    return validation, manifest


def _optional_treatment_version_policy_paths(
    args: argparse.Namespace,
) -> tuple[Path | None, Path | None]:
    summary_value = getattr(args, "treatment_version_policy", None)
    manifest_value = getattr(args, "treatment_version_policy_manifest", None)
    if not summary_value and not manifest_value:
        return None, None
    summary = Path(summary_value) if summary_value else None
    manifest = Path(manifest_value) if manifest_value else None
    if (
        summary is not None
        and manifest is not None
        and not summary.exists()
        and not manifest.exists()
    ):
        return None, None
    return summary, manifest


def _optional_interference_paths(
    args: argparse.Namespace,
) -> tuple[Path | None, Path | None]:
    summary_value = getattr(args, "interference_summary", None)
    manifest_value = getattr(args, "interference_manifest", None)
    if not summary_value and not manifest_value:
        return None, None
    summary = Path(summary_value) if summary_value else None
    manifest = Path(manifest_value) if manifest_value else None
    if (
        summary is not None
        and manifest is not None
        and not summary.exists()
        and not manifest.exists()
    ):
        return None, None
    return summary, manifest


def _optional_nyc_anchor_paths(
    args: argparse.Namespace,
) -> tuple[Path | None, Path | None]:
    anchor_value = getattr(args, "nyc_simulation_anchor", None)
    manifest_value = getattr(args, "nyc_simulation_anchor_manifest", None)
    if not anchor_value and not manifest_value:
        return None, None
    anchor = Path(anchor_value) if anchor_value else None
    manifest = Path(manifest_value) if manifest_value else None
    if (
        anchor is not None
        and manifest is not None
        and not anchor.exists()
        and not manifest.exists()
    ):
        return None, None
    return anchor, manifest


def _optional_manifest_path(args: argparse.Namespace, field: str) -> Path | None:
    """Return an optional generated manifest, treating an absent default as unavailable."""

    value = getattr(args, field, None)
    if not value:
        return None
    path = Path(value)
    return path if path.is_file() else None


def _offline_enrichment_ready(
    label: str,
    *,
    nyc_dependencies: Sequence[Path],
    external_sources: Sequence[Path],
) -> bool:
    """Gate an optional enrichment without silently accepting partial cached state."""

    nyc_present = [path.exists() for path in nyc_dependencies]
    if not any(nyc_present):
        return False
    if not all(nyc_present):
        missing = [
            str(path)
            for path, present in zip(nyc_dependencies, nyc_present, strict=True)
            if not present
        ]
        raise ValueError(f"cached {label} requires complete NYC dependencies; missing {missing}")
    source_present = [path.is_file() for path in external_sources]
    if not any(source_present):
        return False
    if not all(source_present):
        missing = [
            str(path)
            for path, present in zip(external_sources, source_present, strict=True)
            if not present
        ]
        raise ValueError(f"cached {label} requires every pinned external source; missing {missing}")
    return True


def _run_report(args: argparse.Namespace) -> list[Path]:
    policy = Path(args.policy) if args.policy else None
    if policy is not None and not policy.is_file():
        policy = None
    nyc_validation, nyc_manifest = _optional_nyc_full_evidence_paths(args)
    version_policy, version_policy_manifest = _optional_treatment_version_policy_paths(
        args
    )
    interference_summary, interference_manifest = _optional_interference_paths(args)
    nyc_anchor, nyc_anchor_manifest = _optional_nyc_anchor_paths(args)
    nyc_benchmark_manifest = _optional_manifest_path(args, "nyc_benchmark_manifest")
    nyc_graph_manifest = _optional_manifest_path(args, "nyc_graph_benchmark_manifest")
    equilibrium_manifest = _optional_manifest_path(args, "equilibrium_manifest")
    nyc_weather_manifest = _optional_manifest_path(args, "nyc_weather_manifest")
    nyc_events_manifest = _optional_manifest_path(args, "nyc_events_manifest")
    nyc_income_manifest = _optional_manifest_path(args, "nyc_income_manifest")
    outputs = generate_report_bundle(
        args.benchmark,
        output_directory=args.output_dir,
        policy_path=policy,
        descriptive_path=args.descriptive,
        calibration_path=args.calibration,
        failures_path=args.failures,
        hte_summary_path=getattr(args, "hte_summary", None),
        hte_calibration_path=getattr(args, "hte_calibration", None),
        hte_stability_path=getattr(args, "hte_stability", None),
        nyc_full_validation_path=nyc_validation,
        nyc_full_manifest_path=nyc_manifest,
        treatment_version_policy_path=version_policy,
        treatment_version_policy_manifest_path=version_policy_manifest,
        interference_summary_path=interference_summary,
        interference_manifest_path=interference_manifest,
        nyc_simulation_anchor_path=nyc_anchor,
        nyc_simulation_anchor_manifest_path=nyc_anchor_manifest,
        nyc_benchmark_manifest_path=nyc_benchmark_manifest,
        nyc_graph_benchmark_manifest_path=nyc_graph_manifest,
        equilibrium_manifest_path=equilibrium_manifest,
        nyc_weather_manifest_path=nyc_weather_manifest,
        nyc_events_manifest_path=nyc_events_manifest,
        nyc_income_manifest_path=nyc_income_manifest,
        target_estimand=args.target_estimand,
    )
    return list(outputs.values())


def _run_reproduce_inner(args: argparse.Namespace) -> list[Path]:
    outputs: list[Path] = []
    project_root = Path(__file__).resolve().parents[2]
    data_artifacts = run_data_pipeline(args.config, refresh=args.refresh)
    outputs.extend(
        [
            *data_artifacts.raw_files,
            *data_artifacts.clean_files,
            *data_artifacts.panel_files,
            *data_artifacts.od_flow_files,
            data_artifacts.diagnostics_path,
            data_artifacts.manifest_path,
        ]
    )
    panel = read_partitioned_parquet(load_data_config(args.config).panel_dir / "zone_time")
    trips = read_partitioned_parquet(load_data_config(args.config).clean_dir / "trips")
    descriptive = write_descriptive_artifacts(
        panel,
        Path(args.output_root) / "reports/descriptive",
        trips=trips,
    )
    outputs.extend(descriptive.values())

    simulation_template = load_simulation_config(args.simulation_config)
    calibration = calibrate_simulation(panel, simulation_template)
    calibration_path = write_calibration(
        calibration,
        Path(args.output_root) / "reports/calibration.json",
    )
    outputs.append(calibration_path)
    nyc_anchor_outputs: dict[str, Path] = {}
    nyc_benchmark_outputs: dict[str, Path] = {}
    nyc_graph_outputs: dict[str, Path] = {}
    nyc_weather_outputs: dict[str, Path] = {}
    nyc_events_outputs: dict[str, Path] = {}
    nyc_income_outputs: dict[str, Path] = {}
    nyc_validation_value = getattr(args, "nyc_full_validation", None)
    nyc_artifact_root = (
        Path(nyc_validation_value).parent
        if nyc_validation_value
        else project_root / "artifacts/nyc_full"
    )
    nyc_calibration_path = nyc_artifact_root / "calibration_network/calibration.json"
    nyc_calibration_manifest = nyc_artifact_root / "calibration_network/manifest.json"
    if nyc_calibration_path.exists() != nyc_calibration_manifest.exists():
        raise ValueError("cached NYC calibration requires both calibration and manifest")
    if nyc_calibration_path.is_file() and nyc_calibration_manifest.is_file():
        nyc_anchor = build_nyc_simulation_anchor(
            nyc_calibration_path,
            project_root=project_root,
            manifest_path=nyc_calibration_manifest,
            settings=NYCSimulationAnchorSettings(
                target_n_zones=32,
                target_n_periods=168,
                seed=simulation_template.seed,
            ),
            assumption_template=simulation_template,
        )
        nyc_anchor_outputs = write_nyc_simulation_anchor_output(
            nyc_anchor,
            Path(args.output_root) / "nyc_full/simulation_anchor",
            calibration_path=nyc_calibration_path,
            calibration_manifest_path=nyc_calibration_manifest,
            simulation_config_path=args.simulation_config,
            project_root=project_root,
        )
        outputs.extend(nyc_anchor_outputs.values())
        nyc_benchmark_outputs = write_nyc_benchmark_artifacts(
            run_nyc_informed_marketplace_benchmark(
                nyc_anchor_outputs["anchor"],
                nyc_anchor_outputs["manifest"],
                config=NYCBenchmarkConfig(),
                project_root=project_root,
            ),
            Path(args.output_root) / "benchmarks/nyc_informed",
            project_root=project_root,
        )
        outputs.extend(
            path
            for key, path in nyc_benchmark_outputs.items()
            if key != "output_directory"
        )

        nyc_graph_outputs = write_nyc_graph_benchmark_artifacts(
            run_nyc_graph_benchmark(
                nyc_calibration_path.parent,
                NYCGraphBenchmarkConfig(),
            ),
            Path(args.output_root) / "benchmarks/nyc_graph",
            project_root=project_root,
        )
        outputs.extend(
            path
            for key, path in nyc_graph_outputs.items()
            if key != "output_directory"
        )

        full_data_manifest = project_root / "data/nyc_full/manifest.json"
        full_panel_directory = project_root / "data/nyc_full/panel/zone_time"
        weather_raw = (
            project_root
            / "data/nyc_weather/raw/noaa_central_park_2024-01.csv"
        )
        weather_dependencies = (
            full_data_manifest,
            full_panel_directory,
            weather_raw,
        )
        if all(path.exists() for path in weather_dependencies):
            weather_artifacts = write_nyc_weather_bundle(
                weather_raw,
                full_panel_directory,
                full_data_manifest,
                Path(args.output_root) / "nyc_full/weather",
                project_root=project_root,
            )
            nyc_weather_outputs = {
                "normalized": weather_artifacts.normalized_weather_path,
                "daily": weather_artifacts.daily_panel_path,
                "hourly": weather_artifacts.hourly_contrast_path,
                "summary": weather_artifacts.summary_path,
                "manifest": weather_artifacts.manifest_path,
            }
            outputs.extend(nyc_weather_outputs.values())

    full_data_manifest = project_root / "data/nyc_full/manifest.json"
    full_panel_directory = project_root / "data/nyc_full/panel/zone_time"
    shared_nyc_dependencies = (full_data_manifest, full_panel_directory)
    income_sources = (
        project_root / "data/nyc_income/raw/taxi_zones.zip",
        project_root / "data/nyc_income/raw/nyc_nta2020.geojson",
        project_root / "data/nyc_income/raw/nyc_tract2020_to_nta2020.csv",
        project_root / "data/nyc_income/raw/acs_2022_5yr_b19001_nyc_tracts.dat",
    )
    if _offline_enrichment_ready(
        "NYC income enrichment",
        nyc_dependencies=shared_nyc_dependencies,
        external_sources=income_sources,
    ):
        income_artifacts = write_nyc_income_bundle(
            *income_sources,
            full_panel_directory,
            full_data_manifest,
            Path(args.output_root) / "nyc_full/income",
            project_root=project_root,
        )
        nyc_income_outputs = {
            "crosswalk": income_artifacts.crosswalk_path,
            "nta_income": income_artifacts.nta_income_path,
            "zone_income": income_artifacts.zone_income_path,
            "daily": income_artifacts.daily_path,
            "monthly": income_artifacts.monthly_path,
            "summary": income_artifacts.summary_path,
            "manifest": income_artifacts.manifest_path,
        }
        outputs.extend(nyc_income_outputs.values())

    event_sources = (
        project_root / "data/nyc_events/raw/official_holidays_2024-01.csv",
        project_root / "data/nyc_events/raw/nyc_permitted_events_overlap_2024-01.csv",
    )
    if _offline_enrichment_ready(
        "NYC calendar/event enrichment",
        nyc_dependencies=shared_nyc_dependencies,
        external_sources=event_sources,
    ):
        event_artifacts = write_nyc_events_bundle(
            *event_sources,
            full_panel_directory,
            full_data_manifest,
            Path(args.output_root) / "nyc_full/events",
            project_root=project_root,
        )
        nyc_events_outputs = {
            "calendar_daily": event_artifacts.calendar_daily_path,
            "normalized_events": event_artifacts.normalized_events_path,
            "event_type_daily": event_artifacts.event_type_daily_path,
            "daily": event_artifacts.daily_panel_path,
            "hourly": event_artifacts.hourly_contrast_path,
            "summary": event_artifacts.summary_path,
            "manifest": event_artifacts.manifest_path,
        }
        outputs.extend(nyc_events_outputs.values())
    outputs.extend(
        write_simulation_outputs(
            simulate_market(calibration.config),
            Path(args.output_root) / "simulation",
        ).values()
    )

    equilibrium_artifacts = write_equilibrium_artifacts(
        run_equilibrium_benchmark(EquilibriumConfig()),
        Path(args.output_root) / "benchmarks/equilibrium",
        project_root,
    )
    equilibrium_outputs = {
        "summary": equilibrium_artifacts.summary_path,
        "zone_effects": equilibrium_artifacts.zone_effects_path,
        "ledger": equilibrium_artifacts.ledger_path,
        "manifest": equilibrium_artifacts.manifest_path,
    }
    outputs.extend(equilibrium_outputs.values())

    benchmark = BenchmarkConfig.from_yaml(args.benchmark_config)
    benchmark_result = run_marketplace_benchmark(benchmark, calibration.config)
    benchmark_outputs = write_marketplace_benchmark_outputs(
        benchmark_result.records,
        benchmark_result.summary,
        benchmark_result.failures,
        benchmark_result.fit_ledger,
        Path(args.output_root) / "benchmarks",
        benchmark_config=benchmark,
        benchmark_config_path=args.benchmark_config,
        simulation_config=calibration.config,
        simulation_config_path=args.simulation_config,
        additional_input_paths=(calibration_path,),
    )
    outputs.extend(benchmark_outputs.values())
    interference_outputs = write_interference_benchmark_outputs(
        run_interference_benchmark(),
        Path(args.output_root) / "benchmarks",
    )
    outputs.extend(interference_outputs.values())
    hte_outputs = _write_hte_artifacts(
        calibration.config,
        Path(args.output_root) / "benchmarks/heterogeneity",
    )
    outputs.extend(hte_outputs.values())

    # Imported lazily so the core data/simulation commands remain usable even when
    # policy extras are being developed independently.
    from casuallab.marketplace_policy import (  # noqa: PLC0415
        MarketplacePolicyConfig,
        run_marketplace_policy_evaluation,
        run_treatment_version_policy_evaluation,
    )

    policy_values, n_train, n_holdout = _load_policy_yaml(args.policy_config)
    policy_config = MarketplacePolicyConfig.from_mapping(policy_values)
    policy_result = run_marketplace_policy_evaluation(
        calibration.config,
        policy_config,
        n_train_markets=n_train,
        n_holdout_markets=n_holdout,
    )
    policy_path = Path(args.output_root) / "benchmarks/policy_results.csv"
    policy_ledger_path = Path(args.output_root) / "benchmarks/policy_market_ledger.csv"
    policy_path.parent.mkdir(parents=True, exist_ok=True)
    policy_result.summary.to_csv(policy_path, index=False)
    policy_result.market_results.to_csv(policy_ledger_path, index=False)
    policy_manifest = _artifact_manifest(
        [policy_path, policy_ledger_path, args.policy_config, calibration_path],
        Path(args.output_root) / "benchmarks/policy_manifest.json",
        metadata={
            "evidence_type": "semi_synthetic_policy_holdout",
            "simulation_config": calibration.config.to_dict(),
            "policy_config": policy_values,
            "training_markets": n_train,
            "holdout_markets": n_holdout,
        },
    )
    outputs.extend([policy_path, policy_ledger_path, policy_manifest])

    version_policy_result = run_treatment_version_policy_evaluation(
        calibration.config,
        policy_config,
        n_train_markets=n_train,
        n_holdout_markets=n_holdout,
    )
    version_policy_path = (
        Path(args.output_root) / "benchmarks/treatment_version_policy_results.csv"
    )
    version_policy_ledger_path = (
        Path(args.output_root) / "benchmarks/treatment_version_policy_market_ledger.csv"
    )
    version_policy_result.summary.to_csv(version_policy_path, index=False)
    version_policy_result.market_results.to_csv(
        version_policy_ledger_path, index=False
    )
    treatment_versions = list(
        dict.fromkeys(version_policy_result.summary["treatment_version"].astype(str))
    )
    version_policy_manifest = _artifact_manifest(
        [
            version_policy_path,
            version_policy_ledger_path,
            args.policy_config,
            calibration_path,
        ],
        Path(args.output_root) / "benchmarks/treatment_version_policy_manifest.json",
        metadata={
            "evidence_type": "semi_synthetic_treatment_version_policy_sensitivity",
            "treatment_versions": treatment_versions,
            "version_pairing": (
                "common training/holdout market seeds across intervention versions"
            ),
            "simulation_config_before_treatment_version_overrides": (
                calibration.config.to_dict()
            ),
            "policy_config": policy_values,
            "training_markets": n_train,
            "holdout_markets": n_holdout,
        },
    )
    outputs.extend(
        [version_policy_path, version_policy_ledger_path, version_policy_manifest]
    )

    report_args = argparse.Namespace(
        benchmark=str(benchmark_outputs["summary"]),
        policy=str(policy_path),
        output_dir=str(Path(args.output_root) / "reports"),
        descriptive=str(descriptive["moments"]),
        calibration=str(calibration_path),
        failures=str(benchmark_outputs["failures"]),
        hte_summary=str(hte_outputs["summary"]),
        hte_calibration=str(hte_outputs["calibration"]),
        hte_stability=str(hte_outputs["fold_stability"]),
        nyc_full_validation=getattr(args, "nyc_full_validation", None),
        nyc_full_manifest=getattr(args, "nyc_full_manifest", None),
        treatment_version_policy=str(version_policy_path),
        treatment_version_policy_manifest=str(version_policy_manifest),
        interference_summary=str(interference_outputs["summary"]),
        interference_manifest=str(interference_outputs["manifest"]),
        nyc_simulation_anchor=(
            str(nyc_anchor_outputs["anchor"]) if nyc_anchor_outputs else None
        ),
        nyc_simulation_anchor_manifest=(
            str(nyc_anchor_outputs["manifest"]) if nyc_anchor_outputs else None
        ),
        nyc_benchmark_manifest=(
            str(nyc_benchmark_outputs["manifest"])
            if nyc_benchmark_outputs
            else None
        ),
        nyc_graph_benchmark_manifest=(
            str(nyc_graph_outputs["manifest"]) if nyc_graph_outputs else None
        ),
        equilibrium_manifest=str(equilibrium_outputs["manifest"]),
        nyc_weather_manifest=(
            str(nyc_weather_outputs["manifest"])
            if nyc_weather_outputs
            else None
        ),
        nyc_events_manifest=(
            str(nyc_events_outputs["manifest"])
            if nyc_events_outputs
            else None
        ),
        nyc_income_manifest=(
            str(nyc_income_outputs["manifest"])
            if nyc_income_outputs
            else None
        ),
        target_estimand=benchmark.target_estimand,
    )
    outputs.extend(_run_report(report_args))
    nyc_validation, nyc_manifest = _optional_nyc_full_evidence_paths(report_args)
    nyc_full_lineage: dict[str, Any] | None = None
    if nyc_validation is not None and nyc_manifest is not None:
        validation_payload = json.loads(nyc_validation.read_text(encoding="utf-8"))
        nyc_full_lineage = {
            "validation_sha256": sha256_file(nyc_validation),
            "analysis_manifest_sha256": sha256_file(nyc_manifest),
            "source_data_manifest_sha256": validation_payload["provenance"][
                "data_manifest_sha256"
            ],
        }
    treatment_version_policy_lineage = {
        "summary_sha256": sha256_file(version_policy_path),
        "manifest_sha256": sha256_file(version_policy_manifest),
    }
    extended_evidence_layers = [
        "theoretical_simulation_known_ground_truth",
    ]
    if nyc_benchmark_outputs:
        extended_evidence_layers.append(
            "semi_synthetic_nyc_informed_known_truth_monte_carlo"
        )
    if nyc_graph_outputs:
        extended_evidence_layers.append(
            "semi_synthetic_known_truth_on_descriptive_nyc_graph"
        )
    if nyc_weather_outputs:
        extended_evidence_layers.append("descriptive_observed_external_weather")
    if nyc_events_outputs:
        extended_evidence_layers.append(
            "descriptive_observed_external_calendar_events"
        )
    if nyc_income_outputs:
        extended_evidence_layers.append(
            "descriptive_observed_external_neighborhood_income"
        )
    manifest = _artifact_manifest(
        outputs,
        Path(args.output_root) / "reproduce_manifest.json",
        metadata={
            "evidence_layers": [
                "descriptive_real_data",
                "illustrative_empirical_scale_anchor",
                "semi_synthetic_known_ground_truth",
                "semi_synthetic_causal_monte_carlo",
                "semi_synthetic_policy_holdout",
                "semi_synthetic_treatment_version_policy_sensitivity",
                "semi_synthetic_exposure_mapped_known_truth_benchmark",
                "semi_synthetic_descriptive_anchor",
                *extended_evidence_layers,
            ],
            "data_config_sha256": sha256_file(args.config),
            "simulation_config_sha256": sha256_file(args.simulation_config),
            "benchmark_config_sha256": sha256_file(args.benchmark_config),
            "policy_config_sha256": sha256_file(args.policy_config),
            "constraints_sha256": sha256_file(project_root / "constraints.txt"),
            "source_tree_sha256": _source_tree_sha256(project_root),
            "runtime_environment": _runtime_environment(),
            "nyc_full_evidence": nyc_full_lineage,
            "treatment_version_policy_evidence": treatment_version_policy_lineage,
            "interference_benchmark_evidence": {
                "summary_sha256": sha256_file(interference_outputs["summary"]),
                "manifest_sha256": sha256_file(interference_outputs["manifest"]),
            },
            "nyc_simulation_anchor_evidence": (
                {
                    "anchor_sha256": sha256_file(nyc_anchor_outputs["anchor"]),
                    "manifest_sha256": sha256_file(nyc_anchor_outputs["manifest"]),
                }
                if nyc_anchor_outputs
                else None
            ),
            "nyc_informed_benchmark_evidence": (
                {
                    "manifest_sha256": sha256_file(
                        nyc_benchmark_outputs["manifest"]
                    ),
                    "summary_sha256": sha256_file(nyc_benchmark_outputs["summary"]),
                }
                if nyc_benchmark_outputs
                else None
            ),
            "nyc_graph_benchmark_evidence": (
                {
                    "manifest_sha256": sha256_file(nyc_graph_outputs["manifest"]),
                    "summary_sha256": sha256_file(nyc_graph_outputs["summary"]),
                }
                if nyc_graph_outputs
                else None
            ),
            "equilibrium_benchmark_evidence": {
                "manifest_sha256": sha256_file(equilibrium_outputs["manifest"]),
                "summary_sha256": sha256_file(equilibrium_outputs["summary"]),
            },
            "nyc_weather_evidence": (
                {
                    "manifest_sha256": sha256_file(nyc_weather_outputs["manifest"]),
                    "summary_sha256": sha256_file(nyc_weather_outputs["summary"]),
                }
                if nyc_weather_outputs
                else None
            ),
            "nyc_events_evidence": (
                {
                    "manifest_sha256": sha256_file(nyc_events_outputs["manifest"]),
                    "summary_sha256": sha256_file(nyc_events_outputs["summary"]),
                }
                if nyc_events_outputs
                else None
            ),
            "nyc_income_evidence": (
                {
                    "manifest_sha256": sha256_file(nyc_income_outputs["manifest"]),
                    "summary_sha256": sha256_file(nyc_income_outputs["summary"]),
                }
                if nyc_income_outputs
                else None
            ),
        },
    )
    outputs.append(manifest)
    return outputs


def _run_reproduce(args: argparse.Namespace) -> list[Path]:
    """Publish a complete run only after every stage and final manifest succeed.

    Artifacts are still written incrementally so the workflow remains portable on a
    laptop, but an old completion manifest is invalidated before the first write.
    Consumers fail closed while the marker exists, and a failed run deliberately
    leaves that marker behind for diagnosis.
    """

    data_config = load_data_config(args.config)
    if data_config.mode != "sample":
        raise ValueError(
            "reproduce-sample requires a bounded mode: sample data config; "
            "full-data ingestion is a separate explicit operation"
        )
    output_root = Path(args.output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    completion_manifest = output_root / "reproduce_manifest.json"
    incomplete_marker = output_root / "REPRODUCE_INCOMPLETE.json"
    completion_manifest.unlink(missing_ok=True)
    started_at = datetime.now(UTC).isoformat()
    _write_json(
        {
            "status": "incomplete",
            "started_at_utc": started_at,
            "message": (
                "This marker is removed only after every requested artifact and the "
                "hash manifest have been written successfully."
            ),
            "configs": {
                "data": str(args.config),
                "simulation": str(args.simulation_config),
                "benchmark": str(args.benchmark_config),
                "policy": str(args.policy_config),
            },
        },
        incomplete_marker,
    )
    outputs = _run_reproduce_inner(args)
    if not completion_manifest.is_file():
        raise RuntimeError("reproduction completed without a final hash manifest")
    incomplete_marker.unlink(missing_ok=True)
    return outputs


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="casuallab",
        description="Reproducible causal marketplace experiment laboratory",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    download = subparsers.add_parser(
        "download-sample", help="materialize a bounded configured raw sample"
    )
    download.add_argument("--config", default="configs/sample.yaml")
    download.add_argument("--refresh", action="store_true")
    download.set_defaults(handler=_run_download_sample)

    panel = subparsers.add_parser("build-panel", help="build clean trip and market panels")
    panel.add_argument("--config", default="configs/sample.yaml")
    panel.add_argument("--refresh", action="store_true")
    panel.add_argument(
        "--allow-full-download",
        action="store_true",
        help="explicitly permit an unbounded full-data download",
    )
    panel.set_defaults(handler=_run_build_panel)

    full_validation = subparsers.add_parser(
        "validate-nyc-full",
        help=(
            "stream, validate, describe, and build calibration/network inputs for "
            "one full NYC HVFHV month"
        ),
    )
    full_validation.add_argument("--config", default="configs/full.yaml")
    full_validation.add_argument("--output-dir", default="artifacts/nyc_full")
    full_validation.add_argument("--refresh", action="store_true")
    full_validation.add_argument(
        "--allow-full-download",
        action="store_true",
        help="explicitly permit the configured full-month data operation",
    )
    full_validation.set_defaults(handler=_run_validate_nyc_full)

    simulation = subparsers.add_parser("simulate", help="run the structural simulator")
    simulation.add_argument("--config", default="configs/simulation.yaml")
    simulation.add_argument("--output-dir", default="artifacts/simulation")
    simulation.set_defaults(handler=_run_simulate)

    benchmark = subparsers.add_parser("benchmark", help="run Monte Carlo design comparisons")
    benchmark.add_argument("--config", default="configs/benchmark.yaml")
    benchmark.add_argument("--simulation-config", default="configs/simulation.yaml")
    benchmark.add_argument("--output-dir", default="artifacts/benchmarks")
    benchmark.set_defaults(handler=_run_benchmark)

    interference = subparsers.add_parser(
        "interference-benchmark",
        help="run the known-truth two-stage saturation exposure benchmark",
    )
    interference.add_argument("--replications", type=int, default=24)
    interference.add_argument("--seed", type=int, default=880321)
    interference.add_argument("--output-dir", default="artifacts/benchmarks")
    interference.set_defaults(handler=_run_interference_benchmark)

    nyc_anchor = subparsers.add_parser(
        "nyc-simulation-anchor",
        help="build a validated semi-synthetic anchor from the NYC full-month bundle",
    )
    nyc_anchor.add_argument(
        "--calibration",
        default="artifacts/nyc_full/calibration_network/calibration.json",
    )
    nyc_anchor.add_argument(
        "--calibration-manifest",
        default="artifacts/nyc_full/calibration_network/manifest.json",
    )
    nyc_anchor.add_argument("--simulation-config", default="configs/simulation.yaml")
    nyc_anchor.add_argument("--n-zones", type=int, default=32)
    nyc_anchor.add_argument("--n-periods", type=int, default=168)
    nyc_anchor.add_argument("--seed", type=int, default=202503)
    nyc_anchor.add_argument(
        "--output-dir", default="artifacts/nyc_full/simulation_anchor"
    )
    nyc_anchor.set_defaults(handler=_run_nyc_simulation_anchor)

    nyc_weather = subparsers.add_parser(
        "nyc-weather",
        help=(
            "validate pinned NOAA Central Park weather and compute descriptive "
            "full-month NYC associations"
        ),
    )
    nyc_weather.add_argument(
        "--raw",
        default="data/nyc_weather/raw/noaa_central_park_2024-01.csv",
    )
    nyc_weather.add_argument(
        "--panel-dir",
        default="data/nyc_full/panel/zone_time",
    )
    nyc_weather.add_argument(
        "--data-manifest",
        default="data/nyc_full/manifest.json",
    )
    nyc_weather.add_argument(
        "--output-dir",
        default="artifacts/nyc_full/weather",
    )
    nyc_weather.add_argument(
        "--refresh",
        action="store_true",
        help="redownload the pinned NOAA response before validation",
    )
    nyc_weather.set_defaults(handler=_run_nyc_weather)

    nyc_events = subparsers.add_parser(
        "nyc-events",
        help="validate official calendars and describe NYC permitted-event associations",
    )
    nyc_events.add_argument(
        "--holidays",
        default="data/nyc_events/raw/official_holidays_2024-01.csv",
    )
    nyc_events.add_argument(
        "--events",
        default="data/nyc_events/raw/nyc_permitted_events_overlap_2024-01.csv",
    )
    nyc_events.add_argument("--panel-dir", default="data/nyc_full/panel/zone_time")
    nyc_events.add_argument("--data-manifest", default="data/nyc_full/manifest.json")
    nyc_events.add_argument("--output-dir", default="artifacts/nyc_full/events")
    nyc_events.add_argument(
        "--refresh",
        action="store_true",
        help="redownload the pinned NYC permitted-events response before validation",
    )
    nyc_events.set_defaults(handler=_run_nyc_events)

    nyc_income = subparsers.add_parser(
        "nyc-income",
        help="build ecological NYC Taxi Zone income descriptions from pinned sources",
    )
    nyc_income.add_argument(
        "--taxi-zones", default="data/nyc_income/raw/taxi_zones.zip"
    )
    nyc_income.add_argument(
        "--nta", default="data/nyc_income/raw/nyc_nta2020.geojson"
    )
    nyc_income.add_argument(
        "--tract-to-nta",
        default="data/nyc_income/raw/nyc_tract2020_to_nta2020.csv",
    )
    nyc_income.add_argument(
        "--acs-b19001",
        default="data/nyc_income/raw/acs_2022_5yr_b19001_nyc_tracts.dat",
    )
    nyc_income.add_argument("--panel-dir", default="data/nyc_full/panel/zone_time")
    nyc_income.add_argument("--data-manifest", default="data/nyc_full/manifest.json")
    nyc_income.add_argument("--output-dir", default="artifacts/nyc_full/income")
    nyc_income.set_defaults(handler=_run_nyc_income)

    nyc_benchmark = subparsers.add_parser(
        "nyc-benchmark",
        help="run a known-truth benchmark initialized from the validated NYC anchor",
    )
    nyc_benchmark.add_argument(
        "--anchor",
        default="artifacts/nyc_full/simulation_anchor/nyc_simulation_anchor.json",
    )
    nyc_benchmark.add_argument(
        "--anchor-manifest",
        default="artifacts/nyc_full/simulation_anchor/manifest.json",
    )
    nyc_benchmark.add_argument("--replications", type=int, default=6)
    nyc_benchmark.add_argument("--seed", type=int, default=870221)
    nyc_benchmark.add_argument("--n-zones", type=int, default=16)
    nyc_benchmark.add_argument("--n-periods", type=int, default=48)
    nyc_benchmark.add_argument(
        "--output-dir", default="artifacts/benchmarks/nyc_informed"
    )
    nyc_benchmark.set_defaults(handler=_run_nyc_benchmark)

    nyc_graph = subparsers.add_parser(
        "nyc-graph-benchmark",
        help="run a known-truth exposure benchmark on the validated NYC OD graph",
    )
    nyc_graph.add_argument(
        "--bundle",
        default="artifacts/nyc_full/calibration_network",
    )
    nyc_graph.add_argument("--replications", type=int, default=12)
    nyc_graph.add_argument("--seed", type=int, default=912731)
    nyc_graph.add_argument("--n-zones", type=int, default=16)
    nyc_graph.add_argument("--n-periods", type=int, default=24)
    nyc_graph.add_argument(
        "--output-dir", default="artifacts/benchmarks/nyc_graph"
    )
    nyc_graph.set_defaults(handler=_run_nyc_graph_benchmark)

    equilibrium = subparsers.add_parser(
        "equilibrium-benchmark",
        help="solve a theoretical two-sided fixed-point equilibrium benchmark",
    )
    equilibrium.add_argument("--n-zones", type=int, default=2)
    equilibrium.add_argument("--seed", type=int, default=202503)
    equilibrium.add_argument(
        "--treatment-version",
        choices=("rider_discount", "driver_incentive", "bundled"),
        default="bundled",
    )
    equilibrium.add_argument("--budget", type=float)
    equilibrium.add_argument("--treatment-intensity", type=float, default=1.0)
    equilibrium.add_argument(
        "--output-dir", default="artifacts/benchmarks/equilibrium"
    )
    equilibrium.set_defaults(handler=_run_equilibrium_benchmark)

    report = subparsers.add_parser("report", help="generate reports from computed artifacts")
    report.add_argument("--benchmark", default="artifacts/benchmarks/benchmark_results.csv")
    report.add_argument("--policy", default="artifacts/benchmarks/policy_results.csv")
    report.add_argument("--output-dir", default="artifacts/reports")
    report.add_argument(
        "--descriptive",
        default="artifacts/reports/descriptive/descriptive_moments.json",
    )
    report.add_argument("--calibration", default="artifacts/reports/calibration.json")
    report.add_argument("--failures", default="artifacts/benchmarks/benchmark_failures.csv")
    report.add_argument(
        "--hte-summary",
        default="artifacts/benchmarks/heterogeneity/hte_recovery.json",
    )
    report.add_argument(
        "--hte-calibration",
        default="artifacts/benchmarks/heterogeneity/hte_calibration_by_score.csv",
    )
    report.add_argument(
        "--hte-stability",
        default="artifacts/benchmarks/heterogeneity/hte_fold_stability.csv",
    )
    report.add_argument(
        "--nyc-full-validation",
        default="artifacts/nyc_full/validation.json",
        help="optional verified NYC full-month validation artifact",
    )
    report.add_argument(
        "--nyc-full-manifest",
        default="artifacts/nyc_full/manifest.json",
        help="lineage manifest paired with --nyc-full-validation",
    )
    report.add_argument(
        "--treatment-version-policy",
        default="artifacts/benchmarks/treatment_version_policy_results.csv",
        help="optional rider/driver/bundled policy sensitivity summary",
    )
    report.add_argument(
        "--treatment-version-policy-manifest",
        default="artifacts/benchmarks/treatment_version_policy_manifest.json",
        help="lineage manifest paired with --treatment-version-policy",
    )
    report.add_argument(
        "--interference-summary",
        default="artifacts/benchmarks/interference_summary.csv",
        help="optional known-truth mapped-exposure benchmark summary",
    )
    report.add_argument(
        "--interference-manifest",
        default="artifacts/benchmarks/interference_manifest.json",
        help="lineage manifest paired with --interference-summary",
    )
    report.add_argument(
        "--nyc-simulation-anchor",
        default="artifacts/nyc_full/simulation_anchor/nyc_simulation_anchor.json",
        help="optional validated NYC descriptive simulator anchor",
    )
    report.add_argument(
        "--nyc-simulation-anchor-manifest",
        default="artifacts/nyc_full/simulation_anchor/manifest.json",
        help="lineage manifest paired with --nyc-simulation-anchor",
    )
    report.add_argument(
        "--nyc-benchmark-manifest",
        default="artifacts/benchmarks/nyc_informed/manifest.json",
        help="optional NYC-informed known-truth benchmark manifest",
    )
    report.add_argument(
        "--nyc-graph-benchmark-manifest",
        default="artifacts/benchmarks/nyc_graph/manifest.json",
        help="optional NYC OD-graph known-truth benchmark manifest",
    )
    report.add_argument(
        "--equilibrium-manifest",
        default="artifacts/benchmarks/equilibrium/manifest.json",
        help="optional theoretical fixed-point equilibrium benchmark manifest",
    )
    report.add_argument(
        "--nyc-weather-manifest",
        default="artifacts/nyc_full/weather/manifest.json",
        help="optional descriptive NOAA weather association manifest",
    )
    report.add_argument(
        "--nyc-events-manifest",
        default="artifacts/nyc_full/events/manifest.json",
        help="optional descriptive official-calendar/permitted-event manifest",
    )
    report.add_argument(
        "--nyc-income-manifest",
        default="artifacts/nyc_full/income/manifest.json",
        help="optional ecological NYC neighborhood-income manifest",
    )
    report.add_argument("--target-estimand")
    report.set_defaults(handler=_run_report)

    reproduce = subparsers.add_parser(
        "reproduce-sample",
        help="rebuild the complete offline vertical slice",
    )
    reproduce.add_argument("--config", default="configs/sample.yaml")
    reproduce.add_argument("--simulation-config", default="configs/simulation.yaml")
    reproduce.add_argument("--benchmark-config", default="configs/benchmark.yaml")
    reproduce.add_argument("--policy-config", default="configs/policy.yaml")
    reproduce.add_argument("--output-root", default="artifacts")
    reproduce.add_argument(
        "--nyc-full-validation",
        default="artifacts/nyc_full/validation.json",
        help="reuse an already-validated NYC full month without downloading it",
    )
    reproduce.add_argument(
        "--nyc-full-manifest",
        default="artifacts/nyc_full/manifest.json",
        help="lineage manifest paired with --nyc-full-validation",
    )
    reproduce.add_argument("--refresh", action="store_true")
    reproduce.set_defaults(handler=_run_reproduce)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    paths = args.handler(args)
    for path in paths:
        print(path)
    return 0
