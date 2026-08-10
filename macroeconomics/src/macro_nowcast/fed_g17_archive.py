"""Acquire, audit, and parse Federal Reserve G.17 publication vintages.

The Board's G.17 release index exposes dated ASCII copies of monthly releases
and historical/annual revisions.  Those files are publication snapshots, not a
current-history API export.  Their headers state both the release date and the
historical EST/EDT release time.  Parsing and auditing are deterministic and
offline; network access is confined to :func:`acquire_fed_g17_archive`.

Two directly published series are retained.  The total industrial-production
index preserves the release-specific base period, while the published monthly
percent change is a separate series so changes remain comparable across
historical rebasing events.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections import defaultdict
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Final
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from macro_nowcast.schema import VintageObservation

FED_G17_INDEX_SERIES_ID: Final = "FED_G17_TOTAL_IP_SA"
FED_G17_MOM_SERIES_ID: Final = "FED_G17_TOTAL_IP_MOM_PCT"
FED_G17_SOURCE: Final = "FED_G17_RELEASE_ARCHIVE"
FED_G17_PROVENANCE: Final = "official_agency_archive"
FED_G17_DIRECTORY: Final = "fed-g17"
FED_G17_INDEX_URL: Final = "https://www.federalreserve.gov/releases/g17/default.htm"
FED_G17_ABOUT_URL: Final = "https://www.federalreserve.gov/releases/g17/about.htm"
FED_G17_DOWNLOAD_URL: Final = "https://www.federalreserve.gov/releases/g17/download.htm"
FED_G17_PUBLIC_DOMAIN_URL: Final = "https://www.federalreserve.gov/disclaimer.htm"
FED_G17_TIMING_QUALITY: Final = "official_header_clock_America_New_York"

_BASE_URL: Final = "https://www.federalreserve.gov/releases/g17/"
_CURRENT_ASCII_URL: Final = f"{_BASE_URL}Current/g17.txt"
_USER_AGENT: Final = "macro-nowcast-research/0.1 (public archive verification)"
_NEW_YORK: Final = ZoneInfo("America/New_York")

_MONTHLY_HREF_RE = re.compile(
    r"^(?:\./)?(?P<stamp>\d{8})/g17\.txt$",
    re.IGNORECASE,
)
_REVISION_HREF_RE = re.compile(
    r"^(?:\./)?revisions/(?P<stamp>\d{8})/g17rev\.txt$",
    re.IGNORECASE,
)
_MONTH_PATTERN = (
    r"Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|"
    r"Aug(?:ust)?|Sept?(?:ember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?"
)
_MONTH_RE = re.compile(
    rf"(?P<month>{_MONTH_PATTERN})\.?\s*(?:\[(?P<bracket>[pPrR])\]|(?P<suffix>[pPrR])\b)?",
    re.IGNORECASE,
)
_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
_NUMBER_RE = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)")
_HEADER_IDENTITY_RE = re.compile(
    rf"For\s+release\s+at\s+(?P<hour>\d{{1,2}}):(?P<minute>\d{{2}})\s+"
    rf"(?P<ampm>a\.m\.|p\.m\.|noon)\s*\((?P<zone>EST|EDT|AM|PM)\)\s*\n\s*"
    rf"(?P<month>{_MONTH_PATTERN})\.?\s+(?P<day>\d{{1,2}}),\s+(?P<year>\d{{4}})",
    re.IGNORECASE,
)
_BASE_PERIOD_RE = re.compile(r"\b(?P<base>\d{4})\s*=\s*100\b")
_ANNUAL_INDEX_HEADER_RE = re.compile(
    r"^\s*IP\s*\((?P<base>\d{4})\s*=\s*100\)",
    re.IGNORECASE,
)
_ANNUAL_PERCENT_HEADER_RE = re.compile(r"^\s*IP\s*\(percent\b", re.IGNORECASE)
_YEAR_ROW_RE = re.compile(r"^\s*(?P<year>(?:19|20)\d{2})\s*\|")

_MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}


class FedG17ArchiveError(RuntimeError):
    """Raised when official G.17 archive content cannot be used without guessing."""


@dataclass(frozen=True, slots=True)
class FedG17Release:
    """One dated ASCII release enumerated by the Board's official index."""

    release_date: date
    release_type: str
    href: str

    @property
    def official_url(self) -> str:
        return urljoin(_BASE_URL, self.href.removeprefix("./"))

    @property
    def archive_path_date(self) -> date:
        match = (
            _REVISION_HREF_RE.fullmatch(self.href)
            if self.release_type == "annual_revision"
            else _MONTHLY_HREF_RE.fullmatch(self.href)
        )
        return _release_date(match.group("stamp")) if match is not None else self.release_date

    @property
    def relative_path(self) -> Path:
        directory = "revisions" if self.release_type == "annual_revision" else "releases"
        filename = "g17rev.txt" if self.release_type == "annual_revision" else "g17.txt"
        stamp = self.archive_path_date.strftime("%Y%m%d")
        return Path(directory) / stamp / filename


