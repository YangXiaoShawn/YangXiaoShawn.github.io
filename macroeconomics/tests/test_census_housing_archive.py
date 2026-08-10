from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

import macro_nowcast.census_housing_archive as nrc
from macro_nowcast.census_housing_archive import (
    CENSUS_HOUSING_STARTS_SERIES_ID,
    CensusHousingArchiveError,
    CensusHousingReleaseValues,
    audit_census_housing_archive,
    parse_census_housing_archive,
    parse_census_housing_archive_index,
    parse_census_housing_release_text,
)


def _release_text(
    *,
    header: str,
    title: str,
    month: str,
    level: str,
) -> str:
    return f"""
    {header}
    {title}
    BUILDING PERMITS
    Privately-owned housing units authorized by building permits in {month} were at a
    seasonally adjusted annual rate of 1,500,000.
    HOUSING STARTS
    Privately-owned housing starts in {month} were at a seasonally adjusted annual rate
    of {level}. This is 2.0 percent above the revised prior-month estimate.
    """


def test_archive_index_retains_unique_reference_month_pdfs() -> None:
    releases = parse_census_housing_archive_index(
        """
        <a href="/construction/nrc/pdf/newresconst_202401.pdf">January</a>
        <a href="/construction/nrc/pdf/newresconst_202401.pdf">duplicate</a>
        <a href="/construction/nrc/pdf/newresconst_202402.pdf">February</a>
        <a href="fhttps://www.census.gov/construction/nrc/pdf/newresconst_200904.pdf">
        malformed official April 2009 link</a>
        <a href="/construction/nrc/data/newresconst_202402.xlsx">workbook</a>
        """
    )

    assert [release.observation_date for release in releases] == [
        date(2009, 4, 1),
        date(2024, 1, 1),
        date(2024, 2, 1),
    ]
    assert releases[0].official_url.startswith("https://")
    assert releases[1].relative_path == Path("releases/newresconst_202401.pdf")


@pytest.mark.parametrize(
    ("header", "title", "month", "level", "observation_date", "expected"),
    [
        (
            "U.S. Census Bureau For Release 8: 30 A.M. EST, Wednesday, February 19, 2003",
            "NEW RESIDENTIAL CONSTRUCTION IN JANUARY 2003",
            "January",
            "1,850,000",
            date(2003, 1, 1),
            ("2003-02-19T13:30:00+00:00", 1850.0, "EST"),
        ),
        (
            "FOR IMMEDIATE RELEASE WEDNESDAY, FEBRUARY 18, 2015 AT 8:30 A.M. EST",
            "NEW RESIDENTIAL CONSTRUCTION IN JANUARY 2015",
            "January",
            "1,065,000",
            date(2015, 1, 1),
            ("2015-02-18T13:30:00+00:00", 1065.0, "EST"),
        ),
        (
            "FOR RELEASE AT 8:30 AM EDT, FRIDAY, JULY 17, 2026",
            "MONTHLY NEW RESIDENTIAL CONSTRUCTION, JUNE 2026",
            "June",
            "1,427,000",
            date(2026, 6, 1),
            ("2026-07-17T12:30:00+00:00", 1427.0, "EDT"),
        ),
    ],
)
def test_release_text_parses_cross_era_header_and_housing_starts(
    header: str,
    title: str,
    month: str,
    level: str,
    observation_date: date,
    expected: tuple[str, float, str],
) -> None:
    parsed = parse_census_housing_release_text(
        _release_text(header=header, title=title, month=month, level=level),
        observation_date=observation_date,
    )

    assert parsed.release_timestamp.isoformat() == expected[0]
    assert parsed.housing_starts_thousands_saar == expected[1]
    assert parsed.release_zone_label == expected[2]


def test_release_text_rejects_filename_title_month_disagreement() -> None:
    with pytest.raises(CensusHousingArchiveError, match="disagrees"):
        parse_census_housing_release_text(
            _release_text(
                header="FOR RELEASE AT 8:30 AM EST, FRIDAY, FEBRUARY 16, 2024",
                title="MONTHLY NEW RESIDENTIAL CONSTRUCTION, JANUARY 2024",
                month="January",
                level="1,331,000",
            ),
            observation_date=date(2024, 2, 1),
        )


def test_local_archive_hash_audit_builds_canonical_housing_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "census-nrc"
    entries: list[dict[str, object]] = []
    for observation_date, release_date, payload in [
        (date(2024, 1, 1), date(2024, 2, 16), b"%PDF fixture-one"),
        (date(2024, 2, 1), date(2024, 3, 19), b"%PDF fixture-two"),
    ]:
        filename = f"newresconst_{observation_date:%Y%m}.pdf"
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
                    13 if release_date.month == 2 else 12,
                    30,
                    tzinfo=UTC,
                ).isoformat(),
                "release_zone_label": "EST" if release_date.month == 2 else "EDT",
                "url": f"https://www.census.gov/construction/nrc/pdf/{filename}",
                "content_type": "application/pdf",
                "path": path.relative_to(root).as_posix(),
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    index_payload = b'<a href="newresconst_202401.pdf">one</a>'
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
        release: nrc.CensusHousingRelease,
    ) -> CensusHousingReleaseValues:
        del payload
        release_date = date(
            release.observation_date.year + (release.observation_date.month == 12),
            release.observation_date.month % 12 + 1,
            16 if release.observation_date.month == 1 else 19,
        )
        return CensusHousingReleaseValues(
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
            housing_starts_thousands_saar=1_400.0 + release.observation_date.month,
        )

    monkeypatch.setattr(nrc, "parse_census_housing_release", parse_fixture)
    observations = parse_census_housing_archive(root)
    audit = audit_census_housing_archive(root)

    assert len(observations) == 2
    assert {row.series_id for row in observations} == {CENSUS_HOUSING_STARTS_SERIES_ID}
    assert all(row.release_timestamp is not None for row in observations)
    assert audit["release_count"] == 2
    assert audit["canonical_vintage_rows"] == 2
    assert audit["missing_reference_months"] == []
    assert audit["all_canonical_keys_unique"] is True
