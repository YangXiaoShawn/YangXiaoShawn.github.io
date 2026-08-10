"""Acquire, audit, and parse official DOL weekly-claims release vintages.

The Employment and Training Administration archive exposes the news release
that was public each week, rather than a latest-revised time series.  Each
release supplies the advance seasonally adjusted initial-claims estimate for
the current reference week and the preceding week's reported value.  The
archive explicitly labels that prior value revised or unrevised, and the parser
preserves the source label rather than silently treating every value as revised.

Network access is confined to :func:`acquire_dol_claims_archive`.  Parsing and
auditing are deterministic and offline.  Raw release files are immutable by
default and every file is identified by its official URL and SHA-256 digest.
"""

from __future__ import annotations

import hashlib
import html
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
from pathlib import Path, PurePosixPath
from typing import Final
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from pypdf import PdfReader

from macro_nowcast.schema import VintageObservation

DOL_CLAIMS_SERIES_ID: Final = "DOL_UI_INITIAL_CLAIMS_SA"
DOL_CLAIMS_4WMA_SERIES_ID: Final = "DOL_UI_INITIAL_CLAIMS_4WMA_SA"
DOL_CLAIMS_SOURCE: Final = "DOL_UI_WEEKLY_CLAIMS_ARCHIVE"
DOL_CLAIMS_PROVENANCE: Final = "official_agency_archive"
DOL_CLAIMS_DIRECTORY: Final = "dol-ui-claims"
DOL_CLAIMS_ARCHIVE_URL: Final = "https://oui.doleta.gov/unemploy/claims_arch.asp"
DOL_CLAIMS_INDEX_URL: Final = "https://oui.doleta.gov/unemploy/archive.asp"
DOL_PUBLIC_DOMAIN_URL: Final = "https://www.dol.gov/general/aboutdol/copyright"
DOL_CLAIMS_TIMING_QUALITY: Final = "official_weekly_schedule_0830_America_New_York"
_BASE_URL: Final = "https://oui.doleta.gov"
_USER_AGENT: Final = "macro-nowcast-research/0.1 (public archive verification)"
_NEW_YORK: Final = ZoneInfo("America/New_York")

