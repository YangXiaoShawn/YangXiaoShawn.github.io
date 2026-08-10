from pathlib import Path

import pandas as pd
import pytest

from casuallab.reporting import (
    _validate_policy_provenance,
    choose_recommendation,
    generate_decision_appendix,
)


def _safe_benchmark(values: dict[str, list[object]]) -> pd.DataFrame:
    frame = pd.DataFrame(values)
    rows = len(frame)
    defaults: dict[str, object] = {
        "identified": True,
        "inference_valid": True,
        "fit_complete": True,
        "applicable": True,
        "attempted_fits": 10,
        "successful_fits": 10,
        "confidence_level": 0.95,
    }
    for column, value in defaults.items():
        if column not in frame:
            frame[column] = [value] * rows
    return frame


def _safe_policy() -> pd.DataFrame:
    policies = ["no_treatment", "random", "uniform", "rule_based", "model_based"]
    rows = len(policies)
    return pd.DataFrame(
        {
            "policy": policies,
            "expected_incremental_outcome": [0.0, 3.0, 3.5, 4.0, 5.0],
            "incremental_outcome_se": [0.0, 0.3, 0.3, 0.35, 0.4],
            "incremental_outcome_p10": [0.0, 2.0, 2.4, 3.0, 4.0],
            "budget_spent": [0.0, 100.0, 100.0, 100.0, 100.0],
            "budget_efficiency": [float("nan"), 0.03, 0.035, 0.04, 0.05],
            "budget_feasible": [True] * rows,
            "evaluation_complete": [True] * rows,
            "policy_eligible": [True] * rows,
            "mean_model_instability": [0.0, 0.0, 0.0, 0.0, 0.1],
            "decision_instability": [0.0, 0.0, 0.0, 0.0, 0.1],
            "training_market_seeds": ["[1, 2]"] * rows,
            "holdout_market_seeds": ["[3, 4]"] * rows,
            "training_markets": [2] * rows,
            "holdout_markets": [2] * rows,
            "training_signal": ["randomized outcomes; no structural truth"] * rows,
            "evaluation_engine": ["full simulator rerun"] * rows,
            "planning_cost_basis": ["pre-treatment; no treated holdout"] * rows,
            "target_estimand": ["full_horizon_incremental_trips"] * rows,
            "target_population_id": ["two_markets"] * rows,
            "n_zones": [4] * rows,
            "n_periods": [12] * rows,
            "weighting": ["paired holdout means"] * rows,
            "simulation_config": ['{"n_zones":4}'] * rows,
            "policy_config": ['{"budget":100}'] * rows,
            "evidence_type": ["semi_synthetic_causal_holdout"] * rows,
        }
    )


def test_policy_provenance_rejects_missing_or_spliced_policy_rows() -> None:
    policy = _safe_policy()
    with pytest.raises(ValueError, match="exactly one row"):
        _validate_policy_provenance(policy.iloc[:-1])

    spliced = policy.copy()
    spliced.loc[spliced.index[-1], "holdout_market_seeds"] = "[3, 5]"
    with pytest.raises(ValueError, match="differs across rows"):
        _validate_policy_provenance(spliced)


def test_generated_report_uses_computed_results_and_labels_evidence(tmp_path: Path) -> None:
    benchmark_path = tmp_path / "benchmark.csv"
    policy_path = tmp_path / "policy.csv"
    output_path = tmp_path / "report.md"
    _safe_benchmark(
        {
            "design": ["individual", "geo_cluster"],
            "estimator": ["difference_in_means", "cluster_robust"],
            "target_estimand": ["market_total_effect", "market_total_effect"],
            "bias": [0.5, 0.1],
            "rmse": [0.05, 0.3],
            "coverage": [0.7, 0.94],
            "power": [0.9, 0.8],
            "mean_std_error": [0.2, 0.3],
            "information_cost": [2.0, 1.5],
            "confidence_level": [0.95, 0.95],
            "evidence_type": ["semi_synthetic_causal_monte_carlo"] * 2,
        }
    ).to_csv(benchmark_path, index=False)
    _safe_policy().to_csv(policy_path, index=False)

    generate_decision_appendix(
        benchmark_path,
        output_path=output_path,
        policy_path=policy_path,
        target_estimand="market_total_effect",
    )
    report = output_path.read_text(encoding="utf-8")
    assert "geo_cluster" in report
    assert "0.1000" in report
    assert "semi-synthetic causal benchmark" in report
    assert "Benchmark SHA-256" in report


def test_recommendation_uses_worst_case_not_easiest_scenario() -> None:
    benchmark = _safe_benchmark(
        {
            "design": ["geo_cluster", "geo_cluster", "switchback", "switchback"],
            "estimator": ["cluster_robust"] * 4,
            "target_estimand": ["market_total_effect"] * 4,
            "scenario": ["easy", "adverse", "easy", "adverse"],
            "rmse": [0.10, 1.20, 0.40, 0.50],
            "coverage": [0.95] * 4,
            "power": [0.8] * 4,
            "bias": [0.0] * 4,
        }
    )
    selected = choose_recommendation(benchmark, "market_total_effect")
    assert selected["design"] == "switchback"
    assert selected["scenario"] == "adverse"


