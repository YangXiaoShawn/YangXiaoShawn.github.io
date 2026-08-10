"""Acquire and audit BEA real-GDP level snapshots from the NIPA archive.

The ordinary BEA API exposes current estimates, not historical as-of vintages.
This module instead uses BEA's public historical-data directory and downloads
only the Section 1 workbook published with each initial GDP release.  Original
bytes, the evolving directory response, per-release file lists, hashes, archive
directory dates, and separately verified news-release clocks are retained.

BEA changed workbook names, Excel formats, sheet names, series-code suffixes,
scale, and chained-dollar reference years across the archive.  Consequently,
raw levels are never compared across release snapshots.  The supported target
operation is the q/q SAAR ratio of two adjacent levels from the *same* snapshot.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
import subprocess
import tempfile
import time
from collections import defaultdict
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Final
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from macro_nowcast.archive_audit import _xlsx_rows, _xlsx_sheet_names
from macro_nowcast.bea_gdp_clock_archive import (
    BEA_GDP_CLOCK_TIMING_QUALITY,
    BEAReleaseClock,
    parse_bea_gdp_clock_archive,
)
from macro_nowcast.schema import VintageObservation

BEA_NIPA_LEVEL_DIRECTORY: Final = "bea-nipa-levels"
BEA_NIPA_LEVEL_SOURCE: Final = "BEA_NIPA_HISTORICAL_RELEASE_ARCHIVE"
BEA_NIPA_LEVEL_SERIES_ID: Final = "GDPC1"
BEA_NIPA_LEVEL_PROVENANCE: Final = "official_agency_archive"
BEA_NIPA_ARCHIVE_INDEX_URL: Final = "https://apps.bea.gov/histdata/"
BEA_NIPA_RELEASE_INVENTORY_URL: Final = (
    "https://apps.bea.gov/histdata/core/data/Fea_DisplayChildrenC/"
    "?HistMainId=7&getFiles=false&getDirs=true"
)
BEA_NIPA_FILE_INVENTORY_ENDPOINT: Final = (
    "https://apps.bea.gov/histdata/core/data/Fea_DisplayChildrenC/"
)
BEA_NIPA_PUBLIC_FILE_ROOT: Final = "https://apps.bea.gov"
BEA_NIPA_EXPECTED_FIRST_QUARTER: Final = "2002Q1"
BEA_NIPA_EXPECTED_LAST_QUARTER: Final = "2026Q2"
BEA_NIPA_DOCUMENTED_MISSING_QUARTERS: Final = ("2002Q1", "2002Q2")

_SERVER_ROOT = "/Inetpub/wwwroot/website/website"
_USER_AGENT = "macro-nowcast-research/0.1 (public BEA NIPA archive verification)"
_OLE_SIGNATURE = bytes.fromhex("d0cf11e0a1b11ae1")
_RELEASE_PATH_RE = re.compile(
    r"GDP_and_PI[\\\\/](?P<year>20\d{2})[\\\\/]"
    r"(?P<quarter>[Qq][1-4])[\\\\/](?P<label>[^\\\\/]+)$"
)
_RELEASE_LABEL_RE = re.compile(
    r"^(?:\d+\.\s*)?(?P<release_type>Advance|Initial)_"
    r"(?P<month>[A-Za-z]+)-(?P<day>\d{1,2})-(?P<year>\d{4})$",
    re.IGNORECASE,
)
_SECTION1_RE = re.compile(r"Section1all_xls\.(?:xls|xlsx)$", re.IGNORECASE)
_QUARTER_RE = re.compile(r"(?P<year>\d{4})Q(?P<quarter>[1-4])", re.IGNORECASE)
_PUBLISHED_RE = re.compile(
    r"Data\s+published\s*:?[ ]*"
    r"(?P<month>Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|"
    r"July?|Aug(?:ust)?|Sept?(?:ember)?|Oct(?:ober)?|Nov(?:ember)?|"
    r"Dec(?:ember)?)\.?\s+(?P<day>\d{1,2}),?\s*(?P<year>\d{4})",
    re.IGNORECASE,
)
_BASE_YEAR_RE = re.compile(r"chained\s*\((\d{4})\)\s*dollars", re.IGNORECASE)
_GDP_CODE_RE = re.compile(r"A191RX\d*", re.IGNORECASE)
_LABEL_QUARTER_RE = re.compile(
    r"(?P<quarter>First|Second|Third|Fourth|1st|2nd|3rd|4th)\s+Quarter"
    r"(?:\s+and\s+(?:Annual|Year))?\s+(?:of\s+)?(?P<year>20\d{2})",
    re.IGNORECASE,
)
_QUARTER_NUMBERS = {
    "first": 1,
    "second": 2,
    "third": 3,
    "fourth": 4,
    "1st": 1,
    "2nd": 2,
    "3rd": 3,
    "4th": 4,
}


class BEANIPAArchiveError(RuntimeError):
    """Raised when NIPA level evidence cannot be used without guessing."""


@dataclass(frozen=True, slots=True)
class BEANIPARelease:
    """One top-level initial-release directory returned by BEA."""

    target_quarter: str
    release_type: str
    archive_directory_date: date
    archive_directory_label: str
    archive_path: str


@dataclass(frozen=True, slots=True)
class BEANIPAReleaseInventory:
    """Filtered initial-release inventory and explicit expected-coverage gaps."""

    releases: tuple[BEANIPARelease, ...]
    missing_quarters: tuple[str, ...]
    expected_first_quarter: str
    expected_last_quarter: str
    source_sha256: str


@dataclass(frozen=True, slots=True)
class BEANIPALevelSnapshot:
    """Real-GDP quarterly levels parsed from one release's Section 1 workbook."""

    target_quarter: str
    release_date: date
    release_timestamp: datetime
    release_type: str
    published_date: date
    sheet_name: str
    table_title: str
    series_code: str
    units_text: str
    scale: str
    chained_dollar_reference_year: int
    levels: tuple[tuple[date, float], ...]

    def level(self, quarter: str) -> float:
        """Return one quarter's level or fail rather than interpolate."""

        observation_date = quarter_start(quarter)
        for period, value in self.levels:
            if period == observation_date:
                return value
        raise BEANIPAArchiveError(
            f"{self.target_quarter} snapshot is missing required level {quarter}"
        )

    @property
    def target_level(self) -> float:
        return self.level(self.target_quarter)

    @property
    def prior_level(self) -> float:
        return self.level(previous_quarter(self.target_quarter))

    @property
    def qoq_saar_percent(self) -> float:
        return 100.0 * ((self.target_level / self.prior_level) ** 4 - 1.0)


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _json_document(source: bytes | str | Mapping[str, object]) -> tuple[dict[str, object], bytes]:
    if isinstance(source, Mapping):
        document = dict(source)
        payload = json.dumps(document, separators=(",", ":"), sort_keys=True).encode()
        return document, payload
    payload = source.encode() if isinstance(source, str) else source
    try:
        document = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise BEANIPAArchiveError("BEA NIPA directory response is not valid JSON") from exc
    if not isinstance(document, dict):
        raise BEANIPAArchiveError("BEA NIPA directory response must be a JSON object")
    return document, payload


