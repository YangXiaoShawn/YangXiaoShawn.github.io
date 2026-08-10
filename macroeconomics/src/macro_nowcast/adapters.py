"""Offline fixtures and guarded live FRED/ALFRED observation adapters."""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Protocol, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import polars as pl

from macro_nowcast.config import FredAPIConfig, SeriesConfig
from macro_nowcast.schema import SchemaValidationError, VintageObservation


class AdapterError(RuntimeError):
    """Base class for acquisition or source-parsing failures."""


class AdapterAuthorizationError(AdapterError):
    """Raised when live source access was not explicitly authorized."""


class AdapterCredentialError(AdapterError):
    """Raised when the configured FRED API key environment variable is absent."""


class AdapterResponseError(AdapterError):
    """Raised when a source response is malformed or violates the canonical schema."""


class AdapterRequestError(AdapterError):
    """Raised when a guarded live request ultimately fails."""


class RetryableAdapterError(AdapterRequestError):
    """A transport failure an injected client explicitly marks as retryable."""


type Transport = Callable[[str, float], bytes | str]
type Sleep = Callable[[float], None]
type Clock = Callable[[], float]
type Now = Callable[[], datetime]


class ObservationAdapter(Protocol):
    def fetch(
        self,
        series: SeriesConfig,
        *,
        observation_start: date | None = None,
        observation_end: date | None = None,
    ) -> list[VintageObservation]: ...


def _payload_mapping(payload: Mapping[str, Any] | bytes | str) -> Mapping[str, Any]:
    if isinstance(payload, Mapping):
        return payload
    try:
        if isinstance(payload, bytes):
            text = payload.decode("utf-8")
        elif isinstance(payload, str):
            text = payload
        else:
            raise AdapterResponseError("response payload must be a JSON object")
        decoded = json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AdapterResponseError("response payload is not valid UTF-8 JSON") from exc
    if not isinstance(decoded, Mapping):
        raise AdapterResponseError("response payload must be a JSON object")
    return decoded


