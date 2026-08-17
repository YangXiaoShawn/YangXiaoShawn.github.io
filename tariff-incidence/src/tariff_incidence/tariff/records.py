"""Atomic tariff-policy records.

A :class:`TariffRecord` is one legal fact drawn from one source document: "as of
this date, this additional duty applies to this product line imported from this
country, until this date". Rate increases, exclusions, exclusion expirations and
reinstatements are all separate records rather than mutations of an existing
one, so the schedule is append-only and the engine can always answer a
point-in-time question.

Two dates are kept distinct throughout, because conflating them is a standard
way to get tariff research wrong:

``announcement_date``
    When the action became public. Drives anticipation and front-running.
``effective_date``
    When duties were actually collected. Drives the mechanical cost shock.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum


class RecordType(str, Enum):
    ADDITIONAL_DUTY = "ADDITIONAL_DUTY"
    """Imposes (or re-sets) an additional ad valorem duty on a product line."""

    RATE_CHANGE = "RATE_CHANGE"
    """Changes the additional rate for a line already covered by an action."""

    EXCLUSION = "EXCLUSION"
    """Removes the additional duty for a product (possibly a sub-line) in a window."""

    REINSTATEMENT = "REINSTATEMENT"
    """Restores a previously excluded product to the additional duty."""


class Confidence(str, Enum):
    OFFICIAL_PARSED = "OFFICIAL_PARSED"
    """Parsed directly from an official source document."""

    OFFICIAL_MANUAL = "OFFICIAL_MANUAL"
    """Transcribed by hand from an official source document, with citation."""

    DERIVED = "DERIVED"
    """Inferred from other records (e.g. an expiry implied by a stated duration)."""

    UNVERIFIED = "UNVERIFIED"
    """Present in the schedule but not confirmed against a source. Never used to
    assign a rate without surfacing the status."""


@dataclass(frozen=True, slots=True)
class SourceRef:
    """Where a record came from, precisely enough to re-derive it."""

    document_id: str
    citation: str
    title: str
    url: str
    publication_date: str
    checksum_sha256: str
    page_or_locator: str = ""

    def short(self) -> str:
        return f"{self.citation} ({self.document_id})"


@dataclass(frozen=True, slots=True)
class TariffRecord:
    """One point-in-time tariff fact."""

    record_id: str
    episode_id: str
    action_id: str
    record_type: RecordType
    product_code: str
    product_code_level: int  # 6, 8 or 10 digits
    product_code_vintage: str  # e.g. "HTS2018_REV13"
    partner_country_code: str  # Census/ISO numeric-style code; "5700" = China
    announcement_date: date | None
    effective_date: date
    expiry_date: date | None
    ad_valorem_rate: float | None
    source: SourceRef
    confidence: Confidence = Confidence.OFFICIAL_PARSED
    partial_line: bool = False
    partial_line_note: str = ""
    partial_line_excluded_codes: tuple[str, ...] = field(default_factory=tuple)
    """10-digit statistical numbers carved *out* of the duty on this line.

    Held structurally rather than only in prose so the engine can resolve a
    10-digit query exactly: an HS10 line named here is untreated, any other
    child of the same HS8 parent is fully treated. At HS8 or HS6 the line can
    only be flagged as partial."""
    notes: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.product_code_level not in (6, 8, 10):
            raise ValueError(f"product_code_level must be 6, 8 or 10, got {self.product_code_level}")
        if len(self.product_code) != self.product_code_level:
            raise ValueError(
                f"product_code {self.product_code!r} does not match declared level "
                f"{self.product_code_level}"
            )
        if not self.product_code.isdigit():
            raise ValueError(f"product_code must be digits only, got {self.product_code!r}")
        if self.expiry_date is not None and self.expiry_date < self.effective_date:
            raise ValueError(
                f"record {self.record_id}: expiry {self.expiry_date} precedes effective "
                f"{self.effective_date}"
            )
        if self.record_type in (RecordType.ADDITIONAL_DUTY, RecordType.RATE_CHANGE):
            if self.ad_valorem_rate is None:
                raise ValueError(f"record {self.record_id}: duty record requires a rate")
            if not 0.0 <= self.ad_valorem_rate <= 3.0:
                raise ValueError(
                    f"record {self.record_id}: implausible ad valorem rate "
                    f"{self.ad_valorem_rate} (expressed as a fraction, e.g. 0.25)"
                )

    def is_active_on(self, when: date) -> bool:
        """Whether the record's window covers ``when`` (effective inclusive, expiry exclusive)."""
        if when < self.effective_date:
            return False
        return not (self.expiry_date is not None and when >= self.expiry_date)

    @property
    def hs6(self) -> str:
        return self.product_code[:6]

    @property
    def hs8(self) -> str | None:
        return self.product_code[:8] if self.product_code_level >= 8 else None