@dataclass(frozen=True, slots=True)
class FedG17PublishedValue:
    """One total-IP month as printed in one release snapshot."""

    observation_date: date
    index_value: float
    percent_change: float | None
    vintage_type: str


@dataclass(frozen=True, slots=True)
class FedG17ReleaseValues:
    """Parsed identity, timing, base period, and recent total-IP values."""

    release_date: date
    release_type: str
    release_timestamp: datetime
    release_zone_label: str
    base_period: str
    values: tuple[FedG17PublishedValue, ...]
    extraction_pattern: str


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hrefs: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag.lower() != "a":
            return
        href = dict(attrs).get("href")
        if href is not None:
            self.hrefs.append(href.strip())


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _release_date(stamp: str) -> date:
    try:
        return datetime.strptime(stamp, "%Y%m%d").date()
    except ValueError as exc:
        raise FedG17ArchiveError(f"invalid G.17 release date in link: {stamp}") from exc


def parse_fed_g17_archive_index(document: str | bytes) -> list[FedG17Release]:
    """Return all stable, dated monthly and annual-revision ASCII links."""

    if isinstance(document, bytes):
        document = document.decode("utf-8-sig", errors="replace")
    parser = _LinkParser()
    parser.feed(document)
    releases: dict[tuple[date, str], FedG17Release] = {}
    for raw_href in parser.hrefs:
        href = raw_href.strip()
        monthly = _MONTHLY_HREF_RE.fullmatch(href)
        revision = _REVISION_HREF_RE.fullmatch(href)
        if monthly is None and revision is None:
            continue
        match = revision or monthly
        assert match is not None
        release_type = "annual_revision" if revision is not None else "monthly"
        release = FedG17Release(_release_date(match.group("stamp")), release_type, href)
        key = (release.release_date, release.release_type)
        existing = releases.get(key)
        if existing is not None and existing.official_url.lower() != release.official_url.lower():
            raise FedG17ArchiveError(f"conflicting G.17 archive links for {key}")
        releases[key] = release
    if not releases:
        raise FedG17ArchiveError("G.17 archive index contains no dated ASCII releases")
    return sorted(releases.values(), key=lambda item: (item.release_date, item.release_type))


def _release_identity(text: str) -> tuple[date, datetime, str]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    match = _HEADER_IDENTITY_RE.search(normalized[:8_000])
    if match is None:
        raise FedG17ArchiveError("G.17 release header date/time was not found")
    month = _MONTHS[match.group("month").rstrip(".").lower()]
    release_date = date(int(match.group("year")), month, int(match.group("day")))
    hour = int(match.group("hour")) % 12
    if match.group("ampm").lower() == "noon":
        hour = 12
    elif match.group("ampm").lower().startswith("p"):
        hour += 12
    local = datetime(
        release_date.year,
        release_date.month,
        release_date.day,
        hour,
        int(match.group("minute")),
        tzinfo=_NEW_YORK,
    )
    source_zone = match.group("zone").upper()
    if source_zone in {"EST", "EDT"} and local.tzname() != source_zone:
        raise FedG17ArchiveError(
            f"G.17 header zone {source_zone} disagrees with release date {release_date}"
        )
    return release_date, local.astimezone(UTC), source_zone


def _split_table_line(line: str) -> list[str]:
    return line.split("|")


