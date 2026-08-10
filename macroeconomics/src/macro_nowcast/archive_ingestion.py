"""Parse audited BLS/BEA/Census/DOL/Federal Reserve archives into canonical rows.

Verified source-page clocks propagate as exact timezone-aware timestamps. Events
without equivalent evidence retain the documented conservative date-only rule.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import ClassVar
from zipfile import ZipFile

import polars as pl

from macro_nowcast.archive_audit import (
    CES_FILENAME,
    CPI_ARCHIVE_YEARS,
    CPI_CURRENT_PERIODS,
    CPI_RELEASE_INDEX_FILENAME,
    GDP_VINTAGE_FILENAME,
    ArchiveAuditError,
    audit_agency_vintages,
    convert_legacy_xls_to_xlsx,
)
from macro_nowcast.archive_audit import _xlsx_rows as read_xlsx_rows
from macro_nowcast.bea_gdp_clock_archive import (
    BEA_GDP_CLOCK_DIRECTORY,
    BEA_GDP_CLOCK_FILENAME,
    BEA_GDP_CLOCK_TIMING_QUALITY,
    BEAGDPClockArchive,
    BEAReleaseClock,
    parse_bea_gdp_clock_archive,
)
from macro_nowcast.bea_nipa_archive import (
    BEA_NIPA_LEVEL_DIRECTORY,
    BEA_NIPA_LEVEL_SERIES_ID,
    BEA_NIPA_LEVEL_SOURCE,
    parse_bea_nipa_level_archive,
)
from macro_nowcast.bls_cpi_clock_archive import (
    BLS_CPI_CLOCK_DIRECTORY,
    BLS_CPI_CLOCK_FILENAME,
    BLSCPIClockArchive,
    parse_bls_cpi_clock_archive,
)
from macro_nowcast.bls_empsit_clock_archive import (
    BLS_EMPSIT_CLOCK_DIRECTORY,
    merge_empsit_release_clocks,
    parse_empsit_text_clock_archive,
)
from macro_nowcast.bls_release_clock import (
    BLS_EMBARGO_CLOCK_TIMING_QUALITY,
    BLSReleaseClock,
    parse_empsit_release_clock_archive,
)
from macro_nowcast.calendar import (
    DATE_ONLY_TIMING_QUALITY,
    RELEASE_CALENDAR_SCHEMA,
    validate_release_calendar,
)
from macro_nowcast.census_housing_archive import (
    CENSUS_HOUSING_DIRECTORY,
    CENSUS_HOUSING_SOURCE,
    CENSUS_HOUSING_STARTS_SERIES_ID,
    CENSUS_HOUSING_TIMING_QUALITY,
    parse_census_housing_archive,
)
from macro_nowcast.census_retail_archive import (
    CENSUS_RETAIL_DIRECTORY,
    CENSUS_RETAIL_LEVEL_SERIES_ID,
    CENSUS_RETAIL_MOM_SERIES_ID,
    CENSUS_RETAIL_SOURCE,
    CENSUS_RETAIL_TIMING_QUALITY,
    parse_census_retail_archive,
)
from macro_nowcast.dol_claims_archive import (
    DOL_CLAIMS_DIRECTORY,
    DOL_CLAIMS_SERIES_ID,
    DOL_CLAIMS_SOURCE,
    DOL_CLAIMS_TIMING_QUALITY,
    parse_dol_claims_archive,
)
from macro_nowcast.fed_g17_archive import (
    FED_G17_DIRECTORY,
    FED_G17_INDEX_SERIES_ID,
    FED_G17_MOM_SERIES_ID,
    FED_G17_SOURCE,
    FED_G17_TIMING_QUALITY,
    parse_fed_g17_archive,
)
from macro_nowcast.schema import VintageObservation, observations_to_frame
from macro_nowcast.storage import VintageStore
from macro_nowcast.treasury_rates_archive import (
    TREASURY_10Y_SERIES_ID,
    TREASURY_RATES_AVAILABILITY_RULE,
    TREASURY_RATES_DIRECTORY,
    TREASURY_RATES_TIMING_QUALITY,
    parse_treasury_rates_archive,
)

OFFICIAL_ARCHIVE_PROVENANCE = "official_agency_archive"
GDP_GROWTH_SERIES_ID = "BEA_REAL_GDP_GROWTH_QOQ_SAAR"
UNEMPLOYMENT_RATE_SERIES_ID = "LNS14000000"
EMPSIT_DOM_DIRECTORY = "bls-empsit-html"

_CES_HEADER_RE = re.compile(r"([A-Z][a-z]{2})_(\d{2})")
_CPI_MEMBER_RE = re.compile(r"(?:^|/)cpi-u[_-](\d{6})\.(xls|xlsx)$", re.IGNORECASE)
_GDP_QUARTER_RE = re.compile(r"(\d{4})Q([1-4])")
_GDP_DATE_RE = re.compile(r"([A-Z][a-z]{2} \d{1,2}, \d{4})")
_MONTHS = {
    name: number
    for number, name in enumerate(
        ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"),
        start=1,
    )
}
_GDP_RELEASE_TYPES = {
    "Advance": "initial",
    "Initial": "initial",
    "Second": "second",
    "Preliminary": "second",
    "Third": "third",
    "Final": "third",
    "Updated": "revised",
    "Revised": "revised",
}
_MISSING_CPI_VALUES = {"", ".", "-", "\N{EN DASH}", "\N{EM DASH}"}
_MONTH_TOKEN_RE = re.compile(
    r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|"
    r"Aug(?:ust)?|Sept?(?:ember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?",
    re.IGNORECASE,
)
_NUMBER_RE = re.compile(r"[pr]?(-?\d+(?:\.\d+)?)", re.IGNORECASE)
_EMPSIT_LABEL_RE = re.compile(r"([A-Za-z]+) (\d{4}) Employment Situation")
_EMPSIT_FILENAME_RE = re.compile(r"empsit_(\d{2})(\d{2})(\d{4})\.htm")


class ArchiveIngestionError(RuntimeError):
    """Raised when audited source content cannot be mapped without guessing."""


@dataclass(frozen=True, slots=True)
class OfficialArchiveData:
    """Canonical official observations, target releases, and ingestion metadata."""

    observations: pl.DataFrame
    release_calendar: pl.DataFrame
    metadata: Mapping[str, object]


def _gdp_level_target_validation(
    observations: pl.DataFrame,
    release_calendar: pl.DataFrame,
) -> pl.DataFrame:
    """Reconcile level-derived and directly published initial GDP growth."""

    from macro_nowcast.targets import (
        PUBLISHED_REAL_GDP_TARGET_SPEC,
        REAL_GDP_TARGET_SPEC,
        build_targets_for_spec,
    )

    if not observations.filter(pl.col("series_id") == BEA_NIPA_LEVEL_SERIES_ID).height:
        return pl.DataFrame()
    latest_as_of = release_calendar["release_timestamp"].max()
    assert isinstance(latest_as_of, datetime)
    level_targets = build_targets_for_spec(
        observations,
        release_calendar,
        REAL_GDP_TARGET_SPEC,
        latest_as_of=latest_as_of,
        modes=("first_release",),
        built_at=latest_as_of,
    ).select(
        "target_period",
        pl.col("value").alias("level_derived_qoq_saar_percent"),
        pl.col("current_level").alias("level_current"),
        pl.col("prior_level").alias("level_prior"),
        pl.col("current_level_realtime_start").alias("current_level_vintage_date"),
        pl.col("prior_level_realtime_start").alias("prior_level_vintage_date"),
        pl.col("snapshot_timestamp").alias("level_snapshot_timestamp"),
        pl.col("target_release_timestamp").alias("level_target_release_timestamp"),
        pl.col("release_id").alias("level_release_id"),
        pl.col("target_formula").alias("level_target_formula"),
        pl.col("observation_source").alias("level_observation_source"),
        pl.col("calendar_source").alias("level_calendar_source"),
    )
    published_targets = build_targets_for_spec(
        observations,
        release_calendar,
        PUBLISHED_REAL_GDP_TARGET_SPEC,
        latest_as_of=latest_as_of,
        modes=("first_release",),
        built_at=latest_as_of,
    ).select(
        "target_period",
        pl.col("value").alias("published_qoq_saar_percent"),
        pl.col("snapshot_timestamp").alias("published_snapshot_timestamp"),
        pl.col("release_id").alias("published_release_id"),
        pl.col("observation_source").alias("published_observation_source"),
    )
    joined = (
        level_targets.join(published_targets, on="target_period", how="left", validate="1:1")
        .with_columns(
            (
                pl.col("level_derived_qoq_saar_percent")
                - pl.col("published_qoq_saar_percent")
            ).alias("difference_pp"),
            (
                pl.col("current_level_vintage_date")
                == pl.col("prior_level_vintage_date")
            ).alias("same_snapshot_adjacent_levels"),
        )
        .with_columns(
            pl.col("difference_pp").abs().alias("absolute_difference_pp"),
            (
                pl.col("level_derived_qoq_saar_percent").round(1)
                == pl.col("published_qoq_saar_percent")
            ).alias("rounds_exactly_to_published_tenth"),
            (pl.col("difference_pp").abs() <= 0.06).alias(
                "within_006pp_level_rounding_tolerance"
            ),
        )
        .sort("target_period")
    )
    if joined.height != 96:
        raise ArchiveIngestionError(
            f"expected 96 level-derived GDP validation rows, found {joined.height}"
        )
    if joined["published_qoq_saar_percent"].null_count():
        raise ArchiveIngestionError("GDP level validation has no published comparison")
    if not joined["same_snapshot_adjacent_levels"].all():
        raise ArchiveIngestionError("GDP level target mixes source snapshots")
    if not joined["within_006pp_level_rounding_tolerance"].all():
        raise ArchiveIngestionError("GDP level target fails published-growth reconciliation")
    return joined


@dataclass(frozen=True, slots=True)
class CESVintageSeriesSpec:
    """One seasonally adjusted CES employment series in the BLS vintage ZIP."""

    series_id: str
    agency_series_id: str
    archive_member: str
    industry_title: str
    observation_start: date | None = None


class _A1TableParser(HTMLParser):
    """Collect cells from the archived CPS table A-1 without third-party HTML deps."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_target = False
        self.table_depth = 0
        self.current_row: list[str] | None = None
        self.current_cell: list[str] | None = None
        self.rows: list[list[str]] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        attributes = dict(attrs)
        if tag == "table" and attributes.get("id") == "cps_empsit_a01":
            self.in_target = True
            self.table_depth = 1
            return
        if not self.in_target:
            return
        if tag == "table":
            self.table_depth += 1
        elif tag == "tr":
            self.current_row = []
        elif tag in {"th", "td"}:
            self.current_cell = []

    def handle_endtag(self, tag: str) -> None:
        if not self.in_target:
            return
        if tag in {"th", "td"} and self.current_cell is not None:
            assert self.current_row is not None
            text = " ".join("".join(self.current_cell).split())
            self.current_row.append(text)
            self.current_cell = None
        elif tag == "tr" and self.current_row is not None:
            if self.current_row:
                self.rows.append(self.current_row)
            self.current_row = None
        elif tag == "table":
            self.table_depth -= 1
            if self.table_depth == 0:
                self.in_target = False

    def handle_data(self, data: str) -> None:
        if self.in_target and self.current_cell is not None:
            self.current_cell.append(data)


