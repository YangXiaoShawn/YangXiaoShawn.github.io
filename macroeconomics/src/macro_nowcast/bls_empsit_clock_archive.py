"""Audited pre-2008 Employment Situation release-clock evidence.

BLS exposes historical Employment Situation releases as direct text files.
The project imports those original text bytes through the official archive
page, hashes them, and verifies the printed embargo date, weekday, clock, and
EST/EDT label before using an exact timestamp.  Network access is deliberately
outside the parser and audit path.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Final

from macro_nowcast.bls_release_clock import (
    BLS_EMBARGO_CLOCK_TIMING_QUALITY,
    BLSReleaseClock,
    BLSReleaseClockError,
    parse_bls_embargo_header,
)

BLS_EMPSIT_CLOCK_DIRECTORY: Final = "bls-empsit-clock-txt"
BLS_EMPSIT_CLOCK_INDEX_FILENAME: Final = "release-index.json"
BLS_EMPSIT_ARCHIVE_INDEX_URL: Final = (
    "https://www.bls.gov/bls/news-release/empsit.htm"
)
BLS_EMPSIT_TEXT_URL_TEMPLATE: Final = (
    "https://www.bls.gov/news.release/history/empsit_{stamp}.txt"
)
BLS_EMPSIT_TEXT_CLOCK_SOURCE: Final = (
    "BLS_EMPLOYMENT_SITUATION_OFFICIAL_TEXT_ARCHIVE"
)
BLS_EMPSIT_TEXT_START: Final = date(2003, 6, 6)
BLS_EMPSIT_TEXT_END: Final = date(2008, 1, 4)

_TEXT_FILENAME_RE = re.compile(r"empsit_(\d{2})(\d{2})(\d{4})\.txt")


class BLSEmpsitTextClockError(ValueError):
    """Raised when imported BLS text-clock evidence is incomplete or inconsistent."""


@dataclass(frozen=True, slots=True)
class BLSEmpsitTextClockArchive:
    """Verified exact clocks and immutable per-release evidence metadata."""

    clocks: Mapping[date, BLSReleaseClock]
    event_metadata: Mapping[date, Mapping[str, object]]
    evidence_sha256: str


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_path(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _decode_text(payload: bytes) -> tuple[str, str]:
    try:
        return payload.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        return payload.decode("cp1252"), "cp1252"


def _release_date_from_filename(path: Path) -> date:
    match = _TEXT_FILENAME_RE.fullmatch(path.name)
    if match is None:
        raise BLSEmpsitTextClockError(
            f"unexpected Employment Situation text filename: {path.name}"
        )
    return date(int(match.group(3)), int(match.group(1)), int(match.group(2)))


def _expected_release_dates(
    release_index_path: str | Path,
    *,
    start: date = BLS_EMPSIT_TEXT_START,
    end: date = BLS_EMPSIT_TEXT_END,
) -> list[date]:
    source = Path(release_index_path)
    try:
        document = json.loads(source.read_text(encoding="utf-8"))
        events = document["release_events"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise BLSEmpsitTextClockError(
            "Employment Situation archive index is missing or invalid"
        ) from exc
    releases = sorted(
        date.fromisoformat(str(event["release_date"]))
        for event in events
        if start <= date.fromisoformat(str(event["release_date"])) <= end
    )
    if not releases:
        raise BLSEmpsitTextClockError("no expected text-clock releases in requested range")
    if len(releases) != len(set(releases)):
        raise BLSEmpsitTextClockError("duplicate releases in Employment Situation index")
    return releases


def parse_empsit_text_clock_file(path: str | Path) -> BLSReleaseClock:
    """Parse one original BLS text release and verify its filename date."""

    source = Path(path)
    expected = _release_date_from_filename(source)
    document, _encoding = _decode_text(source.read_bytes())
    try:
        return parse_bls_embargo_header(
            document,
            expected_release_date=expected,
        )
    except BLSReleaseClockError as exc:
        raise BLSEmpsitTextClockError(str(exc)) from exc


def _event_record(path: Path, clock: BLSReleaseClock) -> dict[str, object]:
    payload = path.read_bytes()
    _document, encoding = _decode_text(payload)
    return {
        "release_date": clock.release_date.isoformat(),
        "filename": path.name,
        "official_url": BLS_EMPSIT_TEXT_URL_TEMPLATE.format(
            stamp=clock.release_date.strftime("%m%d%Y")
        ),
        "sha256": _sha256_bytes(payload),
        "byte_count": len(payload),
        "text_encoding": encoding,
        "release_timestamp_utc": clock.release_timestamp.isoformat().replace(
            "+00:00", "Z"
        ),
        "printed_timezone": clock.printed_timezone,
        "printed_weekday": clock.printed_weekday,
        "timing_quality": BLS_EMBARGO_CLOCK_TIMING_QUALITY,
    }


def write_empsit_text_clock_index(
    directory: str | Path,
    release_index_path: str | Path,
    *,
    retrieved_at: datetime | None = None,
    overwrite: bool = False,
) -> dict[str, object]:
    """Index already downloaded official text bytes without using the network."""

    source_directory = Path(directory).resolve()
    source_index = Path(release_index_path).resolve()
    output = source_directory / BLS_EMPSIT_CLOCK_INDEX_FILENAME
    if output.exists() and not overwrite:
        raise FileExistsError(f"clock evidence index already exists: {output.name}")
    expected_dates = _expected_release_dates(source_index)
    expected_names = {
        f"empsit_{release:%m%d%Y}.txt" for release in expected_dates
    }
    actual_paths = {
        path.name: path for path in source_directory.glob("empsit_*.txt")
    }
    missing = sorted(expected_names - set(actual_paths))
    extra = sorted(set(actual_paths) - expected_names)
    if missing or extra:
        raise BLSEmpsitTextClockError(
            f"text-clock inventory mismatch: missing={missing[:3]}, extra={extra[:3]}"
        )
    events = [
        _event_record(actual_paths[name], parse_empsit_text_clock_file(actual_paths[name]))
        for name in sorted(actual_paths, key=lambda item: _release_date_from_filename(Path(item)))
    ]
    hashes = [str(event["sha256"]) for event in events]
    if len(hashes) != len(set(hashes)):
        raise BLSEmpsitTextClockError("text releases contain duplicate content hashes")
    timestamp = (retrieved_at or datetime.now(UTC)).astimezone(UTC)
    document = {
        "schema_version": 1,
        "source": BLS_EMPSIT_TEXT_CLOCK_SOURCE,
        "source_index_url": BLS_EMPSIT_ARCHIVE_INDEX_URL,
        "source_release_index_path": source_index.name,
        "source_release_index_sha256": _sha256_path(source_index),
        "acquisition_method": "browser_download_from_official_archive_text_link",
        "server_original_bytes_claimed": True,
        "network_used_by_indexer": False,
        "retrieved_at": timestamp.isoformat().replace("+00:00", "Z"),
        "first_release_date": expected_dates[0].isoformat(),
        "last_release_date": expected_dates[-1].isoformat(),
        "release_count": len(events),
        "release_events": events,
    }
    output.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "status": "indexed",
        "index_path": output,
        "release_count": len(events),
        "first_release_date": expected_dates[0].isoformat(),
        "last_release_date": expected_dates[-1].isoformat(),
        "network_used": False,
    }


def _load_validated_archive(
    directory: str | Path,
    *,
    release_index_path: str | Path,
) -> tuple[BLSEmpsitTextClockArchive, dict[str, object]]:
    source_directory = Path(directory).resolve()
    evidence_path = source_directory / BLS_EMPSIT_CLOCK_INDEX_FILENAME
    try:
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BLSEmpsitTextClockError("text-clock evidence index is missing or invalid") from exc
    if evidence.get("schema_version") != 1:
        raise BLSEmpsitTextClockError("unsupported text-clock evidence schema")
    if evidence.get("source") != BLS_EMPSIT_TEXT_CLOCK_SOURCE:
        raise BLSEmpsitTextClockError("unexpected text-clock evidence source")
    if evidence.get("source_index_url") != BLS_EMPSIT_ARCHIVE_INDEX_URL:
        raise BLSEmpsitTextClockError("unexpected Employment Situation source index URL")
    source_index = Path(release_index_path).resolve()
    if evidence.get("source_release_index_sha256") != _sha256_path(source_index):
        raise BLSEmpsitTextClockError("Employment Situation source index hash drift")
    expected_dates = _expected_release_dates(source_index)
    events = evidence.get("release_events")
    if not isinstance(events, list):
        raise BLSEmpsitTextClockError("text-clock evidence events must be a list")
    indexed_names = {str(event.get("filename")) for event in events}
    actual_names = {path.name for path in source_directory.glob("empsit_*.txt")}
    expected_names = {f"empsit_{release:%m%d%Y}.txt" for release in expected_dates}
    if indexed_names != actual_names or actual_names != expected_names:
        raise BLSEmpsitTextClockError("text-clock evidence inventory drift")

    clocks: dict[date, BLSReleaseClock] = {}
    metadata: dict[date, Mapping[str, object]] = {}
    hashes: list[str] = []
    for raw_event in events:
        if not isinstance(raw_event, dict):
            raise BLSEmpsitTextClockError("invalid text-clock event record")
        filename = str(raw_event["filename"])
        path = source_directory / filename
        clock = parse_empsit_text_clock_file(path)
        expected_record = _event_record(path, clock)
        if raw_event != expected_record:
            raise BLSEmpsitTextClockError(
                f"text-clock event metadata drift: {filename}"
            )
        if clock.release_date in clocks:
            raise BLSEmpsitTextClockError(
                f"duplicate text-clock release: {clock.release_date}"
            )
        clocks[clock.release_date] = clock
        metadata[clock.release_date] = MappingProxyType(dict(raw_event))
        hashes.append(str(raw_event["sha256"]))
    if sorted(clocks) != expected_dates:
        raise BLSEmpsitTextClockError("text-clock release-date coverage drift")
    if len(hashes) != len(set(hashes)):
        raise BLSEmpsitTextClockError("text releases contain duplicate content hashes")
    archive = BLSEmpsitTextClockArchive(
        clocks=MappingProxyType(clocks),
        event_metadata=MappingProxyType(metadata),
        evidence_sha256=_sha256_path(evidence_path),
    )
    return archive, evidence


def parse_empsit_text_clock_archive(
    directory: str | Path,
    *,
    release_index_path: str | Path,
) -> BLSEmpsitTextClockArchive:
    """Return verified exact clocks from an offline official-text inventory."""

    archive, _evidence = _load_validated_archive(
        directory,
        release_index_path=release_index_path,
    )
    return archive


def audit_empsit_text_clock_archive(
    directory: str | Path,
    *,
    release_index_path: str | Path,
) -> dict[str, object]:
    """Audit hashes, coverage, encodings, and printed embargo clocks offline."""

    archive, evidence = _load_validated_archive(
        directory,
        release_index_path=release_index_path,
    )
    releases = sorted(archive.clocks)
    zones = Counter(clock.printed_timezone for clock in archive.clocks.values())
    encodings = Counter(
        str(metadata["text_encoding"])
        for metadata in archive.event_metadata.values()
    )
    return {
        "passed": True,
        "directory": Path(directory).name,
        "official_url": BLS_EMPSIT_ARCHIVE_INDEX_URL,
        "source": BLS_EMPSIT_TEXT_CLOCK_SOURCE,
        "acquisition_method": evidence["acquisition_method"],
        "server_original_bytes_claimed": True,
        "network_used": False,
        "file_count": len(releases),
        "exact_release_clock_count": len(releases),
        "first_release_date": releases[0].isoformat(),
        "last_release_date": releases[-1].isoformat(),
        "printed_timezone_counts": dict(sorted(zones.items())),
        "text_encoding_counts": dict(sorted(encodings.items())),
        "all_release_dates_weekdays_and_zones_verified": True,
        "all_hashes_unique": True,
        "exact_timing_quality": BLS_EMBARGO_CLOCK_TIMING_QUALITY,
        "evidence_sha256": archive.evidence_sha256,
        "files": {
            release.isoformat(): dict(archive.event_metadata[release])
            for release in releases
        },
    }


def merge_empsit_release_clocks(
    *clock_mappings: Mapping[date, BLSReleaseClock],
) -> Mapping[date, BLSReleaseClock]:
    """Merge independently audited clock inventories, failing on disagreement."""

    merged: dict[date, BLSReleaseClock] = {}
    for mapping in clock_mappings:
        for release_date, clock in mapping.items():
            existing = merged.get(release_date)
            if existing is not None and existing != clock:
                raise BLSEmpsitTextClockError(
                    f"conflicting Employment Situation clocks: {release_date}"
                )
            merged[release_date] = clock
    return MappingProxyType(dict(sorted(merged.items())))


__all__ = [
    "BLS_EMPSIT_ARCHIVE_INDEX_URL",
    "BLS_EMPSIT_CLOCK_DIRECTORY",
    "BLS_EMPSIT_CLOCK_INDEX_FILENAME",
    "BLS_EMPSIT_TEXT_CLOCK_SOURCE",
    "BLS_EMPSIT_TEXT_END",
    "BLS_EMPSIT_TEXT_START",
    "BLS_EMPSIT_TEXT_URL_TEMPLATE",
    "BLSEmpsitTextClockArchive",
    "BLSEmpsitTextClockError",
    "audit_empsit_text_clock_archive",
    "merge_empsit_release_clocks",
    "parse_empsit_text_clock_archive",
    "parse_empsit_text_clock_file",
    "write_empsit_text_clock_index",
]
