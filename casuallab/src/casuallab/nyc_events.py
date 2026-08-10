"""Verified calendar and permitted-event enrichment for the NYC full-month panel.

The external records are used only for descriptive associations.  Permit windows
can include setup and breakdown, a permit is not attendance, and the source does
not enumerate every private-venue event.  Nothing in this module identifies a
causal holiday or event effect.
"""

from __future__ import annotations

import hashlib
import json
import math
import shutil
import tempfile
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

from casuallab.data import sha256_file

OPM_2024_HOLIDAY_URL = (
    "https://www.opm.gov/policy-data-oversight/pay-leave/federal-holidays/#url=2024"
)
NYC_2024_HOLIDAY_URL = (
    "https://www.nyc.gov/assets/opa/downloads/pdf/2024-list-of-holidays.pdf"
)
NYC_PERMITTED_EVENTS_DATASET_URL = (
    "https://data.cityofnewyork.us/City-Government/"
    "NYC-Permitted-Event-Information-Historical/bkfu-528j"
)
NYC_PERMITTED_EVENTS_QUERY_URL = (
    "https://data.cityofnewyork.us/resource/bkfu-528j.csv?"
    "%24select=event_id%2Cevent_name%2Cstart_date_time%2Cend_date_time%2C"
    "event_agency%2Cevent_type%2Cevent_borough%2Cevent_location%2C"
    "community_board%2Cpolice_precinct&"
    "%24where=start_date_time%20%3C%20%272024-02-01T00%3A00%3A00.000%27%20"
    "and%20end_date_time%20%3E%3D%20%272024-01-01T00%3A00%3A00.000%27&"
    "%24order=start_date_time%2Cend_date_time%2Cevent_id%2Cevent_location&"
    "%24limit=10000"
)

HOLIDAY_SNAPSHOT_SHA256 = (
    "31a9c0880a4d248aeb17b7946d356c224dfd7831a7d4f1bed51b8873e81227db"
)
EVENT_SNAPSHOT_SHA256 = (
    "62bb6f5f312382fa647ddb3a45f860bbd979fb03cfb61572544b865569a54e75"
)
EVENT_EVIDENCE_LABEL = "descriptive_observed_external_calendar_events"
EVENT_SCHEMA_VERSION = "1.0.0"

DEFAULT_MAJOR_EVENT_IDS = ("677860", "684757")
DEFAULT_PUBLIC_GATHERING_TYPES = (
    "Athletic Race / Tour",
    "Farmers Market",
    "Parade",
    "Plaza Event",
    "Plaza Partner Event",
    "Religious Event",
    "Single Block Festival",
    "Street Event",
    "Street Festival",
)


@dataclass(frozen=True, slots=True)
class NYCEventsConfig:
    """Pinned January 2024 official-calendar and permit-source contract."""

    start_date: date = date(2024, 1, 1)
    end_date: date = date(2024, 1, 31)
    expected_holiday_rows: int = 2
    expected_event_rows: int = 6007
    expected_unique_event_ids: int = 951
    holiday_snapshot_sha256: str = HOLIDAY_SNAPSHOT_SHA256
    event_snapshot_sha256: str = EVENT_SNAPSHOT_SHA256
    major_event_ids: tuple[str, ...] = DEFAULT_MAJOR_EVENT_IDS
    public_gathering_event_types: tuple[str, ...] = DEFAULT_PUBLIC_GATHERING_TYPES

    def __post_init__(self) -> None:
        if self.start_date > self.end_date:
            raise ValueError("event start_date must not exceed end_date")
        if self.expected_holiday_rows < 1:
            raise ValueError("expected_holiday_rows must be positive")
        if self.expected_event_rows < 1 or self.expected_unique_event_ids < 1:
            raise ValueError("event row and unique-ID expectations must be positive")
        if self.expected_unique_event_ids > self.expected_event_rows:
            raise ValueError("expected_unique_event_ids cannot exceed expected_event_rows")
        for field_name in ("holiday_snapshot_sha256", "event_snapshot_sha256"):
            digest = getattr(self, field_name)
            if len(digest) != 64 or any(
                character not in "0123456789abcdef" for character in digest
            ):
                raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
        if not self.major_event_ids or len(set(self.major_event_ids)) != len(
            self.major_event_ids
        ):
            raise ValueError("major_event_ids must be nonempty and unique")
        if any(not event_id.strip() for event_id in self.major_event_ids):
            raise ValueError("major_event_ids cannot contain blank IDs")
        if not self.public_gathering_event_types or len(
            set(self.public_gathering_event_types)
        ) != len(self.public_gathering_event_types):
            raise ValueError("public_gathering_event_types must be nonempty and unique")

    @property
    def expected_calendar_days(self) -> int:
        return (self.end_date - self.start_date).days + 1


@dataclass(frozen=True, slots=True)
class NYCEventsArtifacts:
    calendar_daily_path: Path
    normalized_events_path: Path
    event_type_daily_path: Path
    daily_panel_path: Path
    hourly_contrast_path: Path
    summary_path: Path
    manifest_path: Path

    def paths(self) -> tuple[Path, ...]:
        return (
            self.calendar_daily_path,
            self.normalized_events_path,
            self.event_type_daily_path,
            self.daily_panel_path,
            self.hourly_contrast_path,
            self.summary_path,
            self.manifest_path,
        )


