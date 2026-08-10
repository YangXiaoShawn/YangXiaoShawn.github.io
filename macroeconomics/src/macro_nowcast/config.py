"""Typed configuration for data acquisition and canonical series metadata."""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Self


class ConfigurationError(ValueError):
    """Raised when a configuration file is incomplete or internally inconsistent."""


class Frequency(StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    ANNUAL = "annual"


class SeriesRole(StrEnum):
    TARGET = "target"
    PREDICTOR = "predictor"
    CONTEXT = "context"


def _text(value: object, name: str, *, default: str | None = None) -> str:
    if value is None:
        if default is None:
            raise ConfigurationError(f"{name} is required")
        value = default
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError(f"{name} must be a non-empty string")
    return value.strip()


def _nonnegative_float(value: object, name: str) -> float:
    if isinstance(value, bool):
        raise ConfigurationError(f"{name} must be a non-negative number")
    try:
        result = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(f"{name} must be a non-negative number") from exc
    if result < 0:
        raise ConfigurationError(f"{name} must be a non-negative number")
    return result


def _positive_int(value: object, name: str) -> int:
    if isinstance(value, bool):
        raise ConfigurationError(f"{name} must be a positive integer")
    try:
        result = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(f"{name} must be a positive integer") from exc
    if result < 1:
        raise ConfigurationError(f"{name} must be a positive integer")
    return result


@dataclass(frozen=True, slots=True)
class SeriesConfig:
    """Source metadata and canonical transformation for one configured series."""

    series_id: str
    units: str
    frequency: str
    seasonal_adjustment: str
    transformation: str = "level"
    source: str = "fred"
    role: SeriesRole = SeriesRole.PREDICTOR
    title: str | None = None
    release_lag_days: int | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "series_id", _text(self.series_id, "series_id"))
        object.__setattr__(self, "units", _text(self.units, "units"))
        object.__setattr__(self, "frequency", _text(self.frequency, "frequency"))
        object.__setattr__(
            self,
            "seasonal_adjustment",
            _text(self.seasonal_adjustment, "seasonal_adjustment"),
        )
        object.__setattr__(
            self,
            "transformation",
            _text(self.transformation, "transformation"),
        )
        object.__setattr__(self, "source", _text(self.source, "source"))
        try:
            role = self.role if isinstance(self.role, SeriesRole) else SeriesRole(self.role)
        except ValueError as exc:
            choices = ", ".join(role.value for role in SeriesRole)
            raise ConfigurationError(f"role must be one of: {choices}") from exc
        object.__setattr__(self, "role", role)
        if self.title is not None:
            object.__setattr__(self, "title", _text(self.title, "title"))
        if self.release_lag_days is not None and (
            isinstance(self.release_lag_days, bool) or self.release_lag_days < 0
        ):
            raise ConfigurationError("release_lag_days must be a non-negative integer")
        if not isinstance(self.metadata, Mapping):
            raise ConfigurationError("series metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))

    @classmethod
    def from_mapping(cls, values: Mapping[str, object]) -> Self:
        known = {
            "series_id",
            "id",
            "units",
            "frequency",
            "seasonal_adjustment",
            "transformation",
            "source",
            "role",
            "title",
            "release_lag_days",
            "metadata",
        }
        metadata = dict(values.get("metadata", {}))  # type: ignore[arg-type]
        metadata.update({key: value for key, value in values.items() if key not in known})
        return cls(
            series_id=_text(values.get("series_id", values.get("id")), "series_id"),
            units=_text(values.get("units"), "units"),
            frequency=_text(values.get("frequency"), "frequency"),
            seasonal_adjustment=_text(
                values.get("seasonal_adjustment"),
                "seasonal_adjustment",
            ),
            transformation=_text(values.get("transformation"), "transformation", default="level"),
            source=_text(values.get("source"), "source", default="fred"),
            role=values.get("role", SeriesRole.PREDICTOR),  # type: ignore[arg-type]
            title=values.get("title"),  # type: ignore[arg-type]
            release_lag_days=values.get("release_lag_days"),  # type: ignore[arg-type]
            metadata=metadata,
        )


@dataclass(frozen=True, slots=True)
class FredAPIConfig:
    """Live FRED/ALFRED policy and retry settings.

    Live access is disabled unless ``terms_authorized`` is explicitly set true.
    Persistent response caching is opt-in through ``cache_dir`` and therefore off
    by default.
    """

    api_key_env: str = "FRED_API_KEY"
    base_url: str = "https://api.stlouisfed.org/fred"
    terms_authorized: bool = False
    timeout_seconds: float = 30.0
    min_interval_seconds: float = 0.5
    max_attempts: int = 3
    initial_backoff_seconds: float = 0.5
    backoff_multiplier: float = 2.0
    cache_dir: Path | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "api_key_env", _text(self.api_key_env, "api_key_env"))
        base_url = _text(self.base_url, "base_url").rstrip("/")
        if not base_url.startswith("https://"):
            raise ConfigurationError("base_url must use HTTPS")
        object.__setattr__(self, "base_url", base_url)
        if not isinstance(self.terms_authorized, bool):
            raise ConfigurationError("terms_authorized must be a boolean")
        object.__setattr__(
            self,
            "timeout_seconds",
            _nonnegative_float(self.timeout_seconds, "timeout_seconds"),
        )
        if self.timeout_seconds == 0:
            raise ConfigurationError("timeout_seconds must be greater than zero")
        object.__setattr__(
            self,
            "min_interval_seconds",
            _nonnegative_float(self.min_interval_seconds, "min_interval_seconds"),
        )
        object.__setattr__(self, "max_attempts", _positive_int(self.max_attempts, "max_attempts"))
        object.__setattr__(
            self,
            "initial_backoff_seconds",
            _nonnegative_float(self.initial_backoff_seconds, "initial_backoff_seconds"),
        )
        multiplier = _nonnegative_float(self.backoff_multiplier, "backoff_multiplier")
        if multiplier < 1:
            raise ConfigurationError("backoff_multiplier must be at least one")
        object.__setattr__(self, "backoff_multiplier", multiplier)
        if self.cache_dir is not None:
            object.__setattr__(self, "cache_dir", Path(self.cache_dir))

    @classmethod
    def from_mapping(cls, values: Mapping[str, object]) -> Self:
        return cls(
            api_key_env=values.get("api_key_env", "FRED_API_KEY"),  # type: ignore[arg-type]
            base_url=values.get(  # type: ignore[arg-type]
                "base_url",
                "https://api.stlouisfed.org/fred",
            ),
            terms_authorized=values.get("terms_authorized", False),  # type: ignore[arg-type]
            timeout_seconds=values.get("timeout_seconds", 30.0),  # type: ignore[arg-type]
            min_interval_seconds=values.get("min_interval_seconds", 0.5),  # type: ignore[arg-type]
            max_attempts=values.get("max_attempts", 3),  # type: ignore[arg-type]
            initial_backoff_seconds=values.get(  # type: ignore[arg-type]
                "initial_backoff_seconds",
                0.5,
            ),
            backoff_multiplier=values.get("backoff_multiplier", 2.0),  # type: ignore[arg-type]
            cache_dir=values.get("cache_dir"),  # type: ignore[arg-type]
        )