def _month_columns(
    month_segment: str,
    year_segment: str,
    release_date: date,
) -> list[tuple[date, str]]:
    printed_years = {int(match.group()) for match in _YEAR_RE.finditer(year_segment)}
    if not printed_years:
        raise FedG17ArchiveError("G.17 summary header has no observation year")
    parsed_months: list[tuple[int, str]] = []
    for match in _MONTH_RE.finditer(month_segment):
        month = _MONTHS[match.group("month").rstrip(".").lower()]
        marker = (match.group("bracket") or match.group("suffix") or "").lower()
        vintage_type = (
            "preliminary"
            if marker == "p"
            else "revised"
            if marker == "r"
            else "source_not_labeled"
        )
        parsed_months.append((month, vintage_type))
    if not parsed_months:
        raise FedG17ArchiveError("G.17 summary header has no observation months")
    latest_month = parsed_months[-1][0]
    year = release_date.year if latest_month < release_date.month else release_date.year - 1
    reversed_columns: list[tuple[date, str]] = []
    next_month: int | None = None
    for month, vintage_type in reversed(parsed_months):
        if next_month is not None and month > next_month:
            year -= 1
        reversed_columns.append((date(year, month, 1), vintage_type))
        next_month = month
    columns = list(reversed(reversed_columns))
    assigned_years = {observation_date.year for observation_date, _ in columns}
    if not assigned_years.issubset(printed_years):
        raise FedG17ArchiveError(
            f"G.17 summary chronology {sorted(assigned_years)} disagrees with printed "
            f"years {sorted(printed_years)}"
        )
    return columns


def _numbers(segment: str) -> list[float]:
    return [float(match.group()) for match in _NUMBER_RE.finditer(segment)]


def _parse_summary_values(
    text: str,
    release_date: date,
) -> tuple[str, tuple[FedG17PublishedValue, ...]]:
    lines = text.splitlines()
    for row_index, line in enumerate(lines):
        if not re.match(r"^\s*Total\s+index\s*\|", line, flags=re.IGNORECASE):
            continue
        if line.count("|") < 3:
            continue
        header_index = next(
            (
                candidate
                for candidate in range(row_index - 1, max(-1, row_index - 14), -1)
                if re.match(
                    r"^\s*Industrial\s+production\s*\|",
                    lines[candidate],
                    flags=re.IGNORECASE,
                )
                and lines[candidate].count("|") >= 3
            ),
            None,
        )
        if header_index is None:
            continue
        year_index = next(
            (
                candidate
                for candidate in range(header_index - 1, max(-1, header_index - 8), -1)
                if _YEAR_RE.search(lines[candidate]) and lines[candidate].count("|") >= 2
            ),
            None,
        )
        if year_index is None:
            continue
        header_parts = _split_table_line(lines[header_index])
        year_parts = _split_table_line(lines[year_index])
        value_parts = _split_table_line(line)
        if min(len(header_parts), len(year_parts), len(value_parts)) < 4:
            continue
        columns = _month_columns(header_parts[1], year_parts[1], release_date)
        index_values = _numbers(value_parts[1])
        percent_values = _numbers(value_parts[2])
        if len(index_values) != len(columns) or len(percent_values) != len(columns):
            raise FedG17ArchiveError(
                "G.17 summary month/value counts do not match: "
                f"months={len(columns)}, indexes={len(index_values)}, "
                f"changes={len(percent_values)}"
            )
        base_match = next(
            (
                match
                for candidate in range(header_index - 1, max(-1, header_index - 15), -1)
                if (match := _BASE_PERIOD_RE.search(lines[candidate])) is not None
            ),
            None,
        )
        if base_match is None:
            raise FedG17ArchiveError("G.17 summary index base period was not found")
        return base_match.group("base"), tuple(
            FedG17PublishedValue(observation_date, index_value, percent_change, vintage_type)
            for (observation_date, vintage_type), index_value, percent_change in zip(
                columns,
                index_values,
                percent_values,
                strict=True,
            )
        )
    raise FedG17ArchiveError("G.17 total-index summary table was not found")


def _year_rows(
    lines: Sequence[str],
    *,
    start: int,
    stop: int,
) -> dict[date, float]:
    values: dict[date, float] = {}
    for line in lines[start:stop]:
        match = _YEAR_ROW_RE.match(line)
        if match is None:
            continue
        parts = _split_table_line(line)
        if len(parts) < 2:
            continue
        monthly = _numbers(parts[1])[:12]
        for month, value in enumerate(monthly, start=1):
            values[date(int(match.group("year")), month, 1)] = value
    return values