def _iso_date(value: object, name: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        candidate = value[:10] if "T" in value else value
        try:
            return date.fromisoformat(candidate)
        except ValueError as exc:
            raise AdapterResponseError(f"{name} must be an ISO date") from exc
    raise AdapterResponseError(f"{name} must be an ISO date")


def _optional_iso_date(value: object, name: str) -> date | None:
    if value in (None, ""):
        return None
    return _iso_date(value, name)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _download_timestamp(value: object, fallback: datetime) -> datetime:
    if value is None:
        value = fallback
    if isinstance(value, str):
        normalized = f"{value[:-1]}+00:00" if value.endswith("Z") else value
        try:
            value = datetime.fromisoformat(normalized)
        except ValueError as exc:
            raise AdapterResponseError("download_timestamp must be an ISO datetime") from exc
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise AdapterResponseError("download_timestamp must include a timezone")
    return value.astimezone(UTC)


def _frequency(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AdapterResponseError("frequency metadata is required")
    normalized = value.strip().lower()
    aliases = {
        "d": "daily",
        "daily": "daily",
        "w": "weekly",
        "weekly": "weekly",
        "bw": "biweekly",
        "biweekly": "biweekly",
        "m": "monthly",
        "monthly": "monthly",
        "q": "quarterly",
        "quarterly": "quarterly",
        "sa": "semiannual",
        "semiannual": "semiannual",
        "a": "annual",
        "annual": "annual",
    }
    return aliases.get(normalized, normalized.replace(" ", "_"))


def _series_metadata(document: Mapping[str, Any]) -> Mapping[str, Any]:
    explicit = document.get("series")
    if isinstance(explicit, Mapping):
        return explicit
    fred_metadata = document.get("seriess")
    if isinstance(fred_metadata, list) and fred_metadata:
        first = fred_metadata[0]
        if isinstance(first, Mapping):
            return first
    return {}


def _metadata_text(
    row: Mapping[str, Any],
    series_metadata: Mapping[str, Any],
    document: Mapping[str, Any],
    *names: str,
) -> object | None:
    for values in (row, series_metadata, document):
        for name in names:
            if values.get(name) not in (None, ""):
                return values[name]
    return None


def _release_lookup(
    release_dates: Mapping[date | str, date | datetime | str] | None,
    observation_date: date,
) -> date | datetime | str | None:
    if release_dates is None:
        return None
    return release_dates.get(observation_date, release_dates.get(observation_date.isoformat()))


def parse_fred_observations(
    payload: Mapping[str, Any] | bytes | str,
    *,
    series: SeriesConfig | None = None,
    series_id: str | None = None,
    units: str | None = None,
    frequency: str | None = None,
    seasonal_adjustment: str | None = None,
    transformation: str | None = None,
    source: str | None = None,
    provenance_label: str | None = None,
    download_timestamp: datetime | None = None,
    release_dates: Mapping[date | str, date | datetime | str] | None = None,
) -> list[VintageObservation]:
    """Parse a FRED/ALFRED JSON response into canonical vintage observations.

    When an explicit release/availability date is absent, ALFRED's
    ``realtime_start`` is used as the availability date and that inference is
    recorded in ``source_metadata``. Missing FRED values represented by ``.`` are
    retained as nulls rather than silently dropped.
    """

    document = _payload_mapping(payload)
    raw_observations = document.get("observations")
    if not isinstance(raw_observations, list):
        raise AdapterResponseError("response must contain an observations array")
    metadata = _series_metadata(document)
    downloaded_at = _download_timestamp(
        download_timestamp or document.get("download_timestamp", document.get("downloaded_at")),
        _utc_now(),
    )

    configured_series_id = series.series_id if series is not None else series_id
    configured_units = series.units if series is not None else units
    configured_frequency = series.frequency if series is not None else frequency
    configured_adjustment = (
        series.seasonal_adjustment if series is not None else seasonal_adjustment
    )
    configured_transformation = series.transformation if series is not None else transformation
    configured_source = series.source if series is not None else source

    response_metadata = {
        key: value
        for key, value in document.items()
        if key not in {"observations", "seriess", "series", "download_timestamp", "downloaded_at"}
    }
    parsed: list[VintageObservation] = []
    for index, observation in enumerate(raw_observations):
        if not isinstance(observation, Mapping):
            raise AdapterResponseError(f"observation {index} must be an object")
        row = cast(Mapping[str, Any], observation)
        row_series_id = configured_series_id or _metadata_text(
            row,
            metadata,
            document,
            "series_id",
            "id",
        )
        row_units = configured_units or _metadata_text(
            row,
            metadata,
            document,
            "units_short",
            "units",
        )
        row_frequency = configured_frequency or _metadata_text(
            row,
            metadata,
            document,
            "frequency_short",
            "frequency",
        )
        row_adjustment = configured_adjustment or _metadata_text(
            row,
            metadata,
            document,
            "seasonal_adjustment_short",
            "seasonal_adjustment",
        )
        row_transformation = configured_transformation or _metadata_text(
            row,
            metadata,
            document,
            "transformation",
        )
        row_source = source or configured_source or document.get("source") or "fred_alfred"
        row_provenance = (
            provenance_label
            or document.get("provenance_label")
            or f"{row_source}_api"
        )
        if not all(
            isinstance(value, str) and value.strip()
            for value in (
                row_series_id,
                row_units,
                row_frequency,
                row_adjustment,
            )
        ):
            raise AdapterResponseError(
                f"observation {index} lacks series, units, frequency, or adjustment metadata"
            )

        observation_date = _iso_date(
            row.get("observation_date", row.get("date")),
            "observation_date",
        )
        realtime_start_value = row.get("realtime_start", document.get("realtime_start"))
        realtime_start = _iso_date(realtime_start_value, "realtime_start")
        realtime_end = _optional_iso_date(
            row.get("realtime_end", document.get("realtime_end")),
            "realtime_end",
        )
        explicit_availability = row.get("availability_date", row.get("release_date"))
        if explicit_availability is None:
            explicit_availability = _release_lookup(release_dates, observation_date)
        availability_basis = "explicit_release_or_availability_date"
        if explicit_availability is None:
            explicit_availability = realtime_start
            availability_basis = "alfred_realtime_start"
        availability_date = _iso_date(explicit_availability, "availability_date")

        release_timestamp = row.get("release_timestamp")
        availability_timestamp = row.get("availability_timestamp")
        if isinstance(explicit_availability, datetime) and availability_timestamp is None:
            availability_timestamp = explicit_availability

        source_metadata = {
            "adapter": "fred_alfred_json",
            "availability_basis": availability_basis,
            "raw_observation": dict(row),
            "response_metadata": response_metadata,
            "series_metadata": dict(metadata),
        }
        try:
            parsed.append(
                VintageObservation(
                    series_id=cast(str, row_series_id),
                    observation_date=observation_date,
                    realtime_start=realtime_start,
                    realtime_end=realtime_end,
                    availability_date=availability_date,
                    release_timestamp=release_timestamp,  # type: ignore[arg-type]
                    availability_timestamp=availability_timestamp,  # type: ignore[arg-type]
                    value=row.get("value"),  # type: ignore[arg-type]
                    units=cast(str, row_units),
                    frequency=_frequency(row_frequency),
                    seasonal_adjustment=cast(str, row_adjustment),
                    transformation=(
                        cast(str, row_transformation)
                        if isinstance(row_transformation, str) and row_transformation.strip()
                        else "level"
                    ),
                    download_timestamp=downloaded_at,
                    source=cast(str, row_source),
                    provenance_label=cast(str, row_provenance),
                    source_metadata=source_metadata,
                )
            )
        except SchemaValidationError as exc:
            raise AdapterResponseError(f"observation {index} is invalid: {exc}") from exc
    return sorted(
        parsed,
        key=lambda row: (row.series_id, row.observation_date, row.realtime_start),
    )


parse_alfred_observations = parse_fred_observations


def _urllib_transport(url: str, timeout_seconds: float) -> bytes:
    request = Request(url, headers={"User-Agent": "macro-nowcast/0.1"})
    with urlopen(request, timeout=timeout_seconds) as response:
        return response.read()


def _retryable_exception(exc: BaseException) -> bool:
    if isinstance(exc, HTTPError):
        return exc.code in {408, 425, 429, 500, 502, 503, 504}
    return isinstance(exc, (RetryableAdapterError, TimeoutError, URLError))


class FredAlfredAdapter:
    """A fail-closed live FRED/ALFRED client with injectable I/O.

    The default configuration performs no persistent caching. Unit tests can inject
    a transport and clock; none of this project's tests use the network.
    """

    def __init__(
        self,
        config: FredAPIConfig | None = None,
        *,
        environ: Mapping[str, str] | None = None,
        transport: Transport | None = None,
        sleep: Sleep = time.sleep,
        clock: Clock = time.monotonic,
        now: Now = _utc_now,
    ) -> None:
        self.config = config or FredAPIConfig()
        self._environ = environ if environ is not None else os.environ
        self._transport = transport or _urllib_transport
        self._sleep = sleep
        self._clock = clock
        self._now = now
        self._last_request_at: float | None = None
        self._throttle_lock = threading.Lock()

    def _api_key(self) -> str:
        if not self.config.terms_authorized:
            raise AdapterAuthorizationError(
                "live FRED/ALFRED access is disabled; set terms_authorized=True only "
                "after confirming authorization under the applicable source terms"
            )
        api_key = self._environ.get(self.config.api_key_env, "").strip()
        if not api_key:
            raise AdapterCredentialError(
                f"live FRED/ALFRED access requires {self.config.api_key_env}"
            )
        return api_key

    def _throttle(self) -> None:
        with self._throttle_lock:
            now = self._clock()
            if self._last_request_at is not None:
                remaining = self.config.min_interval_seconds - (now - self._last_request_at)
                if remaining > 0:
                    self._sleep(remaining)
                    now = self._clock()
            self._last_request_at = now

    def _cache_path(self, endpoint: str, parameters: Mapping[str, object]) -> Path | None:
        if self.config.cache_dir is None:
            return None
        cache_key = json.dumps(
            {"endpoint": endpoint, "parameters": parameters},
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        digest = hashlib.sha256(cache_key).hexdigest()
        return self.config.cache_dir / endpoint.replace("/", "_") / f"{digest}.json"

    def _request_json(
        self,
        endpoint: str,
        parameters: Mapping[str, object],
    ) -> Mapping[str, Any]:
        api_key = self._api_key()
        query = {
            key: value.isoformat() if isinstance(value, date) else value
            for key, value in parameters.items()
            if value is not None
        }
        cache_path = self._cache_path(endpoint, query)
        if cache_path is not None and cache_path.exists():
            return _payload_mapping(cache_path.read_bytes())

        query.update({"api_key": api_key, "file_type": "json"})
        url = f"{self.config.base_url}/{endpoint}?{urlencode(query, doseq=True)}"
        backoff = self.config.initial_backoff_seconds
        response: bytes | str | None = None
        for attempt in range(1, self.config.max_attempts + 1):
            self._throttle()
            try:
                response = self._transport(url, self.config.timeout_seconds)
                break
            except Exception as exc:
                if attempt == self.config.max_attempts or not _retryable_exception(exc):
                    raise AdapterRequestError(
                        f"FRED/ALFRED request failed for endpoint {endpoint}"
                    ) from exc
                if backoff:
                    self._sleep(backoff)
                backoff *= self.config.backoff_multiplier
        if response is None:  # pragma: no cover - loop either succeeds or raises
            raise AdapterRequestError(f"FRED/ALFRED request failed for endpoint {endpoint}")

        document = _payload_mapping(response)
        source_error = document.get("error_message", document.get("message"))
        if document.get("error_code") is not None:
            raise AdapterResponseError(f"FRED/ALFRED returned an error: {source_error}")
        if cache_path is not None:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                with cache_path.open("x", encoding="utf-8", errors="strict") as file_handle:
                    json.dump(document, file_handle, separators=(",", ":"), sort_keys=True)
            except FileExistsError:
                pass
        return document

    def fetch(
        self,
        series: SeriesConfig,
        *,
        observation_start: date | None = None,
        observation_end: date | None = None,
        realtime_start: date | None = None,
        realtime_end: date | None = None,
        vintage_dates: Iterable[date] | None = None,
        output_type: int = 1,
    ) -> list[VintageObservation]:
        """Fetch a normalized interval history with bounded pagination.

        The canonical parser supports the row-oriented output types 1 (real-time
        intervals) and 4 (initial releases). FRED output types 2 and 3 are
        vintage-by-observation cross-tabs and require a different parser, so this
        adapter rejects them rather than silently normalizing them incorrectly.
        """

        if output_type not in {1, 4}:
            raise AdapterRequestError(
                "normalized ingestion supports FRED output_type 1 or 4 only"
            )
        if vintage_dates is not None:
            raise AdapterRequestError(
                "vintage_dates cross-tab ingestion is not supported by the normalized adapter; "
                "use realtime_start/realtime_end intervals instead"
            )

        parameters: dict[str, object] = {
            "series_id": series.series_id,
            "observation_start": observation_start,
            "observation_end": observation_end,
            "realtime_start": realtime_start or date(1776, 7, 4),
            "realtime_end": realtime_end or date(9999, 12, 31),
            "output_type": output_type,
            "units": "lin",
            "sort_order": "asc",
            "limit": 100_000,
        }
        rows: list[VintageObservation] = []
        offset = 0
        while True:
            page_parameters = {**parameters, "offset": offset}
            document = self._request_json("series/observations", page_parameters)
            page_rows = parse_fred_observations(
                document,
                series=series,
                source="fred_alfred",
                provenance_label="fred_alfred_api",
                download_timestamp=self._now(),
            )
            rows.extend(page_rows)
            raw_observations = document.get("observations")
            page_size = len(raw_observations) if isinstance(raw_observations, list) else 0
            try:
                total_count = int(document.get("count", page_size))
            except (TypeError, ValueError) as exc:
                raise AdapterResponseError("response count must be an integer") from exc
            offset += page_size
            if page_size == 0 or offset >= total_count:
                break
        safe_parameters = {
            key: value.isoformat() if isinstance(value, date) else value
            for key, value in parameters.items()
            if value is not None
        }
        return [
            replace(
                row,
                source_metadata={
                    **row.source_metadata,
                    "request_endpoint": "series/observations",
                    "request_parameters": safe_parameters,
                },
            )
            for row in rows
        ]

    fetch_observations = fetch


class FixtureAdapter:
    """Read canonical or FRED-shaped JSON fixtures without network access."""

    def __init__(
        self,
        fixture: str
        | Path
        | pl.DataFrame
        | Iterable[VintageObservation | Mapping[str, object]],
        *,
        series: Iterable[SeriesConfig] = (),
    ) -> None:
        self._fixture = fixture
        self._series = {item.series_id: item for item in series}

    @staticmethod
    def _canonical_mapping(row: Mapping[str, object]) -> bool:
        required = {
            "series_id",
            "observation_date",
            "realtime_start",
            "availability_date",
            "units",
            "frequency",
            "seasonal_adjustment",
            "transformation",
        }
        return required.issubset(row)

    def _label_fixture_row(
        self,
        row: VintageObservation,
        fixture_name: str,
    ) -> VintageObservation:
        return replace(
            row,
            provenance_label="synthetic_fixture",
            source_metadata={
                **row.source_metadata,
                "fixture_name": fixture_name,
                "adapter": "fixture",
            },
        )

    def _document_rows(
        self,
        document: object,
        fixture_name: str,
        requested_series: SeriesConfig | None,
    ) -> list[VintageObservation]:
        if isinstance(document, list):
            rows: list[VintageObservation] = []
            for index, value in enumerate(document):
                if isinstance(value, VintageObservation):
                    rows.append(self._label_fixture_row(value, fixture_name))
                    continue
                if not isinstance(value, Mapping) or not self._canonical_mapping(value):
                    raise AdapterResponseError(
                        f"fixture row {index} is not a canonical observation"
                    )
                canonical = {**value, "provenance_label": "synthetic_fixture"}
                canonical.setdefault("source", "fixture")
                try:
                    rows.append(
                        self._label_fixture_row(
                            VintageObservation.from_mapping(canonical),
                            fixture_name,
                        )
                    )
                except SchemaValidationError as exc:
                    raise AdapterResponseError(f"fixture row {index} is invalid: {exc}") from exc
            return rows

        if not isinstance(document, Mapping):
            raise AdapterResponseError("fixture must be a JSON object or canonical row array")
        if "datasets" in document:
            datasets = document["datasets"]
            if not isinstance(datasets, list):
                raise AdapterResponseError("fixture datasets must be an array")
            return [
                row
                for dataset in datasets
                for row in self._document_rows(dataset, fixture_name, requested_series)
            ]

        observations = document.get("observations")
        if isinstance(observations, list) and all(
            isinstance(item, Mapping) and self._canonical_mapping(item)
            for item in observations
        ):
            defaults = {
                key: document[key]
                for key in (
                    "source",
                    "download_timestamp",
                    "downloaded_at",
                    "release_timestamp",
                    "availability_timestamp",
                )
                if key in document
            }
            canonical_rows = [
                {**defaults, **cast(Mapping[str, object], item)} for item in observations
            ]
            return self._document_rows(canonical_rows, fixture_name, requested_series)

        selected_series = requested_series
        if selected_series is None:
            metadata = _series_metadata(cast(Mapping[str, Any], document))
            fixture_series_id = metadata.get("series_id", metadata.get("id"))
            if isinstance(fixture_series_id, str):
                selected_series = self._series.get(fixture_series_id)
        rows = parse_fred_observations(
            cast(Mapping[str, Any], document),
            series=selected_series,
            provenance_label="synthetic_fixture",
            source=cast(str | None, document.get("source")) or "fixture",
        )
        return [self._label_fixture_row(row, fixture_name) for row in rows]

    def _load(self, requested_series: SeriesConfig | None) -> list[VintageObservation]:
        if isinstance(self._fixture, pl.DataFrame):
            return self._document_rows(
                self._fixture.to_dicts(),
                "in_memory_frame",
                requested_series,
            )
        if isinstance(self._fixture, (str, Path)):
            path = Path(self._fixture)
            if path.suffix.lower() not in {".json", ".jsonl", ".ndjson"}:
                raise AdapterResponseError("fixture files must be JSON or JSON Lines")
            try:
                text = path.read_text(encoding="utf-8")
            except OSError as exc:
                raise AdapterResponseError(f"cannot read fixture: {path.name}") from exc
            try:
                if path.suffix.lower() in {".jsonl", ".ndjson"}:
                    document: object = [
                        json.loads(line) for line in text.splitlines() if line.strip()
                    ]
                else:
                    document = json.loads(text)
            except json.JSONDecodeError as exc:
                raise AdapterResponseError(f"fixture is not valid JSON: {path.name}") from exc
            return self._document_rows(document, path.name, requested_series)
        return self._document_rows(list(self._fixture), "in_memory", requested_series)

    def fetch(
        self,
        series: SeriesConfig | str | None = None,
        *,
        observation_start: date | None = None,
        observation_end: date | None = None,
    ) -> list[VintageObservation]:
        requested_series = series if isinstance(series, SeriesConfig) else None
        series_id = series.series_id if isinstance(series, SeriesConfig) else series
        rows = self._load(requested_series)
        return [
            row
            for row in rows
            if (series_id is None or row.series_id == series_id)
            and (observation_start is None or row.observation_date >= observation_start)
            and (observation_end is None or row.observation_date <= observation_end)
        ]

    fetch_observations = fetch


LiveFredAdapter = FredAlfredAdapter
AlfredAdapter = FredAlfredAdapter
