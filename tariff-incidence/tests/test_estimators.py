"""Estimator tests.

These check the econometrics against cases with a known answer: analytically
recoverable OLS, a Poisson process with a known coefficient, and a simulated
panel whose treatment effect is set by construction. An estimator that cannot
recover a parameter that was deliberately put into the data cannot be trusted to
measure one that was not.
"""

from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from tariff_incidence.econ.designs import (
    build_event_dummies,
    event_study,
    pretrend_test,
    two_way_fe_regression,
)
from tariff_incidence.econ.diversion import decompose
from tariff_incidence.econ.hdfe import FitResult, absorb, ols_hdfe, ppml_hdfe

# --------------------------------------------------------------------- #
# absorption
# --------------------------------------------------------------------- #


def test_single_effect_absorption_demeans_exactly_in_one_pass():
    g = np.array([0, 0, 1, 1, 2, 2])
    X = np.array([[1.0], [3.0], [10.0], [20.0], [5.0], [5.0]])
    out, iters, ok = absorb(X, [g])
    assert ok
    # one demeaning pass plus one confirming pass
    assert iters <= 2
    for grp in np.unique(g):
        assert out[g == grp].mean() == pytest.approx(0.0, abs=1e-12)


def test_two_way_absorption_converges():
    rng = np.random.default_rng(0)
    n = 400
    e = rng.integers(0, 20, n)
    t = rng.integers(0, 10, n)
    X = (rng.normal(size=(n, 2)) + e[:, None] * 0.3 + t[:, None] * 0.2)
    out, _, ok = absorb(X, [e, t])
    assert ok
    for g in (e, t):
        for grp in np.unique(g):
            assert np.abs(out[g == grp].mean(axis=0)).max() < 1e-6


# --------------------------------------------------------------------- #
# OLS with fixed effects
# --------------------------------------------------------------------- #


def test_ols_hdfe_recovers_a_known_slope():
    rng = np.random.default_rng(11)
    n_e, n_t = 40, 24
    e = np.repeat(np.arange(n_e), n_t)
    t = np.tile(np.arange(n_t), n_e)
    n = n_e * n_t
    alpha = rng.normal(0, 2, n_e)[e]
    gamma = rng.normal(0, 1, n_t)[t]
    x = rng.normal(0, 1, n)
    beta = 0.75
    y = alpha + gamma + beta * x + rng.normal(0, 0.05, n)

    fit = ols_hdfe(y, x[:, None], ["x"], {"entity": e, "time": t}, {"entity": e})
    assert fit.params["x"] == pytest.approx(beta, abs=0.01)
    lo, hi = fit.conf_int("x")
    assert lo < beta < hi


def test_ols_hdfe_matches_explicit_dummy_regression():
    rng = np.random.default_rng(3)
    n = 300
    e = rng.integers(0, 8, n)
    x = rng.normal(size=n)
    y = 1.5 * x + np.array([0.0, 1, 2, 3, 4, 5, 6, 7])[e] + rng.normal(0, 0.2, n)

    fit = ols_hdfe(y, x[:, None], ["x"], {"entity": e}, {"entity": e})
    D = np.column_stack([x] + [(e == k).astype(float) for k in range(8)])
    beta_dummy = np.linalg.lstsq(D, y, rcond=None)[0][0]
    assert fit.params["x"] == pytest.approx(beta_dummy, abs=1e-8)


def test_clustered_standard_errors_exceed_naive_ones_under_within_cluster_correlation():
    rng = np.random.default_rng(7)
    n_g, n_per = 30, 25
    g = np.repeat(np.arange(n_g), n_per)
    shock = rng.normal(0, 1.0, n_g)[g]
    x = rng.normal(size=n_g * n_per) + shock
    y = 0.5 * x + shock * 2.0 + rng.normal(0, 0.1, n_g * n_per)
    dummy = np.zeros_like(g)
    clustered = ols_hdfe(y, x[:, None], ["x"], {}, {"g": g})
    unclustered = ols_hdfe(y, x[:, None], ["x"], {}, {"obs": np.arange(y.size)})
    assert clustered.std_errors["x"] > unclustered.std_errors["x"]
    assert clustered.n_clusters["g"] == n_g
    assert dummy.size == y.size