def _quarter_number(quarter: str) -> int:
    match = _QUARTER_RE.fullmatch(quarter)
    if match is None:
        raise ValueError(f"invalid quarter: {quarter!r}")
    return int(match.group("year")) * 4 + int(match.group("quarter")) - 1


def _quarter_from_number(value: int) -> str:
    year, zero_based_quarter = divmod(value, 4)
    return f"{year:04d}Q{zero_based_quarter + 1}"


def quarter_range(first: str, last: str) -> tuple[str, ...]:
    """Return an inclusive sequence of normalized calendar quarters."""

    start = _quarter_number(first)
    stop = _quarter_number(last)
    if stop < start:
        raise ValueError("last quarter cannot precede first quarter")
    return tuple(_quarter_from_number(value) for value in range(start, stop + 1))


def quarter_start(quarter: str) -> date:
    match = _QUARTER_RE.fullmatch(quarter)
    if match is None:
        raise ValueError(f"invalid quarter: {quarter!r}")
    return date(int(match.group("year")), (int(match.group("quarter")) - 1) * 3 + 1, 1)


def previous_quarter(quarter: str) -> str:
    return _quarter_from_number(_quarter_number(quarter) - 1)


def parse_bea_nipa_release_inventory(
    source: bytes | str | Mapping[str, object],
    *,
    expected_first_quarter: str = BEA_NIPA_EXPECTED_FIRST_QUARTER,
    expected_last_quarter: str = BEA_NIPA_EXPECTED_LAST_QUARTER,
) -> BEANIPAReleaseInventory:
    """Select top-level Advance/Initial directories without inventing paths."""

    document, payload = _json_document(source)
    if str(document.get("MainName")) != "National Accounts (NIPA)":
        raise BEANIPAArchiveError("BEA directory response is not the NIPA archive")
    description = str(document.get("DescriptionLong", ""))
    if "research only" not in description.lower() or "Microsoft Excel" not in description:
        raise BEANIPAArchiveError("BEA NIPA archive description/usage warning is absent")
    paths = document.get("FileArray")
    if not isinstance(paths, list) or not paths:
        raise BEANIPAArchiveError("BEA NIPA directory response contains no paths")

    expected = set(quarter_range(expected_first_quarter, expected_last_quarter))
    releases: dict[str, BEANIPARelease] = {}
    for raw_path in paths:
        if not isinstance(raw_path, str):
            raise BEANIPAArchiveError("BEA NIPA directory contains a non-string path")
        path_match = _RELEASE_PATH_RE.search(raw_path)
        if path_match is None:
            continue
        label = path_match.group("label")
        label_match = _RELEASE_LABEL_RE.fullmatch(label)
        if label_match is None:
            continue
        target_quarter = (
            f"{int(path_match.group('year')):04d}{path_match.group('quarter').upper()}"
        )
        if target_quarter not in expected:
            continue
        release = BEANIPARelease(
            target_quarter=target_quarter,
            release_type=label_match.group("release_type").title(),
            archive_directory_date=datetime.strptime(
                "{} {} {}".format(
                    label_match.group("month").title(),
                    label_match.group("day"),
                    label_match.group("year"),
                ),
                "%B %d %Y",
            ).date(),
            archive_directory_label=label,
            archive_path=raw_path,
        )
        if target_quarter in releases:
            raise BEANIPAArchiveError(
                f"multiple initial NIPA release directories for {target_quarter}"
            )
        releases[target_quarter] = release

    ordered = tuple(releases[quarter] for quarter in sorted(releases, key=_quarter_number))
    if not ordered:
        raise BEANIPAArchiveError("BEA NIPA inventory has no initial release directories")
    return BEANIPAReleaseInventory(
        releases=ordered,
        missing_quarters=tuple(sorted(expected - set(releases), key=_quarter_number)),
        expected_first_quarter=expected_first_quarter.upper(),
        expected_last_quarter=expected_last_quarter.upper(),
        source_sha256=_sha256_bytes(payload),
    )


def _file_inventory_url(release: BEANIPARelease) -> str:
    query = urlencode(
        {
            "HistMainId": "7",
            "thePath": release.archive_path,
            "getFiles": "true",
            "getDirs": "false",
        }
    )
    return f"{BEA_NIPA_FILE_INVENTORY_ENDPOINT}?{query}"


def _public_file_url(server_path: str) -> str:
    normalized = server_path.replace("\\", "/")
    if not normalized.startswith(f"{_SERVER_ROOT}/HistData/Files/Releases/GDP_and_PI/"):
        raise BEANIPAArchiveError(f"unexpected BEA NIPA server path: {server_path}")
    relative = normalized[len(_SERVER_ROOT) :]
    return f"{BEA_NIPA_PUBLIC_FILE_ROOT}{quote(relative, safe='/')}"


