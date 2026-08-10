"""Acquire, audit, and parse official daily Treasury 10-year CMT observations.

The Treasury XML feed is a history of daily market observations, not a database
of successive publication vintages.  That distinction is material: a daily CMT
observation is usable as a point-in-time predictor after its source date, but a
later correction cannot be reconstructed from this feed.  Canonical rows use a
conservative same-day New York end-of-day availability timestamp and retain the
feed update timestamp and this limitation in their source metadata.

Network access is confined to :func:`acquire_treasury_rates_archive`.  Parsing
and auditing are deterministic and offline, and every downloaded year is pinned
by SHA-256 in ``release-index.json``.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from datetime import time as datetime_time
from pathlib import Path
from typing import Final
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

from macro_nowcast.schema import VintageObservation

TREASURY_10Y_SERIES_ID: Final = "TREASURY_10Y_CMT"
TREASURY_RATES_SOURCE: Final = "US_TREASURY_DAILY_PAR_YIELD_CURVE"
TREASURY_RATES_PROVENANCE: Final = "official_agency_archive"
TREASURY_RATES_DIRECTORY: Final = "treasury-yield-curve"
TREASURY_RATES_INDEX_URL: Final = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
    "daily-treasury-rate-archives"
)
TREASURY_RATES_FEED_DOCUMENTATION_URL: Final = (
    "https://home.treasury.gov/treasury-daily-interest-rate-xml-feed"
)
TREASURY_RATES_METHOD_URL: Final = (
    "https://home.treasury.gov/policy-issues/financing-the-government/"
    "interest-rate-statistics"
)
TREASURY_RATES_FAQ_URL: Final = (
    "https://home.treasury.gov/policy-issues/financing-the-government/"
    "interest-rate-statistics/interest-rates-frequently-asked-questions"
)
TREASURY_RATES_FEED_URL_TEMPLATE: Final = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
    "pages/xml?data=daily_treasury_yield_curve&field_tdr_date_value={year}"
)
TREASURY_RATES_TIMING_QUALITY: Final = (
    "official_source_date_conservative_America_New_York_EOD"
)
TREASURY_RATES_AVAILABILITY_RULE: Final = (
    "source_date_23_59_59_999999_America_New_York; exact publication clock unavailable"
)

_ATOM_NS = "http://www.w3.org/2005/Atom"
_DATA_NS = "http://schemas.microsoft.com/ado/2007/08/dataservices"
_USER_AGENT = "macro-nowcast-research/0.1 (public Treasury data verification)"
_NEW_YORK = ZoneInfo("America/New_York")


class TreasuryRatesArchiveError(RuntimeError):
    """Raised when Treasury rate data cannot be used without guessing."""


@dataclass(frozen=True, slots=True)
class TreasuryRateFeed:
    """Parsed identity and 10-year observations from one year-specific feed."""

    requested_year: int
    feed_updated: datetime
    observations: tuple[tuple[date, float], ...]


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _feed_url(year: int) -> str:
    return TREASURY_RATES_FEED_URL_TEMPLATE.format(year=year)


def _parse_utc(value: str) -> datetime:
    normalized = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise TreasuryRatesArchiveError(f"invalid Treasury feed timestamp: {value}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _child_text(properties: ElementTree.Element, local_name: str) -> str | None:
    node = properties.find(f"{{{_DATA_NS}}}{local_name}")
    if node is None or node.text is None or not node.text.strip():
        return None
    return node.text.strip()


def parse_treasury_rate_feed(payload: bytes, *, requested_year: int) -> TreasuryRateFeed:
    """Parse one official year-specific XML feed and retain the 10-year CMT."""

    if requested_year < 1990:
        raise ValueError("Treasury par-yield history begins in 1990")
    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError as exc:
        raise TreasuryRatesArchiveError("invalid Treasury XML feed") from exc
    if root.tag != f"{{{_ATOM_NS}}}feed":
        raise TreasuryRatesArchiveError("Treasury XML root is not an Atom feed")
    title = root.findtext(f"{{{_ATOM_NS}}}title", default="").strip()
    if title != "DailyTreasuryYieldCurveRateData":
        raise TreasuryRatesArchiveError(f"unexpected Treasury feed title: {title}")
    updated_text = root.findtext(f"{{{_ATOM_NS}}}updated", default="").strip()
    if not updated_text:
        raise TreasuryRatesArchiveError("Treasury feed has no update timestamp")
    rows: dict[date, float] = {}
    for entry in root.findall(f"{{{_ATOM_NS}}}entry"):
        properties = entry.find(
            f"{{{_ATOM_NS}}}content/"
            "{http://schemas.microsoft.com/ado/2007/08/dataservices/metadata}properties"
        )
        if properties is None:
            raise TreasuryRatesArchiveError("Treasury feed entry has no properties")
        date_text = _child_text(properties, "NEW_DATE")
        value_text = _child_text(properties, "BC_10YEAR")
        if date_text is None:
            raise TreasuryRatesArchiveError("Treasury feed entry has no source date")
        try:
            observation_date = datetime.fromisoformat(date_text).date()
        except ValueError as exc:
            raise TreasuryRatesArchiveError(
                f"invalid Treasury observation date: {date_text}"
            ) from exc
        if observation_date.year != requested_year:
            raise TreasuryRatesArchiveError(
                f"Treasury year feed {requested_year} contains {observation_date}"
            )
        if value_text is None:
            continue
        try:
            value = float(value_text)
        except ValueError as exc:
            raise TreasuryRatesArchiveError(
                f"invalid 10-year Treasury value on {observation_date}: {value_text}"
            ) from exc
        if not -10.0 <= value <= 30.0:
            raise TreasuryRatesArchiveError(
                f"implausible 10-year Treasury value on {observation_date}: {value}"
            )
        if observation_date in rows:
            raise TreasuryRatesArchiveError(
                f"duplicate Treasury observation date: {observation_date}"
            )
        rows[observation_date] = value
    if not rows:
        raise TreasuryRatesArchiveError(
            f"Treasury feed for {requested_year} has no 10-year observations"
        )
    return TreasuryRateFeed(
        requested_year=requested_year,
        feed_updated=_parse_utc(updated_text),
        observations=tuple(sorted(rows.items())),
    )


def _manifest_year(entry: Mapping[str, object]) -> int:
    try:
        year = int(entry["year"])
    except (KeyError, TypeError, ValueError) as exc:
        raise TreasuryRatesArchiveError("invalid Treasury manifest year entry") from exc
    expected = f"years/{year}.xml"
    if str(entry.get("path")) != expected:
        raise TreasuryRatesArchiveError(
            f"Treasury manifest path mismatch for {year}: {entry.get('path')}"
        )
    if str(entry.get("url")) != _feed_url(year):
        raise TreasuryRatesArchiveError(f"Treasury manifest URL mismatch for {year}")
    return year


def _load_manifest(root: Path) -> tuple[dict[str, object], list[Mapping[str, object]]]:
    try:
        manifest = json.loads((root / "release-index.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TreasuryRatesArchiveError(
            "Treasury release-index.json is missing or invalid"
        ) from exc
    entries = manifest.get("years")
    if not isinstance(entries, list) or not entries:
        raise TreasuryRatesArchiveError("Treasury manifest contains no year feeds")
    if any(not isinstance(entry, Mapping) for entry in entries):
        raise TreasuryRatesArchiveError("invalid Treasury manifest year entry")
    return manifest, entries  # type: ignore[return-value]


def _availability_timestamp(observation_date: date) -> datetime:
    return datetime.combine(
        observation_date,
        datetime_time.max,
        tzinfo=_NEW_YORK,
    ).astimezone(UTC)


def parse_treasury_rates_archive(directory: str | Path) -> list[VintageObservation]:
    """Parse a manifest-hashed local Treasury archive into canonical daily rows."""

    root = Path(directory).resolve()
    _, entries = _load_manifest(root)
    rows: list[VintageObservation] = []
    seen_dates: set[date] = set()
    for entry in sorted(entries, key=_manifest_year):
        year = _manifest_year(entry)
        path = root / str(entry["path"])
        payload = path.read_bytes()
        digest = _sha256_bytes(payload)
        if digest != str(entry.get("sha256")):
            raise TreasuryRatesArchiveError(f"Treasury hash mismatch for {year}")
        feed = parse_treasury_rate_feed(payload, requested_year=year)
        if feed.feed_updated.isoformat() != str(entry.get("feed_updated")):
            raise TreasuryRatesArchiveError(f"Treasury feed-update mismatch for {year}")
        if len(feed.observations) != int(entry.get("observation_count", -1)):
            raise TreasuryRatesArchiveError(f"Treasury observation-count mismatch for {year}")
        downloaded_at = datetime.fromtimestamp(path.stat().st_mtime, UTC)
        for observation_date, value in feed.observations:
            if observation_date in seen_dates:
                raise TreasuryRatesArchiveError(
                    f"duplicate Treasury date across year feeds: {observation_date}"
                )
            seen_dates.add(observation_date)
            available_at = _availability_timestamp(observation_date)
            rows.append(
                VintageObservation(
                    series_id=TREASURY_10Y_SERIES_ID,
                    observation_date=observation_date,
                    realtime_start=observation_date,
                    realtime_end=None,
                    availability_date=available_at.date(),
                    value=value,
                    units="percent_per_annum_bond_equivalent_yield",
                    frequency="daily",
                    seasonal_adjustment="not_applicable",
                    transformation="level",
                    source=TREASURY_RATES_SOURCE,
                    provenance_label=TREASURY_RATES_PROVENANCE,
                    download_timestamp=downloaded_at,
                    release_timestamp=None,
                    availability_timestamp=available_at,
                    source_metadata={
                        "agency": "U.S. Department of the Treasury",
                        "agency_series": "10-Year Treasury Constant Maturity Rate",
                        "official_url": str(entry["url"]),
                        "source_file": str(entry["path"]),
                        "source_sha256": digest,
                        "feed_updated": feed.feed_updated.isoformat(),
                        "market_quote_time": "approximately 15:30 America/New_York",
                        "timing_quality": TREASURY_RATES_TIMING_QUALITY,
                        "availability_rule": TREASURY_RATES_AVAILABILITY_RULE,
                        "publication_vintage_dimension_available": False,
                        "later_correction_history_available": False,
                        "source_semantics": "daily_point_in_time_market_observation",
                        "methodology_url": TREASURY_RATES_METHOD_URL,
                        "faq_url": TREASURY_RATES_FAQ_URL,
                    },
                )
            )
    return sorted(rows, key=lambda row: row.observation_date)


def audit_treasury_rates_archive(directory: str | Path) -> dict[str, object]:
    """Verify year inventory, hashes, XML identity, chronology, and canonical rows."""

    root = Path(directory).resolve()
    manifest, entries = _load_manifest(root)
    expected: set[Path] = set()
    years: list[int] = []
    hashes: set[str] = set()
    update_timestamps: set[str] = set()
    counts: dict[str, int] = {}
    for entry in entries:
        year = _manifest_year(entry)
        years.append(year)
        path = (root / str(entry["path"])).resolve()
        expected.add(path)
        payload = path.read_bytes()
        digest = _sha256_bytes(payload)
        if digest != str(entry.get("sha256")):
            raise TreasuryRatesArchiveError(f"Treasury hash mismatch for {year}")
        if digest in hashes:
            raise TreasuryRatesArchiveError(f"duplicate Treasury year payload: {year}")
        hashes.add(digest)
        feed = parse_treasury_rate_feed(payload, requested_year=year)
        if feed.feed_updated.isoformat() != str(entry.get("feed_updated")):
            raise TreasuryRatesArchiveError(f"Treasury feed-update mismatch for {year}")
        if len(feed.observations) != int(entry.get("observation_count", -1)):
            raise TreasuryRatesArchiveError(f"Treasury observation-count mismatch for {year}")
        update_timestamps.add(feed.feed_updated.isoformat())
        counts[str(year)] = len(feed.observations)
    if len(years) != len(set(years)):
        raise TreasuryRatesArchiveError("duplicate Treasury year manifest entries")
    ordered_years = sorted(years)
    expected_years = list(range(ordered_years[0], ordered_years[-1] + 1))
    if ordered_years != expected_years:
        raise TreasuryRatesArchiveError("Treasury year inventory is not contiguous")
    actual = {path.resolve() for path in (root / "years").glob("*.xml") if path.is_file()}
    missing = sorted(str(path.relative_to(root)) for path in expected - actual)
    extra = sorted(str(path.relative_to(root)) for path in actual - expected)
    if missing or extra:
        raise TreasuryRatesArchiveError(
            f"Treasury inventory mismatch: missing={missing[:3]}, extra={extra[:3]}"
        )
    observations = parse_treasury_rates_archive(root)
    dates = [row.observation_date for row in observations]
    if dates != sorted(set(dates)):
        raise TreasuryRatesArchiveError("Treasury canonical dates are not unique and sorted")
    if any(row.release_timestamp is not None for row in observations):
        raise TreasuryRatesArchiveError("Treasury point observations must not invent releases")
    if any(
        row.availability_timestamp != _availability_timestamp(row.observation_date)
        for row in observations
    ):
        raise TreasuryRatesArchiveError("Treasury EOD availability convention drifted")
    return {
        "passed": True,
        "official_url": TREASURY_RATES_INDEX_URL,
        "feed_documentation": TREASURY_RATES_FEED_DOCUMENTATION_URL,
        "methodology": TREASURY_RATES_METHOD_URL,
        "directory": root.name,
        "manifest_schema_version": manifest.get("schema_version"),
        "year_count": len(ordered_years),
        "first_year": ordered_years[0],
        "last_year": ordered_years[-1],
        "observations_by_year": counts,
        "canonical_observation_rows": len(observations),
        "first_observation_date": dates[0].isoformat(),
        "last_observation_date": dates[-1].isoformat(),
        "all_year_hashes_unique": len(hashes) == len(entries),
        "feed_update_timestamps": sorted(update_timestamps),
        "series_id": TREASURY_10Y_SERIES_ID,
        "timing_quality": TREASURY_RATES_TIMING_QUALITY,
        "availability_rule": TREASURY_RATES_AVAILABILITY_RULE,
        "exact_publication_clock_claimed": False,
        "publication_vintage_dimension_available": False,
        "later_correction_history_available": False,
        "point_in_time_market_observation_semantics": True,
        "server_original_bytes_claimed": True,
        "provenance_status": (
            "official_year_feed_hashes_values_and_conservative_availability_verified"
        ),
    }


def _fetch(url: str, *, attempts: int = 5) -> tuple[bytes, str]:
    for attempt in range(attempts):
        request = Request(url, headers={"User-Agent": _USER_AGENT})
        try:
            with urlopen(request, timeout=60) as response:
                return response.read(), response.headers.get_content_type()
        except HTTPError as exc:
            if exc.code not in {429, 500, 502, 503, 504} or attempt == attempts - 1:
                raise TreasuryRatesArchiveError(
                    f"Treasury request failed: {url} ({exc.code})"
                ) from exc
            retry_after = exc.headers.get("Retry-After")
            delay = float(retry_after) if retry_after and retry_after.isdigit() else 2**attempt
        except (TimeoutError, URLError) as exc:
            if attempt == attempts - 1:
                raise TreasuryRatesArchiveError(f"Treasury request failed: {url}") from exc
            delay = 2**attempt
        time.sleep(min(delay, 16))
    raise AssertionError("unreachable")


def _write_immutable(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise TreasuryRatesArchiveError(f"refusing to replace immutable raw file: {path}")
        return
    temporary = path.with_suffix(f"{path.suffix}.part")
    temporary.write_bytes(payload)
    temporary.replace(path)


def acquire_treasury_rates_archive(
    output_dir: str | Path,
    *,
    start_year: int = 2002,
    end_year: int | None = None,
) -> dict[str, object]:
    """Download, pin, parse-check, and audit year-specific official XML feeds."""

    final_year = end_year or datetime.now(UTC).year
    if start_year < 1990 or final_year < start_year:
        raise ValueError("Treasury years must satisfy 1990 <= start_year <= end_year")
    root = Path(output_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, object]] = []
    for year in range(start_year, final_year + 1):
        url = _feed_url(year)
        path = root / "years" / f"{year}.xml"
        if path.exists():
            payload = path.read_bytes()
            content_type = "text/xml"
        else:
            payload, content_type = _fetch(url)
            _write_immutable(path, payload)
            time.sleep(0.05)
        feed = parse_treasury_rate_feed(payload, requested_year=year)
        entries.append(
            {
                "year": year,
                "url": url,
                "content_type": content_type,
                "path": path.relative_to(root).as_posix(),
                "bytes": len(payload),
                "sha256": _sha256_bytes(payload),
                "feed_updated": feed.feed_updated.isoformat(),
                "observation_count": len(feed.observations),
                "first_observation_date": feed.observations[0][0].isoformat(),
                "last_observation_date": feed.observations[-1][0].isoformat(),
            }
        )
    manifest = {
        "schema_version": 1,
        "source": TREASURY_RATES_SOURCE,
        "source_index": TREASURY_RATES_INDEX_URL,
        "feed_documentation": TREASURY_RATES_FEED_DOCUMENTATION_URL,
        "methodology": TREASURY_RATES_METHOD_URL,
        "series_id": TREASURY_10Y_SERIES_ID,
        "acquired_at": datetime.now(UTC).isoformat(),
        "api_credentials_used": False,
        "api_txt_read": False,
        "availability_rule": TREASURY_RATES_AVAILABILITY_RULE,
        "publication_vintage_dimension_available": False,
        "later_correction_history_available": False,
        "years": entries,
    }
    manifest_path = root / "release-index.json"
    payload = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    if manifest_path.exists():
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        existing.pop("acquired_at", None)
        comparison = dict(manifest)
        comparison.pop("acquired_at", None)
        if existing != comparison:
            raise TreasuryRatesArchiveError(
                "refusing to replace Treasury manifest with changed immutable inputs"
            )
    else:
        _write_immutable(manifest_path, payload)
    audit = audit_treasury_rates_archive(root)
    return {
        "status": "complete",
        "output_dir": str(root),
        "year_count": audit["year_count"],
        "observation_rows": audit["canonical_observation_rows"],
        "first_observation_date": audit["first_observation_date"],
        "last_observation_date": audit["last_observation_date"],
        "series_id": TREASURY_10Y_SERIES_ID,
        "api_credentials_used": False,
        "api_txt_read": False,
    }


__all__ = [
    "TREASURY_10Y_SERIES_ID",
    "TREASURY_RATES_AVAILABILITY_RULE",
    "TREASURY_RATES_DIRECTORY",
    "TREASURY_RATES_FEED_DOCUMENTATION_URL",
    "TREASURY_RATES_INDEX_URL",
    "TREASURY_RATES_METHOD_URL",
    "TREASURY_RATES_SOURCE",
    "TREASURY_RATES_TIMING_QUALITY",
    "TreasuryRateFeed",
    "TreasuryRatesArchiveError",
    "acquire_treasury_rates_archive",
    "audit_treasury_rates_archive",
    "parse_treasury_rate_feed",
    "parse_treasury_rates_archive",
]
