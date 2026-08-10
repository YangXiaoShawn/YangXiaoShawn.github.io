from __future__ import annotations

import io
import json
from datetime import UTC, date, datetime
from pathlib import Path
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

import duckdb
import polars as pl
import pytest

import macro_nowcast.archive_ingestion as archive_ingestion
from macro_nowcast.archive_ingestion import (
    DATE_ONLY_TIMING_QUALITY,
    GDP_GROWTH_SERIES_ID,
    UNEMPLOYMENT_RATE_SERIES_ID,
    CESVintageSeriesSpec,
    OfficialArchiveData,
    parse_ces_series_vintage_archive,
    parse_ces_vintage_archive,
    parse_cpi_snapshot,
    parse_empsit_unemployment_rate_snapshot,
    parse_gdp_vintage_history,
    write_official_archive_data,
)
from macro_nowcast.bea_gdp_clock_archive import (
    BEA_GDP_CLOCK_TIMING_QUALITY,
    BEAReleaseClock,
)
from macro_nowcast.bls_release_clock import (
    BLS_EMBARGO_CLOCK_TIMING_QUALITY,
    BLSReleaseClock,
)
from macro_nowcast.calendar import RELEASE_CALENDAR_SCHEMA, build_forecast_origins
from macro_nowcast.schema import VintageObservation, observations_to_frame
from macro_nowcast.storage import VintageStore


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


def test_parse_ces_matrix_preserves_vintages_and_realtime_ends(tmp_path: Path) -> None:
    path = tmp_path / "cesvinall.zip"
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr(
            "tri_000000_SA.csv",
            "year,month,Jan_03,Feb_03,Mar_03,Apr_03,May_03,Jun_03\n"
            "2003,5,100,101,102,103,104,\n"
            "2003,6,100,101,102,103,105,106\n",
        )
    mapping = [
        {
            "vintage_period": "2003-05",
            "release_date": "2003-06-06",
            "mapping_basis": "official_date_prior_month_rule",
        },
        {
            "vintage_period": "2003-06",
            "release_date": "2003-07-03",
            "mapping_basis": "official_date_prior_month_rule",
        },
    ]

    observations = parse_ces_vintage_archive(
        path,
        mapping,
        download_timestamp=datetime(2026, 8, 9, tzinfo=UTC),
    )

    assert len(observations) == 11
    january = [row for row in observations if row.observation_date == date(2003, 1, 1)]
    assert [row.value for row in january] == [100.0, 100.0]
    assert january[0].realtime_end == date(2003, 7, 2)
    assert january[1].realtime_end is None
    assert all(row.availability_timestamp is None for row in observations)


def test_ces_exact_clock_propagates_to_rows_calendar_and_origin(tmp_path: Path) -> None:
    path = tmp_path / "cesvinall.zip"
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr(
            "tri_000000_SA.csv",
            "year,month,Apr_08,May_08\n2008,5,100,101\n2008,6,100,102\n",
        )
    mapping = [
        {
            "vintage_period": "2008-05",
            "release_date": "2008-06-06",
            "mapping_basis": "official_label",
        },
        {
            "vintage_period": "2008-06",
            "release_date": "2008-07-03",
            "mapping_basis": "official_label",
        },
    ]
    clock = BLSReleaseClock(
        release_date=date(2008, 6, 6),
        release_timestamp=datetime(2008, 6, 6, 12, 30, tzinfo=UTC),
        printed_timezone="EDT",
        printed_weekday="Friday",
    )

    observations = parse_ces_vintage_archive(
        path,
        mapping,
        release_clocks={clock.release_date: clock},
        download_timestamp=datetime(2026, 8, 9, tzinfo=UTC),
    )
    exact = [row for row in observations if row.realtime_start == date(2008, 6, 6)]
    fallback = [row for row in observations if row.realtime_start == date(2008, 7, 3)]
    assert {row.availability_timestamp for row in exact} == {clock.release_timestamp}
    assert all(row.availability_timestamp is None for row in fallback)
    assert {
        row.source_metadata["timing_quality"] for row in exact
    } == {BLS_EMBARGO_CLOCK_TIMING_QUALITY}

    calendar = archive_ingestion._release_calendar(
        mapping,
        [],
        [],
        empsit_release_clocks={clock.release_date: clock},
    )
    origins = build_forecast_origins(calendar)
    exact_origin = origins.filter(pl.col("target_period") == date(2008, 5, 1)).row(
        0, named=True
    )
    fallback_origin = origins.filter(pl.col("target_period") == date(2008, 6, 1)).row(
        0, named=True
    )
    assert exact_origin["forecast_origin"] == datetime(
        2008, 6, 6, 12, 29, 59, tzinfo=UTC
    )
    assert fallback_origin["forecast_origin"] == datetime(
        2008, 7, 3, 3, 59, 59, 999999, tzinfo=UTC
    )


