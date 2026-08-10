"""Explicit release calendars and forecast origins for synthetic target fixtures.

The sample calendar is deliberately synthetic.  Its timestamps are exact UTC
instants so tests can exercise same-day information boundaries without pretending
that the dates describe historical BLS releases.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import polars as pl

SYNTHETIC_PROVENANCE = "synthetic_fixture"
DATE_ONLY_TIMING_QUALITY = "official_date_eod_convention"
_NEW_YORK = ZoneInfo("America/New_York")

RELEASE_CALENDAR_SCHEMA = pl.Schema(
    {
        "release_id": pl.String,
        "series_id": pl.String,
        "observation_date": pl.Date,
        "release_timestamp": pl.Datetime("us", "UTC"),
        "release_type": pl.String,
        "timing_quality": pl.String,
        "source": pl.String,
        "provenance_label": pl.String,
    }
)

FORECAST_ORIGIN_SCHEMA = pl.Schema(
    {
        "forecast_id": pl.String,
        "target_series_id": pl.String,
        "target_period": pl.Date,
        "forecast_origin": pl.Datetime("us", "UTC"),
        "as_of_timestamp": pl.Datetime("us", "UTC"),
        "target_release_timestamp": pl.Datetime("us", "UTC"),
        "horizon": pl.Int64,
        "provenance_label": pl.String,
    }
)


def _coerce_date(value: date | str, *, name: str) -> date:
    if isinstance(value, datetime):
        raise TypeError(f"{name} must be a date, not a datetime")
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an ISO date") from exc


def _month_start(value: date) -> date:
    return value.replace(day=1)


def _next_month(value: date) -> date:
    if value.month == 12:
        return date(value.year + 1, 1, 1)
    return date(value.year, value.month + 1, 1)


def _add_months(value: date, months: int) -> date:
    absolute_month = value.year * 12 + value.month - 1 + months
    year, zero_based_month = divmod(absolute_month, 12)
    return date(year, zero_based_month + 1, 1)


def _quarter_start(value: date) -> date:
    return date(value.year, ((value.month - 1) // 3) * 3 + 1, 1)


def _iter_months(start: date, end: date):
    current = _month_start(start)
    final = _month_start(end)
    while current <= final:
        yield current
        current = _next_month(current)


def payroll_release_timestamp(observation_date: date | str) -> datetime:
    """Return the fixture's explicit initial-release instant for a payroll month.

    The deterministic convention is 13:30 UTC on the first Friday of the next
    month.  It exists only to create a stable synthetic test calendar.
    """

    observation_month = _month_start(
        _coerce_date(observation_date, name="observation_date")
    )
    first_of_next_month = _next_month(observation_month)
    days_until_friday = (4 - first_of_next_month.weekday()) % 7
    release_date = first_of_next_month + timedelta(days=days_until_friday)
    return datetime(
        release_date.year,
        release_date.month,
        release_date.day,
        13,
        30,
        tzinfo=UTC,
    )


def core_cpi_release_timestamp(observation_date: date | str) -> datetime:
    """Return the fixture's exact UTC initial release for a core-CPI month."""

    observation_month = _month_start(
        _coerce_date(observation_date, name="observation_date")
    )
    release_month = _next_month(observation_month)
    return datetime(
        release_month.year,
        release_month.month,
        12,
        13,
        30,
        tzinfo=UTC,
    )


def real_gdp_release_timestamp(observation_date: date | str) -> datetime:
    """Return the fixture's exact UTC advance release for a real-GDP quarter."""

    observation_quarter = _quarter_start(
        _coerce_date(observation_date, name="observation_date")
    )
    release_month = _add_months(observation_quarter, 3)
    return datetime(
        release_month.year,
        release_month.month,
        28,
        12,
        30,
        tzinfo=UTC,
    )


