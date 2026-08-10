"""Budget-constrained policy learning evaluated on unseen semi-synthetic markets.

The policy learner never uses holdout treatment effects for fitting or ranking.  The
known holdout effects are used only to score policies after allocations are frozen.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor

DEFAULT_FEATURES = (
    "baseline_demand",
    "market_tightness",
    "hour_sin",
    "hour_cos",
    "adverse_weather",
    "neighborhood_income_index",
    "event_intensity",
)


@dataclass(frozen=True)
class PolicyConfig:
    """Configuration for honest policy learning and evaluation."""

    budget: float = 2_000.0
    incentive_cost: float = 10.0
    instability_penalty: float = 0.25
    model_trees: int = 120
    model_replicates: int = 4
    seed: int = 202503

    def __post_init__(self) -> None:
        if self.budget < 0:
            raise ValueError("budget must be non-negative")
        if self.incentive_cost <= 0:
            raise ValueError("incentive_cost must be positive")
        if self.instability_penalty < 0:
            raise ValueError("instability_penalty must be non-negative")
        if self.model_trees < 10:
            raise ValueError("model_trees must be at least 10")
        if self.model_replicates < 2:
            raise ValueError("model_replicates must be at least 2")


def generate_policy_learning_sample(
    n_rows: int,
    *,
    seed: int,
    incentive_cost: float = 10.0,
) -> pd.DataFrame:
    """Generate a compact policy-learning sample with known unit-level effects.

    This is a semi-synthetic decision surface, not a real-data treatment-effect
    estimate. ``effect_signal`` mimics a noisy cross-fitted treatment-effect signal
    available to the learner. ``true_incremental_outcome`` is hidden from fitting and
    exposed only so an independent holdout can be scored against known truth.
    """

    if n_rows <= 0:
        raise ValueError("n_rows must be positive")
    if incentive_cost <= 0:
        raise ValueError("incentive_cost must be positive")

    rng = np.random.default_rng(seed)
    hour = rng.integers(0, 24, size=n_rows)
    baseline_demand = rng.lognormal(mean=3.0, sigma=0.45, size=n_rows)
    market_tightness = rng.beta(2.4, 2.0, size=n_rows)
    adverse_weather = rng.binomial(1, 0.18, size=n_rows)
    income_index = np.clip(rng.normal(0.0, 1.0, size=n_rows), -2.5, 2.5)
    event_intensity = np.where(rng.random(n_rows) < 0.12, rng.gamma(2.0, 0.7, n_rows), 0.0)

    # Known causal response surface. It intentionally contains interaction and
    # saturation so a learned policy has something real to discover in simulation.
    rush = ((hour >= 7) & (hour <= 9)) | ((hour >= 16) & (hour <= 19))
    true_increment = (
        0.18
        + 0.025 * np.sqrt(baseline_demand)
        + 0.55 * market_tightness
        + 0.20 * rush.astype(float)
        + 0.16 * adverse_weather * market_tightness
        + 0.10 * event_intensity
        - 0.04 * np.maximum(income_index, 0.0)
        - 0.16 * np.square(market_tightness - 0.72)
    )
    true_increment = np.clip(true_increment, 0.02, None)
    effect_signal = true_increment + rng.normal(0.0, 0.28, size=n_rows)

    return pd.DataFrame(
        {
            "market_unit_id": np.arange(n_rows, dtype=int),
            "baseline_demand": baseline_demand,
            "market_tightness": market_tightness,
            "hour_sin": np.sin(2.0 * np.pi * hour / 24.0),
            "hour_cos": np.cos(2.0 * np.pi * hour / 24.0),
            "adverse_weather": adverse_weather.astype(float),
            "neighborhood_income_index": income_index,
            "event_intensity": event_intensity,
            "effect_signal": effect_signal,
            "true_incremental_outcome": true_increment,
            "treatment_cost": np.full(n_rows, float(incentive_cost)),
            "evidence_type": "semi_synthetic",
            "generation_seed": seed,
        }
    )


def _validate_policy_frame(frame: pd.DataFrame, features: Sequence[str], *, training: bool) -> None:
    required = set(features) | {"treatment_cost", "true_incremental_outcome"}
    if training:
        required.add("effect_signal")
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"policy frame missing columns: {sorted(missing)}")
    if frame.empty:
        raise ValueError("policy frame must not be empty")
    if (frame["treatment_cost"] <= 0).any():
        raise ValueError("all treatment costs must be positive")
    if not np.isfinite(frame[list(required)].to_numpy(dtype=float)).all():
        raise ValueError("policy inputs must be finite")


def _fit_stability_adjusted_scores(
    train: pd.DataFrame,
    holdout: pd.DataFrame,
    *,
    features: Sequence[str],
    config: PolicyConfig,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    predictions: list[np.ndarray] = []
    for replicate in range(config.model_replicates):
        model = RandomForestRegressor(
            n_estimators=config.model_trees,
            min_samples_leaf=max(5, len(train) // 100),
            max_depth=6,
            max_features="sqrt",
            bootstrap=True,
            random_state=config.seed + replicate,
            n_jobs=1,
        )
        model.fit(train[list(features)], train["effect_signal"])
        predictions.append(model.predict(holdout[list(features)]))
    prediction_matrix = np.vstack(predictions)
    mean_effect = prediction_matrix.mean(axis=0)
    instability = prediction_matrix.std(axis=0, ddof=1)
    conservative_effect = mean_effect - config.instability_penalty * instability
    return conservative_effect, mean_effect, instability


def allocate_ranked(
    score: Iterable[float],
    cost: Iterable[float],
    budget: float,
) -> np.ndarray:
    """Greedily allocate binary treatment by value per dollar.

    Deterministic index-based tie breaking makes repeated runs byte-for-byte stable.
    Non-positive scores are not funded; an explicit uniform baseline is responsible
    for representing diffuse allocations.
    """

    score_array = np.asarray(list(score), dtype=float)
    cost_array = np.asarray(list(cost), dtype=float)
    if score_array.shape != cost_array.shape:
        raise ValueError("score and cost must have the same shape")
    if budget < 0:
        raise ValueError("budget must be non-negative")
    if (cost_array <= 0).any() or not np.isfinite(cost_array).all():
        raise ValueError("cost must be finite and positive")
    if not np.isfinite(score_array).all():
        raise ValueError("score must be finite")

    ratios = score_array / cost_array
    order = np.lexsort((np.arange(len(ratios)), -ratios))
    allocation = np.zeros(len(ratios), dtype=float)
    remaining = float(budget)
    for index in order:
        if score_array[index] <= 0 or cost_array[index] > remaining + 1e-12:
            continue
        allocation[index] = 1.0
        remaining -= cost_array[index]
    return allocation


def _score_allocation(
    policy_name: str,
    allocation: np.ndarray,
    holdout: pd.DataFrame,
    *,
    budget: float,
    instability: np.ndarray | None = None,
) -> dict[str, float | str | int]:
    cost = holdout["treatment_cost"].to_numpy(dtype=float)
    effect = holdout["true_incremental_outcome"].to_numpy(dtype=float)
    spent = float(np.dot(allocation, cost))
    incremental = float(np.dot(allocation, effect))
    if spent > budget + 1e-8:
        raise AssertionError(f"{policy_name} allocation exceeds budget")
    mean_instability = (
        float(np.average(instability, weights=allocation))
        if instability is not None and allocation.sum() > 0
        else 0.0
    )
    return {
        "policy": policy_name,
        "expected_incremental_outcome": incremental,
        "budget_spent": spent,
        "budget": float(budget),
        "budget_efficiency": incremental / spent if spent > 0 else 0.0,
        "selected_equivalent_units": float(allocation.sum()),
        "selected_share": float(allocation.mean()),
        "mean_model_instability": mean_instability,
        "holdout_rows": int(len(holdout)),
        "evidence_type": "semi_synthetic_causal_holdout",
    }


def evaluate_budget_policies(
    train: pd.DataFrame,
    holdout: pd.DataFrame,
    config: PolicyConfig,
    *,
    features: Sequence[str] = DEFAULT_FEATURES,
) -> pd.DataFrame:
    """Compare no/random/uniform/rule/model policies on an honest holdout.

    ``train`` and ``holdout`` must be generated from independent draws. The function
    rejects overlapping ``generation_seed`` values when that provenance is present.
    """

    _validate_policy_frame(train, features, training=True)
    _validate_policy_frame(holdout, features, training=False)
    if "generation_seed" in train and "generation_seed" in holdout:
        train_seeds = set(train["generation_seed"].unique())
        holdout_seeds = set(holdout["generation_seed"].unique())
        if train_seeds.intersection(holdout_seeds):
            raise ValueError("training and holdout generation seeds must be disjoint")

    costs = holdout["treatment_cost"].to_numpy(dtype=float)
    n_rows = len(holdout)
    no_treatment = np.zeros(n_rows, dtype=float)

    random_rng = np.random.default_rng(config.seed + 50_000)
    random_score = random_rng.random(n_rows)
    random_allocation = allocate_ranked(random_score, costs, config.budget)

    total_cost = float(costs.sum())
    uniform_intensity = min(1.0, config.budget / total_cost) if total_cost else 0.0
    uniform_allocation = np.full(n_rows, uniform_intensity, dtype=float)

    rule_score = (
        holdout["baseline_demand"].to_numpy(dtype=float)
        * holdout["market_tightness"].to_numpy(dtype=float)
    )
    rule_allocation = allocate_ranked(rule_score, costs, config.budget)

    conservative, raw_prediction, instability = _fit_stability_adjusted_scores(
        train,
        holdout,
        features=features,
        config=config,
    )
    model_allocation = allocate_ranked(conservative, costs, config.budget)

    rows = [
        _score_allocation("no_treatment", no_treatment, holdout, budget=config.budget),
        _score_allocation("random", random_allocation, holdout, budget=config.budget),
        _score_allocation("uniform", uniform_allocation, holdout, budget=config.budget),
        _score_allocation("rule_based", rule_allocation, holdout, budget=config.budget),
        _score_allocation(
            "model_based",
            model_allocation,
            holdout,
            budget=config.budget,
            instability=instability,
        ),
    ]
    result = pd.DataFrame(rows)
    result["model_mean_predicted_effect"] = np.nan
    result.loc[result["policy"] == "model_based", "model_mean_predicted_effect"] = float(
        np.mean(raw_prediction[model_allocation > 0]) if model_allocation.sum() else 0.0
    )
    random_value = float(
        result.loc[result["policy"] == "random", "expected_incremental_outcome"].iloc[0]
    )
    result["incremental_outcome_vs_random"] = result["expected_incremental_outcome"] - random_value
    return result.sort_values("policy").reset_index(drop=True)


def run_policy_benchmark(
    config: PolicyConfig,
    *,
    n_train: int = 2_000,
    n_holdout: int = 1_000,
) -> pd.DataFrame:
    """Convenience wrapper using disjoint deterministic simulation seeds."""

    train = generate_policy_learning_sample(
        n_train,
        seed=config.seed,
        incentive_cost=config.incentive_cost,
    )
    holdout = generate_policy_learning_sample(
        n_holdout,
        seed=config.seed + 1,
        incentive_cost=config.incentive_cost,
    )
    return evaluate_budget_policies(train, holdout, config)

