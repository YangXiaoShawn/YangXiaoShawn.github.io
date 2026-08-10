"""Guarded original-provider adapters for current BLS and BEA data.

The public APIs represented here return current, revised observations.  They do
not expose a historical-vintage dimension, so every parsed API row is labeled
``latest_revised`` and becomes available at its retrieval timestamp.  Separate
archive contracts deliberately require an explicit, audited opt-in before a
caller can claim historical release provenance.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from email.utils import parsedate_to_datetime
from enum import StrEnum
from typing import Any, Literal, Protocol, cast
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus, urlencode
from urllib.request import Request, urlopen

from macro_nowcast.schema import VintageObservation

LATEST_REVISED = "latest_revised"

BLS_REGISTRATION_KEY_ENV = "BLS_REGISTRATION_KEY"
BEA_API_KEY_ENV = "BEA_API_KEY"

BLS_API_ENDPOINT = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
BEA_API_ENDPOINT = "https://apps.bea.gov/api/data"


class AgencyAdapterError(RuntimeError):
    """Base error for original-provider access or parsing."""


class AgencyAuthorizationError(AgencyAdapterError):
    """Raised when source terms or archive ingestion were not authorized."""


class AgencyCredentialError(AgencyAdapterError):
    """Raised when an agency-specific environment credential is missing."""


class AgencyRequestError(AgencyAdapterError):
    """Raised when an agency request cannot be completed safely."""


class AgencyResponseError(AgencyAdapterError):
    """Raised when an agency response cannot be parsed without guessing."""


class AgencyProvenanceError(AgencyAdapterError):
    """Raised when current API data are assigned historical provenance."""


def _nonempty_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _positive_float(value: object, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be greater than zero")
    try:
        parsed = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be greater than zero") from exc
    if parsed <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return parsed


def _nonnegative_float(value: object, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be non-negative")
    try:
        parsed = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be non-negative") from exc
    if parsed < 0:
        raise ValueError(f"{name} must be non-negative")
    return parsed


def _positive_int(value: object, name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a positive integer")
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a positive integer") from exc
    if parsed < 1:
        raise ValueError(f"{name} must be a positive integer")
    return parsed


def _aware_utc(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise AgencyResponseError(f"{name} must include a timezone")
    return value.astimezone(UTC)


def _json_mapping(payload: Mapping[str, Any] | bytes | str) -> Mapping[str, Any]:
    if isinstance(payload, Mapping):
        return payload
    try:
        text = payload.decode("utf-8") if isinstance(payload, bytes) else payload
        decoded = json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
        raise AgencyResponseError("agency response is not valid UTF-8 JSON") from exc
    if not isinstance(decoded, Mapping):
        raise AgencyResponseError("agency response must be a JSON object")
    return cast(Mapping[str, Any], decoded)


def _numeric_value(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise AgencyResponseError("observation value must be numeric or null")
    text = str(value).strip()
    if text in {"", ".", "-", "--", "NA", "N/A", "(NA)"}:
        return None
    try:
        return float(text.replace(",", ""))
    except ValueError as exc:
        raise AgencyResponseError("observation value must be numeric or null") from exc


def require_latest_revised(provenance_label: str) -> None:
    """Reject a historical-release claim for current-data API output."""

    if provenance_label != LATEST_REVISED:
        raise AgencyProvenanceError(
            "current BLS/BEA API rows must be labeled 'latest_revised'; "
            "first-release provenance requires an audited archive"
        )


@dataclass(frozen=True, slots=True)
class HTTPRequest:
    """Transport-neutral HTTP request with a credential-redacted representation."""

    method: Literal["GET", "POST"]
    url: str
    headers: Mapping[str, str] = field(default_factory=dict)
    body: bytes | None = None
    _secrets: tuple[str, ...] = field(default=(), repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.method not in {"GET", "POST"}:
            raise ValueError("method must be GET or POST")
        if not self.url.startswith("https://"):
            raise ValueError("agency requests must use HTTPS")
        object.__setattr__(self, "headers", dict(self.headers))

    @property
    def redacted_url(self) -> str:
        result = self.url
        for secret in self._secrets:
            result = result.replace(secret, "[REDACTED]")
            result = result.replace(quote_plus(secret), "%5BREDACTED%5D")
        return result

    def __repr__(self) -> str:
        return (
            "HTTPRequest("
            f"method={self.method!r}, url={self.redacted_url!r}, "
            f"headers={dict(self.headers)!r}, body_bytes={len(self.body or b'')}"
            ")"
        )


@dataclass(frozen=True, slots=True)
class HTTPResponse:
    """Small response value used by injected and standard-library transports."""

    status_code: int
    body: bytes | str
    headers: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "headers", dict(self.headers))

    def __repr__(self) -> str:
        return (
            "HTTPResponse("
            f"status_code={self.status_code!r}, body_bytes={len(self.body)}, "
            f"header_names={tuple(self.headers)!r}"
            ")"
        )


class HTTPTransport(Protocol):
    def __call__(self, request: HTTPRequest, timeout_seconds: float) -> HTTPResponse: ...


type Sleep = Callable[[float], None]
type Clock = Callable[[], float]
type Now = Callable[[], datetime]


def urllib_transport(request: HTTPRequest, timeout_seconds: float) -> HTTPResponse:
    """Execute an agency request; primarily a live-use default, never needed in tests."""

    native_request = Request(
        request.url,
        data=request.body,
        headers=dict(request.headers),
        method=request.method,
    )
    try:
        with urlopen(native_request, timeout=timeout_seconds) as response:
            return HTTPResponse(
                status_code=response.status,
                body=response.read(),
                headers=dict(response.headers.items()),
            )
    except HTTPError as exc:
        return HTTPResponse(
            status_code=exc.code,
            body=exc.read(),
            headers=dict(exc.headers.items()) if exc.headers is not None else {},
        )
    except URLError:
        raise AgencyRequestError("agency transport failed") from None


@dataclass(frozen=True, slots=True)
class AgencyRequestPolicy:
    """Configurable throttle and bounded retry behavior."""

    timeout_seconds: float = 30.0
    min_interval_seconds: float = 0.2
    max_attempts: int = 3
    initial_backoff_seconds: float = 0.5
    backoff_multiplier: float = 2.0
    max_retry_after_seconds: float = 300.0

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "timeout_seconds",
            _positive_float(self.timeout_seconds, "timeout_seconds"),
        )
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
        multiplier = _positive_float(self.backoff_multiplier, "backoff_multiplier")
        if multiplier < 1:
            raise ValueError("backoff_multiplier must be at least one")
        object.__setattr__(self, "backoff_multiplier", multiplier)
        object.__setattr__(
            self,
            "max_retry_after_seconds",
            _positive_float(self.max_retry_after_seconds, "max_retry_after_seconds"),
        )


@dataclass(frozen=True, slots=True)
class BLSLatestConfig:
    """BLS current-data access policy; authorization is disabled by default."""

    terms_authorized: bool = False
    endpoint: str = BLS_API_ENDPOINT
    request_policy: AgencyRequestPolicy = field(default_factory=AgencyRequestPolicy)

    def __post_init__(self) -> None:
        if not isinstance(self.terms_authorized, bool):
            raise ValueError("terms_authorized must be a boolean")
        if not self.endpoint.startswith("https://"):
            raise ValueError("BLS endpoint must use HTTPS")


@dataclass(frozen=True, slots=True)
class BEALatestConfig:
    """BEA current-data access policy; authorization is disabled by default."""

    terms_authorized: bool = False
    endpoint: str = BEA_API_ENDPOINT
    request_policy: AgencyRequestPolicy = field(
        default_factory=lambda: AgencyRequestPolicy(min_interval_seconds=0.6)
    )

    def __post_init__(self) -> None:
        if not isinstance(self.terms_authorized, bool):
            raise ValueError("terms_authorized must be a boolean")
        if not self.endpoint.startswith("https://"):
            raise ValueError("BEA endpoint must use HTTPS")


@dataclass(frozen=True, slots=True)
class BLSSeriesSpec:
    """Canonical metadata for one BLS source series."""

    series_id: str
    units: str
    seasonal_adjustment: str
    frequency: str = "monthly"
    transformation: str = "level"
    canonical_series_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "series_id", _nonempty_text(self.series_id, "series_id"))
        object.__setattr__(self, "units", _nonempty_text(self.units, "units"))
        object.__setattr__(
            self,
            "seasonal_adjustment",
            _nonempty_text(self.seasonal_adjustment, "seasonal_adjustment"),
        )
        object.__setattr__(self, "frequency", _nonempty_text(self.frequency, "frequency"))
        object.__setattr__(
            self,
            "transformation",
            _nonempty_text(self.transformation, "transformation"),
        )
        if self.canonical_series_id is not None:
            object.__setattr__(
                self,
                "canonical_series_id",
                _nonempty_text(self.canonical_series_id, "canonical_series_id"),
            )

    @property
    def output_series_id(self) -> str:
        return self.canonical_series_id or self.series_id


@dataclass(frozen=True, slots=True)
class BEASeriesSpec:
    """Canonical metadata for one row of one BEA NIPA table."""

    table_name: str
    line_number: str
    series_id: str
    units: str
    seasonal_adjustment: str
    frequency: str = "quarterly"
    transformation: str = "level"

    def __post_init__(self) -> None:
        object.__setattr__(self, "table_name", _nonempty_text(self.table_name, "table_name"))
        object.__setattr__(
            self,
            "line_number",
            _nonempty_text(str(self.line_number), "line_number"),
        )
        object.__setattr__(self, "series_id", _nonempty_text(self.series_id, "series_id"))
        object.__setattr__(self, "units", _nonempty_text(self.units, "units"))
        object.__setattr__(
            self,
            "seasonal_adjustment",
            _nonempty_text(self.seasonal_adjustment, "seasonal_adjustment"),
        )
        object.__setattr__(self, "frequency", _nonempty_text(self.frequency, "frequency"))
        object.__setattr__(
            self,
            "transformation",
            _nonempty_text(self.transformation, "transformation"),
        )


BLS_TOTAL_NONFARM_PAYROLL = BLSSeriesSpec(
    series_id="CES0000000001",
    units="thousands_of_persons",
    seasonal_adjustment="seasonally_adjusted",
)
BLS_CORE_CPI = BLSSeriesSpec(
    series_id="CUSR0000SA0L1E",
    units="index_1982_1984_100",
    seasonal_adjustment="seasonally_adjusted",
)
BLS_HEADLINE_CPI = BLSSeriesSpec(
    series_id="CUSR0000SA0",
    units="index_1982_1984_100",
    seasonal_adjustment="seasonally_adjusted",
)
BEA_REAL_GDP_LEVEL = BEASeriesSpec(
    table_name="T10106",
    line_number="1",
    series_id="GDPC1",
    units="billions_of_chained_dollars",
    seasonal_adjustment="seasonally_adjusted_annual_rate",
    transformation="level",
)
BEA_REAL_GDP_GROWTH = BEASeriesSpec(
    table_name="T10101",
    line_number="1",
    series_id="BEA_REAL_GDP_GROWTH_QOQ_SAAR",
    units="percent_change_qoq_saar",
    seasonal_adjustment="seasonally_adjusted_annual_rate",
    transformation="percent_change_qoq_saar",
)


def build_bls_latest_request(
    series_ids: Iterable[str],
    *,
    start_year: int,
    end_year: int,
    registration_key: str,
    endpoint: str = BLS_API_ENDPOINT,
) -> HTTPRequest:
    """Build a registered BLS v2 current-data request without performing I/O."""

    ids = tuple(_nonempty_text(value, "series_id") for value in series_ids)
    if not ids or len(ids) > 50:
        raise ValueError("a BLS request must contain between 1 and 50 series IDs")
    if len(set(ids)) != len(ids):
        raise ValueError("BLS series IDs must be unique within a request")
    if isinstance(start_year, bool) or isinstance(end_year, bool):
        raise ValueError("BLS years must be four-digit integers")
    if not (1000 <= start_year <= end_year <= 9999):
        raise ValueError("BLS years must be an ordered four-digit range")
    if end_year - start_year + 1 > 20:
        raise ValueError("registered BLS API requests may span at most 20 years")
    key = _nonempty_text(registration_key, "registration_key")
    body = json.dumps(
        {
            "seriesid": list(ids),
            "startyear": str(start_year),
            "endyear": str(end_year),
            "registrationkey": key,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return HTTPRequest(
        method="POST",
        url=endpoint,
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        body=body,
        _secrets=(key,),
    )


def _bea_years(years: Iterable[int] | str) -> str:
    if isinstance(years, str):
        candidate = years.strip()
        if candidate.upper() == "X":
            return "X"
        if not candidate:
            raise ValueError("BEA years cannot be empty")
        values = candidate.split(",")
        if any(not value.strip().isdigit() for value in values):
            raise ValueError("BEA years must be four-digit years or 'X'")
        parsed = tuple(int(value) for value in values)
    else:
        parsed = tuple(years)
    if not parsed or any(isinstance(value, bool) or not 1000 <= value <= 9999 for value in parsed):
        raise ValueError("BEA years must be four-digit years or 'X'")
    return ",".join(str(value) for value in parsed)


def build_bea_latest_request(
    *,
    api_key: str,
    table_name: str,
    years: Iterable[int] | str,
    frequency: str = "Q",
    endpoint: str = BEA_API_ENDPOINT,
) -> HTTPRequest:
    """Build a BEA NIPA current-data request without performing I/O."""

    key = _nonempty_text(api_key, "api_key")
    parameters = {
        "UserID": key,
        "method": "GetData",
        "datasetname": "NIPA",
        "TableName": _nonempty_text(table_name, "table_name"),
        "Frequency": _nonempty_text(frequency, "frequency").upper(),
        "Year": _bea_years(years),
        "ResultFormat": "JSON",
    }
    return HTTPRequest(
        method="GET",
        url=f"{endpoint}?{urlencode(parameters)}",
        headers={"Accept": "application/json"},
        _secrets=(key,),
    )


def _normalize_bls_specs(
    specs: BLSSeriesSpec | Iterable[BLSSeriesSpec],
) -> tuple[BLSSeriesSpec, ...]:
    normalized = (specs,) if isinstance(specs, BLSSeriesSpec) else tuple(specs)
    if not normalized:
        raise ValueError("at least one BLS series specification is required")
    if any(not isinstance(spec, BLSSeriesSpec) for spec in normalized):
        raise TypeError("BLS specifications must be BLSSeriesSpec values")
    if len({spec.series_id for spec in normalized}) != len(normalized):
        raise ValueError("BLS source series IDs must be unique")
    return normalized


def parse_bls_latest_response(
    payload: Mapping[str, Any] | bytes | str,
    specs: BLSSeriesSpec | Iterable[BLSSeriesSpec],
    *,
    retrieved_at: datetime,
    provenance_label: str = LATEST_REVISED,
) -> list[VintageObservation]:
    """Parse BLS v2 data while refusing to imply historical availability."""

    require_latest_revised(provenance_label)
    retrieved = _aware_utc(retrieved_at, "retrieved_at")
    document = _json_mapping(payload)
    if document.get("status") != "REQUEST_SUCCEEDED":
        raise AgencyResponseError("BLS response did not report REQUEST_SUCCEEDED")
    results = document.get("Results")
    if not isinstance(results, Mapping) or not isinstance(results.get("series"), list):
        raise AgencyResponseError("BLS response must contain Results.series")

    spec_by_id = {spec.series_id: spec for spec in _normalize_bls_specs(specs)}
    parsed: list[VintageObservation] = []
    seen_series: set[str] = set()
    for raw_series in cast(list[object], results["series"]):
        if not isinstance(raw_series, Mapping):
            raise AgencyResponseError("each BLS series result must be an object")
        source_id = raw_series.get("seriesID")
        if not isinstance(source_id, str) or source_id not in spec_by_id:
            raise AgencyResponseError("BLS response contains an unrequested series")
        spec = spec_by_id[source_id]
        seen_series.add(source_id)
        data = raw_series.get("data")
        if not isinstance(data, list):
            raise AgencyResponseError("each BLS series result must contain a data array")
        for raw_row in data:
            if not isinstance(raw_row, Mapping):
                raise AgencyResponseError("each BLS observation must be an object")
            period = raw_row.get("period")
            year = raw_row.get("year")
            if not isinstance(period, str) or not isinstance(year, str):
                raise AgencyResponseError("BLS observations require year and period")
            if period == "M13":
                continue
            match = re.fullmatch(r"M(0[1-9]|1[0-2])", period)
            if match is None or not year.isdigit() or len(year) != 4:
                raise AgencyResponseError("BLS monthly observations require YYYY and M01-M12")
            observation_date = date(int(year), int(match.group(1)), 1)
            metadata: dict[str, Any] = {
                "api_mode": LATEST_REVISED,
                "availability_basis": "retrieval_timestamp_not_historical_release",
                "source_series_id": source_id,
                "period": period,
            }
            for name in ("periodName", "latest", "footnotes", "aspects"):
                if name in raw_row:
                    metadata[name] = raw_row[name]
            parsed.append(
                VintageObservation(
                    series_id=spec.output_series_id,
                    observation_date=observation_date,
                    realtime_start=retrieved.date(),
                    realtime_end=None,
                    availability_date=retrieved.date(),
                    release_timestamp=None,
                    availability_timestamp=retrieved,
                    value=_numeric_value(raw_row.get("value")),
                    units=spec.units,
                    frequency=spec.frequency,
                    seasonal_adjustment=spec.seasonal_adjustment,
                    transformation=spec.transformation,
                    download_timestamp=retrieved,
                    source="bls_public_data_api_v2",
                    provenance_label=LATEST_REVISED,
                    source_metadata=metadata,
                )
            )
    missing = set(spec_by_id).difference(seen_series)
    if missing:
        raise AgencyResponseError("BLS response omitted one or more requested series")
    return sorted(parsed, key=lambda row: (row.series_id, row.observation_date))


_QUARTER_PATTERN = re.compile(r"^(?P<year>\d{4})Q(?P<quarter>[1-4])$")


def parse_bea_latest_response(
    payload: Mapping[str, Any] | bytes | str,
    spec: BEASeriesSpec,
    *,
    retrieved_at: datetime,
    provenance_label: str = LATEST_REVISED,
) -> list[VintageObservation]:
    """Parse a current BEA NIPA table row with conservative availability."""

    require_latest_revised(provenance_label)
    retrieved = _aware_utc(retrieved_at, "retrieved_at")
    document = _json_mapping(payload)
    api = document.get("BEAAPI")
    if not isinstance(api, Mapping):
        raise AgencyResponseError("BEA response must contain BEAAPI")
    results = api.get("Results")
    if not isinstance(results, Mapping) or "Error" in results:
        raise AgencyResponseError("BEA response did not contain a successful result")
    data = results.get("Data")
    if not isinstance(data, list):
        raise AgencyResponseError("BEA response must contain Results.Data")

    parsed: list[VintageObservation] = []
    for raw_row in data:
        if not isinstance(raw_row, Mapping):
            raise AgencyResponseError("each BEA observation must be an object")
        if str(raw_row.get("TableName", spec.table_name)) != spec.table_name:
            continue
        if str(raw_row.get("LineNumber", "")) != spec.line_number:
            continue
        time_period = raw_row.get("TimePeriod")
        if not isinstance(time_period, str):
            raise AgencyResponseError("BEA observations require TimePeriod")
        match = _QUARTER_PATTERN.fullmatch(time_period)
        if match is None:
            raise AgencyResponseError("quarterly BEA TimePeriod must use YYYYQ1-YYYYQ4")
        quarter = int(match.group("quarter"))
        observation_date = date(int(match.group("year")), (quarter - 1) * 3 + 1, 1)
        metadata: dict[str, Any] = {
            "api_mode": LATEST_REVISED,
            "availability_basis": "retrieval_timestamp_not_historical_release",
            "dataset": "NIPA",
            "table_name": spec.table_name,
            "line_number": spec.line_number,
        }
        for name in (
            "SeriesCode",
            "LineDescription",
            "Metric_Name",
            "CL_UNIT",
            "UNIT_MULT",
        ):
            if name in raw_row:
                metadata[name] = raw_row[name]
        parsed.append(
            VintageObservation(
                series_id=spec.series_id,
                observation_date=observation_date,
                realtime_start=retrieved.date(),
                realtime_end=None,
                availability_date=retrieved.date(),
                release_timestamp=None,
                availability_timestamp=retrieved,
                value=_numeric_value(raw_row.get("DataValue")),
                units=spec.units,
                frequency=spec.frequency,
                seasonal_adjustment=spec.seasonal_adjustment,
                transformation=spec.transformation,
                download_timestamp=retrieved,
                source="bea_data_api_nipa",
                provenance_label=LATEST_REVISED,
                source_metadata=metadata,
            )
        )
    if not parsed:
        raise AgencyResponseError("BEA response omitted the requested table line")
    return sorted(parsed, key=lambda row: row.observation_date)


_RETRYABLE_STATUS_CODES = frozenset({408, 425, 429, 500, 502, 503, 504})


class _LatestAdapter:
    def __init__(
        self,
        *,
        provider: str,
        credential_env: str,
        terms_authorized: bool,
        endpoint: str,
        policy: AgencyRequestPolicy,
        transport: HTTPTransport | None,
        environ: Mapping[str, str] | None,
        sleep: Sleep,
        clock: Clock,
        now: Now,
    ) -> None:
        self._provider = provider
        self._credential_env = credential_env
        self._terms_authorized = terms_authorized
        self._endpoint = endpoint
        self._policy = policy
        self._transport = transport or urllib_transport
        self._environ = os.environ if environ is None else environ
        self._sleep = sleep
        self._clock = clock
        self._now = now
        self._last_request_started: float | None = None
        self._throttle_lock = threading.Lock()

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(provider={self._provider!r}, "
            f"terms_authorized={self._terms_authorized!r}, endpoint={self._endpoint!r}, "
            f"credential_env={self._credential_env!r})"
        )

    def _credential(self) -> str:
        if not self._terms_authorized:
            raise AgencyAuthorizationError(
                f"{self._provider} access is disabled until terms_authorized=True"
            )
        value = self._environ.get(self._credential_env)
        if not isinstance(value, str) or not value.strip():
            raise AgencyCredentialError(
                f"{self._provider} access requires environment variable {self._credential_env}"
            )
        return value.strip()

    def _throttle(self) -> None:
        with self._throttle_lock:
            current = self._clock()
            if self._last_request_started is not None:
                remaining = self._policy.min_interval_seconds - (
                    current - self._last_request_started
                )
                if remaining > 0:
                    self._sleep(remaining)
            self._last_request_started = self._clock()

    def _retry_after(self, response: HTTPResponse) -> float | None:
        raw_value = next(
            (value for name, value in response.headers.items() if name.lower() == "retry-after"),
            None,
        )
        if raw_value is None:
            return None
        try:
            seconds = float(raw_value)
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(raw_value)
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=UTC)
                seconds = (
                    retry_at.astimezone(UTC) - _aware_utc(self._now(), "now")
                ).total_seconds()
            except (TypeError, ValueError, OverflowError):
                return None
        if seconds < 0:
            return None
        return min(seconds, self._policy.max_retry_after_seconds)

    def _send(self, request: HTTPRequest) -> HTTPResponse:
        backoff = self._policy.initial_backoff_seconds
        for attempt in range(1, self._policy.max_attempts + 1):
            self._throttle()
            try:
                response = self._transport(request, self._policy.timeout_seconds)
            except Exception:
                if attempt == self._policy.max_attempts:
                    raise AgencyRequestError(
                        f"{self._provider} request failed after {attempt} attempts"
                    ) from None
                self._sleep(backoff)
                backoff *= self._policy.backoff_multiplier
                continue
            if 200 <= response.status_code < 300:
                return response
            if response.status_code not in _RETRYABLE_STATUS_CODES:
                raise AgencyRequestError(
                    f"{self._provider} request failed with HTTP {response.status_code}"
                )
            if attempt == self._policy.max_attempts:
                raise AgencyRequestError(
                    f"{self._provider} request failed after {attempt} attempts "
                    f"(HTTP {response.status_code})"
                )
            retry_after = self._retry_after(response)
            self._sleep(backoff if retry_after is None else retry_after)
            backoff *= self._policy.backoff_multiplier
        raise AssertionError("unreachable")


class BLSLatestAdapter(_LatestAdapter):
    """Fail-closed adapter for the registered BLS current-data API."""

    def __init__(
        self,
        config: BLSLatestConfig | None = None,
        *,
        transport: HTTPTransport | None = None,
        environ: Mapping[str, str] | None = None,
        sleep: Sleep = time.sleep,
        clock: Clock = time.monotonic,
        now: Now = lambda: datetime.now(UTC),
    ) -> None:
        self.config = config or BLSLatestConfig()
        super().__init__(
            provider="BLS",
            credential_env=BLS_REGISTRATION_KEY_ENV,
            terms_authorized=self.config.terms_authorized,
            endpoint=self.config.endpoint,
            policy=self.config.request_policy,
            transport=transport,
            environ=environ,
            sleep=sleep,
            clock=clock,
            now=now,
        )

    def fetch(
        self,
        specs: BLSSeriesSpec | Iterable[BLSSeriesSpec],
        *,
        start_year: int,
        end_year: int,
        provenance_label: str = LATEST_REVISED,
    ) -> list[VintageObservation]:
        credential = self._credential()
        require_latest_revised(provenance_label)
        normalized = _normalize_bls_specs(specs)
        request = build_bls_latest_request(
            (spec.series_id for spec in normalized),
            start_year=start_year,
            end_year=end_year,
            registration_key=credential,
            endpoint=self.config.endpoint,
        )
        response = self._send(request)
        return parse_bls_latest_response(
            response.body,
            normalized,
            retrieved_at=self._now(),
            provenance_label=provenance_label,
        )


class BEALatestAdapter(_LatestAdapter):
    """Fail-closed adapter for current BEA NIPA table data."""

    def __init__(
        self,
        config: BEALatestConfig | None = None,
        *,
        transport: HTTPTransport | None = None,
        environ: Mapping[str, str] | None = None,
        sleep: Sleep = time.sleep,
        clock: Clock = time.monotonic,
        now: Now = lambda: datetime.now(UTC),
    ) -> None:
        self.config = config or BEALatestConfig()
        super().__init__(
            provider="BEA",
            credential_env=BEA_API_KEY_ENV,
            terms_authorized=self.config.terms_authorized,
            endpoint=self.config.endpoint,
            policy=self.config.request_policy,
            transport=transport,
            environ=environ,
            sleep=sleep,
            clock=clock,
            now=now,
        )

    def fetch(
        self,
        spec: BEASeriesSpec,
        *,
        years: Iterable[int] | str,
        provenance_label: str = LATEST_REVISED,
    ) -> list[VintageObservation]:
        credential = self._credential()
        require_latest_revised(provenance_label)
        request = build_bea_latest_request(
            api_key=credential,
            table_name=spec.table_name,
            years=years,
            frequency="Q",
            endpoint=self.config.endpoint,
        )
        response = self._send(request)
        return parse_bea_latest_response(
            response.body,
            spec,
            retrieved_at=self._now(),
            provenance_label=provenance_label,
        )


class ArchiveKind(StrEnum):
    BLS_CES_VINTAGE = "bls_ces_vintage"
    BLS_CPI_SUPPLEMENTAL = "bls_cpi_supplemental"
    BEA_GDP = "bea_gdp_archive"
    UMICH_SENTIMENT_PUBLIC_REPORTS = "umich_sentiment_public_reports"


@dataclass(frozen=True, slots=True)
class ArchiveManifest:
    """Discovery metadata only; a manifest does not authorize ingestion."""

    kind: ArchiveKind
    provider: str
    official_index_url: str
    formats: tuple[str, ...]
    coverage_start: date | None
    coverage_note: str
    default_enabled: bool = False
    coverage_audited: bool = False

    def __post_init__(self) -> None:
        if not self.official_index_url.startswith("https://"):
            raise ValueError("archive URL must use HTTPS")
        if not self.formats:
            raise ValueError("archive formats cannot be empty")
        if self.default_enabled:
            raise ValueError("agency archive ingestion cannot be enabled by default")


BLS_CES_VINTAGE_ARCHIVE = ArchiveManifest(
    kind=ArchiveKind.BLS_CES_VINTAGE,
    provider="BLS",
    official_index_url="https://www.bls.gov/web/empsit/cesvindata.htm",
    formats=("xlsx", "csv", "zip"),
    coverage_start=date(2003, 6, 6),
    coverage_note=(
        "Published-value snapshots begin with the May 2003 estimate release; "
        "older reference observations in a sheet are not older publication snapshots."
    ),
)
BLS_CPI_SUPPLEMENTAL_ARCHIVE = ArchiveManifest(
    kind=ArchiveKind.BLS_CPI_SUPPLEMENTAL,
    provider="BLS",
    official_index_url="https://www.bls.gov/cpi/tables/supplemental-files/home.htm",
    formats=("xlsx", "zip"),
    coverage_start=date(2012, 1, 1),
    coverage_note=(
        "The official annual ZIP listing starts in 2012; file layouts and missing months "
        "must be audited, and later editions can revise seasonally adjusted history."
    ),
)
BEA_GDP_ARCHIVE = ArchiveManifest(
    kind=ArchiveKind.BEA_GDP,
    provider="BEA",
    official_index_url="https://apps.bea.gov/histdata/",
    formats=("html", "xlsx", "zip"),
    coverage_start=None,
    coverage_note=(
        "Coverage depends on the selected NIPA table and archive product; no complete "
        "machine-readable vintage span is asserted until a release-by-release audit."
    ),
)
UMICH_SENTIMENT_PUBLIC_REPORTS = ArchiveManifest(
    kind=ArchiveKind.UMICH_SENTIMENT_PUBLIC_REPORTS,
    provider="University of Michigan Surveys of Consumers",
    official_index_url="https://data.sca.isr.umich.edu/",
    formats=("html", "pdf"),
    coverage_start=date(1991, 1, 1),
    coverage_note=(
        "Historical preliminary/final release dates are public, but the website usage "
        "agreement restricts reproduction, retransmission, distribution, publication, "
        "and broadcast without express written consent. Public visibility alone is not "
        "treated as permission to build or distribute a historical release archive."
    ),
)
ARCHIVE_MANIFESTS = (
    BLS_CES_VINTAGE_ARCHIVE,
    BLS_CPI_SUPPLEMENTAL_ARCHIVE,
    BEA_GDP_ARCHIVE,
    UMICH_SENTIMENT_PUBLIC_REPORTS,
)


@dataclass(frozen=True, slots=True)
class ArchiveIngestionApproval:
    """Three independent gates required before an archive parser may run."""

    terms_authorized: bool = False
    opt_in: bool = False
    coverage_audited: bool = False


def require_archive_ingestion_approval(approval: ArchiveIngestionApproval) -> None:
    """Fail closed unless terms, operator opt-in, and coverage audit are explicit."""

    if not approval.terms_authorized:
        raise AgencyAuthorizationError("archive source terms have not been authorized")
    if not approval.opt_in:
        raise AgencyAuthorizationError("archive ingestion requires explicit opt-in")
    if not approval.coverage_audited:
        raise AgencyAuthorizationError("archive ingestion requires a recorded coverage audit")


@dataclass(frozen=True, slots=True)
class UMichSentimentIngestionApproval:
    """Source-specific gates for copyrighted Surveys of Consumers materials."""

    terms_reviewed: bool = False
    written_permission_reference: str | None = None
    organization_scope_confirmed: bool = False
    opt_in: bool = False
    coverage_audited: bool = False


def require_umich_sentiment_ingestion_approval(
    approval: UMichSentimentIngestionApproval,
) -> None:
    """Require documented written consent in addition to ordinary archive gates."""

    if not approval.terms_reviewed:
        raise AgencyAuthorizationError("Michigan sentiment usage agreement is not reviewed")
    if (
        not isinstance(approval.written_permission_reference, str)
        or not approval.written_permission_reference.strip()
    ):
        raise AgencyAuthorizationError(
            "Michigan sentiment ingestion requires an express written permission reference"
        )
    if not approval.organization_scope_confirmed:
        raise AgencyAuthorizationError(
            "Michigan sentiment permission scope has not been matched to this organization"
        )
    if not approval.opt_in:
        raise AgencyAuthorizationError("Michigan sentiment ingestion requires explicit opt-in")
    if not approval.coverage_audited:
        raise AgencyAuthorizationError(
            "Michigan sentiment ingestion requires a release-by-release coverage audit"
        )


class AgencyArchiveParser(Protocol):
    """Contract for future audited CES, CPI, and GDP archive parsers."""

    def parse(
        self,
        payload: bytes,
        *,
        manifest: ArchiveManifest,
        approval: ArchiveIngestionApproval,
        retrieved_at: datetime,
        release_timestamp: datetime,
    ) -> list[VintageObservation]: ...


# Concise aliases for callers that use parser/client terminology.
parse_bls_latest = parse_bls_latest_response
parse_bea_latest = parse_bea_latest_response
BLSLatestAPI = BLSLatestAdapter
BEALatestAPI = BEALatestAdapter
