from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from macro_nowcast.bls_empsit_clock_archive import (
    BLS_EMPSIT_CLOCK_INDEX_FILENAME,
    BLSEmpsitTextClockError,
    audit_empsit_text_clock_archive,
    merge_empsit_release_clocks,
    parse_empsit_text_clock_archive,
    parse_empsit_text_clock_file,
    write_empsit_text_clock_index,
)
from macro_nowcast.bls_release_clock import BLSReleaseClock


def _header(release_date: date) -> str:
    zone = datetime.combine(
        release_date,
        datetime.min.time(),
        tzinfo=ZoneInfo("America/New_York"),
    ).tzname()
    return (
        "Technical information\r\n"
        "Transmission of material in this release is embargoed until "
        f"8:30 A.M. ({zone}), {release_date:%A, %B} "
        f"{release_date.day}, {release_date.year}.\r\n"
        "THE EMPLOYMENT SITUATION\r\n"
    )


def _write_fixture(directory: Path, release_dates: list[date]) -> Path:
    directory.mkdir()
    events = []
    for index, release_date in enumerate(release_dates):
        path = directory / f"empsit_{release_date:%m%d%Y}.txt"
        payload = _header(release_date).encode("ascii")
        if index == 1:
            payload += b"Publisher\x92s historical note\r\n"
        path.write_bytes(payload)
        events.append(
            {
                "release_date": release_date.isoformat(),
                "html_available": False,
                "pdf_available": True,
                "observation_label": None,
            }
        )
    release_index = directory.parent / "empsit-release-index.json"
    release_index.write_text(
        json.dumps({"release_events": events}),
        encoding="utf-8",
    )
    return release_index


def test_text_clock_index_round_trip_and_encoding_audit(tmp_path: Path) -> None:
    directory = tmp_path / "clock-text"
    releases = [date(2003, 6, 6), date(2003, 7, 3)]
    release_index = _write_fixture(directory, releases)

    result = write_empsit_text_clock_index(
        directory,
        release_index,
        retrieved_at=datetime(2026, 8, 10, tzinfo=UTC),
    )
    parsed = parse_empsit_text_clock_archive(
        directory,
        release_index_path=release_index,
    )
    audit = audit_empsit_text_clock_archive(
        directory,
        release_index_path=release_index,
    )

    assert result["release_count"] == 2
    assert set(parsed.clocks) == set(releases)
    assert parsed.clocks[releases[0]].release_timestamp == datetime(
        2003,
        6,
        6,
        12,
        30,
        tzinfo=UTC,
    )
    assert audit["passed"] is True
    assert audit["text_encoding_counts"] == {"cp1252": 1, "utf-8": 1}
    assert audit["printed_timezone_counts"] == {"EDT": 2}
    assert (directory / BLS_EMPSIT_CLOCK_INDEX_FILENAME).exists()


def test_text_clock_parser_rejects_filename_header_date_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "empsit_06062003.txt"
    path.write_text(_header(date(2003, 7, 3)), encoding="ascii")

    with pytest.raises(BLSEmpsitTextClockError, match="date mismatch"):
        parse_empsit_text_clock_file(path)


def test_text_clock_audit_detects_hash_or_metadata_drift(tmp_path: Path) -> None:
    directory = tmp_path / "clock-text"
    release_index = _write_fixture(directory, [date(2003, 6, 6)])
    write_empsit_text_clock_index(directory, release_index)
    source = directory / "empsit_06062003.txt"
    source.write_bytes(source.read_bytes() + b"changed\r\n")

    with pytest.raises(BLSEmpsitTextClockError, match="metadata drift"):
        audit_empsit_text_clock_archive(
            directory,
            release_index_path=release_index,
        )


def test_text_clock_index_is_immutable_and_requires_exact_inventory(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "clock-text"
    release_index = _write_fixture(directory, [date(2003, 6, 6)])
    write_empsit_text_clock_index(directory, release_index)

    with pytest.raises(FileExistsError):
        write_empsit_text_clock_index(directory, release_index)

    (directory / "empsit_07032003.txt").write_text(
        _header(date(2003, 7, 3)),
        encoding="ascii",
    )
    with pytest.raises(BLSEmpsitTextClockError, match="inventory mismatch"):
        write_empsit_text_clock_index(directory, release_index, overwrite=True)


def test_merge_empsit_release_clocks_fails_on_disagreement() -> None:
    release_date = date(2003, 6, 6)
    first = BLSReleaseClock(
        release_date=release_date,
        release_timestamp=datetime(2003, 6, 6, 12, 30, tzinfo=UTC),
        printed_timezone="EDT",
        printed_weekday="Friday",
    )
    second = BLSReleaseClock(
        release_date=release_date,
        release_timestamp=datetime(2003, 6, 6, 13, 30, tzinfo=UTC),
        printed_timezone="EDT",
        printed_weekday="Friday",
    )

    assert merge_empsit_release_clocks({release_date: first})[release_date] == first
    with pytest.raises(BLSEmpsitTextClockError, match="conflicting"):
        merge_empsit_release_clocks(
            {release_date: first},
            {release_date: second},
        )
