"""Reproducible empirical pilot using audited official agency archives.

The pilot combines target lags and cross-target values with eight genuine BLS CES
sector-employment publication-vintage matrices, genuine BLS CPS unemployment-rate
release snapshots, genuine DOL weekly initial-claims releases, Federal Reserve G.17
industrial-production snapshots, official daily Treasury 10-year CMT observations,
Census MARTS retail-sales releases, and Census NRC housing-start releases. It still does
not imply that the full cross-agency configured indicator set has genuine vintages.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import numpy as np
import polars as pl

from macro_nowcast.archive_ingestion import (
    CES_SECTOR_PREDICTOR_SPECS,
    UNEMPLOYMENT_RATE_SERIES_ID,
)
from macro_nowcast.artifacts import package_versions, sha256_file, write_json
from macro_nowcast.asof import AS_OF_MODE, LATEST_SAME_MASK_MODE, NAIVE_LATEST_MODE
from macro_nowcast.attribution import linear_news_attribution
from macro_nowcast.bea_nipa_archive import BEA_NIPA_LEVEL_SERIES_ID
from macro_nowcast.calendar import DATE_ONLY_TIMING_QUALITY, build_forecast_origins
from macro_nowcast.census_housing_archive import CENSUS_HOUSING_STARTS_SERIES_ID
from macro_nowcast.census_retail_archive import (
    CENSUS_RETAIL_LEVEL_SERIES_ID,
    CENSUS_RETAIL_MOM_SERIES_ID,
)
from macro_nowcast.dol_claims_archive import (
    DOL_CLAIMS_4WMA_SERIES_ID,
    DOL_CLAIMS_SERIES_ID,
)
from macro_nowcast.evaluation import (
    diebold_mariano,
    regression_metrics,
    residual_prediction_interval,
    run_expanding_backtest,
)
from macro_nowcast.features import FeatureSpec, assert_feature_no_future, build_feature_vector
from macro_nowcast.fed_g17_archive import FED_G17_INDEX_SERIES_ID, FED_G17_MOM_SERIES_ID
from macro_nowcast.models import (
    DeterministicHistGradientBoostingRegressor,
    FixedElasticNetRegressor,
    default_model_ladder,
)
from macro_nowcast.regimes import (
    NBER_REGIME_DEFINITION,
    NBER_REGIME_SOURCE_LAST_UPDATED,
    NBER_REGIME_SOURCE_URL,
    NBER_REGIME_VERIFIED_AT,
    nber_regime,
)
from macro_nowcast.revisions import revision_details, revision_summary
from macro_nowcast.storage import VintageStore
from macro_nowcast.targets import (
    CORE_CPI_TARGET_SPEC,
    PAYEMS_TARGET_SPEC,
    PUBLISHED_REAL_GDP_TARGET_SPEC,
    TargetSpec,
    assert_target_audit,
    build_targets,
)
from macro_nowcast.treasury_rates_archive import (
    TREASURY_10Y_SERIES_ID,
    TREASURY_RATES_AVAILABILITY_RULE,
    TREASURY_RATES_TIMING_QUALITY,
)

OFFICIAL_PROVENANCE = "official_agency_archive"
ARTIFACT_STAGE = "official_archive_empirical_pilot_complete"
DEFAULT_SOURCE_DIR = Path("data/generated/official_vintages")
DEFAULT_OUTPUT_DIR = Path("data/generated/official_pilot")
EXPERIMENTS = (
    ("vintage_aware", AS_OF_MODE, "first_release"),
    (LATEST_SAME_MASK_MODE, LATEST_SAME_MASK_MODE, "latest_revised"),
    (NAIVE_LATEST_MODE, NAIVE_LATEST_MODE, "latest_revised"),
)
ELASTIC_NET_TUNING_GRID: tuple[dict[str, float], ...] = (
    {"alpha": 0.01, "l1_ratio": 0.2},
    {"alpha": 0.01, "l1_ratio": 0.8},
    {"alpha": 0.05, "l1_ratio": 0.2},
    {"alpha": 0.05, "l1_ratio": 0.8},
    {"alpha": 0.2, "l1_ratio": 0.2},
    {"alpha": 0.2, "l1_ratio": 0.8},
)
HIST_GRADIENT_BOOSTING_TUNING_GRID: tuple[dict[str, float | int], ...] = (
    {"learning_rate": 0.03, "max_leaf_nodes": 7, "l2_regularization": 1.0},
    {"learning_rate": 0.05, "max_leaf_nodes": 7, "l2_regularization": 1.0},
    {"learning_rate": 0.05, "max_leaf_nodes": 15, "l2_regularization": 1.0},
    {"learning_rate": 0.05, "max_leaf_nodes": 7, "l2_regularization": 5.0},
)


@dataclass(frozen=True, slots=True)
class OfficialPilotTarget:
    output_series_id: str
    calendar_series_id: str
    frequency: Literal["monthly", "quarterly"]
    target_spec: TargetSpec
    feature_specs: tuple[FeatureSpec, ...]
    min_train_size: int
    horizons: tuple[int, ...] = (0,)
    tuning_periods: int = 0
    final_evaluation_periods: int = 0

    def __post_init__(self) -> None:
        if not self.horizons or any(horizon < 0 for horizon in self.horizons):
            raise ValueError("official pilot horizons must be nonempty and nonnegative")
        if len(set(self.horizons)) != len(self.horizons):
            raise ValueError("official pilot horizons must be unique")
        if self.tuning_periods < 0 or self.final_evaluation_periods < 0:
            raise ValueError("official tuning/evaluation periods must be nonnegative")

    @property
    def feature_names(self) -> tuple[str, ...]:
        return tuple(spec.name for spec in self.feature_specs)


PILOT_TARGETS = (
    OfficialPilotTarget(
        output_series_id="PAYEMS",
        calendar_series_id="PAYEMS",
        frequency="monthly",
        target_spec=PAYEMS_TARGET_SPEC,
        feature_specs=(
            FeatureSpec(
                "payems_change_lag1",
                "PAYEMS",
                "monthly",
                "difference",
                "latest",
                lag_periods=1,
            ),
            FeatureSpec(
                "payems_change_lag2",
                "PAYEMS",
                "monthly",
                "difference",
                "latest",
                lag_periods=2,
            ),
            FeatureSpec(
                "core_cpi_change_lag1",
                "CPILFESL",
                "monthly",
                "percent_change",
                "latest",
                lag_periods=1,
            ),
            FeatureSpec(
                "unemployment_rate_lag1",
                UNEMPLOYMENT_RATE_SERIES_ID,
                "monthly",
                "level",
                "latest",
                lag_periods=1,
            ),
            FeatureSpec(
                "initial_claims_4w_mean",
                DOL_CLAIMS_4WMA_SERIES_ID,
                "weekly",
                "level",
                "latest",
            ),
            FeatureSpec(
                "treasury_10y_20d_mean",
                TREASURY_10Y_SERIES_ID,
                "daily",
                "level",
                "trailing_mean",
                window=20,
            ),
            FeatureSpec(
                "industrial_production_mom_lag1",
                FED_G17_MOM_SERIES_ID,
                "monthly",
                "level",
                "latest",
                lag_periods=1,
            ),
            FeatureSpec(
                "retail_sales_mom_lag1",
                CENSUS_RETAIL_MOM_SERIES_ID,
                "monthly",
                "level",
                "latest",
                lag_periods=1,
            ),
            FeatureSpec(
                "housing_starts_log_change_lag1",
                CENSUS_HOUSING_STARTS_SERIES_ID,
                "monthly",
                "log_change",
                "latest",
                lag_periods=1,
            ),
            FeatureSpec(
                "construction_employment_change_lag1",
                "CES2000000001",
                "monthly",
                "difference",
                "latest",
                lag_periods=1,
            ),
            FeatureSpec(
                "manufacturing_employment_change_lag1",
                "CES3000000001",
                "monthly",
                "difference",
                "latest",
                lag_periods=1,
            ),
            FeatureSpec(
                "trade_transport_utilities_employment_change_lag1",
                "CES4000000001",
                "monthly",
                "difference",
                "latest",
                lag_periods=1,
            ),
            FeatureSpec(
                "professional_business_employment_change_lag1",
                "CES6000000001",
                "monthly",
                "difference",
                "latest",
                lag_periods=1,
            ),
            FeatureSpec(
                "leisure_hospitality_employment_change_lag1",
                "CES7000000001",
                "monthly",
                "difference",
                "latest",
                lag_periods=1,
            ),
        ),
        min_train_size=60,
        horizons=(0, 1),
        tuning_periods=24,
        final_evaluation_periods=24,
    ),
    OfficialPilotTarget(
        output_series_id="CPILFESL",
        calendar_series_id="CPILFESL",
        frequency="monthly",
        target_spec=CORE_CPI_TARGET_SPEC,
        feature_specs=(
            FeatureSpec(
                "core_cpi_change_lag1",
                "CPILFESL",
                "monthly",
                "percent_change",
                "latest",
                lag_periods=1,
            ),
            FeatureSpec(
                "core_cpi_change_lag2",
                "CPILFESL",
                "monthly",
                "percent_change",
                "latest",
                lag_periods=2,
            ),
            FeatureSpec(
                "payems_change_current",
                "PAYEMS",
                "monthly",
                "difference",
                "latest",
            ),
            FeatureSpec(
                "unemployment_rate_current",
                UNEMPLOYMENT_RATE_SERIES_ID,
                "monthly",
                "level",
                "latest",
            ),
            FeatureSpec(
                "initial_claims_4w_mean",
                DOL_CLAIMS_4WMA_SERIES_ID,
                "weekly",
                "level",
                "latest",
            ),
            FeatureSpec(
                "treasury_10y_20d_mean",
                TREASURY_10Y_SERIES_ID,
                "daily",
                "level",
                "trailing_mean",
                window=20,
            ),
            FeatureSpec(
                "industrial_production_mom_lag1",
                FED_G17_MOM_SERIES_ID,
                "monthly",
                "level",
                "latest",
                lag_periods=1,
            ),
            FeatureSpec(
                "retail_sales_mom_lag1",
                CENSUS_RETAIL_MOM_SERIES_ID,
                "monthly",
                "level",
                "latest",
                lag_periods=1,
            ),
            FeatureSpec(
                "housing_starts_log_change_lag1",
                CENSUS_HOUSING_STARTS_SERIES_ID,
                "monthly",
                "log_change",
                "latest",
                lag_periods=1,
            ),
            FeatureSpec(
                "construction_employment_change",
                "CES2000000001",
                "monthly",
                "difference",
                "latest",
            ),
            FeatureSpec(
                "manufacturing_employment_change",
                "CES3000000001",
                "monthly",
                "difference",
                "latest",
            ),
            FeatureSpec(
                "financial_activities_employment_change",
                "CES5500000001",
                "monthly",
                "difference",
                "latest",
            ),
            FeatureSpec(
                "professional_business_employment_change",
                "CES6000000001",
                "monthly",
                "difference",
                "latest",
            ),
            FeatureSpec(
                "education_health_employment_change",
                "CES6500000001",
                "monthly",
                "difference",
                "latest",
            ),
            FeatureSpec(
                "leisure_hospitality_employment_change",
                "CES7000000001",
                "monthly",
                "difference",
                "latest",
            ),
        ),
        min_train_size=36,
        horizons=(0, 1),
        tuning_periods=24,
        final_evaluation_periods=24,
    ),
    OfficialPilotTarget(
        output_series_id="GDPC1",
        calendar_series_id=PUBLISHED_REAL_GDP_TARGET_SPEC.series_id,
        frequency="quarterly",
        target_spec=PUBLISHED_REAL_GDP_TARGET_SPEC,
        feature_specs=(
            FeatureSpec(
                "real_gdp_growth_lag1",
                PUBLISHED_REAL_GDP_TARGET_SPEC.series_id,
                "quarterly",
                "level",
                "latest",
                lag_periods=1,
            ),
            FeatureSpec(
                "real_gdp_growth_lag2",
                PUBLISHED_REAL_GDP_TARGET_SPEC.series_id,
                "quarterly",
                "level",
                "latest",
                lag_periods=2,
            ),
            FeatureSpec(
                "payems_change_quarter_edge",
                "PAYEMS",
                "monthly",
                "difference",
                "latest",
            ),
            FeatureSpec(
                "core_cpi_change_quarter_edge",
                "CPILFESL",
                "monthly",
                "percent_change",
                "latest",
            ),
            FeatureSpec(
                "unemployment_rate_quarter_edge",
                UNEMPLOYMENT_RATE_SERIES_ID,
                "monthly",
                "level",
                "latest",
            ),
            FeatureSpec(
                "initial_claims_4w_mean",
                DOL_CLAIMS_4WMA_SERIES_ID,
                "weekly",
                "level",
                "latest",
            ),
            FeatureSpec(
                "treasury_10y_20d_mean",
                TREASURY_10Y_SERIES_ID,
                "daily",
                "level",
                "trailing_mean",
                window=20,
            ),
            FeatureSpec(
                "industrial_production_mom_quarter_edge",
                FED_G17_MOM_SERIES_ID,
                "monthly",
                "level",
                "latest",
            ),
            FeatureSpec(
                "retail_sales_mom_quarter_edge",
                CENSUS_RETAIL_MOM_SERIES_ID,
                "monthly",
                "level",
                "latest",
            ),
            FeatureSpec(
                "housing_starts_log_change_quarter_edge",
                CENSUS_HOUSING_STARTS_SERIES_ID,
                "monthly",
                "log_change",
                "latest",
            ),
            FeatureSpec(
                "construction_employment_change_quarter_edge",
                "CES2000000001",
                "monthly",
                "difference",
                "latest",
            ),
            FeatureSpec(
                "manufacturing_employment_change_quarter_edge",
                "CES3000000001",
                "monthly",
                "difference",
                "latest",
            ),
            FeatureSpec(
                "trade_transport_utilities_employment_change_quarter_edge",
                "CES4000000001",
                "monthly",
                "difference",
                "latest",
            ),
            FeatureSpec(
                "information_employment_change_quarter_edge",
                "CES5000000001",
                "monthly",
                "difference",
                "latest",
            ),
            FeatureSpec(
                "professional_business_employment_change_quarter_edge",
                "CES6000000001",
                "monthly",
                "difference",
                "latest",
            ),
            FeatureSpec(
                "leisure_hospitality_employment_change_quarter_edge",
                "CES7000000001",
                "monthly",
                "difference",
                "latest",
            ),
        ),
        min_train_size=20,
        horizons=(0, 1),
        tuning_periods=8,
        final_evaluation_periods=8,
    ),
)


def _add_months(value: date, months: int) -> date:
    absolute_month = value.year * 12 + value.month - 1 + months
    year, zero_based_month = divmod(absolute_month, 12)
    return date(year, zero_based_month + 1, 1)


def _feature_cutoff(
    target_period: date,
    target_frequency: str,
    spec: FeatureSpec,
    as_of: datetime,
) -> date:
    if spec.frequency == "monthly":
        anchor = _add_months(target_period, 2) if target_frequency == "quarterly" else target_period
        return _add_months(anchor, -spec.lag_periods)
    if spec.frequency == "quarterly":
        quarter = date(target_period.year, ((target_period.month - 1) // 3) * 3 + 1, 1)
        return _add_months(quarter, -3 * spec.lag_periods)
    if spec.frequency in {"weekly", "daily"}:
        return as_of.date()
    raise ValueError(f"unsupported official archive feature frequency: {spec.frequency}")


def _relevant_observations(
    observations: pl.DataFrame,
    *,
    target_period: date,
    target_frequency: str,
    specs: Sequence[FeatureSpec],
    as_of: datetime,
) -> pl.DataFrame:
    conditions: list[pl.Expr] = []
    for spec in specs:
        cutoff = _feature_cutoff(target_period, target_frequency, spec, as_of)
        if spec.frequency in {"weekly", "daily"}:
            lower_bound = cutoff - timedelta(days=max(42, (spec.window or 1) * 14))
        else:
            lookback = 6 if spec.frequency == "monthly" else 12
            lower_bound = _add_months(cutoff, -lookback)
        conditions.append(
            (pl.col("series_id") == spec.series_id)
            & (pl.col("observation_date") <= cutoff)
            & (pl.col("observation_date") >= lower_bound)
        )
    condition = conditions[0]
    for additional in conditions[1:]:
        condition = condition | additional
    return observations.filter(condition)


def _target_origins(
    release_calendar: pl.DataFrame,
    target: OfficialPilotTarget,
) -> pl.DataFrame:
    origins = build_forecast_origins(
        release_calendar.filter(pl.col("series_id") == target.calendar_series_id)
    )
    return origins.with_columns(
        pl.lit(target.output_series_id).alias("target_series_id"),
        pl.lit(target.frequency).alias("target_frequency"),
        pl.concat_str(
            [
                pl.lit(target.output_series_id),
                pl.lit(":"),
                pl.col("target_period").cast(pl.String),
            ]
        ).alias("forecast_id"),
    )


def build_official_pilot_features(
    observations: pl.DataFrame,
    release_calendar: pl.DataFrame,
    *,
    targets: Sequence[OfficialPilotTarget] = PILOT_TARGETS,
    modes: Sequence[str] = (AS_OF_MODE, LATEST_SAME_MASK_MODE, NAIVE_LATEST_MODE),
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Build evidence-based mixed-precision origins and audited feature cells."""

    origins_by_target: list[pl.DataFrame] = []
    feature_frames: list[pl.DataFrame] = []
    for target in targets:
        origins = _target_origins(release_calendar, target)
        origins_by_target.append(origins)
        for mode in modes:
            for origin in origins.iter_rows(named=True):
                relevant = _relevant_observations(
                    observations,
                    target_period=origin["target_period"],
                    target_frequency=target.frequency,
                    specs=target.feature_specs,
                    as_of=origin["forecast_origin"],
                )
                feature_frames.append(
                    build_feature_vector(
                        relevant,
                        as_of=origin["forecast_origin"],
                        target_period=origin["target_period"],
                        specs=target.feature_specs,
                        mode=mode,  # type: ignore[arg-type]
                        target_series_id=target.output_series_id,
                        target_frequency=target.frequency,
                        forecast_id=origin["forecast_id"],
                    )
                )
    features = pl.concat(feature_frames).sort(
        ["target_series_id", "as_of_timestamp", "information_set_mode", "feature_name"]
    )
    assert_feature_no_future(features)
    origins = pl.concat(origins_by_target).sort(
        ["forecast_origin", "target_series_id", "target_period"]
    )
    return origins, features


