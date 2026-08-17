"""Point-in-time tariff policy engine.

Answers: *for this product code, from this country, on this date, what duty
applied, under which legal instrument, and how much do we trust the answer?*

Design commitments
------------------

**Never silently assign a rate.** Every answer carries a
:class:`ValidationStatus`. Ambiguity (conflicting records, partial statistical
lines, HS6 queries whose HS8 children are only partly covered) is reported, not
smoothed over. Callers decide how to treat an ambiguous line; the engine refuses
to decide for them.

**HS6 queries are treated as coverage questions, not rate questions.** Section
301 lists are legislated at HS8. An HS6 heading frequently contains both covered
and uncovered HS8 children. Returning a single "the HS6 rate" would invent
precision that the law does not have, so an HS6 query returns a *coverage share*
across its known HS8 children plus a trade-weighted rate when weights are
supplied, and is flagged ``PARTIAL_HS6_COVERAGE`` whenever coverage is strictly
between 0 and 1.

**Baseline and additional duties are separate.** The Section 301 duty is
*additive* to the column-1 general (MFN) rate. Total duty is only meaningful when
both are known, so ``total_rate`` is ``None`` when the baseline is unavailable
rather than silently equal to the additional rate.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from enum import Enum

from .records import Confidence, RecordType, SourceRef, TariffRecord


class ValidationStatus(str, Enum):
    OK = "OK"
    """Unambiguous match: a single governing duty record (or none at all)."""

    NO_MATCH = "NO_MATCH"
    """No record covers this product/country/date. Additional duty is zero."""

    PARTIAL_LINE = "PARTIAL_LINE"
    """The governing record covers only part of the statistical line
    (an 'other than ...' carve-out). Line-level treatment is fractional."""

    PARTIAL_HS6_COVERAGE = "PARTIAL_HS6_COVERAGE"
    """Query was at HS6; some but not all known HS8 children are covered."""

    CONFLICT = "CONFLICT"
    """Two or more records from different actions impose different rates on the
    same line at the same time and neither supersedes the other."""

    AMBIGUOUS_CODE = "AMBIGUOUS_CODE"
    """The product code could not be resolved to the schedule's code vintage."""

    EXCLUDED = "EXCLUDED"
    """An exclusion is active, so no additional duty applies on this date."""

    @property
    def usable_for_treatment(self) -> bool:
        """Whether a scalar treatment rate may be used without further judgement."""
        return self in (ValidationStatus.OK, ValidationStatus.NO_MATCH, ValidationStatus.EXCLUDED)


@dataclass(frozen=True, slots=True)
class TariffAssessment:
    """The engine's answer for one (product, country, date)."""

    product_code: str
    product_code_level: int
    partner_country_code: str
    as_of: date

    baseline_rate: float | None
    additional_rate: float | None
    total_rate: float | None

    active_action_ids: tuple[str, ...]
    exclusion_active: bool
    exclusion_record_ids: tuple[str, ...]

    status: ValidationStatus
    confidence: Confidence
    coverage_share: float
    """Fraction of the queried line covered by an additional duty.

    1.0 for a fully covered HS8 line, 0.0 for an untreated line, and the
    (optionally trade-weighted) covered fraction for an HS6 query.
    """

    source_records: tuple[str, ...] = field(default_factory=tuple)
    sources: tuple[SourceRef, ...] = field(default_factory=tuple)
    messages: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_treated(self) -> bool:
        """Treated means a positive additional duty is actually being collected."""
        return bool(self.additional_rate) and self.coverage_share > 0.0

    def explain(self) -> str:
        parts = [
            f"{self.product_code} (HS{self.product_code_level}) from "
            f"{self.partner_country_code} on {self.as_of.isoformat()}",
            f"status={self.status.value}",
            f"baseline={_fmt(self.baseline_rate)}",
            f"additional={_fmt(self.additional_rate)}",
            f"total={_fmt(self.total_rate)}",
            f"coverage={self.coverage_share:.3f}",
        ]
        if self.active_action_ids:
            parts.append("actions=" + ",".join(self.active_action_ids))
        if self.exclusion_active:
            parts.append("EXCLUDED")
        if self.messages:
            parts.append("; ".join(self.messages))
        return " | ".join(parts)


def _fmt(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.4f}"


