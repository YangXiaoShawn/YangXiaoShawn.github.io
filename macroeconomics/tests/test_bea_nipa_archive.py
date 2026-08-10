from __future__ import annotations

import hashlib
import io
import json
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

import macro_nowcast.bea_nipa_archive as nipa
from macro_nowcast.bea_nipa_archive import (
    BEANIPAArchiveError,
    BEANIPARelease,
    acquire_bea_nipa_level_archive,
    audit_bea_nipa_level_archive,
    parse_bea_nipa_release_inventory,
    parse_real_gdp_level_snapshot,
    quarter_range,
    select_bea_nipa_section1_file,
    target_quarter_from_release_label,
)


def _column_name(number: int) -> str:
    result = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        result = chr(ord("A") + remainder) + result
    return result


def _xlsx_bytes(sheet_name: str, rows: list[list[object | None]]) -> bytes:
    xml_rows: list[str] = []
    for row_index, row in enumerate(rows, start=1):
        cells: list[str] = []
        for column_index, value in enumerate(row, start=1):
            if value is None:
                continue
            reference = f"{_column_name(column_index)}{row_index}"
            if isinstance(value, str):
                cells.append(
                    f'<c r="{reference}" t="inlineStr"><is><t>{escape(value)}</t></is></c>'
                )
            else:
                cells.append(f'<c r="{reference}"><v>{value}</v></c>')
        xml_rows.append(f'<row r="{row_index}">{"".join(cells)}</row>')
    workbook = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheets><sheet name="{escape(sheet_name)}" sheetId="1" r:id="rId1"/></sheets>'
        "</workbook>"
    )
    relationships = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/></Relationships>'
    )
    sheet = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(xml_rows)}</sheetData></worksheet>'
    )
    destination = io.BytesIO()
    with ZipFile(destination, "w", ZIP_DEFLATED) as archive:
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", relationships)
        archive.writestr("xl/worksheets/sheet1.xml", sheet)
    return destination.getvalue()


def _modern_snapshot(
    *,
    published: str,
    prior_quarter: str,
    target_quarter: str,
    prior: object,
    target: object,
) -> bytes:
    return _xlsx_bytes(
        "T10106-Q",
        [
            ["Table 1.1.6. Real Gross Domestic Product, Chained Dollars"],
            ["[Millions of chained (2017) dollars] Seasonally adjusted at annual rates"],
            [f"Quarterly data to {target_quarter}"],
            ["Bureau of Economic Analysis"],
            [f"Data published {published}"],
            ["File created for test"],
            [],
            ["Line", None, None, prior_quarter, target_quarter],
            ["1", "Gross domestic product", "A191RX", prior, target],
        ],
    )


def _middle_snapshot() -> bytes:
    return _xlsx_bytes(
        "10106 Qtr",
        [
            ["Table 1.1.6. Real Gross Domestic Product, Chained Dollars"],
            ["[Billions of chained (2009) dollars]; Seasonally adjusted at annual rates"],
            ["Quarterly data from 1969 To 2014"],
            ["Bureau of Economic Analysis"],
            ["Data published October 30, 2014"],
            ["File created 10/29/2014"],
            [],
            ["Line", None, None, 2014, 2014],
            [None, None, None, 2, 3],
            [1, "Gross domestic product", "A191RX1", 16010.4, 16150.6],
        ],
    )


def _old_snapshot() -> bytes:
    return _xlsx_bytes(
        "102 Qtr",
        [
            ["Table 1.2. Real Gross Domestic Product"],
            ["[Billions of chained (1996) dollars]"],
            ["Quarterly data from 1947 To 2002"],
            ["Bureau of Economic Analysis"],
            ["Data published October 31, 2002"],
            ["File created 10/31/2002"],
            [],
            [None, "Line", None, 2002, 2002],
            [None, None, None, 2, 3],
            ["Gross domestic product", 1, "A191RX", 9392.4, 9465.2],
        ],
    )


