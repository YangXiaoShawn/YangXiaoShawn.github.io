"""Acquire, audit, and parse Census MARTS publication vintages.

The Census Bureau's Advance Monthly Retail Trade Survey archive exposes one
dated PDF for each reference month.  The PDFs preserve the release header,
advance total retail-and-food-services sales, and the directly published
month-over-month percent change.  This module never substitutes the mutable
current time series for those publication snapshots.
"""

from __future__ import annotations

import hashlib
import io
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
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from pypdf import PdfReader

from macro_nowcast.schema import VintageObservation

CENSUS_RETAIL_LEVEL_SERIES_ID: Final = "CENSUS_MARTS_RETAIL_FOOD_SERVICES_SA"
CENSUS_RETAIL_MOM_SERIES_ID: Final = "CENSUS_MARTS_RETAIL_FOOD_SERVICES_MOM_PCT"
CENSUS_RETAIL_SOURCE: Final = "CENSUS_MARTS_RELEASE_ARCHIVE"
CENSUS_RETAIL_PROVENANCE: Final = "official_agency_archive"
CENSUS_RETAIL_DIRECTORY: Final = "census-marts"
CENSUS_RETAIL_INDEX_URL: Final = (
    "https://www.census.gov/retail/marts/historic_releases.html"
)
CENSUS_RETAIL_SCHEDULE_URL: Final = "https://www.census.gov/retail/release_schedule.html"
CENSUS_RETAIL_CITATION_URL: Final = (
    "https://www.census.gov/about/policies/citation.html"
)
CENSUS_RETAIL_TIMING_QUALITY: Final = "official_header_clock_America_New_York"

_BASE_URL: Final = "https://www2.census.gov/retail/releases/historical/marts/"
_USER_AGENT: Final = "macro-nowcast-research/0.1 (public archive verification)"
_NEW_YORK: Final = ZoneInfo("America/New_York")
_PDF_HREF_RE = re.compile(r"(?:^|/)adv(?P<year>\d{2})(?P<month>\d{2})\.pdf$", re.I)
_MONTH_PATTERN = (
    r"Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|"
    r"Aug(?:ust)?|Sept?(?:ember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?"
)
_DATE_RE = re.compile(
    rf"(?P<month>{_MONTH_PATTERN})\.?\s+(?P<day>\d{{1,2}}),\s+(?P<year>\d{{4}})",
    re.I,
)
_TIME_RE = re.compile(
    r"(?P<hour>\d{1,2}):(?P<minute>\d{2})\s*"
    r"(?P<ampm>A\.?M\.?|P\.?M\.?)\s*(?P<zone>EDT|EST|ET)\b",
    re.I,
)
_TITLE_RE = re.compile(
    rf"ADVANCE\s+MONTHLY\s+SALES\s+FOR\s+RETAIL(?:\s+TRADE)?\s+AND\s+"
    rf"FOOD\s+SERVICES[,]?\s+(?P<month>{_MONTH_PATTERN})\.?\s+(?P<year>\d{{4}})",
    re.I,
)
_NARRATIVE_RE = re.compile(
    r"advance\s+estimates\s+of\s+U\.?S\.?\s+retail(?:\s+trade)?\s+and\s+"
    r"food\s+services\s+sales\s+for\s+[^,]+,.*?were\s+\$\s*"
    r"(?P<level>\d[\d,.\s]*?)\s+billion,\s+"
    r"(?:(?:an?|the)\s+)?(?P<direction>increase|decrease|rise|decline)\s+of\s+"
    r"(?P<change>\d+(?:\.\d+)?)\s*(?:percent|%)"
    r"|advance\s+estimates\s+of\s+U\.?S\.?\s+retail(?:\s+trade)?\s+and\s+"
    r"food\s+services\s+sales\s+for\s+[^,]+,.*?were\s+\$\s*"
    r"(?P<level_short>\d[\d,.\s]*?)\s+billion,\s+"
    r"(?P<direction_short>up|down)\s+(?P<change_short>\d+(?:\.\d+)?)\s*"
    r"(?:percent|%)",
    re.I,
)
_UNCHANGED_RE = re.compile(
    r"advance\s+estimates\s+of\s+U\.?S\.?\s+retail(?:\s+trade)?\s+and\s+"
    r"food\s+services\s+sales\s+for\s+[^,]+,.*?were\s+\$\s*"
    r"(?P<level>\d[\d,.\s]*?)\s+billion,\s+(?:virtually\s+)?unchanged\b",
    re.I,
)

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