_RELEASE_HREF_RE = re.compile(
    r"^/press/(?P<directory_year>\d{4})/(?P<stem>\d{6}|\d{8})\."
    r"(?P<extension>asp|html?|pdf)$",
    re.IGNORECASE,
)
_MONTH_PATTERN = (
    r"Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|"
    r"Aug(?:ust)?|Sept?(?:ember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?"
)
_CURRENT_RE = re.compile(
    rf"(?:In|For)\s+the\s+week\s+ending\s+"
    rf"(?P<month>{_MONTH_PATTERN})\.?\s*(?P<day>\d{{1,2}})"
    rf"(?:,\s*(?P<year>\d{{4}}))?\s*,?\s*the\s+advance\s+figure\s+for\s+"
    rf"seasonally\s+adjusted\s+initial\s+claims\s+was\s+"
    rf"(?P<value>\d{{1,3}}(?:,\d{{3}})+|\d+)",
    re.IGNORECASE,
)
_REVISED_FROM_TO_RE = re.compile(
    r"previous\s+week(?:'s|s')\s+(?:level|figure)\s+was\s+revised.*?"
    r"from\s+(?P<old>\d{1,3}(?:,\d{3})+|\d+)\s+to\s+"
    r"(?P<new>\d{1,3}(?:,\d{3})+|\d+)",
    re.IGNORECASE,
)
_PRIOR_DIRECT_RE = re.compile(
    r"previous\s+week(?:'s|s')\s+(?P<status>revised|unrevised)\s+(?:figure|level)"
    r"(?:\s+was|\s+of)?\s+(?P<value>\d{1,3}(?:,\d{3})+|\d+)",
    re.IGNORECASE,
)
_PRIOR_UNLABELED_RE = re.compile(
    r"previous\s+week(?:'s|s')\s+(?:figure|level)"
    r"(?:\s+was|\s+of)?\s+(?P<value>\d{1,3}(?:,\d{3})+|\d+)",
    re.IGNORECASE,
)
_UNCHANGED_RE = re.compile(
    r"unchanged\s+from\s+the\s+previous\s+week(?:'s|s')\s+"
    r"(?P<status>revised|unrevised)?\s*(?:figure|level)",
    re.IGNORECASE,
)
_PRIOR_LEVEL_WITHOUT_VALUE_RE = re.compile(
    r"from\s+the\s+previous\s+week(?:'s|s')\s+(?:reported\s+)?(?:figure|level)\b",
    re.IGNORECASE,
)
_CHANGE_RE = re.compile(
    r"(?:an?\s+)?(?P<direction>increase|decrease)\s+of\s+"
    r"(?P<value>\d{1,3}(?:,\d{3})+|\d+)",
    re.IGNORECASE,
)
_FOUR_WEEK_AVERAGE_RE = re.compile(
    r"\bThe\s+4\s*-\s*week\s+moving\s+average\s+was\s+"
    r"(?P<value>\d{1,3}(?:,\d{3})+|\d+)",
    re.IGNORECASE,
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


class DOLClaimsArchiveError(RuntimeError):
    """Raised when the official archive cannot be interpreted without guessing."""


@dataclass(frozen=True, slots=True)
class DOLClaimsRelease:
    """One exact release link enumerated by the official archive calendar."""

    release_date: date
    href: str
    directory_year: int
    extension: str

    @property
    def official_url(self) -> str:
        return f"{_BASE_URL}{self.href}"

    @property
    def relative_path(self) -> Path:
        return Path(PurePosixPath(self.href).relative_to("/"))


@dataclass(frozen=True, slots=True)
class DOLClaimsReleaseValues:
    """The two publication-vintage facts retained from one weekly release."""

    release_date: date
    current_week: date
    current_advance: int
    previous_week: date
    previous_reported: int
    previous_vintage_type: str
    current_four_week_average: int
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


class _VisibleTextParser(HTMLParser):
    _BREAKS = frozenset({"br", "div", "h1", "h2", "h3", "li", "p", "pre", "td", "th", "tr"})

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
        tag = tag.lower()
        if tag in {"script", "style"}:
            self.ignored_depth += 1
        elif not self.ignored_depth and tag in self._BREAKS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style"} and self.ignored_depth:
            self.ignored_depth -= 1
        elif not self.ignored_depth and tag in self._BREAKS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.ignored_depth:
            self.parts.append(data)

    def text(self) -> str:
        return "".join(self.parts)


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _release_date_from_stem(stem: str) -> date:
    pattern = "%m%d%Y" if len(stem) == 8 else "%m%d%y"
    try:
        return datetime.strptime(stem, pattern).date()
    except ValueError as exc:
        raise DOLClaimsArchiveError(f"invalid DOL release filename date: {stem}") from exc


def parse_dol_claims_archive_index(document: str | bytes) -> list[DOLClaimsRelease]:
    """Return unique, date-sorted release links from one official calendar page."""

    if isinstance(document, bytes):
        document = document.decode("utf-8", errors="replace")
    parser = _LinkParser()
    parser.feed(document)
    releases: dict[str, DOLClaimsRelease] = {}
    for href in parser.hrefs:
        match = _RELEASE_HREF_RE.fullmatch(href)
        if match is None:
            continue
        release = DOLClaimsRelease(
            release_date=_release_date_from_stem(match.group("stem")),
            href=href,
            directory_year=int(match.group("directory_year")),
            extension=match.group("extension").lower(),
        )
        existing = releases.get(href)
        if existing is not None and existing != release:
            raise DOLClaimsArchiveError(f"conflicting DOL archive link: {href}")
        releases[href] = release
    if not releases:
        raise DOLClaimsArchiveError("DOL archive calendar contains no release links")
    return sorted(releases.values(), key=lambda item: (item.release_date, item.href))


def _normalize_text(value: str) -> str:
    value = html.unescape(value).replace("\u00a0", " ")
    value = re.sub(r"\bpre\s+vious\b", "previous", value, flags=re.IGNORECASE)
    value = re.sub(r"\ba\s+dvance\b", "advance", value, flags=re.IGNORECASE)
    value = re.sub(r"\badv\s+ance\b", "advance", value, flags=re.IGNORECASE)
    value = re.sub(r"(\d)\s+(\d{2,3},\d{3}\b)", r"\1\2", value)
    value = re.sub(r"(\d{1,3},\d)\s+(\d{2}\b)", r"\1\2", value)
    return " ".join(value.split())


def _resolve_week_ending(
    *,
    release_date: date,
    month_text: str,
    day: int,
    explicit_year: int | None,
) -> date:
    month = _MONTHS.get(month_text.rstrip(".").lower())
    if month is None:
        raise DOLClaimsArchiveError(f"unknown DOL claims month: {month_text}")
    if explicit_year is not None:
        try:
            candidate = date(explicit_year, month, day)
        except ValueError as exc:
            raise DOLClaimsArchiveError(
                f"{release_date}: invalid explicit claims reference date "
                f"{month_text} {day}, {explicit_year}"
            ) from exc
    else:
        candidates = []
        for year in (release_date.year - 1, release_date.year):
            try:
                candidates.append(date(year, month, day))
            except ValueError:
                continue
        if not candidates:
            raise DOLClaimsArchiveError(
                f"{release_date}: invalid claims reference date {month_text} {day}"
            )
        eligible = [candidate for candidate in candidates if candidate <= release_date]
        if not eligible:
            raise DOLClaimsArchiveError("claims reference week occurs after release date")
        candidate = max(eligible)
    lag = (release_date - candidate).days
    if lag < 1 or lag > 14:
        raise DOLClaimsArchiveError(
            f"claims reference week {candidate} has implausible release lag {lag} days"
        )
    return candidate


def _integer(value: str) -> int:
    return int(value.replace(",", ""))


def parse_dol_claims_release_text(
    text: str,
    *,
    release_date: date,
) -> DOLClaimsReleaseValues:
    """Parse the advance and prior-week revised SA initial-claims values."""

    normalized = _normalize_text(text)
    current_match = _CURRENT_RE.search(normalized)
    if current_match is None:
        raise DOLClaimsArchiveError(
            f"{release_date}: seasonally adjusted initial-claims narrative not found"
        )
    current_week = _resolve_week_ending(
        release_date=release_date,
        month_text=current_match.group("month"),
        day=int(current_match.group("day")),
        explicit_year=(
            int(current_match.group("year")) if current_match.group("year") is not None else None
        ),
    )
    current_value = _integer(current_match.group("value"))
    following_text = normalized[current_match.end() : current_match.end() + 1_500]
    four_week_match = _FOUR_WEEK_AVERAGE_RE.search(following_text)
    if four_week_match is None:
        raise DOLClaimsArchiveError(
            f"{release_date}: published four-week initial-claims average not found"
        )
    four_week_average = _integer(four_week_match.group("value"))
    paragraph = following_text
    paragraph = re.split(
        r"\bThe\s+4\s*-\s*week\s+moving\s+average\b",
        paragraph,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    change_match = _CHANGE_RE.search(paragraph)
    revised_match = _REVISED_FROM_TO_RE.search(paragraph)
    if revised_match is not None:
        previous_value = _integer(revised_match.group("new"))
        previous_vintage_type = "revised"
        extraction_pattern = "advance_plus_explicit_revision_from_to"
    else:
        prior_direct = _PRIOR_DIRECT_RE.search(paragraph)
        if prior_direct is not None:
            previous_value = _integer(prior_direct.group("value"))
            previous_vintage_type = prior_direct.group("status").lower()
            extraction_pattern = f"advance_plus_direct_{previous_vintage_type}_value"
        else:
            prior_unlabeled = _PRIOR_UNLABELED_RE.search(paragraph)
            unchanged = _UNCHANGED_RE.search(paragraph)
            if prior_unlabeled is not None:
                previous_value = _integer(prior_unlabeled.group("value"))
                previous_vintage_type = "source_not_labeled"
                extraction_pattern = "advance_plus_direct_source_unlabeled_value"
            elif unchanged is not None:
                previous_value = current_value
                previous_vintage_type = (
                    unchanged.group("status").lower()
                    if unchanged.group("status") is not None
                    else "source_not_labeled"
                )
                extraction_pattern = (
                    f"advance_plus_unchanged_{previous_vintage_type}_value_inferred"
                )
            elif change_match is not None and _PRIOR_LEVEL_WITHOUT_VALUE_RE.search(paragraph):
                change = _integer(change_match.group("value"))
                previous_value = (
                    current_value - change
                    if change_match.group("direction").lower() == "increase"
                    else current_value + change
                )
                previous_vintage_type = "source_not_labeled"
                extraction_pattern = "advance_plus_change_implied_prior_value"
            else:
                raise DOLClaimsArchiveError(
                    f"{release_date}: previous-week reported initial-claims value not found"
                )

    if change_match is not None:
        change = _integer(change_match.group("value"))
        expected = (
            previous_value + change
            if change_match.group("direction").lower() == "increase"
            else previous_value - change
        )
        if current_value != expected:
            raise DOLClaimsArchiveError(
                f"{release_date}: claims arithmetic mismatch, {current_value=} {previous_value=} "
                f"{change_match.group('direction')}={change}"
            )
    return DOLClaimsReleaseValues(
        release_date=release_date,
        current_week=current_week,
        current_advance=current_value,
        previous_week=current_week - timedelta(days=7),
        previous_reported=previous_value,
        previous_vintage_type=previous_vintage_type,
        current_four_week_average=four_week_average,
        extraction_pattern=extraction_pattern,
    )


def _extract_release_text(payload: bytes, extension: str) -> str:
    if extension == "pdf":
        if not payload.startswith(b"%PDF"):
            raise DOLClaimsArchiveError("DOL PDF release is not a PDF document")
        reader = PdfReader(io.BytesIO(payload))
        if not reader.pages:
            raise DOLClaimsArchiveError("DOL PDF release has no pages")
        return "\n".join(
            page.extract_text() or "" for page in reader.pages[: min(3, len(reader.pages))]
        )
    document = payload.decode("utf-8", errors="replace")
    parser = _VisibleTextParser()
    parser.feed(document)
    return parser.text()


def parse_dol_claims_release(
    payload: bytes,
    *,
    release: DOLClaimsRelease,
) -> DOLClaimsReleaseValues:
    """Parse one official HTML/ASP/PDF release payload."""

    return parse_dol_claims_release_text(
        _extract_release_text(payload, release.extension),
        release_date=release.release_date,
    )


def _non_release_reason(payload: bytes, release: DOLClaimsRelease) -> str | None:
    """Identify an official archive placeholder without treating it as data."""

    text = _normalize_text(_extract_release_text(payload, release.extension))
    if text.lower().startswith("dummy file:"):
        return "official_dummy_placeholder"
    return None


def _release_timestamp(release_date: date) -> datetime:
    return datetime(
        release_date.year,
        release_date.month,
        release_date.day,
        8,
        30,
        tzinfo=_NEW_YORK,
    ).astimezone(UTC)


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
            next_start = (
                values[index + 1]["realtime_start"] if index + 1 < len(values) else None
            )
            row["realtime_end"] = (
                next_start - timedelta(days=1) if next_start is not None else None  # type: ignore[operator]
            )
            observations.append(VintageObservation.from_mapping(row))
    return sorted(
        observations,
        key=lambda item: (item.observation_date, item.realtime_start),
    )


def _manifest_release(entry: Mapping[str, object]) -> DOLClaimsRelease:
    release = DOLClaimsRelease(
        release_date=date.fromisoformat(str(entry["release_date"])),
        href=str(entry["href"]),
        directory_year=int(entry["directory_year"]),
        extension=str(entry["extension"]),
    )
    if release.relative_path.as_posix() != str(entry["path"]):
        raise DOLClaimsArchiveError(f"manifest path does not match href: {release.href}")
    return release


def parse_dol_claims_archive(directory: str | Path) -> list[VintageObservation]:
    """Parse an acquired, manifest-hashed archive into canonical vintage rows."""

    root = Path(directory).resolve()
    manifest_path = root / "release-index.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DOLClaimsArchiveError("DOL claims release-index.json is missing or invalid") from exc
    raw_rows: list[dict[str, object]] = []
    for entry in manifest.get("releases", []):
        release = _manifest_release(entry)
        path = root / release.relative_path
        payload = path.read_bytes()
        digest = _sha256_bytes(payload)
        if digest != str(entry["sha256"]):
            raise DOLClaimsArchiveError(f"DOL claims hash mismatch: {release.href}")
        parsed = parse_dol_claims_release(payload, release=release)
        available_at = _release_timestamp(release.release_date)
        common = {
            "realtime_start": release.release_date,
            "availability_date": release.release_date,
            "release_timestamp": available_at,
            "availability_timestamp": available_at,
            "units": "claims",
            "frequency": "weekly",
            "seasonal_adjustment": "seasonally_adjusted",
            "transformation": "level",
            "download_timestamp": datetime.fromtimestamp(path.stat().st_mtime, UTC),
            "source": DOL_CLAIMS_SOURCE,
            "provenance_label": DOL_CLAIMS_PROVENANCE,
        }
        for series_id, observation_date, value, vintage_type in (
            (DOL_CLAIMS_SERIES_ID, parsed.current_week, parsed.current_advance, "advance"),
            (
                DOL_CLAIMS_SERIES_ID,
                parsed.previous_week,
                parsed.previous_reported,
                parsed.previous_vintage_type,
            ),
            (
                DOL_CLAIMS_4WMA_SERIES_ID,
                parsed.current_week,
                parsed.current_four_week_average,
                "published_4_week_moving_average",
            ),
        ):
            raw_rows.append(
                {
                    **common,
                    "series_id": series_id,
                    "observation_date": observation_date,
                    "value": float(value),
                    "source_metadata": {
                        "agency": (
                            "U.S. Department of Labor, Employment and Training Administration"
                        ),
                        "agency_series": "Seasonally Adjusted Initial Claims",
                        "official_url": release.official_url,
                        "source_file": release.relative_path.as_posix(),
                        "source_sha256": digest,
                        "release_date": release.release_date.isoformat(),
                        "scheduled_release_time": "08:30 America/New_York",
                        "timing_quality": DOL_CLAIMS_TIMING_QUALITY,
                        "vintage_type": vintage_type,
                        "extraction_pattern": parsed.extraction_pattern,
                        "public_domain_policy": DOL_PUBLIC_DOMAIN_URL,
                    },
                }
            )
    if not raw_rows:
        raise DOLClaimsArchiveError("DOL claims manifest contains no parsed releases")
    return _rows_with_realtime_ends(raw_rows)


def audit_dol_claims_archive(directory: str | Path) -> dict[str, object]:
    """Verify inventory, hashes, formats, parseability, dates, and coverage offline."""

    root = Path(directory).resolve()
    manifest_path = root / "release-index.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DOLClaimsArchiveError("DOL claims release-index.json is missing or invalid") from exc
    entries = manifest.get("releases")
    if not isinstance(entries, list) or not entries:
        raise DOLClaimsArchiveError("DOL claims manifest has no releases")
    excluded_entries = manifest.get("excluded_links", [])
    if not isinstance(excluded_entries, list):
        raise DOLClaimsArchiveError("DOL claims excluded-link inventory is invalid")
    expected: set[Path] = set()
    hashes: set[str] = set()
    canonical_hashes: set[str] = set()
    entries_by_href = {
        str(entry["href"]): entry
        for entry in [*entries, *excluded_entries]
        if isinstance(entry, Mapping)
    }
    formats: dict[str, int] = defaultdict(int)
    current_weeks: list[date] = []
    release_dates: list[date] = []
    for entry in [*entries, *excluded_entries]:
        if not isinstance(entry, Mapping):
            raise DOLClaimsArchiveError("DOL claims manifest release entry is invalid")
        release = _manifest_release(entry)
        path = root / release.relative_path
        expected.add(path.resolve())
        payload = path.read_bytes()
        digest = _sha256_bytes(payload)
        if digest != str(entry["sha256"]):
            raise DOLClaimsArchiveError(f"DOL claims hash mismatch: {release.href}")
        exclusion_reason = str(entry.get("exclusion_reason", ""))
        if digest in hashes and exclusion_reason != "duplicate_archive_alias":
            raise DOLClaimsArchiveError(f"duplicate DOL claims release content: {release.href}")
        hashes.add(digest)
        if entry in excluded_entries:
            if exclusion_reason == "duplicate_archive_alias":
                alias_of = entries_by_href.get(str(entry.get("alias_of")))
                if alias_of is None or str(alias_of.get("sha256")) != digest:
                    raise DOLClaimsArchiveError(f"invalid DOL alias: {release.href}")
            else:
                reason = _non_release_reason(payload, release)
                if reason != exclusion_reason:
                    raise DOLClaimsArchiveError(f"invalid DOL exclusion: {release.href}")
        else:
            if digest in canonical_hashes:
                raise DOLClaimsArchiveError(
                    f"duplicate canonical DOL claims release content: {release.href}"
                )
            canonical_hashes.add(digest)
            parsed = parse_dol_claims_release(payload, release=release)
            if parsed.release_date != release.release_date:
                raise DOLClaimsArchiveError("parsed DOL release date changed")
            current_weeks.append(parsed.current_week)
            release_dates.append(release.release_date)
            formats[release.extension] += 1
    actual = {path.resolve() for path in (root / "press").glob("*/*") if path.is_file()}
    missing = sorted(str(path.relative_to(root)) for path in expected - actual)
    extra = sorted(str(path.relative_to(root)) for path in actual - expected)
    if missing or extra:
        raise DOLClaimsArchiveError(
            f"DOL claims inventory mismatch: missing={missing[:3]}, extra={extra[:3]}"
        )
    observations = parse_dol_claims_archive(root)
    release_lags = [
        (release_date - current_week).days
        for release_date, current_week in zip(release_dates, current_weeks, strict=True)
    ]
    return {
        "passed": True,
        "official_url": DOL_CLAIMS_ARCHIVE_URL,
        "public_domain_policy": DOL_PUBLIC_DOMAIN_URL,
        "directory": root.name,
        "archive_link_count": len(entries) + len(excluded_entries),
        "release_count": len(entries),
        "excluded_non_release_links": len(excluded_entries),
        "canonical_vintage_rows": len(observations),
        "first_release_date": min(release_dates).isoformat(),
        "last_release_date": max(release_dates).isoformat(),
        "first_observation_date": min(current_weeks).isoformat(),
        "last_observation_date": max(current_weeks).isoformat(),
        "formats": dict(sorted(formats.items())),
        "all_canonical_hashes_unique": len(canonical_hashes) == len(entries),
        "minimum_release_lag_days": min(release_lags),
        "maximum_release_lag_days": max(release_lags),
        "timing_quality": DOL_CLAIMS_TIMING_QUALITY,
        "current_prior_and_published_four_week_average_values_parsed": True,
        "server_original_bytes_claimed": True,
        "provenance_status": "official_archive_inventory_hashes_and_release_values_verified",
    }


def _fetch(
    url: str,
    *,
    data: bytes | None = None,
    attempts: int = 5,
) -> tuple[bytes, str]:
    for attempt in range(attempts):
        request = Request(
            url,
            data=data,
            headers={
                "User-Agent": _USER_AGENT,
                "Referer": DOL_CLAIMS_ARCHIVE_URL,
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST" if data is not None else "GET",
        )
        try:
            with urlopen(request, timeout=60) as response:
                return response.read(), response.headers.get_content_type()
        except HTTPError as exc:
            if exc.code not in {429, 500, 502, 503, 504} or attempt == attempts - 1:
                raise DOLClaimsArchiveError(f"DOL request failed: {url} ({exc.code})") from exc
            retry_after = exc.headers.get("Retry-After")
            delay = float(retry_after) if retry_after and retry_after.isdigit() else 2**attempt
        except (TimeoutError, URLError) as exc:
            if attempt == attempts - 1:
                raise DOLClaimsArchiveError(f"DOL request failed: {url}") from exc
            delay = 2**attempt
        time.sleep(min(delay, 16))
    raise AssertionError("unreachable")


def _write_immutable(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise DOLClaimsArchiveError(f"refusing to replace immutable raw file: {path}")
        return
    temporary = path.with_suffix(f"{path.suffix}.part")
    temporary.write_bytes(payload)
    temporary.replace(path)


def acquire_dol_claims_archive(
    output_dir: str | Path,
    *,
    start_year: int = 2002,
    end_year: int | None = None,
    workers: int = 4,
) -> dict[str, object]:
    """Acquire the complete selected official archive with resumable raw writes."""

    final_year = end_year or datetime.now(UTC).year
    if start_year < 2002 or final_year < start_year:
        raise ValueError("DOL archive years must satisfy 2002 <= start_year <= end_year")
    if workers < 1 or workers > 8:
        raise ValueError("workers must be between 1 and 8")
    root = Path(output_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    releases_by_href: dict[str, DOLClaimsRelease] = {}
    index_records: list[dict[str, object]] = []
    for year in range(start_year, final_year + 1):
        index_path = root / "index" / f"{year}.html"
        if index_path.exists():
            payload = index_path.read_bytes()
        else:
            payload, _ = _fetch(
                DOL_CLAIMS_INDEX_URL,
                data=urlencode({"report": "press", "year": year, "submit": "Submit"}).encode(),
            )
            _write_immutable(index_path, payload)
        releases = parse_dol_claims_archive_index(payload)
        for release in releases:
            if start_year <= release.release_date.year <= final_year:
                releases_by_href[release.href] = release
        index_records.append(
            {
                "year": year,
                "path": index_path.relative_to(root).as_posix(),
                "sha256": _sha256_bytes(payload),
                "release_links": len(releases),
            }
        )

    ordered = sorted(releases_by_href.values(), key=lambda item: (item.release_date, item.href))
    if not ordered:
        raise DOLClaimsArchiveError("selected DOL archive years contain no releases")

    def download(
        release: DOLClaimsRelease,
    ) -> tuple[DOLClaimsRelease, bytes, str, str | None]:
        path = root / release.relative_path
        if path.exists():
            payload = path.read_bytes()
            content_type = "application/pdf" if release.extension == "pdf" else "text/html"
        else:
            payload, content_type = _fetch(release.official_url)
            _write_immutable(path, payload)
            time.sleep(0.05)
        try:
            parse_dol_claims_release(payload, release=release)
            exclusion_reason = None
        except DOLClaimsArchiveError:
            exclusion_reason = _non_release_reason(payload, release)
            if exclusion_reason is None:
                raise
        return release, payload, content_type, exclusion_reason

    completed: dict[str, dict[str, object]] = {}
    parse_errors: list[str] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(download, release): release for release in ordered}
        for future in as_completed(futures):
            try:
                release, payload, content_type, exclusion_reason = future.result()
            except Exception as exc:  # collect every archive-format failure in one pass
                failed_release = futures[future]
                parse_errors.append(f"{failed_release.href}: {exc}")
                continue
            completed[release.href] = {
                "release_date": release.release_date.isoformat(),
                "href": release.href,
                "url": release.official_url,
                "directory_year": release.directory_year,
                "extension": release.extension,
                "content_type": content_type,
                "path": release.relative_path.as_posix(),
                "bytes": len(payload),
                "sha256": _sha256_bytes(payload),
            }
            if exclusion_reason is not None:
                completed[release.href]["exclusion_reason"] = exclusion_reason
    if parse_errors:
        details = "\n".join(sorted(parse_errors)[:20])
        raise DOLClaimsArchiveError(
            f"{len(parse_errors)} DOL archive releases failed validation:\n{details}"
        )

    by_release_date: dict[date, list[DOLClaimsRelease]] = defaultdict(list)
    for release in ordered:
        if "exclusion_reason" not in completed[release.href]:
            by_release_date[release.release_date].append(release)
    for release_date, candidates in by_release_date.items():
        if len(candidates) < 2:
            continue
        hashes = {str(completed[candidate.href]["sha256"]) for candidate in candidates}
        if len(hashes) != 1:
            raise DOLClaimsArchiveError(
                f"conflicting DOL releases share date {release_date}: "
                f"{[candidate.href for candidate in candidates]}"
            )
        canonical = min(
            candidates,
            key=lambda candidate: (
                candidate.directory_year != release_date.year,
                candidate.href,
            ),
        )
        for candidate in candidates:
            if candidate == canonical:
                continue
            completed[candidate.href]["exclusion_reason"] = "duplicate_archive_alias"
            completed[candidate.href]["alias_of"] = canonical.href

    manifest_path = root / "release-index.json"
    existing_manifest = (
        json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest_path.exists()
        else None
    )
    acquired_at = (
        str(existing_manifest.get("acquired_at"))
        if isinstance(existing_manifest, Mapping) and existing_manifest.get("acquired_at")
        else datetime.now(UTC).isoformat().replace("+00:00", "Z")
    )
    manifest = {
        "schema_version": 1,
        "status": "downloaded_and_parse_checked",
        "source_url": DOL_CLAIMS_ARCHIVE_URL,
        "index_url": DOL_CLAIMS_INDEX_URL,
        "public_domain_policy": DOL_PUBLIC_DOMAIN_URL,
        "operator_opt_in_basis": "user_requested_acquisition_and_verification",
        "api_credentials_used": False,
        "api_txt_read": False,
        "acquired_at": acquired_at,
        "start_year": start_year,
        "end_year": final_year,
        "index_pages": index_records,
        "archive_link_count": len(ordered),
        "release_count": sum(
            "exclusion_reason" not in completed[release.href] for release in ordered
        ),
        "excluded_non_release_links": sum(
            "exclusion_reason" in completed[release.href] for release in ordered
        ),
        "releases": [
            completed[release.href]
            for release in ordered
            if "exclusion_reason" not in completed[release.href]
        ],
        "excluded_links": [
            completed[release.href]
            for release in ordered
            if "exclusion_reason" in completed[release.href]
        ],
    }
    if isinstance(existing_manifest, Mapping):
        existing_files = {
            str(entry["href"]): str(entry["sha256"])
            for entry in [
                *existing_manifest.get("releases", []),
                *existing_manifest.get("excluded_links", []),
            ]
        }
        new_files = {
            str(entry["href"]): str(entry["sha256"])
            for entry in [*manifest["releases"], *manifest["excluded_links"]]
        }
        if existing_files and existing_files != new_files:
            raise DOLClaimsArchiveError(
                "refusing to rewrite DOL inventory after raw file hashes changed"
            )
    temporary_manifest = manifest_path.with_suffix(".json.part")
    temporary_manifest.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary_manifest.replace(manifest_path)
    audit = audit_dol_claims_archive(root)
    return {
        "status": "verified",
        "output_dir": root,
        "release_count": audit["release_count"],
        "canonical_vintage_rows": audit["canonical_vintage_rows"],
        "first_release_date": audit["first_release_date"],
        "last_release_date": audit["last_release_date"],
        "formats": audit["formats"],
    }


__all__ = [
    "DOL_CLAIMS_4WMA_SERIES_ID",
    "DOL_CLAIMS_ARCHIVE_URL",
    "DOL_CLAIMS_DIRECTORY",
    "DOL_CLAIMS_PROVENANCE",
    "DOL_CLAIMS_SERIES_ID",
    "DOL_CLAIMS_SOURCE",
    "DOL_CLAIMS_TIMING_QUALITY",
    "DOL_PUBLIC_DOMAIN_URL",
    "DOLClaimsArchiveError",
    "DOLClaimsRelease",
    "DOLClaimsReleaseValues",
    "acquire_dol_claims_archive",
    "audit_dol_claims_archive",
    "parse_dol_claims_archive",
    "parse_dol_claims_archive_index",
    "parse_dol_claims_release",
    "parse_dol_claims_release_text",
]
