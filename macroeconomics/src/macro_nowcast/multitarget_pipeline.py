"""Offline synthetic reproduction for payroll, core CPI, and real GDP targets."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
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
from macro_nowcast.asof import AS_OF_MODE, LATEST_SAME_MASK_MODE, NAIVE_LATEST_MODE
from macro_nowcast.attribution import linear_news_attribution
from macro_nowcast.calendar import build_forecast_origins
from macro_nowcast.evaluation import (
    diebold_mariano,
    regression_metrics,
    residual_prediction_interval,
    run_expanding_backtest,
)
from macro_nowcast.features import (
    FeatureSpec,
    assert_feature_no_future,
    build_feature_matrix,
    build_feature_vector,
)
from macro_nowcast.models import (
    DeterministicHistGradientBoostingRegressor,
    FixedElasticNetRegressor,
    default_model_ladder,
)
from macro_nowcast.multitarget_reporting import (
    write_multitarget_policy_briefs,
    write_multitarget_report,
)
from macro_nowcast.revisions import revision_details, revision_summary
from macro_nowcast.sample_data import build_multitarget_synthetic_fixture
from macro_nowcast.storage import VintageStore
from macro_nowcast.target_config import TargetConfigSet, TargetDefinition, load_target_config
from macro_nowcast.targets import assert_target_audit, build_targets

FIXTURE_LABEL = "synthetic_fixture"
DEFAULT_OUTPUT_SUBDIR = Path("data/generated/multitarget")
ARTIFACT_STAGE = "multitarget_backtest_complete"
FIXED_BUILD_TIMESTAMP = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)
PRIMARY_EXPERIMENTS = (
    ("vintage_aware", AS_OF_MODE, "first_release"),
    (LATEST_SAME_MASK_MODE, LATEST_SAME_MASK_MODE, "latest_revised"),
    (NAIVE_LATEST_MODE, NAIVE_LATEST_MODE, "latest_revised"),
)


def _utc_end_of_day(value: date) -> datetime:
    return datetime.combine(value, time(23, 59, 59, 999_999), tzinfo=UTC)


def _default_output_dir(config_path: Path) -> Path:
    parent = config_path.resolve().parent
    root = parent.parent if parent.name == "config" else Path.cwd()
    return root / DEFAULT_OUTPUT_SUBDIR


def _write_frame(
    frame: pl.DataFrame,
    output_dir: Path,
    name: str,
    store: VintageStore,
) -> Path:
    path = output_dir / f"{name}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.write_parquet(path, compression="zstd", statistics=True)
    store.register_view(path, table_name=name)
    return path


def _all_release_events(observations: pl.DataFrame) -> pl.DataFrame:
    """Build a complete synthetic initial/revision calendar from canonical rows."""

    ordered = observations.sort(
        ["series_id", "observation_date", "release_timestamp", "realtime_start"]
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
            "observation_date",
            "release_timestamp",
            pl.when(pl.col("revision_number") == 1)
            .then(pl.lit("initial"))
            .otherwise(pl.lit("revision"))
            .alias("release_type"),
            "revision_number",
            pl.lit("synthetic_exact").alias("timing_quality"),
            "source",
            "provenance_label",
        )
        .unique(subset=["release_id"], keep="first")
        .sort(["release_timestamp", "series_id", "observation_date"])
    )


def _runtime_feature_specs(target: TargetDefinition) -> tuple[FeatureSpec, ...]:
    return tuple(feature.to_feature_spec() for feature in target.features)


def _origins_for_target(
    all_origins: pl.DataFrame,
    target: TargetDefinition,
) -> pl.DataFrame:
    return all_origins.filter(pl.col("target_series_id") == target.series_id).with_columns(
        pl.lit(target.frequency).alias("target_frequency")
    )


def _wide_features(
    features: pl.DataFrame,
    feature_names: Sequence[str],
) -> pl.DataFrame:
    index = [
        "forecast_id",
        "target_series_id",
        "target_period",
        "target_frequency",
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
        pl.col("max_eligibility_availability").max().alias("max_eligibility_availability_ts"),
        pl.col("is_missing").sum().alias("missing_feature_count"),
        pl.col("is_partial_period").sum().alias("partial_feature_count"),
        pl.col("coverage_ratio").mean().alias("mean_feature_coverage_ratio"),
    )
    wide = pivot.join(audit, on="forecast_id", how="left", validate="1:1")
    for feature_name in feature_names:
        if feature_name not in wide.columns:
            wide = wide.with_columns(pl.lit(None, dtype=pl.Float64).alias(feature_name))
    return wide.select(
        *index,
        *feature_names,
        "max_source_availability_ts",
        "max_eligibility_availability_ts",
        "missing_feature_count",
        "partial_feature_count",
        "mean_feature_coverage_ratio",
    ).sort("target_period")


def _feature_leakage_audit(features: pl.DataFrame) -> pl.DataFrame:
    """Count selected-vintage and eligibility leakage by target and mode."""

    return (
        features.group_by(["target_series_id", "information_set_mode"])
        .agg(
            pl.len().alias("feature_cells"),
            (
                pl.col("max_source_availability") > pl.col("as_of_timestamp")
            ).sum().alias("selected_vintage_after_origin_cells"),
            (
                pl.col("max_eligibility_availability") > pl.col("as_of_timestamp")
            ).sum().alias("first_eligibility_after_origin_cells"),
            pl.col("is_missing").sum().alias("missing_feature_cells"),
        )
        .with_columns(
            (pl.col("information_set_mode") == AS_OF_MODE).alias(
                "valid_real_time_information_set"
            ),
            pl.when(pl.col("information_set_mode") == AS_OF_MODE)
            .then(pl.lit("valid historical information set"))
            .when(pl.col("information_set_mode") == LATEST_SAME_MASK_MODE)
            .then(pl.lit("value-revision counterfactual with historical eligibility mask"))
            .otherwise(pl.lit("intentionally leaky naive latest-revised benchmark"))
            .alias("research_purpose"),
            pl.lit(FIXTURE_LABEL).alias("fixture_label"),
        )
        .sort(["target_series_id", "information_set_mode"])
    )


def _research_dataset(
    wide: pl.DataFrame,
    targets: pl.DataFrame,
    target: TargetDefinition,
    *,
    data_mode: str,
    target_mode: str,
) -> pl.DataFrame:
    realization = targets.filter(
        (pl.col("target_series_id") == target.series_id)
        & (pl.col("realization_mode") == target_mode)
    ).select(
        "target_series_id",
        "target_period",
        "target_name",
        "target_frequency",
        "target_units",
        "target_formula",
        pl.col("value").alias("target_value"),
        "target_release_timestamp",
        "realization_as_of_timestamp",
        "max_source_availability",
        "realization_mode",
    )
    return (
        wide.join(
            realization,
            on=["target_series_id", "target_period", "target_frequency"],
            how="inner",
            validate="1:1",
        )
        .with_columns(
            pl.lit(data_mode).alias("data_mode"),
            pl.lit(FIXTURE_LABEL).alias("fixture_label"),
            pl.lit(target.horizon).cast(pl.Int64).alias("horizon"),
        )
        .sort("target_period")
    )


def _target_regime(period: date, frequency: str) -> str:
    period_index = period.year * 12 + period.month - 1
    span = 18 if frequency == "monthly" else 24
    return "synthetic_regime_a" if (period_index // span) % 2 == 0 else "synthetic_regime_b"


def _datetime64_to_utc(value: np.datetime64) -> datetime:
    if np.isnat(value):
        raise ValueError("audited forecast timestamps cannot be missing")
    nanoseconds = int(value.astype("datetime64[ns]").astype(np.int64))
    return datetime(1970, 1, 1, tzinfo=UTC) + np.timedelta64(nanoseconds, "ns").astype(
        "timedelta64[us]"
    ).astype(object)


def _model_ladder(min_train_periods: int) -> Mapping[str, Any]:
    models = dict(default_model_ladder())
    if min_train_periods < 20:
        models["hist_gradient_boosting"] = DeterministicHistGradientBoostingRegressor(
            min_train_samples=min_train_periods
        )
    return models


def _forecast_records(
    dataset: pl.DataFrame,
    target: TargetDefinition,
    feature_names: Sequence[str],
    *,
    model_name: str,
    estimator: Any,
) -> pl.DataFrame:
    regimes = [
        _target_regime(period, target.frequency) for period in dataset["target_period"].to_list()
    ]
    result = run_expanding_backtest(
        estimator,
        dataset.select(feature_names).to_numpy(),
        dataset["target_value"].to_numpy(),
        origins=dataset["as_of_timestamp"].to_list(),
        target_release_dates=dataset["target_release_timestamp"].to_list(),
        min_train_size=target.minimum_train_periods,
        horizon=[target.horizon] * dataset.height,
        regimes=regimes,
        model_name=model_name,
        interval_coverage_target=0.8,
        interval_min_residuals=min(12, target.minimum_train_periods),
    )
    target_periods = dataset["target_period"].to_list()
    rows: list[dict[str, object]] = []
    for record in result.records:
        rows.append(
            {
                "fold_id": record.fold,
                "row_index": record.row_index,
                "target_series_id": target.series_id,
                "target_name": target.name,
                "target_frequency": target.frequency,
                "target_units": target.units,
                "target_formula": target.formula,
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
    if not rows:
        return pl.DataFrame()
    return pl.DataFrame(rows).filter(
        (pl.col("target_period") >= target.evaluation_start)
        & (pl.col("target_period") <= target.evaluation_end)
    )


def _metric_values(frame: pl.DataFrame) -> dict[str, object]:
    actual = frame["actual"].to_numpy()
    values = regression_metrics(
        actual,
        frame["prediction"].to_numpy(),
        lower=frame["lower"].to_numpy(),
        upper=frame["upper"].to_numpy(),
    )
    finite_actual = actual[np.isfinite(actual)]
    direction_meaningful = np.unique(np.sign(finite_actual)).size > 1
    if not direction_meaningful:
        values["directional_accuracy"] = math.nan
    return {
        "n_forecasts": values.pop("n_obs"),
        **values,
        "directional_accuracy_meaningful": direction_meaningful,
        "sample_start": frame["target_period"].min(),
        "sample_end": frame["target_period"].max(),
    }


def _metrics(predictions: pl.DataFrame) -> tuple[pl.DataFrame, pl.DataFrame]:
    keys = ["target_series_id", "data_mode", "model_id"]
    rows: list[dict[str, object]] = []
    for key in predictions.select(keys).unique().iter_rows(named=True):
        subset = predictions.filter(
            (pl.col("target_series_id") == key["target_series_id"])
            & (pl.col("data_mode") == key["data_mode"])
            & (pl.col("model_id") == key["model_id"])
        )
        rows.append(
            {
                **key,
                "target_name": subset["target_name"][0],
                "target_frequency": subset["target_frequency"][0],
                "target_units": subset["target_units"][0],
                "target_formula": subset["target_formula"][0],
                "feature_mode": subset["feature_mode"][0],
                "target_mode": subset["target_mode"][0],
                "horizon": subset["horizon"][0],
                "fixture_label": FIXTURE_LABEL,
                **_metric_values(subset),
            }
        )
    metrics = pl.DataFrame(rows).sort(["target_series_id", "data_mode", "rmse", "model_id"])
    metrics = metrics.with_columns(
        pl.col("rmse")
        .rank("dense")
        .over(["target_series_id", "data_mode"])
        .cast(pl.Int64)
        .alias("rmse_rank")
    )

    group_keys = [
        "target_series_id",
        "target_name",
        "target_frequency",
        "target_units",
        "data_mode",
        "model_id",
        "horizon",
        "regime",
    ]
    grouped_rows: list[dict[str, object]] = []
    for key in predictions.select(group_keys).unique().iter_rows(named=True):
        condition = pl.lit(True)
        for name, value in key.items():
            condition &= pl.col(name) == value
        subset = predictions.filter(condition)
        grouped_rows.append({**key, "fixture_label": FIXTURE_LABEL, **_metric_values(subset)})
    grouped = pl.DataFrame(grouped_rows).sort(group_keys)
    return metrics, grouped


def _model_stability(predictions: pl.DataFrame, metrics: pl.DataFrame) -> pl.DataFrame:
    """Measure prediction and rank sensitivity to each revised-data counterfactual."""

    rows: list[dict[str, object]] = []
    target_models = predictions.select("target_series_id", "model_id").unique()
    for target_series_id, model_id in target_models.iter_rows():
        vintage = predictions.filter(
            (pl.col("target_series_id") == target_series_id)
            & (pl.col("model_id") == model_id)
            & (pl.col("data_mode") == "vintage_aware")
        ).select("target_period", pl.col("prediction").alias("vintage_prediction"))
        for comparison_mode in (LATEST_SAME_MASK_MODE, NAIVE_LATEST_MODE):
            comparison = predictions.filter(
                (pl.col("target_series_id") == target_series_id)
                & (pl.col("model_id") == model_id)
                & (pl.col("data_mode") == comparison_mode)
            ).select(
                "target_period",
                pl.col("prediction").alias("counterfactual_prediction"),
            )
            aligned = vintage.join(
                comparison,
                on="target_period",
                how="inner",
                validate="1:1",
            )
            if aligned.is_empty():
                continue
            first = aligned["vintage_prediction"].to_numpy()
            second = aligned["counterfactual_prediction"].to_numpy()
            correlation = (
                float(np.corrcoef(first, second)[0, 1])
                if aligned.height > 1 and np.std(first) > 0 and np.std(second) > 0
                else math.nan
            )
            rank_rows = metrics.filter(
                (pl.col("target_series_id") == target_series_id)
                & (pl.col("model_id") == model_id)
            )
            vintage_rank = rank_rows.filter(pl.col("data_mode") == "vintage_aware")[
                "rmse_rank"
            ][0]
            counterfactual_rank = rank_rows.filter(
                pl.col("data_mode") == comparison_mode
            )["rmse_rank"][0]
            metadata = predictions.filter(
                pl.col("target_series_id") == target_series_id
            ).row(0, named=True)
            rows.append(
                {
                    "target_series_id": target_series_id,
                    "target_name": metadata["target_name"],
                    "target_frequency": metadata["target_frequency"],
                    "target_units": metadata["target_units"],
                    "model_id": model_id,
                    "comparison_mode": comparison_mode,
                    "n_aligned": aligned.height,
                    "prediction_correlation": correlation,
                    "mean_abs_prediction_difference": float(
                        np.mean(np.abs(second - first))
                    ),
                    "vintage_rmse_rank": vintage_rank,
                    "counterfactual_rmse_rank": counterfactual_rank,
                    "rank_change": int(counterfactual_rank - vintage_rank),
                    "fixture_label": FIXTURE_LABEL,
                }
            )
    return pl.DataFrame(rows).sort(
        ["target_series_id", "comparison_mode", "model_id"]
    )


def _dm_comparisons(predictions: pl.DataFrame) -> pl.DataFrame:
    rows: list[dict[str, object]] = []
    modes = predictions.select("target_series_id", "data_mode").unique()
    for target_series_id, data_mode in modes.iter_rows():
        mode_frame = predictions.filter(
            (pl.col("target_series_id") == target_series_id) & (pl.col("data_mode") == data_mode)
        )
        baseline = mode_frame.filter(pl.col("model_id") == "historical_mean").select(
            "target_period",
            "actual",
            pl.col("prediction").alias("baseline_prediction"),
        )
        for model_name in mode_frame["model_id"].unique().sort().to_list():
            if model_name == "historical_mean":
                continue
            aligned = baseline.join(
                mode_frame.filter(pl.col("model_id") == model_name).select(
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
            metadata = mode_frame.row(0, named=True)
            rows.append(
                {
                    "target_series_id": target_series_id,
                    "target_name": metadata["target_name"],
                    "target_frequency": metadata["target_frequency"],
                    "target_units": metadata["target_units"],
                    "data_mode": data_mode,
                    "baseline_model": "historical_mean",
                    "comparison_model": model_name,
                    "statistic": result.statistic,
                    "p_value": result.p_value,
                    "mean_loss_differential": result.mean_loss_differential,
                    "n_obs": result.n_obs,
                    "valid": result.valid,
                    "status": "valid_synthetic_diagnostic"
                    if result.valid
                    else "insufficient_or_invalid",
                    "reason": result.reason,
                    "fixture_label": FIXTURE_LABEL,
                }
            )
    return pl.DataFrame(rows).sort(["target_series_id", "data_mode", "comparison_model"])


def _target_revision_effects(
    targets: pl.DataFrame,
    predictions: pl.DataFrame,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    revisions = (
        targets.select(
            "target_series_id",
            "target_period",
            "target_name",
            "target_frequency",
            "target_units",
            "realization_mode",
            "value",
        )
        .pivot(
            on="realization_mode",
            index=[
                "target_series_id",
                "target_period",
                "target_name",
                "target_frequency",
                "target_units",
            ],
            values="value",
            aggregate_function="first",
        )
        .drop_nulls(["first_release", "latest_revised"])
        .with_columns((pl.col("latest_revised") - pl.col("first_release")).alias("target_revision"))
        .with_columns(pl.col("target_revision").abs().alias("absolute_target_revision"))
    )
    detailed = (
        predictions.filter(pl.col("data_mode") == "vintage_aware")
        .join(
            revisions,
            on=[
                "target_series_id",
                "target_period",
                "target_name",
                "target_frequency",
                "target_units",
            ],
            how="inner",
            validate="m:1",
        )
        .with_columns(
            (pl.col("prediction") - pl.col("first_release")).alias("forecast_error_first_release"),
            (pl.col("prediction") - pl.col("latest_revised")).alias(
                "forecast_error_latest_revised"
            ),
        )
        .with_columns(
            pl.col("forecast_error_first_release").abs().alias("absolute_error_first_release"),
            pl.col("forecast_error_latest_revised").abs().alias("absolute_error_latest_revised"),
        )
    )
    summary = (
        detailed.group_by(
            [
                "target_series_id",
                "target_name",
                "target_frequency",
                "target_units",
                "model_id",
            ]
        )
        .agg(
            pl.len().alias("n_forecasts"),
            pl.col("absolute_error_first_release").mean().alias("mae_first_release"),
            pl.col("absolute_error_latest_revised").mean().alias("mae_latest_revised"),
            pl.col("target_revision").mean().alias("mean_target_revision"),
            pl.col("absolute_target_revision").mean().alias("mean_abs_target_revision"),
            (pl.col("absolute_error_latest_revised") - pl.col("absolute_error_first_release"))
            .mean()
            .alias("mean_change_in_absolute_error_due_to_target_revision"),
        )
        .with_columns(pl.lit(FIXTURE_LABEL).alias("fixture_label"))
        .sort(["target_series_id", "model_id"])
    )
    return detailed.sort(["target_series_id", "model_id", "target_period"]), summary


def _feature_maps(frame: pl.DataFrame) -> dict[str, float | None]:
    return dict(
        zip(
            frame["feature_name"].to_list(),
            frame["value"].to_list(),
            strict=True,
        )
    )


def _values_differ(first: float | None, second: float | None) -> bool:
    if first is None and second is None:
        return False
    if first is None or second is None:
        return True
    if math.isnan(first) and math.isnan(second):
        return False
    return not math.isclose(first, second, rel_tol=0.0, abs_tol=1e-12)


def _release_feature_update(
    observations: pl.DataFrame,
    release_events: pl.DataFrame,
    target: TargetDefinition,
    *,
    target_period: date,
    target_release_timestamp: datetime,
) -> tuple[dict[str, object], pl.DataFrame, pl.DataFrame]:
    """Find the latest pre-target release that changes a configured feature."""

    specs = _runtime_feature_specs(target)
    feature_series = [spec.series_id for spec in specs]
    series_frequencies = observations.group_by("series_id").agg(
        pl.col("frequency").first().alias("release_series_frequency")
    )
    candidates = (
        release_events.filter(
            pl.col("series_id").is_in(feature_series)
            & (pl.col("release_timestamp") < pl.lit(target_release_timestamp))
        )
        .join(series_frequencies, on="series_id", how="left", validate="m:1")
        .with_columns(
            (pl.col("series_id") == target.series_id)
            .cast(pl.Int8)
            .alias("target_series_priority"),
            pl.when(pl.col("release_series_frequency").is_in(["monthly", "quarterly"]))
            .then(pl.lit(0))
            .when(pl.col("release_series_frequency") == "weekly")
            .then(pl.lit(1))
            .otherwise(pl.lit(2))
            .cast(pl.Int8)
            .alias("frequency_priority"),
        )
        .sort(
            ["target_series_priority", "frequency_priority", "release_timestamp"],
            descending=[False, False, True],
        )
        .head(300)
    )
    for event in candidates.iter_rows(named=True):
        release_timestamp = event["release_timestamp"]
        previous_timestamp = release_timestamp - timedelta(microseconds=1)
        updated_timestamp = release_timestamp + timedelta(microseconds=1)
        previous = build_feature_vector(
            observations,
            as_of=previous_timestamp,
            target_period=target_period,
            specs=specs,
            mode=AS_OF_MODE,
            target_series_id=target.series_id,
            target_frequency=target.frequency,
        )
        updated = build_feature_vector(
            observations,
            as_of=updated_timestamp,
            target_period=target_period,
            specs=specs,
            mode=AS_OF_MODE,
            target_series_id=target.series_id,
            target_frequency=target.frequency,
        )
        previous_map = _feature_maps(previous)
        updated_map = _feature_maps(updated)
        changed = [
            name
            for name in previous_map
            if _values_differ(previous_map[name], updated_map[name])
        ]
        if changed:
            return {**event, "changed_features": changed}, previous, updated
    raise RuntimeError(
        f"no configured pre-release feature update found for {target.series_id} {target_period}"
    )


def _historical_update_comparison(
    predictions: pl.DataFrame,
    *,
    absolute_update: float,
) -> dict[str, object]:
    ordered = predictions.sort("target_period")["prediction"].to_numpy()
    movements = np.abs(np.diff(ordered))
    movements = movements[np.isfinite(movements)]
    if movements.size == 0:
        return {
            "comparison_kind": "absolute consecutive OOS nowcast movements",
            "n_comparisons": 0,
            "percentile": None,
            "median_absolute_movement": None,
            "interpretation": "insufficient prior synthetic forecasts",
        }
    percentile = float(np.mean(movements <= absolute_update) * 100.0)
    return {
        "comparison_kind": "absolute consecutive OOS nowcast movements",
        "n_comparisons": int(movements.size),
        "percentile": percentile,
        "median_absolute_movement": float(np.median(movements)),
        "interpretation": (
            "fixture-only descriptive scale; not a like-for-like historical release study"
        ),
    }


def _news_updates(
    observations: pl.DataFrame,
    target_release_calendar: pl.DataFrame,
    release_events: pl.DataFrame,
    research: pl.DataFrame,
    predictions: pl.DataFrame,
    targets_config: TargetConfigSet,
) -> list[dict[str, object]]:
    """Generate one frozen-linear-model release update for each configured target."""

    updates: list[dict[str, object]] = []
    for target in targets_config.targets:
        target_period = target.evaluation_end
        target_release = target_release_calendar.filter(
            (pl.col("series_id") == target.series_id)
            & (pl.col("observation_date") == target_period)
            & (pl.col("release_type") == "initial")
        )
        if target_release.height != 1:
            raise RuntimeError(
                f"expected one initial target release for {target.series_id} {target_period}"
            )
        target_release_timestamp = target_release["release_timestamp"][0]
        event, previous_long, updated_long = _release_feature_update(
            observations,
            release_events,
            target,
            target_period=target_period,
            target_release_timestamp=target_release_timestamp,
        )
        feature_names = tuple(feature.name for feature in target.features)
        previous_map = _feature_maps(previous_long)
        updated_map = _feature_maps(updated_long)
        training = research.filter(
            (pl.col("target_series_id") == target.series_id)
            & (pl.col("data_mode") == "vintage_aware")
            & (pl.col("target_period") < pl.lit(target_period))
        ).sort("target_period")
        model = FixedElasticNetRegressor()
        model.fit(
            training.select(feature_names).to_numpy(),
            training["target_value"].to_numpy(),
        )
        attribution = linear_news_attribution(
            model,
            previous_map,
            updated_map,
            feature_names=feature_names,
        )
        prior_predictions = predictions.filter(
            (pl.col("target_series_id") == target.series_id)
            & (pl.col("data_mode") == "vintage_aware")
            & (pl.col("model_id") == "elastic_net")
            & (pl.col("target_release_ts") <= pl.lit(event["release_timestamp"]))
        ).sort("target_period")
        residuals = (
            prior_predictions["actual"] - prior_predictions["prediction"]
            if prior_predictions.height
            else pl.Series([], dtype=pl.Float64)
        )
        lower, upper = residual_prediction_interval(
            [attribution.updated_prediction],
            residuals.to_numpy(),
            coverage=0.8,
            min_residuals=min(12, target.minimum_train_periods),
        )
        contributions = [
            {
                "feature": name,
                "contribution": value,
                "target_units": target.units,
                "previous_value": previous_map.get(name),
                "updated_value": updated_map.get(name),
            }
            for name, value in sorted(
                attribution.contributions.items(),
                key=lambda item: abs(item[1]),
                reverse=True,
            )
        ]
        direction = (
            "increased"
            if attribution.total_change > 0
            else "decreased"
            if attribution.total_change < 0
            else "was unchanged"
        )
        updates.append(
            {
                "fixture_label": FIXTURE_LABEL,
                "empirical_finding": False,
                "target_series_id": target.series_id,
                "target_name": target.name,
                "target_frequency": target.frequency,
                "target_units": target.units,
                "target_formula": target.formula,
                "horizon": target.horizon,
                "target_period": target_period,
                "target_release_timestamp": target_release_timestamp,
                "data_mode": "vintage_aware",
                "model_id": "elastic_net",
                "release_name": (
                    f"Synthetic {event['series_id']} {event['release_type']} release"
                ),
                "release_id": event["release_id"],
                "release_series_id": event["series_id"],
                "release_series_frequency": event["release_series_frequency"],
                "release_observation_date": event["observation_date"],
                "release_type": event["release_type"],
                "release_ts": event["release_timestamp"],
                "previous_as_of_ts": event["release_timestamp"]
                - timedelta(microseconds=1),
                "updated_as_of_ts": event["release_timestamp"]
                + timedelta(microseconds=1),
                "changed_features": event["changed_features"],
                "previous_nowcast": attribution.previous_prediction,
                "updated_nowcast": attribution.updated_prediction,
                "forecast_revision": attribution.total_change,
                "assessment": (
                    f"The frozen synthetic {target.name} nowcast {direction} by "
                    f"{abs(attribution.total_change):.4f} {target.units}."
                ),
                "attribution_method": attribution.method,
                "attribution_label": attribution.label,
                "attribution_approximate": attribution.approximate,
                "unattributed_residual": attribution.unattributed_residual,
                "contributions": contributions,
                "interval": {
                    "coverage": 0.8,
                    "lower": None if np.isnan(lower[0]) else float(lower[0]),
                    "upper": None if np.isnan(upper[0]) else float(upper[0]),
                    "residual_count": residuals.len(),
                },
                "historical_comparison": _historical_update_comparison(
                    prior_predictions,
                    absolute_update=abs(attribution.total_change),
                ),
                "interpretation": (
                    "mechanical frozen-model update on a deterministic fixture; "
                    "not causal, empirical, monetary-policy, or investment evidence"
                ),
            }
        )
    return updates


def _target_manifest(targets: TargetConfigSet) -> list[dict[str, object]]:
    return [
        {
            "target_series_id": target.series_id,
            "target_name": target.name,
            "target_frequency": target.frequency,
            "target_units": target.units,
            "target_formula": target.formula,
            "transformation": target.transformation,
            "annualization": target.annualization,
            "annualization_factor": target.annualization_factor,
            "horizon": target.horizon,
            "evaluation_start": target.evaluation_start,
            "evaluation_end": target.evaluation_end,
            "latest_vintage": target.latest_vintage,
            "minimum_train_periods": target.minimum_train_periods,
            "feature_names": [feature.name for feature in target.features],
        }
        for target in targets.targets
    ]


def _manifest(
    config_path: Path,
    targets_config: TargetConfigSet,
    observations: pl.DataFrame,
    *,
    artifact_hashes: Mapping[str, str],
    predictions: pl.DataFrame,
    metrics: pl.DataFrame,
    origins: pl.DataFrame,
    feature_cells: int,
    target_rows: int,
    naive_leakage_cells: int,
    release_update_count: int,
    policy_brief_count: int,
) -> dict[str, Any]:
    configuration_hash = config_hash(config_path)
    observation_hash = frame_hash(observations)
    return {
        "artifact_stage": ARTIFACT_STAGE,
        "status": "complete",
        "run_id": f"synthetic-multitarget-{configuration_hash[:10]}-{observation_hash[:10]}",
        "fixture_label": FIXTURE_LABEL,
        "synthetic_fixture": True,
        "empirical_findings_supported": False,
        "network_used": False,
        "fred_api_accessed": False,
        "bls_api_accessed": False,
        "bea_api_accessed": False,
        "api_txt_read": False,
        "config_sha256": configuration_hash,
        "observation_frame_sha256": observation_hash,
        "artifact_sha256": dict(artifact_hashes),
        "built_at": FIXED_BUILD_TIMESTAMP,
        "target_series_ids": [target.series_id for target in targets_config.targets],
        "target_definitions": _target_manifest(targets_config),
        "series": observations["series_id"].unique().sort().to_list(),
        "series_count": observations["series_id"].n_unique(),
        "vintage_row_count": observations.height,
        "forecast_origin_count": origins.height,
        "feature_cell_count": feature_cells,
        "target_row_count": target_rows,
        "forecast_count": predictions.height,
        "metric_rows": metrics.height,
        "models": sorted(predictions["model_id"].unique().to_list()),
        "model_count": predictions["model_id"].n_unique(),
        "feature_modes": [AS_OF_MODE, LATEST_SAME_MASK_MODE, NAIVE_LATEST_MODE],
        "target_modes": ["first_release", "latest_revised"],
        "timing_violations": 0,
        "naive_first_eligibility_after_origin_cells": naive_leakage_cells,
        "release_update_count": release_update_count,
        "policy_brief_count": policy_brief_count,
        "release_timing_precision": "synthetic_exact_utc",
        "package_versions": package_versions(),
        "supported_findings": [
            "configured target formulas and timing invariants execute reproducibly",
            "monthly-to-quarterly coverage and staleness remain audited",
            "synthetic vintage and fixed-latest experiments remain separately labeled",
            "the intentionally leaky naive benchmark is separately labeled and counted",
            "frozen linear release attribution and briefs execute for every configured target",
        ],
        "unsupported_claims": [
            "actual U.S. forecast accuracy or revision magnitude",
            "cross-target or within-target model superiority",
            "economic-regime, investment, monetary-policy, or causal conclusions",
        ],
    }


def reproduce_multitarget(
    config_path: Path,
    *,
    output_dir: Path | None = None,
) -> dict[str, object]:
    """Run the deterministic three-target offline workflow and persist artifacts."""

    config_path = config_path.resolve()
    targets_config = load_target_config(config_path)
    destination = (
        _default_output_dir(config_path)
        if output_dir is None
        else output_dir.expanduser().resolve()
    )
    destination.mkdir(parents=True, exist_ok=True)

    fixture = build_multitarget_synthetic_fixture()
    observations = fixture.observations
    target_release_calendar = fixture.all_target_release_calendar
    release_events = _all_release_events(observations)
    raw_origins = build_forecast_origins(target_release_calendar)

    feature_frames: list[pl.DataFrame] = []
    wide_frames: list[pl.DataFrame] = []
    target_frames: list[pl.DataFrame] = []
    origin_frames: list[pl.DataFrame] = []
    research_frames: list[pl.DataFrame] = []
    prediction_frames: list[pl.DataFrame] = []

    for target in targets_config.targets:
        latest_cutoff = _utc_end_of_day(target.latest_vintage)
        origins = _origins_for_target(raw_origins, target).filter(
            pl.col("target_release_timestamp") <= pl.lit(latest_cutoff)
        )
        origin_frames.append(origins)
        specs = _runtime_feature_specs(target)
        feature_names = tuple(spec.name for spec in specs)

        vintage_long = build_feature_matrix(
            observations,
            origins,
            specs=specs,
            mode=AS_OF_MODE,
            target_frequency=target.frequency,
        )
        fixed_latest_observations = observations.filter(
            pl.col("availability_timestamp") <= pl.lit(latest_cutoff)
        )
        latest_long = build_feature_matrix(
            fixed_latest_observations,
            origins,
            specs=specs,
            mode=LATEST_SAME_MASK_MODE,
            target_frequency=target.frequency,
        )
        naive_latest_long = build_feature_matrix(
            fixed_latest_observations,
            origins,
            specs=specs,
            mode=NAIVE_LATEST_MODE,
            target_frequency=target.frequency,
        )
        assert_feature_no_future(vintage_long)
        assert_feature_no_future(latest_long)
        assert_feature_no_future(naive_latest_long)
        feature_frames.extend([vintage_long, latest_long, naive_latest_long])

        target_rows = build_targets(
            observations,
            target_release_calendar,
            latest_as_of=latest_cutoff,
            specs=(target.to_target_spec(),),
            built_at=FIXED_BUILD_TIMESTAMP,
        )
        assert_target_audit(target_rows)
        target_frames.append(target_rows)

        wide_by_mode = {
            AS_OF_MODE: _wide_features(vintage_long, feature_names),
            LATEST_SAME_MASK_MODE: _wide_features(latest_long, feature_names),
            NAIVE_LATEST_MODE: _wide_features(naive_latest_long, feature_names),
        }
        wide_frames.extend(wide_by_mode.values())
        target_datasets: list[pl.DataFrame] = []
        for data_mode, feature_mode, target_mode in PRIMARY_EXPERIMENTS:
            dataset = _research_dataset(
                wide_by_mode[feature_mode],
                target_rows,
                target,
                data_mode=data_mode,
                target_mode=target_mode,
            )
            research_frames.append(dataset)
            target_datasets.append(dataset)

        for dataset in target_datasets:
            for model_name, estimator in _model_ladder(target.minimum_train_periods).items():
                records = _forecast_records(
                    dataset,
                    target,
                    feature_names,
                    model_name=model_name,
                    estimator=estimator,
                )
                if not records.is_empty():
                    prediction_frames.append(records)

    if not prediction_frames:
        raise RuntimeError("multi-target backtest produced no out-of-sample forecasts")

    origins = pl.concat(origin_frames, how="diagonal_relaxed").sort(
        ["target_series_id", "target_period"]
    )
    features = pl.concat(feature_frames, how="vertical").sort(
        ["target_series_id", "target_period", "information_set_mode", "feature_name"]
    )
    wide_features = pl.concat(wide_frames, how="diagonal_relaxed").sort(
        ["target_series_id", "target_period", "information_set_mode"]
    )
    targets = pl.concat(target_frames, how="vertical").sort(
        ["target_series_id", "target_period", "realization_mode"]
    )
    research = pl.concat(research_frames, how="diagonal_relaxed").sort(
        ["target_series_id", "data_mode", "target_period"]
    )
    predictions = pl.concat(prediction_frames, how="diagonal_relaxed").sort(
        ["target_series_id", "data_mode", "model_id", "target_period"]
    )
    leakage_audit = _feature_leakage_audit(features)
    strict_leakage = leakage_audit.filter(
        pl.col("information_set_mode").is_in([AS_OF_MODE, LATEST_SAME_MASK_MODE])
        & (pl.col("first_eligibility_after_origin_cells") > 0)
    )
    if strict_leakage.height:
        raise AssertionError("a strict information-set mode contains future eligibility")
    naive_leakage_cells = int(
        leakage_audit.filter(pl.col("information_set_mode") == NAIVE_LATEST_MODE)[
            "first_eligibility_after_origin_cells"
        ].sum()
    )
    if naive_leakage_cells <= 0:
        raise AssertionError("naive revised-data benchmark did not expose timing leakage")
    metrics, grouped_metrics = _metrics(predictions)
    stability = _model_stability(predictions, metrics)
    dm = _dm_comparisons(predictions)
    target_revision_details, target_revision_summary = _target_revision_effects(
        targets,
        predictions,
    )
    raw_revision_details = revision_details(observations)
    revisions = revision_summary(observations)
    news_updates = _news_updates(
        observations,
        target_release_calendar,
        release_events,
        research,
        predictions,
        targets_config,
    )

    store = VintageStore(destination, destination / "macro_nowcast.duckdb")
    artifact_frames = {
        "observations": observations,
        "series_catalog": fixture.series_metadata,
        "target_release_calendar": target_release_calendar,
        "release_calendar": release_events,
        "forecast_origins": origins,
        "features_long": features,
        "feature_leakage_audit": leakage_audit,
        "features_wide": wide_features,
        "targets": targets,
        "research_datasets": research,
        "predictions": predictions,
        "metrics": metrics,
        "metrics_by_regime_horizon": grouped_metrics,
        "model_stability": stability,
        "dm_comparisons": dm,
        "revision_details": raw_revision_details,
        "revisions": revisions,
        "target_revision_effects": target_revision_details,
        "target_revision_summary": target_revision_summary,
    }
    artifact_hashes: dict[str, str] = {}
    for name, frame in artifact_frames.items():
        path = _write_frame(frame, destination, name, store)
        artifact_hashes[f"{name}.parquet"] = sha256_file(path)

    news_path = write_json(
        {
            "fixture_label": FIXTURE_LABEL,
            "empirical_findings_supported": False,
            "updates": news_updates,
        },
        destination / "news_updates.json",
    )
    artifact_hashes["news_updates.json"] = sha256_file(news_path)

    manifest = _manifest(
        config_path,
        targets_config,
        observations,
        artifact_hashes=artifact_hashes,
        predictions=predictions,
        metrics=metrics,
        origins=origins,
        feature_cells=features.height,
        target_rows=targets.height,
        naive_leakage_cells=naive_leakage_cells,
        release_update_count=len(news_updates),
        policy_brief_count=len(news_updates),
    )
    manifest_path = write_json(manifest, destination / "run_manifest.json")
    brief_paths = write_multitarget_policy_briefs(
        news_updates,
        manifest,
        destination / "policy_briefs",
    )
    for path in brief_paths:
        relative = path.relative_to(destination).as_posix()
        manifest["artifact_sha256"][relative] = sha256_file(path)
    manifest["policy_brief_paths"] = [
        path.relative_to(destination).as_posix() for path in brief_paths
    ]
    report_path = write_multitarget_report(
        manifest,
        metrics,
        dm,
        target_revision_summary,
        destination / "multitarget_report.md",
        model_stability=stability,
        leakage_audit=leakage_audit,
    )
    manifest["artifact_sha256"]["multitarget_report.md"] = sha256_file(report_path)
    write_json(manifest, manifest_path)

    return {
        "status": "complete",
        "artifact_stage": ARTIFACT_STAGE,
        "fixture_label": FIXTURE_LABEL,
        "network_used": False,
        "targets": len(targets_config.targets),
        "series": observations["series_id"].n_unique(),
        "vintage_rows": observations.height,
        "forecast_origins": origins.height,
        "feature_cells": features.height,
        "target_rows": targets.height,
        "models": predictions["model_id"].n_unique(),
        "forecasts": predictions.height,
        "metric_rows": metrics.height,
        "timing_violations": 0,
        "naive_leakage_cells": naive_leakage_cells,
        "release_updates": len(news_updates),
        "policy_briefs": len(brief_paths),
        "output": str(destination),
    }


__all__ = ["reproduce_multitarget"]
