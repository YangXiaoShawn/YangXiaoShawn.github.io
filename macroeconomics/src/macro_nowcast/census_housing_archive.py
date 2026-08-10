"""Acquire, audit, and parse Census new-residential-construction vintages.

The Census Bureau's historical New Residential Construction page exposes the
dated report PDFs.  Each accepted snapshot preserves the release header and the
headline total privately-owned housing-starts estimate.  The mutable current
time series is never substituted for these publication snapshots.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import time
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, date, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Final
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from pypdf import PdfReader

from macro_nowcast.schema import VintageObservation

CENSUS_HOUSING_STARTS_SERIES_ID: Final = "CENSUS_NRC_HOUSING_STARTS_SAAR"
CENSUS_HOUSING_SOURCE: Final = "CENSUS_NRC_RELEASE_ARCHIVE"
CENSUS_HOUSING_PROVENANCE: Final = "official_agency_archive"
CENSUS_HOUSING_DIRECTORY: Final = "census-nrc"
CENSUS_HOUSING_INDEX_URL: Final = (
    "https://www.census.gov/construction/nrc/data/releases.html"
)
CENSUS_HOUSING_SCHEDULE_URL: Final = (
    "https://www.census.gov/construction/nrc/release_schedule.html"
)
CENSUS_HOUSING_CITATION_URL: Final = (
    "https://www.census.gov/about/policies/citation.html"
)
CENSUS_HOUSING_TIMING_QUALITY: Final = "official_header_clock_America_New_York"

_BASE_URL: Final = "https://www.census.gov/construction/nrc/"
_USER_AGENT: Final = "macro-nowcast-research/0.1 (public archive verification)"
_NEW_YORK: Final = ZoneInfo("America/New_York")
_PDF_HREF_RE = re.compile(
    r"(?:^|/)newresconst_(?P<year>\d{4})(?P<month>\d{2})\.pdf$",
    re.I,
)
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
    r"(?P<ampm>A\.?\s*M\.?|P\.?\s*M\.?)\s*(?P<zone>EDT|EST|ET)\b",
    re.I,
)
_TITLE_RE = re.compile(
    rf"(?:MONTHLY\s+NEW\s+RESIDENTIAL\s+CONSTRUCTION[,]?|"
    rf"NEW\s+RESIDENTIAL\s+CONSTRUCTION\s+IN)\s+"
    rf"(?P<month>{_MONTH_PATTERN})\.?\s+(?P<year>\d{{4}})",
    re.I,
)
_STARTS_RE = re.compile(
    r"Privately[-\s]+owned\s+housing\s+starts\s+in\s+[^.]{1,40}?\s+were\s+at\s+a\s+"
    r"seasonally\s+adjusted\s+annual\s+rate\s+of\s+"
    r"(?P<level>\d[\d,\s]*?)\s*\.",
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


class CensusHousingArchiveError(RuntimeError):
    """Raised when a Census housing release cannot be used without guessing."""


@dataclass(frozen=True, slots=True)
class CensusHousingRelease:
    """One reference-month PDF from the official historical index."""

    observation_date: date
    href: str

    @property
    def official_url(self) -> str:
        return urljoin(_BASE_URL, self.href)

    @property
    def relative_path(self) -> Path:
        return Path("releases") / Path(urlparse(self.official_url).path).name


@dataclass(frozen=True, slots=True)
class CensusHousingReleaseValues:
    """Published identity and total housing-starts estimate from one PDF."""

    observation_date: date
    release_date: date
    release_timestamp: datetime
    release_zone_label: str
    housing_starts_thousands_saar: float
    extraction_pattern: str = "headline_housing_starts_narrative"


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
        raise CensusHousingArchiveError(f"invalid NRC release link: {href}")
    return date(int(match.group("year")), int(match.group("month")), 1)


def parse_census_housing_archive_index(
    document: str | bytes,
) -> list[CensusHousingRelease]:
    """Return unique official NRC PDFs in reference-month order."""

    if isinstance(document, bytes):
        document = document.decode("utf-8-sig", errors="replace")
    parser = _LinkParser()
    parser.feed(document)
    releases: dict[date, CensusHousingRelease] = {}
    for source_href in parser.hrefs:
        href = source_href
        if href.lower().startswith(
            "fhttps://www.census.gov/construction/nrc/pdf/newresconst_"
        ):
            # The official April 2009 anchor contains the literal typo `fhttps`.
            href = href[1:]
        if _PDF_HREF_RE.search(urlparse(href).path) is None:
            continue
        release = CensusHousingRelease(_filename_observation_date(href), href)
        existing = releases.get(release.observation_date)
        if existing is not None and existing.official_url.lower() != release.official_url.lower():
            raise CensusHousingArchiveError(
                f"conflicting NRC links for {release.observation_date}"
            )
        releases[release.observation_date] = release
    if not releases:
        raise CensusHousingArchiveError("NRC archive index contains no PDF releases")
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
    for pattern, replacement in {
        r"\b(\d{1,2}):\s+(\d{2})\b": r"\1:\2",
        r"\bseasonally\s+ad\s+justed\b": "seasonally adjusted",
        r"\bseasonally\s+adju\s+sted\b": "seasonally adjusted",
        r"\bseasonally\s+adjust\s+ed\b": "seasonally adjusted",
        r"\bseasonally\s+adjusted\s+an\s+nual\b": (
            "seasonally adjusted annual"
        ),
        r"\bseasonally\s+adjusted\s+annu\s+al\b": (
            "seasonally adjusted annual"
        ),
        r"\bannual\s+ra\s+te\b": "annual rate",
    }.items():
        normalized = re.sub(pattern, replacement, normalized, flags=re.IGNORECASE)
    return normalized


def parse_census_housing_release_text(
    text: str,
    *,
    observation_date: date,
) -> CensusHousingReleaseValues:
    """Parse one NRC PDF text layer without using current revised history."""

    normalized = _normalize_pdf_text(text)
    title = _TITLE_RE.search(normalized[:5_000])
    if title is None:
        raise CensusHousingArchiveError("NRC release title/reference month was not found")
    printed_observation_date = date(
        int(title.group("year")),
        _month_number(title.group("month")),
        1,
    )
    if printed_observation_date != observation_date:
        raise CensusHousingArchiveError(
            f"NRC link month {observation_date} disagrees with PDF title "
            f"{printed_observation_date}"
        )

    header = normalized[: title.start()]
    date_match = _DATE_RE.search(header)
    time_match = _TIME_RE.search(header)
    if date_match is None or time_match is None:
        raise CensusHousingArchiveError("NRC release header date/time was not found")
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
        raise CensusHousingArchiveError(
            f"NRC header zone {zone_label} disagrees with release date {release_date}"
        )
    if release_date <= observation_date:
        raise CensusHousingArchiveError("NRC release date must follow its reference month")

    starts = _STARTS_RE.search(normalized[:15_000])
    if starts is None:
        raise CensusHousingArchiveError("NRC headline total housing-starts value was not found")
    level_units = float(starts.group("level").replace(",", "").replace(" ", ""))
    if level_units < 100_000:
        raise CensusHousingArchiveError("NRC housing-starts narrative is not in annual units")
    return CensusHousingReleaseValues(
        observation_date=observation_date,
        release_date=release_date,
        release_timestamp=local_timestamp.astimezone(UTC),
        release_zone_label=zone_label,
        housing_starts_thousands_saar=level_units / 1_000.0,
    )


def parse_census_housing_release(
    payload: bytes,
    *,
    release: CensusHousingRelease,
) -> CensusHousingReleaseValues:
    """Extract and parse the first two pages of one official NRC PDF."""

    if not payload.startswith(b"%PDF"):
        raise CensusHousingArchiveError(f"invalid NRC PDF: {release.official_url}")
    try:
        reader = PdfReader(io.BytesIO(payload))
        text = "\n".join((page.extract_text() or "") for page in reader.pages[:2])
    except Exception as exc:
        raise CensusHousingArchiveError(
            f"unable to read NRC PDF: {release.official_url}"
        ) from exc
    if not text.strip():
        raise CensusHousingArchiveError(f"NRC PDF has no text layer: {release.official_url}")
    return parse_census_housing_release_text(text, observation_date=release.observation_date)


def _manifest_release(entry: Mapping[str, object]) -> CensusHousingRelease:
    release = CensusHousingRelease(
        observation_date=date.fromisoformat(str(entry["observation_date"])),
        href=str(entry["url"]),
    )
    if release.relative_path.as_posix() != str(entry["path"]):
        raise CensusHousingArchiveError(f"NRC manifest path mismatch: {entry['path']}")
    return release


def parse_census_housing_archive(directory: str | Path) -> list[VintageObservation]:
    """Parse a manifest-hashed NRC archive into canonical publication rows."""

    root = Path(directory).resolve()
    try:
        manifest = json.loads((root / "release-index.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CensusHousingArchiveError("NRC release-index.json is missing or invalid") from exc
    entries = manifest.get("releases")
    if not isinstance(entries, list) or not entries:
        raise CensusHousingArchiveError("NRC manifest contains no releases")
    observations: list[VintageObservation] = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise CensusHousingArchiveError("invalid NRC manifest release entry")
        release = _manifest_release(entry)
        path = root / release.relative_path
        payload = path.read_bytes()
        digest = _sha256_bytes(payload)
        if digest != str(entry["sha256"]):
            raise CensusHousingArchiveError(f"NRC hash mismatch: {release.official_url}")
        parsed = parse_census_housing_release(payload, release=release)
        observations.append(
            VintageObservation(
                series_id=CENSUS_HOUSING_STARTS_SERIES_ID,
                observation_date=parsed.observation_date,
                realtime_start=parsed.release_date,
                availability_date=parsed.release_date,
                release_timestamp=parsed.release_timestamp,
                availability_timestamp=parsed.release_timestamp,
                value=parsed.housing_starts_thousands_saar,
                units="thousands_of_units_saar",
                frequency="monthly",
                seasonal_adjustment="seasonally_adjusted_annual_rate",
                transformation="published_rounded_level",
                download_timestamp=datetime.fromtimestamp(path.stat().st_mtime, UTC),
                source=CENSUS_HOUSING_SOURCE,
                provenance_label=CENSUS_HOUSING_PROVENANCE,
                source_metadata={
                    "agency": (
                        "U.S. Census Bureau and U.S. Department of Housing and Urban "
                        "Development"
                    ),
                    "program": "New Residential Construction",
                    "official_url": release.official_url,
                    "source_file": release.relative_path.as_posix(),
                    "source_sha256": digest,
                    "release_date": parsed.release_date.isoformat(),
                    "release_zone_label": parsed.release_zone_label,
                    "timing_quality": CENSUS_HOUSING_TIMING_QUALITY,
                    "vintage_type": "preliminary",
                    "extraction_pattern": parsed.extraction_pattern,
                    "citation_policy": CENSUS_HOUSING_CITATION_URL,
                },
            )
        )
    return sorted(
        observations,
        key=lambda item: (item.observation_date, item.realtime_start),
    )


def _monthly_gaps(values: list[date]) -> list[str]:
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


def audit_census_housing_archive(directory: str | Path) -> dict[str, object]:
    """Verify NRC inventory, hashes, headers, values, clocks, and coverage."""

    root = Path(directory).resolve()
    try:
        manifest = json.loads((root / "release-index.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CensusHousingArchiveError("NRC release-index.json is missing or invalid") from exc
    entries = manifest.get("releases")
    excluded_entries = manifest.get("excluded_releases", [])
    if not isinstance(entries, list) or not entries or not isinstance(excluded_entries, list):
        raise CensusHousingArchiveError("NRC manifest inventory is invalid")
    expected: set[Path] = set()
    hash_dates: dict[str, date] = {}
    duplicate_hash_aliases: list[list[str]] = []
    observation_dates: list[date] = []
    release_dates: list[date] = []
    zone_labels: set[str] = set()
    et_zone_inferences = 0
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise CensusHousingArchiveError("invalid NRC manifest release entry")
        release = _manifest_release(entry)
        path = (root / release.relative_path).resolve()
        expected.add(path)
        payload = path.read_bytes()
        digest = _sha256_bytes(payload)
        if digest != str(entry["sha256"]):
            raise CensusHousingArchiveError(f"NRC hash mismatch: {release.official_url}")
        if digest in hash_dates:
            raise CensusHousingArchiveError(f"duplicate NRC PDF bytes: {release.official_url}")
        hash_dates[digest] = release.observation_date
        parsed = parse_census_housing_release(payload, release=release)
        observation_dates.append(parsed.observation_date)
        release_dates.append(parsed.release_date)
        zone_labels.add(parsed.release_zone_label)
        if parsed.release_zone_label == "ET":
            et_zone_inferences += 1
    excluded_dates: list[date] = []
    for entry in excluded_entries:
        if not isinstance(entry, Mapping):
            raise CensusHousingArchiveError("invalid NRC excluded-release entry")
        release = _manifest_release(entry)
        path = (root / release.relative_path).resolve()
        expected.add(path)
        payload = path.read_bytes()
        digest = _sha256_bytes(payload)
        if digest != str(entry["sha256"]):
            raise CensusHousingArchiveError(
                f"NRC excluded-file hash mismatch: {release.official_url}"
            )
        if digest in hash_dates:
            duplicate_pair = {hash_dates[digest], release.observation_date}
            if duplicate_pair != {date(2013, 9, 1), date(2013, 10, 1)}:
                raise CensusHousingArchiveError(
                    f"duplicate NRC PDF bytes: {release.official_url}"
                )
            duplicate_hash_aliases.append(
                [value.isoformat() for value in sorted(duplicate_pair)]
            )
        else:
            hash_dates[digest] = release.observation_date
        exclusion_reason = str(entry.get("exclusion_reason"))
        expected_error = {
            "official_pdf_has_no_text_layer": "has no text layer",
            "official_index_link_month_mismatch": "disagrees with PDF title",
            "official_release_omits_housing_starts_due_to_funding_lapse": (
                "headline total housing-starts value was not found"
            ),
        }.get(exclusion_reason)
        if expected_error is None:
            raise CensusHousingArchiveError("NRC exclusion reason is not recognized")
        try:
            parse_census_housing_release(payload, release=release)
        except CensusHousingArchiveError as exc:
            if expected_error not in str(exc):
                raise CensusHousingArchiveError(
                    f"NRC excluded release failed for another reason: {release.official_url}"
                ) from exc
        else:
            raise CensusHousingArchiveError(
                f"NRC excluded release is now parseable: {release.official_url}"
            )
        excluded_dates.append(release.observation_date)
    actual = {
        path.resolve() for path in (root / "releases").glob("*.pdf") if path.is_file()
    }
    if expected != actual:
        raise CensusHousingArchiveError("NRC local PDF inventory does not match manifest")
    index_entry = manifest.get("index_snapshot")
    if not isinstance(index_entry, Mapping):
        raise CensusHousingArchiveError("NRC manifest has no index snapshot")
    index_path = root / str(index_entry["path"])
    if _sha256_bytes(index_path.read_bytes()) != str(index_entry["sha256"]):
        raise CensusHousingArchiveError("NRC index snapshot hash mismatch")
    observations = parse_census_housing_archive(root)
    unique_keys = {
        (row.series_id, row.observation_date, row.realtime_start) for row in observations
    }
    if len(unique_keys) != len(observations):
        raise CensusHousingArchiveError("NRC canonical rows contain duplicate vintage keys")
    return {
        "passed": True,
        "official_url": CENSUS_HOUSING_INDEX_URL,
        "release_schedule": CENSUS_HOUSING_SCHEDULE_URL,
        "citation_policy": CENSUS_HOUSING_CITATION_URL,
        "directory": root.name,
        "enumerated_release_count": len(entries) + len(excluded_entries),
        "release_count": len(entries),
        "excluded_release_count": len(excluded_entries),
        "canonical_vintage_rows": len(observations),
        "first_observation_date": min(observation_dates).isoformat(),
        "last_observation_date": max(observation_dates).isoformat(),
        "first_release_date": min(release_dates).isoformat(),
        "last_release_date": max(release_dates).isoformat(),
        "missing_reference_months": _monthly_gaps(observation_dates),
        "excluded_reference_months": [
            value.isoformat() for value in sorted(excluded_dates)
        ],
        "source_header_zone_labels": sorted(zone_labels),
        "official_index_href_repairs": [
            "2009-04: fhttps:// normalized to https://"
        ]
        if date(2009, 4, 1) in observation_dates
        else [],
        "america_new_york_zone_inference_release_count": et_zone_inferences,
        "all_release_hashes_unique_except_documented_aliases": (
            len(hash_dates) + len(duplicate_hash_aliases)
            == len(entries) + len(excluded_entries)
        ),
        "known_duplicate_hash_aliases": duplicate_hash_aliases,
        "all_canonical_keys_unique": len(unique_keys) == len(observations),
        "exact_release_clock_times_verified": True,
        "server_original_bytes_claimed": True,
        "timing_quality": CENSUS_HOUSING_TIMING_QUALITY,
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
                raise CensusHousingArchiveError(
                    f"NRC request failed: {url} ({exc.code})"
                ) from exc
            retry_after = exc.headers.get("Retry-After")
            delay = float(retry_after) if retry_after and retry_after.isdigit() else 2**attempt
        except (TimeoutError, URLError) as exc:
            if attempt == attempts - 1:
                raise CensusHousingArchiveError(f"NRC request failed: {url}") from exc
            delay = 2**attempt
        time.sleep(min(delay, 16))
    raise AssertionError("unreachable")


def _write_immutable(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise CensusHousingArchiveError(f"refusing to replace immutable raw file: {path}")
        return
    temporary = path.with_suffix(f"{path.suffix}.part")
    temporary.write_bytes(payload)
    temporary.replace(path)


def acquire_census_housing_archive(
    output_dir: str | Path,
    *,
    start_year: int = 2003,
    end_year: int | None = None,
    workers: int = 4,
) -> dict[str, object]:
    """Acquire and immediately parse-check official NRC PDF vintages."""

    final_year = end_year or datetime.now(UTC).year
    if start_year < 1995 or final_year < start_year:
        raise ValueError("NRC archive years must satisfy 1995 <= start_year <= end_year")
    if workers < 1 or workers > 8:
        raise ValueError("workers must be between 1 and 8")
    root = Path(output_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    index_payload, index_content_type = _fetch(CENSUS_HOUSING_INDEX_URL)
    index_digest = _sha256_bytes(index_payload)
    index_path = root / "index" / f"{datetime.now(UTC).date()}-{index_digest[:12]}.html"
    _write_immutable(index_path, index_payload)
    releases = [
        release
        for release in parse_census_housing_archive_index(index_payload)
        if start_year <= release.observation_date.year <= final_year
    ]
    if not releases:
        raise CensusHousingArchiveError("selected NRC years contain no releases")

    def download(
        release: CensusHousingRelease,
    ) -> tuple[CensusHousingRelease, CensusHousingReleaseValues, bytes, str]:
        path = root / release.relative_path
        if path.exists():
            payload = path.read_bytes()
            content_type = "application/pdf"
        else:
            payload, content_type = _fetch(release.official_url)
            _write_immutable(path, payload)
            time.sleep(0.03)
        parsed = parse_census_housing_release(payload, release=release)
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
            except CensusHousingArchiveError as exc:
                path = root / release.relative_path
                exclusion_reason = None
                if path.exists() and "has no text layer" in str(exc):
                    exclusion_reason = "official_pdf_has_no_text_layer"
                elif release.observation_date == date(2013, 9, 1) and "disagrees" in str(exc):
                    exclusion_reason = "official_index_link_month_mismatch"
                elif (
                    release.observation_date == date(2013, 10, 1)
                    and "headline total housing-starts value was not found" in str(exc)
                ):
                    exclusion_reason = (
                        "official_release_omits_housing_starts_due_to_funding_lapse"
                    )
                if path.exists() and exclusion_reason is not None:
                    payload = path.read_bytes()
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
                        "exclusion_reason": exclusion_reason,
                    }
                    continue
                errors.append(f"{release.official_url}: {exc}")
                continue
            except Exception as exc:
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
        raise CensusHousingArchiveError(
            f"{len(errors)} NRC releases failed validation:\n"
            + "\n".join(sorted(errors)[:20])
        )

    manifest_path = root / "release-index.json"
    existing_manifest = (
        json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else None
    )
    manifest = {
        "schema_version": 1,
        "status": "downloaded_and_parse_checked",
        "source_url": CENSUS_HOUSING_INDEX_URL,
        "release_schedule": CENSUS_HOUSING_SCHEDULE_URL,
        "citation_policy": CENSUS_HOUSING_CITATION_URL,
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
            "url": CENSUS_HOUSING_INDEX_URL,
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
        "known_index_anomalies": [
            {
                "observation_date": "2009-04-01",
                "raw_href_scheme": "fhttps",
                "normalized_href_scheme": "https",
                "reason": "official_page_single_character_scheme_typo",
            }
        ]
        if any(release.observation_date == date(2009, 4, 1) for release in releases)
        else [],
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
            raise CensusHousingArchiveError(
                f"refusing to rewrite NRC release hashes: {sorted(conflicts)[:3]}"
            )
    temporary_manifest = manifest_path.with_suffix(".json.part")
    temporary_manifest.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary_manifest.replace(manifest_path)
    audit = audit_census_housing_archive(root)
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
    "CENSUS_HOUSING_CITATION_URL",
    "CENSUS_HOUSING_DIRECTORY",
    "CENSUS_HOUSING_INDEX_URL",
    "CENSUS_HOUSING_PROVENANCE",
    "CENSUS_HOUSING_SCHEDULE_URL",
    "CENSUS_HOUSING_SOURCE",
    "CENSUS_HOUSING_STARTS_SERIES_ID",
    "CENSUS_HOUSING_TIMING_QUALITY",
    "CensusHousingArchiveError",
    "CensusHousingRelease",
    "CensusHousingReleaseValues",
    "acquire_census_housing_archive",
    "audit_census_housing_archive",
    "parse_census_housing_archive",
    "parse_census_housing_archive_index",
    "parse_census_housing_release",
    "parse_census_housing_release_text",
]