def build_payroll_release_calendar(
    start: date | str = date(2017, 1, 1),
    end: date | str = date(2025, 3, 1),
) -> pl.DataFrame:
    """Build the explicit initial-release calendar used by synthetic fixtures."""

    start_date = _month_start(_coerce_date(start, name="start"))
    end_date = _month_start(_coerce_date(end, name="end"))
    if end_date < start_date:
        raise ValueError("end cannot precede start")

    rows = []
    for observation_date in _iter_months(start_date, end_date):
        rows.append(
            {
                "release_id": f"synthetic-payems-{observation_date:%Y-%m}-initial",
                "series_id": "PAYEMS",
                "observation_date": observation_date,
                "release_timestamp": payroll_release_timestamp(observation_date),
                "release_type": "initial",
                "timing_quality": "synthetic_exact",
                "source": "deterministic_synthetic_generator",
                "provenance_label": SYNTHETIC_PROVENANCE,
            }
        )
    calendar = pl.from_dicts(rows, schema=RELEASE_CALENDAR_SCHEMA, strict=True)
    return validate_release_calendar(calendar)


def build_core_cpi_release_calendar(
    start: date | str = date(2017, 1, 1),
    end: date | str = date(2025, 3, 1),
) -> pl.DataFrame:
    """Build explicit synthetic initial-release events for monthly core CPI."""

    start_date = _month_start(_coerce_date(start, name="start"))
    end_date = _month_start(_coerce_date(end, name="end"))
    if end_date < start_date:
        raise ValueError("end cannot precede start")
    rows = [
        {
            "release_id": f"synthetic-cpilfesl-{observation_date:%Y-%m}-initial",
            "series_id": "CPILFESL",
            "observation_date": observation_date,
            "release_timestamp": core_cpi_release_timestamp(observation_date),
            "release_type": "initial",
            "timing_quality": "synthetic_exact",
            "source": "deterministic_synthetic_generator",
            "provenance_label": SYNTHETIC_PROVENANCE,
        }
        for observation_date in _iter_months(start_date, end_date)
    ]
    return validate_release_calendar(
        pl.from_dicts(rows, schema=RELEASE_CALENDAR_SCHEMA, strict=True)
    )


def build_real_gdp_release_calendar(
    start: date | str = date(2017, 1, 1),
    end: date | str = date(2025, 3, 1),
) -> pl.DataFrame:
    """Build explicit synthetic advance-release events for quarterly real GDP."""

    start_date = _quarter_start(_coerce_date(start, name="start"))
    end_date = _quarter_start(_coerce_date(end, name="end"))
    if end_date < start_date:
        raise ValueError("end cannot precede start")
    rows = []
    observation_date = start_date
    while observation_date <= end_date:
        quarter = (observation_date.month + 2) // 3
        rows.append(
            {
                "release_id": (
                    f"synthetic-gdpc1-{observation_date.year}-Q{quarter}-initial"
                ),
                "series_id": "GDPC1",
                "observation_date": observation_date,
                "release_timestamp": real_gdp_release_timestamp(observation_date),
                "release_type": "initial",
                "timing_quality": "synthetic_exact",
                "source": "deterministic_synthetic_generator",
                "provenance_label": SYNTHETIC_PROVENANCE,
            }
        )
        observation_date = _add_months(observation_date, 3)
    return validate_release_calendar(
        pl.from_dicts(rows, schema=RELEASE_CALENDAR_SCHEMA, strict=True)
    )


def build_target_release_calendar(
    series_id: str,
    start: date | str = date(2017, 1, 1),
    end: date | str = date(2025, 3, 1),
) -> pl.DataFrame:
    """Dispatch to the synthetic calendar for one supported target series."""

    builders = {
        "PAYEMS": build_payroll_release_calendar,
        "CPILFESL": build_core_cpi_release_calendar,
        "GDPC1": build_real_gdp_release_calendar,
    }
    try:
        builder = builders[series_id.upper()]
    except KeyError as exc:
        supported = ", ".join(builders)
        message = f"unsupported target series {series_id!r}; expected one of {supported}"
        raise ValueError(message) from exc
    return builder(start, end)


def build_all_target_release_calendars(
    start: date | str = date(2017, 1, 1),
    end: date | str = date(2025, 3, 1),
) -> pl.DataFrame:
    """Return one explicit calendar for all three synthetic target series."""

    combined = pl.concat(
        [
            build_payroll_release_calendar(start, end),
            build_core_cpi_release_calendar(start, end),
            build_real_gdp_release_calendar(start, end),
        ]
    )
    return validate_release_calendar(combined)


