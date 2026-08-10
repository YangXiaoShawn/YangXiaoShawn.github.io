"""Offline audit of browser-captured official BLS CPI embargo-header evidence."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from types import MappingProxyType
from typing import Final

from macro_nowcast.bls_release_clock import BLSReleaseClock, parse_bls_embargo_header

BLS_CPI_CLOCK_DIRECTORY: Final = "bls-cpi-html"
BLS_CPI_CLOCK_FILENAME: Final = "clock-evidence.json"
BLS_CPI_CLOCK_SOURCE: Final = "BLS_CPI_NEWS_RELEASE_HEADER_EVIDENCE"
BLS_CPI_CLOCK_INDEX_URL: Final = "https://www.bls.gov/bls/news-release/cpi.htm"

_ALLOWED_FORMATS = {
    "browser_rendered_html_header_text_extraction",
    "official_pdf_text_extraction",
}


class BLSCPIClockArchiveError(ValueError):
    """Raised when CPI header evidence cannot prove its claimed release clock."""


@dataclass(frozen=True, slots=True)
class BLSCPIClockArchive:
    """Verified CPI release clocks and immutable acquisition metadata."""

    clocks: Mapping[date, BLSReleaseClock]
    event_metadata: Mapping[date, Mapping[str, object]]
    retrieved_at: str
    evidence_sha256: str
    source_release_index_sha256: str


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _validated_document(path: Path) -> tuple[dict[str, object], bytes]:
    payload = path.read_bytes()
    try:
        document = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise BLSCPIClockArchiveError("CPI clock evidence is not valid JSON") from exc
    if not isinstance(document, dict):
        raise BLSCPIClockArchiveError("CPI clock evidence must be a JSON object")
    expected = {
        "schema_version": 1,
        "status": "complete",
        "source_index_url": BLS_CPI_CLOCK_INDEX_URL,
        "acquisition_format": "browser_rendered_embargo_header_text_extraction",
        "server_original_bytes_claimed": False,
        "complete_dom_claimed": False,
    }
    for field, expected_value in expected.items():
        if document.get(field) != expected_value:
            raise BLSCPIClockArchiveError(
                f"CPI clock evidence field {field!r} is not {expected_value!r}"
            )
    if not isinstance(document.get("retrieved_at"), str):
        raise BLSCPIClockArchiveError("CPI clock evidence has no retrieval timestamp")
    events = document.get("events")
    if not isinstance(events, list) or not events:
        raise BLSCPIClockArchiveError("CPI clock evidence has no events")
    if document.get("index_link_count") != len(events):
        raise BLSCPIClockArchiveError("CPI clock index/event counts disagree")
    return document, payload


def parse_bls_cpi_clock_archive(
    path: str | Path,
    *,
    release_index_path: str | Path | None = None,
) -> BLSCPIClockArchive:
    """Parse every saved CPI embargo header and reconcile the official release index."""

    source = Path(path)
    document, payload = _validated_document(source)
    raw_events = document["events"]
    assert isinstance(raw_events, list)
    clocks: dict[date, BLSReleaseClock] = {}
    metadata: dict[date, Mapping[str, object]] = {}
    header_hashes: set[str] = set()
    for raw_event in raw_events:
        if not isinstance(raw_event, dict):
            raise BLSCPIClockArchiveError("CPI clock evidence contains a non-object event")
        try:
            release_date = date.fromisoformat(str(raw_event["release_date"]))
        except (KeyError, ValueError) as exc:
            raise BLSCPIClockArchiveError("CPI clock event has an invalid date") from exc
        if release_date in clocks:
            raise BLSCPIClockArchiveError(f"duplicate CPI clock event: {release_date}")
        header_text = raw_event.get("header_text")
        header_sha256 = raw_event.get("header_sha256")
        evidence_format = raw_event.get("evidence_format")
        if not isinstance(header_text, str) or not header_text:
            raise BLSCPIClockArchiveError(f"CPI clock event has no header: {release_date}")
        if evidence_format not in _ALLOWED_FORMATS:
            raise BLSCPIClockArchiveError(
                f"CPI clock event has unsupported evidence format: {release_date}"
            )
        calculated_hash = _sha256_bytes(header_text.encode("utf-8"))
        if header_sha256 != calculated_hash:
            raise BLSCPIClockArchiveError(
                f"CPI clock event header hash mismatch: {release_date}"
            )
        if calculated_hash in header_hashes:
            raise BLSCPIClockArchiveError("CPI clock evidence contains duplicate headers")
        header_hashes.add(calculated_hash)
        label = raw_event.get("observation_label")
        if not isinstance(label, str) or not label.endswith("Consumer Price Index"):
            raise BLSCPIClockArchiveError(
                f"CPI clock event has an invalid observation label: {release_date}"
            )
        url = raw_event.get("official_url")
        if not isinstance(url, str) or not url.startswith(
            "https://www.bls.gov/news.release/archives/cpi_"
        ):
            raise BLSCPIClockArchiveError(
                f"CPI clock event has an invalid official URL: {release_date}"
            )
        try:
            clock = parse_bls_embargo_header(
                header_text,
                expected_release_date=release_date,
            )
        except ValueError as exc:
            raise BLSCPIClockArchiveError(
                f"CPI clock header failed strict parsing for {release_date}: {exc}"
            ) from exc
        clocks[release_date] = clock
        metadata[release_date] = MappingProxyType(dict(raw_event))

    source_index_hash = str(document.get("source_release_index_sha256", ""))
    if release_index_path is not None:
        index_path = Path(release_index_path)
        calculated_index_hash = _sha256_bytes(index_path.read_bytes())
        if source_index_hash != calculated_index_hash:
            raise BLSCPIClockArchiveError("CPI source release-index hash mismatch")
        index_document = json.loads(index_path.read_text(encoding="utf-8"))
        expected_events = {
            date.fromisoformat(str(event["release_date"])): event
            for event in index_document.get("release_events", [])
            if event.get("html_available")
        }
        if set(expected_events) != set(clocks):
            missing = sorted(set(expected_events) - set(clocks))
            extra = sorted(set(clocks) - set(expected_events))
            raise BLSCPIClockArchiveError(
                f"CPI clock inventory mismatch: missing={missing[:3]}, extra={extra[:3]}"
            )
        for release_date, event in expected_events.items():
            if metadata[release_date]["observation_label"] != event.get("observation_label"):
                raise BLSCPIClockArchiveError(
                    f"CPI clock label disagrees with release index: {release_date}"
                )

    return BLSCPIClockArchive(
        clocks=MappingProxyType(clocks),
        event_metadata=MappingProxyType(metadata),
        retrieved_at=str(document["retrieved_at"]),
        evidence_sha256=_sha256_bytes(payload),
        source_release_index_sha256=source_index_hash,
    )


def audit_bls_cpi_clock_archive(
    directory: str | Path,
    *,
    release_index_path: str | Path,
) -> dict[str, object]:
    """Return machine-readable offline audit facts for saved CPI clock evidence."""

    source = Path(directory) / BLS_CPI_CLOCK_FILENAME
    archive = parse_bls_cpi_clock_archive(
        source,
        release_index_path=release_index_path,
    )
    formats: dict[str, int] = {}
    zones: dict[str, int] = {}
    for release_date, clock in archive.clocks.items():
        event_format = str(archive.event_metadata[release_date]["evidence_format"])
        formats[event_format] = formats.get(event_format, 0) + 1
        zones[clock.printed_timezone] = zones.get(clock.printed_timezone, 0) + 1
    dates = sorted(archive.clocks)
    return {
        "passed": True,
        "directory": Path(directory).name,
        "filename": source.name,
        "bytes": source.stat().st_size,
        "sha256": archive.evidence_sha256,
        "official_url": BLS_CPI_CLOCK_INDEX_URL,
        "event_count": len(dates),
        "first_release_date": dates[0].isoformat(),
        "last_release_date": dates[-1].isoformat(),
        "evidence_format_counts": formats,
        "printed_timezone_counts": zones,
        "all_header_hashes_unique": True,
        "all_release_dates_and_zones_verified": True,
        "server_original_bytes_claimed": False,
        "complete_dom_claimed": False,
        "source_release_index_sha256": archive.source_release_index_sha256,
        "retrieved_at": archive.retrieved_at,
    }


__all__ = [
    "BLS_CPI_CLOCK_DIRECTORY",
    "BLS_CPI_CLOCK_FILENAME",
    "BLS_CPI_CLOCK_INDEX_URL",
    "BLS_CPI_CLOCK_SOURCE",
    "BLSCPIClockArchive",
    "BLSCPIClockArchiveError",
    "audit_bls_cpi_clock_archive",
    "parse_bls_cpi_clock_archive",
]
