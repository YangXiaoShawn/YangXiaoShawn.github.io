"""USTR Section 301 product-exclusion notices.

What this adapter does, and why it does so little
-------------------------------------------------

USTR granted product exclusions from the Section 301 duties in a series of
Federal Register notices. Each notice states, in its own prose, that its
exclusions take one of two forms::

    "the exclusions are established in two different formats: (1) As an
    exclusion of an existing 10-digit subheading from within an 8-digit
    subheading covered by the $34 billion action, or (2) as an exclusion
    reflected in specially prepared product descriptions."
                                            -- 83 FR 67463

Only the first form can be mapped to trade data. The second describes a product
by physical characteristics ("machines of a kind used for..., weighing less
than X kg") that identify a *subset* of a statistical reporting number. U.S.
import statistics are published at the statistical reporting number and no
finer, so there is no way to determine which of a line's imports were excluded.

Across the eleven exclusion notices covering this project's sample window, the
notices' own stated counts are **16 ten-digit subheadings against 824 specially
prepared product descriptions** -- 1.9% mappable. This is not a parser
limitation that better engineering would fix. Exclusions are granted at a
finer granularity than trade data is reported, so the adjustment cannot be made
from published statistics at all.

Two further obstacles, recorded because they would otherwise look like gaps
someone should close:

* The annexes listing exclusions are embedded **raster images** in the Federal
  Register PDFs (``[GRAPHIC] [TIFF OMITTED]``), with no text layer. Unlike the
  List 1-3 annexes, which are typeset text, they cannot be parsed without OCR.
  OCR is not used here: it would introduce an unvalidatable transcription
  channel into a legal treatment variable, which is the same reason a code
  damaged by typesetting is never repaired by guessing (see D-005).
* The USITC HTS exposes the exclusion headings (9903.88.05 onward) but their
  descriptions only *reference* U.S. notes 20(h), 20(i), ...; the enumerated
  product lists live in the note text, which the export endpoint does not
  return.

What the adapter therefore extracts is the part that **is** machine-readable
and decision-relevant: each notice's own stated split between mappable and
prose-only exclusions, and the date the exclusions are retroactive to. That
turns an unparseable input into a quantified bound on how far the project's
intention-to-treat estimates can be from treatment-on-the-treated.

Retroactivity matters and is captured. Exclusions "apply as of the [date]
effective date" of the underlying action -- not the publication date -- and
"extend for one year after the publication of this notice". So the exclusion
window is [action effective date, publication + 1 year), which is another
instance of the rule that announcement, publication and effective dates are
three different facts.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import polars as pl

from .base import FetchResult, cached_get

GOVINFO_PDF = "https://www.govinfo.gov/content/pkg/FR-{pub}/pdf/{doc}.pdf"

_WORD_NUMBERS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20,
}

_FORM = re.compile(r"exclusions?\s+take\s+the\s+form\s+of\s+([^.]{0,220})\.", re.IGNORECASE)
_TEN_DIGIT = re.compile(
    r"([\w,]+)\s+(?:existing\s+)?10-digit\s+HTSUS\s+subheadings?", re.IGNORECASE
)
_PROSE = re.compile(
    r"([\w,]+)\s+specially\s+prepared\s+product\s+descriptions?", re.IGNORECASE
)
_RETROACTIVE = re.compile(
    r"apply\s+as\s+of\s+(?:the\s+)?([A-Z][a-z]+\s+\d{1,2},\s+\d{4})", re.IGNORECASE
)
_DURATION = re.compile(
    r"extend\s+for\s+(one\s+year|\d+\s+years?)\s+after\s+the\s+publication", re.IGNORECASE
)
_TEN_DIGIT_CODE = re.compile(r"\b(\d{4})\.(\d{2})\.(\d{2})\.(\d{2})\b")


def _to_int(token: str | None) -> int | None:
    if not token:
        return None
    t = token.strip().lower().replace(",", "")
    if t.isdigit():
        return int(t)
    return _WORD_NUMBERS.get(t)


@dataclass(slots=True)
class ExclusionNotice:
    """What a single exclusion notice tells us about itself."""

    document_number: str
    publication_date: str
    citation: str = ""
    n_ten_digit_exclusions: int | None = None
    """Exclusions expressed as a 10-digit subheading. Mappable to trade data."""
    n_prose_exclusions: int | None = None
    """Exclusions expressed as a product description. NOT mappable."""
    retroactive_to: str | None = None
    """Exclusions apply from this date, not from publication."""
    expires: str | None = None
    parsed_ten_digit_codes: list[str] = field(default_factory=list)
    """10-digit codes actually recovered from the PDF text layer. Normally empty:
    the annexes are raster images."""
    annex_is_image_only: bool = True
    checksum_sha256: str = ""
    warnings: list[str] = field(default_factory=list)

    @property
    def n_total(self) -> int | None:
        if self.n_ten_digit_exclusions is None and self.n_prose_exclusions is None:
            return None
        return (self.n_ten_digit_exclusions or 0) + (self.n_prose_exclusions or 0)

    @property
    def mappable_share(self) -> float | None:
        tot = self.n_total
        if not tot:
            return None
        return (self.n_ten_digit_exclusions or 0) / tot

    def to_row(self) -> dict:
        d = asdict(self)
        d["n_total"] = self.n_total
        d["mappable_share"] = self.mappable_share
        d["parsed_ten_digit_codes"] = "|".join(self.parsed_ten_digit_codes)
        d["warnings"] = " | ".join(self.warnings)
        return d


def _add_year(iso: str, years: int = 1) -> str:
    d = datetime.strptime(iso, "%Y-%m-%d").date()
    try:
        return d.replace(year=d.year + years).isoformat()
    except ValueError:  # 29 February
        return d.replace(year=d.year + years, day=28).isoformat()


def parse_notice(pdf_path: Path, document_number: str, publication_date: str) -> ExclusionNotice:
    """Extract a notice's self-reported structure. Pure function over a local file."""
    from pypdf import PdfReader

    reader = PdfReader(str(pdf_path))
    pages = [(p.extract_text() or "") for p in reader.pages]
    flat = re.sub(r"\s+", " ", "\n".join(pages))

    notice = ExclusionNotice(
        document_number=document_number, publication_date=publication_date
    )

    form = _FORM.search(flat)
    segment = form.group(1) if form else flat
    if not form:
        notice.warnings.append(
            "the 'exclusions take the form of' sentence was not found; counts were "
            "searched across the whole document and may pick up an unrelated figure"
        )
    ten = _TEN_DIGIT.search(segment)
    prose = _PROSE.search(segment)
    notice.n_ten_digit_exclusions = _to_int(ten.group(1) if ten else None)
    notice.n_prose_exclusions = _to_int(prose.group(1) if prose else None)
    if notice.n_ten_digit_exclusions is None and ten is None:
        # A notice with no 10-digit exclusions simply omits the clause.
        notice.n_ten_digit_exclusions = 0

    retro = _RETROACTIVE.search(flat)
    if retro:
        try:
            notice.retroactive_to = datetime.strptime(
                re.sub(r"\s+", " ", retro.group(1)), "%B %d, %Y"
            ).date().isoformat()
        except ValueError:
            notice.warnings.append(f"unparseable retroactive date {retro.group(1)!r}")
    else:
        notice.warnings.append("no retroactive-application date found")

    if _DURATION.search(flat):
        notice.expires = _add_year(publication_date, 1)
    else:
        notice.warnings.append("no explicit one-year duration clause found")

    codes = sorted({
        f"{a}{b}{c}{d}" for a, b, c, d in _TEN_DIGIT_CODE.findall("\n".join(pages))
    })
    notice.parsed_ten_digit_codes = codes
    notice.annex_is_image_only = not codes
    if notice.annex_is_image_only:
        notice.warnings.append(
            "annex carries no text layer (embedded raster image); the excluded "
            "10-digit subheadings cannot be recovered without OCR, which is not used"
        )
    return notice


