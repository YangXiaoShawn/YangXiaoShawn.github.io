from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from macro_nowcast.bls_release_clock import (
    BLS_EMBARGO_CLOCK_TIMING_QUALITY,
    BLSReleaseClockError,
    parse_bls_embargo_header,
    parse_empsit_release_clock_archive,
)


def _page(header: str) -> str:
    return f"<html><body><pre>{header}</pre></body></html>"


@pytest.mark.parametrize(
    ("release_date", "header", "expected"),
    [
        (
            date(2008, 2, 1),
            "Transmission of material is embargoed until 8:30 A.M. (EST), "
            "Friday, February 1, 2008.",
            datetime(2008, 2, 1, 13, 30, tzinfo=UTC),
        ),
        (
            date(2010, 6, 4),
            "Transmission of material is embargoed until 8:30 a.m. (EDT) "
            "Friday, June 4, 2010",
            datetime(2010, 6, 4, 12, 30, tzinfo=UTC),
        ),
        (
            date(2026, 7, 2),
            "Transmission of material is embargoed until USDL-26-1125 "
            "8:30 a.m. (ET) Thursday, July 2, 2026",
            datetime(2026, 7, 2, 12, 30, tzinfo=UTC),
        ),
        (
            date(2008, 8, 14),
            "RELEASE IS EMBARGOED UNTIL 8:30 A.M. (EDT) "
            "Thursday, August 14,2008",
            datetime(2008, 8, 14, 12, 30, tzinfo=UTC),
        ),
    ],
)
def test_parse_bls_embargo_header_cross_era(
    release_date: date,
    header: str,
    expected: datetime,
) -> None:
    parsed = parse_bls_embargo_header(
        _page(header),
        expected_release_date=release_date,
    )

    assert parsed.release_timestamp == expected
    assert parsed.timing_quality == BLS_EMBARGO_CLOCK_TIMING_QUALITY


def test_parse_bls_embargo_header_rejects_date_and_weekday_conflicts() -> None:
    with pytest.raises(BLSReleaseClockError, match="date mismatch"):
        parse_bls_embargo_header(
            _page("embargoed until 8:30 a.m. (EST) Friday, January 4, 2019"),
            expected_release_date=date(2019, 1, 5),
        )
    with pytest.raises(BLSReleaseClockError, match="weekday conflicts"):
        parse_bls_embargo_header(
            _page("embargoed until 8:30 a.m. (EST) Monday, January 4, 2019"),
            expected_release_date=date(2019, 1, 4),
        )


def test_known_2012_source_timezone_conflict_stays_date_only(tmp_path: Path) -> None:
    (tmp_path / "empsit_02012008.htm").write_text(
        _page("embargoed until 8:30 a.m. (EST) Friday, February 1, 2008"),
        encoding="utf-8",
    )
    (tmp_path / "empsit_12072012.htm").write_text(
        _page("embargoed until 8:30 a.m. (EDT) Friday, December 7, 2012"),
        encoding="utf-8",
    )

    parsed = parse_empsit_release_clock_archive(tmp_path)

    assert set(parsed.clocks) == {date(2008, 2, 1)}
    assert parsed.exclusions == {
        date(2012, 12, 7): "official_header_EDT_conflicts_with_America_New_York_EST"
    }


def test_unknown_timezone_conflict_fails_closed(tmp_path: Path) -> None:
    (tmp_path / "empsit_01042019.htm").write_text(
        _page("embargoed until 8:30 a.m. (EDT) Friday, January 4, 2019"),
        encoding="utf-8",
    )

    with pytest.raises(BLSReleaseClockError, match="timezone label conflicts"):
        parse_empsit_release_clock_archive(tmp_path)
