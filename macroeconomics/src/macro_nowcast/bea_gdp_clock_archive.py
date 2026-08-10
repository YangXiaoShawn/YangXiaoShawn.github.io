"""Offline audit of official BEA GDP release-header clock evidence."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Final
from zoneinfo import ZoneInfo

BEA_GDP_CLOCK_DIRECTORY: Final = "bea-gdp-news"
BEA_GDP_CLOCK_FILENAME: Final = "clock-evidence.json"
BEA_GDP_CLOCK_SOURCE: Final = "BEA_GDP_NEWS_RELEASE_HEADER_EVIDENCE"
BEA_GDP_CLOCK_INDEX_URL: Final = "https://www.bea.gov/news/archive"
BEA_GDP_CLOCK_TIMING_QUALITY: Final = (
    "official_embargo_header_clock_America_New_York"
)

_NEW_YORK = ZoneInfo("America/New_York")
_CLOCK_RE = re.compile(
    r"(?P<hour>\d{1,2}):(?P<minute>\d{2})\s*"
    r"(?P<meridiem>a\.?\s*m\.?|p\.?\s*m\.?)\s*"
    r"(?P<timezone>EST|EDT)\b",
    re.IGNORECASE,
)
_DATE_RE = re.compile(
    r"(?P<weekday>Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)"
    r"\s*,\s*"
    r"(?P<month>January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+"
    r"(?P<day>\d{1,2}),\s*(?P<year>\d{4})",
    re.IGNORECASE,
)
_ALLOWED_FORMATS = {"browser_rendered_html_header_text_extraction"}


class BEAGDPClockArchiveError(ValueError):
    """Raised when BEA header evidence cannot prove its claimed release clock."""


@dataclass(frozen=True, slots=True)
class BEAReleaseClock:
    """One release instant proven by a BEA news-release header."""

    release_date: date
    release_timestamp: datetime
    printed_timezone: str
    printed_weekday: str
    timing_quality: str = BEA_GDP_CLOCK_TIMING_QUALITY


@dataclass(frozen=True, slots=True)
class BEAGDPClockArchive:
    """Verified GDP release clocks and immutable acquisition metadata."""

    clocks: Mapping[date, BEAReleaseClock]
    event_metadata: Mapping[date, Mapping[str, object]]
    retrieved_at: str
    evidence_sha256: str
    source_release_index_sha256: str


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def parse_bea_release_header(
    header_text: str,
    *,
    expected_release_date: date,
) -> BEAReleaseClock:
    """Parse a BEA wire/embargo header and verify its date, weekday, and zone."""

    if not re.search(
        r"FOR WIRE TRANSMISSION|EMBARGOED (?:UNTIL|FOR) RELEASE",
        header_text,
        re.IGNORECASE,
    ):
        raise BEAGDPClockArchiveError("BEA evidence is not a recognized release header")
    clock_match = _CLOCK_RE.search(header_text)
    if clock_match is None:
        raise BEAGDPClockArchiveError("BEA release header has no EST/EDT clock")
    date_match = _DATE_RE.search(header_text, clock_match.end())
    if date_match is None:
        raise BEAGDPClockArchiveError("BEA release header has no weekday and date")

    parsed_date = datetime.strptime(
        "{} {} {}".format(
            date_match.group("month").title(),
            date_match.group("day"),
            date_match.group("year"),
        ),
        "%B %d %Y",
    ).date()
    if parsed_date != expected_release_date:
        raise BEAGDPClockArchiveError(
            "BEA release date mismatch: "
            f"expected {expected_release_date}, found {parsed_date}"
        )
    printed_weekday = date_match.group("weekday").title()
    if parsed_date.strftime("%A") != printed_weekday:
        raise BEAGDPClockArchiveError(
            "BEA release weekday conflicts with its printed date"
        )

    hour = int(clock_match.group("hour"))
    minute = int(clock_match.group("minute"))
    if not 1 <= hour <= 12 or not 0 <= minute <= 59:
        raise BEAGDPClockArchiveError("BEA release clock is outside 12-hour bounds")
    meridiem = re.sub(r"[.\s]", "", clock_match.group("meridiem")).lower()
    if meridiem == "pm" and hour != 12:
        hour += 12
    elif meridiem == "am" and hour == 12:
        hour = 0
    local = datetime(
        parsed_date.year,
        parsed_date.month,
        parsed_date.day,
        hour,
        minute,
        tzinfo=_NEW_YORK,
    )
    printed_timezone = clock_match.group("timezone").upper()
    if local.tzname() != printed_timezone:
        raise BEAGDPClockArchiveError(
            "BEA release timezone label conflicts with America/New_York: "
            f"printed {printed_timezone}, calendar implies {local.tzname()}"
        )
    return BEAReleaseClock(
        release_date=parsed_date,
        release_timestamp=local.astimezone(UTC),
        printed_timezone=printed_timezone,
        printed_weekday=printed_weekday,
    )


def _validated_document(path: Path) -> tuple[dict[str, object], bytes]:
    payload = path.read_bytes()
    try:
        document = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise BEAGDPClockArchiveError("GDP clock evidence is not valid JSON") from exc
    if not isinstance(document, dict):
        raise BEAGDPClockArchiveError("GDP clock evidence must be a JSON object")
    expected = {
        "schema_version": 1,
        "status": "complete",
        "source_index_url": BEA_GDP_CLOCK_INDEX_URL,
        "source_home_url": "https://www.bea.gov/",
        "acquisition_format": "browser_rendered_embargo_header_text_extraction",
        "server_original_bytes_claimed": False,
        "complete_dom_claimed": False,
    }
    for field, expected_value in expected.items():
        if document.get(field) != expected_value:
            raise BEAGDPClockArchiveError(
                f"GDP clock evidence field {field!r} is not {expected_value!r}"
            )
    if not isinstance(document.get("retrieved_at"), str):
        raise BEAGDPClockArchiveError("GDP clock evidence has no retrieval timestamp")
    events = document.get("events")
    inventory = document.get("source_release_index_inventory")
    expected_count = document.get("expected_event_count")
    archive_count = document.get("archive_initial_event_count")
    current_count = document.get("current_event_count")
    if (
        not isinstance(events, list)
        or not events
        or not isinstance(expected_count, int)
        or expected_count != len(events)
        or not isinstance(archive_count, int)
        or not isinstance(current_count, int)
        or archive_count + current_count != len(events)
    ):
        raise BEAGDPClockArchiveError("GDP clock evidence event counts disagree")
    if not isinstance(document.get("archive_filter_page_count"), int):
        raise BEAGDPClockArchiveError("GDP clock evidence has no archive-page count")
    if not isinstance(inventory, list) or len(inventory) != len(events):
        raise BEAGDPClockArchiveError("GDP source index inventory is incomplete")
    inventory_payload = json.dumps(
        inventory,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    if document.get("source_release_index_sha256") != _sha256_bytes(inventory_payload):
        raise BEAGDPClockArchiveError("GDP source release-index hash mismatch")
    return document, payload


def parse_bea_gdp_clock_archive(
    path: str | Path,
    *,
    expected_initial_releases: Mapping[date, str] | None = None,
) -> BEAGDPClockArchive:
    """Parse all 98 saved GDP initial-release headers and reconcile source evidence."""

    document, payload = _validated_document(Path(path))
    raw_events = document["events"]
    inventory = document["source_release_index_inventory"]
    assert isinstance(raw_events, list)
    assert isinstance(inventory, list)
    clocks: dict[date, BEAReleaseClock] = {}
    metadata: dict[date, Mapping[str, object]] = {}
    header_hashes: set[str] = set()
    inventory_by_url = {
        str(item.get("official_url")): item
        for item in inventory
        if isinstance(item, dict)
    }
    if len(inventory_by_url) != len(inventory):
        raise BEAGDPClockArchiveError("GDP source inventory contains duplicate URLs")
    for raw_event in raw_events:
        if not isinstance(raw_event, dict):
            raise BEAGDPClockArchiveError("GDP clock evidence contains a non-object event")
        try:
            release_date = date.fromisoformat(str(raw_event["release_date"]))
        except (KeyError, ValueError) as exc:
            raise BEAGDPClockArchiveError("GDP clock event has an invalid date") from exc
        if release_date in clocks:
            raise BEAGDPClockArchiveError(f"duplicate GDP clock event: {release_date}")
        header_text = raw_event.get("header_text")
        header_sha256 = raw_event.get("header_sha256")
        evidence_format = raw_event.get("evidence_format")
        if not isinstance(header_text, str) or not header_text:
            raise BEAGDPClockArchiveError(f"GDP clock event has no header: {release_date}")
        if evidence_format not in _ALLOWED_FORMATS:
            raise BEAGDPClockArchiveError(
                f"GDP clock event has unsupported evidence format: {release_date}"
            )
        calculated_hash = _sha256_bytes(header_text.encode())
        if header_sha256 != calculated_hash:
            raise BEAGDPClockArchiveError(
                f"GDP clock event header hash mismatch: {release_date}"
            )
        if calculated_hash in header_hashes:
            raise BEAGDPClockArchiveError("GDP clock evidence contains duplicate headers")
        header_hashes.add(calculated_hash)
        label = raw_event.get("observation_label")
        release_type = raw_event.get("source_release_type")
        if (
            not isinstance(label, str)
            or not re.search(r"Gross Domestic Product|\bGDP\b", label)
            or not re.search(r"advance|initial", label, re.IGNORECASE)
        ):
            raise BEAGDPClockArchiveError(
                f"GDP clock event has an invalid observation label: {release_date}"
            )
        if release_type not in {"Advance", "Initial"}:
            raise BEAGDPClockArchiveError(
                f"GDP clock event has an invalid release type: {release_date}"
            )
        url = raw_event.get("official_url")
        resolved_url = raw_event.get("resolved_url")
        if (
            not isinstance(url, str)
            or re.match(
                r"https://www\.bea\.gov/(?:news|index\.(?:php|ph%70)/news)/",
                url,
                re.IGNORECASE,
            )
            is None
            or resolved_url != url
        ):
            raise BEAGDPClockArchiveError(
                f"GDP clock event has an invalid official URL: {release_date}"
            )
        index_event = inventory_by_url.get(url)
        if (
            index_event is None
            or index_event.get("observation_label") != label
            or raw_event.get("archive_index_published_date")
            != index_event.get("release_date")
        ):
            raise BEAGDPClockArchiveError(
                f"GDP event evidence disagrees with source inventory: {release_date}"
            )
        index_date = str(index_event["release_date"])
        discrepancy = raw_event.get("source_date_discrepancy")
        if index_date == release_date.isoformat():
            if discrepancy is not None:
                raise BEAGDPClockArchiveError(
                    f"GDP event records an unsupported date discrepancy: {release_date}"
                )
        elif discrepancy != (
            "archive_index_one_day_early_header_and_vintage_workbook_agree"
        ):
            raise BEAGDPClockArchiveError(
                f"GDP event does not document its source date discrepancy: {release_date}"
            )
        clock = parse_bea_release_header(
            header_text,
            expected_release_date=release_date,
        )
        if clock.release_timestamp.time() != datetime.strptime(
            "12:30" if clock.printed_timezone == "EDT" else "13:30",
            "%H:%M",
        ).time():
            raise BEAGDPClockArchiveError("GDP initial release is not at 8:30 a.m. Eastern")
        clocks[release_date] = clock
        metadata[release_date] = MappingProxyType(dict(raw_event))
    if set(inventory_by_url) != {
        str(event.get("official_url"))
        for event in raw_events
        if isinstance(event, dict)
    }:
        raise BEAGDPClockArchiveError("GDP source/event URL inventories disagree")
    if expected_initial_releases is not None:
        if set(expected_initial_releases) != set(clocks):
            missing = sorted(set(expected_initial_releases) - set(clocks))
            extra = sorted(set(clocks) - set(expected_initial_releases))
            raise BEAGDPClockArchiveError(
                f"GDP clock/workbook inventory mismatch: missing={missing[:3]}, "
                f"extra={extra[:3]}"
            )
        for release_date, expected_type in expected_initial_releases.items():
            if metadata[release_date]["source_release_type"] != expected_type:
                raise BEAGDPClockArchiveError(
                    f"GDP clock/workbook release type mismatch: {release_date}"
                )

    return BEAGDPClockArchive(
        clocks=MappingProxyType(clocks),
        event_metadata=MappingProxyType(metadata),
        retrieved_at=str(document["retrieved_at"]),
        evidence_sha256=_sha256_bytes(payload),
        source_release_index_sha256=str(document["source_release_index_sha256"]),
    )


def audit_bea_gdp_clock_archive(
    directory: str | Path,
    *,
    expected_initial_releases: Mapping[date, str],
) -> dict[str, object]:
    """Return machine-readable offline audit facts for GDP clock evidence."""

    source = Path(directory) / BEA_GDP_CLOCK_FILENAME
    archive = parse_bea_gdp_clock_archive(
        source,
        expected_initial_releases=expected_initial_releases,
    )
    zones: dict[str, int] = {}
    release_types: dict[str, int] = {}
    header_styles: dict[str, int] = {}
    source_date_discrepancies: dict[str, dict[str, str]] = {}
    for release_date, clock in archive.clocks.items():
        zones[clock.printed_timezone] = zones.get(clock.printed_timezone, 0) + 1
        release_type = str(archive.event_metadata[release_date]["source_release_type"])
        release_types[release_type] = release_types.get(release_type, 0) + 1
        header = str(archive.event_metadata[release_date]["header_text"])
        if re.search(r"FOR WIRE TRANSMISSION", header, re.IGNORECASE):
            style = "for_wire_transmission"
        elif re.search(r"EMBARGOED FOR RELEASE", header, re.IGNORECASE):
            style = "embargoed_for_release"
        else:
            style = "embargoed_until_release"
        header_styles[style] = header_styles.get(style, 0) + 1
        discrepancy = archive.event_metadata[release_date].get(
            "source_date_discrepancy"
        )
        if discrepancy is not None:
            source_date_discrepancies[release_date.isoformat()] = {
                "archive_index_published_date": str(
                    archive.event_metadata[release_date][
                        "archive_index_published_date"
                    ]
                ),
                "resolution": str(discrepancy),
            }
    dates = sorted(archive.clocks)
    return {
        "passed": True,
        "directory": Path(directory).name,
        "filename": source.name,
        "bytes": source.stat().st_size,
        "sha256": archive.evidence_sha256,
        "official_url": BEA_GDP_CLOCK_INDEX_URL,
        "event_count": len(dates),
        "first_release_date": dates[0].isoformat(),
        "last_release_date": dates[-1].isoformat(),
        "release_type_counts": release_types,
        "header_style_counts": header_styles,
        "printed_timezone_counts": zones,
        "source_date_discrepancy_count": len(source_date_discrepancies),
        "source_date_discrepancies": source_date_discrepancies,
        "all_header_hashes_unique": True,
        "all_release_dates_weekdays_zones_verified": True,
        "all_workbook_initial_release_dates_reconciled": True,
        "all_release_times_0830_eastern": True,
        "server_original_bytes_claimed": False,
        "complete_dom_claimed": False,
        "source_release_index_sha256": archive.source_release_index_sha256,
        "retrieved_at": archive.retrieved_at,
    }


__all__ = [
    "BEA_GDP_CLOCK_DIRECTORY",
    "BEA_GDP_CLOCK_FILENAME",
    "BEA_GDP_CLOCK_INDEX_URL",
    "BEA_GDP_CLOCK_SOURCE",
    "BEA_GDP_CLOCK_TIMING_QUALITY",
    "BEAGDPClockArchive",
    "BEAGDPClockArchiveError",
    "BEAReleaseClock",
    "audit_bea_gdp_clock_archive",
    "parse_bea_gdp_clock_archive",
    "parse_bea_release_header",
]