def test_parse_ces_sector_matrix_keeps_official_id_and_declared_start(
    tmp_path: Path,
) -> None:
    path = tmp_path / "cesvinall.zip"
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr(
            "tri_300000_SA.csv",
            "year,month,Dec_01,Jan_02,Feb_02\n2003,5,999,1000,1001\n2003,6,998,1000,1002\n",
        )
    mapping = [
        {
            "vintage_period": "2003-05",
            "release_date": "2003-06-06",
            "mapping_basis": "official_date_prior_month_rule",
        },
        {
            "vintage_period": "2003-06",
            "release_date": "2003-07-03",
            "mapping_basis": "official_date_prior_month_rule",
        },
    ]
    definition = CESVintageSeriesSpec(
        series_id="CES3000000001",
        agency_series_id="CES3000000001",
        archive_member="tri_300000_SA.csv",
        industry_title="Manufacturing",
        observation_start=date(2002, 1, 1),
    )

    observations = parse_ces_series_vintage_archive(
        path,
        mapping,
        series=definition,
        download_timestamp=datetime(2026, 8, 9, tzinfo=UTC),
    )

    assert len(observations) == 4
    assert {row.series_id for row in observations} == {"CES3000000001"}
    assert {row.observation_date for row in observations} == {
        date(2002, 1, 1),
        date(2002, 2, 1),
    }
    metadata = observations[0].source_metadata
    assert metadata["agency_series_id"] == "CES3000000001"
    assert metadata["archive_member"] == "tri_300000_SA.csv"
    assert metadata["industry_title"] == "Manufacturing"
    assert metadata["observation_start_filter"] == "2002-01-01"


def test_parse_structured_empsit_table_preserves_published_history(tmp_path: Path) -> None:
    path = tmp_path / "empsit_06042010.htm"
    path.write_text(
        """
        <html><body><h2>Employment Situation News Release</h2>
        <table id="cps_empsit_a01">
          <tr><th>Employment status, sex, and age</th>
          <th colspan="3">Not seasonally adjusted</th>
          <th colspan="6">Seasonally adjusted</th></tr>
          <tr><th>May 2009</th><th>Apr. 2010</th><th>May 2010</th>
          <th>May 2009</th><th>Jan. 2010</th><th>Feb. 2010</th>
          <th>Mar. 2010</th><th>Apr. 2010</th><th>May 2010</th></tr>
          <tr><th>TOTAL</th><td></td></tr>
          <tr><th>Unemployment rate</th>
          <td>9.1</td><td>9.5</td><td>9.3</td><td>9.4</td><td>9.7</td>
          <td>9.7</td><td>9.7</td><td>9.9</td><td>9.7</td></tr>
        </table></body></html>
        """,
        encoding="utf-8",
    )

    rows = parse_empsit_unemployment_rate_snapshot(
        path,
        current_period=date(2010, 5, 1),
        release_date=date(2010, 6, 4),
        download_timestamp=datetime(2026, 8, 9, tzinfo=UTC),
    )

    assert [row["observation_date"] for row in rows] == [
        date(2009, 5, 1),
        date(2010, 1, 1),
        date(2010, 2, 1),
        date(2010, 3, 1),
        date(2010, 4, 1),
        date(2010, 5, 1),
    ]
    assert [row["value"] for row in rows] == [9.4, 9.7, 9.7, 9.7, 9.9, 9.7]
    assert {row["series_id"] for row in rows} == {UNEMPLOYMENT_RATE_SERIES_ID}
    assert rows[-1]["source_metadata"]["extraction_basis"] == "html_table_a1"


def test_release_clock_count_preserves_two_target_rows_on_one_release_date() -> None:
    release_date = date(2025, 12, 16)
    mapping = [
        {"vintage_period": "Oct_25", "release_date": release_date.isoformat()},
        {"vintage_period": "Nov_25", "release_date": release_date.isoformat()},
    ]

    assert archive_ingestion._count_release_rows_with_clock(
        mapping,
        {release_date: object()},
    ) == 2


