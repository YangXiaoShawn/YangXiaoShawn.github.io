from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from casuallab.config import DesignConfig, SimulationConfig, TreatmentVersion
from casuallab.marketplace_policy import (
    MarketplacePolicyConfig,
    _pretreatment_planning_cost,
    _random_full_budget_plan,
    _ranked_full_budget_plan,
    run_marketplace_policy_benchmark,
    run_marketplace_policy_evaluation,
    run_treatment_version_policy_evaluation,
)
from casuallab.simulator import simulate_market


def _simulation(**overrides: object) -> SimulationConfig:
    values: dict[str, object] = {
        "n_zones": 4,
        "n_periods": 16,
        "spillover_strength": 0.15,
        "persistence": 0.20,
        "seed": 31,
        "design": DesignConfig(name="geo_cluster", n_clusters=4, seed=32),
    }
    values.update(overrides)
    return SimulationConfig(**values)


def _policy() -> MarketplacePolicyConfig:
    return MarketplacePolicyConfig(
        budget=500.0,
        model_trees=12,
        model_replicates=2,
        seed=71,
    )


def test_marketplace_policy_is_deterministic_budget_feasible_and_honest() -> None:
    first = run_marketplace_policy_benchmark(
        _simulation(),
        _policy(),
        n_train_markets=3,
        n_holdout_markets=2,
    )
    second = run_marketplace_policy_benchmark(
        _simulation(),
        _policy(),
        n_train_markets=3,
        n_holdout_markets=2,
    )
    pd.testing.assert_frame_equal(first, second)
    assert set(first["policy"]) == {
        "no_treatment",
        "random",
        "uniform",
        "rule_based",
        "model_based",
    }
    assert first["budget_feasible"].all()
    assert first["evaluation_complete"].all()
    assert first["policy_eligible"].all()
    assert (
        first.loc[first["policy"] != "no_treatment", "budget_spent"]
        <= _policy().budget + 1e-6
    ).all()
    assert first.loc[first["policy"] == "no_treatment", "budget_spent"].item() == 0.0
    assert pd.isna(
        first.loc[first["policy"] == "no_treatment", "budget_efficiency"].item()
    )
    assert first["training_signal"].str.contains("no structural truth").all()
    assert first["planning_cost_basis"].str.contains("no treated holdout").all()
    train_seeds = set(json.loads(first.iloc[0]["training_market_seeds"]))
    holdout_seeds = set(json.loads(first.iloc[0]["holdout_market_seeds"]))
    assert train_seeds.isdisjoint(holdout_seeds)
    assert first["evaluation_engine"].str.contains("simulator rerun").all()
    assert set(first["target_estimand"]) == {"full_horizon_incremental_trips"}
    indexed = first.set_index("policy")
    assert indexed.loc["uniform", "treated_cell_share"] == pytest.approx(1.0)
    assert (
        indexed.loc[
            ["random", "rule_based", "model_based"],
            "treated_cell_share",
        ]
        < 1.0
    ).all()
    assert first["expected_incremental_outcome"].nunique() == len(first)

    detailed = run_marketplace_policy_evaluation(
        _simulation(),
        _policy(),
        n_train_markets=3,
        n_holdout_markets=2,
    )
    assert len(detailed.market_results) == 5 * 2
    assert detailed.market_results.groupby("holdout_market_seed")["policy"].nunique().eq(5).all()
    assert (
        detailed.market_results.groupby("holdout_market_seed")["incremental_trips"]
        .nunique()
        .eq(5)
        .all()
    )
    assert "paired_incremental_outcome_vs_random" in detailed.market_results