# --------------------------------------------------------------------- #
# PPML
# --------------------------------------------------------------------- #


def test_ppml_recovers_a_known_poisson_coefficient():
    rng = np.random.default_rng(5)
    n = 6000
    x = rng.normal(0, 1, n)
    beta = -0.8
    mu = np.exp(2.0 + beta * x)
    y = rng.poisson(mu).astype(float)
    fit = ppml_hdfe(y, x[:, None], ["x"], {"const": np.zeros(n, dtype=int)}, {"obs": np.arange(n)})
    assert fit.converged
    assert fit.params["x"] == pytest.approx(beta, abs=0.05)


def test_ppml_recovers_the_coefficient_with_fixed_effects():
    rng = np.random.default_rng(9)
    n_e, n_t = 50, 20
    e = np.repeat(np.arange(n_e), n_t)
    t = np.tile(np.arange(n_t), n_e)
    n = n_e * n_t
    x = rng.normal(0, 1, n)
    beta = 0.4
    eta = 1.5 + rng.normal(0, 0.4, n_e)[e] + rng.normal(0, 0.2, n_t)[t] + beta * x
    y = rng.poisson(np.exp(eta)).astype(float)
    fit = ppml_hdfe(y, x[:, None], ["x"], {"e": e, "t": t}, {"e": e})
    assert fit.converged
    assert fit.params["x"] == pytest.approx(beta, abs=0.05)


def test_ppml_retains_zero_observations():
    rng = np.random.default_rng(13)
    n = 2000
    x = rng.normal(0, 1, n)
    y = rng.poisson(np.exp(0.2 - 0.5 * x)).astype(float)
    assert (y == 0).sum() > 0
    fit = ppml_hdfe(y, x[:, None], ["x"], {"c": np.zeros(n, dtype=int)}, {"obs": np.arange(n)})
    assert fit.n_obs == n, "PPML must use the zeros, not drop them"
    assert any("zero-valued observations retained" in note for note in fit.notes)


def test_ppml_rejects_negative_outcomes():
    with pytest.raises(ValueError, match="non-negative"):
        ppml_hdfe(
            np.array([-1.0, 2.0]), np.array([[1.0], [2.0]]), ["x"],
            {"c": np.zeros(2, dtype=int)}, {},
        )


# --------------------------------------------------------------------- #
# event study
# --------------------------------------------------------------------- #


def _sim_panel(effect: float = -0.30, n_prod: int = 30, seed: int = 42) -> pl.DataFrame:
    """Panel with a known post-treatment jump for treated flows of treated products."""
    rng = np.random.default_rng(seed)
    months = list(range(24))
    rows = []
    for p in range(n_prod):
        treated_product = p < n_prod // 2
        pi = rng.normal(0, 0.5)
        for c in ["5700", "5520", "5490"]:
            ci = rng.normal(0, 0.3)
            for m in months:
                et = m - 12
                is_treated_flow = treated_product and c == "5700"
                y = 5 + pi + ci + 0.01 * m + rng.normal(0, 0.05)
                if is_treated_flow and et >= 0:
                    y += effect
                rows.append(
                    {
                        "hs6": f"{p:06d}",
                        "country_code": c,
                        "flow_id": f"{p:06d}_{c}",
                        "month_key": f"m{m:02d}",
                        "event_time": et if treated_product else None,
                        "is_treated_country": c == "5700",
                        "y": y,
                        "count_outcome": float(np.exp(y - 4)),
                        "treat_rate": 0.25 if (is_treated_flow and et >= 0) else 0.0,
                    }
                )
    return pl.DataFrame(rows)


def test_event_study_recovers_a_known_step_effect():
    panel = _sim_panel(effect=-0.30)
    fit, spec, coefs = event_study(
        panel, "y", fixed_effects=["flow_id", "month_key"], cluster_vars=["hs6"],
        window=(-6, 6), reference=-1,
    )
    post = coefs.filter((pl.col("event_time") >= 0) & (pl.col("std_error") > 0))
    assert post["estimate"].mean() == pytest.approx(-0.30, abs=0.03)
    assert spec.estimator == "OLS-HDFE"