def official_revision_eligible_observations(
    observations: pl.DataFrame,
) -> pl.DataFrame:
    """Exclude level vintages that are not comparable across benchmark definitions.

    BEA's archived real-GDP levels span six chained-dollar reference years and two
    published scales.  Adjacent levels selected from one release snapshot support the
    configured growth calculation, but raw levels cannot be differenced across release
    snapshots as though every change were an economic data revision.
    """

    return observations.filter(pl.col("series_id") != BEA_NIPA_LEVEL_SERIES_ID)


def _date_only_target_timing_counterfactual(
    release_calendar: pl.DataFrame,
    *,
    targets: Sequence[OfficialPilotTarget] = PILOT_TARGETS,
) -> pl.DataFrame:
    target_ids = [target.calendar_series_id for target in targets]
    exact_target = pl.col("series_id").is_in(target_ids) & (
        pl.col("timing_quality") != DATE_ONLY_TIMING_QUALITY
    )
    date_eod = (
        pl.col("release_timestamp").dt.date().cast(pl.Datetime("us", "UTC"))
        + pl.duration(hours=23, minutes=59, seconds=59, microseconds=999_999)
    )
    return release_calendar.with_columns(
        pl.when(exact_target)
        .then(date_eod)
        .otherwise(pl.col("release_timestamp"))
        .alias("release_timestamp"),
        pl.when(exact_target)
        .then(pl.lit(DATE_ONLY_TIMING_QUALITY))
        .otherwise(pl.col("timing_quality"))
        .alias("timing_quality"),
    )


def build_target_timing_precision_audit(
    release_calendar: pl.DataFrame,
    evidence_origins: pl.DataFrame,
    evidence_features: pl.DataFrame,
    evidence_targets: pl.DataFrame,
    conservative_origins: pl.DataFrame,
    conservative_features: pl.DataFrame,
    conservative_targets: pl.DataFrame,
    *,
    targets: Sequence[OfficialPilotTarget] = PILOT_TARGETS,
) -> pl.DataFrame:
    """Compare exact-clock origins with the prior date-only counterfactual."""

    origin_keys = ["target_series_id", "target_period"]
    feature_keys = [*origin_keys, "feature_name", "information_set_mode"]
    feature_fields = [
        "is_missing",
        "latest_source_observation_date",
        "max_source_availability",
        "max_eligibility_availability",
        "source_observation_count",
        "non_null_source_observation_count",
        "coverage_ratio",
    ]
    feature_join = evidence_features.select(
        [*feature_keys, "value", *feature_fields]
    ).join(
        conservative_features.select([*feature_keys, "value", *feature_fields]),
        on=feature_keys,
        how="inner",
        suffix="_date_only",
        validate="1:1",
    )
    if feature_join.height != evidence_features.height or (
        feature_join.height != conservative_features.height
    ):
        raise AssertionError("timing counterfactual feature keys do not match")
    value_changed = ~pl.col("value").eq_missing(pl.col("value_date_only"))
    selection_changed = pl.any_horizontal(
        [
            ~pl.col(field).eq_missing(pl.col(f"{field}_date_only"))
            for field in feature_fields
        ]
    )
    feature_delta = (
        feature_join.with_columns(
            value_changed.alias("value_changed"),
            selection_changed.alias("selection_changed"),
        )
        .group_by(origin_keys)
        .agg(
            pl.len().cast(pl.Int64).alias("feature_cells_compared"),
            pl.col("value_changed")
            .sum()
            .cast(pl.Int64)
            .alias("changed_feature_value_cells"),
            pl.col("selection_changed")
            .sum()
            .cast(pl.Int64)
            .alias("changed_feature_selection_cells"),
        )
    )

    target_keys = [*origin_keys, "realization_mode"]
    target_join = evidence_targets.select([*target_keys, "value"]).join(
        conservative_targets.select([*target_keys, "value"]),
        on=target_keys,
        how="inner",
        suffix="_date_only",
        validate="1:1",
    )
    if target_join.height != evidence_targets.height or (
        target_join.height != conservative_targets.height
    ):
        raise AssertionError("timing counterfactual target keys do not match")
    target_delta = target_join.group_by(origin_keys).agg(
        pl.len().cast(pl.Int64).alias("target_rows_compared"),
        (~pl.col("value").eq_missing(pl.col("value_date_only")))
        .sum()
        .cast(pl.Int64)
        .alias("changed_target_value_rows"),
    )

    timing_frames = [
        release_calendar.filter(
            (pl.col("series_id") == target.calendar_series_id)
            & (pl.col("release_type") == "initial")
        ).select(
            pl.lit(target.output_series_id).alias("target_series_id"),
            pl.col("observation_date").alias("target_period"),
            "timing_quality",
        )
        for target in targets
    ]
    timing = pl.concat(timing_frames)
    audit = (
        evidence_origins.select(
            *origin_keys,
            pl.col("forecast_origin").alias("evidence_based_origin"),
        )
        .join(
            conservative_origins.select(
                *origin_keys,
                pl.col("forecast_origin").alias("conservative_date_only_origin"),
            ),
            on=origin_keys,
            how="inner",
            validate="1:1",
        )
        .join(timing, on=origin_keys, how="left", validate="1:1")
        .join(feature_delta, on=origin_keys, how="left", validate="1:1")
        .join(target_delta, on=origin_keys, how="left", validate="1:1")
        .with_columns(
            (
                pl.col("evidence_based_origin")
                - pl.col("conservative_date_only_origin")
            )
            .dt.total_microseconds()
            .alias("origin_shift_microseconds"),
            pl.lit(OFFICIAL_PROVENANCE).alias("provenance_label"),
        )
        .sort(origin_keys)
    )
    if audit.height != evidence_origins.height:
        raise AssertionError("timing precision audit lost forecast origins")
    if audit.filter(pl.col("origin_shift_microseconds") < 0).height:
        raise AssertionError("evidence-based origin cannot precede date-only counterfactual")
    return audit