def test_parse_preformatted_empsit_table_preserves_published_history(
    tmp_path: Path,
) -> None:
    path = tmp_path / "empsit_11072008.htm"
    path.write_text(
        """
        <html><body><h2>Employment Situation News Release</h2><figure><pre>
        Table A-1.  Employment status of the civilian population by sex and age
        Employment status, sex, and age
        Oct. Sept. Oct. Oct. June July Aug. Sept. Oct.
        2007 2008 2008 2007 2008 2008 2008 2008 2008
        TOTAL
        Unemployment rate.................... 4.4 6.0 6.1 4.8 5.5 5.7 6.1 6.1 6.5
        Table A-2.  Employment status by race
        </pre></figure></body></html>
        """,
        encoding="utf-8",
    )

    rows = parse_empsit_unemployment_rate_snapshot(
        path,
        current_period=date(2008, 10, 1),
        release_date=date(2008, 11, 7),
        download_timestamp=datetime(2026, 8, 9, tzinfo=UTC),
    )

    assert [(row["observation_date"], row["value"]) for row in rows] == [
        (date(2007, 10, 1), 4.8),
        (date(2008, 6, 1), 5.5),
        (date(2008, 7, 1), 5.7),
        (date(2008, 8, 1), 6.1),
        (date(2008, 9, 1), 6.1),
        (date(2008, 10, 1), 6.5),
    ]
    assert rows[-1]["source_metadata"]["extraction_basis"] == "preformatted_table_a1"


def test_parse_cpi_snapshot_handles_merged_headers_and_missing_values() -> None:
    payload = _xlsx_bytes(
        {
            "US": [
                ["Core CPI test"],
                [],
                [
                    "Expenditure category",
                    None,
                    "Unadjusted indexes",
                    None,
                    None,
                    "Seasonally adjusted indexes",
                    None,
                    None,
                    "Unadjusted percent change",
                ],
                [
                    None,
                    None,
                    "Dec.\n2023",
                    "Jan.\n2024",
                    "Feb.\n2024",
                    "Dec.\n2023",
                    "Jan.\n2024",
                    "Feb.\n2024",
                ],
                [
                    "All items less food and energy",
                    None,
                    300.0,
                    301.0,
                    302.0,
                    310.0,
                    "\N{EN DASH}",
                    312.0,
                ],
            ]
        }
    )

    rows = parse_cpi_snapshot(
        payload,
        snapshot_period="202402",
        release_date=date(2024, 3, 12),
        download_timestamp=datetime(2026, 8, 9, tzinfo=UTC),
        source_file="cpi-u-202402.xlsx",
        source_sha256="a" * 64,
        release_clock=BLSReleaseClock(
            release_date=date(2024, 3, 12),
            release_timestamp=datetime(2024, 3, 12, 12, 30, tzinfo=UTC),
            printed_timezone="EDT",
            printed_weekday="Tuesday",
        ),
        release_clock_metadata={
            "evidence_format": "browser_rendered_html_header_text_extraction",
            "header_sha256": "b" * 64,
        },
    )

    assert [(row["observation_date"], row["value"]) for row in rows] == [
        (date(2023, 12, 1), 310.0),
        (date(2024, 2, 1), 312.0),
    ]
    assert all(row["source_metadata"]["item_label_column"] == 1 for row in rows)
    assert {row["availability_timestamp"] for row in rows} == {
        datetime(2024, 3, 12, 12, 30, tzinfo=UTC)
    }
    assert {
        row["source_metadata"]["timing_quality"] for row in rows
    } == {BLS_EMBARGO_CLOCK_TIMING_QUALITY}
    assert rows[0]["source_metadata"]["release_clock_header_sha256"] == "b" * 64


def test_parse_gdp_vintage_history_preserves_published_release_types(tmp_path: Path) -> None:
    path = tmp_path / "gdp-gdi-vintage-history.xlsx"
    path.write_bytes(
        _xlsx_bytes(
            {
                "Vintage History": [
                    ["2024Q4"],
                    [None, "Advance", None, None, 2.3, None, "Jan 30, 2025"],
                    [None, "Second", None, None, 2.4, None, "Feb 27, 2025"],
                    ["2025Q1"],
                    [None, "Advance", None, None, -0.5, None, "Apr 30, 2025"],
                ]
            }
        )
    )

    clock = BEAReleaseClock(
        release_date=date(2025, 1, 30),
        release_timestamp=datetime(2025, 1, 30, 13, 30, tzinfo=UTC),
        printed_timezone="EST",
        printed_weekday="Thursday",
    )
    observations = parse_gdp_vintage_history(
        path,
        release_clocks={clock.release_date: clock},
        release_clock_metadata={
            clock.release_date: {
                "evidence_format": "browser_rendered_html_header_text_extraction",
                "header_sha256": "c" * 64,
                "archive_index_published_date": "2025-01-30",
                "source_date_discrepancy": None,
            }
        },
        download_timestamp=datetime(2026, 8, 9, tzinfo=UTC),
    )

    assert len(observations) == 3
    assert {row.series_id for row in observations} == {GDP_GROWTH_SERIES_ID}
    assert observations[0].source_metadata["release_type"] == "initial"
    assert observations[0].realtime_end == date(2025, 2, 26)
    assert observations[0].availability_timestamp == clock.release_timestamp
    assert (
        observations[0].source_metadata["timing_quality"]
        == BEA_GDP_CLOCK_TIMING_QUALITY
    )
    assert observations[1].availability_timestamp is None
    assert observations[-1].value == -0.5

    calendar = archive_ingestion._release_calendar(
        [],
        [],
        observations,
        gdp_release_clocks={clock.release_date: clock},
    )
    exact_origin = build_forecast_origins(calendar).filter(
        pl.col("target_period") == date(2024, 10, 1)
    ).row(0, named=True)
    assert exact_origin["forecast_origin"] == datetime(
        2025, 1, 30, 13, 29, 59, tzinfo=UTC
    )