def test_event_study_pre_period_coefficients_are_flat_when_there_is_no_pretrend():
    panel = _sim_panel(effect=-0.30)
    fit, _, coefs = event_study(
        panel, "y", fixed_effects=["flow_id", "month_key"], cluster_vars=["hs6"],
        window=(-6, 6), reference=-1,
    )
    pt = pretrend_test(coefs, fit)
    assert pt["max_abs_pre_coef"] < 0.05
    # With a tightly simulated panel the standard errors are small enough that a
    # trivially small pre-coefficient can still be "significant". The design is
    # clean on the economic criterion, which is what the verdict encodes.
    assert pt["economically_small"]
    assert pt["verdict"] in ("CLEAN", "STATISTICALLY_DETECTABLE_BUT_ECONOMICALLY_SMALL")


def test_pretrend_test_detects_an_injected_pretrend():
    panel = _sim_panel(effect=-0.30).with_columns(
        pl.when(pl.col("is_treated_country") & pl.col("event_time").is_not_null())
        .then(pl.col("y") + 0.03 * pl.col("event_time"))
        .otherwise(pl.col("y"))
        .alias("y")
    )
    fit, _, coefs = event_study(
        panel, "y", fixed_effects=["flow_id", "month_key"], cluster_vars=["hs6"],
        window=(-6, 6), reference=-1,
    )
    pt = pretrend_test(coefs, fit)
    assert pt["any_pre_significant_5pct"], "a linear pre-trend must be detected"
    assert not pt["economically_small"]
    assert pt["verdict"] == "PRETREND_PRESENT"


def test_reference_period_is_reported_as_exactly_zero():
    panel = _sim_panel()
    _, _, coefs = event_study(
        panel, "y", fixed_effects=["flow_id", "month_key"], cluster_vars=["hs6"],
        window=(-6, 6), reference=-1,
    )
    ref = coefs.filter(pl.col("term").str.starts_with("evt_reference"))
    assert ref.height == 1
    assert ref.row(0, named=True)["estimate"] == 0.0


def test_event_dummies_bin_the_window_endpoints_rather_than_dropping_them():
    panel = _sim_panel()
    d, names = build_event_dummies(panel, window=(-3, 3), reference=-1)
    assert any(n.startswith("evt_pre_bin") for n in names)
    assert any(n.startswith("evt_post_bin") for n in names)
    assert d.height == panel.height, "no observation should be dropped"


def test_twfe_recovers_the_effect_per_unit_of_treatment():
    panel = _sim_panel(effect=-0.30)
    fit, _ = two_way_fe_regression(
        panel, "y", "treat_rate", fixed_effects=["flow_id", "month_key"], cluster_vars=["hs6"]
    )
    # effect is -0.30 at a treatment rate of 0.25 -> slope -1.2
    assert fit.params["treat_rate"] == pytest.approx(-1.2, abs=0.1)


def test_ppml_event_study_runs_on_a_count_outcome():
    panel = _sim_panel(effect=-0.30)
    fit, _, coefs = event_study(
        panel, "count_outcome", fixed_effects=["flow_id", "month_key"],
        cluster_vars=["hs6"], window=(-6, 6), reference=-1, estimator="ppml",
    )
    assert fit.estimator == "PPML-HDFE"
    post = coefs.filter((pl.col("event_time") >= 0) & (pl.col("std_error") > 0))
    assert post["estimate"].mean() == pytest.approx(-0.30, abs=0.06)


# --------------------------------------------------------------------- #
# diversion decomposition
# --------------------------------------------------------------------- #


