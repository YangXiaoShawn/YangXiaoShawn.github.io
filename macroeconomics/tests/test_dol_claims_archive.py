from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from macro_nowcast.dol_claims_archive import (
    DOL_CLAIMS_4WMA_SERIES_ID,
    DOL_CLAIMS_SERIES_ID,
    DOLClaimsArchiveError,
    audit_dol_claims_archive,
    parse_dol_claims_archive,
    parse_dol_claims_archive_index,
    parse_dol_claims_release_text,
)


def _release_html(current: str, paragraph: str) -> bytes:
    return (
        "<html><body><h1>UNEMPLOYMENT INSURANCE WEEKLY CLAIMS</h1>"
        f"<p>In the week ending {current}, the advance figure for seasonally adjusted "
        f"initial claims was {paragraph}</p></body></html>"
    ).encode()


def test_archive_index_parses_html_asp_and_pdf_links() -> None:
    releases = parse_dol_claims_archive_index(
        """
        <a href="/press/2003/010203.html">2</a>
        <a href="/press/2012/010512.asp">5</a>
        <a href="/press/2024/010424.pdf">4</a>
        <a href="/unemploy/data.asp">not a release</a>
        """
    )

    assert [release.release_date for release in releases] == [
        date(2003, 1, 2),
        date(2012, 1, 5),
        date(2024, 1, 4),
    ]
    assert [release.extension for release in releases] == ["html", "asp", "pdf"]
    assert releases[-1].official_url == "https://oui.doleta.gov/press/2024/010424.pdf"


def test_release_text_parses_legacy_direct_revision() -> None:
    parsed = parse_dol_claims_release_text(
        """
        In the week ending Dec. 28, the advance figure for seasonally adjusted initial
        claims was 403,000, an increase of 13,000 from the previous week's revised
        figure of 390,000. The 4-week moving average was 418,750.
        """,
        release_date=date(2003, 1, 2),
    )

    assert parsed.current_week == date(2002, 12, 28)
    assert parsed.current_advance == 403_000
    assert parsed.previous_week == date(2002, 12, 21)
    assert parsed.previous_reported == 390_000
    assert parsed.current_four_week_average == 418_750
    assert parsed.previous_vintage_type == "revised"
    assert parsed.extraction_pattern == "advance_plus_direct_revised_value"


def test_release_text_parses_modern_from_to_revision() -> None:
    parsed = parse_dol_claims_release_text(
        """
        In the week ending December 30, the advance figure for seasonally adjusted
        initial claims was 202,000, a decrease of 18,000 from the previous week's
        revised level. The previous week's level was revised up by 2,000 from 218,000
        to 220,000. The 4-week moving average was 207,750.
        """,
        release_date=date(2024, 1, 4),
    )

    assert parsed.current_week == date(2023, 12, 30)
    assert parsed.current_advance == 202_000
    assert parsed.previous_reported == 220_000
    assert parsed.previous_vintage_type == "revised"
    assert parsed.extraction_pattern == "advance_plus_explicit_revision_from_to"


def test_release_text_preserves_unrevised_prior_status() -> None:
    parsed = parse_dol_claims_release_text(
        """
        In the week ending Nov. 2, the advance figure for seasonally adjusted initial
        claims was 390,000, a decrease of 20,000 from the previous week's unrevised
        figure of 410,000. The 4-week moving average was 402,000.
        """,
        release_date=date(2002, 11, 7),
    )

    assert parsed.previous_reported == 410_000
    assert parsed.previous_vintage_type == "unrevised"
    assert parsed.extraction_pattern == "advance_plus_direct_unrevised_value"


def test_release_text_accepts_legacy_month_day_without_space() -> None:
    parsed = parse_dol_claims_release_text(
        """
        In the week ending Nov.19, the advance figure for seasonally adjusted initial
        claims was 335,000, an increase of 30,000 from the previous week's revised
        figure of 305,000. The 4-week moving average was 323,250.
        """,
        release_date=date(2005, 11, 23),
    )

    assert parsed.current_week == date(2005, 11, 19)
    assert parsed.current_advance == 335_000