def test_policy_values_are_recomputed_when_market_interference_changes() -> None:
    no_interference = run_marketplace_policy_benchmark(
        _simulation(
            spillover_strength=0.0,
            persistence=0.0,
            rider_substitution=0.0,
            driver_mobility=0.0,
        ),
        _policy(),
        n_train_markets=3,
        n_holdout_markets=2,
    )
    interference = run_marketplace_policy_benchmark(
        _simulation(spillover_strength=0.4, persistence=0.5),
        _policy(),
        n_train_markets=3,
        n_holdout_markets=2,
    )
    merged = no_interference.merge(interference, on="policy", suffixes=("_none", "_active"))
    nonzero = merged["policy"] != "no_treatment"
    assert (
        merged.loc[nonzero, "expected_incremental_outcome_none"]
        != merged.loc[nonzero, "expected_incremental_outcome_active"]
    ).any()


def test_policy_config_rejects_unknown_or_invalid_values() -> None:
    with pytest.raises(ValueError, match="unknown marketplace policy keys"):
        MarketplacePolicyConfig.from_mapping({"budegt": 100.0})
    with pytest.raises(ValueError, match="budget must be positive"):
        MarketplacePolicyConfig(budget=0.0)


def test_planning_cost_respects_selected_treatment_version() -> None:
    rider_config = _simulation(treatment_version=TreatmentVersion.RIDER_DISCOUNT)
    driver_config = _simulation(treatment_version=TreatmentVersion.DRIVER_INCENTIVE)
    bundled_config = _simulation(treatment_version=TreatmentVersion.BUNDLED)
    rider_control = simulate_market(rider_config)
    driver_control = simulate_market(driver_config)
    bundled_control = simulate_market(bundled_config)

    rider_cost = _pretreatment_planning_cost(rider_control, rider_config)
    driver_cost = _pretreatment_planning_cost(driver_control, driver_config)
    bundled_cost = _pretreatment_planning_cost(bundled_control, bundled_config)
    assert (rider_cost > 0).all()
    assert (driver_cost > 0).all()
    assert (bundled_cost > 0).all()
    assert bundled_cost == pytest.approx(rider_cost + driver_cost)


def test_ranked_policy_never_spends_on_nonpositive_scores() -> None:
    allocation = _ranked_full_budget_plan(
        np.array([3.0, 0.0, -2.0]),
        np.ones(3),
        budget=100.0,
    )
    assert allocation.tolist() == [1.0, 0.0, 0.0]


def test_random_policy_uses_a_cost_independent_random_order() -> None:
    planning_cost = np.array([4.0, 1.0, 3.0, 2.0])
    budget = 4.0
    seed = 13
    order = np.random.default_rng(seed).permutation(len(planning_cost))
    expected = np.zeros(len(planning_cost))
    cumulative = 0.0
    for index in order:
        expected[index] = 1.0
        cumulative += planning_cost[index]
        if cumulative >= 1.10 * budget:
            break

    actual = _random_full_budget_plan(planning_cost, budget, random_seed=seed)
    assert actual.tolist() == expected.tolist()


def test_policy_evaluation_pairs_markets_across_treatment_versions() -> None:
    result = run_treatment_version_policy_evaluation(
        _simulation(n_periods=8),
        _policy(),
        n_train_markets=2,
        n_holdout_markets=2,
    )
    assert set(result.summary["treatment_version"]) == {
        "rider_discount",
        "driver_incentive",
        "bundled",
    }
    assert len(result.summary) == 3 * 5
    assert len(result.market_results) == 3 * 5 * 2
    assert result.summary.groupby("treatment_version")["policy"].nunique().eq(5).all()
    assert result.summary["training_market_seeds"].nunique() == 1
    assert result.summary["holdout_market_seeds"].nunique() == 1
    assert result.summary["version_evidence_scope"].str.contains("not an empirical").all()
    nonzero = result.summary.loc[result.summary["policy"] != "no_treatment"]
    assert nonzero.groupby("policy")["expected_incremental_outcome"].nunique().gt(1).any()

    with pytest.raises(ValueError, match="must be unique"):
        run_treatment_version_policy_evaluation(
            _simulation(n_periods=8),
            _policy(),
            treatment_versions=("bundled", "bundled"),
            n_train_markets=2,
            n_holdout_markets=2,
        )