def _wide_features(features: pl.DataFrame, target: OfficialPilotTarget, mode: str) -> pl.DataFrame:
    subset = features.filter(
        (pl.col("target_series_id") == target.output_series_id)
        & (pl.col("information_set_mode") == mode)
    )
    index = [
        "forecast_id",
        "target_series_id",
        "target_period",
        "target_frequency",
        "as_of_timestamp",
        "information_set_mode",
        "is_counterfactual",
    ]
    wide = subset.pivot(
        on="feature_name",
        index=index,
        values="value",
        aggregate_function="first",
    )
    audit = subset.group_by("forecast_id").agg(
        pl.col("max_source_availability").max().alias("max_source_availability"),
        pl.col("max_eligibility_availability").max().alias("max_eligibility_availability"),
        pl.col("is_missing").sum().alias("missing_feature_count"),
    )
    return wide.join(audit, on="forecast_id", how="left", validate="1:1").sort("target_period")


def build_official_research_datasets(
    features: pl.DataFrame,
    targets: pl.DataFrame,
    *,
    definitions: Sequence[OfficialPilotTarget] = PILOT_TARGETS,
) -> pl.DataFrame:
    frames: list[pl.DataFrame] = []
    for definition in definitions:
        for data_mode, feature_mode, target_mode in EXPERIMENTS:
            origin_features = _wide_features(features, definition, feature_mode).rename(
                {
                    "forecast_id": "origin_forecast_id",
                    "target_period": "origin_target_period",
                }
            )
            target_rows = targets.filter(
                (pl.col("target_series_id") == definition.output_series_id)
                & (pl.col("realization_mode") == target_mode)
            ).select(
                "target_series_id",
                "target_period",
                "target_name",
                "target_units",
                "target_formula",
                pl.col("value").alias("target_value"),
                "target_release_timestamp",
                "realization_as_of_timestamp",
                "realization_mode",
            )
            step_months = 1 if definition.frequency == "monthly" else 3
            for horizon in definition.horizons:
                horizon_features = origin_features.with_columns(
                    pl.col("origin_target_period")
                    .dt.offset_by(f"{horizon * step_months}mo")
                    .alias("target_period"),
                    pl.lit(horizon, dtype=pl.Int64).alias("horizon"),
                ).with_columns(
                    pl.concat_str(
                        [
                            pl.col("origin_forecast_id"),
                            pl.lit(":h"),
                            pl.col("horizon").cast(pl.String),
                            pl.lit(":target:"),
                            pl.col("target_period").cast(pl.String),
                        ]
                    ).alias("forecast_id")
                )
                frames.append(
                    horizon_features.join(
                        target_rows,
                        on=["target_series_id", "target_period"],
                        how="inner",
                        validate="1:1",
                    ).with_columns(
                        pl.lit(data_mode).alias("data_mode"),
                        pl.lit(OFFICIAL_PROVENANCE).alias("data_provenance"),
                    )
                )
    return pl.concat(frames, how="diagonal_relaxed").sort(
        ["target_series_id", "data_mode", "horizon", "target_period"]
    )


def _datetime64_to_utc(value: np.datetime64) -> datetime:
    nanoseconds = int(value.astype("datetime64[ns]").astype(np.int64))
    microseconds = nanoseconds // 1_000
    return datetime.fromtimestamp(microseconds / 1_000_000, UTC)


def _evaluation_period_blocks(
    dataset: pl.DataFrame,
    definition: OfficialPilotTarget,
) -> tuple[dict[date, str], tuple[date, ...], tuple[date, ...]]:
    periods = tuple(sorted(dataset["target_period"].unique().to_list()))
    tuning_count = definition.tuning_periods
    final_count = definition.final_evaluation_periods
    if tuning_count == 0 and final_count == 0:
        return ({period: "all_oos" for period in periods}, (), ())
    if tuning_count == 0 or final_count == 0:
        raise ValueError("tuning and final-evaluation blocks must both be nonempty")
    if len(periods) <= tuning_count + final_count + definition.min_train_size:
        raise ValueError(
            f"insufficient {definition.output_series_id} periods for prespecified "
            "development, tuning, and final-evaluation blocks"
        )
    final_periods = periods[-final_count:]
    tuning_periods = periods[-(tuning_count + final_count) : -final_count]
    tuning_set = set(tuning_periods)
    final_set = set(final_periods)
    blocks = {
        period: (
            "tuning_validation"
            if period in tuning_set
            else "final_evaluation"
            if period in final_set
            else "model_development"
        )
        for period in periods
    }
    return blocks, tuning_periods, final_periods


def _advanced_estimator(
    model_name: str,
    parameters: Mapping[str, float | int],
    definition: OfficialPilotTarget,
) -> Any:
    if model_name == "elastic_net":
        return FixedElasticNetRegressor(
            alpha=float(parameters["alpha"]),
            l1_ratio=float(parameters["l1_ratio"]),
            min_train_samples=definition.min_train_size,
        )
    if model_name == "hist_gradient_boosting":
        return DeterministicHistGradientBoostingRegressor(
            learning_rate=float(parameters["learning_rate"]),
            max_iter=30,
            max_leaf_nodes=int(parameters["max_leaf_nodes"]),
            max_depth=3,
            min_samples_leaf=5,
            l2_regularization=float(parameters["l2_regularization"]),
            min_train_samples=definition.min_train_size,
            random_state=0,
        )
    raise ValueError(f"unsupported advanced model for official tuning: {model_name}")


def tune_official_advanced_models(
    research_datasets: pl.DataFrame,
    *,
    definitions: Sequence[OfficialPilotTarget] = PILOT_TARGETS,
) -> tuple[
    pl.DataFrame,
    dict[tuple[str, int, str], dict[str, float | int]],
]:
    """Select advanced-model settings before the untouched final block.

    Candidates are evaluated only on the vintage-aware tuning-validation block.
    The final block is removed before every candidate backtest and cannot affect
    selection. Selected settings are then frozen across all information modes.
    """

    grids: tuple[tuple[str, tuple[dict[str, float | int], ...]], ...] = (
        ("elastic_net", ELASTIC_NET_TUNING_GRID),
        ("hist_gradient_boosting", HIST_GRADIENT_BOOSTING_TUNING_GRID),
    )
    rows: list[dict[str, object]] = []
    selected_parameters: dict[tuple[str, int, str], dict[str, float | int]] = {}
    for definition in definitions:
        for horizon in definition.horizons:
            dataset = research_datasets.filter(
                (pl.col("target_series_id") == definition.output_series_id)
                & (pl.col("data_mode") == "vintage_aware")
                & (pl.col("horizon") == horizon)
            ).sort("target_period")
            _, tuning_periods, final_periods = _evaluation_period_blocks(dataset, definition)
            if not tuning_periods or not final_periods:
                raise ValueError("official tuning requires explicit tuning and final blocks")
            final_start = final_periods[0]
            candidate_dataset = dataset.filter(pl.col("target_period") < final_start)
            periods = candidate_dataset["target_period"].to_list()
            tuning_set = set(tuning_periods)
            for model_name, grid in grids:
                candidate_rows: list[dict[str, object]] = []
                for candidate_index, parameters in enumerate(grid):
                    result = run_expanding_backtest(
                        _advanced_estimator(model_name, parameters, definition),
                        candidate_dataset.select(definition.feature_names).to_numpy(),
                        candidate_dataset["target_value"].to_numpy(),
                        origins=candidate_dataset["as_of_timestamp"].to_list(),
                        target_release_dates=candidate_dataset[
                            "target_release_timestamp"
                        ].to_list(),
                        min_train_size=definition.min_train_size,
                        horizon=[horizon] * candidate_dataset.height,
                        model_name=model_name,
                        interval_min_residuals=min(12, definition.min_train_size),
                    )
                    validation_records = [
                        record
                        for record in result.records
                        if periods[record.row_index] in tuning_set
                    ]
                    if len(validation_records) != len(tuning_periods):
                        raise RuntimeError(
                            f"{definition.output_series_id} horizon {horizon} {model_name} "
                            "did not forecast every prespecified tuning period"
                        )
                    values = regression_metrics(
                        [record.actual for record in validation_records],
                        [record.forecast for record in validation_records],
                    )
                    candidate_id = f"{model_name}:{candidate_index:02d}"
                    candidate_rows.append(
                        {
                            "target_series_id": definition.output_series_id,
                            "target_frequency": definition.frequency,
                            "horizon": horizon,
                            "model_id": model_name,
                            "candidate_id": candidate_id,
                            "parameters_json": json.dumps(parameters, sort_keys=True),
                            "selection_metric": "rmse",
                            "validation_rmse": values["rmse"],
                            "validation_mae": values["mae"],
                            "validation_forecasts": values["n_obs"],
                            "tuning_start": tuning_periods[0],
                            "tuning_end": tuning_periods[-1],
                            "final_evaluation_start": final_periods[0],
                            "final_evaluation_end": final_periods[-1],
                            "final_evaluation_rows_used_for_selection": 0,
                            "tuning_data_mode": "vintage_aware",
                            "selected": False,
                            "data_provenance": OFFICIAL_PROVENANCE,
                        }
                    )
                best = min(
                    candidate_rows,
                    key=lambda row: (float(row["validation_rmse"]), str(row["candidate_id"])),
                )
                best["selected"] = True
                selected_parameters[(definition.output_series_id, horizon, model_name)] = dict(
                    grid[int(str(best["candidate_id"]).rsplit(":", maxsplit=1)[1])]
                )
                rows.extend(candidate_rows)
    return (
        pl.DataFrame(rows).sort(
            ["target_series_id", "horizon", "model_id", "candidate_id"]
        ),
        selected_parameters,
    )


