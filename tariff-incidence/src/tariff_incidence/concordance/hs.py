"""Versioned Harmonized System concordance.

HS codes are revised. The Section 301 lists are written against HTS2018, but a
panel spanning 2017-2020 crosses the WCO HS2017 revision and annual U.S.
statistical-line changes. A product that changes code looks like an exit and an
entry, which is exactly the extensive-margin pattern a tariff study is trying to
measure. Ignoring reclassification therefore does not add noise; it manufactures
the finding.

This module makes the mapping explicit and offers two analysis samples whose
results are meant to be compared:

**Stable-code sample**
    Only codes with a clean one-to-one identity across every year in the window.
    Cleanest interpretation, smaller and non-random (stable codes are typically
    older, more commoditised lines).

**Concordance-weighted sample**
    All codes, mapped to a common basis with split weights. Broader coverage,
    but many-to-one and one-to-many mappings require weights that are themselves
    an assumption.

Codes that cannot be mapped are reported as ``UNRESOLVED`` and never quietly
dropped or force-matched.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum

import polars as pl


class MappingType(str, Enum):
    ONE_TO_ONE = "ONE_TO_ONE"
    ONE_TO_MANY = "ONE_TO_MANY"  # a code was split
    MANY_TO_ONE = "MANY_TO_ONE"  # codes were merged
    MANY_TO_MANY = "MANY_TO_MANY"
    NEW_CODE = "NEW_CODE"
    RETIRED_CODE = "RETIRED_CODE"
    UNRESOLVED = "UNRESOLVED"


@dataclass(frozen=True, slots=True)
class ConcordanceLink:
    """One directed mapping between code vintages."""

    from_code: str
    to_code: str
    from_vintage: str
    to_vintage: str
    weight: float = 1.0
    mapping_type: MappingType = MappingType.ONE_TO_ONE
    source: str = ""
    note: str = ""


@dataclass(slots=True)
class ConcordanceReport:
    n_links: int
    counts_by_type: dict[str, int]
    stable_codes: list[str]
    unresolved_from: list[str]
    unresolved_to: list[str]
    notes: list[str] = field(default_factory=list)


class HSConcordance:
    """A versioned set of code mappings with explicit split weights."""

    def __init__(self, links: list[ConcordanceLink]) -> None:
        self._links = list(links)
        self._fwd: dict[tuple[str, str, str], list[ConcordanceLink]] = defaultdict(list)
        self._rev: dict[tuple[str, str, str], list[ConcordanceLink]] = defaultdict(list)
        for ln in self._links:
            self._fwd[(ln.from_code, ln.from_vintage, ln.to_vintage)].append(ln)
            self._rev[(ln.to_code, ln.to_vintage, ln.from_vintage)].append(ln)
        self._classify()

    def _classify(self) -> None:
        out_deg: dict[tuple[str, str, str], int] = defaultdict(int)
        in_deg: dict[tuple[str, str, str], int] = defaultdict(int)
        for ln in self._links:
            out_deg[(ln.from_code, ln.from_vintage, ln.to_vintage)] += 1
            in_deg[(ln.to_code, ln.to_vintage, ln.from_vintage)] += 1

        reclassified: list[ConcordanceLink] = []
        for ln in self._links:
            o = out_deg[(ln.from_code, ln.from_vintage, ln.to_vintage)]
            i = in_deg[(ln.to_code, ln.to_vintage, ln.from_vintage)]
            mt: MappingType
            if ln.mapping_type in (MappingType.NEW_CODE, MappingType.RETIRED_CODE,
                                   MappingType.UNRESOLVED):
                mt = ln.mapping_type
            elif o > 1 and i > 1:
                mt = MappingType.MANY_TO_MANY
            elif o > 1:
                mt = MappingType.ONE_TO_MANY
            elif i > 1:
                mt = MappingType.MANY_TO_ONE
            else:
                mt = MappingType.ONE_TO_ONE
            reclassified.append(
                ConcordanceLink(
                    ln.from_code, ln.to_code, ln.from_vintage, ln.to_vintage,
                    ln.weight, mt, ln.source, ln.note,
                )
            )
        self._links = reclassified
        self._fwd.clear()
        self._rev.clear()
        for ln in self._links:
            self._fwd[(ln.from_code, ln.from_vintage, ln.to_vintage)].append(ln)
            self._rev[(ln.to_code, ln.to_vintage, ln.from_vintage)].append(ln)

    # ------------------------------------------------------------------ #

    @property
    def links(self) -> list[ConcordanceLink]:
        return list(self._links)

    def map_code(self, code: str, from_vintage: str, to_vintage: str) -> list[ConcordanceLink]:
        """Map one code forward. Empty result means unresolved, not unchanged."""
        return list(self._fwd.get((code, from_vintage, to_vintage), []))

    def is_stable(self, code: str, vintages: list[str]) -> bool:
        """True when the code maps one-to-one with full weight across every step."""
        cur = code
        for a, b in zip(vintages, vintages[1:], strict=False):
            links = self.map_code(cur, a, b)
            if len(links) != 1:
                return False
            ln = links[0]
            if ln.mapping_type is not MappingType.ONE_TO_ONE or abs(ln.weight - 1.0) > 1e-9:
                return False
            if ln.to_code != cur:
                return False  # a renumbered code is not "stable" for panel purposes
            cur = ln.to_code
        return True

    def stable_codes(self, codes: list[str], vintages: list[str]) -> list[str]:
        return sorted(c for c in codes if self.is_stable(c, vintages))

    def report(self, codes: list[str], vintages: list[str]) -> ConcordanceReport:
        counts: dict[str, int] = defaultdict(int)
        for ln in self._links:
            counts[ln.mapping_type.value] += 1
        stable = self.stable_codes(codes, vintages)
        unresolved_from = []
        for c in codes:
            for a, b in zip(vintages, vintages[1:], strict=False):
                if not self.map_code(c, a, b):
                    unresolved_from.append(c)
                    break
        known_to = {ln.to_code for ln in self._links}
        unresolved_to = sorted(set(codes) - known_to - set(stable))
        return ConcordanceReport(
            n_links=len(self._links),
            counts_by_type=dict(counts),
            stable_codes=stable,
            unresolved_from=sorted(set(unresolved_from)),
            unresolved_to=unresolved_to,
            notes=[
                "Stable-code and concordance-weighted samples must be compared; a result that "
                "appears only in one is a reclassification artefact until shown otherwise.",
            ],
        )

    # ------------------------------------------------------------------ #

    def apply_to_panel(
        self,
        panel: pl.DataFrame,
        *,
        code_col: str = "hs6",
        from_vintage: str,
        to_vintage: str,
        value_cols: tuple[str, ...] = ("customs_value", "quantity"),
    ) -> pl.DataFrame:
        """Re-express a panel on the target vintage, splitting values by weight.

        One-to-many links split a value across successor codes using the link
        weight. Those weights are an assumption; the resulting rows carry
        ``concordance_weight`` and ``concordance_mapping_type`` so any estimate
        can be re-run on one-to-one rows only.
        """
        rows = [
            {
                "_from": ln.from_code,
                "_to": ln.to_code,
                "concordance_weight": ln.weight,
                "concordance_mapping_type": ln.mapping_type.value,
            }
            for ln in self._links
            if ln.from_vintage == from_vintage and ln.to_vintage == to_vintage
        ]
        if not rows:
            return panel.with_columns(
                pl.lit(1.0).alias("concordance_weight"),
                pl.lit(MappingType.UNRESOLVED.value).alias("concordance_mapping_type"),
            )
        m = pl.DataFrame(rows)
        joined = panel.join(m, left_on=code_col, right_on="_from", how="left")
        joined = joined.with_columns(
            pl.col("concordance_weight").fill_null(1.0),
            pl.col("concordance_mapping_type").fill_null(MappingType.UNRESOLVED.value),
            pl.coalesce([pl.col("_to"), pl.col(code_col)]).alias(code_col),
        ).drop("_to")
        scaled = [
            (pl.col(c) * pl.col("concordance_weight")).alias(c)
            for c in value_cols
            if c in joined.columns
        ]
        return joined.with_columns(scaled)


def identity_concordance(codes: list[str], vintages: list[str], source: str = "") -> HSConcordance:
    """Build an identity concordance: every code maps to itself in every step.

    This is the honest default when no official concordance file is loaded. It
    asserts stability, so it must be replaced by a real concordance before any
    claim about reclassification is made; the manifest records which was used.
    """
    links = [
        ConcordanceLink(c, c, a, b, 1.0, MappingType.ONE_TO_ONE, source or "IDENTITY_ASSUMED")
        for c in codes
        for a, b in zip(vintages, vintages[1:], strict=False)
    ]
    return HSConcordance(links)


def load_from_frame(
    df: pl.DataFrame,
    *,
    from_col: str = "from_code",
    to_col: str = "to_code",
    from_vintage_col: str = "from_vintage",
    to_vintage_col: str = "to_vintage",
    weight_col: str = "weight",
    source: str = "",
) -> HSConcordance:
    """Load a concordance from a tabular file (e.g. an official correlation table)."""
    links = [
        ConcordanceLink(
            str(r[from_col]),
            str(r[to_col]),
            str(r[from_vintage_col]),
            str(r[to_vintage_col]),
            float(r.get(weight_col, 1.0) or 1.0),
            source=source,
        )
        for r in df.iter_rows(named=True)
    ]
    return HSConcordance(links)
