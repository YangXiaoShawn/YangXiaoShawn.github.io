from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from macro_nowcast.bls_cpi_clock_archive import (
    BLS_CPI_CLOCK_FILENAME,
    BLSCPIClockArchiveError,
    audit_bls_cpi_clock_archive,
    parse_bls_cpi_clock_archive,
)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _write_fixture(directory: Path) -> tuple[Path, Path]:
    directory.mkdir()
    headers = {
        "2012-02-17": (
            "Transmission of material in this release is embargoed until "
            "8:30 a.m. (EST) Friday, February 17, 2012"
        ),
        "2026-07-14": (
            "Transmission of material in this release is embargoed until "
            "8:30 a.m. (ET) Tuesday, July 14, 2026"
        ),
    }
    events = [
        {
            "release_date": release_date,
            "observation_label": label,
            "official_url": url,
            "page_title": "Consumer Price Index News Release",
            "header_text": headers[release_date],
            "header_sha256": _sha256(headers[release_date].encode()),
            "evidence_format": evidence_format,
            "evidence_status": "accepted",
        }
        for release_date, label, url, evidence_format in (
            (
                "2012-02-17",
                "January 2012 Consumer Price Index",
                "https://www.bls.gov/news.release/archives/cpi_02172012.htm",
                "browser_rendered_html_header_text_extraction",
            ),
            (
                "2026-07-14",
                "June 2026 Consumer Price Index",
                "https://www.bls.gov/news.release/archives/cpi_07142026.pdf",
                "official_pdf_text_extraction",
            ),
        )
    ]
    index = {
        "release_events": [
            {
                "release_date": event["release_date"],
                "observation_label": event["observation_label"],
                "html_available": True,
            }
            for event in events
        ]
    }
    index_path = directory / "cpi-release-index.json"
    index_payload = (json.dumps(index, sort_keys=True) + "\n").encode()
    index_path.write_bytes(index_payload)
    evidence = {
        "schema_version": 1,
        "status": "complete",
        "source_index_url": "https://www.bls.gov/bls/news-release/cpi.htm",
        "retrieved_at": "2026-08-10T01:56:33.700Z",
        "acquisition_format": "browser_rendered_embargo_header_text_extraction",
        "server_original_bytes_claimed": False,
        "complete_dom_claimed": False,
        "index_link_count": len(events),
        "source_release_index_sha256": _sha256(index_payload),
        "events": events,
    }
    evidence_path = directory / BLS_CPI_CLOCK_FILENAME
    evidence_path.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    return evidence_path, index_path


def test_parse_and_audit_cpi_clock_evidence(tmp_path: Path) -> None:
    evidence_path, index_path = _write_fixture(tmp_path / "clock")

    archive = parse_bls_cpi_clock_archive(
        evidence_path,
        release_index_path=index_path,
    )
    audit = audit_bls_cpi_clock_archive(
        evidence_path.parent,
        release_index_path=index_path,
    )

    assert len(archive.clocks) == 2
    assert sorted(clock.printed_timezone for clock in archive.clocks.values()) == [
        "EST",
        "ET",
    ]
    assert audit["passed"] is True
    assert audit["event_count"] == 2
    assert audit["all_release_dates_and_zones_verified"] is True
    assert audit["evidence_format_counts"] == {
        "browser_rendered_html_header_text_extraction": 1,
        "official_pdf_text_extraction": 1,
    }


def test_cpi_clock_archive_rejects_header_and_index_hash_drift(tmp_path: Path) -> None:
    evidence_path, index_path = _write_fixture(tmp_path / "clock")
    evidence = json.loads(evidence_path.read_text())
    evidence["events"][0]["header_text"] += " changed"
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")

    with pytest.raises(BLSCPIClockArchiveError, match="header hash mismatch"):
        parse_bls_cpi_clock_archive(evidence_path, release_index_path=index_path)

    evidence_path, index_path = _write_fixture(tmp_path / "other")
    index_path.write_text("{}", encoding="utf-8")
    with pytest.raises(BLSCPIClockArchiveError, match="release-index hash mismatch"):
        parse_bls_cpi_clock_archive(evidence_path, release_index_path=index_path)
