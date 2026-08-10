"""End-to-end orchestration for the offline vintage-aware vertical slice."""

from __future__ import annotations

import json
import math
import tomllib
from collections.abc import Mapping
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from macro_nowcast.artifacts import (
    config_hash,
    frame_hash,
    package_versions,
    sha256_file,
    write_json,
)
from macro_nowcast.asof import AS_OF_MODE, LATEST_SAME_MASK_MODE, select_as_of
from macro_nowcast.attribution import linear_news_attribution
from macro_nowcast.calendar import build_forecast_origins
from macro_nowcast.evaluation import (
    diebold_mariano,
    regression_metrics,
    residual_prediction_interval,
    run_expanding_backtest,
)
from macro_nowcast.features import (
    DEFAULT_FEATURE_SPECS,
    assert_feature_no_future,
    build_feature_matrix,
    build_feature_vector,
    build_payems_targets,
)
from macro_nowcast.models import FixedElasticNetRegressor, default_model_ladder
from macro_nowcast.reporting import write_policy_brief, write_required_reports
from macro_nowcast.revisions import revision_details, revision_summary
from macro_nowcast.sample_data import build_synthetic_fixture
from macro_nowcast.schema import validate_canonical_frame
from macro_nowcast.storage import VintageStore

FIXTURE_LABEL = "synthetic_fixture"
FEATURE_NAMES = tuple(spec.name for spec in DEFAULT_FEATURE_SPECS)
PRIMARY_EXPERIMENTS = (
    ("vintage_aware", AS_OF_MODE, "first_release"),
    (LATEST_SAME_MASK_MODE, LATEST_SAME_MASK_MODE, "latest_revised"),
)


def _load_raw_config(config_path: Path) -> dict[str, Any]:
    with config_path.open("rb") as handle:
        raw = tomllib.load(handle)
    for section in ("project", "target", "backtest"):
        if section not in raw or not isinstance(raw[section], dict):
            raise ValueError(f"configuration is missing [{section}]")
    if raw["project"].get("fixture_label") != FIXTURE_LABEL:
        raise ValueError("the offline sample must remain labeled synthetic_fixture")
    return raw


def _root(config_path: Path) -> Path:
    resolved = config_path.resolve()
    if resolved.parent.name != "config":
        raise ValueError("sample configuration must live under the project config directory")
    return resolved.parent.parent


def _paths(config_path: Path) -> dict[str, Path]:
    root = _root(config_path)
    return {
        "root": root,
        "fixture": root / "data" / "fixtures" / "synthetic_payroll",
        "generated": root / "data" / "generated",
        "generated_reports": root / "reports" / "generated",
    }


def _latest_cutoff(raw: Mapping[str, Any]) -> datetime:
    value = date.fromisoformat(str(raw["backtest"]["latest_evaluation_date"]))
    return datetime.combine(value, time(23, 59, 59, 999_999), tzinfo=UTC)


def _evaluation_bounds(raw: Mapping[str, Any]) -> tuple[date, date]:
    backtest_config = raw["backtest"]
    return (
        date.fromisoformat(str(backtest_config["evaluation_start"])),
        date.fromisoformat(str(backtest_config["evaluation_end"])),
    )


def _write_frame(
    frame: pl.DataFrame,
    path: Path,
    *,
    store: VintageStore | None = None,
    view_name: str | None = None,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.write_parquet(path, compression="zstd", statistics=True)
    if store is not None:
        store.register_view(path, table_name=view_name or path.stem)
    return path


def _read_required(path: Path) -> pl.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"required artifact is missing: {path}")
    return pl.read_parquet(path)


def _all_release_events(observations: pl.DataFrame) -> pl.DataFrame:
    ordered = observations.sort(
        ["series_id", "observation_date", "availability_timestamp", "realtime_start"]
    ).with_columns(
        pl.int_range(1, pl.len() + 1)
        .over(["series_id", "observation_date"])
        .alias("revision_number")
    )
    return (
        ordered.select(
            pl.concat_str(
                [
                    pl.lit("synthetic-"),
                    pl.col("series_id"),
                    pl.lit("-"),
                    pl.col("observation_date").cast(pl.String),
                    pl.lit("-v"),
                    pl.col("revision_number").cast(pl.String),
                ]
            ).alias("release_id"),
            "series_id",
            pl.col("observation_date").alias("reference_period"),
            pl.col("release_timestamp").alias("release_ts"),
            pl.when(pl.col("revision_number") == 1)
            .then(pl.lit("initial"))
            .otherwise(pl.lit("revision"))
            .alias("release_kind"),
            pl.lit("synthetic_exact").alias("timing_quality"),
            "source",
            "provenance_label",
        )
        .unique(subset=["release_id"], keep="first")
        .sort(["release_ts", "series_id", "reference_period"])
    )


