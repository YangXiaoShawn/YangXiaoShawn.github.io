from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from macro_nowcast.bea_gdp_clock_archive import (
    BEA_GDP_CLOCK_FILENAME,
    BEA_GDP_CLOCK_TIMING_QUALITY,
    BEAGDPClockArchiveError,
    audit_bea_gdp_clock_archive,
    parse_bea_gdp_clock_archive,
    parse_bea_release_header,
)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _write_fixture(directory: Path) -> tuple[Path, dict[date, str]]:
    directory.mkdir()
    raw_events = [
        {
            "release_date": "2002-04-26",
            "observation_label": (
                'Gross Domestic Product First Quarter 2002 "advance" estimate'
            ),
            "official_url": (
                "https://www.bea.gov/news/2002/"
                "gross-domestic-product-first-quarter-2002-advance-estimate"
            ),
            "header_text": (
                "FOR WIRE TRANSMISSION: 8:30 A.M. EDT, FRIDAY, APRIL 26, 2002"
            ),
            "source_release_type": "Advance",
        },
        {
            "release_date": "2019-02-28",
            "observation_label": (
                "Gross Domestic Product, Fourth Quarter and Annual 2018 "
                "(Initial Estimate)"
            ),
            "official_url": (
                "https://www.bea.gov/news/2019/"
                "initial-gross-domestic-product-4th-quarter-and-annual-2018"
            ),
            "header_text": (
                "EMBARGOED UNTIL RELEASE AT 8:30 A.M. EST, "
                "Thursday, February 28, 2019"
            ),
            "source_release_type": "Initial",
        },
    ]
    events = [
        {
            **event,
            "resolved_url": event["official_url"],
            "page_title": f"{event['observation_label']} | BEA",
            "header_sha256": _sha256(event["header_text"].encode()),
            "evidence_format": "browser_rendered_html_header_text_extraction",
            "evidence_status": "accepted",
            "archive_index_published_date": event["release_date"],
            "source_date_discrepancy": None,
        }
        for event in raw_events
    ]
    inventory = [
        {
            "release_date": event["release_date"],
            "observation_label": event["observation_label"],
            "official_url": event["official_url"],
        }
        for event in events
    ]
    inventory_payload = json.dumps(
        inventory,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    document = {
        "schema_version": 1,
        "status": "complete",
        "source_index_url": "https://www.bea.gov/news/archive",
        "source_home_url": "https://www.bea.gov/",
        "retrieved_at": "2026-08-10T03:00:00.000Z",
        "acquisition_format": "browser_rendered_embargo_header_text_extraction",
        "server_original_bytes_claimed": False,
        "complete_dom_claimed": False,
        "expected_event_count": 2,
        "archive_filter_page_count": 2,
        "archive_initial_event_count": 2,
        "current_event_count": 0,
        "source_release_index_sha256": _sha256(inventory_payload),
        "archive_filter_pages": [],
        "source_release_index_inventory": inventory,
        "events": events,
    }
    path = directory / BEA_GDP_CLOCK_FILENAME
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return path, {
        date(2002, 4, 26): "Advance",
        date(2019, 2, 28): "Initial",
    }


@pytest.mark.parametrize(
    ("release_date", "header", "expected"),
    [
        (
            date(2002, 4, 26),
            "FOR WIRE TRANSMISSION: 8:30 A.M. EDT, FRIDAY, APRIL 26, 2002",
            datetime(2002, 4, 26, 12, 30, tzinfo=UTC),
        ),
        (
            date(2003, 4, 25),
            "EMBARGOED FOR RELEASE: 8:30 A.M. EDT, FRIDAY, APRIL 25, 2003",
            datetime(2003, 4, 25, 12, 30, tzinfo=UTC),
        ),
        (
            date(2026, 2, 20),
            "EMBARGOED UNTIL RELEASE AT 8:30 a.m. EST, Friday, February 20, 2026",
            datetime(2026, 2, 20, 13, 30, tzinfo=UTC),
        ),
    ],
)
def test_parse_bea_release_header_cross_era(
    release_date: date,
    header: str,
    expected: datetime,
) -> None:
    clock = parse_bea_release_header(header, expected_release_date=release_date)

    assert clock.release_timestamp == expected
    assert clock.timing_quality == BEA_GDP_CLOCK_TIMING_QUALITY


def test_parse_bea_release_header_rejects_calendar_conflicts() -> None:
    with pytest.raises(BEAGDPClockArchiveError, match="date mismatch"):
        parse_bea_release_header(
            "EMBARGOED UNTIL RELEASE AT 8:30 a.m. EST, Friday, January 25, 2024",
            expected_release_date=date(2024, 1, 26),
        )
    with pytest.raises(BEAGDPClockArchiveError, match="weekday conflicts"):
        parse_bea_release_header(
            "EMBARGOED UNTIL RELEASE AT 8:30 a.m. EST, Monday, January 25, 2024",
            expected_release_date=date(2024, 1, 25),
        )
    with pytest.raises(BEAGDPClockArchiveError, match="timezone label conflicts"):
        parse_bea_release_header(
            "EMBARGOED UNTIL RELEASE AT 8:30 a.m. EDT, Friday, February 20, 2026",
            expected_release_date=date(2026, 2, 20),
        )


def test_parse_and_audit_gdp_clock_evidence(tmp_path: Path) -> None:
    path, expected = _write_fixture(tmp_path / "clock")

    archive = parse_bea_gdp_clock_archive(
        path,
        expected_initial_releases=expected,
    )
    audit = audit_bea_gdp_clock_archive(
        path.parent,
        expected_initial_releases=expected,
    )

    assert len(archive.clocks) == 2
    assert audit["passed"] is True
    assert audit["release_type_counts"] == {"Advance": 1, "Initial": 1}
    assert audit["printed_timezone_counts"] == {"EDT": 1, "EST": 1}
    assert audit["all_workbook_initial_release_dates_reconciled"] is True


def test_gdp_clock_archive_rejects_hash_and_workbook_drift(tmp_path: Path) -> None:
    path, expected = _write_fixture(tmp_path / "clock")
    document = json.loads(path.read_text())
    document["events"][0]["header_text"] += " changed"
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(BEAGDPClockArchiveError, match="header hash mismatch"):
        parse_bea_gdp_clock_archive(path, expected_initial_releases=expected)

    path, expected = _write_fixture(tmp_path / "other")
    expected.pop(date(2019, 2, 28))
    with pytest.raises(BEAGDPClockArchiveError, match="inventory mismatch"):
        parse_bea_gdp_clock_archive(path, expected_initial_releases=expected)