def select_bea_nipa_section1_file(
    source: bytes | str | Mapping[str, object],
    *,
    release: BEANIPARelease,
) -> tuple[str, str]:
    """Select the direct-child Section 1 workbook from a BEA file listing."""

    document, _ = _json_document(source)
    paths = document.get("FileArray")
    if not isinstance(paths, list):
        raise BEANIPAArchiveError(
            f"BEA file inventory is invalid for {release.target_quarter}"
        )
    prefix = f"{release.archive_path}\\"
    matches = [
        path
        for path in paths
        if isinstance(path, str)
        and path.startswith(prefix)
        and "\\" not in path[len(prefix) :]
        and _SECTION1_RE.fullmatch(path[len(prefix) :]) is not None
    ]
    if len(matches) != 1:
        raise BEANIPAArchiveError(
            f"{release.target_quarter} requires exactly one direct Section 1 workbook; "
            f"found {len(matches)}"
        )
    return matches[0], _public_file_url(matches[0])


def target_quarter_from_release_label(label: str) -> str:
    """Extract the GDP reference quarter from a verified news-release title."""

    match = _LABEL_QUARTER_RE.search(label)
    if match is None:
        raise BEANIPAArchiveError(f"GDP release label has no target quarter: {label!r}")
    token = match.group("quarter").lower()
    return f"{int(match.group('year')):04d}Q{_QUARTER_NUMBERS[token]}"


def load_bea_initial_release_clocks(
    clock_evidence_path: str | Path,
) -> tuple[dict[str, BEAReleaseClock], dict[str, Mapping[str, object]]]:
    """Map independently verified BEA clocks to reference quarters via page labels."""

    archive = parse_bea_gdp_clock_archive(clock_evidence_path)
    clocks: dict[str, BEAReleaseClock] = {}
    metadata: dict[str, Mapping[str, object]] = {}
    for release_date, clock in archive.clocks.items():
        event = archive.event_metadata[release_date]
        quarter = target_quarter_from_release_label(str(event["observation_label"]))
        if quarter in clocks:
            raise BEANIPAArchiveError(f"duplicate BEA initial release clock for {quarter}")
        clocks[quarter] = clock
        metadata[quarter] = event
    return clocks, metadata


def _metadata_text(rows: Mapping[int, Mapping[int, object]], pattern: re.Pattern[str]) -> str:
    for values in rows.values():
        for value in values.values():
            text = str(value).strip()
            if pattern.search(text):
                return text
    raise BEANIPAArchiveError(f"NIPA workbook is missing metadata matching {pattern.pattern}")


def _select_gdp_sheet(payload: bytes) -> str:
    names = _xlsx_sheet_names(payload)
    normalized = {re.sub(r"\s+", " ", name.strip()).upper(): name for name in names}
    for candidate in ("T10106-Q", "10106 QTR", "102 QTR"):
        if candidate in normalized:
            return normalized[candidate]
    raise BEANIPAArchiveError(
        "NIPA Section 1 workbook lacks a supported quarterly real-GDP table"
    )


def _parse_scale(units_text: str) -> str:
    lowered = units_text.lower()
    if "millions" in lowered:
        return "millions"
    if "billions" in lowered:
        return "billions"
    raise BEANIPAArchiveError(f"unsupported NIPA real-GDP scale: {units_text}")


def _quarter_headers(rows: Mapping[int, Mapping[int, object]]) -> dict[int, str]:
    combined: list[dict[int, str]] = []
    for values in rows.values():
        parsed = {
            column: match.group(0).upper()
            for column, value in values.items()
            if (match := _QUARTER_RE.fullmatch(str(value).strip())) is not None
        }
        if parsed:
            combined.append(parsed)
    if combined:
        return max(combined, key=len)

    for row_number, years in rows.items():
        parsed_years = {
            column: int(value)
            for column, value in years.items()
            if isinstance(value, (int, float))
            and float(value).is_integer()
            and 1900 <= int(value) <= 2200
        }
        if len(parsed_years) < 2:
            continue
        quarters = rows.get(row_number + 1, {})
        result = {
            column: f"{year:04d}Q{int(quarters[column])}"
            for column, year in parsed_years.items()
            if column in quarters
            and isinstance(quarters[column], (int, float))
            and float(quarters[column]).is_integer()
            and 1 <= int(quarters[column]) <= 4
        }
        if len(result) >= 2:
            return result
    raise BEANIPAArchiveError("NIPA real-GDP table has no supported quarterly header")