class _VisibleTextParser(HTMLParser):
    """Extract visible archival text while preserving preformatted line breaks."""

    _BLOCKS: ClassVar[frozenset[str]] = frozenset(
        {
            "br",
            "div",
            "figure",
            "h1",
            "h2",
            "h3",
            "li",
            "p",
            "pre",
            "section",
            "table",
            "tr",
        }
    )

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.ignored_depth = 0

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        del attrs
        if tag in {"script", "style"}:
            self.ignored_depth += 1
        elif not self.ignored_depth and tag in self._BLOCKS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self.ignored_depth:
            self.ignored_depth -= 1
        elif not self.ignored_depth and tag in self._BLOCKS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.ignored_depth:
            self.parts.append(data)

    def text(self) -> str:
        return "".join(self.parts)


PAYEMS_CES_SPEC = CESVintageSeriesSpec(
    series_id="PAYEMS",
    agency_series_id="CES0000000001",
    archive_member="tri_000000_SA.csv",
    industry_title="Total nonfarm",
)

# These are genuine publication-vintage matrices from the same Employment
# Situation releases as PAYEMS.  Keeping the official BLS identifiers as the
# canonical IDs avoids implying that the rows came from FRED aliases.
CES_SECTOR_PREDICTOR_SPECS = (
    CESVintageSeriesSpec(
        "CES2000000001",
        "CES2000000001",
        "tri_200000_SA.csv",
        "Construction",
        date(2002, 1, 1),
    ),
    CESVintageSeriesSpec(
        "CES3000000001",
        "CES3000000001",
        "tri_300000_SA.csv",
        "Manufacturing",
        date(2002, 1, 1),
    ),
    CESVintageSeriesSpec(
        "CES4000000001",
        "CES4000000001",
        "tri_400000_SA.csv",
        "Trade, transportation, and utilities",
        date(2002, 1, 1),
    ),
    CESVintageSeriesSpec(
        "CES5000000001",
        "CES5000000001",
        "tri_500000_SA.csv",
        "Information",
        date(2002, 1, 1),
    ),
    CESVintageSeriesSpec(
        "CES5500000001",
        "CES5500000001",
        "tri_550000_SA.csv",
        "Financial activities",
        date(2002, 1, 1),
    ),
    CESVintageSeriesSpec(
        "CES6000000001",
        "CES6000000001",
        "tri_600000_SA.csv",
        "Professional and business services",
        date(2002, 1, 1),
    ),
    CESVintageSeriesSpec(
        "CES6500000001",
        "CES6500000001",
        "tri_650000_SA.csv",
        "Private education and health services",
        date(2002, 1, 1),
    ),
    CESVintageSeriesSpec(
        "CES7000000001",
        "CES7000000001",
        "tri_700000_SA.csv",
        "Leisure and hospitality",
        date(2002, 1, 1),
    ),
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _download_timestamp(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime, UTC)


def _month_start(period: str) -> date:
    try:
        return date(int(period[:4]), int(period[5:7]), 1)
    except (TypeError, ValueError) as exc:
        raise ArchiveIngestionError(f"invalid monthly period: {period!r}") from exc


def _ces_observation_date(header: str) -> date:
    match = _CES_HEADER_RE.fullmatch(header)
    if match is None:
        raise ArchiveIngestionError(f"invalid CES observation header: {header!r}")
    short_year = int(match.group(2))
    year = 2000 + short_year if short_year < 30 else 1900 + short_year
    return date(year, _MONTHS[match.group(1)], 1)


def _date_only_release_timestamp(release_date: date) -> datetime:
    return datetime.combine(release_date, time.max, UTC)


def _rows_with_realtime_ends(
    rows: Sequence[Mapping[str, object]],
) -> list[VintageObservation]:
    grouped: dict[tuple[str, date], list[dict[str, object]]] = defaultdict(list)
    for source_row in rows:
        row = dict(source_row)
        grouped[(str(row["series_id"]), row["observation_date"])].append(row)  # type: ignore[index]

    result: list[VintageObservation] = []
    for values in grouped.values():
        values.sort(key=lambda row: row["realtime_start"])  # type: ignore[arg-type,return-value]
        starts = [row["realtime_start"] for row in values]
        if len(starts) != len(set(starts)):
            raise ArchiveIngestionError(
                "one observation has multiple source vintages on the same release date"
            )
        for index, row in enumerate(values):
            if index + 1 < len(values):
                next_start = values[index + 1]["realtime_start"]
                assert isinstance(next_start, date)
                row["realtime_end"] = next_start - timedelta(days=1)
            result.append(VintageObservation.from_mapping(row))
    return result


def _month_number(text: str) -> int:
    normalized = text.strip().rstrip(".").lower()
    candidates = (
        "january",
        "february",
        "march",
        "april",
        "may",
        "june",
        "july",
        "august",
        "september",
        "october",
        "november",
        "december",
    )
    for number, candidate in enumerate(candidates, start=1):
        if candidate.startswith(normalized):
            return number
    raise ArchiveIngestionError(f"invalid Employment Situation month: {text!r}")


def _month_year(text: str) -> date:
    compact = "".join(text.split())
    month = _MONTH_TOKEN_RE.match(compact)
    year = re.search(r"(19|20)\d{2}", compact)
    if month is None or year is None:
        raise ArchiveIngestionError(f"invalid Employment Situation month header: {text!r}")
    return date(int(year.group()), _month_number(month.group()), 1)


def _numeric_cell(text: str) -> float | None:
    normalized = "".join(text.split()).replace(",", "")
    if normalized in {"", "-", "--", "\N{EN DASH}", "\N{EM DASH}"}:
        return None
    match = _NUMBER_RE.fullmatch(normalized)
    if match is None:
        raise ArchiveIngestionError(f"invalid Employment Situation numeric cell: {text!r}")
    return float(match.group(1))


def _structured_unemployment_snapshot(document: str) -> tuple[list[tuple[date, float]], str]:
    parser = _A1TableParser()
    parser.feed(document)
    if not parser.rows:
        return [], ""
    header = next(
        (
            row
            for row in parser.rows
            if len(row) == 9
            and all(
                _MONTH_TOKEN_RE.search(cell) and re.search(r"(19|20)\d{2}", cell) for cell in row
            )
        ),
        None,
    )
    values = next(
        (
            row[1:]
            for row in parser.rows
            if row and row[0].strip().lower() == "unemployment rate" and len(row) == 10
        ),
        None,
    )
    if header is None or values is None:
        raise ArchiveIngestionError("structured Employment Situation table A-1 is incomplete")
    dates = [_month_year(cell) for cell in header[3:]]
    parsed_values = [_numeric_cell(cell) for cell in values[3:]]
    return [
        (observation_date, value)
        for observation_date, value in zip(dates, parsed_values, strict=True)
        if value is not None
    ], "html_table_a1"


def _preformatted_unemployment_snapshot(
    document: str,
) -> tuple[list[tuple[date, float]], str]:
    parser = _VisibleTextParser()
    parser.feed(document)
    text = parser.text()
    start_match = re.search(r"Table\s+A-1\.\s+Employment status", text, re.IGNORECASE)
    if start_match is None:
        raise ArchiveIngestionError("Employment Situation DOM has no table A-1")
    following = text[start_match.start() :]
    stop_match = re.search(r"\n\s*Table\s+A-2\.", following, re.IGNORECASE)
    table = following[: stop_match.start()] if stop_match else following
    lines = table.splitlines()
    stub_index = next(
        index for index, line in enumerate(lines) if "Employment status, sex, and age" in line
    )
    header_dates: list[date] | None = None
    for index in range(stub_index + 1, min(stub_index + 20, len(lines) - 1)):
        months = _MONTH_TOKEN_RE.findall(lines[index])
        years = re.findall(r"(?:19|20)\d{2}", lines[index + 1])
        if len(months) == 9 and len(years) == 9:
            header_dates = [
                date(int(year), _month_number(month), 1)
                for month, year in zip(months, years, strict=True)
            ]
            break
    if header_dates is None:
        raise ArchiveIngestionError("preformatted table A-1 has no nine-column month header")
    unemployment_line = next(
        (line for line in lines if re.match(r"^\s*Unemployment rate\.{2,}", line, re.IGNORECASE)),
        None,
    )
    if unemployment_line is None:
        raise ArchiveIngestionError("preformatted table A-1 has no total unemployment-rate row")
    values = [float(value) for value in _NUMBER_RE.findall(unemployment_line)]
    if len(values) != 9:
        raise ArchiveIngestionError(
            f"preformatted table A-1 expected nine unemployment rates; found {len(values)}"
        )
    return list(zip(header_dates[3:], values[3:], strict=True)), "preformatted_table_a1"


def parse_empsit_unemployment_rate_snapshot(
    path: str | Path,
    *,
    current_period: date,
    release_date: date,
    release_clock: BLSReleaseClock | None = None,
    download_timestamp: datetime | None = None,
) -> list[dict[str, object]]:
    """Parse the published seasonally adjusted U-3 history visible in table A-1."""

    source_path = Path(path)
    document = source_path.read_text(encoding="utf-8")
    if not document.rstrip().endswith("</html>"):
        raise ArchiveIngestionError(
            f"incomplete Employment Situation DOM export: {source_path.name}"
        )
    snapshot, extraction_basis = _structured_unemployment_snapshot(document)
    if not snapshot:
        snapshot, extraction_basis = _preformatted_unemployment_snapshot(document)
    if not snapshot or snapshot[-1][0] != current_period:
        found = snapshot[-1][0].isoformat() if snapshot else "none"
        raise ArchiveIngestionError(
            f"Employment Situation {release_date} current period mismatch: "
            f"expected {current_period}, found {found}"
        )
    acquired_at = download_timestamp or _download_timestamp(source_path)
    source_url = f"https://www.bls.gov/news.release/archives/{source_path.name}"
    source_hash = _sha256(source_path)
    if release_clock is not None and release_clock.release_date != release_date:
        raise ArchiveIngestionError("Employment Situation release clock date mismatch")
    release_timestamp = (
        release_clock.release_timestamp if release_clock is not None else None
    )
    timing_quality = (
        BLS_EMBARGO_CLOCK_TIMING_QUALITY
        if release_clock is not None
        else DATE_ONLY_TIMING_QUALITY
    )
    return [
        {
            "series_id": UNEMPLOYMENT_RATE_SERIES_ID,
            "observation_date": observation_date,
            "realtime_start": release_date,
            "availability_date": release_date,
            "release_timestamp": release_timestamp,
            "availability_timestamp": release_timestamp,
            "value": value,
            "units": "percent",
            "frequency": "monthly",
            "seasonal_adjustment": "seasonally_adjusted",
            "transformation": "level",
            "download_timestamp": acquired_at,
            "source": "BLS_EMPLOYMENT_SITUATION_DOM_ARCHIVE",
            "provenance_label": OFFICIAL_ARCHIVE_PROVENANCE,
            "source_metadata": {
                "agency_series_id": UNEMPLOYMENT_RATE_SERIES_ID,
                "archive_file": source_path.name,
                "archive_sha256": source_hash,
                "source_url": source_url,
                "snapshot_current_period": current_period.isoformat(),
                "extraction_basis": extraction_basis,
                "dom_export_kind": "browser_rendered_complete_dom",
                "timing_quality": timing_quality,
                "printed_release_timezone": (
                    release_clock.printed_timezone if release_clock is not None else None
                ),
            },
        }
        for observation_date, value in snapshot
    ]


def parse_empsit_unemployment_rate_archive(
    directory: str | Path,
    release_mapping: Sequence[Mapping[str, object]],
    *,
    release_clocks: Mapping[date, BLSReleaseClock] | None = None,
) -> list[VintageObservation]:
    """Parse all acquired Employment Situation DOM exports as genuine vintages."""

    source_directory = Path(directory)
    index_path = source_directory.parent / "empsit-release-index.json"
    official_periods: dict[date, date] = {}
    if index_path.exists():
        document = json.loads(index_path.read_text(encoding="utf-8"))
        for event in document.get("release_events", []):
            label = event.get("observation_label")
            if not isinstance(label, str):
                continue
            match = _EMPSIT_LABEL_RE.fullmatch(label)
            if match is None:
                continue
            official_periods[date.fromisoformat(str(event["release_date"]))] = date(
                int(match.group(2)),
                _month_number(match.group(1)),
                1,
            )
    raw_rows: list[dict[str, object]] = []
    parsed_files = 0
    mapped_periods: dict[date, date] = {}
    for release in release_mapping:
        release_date = date.fromisoformat(str(release["release_date"]))
        mapped_periods.setdefault(
            release_date,
            _month_start(str(release["vintage_period"])),
        )
    for source_path in sorted(source_directory.glob("empsit_*.htm")):
        match = _EMPSIT_FILENAME_RE.fullmatch(source_path.name)
        if match is None:
            raise ArchiveIngestionError(
                f"unexpected Employment Situation archive filename: {source_path.name}"
            )
        release_date = date(int(match.group(3)), int(match.group(1)), int(match.group(2)))
        current_period = official_periods.get(release_date, mapped_periods.get(release_date))
        if current_period is None:
            raise ArchiveIngestionError(
                f"Employment Situation archive has no official period mapping: {release_date}"
            )
        raw_rows.extend(
            parse_empsit_unemployment_rate_snapshot(
                source_path,
                current_period=current_period,
                release_date=release_date,
                release_clock=(release_clocks or {}).get(release_date),
            )
        )
        parsed_files += 1
    if parsed_files == 0:
        raise ArchiveIngestionError("no Employment Situation DOM exports were parsed")
    return _rows_with_realtime_ends(raw_rows)


def parse_ces_series_vintage_archive(
    path: str | Path,
    release_mapping: Sequence[Mapping[str, object]],
    *,
    series: CESVintageSeriesSpec,
    release_clocks: Mapping[date, BLSReleaseClock] | None = None,
    download_timestamp: datetime | None = None,
) -> list[VintageObservation]:
    """Expand one audited BLS CES vintage matrix into canonical observations."""

    source_path = Path(path)
    mapping = {str(row["vintage_period"]): row for row in release_mapping}
    acquired_at = download_timestamp or _download_timestamp(source_path)
    archive_hash = _sha256(source_path)
    raw_rows: list[dict[str, object]] = []
    with ZipFile(source_path) as archive:
        if series.archive_member not in archive.namelist():
            raise ArchiveIngestionError(
                f"CES archive is missing {series.archive_member} for {series.agency_series_id}"
            )
        binary = archive.open(series.archive_member)
        reader = csv.reader(io.TextIOWrapper(binary, encoding="utf-8-sig", newline=""))
        header = next(reader)
        observation_dates = [_ces_observation_date(value) for value in header[2:]]
        for source_row in reader:
            vintage_period = f"{int(source_row[0]):04d}-{int(source_row[1]):02d}"
            release = mapping.get(vintage_period)
            if release is None:
                raise ArchiveIngestionError(
                    f"CES vintage has no audited release mapping: {vintage_period}"
                )
            if (
                release.get("mapping_basis")
                == "official_november_release_includes_october_ces_initial"
            ):
                continue
            release_date = date.fromisoformat(str(release["release_date"]))
            release_clock = (release_clocks or {}).get(release_date)
            if release_clock is not None and release_clock.release_date != release_date:
                raise ArchiveIngestionError("CES release clock date mismatch")
            release_timestamp = (
                release_clock.release_timestamp if release_clock is not None else None
            )
            timing_quality = (
                BLS_EMBARGO_CLOCK_TIMING_QUALITY
                if release_clock is not None
                else DATE_ONLY_TIMING_QUALITY
            )
            latest_allowed = _month_start(vintage_period)
            for observation_date, raw_value in zip(
                observation_dates,
                source_row[2:],
                strict=True,
            ):
                if (
                    series.observation_start is not None
                    and observation_date < series.observation_start
                ):
                    continue
                if raw_value in {"", ".", "-1"}:
                    continue
                if observation_date > latest_allowed:
                    raise ArchiveIngestionError(
                        f"CES {vintage_period} contains future period {observation_date}"
                    )
                value = float(raw_value)
                if value < 0:
                    raise ArchiveIngestionError("CES employment levels cannot be negative")
                raw_rows.append(
                    {
                        "series_id": series.series_id,
                        "observation_date": observation_date,
                        "realtime_start": release_date,
                        "availability_date": release_date,
                        "release_timestamp": release_timestamp,
                        "availability_timestamp": release_timestamp,
                        "value": value,
                        "units": "thousands_of_persons",
                        "frequency": "monthly",
                        "seasonal_adjustment": "seasonally_adjusted",
                        "transformation": "level",
                        "download_timestamp": acquired_at,
                        "source": "BLS_CES_VINTAGE_ARCHIVE",
                        "provenance_label": OFFICIAL_ARCHIVE_PROVENANCE,
                        "source_metadata": {
                            "agency_series_id": series.agency_series_id,
                            "archive_member": series.archive_member,
                            "archive_sha256": archive_hash,
                            "industry_title": series.industry_title,
                            "observation_start_filter": (
                                series.observation_start.isoformat()
                                if series.observation_start is not None
                                else None
                            ),
                            "vintage_period": vintage_period,
                            "release_mapping_basis": release["mapping_basis"],
                            "timing_quality": timing_quality,
                            "printed_release_timezone": (
                                release_clock.printed_timezone
                                if release_clock is not None
                                else None
                            ),
                        },
                    }
                )
    return _rows_with_realtime_ends(raw_rows)


def parse_ces_vintage_archive(
    path: str | Path,
    release_mapping: Sequence[Mapping[str, object]],
    *,
    release_clocks: Mapping[date, BLSReleaseClock] | None = None,
    download_timestamp: datetime | None = None,
) -> list[VintageObservation]:
    """Backward-compatible total-nonfarm CES vintage parser."""

    return parse_ces_series_vintage_archive(
        path,
        release_mapping,
        series=PAYEMS_CES_SPEC,
        release_clocks=release_clocks,
        download_timestamp=download_timestamp,
    )


def parse_ces_sector_vintage_archives(
    path: str | Path,
    release_mapping: Sequence[Mapping[str, object]],
    *,
    series: Sequence[CESVintageSeriesSpec] = CES_SECTOR_PREDICTOR_SPECS,
    release_clocks: Mapping[date, BLSReleaseClock] | None = None,
    download_timestamp: datetime | None = None,
) -> list[VintageObservation]:
    """Parse the declared set of BLS sector-employment vintage matrices."""

    parsed: list[VintageObservation] = []
    for definition in series:
        parsed.extend(
            parse_ces_series_vintage_archive(
                path,
                release_mapping,
                series=definition,
                release_clocks=release_clocks,
                download_timestamp=download_timestamp,
            )
        )
    return parsed


def _cpi_period(value: object) -> str | None:
    normalized = re.sub(r"[.\n\r]+", " ", str(value)).strip()
    match = re.search(r"([A-Za-z]{3,9})\s+(\d{4})", normalized)
    if match is None:
        return None
    month = _MONTHS.get(match.group(1)[:3].title())
    if month is None:
        return None
    return f"{int(match.group(2)):04d}-{month:02d}"


def parse_cpi_snapshot(
    payload: bytes,
    *,
    snapshot_period: str,
    release_date: date,
    download_timestamp: datetime,
    source_file: str,
    source_sha256: str,
    release_clock: BLSReleaseClock | None = None,
    release_clock_metadata: Mapping[str, object] | None = None,
) -> list[dict[str, object]]:
    """Read the seasonally adjusted core-CPI level row from one snapshot workbook."""

    rows = read_xlsx_rows(payload, "US")
    item_matches = [
        (row_number, column)
        for row_number, values in rows.items()
        for column, value in values.items()
        if str(value).strip() == "All items less food and energy"
    ]
    if len(item_matches) != 1:
        raise ArchiveIngestionError(
            f"{source_file} requires exactly one core-CPI row; found {len(item_matches)}"
        )
    item_row_number, item_label_column = item_matches[0]
    item_row = rows[item_row_number]
    category_candidates = [
        (row_number, values)
        for row_number, values in rows.items()
        if row_number < item_row_number
        and any(str(value).strip() == "Seasonally adjusted indexes" for value in values.values())
    ]
    if not category_candidates:
        raise ArchiveIngestionError(f"{source_file} has no seasonally adjusted index header")
    category_row_number, category_row = max(category_candidates, key=lambda item: item[0])
    explicit_index_columns = {
        column
        for column, value in category_row.items()
        if str(value).strip() == "Seasonally adjusted indexes"
    }
    index_start = min(explicit_index_columns)
    following_heading_columns = [
        column
        for column, value in category_row.items()
        if column > index_start
        and str(value).strip()
        and str(value).strip() != "Seasonally adjusted indexes"
    ]
    index_stop = min(following_heading_columns, default=max(item_row) + 1)
    index_columns = set(range(index_start, index_stop))
    period_candidates: list[tuple[int, dict[int, str]]] = []
    for row_number in range(category_row_number + 1, item_row_number):
        parsed = {
            column: period
            for column in index_columns
            if (period := _cpi_period(rows.get(row_number, {}).get(column))) is not None
        }
        if parsed:
            period_candidates.append((row_number, parsed))
    if not period_candidates:
        raise ArchiveIngestionError(f"{source_file} has no CPI index-period header")
    _, periods_by_column = max(period_candidates, key=lambda item: len(item[1]))
    normalized_snapshot = f"{snapshot_period[:4]}-{snapshot_period[4:]}"
    if normalized_snapshot not in periods_by_column.values():
        raise ArchiveIngestionError(
            f"{source_file} does not contain its snapshot period {normalized_snapshot}"
        )

    if release_clock is not None and release_clock.release_date != release_date:
        raise ArchiveIngestionError("CPI release clock date mismatch")
    release_timestamp = (
        release_clock.release_timestamp if release_clock is not None else None
    )
    timing_quality = (
        BLS_EMBARGO_CLOCK_TIMING_QUALITY
        if release_clock is not None
        else DATE_ONLY_TIMING_QUALITY
    )
    parsed_rows: list[dict[str, object]] = []
    for column, period in sorted(periods_by_column.items(), key=lambda item: item[1]):
        if period > normalized_snapshot:
            raise ArchiveIngestionError(f"{source_file} contains future CPI period {period}")
        raw_value = item_row.get(column)
        if raw_value is None or str(raw_value).strip() in _MISSING_CPI_VALUES:
            continue
        parsed_rows.append(
            {
                "series_id": "CPILFESL",
                "observation_date": _month_start(period),
                "realtime_start": release_date,
                "availability_date": release_date,
                "release_timestamp": release_timestamp,
                "availability_timestamp": release_timestamp,
                "value": float(raw_value),
                "units": "index_1982_1984_100",
                "frequency": "monthly",
                "seasonal_adjustment": "seasonally_adjusted",
                "transformation": "level",
                "download_timestamp": download_timestamp,
                "source": "BLS_CPI_SUPPLEMENTAL_ARCHIVE",
                "provenance_label": OFFICIAL_ARCHIVE_PROVENANCE,
                "source_metadata": {
                    "agency_series_id": "CUSR0000SA0L1E",
                    "source_file": source_file,
                    "source_sha256": source_sha256,
                    "snapshot_period": normalized_snapshot,
                    "sheet": "US",
                    "row": item_row_number,
                    "item_label_column": item_label_column,
                    "column": column,
                    "timing_quality": timing_quality,
                    "printed_release_timezone": (
                        release_clock.printed_timezone
                        if release_clock is not None
                        else None
                    ),
                    "release_clock_evidence_format": (
                        release_clock_metadata.get("evidence_format")
                        if release_clock_metadata is not None
                        else None
                    ),
                    "release_clock_header_sha256": (
                        release_clock_metadata.get("header_sha256")
                        if release_clock_metadata is not None
                        else None
                    ),
                },
            }
        )
    return parsed_rows


def _cpi_members(archive: ZipFile, year: int) -> dict[str, str]:
    result: dict[str, str] = {}
    for name in archive.namelist():
        match = _CPI_MEMBER_RE.search(name)
        if match is not None and match.group(1).startswith(str(year)):
            result[match.group(1)] = name
    if len(result) != 12:
        raise ArchiveIngestionError(f"CPI {year} requires 12 monthly workbooks")
    return result


def parse_cpi_archives(
    raw_dir: str | Path,
    release_mapping: Sequence[Mapping[str, object]],
    *,
    release_clock_archive: BLSCPIClockArchive | None = None,
) -> list[VintageObservation]:
    """Parse every audited CPI supplemental snapshot, including legacy XLS files."""

    directory = Path(raw_dir)
    releases = {
        str(row["snapshot_period"]).replace("-", ""): date.fromisoformat(str(row["release_date"]))
        for row in release_mapping
    }
    raw_rows: list[dict[str, object]] = []
    for year in CPI_ARCHIVE_YEARS:
        archive_path = directory / f"cpi-supplemental-{year}.zip"
        archive_hash = _sha256(archive_path)
        acquired_at = _download_timestamp(archive_path)
        with ZipFile(archive_path) as archive:
            members = _cpi_members(archive, year)
            legacy = {
                period: archive.read(name)
                for period, name in members.items()
                if name.lower().endswith(".xls")
            }
            converted_legacy, _ = convert_legacy_xls_to_xlsx(legacy)
            for period, name in sorted(members.items()):
                payload = (
                    converted_legacy[period]
                    if name.lower().endswith(".xls")
                    else archive.read(name)
                )
                raw_rows.extend(
                    parse_cpi_snapshot(
                        payload,
                        snapshot_period=period,
                        release_date=releases[period],
                        download_timestamp=acquired_at,
                        source_file=name,
                        source_sha256=archive_hash,
                        release_clock=(
                            release_clock_archive.clocks.get(releases[period])
                            if release_clock_archive is not None
                            else None
                        ),
                        release_clock_metadata=(
                            release_clock_archive.event_metadata.get(releases[period])
                            if release_clock_archive is not None
                            else None
                        ),
                    )
                )
    current = directory / "cpi-current"
    for period in CPI_CURRENT_PERIODS:
        path = current / f"cpi-u-{period}.xlsx"
        raw_rows.extend(
            parse_cpi_snapshot(
                path.read_bytes(),
                snapshot_period=period,
                release_date=releases[period],
                download_timestamp=_download_timestamp(path),
                source_file=path.name,
                source_sha256=_sha256(path),
                release_clock=(
                    release_clock_archive.clocks.get(releases[period])
                    if release_clock_archive is not None
                    else None
                ),
                release_clock_metadata=(
                    release_clock_archive.event_metadata.get(releases[period])
                    if release_clock_archive is not None
                    else None
                ),
            )
        )
    return _rows_with_realtime_ends(raw_rows)


def _gdp_release_date(value: object) -> date:
    match = _GDP_DATE_RE.search(str(value))
    if match is None:
        raise ArchiveIngestionError(f"GDP release date text is invalid: {value!r}")
    return datetime.strptime(match.group(1), "%b %d, %Y").date()


def parse_gdp_vintage_history(
    path: str | Path,
    *,
    release_clocks: Mapping[date, BEAReleaseClock] | None = None,
    release_clock_metadata: Mapping[date, Mapping[str, object]] | None = None,
    download_timestamp: datetime | None = None,
) -> list[VintageObservation]:
    """Parse BEA's already-annualized published real-GDP growth vintages."""

    source_path = Path(path)
    acquired_at = download_timestamp or _download_timestamp(source_path)
    source_hash = _sha256(source_path)
    rows = read_xlsx_rows(source_path, "Vintage History")
    quarter_rows: list[tuple[int, str]] = []
    for row_number, values in rows.items():
        for value in values.values():
            if _GDP_QUARTER_RE.fullmatch(str(value).strip()):
                quarter_rows.append((row_number, str(value).strip()))
                break
    quarter_rows.sort()
    raw_rows: list[dict[str, object]] = []
    for index, (start, quarter) in enumerate(quarter_rows):
        stop = quarter_rows[index + 1][0] if index + 1 < len(quarter_rows) else max(rows) + 1
        match = _GDP_QUARTER_RE.fullmatch(quarter)
        assert match is not None
        observation_date = date(int(match.group(1)), (int(match.group(2)) - 1) * 3 + 1, 1)
        for row_number in range(start + 1, stop):
            values = rows.get(row_number, {})
            source_release_type = str(values.get(2, "")).strip()
            release_type = _GDP_RELEASE_TYPES.get(source_release_type)
            if release_type is None:
                continue
            release_text = str(values.get(7, "")).strip()
            release_date = _gdp_release_date(release_text)
            release_clock = (release_clocks or {}).get(release_date)
            clock_metadata = (release_clock_metadata or {}).get(release_date)
            release_timestamp = (
                release_clock.release_timestamp if release_clock is not None else None
            )
            raw_rows.append(
                {
                    "series_id": GDP_GROWTH_SERIES_ID,
                    "observation_date": observation_date,
                    "realtime_start": release_date,
                    "availability_date": release_date,
                    "release_timestamp": release_timestamp,
                    "availability_timestamp": release_timestamp,
                    "value": float(values[5]),
                    "units": "percent_change_qoq_saar",
                    "frequency": "quarterly",
                    "seasonal_adjustment": "seasonally_adjusted_annual_rate",
                    "transformation": "already_transformed",
                    "download_timestamp": acquired_at,
                    "source": "BEA_GDP_GDI_VINTAGE_HISTORY",
                    "provenance_label": OFFICIAL_ARCHIVE_PROVENANCE,
                    "source_metadata": {
                        "agency_series_id": "A191RL",
                        "source_file": source_path.name,
                        "source_sha256": source_hash,
                        "source_release_type": source_release_type,
                        "release_type": release_type,
                        "release_date_text": release_text,
                        "timing_quality": (
                            BEA_GDP_CLOCK_TIMING_QUALITY
                            if release_clock is not None
                            else DATE_ONLY_TIMING_QUALITY
                        ),
                        "printed_release_timezone": (
                            release_clock.printed_timezone
                            if release_clock is not None
                            else None
                        ),
                        "release_clock_evidence_format": (
                            clock_metadata.get("evidence_format")
                            if clock_metadata is not None
                            else None
                        ),
                        "release_clock_header_sha256": (
                            clock_metadata.get("header_sha256")
                            if clock_metadata is not None
                            else None
                        ),
                        "archive_index_published_date": (
                            clock_metadata.get("archive_index_published_date")
                            if clock_metadata is not None
                            else None
                        ),
                        "source_date_discrepancy": (
                            clock_metadata.get("source_date_discrepancy")
                            if clock_metadata is not None
                            else None
                        ),
                    },
                }
            )
    return _rows_with_realtime_ends(raw_rows)


def _release_calendar(
    ces_mapping: Sequence[Mapping[str, object]],
    cpi_mapping: Sequence[Mapping[str, object]],
    gdp_observations: Sequence[VintageObservation],
    dol_claims_observations: Sequence[VintageObservation] = (),
    fed_g17_observations: Sequence[VintageObservation] = (),
    census_retail_observations: Sequence[VintageObservation] = (),
    census_housing_observations: Sequence[VintageObservation] = (),
    gdp_level_observations: Sequence[VintageObservation] = (),
    empsit_release_clocks: Mapping[date, BLSReleaseClock] | None = None,
    cpi_release_clocks: Mapping[date, BLSReleaseClock] | None = None,
    gdp_release_clocks: Mapping[date, BEAReleaseClock] | None = None,
) -> pl.DataFrame:
    rows: list[dict[str, object]] = []
    for mapping in ces_mapping:
        period = str(mapping["vintage_period"])
        release_date = date.fromisoformat(str(mapping["release_date"]))
        release_clock = (empsit_release_clocks or {}).get(release_date)
        rows.append(
            {
                "release_id": f"bls-payems-{period}-initial",
                "series_id": "PAYEMS",
                "observation_date": _month_start(period),
                "release_timestamp": (
                    release_clock.release_timestamp
                    if release_clock is not None
                    else _date_only_release_timestamp(release_date)
                ),
                "release_type": "initial",
                "timing_quality": (
                    BLS_EMBARGO_CLOCK_TIMING_QUALITY
                    if release_clock is not None
                    else DATE_ONLY_TIMING_QUALITY
                ),
                "source": "BLS_EMPLOYMENT_SITUATION_ARCHIVE",
                "provenance_label": OFFICIAL_ARCHIVE_PROVENANCE,
            }
        )
    for mapping in cpi_mapping:
        period = str(mapping["snapshot_period"])
        release_date = date.fromisoformat(str(mapping["release_date"]))
        release_clock = (cpi_release_clocks or {}).get(release_date)
        rows.append(
            {
                "release_id": f"bls-cpilfesl-{period}-initial",
                "series_id": "CPILFESL",
                "observation_date": _month_start(period),
                "release_timestamp": (
                    release_clock.release_timestamp
                    if release_clock is not None
                    else _date_only_release_timestamp(release_date)
                ),
                "release_type": "initial",
                "timing_quality": (
                    BLS_EMBARGO_CLOCK_TIMING_QUALITY
                    if release_clock is not None
                    else DATE_ONLY_TIMING_QUALITY
                ),
                "source": "BLS_CPI_NEWS_RELEASE_ARCHIVE",
                "provenance_label": OFFICIAL_ARCHIVE_PROVENANCE,
            }
        )
    for observation in gdp_observations:
        if observation.source_metadata.get("release_type") != "initial":
            continue
        release_clock = (gdp_release_clocks or {}).get(observation.availability_date)
        quarter = (observation.observation_date.month + 2) // 3
        rows.append(
            {
                "release_id": (
                    f"bea-real-gdp-growth-{observation.observation_date.year}-Q{quarter}-initial"
                ),
                "series_id": GDP_GROWTH_SERIES_ID,
                "observation_date": observation.observation_date,
                "release_timestamp": (
                    release_clock.release_timestamp
                    if release_clock is not None
                    else _date_only_release_timestamp(observation.availability_date)
                ),
                "release_type": "initial",
                "timing_quality": (
                    BEA_GDP_CLOCK_TIMING_QUALITY
                    if release_clock is not None
                    else DATE_ONLY_TIMING_QUALITY
                ),
                "source": "BEA_GDP_GDI_VINTAGE_HISTORY",
                "provenance_label": OFFICIAL_ARCHIVE_PROVENANCE,
            }
        )
    for observation in dol_claims_observations:
        if observation.source_metadata.get("vintage_type") != "advance":
            continue
        if observation.release_timestamp is None:
            raise ArchiveIngestionError("DOL claims advance row requires a release timestamp")
        rows.append(
            {
                "release_id": f"dol-ui-claims-{observation.observation_date.isoformat()}-advance",
                "series_id": DOL_CLAIMS_SERIES_ID,
                "observation_date": observation.observation_date,
                "release_timestamp": observation.release_timestamp,
                "release_type": "initial",
                "timing_quality": DOL_CLAIMS_TIMING_QUALITY,
                "source": DOL_CLAIMS_SOURCE,
                "provenance_label": OFFICIAL_ARCHIVE_PROVENANCE,
            }
        )
    g17_releases: dict[date, list[VintageObservation]] = defaultdict(list)
    for observation in fed_g17_observations:
        if observation.series_id == FED_G17_INDEX_SERIES_ID:
            g17_releases[observation.realtime_start].append(observation)
    for release_date, release_observations in sorted(g17_releases.items()):
        representative = max(release_observations, key=lambda row: row.observation_date)
        if representative.release_timestamp is None:
            raise ArchiveIngestionError("Fed G.17 row requires a release timestamp")
        source_release_type = str(representative.source_metadata.get("release_type"))
        rows.append(
            {
                "release_id": f"fed-g17-{release_date.isoformat()}-{source_release_type}",
                "series_id": FED_G17_MOM_SERIES_ID,
                "observation_date": representative.observation_date,
                "release_timestamp": representative.release_timestamp,
                "release_type": source_release_type,
                "timing_quality": FED_G17_TIMING_QUALITY,
                "source": FED_G17_SOURCE,
                "provenance_label": OFFICIAL_ARCHIVE_PROVENANCE,
            }
        )
    for observation in census_retail_observations:
        if observation.series_id != CENSUS_RETAIL_MOM_SERIES_ID:
            continue
        if observation.release_timestamp is None:
            raise ArchiveIngestionError("Census MARTS row requires a release timestamp")
        rows.append(
            {
                "release_id": (
                    f"census-marts-{observation.observation_date.isoformat()}-advance"
                ),
                "series_id": CENSUS_RETAIL_MOM_SERIES_ID,
                "observation_date": observation.observation_date,
                "release_timestamp": observation.release_timestamp,
                "release_type": "initial",
                "timing_quality": CENSUS_RETAIL_TIMING_QUALITY,
                "source": CENSUS_RETAIL_SOURCE,
                "provenance_label": OFFICIAL_ARCHIVE_PROVENANCE,
            }
        )
    for observation in census_housing_observations:
        if observation.series_id != CENSUS_HOUSING_STARTS_SERIES_ID:
            continue
        if observation.release_timestamp is None:
            raise ArchiveIngestionError("Census NRC row requires a release timestamp")
        rows.append(
            {
                "release_id": (
                    f"census-nrc-{observation.observation_date.isoformat()}-preliminary"
                ),
                "series_id": CENSUS_HOUSING_STARTS_SERIES_ID,
                "observation_date": observation.observation_date,
                "release_timestamp": observation.release_timestamp,
                "release_type": "initial",
                "timing_quality": CENSUS_HOUSING_TIMING_QUALITY,
                "source": CENSUS_HOUSING_SOURCE,
                "provenance_label": OFFICIAL_ARCHIVE_PROVENANCE,
            }
        )
    for observation in gdp_level_observations:
        target_quarter = observation.source_metadata.get("target_quarter")
        if not isinstance(target_quarter, str):
            continue
        quarter = (observation.observation_date.month - 1) // 3 + 1
        observation_quarter = f"{observation.observation_date.year:04d}Q{quarter}"
        if observation_quarter != target_quarter:
            continue
        if observation.release_timestamp is None:
            raise ArchiveIngestionError("BEA NIPA level target row requires exact timing")
        rows.append(
            {
                "release_id": f"bea-real-gdp-level-{target_quarter}-initial",
                "series_id": BEA_NIPA_LEVEL_SERIES_ID,
                "observation_date": observation.observation_date,
                "release_timestamp": observation.release_timestamp,
                "release_type": "initial",
                "timing_quality": BEA_GDP_CLOCK_TIMING_QUALITY,
                "source": BEA_NIPA_LEVEL_SOURCE,
                "provenance_label": OFFICIAL_ARCHIVE_PROVENANCE,
            }
        )
    return validate_release_calendar(
        pl.from_dicts(rows, schema=RELEASE_CALENDAR_SCHEMA, strict=True)
    )


def _count_release_rows_with_clock(
    release_mapping: Sequence[Mapping[str, object]],
    clocks: Mapping[date, object],
) -> int:
    """Count target rows, not unique dates, backed by exact clock evidence."""

    return sum(
        date.fromisoformat(str(row["release_date"])) in clocks
        for row in release_mapping
    )


def build_official_archive_data(raw_dir: str | Path) -> OfficialArchiveData:
    """Audit and parse all acquired official target archives without network access."""

    directory = Path(raw_dir).resolve()
    audit = audit_agency_vintages(directory)
    if audit["status"] != "verified_with_limitations":
        raise ArchiveAuditError("official archive audit must pass before ingestion")
    artifacts = audit["artifacts"]
    ces_artifact = artifacts["ces"]  # type: ignore[index]
    cpi_artifact = artifacts["cpi"]  # type: ignore[index]
    ces_mapping = ces_artifact["release_mapping"]["release_date_mapping"]
    cpi_mapping = cpi_artifact["release_mapping"]["release_date_mapping"]

    empsit_directory = directory / EMPSIT_DOM_DIRECTORY
    empsit_dom_clock_archive = (
        parse_empsit_release_clock_archive(empsit_directory)
        if empsit_directory.exists()
        else None
    )
    empsit_text_clock_directory = directory / BLS_EMPSIT_CLOCK_DIRECTORY
    empsit_text_clock_archive = (
        parse_empsit_text_clock_archive(
            empsit_text_clock_directory,
            release_index_path=directory / "empsit-release-index.json",
        )
        if empsit_text_clock_directory.exists()
        else None
    )
    empsit_release_clocks = merge_empsit_release_clocks(
        (
            empsit_dom_clock_archive.clocks
            if empsit_dom_clock_archive is not None
            else {}
        ),
        (
            empsit_text_clock_archive.clocks
            if empsit_text_clock_archive is not None
            else {}
        ),
    )

    ces = parse_ces_vintage_archive(
        directory / CES_FILENAME,
        ces_mapping,
        release_clocks=empsit_release_clocks,
    )
    ces_sectors = parse_ces_sector_vintage_archives(
        directory / CES_FILENAME,
        ces_mapping,
        release_clocks=empsit_release_clocks,
    )
    unemployment_rate = (
        parse_empsit_unemployment_rate_archive(
            empsit_directory,
            ces_mapping,
            release_clocks=empsit_release_clocks,
        )
        if empsit_directory.exists()
        else []
    )
    cpi_clock_directory = directory / BLS_CPI_CLOCK_DIRECTORY
    cpi_clock_archive = (
        parse_bls_cpi_clock_archive(
            cpi_clock_directory / BLS_CPI_CLOCK_FILENAME,
            release_index_path=directory / CPI_RELEASE_INDEX_FILENAME,
        )
        if cpi_clock_directory.exists()
        else None
    )
    cpi = parse_cpi_archives(
        directory,
        cpi_mapping,
        release_clock_archive=cpi_clock_archive,
    )
    gdp_clock_directory = directory / BEA_GDP_CLOCK_DIRECTORY
    gdp_clock_archive: BEAGDPClockArchive | None = (
        parse_bea_gdp_clock_archive(
            gdp_clock_directory / BEA_GDP_CLOCK_FILENAME,
        )
        if gdp_clock_directory.exists()
        else None
    )
    gdp = parse_gdp_vintage_history(
        directory / GDP_VINTAGE_FILENAME,
        release_clocks=(
            gdp_clock_archive.clocks if gdp_clock_archive is not None else {}
        ),
        release_clock_metadata=(
            gdp_clock_archive.event_metadata if gdp_clock_archive is not None else {}
        ),
    )
    nipa_level_directory = directory / BEA_NIPA_LEVEL_DIRECTORY
    if nipa_level_directory.exists():
        if gdp_clock_archive is None:
            raise ArchiveIngestionError(
                "BEA NIPA level ingestion requires verified GDP clock evidence"
            )
        _, gdp_levels = parse_bea_nipa_level_archive(
            nipa_level_directory,
            clock_evidence_path=gdp_clock_directory / BEA_GDP_CLOCK_FILENAME,
        )
    else:
        gdp_levels = []
    dol_claims_directory = directory / DOL_CLAIMS_DIRECTORY
    dol_claims = (
        parse_dol_claims_archive(dol_claims_directory)
        if dol_claims_directory.exists()
        else []
    )
    fed_g17_directory = directory / FED_G17_DIRECTORY
    fed_g17 = parse_fed_g17_archive(fed_g17_directory) if fed_g17_directory.exists() else []
    treasury_rates_directory = directory / TREASURY_RATES_DIRECTORY
    treasury_rates = (
        parse_treasury_rates_archive(treasury_rates_directory)
        if treasury_rates_directory.exists()
        else []
    )
    census_retail_directory = directory / CENSUS_RETAIL_DIRECTORY
    census_retail = (
        parse_census_retail_archive(census_retail_directory)
        if census_retail_directory.exists()
        else []
    )
    census_housing_directory = directory / CENSUS_HOUSING_DIRECTORY
    census_housing = (
        parse_census_housing_archive(census_housing_directory)
        if census_housing_directory.exists()
        else []
    )
    observations = observations_to_frame(
        [
            *ces,
            *ces_sectors,
            *unemployment_rate,
            *cpi,
            *gdp,
            *gdp_levels,
            *dol_claims,
            *fed_g17,
            *treasury_rates,
            *census_retail,
            *census_housing,
        ]
    )
    calendar = _release_calendar(
        ces_mapping,
        cpi_mapping,
        gdp,
        dol_claims,
        fed_g17,
        census_retail,
        census_housing,
        gdp_levels,
        empsit_release_clocks=empsit_release_clocks,
        cpi_release_clocks=(
            cpi_clock_archive.clocks if cpi_clock_archive is not None else {}
        ),
        gdp_release_clocks=(
            gdp_clock_archive.clocks if gdp_clock_archive is not None else {}
        ),
    )
    metadata: dict[str, object] = {
        "provenance_label": OFFICIAL_ARCHIVE_PROVENANCE,
        "audit_status": audit["status"],
        "historical_ingestion_ready": True,
        "intraday_timing_verified": False,
        "target_intraday_timing_partially_verified": bool(
            empsit_release_clocks or cpi_clock_archive or gdp_clock_archive
        ),
        "employment_situation_exact_release_clock_count": len(
            empsit_release_clocks
        ),
        "employment_situation_html_exact_release_clock_count": (
            len(empsit_dom_clock_archive.clocks)
            if empsit_dom_clock_archive is not None
            else 0
        ),
        "employment_situation_txt_exact_release_clock_count": (
            len(empsit_text_clock_archive.clocks)
            if empsit_text_clock_archive is not None
            else 0
        ),
        "employment_situation_txt_clock_evidence_sha256": (
            empsit_text_clock_archive.evidence_sha256
            if empsit_text_clock_archive is not None
            else None
        ),
        "payems_target_release_clock_count": _count_release_rows_with_clock(
            ces_mapping,
            empsit_release_clocks,
        ),
        "employment_situation_date_only_clock_exclusions": (
            {
                release_date.isoformat(): reason
                for release_date, reason in empsit_dom_clock_archive.exclusions.items()
            }
            if empsit_dom_clock_archive is not None
            else {}
        ),
        "cpi_exact_release_clock_count": (
            len(cpi_clock_archive.clocks) if cpi_clock_archive is not None else 0
        ),
        "cpi_target_release_clock_count": (
            len(
                {
                    date.fromisoformat(str(row["release_date"]))
                    for row in cpi_mapping
                    if cpi_clock_archive is not None
                    and date.fromisoformat(str(row["release_date"]))
                    in cpi_clock_archive.clocks
                }
            )
            if cpi_clock_archive is not None
            else 0
        ),
        "cpi_release_clock_evidence_sha256": (
            cpi_clock_archive.evidence_sha256
            if cpi_clock_archive is not None
            else None
        ),
        "gdp_exact_release_clock_count": (
            len(gdp_clock_archive.clocks) if gdp_clock_archive is not None else 0
        ),
        "gdp_target_release_clock_count": (
            len(
                {
                    row.realtime_start
                    for row in gdp
                    if row.source_metadata.get("release_type") == "initial"
                    and gdp_clock_archive is not None
                    and row.realtime_start in gdp_clock_archive.clocks
                }
            )
            if gdp_clock_archive is not None
            else 0
        ),
        "gdp_release_clock_evidence_sha256": (
            gdp_clock_archive.evidence_sha256
            if gdp_clock_archive is not None
            else None
        ),
        "gdp_release_clock_source_date_discrepancies": (
            artifacts.get("gdp_release_clock_evidence", {}).get(
                "source_date_discrepancies",
                {},
            )
        ),
        "gdp_target_intraday_timing_verified": bool(gdp_clock_archive),
        "empirical_findings_supported": False,
        "timing_convention": (
            "event_specific_exact_clock_else_official_date_eod_convention"
        ),
        "forecast_origin_rule": (
            "one_second_before_exact_release_else_previous_calendar_day_eod_"
            "America/New_York"
        ),
        "gdp_target_semantics": "official_published_qoq_saar_growth_not_level_derived",
        "gdp_nipa_level_vintages_included": bool(gdp_levels),
        "gdp_nipa_level_series_id": BEA_NIPA_LEVEL_SERIES_ID,
        "gdp_nipa_level_canonical_rows": len(gdp_levels),
        "gdp_nipa_level_release_snapshots": len(
            {row.realtime_start for row in gdp_levels}
        ),
        "gdp_nipa_level_missing_target_quarters": (
            artifacts.get("gdp_nipa_level_archive", {}).get("missing_quarters", [])
        ),
        "gdp_nipa_level_same_snapshot_growth_supported": bool(gdp_levels),
        "gdp_nipa_level_cross_vintage_raw_level_comparison_supported": False,
        "gdp_nipa_level_published_growth_exact_rounded_count": (
            artifacts.get("gdp_nipa_level_archive", {}).get(
                "published_growth_exact_rounded_count"
            )
        ),
        "gdp_nipa_level_published_growth_reconciliation_count": (
            artifacts.get("gdp_nipa_level_archive", {}).get(
                "published_growth_reconciliation_count"
            )
        ),
        "ces_sector_predictor_vintages_included": True,
        "cps_unemployment_rate_vintages_included": bool(unemployment_rate),
        "cps_unemployment_rate_series_id": UNEMPLOYMENT_RATE_SERIES_ID,
        "cps_unemployment_rate_release_snapshots": len(
            {row.realtime_start for row in unemployment_rate}
        ),
        "dol_weekly_claims_vintages_included": bool(dol_claims),
        "dol_weekly_claims_series_id": DOL_CLAIMS_SERIES_ID,
        "dol_weekly_claims_release_snapshots": len(
            {
                row.realtime_start
                for row in dol_claims
                if row.source_metadata.get("vintage_type") == "advance"
            }
        ),
        "dol_weekly_claims_intraday_timing_verified": bool(dol_claims),
        "fed_g17_vintages_included": bool(fed_g17),
        "fed_g17_index_series_id": FED_G17_INDEX_SERIES_ID,
        "fed_g17_mom_series_id": FED_G17_MOM_SERIES_ID,
        "fed_g17_release_snapshots": len({row.realtime_start for row in fed_g17}),
        "fed_g17_release_clock_times_verified": bool(fed_g17),
        "treasury_10y_daily_observations_included": bool(treasury_rates),
        "treasury_10y_series_id": TREASURY_10Y_SERIES_ID,
        "treasury_10y_observation_rows": len(treasury_rates),
        "treasury_10y_first_observation_date": (
            min(row.observation_date for row in treasury_rates).isoformat()
            if treasury_rates
            else None
        ),
        "treasury_10y_last_observation_date": (
            max(row.observation_date for row in treasury_rates).isoformat()
            if treasury_rates
            else None
        ),
        "treasury_10y_timing_quality": TREASURY_RATES_TIMING_QUALITY,
        "treasury_10y_availability_rule": TREASURY_RATES_AVAILABILITY_RULE,
        "treasury_10y_exact_publication_clock_claimed": False,
        "treasury_10y_publication_vintage_dimension_available": False,
        "treasury_10y_later_correction_history_available": False,
        "census_retail_vintages_included": bool(census_retail),
        "census_retail_level_series_id": CENSUS_RETAIL_LEVEL_SERIES_ID,
        "census_retail_mom_series_id": CENSUS_RETAIL_MOM_SERIES_ID,
        "census_retail_release_snapshots": len(
            {row.realtime_start for row in census_retail}
        ),
        "census_retail_release_clock_times_verified": bool(census_retail),
        "census_housing_vintages_included": bool(census_housing),
        "census_housing_starts_series_id": CENSUS_HOUSING_STARTS_SERIES_ID,
        "census_housing_release_snapshots": len(census_housing),
        "census_housing_release_clock_times_verified": bool(census_housing),
        "ces_sector_predictor_series": [
            {
                "series_id": spec.series_id,
                "agency_series_id": spec.agency_series_id,
                "industry_title": spec.industry_title,
                "archive_member": spec.archive_member,
                "observation_start": (
                    spec.observation_start.isoformat()
                    if spec.observation_start is not None
                    else None
                ),
            }
            for spec in CES_SECTOR_PREDICTOR_SPECS
        ],
        "observation_rows": observations.height,
        "release_rows": calendar.height,
        "series": observations["series_id"].unique().sort().to_list(),
        "row_counts_by_series": {
            row["series_id"]: row["len"]
            for row in observations.group_by("series_id").len().to_dicts()
        },
        "source_audit": {
            "audited_at": audit["audited_at"],
            "api_credentials_used": audit["api_credentials_used"],
            "api_txt_read": audit["api_txt_read"],
        },
    }
    return OfficialArchiveData(observations, calendar, metadata)


def write_official_archive_data(
    raw_dir: str | Path,
    output_dir: str | Path,
    *,
    overwrite: bool = False,
) -> dict[str, object]:
    """Write frozen Parquet artifacts and metadata after a successful local audit."""

    data = build_official_archive_data(raw_dir)
    destination = Path(output_dir).resolve()
    observations_path = destination / "official_vintage_observations.parquet"
    calendar_path = destination / "official_release_calendar.parquet"
    gdp_level_validation_path = destination / "gdp_level_target_validation.parquet"
    catalog_path = destination / "official_vintages.duckdb"
    metadata_path = destination / "ingestion_manifest.json"
    existing = [
        path
        for path in (
            observations_path,
            calendar_path,
            gdp_level_validation_path,
            catalog_path,
            metadata_path,
        )
        if path.exists()
    ]
    if existing and not overwrite:
        raise FileExistsError(f"official artifacts already exist: {existing[0].name}")
    destination.mkdir(parents=True, exist_ok=True)
    if overwrite and catalog_path.exists():
        catalog_path.unlink()
    store = VintageStore(destination, catalog_path)
    observations_path = store.write_observations(
        data.observations,
        dataset_name="official_vintage_observations",
        overwrite=overwrite,
        table_name="official_vintage_observations",
    )
    data.release_calendar.write_parquet(calendar_path, compression="zstd", statistics=True)
    store.register_view(calendar_path, table_name="official_release_calendar")
    gdp_level_validation = _gdp_level_target_validation(
        data.observations,
        data.release_calendar,
    )
    if gdp_level_validation.height:
        gdp_level_validation.write_parquet(
            gdp_level_validation_path,
            compression="zstd",
            statistics=True,
        )
        store.register_view(
            gdp_level_validation_path,
            table_name="gdp_level_target_validation",
        )
    elif overwrite and gdp_level_validation_path.exists():
        gdp_level_validation_path.unlink()
    manifest = {
        "status": "ready_with_mixed_timing",
        **data.metadata,
        "observation_artifact": {
            "path": observations_path.name,
            "sha256": _sha256(observations_path),
        },
        "release_calendar_artifact": {
            "path": calendar_path.name,
            "sha256": _sha256(calendar_path),
        },
        "gdp_level_target_validation_artifact": (
            {
                "path": gdp_level_validation_path.name,
                "sha256": _sha256(gdp_level_validation_path),
                "rows": gdp_level_validation.height,
                "same_snapshot_rows": int(
                    gdp_level_validation["same_snapshot_adjacent_levels"].sum()
                ),
                "exact_rounded_rows": int(
                    gdp_level_validation["rounds_exactly_to_published_tenth"].sum()
                ),
                "within_006pp_rows": int(
                    gdp_level_validation[
                        "within_006pp_level_rounding_tolerance"
                    ].sum()
                ),
                "maximum_abs_difference_pp": gdp_level_validation[
                    "absolute_difference_pp"
                ].max(),
                "target_semantics": (
                    "same_snapshot_adjacent_real_gdp_levels_qoq_saar_validation_only"
                ),
                "official_pilot_target_replaced": False,
            }
            if gdp_level_validation.height
            else None
        ),
        "duckdb_catalog": {
            "path": catalog_path.name,
            "views": [
                "official_vintage_observations",
                "official_release_calendar",
                *(
                    ["gdp_level_target_validation"]
                    if gdp_level_validation.height
                    else []
                ),
            ],
        },
    }
    metadata_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "status": "ready_with_mixed_timing",
        "output_dir": destination,
        "observation_rows": data.observations.height,
        "release_rows": data.release_calendar.height,
        "gdp_level_target_validation_rows": gdp_level_validation.height,
        "historical_ingestion_ready": True,
    }