def _prediction_rows(
    dataset: pl.DataFrame,
    definition: OfficialPilotTarget,
    *,
    model_name: str,
    estimator: Any,
) -> list[dict[str, object]]:
    periods = dataset["target_period"].to_list()
    regimes = [nber_regime(period, definition.frequency) for period in periods]
    horizons = dataset["horizon"].unique().to_list()
    if len(horizons) != 1:
        raise ValueError("each official backtest dataset must contain exactly one horizon")
    horizon = int(horizons[0])
    evaluation_blocks, _, _ = _evaluation_period_blocks(dataset, definition)
    result = run_expanding_backtest(
        estimator,
        dataset.select(definition.feature_names).to_numpy(),
        dataset["target_value"].to_numpy(),
        origins=dataset["as_of_timestamp"].to_list(),
        target_release_dates=dataset["target_release_timestamp"].to_list(),
        min_train_size=definition.min_train_size,
        horizon=[horizon] * dataset.height,
        regimes=regimes,
        model_name=model_name,
        interval_coverage_target=0.8,
        interval_min_residuals=min(12, definition.min_train_size),
    )
    return [
        {
            "fold_id": record.fold,
            "row_index": record.row_index,
            "target_series_id": definition.output_series_id,
            "target_name": dataset["target_name"][0],
            "target_frequency": definition.frequency,
            "target_units": dataset["target_units"][0],
            "target_formula": dataset["target_formula"][0],
            "model_id": model_name,
            "data_mode": dataset["data_mode"][0],
            "feature_mode": dataset["information_set_mode"][0],
            "target_mode": dataset["realization_mode"][0],
            "target_period": periods[record.row_index],
            "origin_target_period": dataset["origin_target_period"][record.row_index],
            "forecast_id": dataset["forecast_id"][record.row_index],
            "origin_ts": _datetime64_to_utc(record.origin),
            "target_release_ts": _datetime64_to_utc(record.target_release_date),
            "actual": record.actual,
            "prediction": record.forecast,
            "lower": record.lower,
            "upper": record.upper,
            "n_train": record.train_size,
            "horizon": int(record.horizon),
            "regime": record.regime,
            "evaluation_block": evaluation_blocks[periods[record.row_index]],
            "data_provenance": OFFICIAL_PROVENANCE,
        }
        for record in result.records
    ]


def _official_model_ladder(
    definition: OfficialPilotTarget,
    horizon: int,
    selected_parameters: Mapping[
        tuple[str, int, str], Mapping[str, float | int]
    ] | None,
) -> dict[str, Any]:
    ladder = dict(default_model_ladder())
    tree_defaults: dict[str, float | int] = {
        "learning_rate": 0.05,
        "max_leaf_nodes": 7,
        "l2_regularization": 1.0,
    }
    elastic_defaults: dict[str, float | int] = {"alpha": 0.05, "l1_ratio": 0.5}
    if selected_parameters is not None:
        elastic_defaults = dict(
            selected_parameters[(definition.output_series_id, horizon, "elastic_net")]
        )
        tree_defaults = dict(
            selected_parameters[
                (definition.output_series_id, horizon, "hist_gradient_boosting")
            ]
        )
    ladder["elastic_net"] = _advanced_estimator(
        "elastic_net", elastic_defaults, definition
    )
    ladder["hist_gradient_boosting"] = _advanced_estimator(
        "hist_gradient_boosting", tree_defaults, definition
    )
    return ladder