def _atomic_json(payload: dict[str, Any], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        prefix=f".{path.stem}-",
        suffix=path.suffix,
        dir=path.parent,
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        json.dump(payload, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
    temporary.replace(path)
    return path


def _atomic_csv(frame: pd.DataFrame, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="",
        prefix=f".{path.stem}-",
        suffix=path.suffix,
        dir=path.parent,
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        frame.to_csv(handle, index=False)
    temporary.replace(path)
    return path


def download_nyc_permitted_events_snapshot(
    destination: str | Path,
    config: NYCEventsConfig | None = None,
    *,
    refresh: bool = False,
) -> Path:
    """Atomically download and verify the pinned NYC Open Data CSV response."""

    cfg = config or NYCEventsConfig()
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file() and not refresh:
        if sha256_file(target) != cfg.event_snapshot_sha256:
            raise ValueError("cached NYC permitted-events SHA-256 does not match the pin")
        return target
    with tempfile.NamedTemporaryFile(
        prefix=f".{target.stem}-",
        suffix=target.suffix,
        dir=target.parent,
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
    request = urllib.request.Request(
        NYC_PERMITTED_EVENTS_QUERY_URL,
        headers={"User-Agent": "CausalMarketplaceLab/0.1 descriptive research"},
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response, temporary.open(
            "wb"
        ) as stream:
            while block := response.read(1024 * 1024):
                stream.write(block)
        if sha256_file(temporary) != cfg.event_snapshot_sha256:
            raise ValueError("downloaded NYC permitted-events SHA-256 does not match the pin")
        temporary.replace(target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return target


def normalize_nyc_holiday_calendar(
    holiday_snapshot_path: str | Path,
    config: NYCEventsConfig | None = None,
) -> pd.DataFrame:
    """Validate positive holiday rows and expand them to a complete daily calendar."""

    cfg = config or NYCEventsConfig()
    source = Path(holiday_snapshot_path)
    if not source.is_file():
        raise FileNotFoundError(source)
    if sha256_file(source) != cfg.holiday_snapshot_sha256:
        raise ValueError("official holiday snapshot SHA-256 does not match the pin")
    holidays = pd.read_csv(source, dtype="string", keep_default_na=False)
    required_columns = (
        "service_date",
        "federal_holiday_name",
        "nyc_city_employee_holiday_name",
    )
    missing = set(required_columns).difference(holidays.columns)
    if missing:
        raise ValueError(f"holiday snapshot missing fields: {sorted(missing)}")
    if len(holidays) != cfg.expected_holiday_rows:
        raise ValueError("holiday snapshot has an unexpected row count")
    dates = pd.to_datetime(holidays["service_date"], errors="raise").dt.date
    if holidays["service_date"].duplicated().any() or list(dates) != sorted(dates):
        raise ValueError("holiday dates must be unique and sorted")
    if any(day < cfg.start_date or day > cfg.end_date for day in dates):
        raise ValueError("holiday snapshot contains a date outside the configured period")
    for column in ("federal_holiday_name", "nyc_city_employee_holiday_name"):
        if holidays[column].str.strip().eq("").any():
            raise ValueError(f"holiday snapshot contains a blank {column}")

    calendar = pd.DataFrame(
        {"service_date": pd.date_range(cfg.start_date, cfg.end_date, freq="D").date}
    )
    # Keep publication bytes independent of Python's hash-randomized set order.
    selected = holidays.loc[:, required_columns].copy()
    selected["service_date"] = dates
    calendar = calendar.merge(selected, on="service_date", how="left", validate="1:1")
    for column in ("federal_holiday_name", "nyc_city_employee_holiday_name"):
        calendar[column] = calendar[column].fillna("").astype(str)
    calendar["is_federal_holiday"] = calendar["federal_holiday_name"].ne("")
    calendar["is_nyc_city_employee_holiday"] = calendar[
        "nyc_city_employee_holiday_name"
    ].ne("")
    calendar["is_any_official_holiday"] = (
        calendar["is_federal_holiday"]
        | calendar["is_nyc_city_employee_holiday"]
    )
    calendar["evidence_label"] = EVENT_EVIDENCE_LABEL
    calendar["causal_claim"] = False
    return calendar.sort_values("service_date").reset_index(drop=True)


def normalize_nyc_permitted_events(
    event_snapshot_path: str | Path,
    config: NYCEventsConfig | None = None,
) -> pd.DataFrame:
    """Validate the complete ordered January-overlap permit response.

    Invalid source intervals are retained and flagged rather than silently repaired.
    Such rows are excluded from date expansion.
    """

    cfg = config or NYCEventsConfig()
    source = Path(event_snapshot_path)
    if not source.is_file():
        raise FileNotFoundError(source)
    if sha256_file(source) != cfg.event_snapshot_sha256:
        raise ValueError("NYC permitted-events snapshot SHA-256 does not match the pin")
    events = pd.read_csv(source, dtype="string", keep_default_na=False)
    required = {
        "event_id",
        "event_name",
        "start_date_time",
        "end_date_time",
        "event_agency",
        "event_type",
        "event_borough",
        "event_location",
        "community_board",
        "police_precinct",
    }
    missing = required.difference(events.columns)
    if missing:
        raise ValueError(f"permitted-events snapshot missing fields: {sorted(missing)}")
    if len(events) != cfg.expected_event_rows:
        raise ValueError("permitted-events snapshot has an unexpected row count")
    if events.duplicated().any():
        raise ValueError("permitted-events snapshot contains exact duplicate rows")
    for column in (
        "event_id",
        "start_date_time",
        "end_date_time",
        "event_agency",
        "event_type",
        "event_borough",
        "event_location",
    ):
        if events[column].str.strip().eq("").any():
            raise ValueError(f"permitted-events snapshot contains a blank {column}")
    if events["event_id"].nunique() != cfg.expected_unique_event_ids:
        raise ValueError("permitted-events snapshot has an unexpected unique event-ID count")
    if not set(cfg.major_event_ids).issubset(set(events["event_id"])):
        raise ValueError("pre-specified major event IDs are missing from the snapshot")
    if (events.groupby("event_id")["event_type"].nunique() > 1).any():
        raise ValueError("one event ID maps to multiple event types")

    start = pd.to_datetime(events["start_date_time"], errors="raise")
    end = pd.to_datetime(events["end_date_time"], errors="raise")
    ordered = events.assign(
        _start=start,
        _end=end,
        _event_id_number=pd.to_numeric(events["event_id"], errors="raise"),
    ).sort_values(
        ["_start", "_end", "_event_id_number", "event_location"],
        kind="mergesort",
    )
    if not np.array_equal(ordered.index.to_numpy(), events.index.to_numpy()):
        raise ValueError("permitted-events snapshot does not match the pinned query order")

    normalized = events.copy()
    normalized["permit_start_local"] = start
    normalized["permit_end_local"] = end
    normalized["invalid_permit_interval"] = end < start
    normalized["zero_duration_permit_interval"] = end == start
    normalized["usable_for_daily_expansion"] = end > start
    normalized["researcher_defined_major_event"] = normalized["event_id"].isin(
        cfg.major_event_ids
    )
    normalized["public_gathering_permit_subset"] = normalized["event_type"].isin(
        cfg.public_gathering_event_types
    )
    normalized["event_name_missing"] = normalized["event_name"].str.strip().eq("")
    normalized["evidence_label"] = EVENT_EVIDENCE_LABEL
    normalized["causal_claim"] = False
    return normalized


def build_nyc_event_calendar(
    holidays: pd.DataFrame,
    events: pd.DataFrame,
    config: NYCEventsConfig | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Expand valid permit rows to daily event-ID exposures and aggregate by type."""

    cfg = config or NYCEventsConfig()
    expected_dates = list(pd.date_range(cfg.start_date, cfg.end_date, freq="D").date)
    if list(holidays["service_date"]) != expected_dates:
        raise ValueError("holiday calendar is not complete for the configured period")
    required = {
        "event_id",
        "event_name",
        "event_type",
        "permit_start_local",
        "permit_end_local",
        "usable_for_daily_expansion",
        "researcher_defined_major_event",
        "public_gathering_permit_subset",
    }
    missing = required.difference(events.columns)
    if missing:
        raise ValueError(f"normalized events missing fields: {sorted(missing)}")

    event_days: list[dict[str, object]] = []
    valid = events.loc[events["usable_for_daily_expansion"].astype(bool)]
    period_start = pd.Timestamp(cfg.start_date)
    period_end = pd.Timestamp(cfg.end_date)
    for row in valid.itertuples(index=False):
        permit_start = pd.Timestamp(row.permit_start_local)
        permit_end = pd.Timestamp(row.permit_end_local)
        first = max(permit_start.normalize(), period_start)
        # Permit windows are half-open.  An interval ending exactly at midnight
        # does not create exposure on the following service date.
        last = min(
            (permit_end - pd.Timedelta(nanoseconds=1)).normalize(),
            period_end,
        )
        if first > last:
            continue
        for service_date in pd.date_range(first, last, freq="D").date:
            event_days.append(
                {
                    "service_date": service_date,
                    "event_id": str(row.event_id),
                    "event_name": str(row.event_name),
                    "event_type": str(row.event_type),
                    "researcher_defined_major_event": bool(
                        row.researcher_defined_major_event
                    ),
                    "public_gathering_permit_subset": bool(
                        row.public_gathering_permit_subset
                    ),
                }
            )
    expanded = pd.DataFrame(event_days)
    if expanded.empty:
        raise ValueError("no valid permitted-event rows overlap the configured period")
    expanded = expanded.drop_duplicates(["service_date", "event_id"])

    daily = (
        expanded.groupby("service_date", observed=True)
        .agg(
            active_permitted_event_count=("event_id", "nunique"),
            active_public_gathering_permitted_event_count=(
                "public_gathering_permit_subset",
                "sum",
            ),
            active_major_permitted_event_count=(
                "researcher_defined_major_event",
                "sum",
            ),
        )
        .reset_index()
    )
    major_names = (
        expanded.loc[expanded["researcher_defined_major_event"]]
        .groupby("service_date", observed=True)["event_name"]
        .agg(lambda values: " | ".join(sorted(set(values))))
        .rename("major_permitted_event_names")
        .reset_index()
    )
    daily = daily.merge(major_names, on="service_date", how="left", validate="1:1")
    calendar = holidays.merge(daily, on="service_date", how="left", validate="1:1")
    count_columns = (
        "active_permitted_event_count",
        "active_public_gathering_permitted_event_count",
        "active_major_permitted_event_count",
    )
    for column in count_columns:
        calendar[column] = calendar[column].fillna(0).astype(int)
    calendar["major_permitted_event_names"] = calendar[
        "major_permitted_event_names"
    ].fillna("")
    calendar["is_researcher_defined_major_event_day"] = (
        calendar["active_major_permitted_event_count"] > 0
    )
    median_intensity = float(calendar["active_permitted_event_count"].median())
    calendar["monthly_median_active_permitted_event_count"] = median_intensity
    calendar["is_above_monthly_median_permit_intensity_day"] = (
        calendar["active_permitted_event_count"] > median_intensity
    )
    calendar["permit_intensity_band"] = np.where(
        calendar["is_above_monthly_median_permit_intensity_day"],
        "above_monthly_median",
        "at_or_below_monthly_median",
    )
    calendar["event_signal_spatial_granularity"] = "citywide"
    calendar["event_signal_temporal_granularity"] = "service_date"
    calendar["evidence_label"] = EVENT_EVIDENCE_LABEL
    calendar["causal_claim"] = False

    type_daily = (
        expanded.groupby(["service_date", "event_type"], observed=True)["event_id"]
        .nunique()
        .rename("active_unique_permitted_events")
        .reset_index()
        .sort_values(["service_date", "event_type"])
        .reset_index(drop=True)
    )
    type_daily["evidence_label"] = EVENT_EVIDENCE_LABEL
    type_daily["causal_claim"] = False
    return calendar, type_daily


def _sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _scan_sql(paths: Sequence[Path]) -> str:
    if not paths:
        raise FileNotFoundError("NYC event analysis requires zone-time Parquet files")
    rendered = ", ".join(_sql_string(str(path.resolve())) for path in paths)
    return f"read_parquet([{rendered}], hive_partitioning=false)"


def _finite_correlation(left: pd.Series, right: pd.Series) -> float | None:
    valid = left.notna() & right.notna()
    if valid.sum() < 3 or left.loc[valid].nunique() < 2 or right.loc[valid].nunique() < 2:
        return None
    value = float(left.loc[valid].corr(right.loc[valid]))
    return value if math.isfinite(value) else None


def _binary_contrast(frame: pd.DataFrame, flag: str) -> dict[str, float | int | None]:
    selected = frame[flag].astype(bool)
    true_mean = float(frame.loc[selected, "published_completed_trips"].mean())
    false_mean = float(frame.loc[~selected, "published_completed_trips"].mean())
    difference = true_mean - false_mean
    return {
        "exposed_days": int(selected.sum()),
        "comparison_days": int((~selected).sum()),
        "mean_daily_published_completed_trips_exposed": true_mean,
        "mean_daily_published_completed_trips_comparison": false_mean,
        "exposed_minus_comparison_mean_daily_published_completed_trips": difference,
        "exposed_minus_comparison_relative_to_comparison": (
            difference / false_mean if false_mean else None
        ),
    }


def _within_group_demeaned_correlation(
    frame: pd.DataFrame,
    left: str,
    right: str,
    group: str,
) -> float | None:
    left_residual = frame[left] - frame.groupby(group, observed=True)[left].transform("mean")
    right_residual = frame[right] - frame.groupby(group, observed=True)[right].transform(
        "mean"
    )
    return _finite_correlation(left_residual, right_residual)


def event_demand_associations(
    zone_time_paths: Sequence[str | Path],
    calendar: pd.DataFrame,
    events: pd.DataFrame,
    type_daily: pd.DataFrame,
    config: NYCEventsConfig | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Join citywide daily signals to trip totals and compute descriptive contrasts."""

    cfg = config or NYCEventsConfig()
    paths = tuple(Path(path) for path in zone_time_paths)
    scan = _scan_sql(paths)
    connection = duckdb.connect(database=":memory:")
    try:
        daily = connection.execute(
            f"""
            SELECT CAST(service_date AS DATE) AS service_date,
                   SUM(CAST(trip_count AS BIGINT)) AS published_completed_trips,
                   COUNT(DISTINCT zone_id) AS panel_zones,
                   SUM(CASE WHEN trip_count > 0 THEN 1 ELSE 0 END) AS occupied_zone_hours
            FROM {scan}
            GROUP BY 1
            ORDER BY 1
            """
        ).fetchdf()
        hourly = connection.execute(
            f"""
            SELECT CAST(service_date AS DATE) AS service_date,
                   CAST(hour AS INTEGER) AS hour,
                   SUM(CAST(trip_count AS BIGINT)) AS published_completed_trips
            FROM {scan}
            GROUP BY 1, 2
            ORDER BY 1, 2
            """
        ).fetchdf()
    finally:
        connection.close()
    daily["service_date"] = pd.to_datetime(daily["service_date"]).dt.date
    hourly["service_date"] = pd.to_datetime(hourly["service_date"]).dt.date
    expected_dates = set(pd.date_range(cfg.start_date, cfg.end_date, freq="D").date)
    if set(daily["service_date"]) != expected_dates or len(daily) != cfg.expected_calendar_days:
        raise ValueError("NYC zone-time panel does not cover the configured event month")
    if len(hourly) != cfg.expected_calendar_days * 24:
        raise ValueError("NYC zone-time panel does not contain every configured date-hour")

    event_calendar = calendar.copy()
    event_calendar["service_date"] = pd.to_datetime(
        event_calendar["service_date"], errors="raise"
    ).dt.date
    daily = daily.merge(event_calendar, on="service_date", how="left", validate="1:1")
    if daily["evidence_label"].isna().any():
        raise ValueError("calendar/event coverage is incomplete after joining the NYC panel")
    daily["iso_weekday"] = (
        pd.to_datetime(daily["service_date"]).dt.isocalendar().day.astype(int)
    )

    hourly = hourly.merge(
        event_calendar[
            [
                "service_date",
                "is_any_official_holiday",
                "is_researcher_defined_major_event_day",
                "is_above_monthly_median_permit_intensity_day",
            ]
        ],
        on="service_date",
        how="left",
        validate="m:1",
    )
    group_flag = "is_above_monthly_median_permit_intensity_day"
    hourly_contrast = (
        hourly.groupby(["hour", group_flag], observed=True)["published_completed_trips"]
        .agg(["count", "mean"])
        .reset_index()
        .pivot(index="hour", columns=group_flag, values=["count", "mean"])
    )
    hourly_contrast.columns = [
        f"{'days' if measure == 'count' else 'mean_published_completed_trips'}_"
        f"{'above_median_intensity' if high else 'at_or_below_median_intensity'}"
        for measure, high in hourly_contrast.columns
    ]
    hourly_contrast = hourly_contrast.reset_index()
    needed_columns = (
        "days_above_median_intensity",
        "days_at_or_below_median_intensity",
        "mean_published_completed_trips_above_median_intensity",
        "mean_published_completed_trips_at_or_below_median_intensity",
    )
    for column in needed_columns:
        if column not in hourly_contrast:
            hourly_contrast[column] = np.nan
    hourly_contrast["above_minus_at_or_below_mean_published_completed_trips"] = (
        hourly_contrast["mean_published_completed_trips_above_median_intensity"]
        - hourly_contrast[
            "mean_published_completed_trips_at_or_below_median_intensity"
        ]
    )
    hourly_contrast["event_signal_temporal_granularity"] = "service_date"
    hourly_contrast["evidence_label"] = EVENT_EVIDENCE_LABEL
    hourly_contrast["causal_claim"] = False

    major = daily["is_researcher_defined_major_event_day"].astype(bool)
    holiday = daily["is_any_official_holiday"].astype(bool)
    high = daily["is_above_monthly_median_permit_intensity_day"].astype(bool)
    weekend = daily["iso_weekday"] >= 6
    weekdays = daily.loc[~weekend].copy()
    valid_events = events["usable_for_daily_expansion"].astype(bool)
    summary = {
        "schema_version": EVENT_SCHEMA_VERSION,
        "evidence_label": EVENT_EVIDENCE_LABEL,
        "causal_claim": False,
        "scope": {
            "city": "New York City",
            "pickup_month": "2024-01",
            "published_completed_trip_days": len(daily),
            "event_signal_spatial_granularity": "citywide",
            "event_signal_temporal_granularity": "service_date",
            "population_claim": False,
        },
        "definitions": {
            "official_holiday": (
                "A positive date in the complete January transcription of the OPM "
                "federal and/or NYC employee holiday schedules."
            ),
            "active_permitted_event_count": (
                "Unique NYC Open Data event IDs with at least one positive-duration "
                "permit row whose half-open [start, end) interval overlaps the service date."
            ),
            "public_gathering_permit_subset": list(cfg.public_gathering_event_types),
            "above_monthly_median_permit_intensity": (
                "Active unique permitted-event count strictly above the source-only "
                "monthly median; trip outcomes are not used to set the threshold."
            ),
            "researcher_defined_major_permitted_event": {
                "event_ids": list(cfg.major_event_ids),
                "event_names": sorted(
                    set(
                        events.loc[
                            events["event_id"].isin(cfg.major_event_ids), "event_name"
                        ].astype(str)
                    )
                ),
                "official_severity_classification": False,
            },
        },
        "coverage": {
            "holiday_source_positive_rows": cfg.expected_holiday_rows,
            "joined_days": len(daily),
            "joined_date_hours": len(hourly),
            "federal_holiday_days": int(daily["is_federal_holiday"].sum()),
            "nyc_city_employee_holiday_days": int(
                daily["is_nyc_city_employee_holiday"].sum()
            ),
            "any_official_holiday_days": int(holiday.sum()),
            "source_permit_rows": len(events),
            "source_unique_event_ids": int(events["event_id"].nunique()),
            "valid_interval_rows": int(valid_events.sum()),
            "invalid_interval_rows_retained_but_not_expanded": int(
                events["invalid_permit_interval"].sum()
            ),
            "zero_duration_interval_rows_retained_but_not_expanded": int(
                events["zero_duration_permit_interval"].sum()
            ),
            "all_nonpositive_interval_rows_retained_but_not_expanded": int(
                (~valid_events).sum()
            ),
            "event_name_missing_rows_retained": int(events["event_name_missing"].sum()),
            "valid_unique_event_ids": int(
                events.loc[valid_events, "event_id"].nunique()
            ),
            "event_types": int(events["event_type"].nunique()),
            "expanded_unique_event_days": int(
                type_daily["active_unique_permitted_events"].sum()
            ),
            "minimum_daily_active_permitted_events": int(
                daily["active_permitted_event_count"].min()
            ),
            "median_daily_active_permitted_events": float(
                daily["active_permitted_event_count"].median()
            ),
            "maximum_daily_active_permitted_events": int(
                daily["active_permitted_event_count"].max()
            ),
            "above_median_permit_intensity_days": int(high.sum()),
            "at_or_below_median_permit_intensity_days": int((~high).sum()),
            "weekend_days": int(weekend.sum()),
            "above_median_permit_intensity_weekend_days": int((high & weekend).sum()),
            "at_or_below_median_permit_intensity_weekend_days": int(
                ((~high) & weekend).sum()
            ),
            "researcher_defined_major_event_days": int(major.sum()),
        },
        "associations": {
            "above_vs_at_or_below_median_permit_intensity": _binary_contrast(
                daily, "is_above_monthly_median_permit_intensity_day"
            ),
            "above_vs_at_or_below_median_permit_intensity_weekdays_only": (
                _binary_contrast(
                    weekdays, "is_above_monthly_median_permit_intensity_day"
                )
            ),
            "official_holiday_vs_nonholiday": _binary_contrast(
                daily, "is_any_official_holiday"
            ),
            "major_permitted_event_day_vs_other_days": _binary_contrast(
                daily, "is_researcher_defined_major_event_day"
            ),
            "active_permitted_event_count_daily_trip_correlation": _finite_correlation(
                daily["active_permitted_event_count"],
                daily["published_completed_trips"],
            ),
            "active_public_gathering_permit_count_daily_trip_correlation": (
                _finite_correlation(
                    daily["active_public_gathering_permitted_event_count"],
                    daily["published_completed_trips"],
                )
            ),
            "weekday_demeaned_active_permit_count_daily_trip_correlation": (
                _within_group_demeaned_correlation(
                    daily,
                    "active_permitted_event_count",
                    "published_completed_trips",
                    "iso_weekday",
                )
            ),
        },
        "identification_checks": {
            "major_event_days_are_subset_of_holiday_days": bool((~major | holiday).all()),
            "all_weekend_days_are_above_median_permit_intensity": bool(
                high.loc[weekend].all()
            ),
            "major_event_contrast_separately_identifies_event_effect": False,
            "permit_intensity_assignment_is_randomized": False,
            "causal_effect_identified": False,
        },
        "conservation": {
            "zone_time_trip_sum": int(daily["published_completed_trips"].sum()),
            "daily_trip_sum": int(daily["published_completed_trips"].sum()),
            "passes": True,
        },
        "limitations": [
            "All contrasts are observational associations; weekday, seasonality, weather, holidays, and other demand or supply shocks confound them.",
            "In this month every weekend is above the permit-intensity median, so the unstratified high-versus-lower contrast is mechanically entangled with weekend composition; weekday-only and weekday-demeaned diagnostics remain descriptive.",
            "Permit timestamps often include setup and breakdown and do not measure attendance, realized event scale, or the actual audience window.",
            "Signals are citywide daily proxies: borough/board/precinct strings are not a validated Taxi Zone crosswalk, so zone- and hour-specific exposure is unavailable.",
            "The historical permit dataset does not enumerate every arena, stadium, theater, concert, or private-venue event.",
            "One reversed and eight zero-duration source intervals are retained and flagged but excluded from date expansion; no undocumented timestamp correction is made.",
            "The narrow major-event flag occurs only on New Year's Day, so its one-day contrast cannot be separated from the holiday or extrapolated.",
            "Published completed trips exclude latent requests, unserved demand, and available drivers.",
            "One January month does not establish seasonal or annual transportability.",
        ],
    }
    return daily, hourly_contrast, summary


def _portable(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError as exc:
        raise ValueError(f"event artifact path is outside project_root: {path}") from exc


def _manifest_entry(
    path: Path,
    root: Path,
    role: str,
    *,
    source_url: str | None = None,
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "path": _portable(path, root),
        "role": role,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }
    if source_url is not None:
        entry["source_url"] = source_url
    return entry


def _entries_digest(entries: list[dict[str, Any]]) -> str:
    return hashlib.sha256(
        json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def write_nyc_events_bundle(
    holiday_snapshot_path: str | Path,
    event_snapshot_path: str | Path,
    panel_directory: str | Path,
    data_manifest_path: str | Path,
    output_directory: str | Path,
    *,
    project_root: str | Path,
    config: NYCEventsConfig | None = None,
) -> NYCEventsArtifacts:
    """Create a manifest-last, hash-verified NYC calendar/event bundle."""

    cfg = config or NYCEventsConfig()
    root = Path(project_root).resolve()
    holiday_source = Path(holiday_snapshot_path).resolve()
    event_source = Path(event_snapshot_path).resolve()
    panel_root = Path(panel_directory).resolve()
    source_manifest_path = Path(data_manifest_path).resolve()
    output = Path(output_directory).resolve()
    output.mkdir(parents=True, exist_ok=True)
    marker = output / "NYC_EVENTS_INCOMPLETE.json"
    manifest_path = output / "manifest.json"
    manifest_path.unlink(missing_ok=True)
    _atomic_json({"status": "incomplete"}, marker)
    stage = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=output.parent))

    try:
        source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
        if (
            source_manifest.get("config", {}).get("source") != "nyc_hvfhv"
            or source_manifest.get("config", {}).get("mode") != "full"
            or source_manifest.get("metadata", {}).get("evidence_label")
            != "descriptive_real_data"
            or source_manifest.get("metadata", {}).get("causal_claim") is not False
        ):
            raise ValueError("event analysis requires the verified NYC full-data manifest")
        panel_paths = tuple(sorted(path.resolve() for path in panel_root.rglob("*.parquet")))
        if not panel_paths:
            raise FileNotFoundError("NYC full zone-time panel is unavailable")
        declared: dict[Path, dict[str, Any]] = {}
        for entry in source_manifest.get("files", []):
            if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
                raise ValueError("NYC source manifest contains a malformed file entry")
            declared_path = Path(entry["path"])
            if declared_path.is_absolute() or ".." in declared_path.parts:
                raise ValueError("NYC source manifest contains a nonportable path")
            resolved = (root / declared_path).resolve()
            try:
                resolved.relative_to(root)
            except ValueError as exc:
                raise ValueError("NYC source manifest path escapes project_root") from exc
            if resolved in declared:
                raise ValueError("NYC source manifest contains duplicate file paths")
            declared[resolved] = entry
        declared_panel_paths = {
            path
            for path in declared
            if path.suffix == ".parquet" and path.is_relative_to(panel_root)
        }
        if set(panel_paths) != declared_panel_paths:
            raise ValueError(
                "NYC event panel files do not exactly match the source manifest"
            )
        for path in panel_paths:
            entry = declared[path]
            if path.stat().st_size != entry.get("bytes") or sha256_file(path) != entry.get(
                "sha256"
            ):
                raise ValueError(f"NYC event panel lineage mismatch: {path}")

        holidays = normalize_nyc_holiday_calendar(holiday_source, cfg)
        events = normalize_nyc_permitted_events(event_source, cfg)
        calendar, type_daily = build_nyc_event_calendar(holidays, events, cfg)
        daily, hourly, summary = event_demand_associations(
            panel_paths, calendar, events, type_daily, cfg
        )
        expected_trips = int(
            source_manifest["metadata"]["full_month_processing"]["row_conservation"][
                "zone_time_trip_sum"
            ]
        )
        if summary["conservation"]["daily_trip_sum"] != expected_trips:
            raise ValueError("NYC event daily panel does not conserve published trips")
        summary["provenance"] = {
            "holiday_snapshot_path": _portable(holiday_source, root),
            "holiday_snapshot_bytes": holiday_source.stat().st_size,
            "holiday_snapshot_sha256": sha256_file(holiday_source),
            "opm_2024_holiday_url": OPM_2024_HOLIDAY_URL,
            "nyc_2024_employee_holiday_url": NYC_2024_HOLIDAY_URL,
            "permitted_events_dataset_url": NYC_PERMITTED_EVENTS_DATASET_URL,
            "permitted_events_query_url": NYC_PERMITTED_EVENTS_QUERY_URL,
            "event_snapshot_path": _portable(event_source, root),
            "event_snapshot_bytes": event_source.stat().st_size,
            "event_snapshot_sha256": sha256_file(event_source),
            "nyc_data_manifest_path": _portable(source_manifest_path, root),
            "nyc_data_manifest_sha256": sha256_file(source_manifest_path),
            "panel_files_verified": len(panel_paths),
            "hashes_recomputed": True,
        }

        staged_paths = {
            "calendar_daily": _atomic_csv(calendar, stage / "calendar_event_daily.csv"),
            "normalized_events": _atomic_csv(
                events, stage / "permitted_events_normalized.csv"
            ),
            "event_type_daily": _atomic_csv(
                type_daily, stage / "permitted_event_type_daily.csv"
            ),
            "daily_panel": _atomic_csv(daily, stage / "event_trip_daily.csv"),
            "hourly_contrast": _atomic_csv(
                hourly, stage / "event_hourly_contrasts.csv"
            ),
            "summary": _atomic_json(summary, stage / "event_associations.json"),
        }
        published: dict[str, Path] = {}
        for key, staged_path in staged_paths.items():
            destination = output / staged_path.name
            staged_path.replace(destination)
            published[key] = destination

        files = [
            _manifest_entry(published["calendar_daily"], root, "normalized_daily_calendar"),
            _manifest_entry(
                published["normalized_events"], root, "normalized_permit_records"
            ),
            _manifest_entry(
                published["event_type_daily"], root, "daily_permit_type_counts"
            ),
            _manifest_entry(published["daily_panel"], root, "joined_daily_trip_panel"),
            _manifest_entry(
                published["hourly_contrast"], root, "descriptive_hourly_profiles"
            ),
            _manifest_entry(published["summary"], root, "descriptive_summary"),
        ]
        inputs = [
            _manifest_entry(
                holiday_source,
                root,
                "official_holiday_snapshot",
                source_url=OPM_2024_HOLIDAY_URL,
            ),
            _manifest_entry(
                event_source,
                root,
                "official_nyc_permitted_events_snapshot",
                source_url=NYC_PERMITTED_EVENTS_QUERY_URL,
            ),
            _manifest_entry(
                source_manifest_path,
                root,
                "nyc_full_data_manifest",
            ),
            *[
                _manifest_entry(path, root, "nyc_full_zone_time_panel")
                for path in panel_paths
            ],
        ]
        _atomic_json(
            {
                "schema_version": EVENT_SCHEMA_VERSION,
                "evidence_label": EVENT_EVIDENCE_LABEL,
                "causal_claim": False,
                "portable_paths": True,
                "files": files,
                "inputs": inputs,
                "declared_file_set_sha256": _entries_digest(files),
                "declared_input_set_sha256": _entries_digest(inputs),
                "checks": {
                    "holiday_snapshot_hash_matches": (
                        sha256_file(holiday_source) == cfg.holiday_snapshot_sha256
                    ),
                    "event_snapshot_hash_matches": (
                        sha256_file(event_source) == cfg.event_snapshot_sha256
                    ),
                    "calendar_complete": len(calendar) == cfg.expected_calendar_days,
                    "holiday_schedule_coverage_complete": True,
                    "event_source_rows_verified": len(events) == cfg.expected_event_rows,
                    "event_source_unique_ids_verified": (
                        events["event_id"].nunique() == cfg.expected_unique_event_ids
                    ),
                    "invalid_source_intervals_retained_and_excluded": (
                        int(events["invalid_permit_interval"].sum()) == 1
                        if cfg == NYCEventsConfig()
                        else True
                    ),
                    "zero_duration_source_intervals_retained_and_excluded": (
                        int(events["zero_duration_permit_interval"].sum()) == 8
                        if cfg == NYCEventsConfig()
                        else True
                    ),
                    "daily_signal_is_citywide_not_zone_exposure": True,
                    "hourly_profiles_repeat_daily_signal_not_event_hour_exposure": True,
                    "major_event_is_researcher_defined": True,
                    "major_event_contrast_separately_identified": False,
                    "nyc_source_manifest_valid": True,
                    "panel_files_verified": len(panel_paths),
                    "joined_days": len(daily),
                    "joined_date_hours": cfg.expected_calendar_days * 24,
                    "trip_conservation": True,
                    "causal_claim_is_false": True,
                },
            },
            manifest_path,
        )
        marker.unlink(missing_ok=True)
        return NYCEventsArtifacts(
            calendar_daily_path=published["calendar_daily"],
            normalized_events_path=published["normalized_events"],
            event_type_daily_path=published["event_type_daily"],
            daily_panel_path=published["daily_panel"],
            hourly_contrast_path=published["hourly_contrast"],
            summary_path=published["summary"],
            manifest_path=manifest_path,
        )
    finally:
        shutil.rmtree(stage, ignore_errors=True)


__all__ = [
    "DEFAULT_MAJOR_EVENT_IDS",
    "DEFAULT_PUBLIC_GATHERING_TYPES",
    "EVENT_EVIDENCE_LABEL",
    "EVENT_SCHEMA_VERSION",
    "EVENT_SNAPSHOT_SHA256",
    "HOLIDAY_SNAPSHOT_SHA256",
    "NYCEventsArtifacts",
    "NYCEventsConfig",
    "NYC_2024_HOLIDAY_URL",
    "NYC_PERMITTED_EVENTS_DATASET_URL",
    "NYC_PERMITTED_EVENTS_QUERY_URL",
    "OPM_2024_HOLIDAY_URL",
    "build_nyc_event_calendar",
    "download_nyc_permitted_events_snapshot",
    "event_demand_associations",
    "normalize_nyc_holiday_calendar",
    "normalize_nyc_permitted_events",
    "write_nyc_events_bundle",
]