__all__ = [
    "CENSUS_HOUSING_DIRECTORY",
    "CENSUS_HOUSING_STARTS_SERIES_ID",
    "CENSUS_RETAIL_DIRECTORY",
    "CENSUS_RETAIL_LEVEL_SERIES_ID",
    "CENSUS_RETAIL_MOM_SERIES_ID",
    "CES_SECTOR_PREDICTOR_SPECS",
    "DATE_ONLY_TIMING_QUALITY",
    "DOL_CLAIMS_DIRECTORY",
    "DOL_CLAIMS_SERIES_ID",
    "EMPSIT_DOM_DIRECTORY",
    "FED_G17_DIRECTORY",
    "FED_G17_INDEX_SERIES_ID",
    "FED_G17_MOM_SERIES_ID",
    "GDP_GROWTH_SERIES_ID",
    "OFFICIAL_ARCHIVE_PROVENANCE",
    "PAYEMS_CES_SPEC",
    "UNEMPLOYMENT_RATE_SERIES_ID",
    "ArchiveIngestionError",
    "CESVintageSeriesSpec",
    "OfficialArchiveData",
    "build_official_archive_data",
    "parse_ces_sector_vintage_archives",
    "parse_ces_series_vintage_archive",
    "parse_ces_vintage_archive",
    "parse_cpi_archives",
    "parse_cpi_snapshot",
    "parse_empsit_unemployment_rate_archive",
    "parse_empsit_unemployment_rate_snapshot",
    "parse_gdp_vintage_history",
    "write_official_archive_data",
]