class CensusRetailArchiveError(RuntimeError):
    """Raised when Census MARTS content cannot be used without guessing."""


@dataclass(frozen=True, slots=True)
class CensusRetailRelease:
    """One reference-month PDF enumerated by the official historical index."""

    observation_date: date
    href: str

    @property
    def official_url(self) -> str:
        return urljoin(_BASE_URL, self.href)

    @property
    def relative_path(self) -> Path:
        return Path("releases") / Path(urlparse(self.official_url).path).name


@dataclass(frozen=True, slots=True)
class CensusRetailReleaseValues:
    """Published identity and total-sales estimates from one MARTS PDF."""

    observation_date: date
    release_date: date
    release_timestamp: datetime
    release_zone_label: str
    sales_level_billions: float
    percent_change_mom: float
    extraction_pattern: str = "advance_estimate_narrative"


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


def _filename_observation_date(href: str) -> date:
    match = _PDF_HREF_RE.search(urlparse(href).path)
    if match is None:
        raise CensusRetailArchiveError(f"invalid MARTS release link: {href}")
    short_year = int(match.group("year"))
    current_short_year = datetime.now(UTC).year % 100
    year = 2000 + short_year if short_year <= current_short_year else 1900 + short_year
    return date(year, int(match.group("month")), 1)


def parse_census_retail_archive_index(
    document: str | bytes,
) -> list[CensusRetailRelease]:
    """Return unique official MARTS PDF links in reference-month order."""

    if isinstance(document, bytes):
        document = document.decode("utf-8-sig", errors="replace")
    parser = _LinkParser()
    parser.feed(document)
    releases: dict[date, CensusRetailRelease] = {}
    for href in parser.hrefs:
        if _PDF_HREF_RE.search(urlparse(href).path) is None:
            continue
        release = CensusRetailRelease(_filename_observation_date(href), href)
        existing = releases.get(release.observation_date)
        if existing is not None and existing.official_url.lower() != release.official_url.lower():
            raise CensusRetailArchiveError(
                f"conflicting MARTS links for {release.observation_date}"
            )
        releases[release.observation_date] = release
    if not releases:
        raise CensusRetailArchiveError("MARTS archive index contains no PDF releases")
    return sorted(releases.values(), key=lambda item: item.observation_date)


def _month_number(text: str) -> int:
    return _MONTHS[text.rstrip(".").lower()]


def _normalize_pdf_text(text: str) -> str:
    normalized = re.sub(
        r"\s+",
        " ",
        text.replace("\u00a0", " ")
        .replace("\u2010", "-")
        .replace("\u2011", "-")
        .replace("\u2012", "-")
        .replace("\u2212", "-"),
    ).strip()
    # Recurring PDF text-layer defects insert spaces inside common header/narrative words.
    for pattern, replacement in {
        r"\bretai\s+l\b": "retail",
        r"\ba\s+nd\b": "and",
        r"\bin\s+crease\b": "increase",
        r"\bde\s+crease\b": "decrease",
        r"\best\s+imates\b": "estimates",
        r"\bED\s+T\b": "EDT",
        r"\bES\s+T\b": "EST",
    }.items():
        normalized = re.sub(pattern, replacement, normalized, flags=re.IGNORECASE)
    return normalized