def fetch_notice(
    document_number: str, publication_date: str, *, force: bool = False
) -> FetchResult:
    return cached_get(
        GOVINFO_PDF.format(pub=publication_date, doc=document_number),
        f"{document_number}.pdf",
        subdir="federal_register",
        timeout=300.0,
        force=force,
    )


def load_notices(
    notices: dict[str, str], *, offline_dir: Path | None = None
) -> list[ExclusionNotice]:
    """Parse a mapping of ``{document_number: publication_date}``."""
    out: list[ExclusionNotice] = []
    for doc, pub in sorted(notices.items(), key=lambda kv: (kv[1], kv[0])):
        if offline_dir is not None:
            path = Path(offline_dir) / f"{doc}.pdf"
            checksum = ""
        else:
            res = fetch_notice(doc, pub)
            path, checksum = res.path, res.sha256
        n = parse_notice(path, doc, pub)
        n.checksum_sha256 = checksum
        out.append(n)
    return out


def coverage_summary(notices: list[ExclusionNotice]) -> dict:
    """Aggregate what fraction of exclusions could ever be mapped to trade data."""
    ten = sum(n.n_ten_digit_exclusions or 0 for n in notices)
    prose = sum(n.n_prose_exclusions or 0 for n in notices)
    total = ten + prose
    return {
        "n_notices": len(notices),
        "n_ten_digit_exclusions": ten,
        "n_prose_exclusions": prose,
        "n_total_exclusions": total,
        "mappable_share": (ten / total) if total else None,
        "all_annexes_image_only": all(n.annex_is_image_only for n in notices),
        "earliest_retroactive_to": min(
            (n.retroactive_to for n in notices if n.retroactive_to), default=None
        ),
        "conclusion": (
            "Exclusions are granted at a finer granularity than U.S. import statistics are "
            "published. A specially prepared product description identifies a subset of a "
            "statistical reporting number, and trade data is reported at that number and no "
            "finer, so the share of a line's imports that was excluded is not observable. "
            "Exclusion adjustment therefore cannot be performed from published trade "
            "statistics, regardless of parsing effort. Estimates in this project remain "
            "intention-to-treat with respect to the statutory list, and that is a structural "
            "property of the data rather than an outstanding task."
        ),
    }


