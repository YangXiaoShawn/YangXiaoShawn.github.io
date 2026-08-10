import numpy as np
import pandas as pd
import pytest

from casuallab.policy import (
    PolicyConfig,
    allocate_ranked,
    evaluate_budget_policies,
    generate_policy_learning_sample,
    run_policy_benchmark,
)


def test_allocate_ranked_obeys_budget_and_value_order() -> None:
    allocation = allocate_ranked([1.0, 4.0, 2.0], [2.0, 2.0, 2.0], budget=4.0)
    np.testing.assert_array_equal(allocation, [0.0, 1.0, 1.0])
    assert float(np.dot(allocation, [2.0, 2.0, 2.0])) <= 4.0


def test_policy_benchmark_is_deterministic_and_budget_feasible() -> None:
    config = PolicyConfig(budget=500.0, model_trees=20, model_replicates=2, seed=71)
    first = run_policy_benchmark(config, n_train=300, n_holdout=180)
    second = run_policy_benchmark(config, n_train=300, n_holdout=180)
    pd.testing.assert_frame_equal(first, second)
    assert set(first["policy"]) == {
        "no_treatment",
        "random",
        "uniform",
        "rule_based",
        "model_based",
    }
    assert (first["budget_spent"] <= first["budget"] + 1e-8).all()
    assert set(first["evidence_type"]) == {"semi_synthetic_causal_holdout"}


def test_policy_evaluation_rejects_training_holdout_seed_overlap() -> None:
    sample = generate_policy_learning_sample(50, seed=11)
    with pytest.raises(ValueError, match="disjoint"):
        evaluate_budget_policies(
            sample,
            sample.copy(),
            PolicyConfig(model_trees=10, model_replicates=2),
        )