def test_decomposition_margins_sum_to_the_total_change():
    rng = np.random.default_rng(2)
    rows = []
    for p in range(6):
        for c in ["5700", "5520"]:
            for m in range(24):
                et = m - 12
                v = 100.0 + rng.normal(0, 1)
                if c == "5700" and et >= 0:
                    v *= 0.7
                if c == "5520" and et >= 0:
                    v *= 1.4
                rows.append(
                    {"hs6": f"{p:06d}", "country_code": c, "event_time": et,
                     "customs_value": v, "month_index": m}
                )
    panel = pl.DataFrame(rows)
    by_p, totals = decompose(
        panel, treated_country_code="5700", pre_window=(-12, -1), post_window=(1, 10)
    )
    t = totals.row(0, named=True)
    assert t["treated_intensive"] + t["treated_extensive"] + t["alternative_intensive"] + t[
        "alternative_extensive"
    ] == pytest.approx(t["total_change"], rel=1e-9)
    assert t["treated_total"] < 0 < t["alternative_total"], (
        "contraction and expansion must be reported separately, not netted"
    )


def test_decomposition_separates_extensive_margin_exit():
    rows = []
    for m in range(24):
        et = m - 12
        rows.append({"hs6": "000001", "country_code": "5700", "event_time": et,
                     "customs_value": 100.0 if et < 0 else 0.0, "month_index": m})
        rows.append({"hs6": "000001", "country_code": "5520", "event_time": et,
                     "customs_value": 50.0, "month_index": m})
    by_p, totals = decompose(
        pl.DataFrame(rows), treated_country_code="5700",
        pre_window=(-12, -1), post_window=(1, 10),
    )
    t = totals.row(0, named=True)
    assert t["treated_extensive"] == pytest.approx(-100.0)
    assert t["treated_intensive"] == pytest.approx(0.0)
    assert t["n_treated_flows_exited"] == 1


# --------------------------------------------------------------------- #
# stacked multi-wave design
# --------------------------------------------------------------------- #


def _multiwave_panel(seed: int = 7) -> pl.DataFrame:
    """Three waves at three effective months, plus never-treated products.

    Treatment effects differ by cohort (-0.60, -0.40, -0.20). That heterogeneity
    is what breaks naive two-way fixed effects under staggered adoption: the
    estimator uses already-treated units as controls for later-treated ones, and
    the resulting "forbidden comparison" is weighted with signs that need not be
    positive. The stacked design never makes that comparison, because each
    sub-experiment's controls are never-treated units only.
    """
    rng = np.random.default_rng(seed)
    waves = {"W1": 24218, "W2": 24224, "W3": 24230}
    effects = {"W1": -0.60, "W2": -0.40, "W3": -0.20}
    months = list(range(24206, 24242))
    rows = []
    for p in range(60):
        cohort = ["W1", "W2", "W3"][p % 3] if p < 45 else "NEVER_TREATED"
        pi = rng.normal(0, 0.4)
        for c in ["5700", "5520"]:
            ci = rng.normal(0, 0.2)
            for m in months:
                treated_flow = cohort != "NEVER_TREATED" and c == "5700"
                y = 5 + pi + ci + 0.004 * (m - 24206) + rng.normal(0, 0.03)
                if treated_flow and m >= waves[cohort]:
                    y += effects[cohort]
                rows.append(
                    {
                        "hs6": f"{p:06d}", "hs10": f"{p:06d}0000",
                        "country_code": c, "flow_id": f"{p:06d}_{c}",
                        "month_key": f"m{m}", "month_index": m,
                        "treatment_cohort": cohort,
                        "is_treated_country": c == "5700",
                        "event_time": (m - waves[cohort]) if cohort != "NEVER_TREATED" else None,
                        "y": y,
                    }
                )
    return pl.DataFrame(rows)


WAVES = {"W1": 24218, "W2": 24224, "W3": 24230}
TRUE_MEAN_EFFECT = (-0.60 + -0.40 + -0.20) / 3


def test_stacked_design_assigns_one_sub_experiment_per_wave():
    from tariff_incidence.econ.designs import build_stacked_design

    st = build_stacked_design(_multiwave_panel(), WAVES, window=(-6, 6))
    assert set(st["stack_id"].unique()) == {"W1", "W2", "W3"}
    never = st.filter(pl.col("treatment_cohort") == "NEVER_TREATED")
    assert never["stack_id"].n_unique() == 3
    bad = st.filter(pl.col("stack_treated") & (pl.col("treatment_cohort") != pl.col("stack_id")))
    assert bad.height == 0


