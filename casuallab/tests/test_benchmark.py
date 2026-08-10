import numpy as np
import pandas as pd

from casuallab.benchmark import BenchmarkConfig, run_replications, summarize_monte_carlo


def test_summary_computes_bias_rmse_coverage_and_power() -> None:
    records = pd.DataFrame(
        {
            "design": ["cluster"] * 3,
            "estimator": ["dim"] * 3,
            "estimate": [1.0, 2.0, 3.0],
            "std_error": [1.0, 1.0, 1.0],
            "truth": [2.0, 2.0, 2.0],
            "target_estimand": ["total"] * 3,
            "design_cost": [2.0] * 3,
        }
    )
    summary = summarize_monte_carlo(records)
    assert summary.loc[0, "bias"] == 0.0
    assert np.isclose(summary.loc[0, "rmse"], np.sqrt(2.0 / 3.0))
    assert summary.loc[0, "coverage"] == 1.0
    assert summary.loc[0, "replications"] == 3
    assert summary.loc[0, "evidence_type"] == "semi_synthetic_causal_monte_carlo"


def test_replication_runner_is_deterministic() -> None:
    config = BenchmarkConfig(
        replications=3,
        seed=9,
        designs=("individual",),
        estimators=("difference_in_means",),
    )

    def callback(design: str, estimator: str, seed: int) -> dict[str, float]:
        estimate = float(np.random.default_rng(seed).normal(1.0, 0.2))
        return {"estimate": estimate, "std_error": 0.2, "truth": 1.0}

    first_records, first_summary = run_replications(config, callback)
    second_records, second_summary = run_replications(config, callback)
    pd.testing.assert_frame_equal(first_records, second_records)
    pd.testing.assert_frame_equal(first_summary, second_summary)


def test_summary_uses_estimator_specific_intervals_and_p_values() -> None:
    records = pd.DataFrame(
        {
            "design": ["geo_cluster", "geo_cluster"],
            "estimator": ["cluster_robust", "cluster_robust"],
            "estimate": [1.0, 1.0],
            "std_error": [0.01, 0.01],
            "truth": [0.0, 0.0],
            "ci_low": [-1.0, -1.0],
            "ci_high": [2.0, 2.0],
            "p_value": [0.2, 0.2],
            "scenario": ["few_clusters", "few_clusters"],
            "design_cost": [5.0, 5.0],
        }
    )
    summary = summarize_monte_carlo(records)
    assert summary.loc[0, "coverage"] == 1.0
    assert summary.loc[0, "power"] == 0.0
    assert summary.loc[0, "coverage_mcse"] > 0.0
    assert summary.loc[0, "power_mcse"] > 0.0
    assert (
        summary.loc[0, "binomial_mcse_method"]
        == "jeffreys_posterior_standard_deviation"
    )
    assert summary.loc[0, "information_cost"] == 5.0


def test_replication_varying_diagnostics_do_not_fragment_groups() -> None:
    records = pd.DataFrame(
        {
            "design": ["switchback"] * 3,
            "estimator": ["difference_in_means"] * 3,
            "estimate": [0.9, 1.0, 1.1],
            "std_error": [0.1] * 3,
            "truth": [1.0] * 3,
            "full_policy_spend": [90.0, 100.0, 110.0],
        }
    )
    summary = summarize_monte_carlo(records)
    assert len(summary) == 1
    assert summary.loc[0, "replications"] == 3
