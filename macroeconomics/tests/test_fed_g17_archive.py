from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

import pytest

from macro_nowcast.fed_g17_archive import (
    FED_G17_INDEX_SERIES_ID,
    FED_G17_MOM_SERIES_ID,
    FedG17ArchiveError,
    audit_fed_g17_archive,
    parse_fed_g17_archive,
    parse_fed_g17_archive_index,
    parse_fed_g17_release_text,
)


def _monthly_release(
    *,
    release_date: str,
    zone: str,
    years: str,
    months: str,
    indexes: str,
    changes: str,
) -> bytes:
    return f"""
 FEDERAL RESERVE STATISTICAL RELEASE
 G.17 (419) For release at 9:15 a.m. ({zone})
 {release_date}

 Industrial Production and Capacity Utilization
 INDUSTRIAL PRODUCTION AND CAPACITY UTILIZATION: SUMMARY
 Seasonally adjusted
 | 2017=100 | Percent change
 | {years} | {years} | prior year
 Industrial production | {months} | {months} | year ago
 ------------------------------------------------------------
 | | |
 Total index | {indexes} | {changes} | 1.0
 Previous estimates | | |
 """.encode()


def test_archive_index_retains_only_stable_dated_ascii_snapshots() -> None:
    releases = parse_fed_g17_archive_index(
        """
        <a href="Current/g17.txt">mutable current</a>
        <a href="20240618/g17.txt">monthly ASCII</a>
        <a href="20240618/g17.pdf">monthly PDF</a>
        <a href="./Revisions/20240628/g17rev.txt">revision ASCII</a>
        <a href="Revisions/20240628/g17rev.pdf">revision PDF</a>
        """
    )

    assert [(item.release_date, item.release_type) for item in releases] == [
        (date(2024, 6, 18), "monthly"),
        (date(2024, 6, 28), "annual_revision"),
    ]
    assert releases[0].official_url.endswith("/20240618/g17.txt")
    assert releases[1].relative_path == Path("revisions/20240628/g17rev.txt")


def test_monthly_summary_parses_exact_time_cross_year_and_published_change() -> None:
    parsed = parse_fed_g17_release_text(
        _monthly_release(
            release_date="January 17, 2024",
            zone="EST",
            years="2023",
            months="Sept.[r] Oct.[r] Nov.[r] Dec.[p]",
            indexes="102.1 102.2 102.3 102.4",
            changes=".1 .2 .3 .4",
        ).decode(),
        release_date=date(2024, 1, 17),
        release_type="monthly",
    )

    assert parsed.release_timestamp.isoformat() == "2024-01-17T14:15:00+00:00"
    assert parsed.base_period == "2017"
    assert [value.observation_date for value in parsed.values] == [
        date(2023, 9, 1),
        date(2023, 10, 1),
        date(2023, 11, 1),
        date(2023, 12, 1),
    ]
    assert parsed.values[-1].index_value == 102.4
    assert parsed.values[-1].percent_change == 0.4
    assert parsed.values[-1].vintage_type == "preliminary"


def test_legacy_annual_revision_fallback_parses_monthly_total_ip_table() -> None:
    parsed = parse_fed_g17_release_text(
        """
        FEDERAL RESERVE STATISTICAL RELEASE
        G.17 (419) Annual Revision For release at 11:00 a.m. (EST)
        November 27, 2001
        INDUSTRIAL PRODUCTION AND CAPACITY UTILIZATION
        Table 1
        INDUSTRIAL PRODUCTION, CAPACITY AND UTILIZATION: Total Industry
        Seasonally adjusted
        | Jan. Feb. Mar. Apr. May June July Aug. Sept. Oct. Nov. Dec.|
        IP (percent change) |
         2000 | .1 .2 .3 .4 .5 .6 .7 .8 .9 1.0 1.1 1.2 | Q1 Q2
         2001 | -.1 -.2 -.3 -.4 -.5 -.6 -.7 -.8 -.9 -1.0 | Q1 Q2
        IP (1992=100) |
         2000 | 140.1 140.2 140.3 140.4 140.5 140.6 140.7 140.8 140.9 141.0 141.1 141.2 | Q1 Q2
         2001 | 139.1 139.2 139.3 139.4 139.5 139.6 139.7 139.8 139.9 140.0 | Q1 Q2
        Capacity |
        """,
        release_date=date(2001, 11, 27),
        release_type="annual_revision",
    )

    assert parsed.release_timestamp.isoformat() == "2001-11-27T16:00:00+00:00"
    assert parsed.extraction_pattern == "annual_revision_total_industry_monthly_table"
    assert parsed.values[-1].observation_date == date(2001, 10, 1)
    assert parsed.values[-1].index_value == 140.0
    assert parsed.values[-1].percent_change == -1.0
    assert parsed.values[-1].vintage_type == "revised"


