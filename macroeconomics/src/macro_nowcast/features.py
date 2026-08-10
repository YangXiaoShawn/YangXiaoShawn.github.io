"""Audited feature and target construction after vintage selection."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Literal

import polars as pl

from macro_nowcast.asof import (
    AS_OF_MODE,
    LATEST_SAME_MASK_MODE,
    NAIVE_LATEST_MODE,
    select_as_of,
    select_latest_values_same_eligibility_mask,
    select_naive_latest_revised,
)
from macro_nowcast.calendar import validate_release_calendar

InformationSetMode = Literal[
    "as_of",
    "latest_values_same_eligibility_mask",
    "naive_latest_revised",
]


@dataclass(frozen=True, slots=True)
class FeatureSpec:
    name: str
    series_id: str
    frequency: Literal["quarterly", "monthly", "weekly", "daily"]
    transformation: Literal[
        "level",
        "difference",
        "percent_change",
        "annualized_percent_change",
        "log_change",
    ]
    aggregation: Literal["latest", "trailing_mean"]
    window: int | None = None
    lag_periods: int = 0

    def __post_init__(self) -> None:
        if not self.name or not self.series_id:
            raise ValueError("feature name and series_id cannot be empty")
        if self.lag_periods < 0:
            raise ValueError("lag_periods cannot be negative")
        if self.aggregation == "trailing_mean" and (self.window is None or self.window < 1):
            raise ValueError("trailing_mean requires a positive window")
        if self.aggregation == "latest" and self.window is not None:
            raise ValueError("latest aggregation cannot define a window")
        if self.aggregation == "trailing_mean" and self.frequency in {
            "monthly",
            "quarterly",
        }:
            raise ValueError("monthly and quarterly features require latest aggregation")
        if self.frequency not in {"monthly", "quarterly"} and self.lag_periods:
            raise ValueError("lag_periods is defined only for monthly and quarterly features")
        if self.transformation == "annualized_percent_change" and self.frequency != "quarterly":
            raise ValueError("annualized_percent_change is defined only for quarterly features")


DEFAULT_FEATURE_SPECS = (
    FeatureSpec("payems_change_lag1", "PAYEMS", "monthly", "difference", "latest", lag_periods=1),
    FeatureSpec("icsa_4w_mean", "ICSA", "weekly", "level", "trailing_mean", window=4),
    FeatureSpec("ccsa_4w_mean", "CCSA", "weekly", "level", "trailing_mean", window=4),
    FeatureSpec("unrate_level", "UNRATE", "monthly", "level", "latest"),
    FeatureSpec("awhman_change", "AWHMAN", "monthly", "difference", "latest"),
    FeatureSpec("indpro_pct_change", "INDPRO", "monthly", "percent_change", "latest"),
    FeatureSpec("rsafs_pct_change", "RSAFS", "monthly", "percent_change", "latest"),
    FeatureSpec("houst_log_change", "HOUST", "monthly", "log_change", "latest"),
    FeatureSpec("umcsent_change", "UMCSENT", "monthly", "difference", "latest"),
    FeatureSpec("dgs10_20d_mean", "DGS10", "daily", "level", "trailing_mean", window=20),
)

CORE_INFLATION_FEATURE_SPECS = (
    FeatureSpec(
        "core_cpi_pct_change_lag1",
        "CPILFESL",
        "monthly",
        "percent_change",
        "latest",
        lag_periods=1,
    ),
    FeatureSpec("payems_change", "PAYEMS", "monthly", "difference", "latest"),
    FeatureSpec("unrate_level", "UNRATE", "monthly", "level", "latest"),
    FeatureSpec("awhman_change", "AWHMAN", "monthly", "difference", "latest"),
    FeatureSpec("indpro_pct_change", "INDPRO", "monthly", "percent_change", "latest"),
    FeatureSpec("rsafs_pct_change", "RSAFS", "monthly", "percent_change", "latest"),
    FeatureSpec("houst_log_change", "HOUST", "monthly", "log_change", "latest"),
    FeatureSpec("icsa_4w_mean", "ICSA", "weekly", "level", "trailing_mean", window=4),
    FeatureSpec("umcsent_change", "UMCSENT", "monthly", "difference", "latest"),
    FeatureSpec("dgs10_20d_mean", "DGS10", "daily", "level", "trailing_mean", window=20),
)

REAL_GDP_FEATURE_SPECS = (
    FeatureSpec(
        "real_gdp_qoq_saar_lag1",
        "GDPC1",
        "quarterly",
        "annualized_percent_change",
        "latest",
        lag_periods=1,
    ),
    FeatureSpec("indpro_pct_change", "INDPRO", "monthly", "percent_change", "latest"),
    FeatureSpec("rsafs_pct_change", "RSAFS", "monthly", "percent_change", "latest"),
    FeatureSpec("houst_log_change", "HOUST", "monthly", "log_change", "latest"),
    FeatureSpec("payems_change", "PAYEMS", "monthly", "difference", "latest"),
    FeatureSpec("unrate_level", "UNRATE", "monthly", "level", "latest"),
    FeatureSpec("awhman_change", "AWHMAN", "monthly", "difference", "latest"),
    FeatureSpec("icsa_4w_mean", "ICSA", "weekly", "level", "trailing_mean", window=4),
    FeatureSpec("ccsa_4w_mean", "CCSA", "weekly", "level", "trailing_mean", window=4),
    FeatureSpec("dgs10_20d_mean", "DGS10", "daily", "level", "trailing_mean", window=20),
)

TARGET_FEATURE_SPECS: dict[str, tuple[FeatureSpec, ...]] = {
    "PAYEMS": DEFAULT_FEATURE_SPECS,
    "CPILFESL": CORE_INFLATION_FEATURE_SPECS,
    "GDPC1": REAL_GDP_FEATURE_SPECS,
}

FEATURE_AUDIT_SCHEMA = pl.Schema(
    {
        "forecast_id": pl.String,
        "target_series_id": pl.String,
        "target_period": pl.Date,
        "target_frequency": pl.String,
        "as_of_timestamp": pl.Datetime("us", "UTC"),
        "feature_name": pl.String,
        "source_series_id": pl.String,
        "value": pl.Float64,
        "units": pl.String,
        "transformation": pl.String,
        "aggregation": pl.String,
        "information_set_mode": pl.String,
        "is_counterfactual": pl.Boolean,
        "max_source_availability": pl.Datetime("us", "UTC"),
        "max_eligibility_availability": pl.Datetime("us", "UTC"),
        "source_period_cutoff": pl.Date,
        "latest_source_observation_date": pl.Date,
        "source_staleness_periods": pl.Int64,
        "staleness_unit": pl.String,
        "is_partial_period": pl.Boolean,
        "period_observation_count": pl.Int64,
        "expected_period_observation_count": pl.Int64,
        "coverage_ratio": pl.Float64,
        "source_observation_count": pl.Int64,
        "non_null_source_observation_count": pl.Int64,
        "is_missing": pl.Boolean,
        "provenance_label": pl.String,
    }
)

TARGET_SCHEMA = pl.Schema(
    {
        "target_series_id": pl.String,
        "target_period": pl.Date,
        "target_name": pl.String,
        "target_units": pl.String,
        "realization_mode": pl.String,
        "value": pl.Float64,
        "realization_as_of_timestamp": pl.Datetime("us", "UTC"),
        "target_release_timestamp": pl.Datetime("us", "UTC"),
        "current_level_availability": pl.Datetime("us", "UTC"),
        "prior_level_availability": pl.Datetime("us", "UTC"),
        "max_source_availability": pl.Datetime("us", "UTC"),
        "provenance_label": pl.String,
    }
)


def _as_utc(value: datetime | str) -> datetime:
    if isinstance(value, str):
        normalized = f"{value[:-1]}+00:00" if value.endswith("Z") else value
        value = datetime.fromisoformat(normalized)
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("as_of must be a timezone-aware datetime")
    return value.astimezone(UTC)


def _as_month(value: date | str) -> date:
    if isinstance(value, str):
        value = date.fromisoformat(value)
    if isinstance(value, datetime) or not isinstance(value, date):
        raise TypeError("target_period must be a date")
    return value.replace(day=1)


def _add_months(value: date, months: int) -> date:
    absolute_month = value.year * 12 + value.month - 1 + months
    year, zero_based_month = divmod(absolute_month, 12)
    return date(year, zero_based_month + 1, 1)


def _snapshot(
    observations: pl.DataFrame,
    as_of: datetime,
    mode: InformationSetMode,
) -> pl.DataFrame:
    if mode == AS_OF_MODE:
        return select_as_of(observations, as_of)
    if mode == LATEST_SAME_MASK_MODE:
        return select_latest_values_same_eligibility_mask(observations, as_of)
    if mode == NAIVE_LATEST_MODE:
        return select_naive_latest_revised(observations, as_of)
    raise ValueError(f"unsupported information-set mode: {mode}")


def _transform(current: float | None, previous: float | None, kind: str) -> float | None:
    if current is None:
        return None
    if kind == "level":
        return float(current)
    if previous is None:
        return None
    if kind == "difference":
        return float(current - previous)
    if kind == "percent_change":
        return None if previous == 0 else float((current / previous - 1.0) * 100.0)
    if kind == "annualized_percent_change":
        return None if previous == 0 else float(((current / previous) ** 4 - 1.0) * 100.0)
    if kind == "log_change":
        if current <= 0 or previous <= 0:
            return None
        return float((math.log(current) - math.log(previous)) * 100.0)
    raise ValueError(f"unsupported transformation: {kind}")


def _period_cutoff(
    *,
    target_period: date,
    target_frequency: Literal["monthly", "quarterly"],
    source_frequency: str,
    lag_periods: int,
    as_of: datetime,
) -> tuple[date, str]:
    """Return the last eligible source period and its staleness unit.

    Monthly indicators used for a quarterly target are aligned to the quarter's
    final month. Quarterly indicators are aligned to the containing quarter.
    Daily and weekly series retain the ragged edge available at the forecast
    origin, so their cutoff is the origin's UTC date.
    """

    if source_frequency == "monthly":
        anchor = _add_months(target_period, 2) if target_frequency == "quarterly" else target_period
        return _add_months(anchor, -lag_periods), "months"
    if source_frequency == "quarterly":
        quarter = date(
            target_period.year,
            ((target_period.month - 1) // 3) * 3 + 1,
            1,
        )
        return _add_months(quarter, -3 * lag_periods), "quarters"
    return as_of.date(), "days"


def _staleness_periods(
    latest_observation: date | None,
    cutoff: date,
    source_frequency: str,
) -> int | None:
    if latest_observation is None:
        return None
    month_gap = (
        (cutoff.year - latest_observation.year) * 12 + cutoff.month - latest_observation.month
    )
    if source_frequency == "monthly":
        return max(0, month_gap)
    if source_frequency == "quarterly":
        return max(0, month_gap // 3)
    return max(0, (cutoff - latest_observation).days)


def _period_coverage(
    rows: list[dict[str, object]],
    source_rows: list[dict[str, object]],
    spec: FeatureSpec,
    *,
    target_frequency: Literal["monthly", "quarterly"],
    cutoff: date,
) -> tuple[int, int, float]:
    """Record native-period coverage without treating missing rows as released.

    A quarterly target expects three monthly reference periods. The feature may
    still be configured as ``latest``; this audit shows how much of the quarter
    existed at the historical origin instead of completing it with later data.
    """

    if spec.frequency == "monthly":
        expected = 3 if target_frequency == "quarterly" else 1
        start = _add_months(cutoff, -(expected - 1))
        count = len(
            {
                row["observation_date"]
                for row in rows
                if start <= row["observation_date"] <= cutoff  # type: ignore[operator]
            }
        )
    elif spec.frequency == "quarterly":
        expected = 1
        count = int(any(row["observation_date"] == cutoff for row in rows))
    else:
        expected = spec.window or 1
        count = min(len(source_rows), expected)
    return count, expected, count / expected


def _source_rows_for_feature(
    rows: list[dict[str, object]],
    spec: FeatureSpec,
    target_period: date,
    *,
    target_frequency: Literal["monthly", "quarterly"],
    as_of: datetime,
) -> tuple[float | None, list[dict[str, object]], date | None, str, date]:
    cutoff, _ = _period_cutoff(
        target_period=target_period,
        target_frequency=target_frequency,
        source_frequency=spec.frequency,
        lag_periods=spec.lag_periods,
        as_of=as_of,
    )
    if not rows:
        return None, [], None, "unknown", cutoff
    rows.sort(key=lambda row: row["observation_date"])  # type: ignore[arg-type,return-value]
    if spec.frequency in {"monthly", "quarterly"}:
        eligible = [row for row in rows if row["observation_date"] <= cutoff]  # type: ignore[operator]
        if not eligible:
            return None, [], None, str(rows[-1]["units"]), cutoff
        current = eligible[-1]
        source_rows = [current]
        previous: dict[str, object] | None = None
        if spec.transformation != "level":
            step = -3 if spec.frequency == "quarterly" else -1
            expected_previous = _add_months(current["observation_date"], step)  # type: ignore[arg-type]
            if len(eligible) >= 2 and eligible[-2]["observation_date"] == expected_previous:
                previous = eligible[-2]
                source_rows.insert(0, previous)
        value = _transform(
            current["value"],  # type: ignore[arg-type]
            None if previous is None else previous["value"],  # type: ignore[arg-type]
            spec.transformation,
        )
        units = (
            "percent"
            if spec.transformation in {"percent_change", "annualized_percent_change", "log_change"}
            else str(current["units"])
        )
        return value, source_rows, current["observation_date"], units, cutoff  # type: ignore[return-value]

    rows = [row for row in rows if row["observation_date"] <= cutoff]  # type: ignore[operator]
    if not rows:
        return None, [], None, "unknown", cutoff
    if spec.aggregation != "trailing_mean":
        current = rows[-1]
        previous = rows[-2] if len(rows) >= 2 else None
        value = _transform(
            current["value"],  # type: ignore[arg-type]
            None if previous is None else previous["value"],  # type: ignore[arg-type]
            spec.transformation,
        )
        source_rows = [current] if previous is None else [previous, current]
        return value, source_rows, current["observation_date"], str(current["units"]), cutoff  # type: ignore[return-value]

    assert spec.window is not None
    window_rows = rows[-spec.window :]
    values = [float(row["value"]) for row in window_rows if row["value"] is not None]
    value = sum(values) / len(values) if values else None
    units = str(window_rows[-1]["units"])
    return value, window_rows, window_rows[-1]["observation_date"], units, cutoff  # type: ignore[return-value]


def build_feature_vector(
    observations: pl.DataFrame,
    *,
    as_of: datetime | str,
    target_period: date | str,
    specs: Sequence[FeatureSpec] = DEFAULT_FEATURE_SPECS,
    mode: InformationSetMode = AS_OF_MODE,
    target_series_id: str = "PAYEMS",
    target_frequency: Literal["monthly", "quarterly"] = "monthly",
    forecast_id: str | None = None,
) -> pl.DataFrame:
    """Build one long, provenance-rich feature vector from a selected snapshot."""

    cutoff = _as_utc(as_of)
    period = _as_month(target_period)
    if target_frequency == "quarterly" and period.month not in {1, 4, 7, 10}:
        raise ValueError("quarterly target_period must be a quarter-start date")
    if len({spec.name for spec in specs}) != len(specs):
        raise ValueError("feature names must be unique")
    snapshot = _snapshot(observations, cutoff, mode)
    output: list[dict[str, object]] = []
    for spec in specs:
        series_rows = snapshot.filter(pl.col("series_id") == spec.series_id).to_dicts()
        value, source_rows, latest_observation, units, source_period_cutoff = (
            _source_rows_for_feature(
                series_rows,
                spec,
                period,
                target_frequency=target_frequency,
                as_of=cutoff,
            )
        )
        source_availability = [
            row["selected_vintage_availability_timestamp"] for row in source_rows
        ]
        eligibility_availability = [row["eligibility_timestamp"] for row in source_rows]
        labels = {str(row["provenance_label"]) for row in source_rows}
        provenance = next(iter(labels)) if len(labels) == 1 else ("mixed" if labels else "missing")
        period_count, expected_period_count, coverage_ratio = _period_coverage(
            series_rows,
            source_rows,
            spec,
            target_frequency=target_frequency,
            cutoff=source_period_cutoff,
        )
        output.append(
            {
                "forecast_id": forecast_id or f"{target_series_id}:{period.isoformat()}",
                "target_series_id": target_series_id,
                "target_period": period,
                "target_frequency": target_frequency,
                "as_of_timestamp": cutoff,
                "feature_name": spec.name,
                "source_series_id": spec.series_id,
                "value": value,
                "units": units,
                "transformation": spec.transformation,
                "aggregation": spec.aggregation,
                "information_set_mode": mode,
                "is_counterfactual": mode in {LATEST_SAME_MASK_MODE, NAIVE_LATEST_MODE},
                "max_source_availability": max(source_availability, default=None),
                "max_eligibility_availability": max(eligibility_availability, default=None),
                "source_period_cutoff": source_period_cutoff,
                "latest_source_observation_date": latest_observation,
                "source_staleness_periods": _staleness_periods(
                    latest_observation,
                    source_period_cutoff,
                    spec.frequency,
                ),
                "staleness_unit": (
                    "quarters"
                    if spec.frequency == "quarterly"
                    else "months"
                    if spec.frequency == "monthly"
                    else "days"
                ),
                "is_partial_period": (
                    latest_observation is not None and latest_observation < source_period_cutoff
                ),
                "period_observation_count": period_count,
                "expected_period_observation_count": expected_period_count,
                "coverage_ratio": coverage_ratio,
                "source_observation_count": len(source_rows),
                "non_null_source_observation_count": sum(
                    row["value"] is not None for row in source_rows
                ),
                "is_missing": value is None,
                "provenance_label": provenance,
            }
        )
    features = pl.from_dicts(output, schema=FEATURE_AUDIT_SCHEMA, strict=True)
    assert_feature_no_future(features)
    return features.sort("feature_name")


def build_feature_matrix(
    observations: pl.DataFrame,
    forecast_origins: pl.DataFrame,
    *,
    specs: Sequence[FeatureSpec] = DEFAULT_FEATURE_SPECS,
    mode: InformationSetMode = AS_OF_MODE,
    target_frequency: Literal["monthly", "quarterly"] = "monthly",
) -> pl.DataFrame:
    """Build long audited features for every explicit forecast origin."""

    required = {"target_period", "forecast_origin"}
    if missing := required.difference(forecast_origins.columns):
        raise ValueError(f"forecast origins are missing columns: {', '.join(sorted(missing))}")
    frames = []
    for origin in forecast_origins.sort("target_period").iter_rows(named=True):
        origin_frequency = str(origin.get("target_frequency", target_frequency))
        if origin_frequency not in {"monthly", "quarterly"}:
            raise ValueError(f"unsupported target frequency: {origin_frequency}")
        frames.append(
            build_feature_vector(
                observations,
                as_of=origin["forecast_origin"],
                target_period=origin["target_period"],
                specs=specs,
                mode=mode,
                target_series_id=str(origin.get("target_series_id", "PAYEMS")),
                target_frequency=origin_frequency,  # type: ignore[arg-type]
                forecast_id=str(
                    origin.get(
                        "forecast_id",
                        f"PAYEMS:{origin['target_period'].isoformat()}",
                    )
                ),
            )
        )
    return pl.concat(frames) if frames else pl.DataFrame(schema=FEATURE_AUDIT_SCHEMA)


def assert_feature_no_future(features: pl.DataFrame) -> None:
    """Validate strict modes while keeping the naive benchmark explicitly leaky."""

    required = {
        "as_of_timestamp",
        "information_set_mode",
        "max_source_availability",
        "max_eligibility_availability",
    }
    if missing := required.difference(features.columns):
        raise ValueError(f"feature audit columns are missing: {', '.join(sorted(missing))}")
    valid_violations = features.filter(
        (pl.col("information_set_mode") == AS_OF_MODE)
        & (pl.col("max_source_availability") > pl.col("as_of_timestamp"))
    )
    counterfactual_violations = features.filter(
        (pl.col("information_set_mode") == LATEST_SAME_MASK_MODE)
        & (pl.col("max_eligibility_availability") > pl.col("as_of_timestamp"))
    )
    known_modes = {AS_OF_MODE, LATEST_SAME_MASK_MODE, NAIVE_LATEST_MODE}
    unknown_modes = features.filter(~pl.col("information_set_mode").is_in(known_modes))
    mislabeled_naive = features.filter(
        (pl.col("information_set_mode") == NAIVE_LATEST_MODE)
        & ~pl.col("is_counterfactual")
    )
    if (
        valid_violations.height
        or counterfactual_violations.height
        or unknown_modes.height
        or mislabeled_naive.height
    ):
        raise AssertionError("derived feature contains future information")


def _payems_change_row(
    snapshot: pl.DataFrame,
    *,
    target_period: date,
    mode: str,
    realization_as_of: datetime,
    target_release_timestamp: datetime,
) -> dict[str, object] | None:
    previous_period = _add_months(target_period, -1)
    levels = snapshot.filter(
        (pl.col("series_id") == "PAYEMS")
        & pl.col("observation_date").is_in([previous_period, target_period])
    )
    if levels.height != 2:
        return None
    by_period = {row["observation_date"]: row for row in levels.to_dicts()}
    current = by_period.get(target_period)
    previous = by_period.get(previous_period)
    if current is None or previous is None or current["value"] is None or previous["value"] is None:
        return None
    current_availability = current["selected_vintage_availability_timestamp"]
    prior_availability = previous["selected_vintage_availability_timestamp"]
    labels = {str(current["provenance_label"]), str(previous["provenance_label"])}
    return {
        "target_series_id": "PAYEMS",
        "target_period": target_period,
        "target_name": "payems_change_mom_thousands",
        "target_units": "thousands_of_persons_change_mom",
        "realization_mode": mode,
        "value": float(current["value"] - previous["value"]),
        "realization_as_of_timestamp": realization_as_of,
        "target_release_timestamp": target_release_timestamp,
        "current_level_availability": current_availability,
        "prior_level_availability": prior_availability,
        "max_source_availability": max(current_availability, prior_availability),
        "provenance_label": next(iter(labels)) if len(labels) == 1 else "mixed",
    }


def build_payems_targets(
    observations: pl.DataFrame,
    release_calendar: pl.DataFrame,
    *,
    latest_as_of: datetime | str,
) -> pl.DataFrame:
    """Build first-release and fixed-latest PAYEMS monthly-change targets.

    For a first release, both the current and prior levels come from the same
    immediately-post-release snapshot.  This captures the prior-month revision
    published with the current release.
    """

    latest_cutoff = _as_utc(latest_as_of)
    calendar = validate_release_calendar(release_calendar).filter(
        (pl.col("series_id") == "PAYEMS") & (pl.col("release_type") == "initial")
    )
    latest_snapshot = select_as_of(observations, latest_cutoff)
    rows: list[dict[str, object]] = []
    for release in calendar.iter_rows(named=True):
        target_period = release["observation_date"]
        release_timestamp = release["release_timestamp"]
        if release_timestamp > latest_cutoff:
            continue
        first_snapshot = select_as_of(observations, release_timestamp)
        first_row = _payems_change_row(
            first_snapshot,
            target_period=target_period,
            mode="first_release",
            realization_as_of=release_timestamp,
            target_release_timestamp=release_timestamp,
        )
        latest_row = _payems_change_row(
            latest_snapshot,
            target_period=target_period,
            mode="latest_revised",
            realization_as_of=latest_cutoff,
            target_release_timestamp=release_timestamp,
        )
        if first_row is not None:
            rows.append(first_row)
        if latest_row is not None:
            rows.append(latest_row)
    return (
        pl.from_dicts(rows, schema=TARGET_SCHEMA, strict=True)
        if rows
        else pl.DataFrame(schema=TARGET_SCHEMA)
    ).sort(["target_period", "realization_mode"])


__all__ = [
    "CORE_INFLATION_FEATURE_SPECS",
    "DEFAULT_FEATURE_SPECS",
    "FEATURE_AUDIT_SCHEMA",
    "REAL_GDP_FEATURE_SPECS",
    "TARGET_FEATURE_SPECS",
    "TARGET_SCHEMA",
    "FeatureSpec",
    "assert_feature_no_future",
    "build_feature_matrix",
    "build_feature_vector",
    "build_payems_targets",
]
