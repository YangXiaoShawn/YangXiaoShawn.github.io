"""USITC Harmonized Tariff Schedule adapter.

Source: ``https://hts.usitc.gov/reststop/exportList`` (public, no key).

Supplies two things the rest of the project needs:

1. **Baseline column-1 general (MFN) ad valorem rates.** Section 301 duties are
   *additive* to these. A study that reports "the tariff rose to 25%" without the
   baseline is reporting the wrong number: for a line with a 4.4% MFN rate the
   total went to 29.4%.

2. **The universe of 8-digit lines beneath each HS6 heading.** Without it the
   tariff engine cannot answer honestly whether an HS6 heading is fully or only
   partly covered by an action.

Rate parsing is deliberately conservative. ``"Free"`` is 0. ``"4.4%"`` is 0.044.
Compound and specific rates (``"2.5 cents/kg"``, ``"7.5% + 1.4 cents/kg"``) are
**not** converted to an ad valorem equivalent, because doing so requires unit
values and would silently mix a measured quantity into what is presented as a
statutory rate. They are returned as ``None`` with the original string kept.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from ..tariff.engine import BaselineRateSource
from .base import cached_get

HTS_EXPORT = "https://hts.usitc.gov/reststop/exportList"

_PURE_AD_VALOREM = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*%\s*$")
_FREE = re.compile(r"^\s*free\s*$", re.IGNORECASE)


@dataclass(slots=True)
class HTSLine:
    hts10: str | None
    hts8: str
    description: str
    general_rate_text: str
    general_ad_valorem: float | None
    rate_is_pure_ad_valorem: bool
    units: list[str] = field(default_factory=list)
    special_rate_text: str = ""
    other_rate_text: str = ""

    @property
    def hs6(self) -> str:
        return self.hts8[:6]


def parse_rate(text: str) -> tuple[float | None, bool]:
    """Parse an HTS duty-rate string into an ad valorem fraction.

    Returns ``(rate, is_pure_ad_valorem)``. Non-ad-valorem and compound rates
    return ``(None, False)`` rather than a fabricated equivalent.
    """
    if text is None:
        return None, False
    s = text.strip()
    if not s:
        return None, False
    if _FREE.match(s):
        return 0.0, True
    m = _PURE_AD_VALOREM.match(s)
    if m:
        return float(m.group(1)) / 100.0, True
    return None, False


def parse_export_json(payload: bytes | str) -> list[HTSLine]:
    """Parse an ``exportList`` JSON payload into 8-digit lines.

    The export is a flat list of rows at mixed indent levels; only rows whose
    ``htsno`` has at least 8 digits carry a duty rate. Rows are deduplicated to
    the 8-digit line, keeping the first rate seen.
    """
    rows = json.loads(payload) if isinstance(payload, (bytes, str)) else payload
    seen: dict[str, HTSLine] = {}
    for r in rows:
        raw = (r.get("htsno") or "").strip()
        digits = raw.replace(".", "")
        if len(digits) < 8 or not digits.isdigit():
            continue
        hts8 = digits[:8]
        general = (r.get("general") or "").strip()
        rate, pure = parse_rate(general)
        if hts8 in seen:
            # Keep the first (most aggregated) row that actually carries a rate.
            if seen[hts8].general_ad_valorem is None and rate is not None:
                seen[hts8].general_ad_valorem = rate
                seen[hts8].rate_is_pure_ad_valorem = pure
                seen[hts8].general_rate_text = general
            continue
        seen[hts8] = HTSLine(
            hts10=digits if len(digits) == 10 else None,
            hts8=hts8,
            description=(r.get("description") or "").strip(),
            general_rate_text=general,
            general_ad_valorem=rate,
            rate_is_pure_ad_valorem=pure,
            units=list(r.get("units") or []),
            special_rate_text=(r.get("special") or "").strip(),
            other_rate_text=(r.get("other") or "").strip(),
        )
    return sorted(seen.values(), key=lambda x: x.hts8)


def fetch_range(
    from_code: str, to_code: str, *, force: bool = False, cache_tag: str = ""
) -> Path:
    """Fetch an HTS code range. ``from_code``/``to_code`` are dotted, e.g. ``8471.30.00``."""
    tag = cache_tag or f"{from_code}_{to_code}".replace(".", "")
    res = cached_get(
        HTS_EXPORT,
        f"hts_{tag}.json",
        params={"from": from_code, "to": to_code, "format": "JSON", "styles": "false"},
        subdir="usitc_hts",
        timeout=180.0,
        force=force,
    )
    return res.path


def fetch_chapter(chapter: str, *, force: bool = False) -> Path:
    """Fetch a whole 2-digit HTS chapter."""
    ch = chapter.zfill(2)
    return fetch_range(f"{ch}01.00.00", f"{ch}99.99.99", force=force, cache_tag=f"ch{ch}")


def load_chapters(chapters: list[str], *, force: bool = False) -> list[HTSLine]:
    out: list[HTSLine] = []
    for ch in sorted(set(chapters)):
        p = fetch_chapter(ch, force=force)
        try:
            out.extend(parse_export_json(p.read_bytes()))
        except json.JSONDecodeError:
            continue
    return out


def baseline_source(lines: list[HTSLine], vintage_year: int) -> BaselineRateSource:
    """Build a :class:`BaselineRateSource` from parsed HTS lines."""
    src = BaselineRateSource()
    for ln in lines:
        if ln.general_ad_valorem is not None:
            src.add(ln.hts8, vintage_year, ln.general_ad_valorem)
    return src


def hs6_children(lines: list[HTSLine]) -> dict[str, list[str]]:
    """Map each HS6 heading to the 8-digit lines that exist beneath it."""
    out: dict[str, list[str]] = {}
    for ln in lines:
        out.setdefault(ln.hs6, [])
        if ln.hts8 not in out[ln.hs6]:
            out[ln.hs6].append(ln.hts8)
    return {k: sorted(v) for k, v in out.items()}


def resolve_truncated_codes(
    truncated: list[str],
    already_covered: set[str],
    hts_lines: list[HTSLine],
) -> tuple[dict[str, str], list[str]]:
    """Resolve codes whose last two digits were lost in PDF typesetting.

    A truncated code such as ``9033.00`` is resolved **only** when the HTS
    contains exactly one 8-digit line beneath that 6-digit heading that is not
    already in the covered list. That is a deduction from an official source,
    not a guess, and the resolved record is marked ``DERIVED`` confidence.
    Anything ambiguous stays unresolved.

    Returns ``({truncated: resolved_hts8}, still_unresolved)``.
    """
    by_hs6: dict[str, list[str]] = {}
    for ln in hts_lines:
        by_hs6.setdefault(ln.hs6, []).append(ln.hts8)

    resolved: dict[str, str] = {}
    unresolved: list[str] = []
    for t in truncated:
        hs6 = t.replace(".", "")[:6]
        candidates = sorted(set(by_hs6.get(hs6, [])) - already_covered)
        if len(candidates) == 1:
            resolved[t] = candidates[0]
        else:
            unresolved.append(t)
    return resolved, unresolved
