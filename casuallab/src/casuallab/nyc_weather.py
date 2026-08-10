"""Verified NOAA weather enrichment for the NYC full-month descriptive panel.

The weather layer is deliberately descriptive.  A citywide station observation can
describe which published trip records occurred on wet, snowy, or cold days; it does
not create exogenous price variation and it does not identify a causal weather shock.
"""

from __future__ import annotations

import hashlib
import json
import math
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

NOAA_DAILY_SUMMARIES_URL = (
    "https://www.ncei.noaa.gov/access/services/data/v1?dataset=daily-summaries"
    "&stations=USW00094728&startDate=2024-01-01&endDate=2024-01-31"
    "&format=csv&units=metric&includeAttributes=true"
    "&dataTypes=PRCP,SNOW,SNWD,TMAX,TMIN,AWND,WT01,WT02,WT03,WT08,WT16,WT18"
)
NOAA_RAW_SHA256 = "fa9a5486dfa37e1ab61ad853d1811369f25e8c71ebf9dd0d56217f8231a0ee04"
WEATHER_EVIDENCE_LABEL = "descriptive_observed_external_weather"
WEATHER_SCHEMA_VERSION = "1.0.0"


@dataclass(frozen=True, slots=True)
class NYCWeatherConfig:
    """Pinned Central Park daily-weather contract for January 2024."""

    station_id: str = "USW00094728"
    station_name: str = "NY CITY CENTRAL PARK, NY US"
    start_date: date = date(2024, 1, 1)
    end_date: date = date(2024, 1, 31)
    expected_rows: int = 31
    expected_sha256: str = NOAA_RAW_SHA256
    wet_day_threshold_mm: float = 1.0
    heavy_precipitation_threshold_mm: float = 10.0
    freezing_threshold_c: float = 0.0

    def __post_init__(self) -> None:
        if self.start_date > self.end_date:
            raise ValueError("weather start_date must not exceed end_date")
        if self.expected_rows < 1:
            raise ValueError("expected_rows must be positive")
        if len(self.expected_sha256) != 64 or any(
            character not in "0123456789abcdef" for character in self.expected_sha256
        ):
            raise ValueError("expected_sha256 must be a lowercase SHA-256 digest")
        for name in (
            "wet_day_threshold_mm",
            "heavy_precipitation_threshold_mm",
        ):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and nonnegative")
        if self.heavy_precipitation_threshold_mm < self.wet_day_threshold_mm:
            raise ValueError("heavy precipitation threshold must be at least wet threshold")

    @property
    def source_url(self) -> str:
        return NOAA_DAILY_SUMMARIES_URL