def test_stacked_design_never_uses_an_already_treated_unit_as_a_control():
    """The forbidden comparison under staggered adoption."""
    from tariff_incidence.econ.designs import build_stacked_design

    st = build_stacked_design(_multiwave_panel(), WAVES, window=(-6, 6))
    controls = st.filter(~pl.col("stack_treated"))
    other_cohort_treated = controls.filter(
        (pl.col("treatment_cohort") != "NEVER_TREATED")
        & (pl.col("treatment_cohort") != pl.col("stack_id"))
    )
    assert other_cohort_treated.height == 0


def test_stacked_design_breaks_event_time_calendar_time_collinearity():
    from tariff_incidence.econ.designs import build_stacked_design

    st = build_stacked_design(_multiwave_panel(), WAVES, window=(-6, 6))
    assert st.filter(pl.col("event_time") == 0)["month_index"].n_unique() == 3


def test_stacked_event_study_recovers_the_average_effect_under_heterogeneity():
    from tariff_incidence.econ.designs import stacked_event_study

    fit, spec, coefs, comp = stacked_event_study(
        _multiwave_panel(), "y", WAVES, cluster_vars=["hs6"], window=(-6, 6), reference=-3
    )
    post = coefs.filter((pl.col("event_time") >= 0) & (pl.col("std_error") > 0))
    assert post["estimate"].mean() == pytest.approx(TRUE_MEAN_EFFECT, abs=0.08)
    assert comp.height == 3
    assert "flow x stack" in spec.fixed_effects


def test_stacked_pre_period_is_flat_under_heterogeneous_staggered_treatment():
    from tariff_incidence.econ.designs import stacked_event_study

    fit, _, coefs, _ = stacked_event_study(
        _multiwave_panel(), "y", WAVES, cluster_vars=["hs6"], window=(-6, 6), reference=-3
    )
    pt = pretrend_test(coefs, fit)
    assert pt["economically_small"], f"stacked pre-period should be flat, got {pt}"


def test_naive_staggered_twfe_is_biased_where_the_stacked_design_is_not():
    """Motivates the whole rung: the naive design misses by more than stacking."""
    from tariff_incidence.econ.designs import stacked_event_study

    panel = _multiwave_panel()
    naive_fit, _, naive_coefs = event_study(
        panel, "y", fixed_effects=["flow_id", "month_key"], cluster_vars=["hs6"],
        window=(-6, 6), reference=-3,
    )
    naive_post = naive_coefs.filter(
        (pl.col("event_time") >= 0) & (pl.col("std_error") > 0)
    )["estimate"].mean()

    _, _, coefs, _ = stacked_event_study(
        panel, "y", WAVES, cluster_vars=["hs6"], window=(-6, 6), reference=-3
    )
    stacked_post = coefs.filter(
        (pl.col("event_time") >= 0) & (pl.col("std_error") > 0)
    )["estimate"].mean()

    assert abs(stacked_post - TRUE_MEAN_EFFECT) < abs(naive_post - TRUE_MEAN_EFFECT)


def test_stacked_design_rejects_an_unknown_control_definition():
    from tariff_incidence.econ.designs import build_stacked_design

    with pytest.raises(ValueError, match="unknown control_definition"):
        build_stacked_design(_multiwave_panel(), WAVES, control_definition="nonsense")


def test_stacked_design_requires_at_least_one_cohort():
    from tariff_incidence.econ.designs import build_stacked_design

    with pytest.raises(ValueError, match="cohort_months is empty"):
        build_stacked_design(_multiwave_panel(), {})


# --------------------------------------------------------------------- #
# pre-trend test: slope vs noise
# --------------------------------------------------------------------- #