def parse_census_retail_release_text(
    text: str,
    *,
    observation_date: date,
) -> CensusRetailReleaseValues:
    """Parse one PDF text layer without inferring values from current history."""

    normalized = _normalize_pdf_text(text)
    title = _TITLE_RE.search(normalized[:4_000])
    if title is None:
        raise CensusRetailArchiveError("MARTS release title/reference month was not found")
    printed_observation_date = date(
        int(title.group("year")),
        _month_number(title.group("month")),
        1,
    )
    if printed_observation_date != observation_date:
        raise CensusRetailArchiveError(
            f"MARTS link month {observation_date} disagrees with PDF title "
            f"{printed_observation_date}"
        )

    header = normalized[: title.start()]
    date_match = _DATE_RE.search(header)
    time_match = _TIME_RE.search(header)
    if date_match is None or time_match is None:
        raise CensusRetailArchiveError("MARTS release header date/time was not found")
    release_date = date(
        int(date_match.group("year")),
        _month_number(date_match.group("month")),
        int(date_match.group("day")),
    )
    hour = int(time_match.group("hour")) % 12
    if time_match.group("ampm").lower().startswith("p"):
        hour += 12
    local_timestamp = datetime(
        release_date.year,
        release_date.month,
        release_date.day,
        hour,
        int(time_match.group("minute")),
        tzinfo=_NEW_YORK,
    )
    zone_label = time_match.group("zone").upper()
    if zone_label in {"EST", "EDT"} and local_timestamp.tzname() != zone_label:
        raise CensusRetailArchiveError(
            f"MARTS header zone {zone_label} disagrees with release date {release_date}"
        )
    if release_date <= observation_date:
        raise CensusRetailArchiveError("MARTS release date must follow its reference month")

    narrative = _NARRATIVE_RE.search(normalized[:12_000])
    if narrative is not None:
        level_text = narrative.group("level") or narrative.group("level_short")
        change_text = narrative.group("change") or narrative.group("change_short")
        direction = (
            narrative.group("direction") or narrative.group("direction_short") or ""
        ).lower()
        assert level_text is not None and change_text is not None
        level = float(level_text.replace(",", "").replace(" ", ""))
        change = float(change_text)
        if direction in {"decrease", "decline", "down"}:
            change = -change
    else:
        unchanged = _UNCHANGED_RE.search(normalized[:12_000])
        if unchanged is None:
            raise CensusRetailArchiveError(
                "MARTS advance total-sales level/change narrative was not found"
            )
        level = float(unchanged.group("level").replace(",", "").replace(" ", ""))
        change = 0.0
    return CensusRetailReleaseValues(
        observation_date=observation_date,
        release_date=release_date,
        release_timestamp=local_timestamp.astimezone(UTC),
        release_zone_label=zone_label,
        sales_level_billions=level,
        percent_change_mom=change,
    )


def parse_census_retail_release(
    payload: bytes,
    *,
    release: CensusRetailRelease,
) -> CensusRetailReleaseValues:
    """Extract and parse the text layer of one official MARTS PDF."""

    if not payload.startswith(b"%PDF"):
        raise CensusRetailArchiveError(f"invalid MARTS PDF: {release.official_url}")
    try:
        reader = PdfReader(io.BytesIO(payload))
        text = "\n".join((page.extract_text() or "") for page in reader.pages[:2])
    except Exception as exc:
        raise CensusRetailArchiveError(
            f"unable to read MARTS PDF: {release.official_url}"
        ) from exc
    if not text.strip():
        raise CensusRetailArchiveError(f"MARTS PDF has no text layer: {release.official_url}")
    return parse_census_retail_release_text(text, observation_date=release.observation_date)


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


def _manifest_release(entry: Mapping[str, object]) -> CensusRetailRelease:
    release = CensusRetailRelease(
        observation_date=date.fromisoformat(str(entry["observation_date"])),
        href=str(entry["url"]),
    )
    if release.relative_path.as_posix() != str(entry["path"]):
        raise CensusRetailArchiveError(f"MARTS manifest path mismatch: {entry['path']}")
    return release


