from __future__ import annotations

import io
import json
from datetime import UTC, datetime
from pathlib import Path
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

from macro_nowcast.archive_audit import (
    CES_FILENAME,
    CES_RELEASE_INDEX_FILENAME,
    CPI_ARCHIVE_YEARS,
    CPI_CURRENT_PERIODS,
    CPI_RELEASE_INDEX_FILENAME,
    EMPSIT_DOM_DIRECTORY,
    GDP_NIPA_SAMPLE_FILENAME,
    GDP_VINTAGE_FILENAME,
    audit_agency_vintages,
    write_agency_vintage_audit,
)
from macro_nowcast.bls_empsit_clock_archive import (
    BLS_EMPSIT_CLOCK_DIRECTORY,
    write_empsit_text_clock_index,
)


def _column_name(number: int) -> str:
    result = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        result = chr(ord("A") + remainder) + result
    return result


def _xlsx_bytes(sheets: dict[str, list[list[object | None]]]) -> bytes:
    workbook_sheets: list[str] = []
    relationships: list[str] = []
    sheet_documents: list[tuple[str, str]] = []
    for sheet_index, (name, rows) in enumerate(sheets.items(), start=1):
        workbook_sheets.append(
            f'<sheet name="{escape(name)}" sheetId="{sheet_index}" r:id="rId{sheet_index}"/>'
        )
        relationships.append(
            f'<Relationship Id="rId{sheet_index}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            f'Target="worksheets/sheet{sheet_index}.xml"/>'
        )
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
        sheet_documents.append(
            (
                f"xl/worksheets/sheet{sheet_index}.xml",
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                f"<sheetData>{''.join(xml_rows)}</sheetData></worksheet>",
            )
        )

    workbook = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f"<sheets>{''.join(workbook_sheets)}</sheets></workbook>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f"{''.join(relationships)}</Relationships>"
    )
    destination = io.BytesIO()
    with ZipFile(destination, "w", ZIP_DEFLATED) as archive:
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", rels)
        for filename, document in sheet_documents:
            archive.writestr(filename, document)
    return destination.getvalue()