def _coef_frame(pre: list[float], post: list[float], se: float = 0.02) -> pl.DataFrame:
    rows = []
    for i, b in enumerate(pre):
        rows.append({"term": f"m{i}", "event_time": -len(pre) + i, "estimate": b,
                     "std_error": se, "ci_low": b - 2 * se, "ci_high": b + 2 * se,
                     "p_value": 0.5, "is_pre": True})
    for i, b in enumerate(post):
        rows.append({"term": f"p{i}", "event_time": i, "estimate": b,
                     "std_error": se, "ci_low": b - 2 * se, "ci_high": b + 2 * se,
                     "p_value": 0.01, "is_pre": False})
    return pl.DataFrame(rows)


def _dummy_fit() -> FitResult:
    return FitResult(
        params={}, std_errors={}, n_obs=1000, n_params=1, estimator="OLS-HDFE",
        cluster_vars=["hs6"], n_clusters={"hs6": 50}, converged=True, iterations=1,
        absorbed_effects=["flow"], dof_resid=900,
    )


def test_flat_precise_pre_period_is_clean():
    c = _coef_frame(pre=[0.0, 0.01, -0.01, 0.0, 0.005], post=[0.15] * 5)
    t = pretrend_test(c, _dummy_fit())
    assert t["verdict"] == "CLEAN"
    assert abs(t["pre_slope_per_month"]) < 0.01


def test_noisy_but_trendless_pre_period_is_not_called_a_pretrend():
    """A flat-but-noisy pre-period is a precision problem, not a bias problem."""
    c = _coef_frame(pre=[-0.10, 0.12, -0.11, 0.09, -0.08], post=[-0.30] * 5)
    t = pretrend_test(c, _dummy_fit())
    assert t["verdict"] == "NOISY_PRE_PERIOD_NO_SLOPE"
    assert not t["slope_material"]
    assert not t["economically_small"], "it is genuinely noisy; that is still reported"


def test_genuine_linear_pretrend_is_flagged():
    c = _coef_frame(pre=[-0.20, -0.15, -0.10, -0.05, 0.0], post=[-0.30] * 5)
    t = pretrend_test(c, _dummy_fit())
    assert t["slope_material"], "a drift heading into treatment must be caught"
    assert t["verdict"] in ("PRETREND_PRESENT", "PRETREND_SLOPE_PRESENT")
    assert t["pre_slope_per_month"] > 0


def test_implied_bias_is_reported_in_outcome_units():
    c = _coef_frame(pre=[-0.20, -0.15, -0.10, -0.05, 0.0], post=[-0.30] * 5)
    t = pretrend_test(c, _dummy_fit())
    assert t["implied_bias_over_post_window"] is not None
    # slope ~ +0.05/month extrapolated across a post window centred at t=2
    assert t["implied_bias_over_post_window"] == pytest.approx(0.05 * 2.0, abs=0.02)


def test_like_for_like_and_legacy_ratios_are_both_reported():
    """The statistic was changed; both constructions stay visible so it is auditable."""
    c = _coef_frame(pre=[-0.10, 0.12, -0.11, 0.09, -0.08], post=[-0.30] * 5)
    t = pretrend_test(c, _dummy_fit())
    assert t["rms_pre_relative_to_rms_post"] < t["max_pre_relative_to_mean_post"], (
        "max-vs-mean overstates, which is why it was replaced"
    )
    for k in ["rms_pre_relative_to_rms_post", "max_pre_relative_to_max_post",
              "max_pre_relative_to_mean_post"]:
        assert k in t


def test_near_null_effect_is_bounded_not_called_a_pretrend():
    """A relative test punishes a small true effect; that case is detected on its own terms."""
    c = _coef_frame(pre=[0.01, -0.012, 0.008, -0.01, 0.011], post=[0.015, 0.012, 0.018, 0.01, 0.014])
    t = pretrend_test(c, _dummy_fit())
    assert t["verdict"] == "PRECISE_NULL_EFFECT_BOUNDED"
    assert not t["effect_separable_from_pre_noise"]
    assert t["effect_bound_abs"] is not None
    assert t["effect_bound_abs"] >= max(abs(x) for x in [0.015, 0.012, 0.018, 0.01, 0.014])