class BaselineRateSource:
    """Column-1 general (MFN) ad valorem rates, keyed by HS8 and vintage year.

    Implemented as a small class rather than a bare dict so the HTS adapter and
    test fixtures can share the same interface, and so a missing rate is an
    explicit ``None`` instead of a KeyError deep in the engine.
    """

    def __init__(self, rates: Mapping[tuple[str, int], float] | None = None) -> None:
        self._rates: dict[tuple[str, int], float] = dict(rates or {})

    def add(self, hs8: str, year: int, ad_valorem: float) -> None:
        self._rates[(hs8, year)] = ad_valorem

    def get(self, product_code: str, year: int) -> float | None:
        hs8 = product_code[:8]
        if (hs8, year) in self._rates:
            return self._rates[(hs8, year)]
        # Fall back to the nearest earlier vintage we hold for this line.
        candidates = [y for (c, y) in self._rates if c == hs8 and y <= year]
        if candidates:
            return self._rates[(hs8, max(candidates))]
        return None

    def __len__(self) -> int:
        return len(self._rates)


class TariffEngine:
    """Resolve tariff records into point-in-time assessments."""

    def __init__(
        self,
        records: Iterable[TariffRecord],
        baseline: BaselineRateSource | None = None,
        hs6_children: Mapping[str, Sequence[str]] | None = None,
    ) -> None:
        """
        Parameters
        ----------
        records
            The tariff schedule.
        baseline
            Column-1 general (MFN) rates. Without it ``total_rate`` is ``None``.
        hs6_children
            Map HS6 -> the HS8 lines that exist beneath it in the tariff
            schedule. Required to answer HS6 coverage questions honestly: the
            engine cannot know that an HS6 heading has ten children of which
            three are covered unless something tells it the denominator.
        """
        self._records = list(records)
        self._baseline = baseline or BaselineRateSource()
        self._hs6_children = {k: tuple(v) for k, v in (hs6_children or {}).items()}

        self._by_line: dict[tuple[str, str], list[TariffRecord]] = defaultdict(list)
        for r in self._records:
            self._by_line[(r.product_code[:8], r.partner_country_code)].append(r)
        for bucket in self._by_line.values():
            bucket.sort(key=lambda r: (r.effective_date, r.record_id))

        self._hs8_universe: set[str] = {r.product_code[:8] for r in self._records}

    # ------------------------------------------------------------------ #
    # public API
    # ------------------------------------------------------------------ #

    @property
    def records(self) -> list[TariffRecord]:
        return list(self._records)

    def records_for_line(self, product_code: str, country: str) -> list[TariffRecord]:
        """Records governing one 8-digit line, via the prebuilt index.

        Callers that need to know when the law changes (the panel builder's
        within-month day weighting) must not scan the whole schedule per query:
        at HS10 scale that is millions of passes over 12,000+ records.
        """
        return list(self._by_line.get((product_code[:8], country), []))

    def known_hs8_for_hs6(self, hs6: str) -> tuple[str, ...]:
        """HS8 children of an HS6 heading, from the supplied tariff-schedule map."""
        return self._hs6_children.get(hs6, ())

    def assess(
        self,
        product_code: str,
        partner_country_code: str,
        as_of: date,
        hs8_weights: Mapping[str, float] | None = None,
    ) -> TariffAssessment:
        """Assess one (product, country, date).

        ``product_code`` may be 6, 8 or 10 digits. A 10-digit code is resolved
        through its 8-digit parent, which is the level at which Section 301
        lists are written. ``hs8_weights`` supplies pre-treatment import weights
        for HS6 queries; without them an HS6 coverage share is an unweighted
        count share and is labelled as such.
        """
        code = product_code.strip().replace(".", "")
        if not code.isdigit():
            return self._ambiguous(
                product_code, partner_country_code, as_of, f"non-numeric product code {product_code!r}"
            )
        level = len(code)
        if level not in (6, 8, 10):
            return self._ambiguous(
                code, partner_country_code, as_of, f"unsupported code length {level}"
            )

        if level == 6:
            return self._assess_hs6(code, partner_country_code, as_of, hs8_weights)
        return self._assess_line(code, level, partner_country_code, as_of)

    def assess_many(
        self,
        queries: Iterable[tuple[str, str, date]],
    ) -> list[TariffAssessment]:
        return [self.assess(p, c, d) for p, c, d in queries]

    # ------------------------------------------------------------------ #
    # HS8 / HS10 resolution
    # ------------------------------------------------------------------ #

    def _assess_line(
        self, code: str, level: int, country: str, as_of: date
    ) -> TariffAssessment:
        hs8 = code[:8]
        year = as_of.year
        baseline = self._baseline.get(hs8, year)
        bucket = self._by_line.get((hs8, country), [])
        active = [r for r in bucket if r.is_active_on(as_of)]

        messages: list[str] = []

        exclusions = [r for r in active if r.record_type is RecordType.EXCLUSION]
        reinstatements = [r for r in active if r.record_type is RecordType.REINSTATEMENT]
        duties = [
            r
            for r in active
            if r.record_type in (RecordType.ADDITIONAL_DUTY, RecordType.RATE_CHANGE)
        ]

        # A reinstatement effective after an exclusion cancels that exclusion.
        live_exclusions = []
        for ex in exclusions:
            superseding = [
                ri
                for ri in reinstatements
                if ri.action_id == ex.action_id and ri.effective_date > ex.effective_date
            ]
            if superseding:
                messages.append(
                    f"exclusion {ex.record_id} superseded by reinstatement "
                    f"{superseding[-1].record_id}"
                )
            else:
                live_exclusions.append(ex)

        if not duties:
            return TariffAssessment(
                product_code=code,
                product_code_level=level,
                partner_country_code=country,
                as_of=as_of,
                baseline_rate=baseline,
                additional_rate=0.0,
                total_rate=baseline,
                active_action_ids=(),
                exclusion_active=False,
                exclusion_record_ids=(),
                status=ValidationStatus.NO_MATCH,
                confidence=Confidence.OFFICIAL_PARSED,
                coverage_share=0.0,
                messages=tuple(messages),
            )

        # Within one action, the latest-effective duty record governs
        # (this is how a rate increase supersedes the original imposition).
        governing: dict[str, TariffRecord] = {}
        for r in duties:
            cur = governing.get(r.action_id)
            if cur is None or (r.effective_date, r.record_id) > (cur.effective_date, cur.record_id):
                governing[r.action_id] = r

        # A 10-digit carve-out is action-specific and must be applied BEFORE the
        # conflict check. An action whose note names this statistical number does
        # not govern it, so it must not contribute a rate to the comparison.
        # Applying carve-outs afterwards -- as an earlier version did -- zeroed
        # the rate globally, so a number carved out of one action but squarely
        # covered by another came back as untreated. That only became visible
        # once a second action overlapping the same line was loaded.
        carved_out_of: dict[str, TariffRecord] = {}
        if level == 10:
            for act, rec in list(governing.items()):
                if (
                    rec.partial_line
                    and rec.partial_line_excluded_codes
                    and code in rec.partial_line_excluded_codes
                ):
                    carved_out_of[act] = rec
                    del governing[act]
            if carved_out_of:
                messages.append(
                    "carved out of "
                    + ", ".join(sorted(carved_out_of))
                    + " by name in the action's own U.S. note"
                )

        if not governing:
            return TariffAssessment(
                product_code=code,
                product_code_level=level,
                partner_country_code=country,
                as_of=as_of,
                baseline_rate=baseline,
                additional_rate=0.0,
                total_rate=baseline,
                active_action_ids=(),
                exclusion_active=False,
                exclusion_record_ids=(),
                status=ValidationStatus.OK,
                confidence=confidence_of(carved_out_of.values()),
                coverage_share=0.0,
                source_records=tuple(sorted(r.record_id for r in carved_out_of.values())),
                messages=tuple(messages),
            )

        distinct_rates = {r.ad_valorem_rate for r in governing.values()}
        status = ValidationStatus.OK
        confidence = min(
            (r.confidence for r in governing.values()),
            key=lambda c: _CONFIDENCE_ORDER[c],
        )

        if len(governing) > 1 and len(distinct_rates) > 1:
            status = ValidationStatus.CONFLICT
            messages.append(
                "conflicting additional duties from actions "
                + ", ".join(f"{a}={_fmt(r.ad_valorem_rate)}" for a, r in sorted(governing.items()))
                + " — engine will not choose between them"
            )
            additional: float | None = None
        else:
            additional = max(r.ad_valorem_rate or 0.0 for r in governing.values())
            if len(governing) > 1:
                messages.append(
                    "multiple actions cover this line at the same rate: "
                    + ", ".join(sorted(governing))
                )

        if live_exclusions:
            status = ValidationStatus.EXCLUDED
            additional = 0.0
            messages.append(
                "active exclusion(s): " + ", ".join(r.record_id for r in live_exclusions)
            )

        partial = [
            r
            for r in governing.values()
            if r.partial_line and not (level == 10 and r.partial_line_excluded_codes)
        ]
        if partial and status is not ValidationStatus.EXCLUDED:
            # A partial line names the 10-digit statistical numbers carved out of
            # the duty. At 10 digits that is not ambiguity at all -- the query
            # either is one of those numbers or it is not -- so the answer is
            # exact. Only at 8 or 6 digits, where the query spans both the
            # covered and carved-out parts, must it be flagged as partial.
            resolvable = level == 10 and all(r.partial_line_excluded_codes for r in partial)
            if resolvable:
                carved = {c for r in partial for c in r.partial_line_excluded_codes}
                if code in carved:
                    additional = 0.0
                    messages.append(
                        f"statistical reporting number {code} is named in the carve-out of "
                        f"{', '.join(sorted(r.record_id for r in partial))}, so no additional "
                        "duty applies"
                    )
                else:
                    messages.append(
                        "parent line is partially covered, but this 10-digit number is not "
                        "among the carve-outs, so it is fully covered"
                    )
            else:
                status = ValidationStatus.PARTIAL_LINE
                for r in partial:
                    messages.append(
                        f"{r.record_id} covers only part of the statistical line"
                        + (f": {r.partial_line_note}" if r.partial_line_note else "")
                    )

        total = None if (baseline is None or additional is None) else baseline + additional
        srcs = tuple({r.source.document_id: r.source for r in governing.values()}.values())

        return TariffAssessment(
            product_code=code,
            product_code_level=level,
            partner_country_code=country,
            as_of=as_of,
            baseline_rate=baseline,
            additional_rate=additional,
            total_rate=total,
            active_action_ids=tuple(sorted(governing)),
            exclusion_active=bool(live_exclusions),
            exclusion_record_ids=tuple(r.record_id for r in live_exclusions),
            status=status,
            confidence=confidence,
            coverage_share=0.0 if (additional in (0.0, None) and status is not ValidationStatus.CONFLICT) else 1.0,
            source_records=tuple(sorted(r.record_id for r in governing.values())),
            sources=srcs,
            messages=tuple(messages),
        )

    # ------------------------------------------------------------------ #
    # HS6 resolution
    # ------------------------------------------------------------------ #

    def _assess_hs6(
        self,
        hs6: str,
        country: str,
        as_of: date,
        hs8_weights: Mapping[str, float] | None,
    ) -> TariffAssessment:
        children = self._hs6_children.get(hs6)
        messages: list[str] = []

        if not children:
            # Fall back to HS8 lines the schedule itself mentions. The
            # denominator is then "covered lines only", which overstates
            # coverage; say so rather than hide it.
            observed = sorted(c for c in self._hs8_universe if c.startswith(hs6))
            if not observed:
                return TariffAssessment(
                    product_code=hs6,
                    product_code_level=6,
                    partner_country_code=country,
                    as_of=as_of,
                    baseline_rate=None,
                    additional_rate=0.0,
                    total_rate=None,
                    active_action_ids=(),
                    exclusion_active=False,
                    exclusion_record_ids=(),
                    status=ValidationStatus.NO_MATCH,
                    confidence=Confidence.OFFICIAL_PARSED,
                    coverage_share=0.0,
                    messages=("no HS8 child of this heading appears in the schedule",),
                )
            children = tuple(observed)
            messages.append(
                "HS6 child list not supplied; denominator restricted to HS8 lines present "
                "in the tariff schedule, which biases coverage upward"
            )

        child_assessments = [self._assess_line(c, 8, country, as_of) for c in children]

        if hs8_weights:
            weights = {c: float(hs8_weights.get(c, 0.0)) for c in children}
            if sum(weights.values()) <= 0:
                weights = {c: 1.0 for c in children}
                messages.append("supplied HS8 weights summed to zero; fell back to equal weights")
            else:
                messages.append("coverage share is trade-weighted using supplied HS8 weights")
        else:
            weights = {c: 1.0 for c in children}
            messages.append("coverage share is an unweighted count share across HS8 children")

        wsum = sum(weights.values())
        covered_w = sum(weights[a.product_code] for a in child_assessments if a.is_treated)
        coverage = covered_w / wsum if wsum else 0.0

        # Trade-weighted additional rate across the heading.
        addl_num = sum(
            weights[a.product_code] * (a.additional_rate or 0.0)
            for a in child_assessments
            if a.additional_rate is not None
        )
        additional = addl_num / wsum if wsum else 0.0

        base_pairs = [
            (weights[a.product_code], a.baseline_rate)
            for a in child_assessments
            if a.baseline_rate is not None
        ]
        baseline = (
            sum(w * b for w, b in base_pairs) / sum(w for w, _ in base_pairs)
            if base_pairs and len(base_pairs) == len(child_assessments)
            else None
        )
        if baseline is None:
            messages.append("baseline MFN rate unavailable for at least one HS8 child")

        statuses = {a.status for a in child_assessments}
        if ValidationStatus.CONFLICT in statuses:
            status = ValidationStatus.CONFLICT
        elif 0.0 < coverage < 1.0:
            status = ValidationStatus.PARTIAL_HS6_COVERAGE
            messages.append(
                f"{sum(a.is_treated for a in child_assessments)} of {len(children)} HS8 children "
                "are treated; a single HS6 rate would overstate legal precision"
            )
        elif ValidationStatus.PARTIAL_LINE in statuses:
            status = ValidationStatus.PARTIAL_LINE
        elif coverage == 0.0:
            status = (
                ValidationStatus.EXCLUDED
                if any(a.exclusion_active for a in child_assessments)
                else ValidationStatus.NO_MATCH
            )
        else:
            status = ValidationStatus.OK

        actions = tuple(sorted({a for ca in child_assessments for a in ca.active_action_ids}))
        srcs: dict[str, SourceRef] = {}
        for ca in child_assessments:
            for s in ca.sources:
                srcs[s.document_id] = s

        confidences = [a.confidence for a in child_assessments] or [Confidence.OFFICIAL_PARSED]
        return TariffAssessment(
            product_code=hs6,
            product_code_level=6,
            partner_country_code=country,
            as_of=as_of,
            baseline_rate=baseline,
            additional_rate=additional,
            total_rate=None if baseline is None else baseline + additional,
            active_action_ids=actions,
            exclusion_active=any(a.exclusion_active for a in child_assessments),
            exclusion_record_ids=tuple(
                r for a in child_assessments for r in a.exclusion_record_ids
            ),
            status=status,
            confidence=min(confidences, key=lambda c: _CONFIDENCE_ORDER[c]),
            coverage_share=coverage,
            source_records=tuple(sorted({r for a in child_assessments for r in a.source_records})),
            sources=tuple(srcs.values()),
            messages=tuple(messages),
        )

    # ------------------------------------------------------------------ #

    def _ambiguous(
        self, code: str, country: str, as_of: date, why: str
    ) -> TariffAssessment:
        return TariffAssessment(
            product_code=code,
            product_code_level=len(code),
            partner_country_code=country,
            as_of=as_of,
            baseline_rate=None,
            additional_rate=None,
            total_rate=None,
            active_action_ids=(),
            exclusion_active=False,
            exclusion_record_ids=(),
            status=ValidationStatus.AMBIGUOUS_CODE,
            confidence=Confidence.UNVERIFIED,
            coverage_share=0.0,
            messages=(why,),
        )


def confidence_of(records: Iterable[TariffRecord]) -> Confidence:
    """Weakest confidence among a set of records, or OFFICIAL_PARSED if empty."""
    recs = list(records)
    if not recs:
        return Confidence.OFFICIAL_PARSED
    weakest: Confidence = min(
        (r.confidence for r in recs), key=lambda c: _CONFIDENCE_ORDER[c]
    )
    return weakest


_CONFIDENCE_ORDER = {
    Confidence.UNVERIFIED: 0,
    Confidence.DERIVED: 1,
    Confidence.OFFICIAL_MANUAL: 2,
    Confidence.OFFICIAL_PARSED: 3,
}