def test_release_rejects_header_link_date_disagreement() -> None:
    payload = _monthly_release(
        release_date="January 17, 2024",
        zone="EST",
        years="2023",
        months="Sept. Oct. Nov. Dec.",
        indexes="102.1 102.2 102.3 102.4",
        changes=".1 .2 .3 .4",
    )
    with pytest.raises(FedG17ArchiveError, match="disagrees"):
        parse_fed_g17_release_text(
            payload.decode(),
            release_date=date(2024, 1, 18),
            release_type="monthly",
        )


def test_local_archive_hash_audit_yields_level_and_published_change_vintages(
    tmp_path: Path,
) -> None:
    root = tmp_path / "fed-g17"
    payloads = [
        (
            date(2024, 1, 17),
            _monthly_release(
                release_date="January 17, 2024",
                zone="EST",
                years="2023",
                months="Sept.[r] Oct.[r] Nov.[r] Dec.[p]",
                indexes="102.1 102.2 102.3 102.4",
                changes=".1 .2 .3 .4",
            ),
        ),
        (
            date(2024, 2, 15),
            _monthly_release(
                release_date="February 15, 2024",
                zone="EST",
                years="2023 2024",
                months="Oct.[r] Nov.[r] Dec.[r] Jan.[p]",
                indexes="102.2 102.3 102.5 102.6",
                changes=".2 .3 .5 .1",
            ),
        ),
    ]
    entries: list[dict[str, object]] = []
    for release_date, payload in payloads:
        stamp = release_date.strftime("%Y%m%d")
        path = root / "releases" / stamp / "g17.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        entries.append(
            {
                "release_date": release_date.isoformat(),
                "release_type": "monthly",
                "href": f"{stamp}/g17.txt",
                "url": f"https://www.federalreserve.gov/releases/g17/{stamp}/g17.txt",
                "content_type": "text/plain",
                "path": path.relative_to(root).as_posix(),
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    index_payload = b'<a href="20240117/g17.txt">one</a>'
    index_path = root / "index" / "fixture.html"
    index_path.parent.mkdir(parents=True)
    index_path.write_bytes(index_payload)
    (root / "release-index.json").write_text(
        json.dumps(
            {
                "index_snapshot": {
                    "path": index_path.relative_to(root).as_posix(),
                    "sha256": hashlib.sha256(index_payload).hexdigest(),
                },
                "releases": entries,
            }
        ),
        encoding="utf-8",
    )

    observations = parse_fed_g17_archive(root)
    audit = audit_fed_g17_archive(root)

    assert len(observations) == 16
    assert {row.series_id for row in observations} == {
        FED_G17_INDEX_SERIES_ID,
        FED_G17_MOM_SERIES_ID,
    }
    december_levels = [
        row
        for row in observations
        if row.series_id == FED_G17_INDEX_SERIES_ID
        and row.observation_date == date(2023, 12, 1)
    ]
    assert [row.value for row in december_levels] == [102.4, 102.5]
    assert december_levels[0].realtime_end == date(2024, 2, 14)
    assert all(row.release_timestamp is not None for row in observations)
    assert audit["release_count"] == 2
    assert audit["canonical_vintage_rows"] == 16
    assert audit["exact_release_clock_times_verified"] is True