def realised_vs_statutory_bound(
    panel: pl.DataFrame,
    *,
    tolerance: float = 0.03,
    treated_country_col: str = "is_treated_country",
) -> pl.DataFrame | None:
    """Empirical bound on the intention-to-treat gap, month by month.

    Compares the duty Customs actually calculated against the duty the statutory
    schedule implies, on treated flows with a positive modelled rate. The share
    of value where the realised rate falls materially short is an **upper bound**
    on the share affected by exclusions: preference programmes, duty-free entry
    under Chapter 98 provisions, and in-quota entries produce the same signature.

    Exclusions from the first notice apply retroactively from 2018-07-06 but were
    only granted from 2018-12-28 onward, so a gap that widens after that date is
    consistent with exclusions taking effect; a gap present before it is not.
    """
    import polars as pl

    # Condition on a positive **additional** duty, not a positive total rate.
    # The total includes the baseline MFN rate, so filtering on it admitted
    # ordinary MFN-dutiable trade with no Section 301 exposure at all -- six
    # months of it before the first action even took effect, $42.6bn of customs
    # value that could not possibly fall short of a Section 301 duty because
    # none applied. Those months sat in the denominator contributing zero to the
    # numerator and halved the apparent pre-exclusion baseline, which is exactly
    # the quantity this bound decomposes against. A flow carrying no additional
    # duty cannot be affected by an exclusion from that duty and belongs in
    # neither side of the ratio.
    d = panel.filter(
        pl.col(treated_country_col)
        & (pl.col("additional_tariff_rate") > 0)
        & (pl.col("dutiable_value") > 0)
        & (pl.col("customs_value") > 0)
    )
    if d.height == 0:
        return None
    d = d.with_columns(
        (
            pl.col("total_modeled_tariff_rate") - pl.col("realised_duty_rate_on_dutiable")
        ).alias("statutory_minus_realised")
    ).with_columns(
        (pl.col("statutory_minus_realised") > tolerance).alias("materially_short")
    )
    return (
        d.group_by("month_date")
        .agg(
            pl.len().alias("n_obs"),
            pl.col("materially_short").sum().alias("n_short"),
            pl.col("customs_value").sum().alias("customs_value"),
            pl.when(pl.col("materially_short"))
            .then(pl.col("customs_value"))
            .otherwise(0.0)
            .sum()
            .alias("customs_value_short"),
            pl.col("statutory_minus_realised").median().alias("median_gap"),
        )
        .with_columns(
            (pl.col("n_short") / pl.col("n_obs")).alias("share_obs_short"),
            (pl.col("customs_value_short") / pl.col("customs_value")).alias(
                "share_value_short"
            ),
        )
        .sort("month_date")
    )


#: Exclusion notices covering the project's 2017-01..2019-08 sample window.
#: Sourced from the Federal Register API search for USTR product-exclusion
#: notices; each is verified by parsing the document itself.
SAMPLE_WINDOW_NOTICES: dict[str, str] = {
    "2018-28277": "2018-12-28",
    "2019-05588": "2019-03-25",
    "2019-07758": "2019-04-18",
    "2019-09872": "2019-05-14",
    "2019-11573": "2019-06-04",
    "2019-14562": "2019-07-09",
    "2019-16256": "2019-07-31",
    "2019-16886": "2019-08-07",
    "2019-20440": "2019-09-20",
    "2019-20441": "2019-09-20",
    "2019-20442": "2019-09-20",
}


def first_exclusion_effective_month(notices: list[ExclusionNotice]) -> date | None:
    """Month in which exclusions first became legally available (publication, not retroactivity)."""
    pubs = [n.publication_date for n in notices if n.publication_date]
    if not pubs:
        return None
    d = datetime.strptime(min(pubs), "%Y-%m-%d").date()
    return date(d.year, d.month, 1)