def test_a_large_clean_effect_is_not_reclassified_as_null():
    c = _coef_frame(pre=[0.0, 0.01, -0.01, 0.0, 0.005], post=[0.15] * 5)
    t = pretrend_test(c, _dummy_fit())
    assert t["verdict"] == "CLEAN"
    assert t["effect_separable_from_pre_noise"]
    assert t["effect_bound_abs"] is None


def test_a_genuine_pretrend_with_a_large_effect_is_still_flagged():
    """The null branch must not become an escape hatch for a real pre-trend."""
    c = _coef_frame(pre=[-0.20, -0.15, -0.10, -0.05, 0.0], post=[-0.30] * 5)
    t = pretrend_test(c, _dummy_fit())
    assert t["effect_separable_from_pre_noise"], "a -0.30 effect clears pre-noise"
    assert t["verdict"] != "PRECISE_NULL_EFFECT_BOUNDED"
    assert t["slope_material"]


def test_noisy_pre_period_with_a_detectable_effect_keeps_its_own_verdict():
    c = _coef_frame(pre=[-0.10, 0.12, -0.11, 0.09, -0.08], post=[-0.30] * 5)
    t = pretrend_test(c, _dummy_fit())
    assert t["verdict"] == "NOISY_PRE_PERIOD_NO_SLOPE"
    assert t["effect_separable_from_pre_noise"]


# --------------------------------------------------------------------- #
# not-yet-treated controls
# --------------------------------------------------------------------- #


def test_not_yet_treated_admits_only_cohorts_treated_after_the_window():
    """The rule that keeps this from becoming a forbidden comparison."""
    from tariff_incidence.econ.designs import build_stacked_design

    panel = _multiwave_panel()
    st = build_stacked_design(
        panel, WAVES, window=(-6, 6), control_definition="not_yet_treated"
    )
    # W1 at 24218 with window +6 ends at 24224. W2 (24224) is treated ON the
    # boundary and must be refused; W3 (24230) is safe.
    w1 = st.filter(pl.col("stack_id") == "W1")
    cohorts = set(w1["treatment_cohort"].unique())
    assert "W3" in cohorts, "a cohort treated after the window is admissible"
    assert "W2" not in cohorts, "a cohort treated inside the window must be refused"


def test_not_yet_treated_controls_are_never_flagged_treated():
    from tariff_incidence.econ.designs import build_stacked_design

    st = build_stacked_design(
        _multiwave_panel(), WAVES, window=(-6, 6), control_definition="not_yet_treated"
    )
    later = st.filter(
        (pl.col("treatment_cohort") != pl.col("stack_id"))
        & (pl.col("treatment_cohort") != "NEVER_TREATED")
    )
    assert later.height > 0
    assert not later["stack_treated"].any()


def test_not_yet_treated_never_admits_an_already_treated_unit():
    """The last stack has no safe later cohort, so it falls back to never-treated."""
    from tariff_incidence.econ.designs import build_stacked_design

    st = build_stacked_design(
        _multiwave_panel(), WAVES, window=(-6, 6), control_definition="not_yet_treated"
    )
    last = st.filter(pl.col("stack_id") == "W3")
    assert set(last["treatment_cohort"].unique()) == {"W3", "NEVER_TREATED"}


def test_not_yet_treated_enlarges_the_control_group_without_changing_the_estimate():
    from tariff_incidence.econ.designs import stacked_event_study

    panel = _multiwave_panel()
    out = {}
    for ctrl in ("never_treated_products", "not_yet_treated"):
        fit, _, coefs, _ = stacked_event_study(
            panel, "y", WAVES, cluster_vars=["hs6"], window=(-6, 6), reference=-3,
            control_definition=ctrl,
        )
        post = coefs.filter((pl.col("event_time") >= 0) & (pl.col("std_error") > 0))
        out[ctrl] = (float(post["estimate"].mean()), fit.n_obs)
    assert out["not_yet_treated"][1] > out["never_treated_products"][1], "larger sample"
    assert out["not_yet_treated"][0] == pytest.approx(
        out["never_treated_products"][0], abs=0.08
    ), "and the same answer"