def test_recommendation_requires_identification_across_every_declared_scenario() -> None:
    benchmark = _safe_benchmark(
        {
            "design": ["geo_cluster", "geo_cluster", "switchback", "switchback"],
            "estimator": ["cluster_robust"] * 4,
            "target_estimand": ["market_total_effect"] * 4,
            "scenario": ["none", "spillover", "none", "spillover"],
            "identified": [True, False, True, True],
            "inference_valid": [True] * 4,
            "rmse": [0.05, float("nan"), 0.30, 0.35],
            "coverage": [0.95, float("nan"), 0.94, 0.93],
            "power": [0.9, float("nan"), 0.8, 0.8],
            "bias": [0.0, float("nan"), 0.1, 0.1],
        }
    )
    selected = choose_recommendation(benchmark, "market_total_effect")

    assert selected["design"] == "switchback"
    assert selected["declared_scenarios"] == 2


def test_recommendation_refuses_partial_scenario_identification() -> None:
    benchmark = _safe_benchmark(
        {
            "design": ["geo_cluster", "geo_cluster"],
            "estimator": ["cluster_robust"] * 2,
            "target_estimand": ["market_total_effect"] * 2,
            "scenario": ["none", "spillover"],
            "identified": [True, False],
            "inference_valid": [True, True],
            "rmse": [0.1, float("nan")],
            "coverage": [0.95, float("nan")],
            "power": [0.8, float("nan")],
            "bias": [0.0, float("nan")],
        }
    )
    with pytest.raises(ValueError, match="full declared scenario set"):
        choose_recommendation(benchmark, "market_total_effect")


def test_recommendation_conditional_mode_keeps_declaration_but_allows_exact_subset() -> None:
    benchmark = _safe_benchmark(
        {
            "design": ["geo_cluster", "geo_cluster", "switchback", "switchback"],
            "estimator": ["cluster_robust"] * 4,
            "target_estimand": ["market_total_effect"] * 4,
            "scenario": ["none", "spillover", "none", "spillover"],
            "declared_scenario_set": ['["none","spillover"]'] * 4,
            "declared_scenario_count": [2] * 4,
            "rmse": [0.10, 0.50, 0.20, 0.30],
            "coverage": [0.95] * 4,
            "power": [0.8] * 4,
            "bias": [0.0] * 4,
        }
    )
    exact_none = benchmark.loc[benchmark["scenario"] == "none"]

    with pytest.raises(ValueError, match="do not cover the declared scenario set"):
        choose_recommendation(exact_none, "market_total_effect")
    selected = choose_recommendation(
        exact_none,
        "market_total_effect",
        require_declared_scenarios=False,
    )

    assert selected["design"] == "geo_cluster"
    assert selected["recommendation_scope"] == "selected_scenario_conditional"
    assert selected["declared_scenarios"] == 2
    assert selected["evaluated_scenarios"] == 1
    assert selected["unmatched_declared_scenarios"] == '["spillover"]'

    malformed = exact_none.copy()
    malformed["declared_scenario_count"] = 1
    with pytest.raises(ValueError, match="scenario count is inconsistent"):
        choose_recommendation(
            malformed,
            "market_total_effect",
            require_declared_scenarios=False,
        )


def test_recommendation_excludes_incomplete_fit_ledger_candidates() -> None:
    benchmark = _safe_benchmark(
        {
            "design": ["geo_cluster", "geo_cluster", "switchback", "switchback"],
            "estimator": ["cluster_robust"] * 4,
            "target_estimand": ["market_total_effect"] * 4,
            "scenario": ["none", "adverse", "none", "adverse"],
            "identified": [True] * 4,
            "inference_valid": [True] * 4,
            "fit_complete": [True, False, True, True],
            "attempted_fits": [10] * 4,
            "successful_fits": [10, 9, 10, 10],
            "rmse": [0.05, 0.06, 0.30, 0.35],
            "coverage": [0.95] * 4,
            "power": [0.8] * 4,
            "bias": [0.0] * 4,
        }
    )

    selected = choose_recommendation(benchmark, "market_total_effect")

    assert selected["design"] == "switchback"
    assert "complete identified fits" in selected["selection_rule"]


def test_recommendation_rejects_catastrophic_undercoverage() -> None:
    benchmark = _safe_benchmark(
        {
            "design": ["geo_cluster", "switchback"],
            "estimator": ["cluster_robust", "cluster_robust"],
            "target_estimand": ["market_total_effect"] * 2,
            "scenario": ["default", "default"],
            "rmse": [0.01, 1.0],
            "coverage": [0.0, 0.95],
            "coverage_mcse": [0.0, 0.02],
            "power": [1.0, 0.8],
            "bias": [0.0, 0.1],
        }
    )

    selected = choose_recommendation(benchmark, "market_total_effect")

    assert selected["design"] == "switchback"


def test_recommendation_requires_explicit_safety_ledger() -> None:
    unsafe = pd.DataFrame(
        {
            "design": ["geo_cluster"],
            "estimator": ["cluster_robust"],
            "target_estimand": ["market_total_effect"],
            "rmse": [0.1],
            "coverage": [0.95],
            "power": [0.8],
            "bias": [0.0],
        }
    )
    with pytest.raises(ValueError, match="benchmark results missing columns"):
        choose_recommendation(unsafe, "market_total_effect")