def prepare_sample(config_path: Path) -> dict[str, object]:
    """Create and persist a deterministic, explicitly synthetic source fixture."""

    raw = _load_raw_config(config_path)
    paths = _paths(config_path)
    fixture = build_synthetic_fixture(
        start=date.fromisoformat(str(raw["project"].get("fixture_start", "2017-01-01"))),
        end=date.fromisoformat(str(raw["project"].get("fixture_end", "2025-03-01"))),
        seed=int(raw["project"]["random_seed"]),
    )
    destination = paths["fixture"]
    destination.mkdir(parents=True, exist_ok=True)
    observation_path = _write_frame(
        fixture.observations,
        destination / "observation_vintages.parquet",
    )
    _write_frame(fixture.release_calendar, destination / "target_release_calendar.parquet")
    _write_frame(fixture.series_metadata, destination / "series_catalog.parquet")
    fixture_manifest = {
        "fixture_label": FIXTURE_LABEL,
        "description": "Deterministic synthetic FRED/ALFRED-shaped fixture; not economic data",
        "network_used": False,
        "fred_api_accessed": False,
        "seed": int(raw["project"]["random_seed"]),
        "series": fixture.series_metadata["series_id"].sort().to_list(),
        "observation_rows": fixture.observations.height,
        "vintage_start": fixture.observations["availability_timestamp"].min(),
        "vintage_end": fixture.observations["availability_timestamp"].max(),
        "payload_sha256": sha256_file(observation_path),
        "fixture_generated_at": "2026-08-07T12:00:00+00:00",
    }
    write_json(fixture_manifest, destination / "manifest.json")
    (destination / "README.md").write_text(
        "# Synthetic payroll fixture\n\n"
        "This directory is generated deterministically by `make download-sample`. "
        "Every value and release time is artificial and exists only to test vintage, "
        "revision, mixed-frequency, and ragged-edge behavior. No file contains FRED, "
        "ALFRED, BLS, or other source-provider observations.\n"
    )
    return {
        "fixture_label": FIXTURE_LABEL,
        "network_used": False,
        "series": len(fixture_manifest["series"]),
        "rows": fixture.observations.height,
        "path": str(observation_path),
    }


def _base_manifest(
    config_path: Path,
    raw: Mapping[str, Any],
    observations: pl.DataFrame,
) -> dict[str, Any]:
    paths = _paths(config_path)
    fixture_path = paths["fixture"] / "observation_vintages.parquet"
    configuration_hash = config_hash(config_path)
    input_hash = sha256_file(fixture_path)
    run_id = f"synthetic-{configuration_hash[:10]}-{input_hash[:10]}"
    availability = observations["availability_timestamp"]
    return {
        "run_id": run_id,
        "project": raw["project"]["name"],
        "fixture_label": FIXTURE_LABEL,
        "synthetic_fixture": True,
        "empirical_findings_supported": False,
        "network_used": False,
        "fred_api_accessed": False,
        "config_sha256": configuration_hash,
        "input_sha256": input_hash,
        "input_frame_sha256": frame_hash(observations),
        "target": raw["target"]["name"],
        "target_series_id": raw["target"]["series_id"],
        "target_transformation": raw["target"]["transformation"],
        "horizon": int(raw["target"]["horizon"]),
        "latest_evaluation_date": raw["backtest"]["latest_evaluation_date"],
        "series": observations["series_id"].unique().sort().to_list(),
        "series_count": observations["series_id"].n_unique(),
        "vintage_row_count": observations.height,
        "vintage_availability_start": availability.min(),
        "vintage_availability_end": availability.max(),
        "release_timing_precision": "synthetic_exact_utc",
        "date_only_convention": "available at 23:59:59.999999 UTC",
        "feature_modes": [AS_OF_MODE, LATEST_SAME_MASK_MODE],
        "target_modes": ["first_release", "latest_revised"],
        "package_versions": package_versions(),
    }


