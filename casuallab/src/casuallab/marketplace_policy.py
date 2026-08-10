"""Honest-holdout policy learning evaluated through the marketplace simulator.

The learner sees randomized assignments, pre-treatment features, and observed
outcomes from training markets. Structural effect columns are never passed to a
model. After scores are frozen, every baseline allocation is evaluated by running
the complete simulator again on disjoint market seeds, so congestion, spatial
spillovers, persistence, matching, and the shared budget are recomputed jointly.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, fields, replace

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor

from casuallab.config import (
    DesignConfig,
    DesignName,
    SimulationConfig,
    TreatmentVersion,
)
from casuallab.simulator import SimulationResult, simulate_market

POLICY_FEATURES = (
    "baseline_demand",
    "baseline_supply",
    "market_tightness",
    "hour_sin",
    "hour_cos",
    "zone_demand_factor",
    "zone_supply_factor",
)
POLICY_NAMES = (
    "no_treatment",
    "random",
    "uniform",
    "rule_based",
    "model_based",
)


@dataclass(frozen=True, slots=True)
class MarketplacePolicyConfig:
    """Configuration for a fixed-budget honest-holdout policy comparison."""

    budget: float = 2_000.0
    instability_penalty: float = 0.25
    model_trees: int = 120
    model_replicates: int = 4
    seed: int = 202503
    training_treatment_probability: float = 0.5
    training_treatment_duration: int = 4

    def __post_init__(self) -> None:
        if self.budget <= 0:
            raise ValueError("budget must be positive")
        if self.instability_penalty < 0:
            raise ValueError("instability_penalty must be non-negative")
        if self.model_trees < 10:
            raise ValueError("model_trees must be at least 10")
        if self.model_replicates < 2:
            raise ValueError("model_replicates must be at least 2")
        if not 0 < self.training_treatment_probability < 1:
            raise ValueError("training_treatment_probability must lie in (0, 1)")
        if self.training_treatment_duration < 1:
            raise ValueError("training_treatment_duration must be positive")

    @classmethod
    def from_mapping(cls, values: Mapping[str, object]) -> MarketplacePolicyConfig:
        if not isinstance(values, Mapping):
            raise TypeError("policy configuration must be a mapping")
        allowed = {item.name for item in fields(cls)}
        unknown = set(values).difference(allowed)
        if unknown:
            raise ValueError(f"unknown marketplace policy keys: {sorted(unknown)}")
        return cls(**dict(values))


@dataclass(frozen=True)
class MarketplacePolicyResult:
    """Aggregate policy table plus the paired holdout-market evaluation ledger."""

    summary: pd.DataFrame
    market_results: pd.DataFrame


@dataclass(frozen=True)
class TreatmentVersionPolicyResult:
    """Policy summaries and paired ledgers across declared intervention versions."""

    summary: pd.DataFrame
    market_results: pd.DataFrame


def _seed_draws(seed: int, count: int) -> tuple[int, ...]:
    sequence = np.random.SeedSequence(seed)
    return tuple(
        int(child.generate_state(1, dtype=np.uint32)[0])
        for child in sequence.spawn(count)
    )


def _training_design(
    simulation: SimulationConfig,
    config: MarketplacePolicyConfig,
    seed: int,
) -> DesignConfig:
    n_clusters = min(4, simulation.n_zones)
    return DesignConfig(
        name=DesignName.GEO_TIME,
        treatment_probability=config.training_treatment_probability,
        treatment_saturation=1.0,
        n_clusters=n_clusters,
        cluster_size=max(1, int(np.ceil(simulation.n_zones / n_clusters))),
        treatment_duration=config.training_treatment_duration,
        washout_periods=0,
        budget=None,
        seed=seed + 1,
    )


def _randomized_training_frame(
    simulation: SimulationConfig,
    config: MarketplacePolicyConfig,
    seeds: Sequence[int],
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    allowed = {
        *POLICY_FEATURES,
        "outcome",
        "assigned_treatment",
        "treatment_probability",
    }
    for market_index, seed in enumerate(seeds):
        design = _training_design(simulation, config, seed)
        market_config = replace(simulation, seed=seed, budget=None, design=design)
        generated = simulate_market(market_config)
        frame = generated.panel[list(allowed)].copy()
        frame["training_market_index"] = market_index
        frame["training_market_seed"] = seed
        frames.append(frame)
    training = pd.concat(frames, ignore_index=True)
    treatment = training["assigned_treatment"].to_numpy(dtype=float)
    if not set(np.unique(treatment)).issubset({0.0, 1.0}) or np.ptp(treatment) == 0:
        raise ValueError("policy training requires randomized binary assignment variation")
    numeric = training[[*POLICY_FEATURES, "outcome"]].to_numpy(dtype=float)
    if not np.isfinite(numeric).all():
        raise ValueError("policy training features and outcomes must be finite")
    # Deliberately reject accidental leakage of structural validation columns.
    if any(column.startswith("true_") or column == "y0" for column in training):
        raise AssertionError("structural truth leaked into the policy training frame")
    return training


def _fit_t_learner_ensemble(
    training: pd.DataFrame,
    config: MarketplacePolicyConfig,
) -> tuple[tuple[RandomForestRegressor, RandomForestRegressor], ...]:
    models: list[tuple[RandomForestRegressor, RandomForestRegressor]] = []
    treated = training["assigned_treatment"] == 1
    for replicate in range(config.model_replicates):
        pair: list[RandomForestRegressor] = []
        for arm, mask in ((0, ~treated), (1, treated)):
            model = RandomForestRegressor(
                n_estimators=config.model_trees,
                min_samples_leaf=max(5, int(mask.sum()) // 100),
                max_depth=8,
                max_features="sqrt",
                bootstrap=True,
                random_state=config.seed + replicate * 2 + arm,
                n_jobs=1,
            )
            model.fit(training.loc[mask, list(POLICY_FEATURES)], training.loc[mask, "outcome"])
            pair.append(model)
        models.append((pair[0], pair[1]))
    return tuple(models)


def _zero_assignment(simulation: SimulationConfig) -> pd.DataFrame:
    grid = pd.MultiIndex.from_product(
        [range(simulation.n_periods), range(simulation.n_zones)],
        names=["period_id", "zone_id"],
    ).to_frame(index=False)
    grid["treatment"] = 0.0
    grid["assigned_treatment"] = 0.0
    return grid


def _assignment_from_intensity(
    base: pd.DataFrame,
    intensity: np.ndarray,
) -> pd.DataFrame:
    schedule = base[["zone_id", "period_id"]].copy()
    schedule["treatment"] = np.asarray(intensity, dtype=float)
    schedule["assigned_treatment"] = schedule["treatment"]
    return schedule


def _ranked_full_budget_plan(
    score: np.ndarray,
    planning_cost: np.ndarray,
    budget: float,
) -> np.ndarray:
    if score.shape != planning_cost.shape:
        raise ValueError("score and planning cost must align")
    if not np.isfinite(score).all() or not np.isfinite(planning_cost).all():
        raise ValueError("policy scores and planning costs must be finite")
    if (planning_cost <= 0).any():
        raise ValueError("policy planning costs must be positive")
    order = np.lexsort((np.arange(len(score)), -(score / planning_cost)))
    selected = np.zeros(len(score), dtype=float)
    cumulative = 0.0
    # Slightly over-plan so the simulator's nonlinear cost path can scale the
    # selected schedule to the same shared cap rather than systematically underspend.
    target = 1.10 * budget
    for index in order:
        # A targeting policy is allowed to leave budget unused when its estimated
        # incremental value is nonpositive.  Forcing those cells into the plan
        # would turn a maximum budget into a deployment quota.
        if score[index] <= 0.0:
            break
        selected[index] = 1.0
        cumulative += planning_cost[index]
        if cumulative >= target:
            break
    return selected


def _random_full_budget_plan(
    planning_cost: np.ndarray,
    budget: float,
    *,
    random_seed: int,
) -> np.ndarray:
    """Select cells in an independent random order up to the planning cap."""

    if not np.isfinite(planning_cost).all():
        raise ValueError("policy planning costs must be finite")
    if (planning_cost <= 0).any():
        raise ValueError("policy planning costs must be positive")
    selected = np.zeros(len(planning_cost), dtype=float)
    cumulative = 0.0
    target = 1.10 * budget
    order = np.random.default_rng(random_seed).permutation(len(planning_cost))
    for index in order:
        selected[index] = 1.0
        cumulative += planning_cost[index]
        if cumulative >= target:
            break
    return selected


def _ensemble_scores(
    models: Sequence[tuple[RandomForestRegressor, RandomForestRegressor]],
    features: pd.DataFrame,
    config: MarketplacePolicyConfig,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, float]:
    predictions = np.vstack(
        [
            treated.predict(features[list(POLICY_FEATURES)])
            - control.predict(features[list(POLICY_FEATURES)])
            for control, treated in models
        ]
    )
    mean = predictions.mean(axis=0)
    instability = predictions.std(axis=0, ddof=1)
    conservative = mean - config.instability_penalty * instability
    return conservative, mean, instability, float(np.mean(instability))


def _policy_allocations(
    control: SimulationResult,
    planning_cost: np.ndarray,
    models: Sequence[tuple[RandomForestRegressor, RandomForestRegressor]],
    config: MarketplacePolicyConfig,
    *,
    random_seed: int,
) -> tuple[dict[str, np.ndarray], dict[str, float]]:
    base = control.panel
    conservative, _, instability, mean_instability = _ensemble_scores(
        models,
        base,
        config,
    )
    rule_scores = (
        base["baseline_demand"].to_numpy(dtype=float)
        * base["market_tightness"].to_numpy(dtype=float)
    )
    allocations = {
        "no_treatment": np.zeros(len(base), dtype=float),
        "random": _random_full_budget_plan(
            planning_cost,
            config.budget,
            random_seed=random_seed,
        ),
        "uniform": np.ones(len(base), dtype=float),
        "rule_based": _ranked_full_budget_plan(rule_scores, planning_cost, config.budget),
        "model_based": _ranked_full_budget_plan(conservative, planning_cost, config.budget),
    }
    model_selected = allocations["model_based"] > 0
    selected_instability = (
        float(instability[model_selected].mean()) if model_selected.any() else mean_instability
    )

    replicate_allocations = np.vstack(
        [
            _ranked_full_budget_plan(
                treated.predict(base[list(POLICY_FEATURES)])
                - control_model.predict(base[list(POLICY_FEATURES)]),
                planning_cost,
                config.budget,
            )
            for control_model, treated in models
        ]
    )
    decision_instability = float(
        replicate_allocations.std(axis=0, ddof=1).mean()
    )
    diagnostics = {
        "mean_model_instability": selected_instability,
        "decision_instability": decision_instability,
    }
    return allocations, diagnostics


def _score_policy_market(
    policy: str,
    evaluated: SimulationResult,
    control: SimulationResult,
    *,
    budget: float,
    market_seed: int,
    diagnostics: Mapping[str, float],
) -> dict[str, object]:
    panel = evaluated.panel
    baseline = control.panel
    spend = float(panel["treatment_cost"].sum())
    incremental_trips = float(panel["trips"].sum() - baseline["trips"].sum())
    incremental_welfare = float(panel["welfare"].sum() - baseline["welfare"].sum())
    incremental_revenue = float(
        panel["platform_net_revenue"].sum()
        - baseline["platform_net_revenue"].sum()
    )
    return {
        "policy": policy,
        "holdout_market_seed": market_seed,
        "incremental_trips": incremental_trips,
        "incremental_welfare": incremental_welfare,
        "incremental_platform_net_revenue": incremental_revenue,
        "budget_spent": spend,
        "budget": budget,
        "budget_feasible": spend <= budget + 1e-6,
        "mean_treatment_intensity": float(panel["treatment"].mean()),
        "treated_cell_share": float((panel["planned_treatment"] > 0).mean()),
        "mean_wait_minutes_change": float(
            panel["wait_minutes"].mean() - baseline["wait_minutes"].mean()
        ),
        "mean_model_instability": (
            diagnostics["mean_model_instability"] if policy == "model_based" else 0.0
        ),
        "decision_instability": (
            diagnostics["decision_instability"] if policy == "model_based" else 0.0
        ),
        "target_estimand": "full_horizon_incremental_trips",
        "target_population_id": control.metadata["target_population_id"],
        "n_zones": control.metadata["n_zones"],
        "n_periods": control.metadata["n_periods"],
        "weighting": "total across every configured zone-period",
        "evidence_type": "semi_synthetic_policy_holdout_market",
    }


def _pretreatment_planning_cost(
    control: SimulationResult,
    simulation: SimulationConfig,
) -> np.ndarray:
    """Construct a positive cost proxy from pre-treatment state only."""

    panel = control.panel
    proxy = np.zeros(len(panel), dtype=float)
    if simulation.treatment_version in {
        TreatmentVersion.RIDER_DISCOUNT,
        TreatmentVersion.BUNDLED,
    }:
        proxy += (
            panel["baseline_demand"].to_numpy(dtype=float)
            * simulation.base_fare
            * simulation.discount_rate
        )
    if simulation.treatment_version in {
        TreatmentVersion.DRIVER_INCENTIVE,
        TreatmentVersion.BUNDLED,
    }:
        proxy += (
            panel["baseline_supply"].to_numpy(dtype=float)
            * simulation.incentive_per_driver
        )
    if not np.isfinite(proxy).all() or (proxy <= 0).any():
        raise ValueError("pre-treatment planning costs must be finite and positive")
    return proxy


def run_marketplace_policy_evaluation(
    simulation: SimulationConfig,
    config: MarketplacePolicyConfig,
    *,
    n_train_markets: int = 12,
    n_holdout_markets: int = 8,
) -> MarketplacePolicyResult:
    """Return aggregate results and the paired holdout-market ledger."""

    if n_train_markets < 2 or n_holdout_markets < 2:
        raise ValueError("policy evaluation requires at least two train and holdout markets")
    seeds = _seed_draws(config.seed, n_train_markets + n_holdout_markets)
    train_seeds = seeds[:n_train_markets]
    holdout_seeds = seeds[n_train_markets:]
    if set(train_seeds).intersection(holdout_seeds):
        raise AssertionError("training and holdout market seeds must be disjoint")

    training = _randomized_training_frame(simulation, config, train_seeds)
    models = _fit_t_learner_ensemble(training, config)
    market_rows: list[dict[str, object]] = []
    for holdout_index, seed in enumerate(holdout_seeds):
        evaluation_config = replace(simulation, seed=seed, budget=config.budget)
        control = simulate_market(
            evaluation_config,
            assignments=_zero_assignment(evaluation_config),
        )
        planning_cost = _pretreatment_planning_cost(control, evaluation_config)
        allocations, diagnostics = _policy_allocations(
            control,
            planning_cost,
            models,
            config,
            random_seed=config.seed + 100_000 + holdout_index,
        )
        for policy, intensity in allocations.items():
            evaluated = simulate_market(
                evaluation_config,
                assignments=_assignment_from_intensity(control.panel, intensity),
            )
            market_rows.append(
                _score_policy_market(
                    policy,
                    evaluated,
                    control,
                    budget=config.budget,
                    market_seed=seed,
                    diagnostics=diagnostics,
                )
            )

    market_results = pd.DataFrame(market_rows)
    if set(market_results["policy"]) != set(POLICY_NAMES):
        raise AssertionError("every declared baseline policy must be evaluated")
    if not market_results["budget_feasible"].all():
        raise AssertionError("simulator policy evaluation exceeded the fixed budget")

    random_reference = market_results.loc[
        market_results["policy"] == "random",
        ["holdout_market_seed", "incremental_trips"],
    ].rename(columns={"incremental_trips": "random_incremental_trips"})
    market_results = market_results.merge(
        random_reference,
        on="holdout_market_seed",
        how="left",
        validate="many_to_one",
    )
    market_results["paired_incremental_outcome_vs_random"] = (
        market_results["incremental_trips"]
        - market_results["random_incremental_trips"]
    )

    rows: list[dict[str, object]] = []
    for policy, group in market_results.groupby("policy", sort=True):
        total_spend = float(group["budget_spent"].sum())
        total_increment = float(group["incremental_trips"].sum())
        expected = float(group["incremental_trips"].mean())
        paired = group["paired_incremental_outcome_vs_random"]
        rows.append(
            {
                "policy": policy,
                "expected_incremental_outcome": expected,
                "incremental_outcome_sd": float(group["incremental_trips"].std(ddof=1)),
                "incremental_outcome_se": float(
                    group["incremental_trips"].std(ddof=1) / np.sqrt(len(group))
                ),
                "incremental_outcome_p10": float(group["incremental_trips"].quantile(0.10)),
                "incremental_welfare": float(group["incremental_welfare"].mean()),
                "incremental_platform_net_revenue": float(
                    group["incremental_platform_net_revenue"].mean()
                ),
                "budget_spent": float(group["budget_spent"].mean()),
                "budget": config.budget,
                "budget_efficiency": (
                    total_increment / total_spend if total_spend else np.nan
                ),
                "budget_feasible": bool(group["budget_feasible"].all()),
                "mean_treatment_intensity": float(group["mean_treatment_intensity"].mean()),
                "treated_cell_share": float(group["treated_cell_share"].mean()),
                "mean_wait_minutes_change": float(group["mean_wait_minutes_change"].mean()),
                "mean_model_instability": float(group["mean_model_instability"].mean()),
                "decision_instability": float(group["decision_instability"].mean()),
                "training_markets": n_train_markets,
                "training_rows": len(training),
                "holdout_markets": n_holdout_markets,
                "evaluation_complete": len(group) == n_holdout_markets,
                "incremental_outcome_vs_random": float(paired.mean()),
                "paired_difference_se_vs_random": float(
                    paired.std(ddof=1) / np.sqrt(len(paired))
                ),
                "paired_difference_p10_vs_random": float(paired.quantile(0.10)),
                "training_market_seeds": json.dumps(list(train_seeds)),
                "holdout_market_seeds": json.dumps(list(holdout_seeds)),
                "training_signal": "randomized observed outcomes; no structural truth columns",
                "evaluation_engine": "full marketplace simulator rerun per policy and seed",
                "planning_cost_basis": (
                    "pre-treatment baseline demand/supply and configured treatment prices; "
                    "no treated holdout counterfactual"
                ),
                "model": "random_forest_t_learner_ensemble",
                "target_estimand": "full_horizon_incremental_trips",
                "target_population_id": group["target_population_id"].iloc[0],
                "n_zones": simulation.n_zones,
                "n_periods": simulation.n_periods,
                "weighting": "mean of paired full-horizon market totals across holdout seeds",
                "simulation_config": json.dumps(simulation.to_dict(), sort_keys=True),
                "policy_config": json.dumps(asdict(config), sort_keys=True),
                "evidence_type": "semi_synthetic_policy_holdout",
            }
        )
    result = pd.DataFrame(rows).sort_values("policy").reset_index(drop=True)
    result["policy_eligible"] = (
        result["budget_feasible"]
        & result["evaluation_complete"]
        & np.isfinite(result["expected_incremental_outcome"])
    )
    return MarketplacePolicyResult(result, market_results)


def run_marketplace_policy_benchmark(
    simulation: SimulationConfig,
    config: MarketplacePolicyConfig,
    *,
    n_train_markets: int = 12,
    n_holdout_markets: int = 8,
) -> pd.DataFrame:
    """Fit on randomized markets and return the aggregate honest-holdout table."""

    return run_marketplace_policy_evaluation(
        simulation,
        config,
        n_train_markets=n_train_markets,
        n_holdout_markets=n_holdout_markets,
    ).summary


def run_treatment_version_policy_evaluation(
    simulation: SimulationConfig,
    config: MarketplacePolicyConfig,
    *,
    treatment_versions: Sequence[TreatmentVersion | str] = (
        TreatmentVersion.RIDER_DISCOUNT,
        TreatmentVersion.DRIVER_INCENTIVE,
        TreatmentVersion.BUNDLED,
    ),
    n_train_markets: int = 12,
    n_holdout_markets: int = 8,
) -> TreatmentVersionPolicyResult:
    """Evaluate every policy under rider, driver, and bundled interventions.

    The same training and holdout seed schedule is reused across versions. This makes
    latent-market draws paired when geometry is unchanged while fitting a separate
    learner for each treatment version. Version comparisons remain conditional on the
    simulator's declared response functions; they are not empirical dose-response
    estimates.
    """

    versions = tuple(TreatmentVersion.parse(value) for value in treatment_versions)
    if not versions:
        raise ValueError("at least one treatment version is required")
    if len(set(versions)) != len(versions):
        raise ValueError("treatment versions must be unique")
    summaries: list[pd.DataFrame] = []
    ledgers: list[pd.DataFrame] = []
    expected_training_seeds: str | None = None
    expected_holdout_seeds: str | None = None
    for version in versions:
        version_config = replace(simulation, treatment_version=version)
        evaluated = run_marketplace_policy_evaluation(
            version_config,
            config,
            n_train_markets=n_train_markets,
            n_holdout_markets=n_holdout_markets,
        )
        summary = evaluated.summary.copy()
        summary["treatment_version"] = version.value
        summary["version_pairing"] = (
            "common training/holdout market seeds across intervention versions"
        )
        summary["version_evidence_scope"] = (
            "semi-synthetic response-function sensitivity; not an empirical dose response"
        )
        ledger = evaluated.market_results.copy()
        ledger["treatment_version"] = version.value
        ledger["version_pairing"] = (
            "common training/holdout market seeds across intervention versions"
        )
        current_training_seeds = str(summary["training_market_seeds"].iloc[0])
        current_holdout_seeds = str(summary["holdout_market_seeds"].iloc[0])
        if expected_training_seeds is None:
            expected_training_seeds = current_training_seeds
            expected_holdout_seeds = current_holdout_seeds
        elif (
            current_training_seeds != expected_training_seeds
            or current_holdout_seeds != expected_holdout_seeds
        ):
            raise AssertionError("treatment-version evaluation lost common market seeds")
        summaries.append(summary)
        ledgers.append(ledger)
    return TreatmentVersionPolicyResult(
        summary=pd.concat(summaries, ignore_index=True),
        market_results=pd.concat(ledgers, ignore_index=True),
    )


__all__ = [
    "MarketplacePolicyConfig",
    "MarketplacePolicyResult",
    "TreatmentVersionPolicyResult",
    "run_marketplace_policy_benchmark",
    "run_marketplace_policy_evaluation",
    "run_treatment_version_policy_evaluation",
]
