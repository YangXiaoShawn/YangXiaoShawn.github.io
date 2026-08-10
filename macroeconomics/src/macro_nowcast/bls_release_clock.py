"""Strict release-clock extraction from archived official BLS news pages.

The parser treats the printed embargo header as the evidence.  It verifies the
calendar date, weekday, and the EST/EDT label against America/New_York before
returning a UTC instant.  A known source-header conflict remains date-only; the
code never guesses which conflicting timezone representation BLS intended.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from html.parser import HTMLParser
from pathlib import Path
from types import MappingProxyType
from typing import Final
from zoneinfo import ZoneInfo

BLS_EMBARGO_CLOCK_TIMING_QUALITY: Final = (
    "official_embargo_header_clock_America_New_York"
)
BLS_EMPSIT_CLOCK_SOURCE: Final = "BLS_EMPLOYMENT_SITUATION_DOM_ARCHIVE"

_NEW_YORK = ZoneInfo("America/New_York")
_EMPSIT_FILENAME_RE = re.compile(r"empsit_(\d{2})(\d{2})(\d{4})\.htm")
_CLOCK_RE = re.compile(
    r"(?P<hour>\d{1,2}):(?P<minute>\d{2})\s*"
    r"(?P<meridiem>a\.?\s*m\.?|p\.?\s*m\.?)\s*"
    r"\((?P<timezone>EST|EDT|ET)\)",
    re.IGNORECASE,
)
_DATE_RE = re.compile(
    r"(?:(?P<weekday>Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)"
    r"\s*,?\s*)?"
    r"(?P<month>January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+"
    r"(?P<day>\d{1,2})(?:,\s*|\s+)(?P<year>\d{4})",
    re.IGNORECASE,
)
_KNOWN_EMPSIT_CLOCK_EXCLUSIONS: Final[Mapping[date, str]] = MappingProxyType(
    {
        date(2012, 12, 7): (
            "official_header_EDT_conflicts_with_America_New_York_EST"
        ),
    }
)


class BLSReleaseClockError(ValueError):
    """Raised when an official embargo header cannot prove one release instant."""


class _VisibleTextParser(HTMLParser):
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

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self.ignored_depth:
            self.ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self.ignored_depth:
            self.parts.append(data)

    def text(self) -> str:
        return " ".join("".join(self.parts).split())


@dataclass(frozen=True, slots=True)
class BLSReleaseClock:
    """One release instant proven by an archived BLS embargo header."""

    release_date: date
    release_timestamp: datetime
    printed_timezone: str
    printed_weekday: str | None
    timing_quality: str = BLS_EMBARGO_CLOCK_TIMING_QUALITY


@dataclass(frozen=True, slots=True)
class BLSEmpsitClockArchive:
    """Verified clocks plus explicitly retained date-only source anomalies."""

    clocks: Mapping[date, BLSReleaseClock]
    exclusions: Mapping[date, str]


def _visible_text(document: str) -> str:
    parser = _VisibleTextParser()
    parser.feed(document)
    parser.close()
    return parser.text()


def parse_bls_embargo_header(
    document: str,
    *,
    expected_release_date: date,
) -> BLSReleaseClock:
    """Parse and verify the first official embargo header in one BLS page."""

    text = _visible_text(document)
    embargo_start = text.lower().find("embargoed")
    if embargo_start < 0:
        raise BLSReleaseClockError("official page has no embargoed header")
    header = text[embargo_start : embargo_start + 500]
    clock_match = _CLOCK_RE.search(header)
    if clock_match is None:
        raise BLSReleaseClockError("official embargo header has no clock with ET label")
    date_match = _DATE_RE.search(header, clock_match.end())
    if date_match is None:
        raise BLSReleaseClockError("official embargo header has no release date")

    parsed_date = datetime.strptime(
        "{} {} {}".format(
            date_match.group("month").title(),
            date_match.group("day"),
            date_match.group("year"),
        ),
        "%B %d %Y",
    ).date()
    if parsed_date != expected_release_date:
        raise BLSReleaseClockError(
            "official embargo date mismatch: "
            f"expected {expected_release_date}, found {parsed_date}"
        )
    printed_weekday = date_match.group("weekday")
    if printed_weekday is not None and parsed_date.strftime("%A").lower() != (
        printed_weekday.lower()
    ):
        raise BLSReleaseClockError(
            "official embargo weekday conflicts with its printed date"
        )

    hour = int(clock_match.group("hour"))
    minute = int(clock_match.group("minute"))
    if not 1 <= hour <= 12 or not 0 <= minute <= 59:
        raise BLSReleaseClockError("official embargo clock is outside 12-hour bounds")
    meridiem = re.sub(r"[.\s]", "", clock_match.group("meridiem")).lower()
    if meridiem == "pm" and hour != 12:
        hour += 12
    elif meridiem == "am" and hour == 12:
        hour = 0
    local = datetime(
        parsed_date.year,
        parsed_date.month,
        parsed_date.day,
        hour,
        minute,
        tzinfo=_NEW_YORK,
    )
    printed_timezone = clock_match.group("timezone").upper()
    if printed_timezone in {"EST", "EDT"} and local.tzname() != printed_timezone:
        raise BLSReleaseClockError(
            "official embargo timezone label conflicts with America/New_York: "
            f"printed {printed_timezone}, calendar implies {local.tzname()}"
        )
    return BLSReleaseClock(
        release_date=parsed_date,
        release_timestamp=local.astimezone(UTC),
        printed_timezone=printed_timezone,
        printed_weekday=printed_weekday,
    )


def parse_empsit_release_clock_file(path: str | Path) -> BLSReleaseClock:
    """Parse one dated Employment Situation archive file and verify its filename."""

    source = Path(path)
    match = _EMPSIT_FILENAME_RE.fullmatch(source.name)
    if match is None:
        raise BLSReleaseClockError(
            f"unexpected Employment Situation archive filename: {source.name}"
        )
    expected = date(int(match.group(3)), int(match.group(1)), int(match.group(2)))
    return parse_bls_embargo_header(
        source.read_text(encoding="utf-8"),
        expected_release_date=expected,
    )


def parse_empsit_release_clock_archive(
    directory: str | Path,
) -> BLSEmpsitClockArchive:
    """Verify every local Employment Situation clock, allowing only known conflicts."""

    source_directory = Path(directory)
    clocks: dict[date, BLSReleaseClock] = {}
    exclusions: dict[date, str] = {}
    paths = sorted(source_directory.glob("empsit_*.htm"))
    if not paths:
        raise BLSReleaseClockError("no Employment Situation archive files found")
    for path in paths:
        match = _EMPSIT_FILENAME_RE.fullmatch(path.name)
        if match is None:
            raise BLSReleaseClockError(
                f"unexpected Employment Situation archive filename: {path.name}"
            )
        release_date = date(
            int(match.group(3)),
            int(match.group(1)),
            int(match.group(2)),
        )
        try:
            clock = parse_empsit_release_clock_file(path)
        except BLSReleaseClockError as exc:
            expected_reason = _KNOWN_EMPSIT_CLOCK_EXCLUSIONS.get(release_date)
            actual_reason = str(exc)
            if (
                expected_reason is None
                or "timezone label conflicts" not in actual_reason
                or "printed EDT" not in actual_reason
                or "calendar implies EST" not in actual_reason
            ):
                raise
            exclusions[release_date] = expected_reason
            continue
        if release_date in _KNOWN_EMPSIT_CLOCK_EXCLUSIONS:
            raise BLSReleaseClockError(
                "known Employment Situation clock conflict unexpectedly disappeared: "
                f"{release_date}"
            )
        if release_date in clocks:
            raise BLSReleaseClockError(f"duplicate Employment Situation release: {release_date}")
        clocks[release_date] = clock
    expected_exclusions = set(_KNOWN_EMPSIT_CLOCK_EXCLUSIONS) & {
        date(int(match.group(3)), int(match.group(1)), int(match.group(2)))
        for path in paths
        if (match := _EMPSIT_FILENAME_RE.fullmatch(path.name)) is not None
    }
    if set(exclusions) != expected_exclusions:
        raise BLSReleaseClockError("known Employment Situation exclusions were not reproduced")
    return BLSEmpsitClockArchive(
        clocks=MappingProxyType(clocks),
        exclusions=MappingProxyType(exclusions),
    )


__all__ = [
    "BLS_EMBARGO_CLOCK_TIMING_QUALITY",
    "BLS_EMPSIT_CLOCK_SOURCE",
    "BLSEmpsitClockArchive",
    "BLSReleaseClock",
    "BLSReleaseClockError",
    "parse_bls_embargo_header",
    "parse_empsit_release_clock_archive",
    "parse_empsit_release_clock_file",
]