def _inventory(paths: list[str]) -> bytes:
    return json.dumps(
        {
            "MainName": "National Accounts (NIPA)",
            "DescriptionLong": (
                "This archive is provided for research only. "
                "All files are in Microsoft Excel format."
            ),
            "FileArray": paths,
        }
    ).encode()


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _write_clock_evidence(path: Path) -> None:
    raw_events = [
        {
            "release_date": "2024-10-30",
            "observation_label": (
                "Gross Domestic Product, Third Quarter 2024 (Advance Estimate)"
            ),
            "official_url": (
                "https://www.bea.gov/news/2024/"
                "gross-domestic-product-3rd-quarter-2024-advance-estimate"
            ),
            "header_text": (
                "EMBARGOED UNTIL RELEASE AT 8:30 A.M. EDT, "
                "Wednesday, October 30, 2024"
            ),
            "source_release_type": "Advance",
        },
        {
            "release_date": "2025-01-30",
            "observation_label": (
                "Gross Domestic Product, 4th Quarter and Year 2024 (Advance Estimate)"
            ),
            "official_url": (
                "https://www.bea.gov/news/2025/"
                "gross-domestic-product-4th-quarter-and-year-2024-advance-estimate"
            ),
            "header_text": (
                "EMBARGOED UNTIL RELEASE AT 8:30 A.M. EST, "
                "Thursday, January 30, 2025"
            ),
            "source_release_type": "Advance",
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
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def test_release_inventory_preserves_case_and_explicit_gaps() -> None:
    paths = [
        (
            "/Inetpub/wwwroot/website/website/HistData/Files/Releases/GDP_and_PI"
            "\\2002\\Q3\\1. Advance_October-31-2002"
        ),
        (
            "/Inetpub/wwwroot/website/website/HistData/Files/Releases/GDP_and_PI"
            "\\2002\\Q3\\1. Advance_October-31-2002\\UND"
        ),
        (
            "/Inetpub/wwwroot/website/website/HistData/Files/Releases/GDP_and_PI"
            "\\2002\\Q4\\1. Advance_January-30-2003"
        ),
    ]
    parsed = parse_bea_nipa_release_inventory(
        _inventory(paths),
        expected_first_quarter="2002Q1",
        expected_last_quarter="2002Q4",
    )

    assert [row.target_quarter for row in parsed.releases] == ["2002Q3", "2002Q4"]
    assert parsed.missing_quarters == ("2002Q1", "2002Q2")
    assert parsed.releases[0].archive_path.endswith("\\2002\\Q3\\1. Advance_October-31-2002")
    assert quarter_range("2002Q3", "2003Q1") == ("2002Q3", "2002Q4", "2003Q1")


def test_section1_selection_excludes_nested_and_preserves_lowercase_quarter() -> None:
    release = BEANIPARelease(
        target_quarter="2014Q3",
        release_type="Advance",
        archive_directory_date=date(2014, 10, 30),
        archive_directory_label="Advance_October-30-2014",
        archive_path=(
            "/Inetpub/wwwroot/website/website/HistData/Files/Releases/GDP_and_PI"
            "\\2014\\q3\\Advance_October-30-2014"
        ),
    )
    direct = f"{release.archive_path}\\Section1all_xls.xls"
    document = {
        "FileArray": [
            f"{release.archive_path}\\UND\\Section1all_xls.xls",
            f"{release.archive_path}\\Section1ALL_Hist.xls",
            direct,
        ]
    }

    server_path, url = select_bea_nipa_section1_file(document, release=release)

    assert server_path == direct
    assert "/2014/q3/Advance_October-30-2014/Section1all_xls.xls" in unquote(url)


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ('Gross Domestic Product First Quarter 2002 "advance" estimate', "2002Q1"),
        ("Gross Domestic Product, 4th quarter and Annual 2011", "2011Q4"),
        ("GDP (Advance Estimate), 2nd Quarter 2026", "2026Q2"),
    ],
)
def test_target_quarter_from_release_label(label: str, expected: str) -> None:
    assert target_quarter_from_release_label(label) == expected


@pytest.mark.parametrize(
    ("payload", "quarter", "release_date", "timestamp", "sheet", "base", "scale"),
    [
        (
            _old_snapshot(),
            "2002Q3",
            date(2002, 10, 31),
            datetime(2002, 10, 31, 13, 30, tzinfo=UTC),
            "102 Qtr",
            1996,
            "billions",
        ),
        (
            _middle_snapshot(),
            "2014Q3",
            date(2014, 10, 30),
            datetime(2014, 10, 30, 12, 30, tzinfo=UTC),
            "10106 Qtr",
            2009,
            "billions",
        ),
        (
            _modern_snapshot(
                published="January 30, 2025",
                prior_quarter="2024Q3",
                target_quarter="2024Q4",
                prior=23_400_294,
                target=23_530_909,
            ),
            "2024Q4",
            date(2025, 1, 30),
            datetime(2025, 1, 30, 13, 30, tzinfo=UTC),
            "T10106-Q",
            2017,
            "millions",
        ),
    ],
)
def test_parse_real_gdp_level_snapshot_across_workbook_eras(
    payload: bytes,
    quarter: str,
    release_date: date,
    timestamp: datetime,
    sheet: str,
    base: int,
    scale: str,
) -> None:
    snapshot = parse_real_gdp_level_snapshot(
        payload,
        target_quarter=quarter,
        release_date=release_date,
        release_timestamp=timestamp,
        release_type="Advance",
    )

    assert snapshot.sheet_name == sheet
    assert snapshot.chained_dollar_reference_year == base
    assert snapshot.scale == scale
    assert snapshot.target_level > snapshot.prior_level
    assert snapshot.qoq_saar_percent > 0


