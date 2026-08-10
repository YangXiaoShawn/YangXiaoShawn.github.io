"""Deterministic mixed-frequency vintage fixtures for the payroll vertical slice.

Every row is marked ``synthetic_fixture``.  The generated values and dates exist to
exercise information-set behavior; they are not historical macroeconomic data and
must not support empirical economic claims.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import polars as pl

from macro_nowcast.calendar import (
    SYNTHETIC_PROVENANCE,
    build_core_cpi_release_calendar,
    build_payroll_release_calendar,
    build_real_gdp_release_calendar,
    core_cpi_release_timestamp,
    payroll_release_timestamp,
    real_gdp_release_timestamp,
    validate_release_calendar,
)
from macro_nowcast.schema import VintageObservation, observations_to_frame

SERIES_IDS = (
    "PAYEMS",
    "ICSA",
    "CCSA",
    "UNRATE",
    "AWHMAN",
    "INDPRO",
    "RSAFS",
    "HOUST",
    "UMCSENT",
    "DGS10",
)
ADDITIONAL_TARGET_SERIES_IDS = ("CPILFESL", "GDPC1")
ALL_SERIES_IDS = SERIES_IDS + ADDITIONAL_TARGET_SERIES_IDS

SERIES_METADATA_SCHEMA = pl.Schema(
    {
        "series_id": pl.String,
        "title": pl.String,
        "units": pl.String,
        "frequency": pl.String,
        "seasonal_adjustment": pl.String,
        "source": pl.String,
        "provenance_label": pl.String,
    }
)

_SERIES = {
    "PAYEMS": (
        "Synthetic total nonfarm payroll level",
        "thousands_of_persons",
        "monthly",
        "seasonally_adjusted",
    ),
    "ICSA": (
        "Synthetic initial unemployment claims",
        "persons",
        "weekly",
        "seasonally_adjusted",
    ),
    "CCSA": (
        "Synthetic continued unemployment claims",
        "persons",
        "weekly",
        "seasonally_adjusted",
    ),
    "UNRATE": (
        "Synthetic unemployment rate",
        "percent",
        "monthly",
        "seasonally_adjusted",
    ),
    "AWHMAN": (
        "Synthetic manufacturing average weekly hours",
        "hours",
        "monthly",
        "seasonally_adjusted",
    ),
    "INDPRO": (
        "Synthetic industrial production index",
        "index",
        "monthly",
        "seasonally_adjusted",
    ),
    "RSAFS": (
        "Synthetic retail and food services sales",
        "millions_of_dollars",
        "monthly",
        "seasonally_adjusted",
    ),
    "HOUST": (
        "Synthetic housing starts",
        "thousands_of_units",
        "monthly",
        "seasonally_adjusted_annual_rate",
    ),
    "UMCSENT": (
        "Synthetic consumer sentiment index",
        "index",
        "monthly",
        "not_seasonally_adjusted",
    ),
    "DGS10": (
        "Synthetic ten-year government yield",
        "percent",
        "daily",
        "not_seasonally_adjusted",
    ),
    "CPILFESL": (
        "Synthetic core consumer price index level",
        "index_1982_1984_100",
        "monthly",
        "seasonally_adjusted",
    ),
    "GDPC1": (
        "Synthetic real gross domestic product level",
        "billions_of_chained_2017_dollars",
        "quarterly",
        "seasonally_adjusted_annual_rate",
    ),
}

_FIXED_DOWNLOAD_TIMESTAMP = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class SyntheticFixture:
    """In-memory fixture bundle with explicit provenance."""

    observations: pl.DataFrame
    release_calendar: pl.DataFrame
    series_metadata: pl.DataFrame
    provenance_label: str = SYNTHETIC_PROVENANCE
    cpi_release_calendar: pl.DataFrame | None = None
    gdp_release_calendar: pl.DataFrame | None = None

    @property
    def all_target_release_calendar(self) -> pl.DataFrame:
        """Return combined target calendars while keeping payroll compatibility."""

        calendars = [self.release_calendar]
        if self.cpi_release_calendar is not None:
            calendars.append(self.cpi_release_calendar)
        if self.gdp_release_calendar is not None:
            calendars.append(self.gdp_release_calendar)
        return validate_release_calendar(pl.concat(calendars))


def _month_start(value: date) -> date:
    return value.replace(day=1)


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
        current = _add_months(current, 1)


def _series_release_timestamp(series_id: str, observation_date: date) -> datetime:
    if series_id in {"PAYEMS", "UNRATE", "AWHMAN"}:
        return payroll_release_timestamp(observation_date)
    if series_id == "UMCSENT":
        return datetime(
            observation_date.year,
            observation_date.month,
            15,
            15,
            0,
            tzinfo=UTC,
        )
    if series_id == "CPILFESL":
        return core_cpi_release_timestamp(observation_date)
    release_month = _add_months(observation_date, 1)
    day_hour = {
        "INDPRO": (16, 14, 15),
        "RSAFS": (15, 13, 30),
        "HOUST": (18, 13, 30),
    }
    day, hour, minute = day_hour[series_id]
    return datetime(
        release_month.year,
        release_month.month,
        day,
        hour,
        minute,
        tzinfo=UTC,
    )


def _monthly_truth(series_id: str, index: int, rng: random.Random) -> float:
    cycle = math.sin(index / 7.0)
    slower_cycle = math.cos(index / 19.0)
    noise = rng.gauss(0.0, 1.0)
    if series_id == "PAYEMS":
        return 145_000.0 + 155.0 * index + 80.0 * cycle + 8.0 * noise
    if series_id == "UNRATE":
        return max(2.5, 4.8 - 0.006 * index - 0.25 * cycle + 0.03 * noise)
    if series_id == "AWHMAN":
        return 40.6 + 0.12 * slower_cycle + 0.025 * noise
    if series_id == "INDPRO":
        return 100.0 + 0.10 * index + 0.8 * cycle + 0.12 * noise
    if series_id == "RSAFS":
        return 410_000.0 + 1_900.0 * index + 3_200.0 * cycle + 300.0 * noise
    if series_id == "HOUST":
        return max(400.0, 1_250.0 + 130.0 * cycle + 35.0 * noise)
    if series_id == "UMCSENT":
        return 82.0 + 7.0 * cycle + 1.2 * noise
    raise KeyError(series_id)


def _revision_scale(series_id: str) -> float:
    return {
        "PAYEMS": 24.0,
        "UNRATE": 0.04,
        "AWHMAN": 0.025,
        "INDPRO": 0.16,
        "RSAFS": 550.0,
        "HOUST": 20.0,
        "UMCSENT": 0.8,
    }[series_id]


def _row(
    *,
    series_id: str,
    observation_date: date,
    available_at: datetime,
    value: float | None,
    vintage_number: int,
) -> dict[str, object]:
    _, units, frequency, seasonal_adjustment = _SERIES[series_id]
    return {
        "series_id": series_id,
        "observation_date": observation_date,
        "realtime_start": available_at.date(),
        "realtime_end": None,
        "availability_date": available_at.date(),
        "release_timestamp": available_at,
        "availability_timestamp": available_at,
        "value": value,
        "units": units,
        "frequency": frequency,
        "seasonal_adjustment": seasonal_adjustment,
        "transformation": "level",
        "download_timestamp": _FIXED_DOWNLOAD_TIMESTAMP,
        "source": "deterministic_synthetic_generator",
        "provenance_label": SYNTHETIC_PROVENANCE,
        "source_metadata": {
            "fixture_kind": SYNTHETIC_PROVENANCE,
            "fixture_version": 1,
            "vintage_number": vintage_number,
        },
    }


def _monthly_rows(
    start: date,
    end: date,
    rng: random.Random,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    monthly_series = ("PAYEMS", "UNRATE", "AWHMAN", "INDPRO", "RSAFS", "HOUST", "UMCSENT")
    for index, observation_date in enumerate(_iter_months(start, end)):
        for series_id in monthly_series:
            # A wholly absent month creates a genuine ragged edge rather than a null vintage.
            if series_id == "UMCSENT" and observation_date == date(2019, 7, 1):
                continue
            truth = _monthly_truth(series_id, index, rng)
            scale = _revision_scale(series_id)
            initial_release = _series_release_timestamp(series_id, observation_date)
            initial_value = truth + rng.gauss(0.0, scale)
            rows.append(
                _row(
                    series_id=series_id,
                    observation_date=observation_date,
                    available_at=initial_release,
                    value=round(initial_value, 4),
                    vintage_number=1,
                )
            )

            if series_id == "UMCSENT":
                revision_release = datetime(
                    observation_date.year,
                    observation_date.month,
                    28,
                    15,
                    0,
                    tzinfo=UTC,
                )
            else:
                revision_release = _series_release_timestamp(
                    series_id, _add_months(observation_date, 1)
                )
            revised_value: float | None = truth + rng.gauss(0.0, scale / 3.0)
            # A latest null vintage tests that old values are not silently resurrected.
            if series_id == "UMCSENT" and observation_date == date(2025, 3, 1):
                revised_value = None
            rows.append(
                _row(
                    series_id=series_id,
                    observation_date=observation_date,
                    available_at=revision_release,
                    value=None if revised_value is None else round(revised_value, 4),
                    vintage_number=2,
                )
            )

            if series_id == "PAYEMS":
                rows.append(
                    _row(
                        series_id=series_id,
                        observation_date=observation_date,
                        available_at=payroll_release_timestamp(
                            _add_months(observation_date, 2)
                        ),
                        value=round(truth, 4),
                        vintage_number=3,
                    )
                )
    return rows


def _first_weekday_on_or_after(value: date, weekday: int) -> date:
    return value + timedelta(days=(weekday - value.weekday()) % 7)


def _weekly_rows(start: date, end: date, rng: random.Random) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    observation_date = _first_weekday_on_or_after(start, 5)  # Saturday week ending.
    index = 0
    while observation_date <= end:
        # One missing release creates a gap in the weekly grid.
        if index != 137:
            cycle = math.sin(index / 13.0)
            for series_id, base, amplitude, revision_scale in (
                ("ICSA", 225_000.0, 18_000.0, 1_500.0),
                ("CCSA", 1_780_000.0, 95_000.0, 7_500.0),
            ):
                truth = base + amplitude * cycle + rng.gauss(0.0, revision_scale)
                initial_release = datetime.combine(
                    observation_date + timedelta(days=5),
                    datetime.min.time(),
                    tzinfo=UTC,
                ).replace(hour=13, minute=30)
                initial_value: float | None = truth + rng.gauss(0.0, revision_scale)
                # At an intermediate as-of this row is visibly missing; its later
                # revision becomes numeric, testing vintage-dependent raggedness.
                if series_id == "CCSA" and index == 111:
                    initial_value = None
                rows.append(
                    _row(
                        series_id=series_id,
                        observation_date=observation_date,
                        available_at=initial_release,
                        value=None if initial_value is None else round(initial_value, 2),
                        vintage_number=1,
                    )
                )
                rows.append(
                    _row(
                        series_id=series_id,
                        observation_date=observation_date,
                        available_at=initial_release + timedelta(days=7),
                        value=round(truth, 2),
                        vintage_number=2,
                    )
                )
        observation_date += timedelta(days=7)
        index += 1
    return rows


def _core_cpi_rows(
    start: date,
    end: date,
    rng: random.Random,
) -> list[dict[str, object]]:
    """Create two explicitly timed vintages for every synthetic core-CPI month."""

    rows: list[dict[str, object]] = []
    for index, observation_date in enumerate(_iter_months(start, end)):
        cycle = math.sin(index / 8.0)
        truth = 260.0 + 0.58 * index + 0.45 * cycle + rng.gauss(0.0, 0.025)
        initial_release = core_cpi_release_timestamp(observation_date)
        rows.append(
            _row(
                series_id="CPILFESL",
                observation_date=observation_date,
                available_at=initial_release,
                value=round(truth + rng.gauss(0.0, 0.10), 4),
                vintage_number=1,
            )
        )
        rows.append(
            _row(
                series_id="CPILFESL",
                observation_date=observation_date,
                available_at=core_cpi_release_timestamp(_add_months(observation_date, 1)),
                value=round(truth + rng.gauss(0.0, 0.025), 4),
                vintage_number=2,
            )
        )
    return rows


def _quarterly_gdp_rows(
    start: date,
    end: date,
    rng: random.Random,
) -> list[dict[str, object]]:
    """Create advance, second, and third synthetic real-GDP vintages."""

    rows: list[dict[str, object]] = []
    observation_date = _quarter_start(start)
    final_quarter = _quarter_start(end)
    index = 0
    while observation_date <= final_quarter:
        cycle = math.sin(index / 3.5)
        truth = 19_000.0 + 135.0 * index + 85.0 * cycle + rng.gauss(0.0, 5.0)
        initial_release = real_gdp_release_timestamp(observation_date)
        second_release_month = _add_months(initial_release.date().replace(day=1), 1)
        third_release_month = _add_months(initial_release.date().replace(day=1), 2)
        second_release = datetime(
            second_release_month.year,
            second_release_month.month,
            27,
            12,
            30,
            tzinfo=UTC,
        )
        third_release = datetime(
            third_release_month.year,
            third_release_month.month,
            26,
            12,
            30,
            tzinfo=UTC,
        )
        for vintage_number, available_at, vintage_value in (
            (1, initial_release, truth + rng.gauss(0.0, 35.0)),
            (2, second_release, truth + rng.gauss(0.0, 12.0)),
            (3, third_release, truth),
        ):
            rows.append(
                _row(
                    series_id="GDPC1",
                    observation_date=observation_date,
                    available_at=available_at,
                    value=round(vintage_value, 3),
                    vintage_number=vintage_number,
                )
            )
        observation_date = _add_months(observation_date, 3)
        index += 1
    return rows


def _daily_rows(start: date, end: date, rng: random.Random) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    observation_date = start
    business_index = 0
    while observation_date <= end:
        if observation_date.weekday() < 5:
            # Deterministic missing weekdays mimic holidays without claiming real dates.
            if business_index % 41 != 17:
                value = 2.2 + 0.008 * business_index + 0.35 * math.sin(business_index / 31.0)
                value += rng.gauss(0.0, 0.025)
                available_at = datetime(
                    observation_date.year,
                    observation_date.month,
                    observation_date.day,
                    22,
                    0,
                    tzinfo=UTC,
                )
                rows.append(
                    _row(
                        series_id="DGS10",
                        observation_date=observation_date,
                        available_at=available_at,
                        value=round(value, 4),
                        vintage_number=1,
                    )
                )
            business_index += 1
        observation_date += timedelta(days=1)
    return rows


def _set_realtime_ends(rows: list[dict[str, object]]) -> list[VintageObservation]:
    grouped: dict[tuple[str, date], list[dict[str, object]]] = {}
    for row in rows:
        key = (str(row["series_id"]), row["observation_date"])  # type: ignore[arg-type]
        grouped.setdefault(key, []).append(row)

    validated: list[VintageObservation] = []
    for group in grouped.values():
        group.sort(key=lambda row: row["availability_timestamp"])  # type: ignore[arg-type,return-value]
        for index, row in enumerate(group):
            if index + 1 < len(group):
                next_start = group[index + 1]["realtime_start"]
                assert isinstance(next_start, date)
                row["realtime_end"] = next_start - timedelta(days=1)
            validated.append(VintageObservation.from_mapping(row))
    return validated


def _series_metadata(series_ids: tuple[str, ...] = SERIES_IDS) -> pl.DataFrame:
    rows = [
        {
            "series_id": series_id,
            "title": metadata[0],
            "units": metadata[1],
            "frequency": metadata[2],
            "seasonal_adjustment": metadata[3],
            "source": "deterministic_synthetic_generator",
            "provenance_label": SYNTHETIC_PROVENANCE,
        }
        for series_id, metadata in _SERIES.items()
        if series_id in series_ids
    ]
    return pl.from_dicts(rows, schema=SERIES_METADATA_SCHEMA, strict=True).sort("series_id")


def build_synthetic_fixture(
    start: date = date(2017, 1, 1),
    end: date = date(2025, 3, 1),
    *,
    seed: int = 20_260_807,
    include_additional_targets: bool = False,
) -> SyntheticFixture:
    """Return the original payroll fixture, optionally adding CPI and GDP targets."""

    if isinstance(start, datetime) or isinstance(end, datetime):
        raise TypeError("start and end must be dates")
    start = _month_start(start)
    end = _month_start(end)
    if end < start:
        raise ValueError("end cannot precede start")
    rng = random.Random(seed)
    raw_rows = _monthly_rows(start, end, rng)
    raw_rows.extend(_weekly_rows(start, end, rng))
    raw_rows.extend(_daily_rows(start, end, rng))
    if include_additional_targets:
        # Independent streams keep the original payroll/predictor fixture stable as
        # new targets are added.
        raw_rows.extend(_core_cpi_rows(start, end, random.Random(seed + 1)))
        raw_rows.extend(_quarterly_gdp_rows(start, end, random.Random(seed + 2)))
    observations = observations_to_frame(_set_realtime_ends(raw_rows))
    if set(observations["provenance_label"].unique()) != {SYNTHETIC_PROVENANCE}:
        raise AssertionError("synthetic fixture lost its provenance label")
    return SyntheticFixture(
        observations=observations,
        release_calendar=build_payroll_release_calendar(start, end),
        series_metadata=_series_metadata(
            ALL_SERIES_IDS if include_additional_targets else SERIES_IDS
        ),
        cpi_release_calendar=(
            build_core_cpi_release_calendar(start, end)
            if include_additional_targets
            else None
        ),
        gdp_release_calendar=(
            build_real_gdp_release_calendar(start, end)
            if include_additional_targets
            else None
        ),
    )


def build_multitarget_synthetic_fixture(
    start: date = date(2017, 1, 1),
    end: date = date(2025, 3, 1),
    *,
    seed: int = 20_260_807,
) -> SyntheticFixture:
    """Return the explicit 12-series payroll, core-CPI, and real-GDP fixture."""

    return build_synthetic_fixture(
        start,
        end,
        seed=seed,
        include_additional_targets=True,
    )


# Verb-oriented compatibility alias for callers constructing sample artifacts.
generate_synthetic_fixture = build_synthetic_fixture


__all__ = [
    "ADDITIONAL_TARGET_SERIES_IDS",
    "ALL_SERIES_IDS",
    "SERIES_IDS",
    "SERIES_METADATA_SCHEMA",
    "SyntheticFixture",
    "build_multitarget_synthetic_fixture",
    "build_synthetic_fixture",
    "generate_synthetic_fixture",
]