def test_date_only_release_uses_previous_new_york_day_eod_origin() -> None:
    calendar = pl.from_dicts(
        [
            {
                "release_id": "bea-gdp-2024q4-initial",
                "series_id": GDP_GROWTH_SERIES_ID,
                "observation_date": date(2024, 10, 1),
                "release_timestamp": datetime(2025, 1, 30, 23, 59, 59, 999999, UTC),
                "release_type": "initial",
                "timing_quality": DATE_ONLY_TIMING_QUALITY,
                "source": "BEA_GDP_GDI_VINTAGE_HISTORY",
                "provenance_label": "official_agency_archive",
            }
        ],
        schema=RELEASE_CALENDAR_SCHEMA,
        strict=True,
    )

    origin = build_forecast_origins(calendar).row(0, named=True)

    assert origin["forecast_origin"] == datetime(2025, 1, 30, 4, 59, 59, 999999, UTC)
    assert origin["forecast_origin"] < origin["target_release_timestamp"]


def test_write_official_archive_data_freezes_parquet_and_duckdb(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observation = VintageObservation(
        series_id="PAYEMS",
        observation_date=date(2024, 1, 1),
        realtime_start=date(2024, 2, 2),
        availability_date=date(2024, 2, 2),
        value=157_000.0,
        units="thousands_of_persons",
        frequency="monthly",
        seasonal_adjustment="seasonally_adjusted",
        transformation="level",
        source="BLS_CES_VINTAGE_ARCHIVE",
        provenance_label="official_agency_archive",
        download_timestamp=datetime(2026, 8, 9, tzinfo=UTC),
    )
    calendar = pl.from_dicts(
        [
            {
                "release_id": "bls-payems-2024-01-initial",
                "series_id": "PAYEMS",
                "observation_date": date(2024, 1, 1),
                "release_timestamp": datetime(2024, 2, 2, 23, 59, 59, 999999, UTC),
                "release_type": "initial",
                "timing_quality": DATE_ONLY_TIMING_QUALITY,
                "source": "BLS_EMPLOYMENT_SITUATION_ARCHIVE",
                "provenance_label": "official_agency_archive",
            }
        ],
        schema=RELEASE_CALENDAR_SCHEMA,
        strict=True,
    )
    fixture = OfficialArchiveData(
        observations_to_frame([observation]),
        calendar,
        {"historical_ingestion_ready": True, "empirical_findings_supported": False},
    )
    monkeypatch.setattr(
        archive_ingestion,
        "build_official_archive_data",
        lambda _raw_dir: fixture,
    )
    output = tmp_path / "official"

    result = write_official_archive_data(tmp_path / "raw", output)
    manifest = json.loads((output / "ingestion_manifest.json").read_text())
    store = VintageStore(output, output / "official_vintages.duckdb")

    assert result["status"] == "ready_with_mixed_timing"
    assert manifest["status"] == "ready_with_mixed_timing"
    assert manifest["observation_artifact"]["sha256"]
    assert manifest["release_calendar_artifact"]["sha256"]
    assert store.query("SELECT count(*) AS n FROM official_vintage_observations")[0, "n"] == 1
    assert store.query("SELECT count(*) AS n FROM official_release_calendar")[0, "n"] == 1
    with pytest.raises(FileExistsError, match="already exist"):
        write_official_archive_data(tmp_path / "raw", output)

    stale_validation = output / "gdp_level_target_validation.parquet"
    pl.DataFrame({"stale": [True]}).write_parquet(stale_validation)
    store.register_view(stale_validation, table_name="gdp_level_target_validation")

    overwrite_result = write_official_archive_data(
        tmp_path / "raw",
        output,
        overwrite=True,
    )
    refreshed_store = VintageStore(output, output / "official_vintages.duckdb")

    assert overwrite_result["gdp_level_target_validation_rows"] == 0
    assert not stale_validation.exists()
    with pytest.raises(duckdb.CatalogException, match="gdp_level_target_validation"):
        refreshed_store.query("SELECT * FROM gdp_level_target_validation")