def build_vintages(config_path: Path) -> dict[str, object]:
    """Normalize fixtures into durable Parquet artifacts and DuckDB views."""

    raw = _load_raw_config(config_path)
    paths = _paths(config_path)
    fixture_observations = paths["fixture"] / "observation_vintages.parquet"
    if not fixture_observations.exists():
        prepare_sample(config_path)
    observations = validate_canonical_frame(_read_required(fixture_observations))
    target_calendar = _read_required(
        paths["fixture"] / "target_release_calendar.parquet"
    )
    catalog = _read_required(paths["fixture"] / "series_catalog.parquet")
    origins = build_forecast_origins(target_calendar)
    all_releases = _all_release_events(observations)

    generated = paths["generated"]
    generated.mkdir(parents=True, exist_ok=True)
    store = VintageStore(generated, generated / "macro_nowcast.duckdb")
    observation_path = store.write_observations(
        observations,
        dataset_name="observation_vintages",
        overwrite=True,
        register=True,
    )
    _write_frame(catalog, generated / "series_catalog.parquet", store=store)
    _write_frame(target_calendar, generated / "target_release_calendar.parquet", store=store)
    _write_frame(all_releases, generated / "release_calendar.parquet", store=store)
    _write_frame(origins, generated / "forecast_origins.parquet", store=store)
    manifest = _base_manifest(config_path, raw, observations)
    manifest["artifact_stage"] = "vintages_built"
    write_json(manifest, generated / "run_manifest.json")
    return {
        "fixture_label": FIXTURE_LABEL,
        "observation_rows": observations.height,
        "release_events": all_releases.height,
        "forecast_origins": origins.height,
        "parquet": str(observation_path),
        "duckdb": str(store.duckdb_path),
    }


