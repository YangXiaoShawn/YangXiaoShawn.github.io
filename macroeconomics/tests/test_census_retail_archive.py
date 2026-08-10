from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

import macro_nowcast.census_retail_archive as marts
from macro_nowcast.census_retail_archive import (
    CENSUS_RETAIL_LEVEL_SERIES_ID,
    CENSUS_RETAIL_MOM_SERIES_ID,
    CensusRetailArchiveError,
    CensusRetailReleaseValues,
    audit_census_retail_archive,
    parse_census_retail_archive,
    parse_census_retail_archive_index,
    parse_census_retail_release_text,
)


def _release_text(
    *,
    header: str,
    observation_label: str,
    level: str,
    direction: str,
    change: str,
) -> str:
    return f"""
    {header}
    ADVANCE MONTHLY SALES FOR RETAIL AND FOOD SERVICES, {observation_label}
    The U.S. Census Bureau announced the following advance estimates.
    Advance estimates of U.S. retail and food services sales for {observation_label},
    adjusted for seasonal variation and holiday and trading-day differences, but not for
    price changes, were ${level} billion, {direction} {change} percent from the previous
    month, and up 4.0 percent from the prior year.
    """


def test_archive_index_retains_unique_pdf_reference_months() -> None:
    releases = parse_census_retail_archive_index(
        """
        <a href="https://www2.census.gov/retail/releases/historical/marts/adv2401.pdf">PDF</a>
        <a href="https://www2.census.gov/retail/releases/historical/marts/rs2401.xlsx">XLSX</a>
        <a href="https://www2.census.gov/retail/releases/historical/marts/adv2401.pdf">
        PDF duplicate</a>
        <a href="https://www2.census.gov/retail/releases/historical/marts/adv2402.pdf">PDF</a>
        """
    )

    assert [release.observation_date for release in releases] == [
        date(2024, 1, 1),
        date(2024, 2, 1),
    ]
    assert releases[0].relative_path == Path("releases/adv2401.pdf")


@pytest.mark.parametrize(
    ("header", "observation_label", "level", "direction", "change", "expected"),
    [
        (
            "FOR RELEASE AT 8:30 AM EDT, WEDNESDAY, JUNE 17, 2026",
            "MAY 2026",
            "763.7",
            "up",
            "0.9",
            ("2026-06-17T12:30:00+00:00", 763.7, 0.9, "EDT"),
        ),
        (
            "FOR IMMEDIATE RELEASE THURSDAY, JANUARY 12, 2012, AT 8:30 A.M. EST",
            "DECEMBER 2011",
            "400.6",
            "an increase of",
            "0.1",
            ("2012-01-12T13:30:00+00:00", 400.6, 0.1, "EST"),
        ),
        (
            "FOR WIRE TRANSMISSION 8:30 A.M. ET, Thursday, February 13, 2003.",
            "JANUARY 2003",
            "306.6",
            "a decrease of",
            "0.9",
            ("2003-02-13T13:30:00+00:00", 306.6, -0.9, "ET"),
        ),
    ],
)
def test_release_text_parses_cross_era_header_and_advance_estimate(
    header: str,
    observation_label: str,
    level: str,
    direction: str,
    change: str,
    expected: tuple[str, float, float, str],
) -> None:
    month, year = observation_label.split()
    parsed = parse_census_retail_release_text(
        _release_text(
            header=header,
            observation_label=observation_label,
            level=level,
            direction=direction,
            change=change,
        ),
        observation_date=date(int(year), marts._MONTHS[month.lower()], 1),
    )

    assert parsed.release_timestamp.isoformat() == expected[0]
    assert parsed.sales_level_billions == expected[1]
    assert parsed.percent_change_mom == expected[2]
    assert parsed.release_zone_label == expected[3]


def test_release_text_rejects_filename_title_month_disagreement() -> None:
    with pytest.raises(CensusRetailArchiveError, match="disagrees"):
        parse_census_retail_release_text(
            _release_text(
                header="FOR RELEASE AT 8:30 AM EST, THURSDAY, FEBRUARY 15, 2024",
                observation_label="JANUARY 2024",
                level="700.0",
                direction="up",
                change="0.2",
            ),
            observation_date=date(2024, 2, 1),
        )


def test_local_archive_hash_audit_builds_level_and_published_change_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "census-marts"
    entries: list[dict[str, object]] = []
    for observation_date, release_date, payload in [
        (date(2024, 1, 1), date(2024, 2, 15), b"%PDF fixture-one"),
        (date(2024, 2, 1), date(2024, 3, 14), b"%PDF fixture-two"),
    ]:
        filename = f"adv{observation_date:%y%m}.pdf"
        path = root / "releases" / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        entries.append(
            {
                "observation_date": observation_date.isoformat(),
                "release_date": release_date.isoformat(),
                "release_timestamp": datetime(
                    release_date.year,
                    release_date.month,
                    release_date.day,
                    13,
                    30,
                    tzinfo=UTC,
                ).isoformat(),
                "release_zone_label": "EST" if release_date.month == 2 else "EDT",
                "url": f"https://www2.census.gov/retail/releases/historical/marts/{filename}",
                "content_type": "application/pdf",
                "path": path.relative_to(root).as_posix(),
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    index_payload = b'<a href="adv2401.pdf">one</a>'
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

    def parse_fixture(
        payload: bytes,
        *,
        release: marts.CensusRetailRelease,
    ) -> CensusRetailReleaseValues:
        del payload
        release_date = date(
            release.observation_date.year + (release.observation_date.month == 12),
            release.observation_date.month % 12 + 1,
            15 if release.observation_date.month == 1 else 14,
        )
        return CensusRetailReleaseValues(
            observation_date=release.observation_date,
            release_date=release_date,
            release_timestamp=datetime(
                release_date.year,
                release_date.month,
                release_date.day,
                13 if release_date.month == 2 else 12,
                30,
                tzinfo=UTC,
            ),
            release_zone_label="EST" if release_date.month == 2 else "EDT",
            sales_level_billions=700.0 + release.observation_date.month,
            percent_change_mom=0.1 * release.observation_date.month,
        )

    monkeypatch.setattr(marts, "parse_census_retail_release", parse_fixture)
    observations = parse_census_retail_archive(root)
    audit = audit_census_retail_archive(root)

    assert len(observations) == 4
    assert {row.series_id for row in observations} == {
        CENSUS_RETAIL_LEVEL_SERIES_ID,
        CENSUS_RETAIL_MOM_SERIES_ID,
    }
    assert all(row.release_timestamp is not None for row in observations)
    assert audit["release_count"] == 2
    assert audit["canonical_vintage_rows"] == 4
    assert audit["missing_reference_months"] == []
    assert audit["all_canonical_keys_unique"] is True