def convert_nipa_legacy_workbooks(
    payloads: Mapping[str, bytes],
) -> tuple[dict[str, bytes], str]:
    """Convert OLE XLS payloads in one isolated LibreOffice batch."""

    converted: dict[str, bytes] = {}
    legacy: dict[str, bytes] = {}
    for quarter, payload in payloads.items():
        if payload.startswith(b"PK"):
            converted[quarter] = payload
        elif payload.startswith(_OLE_SIGNATURE):
            legacy[quarter] = payload
        else:
            raise BEANIPAArchiveError(f"{quarter} Section 1 is neither XLS nor XLSX")
    if not legacy:
        return converted, "not_required"
    executable = shutil.which("soffice")
    if executable is None:
        raise BEANIPAArchiveError(
            "legacy BEA NIPA XLS parsing requires LibreOffice 'soffice'"
        )
    with tempfile.TemporaryDirectory(prefix="macro-nowcast-bea-nipa-") as temporary:
        root = Path(temporary)
        inputs = root / "input"
        outputs = root / "output"
        inputs.mkdir()
        outputs.mkdir()
        sources: list[Path] = []
        for quarter, payload in sorted(legacy.items()):
            path = inputs / f"bea-nipa-{quarter}.xls"
            path.write_bytes(payload)
            sources.append(path)
        completed = subprocess.run(
            [
                executable,
                f"-env:UserInstallation={(root / 'profile').as_uri()}",
                "--headless",
                "--convert-to",
                "xlsx",
                "--outdir",
                str(outputs),
                *(str(path) for path in sources),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=600,
        )
        if completed.returncode != 0:
            message = completed.stderr.strip() or completed.stdout.strip()
            raise BEANIPAArchiveError(f"legacy BEA NIPA XLS conversion failed: {message}")
        for quarter in sorted(legacy):
            path = outputs / f"bea-nipa-{quarter}.xlsx"
            if not path.exists():
                raise BEANIPAArchiveError(
                    f"legacy BEA NIPA XLS conversion missing output: {quarter}"
                )
            converted[quarter] = path.read_bytes()
    return converted, Path(executable).name


def parse_real_gdp_level_snapshot(
    payload: bytes,
    *,
    target_quarter: str,
    release_date: date,
    release_timestamp: datetime,
    release_type: str,
) -> BEANIPALevelSnapshot:
    """Parse one legacy or modern Section 1 workbook without era assumptions."""

    converted, _ = convert_nipa_legacy_workbooks({target_quarter: payload})
    workbook = converted[target_quarter]
    sheet = _select_gdp_sheet(workbook)
    rows = _xlsx_rows(workbook, sheet)
    title = str(rows.get(1, {}).get(1, "")).strip()
    if "Real Gross Domestic Product" not in title:
        raise BEANIPAArchiveError(f"{target_quarter} selected table is not real GDP")
    units_text = str(rows.get(2, {}).get(1, "")).strip()
    base_match = _BASE_YEAR_RE.search(units_text)
    if base_match is None:
        raise BEANIPAArchiveError(
            f"{target_quarter} real-GDP table has no chained-dollar reference year"
        )
    published_text = _metadata_text(rows, _PUBLISHED_RE)
    published_match = _PUBLISHED_RE.search(published_text)
    assert published_match is not None
    published_date = datetime.strptime(
        "{} {} {}".format(
            published_match.group("month")[:3].title(),
            published_match.group("day"),
            published_match.group("year"),
        ),
        "%b %d %Y",
    ).date()
    if published_date != release_date:
        raise BEANIPAArchiveError(
            f"{target_quarter} workbook publication date {published_date} "
            f"disagrees with verified release date {release_date}"
        )
    if release_timestamp.tzinfo is None or release_timestamp.utcoffset() is None:
        raise BEANIPAArchiveError("BEA release timestamp must be timezone-aware")
    if release_timestamp.astimezone(UTC).date() != release_date:
        raise BEANIPAArchiveError("BEA release timestamp date disagrees with release date")

    matches = [
        (row_number, values)
        for row_number, values in rows.items()
        if any(_GDP_CODE_RE.fullmatch(str(value).strip()) for value in values.values())
        and any(
            str(value).strip().lower() == "gross domestic product"
            for value in values.values()
        )
    ]
    if len(matches) != 1:
        raise BEANIPAArchiveError(
            f"{target_quarter} requires exactly one A191RX GDP row; found {len(matches)}"
        )
    _, gdp_row = matches[0]
    series_code = next(
        str(value).strip()
        for value in gdp_row.values()
        if _GDP_CODE_RE.fullmatch(str(value).strip())
    )
    headers = _quarter_headers(rows)
    levels: list[tuple[date, float]] = []
    for column, quarter in sorted(headers.items(), key=lambda item: _quarter_number(item[1])):
        raw = gdp_row.get(column)
        if raw is None or str(raw).strip() in {"", ".", ".....", "--"}:
            continue
        try:
            value = float(str(raw).strip().replace(",", ""))
        except (TypeError, ValueError) as exc:
            raise BEANIPAArchiveError(
                f"{target_quarter} has invalid GDP level for {quarter}: {raw!r}"
            ) from exc
        if not math.isfinite(value) or value <= 0:
            raise BEANIPAArchiveError(
                f"{target_quarter} has nonpositive/nonfinite GDP level for {quarter}"
            )
        if _quarter_number(quarter) > _quarter_number(target_quarter):
            raise BEANIPAArchiveError(
                f"{target_quarter} snapshot contains future quarter {quarter}"
            )
        levels.append((quarter_start(quarter), value))
    if not levels:
        raise BEANIPAArchiveError(f"{target_quarter} snapshot has no real-GDP levels")
    if levels[-1][0] != quarter_start(target_quarter):
        raise BEANIPAArchiveError(
            f"{target_quarter} snapshot ends at {levels[-1][0]} instead of its target quarter"
        )
    snapshot = BEANIPALevelSnapshot(
        target_quarter=target_quarter,
        release_date=release_date,
        release_timestamp=release_timestamp.astimezone(UTC),
        release_type=release_type,
        published_date=published_date,
        sheet_name=sheet,
        table_title=title,
        series_code=series_code,
        units_text=units_text,
        scale=_parse_scale(units_text),
        chained_dollar_reference_year=int(base_match.group(1)),
        levels=tuple(levels),
    )
    _ = snapshot.prior_level
    return snapshot


def _manifest(root: Path) -> tuple[dict[str, object], list[Mapping[str, object]]]:
    try:
        document = json.loads((root / "release-index.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BEANIPAArchiveError("BEA NIPA release-index.json is missing or invalid") from exc
    if document.get("schema_version") != 1:
        raise BEANIPAArchiveError("unsupported BEA NIPA manifest schema")
    entries = document.get("releases")
    if not isinstance(entries, list) or not entries:
        raise BEANIPAArchiveError("BEA NIPA manifest has no releases")
    if any(not isinstance(entry, Mapping) for entry in entries):
        raise BEANIPAArchiveError("BEA NIPA manifest contains an invalid release")
    return document, entries  # type: ignore[return-value]


def _entry_quarter(entry: Mapping[str, object]) -> str:
    quarter = str(entry.get("target_quarter", ""))
    _quarter_number(quarter)
    expected_prefix = f"snapshots/{quarter}/"
    if not str(entry.get("path", "")).startswith(expected_prefix):
        raise BEANIPAArchiveError(f"manifest path mismatch for {quarter}")
    return quarter


def _read_archive_payloads(
    root: Path,
    entries: Sequence[Mapping[str, object]],
) -> dict[str, bytes]:
    payloads: dict[str, bytes] = {}
    expected_paths: set[Path] = set()
    for entry in entries:
        quarter = _entry_quarter(entry)
        if quarter in payloads:
            raise BEANIPAArchiveError(f"duplicate BEA NIPA manifest quarter: {quarter}")
        path = (root / str(entry["path"])).resolve()
        expected_paths.add(path)
        payload = path.read_bytes()
        if len(payload) != int(entry.get("bytes", -1)):
            raise BEANIPAArchiveError(f"BEA NIPA byte-count mismatch for {quarter}")
        if _sha256_bytes(payload) != str(entry.get("sha256")):
            raise BEANIPAArchiveError(f"BEA NIPA hash mismatch for {quarter}")
        payloads[quarter] = payload
    actual_paths = {
        path.resolve()
        for path in (root / "snapshots").glob("*/*")
        if path.is_file()
    }
    if actual_paths != expected_paths:
        raise BEANIPAArchiveError("local BEA NIPA workbook inventory differs from manifest")
    return payloads


def parse_bea_nipa_level_archive(
    directory: str | Path,
    *,
    clock_evidence_path: str | Path,
) -> tuple[list[BEANIPALevelSnapshot], list[VintageObservation]]:
    """Verify hashes and parse all manifest-pinned NIPA snapshots offline."""

    root = Path(directory).resolve()
    manifest, entries = _manifest(root)
    clocks, clock_metadata = load_bea_initial_release_clocks(clock_evidence_path)
    payloads = _read_archive_payloads(root, entries)
    converted, conversion_tool = convert_nipa_legacy_workbooks(payloads)
    snapshots: list[BEANIPALevelSnapshot] = []
    raw_rows: list[dict[str, object]] = []
    for entry in sorted(entries, key=lambda item: _quarter_number(_entry_quarter(item))):
        quarter = _entry_quarter(entry)
        clock = clocks.get(quarter)
        if clock is None:
            raise BEANIPAArchiveError(f"no verified BEA release clock for {quarter}")
        event = clock_metadata[quarter]
        release_type = str(entry.get("release_type"))
        if event.get("source_release_type") != release_type:
            raise BEANIPAArchiveError(f"BEA release-type mismatch for {quarter}")
        if str(entry.get("verified_release_date")) != clock.release_date.isoformat():
            raise BEANIPAArchiveError(f"BEA verified release-date drift for {quarter}")
        if str(entry.get("release_timestamp")) != clock.release_timestamp.isoformat():
            raise BEANIPAArchiveError(f"BEA verified release-clock drift for {quarter}")
        snapshot = parse_real_gdp_level_snapshot(
            converted[quarter],
            target_quarter=quarter,
            release_date=clock.release_date,
            release_timestamp=clock.release_timestamp,
            release_type=release_type,
        )
        snapshots.append(snapshot)
        downloaded_at = datetime.fromisoformat(str(entry["retrieved_at"]))
        units = (
            f"{snapshot.scale}_of_chained_{snapshot.chained_dollar_reference_year}_"
            "dollars_saar"
        )
        for observation_date, value in snapshot.levels:
            raw_rows.append(
                {
                    "series_id": BEA_NIPA_LEVEL_SERIES_ID,
                    "observation_date": observation_date,
                    "realtime_start": clock.release_date,
                    "availability_date": clock.release_date,
                    "release_timestamp": clock.release_timestamp,
                    "availability_timestamp": clock.release_timestamp,
                    "value": value,
                    "units": units,
                    "frequency": "quarterly",
                    "seasonal_adjustment": "seasonally_adjusted_annual_rate",
                    "transformation": "level",
                    "download_timestamp": downloaded_at,
                    "source": BEA_NIPA_LEVEL_SOURCE,
                    "provenance_label": BEA_NIPA_LEVEL_PROVENANCE,
                    "source_metadata": {
                        "agency_series_id": snapshot.series_code,
                        "agency_series_family": "A191RX",
                        "source_file": str(entry["path"]),
                        "source_sha256": str(entry["sha256"]),
                        "official_url": str(entry["url"]),
                        "target_quarter": quarter,
                        "release_type": "initial",
                        "source_release_type": release_type,
                        "verified_release_date": clock.release_date.isoformat(),
                        "archive_directory_date": str(entry["archive_directory_date"]),
                        "archive_directory_date_matches_release": bool(
                            entry["archive_directory_date_matches_release"]
                        ),
                        "sheet": snapshot.sheet_name,
                        "table_title": snapshot.table_title,
                        "source_units_text": snapshot.units_text,
                        "source_scale": snapshot.scale,
                        "chained_dollar_reference_year": (
                            snapshot.chained_dollar_reference_year
                        ),
                        "timing_quality": BEA_GDP_CLOCK_TIMING_QUALITY,
                        "printed_release_timezone": clock.printed_timezone,
                        "legacy_conversion_tool": conversion_tool,
                        "same_snapshot_adjacent_level_ratio_supported": True,
                        "cross_vintage_raw_level_comparison_supported": False,
                        "base_and_scale_changes_preserved": True,
                    },
                }
            )

    grouped: dict[date, list[dict[str, object]]] = defaultdict(list)
    for row in raw_rows:
        grouped[row["observation_date"]].append(row)  # type: ignore[index]
    observations: list[VintageObservation] = []
    for rows in grouped.values():
        rows.sort(key=lambda row: row["realtime_start"])  # type: ignore[arg-type,return-value]
        starts = [row["realtime_start"] for row in rows]
        if len(starts) != len(set(starts)):
            raise BEANIPAArchiveError("duplicate NIPA vintage date for one observation")
        for index, row in enumerate(rows):
            if index + 1 < len(rows):
                next_start = rows[index + 1]["realtime_start"]
                assert isinstance(next_start, date)
                row["realtime_end"] = next_start - timedelta(days=1)
            observations.append(VintageObservation.from_mapping(row))
    observations.sort(key=lambda row: (row.observation_date, row.realtime_start))
    if manifest.get("conversion_policy") != "legacy_xls_converted_in_temporary_directory":
        raise BEANIPAArchiveError("BEA NIPA manifest conversion policy drifted")
    return snapshots, observations


def _initial_growth_by_quarter(
    path: str | Path,
    *,
    clocks: Mapping[str, BEAReleaseClock],
) -> dict[str, float]:
    from macro_nowcast.archive_ingestion import parse_gdp_vintage_history

    by_date = {clock.release_date: clock for clock in clocks.values()}
    rows = parse_gdp_vintage_history(path, release_clocks=by_date)
    result: dict[str, float] = {}
    for row in rows:
        if row.source_metadata.get("release_type") != "initial":
            continue
        quarter = f"{row.observation_date.year:04d}Q{(row.observation_date.month - 1) // 3 + 1}"
        if row.value is None:
            raise BEANIPAArchiveError(f"published initial GDP growth is null for {quarter}")
        result[quarter] = row.value
    return result


def audit_bea_nipa_level_archive(
    directory: str | Path,
    *,
    clock_evidence_path: str | Path,
    published_growth_path: str | Path | None = None,
) -> dict[str, object]:
    """Audit coverage, raw evidence, clocks, workbook content, and target ratios."""

    root = Path(directory).resolve()
    manifest, entries = _manifest(root)
    first = str(manifest.get("expected_first_quarter"))
    last = str(manifest.get("expected_last_quarter"))
    expected = set(quarter_range(first, last))
    quarters = {_entry_quarter(entry) for entry in entries}
    missing = sorted(expected - quarters, key=_quarter_number)
    if missing != list(manifest.get("missing_quarters", [])):
        raise BEANIPAArchiveError("BEA NIPA manifest missing-quarter inventory drifted")
    if set(manifest.get("documented_archive_gaps", [])) != set(missing):
        raise BEANIPAArchiveError("BEA NIPA archive gaps are not explicitly documented")
    if manifest.get("status") != "verified_with_archive_gaps":
        raise BEANIPAArchiveError("BEA NIPA manifest must remain gap-labeled")

    inventory_entry = manifest.get("source_inventory")
    if not isinstance(inventory_entry, Mapping):
        raise BEANIPAArchiveError("BEA NIPA manifest has no source inventory")
    inventory_path = root / str(inventory_entry["path"])
    inventory_payload = inventory_path.read_bytes()
    if _sha256_bytes(inventory_payload) != str(inventory_entry["sha256"]):
        raise BEANIPAArchiveError("BEA NIPA source-inventory hash mismatch")
    parsed_inventory = parse_bea_nipa_release_inventory(
        inventory_payload,
        expected_first_quarter=first,
        expected_last_quarter=last,
    )
    if {release.target_quarter for release in parsed_inventory.releases} != quarters:
        raise BEANIPAArchiveError("BEA NIPA source and manifest release inventories differ")

    for entry in entries:
        quarter = _entry_quarter(entry)
        file_list_path = root / str(entry["file_inventory_path"])
        file_list_payload = file_list_path.read_bytes()
        if _sha256_bytes(file_list_payload) != str(entry["file_inventory_sha256"]):
            raise BEANIPAArchiveError(f"BEA file-inventory hash mismatch for {quarter}")
        release = next(
            item for item in parsed_inventory.releases if item.target_quarter == quarter
        )
        server_path, url = select_bea_nipa_section1_file(
            file_list_payload,
            release=release,
        )
        if server_path != entry["server_path"] or url != entry["url"]:
            raise BEANIPAArchiveError(f"BEA selected file drift for {quarter}")

    snapshots, observations = parse_bea_nipa_level_archive(
        root,
        clock_evidence_path=clock_evidence_path,
    )
    clocks, _ = load_bea_initial_release_clocks(clock_evidence_path)
    reconciled = 0
    exact_rounded_reconciled = 0
    reconciliation_differences: list[float] = []
    discrepancies: list[dict[str, object]] = []
    if published_growth_path is not None:
        published = _initial_growth_by_quarter(published_growth_path, clocks=clocks)
        for snapshot in snapshots:
            expected_growth = published.get(snapshot.target_quarter)
            if expected_growth is None:
                raise BEANIPAArchiveError(
                    f"published GDP history is missing {snapshot.target_quarter}"
                )
            calculated = snapshot.qoq_saar_percent
            difference = abs(calculated - expected_growth)
            reconciliation_differences.append(difference)
            exact_rounded = math.isclose(
                round(calculated, 1),
                expected_growth,
                abs_tol=1e-12,
            )
            passed = difference <= 0.06
            if not passed:
                discrepancies.append(
                    {
                        "target_quarter": snapshot.target_quarter,
                        "calculated_qoq_saar_percent": calculated,
                        "published_qoq_saar_percent": expected_growth,
                    }
                )
            else:
                reconciled += 1
                exact_rounded_reconciled += int(exact_rounded)
        if discrepancies:
            raise BEANIPAArchiveError(
                "NIPA level-derived growth does not reconcile to published initial growth: "
                f"{discrepancies[:3]}"
            )

    formats: dict[str, int] = defaultdict(int)
    directory_date_conflicts: dict[str, dict[str, str]] = {}
    for entry in entries:
        formats[str(entry["file_format"])] += 1
        if not bool(entry["archive_directory_date_matches_release"]):
            directory_date_conflicts[_entry_quarter(entry)] = {
                "archive_directory_date": str(entry["archive_directory_date"]),
                "verified_release_date": str(entry["verified_release_date"]),
            }
    base_years = sorted({snapshot.chained_dollar_reference_year for snapshot in snapshots})
    scales = sorted({snapshot.scale for snapshot in snapshots})
    return {
        "passed": True,
        "status": "verified_with_archive_gaps",
        "official_url": BEA_NIPA_ARCHIVE_INDEX_URL,
        "directory": root.name,
        "expected_release_count": len(expected),
        "snapshot_count": len(snapshots),
        "coverage_ratio": len(snapshots) / len(expected),
        "first_expected_quarter": first,
        "last_expected_quarter": last,
        "first_available_quarter": snapshots[0].target_quarter,
        "last_available_quarter": snapshots[-1].target_quarter,
        "missing_quarters": missing,
        "file_format_counts": dict(sorted(formats.items())),
        "canonical_vintage_rows": len(observations),
        "all_target_and_prior_levels_present": True,
        "all_workbook_publication_dates_match_verified_clocks": True,
        "release_clock_count": len(snapshots),
        "directory_date_conflict_count": len(directory_date_conflicts),
        "directory_date_conflicts": directory_date_conflicts,
        "chained_dollar_reference_years": base_years,
        "source_scales": scales,
        "cross_vintage_raw_level_comparison_supported": False,
        "same_snapshot_adjacent_level_growth_supported": True,
        "published_growth_reconciliation_requested": published_growth_path is not None,
        "published_growth_reconciliation_count": reconciled,
        "published_growth_exact_rounded_count": (
            exact_rounded_reconciled if published_growth_path is not None else None
        ),
        "published_growth_reconciliation_tolerance_pp": (
            0.06 if published_growth_path is not None else None
        ),
        "maximum_abs_reconciliation_difference_pp": (
            max(reconciliation_differences)
            if reconciliation_differences
            else None
        ),
        "all_level_derived_growth_within_006pp_of_published_initial_growth": (
            reconciled == len(snapshots) if published_growth_path is not None else None
        ),
        "api_credentials_used": False,
        "api_txt_read": False,
        "server_original_workbook_bytes_claimed": True,
        "provenance_status": (
            "official_directory_file_lists_workbook_hashes_levels_and_clocks_verified_"
            "with_two_prearchive_quarter_gaps"
        ),
    }


def _fetch(url: str, *, attempts: int = 5) -> tuple[bytes, str]:
    for attempt in range(attempts):
        request = Request(url, headers={"User-Agent": _USER_AGENT})
        try:
            with urlopen(request, timeout=90) as response:
                return response.read(), response.headers.get_content_type()
        except HTTPError as exc:
            if exc.code not in {429, 500, 502, 503, 504} or attempt == attempts - 1:
                raise BEANIPAArchiveError(f"BEA NIPA request failed: {url} ({exc.code})") from exc
            retry_after = exc.headers.get("Retry-After")
            delay = float(retry_after) if retry_after and retry_after.isdigit() else 2**attempt
        except (TimeoutError, URLError) as exc:
            if attempt == attempts - 1:
                raise BEANIPAArchiveError(f"BEA NIPA request failed: {url}") from exc
            delay = 2**attempt
        time.sleep(min(delay, 16))
    raise AssertionError("unreachable")


def _write_immutable(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise BEANIPAArchiveError(f"refusing to replace immutable NIPA evidence: {path}")
        return
    temporary = path.with_suffix(f"{path.suffix}.part")
    temporary.write_bytes(payload)
    temporary.replace(path)


def _acquire_release(
    root: Path,
    release: BEANIPARelease,
    *,
    clock: BEAReleaseClock,
    clock_metadata: Mapping[str, object],
) -> dict[str, object]:
    file_inventory_url = _file_inventory_url(release)
    file_inventory, file_inventory_content_type = _fetch(file_inventory_url)
    server_path, url = select_bea_nipa_section1_file(file_inventory, release=release)
    filename = server_path.replace("\\", "/").rsplit("/", 1)[-1]
    file_inventory_path = root / "file-lists" / f"{release.target_quarter}.json"
    output_path = root / "snapshots" / release.target_quarter / filename
    _write_immutable(file_inventory_path, file_inventory)
    if output_path.exists():
        payload = output_path.read_bytes()
        content_type = "application/octet-stream"
    else:
        payload, content_type = _fetch(url)
        _write_immutable(output_path, payload)
    if payload.startswith(b"PK"):
        file_format = "xlsx"
        _xlsx_sheet_names(payload)
    elif payload.startswith(_OLE_SIGNATURE):
        file_format = "xls"
    else:
        raise BEANIPAArchiveError(
            f"{release.target_quarter} Section 1 response is not an Excel workbook"
        )
    retrieved_at = datetime.now(UTC)
    return {
        "target_quarter": release.target_quarter,
        "release_type": release.release_type,
        "archive_path": release.archive_path,
        "archive_directory_label": release.archive_directory_label,
        "archive_directory_date": release.archive_directory_date.isoformat(),
        "archive_directory_date_matches_release": (
            release.archive_directory_date == clock.release_date
        ),
        "verified_release_date": clock.release_date.isoformat(),
        "release_timestamp": clock.release_timestamp.isoformat(),
        "clock_timing_quality": clock.timing_quality,
        "clock_evidence_url": str(clock_metadata["official_url"]),
        "file_inventory_url": file_inventory_url,
        "file_inventory_content_type": file_inventory_content_type,
        "file_inventory_path": file_inventory_path.relative_to(root).as_posix(),
        "file_inventory_sha256": _sha256_bytes(file_inventory),
        "server_path": server_path,
        "url": url,
        "content_type": content_type,
        "path": output_path.relative_to(root).as_posix(),
        "file_format": file_format,
        "bytes": len(payload),
        "sha256": _sha256_bytes(payload),
        "retrieved_at": retrieved_at.isoformat(),
    }


def acquire_bea_nipa_level_archive(
    output_dir: str | Path,
    *,
    clock_evidence_path: str | Path,
    published_growth_path: str | Path | None = None,
    expected_first_quarter: str = BEA_NIPA_EXPECTED_FIRST_QUARTER,
    expected_last_quarter: str = BEA_NIPA_EXPECTED_LAST_QUARTER,
    workers: int = 4,
) -> dict[str, object]:
    """Acquire all available initial-release Section 1 workbooks and audit them."""

    if workers < 1 or workers > 8:
        raise ValueError("workers must be between 1 and 8")
    root = Path(output_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    existing_manifest_path = root / "release-index.json"
    if existing_manifest_path.exists():
        existing_manifest = json.loads(existing_manifest_path.read_text(encoding="utf-8"))
        existing_window = (
            existing_manifest.get("expected_first_quarter"),
            existing_manifest.get("expected_last_quarter"),
        )
        requested_window = (expected_first_quarter, expected_last_quarter)
        if existing_window != requested_window:
            raise BEANIPAArchiveError(
                "existing BEA NIPA archive window differs from the requested window: "
                f"existing={existing_window}, requested={requested_window}"
            )
        audit = audit_bea_nipa_level_archive(
            root,
            clock_evidence_path=clock_evidence_path,
            published_growth_path=published_growth_path,
        )
        return {
            "status": audit["status"],
            "output_dir": str(root),
            "expected_release_count": audit["expected_release_count"],
            "snapshot_count": audit["snapshot_count"],
            "missing_quarters": audit["missing_quarters"],
            "canonical_vintage_rows": audit["canonical_vintage_rows"],
            "published_growth_reconciliation_count": audit[
                "published_growth_reconciliation_count"
            ],
            "network_used": False,
            "api_credentials_used": False,
            "api_txt_read": False,
        }
    inventory_payload, inventory_content_type = _fetch(BEA_NIPA_RELEASE_INVENTORY_URL)
    inventory = parse_bea_nipa_release_inventory(
        inventory_payload,
        expected_first_quarter=expected_first_quarter,
        expected_last_quarter=expected_last_quarter,
    )
    inventory_filename = f"source-inventory-{inventory.source_sha256[:16]}.json"
    inventory_path = root / inventory_filename
    _write_immutable(inventory_path, inventory_payload)
    clocks, clock_metadata = load_bea_initial_release_clocks(clock_evidence_path)
    expected = set(quarter_range(expected_first_quarter, expected_last_quarter))
    if set(clocks) != expected:
        missing_clocks = sorted(expected - set(clocks), key=_quarter_number)
        extra_clocks = sorted(set(clocks) - expected, key=_quarter_number)
        raise BEANIPAArchiveError(
            f"BEA clock coverage differs from requested NIPA window: "
            f"missing={missing_clocks[:3]}, extra={extra_clocks[:3]}"
        )
    entries: list[dict[str, object]] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                _acquire_release,
                root,
                release,
                clock=clocks[release.target_quarter],
                clock_metadata=clock_metadata[release.target_quarter],
            ): release.target_quarter
            for release in inventory.releases
        }
        for future in as_completed(futures):
            entries.append(future.result())
    entries.sort(key=lambda entry: _quarter_number(str(entry["target_quarter"])))

    expected_missing = list(BEA_NIPA_DOCUMENTED_MISSING_QUARTERS)
    if (
        expected_first_quarter == BEA_NIPA_EXPECTED_FIRST_QUARTER
        and expected_last_quarter == BEA_NIPA_EXPECTED_LAST_QUARTER
        and list(inventory.missing_quarters) != expected_missing
    ):
        raise BEANIPAArchiveError(
            "BEA NIPA archive coverage changed; review gaps before updating the manifest"
        )
    manifest = {
        "schema_version": 1,
        "status": "verified_with_archive_gaps",
        "source": BEA_NIPA_LEVEL_SOURCE,
        "source_index_url": BEA_NIPA_ARCHIVE_INDEX_URL,
        "source_inventory_url": BEA_NIPA_RELEASE_INVENTORY_URL,
        "acquired_at": datetime.now(UTC).isoformat(),
        "expected_first_quarter": inventory.expected_first_quarter,
        "expected_last_quarter": inventory.expected_last_quarter,
        "expected_release_count": len(expected),
        "downloaded_release_count": len(entries),
        "missing_quarters": list(inventory.missing_quarters),
        "documented_archive_gaps": list(inventory.missing_quarters),
        "gap_policy": "remain_missing_never_impute_or_substitute_current_api_values",
        "target_semantics": "same_snapshot_adjacent_level_qoq_saar_only",
        "cross_vintage_raw_level_comparison_supported": False,
        "conversion_policy": "legacy_xls_converted_in_temporary_directory",
        "source_inventory": {
            "url": BEA_NIPA_RELEASE_INVENTORY_URL,
            "content_type": inventory_content_type,
            "path": inventory_path.relative_to(root).as_posix(),
            "bytes": len(inventory_payload),
            "sha256": inventory.source_sha256,
        },
        "clock_evidence_sha256": _sha256_bytes(Path(clock_evidence_path).read_bytes()),
        "published_growth_cross_check_requested": published_growth_path is not None,
        "api_credentials_used": False,
        "api_txt_read": False,
        "releases": entries,
    }
    manifest_path = existing_manifest_path
    payload = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    if manifest_path.exists():
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        comparable_existing = dict(existing)
        comparable_existing.pop("acquired_at", None)
        comparable_new = dict(manifest)
        comparable_new.pop("acquired_at", None)
        for entry in comparable_existing.get("releases", []):
            if isinstance(entry, dict):
                entry.pop("retrieved_at", None)
        for entry in comparable_new["releases"]:
            entry.pop("retrieved_at", None)
        if comparable_existing != comparable_new:
            raise BEANIPAArchiveError(
                "refusing to replace BEA NIPA manifest with changed immutable inputs"
            )
    else:
        _write_immutable(manifest_path, payload)
    audit = audit_bea_nipa_level_archive(
        root,
        clock_evidence_path=clock_evidence_path,
        published_growth_path=published_growth_path,
    )
    return {
        "status": audit["status"],
        "output_dir": str(root),
        "expected_release_count": audit["expected_release_count"],
        "snapshot_count": audit["snapshot_count"],
        "missing_quarters": audit["missing_quarters"],
        "canonical_vintage_rows": audit["canonical_vintage_rows"],
        "published_growth_reconciliation_count": audit[
            "published_growth_reconciliation_count"
        ],
        "network_used": True,
        "api_credentials_used": False,
        "api_txt_read": False,
    }


__all__ = [
    "BEA_NIPA_ARCHIVE_INDEX_URL",
    "BEA_NIPA_DOCUMENTED_MISSING_QUARTERS",
    "BEA_NIPA_EXPECTED_FIRST_QUARTER",
    "BEA_NIPA_EXPECTED_LAST_QUARTER",
    "BEA_NIPA_FILE_INVENTORY_ENDPOINT",
    "BEA_NIPA_LEVEL_DIRECTORY",
    "BEA_NIPA_LEVEL_PROVENANCE",
    "BEA_NIPA_LEVEL_SERIES_ID",
    "BEA_NIPA_LEVEL_SOURCE",
    "BEA_NIPA_RELEASE_INVENTORY_URL",
    "BEANIPAArchiveError",
    "BEANIPALevelSnapshot",
    "BEANIPARelease",
    "BEANIPAReleaseInventory",
    "acquire_bea_nipa_level_archive",
    "audit_bea_nipa_level_archive",
    "convert_nipa_legacy_workbooks",
    "load_bea_initial_release_clocks",
    "parse_bea_nipa_level_archive",
    "parse_bea_nipa_release_inventory",
    "parse_real_gdp_level_snapshot",
    "previous_quarter",
    "quarter_range",
    "quarter_start",
    "select_bea_nipa_section1_file",
    "target_quarter_from_release_label",
]