def _build_all_features(
    observations: pl.DataFrame,
    origins: pl.DataFrame,
    *,
    latest_cutoff: datetime,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    vintage_features = build_feature_matrix(
        observations,
        origins,
        specs=DEFAULT_FEATURE_SPECS,
        mode=AS_OF_MODE,
    )
    fixed_latest_observations = observations.filter(
        pl.col("availability_timestamp") <= pl.lit(latest_cutoff)
    )
    revised_features = build_feature_matrix(
        fixed_latest_observations,
        origins,
        specs=DEFAULT_FEATURE_SPECS,
        mode=LATEST_SAME_MASK_MODE,
    )
    assert_feature_no_future(vintage_features)
    assert_feature_no_future(revised_features)
    return vintage_features, revised_features


def validate_asof(config_path: Path) -> dict[str, object]:
    """Validate all raw and derived information boundaries for every origin."""

    raw = _load_raw_config(config_path)
    paths = _paths(config_path)
    if not (paths["generated"] / "observation_vintages.parquet").exists():
        build_vintages(config_path)
    observations = _read_required(paths["generated"] / "observation_vintages.parquet")
    origins = _read_required(paths["generated"] / "forecast_origins.parquet")
    checked_rows = 0
    for origin in origins.iter_rows(named=True):
        snapshot = select_as_of(observations, origin["forecast_origin"])
        checked_rows += snapshot.height
        violations = snapshot.filter(
            pl.col("effective_availability_timestamp") > pl.col("as_of_timestamp")
        )
        if violations.height:
            raise AssertionError("a raw snapshot contains post-origin information")
    vintage_features, revised_features = _build_all_features(
        observations,
        origins,
        latest_cutoff=_latest_cutoff(raw),
    )
    return {
        "origins_checked": origins.height,
        "snapshot_rows_checked": checked_rows,
        "derived_cells_checked": vintage_features.height + revised_features.height,
        "future_information_violations": 0,
        "counterfactual_rows_labeled": revised_features["is_counterfactual"].sum(),
    }


def _wide_features(features: pl.DataFrame) -> pl.DataFrame:
    index = [
        "forecast_id",
        "target_series_id",
        "target_period",
        "as_of_timestamp",
        "information_set_mode",
        "is_counterfactual",
    ]
    pivot = features.pivot(
        on="feature_name",
        index=index,
        values="value",
        aggregate_function="first",
    )
    audit = features.group_by("forecast_id").agg(
        pl.col("max_source_availability").max().alias("max_source_availability_ts"),
        pl.col("max_eligibility_availability")
        .max()
        .alias("max_eligibility_availability_ts"),
        pl.col("is_missing").sum().alias("missing_feature_count"),
    )
    wide = pivot.join(audit, on="forecast_id", how="left", validate="1:1")
    for feature_name in FEATURE_NAMES:
        if feature_name not in wide.columns:
            wide = wide.with_columns(pl.lit(None, dtype=pl.Float64).alias(feature_name))
    return wide.select(
        *index,
        *FEATURE_NAMES,
        "max_source_availability_ts",
        "max_eligibility_availability_ts",
        "missing_feature_count",
    ).sort("target_period")


def _research_dataset(
    wide: pl.DataFrame,
    targets: pl.DataFrame,
    *,
    experiment: str,
    target_mode: str,
) -> pl.DataFrame:
    realization = targets.filter(pl.col("realization_mode") == target_mode).select(
        "target_period",
        pl.col("value").alias("target_value"),
        "target_release_timestamp",
        "realization_as_of_timestamp",
        "max_source_availability",
        "realization_mode",
    )
    return (
        wide.join(realization, on="target_period", how="inner", validate="1:1")
        .with_columns(
            pl.lit(experiment).alias("data_mode"),
            pl.lit(FIXTURE_LABEL).alias("fixture_label"),
        )
        .sort("target_period")
    )


def _fixture_regime(period: date) -> str:
    month_number = period.year * 12 + period.month - 1
    return "synthetic_regime_a" if (month_number // 18) % 2 == 0 else "synthetic_regime_b"


def _datetime64_to_utc(value: np.datetime64) -> datetime:
    if np.isnat(value):
        raise ValueError("audited forecast timestamps cannot be missing")
    nanoseconds = int(value.astype("datetime64[ns]").astype(np.int64))
    return datetime(1970, 1, 1, tzinfo=UTC) + timedelta(microseconds=nanoseconds // 1_000)


def _records_for_experiment(
    dataset: pl.DataFrame,
    *,
    model_name: str,
    estimator: Any,
    raw: Mapping[str, Any],
) -> pl.DataFrame:
    x = dataset.select(FEATURE_NAMES).to_numpy()
    y = dataset["target_value"].to_numpy()
    origins = dataset["as_of_timestamp"].to_list()
    releases = dataset["target_release_timestamp"].to_list()
    regimes = [_fixture_regime(period) for period in dataset["target_period"].to_list()]
    result = run_expanding_backtest(
        estimator,
        x,
        y,
        origins=origins,
        target_release_dates=releases,
        min_train_size=int(raw["backtest"]["minimum_train_periods"]),
        horizon=[int(raw["target"]["horizon"])] * dataset.height,
        regimes=regimes,
        model_name=model_name,
        interval_coverage_target=1.0 - float(raw["backtest"]["interval_alpha"]),
        interval_min_residuals=int(raw["backtest"]["interval_min_residuals"]),
    )
    rows: list[dict[str, object]] = []
    target_periods = dataset["target_period"].to_list()
    for record in result.records:
        rows.append(
            {
                "fold_id": record.fold,
                "row_index": record.row_index,
                "model_id": model_name,
                "data_mode": dataset["data_mode"][0],
                "feature_mode": dataset["information_set_mode"][0],
                "target_mode": dataset["realization_mode"][0],
                "target_period": target_periods[record.row_index],
                "origin_ts": _datetime64_to_utc(record.origin),
                "target_release_ts": _datetime64_to_utc(record.target_release_date),
                "actual": record.actual,
                "prediction": record.forecast,
                "lower": record.lower,
                "upper": record.upper,
                "n_train": record.train_size,
                "horizon": int(record.horizon),
                "regime": str(record.regime),
                "fixture_label": FIXTURE_LABEL,
            }
        )
    return pl.DataFrame(rows).sort(["target_period", "model_id"])


def _metric_row(frame: pl.DataFrame) -> dict[str, object]:
    actual = frame["actual"].to_numpy()
    metrics = regression_metrics(
        actual,
        frame["prediction"].to_numpy(),
        lower=frame["lower"].to_numpy(),
        upper=frame["upper"].to_numpy(),
    )
    finite_actual = actual[np.isfinite(actual)]
    direction_meaningful = np.unique(np.sign(finite_actual)).size > 1
    if not direction_meaningful:
        metrics["directional_accuracy"] = math.nan
    return {
        "n_forecasts": metrics.pop("n_obs"),
        **metrics,
        "directional_accuracy_meaningful": direction_meaningful,
        "sample_start": frame["target_period"].min(),
        "sample_end": frame["target_period"].max(),
    }


def _metrics(predictions: pl.DataFrame) -> tuple[pl.DataFrame, pl.DataFrame]:
    metric_rows: list[dict[str, object]] = []
    for mode, model in predictions.select("data_mode", "model_id").unique().iter_rows():
        subset = predictions.filter(
            (pl.col("data_mode") == mode) & (pl.col("model_id") == model)
        )
        metric_rows.append(
            {
                "model_id": model,
                "data_mode": mode,
                "feature_mode": subset["feature_mode"][0],
                "target_mode": subset["target_mode"][0],
                "horizon": subset["horizon"][0],
                "fixture_label": FIXTURE_LABEL,
                **_metric_row(subset),
            }
        )
    metrics = pl.DataFrame(metric_rows).sort(["data_mode", "rmse", "model_id"])
    metrics = metrics.with_columns(
        pl.col("rmse").rank("dense").over("data_mode").cast(pl.Int64).alias("rmse_rank")
    )

    grouped_rows: list[dict[str, object]] = []
    grouping_keys = ["data_mode", "model_id", "horizon", "regime"]
    for key in predictions.select(grouping_keys).unique().iter_rows(named=True):
        condition = pl.lit(True)
        for name in grouping_keys:
            condition &= pl.col(name) == key[name]
        subset = predictions.filter(condition)
        grouped_rows.append({**key, **_metric_row(subset), "fixture_label": FIXTURE_LABEL})
    grouped = pl.DataFrame(grouped_rows).sort(grouping_keys)
    return metrics, grouped


def _dm_comparisons(predictions: pl.DataFrame) -> pl.DataFrame:
    rows: list[dict[str, object]] = []
    for mode in predictions["data_mode"].unique().sort().to_list():
        mode_frame = predictions.filter(pl.col("data_mode") == mode)
        baseline = mode_frame.filter(pl.col("model_id") == "historical_mean").select(
            "target_period",
            "actual",
            pl.col("prediction").alias("baseline_prediction"),
        )
        for model in mode_frame["model_id"].unique().sort().to_list():
            if model == "historical_mean":
                continue
            aligned = baseline.join(
                mode_frame.filter(pl.col("model_id") == model).select(
                    "target_period", pl.col("prediction").alias("model_prediction")
                ),
                on="target_period",
                how="inner",
                validate="1:1",
            )
            result = diebold_mariano(
                aligned["actual"].to_numpy(),
                aligned["baseline_prediction"].to_numpy(),
                aligned["model_prediction"].to_numpy(),
                horizon=1,
                min_observations=20,
            )
            rows.append(
                {
                    "data_mode": mode,
                    "baseline_model": "historical_mean",
                    "comparison_model": model,
                    "statistic": result.statistic,
                    "p_value": result.p_value,
                    "mean_loss_differential": result.mean_loss_differential,
                    "n_obs": result.n_obs,
                    "valid": result.valid,
                    "reason": result.reason,
                    "fixture_label": FIXTURE_LABEL,
                }
            )
    return pl.DataFrame(rows).sort(["data_mode", "comparison_model"])


def _model_stability(predictions: pl.DataFrame, metrics: pl.DataFrame) -> pl.DataFrame:
    rows: list[dict[str, object]] = []
    for model in predictions["model_id"].unique().sort().to_list():
        vintage = predictions.filter(
            (pl.col("model_id") == model) & (pl.col("data_mode") == "vintage_aware")
        ).select("target_period", pl.col("prediction").alias("vintage_prediction"))
        revised = predictions.filter(
            (pl.col("model_id") == model)
            & (pl.col("data_mode") == LATEST_SAME_MASK_MODE)
        ).select("target_period", pl.col("prediction").alias("revised_prediction"))
        aligned = vintage.join(revised, on="target_period", how="inner", validate="1:1")
        first = aligned["vintage_prediction"].to_numpy()
        second = aligned["revised_prediction"].to_numpy()
        correlation = float(np.corrcoef(first, second)[0, 1]) if aligned.height > 1 else math.nan
        ranks = metrics.filter(pl.col("model_id") == model)
        vintage_rank = ranks.filter(pl.col("data_mode") == "vintage_aware")["rmse_rank"][0]
        revised_rank = ranks.filter(pl.col("data_mode") == LATEST_SAME_MASK_MODE)[
            "rmse_rank"
        ][0]
        rows.append(
            {
                "model_id": model,
                "n_aligned": aligned.height,
                "prediction_correlation": correlation,
                "mean_abs_prediction_difference": float(np.mean(np.abs(second - first))),
                "vintage_rmse_rank": vintage_rank,
                "revised_rmse_rank": revised_rank,
                "rank_change": int(revised_rank - vintage_rank),
                "fixture_label": FIXTURE_LABEL,
            }
        )
    return pl.DataFrame(rows).sort("model_id")


def _target_revision_effects(
    targets: pl.DataFrame,
    predictions: pl.DataFrame,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    target_revisions = (
        targets.pivot(
            on="realization_mode",
            index="target_period",
            values="value",
            aggregate_function="first",
        )
        .drop_nulls(["first_release", "latest_revised"])
        .with_columns(
            (pl.col("latest_revised") - pl.col("first_release")).alias("target_revision")
        )
        .with_columns(pl.col("target_revision").abs().alias("absolute_target_revision"))
        .sort("target_period")
    )
    detailed = (
        predictions.filter(pl.col("data_mode") == "vintage_aware")
        .join(target_revisions, on="target_period", how="inner", validate="m:1")
        .with_columns(
            (pl.col("prediction") - pl.col("first_release")).alias(
                "forecast_error_first_release"
            ),
            (pl.col("prediction") - pl.col("latest_revised")).alias(
                "forecast_error_latest_revised"
            ),
        )
        .with_columns(
            pl.col("forecast_error_first_release")
            .abs()
            .alias("absolute_error_first_release"),
            pl.col("forecast_error_latest_revised")
            .abs()
            .alias("absolute_error_latest_revised"),
        )
    )
    summary = (
        detailed.group_by("model_id")
        .agg(
            pl.len().alias("n_forecasts"),
            pl.col("absolute_error_first_release").mean().alias("mae_first_release"),
            pl.col("absolute_error_latest_revised").mean().alias("mae_latest_revised"),
            pl.col("target_revision").mean().alias("mean_target_revision"),
            pl.col("absolute_target_revision").mean().alias("mean_abs_target_revision"),
            (
                pl.col("absolute_error_latest_revised")
                - pl.col("absolute_error_first_release")
            )
            .mean()
            .alias("mean_change_in_absolute_error_due_to_target_revision"),
        )
        .with_columns(pl.lit(FIXTURE_LABEL).alias("fixture_label"))
        .sort("model_id")
    )
    return detailed, summary


def _news_update(
    observations: pl.DataFrame,
    vintage_dataset: pl.DataFrame,
    predictions: pl.DataFrame,
    *,
    raw: Mapping[str, Any],
) -> dict[str, Any]:
    target_period = date.fromisoformat(str(raw["backtest"]["evaluation_end"]))
    release_ts = datetime(target_period.year, target_period.month, 15, 15, 0, tzinfo=UTC)
    previous_ts = release_ts - timedelta(microseconds=1)
    updated_ts = release_ts + timedelta(microseconds=1)
    previous_long = build_feature_vector(
        observations,
        as_of=previous_ts,
        target_period=target_period,
        mode=AS_OF_MODE,
    )
    updated_long = build_feature_vector(
        observations,
        as_of=updated_ts,
        target_period=target_period,
        mode=AS_OF_MODE,
    )
    previous_map = dict(
        zip(previous_long["feature_name"].to_list(), previous_long["value"].to_list(), strict=True)
    )
    updated_map = dict(
        zip(updated_long["feature_name"].to_list(), updated_long["value"].to_list(), strict=True)
    )
    training = vintage_dataset.filter(pl.col("target_period") < pl.lit(target_period))
    model = FixedElasticNetRegressor()
    model.fit(training.select(FEATURE_NAMES).to_numpy(), training["target_value"].to_numpy())
    attribution = linear_news_attribution(
        model,
        previous_map,
        updated_map,
        feature_names=FEATURE_NAMES,
    )
    prior_predictions = predictions.filter(
        (pl.col("data_mode") == "vintage_aware")
        & (pl.col("model_id") == "elastic_net")
        & (pl.col("target_release_ts") <= pl.lit(updated_ts))
    )
    residuals = (
        prior_predictions["actual"] - prior_predictions["prediction"]
        if prior_predictions.height
        else pl.Series([], dtype=pl.Float64)
    )
    lower, upper = residual_prediction_interval(
        [attribution.updated_prediction],
        residuals.to_numpy(),
        coverage=1.0 - float(raw["backtest"]["interval_alpha"]),
        min_residuals=int(raw["backtest"]["interval_min_residuals"]),
    )
    contributions = [
        {"feature": name, "contribution": value}
        for name, value in sorted(
            attribution.contributions.items(), key=lambda item: abs(item[1]), reverse=True
        )
    ]
    return {
        "fixture_label": FIXTURE_LABEL,
        "data_mode": "vintage_aware",
        "release_name": "Synthetic consumer sentiment initial release",
        "release_series_id": "UMCSENT",
        "release_ts": release_ts,
        "previous_as_of_ts": previous_ts,
        "updated_as_of_ts": updated_ts,
        "target_period": target_period,
        "previous_nowcast": attribution.previous_prediction,
        "updated_nowcast": attribution.updated_prediction,
        "forecast_revision": attribution.total_change,
        "attribution_method": attribution.method,
        "attribution_label": attribution.label,
        "unattributed_residual": attribution.unattributed_residual,
        "contributions": contributions,
        "interval": {
            "coverage": 1.0 - float(raw["backtest"]["interval_alpha"]),
            "lower": None if np.isnan(lower[0]) else float(lower[0]),
            "upper": None if np.isnan(upper[0]) else float(upper[0]),
        },
        "interpretation": "mechanical fixed-model update; not causal and not empirical",
    }


def backtest(config_path: Path) -> dict[str, object]:
    """Build research datasets and run both honest and revised counterfactual backtests."""

    raw = _load_raw_config(config_path)
    paths = _paths(config_path)
    generated = paths["generated"]
    if not (generated / "observation_vintages.parquet").exists():
        build_vintages(config_path)
    observations = _read_required(generated / "observation_vintages.parquet")
    origins = _read_required(generated / "forecast_origins.parquet")
    target_calendar = _read_required(generated / "target_release_calendar.parquet")
    latest_cutoff = _latest_cutoff(raw)
    vintage_long, revised_long = _build_all_features(
        observations,
        origins,
        latest_cutoff=latest_cutoff,
    )
    targets = build_payems_targets(
        observations,
        target_calendar,
        latest_as_of=latest_cutoff,
    )
    wide_by_mode = {
        AS_OF_MODE: _wide_features(vintage_long),
        LATEST_SAME_MASK_MODE: _wide_features(revised_long),
    }
    datasets: list[pl.DataFrame] = []
    for experiment, feature_mode, target_mode in PRIMARY_EXPERIMENTS:
        datasets.append(
            _research_dataset(
                wide_by_mode[feature_mode],
                targets,
                experiment=experiment,
                target_mode=target_mode,
            )
        )
    research = pl.concat(datasets, how="diagonal_relaxed")
    evaluation_start, evaluation_end = _evaluation_bounds(raw)
    prediction_frames: list[pl.DataFrame] = []
    for experiment, _, _ in PRIMARY_EXPERIMENTS:
        dataset = research.filter(pl.col("data_mode") == experiment).sort("target_period")
        for model_name, estimator in default_model_ladder().items():
            records = _records_for_experiment(
                dataset,
                model_name=model_name,
                estimator=estimator,
                raw=raw,
            ).filter(
                (pl.col("target_period") >= pl.lit(evaluation_start))
                & (pl.col("target_period") <= pl.lit(evaluation_end))
            )
            if records.height:
                prediction_frames.append(records)
    if not prediction_frames:
        raise RuntimeError("backtest produced no out-of-sample predictions")
    predictions = pl.concat(prediction_frames, how="diagonal_relaxed").sort(
        ["data_mode", "model_id", "target_period"]
    )
    metrics, grouped = _metrics(predictions)
    dm = _dm_comparisons(predictions)
    stability = _model_stability(predictions, metrics)
    target_revision_details, target_revision_summary = _target_revision_effects(
        targets,
        predictions,
    )
    revision_detail = revision_details(observations)
    revisions = revision_summary(observations)
    news = _news_update(
        observations,
        research.filter(pl.col("data_mode") == "vintage_aware"),
        predictions,
        raw=raw,
    )

    store = VintageStore(generated, generated / "macro_nowcast.duckdb")
    artifact_frames = {
        "features_long": pl.concat([vintage_long, revised_long], how="vertical"),
        "features_wide": pl.concat(list(wide_by_mode.values()), how="diagonal_relaxed"),
        "targets": targets,
        "research_datasets": research,
        "predictions": predictions,
        "metrics": metrics,
        "metrics_by_regime_horizon": grouped,
        "dm_comparisons": dm,
        "revision_details": revision_detail,
        "revisions": revisions,
        "model_stability": stability,
        "target_revision_effects": target_revision_details,
        "target_revision_summary": target_revision_summary,
    }
    artifact_paths: dict[str, str] = {}
    for name, frame in artifact_frames.items():
        path = _write_frame(frame, generated / f"{name}.parquet", store=store)
        artifact_paths[name] = sha256_file(path)
    write_json(news, generated / "news_update.json")
    manifest = _base_manifest(config_path, raw, observations)
    manifest.update(
        {
            "artifact_stage": "backtest_complete",
            "models": list(default_model_ladder()),
            "evaluation_start": evaluation_start,
            "evaluation_end": evaluation_end,
            "forecast_count": predictions.height,
            "metric_rows": metrics.height,
            "feature_cell_count": vintage_long.height + revised_long.height,
            "target_revision_rows": target_revision_details.height,
            "artifact_sha256": artifact_paths,
            "supported_findings": [
                "strict timing invariants hold for the generated matrices",
                "the synthetic revised and vintage backtests are reproducibly distinct",
                "the fixed linear news attribution sums to the nowcast update",
            ],
            "unsupported_claims": [
                "actual U.S. macroeconomic forecast accuracy",
                "actual revision leakage magnitude",
                "policy, investment, or model-superiority conclusions",
            ],
        }
    )
    write_json(manifest, generated / "run_manifest.json")
    return {
        "fixture_label": FIXTURE_LABEL,
        "experiments": len(PRIMARY_EXPERIMENTS),
        "models": len(default_model_ladder()),
        "forecasts": predictions.height,
        "metric_rows": metrics.height,
        "asof_violations": 0,
        "output": str(generated),
    }


def _load_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(path)
    return json.loads(path.read_text())


def policy_brief(config_path: Path) -> dict[str, object]:
    paths = _paths(config_path)
    if not (paths["generated"] / "news_update.json").exists():
        backtest(config_path)
    manifest = _load_manifest(paths["generated"] / "run_manifest.json")
    news = _load_manifest(paths["generated"] / "news_update.json")
    destination = write_policy_brief(
        news,
        manifest,
        paths["root"] / "reports" / "sample_policy_brief.md",
    )
    generated_copy = write_policy_brief(
        news,
        manifest,
        paths["generated_reports"] / "sample_policy_brief.md",
    )
    return {
        "fixture_label": FIXTURE_LABEL,
        "attribution": news["attribution_label"],
        "brief": str(destination),
        "generated_copy": str(generated_copy),
    }


def report(config_path: Path) -> dict[str, object]:
    paths = _paths(config_path)
    generated = paths["generated"]
    if not (generated / "metrics.parquet").exists():
        backtest(config_path)
    manifest = _load_manifest(generated / "run_manifest.json")
    news = _load_manifest(generated / "news_update.json")
    written = write_required_reports(
        root=paths["root"],
        manifest=manifest,
        metrics=_read_required(generated / "metrics.parquet"),
        revisions=_read_required(generated / "revisions.parquet"),
        dm=_read_required(generated / "dm_comparisons.parquet"),
        grouped=_read_required(generated / "metrics_by_regime_horizon.parquet"),
        stability=_read_required(generated / "model_stability.parquet"),
        target_revision_summary=_read_required(
            generated / "target_revision_summary.parquet"
        ),
        news=news,
    )
    return {
        "fixture_label": FIXTURE_LABEL,
        "reports_written": len(written),
        "paths": ", ".join(str(path) for path in written),
    }


def reproduce_sample(config_path: Path) -> dict[str, object]:
    prepared = prepare_sample(config_path)
    built = build_vintages(config_path)
    validation = validate_asof(config_path)
    evaluated = backtest(config_path)
    brief = policy_brief(config_path)
    reports = report(config_path)
    return {
        "fixture_label": FIXTURE_LABEL,
        "network_used": prepared["network_used"],
        "series": prepared["series"],
        "vintage_rows": built["observation_rows"],
        "asof_violations": validation["future_information_violations"],
        "forecasts": evaluated["forecasts"],
        "policy_brief": brief["brief"],
        "reports_written": reports["reports_written"],
    }


def clean_generated(config_path: Path) -> dict[str, object]:
    """Remove only reproducible generated files after validating narrow targets."""

    _load_raw_config(config_path)
    paths = _paths(config_path)
    allowed = [paths["generated"].resolve(), paths["generated_reports"].resolve()]
    root = paths["root"].resolve()
    removed = 0
    for directory in allowed:
        if root not in directory.parents:
            raise RuntimeError(f"refusing to clean a path outside the project: {directory}")
        if not directory.exists():
            continue
        for path in sorted(directory.rglob("*"), reverse=True):
            if path.is_file() and path.name != ".gitkeep":
                path.unlink()
                removed += 1
            elif path.is_dir() and not any(path.iterdir()):
                path.rmdir()
    return {"removed_files": removed, "scope": ", ".join(str(path) for path in allowed)}
