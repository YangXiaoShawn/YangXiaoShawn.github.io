from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

from casuallab.config import DesignConfig, SimulationConfig, TreatmentVersion
from casuallab.simulator import simulate_market


def _small_config(**overrides: object) -> SimulationConfig:
    base = SimulationConfig(
        n_zones=4,
        n_periods=16,
        individuals_per_cell=80,
        seed=123,
        design=DesignConfig(name="geo_cluster", cluster_size=1),
    )
    return replace(base, **overrides)


def test_same_seed_reproduces_panel_assignment_and_truth() -> None:
    config = _small_config()
    first = simulate_market(config)
    second = simulate_market(config)

    pd.testing.assert_frame_equal(first.panel, second.panel)
    pd.testing.assert_frame_equal(first.assignment, second.assignment)
    assert first.ground_truth.keys() == second.ground_truth.keys()
    for key in first.ground_truth:
        assert np.isclose(
            first.ground_truth[key],
            second.ground_truth[key],
            equal_nan=True,
        )
    assert first.metadata == second.metadata


def test_different_seed_changes_exogenous_market() -> None:
    first = simulate_market(_small_config(seed=12))
    second = simulate_market(_small_config(seed=13))

    assert not np.allclose(first.panel["baseline_demand"], second.panel["baseline_demand"])


def test_no_effect_configuration_has_zero_trip_ground_truth() -> None:
    config = _small_config(
        direct_demand_effect=0.0,
        direct_supply_effect=0.0,
        spillover_strength=0.0,
        rider_substitution=0.0,
        driver_mobility=0.0,
        persistence=0.0,
    )
    result = simulate_market(config)

    for key in (
        "controlled_zone_direct_effect",
        "market_total_effect",
        "spillover_effect",
        "short_run_effect",
        "persistent_effect",
        "cumulative_effect",
    ):
        assert np.isclose(result.ground_truth[key], 0.0, atol=1e-12)
    assert np.isnan(result.ground_truth["direct_effect"])


def test_substitution_and_driver_movement_reallocate_without_creating_mass() -> None:
    result = simulate_market(
        _small_config(
            direct_demand_effect=0.0,
            direct_supply_effect=0.0,
            spillover_strength=0.0,
            rider_substitution=0.30,
            driver_mobility=0.25,
            persistence=0.0,
        )
    )
    by_period = result.panel.groupby("period_id")

    np.testing.assert_allclose(
        by_period["latent_demand"].sum(),
        by_period["baseline_demand"].sum(),
    )
    np.testing.assert_allclose(
        by_period["available_drivers"].sum(),
        by_period["baseline_supply"].sum(),
    )
    assert result.panel["rider_reallocation_signal"].abs().sum() > 0
    assert result.panel["driver_reallocation_signal"].abs().sum() > 0


def test_canonical_truth_matches_structural_counterfactual_paths() -> None:
    config = _small_config(
        spillover_strength=0.08,
        rider_substitution=0.03,
        driver_mobility=0.04,
        persistence=0.45,
    )
    result = simulate_market(config)
    control = result.counterfactuals["control"]
    all_treated = result.counterfactuals["all_treated"]
    all_treated_short = result.counterfactuals["all_treated_short_run"]
    full_effect = all_treated["trips"].to_numpy() - control["trips"].to_numpy()
    short_effect = all_treated_short["trips"].to_numpy() - control["trips"].to_numpy()

    assert np.isclose(result.ground_truth["market_total_effect"], full_effect.mean())
    assert np.isclose(result.ground_truth["cumulative_effect"], full_effect.sum())
    assert np.isclose(result.ground_truth["short_run_effect"], short_effect.mean())
    assert np.isclose(
        result.ground_truth["persistent_effect"], (full_effect - short_effect).mean()
    )
    assert result.ground_truth["persistent_effect"] > 0
    assert "realized_schedule_mean_effect" in result.ground_truth
    assert result.metadata["ground_truth_definitions"]["market_total_effect"].startswith(
        "all-zone"
    )


def test_no_cross_zone_path_has_zero_controlled_spillover() -> None:
    result = simulate_market(
        _small_config(
            spillover_strength=0.0,
            rider_substitution=0.0,
            driver_mobility=0.0,
        )
    )

    assert np.isclose(result.ground_truth["spillover_effect"], 0.0, atol=1e-12)
    # With no cross-zone pathways or persistence, the focal own-only contrast and
    # the all-zone policy contrast are the same average cell effect.
    assert np.isclose(
        result.ground_truth["controlled_zone_direct_effect"],
        result.ground_truth["market_total_effect"],
    )
    assert result.metadata["itt_available"] is True
    assert np.isclose(
        result.ground_truth["intent_to_treat"],
        result.ground_truth["market_total_effect"],
    )


def test_itt_is_unavailable_when_assignment_contrast_is_not_full_policy_contrast() -> None:
    result = simulate_market(
        _small_config(
            spillover_strength=0.1,
            rider_substitution=0.02,
            driver_mobility=0.03,
            persistence=0.2,
        )
    )

    assert result.metadata["itt_available"] is False
    assert np.isnan(result.ground_truth["intent_to_treat"])
    assert np.isnan(result.ground_truth["treatment_on_treated"])
    assert result.metadata["ground_truth"]["intent_to_treat"] is None
    json.dumps(result.metadata, allow_nan=False)