def _parse_annual_table_values(text: str) -> tuple[str, tuple[FedG17PublishedValue, ...]]:
    lines = text.splitlines()
    percent_header = next(
        (index for index, line in enumerate(lines) if _ANNUAL_PERCENT_HEADER_RE.match(line)),
        None,
    )
    index_header = next(
        (index for index, line in enumerate(lines) if _ANNUAL_INDEX_HEADER_RE.match(line)),
        None,
    )
    if percent_header is None or index_header is None or percent_header >= index_header:
        return _parse_legacy_annual_table_values(text)
    base_match = _ANNUAL_INDEX_HEADER_RE.match(lines[index_header])
    assert base_match is not None
    capacity_header = next(
        (
            index
            for index in range(index_header + 1, len(lines))
            if re.match(r"^\s*Capacity\b", lines[index], flags=re.IGNORECASE)
        ),
        len(lines),
    )
    percent = _year_rows(lines, start=percent_header + 1, stop=index_header)
    indexes = _year_rows(lines, start=index_header + 1, stop=capacity_header)
    if not indexes:
        raise FedG17ArchiveError("G.17 annual revision contains no total-IP index months")
    return base_match.group("base"), tuple(
        FedG17PublishedValue(
            observation_date,
            index_value,
            percent.get(observation_date),
            "revised",
        )
        for observation_date, index_value in sorted(indexes.items())
    )


def _parse_legacy_annual_table_values(
    text: str,
) -> tuple[str, tuple[FedG17PublishedValue, ...]]:
    """Parse early revisions whose total-industry row labels span several lines."""

    lines = text.splitlines()
    table_start = next(
        (
            index
            for index, line in enumerate(lines)
            if re.match(r"^\s*1?Table\s+1\s*$", line, flags=re.IGNORECASE)
        ),
        None,
    )
    if table_start is None:
        raise FedG17ArchiveError("G.17 annual revision table one was not found")
    capacity_start = next(
        (
            index
            for index in range(table_start + 1, len(lines))
            if re.match(r"^\s*Capacity\s*\|?", lines[index], flags=re.IGNORECASE)
        ),
        None,
    )
    if capacity_start is None:
        raise FedG17ArchiveError("G.17 annual revision capacity boundary was not found")
    year_lines = [
        (index, int(match.group("year")))
        for index in range(table_start + 1, capacity_start)
        if (match := _YEAR_ROW_RE.match(lines[index])) is not None
    ]
    split = next(
        (
            index
            for index in range(1, len(year_lines))
            if year_lines[index][1] <= year_lines[index - 1][1]
        ),
        None,
    )
    if split is None:
        raise FedG17ArchiveError("G.17 annual revision IP level row block was not found")
    percent_lines = [lines[index] for index, _ in year_lines[:split]]
    index_lines = [lines[index] for index, _ in year_lines[split:]]
    percent = _year_rows(percent_lines, start=0, stop=len(percent_lines))
    indexes = _year_rows(index_lines, start=0, stop=len(index_lines))
    base_match = re.search(
        r"(?:output\s+in|reference\s+period(?:\s+for\s+the\s+index)?\s+is)\s+"
        r"(?P<base>\d{4})",
        text,
        flags=re.IGNORECASE,
    )
    if base_match is None or not indexes:
        raise FedG17ArchiveError("G.17 annual revision total-industry monthly table not found")
    return base_match.group("base"), tuple(
        FedG17PublishedValue(
            observation_date,
            index_value,
            percent.get(observation_date),
            "revised",
        )
        for observation_date, index_value in sorted(indexes.items())
    )


def parse_fed_g17_release_text(
    text: str,
    *,
    release_date: date,
    release_type: str,
) -> FedG17ReleaseValues:
    """Parse one official monthly or annual-revision ASCII snapshot."""

    if release_type not in {"monthly", "annual_revision"}:
        raise ValueError(f"unsupported G.17 release type: {release_type}")
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").replace("\u00a0", " ")
    parsed_date, released_at, source_zone = _release_identity(normalized)
    if parsed_date != release_date:
        raise FedG17ArchiveError(
            f"G.17 link date {release_date} disagrees with file header {parsed_date}"
        )
    try:
        base_period, values = _parse_summary_values(normalized, release_date)
        pattern = "published_summary_index_and_percent_change"
    except FedG17ArchiveError:
        if release_type != "annual_revision":
            raise
        base_period, values = _parse_annual_table_values(normalized)
        pattern = "annual_revision_total_industry_monthly_table"
    if not values:
        raise FedG17ArchiveError(f"{release_date}: G.17 release has no total-IP values")
    if max(value.observation_date for value in values) >= date(
        release_date.year,
        release_date.month,
        1,
    ):
        raise FedG17ArchiveError(f"{release_date}: G.17 contains a future observation month")
    return FedG17ReleaseValues(
        release_date=release_date,
        release_type=release_type,
        release_timestamp=released_at,
        release_zone_label=source_zone,
        base_period=base_period,
        values=values,
        extraction_pattern=pattern,
    )