def test_release_text_preserves_source_omission_of_revision_status() -> None:
    parsed = parse_dol_claims_release_text(
        """
        In the week ending December 14, the advance figure for seasonally adjusted
        initial claims was 379,000, an increase of 10,000 from the previous week's
        figure of 369,000. The 4-week moving average was 343,500.
        """,
        release_date=date(2013, 12, 19),
    )

    assert parsed.previous_reported == 369_000
    assert parsed.previous_vintage_type == "source_not_labeled"


def test_release_text_derives_prior_value_from_unchanged_statement() -> None:
    parsed = parse_dol_claims_release_text(
        """
        In the week ending November 7, the advance figure for seasonally adjusted
        initial claims was 276,000, unchanged from the previous week's unrevised level.
        The 4-week moving average was 267,750.
        """,
        release_date=date(2015, 11, 12),
    )

    assert parsed.current_advance == 276_000
    assert parsed.previous_reported == 276_000
    assert parsed.previous_vintage_type == "unrevised"
    assert parsed.extraction_pattern == "advance_plus_unchanged_unrevised_value_inferred"


def test_release_text_repairs_pdf_spacing_and_change_implied_prior() -> None:
    parsed = parse_dol_claims_release_text(
        """
        In the week ending November 15, the a dvance figure for seasonally adjusted
        initial claims was 220,000, a decrease of 8,000 from the pre vious week's
        level. The 4 -week moving average was 224,250.
        """,
        release_date=date(2025, 11, 20),
    )

    assert parsed.current_advance == 220_000
    assert parsed.previous_reported == 228_000
    assert parsed.previous_vintage_type == "source_not_labeled"
    assert parsed.extraction_pattern == "advance_plus_change_implied_prior_value"


def test_release_text_rejects_inconsistent_arithmetic() -> None:
    with pytest.raises(DOLClaimsArchiveError, match="arithmetic mismatch"):
        parse_dol_claims_release_text(
            """
            In the week ending January 6, the advance figure for seasonally adjusted
            initial claims was 200,000, a decrease of 10,000 from the previous week's
            revised figure of 250,000. The 4-week moving average was 220,000.
            """,
            release_date=date(2024, 1, 11),
        )


def test_local_archive_is_hash_audited_and_yields_two_vintages_per_release(
    tmp_path: Path,
) -> None:
    root = tmp_path / "dol-ui-claims"
    source_rows = [
        (
            date(2003, 1, 2),
            "/press/2003/010203.html",
            _release_html(
                "Dec. 28",
                "403,000, an increase of 13,000 from the previous week's revised "
                "figure of 390,000. The 4-week moving average was 418,750.",
            ),
        ),
        (
            date(2003, 1, 9),
            "/press/2003/010903.html",
            _release_html(
                "Jan. 4",
                "421,000, a decrease of 5,000 from the previous week's revised "
                "figure of 426,000. The 4-week moving average was 420,000.",
            ),
        ),
    ]
    entries: list[dict[str, object]] = []
    for release_date, href, payload in source_rows:
        relative = Path(href.removeprefix("/"))
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        entries.append(
            {
                "release_date": release_date.isoformat(),
                "href": href,
                "url": f"https://oui.doleta.gov{href}",
                "directory_year": 2003,
                "extension": "html",
                "content_type": "text/html",
                "path": relative.as_posix(),
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    (root / "release-index.json").write_text(
        json.dumps({"releases": entries}),
        encoding="utf-8",
    )

    observations = parse_dol_claims_archive(root)
    audit = audit_dol_claims_archive(root)

    assert len(observations) == 6
    assert {row.series_id for row in observations} == {
        DOL_CLAIMS_SERIES_ID,
        DOL_CLAIMS_4WMA_SERIES_ID,
    }
    assert {row.observation_date for row in observations} == {
        date(2002, 12, 21),
        date(2002, 12, 28),
        date(2003, 1, 4),
    }
    dec_28 = [
        row
        for row in observations
        if row.series_id == DOL_CLAIMS_SERIES_ID
        and row.observation_date == date(2002, 12, 28)
    ]
    assert [row.value for row in dec_28] == [403_000.0, 426_000.0]
    assert dec_28[0].realtime_end == date(2003, 1, 8)
    assert dec_28[0].availability_timestamp == datetime(2003, 1, 2, 13, 30, tzinfo=UTC)
    assert audit["passed"] is True
    assert audit["release_count"] == 2
    assert audit["canonical_vintage_rows"] == 6
    assert audit["formats"] == {"html": 2}