def _write_offline_fixture(directory: Path) -> None:
    directory.mkdir()
    with ZipFile(directory / CES_FILENAME, "w", ZIP_DEFLATED) as archive:
        archive.writestr(
            "tri_000000_SA.csv",
            "year,month,Jan_03,Feb_03,Mar_03,Apr_03,May_03,Jun_03\n"
            "2003,5,1,2,3,4,5,\n"
            "2003,6,1,2,3,4,5,6\n",
        )
    (directory / CES_RELEASE_INDEX_FILENAME).write_text(
        json.dumps(
            {
                "source_url": "https://www.bls.gov/bls/news-release/empsit.htm",
                "release_events": [
                    {
                        "release_date": "2003-06-06",
                        "observation_label": None,
                        "html_available": True,
                    },
                    {
                        "release_date": "2003-07-03",
                        "observation_label": None,
                        "html_available": True,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    empsit_dom = directory / EMPSIT_DOM_DIRECTORY
    empsit_dom.mkdir()
    for release_date in ("06062003", "07032003"):
        parsed = datetime.strptime(release_date, "%m%d%Y")
        (empsit_dom / f"empsit_{release_date}.htm").write_text(
            "<html><body>Employment Situation News Release "
            "Transmission of material is embargoed until 8:30 a.m. (EDT) "
            f"{parsed:%A, %B %-d, %Y}. Table A-1 {release_date}</body></html>",
            encoding="utf-8",
        )
    empsit_text = directory / BLS_EMPSIT_CLOCK_DIRECTORY
    empsit_text.mkdir()
    for release_date in ("06062003", "07032003"):
        parsed = datetime.strptime(release_date, "%m%d%Y")
        (empsit_text / f"empsit_{release_date}.txt").write_text(
            "Transmission of material in this release is embargoed until "
            f"8:30 a.m. (EDT) {parsed:%A, %B %-d, %Y}.\n",
            encoding="ascii",
        )
    write_empsit_text_clock_index(
        empsit_text,
        directory / CES_RELEASE_INDEX_FILENAME,
        retrieved_at=datetime(2026, 8, 10, tzinfo=UTC),
    )

    cpi_workbook = _xlsx_bytes({"US": [["Item"], ["All items less food and energy", 313.623]]})
    for year in CPI_ARCHIVE_YEARS:
        with ZipFile(
            directory / f"cpi-supplemental-{year}.zip",
            "w",
            ZIP_DEFLATED,
        ) as archive:
            for month in range(1, 13):
                legacy = year < 2014 or (year == 2014 and month < 12)
                extension = "xls" if legacy else "xlsx"
                archive.writestr(
                    f"archive-{year}/CPI-U_{year}{month:02d}.{extension}",
                    cpi_workbook,
                )
    current = directory / "cpi-current"
    current.mkdir()
    for period in CPI_CURRENT_PERIODS:
        (current / f"cpi-u-{period}.xlsx").write_bytes(cpi_workbook)
    month_names = (
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
    )
    cpi_periods = [
        f"{year}{month:02d}" for year in CPI_ARCHIVE_YEARS for month in range(1, 13)
    ] + list(CPI_CURRENT_PERIODS)
    (directory / CPI_RELEASE_INDEX_FILENAME).write_text(
        json.dumps(
            {
                "source_url": "https://www.bls.gov/bls/news-release/cpi.htm",
                "release_events": [
                    {
                        "release_date": f"{period[:4]}-{period[4:]}-15",
                        "observation_label": (
                            f"{month_names[int(period[4:]) - 1]} {period[:4]} Consumer Price Index"
                        ),
                    }
                    for period in cpi_periods
                ],
            }
        ),
        encoding="utf-8",
    )

    (directory / GDP_VINTAGE_FILENAME).write_bytes(
        _xlsx_bytes(
            {
                "ReadMe": [["Advance, Second, and Third estimates"]],
                "Vintage History": [
                    ["2024Q4"],
                    [None, "Advance", None, None, 2.3, None, "Jan 30, 2025"],
                    ["2002Q1"],
                    [None, "Advance", None, None, 5.8, None, "Apr 26, 2002"],
                ],
            }
        )
    )
    (directory / GDP_NIPA_SAMPLE_FILENAME).write_bytes(
        _xlsx_bytes(
            {
                "Contents": [["Table 1.1.6. Real Gross Domestic Product"]],
                "T10106-Q": [
                    ["Table 1.1.6. Real Gross Domestic Product, Chained Dollars"],
                    ["Data published January 30, 2025"],
                    ["Line", "Description", "Code", "2024Q3", "2024Q4"],
                    ["1", "Gross domestic product", "A191RX", 23_400_294, 23_530_909],
                ],
            }
        )
    )


def test_audit_fails_closed_when_required_files_are_missing(tmp_path: Path) -> None:
    report = audit_agency_vintages(
        tmp_path,
        audited_at=datetime(2026, 8, 9, 18, tzinfo=UTC),
    )

    assert report["status"] == "failed"
    assert report["historical_ingestion_ready"] is False
    assert report["api_credentials_used"] is False
    assert report["api_txt_read"] is False
    assert all(
        artifact["passed"] is False
        for artifact in report["artifacts"].values()  # type: ignore[union-attr]
    )


def test_offline_archive_audit_verifies_content_and_gdp_crosscheck(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    _write_offline_fixture(raw_dir)

    report = audit_agency_vintages(
        raw_dir,
        audited_at=datetime(2026, 8, 9, 18, tzinfo=UTC),
    )
    artifacts = report["artifacts"]

    assert report["status"] == "verified_with_limitations"
    assert report["historical_ingestion_ready"] is False
    assert artifacts["ces"]["first_vintage_period"] == "2003-05"  # type: ignore[index]
    assert artifacts["ces"]["vintage_rows"] == 2  # type: ignore[index]
    assert artifacts["ces"]["release_mapping"]["mapped_vintage_periods"] == 2  # type: ignore[index]
    assert artifacts["employment_situation_dom"]["file_count"] == 2  # type: ignore[index]
    assert artifacts["employment_situation_dom"]["all_hashes_unique"] is True  # type: ignore[index]
    assert artifacts["employment_situation_dom"]["exact_release_clock_count"] == 2  # type: ignore[index]
    assert artifacts["employment_situation_dom"]["date_only_clock_exclusion_count"] == 0  # type: ignore[index]
    text_clocks = artifacts["employment_situation_txt_clock_evidence"]  # type: ignore[index]
    assert text_clocks["file_count"] == 2
    assert text_clocks["exact_release_clock_count"] == 2
    assert text_clocks["server_original_bytes_claimed"] is True
    assert artifacts["cpi"]["annual_archive_count"] == 13  # type: ignore[index]
    assert artifacts["cpi"]["monthly_workbooks_inventoried"] == 173  # type: ignore[index]
    assert artifacts["cpi"]["xlsx_core_content_verified"] == 138  # type: ignore[index]
    assert artifacts["cpi"]["legacy_xls_inventory_verified"] == 35  # type: ignore[index]
    assert artifacts["cpi"]["legacy_xls_core_content_verified"] == 35  # type: ignore[index]
    assert artifacts["cpi"]["legacy_xls_value_parser_available"] is True  # type: ignore[index]
    assert artifacts["cpi"]["legacy_xls_value_parser_pending"] is False  # type: ignore[index]
    assert artifacts["cpi"]["documented_missing_periods"] == ["202510"]  # type: ignore[index]
    assert artifacts["cpi"]["release_mapping"]["mapped_snapshot_periods"] == 173  # type: ignore[index]
    assert artifacts["gdp_vintage_summary"]["first_quarter"] == "2002Q1"  # type: ignore[index]
    assert artifacts["gdp_vintage_summary"]["initial_estimate_count"] == 2  # type: ignore[index]
    assert artifacts["gdp_vintage_summary"]["estimate_row_count"] == 2  # type: ignore[index]
    assert artifacts["gdp_vintage_summary"]["supports_published_first_release_growth"] is True  # type: ignore[index]
    nipa = artifacts["gdp_nipa_snapshot"]  # type: ignore[index]
    assert nipa["q3_2024_level"] == 23_400_294
    assert nipa["q4_2024_level"] == 23_530_909
    assert nipa["published_qoq_saar_percent"] == 2.3
    assert nipa["rounded_reconciliation_passed"] is True
    assert nipa["archive_directory_date_disagrees_with_release_evidence"] is True


def test_write_audit_creates_machine_readable_evidence(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    _write_offline_fixture(raw_dir)
    output = tmp_path / "audit" / "manifest.json"

    result = write_agency_vintage_audit(
        raw_dir,
        output,
        audited_at=datetime(2026, 8, 9, 18, tzinfo=UTC),
    )
    written = json.loads(output.read_text(encoding="utf-8"))

    assert result["status"] == "verified_with_limitations"
    assert result["audit_path"] == output.resolve()
    assert written["audited_at"] == "2026-08-09T18:00:00Z"
    assert written["archive_ingestion_approval"]["full_coverage_audited"] is False
