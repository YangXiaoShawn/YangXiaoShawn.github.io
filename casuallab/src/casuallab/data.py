"""Reproducible ingestion and panel construction for public ride-hail trips.

The small-data vertical slice uses a committed, provenance-documented extract from
Chicago's legacy TNP trip dataset.  The NYC adapter targets TLC's monthly HVFHV
Parquet files.  This module intentionally keeps measurement-quality flags in the
cleaned data: Chicago timestamps, fares, and tips are reported on rounded grids,
and missing census tracts may reflect privacy suppression or out-of-city travel.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
import tempfile
from calendar import monthrange
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, fields
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, BinaryIO, Literal, TypeAlias
from urllib.parse import urlencode
from urllib.request import urlopen

import duckdb
import polars as pl
import pyarrow.parquet as pq
import yaml

Source = Literal["chicago_tnp", "nyc_hvfhv"]
Mode = Literal["sample", "full"]
PathLike: TypeAlias = str | os.PathLike[str]
FrameInput: TypeAlias = pl.DataFrame | PathLike | Sequence[PathLike]

SCHEMA_VERSION = "1.0.0"
CHICAGO_DATASET_ID = "m6dm-c72p"
CHICAGO_API_ROOT = "https://data.cityofchicago.org/resource"
CHICAGO_DATASET_PAGE = (
    "https://data.cityofchicago.org/Transportation/"
    "Transportation-Network-Providers-Trips-2018-2022-/m6dm-c72p"
)
NYC_HVFHV_BASE_URL = "https://d37ci6vzurychx.cloudfront.net/trip-data"
NYC_TLC_TRIP_RECORD_PAGE = "https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page"
CHICAGO_SAMPLE_HOURS = tuple(range(0, 24, 2))
MISSING_ZONE_ID = "__MISSING_OR_OUTSIDE__"

CHICAGO_COLUMNS = (
    "trip_id",
    "trip_start_timestamp",
    "trip_end_timestamp",
    "trip_seconds",
    "trip_miles",
    "pickup_census_tract",
    "dropoff_census_tract",
    "pickup_community_area",
    "dropoff_community_area",
    "fare",
    "tip",
    "additional_charges",
    "trip_total",
    "shared_trip_authorized",
    "trips_pooled",
    "pickup_centroid_latitude",
    "pickup_centroid_longitude",
    "dropoff_centroid_latitude",
    "dropoff_centroid_longitude",
)

CHICAGO_RAW_SCHEMA = pl.Schema(
    {
        "trip_id": pl.String,
        "trip_start_timestamp": pl.String,
        "trip_end_timestamp": pl.String,
        "trip_seconds": pl.Int64,
        "trip_miles": pl.Float64,
        "pickup_census_tract": pl.String,
        "dropoff_census_tract": pl.String,
        "pickup_community_area": pl.Int64,
        "dropoff_community_area": pl.Int64,
        "fare": pl.Float64,
        "tip": pl.Float64,
        "additional_charges": pl.Float64,
        "trip_total": pl.Float64,
        "shared_trip_authorized": pl.Boolean,
        "trips_pooled": pl.Int64,
        "pickup_centroid_latitude": pl.Float64,
        "pickup_centroid_longitude": pl.Float64,
        "dropoff_centroid_latitude": pl.Float64,
        "dropoff_centroid_longitude": pl.Float64,
    }
)

NYC_HVFHV_RAW_SCHEMA = pl.Schema(
    {
        "hvfhs_license_num": pl.String,
        "dispatching_base_num": pl.String,
        "originating_base_num": pl.String,
        "request_datetime": pl.Datetime("us"),
        "on_scene_datetime": pl.Datetime("us"),
        "pickup_datetime": pl.Datetime("us"),
        "dropoff_datetime": pl.Datetime("us"),
        "PULocationID": pl.Int64,
        "DOLocationID": pl.Int64,
        "trip_miles": pl.Float64,
        "trip_time": pl.Int64,
        "base_passenger_fare": pl.Float64,
        "tolls": pl.Float64,
        "bcf": pl.Float64,
        "sales_tax": pl.Float64,
        "congestion_surcharge": pl.Float64,
        "airport_fee": pl.Float64,
        "tips": pl.Float64,
        "driver_pay": pl.Float64,
        "shared_request_flag": pl.String,
        "shared_match_flag": pl.String,
        "access_a_ride_flag": pl.String,
        "wav_request_flag": pl.String,
        "wav_match_flag": pl.String,
        # Added to TLC trip records in 2025; normalization treats it as optional.
        "cbd_congestion_fee": pl.Float64,
    }
)

CLEAN_TRIP_SCHEMA = pl.Schema(
    {
        "source": pl.String,
        "source_dataset_id": pl.String,
        "trip_id": pl.String,
        "record_id_is_surrogate": pl.Boolean,
        "provider_id": pl.String,
        "dispatching_base_id": pl.String,
        "request_datetime": pl.Datetime("us"),
        "pickup_datetime": pl.Datetime("us"),
        "dropoff_datetime": pl.Datetime("us"),
        "pickup_datetime_utc": pl.Datetime("us", "UTC"),
        "dropoff_datetime_utc": pl.Datetime("us", "UTC"),
        "source_timezone": pl.String,
        "service_date": pl.Date,
        "service_year": pl.Int32,
        "service_month": pl.Int8,
        "service_day_of_week": pl.Int8,
        "pickup_zone_id": pl.String,
        "dropoff_zone_id": pl.String,
        "zone_type": pl.String,
        "pickup_census_tract": pl.String,
        "dropoff_census_tract": pl.String,
        "trip_seconds": pl.Int64,
        "trip_miles": pl.Float64,
        "fare": pl.Float64,
        "tips": pl.Float64,
        "tolls": pl.Float64,
        "taxes_and_surcharges": pl.Float64,
        "additional_charges": pl.Float64,
        "total_amount": pl.Float64,
        "driver_pay": pl.Float64,
        "airport_fee": pl.Float64,
        "shared_requested": pl.Boolean,
        "shared_matched": pl.Boolean,
        "trips_pooled": pl.Int64,
        "airport_trip": pl.Boolean,
        "pickup_zone_missing": pl.Boolean,
        "dropoff_zone_missing": pl.Boolean,
        "pickup_census_tract_missing_or_suppressed": pl.Boolean,
        "dropoff_census_tract_missing_or_suppressed": pl.Boolean,
        "reported_timestamp_rounding_minutes": pl.Int16,
        "reported_fare_rounding_increment": pl.Float64,
        "reported_tip_rounding_increment": pl.Float64,
        "pickup_on_15_minute_grid": pl.Boolean,
        "fare_on_declared_grid": pl.Boolean,
    }
)

REQUIRED_RAW_COLUMNS: dict[Source, frozenset[str]] = {
    "chicago_tnp": frozenset(
        {
            "trip_id",
            "trip_start_timestamp",
            "trip_end_timestamp",
            "trip_seconds",
            "trip_miles",
            "pickup_community_area",
            "dropoff_community_area",
            "fare",
        }
    ),
    "nyc_hvfhv": frozenset(
        {
            "hvfhs_license_num",
            "pickup_datetime",
            "dropoff_datetime",
            "PULocationID",
            "DOLocationID",
            "trip_miles",
            "trip_time",
            "base_passenger_fare",
        }
    ),
}

SOURCE_METADATA: dict[Source, dict[str, Any]] = {
    "chicago_tnp": {
        "publisher": "City of Chicago",
        "dataset_id": CHICAGO_DATASET_ID,
        "dataset_page": CHICAGO_DATASET_PAGE,
        "timezone": "America/Chicago",
        "known_measurement": {
            "timestamps": "rounded to nearest 15 minutes",
            "fare": "rounded to nearest $2.50",
            "tips": "rounded to nearest $1.00",
            "census_tracts": "may be suppressed; blanks also occur outside Chicago",
            "airport_activity": (
                "left unknown when a missing endpoint prevents ruling airport activity in or out"
            ),
        },
    },
    "nyc_hvfhv": {
        "publisher": "New York City Taxi and Limousine Commission",
        "dataset_page": NYC_TLC_TRIP_RECORD_PAGE,
        "timezone": "America/New_York",
        "known_measurement": {
            "schema": "monthly HVFHV Parquet; cbd_congestion_fee is optional pre-2025",
            "census_tracts": "not published in the monthly HVFHV trip schema",
        },
    },
}


@dataclass(frozen=True, slots=True)
class DataConfig:
    """Validated data-pipeline configuration.

    Relative paths are resolved by :func:`load_data_config` against ``project_root``.
    Direct construction leaves path resolution to the caller, which is convenient in
    tests and programmatic use.
    """

    source: Source = "chicago_tnp"
    mode: Mode = "sample"
    project_root: Path = Path(".")
    fixture_path: Path | None = None
    raw_dir: Path = Path("data/raw")
    clean_dir: Path = Path("data/clean")
    panel_dir: Path = Path("data/panel")
    manifest_path: Path = Path("data/manifest.json")
    diagnostics_path: Path = Path("data/diagnostics.json")
    sample_rows: int = 300
    start_datetime: str | None = "2022-01-01T00:00:00"
    end_datetime: str | None = "2022-01-01T22:00:00"
    chicago_dataset_id: str = CHICAGO_DATASET_ID
    nyc_year: int = 2024
    nyc_months: tuple[int, ...] = (1,)
    # Spread four valid-in-every-month dates across both the month and weekdays.
    nyc_sample_days: tuple[int, ...] = (1, 10, 19, 28)
    nyc_sample_hours: tuple[int, ...] = tuple(range(24))
    nyc_batch_rows: int = 100_000
    nyc_expected_rows: int | None = None
    nyc_expected_bytes: int | None = None
    nyc_expected_sha256: str | None = None
    panel_frequency: str = "15m"
    complete_panel_grid: bool = False
    partition_by: tuple[str, ...] = ("source", "service_year", "service_month")
    page_size: int = 50_000
    max_pages: int | None = None
    timeout_seconds: int = 120

    def __post_init__(self) -> None:
        source = _canonical_source(self.source)
        object.__setattr__(self, "source", source)
        if self.mode not in {"sample", "full"}:
            raise ValueError("mode must be 'sample' or 'full'")
        if self.sample_rows < 1:
            raise ValueError("sample_rows must be positive")
        if not 2009 <= self.nyc_year <= 2100:
            raise ValueError("nyc_year is outside the supported range")
        if not self.nyc_months or any(month not in range(1, 13) for month in self.nyc_months):
            raise ValueError("nyc_months must contain integers from 1 through 12")
        if len(set(self.nyc_months)) != len(self.nyc_months):
            raise ValueError("nyc_months must not contain duplicates")
        if not self.nyc_sample_days or len(set(self.nyc_sample_days)) != len(
            self.nyc_sample_days
        ):
            raise ValueError("nyc_sample_days must contain unique calendar days")
        if any(day < 1 for day in self.nyc_sample_days):
            raise ValueError("nyc_sample_days must be positive")
        if not self.nyc_sample_hours or any(
            hour not in range(24) for hour in self.nyc_sample_hours
        ):
            raise ValueError("nyc_sample_hours must contain hours from 0 through 23")
        if len(set(self.nyc_sample_hours)) != len(self.nyc_sample_hours):
            raise ValueError("nyc_sample_hours must not contain duplicates")
        if self.nyc_batch_rows < 1:
            raise ValueError("nyc_batch_rows must be positive")
        if self.nyc_expected_rows is not None and self.nyc_expected_rows < 1:
            raise ValueError("nyc_expected_rows must be positive when supplied")
        if self.nyc_expected_bytes is not None and self.nyc_expected_bytes < 1:
            raise ValueError("nyc_expected_bytes must be positive when supplied")
        if self.nyc_expected_sha256 is not None:
            normalized_sha = self.nyc_expected_sha256.lower()
            if re.fullmatch(r"[0-9a-f]{64}", normalized_sha) is None:
                raise ValueError("nyc_expected_sha256 must be a 64-character SHA-256")
            object.__setattr__(self, "nyc_expected_sha256", normalized_sha)
        has_exact_nyc_expectation = any(
            value is not None
            for value in (
                self.nyc_expected_rows,
                self.nyc_expected_bytes,
                self.nyc_expected_sha256,
            )
        )
        if has_exact_nyc_expectation and not (
            self.source == "nyc_hvfhv" and self.mode == "full"
        ):
            raise ValueError("NYC exact raw expectations are only valid in NYC full mode")
        if has_exact_nyc_expectation and len(self.nyc_months) != 1:
            raise ValueError("NYC exact raw expectations require exactly one configured month")
        if self.source == "nyc_hvfhv" and self.mode == "sample":
            if len(self.nyc_months) != 1:
                raise ValueError("NYC sample mode requires exactly one configured month")
            month = self.nyc_months[0]
            maximum_day = monthrange(self.nyc_year, month)[1]
            if any(day > maximum_day for day in self.nyc_sample_days):
                raise ValueError(
                    "nyc_sample_days contains a day outside the configured month"
                )
            strata = len(self.nyc_sample_days) * len(self.nyc_sample_hours)
            if self.sample_rows < strata:
                raise ValueError(
                    "NYC sample_rows must be at least the number of configured day-hour strata"
                )
        if self.page_size < 1 or self.page_size > 50_000:
            raise ValueError("page_size must be between 1 and Socrata's 50,000-row limit")
        if self.max_pages is not None and self.max_pages < 1:
            raise ValueError("max_pages must be positive when supplied")
        if not self.partition_by:
            raise ValueError("partition_by must contain at least one column")

    def as_serializable_dict(self) -> dict[str, Any]:
        """Return a portable JSON-safe representation for manifests.

        Paths below ``project_root`` are stored relative to it, and the root itself
        is represented by ``.``. Paths outside the project (possible in tests or an
        explicitly shared cache) remain absolute so their identity is not obscured.
        """

        payload = asdict(self)
        root = self.project_root.resolve()
        payload["project_root"] = "."
        if self.mode == "full":
            # These fields configure bounded engineering samples only.  Keeping their
            # dataclass defaults is API-compatible, but serializing numeric values in
            # a full-data manifest would falsely imply a row or stratum bound.
            payload["sample_rows"] = None
            payload["nyc_sample_days"] = None
            payload["nyc_sample_hours"] = None
        for key in (
            "fixture_path",
            "raw_dir",
            "clean_dir",
            "panel_dir",
            "manifest_path",
            "diagnostics_path",
        ):
            value = payload[key]
            if value is None:
                continue
            path = Path(value).resolve()
            try:
                payload[key] = str(path.relative_to(root))
            except ValueError:
                payload[key] = str(path)
        return _json_safe(payload)


@dataclass(frozen=True, slots=True)
class PipelineArtifacts:
    """Paths and row counts produced by :func:`run_data_pipeline`."""

    raw_files: tuple[Path, ...]
    clean_files: tuple[Path, ...]
    panel_files: tuple[Path, ...]
    od_flow_files: tuple[Path, ...]
    manifest_path: Path
    diagnostics_path: Path
    trip_rows: int
    panel_rows: int


def _canonical_source(source: str) -> Source:
    aliases = {
        "chicago": "chicago_tnp",
        "chicago_tnp": "chicago_tnp",
        "nyc": "nyc_hvfhv",
        "hvfhv": "nyc_hvfhv",
        "nyc_hvfhv": "nyc_hvfhv",
    }
    try:
        return aliases[source.lower()]  # type: ignore[return-value]
    except KeyError as exc:
        raise ValueError(f"unsupported data source: {source!r}") from exc


def load_data_config(path: PathLike) -> DataConfig:
    """Load a YAML data config and resolve all relative paths reproducibly.

    ``project_root`` is resolved relative to the YAML file.  Other relative paths
    are then resolved relative to that root, not the caller's working directory.
    Unknown keys fail fast so configuration typos cannot silently change a run.
    """

    config_path = Path(path).expanduser().resolve()
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, Mapping):
        raise TypeError("data configuration must be a YAML mapping")
    if "data" in raw:
        raw = raw["data"]
        if not isinstance(raw, Mapping):
            raise TypeError("the YAML 'data' value must be a mapping")
    values = dict(raw)
    if values.get("mode") == "full" and "sample_rows" in values:
        raise ValueError(
            "sample_rows does not bound full mode; remove it and use explicit full-data opt-in"
        )
    allowed = {field.name for field in fields(DataConfig)}
    unknown = sorted(set(values) - allowed)
    if unknown:
        raise ValueError(f"unknown data configuration keys: {', '.join(unknown)}")

    project_value = Path(values.get("project_root", ".")).expanduser()
    project_root = (
        project_value.resolve()
        if project_value.is_absolute()
        else (config_path.parent / project_value).resolve()
    )
    values["project_root"] = project_root
    for key in (
        "fixture_path",
        "raw_dir",
        "clean_dir",
        "panel_dir",
        "manifest_path",
        "diagnostics_path",
    ):
        if key not in values or values[key] is None:
            continue
        value = Path(values[key]).expanduser()
        values[key] = value if value.is_absolute() else project_root / value
    if "nyc_months" in values:
        values["nyc_months"] = tuple(int(month) for month in values["nyc_months"])
    if "nyc_sample_days" in values:
        values["nyc_sample_days"] = tuple(int(day) for day in values["nyc_sample_days"])
    if "nyc_sample_hours" in values:
        values["nyc_sample_hours"] = tuple(int(hour) for hour in values["nyc_sample_hours"])
    if "partition_by" in values:
        values["partition_by"] = tuple(str(column) for column in values["partition_by"])
    return DataConfig(**values)


def chicago_query_url(config: DataConfig) -> str:
    """Build the deterministic Socrata CSV query for a Chicago extraction."""

    clauses: list[str] = []
    if config.start_datetime:
        clauses.append(f"trip_start_timestamp >= '{config.start_datetime}'")
    if config.end_datetime:
        clauses.append(f"trip_start_timestamp <= '{config.end_datetime}'")
    query: dict[str, str | int] = {
        "$select": ",".join(CHICAGO_COLUMNS),
        "$order": "trip_start_timestamp,trip_id",
    }
    if clauses:
        query["$where"] = " and ".join(clauses)
    if config.mode == "sample":
        query["$limit"] = config.sample_rows
    return f"{CHICAGO_API_ROOT}/{config.chicago_dataset_id}.csv?{urlencode(query)}"


def chicago_sample_urls(config: DataConfig) -> tuple[str, ...]:
    """Build deterministic hourly-stratum URLs for the Chicago sample.

    The total requested rows equals ``sample_rows``.  Rows are distributed over
    twelve even-numbered local hours and ordered by ``trip_id`` within each hour,
    preventing a 300-row sample from collapsing into a single busy 15-minute cell.
    """

    if not config.start_datetime:
        raise ValueError("Chicago sample mode requires start_datetime to select a service date")
    service_date = config.start_datetime[:10]
    base, remainder = divmod(config.sample_rows, len(CHICAGO_SAMPLE_HOURS))
    urls: list[str] = []
    for index, hour in enumerate(CHICAGO_SAMPLE_HOURS):
        limit = base + (1 if index < remainder else 0)
        if limit == 0:
            continue
        timestamp = f"{service_date}T{hour:02d}:00:00"
        query: dict[str, str | int] = {
            "$select": ",".join(CHICAGO_COLUMNS),
            "$where": f"trip_start_timestamp = '{timestamp}'",
            "$order": "trip_id",
            "$limit": limit,
        }
        urls.append(f"{CHICAGO_API_ROOT}/{config.chicago_dataset_id}.csv?{urlencode(query)}")
    return tuple(urls)


def nyc_hvfhv_urls(config: DataConfig) -> tuple[str, ...]:
    """Return official TLC monthly HVFHV Parquet URLs in chronological order."""

    return tuple(
        f"{NYC_HVFHV_BASE_URL}/fhvhv_tripdata_{config.nyc_year}-{month:02d}.parquet"
        for month in sorted(config.nyc_months)
    )


def sha256_file(path: PathLike, *, chunk_size: int = 1 << 20) -> str:
    """Compute a file SHA-256 without loading it into memory."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_if_changed(source: Path, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and sha256_file(source) == sha256_file(destination):
        return destination
    temporary = destination.with_name(f".{destination.name}.tmp")
    shutil.copyfile(source, temporary)
    temporary.replace(destination)
    return destination