def test_unknown_control_definition_is_still_rejected():
    from tariff_incidence.econ.designs import build_stacked_design

    with pytest.raises(ValueError, match="unknown control_definition"):
        build_stacked_design(_multiwave_panel(), WAVES, control_definition="whatever")


def test_binned_endpoints_are_labelled_by_period_and_excluded_from_trend_stats():
    """The pre-period bin was labelled `is_pre=False` because its event time is null.

    Two things went wrong from one cause. Reports printed it as a post-period
    row, and the pre-trend statistics stayed correct only because the post
    filter separately required a non-null event time -- so correctness rested on
    that one guard rather than on the rule being written down. The bin belongs
    to the pre period and belongs in neither trend statistic.
    """
    coefs = pl.DataFrame(
        {
            "term": ["evt_pre_bin_13", "evt_m2", "evt_reference_-1", "evt_p0", "evt_p1",
                     "evt_post_bin_11"],
            "event_time": [None, -2, -1, 0, 1, None],
            "estimate": [0.9, 0.01, 0.0, 0.20, 0.22, 0.9],
            "std_error": [0.01, 0.01, 0.0, 0.01, 0.01, 0.01],
            "ci_low": [0.0] * 6,
            "ci_high": [0.0] * 6,
            "p_value": [0.5] * 6,
            "is_pre": [True, True, True, False, False, False],
        }
    )

    class _Fit:
        n_obs = 1000
        params: dict = {}
        std_errors: dict = {}

    res = pretrend_test(coefs, _Fit())

    # One usable pre coefficient (-2); the reference has zero standard error and
    # the bin has no event time, so neither enters.
    assert res["n_pre_coefs"] == 1
    # The bins carry a deliberately huge estimate: if either leaked into a trend
    # statistic, these would not hold.
    assert res["rms_pre_coef"] == pytest.approx(0.01, abs=1e-9)
    assert res["rms_post_coef"] == pytest.approx(
        ((0.20**2 + 0.22**2) / 2) ** 0.5, abs=1e-9
    )


def test_dependence_split_reconciles_with_the_totals_it_partitions():
    """A heading-level join keyed on a line-level attribute fans out silently.

    `pretreatment_treated_country_share` is a property of the 10-digit line, and
    several lines sit under one HS6. Taking `.unique()` over (hs6, share) kept
    one row per distinct share, so joining it to the per-heading decomposition
    multiplied every heading by however many shares it had -- 4,355 rows for
    1,376 headings. Percentage changes survived, because numerator and
    denominator inflate together, which is why the table looked plausible while
    its levels disagreed with the totals table in the same report by 3.16x.

    The invariant that catches it: a partition of the headings must sum to what
    it partitions.
    """
    by_product = pl.DataFrame(
        {
            "hs6": ["100100", "200200", "300300"],
            "treated_total": [-100.0, -200.0, -300.0],
            "alternative_total": [40.0, 50.0, 60.0],
            "pre_treated_value": [1000.0, 2000.0, 3000.0],
            "replacement_ratio": [0.4, 0.25, 0.2],
        }
    )
    # Two lines under 100100 carry different shares -- the fan-out trigger.
    line_level = pl.DataFrame(
        {
            "hs6": ["100100", "100100", "200200", "300300"],
            "pretreatment_treated_country_share": [0.9, 0.1, 0.5, 0.2],
        }
    )

    naive = line_level.unique().join(by_product, on="hs6", how="inner")
    assert naive.height == 4  # the defect: three headings became four rows
    assert naive["treated_total"].sum() != pytest.approx(by_product["treated_total"].sum())

    # One share per heading, however it is derived, restores the partition.
    per_heading = line_level.group_by("hs6").agg(
        pl.col("pretreatment_treated_country_share").mean()
    )
    fixed = per_heading.join(by_product, on="hs6", how="inner")
    assert fixed.height == by_product.height
    for col in ["treated_total", "alternative_total", "pre_treated_value"]:
        assert fixed[col].sum() == pytest.approx(by_product[col].sum())