@dataclass(frozen=True, slots=True)
class StorageConfig:
    parquet_dir: Path = Path("data/generated/parquet")
    duckdb_path: Path = Path("data/generated/macro_nowcast.duckdb")

    def __post_init__(self) -> None:
        object.__setattr__(self, "parquet_dir", Path(self.parquet_dir))
        object.__setattr__(self, "duckdb_path", Path(self.duckdb_path))

    @classmethod
    def from_mapping(cls, values: Mapping[str, object]) -> Self:
        return cls(
            parquet_dir=Path(values.get("parquet_dir", "data/generated/parquet")),
            duckdb_path=Path(
                values.get("duckdb_path", "data/generated/macro_nowcast.duckdb")
            ),
        )


@dataclass(frozen=True, slots=True)
class DataFoundationConfig:
    series: tuple[SeriesConfig, ...]
    fred: FredAPIConfig = field(default_factory=FredAPIConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)

    def __post_init__(self) -> None:
        ids = [item.series_id for item in self.series]
        duplicates = sorted({series_id for series_id in ids if ids.count(series_id) > 1})
        if duplicates:
            raise ConfigurationError(
                f"duplicate series_id values: {', '.join(duplicates)}"
            )

    @property
    def series_by_id(self) -> dict[str, SeriesConfig]:
        return {item.series_id: item for item in self.series}

    def require_series(self, series_id: str) -> SeriesConfig:
        try:
            return self.series_by_id[series_id]
        except KeyError as exc:
            raise ConfigurationError(f"series is not configured: {series_id}") from exc


def _series_entries(raw: object) -> list[Mapping[str, object]]:
    if isinstance(raw, list):
        if not all(isinstance(item, Mapping) for item in raw):
            raise ConfigurationError("series must be an array of tables")
        return raw
    if isinstance(raw, Mapping):
        entries: list[Mapping[str, object]] = []
        for series_id, values in raw.items():
            if not isinstance(values, Mapping):
                raise ConfigurationError("named series entries must be tables")
            entries.append({"series_id": series_id, **values})
        return entries
    raise ConfigurationError("series must be an array or table")


def load_data_config(path: str | Path) -> DataFoundationConfig:
    """Load the data-foundation sections of a TOML configuration file."""

    config_path = Path(path)
    with config_path.open("rb") as file_handle:
        raw = tomllib.load(file_handle)
    if "series" not in raw:
        raise ConfigurationError("configuration must define at least one series")
    series = tuple(SeriesConfig.from_mapping(item) for item in _series_entries(raw["series"]))
    if not series:
        raise ConfigurationError("configuration must define at least one series")
    fred_raw = raw.get("fred", {})
    storage_raw = raw.get("storage", {})
    if not isinstance(fred_raw, Mapping) or not isinstance(storage_raw, Mapping):
        raise ConfigurationError("fred and storage sections must be tables")
    return DataFoundationConfig(
        series=series,
        fred=FredAPIConfig.from_mapping(fred_raw),
        storage=StorageConfig.from_mapping(storage_raw),
    )


def load_series_config(path: str | Path) -> tuple[SeriesConfig, ...]:
    """Load only configured series, preserving declaration order."""

    return load_data_config(path).series


load_config = load_data_config
ProjectDataConfig = DataFoundationConfig
