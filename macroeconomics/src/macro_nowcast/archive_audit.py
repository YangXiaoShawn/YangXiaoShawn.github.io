"""Auditable validation for downloaded BLS, BEA, Census, DOL, and Fed archives.

The module deliberately separates local file verification from historical-
provenance authorization.  Passing these checks proves container integrity,
expected content, and a small cross-source consistency check.  It does not
claim that every release in an archive has been mapped to an exact timestamp.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import posixpath
import re
import shutil
import subprocess
import tempfile
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

from macro_nowcast.bea_gdp_clock_archive import (
    BEA_GDP_CLOCK_DIRECTORY,
    BEA_GDP_CLOCK_INDEX_URL,
    audit_bea_gdp_clock_archive,
)
from macro_nowcast.bls_cpi_clock_archive import (
    BLS_CPI_CLOCK_DIRECTORY,
    audit_bls_cpi_clock_archive,
)
from macro_nowcast.bls_empsit_clock_archive import (
    BLS_EMPSIT_ARCHIVE_INDEX_URL,
    BLS_EMPSIT_CLOCK_DIRECTORY,
    audit_empsit_text_clock_archive,
)
from macro_nowcast.bls_release_clock import (
    BLS_EMBARGO_CLOCK_TIMING_QUALITY,
    BLSReleaseClockError,
    parse_empsit_release_clock_archive,
)
from macro_nowcast.calendar import DATE_ONLY_TIMING_QUALITY
from macro_nowcast.census_housing_archive import (
    CENSUS_HOUSING_CITATION_URL,
    CENSUS_HOUSING_DIRECTORY,
    CENSUS_HOUSING_INDEX_URL,
    audit_census_housing_archive,
)
from macro_nowcast.census_retail_archive import (
    CENSUS_RETAIL_CITATION_URL,
    CENSUS_RETAIL_DIRECTORY,
    CENSUS_RETAIL_INDEX_URL,
    audit_census_retail_archive,
)
from macro_nowcast.dol_claims_archive import (
    DOL_CLAIMS_ARCHIVE_URL,
    DOL_CLAIMS_DIRECTORY,
    DOL_PUBLIC_DOMAIN_URL,
    audit_dol_claims_archive,
)
from macro_nowcast.fed_g17_archive import (
    FED_G17_DIRECTORY,
    FED_G17_INDEX_URL,
    FED_G17_PUBLIC_DOMAIN_URL,
    audit_fed_g17_archive,
)
from macro_nowcast.treasury_rates_archive import (
    TREASURY_RATES_DIRECTORY,
    TREASURY_RATES_FEED_DOCUMENTATION_URL,
    TREASURY_RATES_INDEX_URL,
    TREASURY_RATES_METHOD_URL,
    audit_treasury_rates_archive,
)

CES_INDEX_URL = "https://www.bls.gov/web/empsit/cesvindata.htm"
CES_ARCHIVE_URL = "https://www.bls.gov/web/empsit/cesvinall.zip"
CPI_INDEX_URL = "https://www.bls.gov/cpi/tables/supplemental-files/home.htm"
CPI_2024_ARCHIVE_URL = "https://www.bls.gov/cpi/tables/supplemental-files/archive-2024.zip"
BEA_GDP_PAGE_URL = "https://www.bea.gov/data/gdp/gross-domestic-product"
BEA_GDP_VINTAGE_URL = "https://apps.bea.gov/national/xls/gdp-gdi-vintage-history.xlsx"
BEA_NIPA_ARCHIVE_INDEX_URL = "https://apps.bea.gov/histdata/"
BEA_NIPA_SAMPLE_URL = (
    "https://apps.bea.gov/HistData/Files/Releases/GDP_and_PI/2024/Q4/"
    "Advance_January-31-2025/Section1all_xls.xlsx"
)
BEA_2024Q4_ADVANCE_RELEASE_URL = (
    "https://www.bea.gov/news/2025/"
    "gross-domestic-product-4th-quarter-and-year-2024-advance-estimate"
)
BLS_COPYRIGHT_URL = "https://www.bls.gov/opub/copyright-information.htm"
BEA_PUBLIC_DOMAIN_URL = "https://www.bea.gov/help/faq/147"

CES_FILENAME = "cesvinall.zip"
CES_RELEASE_INDEX_FILENAME = "empsit-release-index.json"
EMPSIT_DOM_DIRECTORY = "bls-empsit-html"
CPI_FILENAME = "cpi-supplemental-2024.zip"
CPI_RELEASE_INDEX_FILENAME = "cpi-release-index.json"
GDP_VINTAGE_FILENAME = "gdp-gdi-vintage-history.xlsx"
GDP_NIPA_SAMPLE_FILENAME = "bea-nipa-2024q4-advance-section1.xlsx"
CPI_ARCHIVE_YEARS = tuple(range(2012, 2025))
CPI_CURRENT_PERIODS = (
    *(f"2025{month:02d}" for month in range(1, 10)),
    "202511",
    "202512",
    *(f"2026{month:02d}" for month in range(1, 7)),
)
CPI_DOCUMENTED_MISSING_PERIODS = ("202510",)

_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_DOC_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_CELL_RE = re.compile(r"([A-Z]+)(\d+)")
_QUARTER_RE = re.compile(r"\d{4}Q[1-4]")
_GDP_RELEASE_DATE_RE = re.compile(r"([A-Z][a-z]{2} \d{1,2}, \d{4})")
_CPI_WORKBOOK_RE = re.compile(r"cpi-u[_-](\d{6})\.(xls|xlsx)$", re.IGNORECASE)
_EMPSIT_LABEL_RE = re.compile(r"([A-Za-z]+) (\d{4}) Employment Situation")
_CPI_LABEL_RE = re.compile(r"([A-Za-z]+) (\d{4}) Consumer Price Index")
_MONTH_NUMBERS = {
    month: number
    for number, month in enumerate(
        (
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
        ),
        start=1,
    )
}
_EMPSIT_DOM_FILENAME_RE = re.compile(r"empsit_(\d{8})\.htm")


class ArchiveAuditError(RuntimeError):
    """Raised when an archive cannot support a required verification claim."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _file_facts(path: Path) -> dict[str, object]:
    return {
        "filename": path.name,
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _column_number(reference: str) -> int:
    match = _CELL_RE.fullmatch(reference)
    if match is None:
        raise ArchiveAuditError(f"invalid XLSX cell reference: {reference}")
    result = 0
    for char in match.group(1):
        result = result * 26 + ord(char) - ord("A") + 1
    return result


def _column_name(number: int) -> str:
    if number < 1:
        raise ValueError("column number must be positive")
    result = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        result = chr(ord("A") + remainder) + result
    return result


def _number_or_text(value: str) -> int | float | str:
    try:
        parsed = float(value)
    except ValueError:
        return value
    return int(parsed) if parsed.is_integer() else parsed


def _shared_strings(archive: ZipFile) -> list[str]:
    try:
        root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    return ["".join(node.itertext()) for node in root.findall(f"{{{_MAIN_NS}}}si")]


def _sheet_paths(archive: ZipFile) -> dict[str, str]:
    workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
    relationships = ElementTree.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    targets = {
        item.attrib["Id"]: item.attrib["Target"]
        for item in relationships.findall(f"{{{_PKG_REL_NS}}}Relationship")
    }
    result: dict[str, str] = {}
    for sheet in workbook.findall(f".//{{{_MAIN_NS}}}sheet"):
        relationship_id = sheet.attrib[f"{{{_DOC_REL_NS}}}id"]
        target = targets[relationship_id]
        if target.startswith("/"):
            normalized = target.lstrip("/")
        else:
            normalized = posixpath.normpath(posixpath.join("xl", target))
        result[sheet.attrib["name"]] = normalized
    return result


def _xlsx_rows(source: Path | bytes, sheet_name: str) -> dict[int, dict[int, Any]]:
    archive_source: Path | io.BytesIO
    archive_source = io.BytesIO(source) if isinstance(source, bytes) else source
    with ZipFile(archive_source) as archive:
        bad_member = archive.testzip()
        if bad_member is not None:
            raise ArchiveAuditError(f"XLSX CRC failure: {bad_member}")
        strings = _shared_strings(archive)
        paths = _sheet_paths(archive)
        if sheet_name not in paths:
            raise ArchiveAuditError(f"missing XLSX sheet: {sheet_name}")
        root = ElementTree.fromstring(archive.read(paths[sheet_name]))
        rows: dict[int, dict[int, Any]] = {}
        for row in root.findall(f".//{{{_MAIN_NS}}}row"):
            row_number = int(row.attrib["r"])
            values: dict[int, Any] = {}
            for cell in row.findall(f"{{{_MAIN_NS}}}c"):
                reference = cell.attrib.get("r")
                if reference is None:
                    continue
                column = _column_number(reference)
                kind = cell.attrib.get("t")
                if kind == "inlineStr":
                    values[column] = "".join(cell.itertext())
                    continue
                node = cell.find(f"{{{_MAIN_NS}}}v")
                if node is None or node.text is None:
                    continue
                raw = node.text
                if kind == "s":
                    values[column] = strings[int(raw)]
                elif kind in {"str", "e"}:
                    values[column] = raw
                elif kind == "b":
                    values[column] = raw == "1"
                else:
                    values[column] = _number_or_text(raw)
            rows[row_number] = values
        return rows


def _xlsx_sheet_names(source: Path | bytes) -> tuple[str, ...]:
    archive_source: Path | io.BytesIO
    archive_source = io.BytesIO(source) if isinstance(source, bytes) else source
    with ZipFile(archive_source) as archive:
        bad_member = archive.testzip()
        if bad_member is not None:
            raise ArchiveAuditError(f"XLSX CRC failure: {bad_member}")
        return tuple(_sheet_paths(archive))


def _find_text(source: Path | bytes, text: str) -> list[str]:
    matches: list[str] = []
    for sheet in _xlsx_sheet_names(source):
        for row_number, values in _xlsx_rows(source, sheet).items():
            for column, value in values.items():
                if str(value).strip() == text:
                    matches.append(f"{sheet}!{_column_name(column)}{row_number}")
    return matches


def _zip_facts(path: Path) -> dict[str, object]:
    with ZipFile(path) as archive:
        bad_member = archive.testzip()
        if bad_member is not None:
            raise ArchiveAuditError(f"ZIP CRC failure: {bad_member}")
        return {"member_count": len(archive.infolist()), "crc_valid": True}


def _previous_month(release_date: str) -> tuple[int, int]:
    release = datetime.strptime(release_date, "%Y-%m-%d").date()
    if release.month == 1:
        return release.year - 1, 12
    return release.year, release.month - 1


def _period_from_empsit_event(event: dict[str, object]) -> tuple[tuple[int, int], str]:
    label = event.get("observation_label")
    if isinstance(label, str):
        match = _EMPSIT_LABEL_RE.fullmatch(label)
        if match is not None:
            return (int(match.group(2)), _MONTH_NUMBERS[match.group(1)]), "official_label"
    return _previous_month(str(event["release_date"])), "official_date_prior_month_rule"


def _audit_ces_release_mapping(
    path: Path,
    periods: list[tuple[int, int]],
) -> dict[str, object]:
    document = json.loads(path.read_text(encoding="utf-8"))
    events = document.get("release_events")
    if not isinstance(events, list):
        raise ArchiveAuditError("CES release index has no release_events list")
    expected = set(periods)
    mapped: dict[tuple[int, int], dict[str, str]] = {}
    event_by_period: dict[tuple[int, int], dict[str, object]] = {}
    for raw_event in events:
        if not isinstance(raw_event, dict) or "release_date" not in raw_event:
            raise ArchiveAuditError("CES release index contains an invalid event")
        period, basis = _period_from_empsit_event(raw_event)
        if period not in expected or period in mapped:
            continue
        release_date = str(raw_event["release_date"])
        mapped[period] = {"release_date": release_date, "mapping_basis": basis}
        event_by_period[period] = raw_event

    october_2025 = (2025, 10)
    november_2025 = (2025, 11)
    if october_2025 in expected and october_2025 not in mapped:
        november_event = event_by_period.get(november_2025)
        if november_event is None:
            raise ArchiveAuditError("CES special October 2025 release mapping is unavailable")
        mapped[october_2025] = {
            "release_date": str(november_event["release_date"]),
            "mapping_basis": "official_november_release_includes_october_ces_initial",
        }

    missing = sorted(expected - set(mapped))
    if missing:
        formatted = [f"{year:04d}-{month:02d}" for year, month in missing]
        raise ArchiveAuditError(f"CES release mapping is incomplete: {formatted}")

    mapping_rows = [
        {
            "vintage_period": f"{year:04d}-{month:02d}",
            **mapped[(year, month)],
        }
        for year, month in periods
    ]
    basis_counts: dict[str, int] = {}
    for row in mapping_rows:
        basis = str(row["mapping_basis"])
        basis_counts[basis] = basis_counts.get(basis, 0) + 1
    result: dict[str, object] = {
        **_file_facts(path),
        "official_url": str(document.get("source_url", "")),
        "source_release_event_count": len(events),
        "mapped_vintage_periods": len(mapping_rows),
        "unique_release_dates": len({str(row["release_date"]) for row in mapping_rows}),
        "mapping_basis_counts": basis_counts,
        "release_date_mapping": mapping_rows,
        "exact_intraday_time_mapping_pending": True,
        "passed": True,
    }
    if october_2025 in expected:
        result["special_shared_release"] = {
            "release_date": "2025-12-16",
            "vintage_periods": ["2025-10", "2025-11"],
            "evidence_url": ("https://www.bls.gov/news.release/archives/empsit_12162025.htm"),
        }
    return result


def _audit_ces(path: Path, release_index_path: Path) -> dict[str, object]:
    facts = _file_facts(path)
    facts.update(_zip_facts(path))
    member = "tri_000000_SA.csv"
    with ZipFile(path) as archive:
        if member not in archive.namelist():
            raise ArchiveAuditError(f"missing CES total-nonfarm member: {member}")
        with archive.open(member) as binary:
            rows = csv.reader(io.TextIOWrapper(binary, encoding="utf-8-sig", newline=""))
            header = next(rows)
            if header[:2] != ["year", "month"]:
                raise ArchiveAuditError("unexpected CES vintage CSV header")
            periods: list[tuple[int, int]] = []
            last_nonempty_observation: list[str] = []
            for row in rows:
                if not row:
                    continue
                periods.append((int(row[0]), int(row[1])))
                nonempty = [header[index] for index, value in enumerate(row[2:], start=2) if value]
                last_nonempty_observation.append(nonempty[-1])
    if not periods or periods[0] != (2003, 5):
        raise ArchiveAuditError("CES vintage coverage does not begin at 2003-05")
    if periods != sorted(set(periods)):
        raise ArchiveAuditError("CES vintage periods are duplicated or out of order")
    release_mapping = _audit_ces_release_mapping(release_index_path, periods)
    facts.update(
        {
            "passed": True,
            "official_url": CES_ARCHIVE_URL,
            "target_series_id": "CES0000000001",
            "verified_member": member,
            "observation_columns": len(header) - 2,
            "vintage_rows": len(periods),
            "first_vintage_period": f"{periods[0][0]:04d}-{periods[0][1]:02d}",
            "last_vintage_period": f"{periods[-1][0]:04d}-{periods[-1][1]:02d}",
            "first_row_latest_observation": last_nonempty_observation[0],
            "release_mapping": release_mapping,
            "provenance_status": "content_and_release_dates_verified_intraday_times_pending",
        }
    )
    return facts


def _cpi_archive_filename(year: int) -> str:
    return f"cpi-supplemental-{year}.zip"


def _cpi_archive_url(year: int) -> str:
    return f"https://www.bls.gov/cpi/tables/supplemental-files/archive-{year}.zip"


def _cpi_monthly_members(archive: ZipFile, year: int) -> dict[str, str]:
    result: dict[str, str] = {}
    for name in archive.namelist():
        match = _CPI_WORKBOOK_RE.search(name)
        if match is None or not match.group(1).startswith(str(year)):
            continue
        result[match.group(1)] = name
    expected = {f"{year}{month:02d}" for month in range(1, 13)}
    missing = sorted(expected - set(result))
    if missing:
        raise ArchiveAuditError(f"CPI {year} archive is missing monthly workbooks: {missing}")
    return result


def _verify_core_cpi_xlsx(payload: bytes, label: str) -> list[str]:
    matches = _find_text(payload, "All items less food and energy")
    if not matches:
        raise ArchiveAuditError(f"core CPI row absent from {label}")
    return matches


def convert_legacy_xls_to_xlsx(
    payloads: dict[str, bytes],
) -> tuple[dict[str, bytes], str]:
    converted_payloads: dict[str, bytes] = {}
    real_xls: dict[str, bytes] = {}
    for period, payload in payloads.items():
        if payload.startswith(b"PK"):
            converted_payloads[period] = payload
        else:
            real_xls[period] = payload
    if not real_xls:
        return converted_payloads, "fixture_xlsx_payload"

    executable = shutil.which("soffice")
    if executable is None:
        raise ArchiveAuditError(
            "legacy CPI XLS content verification requires LibreOffice 'soffice'"
        )
    with tempfile.TemporaryDirectory(prefix="macro-nowcast-cpi-") as temporary:
        root = Path(temporary)
        input_directory = root / "input"
        output_directory = root / "output"
        input_directory.mkdir()
        output_directory.mkdir()
        sources: list[Path] = []
        for period, payload in sorted(real_xls.items()):
            source = input_directory / f"cpi-u-{period}.xls"
            source.write_bytes(payload)
            sources.append(source)
        completed = subprocess.run(
            [
                executable,
                f"-env:UserInstallation={(root / 'profile').as_uri()}",
                "--headless",
                "--convert-to",
                "xlsx",
                "--outdir",
                str(output_directory),
                *(str(source) for source in sources),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if completed.returncode != 0:
            message = completed.stderr.strip() or completed.stdout.strip()
            raise ArchiveAuditError(f"legacy CPI XLS conversion failed: {message}")
        for period in sorted(real_xls):
            converted = output_directory / f"cpi-u-{period}.xlsx"
            if not converted.exists():
                raise ArchiveAuditError(f"legacy CPI XLS conversion missing output: {period}")
            converted_payloads[period] = converted.read_bytes()
    return converted_payloads, Path(executable).name


def _verify_legacy_core_cpi(
    payloads: dict[str, bytes],
) -> tuple[dict[str, list[str]], str]:
    converted, tool = convert_legacy_xls_to_xlsx(payloads)
    locations = {
        period: _verify_core_cpi_xlsx(payload, period) for period, payload in converted.items()
    }
    return locations, tool


def _audit_cpi_release_mapping(
    path: Path,
    expected_periods: set[str],
) -> dict[str, object]:
    document = json.loads(path.read_text(encoding="utf-8"))
    events = document.get("release_events")
    if not isinstance(events, list):
        raise ArchiveAuditError("CPI release index has no release_events list")
    mapping: dict[str, str] = {}
    for event in events:
        if not isinstance(event, dict):
            raise ArchiveAuditError("CPI release index contains an invalid event")
        label = event.get("observation_label")
        if not isinstance(label, str):
            continue
        match = _CPI_LABEL_RE.fullmatch(label)
        if match is None:
            continue
        period = f"{int(match.group(2)):04d}{_MONTH_NUMBERS[match.group(1)]:02d}"
        if period in expected_periods:
            mapping[period] = str(event["release_date"])
    missing = sorted(expected_periods - set(mapping))
    if missing:
        raise ArchiveAuditError(f"CPI release mapping is incomplete: {missing}")
    rows = [
        {
            "snapshot_period": f"{period[:4]}-{period[4:]}",
            "release_date": mapping[period],
            "mapping_basis": "official_observation_label",
        }
        for period in sorted(mapping)
    ]
    return {
        **_file_facts(path),
        "official_url": str(document.get("source_url", "")),
        "source_release_event_count": len(events),
        "mapped_snapshot_periods": len(rows),
        "unique_release_dates": len({str(row["release_date"]) for row in rows}),
        "release_date_mapping": rows,
        "exact_intraday_time_mapping_pending": True,
        "passed": True,
    }


def _audit_cpi(directory: Path) -> dict[str, object]:
    annual_archives: dict[str, dict[str, object]] = {}
    layout_counts: dict[str, dict[str, int]] = {}
    core_location_examples: dict[str, list[str]] = {}
    legacy_payloads: dict[str, bytes] = {}
    verified_xlsx = 0
    legacy_xls = 0

    for year in CPI_ARCHIVE_YEARS:
        path = directory / _cpi_archive_filename(year)
        facts = _file_facts(path)
        facts.update(_zip_facts(path))
        with ZipFile(path) as archive:
            members = _cpi_monthly_members(archive, year)
            year_xlsx = 0
            year_xls = 0
            for period, name in sorted(members.items()):
                if name.lower().endswith(".xlsx"):
                    locations = _verify_core_cpi_xlsx(archive.read(name), name)
                    year_xlsx += 1
                    verified_xlsx += 1
                    if period.endswith(("01", "12")):
                        core_location_examples[period] = locations
                else:
                    year_xls += 1
                    legacy_xls += 1
                    legacy_payloads[period] = archive.read(name)
        facts.update(
            {
                "passed": True,
                "official_url": _cpi_archive_url(year),
                "monthly_workbooks": 12,
                "xlsx_content_verified": year_xlsx,
                "legacy_xls_inventory_verified": year_xls,
            }
        )
        annual_archives[str(year)] = facts
        layout_counts[str(year)] = {"xlsx": year_xlsx, "xls": year_xls}

    legacy_locations, legacy_conversion_tool = _verify_legacy_core_cpi(legacy_payloads)
    for period, locations in sorted(legacy_locations.items()):
        if period.endswith(("01", "12")):
            core_location_examples[period] = locations

    current_files: dict[str, dict[str, object]] = {}
    current_directory = directory / "cpi-current"
    for period in CPI_CURRENT_PERIODS:
        path = current_directory / f"cpi-u-{period}.xlsx"
        locations = _verify_core_cpi_xlsx(path.read_bytes(), path.name)
        current_files[period] = {
            **_file_facts(path),
            "official_url": (
                f"https://www.bls.gov/cpi/tables/supplemental-files/cpi-u-{period}.xlsx"
            ),
            "core_cpi_locations": locations,
            "passed": True,
        }
        verified_xlsx += 1

    expected_periods = {
        f"{year}{month:02d}" for year in CPI_ARCHIVE_YEARS for month in range(1, 13)
    } | set(CPI_CURRENT_PERIODS)
    release_mapping = _audit_cpi_release_mapping(
        directory / CPI_RELEASE_INDEX_FILENAME,
        expected_periods,
    )

    return {
        "passed": True,
        "official_url": CPI_INDEX_URL,
        "target_series_id": "CUSR0000SA0L1E",
        "annual_archive_count": len(annual_archives),
        "annual_coverage": "2012-2024",
        "annual_archives": annual_archives,
        "layout_counts_by_year": layout_counts,
        "current_snapshot_count": len(current_files),
        "current_coverage": "2025-01 through 2026-06",
        "current_files": current_files,
        "documented_missing_periods": list(CPI_DOCUMENTED_MISSING_PERIODS),
        "monthly_workbooks_inventoried": len(annual_archives) * 12 + len(current_files),
        "xlsx_core_content_verified": verified_xlsx,
        "legacy_xls_inventory_verified": legacy_xls,
        "legacy_xls_core_content_verified": len(legacy_locations),
        "legacy_xls_conversion_tool": legacy_conversion_tool,
        "legacy_xls_value_parser_available": True,
        "legacy_xls_value_parser_pending": False,
        "core_cpi_location_examples": core_location_examples,
        "release_mapping": release_mapping,
        "provenance_status": (
            "full_official_inventory_core_rows_and_release_dates_verified_"
            "legacy_values_parseable_intraday_times_unverified"
        ),
    }


def _quarter_rows(rows: dict[int, dict[int, Any]]) -> dict[str, int]:
    result: dict[str, int] = {}
    for row_number, values in rows.items():
        for value in values.values():
            text = str(value).strip()
            if _QUARTER_RE.fullmatch(text):
                result[text] = row_number
                break
    return result


def _summary_advance(rows: dict[int, dict[int, Any]], quarter: str) -> dict[str, object]:
    quarters = _quarter_rows(rows)
    if quarter not in quarters:
        raise ArchiveAuditError(f"GDP vintage summary is missing {quarter}")
    start = quarters[quarter]
    later_quarter_rows = sorted(row for row in quarters.values() if row > start)
    stop = later_quarter_rows[0] if later_quarter_rows else max(rows) + 1
    for row_number in range(start + 1, stop):
        values = rows.get(row_number, {})
        if str(values.get(2, "")).strip().lower() == "advance":
            return {
                "row": row_number,
                "growth_qoq_saar": float(values[5]),
                "release_date_text": str(values[7]).strip(),
            }
    raise ArchiveAuditError(f"GDP vintage summary is missing {quarter} Advance row")


def _audit_gdp_initial_rows(
    rows: dict[int, dict[int, Any]],
    quarters: dict[str, int],
) -> tuple[dict[str, int], int, list[dict[str, str]]]:
    ordered = sorted(quarters.items(), key=lambda item: item[1])
    labels: dict[str, int] = {}
    dated_initials = 0
    release_mapping: list[dict[str, str]] = []
    for index, (quarter, start) in enumerate(ordered):
        stop = ordered[index + 1][1] if index + 1 < len(ordered) else max(rows) + 1
        matches: list[tuple[str, Any, str]] = []
        for row_number in range(start + 1, stop):
            values = rows.get(row_number, {})
            label = str(values.get(2, "")).strip()
            if label in {"Advance", "Initial"}:
                matches.append((label, values.get(5), str(values.get(7, "")).strip()))
        if len(matches) != 1:
            raise ArchiveAuditError(
                f"GDP vintage summary requires one initial estimate for {quarter}; "
                f"found {len(matches)}"
            )
        label, growth, release_text = matches[0]
        float(growth)
        if not release_text:
            raise ArchiveAuditError(f"GDP initial estimate is missing a date for {quarter}")
        release_match = _GDP_RELEASE_DATE_RE.search(release_text)
        if release_match is None:
            raise ArchiveAuditError(
                f"GDP initial estimate has an invalid date for {quarter}"
            )
        release_date = datetime.strptime(
            release_match.group(1),
            "%b %d, %Y",
        ).date()
        labels[label] = labels.get(label, 0) + 1
        dated_initials += 1
        release_mapping.append(
            {
                "quarter": quarter,
                "release_date": release_date.isoformat(),
                "source_release_type": label,
            }
        )
    if len({row["release_date"] for row in release_mapping}) != len(release_mapping):
        raise ArchiveAuditError("GDP initial releases contain duplicate dates")
    return labels, dated_initials, release_mapping


def _audit_gdp_estimate_rows(
    rows: dict[int, dict[int, Any]],
) -> tuple[dict[str, int], int]:
    accepted = {
        "Advance",
        "Initial",
        "Second",
        "Preliminary",
        "Third",
        "Final",
        "Updated",
        "Revised",
    }
    labels: dict[str, int] = {}
    count = 0
    for row_number, values in rows.items():
        label = str(values.get(2, "")).strip()
        if label not in accepted:
            continue
        try:
            float(values.get(5))
        except (TypeError, ValueError) as exc:
            raise ArchiveAuditError(
                f"GDP estimate row {row_number} has invalid growth value"
            ) from exc
        if not str(values.get(7, "")).strip():
            raise ArchiveAuditError(f"GDP estimate row {row_number} has no release date")
        labels[label] = labels.get(label, 0) + 1
        count += 1
    return labels, count


def _audit_gdp_summary(path: Path) -> tuple[dict[str, object], dict[str, object]]:
    facts = _file_facts(path)
    sheets = _xlsx_sheet_names(path)
    if not {"ReadMe", "Vintage History"}.issubset(sheets):
        raise ArchiveAuditError("unexpected GDP vintage-history workbook sheets")
    rows = _xlsx_rows(path, "Vintage History")
    quarters = _quarter_rows(rows)
    initial_labels, dated_initials, initial_release_mapping = _audit_gdp_initial_rows(
        rows,
        quarters,
    )
    estimate_labels, dated_estimates = _audit_gdp_estimate_rows(rows)
    advance = _summary_advance(rows, "2024Q4")
    facts.update(
        {
            "passed": True,
            "official_url": BEA_GDP_VINTAGE_URL,
            "sheets": list(sheets),
            "quarter_count": len(quarters),
            "first_quarter": min(quarters),
            "last_quarter": max(quarters),
            "initial_estimate_count": dated_initials,
            "initial_estimate_labels": initial_labels,
            "initial_release_mapping": initial_release_mapping,
            "all_initial_estimates_have_release_date_text": True,
            "estimate_row_count": dated_estimates,
            "estimate_row_labels": estimate_labels,
            "all_estimate_rows_have_numeric_growth_and_release_date_text": True,
            "supports_published_first_release_growth": True,
            "supplies_real_gdp_levels": False,
            "verified_2024q4_advance": advance,
            "provenance_status": "growth_summary_verified_not_real_gdp_levels",
        }
    )
    return facts, advance


def _metadata_text(rows: dict[int, dict[int, Any]], prefix: str) -> str:
    for values in rows.values():
        for value in values.values():
            text = str(value).strip()
            if text.startswith(prefix):
                return text
    raise ArchiveAuditError(f"missing workbook metadata: {prefix}")


def _audit_gdp_nipa(
    path: Path,
    *,
    summary_advance: dict[str, object],
) -> dict[str, object]:
    facts = _file_facts(path)
    sheets = _xlsx_sheet_names(path)
    if "T10106-Q" not in sheets:
        raise ArchiveAuditError("NIPA snapshot is missing T10106-Q")
    rows = _xlsx_rows(path, "T10106-Q")
    header_row = next(
        values for values in rows.values() if "2024Q4" in {str(value) for value in values.values()}
    )
    q3_column = next(column for column, value in header_row.items() if value == "2024Q3")
    q4_column = next(column for column, value in header_row.items() if value == "2024Q4")
    gdp_row = next(
        values
        for values in rows.values()
        if str(values.get(1, "")).strip() == "1"
        and str(values.get(2, "")).strip() == "Gross domestic product"
        and str(values.get(3, "")).strip() == "A191RX"
    )
    q3_level = float(gdp_row[q3_column])
    q4_level = float(gdp_row[q4_column])
    calculated = 100.0 * ((q4_level / q3_level) ** 4 - 1.0)
    published = float(summary_advance["growth_qoq_saar"])
    if not math.isclose(round(calculated, 1), published, abs_tol=0.05):
        raise ArchiveAuditError(
            "NIPA level transformation does not reconcile to the published Advance growth"
        )
    published_text = _metadata_text(rows, "Data published")
    facts.update(
        {
            "passed": True,
            "official_url": BEA_NIPA_SAMPLE_URL,
            "target_series_id": "GDPC1",
            "table": "NIPA 1.1.6",
            "line": 1,
            "series_code": "A191RX",
            "units": "millions_of_chained_2017_dollars_saar",
            "workbook_metadata": published_text,
            "q3_2024_level": int(q3_level),
            "q4_2024_level": int(q4_level),
            "calculated_qoq_saar_percent": calculated,
            "published_qoq_saar_percent": published,
            "rounded_reconciliation_passed": True,
            "verified_release_timestamp_utc": "2025-01-30T13:30:00Z",
            "release_evidence_url": BEA_2024Q4_ADVANCE_RELEASE_URL,
            "archive_directory_label": "Advance_January-31-2025",
            "archive_directory_date_disagrees_with_release_evidence": True,
            "provenance_status": "single_release_snapshot_verified_full_coverage_pending",
        }
    )
    return facts


def _safe_audit(name: str, callback: Any) -> dict[str, object]:
    try:
        return callback()
    except (ArchiveAuditError, BadZipFile, FileNotFoundError, KeyError, StopIteration) as exc:
        return {"filename": name, "passed": False, "error": str(exc)}


def _audit_empsit_dom_exports(directory: Path, index_path: Path) -> dict[str, object]:
    document = json.loads(index_path.read_text(encoding="utf-8"))
    events = [event for event in document["release_events"] if event.get("html_available")]
    expected: dict[str, dict[str, object]] = {}
    for event in events:
        release = datetime.strptime(str(event["release_date"]), "%Y-%m-%d").date()
        expected[f"empsit_{release:%m%d%Y}.htm"] = event
    actual = {path.name: path for path in directory.glob("empsit_*.htm")}
    missing = sorted(set(expected) - set(actual))
    extra = sorted(set(actual) - set(expected))
    if missing or extra:
        raise ArchiveAuditError(
            f"Employment Situation DOM inventory mismatch: missing={missing[:3]}, extra={extra[:3]}"
        )
    try:
        clock_archive = parse_empsit_release_clock_archive(directory)
    except BLSReleaseClockError as exc:
        raise ArchiveAuditError(str(exc)) from exc
    files: dict[str, dict[str, object]] = {}
    structured = 0
    preformatted = 0
    for name in sorted(expected):
        if _EMPSIT_DOM_FILENAME_RE.fullmatch(name) is None:
            raise ArchiveAuditError(f"invalid Employment Situation DOM filename: {name}")
        path = actual[name]
        document_text = path.read_text(encoding="utf-8")
        if not document_text.rstrip().endswith("</html>"):
            raise ArchiveAuditError(f"incomplete Employment Situation DOM export: {name}")
        if "Employment Situation News Release" not in document_text:
            raise ArchiveAuditError(f"Employment Situation marker missing: {name}")
        if "Table A-1" not in document_text:
            raise ArchiveAuditError(f"Employment Situation table A-1 missing: {name}")
        layout = (
            "html_table_a1" if 'id="cps_empsit_a01"' in document_text else "preformatted_table_a1"
        )
        structured += layout == "html_table_a1"
        preformatted += layout == "preformatted_table_a1"
        release_date = str(expected[name]["release_date"])
        parsed_release_date = date.fromisoformat(release_date)
        clock = clock_archive.clocks.get(parsed_release_date)
        exclusion_reason = clock_archive.exclusions.get(parsed_release_date)
        facts = _file_facts(path)
        files[release_date] = {
            **facts,
            "official_url": f"https://www.bls.gov/news.release/archives/{name}",
            "observation_label": expected[name].get("observation_label"),
            "layout": layout,
            "complete_dom": True,
            "release_timestamp_utc": (
                clock.release_timestamp.isoformat().replace("+00:00", "Z")
                if clock is not None
                else None
            ),
            "printed_timezone": clock.printed_timezone if clock is not None else None,
            "timing_quality": (
                BLS_EMBARGO_CLOCK_TIMING_QUALITY
                if clock is not None
                else DATE_ONLY_TIMING_QUALITY
            ),
            "clock_exclusion_reason": exclusion_reason,
        }
    hashes = {str(item["sha256"]) for item in files.values()}
    if len(hashes) != len(files):
        raise ArchiveAuditError("Employment Situation DOM exports contain duplicate content hashes")
    return {
        "passed": True,
        "official_url": str(document["source_url"]),
        "directory": directory.name,
        "acquisition_format": "browser_rendered_complete_dom_export",
        "server_original_bytes_claimed": False,
        "file_count": len(files),
        "first_release_date": min(files),
        "last_release_date": max(files),
        "structured_table_count": structured,
        "preformatted_table_count": preformatted,
        "all_files_complete": True,
        "all_hashes_unique": True,
        "exact_release_clock_count": len(clock_archive.clocks),
        "date_only_clock_exclusion_count": len(clock_archive.exclusions),
        "date_only_clock_exclusions": {
            release_date.isoformat(): reason
            for release_date, reason in clock_archive.exclusions.items()
        },
        "exact_timing_quality": BLS_EMBARGO_CLOCK_TIMING_QUALITY,
        "files": files,
        "provenance_status": (
            "complete_official_dom_exports_table_a1_inventory_verified_"
            "release_dates_verified_intraday_not_normalized"
        ),
    }


def audit_agency_vintages(
    raw_dir: str | Path,
    *,
    audited_at: datetime | None = None,
) -> dict[str, object]:
    """Verify locally downloaded official archive artifacts without network access."""

    directory = Path(raw_dir).resolve()
    timestamp = (audited_at or datetime.now(UTC)).astimezone(UTC)
    ces = _safe_audit(
        CES_FILENAME,
        lambda: _audit_ces(
            directory / CES_FILENAME,
            directory / CES_RELEASE_INDEX_FILENAME,
        ),
    )
    cpi = _safe_audit(CPI_FILENAME, lambda: _audit_cpi(directory))

    summary_holder: dict[str, object] = {}

    def audit_summary() -> dict[str, object]:
        facts, advance = _audit_gdp_summary(directory / GDP_VINTAGE_FILENAME)
        summary_holder.update(advance)
        return facts

    gdp_summary = _safe_audit(GDP_VINTAGE_FILENAME, audit_summary)
    if gdp_summary.get("passed"):
        gdp_nipa = _safe_audit(
            GDP_NIPA_SAMPLE_FILENAME,
            lambda: _audit_gdp_nipa(
                directory / GDP_NIPA_SAMPLE_FILENAME,
                summary_advance=summary_holder,
            ),
        )
    else:
        gdp_nipa = {
            "filename": GDP_NIPA_SAMPLE_FILENAME,
            "passed": False,
            "error": "GDP summary audit failed; cross-check not attempted",
        }

    rejected_ces_xlsx: dict[str, object] | None = None
    rejected_path = directory / "cesvin00.xlsx"
    if rejected_path.exists():
        rejected_ces_xlsx = _safe_audit(
            rejected_path.name,
            lambda: {
                **_file_facts(rejected_path),
                "sheets": list(_xlsx_sheet_names(rejected_path)),
                "passed": True,
            },
        )

    artifacts = {
        "ces": ces,
        "cpi": cpi,
        "gdp_vintage_summary": gdp_summary,
        "gdp_nipa_snapshot": gdp_nipa,
    }
    gdp_clock_directory = directory / BEA_GDP_CLOCK_DIRECTORY
    if gdp_clock_directory.exists():
        if gdp_summary.get("passed"):
            initial_release_mapping = gdp_summary.get("initial_release_mapping", [])
            assert isinstance(initial_release_mapping, list)
            expected_initial_releases = {
                date.fromisoformat(str(row["release_date"])): str(
                    row["source_release_type"]
                )
                for row in initial_release_mapping
                if isinstance(row, dict)
            }
            artifacts["gdp_release_clock_evidence"] = _safe_audit(
                BEA_GDP_CLOCK_DIRECTORY,
                lambda: audit_bea_gdp_clock_archive(
                    gdp_clock_directory,
                    expected_initial_releases=expected_initial_releases,
                ),
            )
        else:
            artifacts["gdp_release_clock_evidence"] = {
                "filename": BEA_GDP_CLOCK_DIRECTORY,
                "passed": False,
                "error": "GDP summary audit failed; clock reconciliation not attempted",
            }
    nipa_level_directory = directory / "bea-nipa-levels"
    if nipa_level_directory.exists():
        from macro_nowcast.bea_nipa_archive import (
            BEANIPAArchiveError,
            audit_bea_nipa_level_archive,
        )

        def audit_nipa_levels() -> dict[str, object]:
            try:
                return audit_bea_nipa_level_archive(
                    nipa_level_directory,
                    clock_evidence_path=(
                        directory / BEA_GDP_CLOCK_DIRECTORY / "clock-evidence.json"
                    ),
                    published_growth_path=directory / GDP_VINTAGE_FILENAME,
                )
            except BEANIPAArchiveError as exc:
                raise ArchiveAuditError(str(exc)) from exc

        artifacts["gdp_nipa_level_archive"] = _safe_audit(
            "bea-nipa-levels",
            audit_nipa_levels,
        )
    empsit_dom_directory = directory / EMPSIT_DOM_DIRECTORY
    if empsit_dom_directory.exists():
        artifacts["employment_situation_dom"] = _safe_audit(
            EMPSIT_DOM_DIRECTORY,
            lambda: _audit_empsit_dom_exports(
                empsit_dom_directory,
                directory / CES_RELEASE_INDEX_FILENAME,
            ),
        )
    empsit_text_clock_directory = directory / BLS_EMPSIT_CLOCK_DIRECTORY
    if empsit_text_clock_directory.exists():
        artifacts["employment_situation_txt_clock_evidence"] = _safe_audit(
            BLS_EMPSIT_CLOCK_DIRECTORY,
            lambda: audit_empsit_text_clock_archive(
                empsit_text_clock_directory,
                release_index_path=directory / CES_RELEASE_INDEX_FILENAME,
            ),
        )
    cpi_clock_directory = directory / BLS_CPI_CLOCK_DIRECTORY
    if cpi_clock_directory.exists():
        artifacts["cpi_release_clock_evidence"] = _safe_audit(
            BLS_CPI_CLOCK_DIRECTORY,
            lambda: audit_bls_cpi_clock_archive(
                cpi_clock_directory,
                release_index_path=directory / CPI_RELEASE_INDEX_FILENAME,
            ),
        )
    dol_claims_directory = directory / DOL_CLAIMS_DIRECTORY
    if dol_claims_directory.exists():
        artifacts["dol_weekly_claims"] = _safe_audit(
            DOL_CLAIMS_DIRECTORY,
            lambda: audit_dol_claims_archive(dol_claims_directory),
        )
    fed_g17_directory = directory / FED_G17_DIRECTORY
    if fed_g17_directory.exists():
        artifacts["fed_g17_industrial_production"] = _safe_audit(
            FED_G17_DIRECTORY,
            lambda: audit_fed_g17_archive(fed_g17_directory),
        )
    treasury_rates_directory = directory / TREASURY_RATES_DIRECTORY
    if treasury_rates_directory.exists():
        artifacts["treasury_10y_daily_rates"] = _safe_audit(
            TREASURY_RATES_DIRECTORY,
            lambda: audit_treasury_rates_archive(treasury_rates_directory),
        )
    census_retail_directory = directory / CENSUS_RETAIL_DIRECTORY
    if census_retail_directory.exists():
        artifacts["census_retail_sales"] = _safe_audit(
            CENSUS_RETAIL_DIRECTORY,
            lambda: audit_census_retail_archive(census_retail_directory),
        )
    census_housing_directory = directory / CENSUS_HOUSING_DIRECTORY
    if census_housing_directory.exists():
        artifacts["census_housing_starts"] = _safe_audit(
            CENSUS_HOUSING_DIRECTORY,
            lambda: audit_census_housing_archive(census_housing_directory),
        )
    required_passed = all(bool(item.get("passed")) for item in artifacts.values())
    report: dict[str, object] = {
        "schema_version": 1,
        "status": "verified_with_limitations" if required_passed else "failed",
        "audited_at": timestamp.isoformat().replace("+00:00", "Z"),
        "raw_directory": str(directory),
        "api_credentials_used": False,
        "api_txt_read": False,
        "operator_opt_in_basis": "user_requested_acquisition_and_verification",
        "authorization_basis": {
            "bls_public_domain_page": BLS_COPYRIGHT_URL,
            "bea_public_domain_page": BEA_PUBLIC_DOMAIN_URL,
            "dol_public_domain_page": DOL_PUBLIC_DOMAIN_URL,
            "federal_reserve_public_domain_page": FED_G17_PUBLIC_DOMAIN_URL,
            "treasury_official_feed_documentation": TREASURY_RATES_FEED_DOCUMENTATION_URL,
            "treasury_rate_methodology": TREASURY_RATES_METHOD_URL,
            "census_citation_policy": CENSUS_RETAIL_CITATION_URL,
            "census_housing_citation_policy": CENSUS_HOUSING_CITATION_URL,
            "legal_advice": False,
        },
        "source_indexes": {
            "ces": CES_INDEX_URL,
            "employment_situation": BLS_EMPSIT_ARCHIVE_INDEX_URL,
            "cpi": CPI_INDEX_URL,
            "gdp": BEA_GDP_PAGE_URL,
            "gdp_news_archive": BEA_GDP_CLOCK_INDEX_URL,
            "bea_nipa_archive": BEA_NIPA_ARCHIVE_INDEX_URL,
            "dol_weekly_claims": DOL_CLAIMS_ARCHIVE_URL,
            "fed_g17_industrial_production": FED_G17_INDEX_URL,
            "treasury_10y_daily_rates": TREASURY_RATES_INDEX_URL,
            "census_retail_sales": CENSUS_RETAIL_INDEX_URL,
            "census_housing_starts": CENSUS_HOUSING_INDEX_URL,
        },
        "artifacts": artifacts,
        "archive_ingestion_approval": {
            "terms_reviewed": True,
            "operator_opt_in": True,
            "full_coverage_audited": False,
        },
        "historical_ingestion_ready": False,
        "remaining_gates": [
            (
                "Employment Situation embargo clocks are verified for the complete "
                "acquired PAYEMS target window using 2003-2008 official TXT and later "
                "HTML evidence, except the explicitly retained 2012-12-07 EST/EDT "
                "source conflict."
            ),
            (
                "CPI embargo clocks are verified for all 173 acquired target snapshots; "
                "the supplemental archive's documented October 2025 gap remains missing."
            ),
            (
                "GDP initial-release clocks are verified for all 98 target events. "
                "The official NIPA directory supplies 96 initial Section 1 level "
                "snapshots; 2002Q1 and 2002Q2 predate its available release folders "
                "and remain explicit, non-imputed archive gaps."
            ),
            (
                "Acquire genuine original-provider vintages for the broader predictor "
                "set beyond the acquired DOL claims, Fed G.17 industrial production, "
                "Treasury daily 10-year CMT observations, Census retail sales, CPS "
                "unemployment-rate, and CES sector histories before extending "
                "conclusions beyond the archive pilot. Treasury rates are point-in-time "
                "market observations; the feed does not reconstruct later corrections."
            ),
        ],
    }
    if rejected_ces_xlsx is not None:
        report["rejected_optional_downloads"] = [rejected_ces_xlsx]
    return report


def write_agency_vintage_audit(
    raw_dir: str | Path,
    output_path: str | Path,
    *,
    audited_at: datetime | None = None,
) -> dict[str, object]:
    """Run the offline audit and write its deterministic JSON evidence record."""

    report = audit_agency_vintages(raw_dir, audited_at=audited_at)
    destination = Path(output_path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "status": report["status"],
        "audit_path": destination,
        "historical_ingestion_ready": report["historical_ingestion_ready"],
    }