def _download_url(
    url: str,
    destination: Path,
    *,
    timeout: int,
    opener: Callable[..., BinaryIO] = urlopen,
) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    try:
        with opener(url, timeout=timeout) as response, temporary.open("wb") as output:
            shutil.copyfileobj(response, output, length=1 << 20)
        temporary.replace(destination)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return destination


def _download_chicago_sample(
    config: DataConfig,
    destination: Path,
    *,
    opener: Callable[..., BinaryIO],
) -> Path:
    """Download and concatenate the pinned Chicago hourly strata atomically."""

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    expected_header: bytes | None = None
    rows_written = 0
    try:
        with temporary.open("wb") as output:
            for url in chicago_sample_urls(config):
                with opener(url, timeout=config.timeout_seconds) as response:
                    payload = response.read()
                lines = payload.splitlines(keepends=True)
                if not lines:
                    raise ValueError(f"Chicago API returned an empty response for {url}")
                header = lines[0].rstrip(b"\r\n")
                if expected_header is None:
                    expected_header = header
                    output.write(header + b"\n")
                elif header != expected_header:
                    raise ValueError("Chicago API schemas differed across hourly sample strata")
                for line in lines[1:]:
                    output.write(line.rstrip(b"\r\n") + b"\n")
                    rows_written += 1
        if rows_written != config.sample_rows:
            raise ValueError(
                f"Chicago API returned {rows_written} sample rows; expected {config.sample_rows}"
            )
        temporary.replace(destination)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return destination