def parse_fed_g17_release(
    payload: bytes,
    *,
    release: FedG17Release,
) -> FedG17ReleaseValues:
    """Decode and parse one official ASCII payload."""

    if not payload.strip():
        raise FedG17ArchiveError(f"empty G.17 release: {release.official_url}")
    return parse_fed_g17_release_text(
        payload.decode("utf-8-sig", errors="replace"),
        release_date=release.release_date,
        release_type=release.release_type,
    )


def _rows_with_realtime_ends(
    rows: Sequence[Mapping[str, object]],
) -> list[VintageObservation]:
    grouped: dict[tuple[str, date], list[dict[str, object]]] = defaultdict(list)
    for source_row in rows:
        row = dict(source_row)
        grouped[(str(row["series_id"]), row["observation_date"])].append(row)  # type: ignore[index]
    observations: list[VintageObservation] = []
    for values in grouped.values():
        values.sort(key=lambda row: row["realtime_start"])  # type: ignore[arg-type,return-value]
        for index, row in enumerate(values):
            next_start = values[index + 1]["realtime_start"] if index + 1 < len(values) else None
            row["realtime_end"] = (
                next_start - timedelta(days=1) if next_start is not None else None  # type: ignore[operator]
            )
            observations.append(VintageObservation.from_mapping(row))
    return sorted(
        observations,
        key=lambda item: (item.series_id, item.observation_date, item.realtime_start),
    )


def _manifest_release(entry: Mapping[str, object]) -> FedG17Release:
    release = FedG17Release(
        release_date=date.fromisoformat(str(entry["release_date"])),
        release_type=str(entry["release_type"]),
        href=str(entry["href"]),
    )
    if release.relative_path.as_posix() != str(entry["path"]):
        raise FedG17ArchiveError(f"G.17 manifest path mismatch: {entry['path']}")
    return release


def parse_fed_g17_archive(directory: str | Path) -> list[VintageObservation]:
    """Parse a manifest-hashed local G.17 archive into canonical vintage rows."""

    root = Path(directory).resolve()
    manifest_path = root / "release-index.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FedG17ArchiveError("G.17 release-index.json is missing or invalid") from exc
    entries = manifest.get("releases")
    if not isinstance(entries, list) or not entries:
        raise FedG17ArchiveError("G.17 manifest contains no releases")
    rows: list[dict[str, object]] = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise FedG17ArchiveError("invalid G.17 manifest release entry")
        release = _manifest_release(entry)
        path = root / release.relative_path
        payload = path.read_bytes()
        digest = _sha256_bytes(payload)
        if digest != str(entry["sha256"]):
            raise FedG17ArchiveError(f"G.17 hash mismatch: {release.official_url}")
        parsed = parse_fed_g17_release(payload, release=release)
        downloaded_at = datetime.fromtimestamp(path.stat().st_mtime, UTC)
        for published in parsed.values:
            common = {
                "observation_date": published.observation_date,
                "realtime_start": release.release_date,
                "availability_date": release.release_date,
                "release_timestamp": parsed.release_timestamp,
                "availability_timestamp": parsed.release_timestamp,
                "frequency": "monthly",
                "seasonal_adjustment": "seasonally_adjusted",
                "download_timestamp": downloaded_at,
                "source": FED_G17_SOURCE,
                "provenance_label": FED_G17_PROVENANCE,
                "source_metadata": {
                    "agency": "Board of Governors of the Federal Reserve System",
                    "agency_series": "Total Industrial Production",
                    "official_url": release.official_url,
                    "source_file": release.relative_path.as_posix(),
                    "source_sha256": digest,
                    "release_date": release.release_date.isoformat(),
                    "archive_path_date": release.archive_path_date.isoformat(),
                    "release_type": release.release_type,
                    "release_zone_label": parsed.release_zone_label,
                    "timing_quality": FED_G17_TIMING_QUALITY,
                    "base_period": parsed.base_period,
                    "vintage_type": published.vintage_type,
                    "extraction_pattern": parsed.extraction_pattern,
                    "public_domain_policy": FED_G17_PUBLIC_DOMAIN_URL,
                },
            }
            rows.append(
                {
                    **common,
                    "series_id": FED_G17_INDEX_SERIES_ID,
                    "value": published.index_value,
                    "units": f"index_{parsed.base_period}_100",
                    "transformation": "level",
                }
            )
            if published.percent_change is not None:
                rows.append(
                    {
                        **common,
                        "series_id": FED_G17_MOM_SERIES_ID,
                        "value": published.percent_change,
                        "units": "percent_change_mom",
                        "transformation": "already_transformed",
                    }
                )
    return _rows_with_realtime_ends(rows)


