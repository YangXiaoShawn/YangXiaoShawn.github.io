"""Estimation designs: the model ladder from descriptive means to event studies.

Every design here states its estimand, its identifying assumption, and what
would falsify it. Fixed effects are chosen to match the estimand rather than to
maximise fit -- for instance, product-time effects are included when the target
is *relative* reallocation across sourcing countries within a product, and
deliberately excluded when the target is the *level* response of a product's
total imports, because product-time effects would absorb exactly that.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import polars as pl

from .hdfe import FitResult, ols_hdfe, ppml_hdfe


@dataclass(slots=True)
class DesignSpec:
    """A fully described specification, carried into every results table."""

    name: str
    outcome: str
    estimator: str
    treatment_definition: str
    fixed_effects: list[str]
    cluster_vars: list[str]
    sample_filter: str
    weighting: str
    aggregation_level: str
    estimand: str
    identifying_assumption: str
    falsification: str
    notes: list[str] = field(default_factory=list)

    def to_row(self) -> dict:
        return {
            "specification": self.name,
            "outcome": self.outcome,
            "estimator": self.estimator,
            "treatment_definition": self.treatment_definition,
            "fixed_effects": " + ".join(self.fixed_effects),
            "cluster_vars": ", ".join(self.cluster_vars),
            "sample": self.sample_filter,
            "weighting": self.weighting,
            "aggregation_level": self.aggregation_level,
            "estimand": self.estimand,
            "identifying_assumption": self.identifying_assumption,
        }


def _fe_arrays(df: pl.DataFrame, fe: list[str]) -> dict[str, np.ndarray]:
    out: dict[str, np.ndarray] = {}
    for f in fe:
        if "*" in f:
            parts = [p.strip() for p in f.split("*")]
            vals = df.select(parts).with_columns(
                pl.concat_str([pl.col(p).cast(pl.String) for p in parts], separator="\x1f").alias("_k")
            )["_k"].to_numpy()
            out[f] = vals
        else:
            out[f] = df[f].to_numpy()
    return out


def _cluster_arrays(df: pl.DataFrame, cl: list[str]) -> dict[str, np.ndarray]:
    return {c: df[c].to_numpy() for c in cl}


def descriptive_event_means(
    panel: pl.DataFrame,
    outcome: str,
    *,
    treat_col: str = "is_treated_country",
    event_col: str = "event_time",
    window: tuple[int, int] = (-12, 12),
) -> pl.DataFrame:
    """Rung 1: raw means by event time and treatment status.

    Purely descriptive. Differences here confound the tariff with anything else
    that moved at the same time; they exist to show the raw data before any
    modelling, not to support a causal claim.
    """
    lo, hi = window
    d = panel.filter(
        pl.col(event_col).is_not_null()
        & (pl.col(event_col) >= lo)
        & (pl.col(event_col) <= hi)
        & pl.col(outcome).is_not_null()
        & pl.col(outcome).is_finite()
    )
    return (
        d.group_by([event_col, treat_col])
        .agg(
            pl.col(outcome).mean().alias("mean"),
            pl.col(outcome).median().alias("median"),
            pl.col(outcome).std().alias("sd"),
            pl.len().alias("n_obs"),
        )
        .sort([event_col, treat_col])
    )


def _observation_level(panel: pl.DataFrame) -> str:
    """The level a specification is actually estimated at, read off the panel.

    This was the fixed string "hs6 x country x month", written when the panel was
    keyed on the 6-digit heading. The panel moved to the 10-digit statistical
    reporting number, and the specification register -- the project's own record
    of what estimand was estimated at what level -- went on claiming 353,188
    heading-level cells for regressions running on 923,440 line-level ones.
    """
    for col in ("hs10", "hs8", "hs6"):
        if col in panel.columns:
            return f"{col} x country x month"
    return "unknown x country x month"


def two_way_fe_regression(
    panel: pl.DataFrame,
    outcome: str,
    treatment: str,
    *,
    fixed_effects: list[str],
    cluster_vars: list[str],
    weights_col: str | None = None,
    extra_regressors: list[str] | None = None,
) -> tuple[FitResult, DesignSpec]:
    """Rung 2: a single treatment coefficient with absorbed fixed effects."""
    regs = [treatment] + (extra_regressors or [])
    cols = [outcome, *regs, *{c for f in fixed_effects for c in f.split("*")}, *cluster_vars]
    if weights_col:
        cols.append(weights_col)
    d = panel.select(sorted(set(c.strip() for c in cols))).drop_nulls(
        subset=[outcome, *regs]
    )
    d = d.filter(pl.col(outcome).is_finite())

    y = d[outcome].to_numpy()
    X = np.column_stack([d[r].to_numpy().astype(float) for r in regs])
    w = d[weights_col].to_numpy() if weights_col else None

    fit = ols_hdfe(y, X, regs, _fe_arrays(d, fixed_effects), _cluster_arrays(d, cluster_vars), w)
    spec = DesignSpec(
        name=f"twfe_{outcome}_on_{treatment}",
        outcome=outcome,
        estimator="OLS-HDFE",
        treatment_definition=treatment,
        fixed_effects=fixed_effects,
        cluster_vars=cluster_vars,
        sample_filter="non-missing, finite outcome",
        weighting=weights_col or "unweighted",
        aggregation_level=_observation_level(panel),
        estimand="average effect of the additional duty on the outcome",
        identifying_assumption=(
            "conditional on the absorbed effects, treated and untreated flows would have "
            "followed parallel paths"
        ),
        falsification="non-zero pre-treatment coefficients in the event study",
    )
    return fit, spec


def build_event_dummies(
    df: pl.DataFrame,
    *,
    event_col: str = "event_time",
    treat_col: str = "is_treated_country",
    window: tuple[int, int] = (-12, 12),
    reference: int = -1,
) -> tuple[pl.DataFrame, list[str]]:
    """Interact event-time indicators with treatment, omitting the reference period.

    Observations outside the window are **binned** into endpoint indicators
    rather than dropped, so the comparison group does not silently change
    composition at the window edge.
    """
    lo, hi = window
    et = pl.col(event_col)
    binned = (
        pl.when(et.is_null())
        .then(None)
        .when(et < lo)
        .then(pl.lit(lo - 1))
        .when(et > hi)
        .then(pl.lit(hi + 1))
        .otherwise(et)
        .alias("_et_binned")
    )
    d = df.with_columns(binned)
    levels = [lo - 1, *range(lo, hi + 1), hi + 1]
    names: list[str] = []
    exprs = []
    for k in levels:
        if k == reference:
            continue
        label = f"evt_{'m' if k < 0 else 'p'}{abs(k)}"
        if k == lo - 1:
            label = f"evt_pre_bin_{abs(lo - 1)}"
        if k == hi + 1:
            label = f"evt_post_bin_{hi + 1}"
        names.append(label)
        exprs.append(
            (
                (pl.col("_et_binned") == k).fill_null(False) & pl.col(treat_col)
            ).cast(pl.Float64).alias(label)
        )
    return d.with_columns(exprs), names


def event_study(
    panel: pl.DataFrame,
    outcome: str,
    *,
    fixed_effects: list[str],
    cluster_vars: list[str],
    window: tuple[int, int] = (-12, 12),
    reference: int = -1,
    treat_col: str = "is_treated_country",
    weights_col: str | None = None,
    estimator: str = "ols",
) -> tuple[FitResult, DesignSpec, pl.DataFrame]:
    """Rung 3: dynamic treatment effects by event time.

    Pre-period coefficients are the test, not decoration: if they differ from
    zero, the parallel-trends assumption behind every other rung is in doubt and
    the post-period coefficients should not be read as causal.
    """
    d, dummies = build_event_dummies(
        panel, treat_col=treat_col, window=window, reference=reference
    )
    need = {c for f in fixed_effects for c in f.split("*")}
    keep = sorted({outcome, *dummies, *need, *cluster_vars, *( [weights_col] if weights_col else [])})
    d = d.select(keep).drop_nulls(subset=[outcome])
    if estimator == "ols":
        d = d.filter(pl.col(outcome).is_finite())

    y = d[outcome].to_numpy()
    X = np.column_stack([d[c].to_numpy() for c in dummies])
    fe = _fe_arrays(d, fixed_effects)
    cl = _cluster_arrays(d, cluster_vars)

    if estimator == "ppml":
        fit = ppml_hdfe(y, X, dummies, fe, cl)
    else:
        w = d[weights_col].to_numpy() if weights_col else None
        fit = ols_hdfe(y, X, dummies, fe, cl, w)

    rows = []
    for name in dummies:
        if name.startswith("evt_pre_bin") or name.startswith("evt_post_bin"):
            k = None
        elif name.startswith("evt_m"):
            k = -int(name.split("evt_m")[1])
        else:
            k = int(name.split("evt_p")[1])
        lo_ci, hi_ci = fit.conf_int(name)
        rows.append(
            {
                "term": name,
                "event_time": k,
                "estimate": fit.params[name],
                "std_error": fit.std_errors[name],
                "ci_low": lo_ci,
                "ci_high": hi_ci,
                "p_value": fit.pvalue(name),
                # The binned endpoints have no single event time, so `k` is
                # None -- but `evt_pre_bin_*` is unambiguously a pre-period
                # coefficient and labelling it otherwise printed it in reports
                # as a post-period row. The trend statistics exclude both bins
                # regardless, via the event_time filter in pretrend_test.
                "is_pre": (k < 0) if k is not None else name.startswith("evt_pre_bin"),
                "is_binned_endpoint": k is None,
            }
        )
    # The omitted reference period is zero by construction; show it explicitly.
    rows.append(
        {
            "term": f"evt_reference_{reference}",
            "event_time": reference,
            "estimate": 0.0,
            "std_error": 0.0,
            "ci_low": 0.0,
            "ci_high": 0.0,
            "p_value": float("nan"),
            "is_pre": reference < 0,
        }
    )
    coefs = pl.DataFrame(rows).sort("event_time", nulls_last=True)

    spec = DesignSpec(
        name=f"event_study_{outcome}_{estimator}",
        outcome=outcome,
        estimator="PPML-HDFE" if estimator == "ppml" else "OLS-HDFE",
        treatment_definition=(
            f"event-time indicators interacted with {treat_col}; reference period {reference}"
        ),
        fixed_effects=fixed_effects,
        cluster_vars=cluster_vars,
        sample_filter=f"event window [{window[0]}, {window[1]}] with binned endpoints",
        weighting=weights_col or "unweighted",
        aggregation_level=_observation_level(panel),
        estimand="dynamic effect of the tariff action relative to the reference month",
        identifying_assumption="parallel trends absent treatment, no anticipation before the window",
        falsification="pre-period coefficients jointly different from zero",
    )
    return fit, spec, coefs


def pretrend_test(
    coefs: pl.DataFrame,
    fit: FitResult,
    relative_threshold: float = 0.20,
    null_multiple: float = 2.0,
) -> dict:
    """Assess pre-period event-study coefficients on three separate criteria.

    **Slope.** Parallel trends is a statement about *slopes*, not levels. A
    constant pre-period offset is absorbed by the reference-period
    normalisation and is largely harmless; a drift heading into treatment is
    the real threat, because extrapolating it into the post window contaminates
    the estimate. The pre-period coefficients are regressed on event time and
    the implied bias over the post window is reported in the outcome's own
    units, which is what a reader actually needs.

    **Magnitude, like for like.** An earlier version of this function compared
    ``max|pre|`` against ``mean|post|``. That is apples to oranges: the maximum
    of a dozen noisy coefficients is mechanically larger than the mean of
    another dozen, so it flagged designs whose pre-periods were merely noisy.
    The primary magnitude statistic is now RMS against RMS. ``max/max`` and the
    old ``max/mean`` are both still reported so the change is auditable and so
    no verdict rests on one construction.

    **Significance.** Whether the pre-period coefficients are distinguishable
    from zero at all. Reported, but never sufficient on its own: in a large
    panel the standard errors shrink until economically trivial movement is
    significant.

    **Small true effects.** A relative-magnitude criterion punishes an outcome
    whose effect really is near zero: such an outcome fails "pre-noise relative
    to post-effect" however clean the design, because the denominator is small.
    That case is detected on its own terms. When the post-treatment path does
    not rise clear of the pre-period noise (``rms_post < null_multiple *
    rms_pre``) the verdict is ``PRECISE_NULL_EFFECT_BOUNDED`` and
    ``effect_bound_abs`` reports how large the effect could be given both the
    observed post path and the slope bias. A bound on a near-zero effect is a
    finding, not a failure -- for tariff incidence, a bounded-small exporter
    price response is exactly what completes the pass-through account.

    The chi-square statistic uses the diagonal of the covariance only, so it is
    an approximation to the joint test, not the exact one.
    """
    # Only coefficients sitting at a definite event time enter these statistics.
    # The binned endpoints aggregate everything beyond the window, so they have
    # no event time to regress on and no defined position in a trend. Both sides
    # state that condition explicitly: the post side used to carry it alone,
    # which meant correctness rested on that one guard rather than on the rule
    # being written down.
    at_event_time = pl.col("std_error") > 0
    if "event_time" in coefs.columns:
        at_event_time = at_event_time & pl.col("event_time").is_not_null()
    pre = coefs.filter(pl.col("is_pre") & at_event_time)
    post = coefs.filter((~pl.col("is_pre")) & at_event_time)
    if pre.height == 0:
        return {"n_pre_coefs": 0, "test": "unavailable"}

    from scipy import stats as st

    b_pre = pre["estimate"].to_numpy()
    se_pre = pre["std_error"].to_numpy()
    t_pre = pre["event_time"].to_numpy().astype(float)

    z = b_pre / se_pre
    stat = float(np.sum(z**2))
    p_joint = float(st.chi2.sf(stat, df=pre.height))
    any_sig = bool((pre["p_value"] < 0.05).any())

    max_pre = float(np.abs(b_pre).max())
    rms_pre = float(np.sqrt((b_pre**2).mean()))

    b_post = post["estimate"].to_numpy() if post.height else np.array([np.nan])
    mean_post = float(np.abs(b_post).mean())
    rms_post = float(np.sqrt((b_post**2).mean()))
    max_post = float(np.abs(b_post).max())

    def _ratio(a: float, b: float) -> float | None:
        return a / b if b and np.isfinite(b) and b > 0 else None

    rms_ratio = _ratio(rms_pre, rms_post)
    max_ratio = _ratio(max_pre, max_post)
    legacy_ratio = _ratio(max_pre, mean_post)

    # Pre-period slope, weighted by precision, plus the bias it would imply if
    # extrapolated across the post window.
    slope = slope_se = slope_p = implied_bias = None
    if pre.height >= 3 and np.ptp(t_pre) > 0:
        w = 1.0 / np.clip(se_pre, 1e-12, None) ** 2
        X = np.column_stack([np.ones_like(t_pre), t_pre])
        W = np.diag(w)
        XtWX_inv = np.linalg.pinv(X.T @ W @ X)
        beta = XtWX_inv @ (X.T @ W @ b_pre)
        resid = b_pre - X @ beta
        dof = max(pre.height - 2, 1)
        sigma2 = float((w * resid**2).sum() / dof)
        cov = XtWX_inv * sigma2
        slope = float(beta[1])
        slope_se = float(np.sqrt(max(cov[1, 1], 0.0)))
        slope_p = (
            float(2 * st.t.sf(abs(slope / slope_se), dof)) if slope_se > 0 else None
        )
        if post.height:
            implied_bias = float(slope * float(np.mean(post["event_time"].to_numpy())))

    slope_material = (
        implied_bias is not None
        and rms_post > 0
        and abs(implied_bias) > relative_threshold * rms_post
    )
    magnitude_small = rms_ratio is not None and rms_ratio < relative_threshold

    # A relative-magnitude test systematically punishes a small true effect: an
    # outcome whose effect really is zero fails "pre-noise relative to
    # post-effect" no matter how clean the design. Detect that case explicitly
    # instead of mislabelling it a pre-trend. The signature is a post-treatment
    # path that does not rise clear of the pre-period noise.
    effect_separable = rms_post >= null_multiple * rms_pre if rms_pre > 0 else True
    # A genuine pre-trend inflates the pre-period RMS and, by offsetting the
    # effect, deflates the post-period RMS -- which can push the ratio below the
    # threshold and disguise a contaminated design as a null. The null branch is
    # therefore gated on the slope being statistically undetectable, not on
    # another ratio. A test with an injected linear pre-trend caught exactly this
    # false positive.
    slope_detectable = slope_p is not None and slope_p < 0.05
    is_precise_null = (not effect_separable) and not slope_detectable
    effect_bound = (
        float(max_post + abs(implied_bias or 0.0)) if is_precise_null else None
    )

    if is_precise_null:
        verdict = "PRECISE_NULL_EFFECT_BOUNDED"
    elif magnitude_small and not slope_material:
        verdict = "CLEAN"
    elif magnitude_small and slope_material:
        verdict = "PRETREND_SLOPE_PRESENT"
    elif not magnitude_small and not slope_material:
        verdict = "NOISY_PRE_PERIOD_NO_SLOPE"
    else:
        verdict = "PRETREND_PRESENT"

    return {
        "n_pre_coefs": pre.height,
        "approx_chi2": stat,
        "approx_p_value": p_joint,
        "any_pre_significant_5pct": any_sig,
        "max_abs_pre_coef": max_pre,
        "rms_pre_coef": rms_pre,
        "mean_abs_post_coef": mean_post,
        "rms_post_coef": rms_post,
        "max_abs_post_coef": max_post,
        "rms_pre_relative_to_rms_post": rms_ratio,
        "max_pre_relative_to_max_post": max_ratio,
        "max_pre_relative_to_mean_post": legacy_ratio,
        "pre_slope_per_month": slope,
        "pre_slope_se": slope_se,
        "pre_slope_p_value": slope_p,
        "implied_bias_over_post_window": implied_bias,
        "slope_material": slope_material,
        "economically_small": magnitude_small,
        "effect_separable_from_pre_noise": effect_separable,
        "slope_detectable": slope_detectable,
        "effect_bound_abs": effect_bound,
        "null_multiple": null_multiple,
        "relative_threshold": relative_threshold,
        "verdict": verdict,
        "caveat": (
            "Parallel trends concerns slopes; a flat but noisy pre-period is a precision "
            "problem, not a bias problem, and is reported as NOISY_PRE_PERIOD_NO_SLOPE. "
            "The chi-square is a diagonal-only approximation. Statistical significance of a "
            "pre-coefficient is not by itself grounds to reject a design in a large panel."
        ),
    }


def ppml_trade_flow(
    panel: pl.DataFrame,
    *,
    outcome: str = "customs_value",
    treatment: str = "log1p_total_tariff",
    fixed_effects: list[str],
    cluster_vars: list[str],
    extra_regressors: list[str] | None = None,
) -> tuple[FitResult, DesignSpec]:
    """Rung 5: PPML on the trade flow in levels, retaining zeros."""
    regs = [treatment] + (extra_regressors or [])
    need = {c for f in fixed_effects for c in f.split("*")}
    d = panel.select(sorted({outcome, *regs, *need, *cluster_vars})).drop_nulls(
        subset=[outcome, *regs]
    )
    d = d.filter(pl.col(outcome) >= 0)

    y = d[outcome].to_numpy()
    X = np.column_stack([d[r].to_numpy().astype(float) for r in regs])
    fit = ppml_hdfe(y, X, regs, _fe_arrays(d, fixed_effects), _cluster_arrays(d, cluster_vars))
    spec = DesignSpec(
        name=f"ppml_{outcome}_on_{treatment}",
        outcome=outcome,
        estimator="PPML-HDFE",
        treatment_definition=treatment,
        fixed_effects=fixed_effects,
        cluster_vars=cluster_vars,
        sample_filter="non-negative outcome, zeros retained",
        weighting="PPML (implicit)",
        aggregation_level=_observation_level(panel),
        estimand="semi-elasticity of the trade flow in levels with respect to the tariff term",
        identifying_assumption=(
            "correct conditional mean given the absorbed effects; tariff variation is "
            "conditionally exogenous"
        ),
        falsification="event-study pre-trends; placebo dates; leave-one-sector-out instability",
    )
    return fit, spec


# ------------------------------------------------------------------------- #
# Rung 4: stacked multi-wave design
# ------------------------------------------------------------------------- #


def build_stacked_design(
    panel: pl.DataFrame,
    cohort_months: dict[str, int],
    *,
    window: tuple[int, int] = (-12, 10),
    cohort_col: str = "treatment_cohort",
    never_treated_label: str = "NEVER_TREATED",
    treat_country_col: str = "is_treated_country",
    control_definition: str = "never_treated_products",
) -> pl.DataFrame:
    """Build a stacked event-study dataset, one sub-experiment per treatment wave.

    Why this exists
    ---------------

    **The primary reason is the forbidden comparison.** With staggered adoption,
    two-way fixed effects uses already-treated units as controls for
    later-treated ones. When effects differ across waves -- and Section 301's do,
    since Lists 1 and 2 impose 25% while List 3 began at 10% -- those comparisons
    enter with weights that need not be positive, and the pooled estimate need
    not lie inside the range of the true effects. Each sub-experiment here draws
    its controls from never-treated products only, so that comparison is never
    made. There is a regression test asserting that the naive staggered design
    lands further from a known average effect than this one does.

    **A secondary reason is calendar-time collinearity.** With a single
    treatment date, event time is identical to calendar time for every treated
    unit, so treated-group-specific time variation cannot be separated from
    treatment dynamics. Three waves at three dates (2018-07-06, 2018-08-23,
    2018-09-24) weaken that, since event month k falls in a different calendar
    month per wave -- though with waves only weeks apart the averaging is
    partial, not a cure. On this panel the single-wave design left
    ``log_quantity`` with pre-period coefficients as large as its post-treatment
    effect, and country-by-month, chapter-by-month and
    month-of-year-by-treated-group effects all failed to remove them.

    Construction
    ------------

    For each wave *g* with treatment month *m_g*, take the window
    ``[m_g + window[0], m_g + window[1]]`` and keep wave-*g* products plus
    controls. Each sub-experiment gets its own copy of the fixed effects
    (``stack_flow``, ``stack_month``), so no unit is ever used as a control for
    a period in which it is itself treated -- the failure mode of two-way fixed
    effects under staggered adoption.

    A never-treated unit appears in all three sub-experiments. Clustering on the
    product handles the repetition, since the same product carries the same
    cluster id in every stack.

    ``control_definition``
        ``"never_treated_products"`` -- controls are never-treated products,
        all partners.
        ``"never_treated_products_treated_country_only"`` -- controls are
        never-treated products imported from the treated country only. Immune to
        the diversion spillover that makes third-country suppliers invalid
        controls, at the cost of a weaker common-shock argument.
        ``"not_yet_treated"`` -- never-treated products **plus** products
        belonging to a cohort whose own treatment falls entirely after this
        sub-experiment's window, so they are untreated throughout it.

    Why ``not_yet_treated`` matters here
    ------------------------------------

    By September 2019 almost every line in the sampled chapters had been
    tariffed. The never-treated residual is 379 lines -- 7% of the sample -- and
    not a random 7%: they are what USTR declined to tariff even in the $300
    billion round, so the counterfactual rests on a selected set. Products
    tariffed *later* are untreated during an earlier wave's window and are
    economically far closer to the treated group, which is the point of the
    not-yet-treated comparison.

    Admissibility is checked per sub-experiment rather than assumed: a cohort
    qualifies only if its treatment month falls strictly after the end of this
    window. Using a unit that becomes treated inside the window would reintroduce
    the forbidden comparison this design exists to avoid, so the rule is
    enforced, not left to the caller.
    """
    if not cohort_months:
        raise ValueError("cohort_months is empty; nothing to stack")
    lo, hi = window
    frames: list[pl.DataFrame] = []

    admissible_by_stack: dict[str, list[str]] = {}
    for g, m_g in sorted(cohort_months.items()):
        keep = [g, never_treated_label]
        if control_definition == "not_yet_treated":
            # A later cohort is admissible only if its own treatment starts after
            # this window ends, so it is untreated for every period used here.
            not_yet = [
                h
                for h, m_h in cohort_months.items()
                if h != g and m_h > m_g + hi
            ]
            keep += not_yet
            admissible_by_stack[g] = not_yet
        elif control_definition not in (
            "never_treated_products",
            "never_treated_products_treated_country_only",
        ):
            raise ValueError(f"unknown control_definition {control_definition!r}")

        sub = panel.filter(
            pl.col("month_index").is_between(m_g + lo, m_g + hi)
            & (pl.col(cohort_col).is_in(keep))
        )
        if control_definition == "never_treated_products_treated_country_only":
            sub = sub.filter(pl.col(treat_country_col))
        if sub.height == 0:
            continue
        frames.append(
            sub.with_columns(
                pl.lit(g).alias("stack_id"),
                (pl.col("month_index") - m_g).alias("event_time"),
                ((pl.col(cohort_col) == g) & pl.col(treat_country_col)).alias("stack_treated"),
                pl.lit(m_g).alias("stack_treatment_month"),
                pl.lit(
                    "|".join(sorted(admissible_by_stack.get(g, []))) or "none"
                ).alias("not_yet_treated_cohorts"),
            )
        )
    if not frames:
        raise ValueError("stacked design is empty; check the window and cohort labels")

    out = pl.concat(frames, how="diagonal_relaxed")
    return out.with_columns(
        pl.concat_str([pl.col("flow_id"), pl.col("stack_id")], separator="@").alias("stack_flow"),
        pl.concat_str([pl.col("month_key"), pl.col("stack_id")], separator="@").alias("stack_month"),
    )


def stacked_event_study(
    panel: pl.DataFrame,
    outcome: str,
    cohort_months: dict[str, int],
    *,
    cluster_vars: list[str],
    window: tuple[int, int] = (-12, 10),
    reference: int = -3,
    control_definition: str = "never_treated_products",
    estimator: str = "ols",
) -> tuple[FitResult, DesignSpec, pl.DataFrame, pl.DataFrame]:
    """Rung 4: event study on the stacked multi-wave design.

    Returns ``(fit, spec, coefficients, stack_composition)``. The composition
    table is returned rather than logged so the weight each wave carries is
    visible in the results, not buried.
    """
    stacked = build_stacked_design(
        panel, cohort_months, window=window, control_definition=control_definition
    )
    composition = (
        stacked.group_by("stack_id")
        .agg(
            pl.len().alias("n_obs"),
            pl.col("stack_treated").sum().alias("n_treated_obs"),
            pl.col("hs10").n_unique().alias("n_products")
            if "hs10" in stacked.columns
            else pl.col("hs6").n_unique().alias("n_products"),
            pl.col("stack_treatment_month").first().alias("treatment_month_index"),
        )
        .sort("stack_id")
    )

    fit, spec, coefs = event_study(
        stacked,
        outcome,
        fixed_effects=["stack_flow", "stack_month"],
        cluster_vars=cluster_vars,
        window=window,
        reference=reference,
        treat_col="stack_treated",
        estimator=estimator,
    )
    spec.name = f"stacked_event_study_{outcome}_{control_definition}"
    spec.fixed_effects = ["flow x stack", "calendar month x stack"]
    spec.sample_filter = (
        f"stacked sub-experiments, one per wave, window [{window[0]}, {window[1]}]; "
        f"controls = {control_definition}"
    )
    spec.estimand = (
        "dynamic effect of a wave relative to event month "
        f"{reference}, pooled across waves with wave-specific calendar-time effects"
    )
    spec.identifying_assumption = (
        "within each sub-experiment, treated and control products would have followed "
        "parallel paths absent that wave"
    )
    spec.notes.append(
        "Event time is not collinear with calendar time here, because each wave's event "
        "month 0 falls in a different calendar month."
    )
    return fit, spec, coefs, composition