def _nyc_sample_filename(config: DataConfig) -> str:
    """Return a cache key that captures every NYC sample-selection dimension."""

    month = config.nyc_months[0]
    signature = json.dumps(
        {
            "year": config.nyc_year,
            "month": month,
            "days": sorted(config.nyc_sample_days),
            "hours": sorted(config.nyc_sample_hours),
            "rows": config.sample_rows,
            "strategy": "day_hour_stable_hash_v1",
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    fingerprint = hashlib.sha256(signature.encode("utf-8")).hexdigest()[:12]
    return (
        f"fhvhv_tripdata_{config.nyc_year}-{month:02d}_"
        f"stratified_{config.sample_rows}_{fingerprint}.parquet"
    )


def _nyc_sample_quotas(config: DataConfig) -> dict[tuple[int, int], int]:
    """Allocate the requested row bound exactly across configured day-hour strata."""

    strata = [
        (day, hour)
        for day in sorted(config.nyc_sample_days)
        for hour in sorted(config.nyc_sample_hours)
    ]
    base_quota, remainder = divmod(config.sample_rows, len(strata))
    return {
        stratum: base_quota + int(index < remainder)
        for index, stratum in enumerate(strata)
    }


def _validate_nyc_sample_cache(path: Path, config: DataConfig) -> None:
    """Fail closed when a cached NYC sample does not match its selection contract."""

    try:
        lazy = pl.scan_parquet(path)
        schema = lazy.collect_schema()
    except Exception as exc:
        raise ValueError(
            f"cached NYC sample is not readable; rerun with --refresh: {path}"
        ) from exc
    missing = sorted(REQUIRED_RAW_COLUMNS["nyc_hvfhv"] - set(schema.names()))
    if missing:
        raise ValueError(
            "cached NYC sample is missing required columns; rerun with --refresh: "
            + ", ".join(missing)
        )
    pickups = lazy.select("pickup_datetime").collect()
    if pickups.height != config.sample_rows:
        raise ValueError(
            f"cached NYC sample has {pickups.height} rows, expected {config.sample_rows}; "
            "rerun with --refresh"
        )
    observed = (
        pickups.with_columns(
            pl.col("pickup_datetime").dt.year().alias("year"),
            pl.col("pickup_datetime").dt.month().alias("month"),
            pl.col("pickup_datetime").dt.day().alias("day"),
            pl.col("pickup_datetime").dt.hour().alias("hour"),
        )
        .group_by("year", "month", "day", "hour")
        .len()
    )
    actual = {
        (int(row["day"]), int(row["hour"])): int(row["len"])
        for row in observed.iter_rows(named=True)
        if row["year"] == config.nyc_year and row["month"] == config.nyc_months[0]
    }
    expected = _nyc_sample_quotas(config)
    if actual != expected or observed.height != len(expected):
        raise ValueError(
            "cached NYC sample does not match the configured day-hour quotas; "
            "rerun with --refresh"
        )


def materialize_nyc_hvfhv_sample(
    config: DataConfig,
    destination: PathLike | None = None,
    *,
    source_url: str | None = None,
    connection: duckdb.DuckDBPyConnection | None = None,
) -> Path:
    """Materialize a bounded, deterministic NYC day-hour sample via range reads.

    TLC publishes monthly Parquet rather than a separate small extract. DuckDB reads
    Parquet metadata and predicate-selected row groups over HTTP. Within each
    configured day-hour stratum, a stable hash ordering selects a fixed quota. This
    avoids both storing the entire monthly file and collapsing a bounded sample into
    the upstream object's first hour. It remains a deterministic engineering sample,
    not a probability sample.

    ``source_url`` is exposed for mirrors and offline tests; production defaults to
    the first month returned by :func:`nyc_hvfhv_urls`.
    """

    if config.source != "nyc_hvfhv" or config.mode != "sample":
        raise ValueError("materialize_nyc_hvfhv_sample requires NYC mode='sample'")
    url = source_url or nyc_hvfhv_urls(config)[0]
    target = (
        Path(destination)
        if destination is not None
        else config.raw_dir / _nyc_sample_filename(config)
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        prefix=f".{target.stem}-", suffix=".parquet", dir=target.parent, delete=False
    ) as handle:
        temporary = Path(handle.name)
    temporary.unlink()
    owns_connection = connection is None
    database = connection or duckdb.connect()
    try:
        database.execute("SET threads = 1")
        database.read_parquet(url).create_view(
            "_nyc_hvfhv_sample_source", replace=True
        )
        quotas = _nyc_sample_quotas(config)
        branches: list[str] = []
        month = config.nyc_months[0]
        stable_order = (
            "hash(hvfhs_license_num, pickup_datetime, dropoff_datetime, "
            "PULocationID, DOLocationID, trip_miles, trip_time, "
            "base_passenger_fare), pickup_datetime, dropoff_datetime, "
            "PULocationID, DOLocationID"
        )
        for day in sorted(config.nyc_sample_days):
            for hour in sorted(config.nyc_sample_hours):
                quota = quotas[(day, hour)]
                start = datetime(config.nyc_year, month, day, hour)
                end = start + timedelta(hours=1)
                start_sql = start.strftime("%Y-%m-%d %H:%M:%S")
                end_sql = end.strftime("%Y-%m-%d %H:%M:%S")
                branches.append(
                    "SELECT * FROM ("
                    "SELECT * FROM _nyc_hvfhv_sample_source "
                    f"WHERE pickup_datetime >= TIMESTAMP '{start_sql}' "
                    f"AND pickup_datetime < TIMESTAMP '{end_sql}' "
                    f"ORDER BY {stable_order} LIMIT {quota}"
                    ")"
                )
        sample = database.sql(" UNION ALL ".join(branches)).order(
            f"pickup_datetime, {stable_order}"
        )
        sample.write_parquet(str(temporary), compression="zstd")
        _validate_nyc_sample_cache(temporary, config)
        temporary.replace(target)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    finally:
        if owns_connection:
            database.close()
    return target


def download_sample(
    config: DataConfig | PathLike,
    *,
    refresh: bool = False,
    opener: Callable[..., BinaryIO] = urlopen,
) -> Path:
    """Materialize one sample raw file, using the committed fixture by default.

    For the default Chicago sample, ``refresh=False`` performs no network access
    and copies the immutable fixture into ``raw_dir``.  ``refresh=True`` explicitly
    reruns the pinned Socrata query.  NYC does not publish a small fixture; its
    sample mode downloads one configured monthly Parquet and normalization applies
    ``sample_rows`` deterministically.
    """

    cfg = load_data_config(config) if not isinstance(config, DataConfig) else config
    if cfg.mode != "sample":
        raise ValueError("download_sample requires mode='sample'")
    cfg.raw_dir.mkdir(parents=True, exist_ok=True)

    if cfg.source == "chicago_tnp":
        destination = cfg.raw_dir / "chicago_tnp_sample.csv"
        if not refresh:
            if cfg.fixture_path is None:
                raise FileNotFoundError("sample config has no offline fixture_path")
            if not cfg.fixture_path.exists():
                raise FileNotFoundError(f"Chicago fixture does not exist: {cfg.fixture_path}")
            return _copy_if_changed(cfg.fixture_path, destination)
        return _download_chicago_sample(cfg, destination, opener=opener)

    destination = cfg.raw_dir / _nyc_sample_filename(cfg)
    if destination.exists() and not refresh:
        _validate_nyc_sample_cache(destination, cfg)
        return destination
    return materialize_nyc_hvfhv_sample(cfg, destination)


def _download_chicago_full(
    config: DataConfig,
    *,
    refresh: bool,
    opener: Callable[..., BinaryIO],
) -> tuple[Path, ...]:
    if not config.start_datetime or not config.end_datetime:
        raise ValueError(
            "Chicago full mode requires start_datetime and end_datetime; "
            "an unbounded 300M-row request is intentionally refused"
        )
    outputs: list[Path] = []
    page = 0
    while config.max_pages is None or page < config.max_pages:
        query_url = chicago_query_url(config)
        separator = "&" if "?" in query_url else "?"
        url = (
            f"{query_url}{separator}"
            f"{urlencode({'$limit': config.page_size, '$offset': page * config.page_size})}"
        )
        destination = config.raw_dir / f"chicago_tnp_page_{page:05d}.csv"
        if refresh or not destination.exists():
            _download_url(url, destination, timeout=config.timeout_seconds, opener=opener)
        with destination.open("r", encoding="utf-8", newline="") as handle:
            row_count = max(sum(1 for _ in csv.reader(handle)) - 1, 0)
        if row_count == 0:
            destination.unlink(missing_ok=True)
            break
        outputs.append(destination)
        page += 1
        if row_count < config.page_size:
            break
    return tuple(outputs)


def download_data(
    config: DataConfig | PathLike,
    *,
    refresh: bool = False,
    opener: Callable[..., BinaryIO] = urlopen,
) -> tuple[Path, ...]:
    """Download or materialize all raw files selected by a data config."""

    cfg = load_data_config(config) if not isinstance(config, DataConfig) else config
    cfg.raw_dir.mkdir(parents=True, exist_ok=True)
    if cfg.mode == "sample":
        return (download_sample(cfg, refresh=refresh, opener=opener),)
    if cfg.source == "chicago_tnp":
        return _download_chicago_full(cfg, refresh=refresh, opener=opener)

    outputs: list[Path] = []
    for url in nyc_hvfhv_urls(cfg):
        destination = cfg.raw_dir / Path(url).name
        if refresh or not destination.exists():
            _download_url(url, destination, timeout=cfg.timeout_seconds, opener=opener)
        outputs.append(destination)
    return tuple(outputs)


def _read_frame(data: FrameInput) -> pl.DataFrame:
    if isinstance(data, pl.DataFrame):
        return data.clone()
    if isinstance(data, (str, os.PathLike)):
        paths = (Path(data),)
    else:
        paths = tuple(Path(path) for path in data)
    if not paths:
        raise ValueError("at least one input file is required")
    frames: list[pl.DataFrame] = []
    for path in paths:
        suffix = path.suffix.lower()
        if suffix in {".parquet", ".pq"}:
            frames.append(pl.read_parquet(path))
        elif suffix in {".csv", ".csv.gz"} or path.name.endswith(".csv.gz"):
            frames.append(
                pl.read_csv(
                    path,
                    null_values=["", "null", "NULL"],
                    try_parse_dates=False,
                    infer_schema_length=10_000,
                )
            )
        else:
            raise ValueError(f"unsupported input format: {path}")
    return pl.concat(frames, how="diagonal_relaxed") if len(frames) > 1 else frames[0]


def _validate_raw_columns(frame: pl.DataFrame, source: Source) -> None:
    missing = sorted(REQUIRED_RAW_COLUMNS[source] - set(frame.columns))
    if missing:
        raise ValueError(f"{source} raw data are missing required columns: {', '.join(missing)}")


def _ensure_columns(frame: pl.DataFrame, schema: pl.Schema) -> pl.DataFrame:
    additions = [
        pl.lit(None, dtype=dtype).alias(name)
        for name, dtype in schema.items()
        if name not in frame.columns
    ]
    return frame.with_columns(additions) if additions else frame


def _datetime_expr(frame: pl.DataFrame, name: str) -> pl.Expr:
    dtype = frame.schema[name]
    if dtype == pl.Date or isinstance(dtype, pl.Datetime):
        return pl.col(name).cast(pl.Datetime("us"), strict=False)
    return pl.col(name).cast(pl.String).str.to_datetime(strict=False).cast(pl.Datetime("us"))


def _string_expr(name: str) -> pl.Expr:
    return pl.col(name).cast(pl.String, strict=False).str.strip_chars().replace("", None)


def _zone_expr(name: str) -> pl.Expr:
    return pl.col(name).cast(pl.Int64, strict=False).cast(pl.String)


def _boolean_expr(name: str) -> pl.Expr:
    normalized = pl.col(name).cast(pl.String, strict=False).str.to_lowercase().str.strip_chars()
    return (
        pl.when(normalized.is_in(["true", "t", "1", "yes", "y"]))
        .then(pl.lit(True))
        .when(normalized.is_in(["false", "f", "0", "no", "n"]))
        .then(pl.lit(False))
        .otherwise(pl.lit(None, dtype=pl.Boolean))
    )


def _flag_expr(name: str) -> pl.Expr:
    normalized = pl.col(name).cast(pl.String, strict=False).str.to_uppercase().str.strip_chars()
    return (
        pl.when(normalized == "Y")
        .then(pl.lit(True))
        .when(normalized == "N")
        .then(pl.lit(False))
        .otherwise(pl.lit(None, dtype=pl.Boolean))
    )


def _utc_expr(name: str, timezone: str) -> pl.Expr:
    return (
        pl.col(name)
        .dt.replace_time_zone(timezone, ambiguous="null", non_existent="null")
        .dt.convert_time_zone("UTC")
    )


def _grid_15m_expr(name: str) -> pl.Expr:
    return (
        (pl.col(name).dt.minute() % 15 == 0)
        & (pl.col(name).dt.second() == 0)
        & (pl.col(name).dt.millisecond() == 0)
    )


def _normalize_chicago(frame: pl.DataFrame) -> pl.DataFrame:
    frame = _ensure_columns(frame, CHICAGO_RAW_SCHEMA)
    frame = frame.with_columns(
        _datetime_expr(frame, "trip_start_timestamp").alias("_pickup_local"),
        _datetime_expr(frame, "trip_end_timestamp").alias("_dropoff_local"),
        _string_expr("pickup_census_tract").alias("_pickup_tract"),
        _string_expr("dropoff_census_tract").alias("_dropoff_tract"),
        _zone_expr("pickup_community_area").alias("_pickup_zone"),
        _zone_expr("dropoff_community_area").alias("_dropoff_zone"),
        pl.col("fare").cast(pl.Float64, strict=False).alias("_fare"),
        pl.col("tip").cast(pl.Float64, strict=False).alias("_tips"),
        pl.col("additional_charges").cast(pl.Float64, strict=False).alias("_additional"),
        pl.col("trips_pooled").cast(pl.Int64, strict=False).alias("_trips_pooled"),
        _boolean_expr("shared_trip_authorized").alias("_shared_requested"),
    )
    result = frame.select(
        pl.lit("chicago_tnp").alias("source"),
        pl.lit(CHICAGO_DATASET_ID).alias("source_dataset_id"),
        _string_expr("trip_id").alias("trip_id"),
        pl.lit(False).alias("record_id_is_surrogate"),
        pl.lit(None, dtype=pl.String).alias("provider_id"),
        pl.lit(None, dtype=pl.String).alias("dispatching_base_id"),
        pl.lit(None, dtype=pl.Datetime("us")).alias("request_datetime"),
        pl.col("_pickup_local").alias("pickup_datetime"),
        pl.col("_dropoff_local").alias("dropoff_datetime"),
        _utc_expr("_pickup_local", "America/Chicago").alias("pickup_datetime_utc"),
        _utc_expr("_dropoff_local", "America/Chicago").alias("dropoff_datetime_utc"),
        pl.lit("America/Chicago").alias("source_timezone"),
        pl.col("_pickup_local").dt.date().alias("service_date"),
        pl.col("_pickup_local").dt.year().cast(pl.Int32).alias("service_year"),
        pl.col("_pickup_local").dt.month().cast(pl.Int8).alias("service_month"),
        pl.col("_pickup_local").dt.weekday().cast(pl.Int8).alias("service_day_of_week"),
        pl.col("_pickup_zone").alias("pickup_zone_id"),
        pl.col("_dropoff_zone").alias("dropoff_zone_id"),
        pl.lit("chicago_community_area").alias("zone_type"),
        pl.col("_pickup_tract").alias("pickup_census_tract"),
        pl.col("_dropoff_tract").alias("dropoff_census_tract"),
        pl.col("trip_seconds").cast(pl.Int64, strict=False).alias("trip_seconds"),
        pl.col("trip_miles").cast(pl.Float64, strict=False).alias("trip_miles"),
        pl.col("_fare").alias("fare"),
        pl.col("_tips").alias("tips"),
        pl.lit(None, dtype=pl.Float64).alias("tolls"),
        pl.lit(None, dtype=pl.Float64).alias("taxes_and_surcharges"),
        pl.col("_additional").alias("additional_charges"),
        pl.col("trip_total").cast(pl.Float64, strict=False).alias("total_amount"),
        pl.lit(None, dtype=pl.Float64).alias("driver_pay"),
        pl.lit(None, dtype=pl.Float64).alias("airport_fee"),
        pl.col("_shared_requested").alias("shared_requested"),
        (pl.col("_trips_pooled") > 1).alias("shared_matched"),
        pl.col("_trips_pooled").alias("trips_pooled"),
        (
            pl.col("_pickup_zone").is_in(["56", "76"])
            | pl.col("_dropoff_zone").is_in(["56", "76"])
        ).alias("airport_trip"),
        pl.col("_pickup_zone").is_null().alias("pickup_zone_missing"),
        pl.col("_dropoff_zone").is_null().alias("dropoff_zone_missing"),
        pl.col("_pickup_tract").is_null().alias(
            "pickup_census_tract_missing_or_suppressed"
        ),
        pl.col("_dropoff_tract").is_null().alias(
            "dropoff_census_tract_missing_or_suppressed"
        ),
        pl.lit(15, dtype=pl.Int16).alias("reported_timestamp_rounding_minutes"),
        pl.lit(2.5).alias("reported_fare_rounding_increment"),
        pl.lit(1.0).alias("reported_tip_rounding_increment"),
        _grid_15m_expr("_pickup_local").alias("pickup_on_15_minute_grid"),
        (((pl.col("_fare") / 2.5).round() * 2.5 - pl.col("_fare")).abs() <= 1e-8).alias(
            "fare_on_declared_grid"
        ),
    )
    return result.cast(CLEAN_TRIP_SCHEMA, strict=False)


def _normalize_nyc(
    frame: pl.DataFrame,
    *,
    source_row_offset: int = 0,
) -> pl.DataFrame:
    """Normalize one NYC frame using a caller-supplied global source-row offset.

    The offset is zero for the public eager API.  The full-month streaming path
    advances it across every record batch and raw file so otherwise identical rows
    cannot receive the same surrogate ``trip_id`` merely because a new batch began.
    """

    frame = _ensure_columns(frame, NYC_HVFHV_RAW_SCHEMA).with_row_index(
        "_source_row", offset=source_row_offset
    )
    frame = frame.with_columns(
        _datetime_expr(frame, "request_datetime").alias("_request_local"),
        _datetime_expr(frame, "pickup_datetime").alias("_pickup_local"),
        _datetime_expr(frame, "dropoff_datetime").alias("_dropoff_local"),
        _zone_expr("PULocationID").alias("_pickup_zone"),
        _zone_expr("DOLocationID").alias("_dropoff_zone"),
        pl.col("base_passenger_fare").cast(pl.Float64, strict=False).alias("_fare"),
        pl.col("tips").cast(pl.Float64, strict=False).alias("_tips"),
        pl.col("tolls").cast(pl.Float64, strict=False).alias("_tolls"),
        pl.col("airport_fee").cast(pl.Float64, strict=False).alias("_airport_fee"),
        pl.col("cbd_congestion_fee").cast(pl.Float64, strict=False).alias("_cbd_fee"),
        _flag_expr("shared_request_flag").alias("_shared_requested"),
        _flag_expr("shared_match_flag").alias("_shared_matched"),
    )
    taxes = pl.sum_horizontal(
        pl.col("bcf").cast(pl.Float64, strict=False).fill_null(0.0),
        pl.col("sales_tax").cast(pl.Float64, strict=False).fill_null(0.0),
        pl.col("congestion_surcharge").cast(pl.Float64, strict=False).fill_null(0.0),
        pl.col("_cbd_fee").fill_null(0.0),
    )
    additional = taxes + pl.col("_tolls").fill_null(0.0) + pl.col("_airport_fee").fill_null(0.0)
    trip_id = pl.concat_str(
        [
            pl.lit("nyc_hvfhv"),
            _string_expr("hvfhs_license_num").fill_null("unknown"),
            pl.col("_pickup_local").cast(pl.String),
            pl.col("_dropoff_local").cast(pl.String),
            pl.col("_pickup_zone").fill_null("unknown"),
            pl.col("_dropoff_zone").fill_null("unknown"),
            pl.col("_source_row").cast(pl.String),
        ],
        separator=":",
    )
    result = frame.select(
        pl.lit("nyc_hvfhv").alias("source"),
        pl.lit(f"fhvhv-{SCHEMA_VERSION}").alias("source_dataset_id"),
        trip_id.alias("trip_id"),
        pl.lit(True).alias("record_id_is_surrogate"),
        _string_expr("hvfhs_license_num").alias("provider_id"),
        _string_expr("dispatching_base_num").alias("dispatching_base_id"),
        pl.col("_request_local").alias("request_datetime"),
        pl.col("_pickup_local").alias("pickup_datetime"),
        pl.col("_dropoff_local").alias("dropoff_datetime"),
        _utc_expr("_pickup_local", "America/New_York").alias("pickup_datetime_utc"),
        _utc_expr("_dropoff_local", "America/New_York").alias("dropoff_datetime_utc"),
        pl.lit("America/New_York").alias("source_timezone"),
        pl.col("_pickup_local").dt.date().alias("service_date"),
        pl.col("_pickup_local").dt.year().cast(pl.Int32).alias("service_year"),
        pl.col("_pickup_local").dt.month().cast(pl.Int8).alias("service_month"),
        pl.col("_pickup_local").dt.weekday().cast(pl.Int8).alias("service_day_of_week"),
        pl.col("_pickup_zone").alias("pickup_zone_id"),
        pl.col("_dropoff_zone").alias("dropoff_zone_id"),
        pl.lit("nyc_taxi_zone").alias("zone_type"),
        pl.lit(None, dtype=pl.String).alias("pickup_census_tract"),
        pl.lit(None, dtype=pl.String).alias("dropoff_census_tract"),
        pl.col("trip_time").cast(pl.Int64, strict=False).alias("trip_seconds"),
        pl.col("trip_miles").cast(pl.Float64, strict=False).alias("trip_miles"),
        pl.col("_fare").alias("fare"),
        pl.col("_tips").alias("tips"),
        pl.col("_tolls").alias("tolls"),
        taxes.alias("taxes_and_surcharges"),
        additional.alias("additional_charges"),
        (
            pl.col("_fare").fill_null(0.0)
            + pl.col("_tips").fill_null(0.0)
            + additional
        ).alias("total_amount"),
        pl.col("driver_pay").cast(pl.Float64, strict=False).alias("driver_pay"),
        pl.col("_airport_fee").alias("airport_fee"),
        pl.col("_shared_requested").alias("shared_requested"),
        pl.col("_shared_matched").alias("shared_matched"),
        pl.lit(None, dtype=pl.Int64).alias("trips_pooled"),
        (
            (pl.col("_airport_fee").fill_null(0.0) > 0)
            | pl.col("_pickup_zone").is_in(["1", "132", "138"])
            | pl.col("_dropoff_zone").is_in(["1", "132", "138"])
        ).alias("airport_trip"),
        pl.col("_pickup_zone").is_null().alias("pickup_zone_missing"),
        pl.col("_dropoff_zone").is_null().alias("dropoff_zone_missing"),
        pl.lit(None, dtype=pl.Boolean).alias(
            "pickup_census_tract_missing_or_suppressed"
        ),
        pl.lit(None, dtype=pl.Boolean).alias(
            "dropoff_census_tract_missing_or_suppressed"
        ),
        pl.lit(None, dtype=pl.Int16).alias("reported_timestamp_rounding_minutes"),
        pl.lit(None, dtype=pl.Float64).alias("reported_fare_rounding_increment"),
        pl.lit(None, dtype=pl.Float64).alias("reported_tip_rounding_increment"),
        _grid_15m_expr("_pickup_local").alias("pickup_on_15_minute_grid"),
        pl.lit(None, dtype=pl.Boolean).alias("fare_on_declared_grid"),
    )
    return result.cast(CLEAN_TRIP_SCHEMA, strict=False)


def normalize_trips(
    data: FrameInput,
    source: str | None = None,
    *,
    config: DataConfig | PathLike | None = None,
) -> pl.DataFrame:
    """Normalize Chicago TNP or NYC TLC HVFHV records to ``CLEAN_TRIP_SCHEMA``.

    Sample mode takes the first ``sample_rows`` after deterministic source ordering.
    It never random-samples, so rerunning the same pinned input yields identical rows.
    Local naive timestamps are retained alongside UTC timestamps.  Ambiguous or
    nonexistent daylight-saving local times produce null UTC values rather than an
    invented offset; the local value remains available for panel construction.
    """

    cfg: DataConfig | None
    if config is None:
        cfg = None
    else:
        cfg = load_data_config(config) if not isinstance(config, DataConfig) else config
    source_name = _canonical_source(source or (cfg.source if cfg else ""))
    frame = _read_frame(data)
    _validate_raw_columns(frame, source_name)
    if source_name == "chicago_tnp":
        frame = frame.sort(["trip_start_timestamp", "trip_id"])
    else:
        frame = frame.sort(["pickup_datetime", "dropoff_datetime"])
    if cfg is not None and cfg.mode == "sample":
        frame = frame.head(cfg.sample_rows)
    return _normalize_chicago(frame) if source_name == "chicago_tnp" else _normalize_nyc(frame)


def validate_clean_schema(frame: pl.DataFrame) -> None:
    """Raise when columns or dtypes diverge from the canonical cleaned contract."""

    missing = sorted(set(CLEAN_TRIP_SCHEMA.names()) - set(frame.columns))
    if missing:
        raise ValueError(f"cleaned trips are missing columns: {', '.join(missing)}")
    mismatches = {
        name: {"expected": str(dtype), "actual": str(frame.schema[name])}
        for name, dtype in CLEAN_TRIP_SCHEMA.items()
        if frame.schema[name] != dtype
    }
    if mismatches:
        raise TypeError(f"cleaned trip schema mismatches: {mismatches}")


def _true_count(frame: pl.DataFrame, column: str) -> int:
    return int(frame.select(pl.col(column).fill_null(False).sum()).item() or 0)


def _known_rate(frame: pl.DataFrame, column: str) -> float | None:
    known = frame.select(pl.col(column).drop_nulls().len()).item()
    if not known:
        return None
    return float(frame.select(pl.col(column).drop_nulls().mean()).item())


def data_quality_diagnostics(frame: pl.DataFrame) -> dict[str, Any]:
    """Compute JSON-safe missingness, suppression, rounding, and validity checks."""

    validate_clean_schema(frame)
    rows = frame.height
    nulls = frame.null_count().row(0, named=True)
    missingness = {
        column: {
            "count": int(nulls[column]),
            "rate": (float(nulls[column]) / rows if rows else None),
        }
        for column in frame.columns
    }
    sources = sorted(frame.get_column("source").drop_nulls().unique().to_list())
    pickup_indicator = "pickup_census_tract_missing_or_suppressed"
    dropoff_indicator = "dropoff_census_tract_missing_or_suppressed"
    pickup_suppressed = _true_count(frame, pickup_indicator)
    dropoff_suppressed = _true_count(frame, dropoff_indicator)
    pickup_known = rows - int(nulls[pickup_indicator])
    dropoff_known = rows - int(nulls[dropoff_indicator])
    trip_ids = frame.get_column("trip_id")
    diagnostics = {
        "schema_version": SCHEMA_VERSION,
        "row_count": rows,
        "sources": sources,
        "missingness": missingness,
        "suppression_or_nonreporting": {
            "pickup_census_tract_count": pickup_suppressed,
            "pickup_census_tract_rate": (
                pickup_suppressed / pickup_known if pickup_known else None
            ),
            "pickup_indicator_known_count": pickup_known,
            "pickup_indicator_status": (
                "available"
                if pickup_known == rows
                else "unavailable"
                if not pickup_known
                else "partial"
            ),
            "dropoff_census_tract_count": dropoff_suppressed,
            "dropoff_census_tract_rate": (
                dropoff_suppressed / dropoff_known if dropoff_known else None
            ),
            "dropoff_indicator_known_count": dropoff_known,
            "dropoff_indicator_status": (
                "available"
                if dropoff_known == rows
                else "unavailable"
                if not dropoff_known
                else "partial"
            ),
            "interpretation": (
                "Null availability indicators mean the source does not report the field; they "
                "must not be recoded as unsuppressed. Chicago blank census tracts may be "
                "privacy-suppressed or outside Chicago, and no record-level mechanism is claimed."
            ),
        },
        "rounding": {
            "pickup_on_15_minute_grid_rate": _known_rate(
                frame, "pickup_on_15_minute_grid"
            ),
            "fare_on_declared_grid_rate": _known_rate(frame, "fare_on_declared_grid"),
            "declared_timestamp_rounding_minutes": sorted(
                int(value)
                for value in frame.get_column("reported_timestamp_rounding_minutes")
                .drop_nulls()
                .unique()
                .to_list()
            ),
            "declared_fare_rounding_increments": sorted(
                float(value)
                for value in frame.get_column("reported_fare_rounding_increment")
                .drop_nulls()
                .unique()
                .to_list()
            ),
            "interpretation": (
                "Grid conformance verifies reported-value patterns; it does not recover "
                "latent exact fares or timestamps."
            ),
        },
        "validity": {
            "duplicate_trip_id_count": rows - trip_ids.n_unique(),
            "missing_trip_id_count": trip_ids.null_count(),
            "nonpositive_trip_seconds_count": int(
                frame.select((pl.col("trip_seconds") <= 0).fill_null(False).sum()).item() or 0
            ),
            "negative_trip_miles_count": int(
                frame.select((pl.col("trip_miles") < 0).fill_null(False).sum()).item() or 0
            ),
            "negative_fare_count": int(
                frame.select((pl.col("fare") < 0).fill_null(False).sum()).item() or 0
            ),
            "utc_conversion_null_count": int(
                frame.select(pl.col("pickup_datetime_utc").is_null().sum()).item() or 0
            ),
        },
        "source_caveats": {source: SOURCE_METADATA[source]["known_measurement"] for source in sources},
    }
    return _json_safe(diagnostics)


def build_zone_time_panel(
    trips: pl.DataFrame,
    *,
    frequency: str = "15m",
    complete_grid: bool = False,
) -> pl.DataFrame:
    """Aggregate cleaned trips to pickup-zone × local-time cells.

    ``avg_fare`` is descriptive and inherits source rounding/selection.  It must not
    be interpreted as an exogenous price or a causal demand elasticity.  OD structure
    appears as outbound counts and distinct destinations; use
    :func:`build_od_flow_panel` for the full origin-destination panel.
    """

    validate_clean_schema(trips)
    usable = trips.filter(pl.col("pickup_datetime").is_not_null()).with_columns(
        pl.col("pickup_datetime").dt.truncate(frequency).alias("time_bin"),
        (
            pl.col("pickup_zone_id").is_not_null()
            & pl.col("dropoff_zone_id").is_not_null()
        ).alias("_od_pair_observed"),
        pl.col("pickup_zone_id").fill_null(MISSING_ZONE_ID),
        pl.col("dropoff_zone_id").fill_null(MISSING_ZONE_ID),
    )
    panel = (
        usable.group_by(["source", "zone_type", "pickup_zone_id", "time_bin"])
        .agg(
            pl.len().cast(pl.Int64).alias("trip_count"),
            pl.when(pl.col("_od_pair_observed").sum() > 0)
            .then(
                pl.col("dropoff_zone_id")
                .filter(pl.col("_od_pair_observed"))
                .n_unique()
                .cast(pl.Int64)
            )
            .otherwise(None)
            .alias("distinct_dropoff_zones"),
            pl.when(pl.col("_od_pair_observed").sum() > 0)
            .then(
                (pl.col("pickup_zone_id") != pl.col("dropoff_zone_id"))
                .filter(pl.col("_od_pair_observed"))
                .sum()
                .cast(pl.Int64)
            )
            .otherwise(None)
            .alias("outbound_trip_count"),
            pl.when(pl.col("_od_pair_observed"))
            .then(pl.col("pickup_zone_id") == pl.col("dropoff_zone_id"))
            .otherwise(None)
            .mean()
            .alias("intra_zone_share"),
            pl.col("_od_pair_observed").sum().cast(pl.Int64).alias("od_pair_observed_count"),
            pl.col("_od_pair_observed").mean().alias("od_pair_observed_share"),
            pl.col("fare").mean().alias("avg_fare"),
            pl.col("fare").median().alias("median_fare"),
            pl.col("fare").sum().alias("total_fare"),
            pl.col("trip_seconds").mean().alias("avg_trip_seconds"),
            pl.col("trip_miles").mean().alias("avg_trip_miles"),
            pl.col("trip_miles").sum().alias("total_trip_miles"),
            pl.col("shared_requested").mean().alias("shared_requested_share"),
            pl.col("shared_matched").mean().alias("shared_matched_share"),
            pl.col("airport_trip").mean().alias("airport_trip_share"),
            pl.col("pickup_census_tract_missing_or_suppressed")
            .mean()
            .alias("pickup_geography_missing_or_suppressed_share"),
            pl.col("reported_timestamp_rounding_minutes")
            .is_not_null()
            .mean()
            .alias("timestamp_rounded_measurement_share"),
            pl.col("reported_fare_rounding_increment")
            .is_not_null()
            .mean()
            .alias("fare_rounded_measurement_share"),
        )
        .rename({"pickup_zone_id": "zone_id"})
        .with_columns(
            pl.col("time_bin").dt.date().alias("service_date"),
            pl.col("time_bin").dt.year().cast(pl.Int32).alias("year"),
            pl.col("time_bin").dt.month().cast(pl.Int8).alias("month"),
            pl.col("time_bin").dt.weekday().cast(pl.Int8).alias("day_of_week"),
            pl.col("time_bin").dt.hour().cast(pl.Int8).alias("hour"),
            pl.col("time_bin").dt.minute().cast(pl.Int8).alias("minute"),
            (pl.col("time_bin").dt.weekday() >= 6).alias("is_weekend"),
            pl.lit(f"pickup_zone_x_{frequency}").alias("panel_grain"),
            pl.lit("descriptive_real_data").alias("evidence_label"),
        )
        .sort(["source", "zone_type", "zone_id", "time_bin"])
    )
    return _complete_zone_time_grid(panel, frequency) if complete_grid else panel


def _complete_zone_time_grid(panel: pl.DataFrame, frequency: str) -> pl.DataFrame:
    if panel.is_empty():
        return panel
    frames: list[pl.DataFrame] = []
    for key, group in panel.partition_by(["source", "zone_type"], as_dict=True).items():
        source, zone_type = key if isinstance(key, tuple) else (key, "unknown")
        observed = group.with_columns(pl.lit(True).alias("_observed_cell"))
        times = pl.DataFrame(
            {
                "time_bin": pl.datetime_range(
                    observed.get_column("time_bin").min(),
                    observed.get_column("time_bin").max(),
                    interval=frequency,
                    eager=True,
                )
            }
        )
        zones = observed.select("zone_id").unique().sort("zone_id")
        grid = (
            zones.join(times, how="cross")
            .with_columns(
                pl.lit(source).alias("source"),
                pl.lit(zone_type).alias("zone_type"),
            )
            .join(
                observed,
                on=["source", "zone_type", "zone_id", "time_bin"],
                how="left",
            )
        )
        # A synthesized cell is a known zero-trip cell. An observed trip cell whose
        # destinations are all unavailable is different: its OD summaries remain
        # unknown instead of being silently recoded to zero.
        synthetic_zero_columns = [
            "trip_count",
            "distinct_dropoff_zones",
            "outbound_trip_count",
            "od_pair_observed_count",
            "total_fare",
            "total_trip_miles",
        ]
        grid = (
            grid.with_columns(
                *[
                    pl.when(pl.col("_observed_cell").is_null())
                    .then(0)
                    .otherwise(pl.col(column))
                    .alias(column)
                    for column in synthetic_zero_columns
                ],
                pl.col("time_bin").dt.date().alias("service_date"),
                pl.col("time_bin").dt.year().cast(pl.Int32).alias("year"),
                pl.col("time_bin").dt.month().cast(pl.Int8).alias("month"),
                pl.col("time_bin").dt.weekday().cast(pl.Int8).alias("day_of_week"),
                pl.col("time_bin").dt.hour().cast(pl.Int8).alias("hour"),
                pl.col("time_bin").dt.minute().cast(pl.Int8).alias("minute"),
                (pl.col("time_bin").dt.weekday() >= 6).alias("is_weekend"),
                pl.lit(f"pickup_zone_x_{frequency}").alias("panel_grain"),
                pl.lit("descriptive_real_data").alias("evidence_label"),
            ).drop("_observed_cell")
        )
        frames.append(grid)
    return pl.concat(frames, how="diagonal_relaxed").sort(
        ["source", "zone_type", "zone_id", "time_bin"]
    )


def build_od_flow_panel(trips: pl.DataFrame, *, frequency: str = "15m") -> pl.DataFrame:
    """Build origin × destination × local-time trip-flow counts."""

    validate_clean_schema(trips)
    return (
        trips.filter(pl.col("pickup_datetime").is_not_null())
        .with_columns(
            pl.col("pickup_datetime").dt.truncate(frequency).alias("time_bin"),
            pl.col("pickup_zone_id").fill_null(MISSING_ZONE_ID),
            pl.col("dropoff_zone_id").fill_null(MISSING_ZONE_ID),
        )
        .group_by(
            ["source", "zone_type", "pickup_zone_id", "dropoff_zone_id", "time_bin"]
        )
        .agg(
            pl.len().cast(pl.Int64).alias("trip_count"),
            pl.col("fare").mean().alias("avg_fare"),
            pl.col("trip_miles").mean().alias("avg_trip_miles"),
        )
        .rename(
            {"pickup_zone_id": "origin_zone_id", "dropoff_zone_id": "destination_zone_id"}
        )
        .with_columns(
            pl.lit("descriptive_real_data").alias("evidence_label"),
            pl.col("time_bin").dt.date().alias("service_date"),
            pl.col("time_bin").dt.year().cast(pl.Int32).alias("year"),
            pl.col("time_bin").dt.month().cast(pl.Int8).alias("month"),
        )
        .sort(["source", "origin_zone_id", "destination_zone_id", "time_bin"])
    )


def _partition_value(value: Any) -> str:
    if value is None:
        return "__HIVE_DEFAULT_PARTITION__"
    rendered = str(value)
    return "".join(character if character.isalnum() or character in "-_." else "_" for character in rendered)


def write_partitioned_parquet(
    frame: pl.DataFrame,
    output_dir: PathLike,
    *,
    partition_by: Sequence[str] = ("source", "service_year", "service_month"),
    basename: str = "part-00000.parquet",
    overwrite: bool = True,
) -> tuple[Path, ...]:
    """Write a deterministic Hive-style Parquet dataset with atomic part writes."""

    if not basename.endswith(".parquet") or Path(basename).name != basename:
        raise ValueError("basename must be a simple .parquet filename")
    missing = sorted(set(partition_by) - set(frame.columns))
    if missing:
        raise ValueError(f"partition columns are missing: {', '.join(missing)}")
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    if frame.is_empty():
        if overwrite:
            for stale in root.rglob("*.parquet"):
                stale.unlink()
        return ()
    groups = frame.partition_by(list(partition_by), as_dict=True, maintain_order=True)
    outputs: list[Path] = []
    for raw_key, partition in sorted(groups.items(), key=lambda item: str(item[0])):
        key = raw_key if isinstance(raw_key, tuple) else (raw_key,)
        directory = root
        for column, value in zip(partition_by, key, strict=True):
            directory = directory / f"{column}={_partition_value(value)}"
        directory.mkdir(parents=True, exist_ok=True)
        destination = directory / basename
        if destination.exists() and not overwrite:
            raise FileExistsError(destination)
        sort_columns = [
            column
            for column in ("pickup_datetime", "time_bin", "zone_id", "trip_id")
            if column in partition.columns
        ]
        payload = partition.sort(sort_columns) if sort_columns else partition
        with tempfile.NamedTemporaryFile(
            prefix=f".{destination.stem}-", suffix=".parquet", dir=directory, delete=False
        ) as handle:
            temporary = Path(handle.name)
        try:
            payload.write_parquet(temporary, compression="zstd", statistics=True)
            temporary.replace(destination)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
        outputs.append(destination)
    if overwrite:
        expected = {path.resolve() for path in outputs}
        for stale in root.rglob("*.parquet"):
            if stale.resolve() not in expected:
                stale.unlink()
        for directory in sorted(
            (path for path in root.rglob("*") if path.is_dir()),
            key=lambda path: len(path.parts),
            reverse=True,
        ):
            try:
                directory.rmdir()
            except OSError:
                pass
    return tuple(sorted(outputs))


def read_partitioned_parquet(path: PathLike) -> pl.DataFrame:
    """Read all Parquet parts below a partitioned-dataset directory."""

    root = Path(path)
    files = sorted(root.rglob("*.parquet"))
    if not files:
        raise FileNotFoundError(f"no Parquet parts under {root}")
    return pl.concat([pl.read_parquet(file) for file in files], how="diagonal_relaxed")


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(item) for item in value]
    return value


def _atomic_json(payload: Mapping[str, Any], destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        prefix=f".{destination.stem}-",
        suffix=".json",
        dir=destination.parent,
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        json.dump(_json_safe(payload), handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
    temporary.replace(destination)
    return destination


def write_diagnostics(frame: pl.DataFrame, destination: PathLike) -> Path:
    """Write :func:`data_quality_diagnostics` as strict JSON."""

    return _atomic_json(data_quality_diagnostics(frame), Path(destination))


def write_manifest(
    files: Iterable[PathLike],
    destination: PathLike,
    *,
    config: DataConfig | None = None,
    metadata: Mapping[str, Any] | None = None,
    root: PathLike | None = None,
) -> Path:
    """Write an input/output manifest with byte sizes and SHA-256 checksums."""

    paths = tuple(sorted({Path(path).resolve() for path in files}))
    relative_root = Path(root).resolve() if root is not None else None
    entries: list[dict[str, Any]] = []
    for path in paths:
        if not path.is_file():
            raise FileNotFoundError(path)
        try:
            rendered_path = str(path.relative_to(relative_root)) if relative_root else str(path)
        except ValueError:
            rendered_path = str(path)
        entries.append(
            {
                "path": rendered_path,
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "files": entries,
    }
    if config is not None:
        payload["config"] = config.as_serializable_dict()
        payload["source_metadata"] = SOURCE_METADATA[config.source]
        payload["source_urls"] = (
            list(chicago_sample_urls(config))
            if config.source == "chicago_tnp" and config.mode == "sample"
            else [chicago_query_url(config)]
            if config.source == "chicago_tnp"
            else list(nyc_hvfhv_urls(config))
        )
    if metadata:
        payload["metadata"] = _json_safe(metadata)
    return _atomic_json(payload, Path(destination))


def _sql_string(value: str) -> str:
    """Return a DuckDB string literal for a trusted local value."""

    return "'" + value.replace("'", "''") + "'"


def _parquet_scan_sql(files: Sequence[PathLike]) -> str:
    paths = tuple(Path(path).resolve() for path in files)
    if not paths:
        raise ValueError("at least one Parquet file is required")
    rendered = ", ".join(_sql_string(str(path)) for path in paths)
    return (
        f"read_parquet([{rendered}], union_by_name=true, "
        "hive_partitioning=false)"
    )


def _duckdb_interval(frequency: str) -> str:
    """Translate the bounded Polars frequency syntax used by configs to SQL."""

    match = re.fullmatch(r"([1-9][0-9]*)(ms|s|m|h|d|w)", frequency.strip())
    if match is None:
        raise ValueError(
            "streaming NYC full mode requires panel_frequency like 15m, 1h, or 1d"
        )
    amount, abbreviation = match.groups()
    units = {
        "ms": "milliseconds",
        "s": "seconds",
        "m": "minutes",
        "h": "hours",
        "d": "days",
        "w": "weeks",
    }
    return f"INTERVAL '{amount} {units[abbreviation]}'"


def _new_staging_directory(destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    return Path(
        tempfile.mkdtemp(
            prefix=f".{destination.name}-streaming-",
            dir=destination.parent,
        )
    )


def _replace_directory(staging: Path, destination: Path) -> None:
    """Install a completed staged directory while retaining rollback on failure."""

    if not staging.is_dir():
        raise FileNotFoundError(staging)
    destination.parent.mkdir(parents=True, exist_ok=True)
    backup_root: Path | None = None
    backup: Path | None = None
    if destination.exists():
        if not destination.is_dir():
            raise NotADirectoryError(destination)
        backup_root = Path(
            tempfile.mkdtemp(
                prefix=f".{destination.name}-previous-",
                dir=destination.parent,
            )
        )
        backup = backup_root / "dataset"
        destination.replace(backup)
    try:
        staging.replace(destination)
    except BaseException:
        if backup is not None:
            backup.replace(destination)
        raise
    finally:
        if backup_root is not None and backup_root.exists():
            shutil.rmtree(backup_root)


def _stream_normalize_nyc_full(
    raw_files: Sequence[Path],
    config: DataConfig,
    output_dir: Path,
) -> tuple[tuple[Path, ...], dict[str, Any]]:
    """Normalize NYC Parquet record batches to unique staged clean parts."""

    if not raw_files:
        raise ValueError("NYC full mode requires at least one raw monthly Parquet file")
    if any(
        value is not None
        for value in (
            config.nyc_expected_rows,
            config.nyc_expected_bytes,
            config.nyc_expected_sha256,
        )
    ) and len(raw_files) != 1:
        raise ValueError("NYC exact raw expectations require exactly one raw file")
    if config.nyc_expected_bytes is not None:
        actual_bytes = raw_files[0].stat().st_size
        if actual_bytes != config.nyc_expected_bytes:
            raise ValueError(
                "NYC raw byte-size mismatch: "
                f"expected {config.nyc_expected_bytes}, found {actual_bytes}"
            )
    if config.nyc_expected_sha256 is not None:
        actual_sha256 = sha256_file(raw_files[0])
        if actual_sha256 != config.nyc_expected_sha256:
            raise ValueError(
                "NYC raw SHA-256 mismatch: "
                f"expected {config.nyc_expected_sha256}, found {actual_sha256}"
            )
    output_dir.mkdir(parents=True, exist_ok=True)
    source_row_offset = 0
    batch_index = 0
    total_row_groups = 0
    observed_dates: set[date] = set()
    observed_date_hours: set[tuple[date, int]] = set()
    pickup_min: datetime | None = None
    pickup_max: datetime | None = None
    file_validation: list[dict[str, Any]] = []

    for raw_path in raw_files:
        if raw_path.suffix.lower() not in {".parquet", ".pq"}:
            raise ValueError(f"NYC full streaming input must be Parquet: {raw_path}")
        try:
            parquet = pq.ParquetFile(raw_path)
        except Exception as exc:
            raise ValueError(f"NYC raw Parquet is unreadable: {raw_path}") from exc
        metadata = parquet.metadata
        raw_rows = int(metadata.num_rows)
        row_groups = int(metadata.num_row_groups)
        if raw_rows < 1 or row_groups < 1:
            raise ValueError(f"NYC raw Parquet has no rows or row groups: {raw_path}")
        if config.nyc_expected_rows is not None and raw_rows != config.nyc_expected_rows:
            raise ValueError(
                "NYC raw row-count mismatch: "
                f"expected {config.nyc_expected_rows}, found {raw_rows}"
            )
        missing = sorted(REQUIRED_RAW_COLUMNS["nyc_hvfhv"] - set(parquet.schema_arrow.names))
        if missing:
            raise ValueError(
                "nyc_hvfhv raw data are missing required columns: " + ", ".join(missing)
            )

        file_rows = 0
        file_batches = 0
        file_pickup_min: datetime | None = None
        file_pickup_max: datetime | None = None
        for arrow_batch in parquet.iter_batches(batch_size=config.nyc_batch_rows):
            raw_batch = pl.from_arrow(arrow_batch)
            if not isinstance(raw_batch, pl.DataFrame):
                raise TypeError("PyArrow record batch did not convert to a Polars DataFrame")
            _validate_raw_columns(raw_batch, "nyc_hvfhv")
            clean_batch = _normalize_nyc(
                raw_batch,
                source_row_offset=source_row_offset,
            )
            validate_clean_schema(clean_batch)
            if clean_batch.height != raw_batch.height:
                raise RuntimeError("NYC normalization changed the number of trip records")

            write_partitioned_parquet(
                clean_batch,
                output_dir,
                partition_by=config.partition_by,
                basename=f"part-{batch_index:05d}.parquet",
                overwrite=False,
            )
            pickup = clean_batch.get_column("pickup_datetime").drop_nulls()
            if not pickup.is_empty():
                batch_min = pickup.min()
                batch_max = pickup.max()
                if isinstance(batch_min, datetime):
                    pickup_min = batch_min if pickup_min is None else min(pickup_min, batch_min)
                    file_pickup_min = (
                        batch_min
                        if file_pickup_min is None
                        else min(file_pickup_min, batch_min)
                    )
                if isinstance(batch_max, datetime):
                    pickup_max = batch_max if pickup_max is None else max(pickup_max, batch_max)
                    file_pickup_max = (
                        batch_max
                        if file_pickup_max is None
                        else max(file_pickup_max, batch_max)
                    )
            coverage = clean_batch.select(
                "service_date",
                pl.col("pickup_datetime").dt.hour().alias("pickup_hour"),
            ).drop_nulls().unique()
            for service_date, pickup_hour in coverage.iter_rows():
                observed_dates.add(service_date)
                observed_date_hours.add((service_date, int(pickup_hour)))

            source_row_offset += clean_batch.height
            file_rows += clean_batch.height
            file_batches += 1
            batch_index += 1

        if file_rows != raw_rows:
            raise RuntimeError(
                f"NYC raw metadata reports {raw_rows} rows but streamed {file_rows}: {raw_path}"
            )
        total_row_groups += row_groups
        try:
            rendered_raw_path = str(
                raw_path.resolve().relative_to(config.project_root.resolve())
            )
        except ValueError:
            rendered_raw_path = str(raw_path.resolve())
        file_validation.append(
            {
                "path": rendered_raw_path,
                "rows": raw_rows,
                "row_groups": row_groups,
                "batches": file_batches,
                "pickup_min": file_pickup_min.isoformat() if file_pickup_min else None,
                "pickup_max": file_pickup_max.isoformat() if file_pickup_max else None,
            }
        )

    expected_dates = {
        date(config.nyc_year, month, day)
        for month in config.nyc_months
        for day in range(1, monthrange(config.nyc_year, month)[1] + 1)
    }
    outside_dates = sorted(observed_dates - expected_dates)
    if outside_dates:
        raise ValueError(
            "NYC full raw data include pickup dates outside configured months: "
            + ", ".join(value.isoformat() for value in outside_dates[:5])
        )
    missing_dates = sorted(expected_dates - observed_dates)
    if missing_dates:
        preview = ", ".join(value.isoformat() for value in missing_dates[:5])
        raise ValueError(
            f"NYC full raw data are missing {len(missing_dates)} configured calendar days: "
            f"{preview}"
        )
    expected_date_hours = {
        (service_date, hour) for service_date in expected_dates for hour in range(24)
    }
    missing_date_hours = sorted(expected_date_hours - observed_date_hours)
    if missing_date_hours:
        preview = ", ".join(
            f"{service_date.isoformat()}T{hour:02d}"
            for service_date, hour in missing_date_hours[:5]
        )
        raise ValueError(
            f"NYC full raw data are missing {len(missing_date_hours)} configured date-hours: "
            f"{preview}"
        )

    outputs = tuple(sorted(output_dir.rglob("*.parquet")))
    if not outputs:
        raise RuntimeError("NYC full streaming normalization produced no clean parts")
    return outputs, {
        "strategy": "parquet_record_batch_streaming_v1",
        "batch_rows": config.nyc_batch_rows,
        "raw_rows": source_row_offset,
        "clean_rows": source_row_offset,
        "raw_row_groups": total_row_groups,
        "normalized_batches": batch_index,
        "clean_parts": len(outputs),
        "raw_file_validation": file_validation,
        "pickup_min": pickup_min.isoformat() if pickup_min else None,
        "pickup_max": pickup_max.isoformat() if pickup_max else None,
        "configured_calendar_days": len(expected_dates),
        "observed_calendar_days": len(observed_dates),
        "configured_date_hours": len(expected_date_hours),
        "observed_date_hours": len(observed_date_hours),
        "complete_calendar_coverage": True,
    }


def _open_streaming_duckdb(
    clean_files: Sequence[Path],
    temporary_dir: Path,
) -> duckdb.DuckDBPyConnection:
    temporary_dir.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect()
    connection.execute("SET memory_limit = '1GB'")
    # A single aggregation thread makes floating-point reduction order and Parquet
    # row-group boundaries reproducible across identical full-month reruns.
    connection.execute("SET threads = 1")
    connection.execute(f"SET temp_directory = {_sql_string(str(temporary_dir.resolve()))}")
    connection.execute(
        f"CREATE TEMP VIEW clean_trips AS SELECT * FROM {_parquet_scan_sql(clean_files)}"
    )
    return connection


def _streaming_zone_query(frequency: str) -> str:
    interval = _duckdb_interval(frequency)
    missing_zone = _sql_string(MISSING_ZONE_ID)
    return f"""
        WITH usable AS (
            SELECT
                source,
                zone_type,
                coalesce(pickup_zone_id, {missing_zone}) AS zone_id,
                coalesce(dropoff_zone_id, {missing_zone}) AS dropoff_zone_id,
                pickup_zone_id IS NOT NULL AND dropoff_zone_id IS NOT NULL
                    AS od_pair_observed,
                time_bucket({interval}, pickup_datetime) AS time_bin,
                fare,
                trip_seconds,
                trip_miles,
                shared_requested,
                shared_matched,
                airport_trip,
                pickup_census_tract_missing_or_suppressed,
                reported_timestamp_rounding_minutes,
                reported_fare_rounding_increment
            FROM clean_trips
            WHERE pickup_datetime IS NOT NULL
        ), grouped AS (
            SELECT
                source,
                zone_type,
                zone_id,
                time_bin,
                count(*)::BIGINT AS trip_count,
                CASE WHEN count(*) FILTER (WHERE od_pair_observed) > 0
                    THEN count(DISTINCT dropoff_zone_id)
                        FILTER (WHERE od_pair_observed)::BIGINT
                    ELSE NULL END AS distinct_dropoff_zones,
                CASE WHEN count(*) FILTER (WHERE od_pair_observed) > 0
                    THEN count(*) FILTER (
                        WHERE od_pair_observed AND zone_id <> dropoff_zone_id
                    )::BIGINT
                    ELSE NULL END AS outbound_trip_count,
                avg(CASE WHEN od_pair_observed
                    THEN (zone_id = dropoff_zone_id)::DOUBLE ELSE NULL END)
                    AS intra_zone_share,
                count(*) FILTER (WHERE od_pair_observed)::BIGINT
                    AS od_pair_observed_count,
                avg(od_pair_observed::DOUBLE) AS od_pair_observed_share,
                avg(fare) AS avg_fare,
                median(fare) AS median_fare,
                sum(fare) AS total_fare,
                avg(trip_seconds) AS avg_trip_seconds,
                avg(trip_miles) AS avg_trip_miles,
                sum(trip_miles) AS total_trip_miles,
                avg(shared_requested::DOUBLE) AS shared_requested_share,
                avg(shared_matched::DOUBLE) AS shared_matched_share,
                avg(airport_trip::DOUBLE) AS airport_trip_share,
                avg(pickup_census_tract_missing_or_suppressed::DOUBLE)
                    AS pickup_geography_missing_or_suppressed_share,
                avg((reported_timestamp_rounding_minutes IS NOT NULL)::DOUBLE)
                    AS timestamp_rounded_measurement_share,
                avg((reported_fare_rounding_increment IS NOT NULL)::DOUBLE)
                    AS fare_rounded_measurement_share
            FROM usable
            GROUP BY source, zone_type, zone_id, time_bin
        )
        SELECT
            *,
            time_bin::DATE AS service_date,
            year(time_bin)::INTEGER AS year,
            month(time_bin)::TINYINT AS month,
            isodow(time_bin)::TINYINT AS day_of_week,
            hour(time_bin)::TINYINT AS hour,
            minute(time_bin)::TINYINT AS minute,
            (isodow(time_bin) >= 6) AS is_weekend,
            {_sql_string(f"pickup_zone_x_{frequency}")} AS panel_grain,
            'descriptive_real_data' AS evidence_label
        FROM grouped
        ORDER BY source, zone_type, zone_id, time_bin
    """


def _streaming_od_query(frequency: str) -> str:
    interval = _duckdb_interval(frequency)
    missing_zone = _sql_string(MISSING_ZONE_ID)
    return f"""
        WITH grouped AS (
            SELECT
                source,
                zone_type,
                coalesce(pickup_zone_id, {missing_zone}) AS origin_zone_id,
                coalesce(dropoff_zone_id, {missing_zone}) AS destination_zone_id,
                time_bucket({interval}, pickup_datetime) AS time_bin,
                count(*)::BIGINT AS trip_count,
                avg(fare) AS avg_fare,
                avg(trip_miles) AS avg_trip_miles
            FROM clean_trips
            WHERE pickup_datetime IS NOT NULL
            GROUP BY source, zone_type, origin_zone_id, destination_zone_id, time_bin
        )
        SELECT
            *,
            'descriptive_real_data' AS evidence_label,
            time_bin::DATE AS service_date,
            year(time_bin)::INTEGER AS year,
            month(time_bin)::TINYINT AS month
        FROM grouped
        ORDER BY source, origin_zone_id, destination_zone_id, time_bin
    """


def _copy_partitioned_query(
    connection: duckdb.DuckDBPyConnection,
    query: str,
    output_dir: Path,
) -> tuple[Path, ...]:
    output_dir.mkdir(parents=True, exist_ok=True)
    connection.execute(
        f"COPY ({query}) TO {_sql_string(str(output_dir.resolve()))} "
        "(FORMAT PARQUET, COMPRESSION ZSTD, "
        "PARTITION_BY (source, year, month), WRITE_PARTITION_COLUMNS)"
    )
    outputs = tuple(sorted(output_dir.rglob("*.parquet")))
    if not outputs:
        raise RuntimeError("streaming aggregation produced no Parquet output")
    return outputs


def _streaming_diagnostics(
    connection: duckdb.DuckDBPyConnection,
) -> dict[str, Any]:
    columns = CLEAN_TRIP_SCHEMA.names()
    null_expressions = [
        f"count(*) FILTER (WHERE \"{column}\" IS NULL)::BIGINT AS null_{index}"
        for index, column in enumerate(columns)
    ]
    summary = connection.execute(
        "SELECT count(*)::BIGINT AS rows, "
        + ", ".join(null_expressions)
        + ", count(DISTINCT trip_id)::BIGINT AS distinct_trip_ids, "
        "count(*) FILTER (WHERE trip_seconds <= 0)::BIGINT AS nonpositive_seconds, "
        "count(*) FILTER (WHERE trip_miles < 0)::BIGINT AS negative_miles, "
        "count(*) FILTER (WHERE fare < 0)::BIGINT AS negative_fare "
        "FROM clean_trips"
    ).fetchone()
    if summary is None:
        raise RuntimeError("streaming diagnostics returned no summary")
    rows = int(summary[0])
    null_counts = {column: int(summary[index + 1]) for index, column in enumerate(columns)}
    metric_offset = 1 + len(columns)
    distinct_trip_ids = int(summary[metric_offset])
    nonpositive_seconds = int(summary[metric_offset + 1])
    negative_miles = int(summary[metric_offset + 2])
    negative_fare = int(summary[metric_offset + 3])
    sources = [
        str(row[0])
        for row in connection.execute(
            "SELECT DISTINCT source FROM clean_trips WHERE source IS NOT NULL ORDER BY source"
        ).fetchall()
    ]

    pickup_indicator = "pickup_census_tract_missing_or_suppressed"
    dropoff_indicator = "dropoff_census_tract_missing_or_suppressed"
    availability = connection.execute(
        f"""
        SELECT
            count({pickup_indicator})::BIGINT,
            count(*) FILTER (WHERE {pickup_indicator} IS TRUE)::BIGINT,
            count({dropoff_indicator})::BIGINT,
            count(*) FILTER (WHERE {dropoff_indicator} IS TRUE)::BIGINT,
            avg(pickup_on_15_minute_grid::DOUBLE),
            avg(fare_on_declared_grid::DOUBLE)
        FROM clean_trips
        """
    ).fetchone()
    if availability is None:
        raise RuntimeError("streaming diagnostics returned no availability summary")
    pickup_known, pickup_suppressed, dropoff_known, dropoff_suppressed = (
        int(value) for value in availability[:4]
    )
    timestamp_increments = [
        int(row[0])
        for row in connection.execute(
            "SELECT DISTINCT reported_timestamp_rounding_minutes FROM clean_trips "
            "WHERE reported_timestamp_rounding_minutes IS NOT NULL ORDER BY 1"
        ).fetchall()
    ]
    fare_increments = [
        float(row[0])
        for row in connection.execute(
            "SELECT DISTINCT reported_fare_rounding_increment FROM clean_trips "
            "WHERE reported_fare_rounding_increment IS NOT NULL ORDER BY 1"
        ).fetchall()
    ]
    missingness = {
        column: {
            "count": null_counts[column],
            "rate": (null_counts[column] / rows if rows else None),
        }
        for column in columns
    }
    diagnostics = {
        "schema_version": SCHEMA_VERSION,
        "row_count": rows,
        "sources": sources,
        "missingness": missingness,
        "suppression_or_nonreporting": {
            "pickup_census_tract_count": pickup_suppressed,
            "pickup_census_tract_rate": (
                pickup_suppressed / pickup_known if pickup_known else None
            ),
            "pickup_indicator_known_count": pickup_known,
            "pickup_indicator_status": (
                "available"
                if pickup_known == rows
                else "unavailable"
                if not pickup_known
                else "partial"
            ),
            "dropoff_census_tract_count": dropoff_suppressed,
            "dropoff_census_tract_rate": (
                dropoff_suppressed / dropoff_known if dropoff_known else None
            ),
            "dropoff_indicator_known_count": dropoff_known,
            "dropoff_indicator_status": (
                "available"
                if dropoff_known == rows
                else "unavailable"
                if not dropoff_known
                else "partial"
            ),
            "interpretation": (
                "Null availability indicators mean the source does not report the field; they "
                "must not be recoded as unsuppressed. Chicago blank census tracts may be "
                "privacy-suppressed or outside Chicago, and no record-level mechanism is claimed."
            ),
        },
        "rounding": {
            "pickup_on_15_minute_grid_rate": (
                float(availability[4]) if availability[4] is not None else None
            ),
            "fare_on_declared_grid_rate": (
                float(availability[5]) if availability[5] is not None else None
            ),
            "declared_timestamp_rounding_minutes": timestamp_increments,
            "declared_fare_rounding_increments": fare_increments,
            "interpretation": (
                "Grid conformance verifies reported-value patterns; it does not recover "
                "latent exact fares or timestamps."
            ),
        },
        "validity": {
            "duplicate_trip_id_count": rows - distinct_trip_ids,
            "missing_trip_id_count": null_counts["trip_id"],
            "nonpositive_trip_seconds_count": nonpositive_seconds,
            "negative_trip_miles_count": negative_miles,
            "negative_fare_count": negative_fare,
            "utc_conversion_null_count": null_counts["pickup_datetime_utc"],
        },
        "source_caveats": {
            source: SOURCE_METADATA[source]["known_measurement"] for source in sources
        },
    }
    return _json_safe(diagnostics)


def _aggregate_nyc_full_from_clean(
    clean_files: Sequence[Path],
    config: DataConfig,
    zone_output_dir: Path,
    od_output_dir: Path,
    temporary_dir: Path,
) -> tuple[tuple[Path, ...], tuple[Path, ...], dict[str, Any], dict[str, int]]:
    connection = _open_streaming_duckdb(clean_files, temporary_dir)
    try:
        observed_panel = connection.sql(
            _streaming_zone_query(config.panel_frequency)
        ).pl()
        observed_panel_rows = observed_panel.height
        panel = (
            _complete_zone_time_grid(observed_panel, config.panel_frequency)
            if config.complete_panel_grid
            else observed_panel
        )
        panel_files = write_partitioned_parquet(
            panel,
            zone_output_dir,
            partition_by=("source", "year", "month"),
        )
        od_files = _copy_partitioned_query(
            connection,
            _streaming_od_query(config.panel_frequency),
            od_output_dir,
        )
        eligible_rows = int(
            connection.execute(
                "SELECT count(*) FROM clean_trips WHERE pickup_datetime IS NOT NULL"
            ).fetchone()[0]
        )
        od_stats = connection.execute(
            f"SELECT count(*)::BIGINT, coalesce(sum(trip_count), 0)::BIGINT "
            f"FROM {_parquet_scan_sql(od_files)}"
        ).fetchone()
        if od_stats is None:
            raise RuntimeError("OD aggregation returned no validation summary")
        panel_trip_sum = int(panel.get_column("trip_count").sum() or 0)
        od_rows = int(od_stats[0])
        od_trip_sum = int(od_stats[1])
        if panel_trip_sum != eligible_rows or od_trip_sum != eligible_rows:
            raise RuntimeError(
                "NYC full aggregation failed row conservation: "
                f"eligible={eligible_rows}, zone={panel_trip_sum}, od={od_trip_sum}"
            )
        diagnostics = _streaming_diagnostics(connection)
        counts = {
            "eligible_trip_rows": eligible_rows,
            "zone_time_rows": panel.height,
            "observed_zone_time_rows": observed_panel_rows,
            "synthesized_zone_time_rows": panel.height - observed_panel_rows,
            "zone_time_trip_sum": panel_trip_sum,
            "od_flow_rows": od_rows,
            "od_flow_trip_sum": od_trip_sum,
        }
        return panel_files, od_files, diagnostics, counts
    finally:
        connection.close()


def _run_nyc_full_pipeline(
    config: DataConfig,
    raw_files: Sequence[Path],
) -> PipelineArtifacts:
    clean_target = config.clean_dir / "trips"
    zone_target = config.panel_dir / "zone_time"
    od_target = config.panel_dir / "od_flow"
    clean_staging = _new_staging_directory(clean_target)
    zone_staging = _new_staging_directory(zone_target)
    od_staging = _new_staging_directory(od_target)
    duckdb_temporary = _new_staging_directory(config.clean_dir / "duckdb_spill")
    staging_paths = (clean_staging, zone_staging, od_staging, duckdb_temporary)
    try:
        staged_clean_files, streaming = _stream_normalize_nyc_full(
            raw_files,
            config,
            clean_staging,
        )
        _, _, diagnostics, counts = _aggregate_nyc_full_from_clean(
            staged_clean_files,
            config,
            zone_staging,
            od_staging,
            duckdb_temporary,
        )
        if int(streaming["clean_rows"]) != int(diagnostics["row_count"]):
            raise RuntimeError("NYC full clean rows disagree with diagnostics")
        if int(streaming["clean_rows"]) < counts["eligible_trip_rows"]:
            raise RuntimeError("NYC full eligible trip count exceeds clean row count")

        _replace_directory(clean_staging, clean_target)
        _replace_directory(zone_staging, zone_target)
        _replace_directory(od_staging, od_target)
        clean_files = tuple(sorted(clean_target.rglob("*.parquet")))
        panel_files = tuple(sorted(zone_target.rglob("*.parquet")))
        od_flow_files = tuple(sorted(od_target.rglob("*.parquet")))
        _atomic_json(diagnostics, config.diagnostics_path)

        streaming["row_conservation"] = {
            "raw_rows": int(streaming["raw_rows"]),
            "clean_rows": int(streaming["clean_rows"]),
            "pickup_datetime_null_rows": (
                int(streaming["clean_rows"]) - counts["eligible_trip_rows"]
            ),
            "panel_eligible_rows": counts["eligible_trip_rows"],
            "zone_time_trip_sum": counts["zone_time_trip_sum"],
            "od_flow_trip_sum": counts["od_flow_trip_sum"],
            "passes": True,
        }
        streaming["duckdb_memory_limit"] = "1GB"
        streaming["duckdb_threads"] = 1
        streaming["observed_zone_time_rows"] = counts["observed_zone_time_rows"]
        streaming["synthesized_zone_time_rows"] = counts[
            "synthesized_zone_time_rows"
        ]
        all_files = (
            *raw_files,
            *clean_files,
            *panel_files,
            *od_flow_files,
            config.diagnostics_path,
        )
        write_manifest(
            all_files,
            config.manifest_path,
            config=config,
            root=config.project_root,
            metadata={
                "trip_rows": int(streaming["clean_rows"]),
                "zone_time_rows": counts["zone_time_rows"],
                "od_flow_rows": counts["od_flow_rows"],
                "evidence_label": "descriptive_real_data",
                "causal_claim": False,
                "full_month_processing": streaming,
            },
        )
        _nyc_full_incomplete_path(config).unlink(missing_ok=True)
        return PipelineArtifacts(
            raw_files=tuple(raw_files),
            clean_files=clean_files,
            panel_files=panel_files,
            od_flow_files=od_flow_files,
            manifest_path=config.manifest_path,
            diagnostics_path=config.diagnostics_path,
            trip_rows=int(streaming["clean_rows"]),
            panel_rows=counts["zone_time_rows"],
        )
    finally:
        for staging in staging_paths:
            if staging.exists():
                shutil.rmtree(staging)


def _nyc_full_incomplete_path(config: DataConfig) -> Path:
    return config.manifest_path.with_name("NYC_FULL_INCOMPLETE.json")


def _begin_nyc_full_run(config: DataConfig) -> Path:
    """Publish a fail-closed run marker before raw download or cache reuse."""

    marker = _nyc_full_incomplete_path(config)
    _atomic_json(
        {
            "schema_version": SCHEMA_VERSION,
            "status": "incomplete",
            "started_at_utc": datetime.now(UTC).isoformat(),
            "config": config.as_serializable_dict(),
            "interpretation": (
                "The NYC full-month manifest and outputs must not be treated as a "
                "successful run while this marker exists."
            ),
        },
        marker,
    )
    config.manifest_path.unlink(missing_ok=True)
    return marker


def run_data_pipeline(
    config: DataConfig | PathLike,
    *,
    refresh: bool = False,
) -> PipelineArtifacts:
    """Run ingestion → normalization → diagnostics → zone/OD panels → manifest."""

    cfg = load_data_config(config) if not isinstance(config, DataConfig) else config
    if cfg.source == "nyc_hvfhv" and cfg.mode == "full":
        _begin_nyc_full_run(cfg)
        raw_files = download_data(cfg, refresh=refresh)
        return _run_nyc_full_pipeline(cfg, raw_files)
    raw_files = download_data(cfg, refresh=refresh)
    trips = normalize_trips(raw_files, config=cfg)
    validate_clean_schema(trips)
    clean_files = write_partitioned_parquet(
        trips,
        cfg.clean_dir / "trips",
        partition_by=cfg.partition_by,
    )
    panel = build_zone_time_panel(
        trips,
        frequency=cfg.panel_frequency,
        complete_grid=cfg.complete_panel_grid,
    )
    panel_partition = tuple(
        column for column in ("source", "year", "month") if column in panel.columns
    )
    panel_files = write_partitioned_parquet(
        panel,
        cfg.panel_dir / "zone_time",
        partition_by=panel_partition,
    )
    od_flow = build_od_flow_panel(trips, frequency=cfg.panel_frequency)
    od_partition = tuple(
        column for column in ("source", "year", "month") if column in od_flow.columns
    )
    od_flow_files = write_partitioned_parquet(
        od_flow,
        cfg.panel_dir / "od_flow",
        partition_by=od_partition,
    )
    write_diagnostics(trips, cfg.diagnostics_path)
    all_files = (*raw_files, *clean_files, *panel_files, *od_flow_files, cfg.diagnostics_path)
    write_manifest(
        all_files,
        cfg.manifest_path,
        config=cfg,
        root=cfg.project_root,
        metadata={
            "trip_rows": trips.height,
            "zone_time_rows": panel.height,
            "od_flow_rows": od_flow.height,
            "evidence_label": "descriptive_real_data",
            "causal_claim": False,
            **(
                {
                    "sample_selection": {
                        "strategy": "equal_quota_per_configured_day_hour_stable_hash_v1",
                        "days": list(sorted(cfg.nyc_sample_days)),
                        "hours": list(sorted(cfg.nyc_sample_hours)),
                        "requested_rows": cfg.sample_rows,
                        "probability_sample": False,
                        "population_weighted": False,
                    }
                }
                if cfg.source == "nyc_hvfhv" and cfg.mode == "sample"
                else {}
            ),
        },
    )
    return PipelineArtifacts(
        raw_files=tuple(raw_files),
        clean_files=clean_files,
        panel_files=panel_files,
        od_flow_files=od_flow_files,
        manifest_path=cfg.manifest_path,
        diagnostics_path=cfg.diagnostics_path,
        trip_rows=trips.height,
        panel_rows=panel.height,
    )


__all__ = [
    "CHICAGO_DATASET_ID",
    "CHICAGO_RAW_SCHEMA",
    "CLEAN_TRIP_SCHEMA",
    "DataConfig",
    "MISSING_ZONE_ID",
    "NYC_HVFHV_RAW_SCHEMA",
    "PipelineArtifacts",
    "build_od_flow_panel",
    "build_zone_time_panel",
    "chicago_query_url",
    "chicago_sample_urls",
    "data_quality_diagnostics",
    "download_data",
    "download_sample",
    "load_data_config",
    "materialize_nyc_hvfhv_sample",
    "normalize_trips",
    "nyc_hvfhv_urls",
    "read_partitioned_parquet",
    "run_data_pipeline",
    "sha256_file",
    "validate_clean_schema",
    "write_diagnostics",
    "write_manifest",
    "write_partitioned_parquet",
]