def test_budget_is_binding_without_rewriting_random_assignment() -> None:
    unconstrained = simulate_market(_small_config(spillover_strength=0.12))
    constrained = simulate_market(
        _small_config(spillover_strength=0.12, budget=250.0)
    )

    pd.testing.assert_series_equal(
        unconstrained.assignment["assigned_treatment"],
        constrained.assignment["assigned_treatment"],
    )
    assert constrained.panel["treatment_cost"].sum() <= 250.0 + 1e-8
    assert constrained.metadata["budget_feasible"]
    assert constrained.metadata["budget_scale"] < 1.0
    assert np.isclose(
        constrained.ground_truth["controlled_zone_direct_effect"],
        unconstrained.ground_truth["controlled_zone_direct_effect"],
    )
    assert np.isclose(
        constrained.ground_truth["spillover_effect"],
        unconstrained.ground_truth["spillover_effect"],
    )
    assert constrained.metadata["treatment_version"] == "bundled"
    assert "factorial" in constrained.metadata["treatment_version_limitation"]
    assert (
        constrained.assignment["treatment"]
        <= constrained.assignment["planned_treatment"] + 1e-12
    ).all()


def test_treatment_versions_activate_only_the_declared_market_side() -> None:
    common = dict(
        direct_demand_effect=0.20,
        direct_supply_effect=0.20,
        spillover_strength=0.0,
        rider_substitution=0.0,
        driver_mobility=0.0,
        persistence=0.0,
    )
    rider = simulate_market(
        _small_config(treatment_version=TreatmentVersion.RIDER_DISCOUNT, **common)
    )
    driver = simulate_market(
        _small_config(treatment_version=TreatmentVersion.DRIVER_INCENTIVE, **common)
    )
    bundled = simulate_market(
        _small_config(treatment_version=TreatmentVersion.BUNDLED, **common)
    )

    rider_treated = rider.panel["treatment"] > 0
    driver_treated = driver.panel["treatment"] > 0
    assert np.allclose(
        rider.panel.loc[rider_treated, "available_drivers"],
        rider.panel.loc[rider_treated, "baseline_supply"],
    )
    assert np.allclose(
        driver.panel.loc[driver_treated, "latent_demand"],
        driver.panel.loc[driver_treated, "baseline_demand"],
    )
    assert np.isclose(rider.panel["driver_incentive_cost"].sum(), 0.0)
    assert np.isclose(driver.panel["rider_discount_cost"].sum(), 0.0)
    assert bundled.panel["rider_discount_cost"].sum() > 0
    assert bundled.panel["driver_incentive_cost"].sum() > 0
    assert rider.metadata["treatment_version"] == "rider_discount"
    assert driver.metadata["treatment_version"] == "driver_incentive"


def test_driver_incentive_dose_scales_supply_response_and_zero_has_no_effect() -> None:
    common = dict(
        treatment_version=TreatmentVersion.DRIVER_INCENTIVE,
        direct_demand_effect=0.0,
        direct_supply_effect=0.12,
        spillover_strength=0.0,
        rider_substitution=0.0,
        driver_mobility=0.0,
        persistence=0.0,
        reference_incentive_per_driver=1.5,
    )
    zero = simulate_market(_small_config(incentive_per_driver=0.0, **common))
    reference = simulate_market(_small_config(incentive_per_driver=1.5, **common))
    double = simulate_market(_small_config(incentive_per_driver=3.0, **common))

    assert np.isclose(zero.ground_truth["market_total_effect"], 0.0, atol=1e-12)
    assert reference.ground_truth["market_total_effect"] > 0
    assert double.ground_truth["market_total_effect"] > reference.ground_truth[
        "market_total_effect"
    ]
    assert zero.metadata["driver_incentive_response_scale"] == 0.0
    assert reference.metadata["driver_incentive_response_scale"] == 1.0
    assert double.metadata["driver_incentive_response_scale"] == 2.0


def test_individual_design_exposes_continuous_saturation_for_regression() -> None:
    config = _small_config(
        design=DesignConfig(name="individual", treatment_probability=0.5)
    )
    result = simulate_market(config)

    assert result.panel["assigned_treatment"].nunique() > 2
    assert result.panel["assigned_treatment"].between(0, 1).all()
    assert set(result.panel["evidence_type"]) == {"semi_synthetic_causal"}


def test_supplied_schedule_is_validated_and_used() -> None:
    config = _small_config(n_zones=2, n_periods=5)
    assignment = pd.MultiIndex.from_product(
        [range(5), range(2)], names=["period_id", "zone_id"]
    ).to_frame(index=False)
    assignment["assigned_treatment"] = (assignment["zone_id"] == 0).astype(float)
    result = simulate_market(config, assignments=assignment)

    assert np.array_equal(
        result.panel["assigned_treatment"], assignment["assigned_treatment"]
    )
    assert (result.panel.loc[result.panel["zone_id"] == 1, "treatment"] == 0).all()


def test_truth_uses_same_washout_population_as_estimators() -> None:
    config = _small_config(
        design=DesignConfig(
            name="switchback",
            treatment_duration=3,
            washout_periods=1,
        )
    )
    result = simulate_market(config)
    eligible = result.panel["analysis_eligible"].astype(bool).to_numpy()
    control = result.counterfactuals["control"]["trips"].to_numpy()
    policy = result.counterfactuals["all_treated"]["trips"].to_numpy()
    full_effect = policy - control

    assert eligible.sum() < len(eligible)
    assert np.isclose(
        result.ground_truth["market_total_effect"], full_effect.mean()
    )
    assert np.isclose(
        result.ground_truth["analysis_population_market_total_effect"],
        full_effect[eligible].mean(),
    )
    assert result.metadata["analysis_rows"] == int(eligible.sum())
    assert result.metadata["target_population_id"].startswith("all_4_zones")


def test_committed_simulation_config_is_runnable() -> None:
    config_path = Path(__file__).parents[1] / "configs" / "simulation.yaml"
    config = SimulationConfig.from_yaml(config_path, section="simulation")
    result = simulate_market(config)

    assert len(result.panel) == config.n_zones * config.n_periods
    assert result.panel["analysis_eligible"].eq(1).all()
