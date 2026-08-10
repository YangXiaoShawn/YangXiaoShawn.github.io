"""Canonical, typed records for vintage-aware macroeconomic observations.

The date-only ``availability_date`` is the repository's authoritative eligibility
field.  Timestamp fields are optional because many public macro releases expose a
release date without defensible intraday timing.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

import polars as pl


class SchemaValidationError(ValueError):
    """Raised when a row cannot satisfy the canonical vintage schema."""


def _date_value(value: object, field_name: str, *, optional: bool = False) -> date | None:
    if value is None:
        if optional:
            return None
        raise SchemaValidationError(f"{field_name} is required")
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise SchemaValidationError(f"{field_name} must be an ISO date") from exc
    raise SchemaValidationError(f"{field_name} must be a date")


def _datetime_value(
    value: object,
    field_name: str,
    *,
    optional: bool = False,
) -> datetime | None:
    if value is None:
        if optional:
            return None
        raise SchemaValidationError(f"{field_name} is required")
    if isinstance(value, str):
        normalized = f"{value[:-1]}+00:00" if value.endswith("Z") else value
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError as exc:
            raise SchemaValidationError(f"{field_name} must be an ISO datetime") from exc
    elif isinstance(value, datetime):
        parsed = value
    else:
        raise SchemaValidationError(f"{field_name} must be a datetime")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SchemaValidationError(f"{field_name} must include a timezone")
    return parsed.astimezone(UTC)


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SchemaValidationError(f"{field_name} must be a non-empty string")
    return value.strip()


def _metadata_value(value: object) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise SchemaValidationError("source_metadata must contain valid JSON") from exc
    if not isinstance(value, Mapping):
        raise SchemaValidationError("source_metadata must be a mapping")
    metadata = dict(value)
    if any(not isinstance(key, str) for key in metadata):
        raise SchemaValidationError("source_metadata keys must be strings")
    try:
        json.dumps(metadata, allow_nan=False, sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise SchemaValidationError("source_metadata must be JSON serializable") from exc
    return metadata


def _optional_float(value: object) -> float | None:
    if value is None or value == "" or value == ".":
        return None
    if isinstance(value, bool):
        raise SchemaValidationError("value must be numeric or null")
    try:
        parsed = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise SchemaValidationError("value must be numeric or null") from exc
    if not math.isfinite(parsed):
        raise SchemaValidationError("value must be finite when present")
    return parsed


@dataclass(frozen=True, slots=True, kw_only=True)
class VintageObservation:
    """One value of one observation as it existed in one source vintage.

    ``availability_date`` is mandatory even when a release timestamp exists.  It
    supports strict date-granularity as-of filtering without inventing intraday
    precision. ``provenance_label`` distinguishes genuine source data from fixture
    data and derived products.
    """

    series_id: str
    observation_date: date
    realtime_start: date
    availability_date: date
    value: float | None
    units: str
    frequency: str
    seasonal_adjustment: str
    transformation: str
    source: str
    provenance_label: str
    download_timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    realtime_end: date | None = None
    release_timestamp: datetime | None = None
    availability_timestamp: datetime | None = None
    source_metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "series_id", _required_text(self.series_id, "series_id"))
        object.__setattr__(self, "units", _required_text(self.units, "units"))
        object.__setattr__(self, "frequency", _required_text(self.frequency, "frequency"))
        object.__setattr__(
            self,
            "seasonal_adjustment",
            _required_text(self.seasonal_adjustment, "seasonal_adjustment"),
        )
        object.__setattr__(
            self,
            "transformation",
            _required_text(self.transformation, "transformation"),
        )
        object.__setattr__(self, "source", _required_text(self.source, "source"))
        object.__setattr__(
            self,
            "provenance_label",
            _required_text(self.provenance_label, "provenance_label"),
        )

        observation_date = _date_value(self.observation_date, "observation_date")
        realtime_start = _date_value(self.realtime_start, "realtime_start")
        realtime_end = _date_value(self.realtime_end, "realtime_end", optional=True)
        availability_date = _date_value(self.availability_date, "availability_date")
        assert observation_date is not None
        assert realtime_start is not None
        assert availability_date is not None
        if realtime_end is not None and realtime_end < realtime_start:
            raise SchemaValidationError("realtime_end cannot precede realtime_start")

        object.__setattr__(self, "observation_date", observation_date)
        object.__setattr__(self, "realtime_start", realtime_start)
        object.__setattr__(self, "realtime_end", realtime_end)
        object.__setattr__(self, "availability_date", availability_date)
        object.__setattr__(self, "value", _optional_float(self.value))
        object.__setattr__(
            self,
            "download_timestamp",
            _datetime_value(self.download_timestamp, "download_timestamp"),
        )
        object.__setattr__(
            self,
            "release_timestamp",
            _datetime_value(self.release_timestamp, "release_timestamp", optional=True),
        )
        object.__setattr__(
            self,
            "availability_timestamp",
            _datetime_value(
                self.availability_timestamp,
                "availability_timestamp",
                optional=True,
            ),
        )
        object.__setattr__(self, "source_metadata", _metadata_value(self.source_metadata))

    @property
    def downloaded_at(self) -> datetime:
        """Compatibility alias for callers that use the shorter timestamp name."""

        return self.download_timestamp

    @classmethod
    def from_mapping(cls, row: Mapping[str, object]) -> VintageObservation:
        """Validate a canonical mapping, accepting storage-format metadata JSON."""

        availability_timestamp = row.get("availability_timestamp")
        availability_date = row.get("availability_date")
        if availability_date is None and availability_timestamp is not None:
            parsed_timestamp = _datetime_value(
                availability_timestamp,
                "availability_timestamp",
            )
            assert parsed_timestamp is not None
            availability_date = parsed_timestamp.date()

        download_timestamp = row.get("download_timestamp", row.get("downloaded_at"))
        if download_timestamp is None:
            download_timestamp = datetime.now(UTC)

        return cls(
            series_id=row.get("series_id"),  # type: ignore[arg-type]
            observation_date=row.get("observation_date"),  # type: ignore[arg-type]
            realtime_start=row.get("realtime_start"),  # type: ignore[arg-type]
            realtime_end=row.get("realtime_end"),  # type: ignore[arg-type]
            availability_date=availability_date,  # type: ignore[arg-type]
            release_timestamp=row.get("release_timestamp"),  # type: ignore[arg-type]
            availability_timestamp=availability_timestamp,  # type: ignore[arg-type]
            value=row.get("value"),  # type: ignore[arg-type]
            units=row.get("units"),  # type: ignore[arg-type]
            frequency=row.get("frequency"),  # type: ignore[arg-type]
            seasonal_adjustment=row.get("seasonal_adjustment"),  # type: ignore[arg-type]
            transformation=row.get("transformation"),  # type: ignore[arg-type]
            download_timestamp=download_timestamp,  # type: ignore[arg-type]
            source=row.get("source"),  # type: ignore[arg-type]
            provenance_label=row.get("provenance_label"),  # type: ignore[arg-type]
            source_metadata=_metadata_value(row.get("source_metadata")),
        )

    def to_dict(self) -> dict[str, object]:
        """Return Python-native values, keeping provenance metadata structured."""

        return {
            "series_id": self.series_id,
            "observation_date": self.observation_date,
            "realtime_start": self.realtime_start,
            "realtime_end": self.realtime_end,
            "availability_date": self.availability_date,
            "release_timestamp": self.release_timestamp,
            "availability_timestamp": self.availability_timestamp,
            "value": self.value,
            "units": self.units,
            "frequency": self.frequency,
            "seasonal_adjustment": self.seasonal_adjustment,
            "transformation": self.transformation,
            "download_timestamp": self.download_timestamp,
            "source": self.source,
            "provenance_label": self.provenance_label,
            "source_metadata": dict(self.source_metadata),
        }

    def to_storage_dict(self) -> dict[str, object]:
        """Return a stable Parquet representation with metadata encoded as JSON."""

        row = self.to_dict()
        row["source_metadata"] = json.dumps(
            self.source_metadata,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return row


CANONICAL_POLARS_SCHEMA = pl.Schema(
    {
        "series_id": pl.String,
        "observation_date": pl.Date,
        "realtime_start": pl.Date,
        "realtime_end": pl.Date,
        "availability_date": pl.Date,
        "release_timestamp": pl.Datetime("us", "UTC"),
        "availability_timestamp": pl.Datetime("us", "UTC"),
        "value": pl.Float64,
        "units": pl.String,
        "frequency": pl.String,
        "seasonal_adjustment": pl.String,
        "transformation": pl.String,
        "download_timestamp": pl.Datetime("us", "UTC"),
        "source": pl.String,
        "provenance_label": pl.String,
        "source_metadata": pl.String,
    }
)
CANONICAL_SCHEMA = CANONICAL_POLARS_SCHEMA
CANONICAL_COLUMNS = tuple(CANONICAL_POLARS_SCHEMA.names())
VintageRow = VintageObservation


def observations_to_frame(
    rows: Iterable[VintageObservation | Mapping[str, object]],
) -> pl.DataFrame:
    """Build a deterministically ordered Polars frame with canonical dtypes."""

    observations = [
        row if isinstance(row, VintageObservation) else VintageObservation.from_mapping(row)
        for row in rows
    ]
    if not observations:
        return pl.DataFrame(schema=CANONICAL_POLARS_SCHEMA)
    frame = pl.from_dicts(
        [row.to_storage_dict() for row in observations],
        schema=CANONICAL_POLARS_SCHEMA,
        strict=True,
    )
    return frame.sort(["series_id", "observation_date", "realtime_start", "availability_date"])


def validate_canonical_frame(frame: pl.DataFrame) -> pl.DataFrame:
    """Validate required columns and return them cast to canonical dtypes/order."""

    missing = set(CANONICAL_COLUMNS).difference(frame.columns)
    if missing:
        names = ", ".join(sorted(missing))
        raise SchemaValidationError(f"canonical frame is missing columns: {names}")
    try:
        canonical = frame.select(
            pl.col(column).cast(dtype, strict=True)
            for column, dtype in CANONICAL_POLARS_SCHEMA.items()
        )
    except (pl.exceptions.InvalidOperationError, pl.exceptions.ComputeError) as exc:
        raise SchemaValidationError("canonical frame contains incompatible values") from exc
    observations_from_frame(canonical)
    return canonical.sort(
        ["series_id", "observation_date", "realtime_start", "availability_date"]
    )


def observations_from_frame(frame: pl.DataFrame) -> list[VintageObservation]:
    """Deserialize a canonical storage frame to validated typed observations."""

    missing = set(CANONICAL_COLUMNS).difference(frame.columns)
    if missing:
        names = ", ".join(sorted(missing))
        raise SchemaValidationError(f"canonical frame is missing columns: {names}")
    return [VintageObservation.from_mapping(row) for row in frame.to_dicts()]