@dataclass(frozen=True, slots=True)
class NYCWeatherArtifacts:
    normalized_weather_path: Path
    daily_panel_path: Path
    hourly_contrast_path: Path
    summary_path: Path
    manifest_path: Path

    def paths(self) -> tuple[Path, ...]:
        return (
            self.normalized_weather_path,
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


def download_noaa_daily_weather(
    destination: str | Path,
    config: NYCWeatherConfig | None = None,
    *,
    refresh: bool = False,
) -> Path:
    """Atomically download and verify the pinned 31-row NOAA response."""

    cfg = config or NYCWeatherConfig()
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file() and not refresh:
        if sha256_file(target) != cfg.expected_sha256:
            raise ValueError("cached NOAA weather SHA-256 does not match the pinned response")
        return target
    with tempfile.NamedTemporaryFile(
        prefix=f".{target.stem}-",
        suffix=target.suffix,
        dir=target.parent,
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
    request = urllib.request.Request(
        cfg.source_url,
        headers={"User-Agent": "CausalMarketplaceLab/0.1 descriptive research"},
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response, temporary.open(
            "wb"
        ) as stream:
            while block := response.read(1024 * 1024):
                stream.write(block)
        if sha256_file(temporary) != cfg.expected_sha256:
            raise ValueError("downloaded NOAA weather SHA-256 does not match the pin")
        temporary.replace(target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return target


def normalize_noaa_daily_weather(
    raw_path: str | Path,
    config: NYCWeatherConfig | None = None,
) -> pd.DataFrame:
    """Validate and normalize the pinned NOAA daily summaries response."""

    cfg = config or NYCWeatherConfig()
    source = Path(raw_path)
    if not source.is_file():
        raise FileNotFoundError(source)
    if sha256_file(source) != cfg.expected_sha256:
        raise ValueError("NOAA weather raw SHA-256 does not match the configured pin")
    raw = pd.read_csv(source, dtype={"STATION": "string", "DATE": "string"})
    required = {
        "STATION",
        "DATE",
        "AWND",
        "PRCP",
        "SNOW",
        "SNWD",
        "TMAX",
        "TMIN",
    }
    missing = required.difference(raw.columns)
    if missing:
        raise ValueError(f"NOAA weather response missing fields: {sorted(missing)}")
    if len(raw) != cfg.expected_rows:
        raise ValueError("NOAA weather response has an unexpected row count")
    if set(raw["STATION"].dropna().astype(str)) != {cfg.station_id}:
        raise ValueError("NOAA weather response contains an unexpected station")
    service_date = pd.to_datetime(raw["DATE"], errors="raise").dt.date
    expected_dates = pd.date_range(cfg.start_date, cfg.end_date, freq="D").date
    if raw["DATE"].duplicated().any() or list(service_date) != list(expected_dates):
        raise ValueError("NOAA weather dates must be unique, sorted, and calendar-complete")

    numeric_columns = ("AWND", "PRCP", "SNOW", "SNWD", "TMAX", "TMIN")
    numeric = raw[list(numeric_columns)].apply(pd.to_numeric, errors="coerce")
    if numeric[["PRCP", "SNOW", "SNWD", "TMAX", "TMIN"]].isna().any().any():
        raise ValueError("NOAA weather response is missing required daily measurements")
    if (numeric[["PRCP", "SNOW", "SNWD"]] < 0).any().any():
        raise ValueError("NOAA precipitation and snow measurements cannot be negative")
    if (numeric["TMAX"] < numeric["TMIN"]).any():
        raise ValueError("NOAA daily maximum temperature is below minimum temperature")

    normalized = pd.DataFrame(
        {
            "service_date": pd.Series(service_date, dtype="object"),
            "station_id": cfg.station_id,
            "station_name": cfg.station_name,
            "temperature_max_c": numeric["TMAX"],
            "temperature_min_c": numeric["TMIN"],
            "temperature_midrange_c": (numeric["TMAX"] + numeric["TMIN"]) / 2.0,
            "precipitation_mm": numeric["PRCP"],
            "snowfall_mm": numeric["SNOW"],
            "snow_depth_mm": numeric["SNWD"],
            "average_wind_mps": numeric["AWND"],
        }
    )
    normalized["wet_day"] = normalized["precipitation_mm"] >= cfg.wet_day_threshold_mm
    normalized["heavy_precipitation_day"] = (
        normalized["precipitation_mm"] >= cfg.heavy_precipitation_threshold_mm
    )
    normalized["snow_day"] = normalized["snowfall_mm"] > 0
    normalized["freezing_day"] = (
        normalized["temperature_min_c"] <= cfg.freezing_threshold_c
    )
    normalized["wet_or_snow_day"] = normalized["wet_day"] | normalized["snow_day"]
    for field in ("AWND", "PRCP", "SNOW", "SNWD", "TMAX", "TMIN"):
        attributes = f"{field}_ATTRIBUTES"
        if attributes in raw:
            normalized[f"{field.lower()}_measurement_attributes"] = raw[attributes].fillna("")
    normalized["evidence_label"] = WEATHER_EVIDENCE_LABEL
    normalized["causal_claim"] = False
    normalized["source_url"] = cfg.source_url
    normalized["raw_sha256"] = cfg.expected_sha256
    return normalized


def _sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _scan_sql(paths: Sequence[Path]) -> str:
    if not paths:
        raise FileNotFoundError("NYC weather analysis requires zone-time Parquet files")
    rendered = ", ".join(_sql_string(str(path.resolve())) for path in paths)
    return f"read_parquet([{rendered}], hive_partitioning=false)"


def _finite_correlation(left: pd.Series, right: pd.Series) -> float | None:
    valid = left.notna() & right.notna()
    if valid.sum() < 3 or left.loc[valid].nunique() < 2 or right.loc[valid].nunique() < 2:
        return None
    value = float(left.loc[valid].corr(right.loc[valid]))
    return value if math.isfinite(value) else None


def weather_demand_associations(
    zone_time_paths: Sequence[str | Path],
    weather: pd.DataFrame,
    config: NYCWeatherConfig | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Join weather to daily/hourly completed trips and compute descriptive contrasts."""

    cfg = config or NYCWeatherConfig()
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
    if set(daily["service_date"]) != expected_dates or len(daily) != cfg.expected_rows:
        raise ValueError("NYC zone-time panel does not cover the configured weather month")
    if len(hourly) != cfg.expected_rows * 24:
        raise ValueError("NYC zone-time panel does not contain every configured date-hour")

    weather_frame = weather.copy()
    weather_frame["service_date"] = pd.to_datetime(
        weather_frame["service_date"], errors="raise"
    ).dt.date
    daily = daily.merge(weather_frame, on="service_date", how="left", validate="1:1")
    if daily["evidence_label"].isna().any():
        raise ValueError("weather coverage is incomplete after joining the NYC panel")
    daily["iso_weekday"] = pd.to_datetime(daily["service_date"]).dt.isocalendar().day.astype(int)
    daily["day_index"] = np.arange(len(daily), dtype=int)
    hourly = hourly.merge(
        weather_frame[["service_date", "wet_day", "snow_day", "freezing_day"]],
        on="service_date",
        how="left",
        validate="m:1",
    )
    hourly_contrast = (
        hourly.groupby(["hour", "wet_day"], observed=True)["published_completed_trips"]
        .agg(["count", "mean"])
        .reset_index()
        .pivot(index="hour", columns="wet_day", values=["count", "mean"])
    )
    hourly_contrast.columns = [
        f"{'days' if measure == 'count' else 'mean_published_completed_trips'}_"
        f"{'wet' if wet else 'dry'}"
        for measure, wet in hourly_contrast.columns
    ]
    hourly_contrast = hourly_contrast.reset_index()
    for column in (
        "days_wet",
        "days_dry",
        "mean_published_completed_trips_wet",
        "mean_published_completed_trips_dry",
    ):
        if column not in hourly_contrast:
            hourly_contrast[column] = np.nan
    hourly_contrast["wet_minus_dry_mean_published_completed_trips"] = (
        hourly_contrast["mean_published_completed_trips_wet"]
        - hourly_contrast["mean_published_completed_trips_dry"]
    )
    hourly_contrast["evidence_label"] = WEATHER_EVIDENCE_LABEL
    hourly_contrast["causal_claim"] = False

    wet = daily["wet_day"].astype(bool)
    wet_mean = float(daily.loc[wet, "published_completed_trips"].mean())
    dry_mean = float(daily.loc[~wet, "published_completed_trips"].mean())
    summary = {
        "schema_version": WEATHER_SCHEMA_VERSION,
        "evidence_label": WEATHER_EVIDENCE_LABEL,
        "causal_claim": False,
        "scope": {
            "city": "New York City",
            "pickup_month": "2024-01",
            "weather_station_id": cfg.station_id,
            "weather_station_name": cfg.station_name,
            "published_completed_trip_days": len(daily),
            "population_claim": False,
        },
        "definitions": {
            "wet_day": f"NOAA daily precipitation >= {cfg.wet_day_threshold_mm:g} mm",
            "heavy_precipitation_day": (
                "NOAA daily precipitation >= "
                f"{cfg.heavy_precipitation_threshold_mm:g} mm"
            ),
            "snow_day": "NOAA daily snowfall > 0 mm",
            "freezing_day": (
                f"NOAA daily minimum temperature <= {cfg.freezing_threshold_c:g} C"
            ),
            "temperature_midrange_c": "(daily TMAX + daily TMIN) / 2; not TAVG",
        },
        "coverage": {
            "weather_rows": len(weather_frame),
            "joined_days": len(daily),
            "joined_date_hours": len(hourly),
            "wet_days": int(wet.sum()),
            "dry_days": int((~wet).sum()),
            "heavy_precipitation_days": int(daily["heavy_precipitation_day"].sum()),
            "snow_days": int(daily["snow_day"].sum()),
            "freezing_days": int(daily["freezing_day"].sum()),
        },
        "associations": {
            "mean_daily_published_completed_trips_wet": wet_mean,
            "mean_daily_published_completed_trips_dry": dry_mean,
            "wet_minus_dry_mean_daily_published_completed_trips": wet_mean - dry_mean,
            "wet_minus_dry_relative_to_dry": (
                (wet_mean - dry_mean) / dry_mean if dry_mean else None
            ),
            "precipitation_daily_trip_correlation": _finite_correlation(
                daily["precipitation_mm"], daily["published_completed_trips"]
            ),
            "temperature_midrange_daily_trip_correlation": _finite_correlation(
                daily["temperature_midrange_c"], daily["published_completed_trips"]
            ),
        },
        "conservation": {
            "zone_time_trip_sum": int(daily["published_completed_trips"].sum()),
            "daily_trip_sum": int(daily["published_completed_trips"].sum()),
            "passes": True,
        },
        "limitations": [
            "The Central Park station is a citywide proxy and does not measure zone-level weather.",
            "Wet-versus-dry and temperature contrasts are observational associations confounded by seasonality, weekday composition, and other shocks.",
            "Published completed trips exclude latent requests, unserved demand, and available drivers.",
            "Weather is not an instrument for fare or treatment, and no causal elasticity or weather effect is identified.",
            "One January month does not establish seasonal or annual transportability.",
        ],
    }
    return daily, hourly_contrast, summary


def _portable(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError as exc:
        raise ValueError(f"weather artifact path is outside project_root: {path}") from exc


def write_nyc_weather_bundle(
    raw_path: str | Path,
    panel_directory: str | Path,
    data_manifest_path: str | Path,
    output_directory: str | Path,
    *,
    project_root: str | Path,
    config: NYCWeatherConfig | None = None,
) -> NYCWeatherArtifacts:
    """Create an atomic, hash-manifested NYC weather association bundle."""

    cfg = config or NYCWeatherConfig()
    root = Path(project_root).resolve()
    raw = Path(raw_path).resolve()
    panel_root = Path(panel_directory).resolve()
    source_manifest_path = Path(data_manifest_path).resolve()
    output = Path(output_directory).resolve()
    output.mkdir(parents=True, exist_ok=True)
    marker = output / "NYC_WEATHER_INCOMPLETE.json"
    manifest_path = output / "manifest.json"
    manifest_path.unlink(missing_ok=True)
    _atomic_json({"status": "incomplete"}, marker)

    source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    if (
        source_manifest.get("config", {}).get("source") != "nyc_hvfhv"
        or source_manifest.get("config", {}).get("mode") != "full"
        or source_manifest.get("metadata", {}).get("evidence_label")
        != "descriptive_real_data"
        or source_manifest.get("metadata", {}).get("causal_claim") is not False
    ):
        raise ValueError("weather analysis requires the verified NYC full-data manifest")
    panel_paths = tuple(sorted(panel_root.rglob("*.parquet")))
    if not panel_paths:
        raise FileNotFoundError("NYC full zone-time panel is unavailable")
    declared = {
        (root / entry["path"]).resolve(): entry
        for entry in source_manifest.get("files", [])
        if isinstance(entry, dict) and isinstance(entry.get("path"), str)
    }
    if set(panel_paths).difference(declared):
        raise ValueError("NYC weather panel files are not all declared in the source manifest")
    for path in panel_paths:
        entry = declared[path]
        if path.stat().st_size != entry.get("bytes") or sha256_file(path) != entry.get(
            "sha256"
        ):
            raise ValueError(f"NYC weather panel lineage mismatch: {path}")

    normalized = normalize_noaa_daily_weather(raw, cfg)
    daily, hourly, summary = weather_demand_associations(panel_paths, normalized, cfg)
    expected_trips = int(
        source_manifest["metadata"]["full_month_processing"]["row_conservation"][
            "zone_time_trip_sum"
        ]
    )
    if summary["conservation"]["daily_trip_sum"] != expected_trips:
        raise ValueError("NYC weather daily panel does not conserve published trips")
    summary["provenance"] = {
        "noaa_url": cfg.source_url,
        "noaa_raw_path": _portable(raw, root),
        "noaa_raw_sha256": sha256_file(raw),
        "nyc_data_manifest_path": _portable(source_manifest_path, root),
        "nyc_data_manifest_sha256": sha256_file(source_manifest_path),
        "panel_files_verified": len(panel_paths),
        "hashes_recomputed": True,
    }
    normalized_path = _atomic_csv(normalized, output / "weather_daily.csv")
    daily_path = _atomic_csv(daily, output / "weather_trip_daily.csv")
    hourly_path = _atomic_csv(hourly, output / "weather_hourly_contrasts.csv")
    summary_path = _atomic_json(summary, output / "weather_associations.json")
    files = [raw, source_manifest_path, normalized_path, daily_path, hourly_path, summary_path]
    entries = [
        {
            "path": _portable(path, root),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in files
    ]
    declared_digest = hashlib.sha256(
        json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    _atomic_json(
        {
            "schema_version": WEATHER_SCHEMA_VERSION,
            "evidence_label": WEATHER_EVIDENCE_LABEL,
            "causal_claim": False,
            "portable_paths": True,
            "files": entries,
            "declared_file_set_sha256": declared_digest,
            "checks": {
                "noaa_raw_hash_matches": sha256_file(raw) == cfg.expected_sha256,
                "calendar_complete": len(normalized) == cfg.expected_rows,
                "nyc_source_manifest_valid": True,
                "panel_files_verified": len(panel_paths),
                "trip_conservation": True,
            },
        },
        manifest_path,
    )
    if not manifest_path.is_file():
        raise RuntimeError("NYC weather bundle completed without a manifest")
    marker.unlink(missing_ok=True)
    return NYCWeatherArtifacts(
        normalized_weather_path=normalized_path,
        daily_panel_path=daily_path,
        hourly_contrast_path=hourly_path,
        summary_path=summary_path,
        manifest_path=manifest_path,
    )


__all__ = [
    "NOAA_DAILY_SUMMARIES_URL",
    "NOAA_RAW_SHA256",
    "NYCWeatherArtifacts",
    "NYCWeatherConfig",
    "WEATHER_EVIDENCE_LABEL",
    "download_noaa_daily_weather",
    "normalize_noaa_daily_weather",
    "weather_demand_associations",
    "write_nyc_weather_bundle",
]