def parse_census_retail_archive(directory: str | Path) -> list[VintageObservation]:
    """Parse a manifest-hashed local MARTS archive into canonical vintage rows."""

    root = Path(directory).resolve()
    try:
        manifest = json.loads((root / "release-index.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CensusRetailArchiveError("MARTS release-index.json is missing or invalid") from exc
    entries = manifest.get("releases")
    if not isinstance(entries, list) or not entries:
        raise CensusRetailArchiveError("MARTS manifest contains no releases")
    rows: list[dict[str, object]] = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise CensusRetailArchiveError("invalid MARTS manifest release entry")
        release = _manifest_release(entry)
        path = root / release.relative_path
        payload = path.read_bytes()
        digest = _sha256_bytes(payload)
        if digest != str(entry["sha256"]):
            raise CensusRetailArchiveError(f"MARTS hash mismatch: {release.official_url}")
        parsed = parse_census_retail_release(payload, release=release)
        downloaded_at = datetime.fromtimestamp(path.stat().st_mtime, UTC)
        common = {
            "observation_date": parsed.observation_date,
            "realtime_start": parsed.release_date,
            "availability_date": parsed.release_date,
            "release_timestamp": parsed.release_timestamp,
            "availability_timestamp": parsed.release_timestamp,
            "frequency": "monthly",
            "seasonal_adjustment": "seasonally_adjusted",
            "download_timestamp": downloaded_at,
            "source": CENSUS_RETAIL_SOURCE,
            "provenance_label": CENSUS_RETAIL_PROVENANCE,
            "source_metadata": {
                "agency": "U.S. Census Bureau",
                "program": "Advance Monthly Retail Trade Survey",
                "official_url": release.official_url,
                "source_file": release.relative_path.as_posix(),
                "source_sha256": digest,
                "release_date": parsed.release_date.isoformat(),
                "release_zone_label": parsed.release_zone_label,
                "timing_quality": CENSUS_RETAIL_TIMING_QUALITY,
                "vintage_type": "advance",
                "extraction_pattern": parsed.extraction_pattern,
                "citation_policy": CENSUS_RETAIL_CITATION_URL,
            },
        }
        rows.extend(
            [
                {
                    **common,
                    "series_id": CENSUS_RETAIL_LEVEL_SERIES_ID,
                    "value": parsed.sales_level_billions,
                    "units": "billions_current_dollars_rounded_0.1",
                    "transformation": "published_rounded_level",
                },
                {
                    **common,
                    "series_id": CENSUS_RETAIL_MOM_SERIES_ID,
                    "value": parsed.percent_change_mom,
                    "units": "percent_change_mom",
                    "transformation": "already_transformed",
                },
            ]
        )
    return _rows_with_realtime_ends(rows)


def _monthly_gaps(values: Sequence[date]) -> list[str]:
    if not values:
        return []
    observed = set(values)
    current = min(values)
    last = max(values)
    missing: list[str] = []
    while current <= last:
        if current not in observed:
            missing.append(current.isoformat())
        current = date(current.year + (current.month == 12), current.month % 12 + 1, 1)
    return missing


def audit_census_retail_archive(directory: str | Path) -> dict[str, object]:
    """Verify local MARTS inventory, hashes, PDF headers, values, and coverage."""

    root = Path(directory).resolve()
    try:
        manifest = json.loads((root / "release-index.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CensusRetailArchiveError("MARTS release-index.json is missing or invalid") from exc
    entries = manifest.get("releases")
    if not isinstance(entries, list) or not entries:
        raise CensusRetailArchiveError("MARTS manifest contains no releases")
    excluded_entries = manifest.get("excluded_releases", [])
    if not isinstance(excluded_entries, list):
        raise CensusRetailArchiveError("MARTS excluded-release inventory is invalid")
    expected: set[Path] = set()
    hashes: set[str] = set()
    observation_dates: list[date] = []
    release_dates: list[date] = []
    zone_labels: set[str] = set()
    et_zone_inferences = 0
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise CensusRetailArchiveError("invalid MARTS manifest release entry")
        release = _manifest_release(entry)
        path = (root / release.relative_path).resolve()
        expected.add(path)
        payload = path.read_bytes()
        digest = _sha256_bytes(payload)
        if digest != str(entry["sha256"]):
            raise CensusRetailArchiveError(f"MARTS hash mismatch: {release.official_url}")
        if digest in hashes:
            raise CensusRetailArchiveError(f"duplicate MARTS PDF bytes: {release.official_url}")
        hashes.add(digest)
        parsed = parse_census_retail_release(payload, release=release)
        observation_dates.append(parsed.observation_date)
        release_dates.append(parsed.release_date)
        zone_labels.add(parsed.release_zone_label)
        if parsed.release_zone_label == "ET":
            et_zone_inferences += 1
    excluded_observation_dates: list[date] = []
    for entry in excluded_entries:
        if not isinstance(entry, Mapping):
            raise CensusRetailArchiveError("invalid MARTS excluded-release entry")
        release = _manifest_release(entry)
        path = (root / release.relative_path).resolve()
        expected.add(path)
        payload = path.read_bytes()
        digest = _sha256_bytes(payload)
        if digest != str(entry["sha256"]):
            raise CensusRetailArchiveError(
                f"MARTS excluded-file hash mismatch: {release.official_url}"
            )
        if digest in hashes:
            raise CensusRetailArchiveError(
                f"duplicate MARTS PDF bytes: {release.official_url}"
            )
        hashes.add(digest)
        if str(entry.get("exclusion_reason")) != "official_pdf_has_no_text_layer":
            raise CensusRetailArchiveError("MARTS exclusion reason is not recognized")
        try:
            parse_census_retail_release(payload, release=release)
        except CensusRetailArchiveError as exc:
            if "has no text layer" not in str(exc):
                raise CensusRetailArchiveError(
                    f"MARTS excluded release failed for a different reason: {release.official_url}"
                ) from exc
        else:
            raise CensusRetailArchiveError(
                f"MARTS excluded release is now parseable: {release.official_url}"
            )
        excluded_observation_dates.append(release.observation_date)
    actual = {path.resolve() for path in (root / "releases").glob("*.pdf") if path.is_file()}
    missing_files = sorted(str(path.relative_to(root)) for path in expected - actual)
    extra_files = sorted(str(path.relative_to(root)) for path in actual - expected)
    if missing_files or extra_files:
        raise CensusRetailArchiveError(
            f"MARTS inventory mismatch: missing={missing_files[:3]}, extra={extra_files[:3]}"
        )
    index_entry = manifest.get("index_snapshot")
    if not isinstance(index_entry, Mapping):
        raise CensusRetailArchiveError("MARTS manifest has no index snapshot")
    index_path = root / str(index_entry["path"])
    if _sha256_bytes(index_path.read_bytes()) != str(index_entry["sha256"]):
        raise CensusRetailArchiveError("MARTS index snapshot hash mismatch")
    observations = parse_census_retail_archive(root)
    unique_keys = {
        (row.series_id, row.observation_date, row.realtime_start) for row in observations
    }
    if len(unique_keys) != len(observations):
        raise CensusRetailArchiveError("MARTS canonical rows contain duplicate vintage keys")
    gaps = _monthly_gaps(observation_dates)
    return {
        "passed": True,
        "official_url": CENSUS_RETAIL_INDEX_URL,
        "release_schedule": CENSUS_RETAIL_SCHEDULE_URL,
        "citation_policy": CENSUS_RETAIL_CITATION_URL,
        "directory": root.name,
        "enumerated_release_count": len(entries) + len(excluded_entries),
        "release_count": len(entries),
        "excluded_release_count": len(excluded_entries),
        "canonical_vintage_rows": len(observations),
        "first_observation_date": min(observation_dates).isoformat(),
        "last_observation_date": max(observation_dates).isoformat(),
        "first_release_date": min(release_dates).isoformat(),
        "last_release_date": max(release_dates).isoformat(),
        "missing_reference_months": gaps,
        "excluded_reference_months": [
            value.isoformat() for value in sorted(excluded_observation_dates)
        ],
        "source_header_zone_labels": sorted(zone_labels),
        "america_new_york_zone_inference_release_count": et_zone_inferences,
        "all_release_hashes_unique": len(hashes) == len(entries) + len(excluded_entries),
        "all_canonical_keys_unique": len(unique_keys) == len(observations),
        "exact_release_clock_times_verified": True,
        "published_level_and_percent_change_retained": True,
        "server_original_bytes_claimed": True,
        "timing_quality": CENSUS_RETAIL_TIMING_QUALITY,
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
                raise CensusRetailArchiveError(
                    f"MARTS request failed: {url} ({exc.code})"
                ) from exc
            retry_after = exc.headers.get("Retry-After")
            delay = float(retry_after) if retry_after and retry_after.isdigit() else 2**attempt
        except (TimeoutError, URLError) as exc:
            if attempt == attempts - 1:
                raise CensusRetailArchiveError(f"MARTS request failed: {url}") from exc
            delay = 2**attempt
        time.sleep(min(delay, 16))
    raise AssertionError("unreachable")


def _write_immutable(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise CensusRetailArchiveError(f"refusing to replace immutable raw file: {path}")
        return
    temporary = path.with_suffix(f"{path.suffix}.part")
    temporary.write_bytes(payload)
    temporary.replace(path)


def acquire_census_retail_archive(
    output_dir: str | Path,
    *,
    start_year: int = 2003,
    end_year: int | None = None,
    workers: int = 4,
) -> dict[str, object]:
    """Acquire and immediately parse-check official MARTS PDF vintages."""

    final_year = end_year or datetime.now(UTC).year
    if start_year < 1953 or final_year < start_year:
        raise ValueError("MARTS archive years must satisfy 1953 <= start_year <= end_year")
    if workers < 1 or workers > 8:
        raise ValueError("workers must be between 1 and 8")
    root = Path(output_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    index_payload, index_content_type = _fetch(CENSUS_RETAIL_INDEX_URL)
    index_digest = _sha256_bytes(index_payload)
    index_path = root / "index" / f"{datetime.now(UTC).date().isoformat()}-{index_digest[:12]}.html"
    _write_immutable(index_path, index_payload)
    releases = [
        release
        for release in parse_census_retail_archive_index(index_payload)
        if start_year <= release.observation_date.year <= final_year
    ]
    if not releases:
        raise CensusRetailArchiveError("selected MARTS years contain no releases")

    def download(
        release: CensusRetailRelease,
    ) -> tuple[CensusRetailRelease, CensusRetailReleaseValues, bytes, str]:
        path = root / release.relative_path
        if path.exists():
            payload = path.read_bytes()
            content_type = "application/pdf"
        else:
            payload, content_type = _fetch(release.official_url)
            _write_immutable(path, payload)
            time.sleep(0.03)
        parsed = parse_census_retail_release(payload, release=release)
        return release, parsed, payload, content_type

    completed: dict[date, dict[str, object]] = {}
    excluded: dict[date, dict[str, object]] = {}
    errors: list[str] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(download, release): release for release in releases}
        for future in as_completed(futures):
            release = futures[future]
            try:
                release, parsed, payload, content_type = future.result()
            except CensusRetailArchiveError as exc:
                path = root / release.relative_path
                payload = path.read_bytes()
                if "has no text layer" in str(exc):
                    excluded[release.observation_date] = {
                        "observation_date": release.observation_date.isoformat(),
                        "release_date": None,
                        "release_timestamp": None,
                        "release_zone_label": None,
                        "url": release.official_url,
                        "content_type": "application/pdf",
                        "path": release.relative_path.as_posix(),
                        "bytes": len(payload),
                        "sha256": _sha256_bytes(payload),
                        "exclusion_reason": "official_pdf_has_no_text_layer",
                    }
                    continue
                errors.append(f"{release.official_url}: {exc}")
                continue
            except Exception as exc:  # collect unexpected drift across the whole archive
                errors.append(f"{release.official_url}: {exc}")
                continue
            completed[release.observation_date] = {
                "observation_date": release.observation_date.isoformat(),
                "release_date": parsed.release_date.isoformat(),
                "release_timestamp": parsed.release_timestamp.isoformat(),
                "release_zone_label": parsed.release_zone_label,
                "url": release.official_url,
                "content_type": content_type,
                "path": release.relative_path.as_posix(),
                "bytes": len(payload),
                "sha256": _sha256_bytes(payload),
            }
    if errors:
        raise CensusRetailArchiveError(
            f"{len(errors)} MARTS releases failed validation:\n"
            + "\n".join(sorted(errors)[:20])
        )

    manifest_path = root / "release-index.json"
    existing_manifest = (
        json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else None
    )
    manifest = {
        "schema_version": 1,
        "status": "downloaded_and_parse_checked",
        "source_url": CENSUS_RETAIL_INDEX_URL,
        "release_schedule": CENSUS_RETAIL_SCHEDULE_URL,
        "citation_policy": CENSUS_RETAIL_CITATION_URL,
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
            "url": CENSUS_RETAIL_INDEX_URL,
            "content_type": index_content_type,
            "path": index_path.relative_to(root).as_posix(),
            "bytes": len(index_payload),
            "sha256": index_digest,
        },
        "enumerated_release_count": len(releases),
        "release_count": len(completed),
        "excluded_release_count": len(excluded),
        "releases": [
            completed[release.observation_date]
            for release in releases
            if release.observation_date in completed
        ],
        "excluded_releases": [
            excluded[release.observation_date]
            for release in releases
            if release.observation_date in excluded
        ],
    }
    if isinstance(existing_manifest, Mapping):
        existing_hashes = {
            str(entry["observation_date"]): str(entry["sha256"])
            for group in ("releases", "excluded_releases")
            for entry in existing_manifest.get(group, [])
        }
        new_hashes = {
            str(entry["observation_date"]): str(entry["sha256"])
            for group in ("releases", "excluded_releases")
            for entry in manifest[group]
        }
        conflicts = {
            key
            for key, digest in existing_hashes.items()
            if key in new_hashes and new_hashes[key] != digest
        }
        if conflicts:
            raise CensusRetailArchiveError(
                f"refusing to rewrite MARTS release hashes: {sorted(conflicts)[:3]}"
            )
    temporary_manifest = manifest_path.with_suffix(".json.part")
    temporary_manifest.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary_manifest.replace(manifest_path)
    audit = audit_census_retail_archive(root)
    return {
        "status": "verified",
        "output_dir": root,
        "release_count": audit["release_count"],
        "excluded_release_count": audit["excluded_release_count"],
        "canonical_vintage_rows": audit["canonical_vintage_rows"],
        "first_observation_date": audit["first_observation_date"],
        "last_observation_date": audit["last_observation_date"],
        "first_release_date": audit["first_release_date"],
        "last_release_date": audit["last_release_date"],
        "missing_reference_months": audit["missing_reference_months"],
        "exact_release_clock_times_verified": audit["exact_release_clock_times_verified"],
    }


__all__ = [
    "CENSUS_RETAIL_CITATION_URL",
    "CENSUS_RETAIL_DIRECTORY",
    "CENSUS_RETAIL_INDEX_URL",
    "CENSUS_RETAIL_LEVEL_SERIES_ID",
    "CENSUS_RETAIL_MOM_SERIES_ID",
    "CENSUS_RETAIL_PROVENANCE",
    "CENSUS_RETAIL_SCHEDULE_URL",
    "CENSUS_RETAIL_SOURCE",
    "CENSUS_RETAIL_TIMING_QUALITY",
    "CensusRetailArchiveError",
    "CensusRetailRelease",
    "CensusRetailReleaseValues",
    "acquire_census_retail_archive",
    "audit_census_retail_archive",
    "parse_census_retail_archive",
    "parse_census_retail_archive_index",
    "parse_census_retail_release",
    "parse_census_retail_release_text",
]
