"""Configurable, vintage-audited macroeconomic target construction.

Every growth target uses its current and prior levels from one selected snapshot.
The first-release snapshot is the explicit UTC release instant; the fixed-latest
snapshot is one caller-supplied UTC cutoff shared by every target and model.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Literal

import polars as pl

from macro_nowcast.asof import select_as_of
from macro_nowcast.calendar import validate_release_calendar

TargetFrequency = Literal["monthly", "quarterly"]
TargetTransformation = Literal[
    "difference",
    "arithmetic_percent_change",
    "compounded_percent_change",
    "published_value",
]
RealizationMode = Literal["first_release", "latest_revised"]


@dataclass(frozen=True, slots=True)
class TargetSpec:
    """Typed definition of a two-adjacent-level target transformation."""

    series_id: str
    target_name: str
    target_units: str
    frequency: TargetFrequency
    transformation: TargetTransformation
    annualization_factor: int | None = None
    release_type: str = "initial"
    published_value_is_annualized: bool = False
    output_series_id: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("series_id", "target_name", "target_units", "release_type"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string")
            object.__setattr__(self, field_name, value.strip())
        object.__setattr__(self, "series_id", self.series_id.upper())
        if self.output_series_id is not None:
            if not isinstance(self.output_series_id, str) or not self.output_series_id.strip():
                raise ValueError("output_series_id must be a non-empty string when provided")
            object.__setattr__(self, "output_series_id", self.output_series_id.strip().upper())
        if self.frequency not in {"monthly", "quarterly"}:
            raise ValueError("frequency must be 'monthly' or 'quarterly'")
        if self.transformation not in {
            "difference",
            "arithmetic_percent_change",
            "compounded_percent_change",
            "published_value",
        }:
            raise ValueError("unsupported target transformation")
        if self.transformation == "compounded_percent_change":
            if self.annualization_factor is None or self.annualization_factor < 1:
                raise ValueError(
                    "compounded_percent_change requires a positive annualization_factor"
                )
        elif self.annualization_factor is not None:
            raise ValueError(
                "annualization_factor is valid only for compounded_percent_change"
            )
        if self.published_value_is_annualized and self.transformation != "published_value":
            raise ValueError(
                "published_value_is_annualized is valid only for published_value"
            )

    @property
    def period_months(self) -> int:
        return 1 if self.frequency == "monthly" else 3

    @property
    def name(self) -> str:
        """Compatibility alias for configuration code using ``name``."""

        return self.target_name

    @property
    def units(self) -> str:
        """Compatibility alias for configuration code using ``units``."""

        return self.target_units

    @property
    def is_annualized(self) -> bool:
        return self.annualization_factor is not None or self.published_value_is_annualized

    @property
    def target_series_id(self) -> str:
        return self.output_series_id or self.series_id

    @property
    def formula(self) -> str:
        if self.transformation == "difference":
            return "current_level - prior_level"
        if self.transformation == "arithmetic_percent_change":
            return "100 * (current_level / prior_level - 1)"
        if self.transformation == "published_value":
            return "official_published_value_already_transformed_no_retransformation"
        return (
            "100 * ((current_level / prior_level) ** "
            f"{self.annualization_factor} - 1)"
        )

    def prior_period(self, target_period: date) -> date:
        period = _normalized_period(target_period, self.frequency)
        return _add_months(period, -self.period_months)

    def transform_levels(self, current_level: float, prior_level: float) -> float:
        current = float(current_level)
        prior = float(prior_level)
        if self.transformation == "published_value":
            return current
        if self.transformation == "difference":
            return current - prior
        if prior == 0:
            raise ValueError(f"{self.target_name} cannot divide by a zero prior level")
        if self.transformation == "arithmetic_percent_change":
            return 100.0 * (current / prior - 1.0)
        if current <= 0 or prior <= 0:
            raise ValueError(
                f"{self.target_name} requires positive levels for exact compounding"
            )
        assert self.annualization_factor is not None
        return 100.0 * ((current / prior) ** self.annualization_factor - 1.0)


PAYEMS_TARGET_SPEC = TargetSpec(
    series_id="PAYEMS",
    target_name="payems_change_mom_thousands",
    target_units="thousands_of_persons_change_mom",
    frequency="monthly",
    transformation="difference",
)

CORE_CPI_TARGET_SPEC = TargetSpec(
    series_id="CPILFESL",
    target_name="core_cpi_pct_change_mom",
    target_units="percent_change_mom_nonannualized",
    frequency="monthly",
    transformation="arithmetic_percent_change",
)

REAL_GDP_TARGET_SPEC = TargetSpec(
    series_id="GDPC1",
    target_name="real_gdp_pct_change_qoq_saar",
    target_units="percent_change_qoq_saar",
    frequency="quarterly",
    transformation="compounded_percent_change",
    annualization_factor=4,
)

PUBLISHED_REAL_GDP_TARGET_SPEC = TargetSpec(
    series_id="BEA_REAL_GDP_GROWTH_QOQ_SAAR",
    output_series_id="GDPC1",
    target_name="real_gdp_pct_change_qoq_saar",
    target_units="percent_change_qoq_saar",
    frequency="quarterly",
    transformation="published_value",
    published_value_is_annualized=True,
)

DEFAULT_TARGET_SPECS = (
    PAYEMS_TARGET_SPEC,
    CORE_CPI_TARGET_SPEC,
    REAL_GDP_TARGET_SPEC,
)
DEFAULT_TARGET_SPECS_BY_SERIES: Mapping[str, TargetSpec] = {
    spec.series_id: spec for spec in DEFAULT_TARGET_SPECS
}


# The first twelve columns intentionally match features.TARGET_SCHEMA by name and
# dtype.  Additional fields make snapshot identity, transformation, and source
# lineage independently auditable without changing the legacy feature module.
TARGET_AUDIT_SCHEMA = pl.Schema(
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
        "target_frequency": pl.String,
        "transformation": pl.String,
        "target_formula": pl.String,
        "annualization_factor": pl.Int64,
        "is_annualized": pl.Boolean,
        "release_id": pl.String,
        "release_type": pl.String,
        "release_timing_quality": pl.String,
        "snapshot_timestamp": pl.Datetime("us", "UTC"),
        "evaluation_cutoff_timestamp": pl.Datetime("us", "UTC"),
        "prior_period": pl.Date,
        "current_level": pl.Float64,
        "prior_level": pl.Float64,
        "current_level_realtime_start": pl.Date,
        "prior_level_realtime_start": pl.Date,
        "current_level_download_timestamp": pl.Datetime("us", "UTC"),
        "prior_level_download_timestamp": pl.Datetime("us", "UTC"),
        "max_download_timestamp": pl.Datetime("us", "UTC"),
        "calendar_source": pl.String,
        "observation_source": pl.String,
        "calendar_provenance_label": pl.String,
        "observation_provenance_label": pl.String,
        "built_at_timestamp": pl.Datetime("us", "UTC"),
    }
)
TARGET_SCHEMA = TARGET_AUDIT_SCHEMA


def _as_utc(value: datetime | str, *, name: str) -> datetime:
    if isinstance(value, str):
        normalized = f"{value[:-1]}+00:00" if value.endswith("Z") else value
        try:
            value = datetime.fromisoformat(normalized)
        except ValueError as exc:
            raise ValueError(f"{name} must be an ISO datetime with a timezone") from exc
    if not isinstance(value, datetime):
        raise TypeError(f"{name} must be a timezone-aware datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must include an explicit timezone")
    return value.astimezone(UTC)


def _add_months(value: date, months: int) -> date:
    absolute_month = value.year * 12 + value.month - 1 + months
    year, zero_based_month = divmod(absolute_month, 12)
    return date(year, zero_based_month + 1, 1)


def _normalized_period(value: date, frequency: TargetFrequency) -> date:
    if isinstance(value, datetime) or not isinstance(value, date):
        raise TypeError("target periods must be dates, not datetimes")
    expected_month = value.month if frequency == "monthly" else ((value.month - 1) // 3) * 3 + 1
    normalized = date(value.year, expected_month, 1)
    if value != normalized:
        qualifier = "month" if frequency == "monthly" else "quarter"
        raise ValueError(f"target period must be the first day of its {qualifier}")
    return normalized


def _validate_specs(specs: Sequence[TargetSpec]) -> tuple[TargetSpec, ...]:
    result = tuple(specs)
    if not result:
        raise ValueError("At least one target spec is required")
    if not all(isinstance(spec, TargetSpec) for spec in result):
        raise TypeError("specs must contain only TargetSpec instances")
    if len({spec.series_id for spec in result}) != len(result):
        raise ValueError("Target series IDs must be unique")
    if len({spec.target_name for spec in result}) != len(result):
        raise ValueError("Target names must be unique")
    return result


def _validate_modes(modes: Collection[RealizationMode]) -> tuple[RealizationMode, ...]:
    result = tuple(modes)
    allowed = {"first_release", "latest_revised"}
    if not result or len(result) != len(set(result)) or set(result) - allowed:
        raise ValueError("modes must contain unique first_release/latest_revised values")
    return result


def _validated_utc_calendar(release_calendar: pl.DataFrame) -> pl.DataFrame:
    timestamp_dtype = release_calendar.schema.get("release_timestamp")
    if not isinstance(timestamp_dtype, pl.Datetime) or timestamp_dtype.time_zone != "UTC":
        raise ValueError("release_timestamp must have an explicit UTC timezone")
    return validate_release_calendar(release_calendar)


def _combined_label(*labels: object) -> str:
    normalized = {str(label) for label in labels}
    return next(iter(normalized)) if len(normalized) == 1 else "mixed"


def _combined_source(*sources: object) -> str:
    return "|".join(sorted({str(source) for source in sources}))


def _target_row(
    snapshot: pl.DataFrame,
    *,
    spec: TargetSpec,
    release: Mapping[str, object],
    target_period: date,
    mode: RealizationMode,
    snapshot_timestamp: datetime,
    evaluation_cutoff: datetime,
    built_at: datetime,
) -> dict[str, object] | None:
    prior_period = spec.prior_period(target_period)
    if spec.transformation == "published_value":
        published = snapshot.filter(
            (pl.col("series_id") == spec.series_id)
            & (pl.col("observation_date") == target_period)
        )
        if published.height != 1:
            return None
        source_row = published.row(0, named=True)
        if source_row["value"] is None:
            return None
        availability = source_row["selected_vintage_availability_timestamp"]
        if availability > snapshot_timestamp:
            raise AssertionError("published target contains a post-snapshot source vintage")
        calendar_label = str(release["provenance_label"])
        observation_label = str(source_row["provenance_label"])
        download_timestamp = source_row["download_timestamp"]
        return {
            "target_series_id": spec.target_series_id,
            "target_period": target_period,
            "target_name": spec.target_name,
            "target_units": spec.target_units,
            "realization_mode": mode,
            "value": float(source_row["value"]),
            "realization_as_of_timestamp": snapshot_timestamp,
            "target_release_timestamp": release["release_timestamp"],
            "current_level_availability": availability,
            "prior_level_availability": None,
            "max_source_availability": availability,
            "provenance_label": _combined_label(observation_label, calendar_label),
            "target_frequency": spec.frequency,
            "transformation": spec.transformation,
            "target_formula": spec.formula,
            "annualization_factor": None,
            "is_annualized": spec.is_annualized,
            "release_id": release["release_id"],
            "release_type": release["release_type"],
            "release_timing_quality": release["timing_quality"],
            "snapshot_timestamp": snapshot_timestamp,
            "evaluation_cutoff_timestamp": evaluation_cutoff,
            "prior_period": None,
            "current_level": None,
            "prior_level": None,
            "current_level_realtime_start": source_row["realtime_start"],
            "prior_level_realtime_start": None,
            "current_level_download_timestamp": download_timestamp,
            "prior_level_download_timestamp": None,
            "max_download_timestamp": download_timestamp,
            "calendar_source": release["source"],
            "observation_source": source_row["source"],
            "calendar_provenance_label": calendar_label,
            "observation_provenance_label": observation_label,
            "built_at_timestamp": built_at,
        }
    levels = snapshot.filter(
        (pl.col("series_id") == spec.series_id)
        & pl.col("observation_date").is_in([prior_period, target_period])
    )
    if levels.height != 2:
        return None
    by_period = {row["observation_date"]: row for row in levels.to_dicts()}
    current = by_period.get(target_period)
    prior = by_period.get(prior_period)
    if current is None or prior is None:
        return None
    if current["value"] is None or prior["value"] is None:
        return None

    current_availability = current["selected_vintage_availability_timestamp"]
    prior_availability = prior["selected_vintage_availability_timestamp"]
    if current_availability > snapshot_timestamp or prior_availability > snapshot_timestamp:
        raise AssertionError("target snapshot contains a post-snapshot source vintage")
    current_level = float(current["value"])
    prior_level = float(prior["value"])
    value = spec.transform_levels(current_level, prior_level)
    observation_label = _combined_label(
        current["provenance_label"], prior["provenance_label"]
    )
    calendar_label = str(release["provenance_label"])
    current_download = current["download_timestamp"]
    prior_download = prior["download_timestamp"]
    return {
        "target_series_id": spec.target_series_id,
        "target_period": target_period,
        "target_name": spec.target_name,
        "target_units": spec.target_units,
        "realization_mode": mode,
        "value": value,
        "realization_as_of_timestamp": snapshot_timestamp,
        "target_release_timestamp": release["release_timestamp"],
        "current_level_availability": current_availability,
        "prior_level_availability": prior_availability,
        "max_source_availability": max(current_availability, prior_availability),
        "provenance_label": _combined_label(observation_label, calendar_label),
        "target_frequency": spec.frequency,
        "transformation": spec.transformation,
        "target_formula": spec.formula,
        "annualization_factor": spec.annualization_factor,
        "is_annualized": spec.is_annualized,
        "release_id": release["release_id"],
        "release_type": release["release_type"],
        "release_timing_quality": release["timing_quality"],
        "snapshot_timestamp": snapshot_timestamp,
        "evaluation_cutoff_timestamp": evaluation_cutoff,
        "prior_period": prior_period,
        "current_level": current_level,
        "prior_level": prior_level,
        "current_level_realtime_start": current["realtime_start"],
        "prior_level_realtime_start": prior["realtime_start"],
        "current_level_download_timestamp": current_download,
        "prior_level_download_timestamp": prior_download,
        "max_download_timestamp": max(current_download, prior_download),
        "calendar_source": release["source"],
        "observation_source": _combined_source(current["source"], prior["source"]),
        "calendar_provenance_label": calendar_label,
        "observation_provenance_label": observation_label,
        "built_at_timestamp": built_at,
    }


def build_targets(
    observations: pl.DataFrame,
    release_calendar: pl.DataFrame,
    *,
    latest_as_of: datetime | str,
    specs: Sequence[TargetSpec] = DEFAULT_TARGET_SPECS,
    modes: Collection[RealizationMode] = ("first_release", "latest_revised"),
    built_at: datetime | str | None = None,
) -> pl.DataFrame:
    """Build first-release and one-cutoff latest-revised target realizations.

    Release events after ``latest_as_of`` are excluded.  Each mode selects one
    snapshot first and then takes both adjacent levels from that snapshot, which
    prevents mixed-vintage growth calculations.
    """

    target_specs = _validate_specs(specs)
    requested_modes = _validate_modes(modes)
    latest_cutoff = _as_utc(latest_as_of, name="latest_as_of")
    build_timestamp = (
        datetime.now(UTC) if built_at is None else _as_utc(built_at, name="built_at")
    )
    calendar = _validated_utc_calendar(release_calendar)
    latest_snapshot = (
        select_as_of(observations, latest_cutoff)
        if "latest_revised" in requested_modes
        else None
    )
    rows: list[dict[str, object]] = []
    for spec in target_specs:
        releases = calendar.filter(
            (pl.col("series_id") == spec.series_id)
            & (pl.col("release_type") == spec.release_type)
            & (pl.col("release_timestamp") <= pl.lit(latest_cutoff))
        )
        for release in releases.iter_rows(named=True):
            target_period = _normalized_period(release["observation_date"], spec.frequency)
            prior_period = spec.prior_period(target_period)
            release_timestamp = _as_utc(
                release["release_timestamp"], name="release_timestamp"
            )
            if "first_release" in requested_modes:
                required_periods = (
                    [target_period]
                    if spec.transformation == "published_value"
                    else [prior_period, target_period]
                )
                target_period_observations = observations.filter(
                    (pl.col("series_id") == spec.series_id)
                    & pl.col("observation_date").is_in(required_periods)
                )
                first_snapshot = select_as_of(
                    target_period_observations,
                    release_timestamp,
                )
                row = _target_row(
                    first_snapshot,
                    spec=spec,
                    release=release,
                    target_period=target_period,
                    mode="first_release",
                    snapshot_timestamp=release_timestamp,
                    evaluation_cutoff=latest_cutoff,
                    built_at=build_timestamp,
                )
                if row is not None:
                    rows.append(row)
            if "latest_revised" in requested_modes:
                assert latest_snapshot is not None
                row = _target_row(
                    latest_snapshot,
                    spec=spec,
                    release=release,
                    target_period=target_period,
                    mode="latest_revised",
                    snapshot_timestamp=latest_cutoff,
                    evaluation_cutoff=latest_cutoff,
                    built_at=build_timestamp,
                )
                if row is not None:
                    rows.append(row)

    targets = (
        pl.from_dicts(rows, schema=TARGET_AUDIT_SCHEMA, strict=True)
        if rows
        else pl.DataFrame(schema=TARGET_AUDIT_SCHEMA)
    ).sort(["target_series_id", "target_period", "realization_mode"])
    assert_target_audit(targets)
    return targets


def build_targets_for_spec(
    observations: pl.DataFrame,
    release_calendar: pl.DataFrame,
    spec: TargetSpec,
    *,
    latest_as_of: datetime | str,
    modes: Collection[RealizationMode] = ("first_release", "latest_revised"),
    built_at: datetime | str | None = None,
) -> pl.DataFrame:
    """Convenience wrapper for one configured target."""

    return build_targets(
        observations,
        release_calendar,
        latest_as_of=latest_as_of,
        specs=(spec,),
        modes=modes,
        built_at=built_at,
    )


def assert_target_audit(targets: pl.DataFrame) -> None:
    """Assert snapshot/cutoff timing and same-snapshot target invariants."""

    missing = set(TARGET_AUDIT_SCHEMA.names()).difference(targets.columns)
    if missing:
        raise ValueError(f"target audit columns are missing: {', '.join(sorted(missing))}")
    if targets.is_empty():
        return
    violations = targets.filter(
        (pl.col("current_level_availability") > pl.col("snapshot_timestamp"))
        | (pl.col("prior_level_availability") > pl.col("snapshot_timestamp"))
        | (pl.col("max_source_availability") > pl.col("realization_as_of_timestamp"))
        | (pl.col("target_release_timestamp") > pl.col("evaluation_cutoff_timestamp"))
        | (
            (pl.col("realization_mode") == "first_release")
            & (pl.col("snapshot_timestamp") != pl.col("target_release_timestamp"))
        )
        | (
            (pl.col("realization_mode") == "latest_revised")
            & (pl.col("snapshot_timestamp") != pl.col("evaluation_cutoff_timestamp"))
        )
    )
    if violations.height:
        raise AssertionError(f"target audit failed for {violations.height} row(s)")
    unsupported_modes = targets.filter(
        ~pl.col("realization_mode").is_in(["first_release", "latest_revised"])
    )
    if unsupported_modes.height:
        raise ValueError("target rows contain an unsupported realization mode")


def target_spec_for_series(series_id: str) -> TargetSpec:
    """Return one default target spec by case-insensitive series ID."""

    try:
        return DEFAULT_TARGET_SPECS_BY_SERIES[series_id.strip().upper()]
    except (AttributeError, KeyError) as exc:
        raise KeyError(f"No default target spec for {series_id!r}") from exc


build_target_realizations = build_targets


__all__ = [
    "CORE_CPI_TARGET_SPEC",
    "DEFAULT_TARGET_SPECS",
    "DEFAULT_TARGET_SPECS_BY_SERIES",
    "PAYEMS_TARGET_SPEC",
    "PUBLISHED_REAL_GDP_TARGET_SPEC",
    "REAL_GDP_TARGET_SPEC",
    "TARGET_AUDIT_SCHEMA",
    "TARGET_SCHEMA",
    "RealizationMode",
    "TargetFrequency",
    "TargetSpec",
    "TargetTransformation",
    "assert_target_audit",
    "build_target_realizations",
    "build_targets",
    "build_targets_for_spec",
    "target_spec_for_series",
]
