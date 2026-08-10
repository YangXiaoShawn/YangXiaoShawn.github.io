from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from casuallab.config import DesignConfig, EstimatorConfig, SimulationConfig
from casuallab.estimators import (
    estimate_effect,
    estimate_heterogeneous_effects,
    estimate_ladder,
)
from casuallab.simulator import simulate_market


def _randomized_sample(seed: int = 4, n_obs: int = 400) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    covariate = rng.normal(size=n_obs)
    treatment = np.repeat([0.0, 1.0], n_obs // 2)
    noise = rng.normal(scale=0.25, size=n_obs)
    outcome = 2.0 * treatment + 1.5 * covariate + noise
    return pd.DataFrame(
        {
            "outcome": outcome,
            "assigned_treatment": treatment,
            "covariate": covariate,
            "cluster": np.repeat(np.arange(n_obs // 10), 10),
        }
    )


def test_difference_in_means_returns_common_uncertainty_contract() -> None:
    result = estimate_effect(_randomized_sample(), "difference_in_means")

    assert abs(result.estimate - 2.0) < 0.25
    assert result.standard_error > 0
    assert result.std_error == result.se
    assert result.ci_low < result.estimate < result.ci_high
    assert result.target_estimand == "intent_to_treat"
    assert result.to_dict()["std_error"] == result.standard_error


def test_regression_and_cluster_adjustment_recover_constructed_effect() -> None:
    data = _randomized_sample()
    regression = estimate_effect(
        data,
        "regression_adjusted",
        covariates=("covariate",),
    )
    clustered = estimate_effect(
        data,
        "cluster_robust",
        covariates=("covariate",),
        cluster="cluster",
    )

    assert abs(regression.estimate - 2.0) < 0.08
    assert np.isclose(regression.estimate, clustered.estimate)
    assert clustered.diagnostics["n_clusters"] == 40
    assert clustered.diagnostics["variance_estimator"] == "CR1"


def test_difference_in_differences_recovers_known_panel_effect() -> None:
    rows: list[dict[str, float | int]] = []
    for unit in range(12):
        for period in range(8):
            treated_group = float(unit < 6)
            post = float(period >= 4)
            rows.append(
                {
                    "unit": unit,
                    "period": period,
                    "treated_group": treated_group,
                    "post": post,
                    "outcome": 0.3 * unit + 0.2 * period + 3.0 * treated_group * post,
                }
            )
    panel = pd.DataFrame(rows)
    config = EstimatorConfig(
        outcome="outcome",
        treatment="treated_group",
        unit="unit",
        time="period",
        post="post",
    )
    result = estimate_effect(panel, "did", config)

    assert np.isclose(result.estimate, 3.0, atol=1e-10)
    assert result.diagnostics["parallel_trends_required"] is True


def test_cross_fitted_doubly_robust_estimator_recovers_ate() -> None:
    data = _randomized_sample(n_obs=600)
    result = estimate_effect(
        data,
        "aipw",
        covariates=("covariate",),
        crossfit_folds=3,
        seed=9,
    )

    assert abs(result.estimate - 2.0) < 0.08
    assert result.diagnostics["estimating_equation"] == "AIPW"
    assert result.diagnostics["crossfit_folds"] == 3


def test_doubly_robust_nuisance_folds_keep_clusters_intact() -> None:
    data = _randomized_sample(n_obs=400)
    # Assignment is homogeneous in each ten-row cluster for this constructed sample.
    result = estimate_effect(
        data,
        "doubly_robust",
        covariates=("covariate",),
        cluster="cluster",
        crossfit_folds=4,
        seed=17,
    )

    assert result.diagnostics["crossfit_unit"] == "cluster"
    assert result.diagnostics["crossfit_groups"] == 40
    assert result.diagnostics["group_leakage_prevented"] is True
    assert result.diagnostics["reference_distribution"] == "cluster_t"
    assert result.diagnostics["degrees_freedom"] == 39


def test_synthetic_control_uses_preperiod_donor_fit() -> None:
    rows: list[dict[str, float | int | str]] = []
    for period in range(10):
        baseline = 10.0 + period
        rows.extend(
            [
                {
                    "unit": "treated",
                    "period": period,
                    "treatment": float(period >= 6),
                    "outcome": baseline + (4.0 if period >= 6 else 0.0),
                },
                {
                    "unit": "donor_exact",
                    "period": period,
                    "treatment": 0.0,
                    "outcome": baseline,
                },
                {
                    "unit": "donor_other",
                    "period": period,
                    "treatment": 0.0,
                    "outcome": 0.5 * baseline + 3.0,
                },
            ]
        )
    panel = pd.DataFrame(rows)
    result = estimate_effect(
        panel,
        "synthetic_control_style",
        outcome="outcome",
        treatment="treatment",
        unit="unit",
        time="period",
    )

    assert np.isclose(result.estimate, 4.0, atol=1e-5)
    assert result.diagnostics["pre_rmspe"] < 1e-5
    assert np.isclose(sum(result.diagnostics["donor_weights"].values()), 1.0)
    assert "uncertainty_warning" in result.diagnostics


def test_continuous_saturation_is_regressed_not_dichotomized() -> None:
    saturation = np.linspace(0.1, 0.9, 80)
    data = pd.DataFrame(
        {
            "outcome": 5.0 + 3.0 * saturation,
            "assigned_treatment": saturation,
        }
    )
    with pytest.raises(ValueError, match="exactly two"):
        estimate_effect(data, "difference_in_means")
    result = estimate_effect(data, "regression_adjustment")
    assert np.isclose(result.estimate, 3.0)


def test_ladder_records_inapplicable_methods() -> None:
    data = _randomized_sample()
    ladder = estimate_ladder(
        data,
        methods=("difference_in_means", "cluster_robust"),
    )

    assert ladder.loc[ladder["method"] == "difference_in_means", "status"].iat[0] == "ok"
    failed = ladder.loc[ladder["method"] == "cluster_robust"].iloc[0]
    assert failed["status"] == "not_applicable"
    assert "requires config.cluster" in failed["diagnostics"]["error"]


def test_two_way_cluster_robust_uses_geographic_and_time_groups() -> None:
    rng = np.random.default_rng(401)
    rows: list[dict[str, float | int]] = []
    zone_shocks = rng.normal(0.0, 1.0, 16)
    time_shocks = rng.normal(0.0, 1.0, 18)
    for period in range(18):
        for zone in range(16):
            treatment = float(rng.binomial(1, 0.5))
            rows.append(
                {
                    "zone_id": zone,
                    "time_block": period,
                    "assigned_treatment": treatment,
                    "baseline": float(np.cos(zone)),
                    "outcome": (
                        3.0
                        + 2.25 * treatment
                        + zone_shocks[zone]
                        + time_shocks[period]
                        + 0.3 * np.cos(zone)
                        + rng.normal(0.0, 0.2)
                    ),
                }
            )
    result = estimate_effect(
        pd.DataFrame(rows),
        "two_way_cluster",
        cluster="zone_id",
        time="time_block",
        covariates=("baseline",),
        target_estimand="market_total_effect",
    )

    assert result.estimate == pytest.approx(2.25, abs=0.3)
    assert result.standard_error > 0
    assert result.diagnostics["n_geographic_clusters"] == 16
    assert result.diagnostics["n_time_clusters"] == 18
    assert result.diagnostics["degrees_freedom"] == 15
    assert result.diagnostics["inference_warning"] is None


def test_two_way_cluster_robust_requires_both_group_dimensions() -> None:
    with pytest.raises(ValueError, match="config.cluster and config.time"):
        estimate_effect(
            _randomized_sample(),
            "two_way_cluster_robust",
            cluster="cluster",
        )


def test_simple_hte_benchmark_is_deterministic() -> None:
    data = _randomized_sample(n_obs=300)
    first = estimate_heterogeneous_effects(data, ("covariate",), seed=21)
    second = estimate_heterogeneous_effects(data, ("covariate",), seed=21)

    pd.testing.assert_frame_equal(first, second)
    assert set(first["method"]) == {"cross_fitted_linear_t_learner"}
    assert np.isfinite(first["estimated_treatment_effect"]).all()


def test_no_interference_design_recovers_simulator_truth_within_mc_uncertainty() -> None:
    errors: list[float] = []
    for replication in range(24):
        simulation = simulate_market(
            SimulationConfig(
                n_zones=20,
                n_periods=12,
                seed=500 + replication,
                design=DesignConfig(name="geo_cluster", cluster_size=1),
                spillover_strength=0.0,
                rider_substitution=0.0,
                driver_mobility=0.0,
                persistence=0.0,
                budget=None,
            )
        )
        estimate = estimate_effect(
            simulation.panel,
            "difference_in_means",
            target_estimand="market_total_effect",
        )
        errors.append(
            estimate.estimate - simulation.ground_truth["market_total_effect"]
        )

    error_array = np.asarray(errors)
    monte_carlo_se = float(error_array.std(ddof=1) / np.sqrt(len(error_array)))
    assert abs(float(error_array.mean())) <= 2.5 * monte_carlo_se


def test_individual_saturation_slope_targets_direct_not_total_effect_with_spillovers() -> None:
    direct_errors: list[float] = []
    total_errors: list[float] = []
    for replication in range(20):
        simulation = simulate_market(
            SimulationConfig(
                n_zones=10,
                n_periods=16,
                individuals_per_cell=60,
                seed=800 + replication,
                design=DesignConfig(name="individual", treatment_probability=0.5),
                spillover_strength=0.30,
                rider_substitution=0.15,
                driver_mobility=0.15,
                persistence=0.0,
                budget=None,
            )
        )
        naive_saturation_slope = estimate_effect(
            simulation.panel,
            "regression_adjustment",
            covariates=(
                "baseline_demand",
                "baseline_supply",
                "hour_sin",
                "hour_cos",
            ),
            target_estimand="controlled_zone_direct_effect",
        ).estimate
        direct_errors.append(
            naive_saturation_slope
            - simulation.ground_truth["controlled_zone_direct_effect"]
        )
        total_errors.append(
            naive_saturation_slope - simulation.ground_truth["market_total_effect"]
        )

    direct_error = np.asarray(direct_errors)
    total_error = np.asarray(total_errors)
    direct_mcse = float(direct_error.std(ddof=1) / np.sqrt(len(direct_error)))
    total_mcse = float(total_error.std(ddof=1) / np.sqrt(len(total_error)))
    assert abs(float(direct_error.mean())) <= 2.5 * direct_mcse
    assert float(total_error.mean()) < 0
    assert abs(float(total_error.mean())) > 4.0 * total_mcse