def validate_release_calendar(calendar: pl.DataFrame) -> pl.DataFrame:
    """Validate and deterministically order a release calendar."""

    missing = set(RELEASE_CALENDAR_SCHEMA.names()).difference(calendar.columns)
    if missing:
        names = ", ".join(sorted(missing))
        raise ValueError(f"release calendar is missing columns: {names}")
    try:
        validated = calendar.select(
            pl.col(column).cast(dtype, strict=True)
            for column, dtype in RELEASE_CALENDAR_SCHEMA.items()
        )
    except (pl.exceptions.ComputeError, pl.exceptions.InvalidOperationError) as exc:
        raise ValueError("release calendar contains incompatible values") from exc

    if validated["release_timestamp"].null_count():
        raise ValueError("release_timestamp cannot be null")
    if validated["release_id"].n_unique() != validated.height:
        raise ValueError("release_id must be unique")
    duplicate_targets = (
        validated.filter(pl.col("release_type") == "initial")
        .group_by(["series_id", "observation_date"])
        .len()
        .filter(pl.col("len") != 1)
    )
    if duplicate_targets.height:
        raise ValueError("each target period must have exactly one initial release")
    if validated.filter(pl.col("release_timestamp").dt.date() <= pl.col("observation_date")).height:
        raise ValueError("target releases must occur after their reference period starts")
    return validated.sort(["release_timestamp", "series_id", "observation_date"])


def _previous_new_york_eod(release_timestamp: datetime) -> datetime:
    """Return prior-calendar-day EOD in New York for date-only releases."""

    release_date = release_timestamp.astimezone(UTC).date()
    prior_date = release_date - timedelta(days=1)
    return datetime.combine(prior_date, time.max, _NEW_YORK).astimezone(UTC)


def build_forecast_origins(
    release_calendar: pl.DataFrame,
    *,
    lead: timedelta = timedelta(seconds=1),
) -> pl.DataFrame:
    """Construct pre-release origins from explicit initial-release events."""

    if lead <= timedelta(0):
        raise ValueError("lead must be positive so origins precede releases")
    calendar = validate_release_calendar(release_calendar)
    lead_microseconds = int(lead.total_seconds() * 1_000_000)
    initial = calendar.filter(pl.col("release_type") == "initial")
    precise_origin = pl.col("release_timestamp") - pl.duration(
        microseconds=lead_microseconds
    )
    forecast_origin = (
        pl.when(pl.col("timing_quality") == DATE_ONLY_TIMING_QUALITY)
        .then(
            pl.col("release_timestamp").map_elements(
                _previous_new_york_eod,
                return_dtype=pl.Datetime("us", "UTC"),
            )
        )
        .otherwise(precise_origin)
    )
    origins = initial.select(
        pl.format("{}:{}", pl.col("series_id"), pl.col("observation_date")).alias(
            "forecast_id"
        ),
        pl.col("series_id").alias("target_series_id"),
        pl.col("observation_date").alias("target_period"),
        forecast_origin.alias("forecast_origin"),
        forecast_origin.alias("as_of_timestamp"),
        pl.col("release_timestamp").alias("target_release_timestamp"),
        pl.lit(0, dtype=pl.Int64).alias("horizon"),
        pl.col("provenance_label"),
    ).cast(FORECAST_ORIGIN_SCHEMA)
    if origins.filter(pl.col("forecast_origin") >= pl.col("target_release_timestamp")).height:
        raise AssertionError("forecast origins must strictly precede target releases")
    return origins.sort(["target_period", "target_series_id"])


# Short aliases retain discoverable economic names without duplicating behavior.
build_cpi_release_calendar = build_core_cpi_release_calendar
build_gdp_release_calendar = build_real_gdp_release_calendar
cpi_release_timestamp = core_cpi_release_timestamp
gdp_release_timestamp = real_gdp_release_timestamp


__all__ = [
    "DATE_ONLY_TIMING_QUALITY",
    "FORECAST_ORIGIN_SCHEMA",
    "RELEASE_CALENDAR_SCHEMA",
    "SYNTHETIC_PROVENANCE",
    "build_all_target_release_calendars",
    "build_core_cpi_release_calendar",
    "build_cpi_release_calendar",
    "build_forecast_origins",
    "build_gdp_release_calendar",
    "build_payroll_release_calendar",
    "build_real_gdp_release_calendar",
    "build_target_release_calendar",
    "core_cpi_release_timestamp",
    "cpi_release_timestamp",
    "gdp_release_timestamp",
    "payroll_release_timestamp",
    "real_gdp_release_timestamp",
    "validate_release_calendar",
]