def run_official_pilot_backtests(
    research_datasets: pl.DataFrame,
    *,
    definitions: Sequence[OfficialPilotTarget] = PILOT_TARGETS,
    models: Mapping[str, Any] | None = None,
    advanced_model_parameters: Mapping[
        tuple[str, int, str], Mapping[str, float | int]
    ] | None = None,
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    prediction_rows: list[dict[str, object]] = []
    for definition in definitions:
        for data_mode, _, _ in EXPERIMENTS:
            for horizon in definition.horizons:
                model_ladder = (
                    dict(models)
                    if models is not None
                    else _official_model_ladder(
                        definition,
                        horizon,
                        advanced_model_parameters,
                    )
                )
                dataset = research_datasets.filter(
                    (pl.col("target_series_id") == definition.output_series_id)
                    & (pl.col("data_mode") == data_mode)
                    & (pl.col("horizon") == horizon)
                ).sort("target_period")
                for model_name, estimator in model_ladder.items():
                    prediction_rows.extend(
                        _prediction_rows(
                            dataset,
                            definition,
                            model_name=model_name,
                            estimator=estimator,
                        )
                    )
    predictions = pl.DataFrame(prediction_rows).sort(
        ["target_series_id", "data_mode", "horizon", "model_id", "target_period"]
    )

    metric_rows: list[dict[str, object]] = []
    for key in (
        predictions.select(["target_series_id", "data_mode", "horizon", "model_id"])
        .unique()
        .iter_rows(named=True)
    ):
        subset = predictions.filter(
            (pl.col("target_series_id") == key["target_series_id"])
            & (pl.col("data_mode") == key["data_mode"])
            & (pl.col("horizon") == key["horizon"])
            & (pl.col("model_id") == key["model_id"])
        )
        values = regression_metrics(
            subset["actual"].to_numpy(),
            subset["prediction"].to_numpy(),
            lower=subset["lower"].to_numpy(),
            upper=subset["upper"].to_numpy(),
        )
        metric_rows.append(
            {
                **key,
                "target_name": subset["target_name"][0],
                "target_units": subset["target_units"][0],
                "target_formula": subset["target_formula"][0],
                "n_forecasts": values.pop("n_obs"),
                **values,
                "sample_start": subset["target_period"].min(),
                "sample_end": subset["target_period"].max(),
                "evaluation_block": "all_oos_descriptive",
                "data_provenance": OFFICIAL_PROVENANCE,
            }
        )
    metrics = pl.DataFrame(metric_rows).sort(
        ["target_series_id", "data_mode", "horizon", "rmse", "model_id"]
    )
    metrics = metrics.with_columns(
        pl.col("rmse")
        .rank("dense")
        .over(["target_series_id", "data_mode", "horizon"])
        .cast(pl.Int64)
        .alias("rmse_rank")
    )

    dm_rows: list[dict[str, object]] = []
    for target_id in predictions["target_series_id"].unique().sort():
        for data_mode in predictions["data_mode"].unique().sort():
            for horizon in predictions["horizon"].unique().sort():
                comparison = predictions.filter(
                    (pl.col("target_series_id") == target_id)
                    & (pl.col("data_mode") == data_mode)
                    & (pl.col("horizon") == horizon)
                )
                if comparison.is_empty():
                    continue
                dm_evaluation_block = (
                    "final_evaluation"
                    if comparison.filter(
                        pl.col("evaluation_block") == "final_evaluation"
                    ).height
                    else "all_oos"
                )
                comparison = comparison.filter(
                    pl.col("evaluation_block") == dm_evaluation_block
                )
                baseline = comparison.filter(pl.col("model_id") == "historical_mean")
                for model_name in comparison["model_id"].unique().sort():
                    if model_name == "historical_mean":
                        continue
                    challenger = comparison.filter(pl.col("model_id") == model_name)
                    paired = baseline.select(
                        "target_period",
                        "actual",
                        pl.col("prediction").alias("baseline_prediction"),
                    ).join(
                        challenger.select(
                            "target_period",
                            pl.col("prediction").alias("challenger_prediction"),
                        ),
                        on="target_period",
                        how="inner",
                        validate="1:1",
                    )
                    dm = diebold_mariano(
                        paired["actual"].to_numpy(),
                        paired["baseline_prediction"].to_numpy(),
                        paired["challenger_prediction"].to_numpy(),
                        horizon=int(horizon) + 1,
                        min_observations=20,
                    )
                    dm_rows.append(
                        {
                            "target_series_id": target_id,
                            "data_mode": data_mode,
                            "horizon": int(horizon),
                            "hac_lag": dm.hac_lag,
                            "evaluation_block": dm_evaluation_block,
                            "baseline_model": "historical_mean",
                            "challenger_model": model_name,
                            "n_obs": dm.n_obs,
                            "statistic": dm.statistic,
                            "p_value": dm.p_value,
                            "mean_loss_differential": dm.mean_loss_differential,
                            "valid": dm.valid,
                            "reason": dm.reason,
                            "data_provenance": OFFICIAL_PROVENANCE,
                        }
                    )
    dm_comparisons = pl.DataFrame(dm_rows).sort(
        ["target_series_id", "data_mode", "horizon", "challenger_model"]
    )
    return predictions, metrics, dm_comparisons


def official_final_evaluation_metrics(predictions: pl.DataFrame) -> pl.DataFrame:
    """Score only the holdout block that hyperparameter selection never sees."""

    final = predictions.filter(pl.col("evaluation_block") == "final_evaluation")
    if final.is_empty():
        raise ValueError("predictions contain no final-evaluation block")
    keys = ["target_series_id", "data_mode", "horizon", "model_id"]
    rows: list[dict[str, object]] = []
    for key in final.select(keys).unique().iter_rows(named=True):
        subset = final.filter(
            (pl.col("target_series_id") == key["target_series_id"])
            & (pl.col("data_mode") == key["data_mode"])
            & (pl.col("horizon") == key["horizon"])
            & (pl.col("model_id") == key["model_id"])
        )
        values = regression_metrics(
            subset["actual"].to_numpy(),
            subset["prediction"].to_numpy(),
            lower=subset["lower"].to_numpy(),
            upper=subset["upper"].to_numpy(),
        )
        rows.append(
            {
                **key,
                "target_name": subset["target_name"][0],
                "target_units": subset["target_units"][0],
                "target_formula": subset["target_formula"][0],
                "n_forecasts": values.pop("n_obs"),
                **values,
                "sample_start": subset["target_period"].min(),
                "sample_end": subset["target_period"].max(),
                "evaluation_block": "final_evaluation_not_used_for_tuning",
                "data_provenance": OFFICIAL_PROVENANCE,
            }
        )
    metrics = pl.DataFrame(rows).sort(
        ["target_series_id", "data_mode", "horizon", "rmse", "model_id"]
    )
    return metrics.with_columns(
        pl.col("rmse")
        .rank("dense")
        .over(["target_series_id", "data_mode", "horizon"])
        .cast(pl.Int64)
        .alias("rmse_rank")
    )


def official_metrics_by_regime_horizon(predictions: pl.DataFrame) -> pl.DataFrame:
    """Summarize official-pilot errors by horizon and ex-post NBER regime.

    NBER chronology is evaluation metadata only. It is deliberately absent from
    every feature matrix and estimator input.
    """

    group_keys = [
        "target_series_id",
        "target_name",
        "target_frequency",
        "target_units",
        "target_formula",
        "data_mode",
        "feature_mode",
        "target_mode",
        "model_id",
        "horizon",
        "regime",
    ]
    missing = sorted(set(group_keys) - set(predictions.columns))
    if missing:
        raise ValueError(f"predictions are missing grouped-metric fields: {missing}")

    rows: list[dict[str, object]] = []
    for key in predictions.select(group_keys).unique().iter_rows(named=True):
        condition = pl.lit(True)
        for name, value in key.items():
            condition &= pl.col(name) == value
        subset = predictions.filter(condition)
        values = regression_metrics(
            subset["actual"].to_numpy(),
            subset["prediction"].to_numpy(),
            lower=subset["lower"].to_numpy(),
            upper=subset["upper"].to_numpy(),
        )
        rows.append(
            {
                **key,
                "n_forecasts": values.pop("n_obs"),
                **values,
                "sample_start": subset["target_period"].min(),
                "sample_end": subset["target_period"].max(),
                "regime_definition": NBER_REGIME_DEFINITION,
                "regime_source_url": NBER_REGIME_SOURCE_URL,
                "regime_source_last_updated": NBER_REGIME_SOURCE_LAST_UPDATED,
                "regime_is_forecast_input": False,
                "data_provenance": OFFICIAL_PROVENANCE,
            }
        )
    return pl.DataFrame(rows).sort(group_keys)


def official_model_stability(
    predictions: pl.DataFrame,
    metrics: pl.DataFrame,
) -> pl.DataFrame:
    """Measure prediction and ranking sensitivity to revised-data counterfactuals."""

    rows: list[dict[str, object]] = []
    for target_series_id, model_id, horizon in (
        predictions.select("target_series_id", "model_id", "horizon").unique().iter_rows()
    ):
        vintage = predictions.filter(
            (pl.col("target_series_id") == target_series_id)
            & (pl.col("model_id") == model_id)
            & (pl.col("horizon") == horizon)
            & (pl.col("data_mode") == "vintage_aware")
        ).select("target_period", pl.col("prediction").alias("vintage_prediction"))
        for comparison_mode in (LATEST_SAME_MASK_MODE, NAIVE_LATEST_MODE):
            comparison = predictions.filter(
                (pl.col("target_series_id") == target_series_id)
                & (pl.col("model_id") == model_id)
                & (pl.col("horizon") == horizon)
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
                & (pl.col("horizon") == horizon)
            )
            vintage_rank = rank_rows.filter(pl.col("data_mode") == "vintage_aware")["rmse_rank"][0]
            counterfactual_rank = rank_rows.filter(pl.col("data_mode") == comparison_mode)[
                "rmse_rank"
            ][0]
            metadata = predictions.filter(pl.col("target_series_id") == target_series_id).row(
                0, named=True
            )
            rows.append(
                {
                    "target_series_id": target_series_id,
                    "target_name": metadata["target_name"],
                    "target_frequency": metadata["target_frequency"],
                    "target_units": metadata["target_units"],
                    "model_id": model_id,
                    "horizon": int(horizon),
                    "comparison_mode": comparison_mode,
                    "n_aligned": aligned.height,
                    "prediction_correlation": correlation,
                    "mean_abs_prediction_difference": float(np.mean(np.abs(second - first))),
                    "vintage_rmse_rank": vintage_rank,
                    "counterfactual_rmse_rank": counterfactual_rank,
                    "rank_change": int(counterfactual_rank - vintage_rank),
                    "rmse_rank_evaluation_block": rank_rows["evaluation_block"][0],
                    "data_provenance": OFFICIAL_PROVENANCE,
                }
            )
    return pl.DataFrame(rows).sort(
        ["target_series_id", "horizon", "comparison_mode", "model_id"]
    )


def official_target_revision_effects(
    targets: pl.DataFrame,
    predictions: pl.DataFrame,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Hold vintage-aware forecasts fixed and isolate later target revisions."""

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
                "horizon",
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
        .with_columns(pl.lit(OFFICIAL_PROVENANCE).alias("data_provenance"))
        .sort(["target_series_id", "horizon", "model_id"])
    )
    return detailed.sort(
        ["target_series_id", "horizon", "model_id", "target_period"]
    ), summary


def _feature_value_map(frame: pl.DataFrame) -> dict[str, float | None]:
    return dict(
        zip(
            frame["feature_name"].to_list(),
            frame["value"].to_list(),
            strict=True,
        )
    )


def _feature_values_differ(first: float | None, second: float | None) -> bool:
    if first is None and second is None:
        return False
    if first is None or second is None:
        return True
    if math.isnan(first) and math.isnan(second):
        return False
    return not math.isclose(first, second, rel_tol=0.0, abs_tol=1e-12)


def _official_historical_update_comparison(
    predictions: pl.DataFrame,
    *,
    absolute_update: float,
) -> dict[str, object]:
    ordered = predictions.sort("target_period")["prediction"].to_numpy()
    movements = np.abs(np.diff(ordered))
    movements = movements[np.isfinite(movements)]
    if movements.size == 0:
        return {
            "comparison_kind": "absolute consecutive official-pilot OOS movements",
            "n_comparisons": 0,
            "percentile": None,
            "median_absolute_movement": None,
            "interpretation": "insufficient prior official-pilot forecasts",
        }
    return {
        "comparison_kind": "absolute consecutive official-pilot OOS movements",
        "n_comparisons": int(movements.size),
        "percentile": float(np.mean(movements <= absolute_update) * 100.0),
        "median_absolute_movement": float(np.median(movements)),
        "interpretation": (
            "descriptive scale within this fixed pilot; not a causal or like-for-like "
            "historical release-event study"
        ),
    }


def build_official_news_updates(
    observations: pl.DataFrame,
    release_calendar: pl.DataFrame,
    research_datasets: pl.DataFrame,
    predictions: pl.DataFrame,
    *,
    definitions: Sequence[OfficialPilotTarget] = PILOT_TARGETS,
    advanced_model_parameters: Mapping[
        tuple[str, int, str], Mapping[str, float | int]
    ] | None = None,
) -> list[dict[str, object]]:
    """Create one date-level, frozen-model release update for every target."""

    updates: list[dict[str, object]] = []
    for definition in definitions:
        news_horizon = 1 if 1 in definition.horizons else 0
        release = (
            build_forecast_origins(
                release_calendar.filter(pl.col("series_id") == definition.calendar_series_id)
            )
            .sort("target_release_timestamp")
            .tail(1)
            .row(0, named=True)
        )
        step = 1 if definition.frequency == "monthly" else 3
        forecast_period = _add_months(release["target_period"], step)
        previous_as_of = release["forecast_origin"]
        updated_as_of = release["target_release_timestamp"]
        previous_long = build_feature_vector(
            observations,
            as_of=previous_as_of,
            target_period=forecast_period,
            specs=definition.feature_specs,
            mode=AS_OF_MODE,
            target_series_id=definition.output_series_id,
            target_frequency=definition.frequency,
            forecast_id=f"official-news:{definition.output_series_id}:{forecast_period}",
        )
        updated_long = build_feature_vector(
            observations,
            as_of=updated_as_of,
            target_period=forecast_period,
            specs=definition.feature_specs,
            mode=AS_OF_MODE,
            target_series_id=definition.output_series_id,
            target_frequency=definition.frequency,
            forecast_id=f"official-news:{definition.output_series_id}:{forecast_period}",
        )
        previous_map = _feature_value_map(previous_long)
        updated_map = _feature_value_map(updated_long)
        changed_features = [
            name
            for name in definition.feature_names
            if _feature_values_differ(previous_map[name], updated_map[name])
        ]
        if not changed_features:
            raise RuntimeError(
                f"latest official {definition.output_series_id} release changes no feature"
            )

        training = research_datasets.filter(
            (pl.col("target_series_id") == definition.output_series_id)
            & (pl.col("data_mode") == "vintage_aware")
            & (pl.col("horizon") == news_horizon)
            & (pl.col("target_release_timestamp") <= pl.lit(previous_as_of))
        ).sort("target_period")
        if training.height < definition.min_train_size:
            raise RuntimeError(
                f"insufficient released training rows for {definition.output_series_id} news"
            )
        news_parameters = (
            advanced_model_parameters[
                (definition.output_series_id, news_horizon, "elastic_net")
            ]
            if advanced_model_parameters is not None
            else {"alpha": 0.05, "l1_ratio": 0.5}
        )
        model = _advanced_estimator("elastic_net", news_parameters, definition)
        model.fit(
            training.select(definition.feature_names).to_numpy(),
            training["target_value"].to_numpy(),
        )
        attribution = linear_news_attribution(
            model,
            previous_map,
            updated_map,
            feature_names=definition.feature_names,
        )
        prior_predictions = predictions.filter(
            (pl.col("target_series_id") == definition.output_series_id)
            & (pl.col("data_mode") == "vintage_aware")
            & (pl.col("model_id") == "elastic_net")
            & (pl.col("horizon") == news_horizon)
            & (pl.col("target_release_ts") <= pl.lit(previous_as_of))
        ).sort("target_period")
        residuals = prior_predictions["actual"] - prior_predictions["prediction"]
        lower, upper = residual_prediction_interval(
            [attribution.updated_prediction],
            residuals.to_numpy(),
            coverage=0.8,
            min_residuals=min(12, definition.min_train_size),
        )
        contributions = [
            {
                "feature": name,
                "contribution": value,
                "target_units": definition.target_spec.target_units,
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
                "evidence_tier": "official_archive_pilot",
                "data_provenance": OFFICIAL_PROVENANCE,
                "scoped_empirical_evidence": True,
                "broad_policy_or_model_claims_supported": False,
                "target_series_id": definition.output_series_id,
                "target_name": definition.target_spec.target_name,
                "target_frequency": definition.frequency,
                "target_units": definition.target_spec.target_units,
                "target_formula": definition.target_spec.formula,
                "forecast_target_period": forecast_period,
                "horizon": news_horizon,
                "data_mode": "vintage_aware",
                "model_id": "elastic_net",
                "model_status": "frozen_after_training_on_released_targets_only",
                "model_hyperparameters": dict(news_parameters),
                "training_rows": training.height,
                "release_name": (
                    f"Official {release['target_series_id']} archive release for "
                    f"{release['target_period']}"
                ),
                "release_id": release["forecast_id"],
                "release_series_id": release["target_series_id"],
                "release_observation_date": release["target_period"],
                "release_type": "initial",
                "release_timestamp": updated_as_of,
                "release_timing_quality": DATE_ONLY_TIMING_QUALITY,
                "previous_as_of_timestamp": previous_as_of,
                "updated_as_of_timestamp": updated_as_of,
                "changed_features": changed_features,
                "previous_nowcast": attribution.previous_prediction,
                "updated_nowcast": attribution.updated_prediction,
                "forecast_revision": attribution.total_change,
                "assessment": (
                    f"The frozen official-pilot {definition.target_spec.target_name} "
                    f"nowcast {direction} by {abs(attribution.total_change):.4f} "
                    f"{definition.target_spec.target_units}."
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
                "historical_comparison": _official_historical_update_comparison(
                    prior_predictions,
                    absolute_update=abs(attribution.total_change),
                ),
                "interpretation": (
                    "exact fixed-linear-model decomposition within the declared official "
                    "archive pilot; not causal, investment, or monetary-policy advice"
                ),
            }
        )
    return updates


def render_official_policy_brief(update: Mapping[str, object]) -> str:
    """Render a guarded one-page Markdown brief from one official update."""

    interval = update["interval"]
    assert isinstance(interval, Mapping)
    contributions = update["contributions"]
    assert isinstance(contributions, list)
    contribution_lines = [
        (
            f"- `{row['feature']}`: {float(row['contribution']):.4f} "
            f"{row['target_units']} (feature {row['previous_value']} → "
            f"{row['updated_value']})"
        )
        for row in contributions
        if isinstance(row, Mapping)
    ]
    return "\n".join(
        [
            f"# Official Archive Pilot Brief — {update['target_series_id']}",
            "",
            "> **SCOPED EMPIRICAL PILOT.** This brief uses audited official archives and "
            "a frozen model. Date-only timing is conservative; the decomposition is "
            "predictive, not causal, and is not investment or monetary-policy advice.",
            "",
            f"**Release:** {update['release_name']}  ",
            f"**Release date convention:** {update['release_timestamp']} "
            f"(`{update['release_timing_quality']}`)  ",
            f"**Forecast target:** {update['target_name']} for "
            f"{update['forecast_target_period']}  ",
            f"**Formula:** `{update['target_formula']}`  ",
            f"**Model:** frozen Elastic Net trained on {update['training_rows']} released "
            "historical targets",
            "",
            "## What changed",
            "",
            f"The nowcast moved from **{float(update['previous_nowcast']):.4f}** to "
            f"**{float(update['updated_nowcast']):.4f}** "
            f"{update['target_units']}, a revision of "
            f"**{float(update['forecast_revision']):+.4f}**. Changed inputs: "
            f"{', '.join(f'`{name}`' for name in update['changed_features'])}.",
            "",
            "## Exact contribution accounting",
            "",
            *contribution_lines,
            "",
            f"Unattributed residual: `{float(update['unattributed_residual']):.3e}`.",
            "",
            "## Uncertainty",
            "",
            f"The prior-residual 80% interval is **[{interval['lower']}, "
            f"{interval['upper']}]**, based on {interval['residual_count']} previously "
            "released out-of-sample errors. It is descriptive and not a structural risk "
            "distribution.",
            "",
            "## Risks to interpretation",
            "",
            "- Every acquired Employment Situation target event uses its printed "
            "embargo clock from official TXT or HTML evidence, except the retained "
            "2012-12-07 EST/EDT conflict. Every acquired CPI and GDP target snapshot "
            "uses its verified agency header clock. "
            "DOL claims, G.17, MARTS, and NRC predictors retain their separately verified "
            "exact clocks. Treasury 10-year observations use conservative source-date "
            "New York EOD availability because the XML feed has no publication clock.",
            "- The feature panel includes genuine DOL claims, Fed G.17 industrial "
            "production, Treasury 10-year CMT rates, Census MARTS retail sales, and rich "
            "CES sector detail, but still omits authorized consumer-sentiment vintages. "
            "Treasury rates are daily point observations, not a correction-vintage "
            "archive. Census NRC housing starts is included.",
            "- Revisions, benchmark changes, COVID-era extremes, missing values, and fixed "
            "hyperparameters can materially affect the update.",
            "- Contributions explain this frozen linear prediction change; they do not "
            "identify economic causes.",
            "",
            "## What would change the assessment",
            "",
            "The next official target release, subsequent revisions, verified intraday "
            "timing, a wider original-provider vintage panel, or materially different "
            "out-of-sample residual behavior would change this pilot assessment.",
            "",
        ]
    )


def _write_frame(
    frame: pl.DataFrame,
    output_dir: Path,
    store: VintageStore,
    name: str,
) -> Path:
    path = output_dir / f"{name}.parquet"
    frame.write_parquet(path, compression="zstd", statistics=True)
    store.register_view(path, table_name=name)
    return path


def _format_cell(value: object) -> str:
    if value is None:
        return "NA"
    if isinstance(value, float):
        return "NA" if not math.isfinite(value) else f"{value:.6g}"
    return str(value).replace("|", "\\|")


def _markdown_table(frame: pl.DataFrame, columns: Sequence[str]) -> str:
    header = "| " + " | ".join(columns) + " |"
    separator = "| " + " | ".join("---" for _ in columns) + " |"
    rows = [
        "| " + " | ".join(_format_cell(row[column]) for column in columns) + " |"
        for row in frame.select(columns).iter_rows(named=True)
    ]
    return "\n".join([header, separator, *rows])


def render_official_pilot_report(
    metrics: pl.DataFrame,
    leakage: pl.DataFrame,
    dm_comparisons: pl.DataFrame,
    *,
    metrics_by_regime_horizon: pl.DataFrame | None = None,
    final_evaluation_metrics: pl.DataFrame | None = None,
    hyperparameter_tuning: pl.DataFrame | None = None,
    series_revisions: pl.DataFrame | None = None,
    model_stability: pl.DataFrame | None = None,
    target_revision_summary: pl.DataFrame | None = None,
    news_updates: Sequence[Mapping[str, object]] | None = None,
    timing_summary: str | None = None,
    timing_precision_audit: pl.DataFrame | None = None,
) -> str:
    """Render a narrowly scoped empirical report without policy extrapolation."""

    metric_columns = [
        "target_series_id",
        "data_mode",
        "horizon",
        "model_id",
        "n_forecasts",
        "rmse",
        "mae",
        "bias",
        "directional_accuracy",
        "interval_coverage",
    ]
    leakage_columns = [
        "target_series_id",
        "information_set_mode",
        "feature_cells",
        "selected_vintage_after_origin_cells",
        "first_eligibility_after_origin_cells",
        "missing_feature_cells",
    ]
    dm_columns = [
        "target_series_id",
        "data_mode",
        "horizon",
        "hac_lag",
        "evaluation_block",
        "challenger_model",
        "n_obs",
        "statistic",
        "p_value",
        "valid",
        "reason",
    ]
    regime_columns = [
        "target_series_id",
        "data_mode",
        "model_id",
        "horizon",
        "regime",
        "n_forecasts",
        "rmse",
        "mae",
        "bias",
        "directional_accuracy",
        "interval_coverage",
        "sample_start",
        "sample_end",
    ]
    timing_statement = timing_summary or (
        "Date-only releases use the previous calendar day at New York EOD as the "
        "forecast origin; exact historical intraday timing is not claimed."
    )
    timing_precision_sections: list[str] = []
    if timing_precision_audit is not None:
        timing_effects = (
            timing_precision_audit.group_by("timing_quality")
            .agg(
                pl.len().alias("origin_rows"),
                (pl.col("origin_shift_microseconds") != 0)
                .sum()
                .alias("origins_changed_from_date_only"),
                (pl.col("origin_shift_microseconds").min() / 1_000_000).alias(
                    "minimum_origin_shift_seconds"
                ),
                (pl.col("origin_shift_microseconds").max() / 1_000_000).alias(
                    "maximum_origin_shift_seconds"
                ),
                pl.col("changed_feature_value_cells").sum(),
                pl.col("changed_feature_selection_cells").sum(),
                pl.col("changed_target_value_rows").sum(),
            )
            .sort("timing_quality")
        )
        timing_precision_sections = [
            "## Target-clock precision counterfactual",
            "",
            _markdown_table(
                timing_effects,
                [
                    "timing_quality",
                    "origin_rows",
                    "origins_changed_from_date_only",
                    "minimum_origin_shift_seconds",
                    "maximum_origin_shift_seconds",
                    "changed_feature_value_cells",
                    "changed_feature_selection_cells",
                    "changed_target_value_rows",
                ],
            ),
            "",
            "This audit rebuilds the complete feature and target panels after replacing "
            "verified target clocks with the prior conservative date-only convention. "
            "A zero changed-cell count is an observed result for this predictor set, not "
            "an assumption that intraday precision never matters.",
            "",
        ]
    revision_columns = [
        "series_id",
        "observation_count",
        "revision_count",
        "mean_revision",
        "mean_abs_revision",
        "max_abs_revision",
    ]
    stability_columns = [
        "target_series_id",
        "horizon",
        "comparison_mode",
        "model_id",
        "n_aligned",
        "mean_abs_prediction_difference",
        "vintage_rmse_rank",
        "counterfactual_rmse_rank",
        "rank_change",
        "rmse_rank_evaluation_block",
    ]
    target_revision_columns = [
        "target_series_id",
        "horizon",
        "model_id",
        "n_forecasts",
        "mae_first_release",
        "mae_latest_revised",
        "mean_target_revision",
        "mean_abs_target_revision",
        "mean_change_in_absolute_error_due_to_target_revision",
    ]
    revision_sections: list[str] = []
    if series_revisions is not None:
        revision_sections.extend(
            [
                "## Source-series revision distributions",
                "",
                _markdown_table(series_revisions, revision_columns),
                "",
                "Values retain their native units, so revision magnitudes must not be "
                "ranked across unlike series without normalization.",
                "",
            ]
        )
    if target_revision_summary is not None:
        revision_sections.extend(
            [
                "## Target-revision effect with forecasts held fixed",
                "",
                _markdown_table(target_revision_summary, target_revision_columns),
                "",
                "The error change in this table holds each historical vintage-aware "
                "forecast fixed and changes only the target realization.",
                "",
            ]
        )
    if model_stability is not None:
        revision_sections.extend(
            [
                "## Prediction and rank stability across information modes",
                "",
                _markdown_table(model_stability, stability_columns),
                "",
                "Fixed-mask comparisons isolate revised values among historically eligible "
                "cells. Naive comparisons also include measured timing leakage.",
                "",
            ]
        )
    news_sections: list[str] = []
    if news_updates is not None:
        news_frame = pl.from_dicts(
            [
                {
                    "target_series_id": update["target_series_id"],
                    "release_series_id": update["release_series_id"],
                    "release_observation_date": update["release_observation_date"],
                    "forecast_target_period": update["forecast_target_period"],
                    "horizon": update["horizon"],
                    "training_rows": update["training_rows"],
                    "previous_nowcast": update["previous_nowcast"],
                    "updated_nowcast": update["updated_nowcast"],
                    "forecast_revision": update["forecast_revision"],
                    "attribution_residual": update["unattributed_residual"],
                }
                for update in news_updates
            ]
        )
        news_sections.extend(
            [
                "## Official archive release updates",
                "",
                _markdown_table(
                    news_frame,
                    [
                        "target_series_id",
                        "release_series_id",
                        "release_observation_date",
                        "forecast_target_period",
                        "horizon",
                        "training_rows",
                        "previous_nowcast",
                        "updated_nowcast",
                        "forecast_revision",
                        "attribution_residual",
                    ],
                ),
                "",
                "Each row freezes one Elastic Net trained only on targets released before "
                "the event. The exact contribution tables and guarded interpretation are "
                "in `news_updates.json` and the three generated policy briefs.",
                "",
            ]
        )
    regime_sections: list[str] = []
    if metrics_by_regime_horizon is not None:
        horizons = sorted(metrics_by_regime_horizon["horizon"].unique().to_list())
        if horizons == [0]:
            horizon_statement = (
                "The supplied results contain only release nowcasts (`0`), so this table "
                "does not constitute a multi-horizon comparison."
            )
        else:
            horizon_statement = (
                "Horizon `0` is the target-release nowcast and horizon `1` is one native "
                "target period ahead (one month for PAYEMS/core CPI; one quarter for GDP)."
            )
        regime_sections.extend(
            [
                "## Performance by forecast horizon and ex-post NBER regime",
                "",
                _markdown_table(metrics_by_regime_horizon, regime_columns),
                "",
                "NBER peak/trough labels are ex-post evaluation strata and never model "
                f"features. {horizon_statement} Recession groups are small and their metrics "
                "are descriptive, not model-superiority or policy evidence. Source: "
                f"{NBER_REGIME_SOURCE_URL} (chronology last updated "
                f"{NBER_REGIME_SOURCE_LAST_UPDATED}; verified {NBER_REGIME_VERIFIED_AT}).",
                "",
            ]
        )
    tuning_sections: list[str] = []
    if hyperparameter_tuning is not None and final_evaluation_metrics is not None:
        selected_tuning = hyperparameter_tuning.filter(pl.col("selected"))
        tuning_sections.extend(
            [
                "## Prespecified tuning and untouched final evaluation",
                "",
                _markdown_table(
                    selected_tuning,
                    [
                        "target_series_id",
                        "horizon",
                        "model_id",
                        "parameters_json",
                        "validation_forecasts",
                        "validation_rmse",
                        "tuning_start",
                        "tuning_end",
                        "final_evaluation_start",
                        "final_evaluation_end",
                        "final_evaluation_rows_used_for_selection",
                    ],
                ),
                "",
                "Candidate selection uses only vintage-aware tuning-validation forecasts. "
                "The final block contributes zero rows to hyperparameter selection; one "
                "selected setting per target/horizon is frozen across all information modes.",
                "",
                "### Final-evaluation metrics",
                "",
                _markdown_table(final_evaluation_metrics, metric_columns),
                "",
                "These holdout rows are the appropriate model-ranking diagnostic for the "
                "selected advanced specifications. Small samples and multiple comparisons "
                "still preclude broad superiority claims.",
                "",
            ]
        )
    return "\n".join(
        [
            "# Official Agency Archive Empirical Pilot",
            "",
            "> **SCOPED EMPIRICAL EVIDENCE.** This run uses official BLS CES, BLS core-CPI, "
            "and BEA published real-GDP archives. Predictors include own lags, cross-target "
            "values, eight genuine BLS CES sector-employment vintage matrices, CPS "
            "unemployment, DOL initial claims, Fed G.17 industrial production, Treasury "
            "10-year CMT observations, and Census MARTS retail sales plus Census NRC "
            "housing starts. The "
            "full cross-agency indicator set is "
            "not yet historical-vintage complete, so this run "
            "does not support broad-indicator, regime, investment, monetary-policy, or "
            "model-superiority claims.",
            "",
            "## Timing and target conventions",
            "",
            f"- {timing_statement}",
            "- PAYEMS is the same-snapshot monthly level difference.",
            "- Core CPI is the same-snapshot nonannualized monthly percent change.",
            "- GDP is BEA's already transformed published q/q SAAR value and is not "
            "annualized again.",
            "- A separate 96-quarter NIPA level-derived validation uses adjacent levels "
            "from one snapshot; raw levels are excluded from revision summaries because "
            "benchmark definitions change across vintages.",
            "- `latest_values_same_eligibility_mask` is a revision-value counterfactual. "
            "`naive_latest_revised` is intentionally leaky.",
            "",
            *timing_precision_sections,
            "## Forecast metrics",
            "",
            _markdown_table(metrics, metric_columns),
            "",
            "Metric magnitudes are not comparable across targets with different units. "
            "Rows are descriptive; ranking alone is not evidence of structural superiority.",
            "",
            *tuning_sections,
            *regime_sections,
            "## Feature timing and leakage audit",
            "",
            _markdown_table(leakage, leakage_columns),
            "",
            "Strict as-of rows must have zero selected-vintage-after-origin cells. The "
            "fixed-mask mode may substitute later values only for historically eligible "
            "cells. Naive first-eligibility violations are deliberately measured leakage.",
            "",
            *news_sections,
            *revision_sections,
            "## Guarded Diebold-Mariano diagnostics",
            "",
            _markdown_table(dm_comparisons, dm_columns),
            "",
            "Invalid or degenerate comparisons remain labeled invalid. Reported p-values "
            "are diagnostics for this fixed pilot design, not multiple-testing-adjusted "
            "policy evidence.",
            "",
        ]
    )


def reproduce_official_pilot(
    source_dir: str | Path = DEFAULT_SOURCE_DIR,
    *,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    overwrite: bool = False,
) -> dict[str, object]:
    """Run the official-archive empirical pilot without network access."""

    source = Path(source_dir).resolve()
    destination = Path(output_dir).resolve()
    manifest_path = destination / "run_manifest.json"
    if manifest_path.exists() and not overwrite:
        raise FileExistsError("official pilot artifacts exist; pass overwrite=True explicitly")
    destination.mkdir(parents=True, exist_ok=True)
    observations = pl.read_parquet(source / "official_vintage_observations.parquet")
    release_calendar = pl.read_parquet(source / "official_release_calendar.parquet")
    source_manifest_path = source / "ingestion_manifest.json"
    source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    latest_as_of = release_calendar["release_timestamp"].max()
    built_at = observations["download_timestamp"].max()
    target_specs = tuple(definition.target_spec for definition in PILOT_TARGETS)
    targets = build_targets(
        observations,
        release_calendar,
        latest_as_of=latest_as_of,
        specs=target_specs,
        built_at=built_at,
    )
    assert_target_audit(targets)
    origins, features = build_official_pilot_features(observations, release_calendar)
    conservative_calendar = _date_only_target_timing_counterfactual(release_calendar)
    conservative_targets = build_targets(
        observations,
        conservative_calendar,
        latest_as_of=latest_as_of,
        specs=target_specs,
        built_at=built_at,
    )
    conservative_origins, conservative_features = build_official_pilot_features(
        observations,
        conservative_calendar,
    )
    timing_precision_audit = build_target_timing_precision_audit(
        release_calendar,
        origins,
        features,
        targets,
        conservative_origins,
        conservative_features,
        conservative_targets,
    )
    datasets = build_official_research_datasets(features, targets)
    hyperparameter_tuning, advanced_model_parameters = tune_official_advanced_models(
        datasets
    )
    predictions, metrics, dm_comparisons = run_official_pilot_backtests(
        datasets,
        advanced_model_parameters=advanced_model_parameters,
    )
    final_evaluation_metrics = official_final_evaluation_metrics(predictions)
    metrics_by_regime_horizon = official_metrics_by_regime_horizon(predictions)
    leakage = (
        features.group_by(["target_series_id", "information_set_mode"])
        .agg(
            pl.len().alias("feature_cells"),
            (pl.col("max_source_availability") > pl.col("as_of_timestamp"))
            .sum()
            .alias("selected_vintage_after_origin_cells"),
            (pl.col("max_eligibility_availability") > pl.col("as_of_timestamp"))
            .sum()
            .alias("first_eligibility_after_origin_cells"),
            pl.col("is_missing").sum().alias("missing_feature_cells"),
        )
        .sort(["target_series_id", "information_set_mode"])
    )
    if leakage.filter(
        (pl.col("information_set_mode") == AS_OF_MODE)
        & (pl.col("selected_vintage_after_origin_cells") > 0)
    ).height:
        raise AssertionError("official strict feature mode contains future information")
    revision_observations = official_revision_eligible_observations(observations)
    source_revision_details = revision_details(revision_observations)
    source_revision_summary = revision_summary(revision_observations)
    model_stability = official_model_stability(predictions, final_evaluation_metrics)
    target_revision_details, target_revision_summary = official_target_revision_effects(
        targets,
        predictions,
    )
    news_updates = build_official_news_updates(
        observations,
        release_calendar,
        datasets,
        predictions,
        advanced_model_parameters=advanced_model_parameters,
    )

    store = VintageStore(destination, destination / "official_pilot.duckdb")
    frames = {
        "forecast_origins": origins,
        "features_long": features,
        "targets": targets,
        "research_datasets": datasets,
        "predictions": predictions,
        "metrics": metrics,
        "final_evaluation_metrics": final_evaluation_metrics,
        "hyperparameter_tuning": hyperparameter_tuning,
        "metrics_by_regime_horizon": metrics_by_regime_horizon,
        "dm_comparisons": dm_comparisons,
        "feature_leakage_audit": leakage,
        "revision_details": source_revision_details,
        "revisions": source_revision_summary,
        "model_stability": model_stability,
        "target_revision_effects": target_revision_details,
        "target_revision_summary": target_revision_summary,
        "target_timing_precision_audit": timing_precision_audit,
    }
    artifact_paths = {
        name: _write_frame(frame, destination, store, name) for name, frame in frames.items()
    }
    news_path = destination / "news_updates.json"
    write_json(
        {
            "evidence_tier": "official_archive_pilot",
            "data_provenance": OFFICIAL_PROVENANCE,
            "broad_policy_or_model_claims_supported": False,
            "updates": news_updates,
        },
        news_path,
    )
    artifact_paths["news_updates"] = news_path
    brief_dir = destination / "policy_briefs"
    brief_dir.mkdir(parents=True, exist_ok=True)
    for update in news_updates:
        target_id = str(update["target_series_id"])
        brief_path = brief_dir / f"{target_id}_official_policy_brief.md"
        brief_path.write_text(render_official_policy_brief(update), encoding="utf-8")
        artifact_paths[f"policy_brief_{target_id}"] = brief_path
    report_path = destination / "official_pilot_report.md"
    report_path.write_text(
        render_official_pilot_report(
            metrics,
            leakage,
            dm_comparisons,
            metrics_by_regime_horizon=metrics_by_regime_horizon,
            final_evaluation_metrics=final_evaluation_metrics,
            hyperparameter_tuning=hyperparameter_tuning,
            series_revisions=source_revision_summary,
            model_stability=model_stability,
            target_revision_summary=target_revision_summary,
            news_updates=news_updates,
            timing_summary=(
                "Employment Situation, CPI, and GDP events with verified release headers "
                "use an origin one second before the exact release clock. Official TXT "
                "evidence covers the acquired pre-2008 PAYEMS window; only the retained "
                "2012-12-07 EST/EDT conflict remains on the conservative prior-New-York-"
                "day EOD rule."
            ),
            timing_precision_audit=timing_precision_audit,
        ),
        encoding="utf-8",
    )
    artifact_paths["official_pilot_report"] = report_path
    manifest: dict[str, Any] = {
        "status": "complete",
        "artifact_stage": ARTIFACT_STAGE,
        "data_provenance": OFFICIAL_PROVENANCE,
        "network_used": False,
        "api_credentials_used": False,
        "api_txt_read": False,
        "source_manifest": str(source_manifest_path),
        "source_manifest_sha256": sha256_file(source_manifest_path),
        "latest_evaluation_cutoff": latest_as_of,
        "intraday_timing_verified": False,
        "target_intraday_timing_partially_verified": bool(
            source_manifest.get("target_intraday_timing_partially_verified", False)
        ),
        "employment_situation_exact_release_clock_count": int(
            source_manifest.get("employment_situation_exact_release_clock_count", 0)
        ),
        "employment_situation_html_exact_release_clock_count": int(
            source_manifest.get(
                "employment_situation_html_exact_release_clock_count",
                0,
            )
        ),
        "employment_situation_txt_exact_release_clock_count": int(
            source_manifest.get(
                "employment_situation_txt_exact_release_clock_count",
                0,
            )
        ),
        "employment_situation_txt_clock_evidence_sha256": source_manifest.get(
            "employment_situation_txt_clock_evidence_sha256"
        ),
        "payems_target_release_clock_count": int(
            source_manifest.get("payems_target_release_clock_count", 0)
        ),
        "employment_situation_date_only_clock_exclusions": source_manifest.get(
            "employment_situation_date_only_clock_exclusions", {}
        ),
        "cpi_exact_release_clock_count": int(
            source_manifest.get("cpi_exact_release_clock_count", 0)
        ),
        "cpi_target_release_clock_count": int(
            source_manifest.get("cpi_target_release_clock_count", 0)
        ),
        "cpi_release_clock_evidence_sha256": source_manifest.get(
            "cpi_release_clock_evidence_sha256"
        ),
        "gdp_exact_release_clock_count": int(
            source_manifest.get("gdp_exact_release_clock_count", 0)
        ),
        "gdp_target_release_clock_count": int(
            source_manifest.get("gdp_target_release_clock_count", 0)
        ),
        "gdp_release_clock_evidence_sha256": source_manifest.get(
            "gdp_release_clock_evidence_sha256"
        ),
        "gdp_release_clock_source_date_discrepancies": source_manifest.get(
            "gdp_release_clock_source_date_discrepancies", {}
        ),
        "gdp_target_semantics": source_manifest.get(
            "gdp_target_semantics",
            "official_published_qoq_saar_growth_not_level_derived",
        ),
        "gdp_nipa_level_vintages_included": bool(
            source_manifest.get("gdp_nipa_level_vintages_included", False)
        ),
        "gdp_nipa_level_series_id": source_manifest.get(
            "gdp_nipa_level_series_id", BEA_NIPA_LEVEL_SERIES_ID
        ),
        "gdp_nipa_level_canonical_rows": int(
            source_manifest.get("gdp_nipa_level_canonical_rows", 0)
        ),
        "gdp_nipa_level_release_snapshots": int(
            source_manifest.get("gdp_nipa_level_release_snapshots", 0)
        ),
        "gdp_nipa_level_missing_target_quarters": source_manifest.get(
            "gdp_nipa_level_missing_target_quarters", []
        ),
        "gdp_nipa_level_same_snapshot_growth_supported": bool(
            source_manifest.get(
                "gdp_nipa_level_same_snapshot_growth_supported", False
            )
        ),
        "gdp_nipa_level_cross_vintage_raw_level_comparison_supported": False,
        "gdp_nipa_level_raw_revision_analysis_included": False,
        "gdp_level_target_validation_artifact": source_manifest.get(
            "gdp_level_target_validation_artifact"
        ),
        "timing_convention": source_manifest.get(
            "timing_convention", "official_date_eod_convention"
        ),
        "forecast_origin_rule": source_manifest.get(
            "forecast_origin_rule", "previous_calendar_day_eod_America/New_York"
        ),
        "target_release_timing_counts": {
            str(row["timing_quality"]): int(row["len"])
            for row in release_calendar.filter(
                pl.col("series_id").is_in(
                    [definition.target_spec.series_id for definition in PILOT_TARGETS]
                )
                & (pl.col("release_type") == "initial")
            )
            .group_by("timing_quality")
            .len()
            .to_dicts()
        },
        "origins_changed_from_date_only_timing": int(
            timing_precision_audit.filter(pl.col("origin_shift_microseconds") != 0).height
        ),
        "feature_value_cells_changed_by_target_timing_precision": int(
            timing_precision_audit["changed_feature_value_cells"].sum()
        ),
        "feature_selection_cells_changed_by_target_timing_precision": int(
            timing_precision_audit["changed_feature_selection_cells"].sum()
        ),
        "target_value_rows_changed_by_target_timing_precision": int(
            timing_precision_audit["changed_target_value_rows"].sum()
        ),
        "scope": (
            "official CES/core-CPI/GDP targets with cross-target, eight BLS CES "
            "sector-employment, BLS CPS unemployment-rate, DOL weekly initial-claims, "
            "Federal Reserve G.17 industrial-production, official daily Treasury 10-year "
            "CMT point observations, and Census MARTS retail-sales plus Census NRC "
            "housing-start vintage predictors; BEA NIPA real-GDP level snapshots are "
            "retained as a separate same-snapshot target-validation layer"
        ),
        "broader_indicator_vintages_included": False,
        "sectoral_ces_predictor_vintages_included": True,
        "cps_unemployment_rate_predictor_vintages_included": True,
        "cps_unemployment_rate_series_id": UNEMPLOYMENT_RATE_SERIES_ID,
        "dol_weekly_claims_predictor_vintages_included": True,
        "dol_weekly_claims_series_id": DOL_CLAIMS_SERIES_ID,
        "dol_weekly_claims_4wma_series_id": DOL_CLAIMS_4WMA_SERIES_ID,
        "dol_weekly_claims_intraday_timing_verified": True,
        "fed_g17_predictor_vintages_included": True,
        "fed_g17_index_series_id": FED_G17_INDEX_SERIES_ID,
        "fed_g17_mom_series_id": FED_G17_MOM_SERIES_ID,
        "fed_g17_release_clock_times_verified": True,
        "treasury_10y_daily_observations_included": bool(
            source_manifest.get("treasury_10y_daily_observations_included", False)
        ),
        "treasury_10y_series_id": TREASURY_10Y_SERIES_ID,
        "treasury_10y_timing_quality": source_manifest.get(
            "treasury_10y_timing_quality", TREASURY_RATES_TIMING_QUALITY
        ),
        "treasury_10y_availability_rule": source_manifest.get(
            "treasury_10y_availability_rule", TREASURY_RATES_AVAILABILITY_RULE
        ),
        "treasury_10y_exact_publication_clock_claimed": False,
        "treasury_10y_publication_vintage_dimension_available": False,
        "treasury_10y_later_correction_history_available": False,
        "census_retail_predictor_vintages_included": True,
        "census_retail_level_series_id": CENSUS_RETAIL_LEVEL_SERIES_ID,
        "census_retail_mom_series_id": CENSUS_RETAIL_MOM_SERIES_ID,
        "census_retail_release_clock_times_verified": True,
        "census_housing_predictor_vintages_included": True,
        "census_housing_starts_series_id": CENSUS_HOUSING_STARTS_SERIES_ID,
        "census_housing_release_clock_times_verified": True,
        "full_configured_predictor_set_included": False,
        "official_predictor_series": sorted(
            {spec.series_id for definition in PILOT_TARGETS for spec in definition.feature_specs}
        ),
        "ces_sector_predictor_series": [
            {
                "series_id": spec.series_id,
                "agency_series_id": spec.agency_series_id,
                "industry_title": spec.industry_title,
                "archive_member": spec.archive_member,
            }
            for spec in CES_SECTOR_PREDICTOR_SPECS
        ],
        "empirical_pilot_findings_supported": True,
        "broad_model_or_policy_claims_supported": False,
        "observation_rows": observations.height,
        "origin_rows": origins.height,
        "feature_cells": features.height,
        "target_rows": targets.height,
        "research_rows": datasets.height,
        "prediction_rows": predictions.height,
        "forecast_horizons": sorted(predictions["horizon"].unique().to_list()),
        "horizon_definition": (
            "0=target-release nowcast; 1=one native target period ahead "
            "(month for PAYEMS/core CPI, quarter for GDP)"
        ),
        "dm_hac_convention": "DM horizon argument=horizon+1, so HAC lag equals horizon",
        "metric_rows": metrics.height,
        "final_evaluation_metric_rows": final_evaluation_metrics.height,
        "hyperparameter_tuning_candidate_rows": hyperparameter_tuning.height,
        "hyperparameter_tuning_selected_rows": hyperparameter_tuning.filter(
            pl.col("selected")
        ).height,
        "hyperparameter_selection_data_mode": "vintage_aware",
        "hyperparameter_selection_metric": "rmse",
        "final_evaluation_rows_used_for_hyperparameter_selection": int(
            hyperparameter_tuning[
                "final_evaluation_rows_used_for_selection"
            ].sum()
        ),
        "selected_hyperparameters": hyperparameter_tuning.filter(
            pl.col("selected")
        ).select(
            "target_series_id",
            "horizon",
            "model_id",
            "parameters_json",
            "tuning_start",
            "tuning_end",
            "final_evaluation_start",
            "final_evaluation_end",
        ).to_dicts(),
        "regime_metric_rows": metrics_by_regime_horizon.height,
        "regime_definition": NBER_REGIME_DEFINITION,
        "regime_source_url": NBER_REGIME_SOURCE_URL,
        "regime_source_last_updated": NBER_REGIME_SOURCE_LAST_UPDATED,
        "regime_verified_at": NBER_REGIME_VERIFIED_AT,
        "regime_is_forecast_input": False,
        "dm_rows": dm_comparisons.height,
        "source_revision_detail_rows": source_revision_details.height,
        "source_revision_summary_rows": source_revision_summary.height,
        "model_stability_rows": model_stability.height,
        "target_revision_effect_rows": target_revision_details.height,
        "target_revision_summary_rows": target_revision_summary.height,
        "release_update_count": len(news_updates),
        "policy_brief_count": len(news_updates),
        "maximum_attribution_residual": max(
            abs(float(update["unattributed_residual"])) for update in news_updates
        ),
        "strict_feature_timing_violations": int(
            leakage.filter(pl.col("information_set_mode") == AS_OF_MODE)[
                "selected_vintage_after_origin_cells"
            ].sum()
        ),
        "naive_first_eligibility_after_origin_cells": int(
            leakage.filter(pl.col("information_set_mode") == NAIVE_LATEST_MODE)[
                "first_eligibility_after_origin_cells"
            ].sum()
        ),
        "models": sorted(predictions["model_id"].unique().to_list()),
        "target_definitions": [
            {
                "target_series_id": definition.output_series_id,
                "source_series_id": definition.target_spec.series_id,
                "target_name": definition.target_spec.target_name,
                "target_frequency": definition.frequency,
                "target_units": definition.target_spec.target_units,
                "target_formula": definition.target_spec.formula,
                "minimum_train_periods": definition.min_train_size,
                "forecast_horizons": list(definition.horizons),
                "tuning_periods": definition.tuning_periods,
                "final_evaluation_periods": definition.final_evaluation_periods,
                "feature_definitions": [
                    {
                        "name": spec.name,
                        "series_id": spec.series_id,
                        "frequency": spec.frequency,
                        "transformation": spec.transformation,
                        "aggregation": spec.aggregation,
                        "lag_periods": spec.lag_periods,
                    }
                    for spec in definition.feature_specs
                ],
            }
            for definition in PILOT_TARGETS
        ],
        "artifacts": {
            name: {
                "path": str(path.relative_to(destination)),
                "sha256": sha256_file(path),
            }
            for name, path in artifact_paths.items()
        },
        "package_versions": package_versions(),
    }
    write_json(manifest, manifest_path)
    return {
        "status": "complete",
        "output_dir": destination,
        "targets": len(PILOT_TARGETS),
        "feature_cells": features.height,
        "target_rows": targets.height,
        "predictions": predictions.height,
        "release_updates": len(news_updates),
        "policy_briefs": len(news_updates),
        "strict_timing_violations": 0,
        "empirical_scope": "official_archive_pilot",
    }


__all__ = [
    "ARTIFACT_STAGE",
    "DEFAULT_OUTPUT_DIR",
    "DEFAULT_SOURCE_DIR",
    "ELASTIC_NET_TUNING_GRID",
    "EXPERIMENTS",
    "HIST_GRADIENT_BOOSTING_TUNING_GRID",
    "OFFICIAL_PROVENANCE",
    "PILOT_TARGETS",
    "OfficialPilotTarget",
    "build_official_news_updates",
    "build_official_pilot_features",
    "build_official_research_datasets",
    "build_target_timing_precision_audit",
    "official_final_evaluation_metrics",
    "official_metrics_by_regime_horizon",
    "official_model_stability",
    "official_revision_eligible_observations",
    "official_target_revision_effects",
    "render_official_pilot_report",
    "render_official_policy_brief",
    "reproduce_official_pilot",
    "run_official_pilot_backtests",
    "tune_official_advanced_models",
]