def audit_fed_g17_archive(directory: str | Path) -> dict[str, object]:
    """Verify local inventory, hashes, release headers, values, and coverage offline."""

    root = Path(directory).resolve()
    try:
        manifest = json.loads((root / "release-index.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FedG17ArchiveError("G.17 release-index.json is missing or invalid") from exc
    entries = manifest.get("releases")
    if not isinstance(entries, list) or not entries:
        raise FedG17ArchiveError("G.17 manifest contains no releases")
    expected: set[Path] = set()
    hashes: set[str] = set()
    release_dates: list[date] = []
    observation_dates: list[date] = []
    release_types: dict[str, int] = defaultdict(int)
    base_periods: set[str] = set()
    source_zone_labels: set[str] = set()
    zone_inference_release_count = 0
    path_header_date_mismatches: list[dict[str, str]] = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise FedG17ArchiveError("invalid G.17 manifest release entry")
        release = _manifest_release(entry)
        path = (root / release.relative_path).resolve()
        expected.add(path)
        payload = path.read_bytes()
        digest = _sha256_bytes(payload)
        if digest != str(entry["sha256"]):
            raise FedG17ArchiveError(f"G.17 hash mismatch: {release.official_url}")
        if digest in hashes:
            raise FedG17ArchiveError(f"duplicate G.17 release bytes: {release.official_url}")
        hashes.add(digest)
        parsed = parse_fed_g17_release(payload, release=release)
        release_dates.append(release.release_date)
        observation_dates.extend(value.observation_date for value in parsed.values)
        release_types[release.release_type] += 1
        base_periods.add(parsed.base_period)
        source_zone_labels.add(parsed.release_zone_label)
        if parsed.release_zone_label in {"AM", "PM"}:
            zone_inference_release_count += 1
        if release.archive_path_date != release.release_date:
            path_header_date_mismatches.append(
                {
                    "archive_path_date": release.archive_path_date.isoformat(),
                    "header_release_date": release.release_date.isoformat(),
                    "official_url": release.official_url,
                }
            )
    actual = {
        path.resolve()
        for directory_name in ("releases", "revisions")
        for path in (root / directory_name).glob("*/*")
        if path.is_file()
    }
    missing = sorted(str(path.relative_to(root)) for path in expected - actual)
    extra = sorted(str(path.relative_to(root)) for path in actual - expected)
    if missing or extra:
        raise FedG17ArchiveError(
            f"G.17 inventory mismatch: missing={missing[:3]}, extra={extra[:3]}"
        )
    index_entry = manifest.get("index_snapshot")
    if not isinstance(index_entry, Mapping):
        raise FedG17ArchiveError("G.17 manifest has no index snapshot")
    index_path = root / str(index_entry["path"])
    if _sha256_bytes(index_path.read_bytes()) != str(index_entry["sha256"]):
        raise FedG17ArchiveError("G.17 index snapshot hash mismatch")
    observations = parse_fed_g17_archive(root)
    timestamps = {row.release_timestamp for row in observations}
    if None in timestamps:
        raise FedG17ArchiveError("G.17 canonical rows require exact release timestamps")
    return {
        "passed": True,
        "official_url": FED_G17_INDEX_URL,
        "download_documentation": FED_G17_DOWNLOAD_URL,
        "public_domain_policy": FED_G17_PUBLIC_DOMAIN_URL,
        "directory": root.name,
        "release_count": len(entries),
        "release_types": dict(sorted(release_types.items())),
        "canonical_vintage_rows": len(observations),
        "first_release_date": min(release_dates).isoformat(),
        "last_release_date": max(release_dates).isoformat(),
        "first_observation_date": min(observation_dates).isoformat(),
        "last_observation_date": max(observation_dates).isoformat(),
        "base_periods": sorted(base_periods),
        "source_header_zone_labels": sorted(source_zone_labels),
        "america_new_york_zone_inference_release_count": zone_inference_release_count,
        "archive_path_header_date_mismatches": path_header_date_mismatches,
        "all_release_hashes_unique": len(hashes) == len(entries),
        "exact_release_clock_times_verified": True,
        "historical_EST_EDT_labels_preserved": True,
        "timing_quality": FED_G17_TIMING_QUALITY,
        "index_and_published_percent_change_retained": True,
        "server_original_bytes_claimed": True,
        "provenance_status": "official_archive_inventory_hashes_headers_and_values_verified",
    }


def _fetch(url: str, *, attempts: int = 5) -> tuple[bytes, str]:
    for attempt in range(attempts):
        request = Request(url, headers={"User-Agent": _USER_AGENT})
        try:
            with urlopen(request, timeout=60) as response:
                return response.read(), response.headers.get_content_type()
        except HTTPError as exc:
            if exc.code not in {429, 500, 502, 503, 504} or attempt == attempts - 1:
                raise FedG17ArchiveError(f"G.17 request failed: {url} ({exc.code})") from exc
            retry_after = exc.headers.get("Retry-After")
            delay = float(retry_after) if retry_after and retry_after.isdigit() else 2**attempt
        except (TimeoutError, URLError) as exc:
            if attempt == attempts - 1:
                raise FedG17ArchiveError(f"G.17 request failed: {url}") from exc
            delay = 2**attempt
        time.sleep(min(delay, 16))
    raise AssertionError("unreachable")


def _write_immutable(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise FedG17ArchiveError(f"refusing to replace immutable raw file: {path}")
        return
    temporary = path.with_suffix(f"{path.suffix}.part")
    temporary.write_bytes(payload)
    temporary.replace(path)


def acquire_fed_g17_archive(
    output_dir: str | Path,
    *,
    start_year: int = 1997,
    end_year: int | None = None,
    workers: int = 4,
) -> dict[str, object]:
    """Acquire and immediately parse-check selected official G.17 ASCII vintages."""

    final_year = end_year or datetime.now(UTC).year
    if start_year < 1997 or final_year < start_year:
        raise ValueError("G.17 archive years must satisfy 1997 <= start_year <= end_year")
    if workers < 1 or workers > 8:
        raise ValueError("workers must be between 1 and 8")
    root = Path(output_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    index_payload, index_content_type = _fetch(FED_G17_INDEX_URL)
    index_digest = _sha256_bytes(index_payload)
    index_path = root / "index" / f"{datetime.now(UTC).date().isoformat()}-{index_digest[:12]}.html"
    _write_immutable(index_path, index_payload)
    releases = parse_fed_g17_archive_index(index_payload)

    current_payload, _ = _fetch(_CURRENT_ASCII_URL)
    current_text = current_payload.decode("utf-8-sig", errors="replace")
    current_date, _, _ = _release_identity(current_text)
    current_release = FedG17Release(
        current_date,
        "monthly",
        f"{current_date.strftime('%Y%m%d')}/g17.txt",
    )
    if start_year <= current_date.year <= final_year:
        releases.append(current_release)
    unique = {
        (release.release_date, release.release_type): release
        for release in releases
        if start_year <= release.release_date.year <= final_year
    }
    ordered = sorted(unique.values(), key=lambda item: (item.release_date, item.release_type))
    if not ordered:
        raise FedG17ArchiveError("selected G.17 years contain no releases")

    def download(release: FedG17Release) -> tuple[FedG17Release, bytes, str]:
        path = root / release.relative_path
        if path.exists():
            payload = path.read_bytes()
            content_type = "text/plain"
        else:
            payload, content_type = _fetch(release.official_url)
            _write_immutable(path, payload)
            time.sleep(0.03)
        header_date, _, _ = _release_identity(payload.decode("utf-8-sig", errors="replace"))
        parsed_release = FedG17Release(header_date, release.release_type, release.href)
        parse_fed_g17_release(payload, release=parsed_release)
        return parsed_release, payload, content_type

    completed: dict[tuple[str, str], dict[str, object]] = {}
    errors: list[str] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(download, release): release for release in ordered}
        for future in as_completed(futures):
            release = futures[future]
            try:
                parsed_release, payload, content_type = future.result()
            except Exception as exc:  # collect format drift across the whole archive
                errors.append(f"{release.official_url}: {exc}")
                continue
            completed[(parsed_release.href.lower(), parsed_release.release_type)] = {
                "release_date": parsed_release.release_date.isoformat(),
                "archive_path_date": parsed_release.archive_path_date.isoformat(),
                "release_type": parsed_release.release_type,
                "href": parsed_release.href,
                "url": parsed_release.official_url,
                "content_type": content_type,
                "path": parsed_release.relative_path.as_posix(),
                "bytes": len(payload),
                "sha256": _sha256_bytes(payload),
            }
    if errors:
        raise FedG17ArchiveError(
            f"{len(errors)} G.17 releases failed validation:\n" + "\n".join(sorted(errors)[:20])
        )

    manifest_path = root / "release-index.json"
    existing_manifest = (
        json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else None
    )
    manifest = {
        "schema_version": 1,
        "status": "downloaded_and_parse_checked",
        "source_url": FED_G17_INDEX_URL,
        "download_documentation": FED_G17_DOWNLOAD_URL,
        "public_domain_policy": FED_G17_PUBLIC_DOMAIN_URL,
        "operator_opt_in_basis": "user_requested_acquisition_and_verification",
        "api_credentials_used": False,
        "api_txt_read": False,
        "acquired_at": (
            str(existing_manifest.get("acquired_at"))
            if isinstance(existing_manifest, Mapping) and existing_manifest.get("acquired_at")
            else datetime.now(UTC).isoformat().replace("+00:00", "Z")
        ),
        "start_year": start_year,
        "end_year": final_year,
        "index_snapshot": {
            "url": FED_G17_INDEX_URL,
            "content_type": index_content_type,
            "path": index_path.relative_to(root).as_posix(),
            "bytes": len(index_payload),
            "sha256": index_digest,
        },
        "release_count": len(ordered),
        "releases": [
            completed[(release.href.lower(), release.release_type)] for release in ordered
        ],
    }
    if isinstance(existing_manifest, Mapping):
        existing_hashes = {
            (str(entry["release_date"]), str(entry["release_type"])): str(entry["sha256"])
            for entry in existing_manifest.get("releases", [])
        }
        new_hashes = {
            (str(entry["release_date"]), str(entry["release_type"])): str(entry["sha256"])
            for entry in manifest["releases"]
        }
        conflicts = {
            key
            for key, digest in existing_hashes.items()
            if key in new_hashes and new_hashes[key] != digest
        }
        if conflicts:
            raise FedG17ArchiveError(
                f"refusing to rewrite G.17 release hashes: {sorted(conflicts)[:3]}"
            )
    temporary_manifest = manifest_path.with_suffix(".json.part")
    temporary_manifest.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary_manifest.replace(manifest_path)
    audit = audit_fed_g17_archive(root)
    return {
        "status": "verified",
        "output_dir": root,
        "release_count": audit["release_count"],
        "release_types": audit["release_types"],
        "canonical_vintage_rows": audit["canonical_vintage_rows"],
        "first_release_date": audit["first_release_date"],
        "last_release_date": audit["last_release_date"],
        "base_periods": audit["base_periods"],
        "exact_release_clock_times_verified": True,
    }


__all__ = [
    "FED_G17_ABOUT_URL",
    "FED_G17_DIRECTORY",
    "FED_G17_DOWNLOAD_URL",
    "FED_G17_INDEX_SERIES_ID",
    "FED_G17_INDEX_URL",
    "FED_G17_MOM_SERIES_ID",
    "FED_G17_PROVENANCE",
    "FED_G17_PUBLIC_DOMAIN_URL",
    "FED_G17_SOURCE",
    "FED_G17_TIMING_QUALITY",
    "FedG17ArchiveError",
    "FedG17PublishedValue",
    "FedG17Release",
    "FedG17ReleaseValues",
    "acquire_fed_g17_archive",
    "audit_fed_g17_archive",
    "parse_fed_g17_archive",
    "parse_fed_g17_archive_index",
    "parse_fed_g17_release",
    "parse_fed_g17_release_text",
]
