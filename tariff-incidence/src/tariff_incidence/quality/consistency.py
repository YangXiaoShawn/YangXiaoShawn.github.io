"""Cross-artefact consistency checks: do the result tables agree with each other?

The data-quality battery in ``checks`` validates the panel against itself. This
module validates the **results** against each other, which is a different failure
mode and the one that actually bit.

Every defect found by reading the eleven generated reports end to end was
invisible to the test suite, because a test exercises code on fixtures and these
were disagreements between artefacts that no code compared:

* a heterogeneity table that partitioned the diversion totals and summed to
  3.16x them, because a heading-level join was keyed on a line-level attribute;
* an exclusion bound whose denominator included six months of trade the tariff
  never touched;
* a specification register naming an aggregation level the panel had not used
  for four sessions;
* headline incidence figures typed into a report as literals, drifted from the
  estimates printed in the same document's tables.

The unifying property is that each was a **stated identity that nothing
evaluated**. These checks evaluate them. They are cheap, they run on whatever
results exist, and they are silent about artefacts that are absent rather than
treating absence as failure -- a partial pipeline run should not fail this.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from .checks import CheckResult, Severity

#: A partition may fall short of its whole by this fraction and still pass:
#: rows are legitimately excluded when a statistic is undefined for them, and
#: those exclusions are reported separately. It is tight enough that a fan-out,
#: which multiplies rather than shaves, cannot hide inside it.
PARTITION_TOLERANCE = 0.01


def _read(results_dir: Path, name: str) -> pl.DataFrame | None:
    p = results_dir / f"{name}.parquet"
    return pl.read_parquet(p) if p.exists() else None


def _skip(check_id: str, description: str, why: str) -> CheckResult:
    return CheckResult(
        check_id=check_id,
        description=description,
        severity=Severity.INFO,
        passed=None,
        n_flagged=0,
        n_total=0,
        detail=why,
    )


def check_diversion_partition_sums(results_dir: Path) -> CheckResult:
    """The dependence split must sum to the totals it partitions.

    This is the check that would have caught the 3.16x fan-out: the split and
    the totals are two views of the same headings, so their level columns agree
    or one of them is wrong. Percentage columns cannot catch it -- a ratio of
    two equally inflated quantities is exactly right.
    """
    cid = "DIVERSION_PARTITION_SUMS_TO_TOTALS"
    desc = "heterogeneity-by-dependence sums to the diversion totals it partitions"
    het = _read(results_dir, "diversion_heterogeneity_by_dependence")
    tot = _read(results_dir, "diversion_totals")
    if het is None or tot is None or tot.height == 0:
        return _skip(cid, desc, "diversion results not present")

    t = tot.row(0, named=True)
    pairs = [
        ("treated_change", "treated_total"),
        ("alternative_change", "alternative_total"),
        ("pre_treated_value", "pre_treated_value"),
    ]
    bad: list[str] = []
    for group_col, total_col in pairs:
        if group_col not in het.columns or total_col not in t:
            continue
        s, whole = float(het[group_col].sum()), float(t[total_col])
        if whole == 0:
            continue
        if abs(s - whole) / abs(whole) > PARTITION_TOLERANCE:
            bad.append(f"{group_col}={s:,.0f} vs {total_col}={whole:,.0f} ({s / whole:.2f}x)")

    return CheckResult(
        check_id=cid,
        description=desc,
        severity=Severity.ERROR,
        passed=not bad,
        n_flagged=len(bad),
        n_total=len(pairs),
        detail=(
            "; ".join(bad)
            if bad
            else "every level column in the split agrees with the totals table"
        ),
    )


def check_country_gains_sum(results_dir: Path) -> CheckResult:
    """Per-partner changes must add up to the alternative-source total."""
    cid = "DIVERSION_COUNTRY_GAINS_SUM_TO_ALTERNATIVE_TOTAL"
    desc = "per-partner changes sum to the alternative-source total"
    gains = _read(results_dir, "diversion_country_gains")
    tot = _read(results_dir, "diversion_totals")
    if gains is None or tot is None or tot.height == 0:
        return _skip(cid, desc, "diversion results not present")
    if "is_treated_country" not in gains.columns or "change" not in gains.columns:
        return _skip(cid, desc, "country gains table lacks the expected columns")

    alt = float(gains.filter(~pl.col("is_treated_country"))["change"].sum())
    whole = float(tot.row(0, named=True)["alternative_total"])
    ok = whole == 0 or abs(alt - whole) / abs(whole) <= PARTITION_TOLERANCE
    return CheckResult(
        check_id=cid,
        description=desc,
        severity=Severity.ERROR,
        passed=ok,
        n_flagged=0 if ok else 1,
        n_total=1,
        detail=f"partners sum to {alt:,.0f} against alternative_total {whole:,.0f}",
    )


def check_specification_level_matches_panel(
    results_dir: Path, panel: pl.DataFrame | None
) -> CheckResult:
    """The register's aggregation level must be the level the panel is keyed on.

    The register is what a reader consults instead of trusting the prose, so a
    stale level there is worse than a stale sentence. It claimed ``hs6`` for four
    sessions after the panel moved to ``hs10``.
    """
    cid = "SPEC_REGISTER_LEVEL_MATCHES_PANEL"
    desc = "specification register states the level the panel is actually keyed on"
    specs = _read(results_dir, "specification_register")
    if specs is None or panel is None or "aggregation_level" not in specs.columns:
        return _skip(cid, desc, "specification register or panel not present")

    expected = next((c for c in ("hs10", "hs8", "hs6") if c in panel.columns), None)
    if expected is None:
        return _skip(cid, desc, "panel has no recognised product column")

    stated = specs["aggregation_level"].unique().to_list()
    wrong = [s for s in stated if s and not str(s).startswith(expected)]
    return CheckResult(
        check_id=cid,
        description=desc,
        severity=Severity.ERROR,
        passed=not wrong,
        n_flagged=len(wrong),
        n_total=len(stated),
        detail=(
            f"panel is keyed on {expected}; register states {wrong}"
            if wrong
            else f"every specification states {expected}"
        ),
    )


def check_reported_incidence_matches_estimates(results_dir: Path) -> CheckResult:
    """The headline incidence figures must be the ones in the estimates table.

    They were literals in an f-string that interpolated nothing, and had drifted
    from the table printed below them in the same document. The report reads them
    now; this asserts the row it reads from still exists and is unique, so the
    reading cannot silently fall back to a stale constant.
    """
    cid = "INCIDENCE_HEADLINE_IS_TRACEABLE"
    desc = "headline incidence responses are selectable rows in the estimates table"
    est = _read(results_dir, "incidence_estimates")
    if est is None:
        return _skip(cid, desc, "incidence estimates not present")
    if "control_definition" not in est.columns:
        return CheckResult(
            check_id=cid,
            description=desc,
            severity=Severity.ERROR,
            passed=False,
            n_flagged=1,
            n_total=1,
            detail=(
                "stacked_mean_post_effect rows carry no control_definition, so the "
                "headline design can only be selected by row order"
            ),
        )

    mp = est.filter(
        (pl.col("term") == "stacked_mean_post_effect")
        & (pl.col("control_definition") == "never_treated_products")
        & (pl.col("rung") == "4_stacked" if "rung" in est.columns else pl.lit(True))
    )
    wanted = {"log_landed_unit_value", "log_customs_unit_value"}
    found = set(mp["outcome"].to_list())
    dupes = mp.height != mp["outcome"].n_unique()
    missing = sorted(wanted - found)
    ok = not missing and not dupes
    return CheckResult(
        check_id=cid,
        description=desc,
        severity=Severity.ERROR,
        passed=ok,
        n_flagged=len(missing) + (1 if dupes else 0),
        n_total=len(wanted),
        detail=(
            "landed and customs mean post-treatment effects are each a unique row"
            if ok
            else f"missing={missing} duplicated={dupes}"
        ),
    )


def check_exclusion_bound_population(results_dir: Path) -> CheckResult:
    """The bound's frame must start when a Section 301 duty was first in force.

    A month before the first action cannot contain a flow that falls short of a
    Section 301 duty, so its presence means the population was conditioned on
    something other than that duty -- it was the total rate, which includes
    baseline MFN, and it halved the pre-exclusion baseline the bound decomposes
    against.
    """
    cid = "EXCLUSION_BOUND_POPULATION_IS_TARIFFED_TRADE"
    desc = "the intention-to-treat bound covers only months with a Section 301 duty in force"
    bound = _read(results_dir, "exclusion_itt_bound_by_month")
    sched = None
    for candidate in (results_dir.parent / "normalized" / "tariff_schedule.parquet",):
        if candidate.exists():
            sched = pl.read_parquet(candidate)
    if bound is None or sched is None or "effective_date" not in sched.columns:
        return _skip(cid, desc, "bound or tariff schedule not present")

    # Compare on the month, not the date. The first action took effect mid-month
    # (2018-07-06), so July is partly treated and belongs in the frame; only
    # months entirely before it are evidence of the wrong population. Counting
    # on the raw date contradicted the pass condition, which already floored to
    # the month -- the check would have failed and then miscounted why.
    first_duty = sched["effective_date"].min()
    first_duty_month = first_duty.replace(day=1)
    first_month = bound["month_date"].min()
    ok = first_month is not None and first_month >= first_duty_month
    return CheckResult(
        check_id=cid,
        description=desc,
        severity=Severity.ERROR,
        passed=ok,
        n_flagged=0 if ok else int(bound.filter(pl.col("month_date") < first_duty_month).height),
        n_total=bound.height,
        detail=(
            f"bound starts {first_month}, first duty effective {first_duty}"
            + ("" if ok else "; months before the first action cannot fall short of it")
        ),
    )


def run_all(results_dir: Path, panel: pl.DataFrame | None = None) -> list[CheckResult]:
    """Every cross-artefact identity, in one pass."""
    return [
        check_diversion_partition_sums(results_dir),
        check_country_gains_sum(results_dir),
        check_specification_level_matches_panel(results_dir, panel),
        check_reported_incidence_matches_estimates(results_dir),
        check_exclusion_bound_population(results_dir),
        check_placebo_covers_every_verdicted_outcome(results_dir),
    ]


def check_placebo_covers_every_verdicted_outcome(results_dir: Path) -> CheckResult:
    """Every outcome carrying a pre-trend verdict must also carry a date placebo.

    The placebo ran on ``log_quantity`` alone and recorded no outcome at all, so
    the report showed a check reporting a significant effect with nothing saying
    what it applied to -- and the two price outcomes the incidence claim rests on
    were never date-placebo-tested. An outcome licensed for a causal reading by
    one test and untested by the other is a gap the reader cannot see.
    """
    cid = "PLACEBO_COVERS_EVERY_VERDICTED_OUTCOME"
    desc = "each outcome with a pre-trend verdict also has a date-placebo result naming it"
    import json

    p = results_dir / "identification_checks.json"
    if not p.exists():
        return _skip(cid, desc, "identification checks not present")
    doc = json.loads(p.read_text())

    verdicted = {
        k[len("pretrend_stacked_") : -len("_never_treated_products")]
        for k in doc.get("pretrend_tests", {})
        if k.startswith("pretrend_stacked_") and k.endswith("_never_treated_products")
    }
    placeboed = {
        c["outcome"]
        for c in doc.get("checks", [])
        if c.get("check") == "placebo_treatment_date_minus_12m" and c.get("outcome")
    }
    if not verdicted:
        return _skip(cid, desc, "no stacked pre-trend verdicts present")

    missing = sorted(verdicted - placeboed)
    return CheckResult(
        check_id=cid,
        description=desc,
        severity=Severity.ERROR,
        passed=not missing,
        n_flagged=len(missing),
        n_total=len(verdicted),
        detail=(
            f"outcomes with a verdict but no date placebo: {missing}"
            if missing
            else f"all {len(verdicted)} verdicted outcomes carry a named placebo result"
        ),
    )
