"""Report rendering.

Reports are generated from result tables, never typed by hand. Two guards make
that mechanically safe:

* every rendered document opens with the run's provenance banner, so a reader
  cannot reach a number without first reading what produced it;
* :func:`guard_language` scans generated prose for causal and welfare claims and
  refuses to emit them when the underlying data is not official, which is the
  enforcement mechanism behind acceptance criterion 17.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import polars as pl

from ..provenance import DataProvenance, RunStamp

_POLICY = r"(?:tariffs?|duty|duties|section\s*301|the action|the policy|treatment)"

#: Assertions that a policy produced an outcome. These are blocked outright when
#: the data cannot support them.
CAUSAL_ASSERTIONS = [
    rf"{_POLICY}\s+(?:\w+\s+){{0,3}}(?:caused|led to|resulted in|drove|brought about)\b",
    rf"(?:caused|driven|produced)\s+by\s+(?:the\s+)?{_POLICY}",
    r"\bproves?\s+that\b",
    r"\bdemonstrates?\s+that\s+(?:the\s+)?(?:tariff|duty|policy)",
    r"\bthe\s+causal\s+effect\s+(?:is|was|of the tariff)\b",
    r"\bwe\s+(?:find|show|establish)\s+that\s+(?:the\s+)?(?:tariff|duty)\s+\w+ed\b",
]

#: Quantified welfare claims. Blocked unless the data is official *and* a
#: structural module actually produced them, which this project does not yet do.
WELFARE_ASSERTIONS = [
    r"\bwelfare (?:loss|gain|cost|effect)s?\s+(?:of|was|were|is|are|totall?ed)\b",
    r"\bdeadweight loss\b",
    r"\bconsumers? (?:lost|paid|bore)\s+\$?[\d,.]",
    r"\bcost (?:to )?(?:U\.S\.|American) (?:consumers?|households|the economy)\s+\$?[\d,.]",
    r"\breal income (?:loss|gain)s?\s+of\b",
]

#: Vocabulary that merely *discusses* evidential status. Permitted only in
#: sections that declare they are doing so, because a report is required to say
#: which of its conclusions are causal and which are not.
META_VOCABULARY = [r"\bcausal(?:ly)?\b", r"\bcaused?\b", r"\bthe effect of\b"]


class UnsupportedClaim(RuntimeError):
    """Raised when generated prose makes a claim the data cannot support."""


@dataclass(slots=True)
class Section:
    heading: str
    body: str = ""
    tables: list[tuple[str, pl.DataFrame]] | None = None
    level: int = 2
    discusses_evidential_status: bool = False
    """Set for text whose job is to state which conclusions are causal and which
    are not. Permits the meta-vocabulary; assertion patterns stay blocked."""


def guard_language(
    text: str,
    provenance: DataProvenance,
    *,
    context: str = "",
    discusses_evidential_status: bool = False,
) -> None:
    """Reject unsupported causal and welfare claims in generated prose.

    Three tiers:

    * **Welfare assertions** are blocked always. This project runs no structural
      module, so no welfare number can be supported regardless of provenance.
    * **Causal assertions** attributing an outcome to the policy are blocked
      unless the data provenance is OFFICIAL.
    * **Meta-vocabulary** ("causal", "the effect of") is blocked in ordinary
      prose under non-official data but allowed in sections that declare they
      are discussing evidential status, because a report is *required* to say
      which of its conclusions are causal.

    If this raises, the fix is to change the claim, not to bypass the guard.
    """
    lowered = text.lower()

    welfare = [p for p in WELFARE_ASSERTIONS if re.search(p, lowered)]
    if welfare:
        raise UnsupportedClaim(
            f"{context}: quantified welfare claim {welfare}. No structural module has produced "
            "a welfare estimate in this project, so no such claim can be supported."
        )

    if provenance.is_empirical:
        return

    causal = [p for p in CAUSAL_ASSERTIONS if re.search(p, lowered)]
    if causal:
        raise UnsupportedClaim(
            f"{context}: causal assertion {causal} but data provenance is "
            f"{provenance.value}. Rephrase as a statement about the estimator or the model."
        )

    if not discusses_evidential_status:
        meta = [p for p in META_VOCABULARY if re.search(p, lowered)]
        if meta:
            raise UnsupportedClaim(
                f"{context}: causal vocabulary {meta} under provenance {provenance.value}. "
                "Either rephrase, or mark the section discusses_evidential_status=True if its "
                "purpose is to state what is and is not causal."
            )


def df_to_markdown(df: pl.DataFrame, max_rows: int = 25, float_fmt: str = "{:,.4f}") -> str:
    """Render a DataFrame as a GitHub-flavoured Markdown table."""
    if df.height == 0:
        return "_(no rows)_\n"
    shown = df.head(max_rows)
    cols = shown.columns

    def fmt(v: object) -> str:
        if v is None:
            return ""
        if isinstance(v, bool):
            return "yes" if v else "no"
        if isinstance(v, float):
            if v != v:  # NaN
                return ""
            return float_fmt.format(v)
        return str(v)

    head = "| " + " | ".join(cols) + " |"
    rule = "| " + " | ".join("---" for _ in cols) + " |"
    body = [
        "| " + " | ".join(fmt(r[c]) for c in cols) + " |"
        for r in shown.iter_rows(named=True)
    ]
    out = "\n".join([head, rule, *body])
    if df.height > max_rows:
        out += f"\n\n_{df.height - max_rows} further rows omitted._"
    return out + "\n"


def render(
    title: str,
    stamp: RunStamp,
    sections: list[Section],
    *,
    intro: str = "",
    out_path: Path,
    guard: bool = True,
) -> Path:
    """Render a report to Markdown with a provenance banner and guarded prose."""
    parts = [f"# {title}\n", stamp.banner(), ""]
    if intro:
        if guard:
            guard_language(
                intro,
                stamp.data_provenance,
                context=f"{title}/intro",
                discusses_evidential_status=True,
            )
        parts += [intro, ""]

    for s in sections:
        if guard and s.body:
            guard_language(
                s.body,
                stamp.data_provenance,
                context=f"{title}/{s.heading}",
                discusses_evidential_status=s.discusses_evidential_status,
            )
        parts.append(f"{'#' * s.level} {s.heading}\n")
        if s.body:
            parts += [s.body.strip(), ""]
        for name, df in s.tables or []:
            parts += [f"**{name}**\n", df_to_markdown(df), ""]

    parts += [
        "---\n",
        "## Reproducibility\n",
        f"- run id: `{stamp.run_id}`",
        f"- git commit: `{stamp.git_commit}`",
        f"- configuration: `{stamp.config_name}` (sha256 `{stamp.config_sha256}`)",
        f"- data provenance: `{stamp.data_provenance.value}`",
        f"- data period: {stamp.data_period_start} to {stamp.data_period_end}",
        f"- generated: {stamp.created_utc}",
        f"- python {stamp.python_version} on {stamp.platform}",
        "",
        "_This document is generated by `scripts/generate_reports.py`. Do not edit it by hand; "
        "edit the generator or the underlying result tables._",
        "",
    ]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(parts))
    return out_path


def significance_marker(p: float | None) -> str:
    if p is None or p != p:
        return ""
    if p < 0.01:
        return "***"
    if p < 0.05:
        return "**"
    if p < 0.10:
        return "*"
    return ""


def describe_estimate(
    estimate: float, ci_low: float, ci_high: float, p: float | None, unit: str = ""
) -> str:
    """One-line description that never overstates precision or significance."""
    sig = significance_marker(p)
    crosses_zero = ci_low <= 0 <= ci_high
    tail = (
        " (interval includes zero, so the sign is not resolved)"
        if crosses_zero
        else ""
    )
    return f"{estimate:+.4f}{unit} [95% CI {ci_low:+.4f}, {ci_high:+.4f}]{sig}{tail}"