def test_snapshot_rejects_publication_date_and_future_period_drift() -> None:
    payload = _modern_snapshot(
        published="January 31, 2025",
        prior_quarter="2024Q3",
        target_quarter="2024Q4",
        prior=100,
        target=101,
    )
    with pytest.raises(BEANIPAArchiveError, match="publication date"):
        parse_real_gdp_level_snapshot(
            payload,
            target_quarter="2024Q4",
            release_date=date(2025, 1, 30),
            release_timestamp=datetime(2025, 1, 30, 13, 30, tzinfo=UTC),
            release_type="Advance",
        )

    abbreviated = _modern_snapshot(
        published="Oct 27 2017 8:30AM",
        prior_quarter="2017Q2",
        target_quarter="2017Q3",
        prior="19,034,471",
        target="19,188,218",
    )
    parsed = parse_real_gdp_level_snapshot(
        abbreviated,
        target_quarter="2017Q3",
        release_date=date(2017, 10, 27),
        release_timestamp=datetime(2017, 10, 27, 12, 30, tzinfo=UTC),
        release_type="Advance",
    )
    assert parsed.published_date == date(2017, 10, 27)


def test_acquire_and_audit_two_release_archive_offline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prefix = "/Inetpub/wwwroot/website/website/HistData/Files/Releases/GDP_and_PI"
    release_paths = {
        "2024Q3": f"{prefix}\\2024\\Q3\\Advance_October-30-2024",
        "2024Q4": f"{prefix}\\2024\\Q4\\Advance_January-31-2025",
    }
    source_inventory = _inventory(list(release_paths.values()))
    workbooks = {
        "2024Q3": _modern_snapshot(
            published="October 30, 2024",
            prior_quarter="2024Q2",
            target_quarter="2024Q3",
            prior=23_223_906,
            target=23_400_294,
        ),
        "2024Q4": _modern_snapshot(
            published="January 30, 2025",
            prior_quarter="2024Q3",
            target_quarter="2024Q4",
            prior=23_400_294,
            target=23_530_909,
        ),
    }
    file_lists: dict[str, bytes] = {}
    file_urls: dict[str, bytes] = {}
    for quarter, path in release_paths.items():
        filename = "Section1all_xls.xlsx"
        server_path = f"{path}\\{filename}"
        file_lists[quarter] = json.dumps({"FileArray": [server_path]}).encode()
        file_urls[nipa._public_file_url(server_path)] = workbooks[quarter]

    def fake_fetch(url: str, *, attempts: int = 5) -> tuple[bytes, str]:
        del attempts
        if url == nipa.BEA_NIPA_RELEASE_INVENTORY_URL:
            return source_inventory, "application/json"
        if url.startswith(nipa.BEA_NIPA_FILE_INVENTORY_ENDPOINT):
            path = parse_qs(urlparse(url).query)["thePath"][0]
            quarter = next(q for q, release_path in release_paths.items() if release_path == path)
            return file_lists[quarter], "application/json"
        if url in file_urls:
            return (
                file_urls[url],
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr(nipa, "_fetch", fake_fetch)
    clock_path = tmp_path / "clock-evidence.json"
    _write_clock_evidence(clock_path)
    root = tmp_path / "archive"

    result = acquire_bea_nipa_level_archive(
        root,
        clock_evidence_path=clock_path,
        expected_first_quarter="2024Q3",
        expected_last_quarter="2024Q4",
        workers=2,
    )
    audit = audit_bea_nipa_level_archive(root, clock_evidence_path=clock_path)

    assert result["status"] == "verified_with_archive_gaps"
    assert result["snapshot_count"] == 2
    assert result["canonical_vintage_rows"] == 4
    assert audit["missing_quarters"] == []
    assert audit["directory_date_conflict_count"] == 1
    assert audit["chained_dollar_reference_years"] == [2017]
    manifest = json.loads((root / "release-index.json").read_text())
    assert manifest["api_txt_read"] is False
    assert manifest["releases"][1]["archive_directory_date"] == "2025-01-31"
    assert manifest["releases"][1]["verified_release_date"] == "2025-01-30"

    monkeypatch.setattr(
        nipa,
        "_fetch",
        lambda *_args, **_kwargs: pytest.fail("completed archive must audit offline"),
    )
    repeated = acquire_bea_nipa_level_archive(
        root,
        clock_evidence_path=clock_path,
        expected_first_quarter="2024Q3",
        expected_last_quarter="2024Q4",
        workers=2,
    )
    assert repeated["network_used"] is False

    with pytest.raises(BEANIPAArchiveError, match="window differs"):
        acquire_bea_nipa_level_archive(
            root,
            clock_evidence_path=clock_path,
            expected_first_quarter="2024Q4",
            expected_last_quarter="2024Q4",
        )

    workbook_path = next((root / "snapshots" / "2024Q4").iterdir())
    workbook_path.write_bytes(workbook_path.read_bytes() + b"tampered")
    with pytest.raises(BEANIPAArchiveError, match="byte-count mismatch"):
        audit_bea_nipa_level_archive(root, clock_evidence_path=clock_path)
