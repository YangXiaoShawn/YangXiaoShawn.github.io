"""End-to-end simulator, design, and estimator Monte Carlo orchestration."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from math import isfinite
from numbers import Integral, Real

import numpy as np
import pandas as pd

from casuallab.benchmark import BenchmarkConfig, summarize_monte_carlo
from casuallab.config import (
    DesignConfig,
    DesignName,
    EstimatorConfig,
    SimulationConfig,
    TreatmentVersion,
)
from casuallab.estimands import EstimandName, get_estimand, identification_assessment
from casuallab.estimators import estimate_effect
from casuallab.simulator import simulate_market


@dataclass(frozen=True)
class SensitivityScenario:
    name: str
    spillover_strength: float
    persistence: float
    treatment_duration: int | None = None
    n_clusters: int | None = None
    treatment_saturation: float | None = None
    washout_periods: int | None = None
    budget: float | None = None
    treatment_version: TreatmentVersion | str | None = None
    varied_dimension: str = "custom"

    @property
    def scenario_role(self) -> str:
        """Return the scenario's role in the predeclared benchmark plan."""

        if self.budget is not None:
            return "target_mismatch_diagnostic"
        if self.varied_dimension == "reference":
            return "reference"
        if self.varied_dimension == "treatment_version":
            return "intervention_sensitivity"
        if self.varied_dimension in {
            "spillover_strength",
            "persistence",
            "spillover_x_persistence",
        }:
            return "mechanism_sensitivity"
        return "operational_sensitivity"

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("scenario name must not be empty")
        if not self.varied_dimension.strip():
            raise ValueError("varied_dimension must not be empty")
        for field_name, value in {
            "spillover_strength": self.spillover_strength,
            "persistence": self.persistence,
        }.items():
            if not isinstance(value, Real) or not isfinite(float(value)):
                raise ValueError(f"{field_name} must be a finite number")
        if self.spillover_strength < 0:
            raise ValueError("spillover_strength must be non-negative")
        if not 0 <= self.persistence < 1:
            raise ValueError("persistence must lie in [0, 1)")
        for field_name, value in {
            "treatment_duration": self.treatment_duration,
            "n_clusters": self.n_clusters,
            "washout_periods": self.washout_periods,
        }.items():
            if value is not None and (isinstance(value, bool) or not isinstance(value, Integral)):
                raise ValueError(f"{field_name} must be an integer when supplied")
        if self.treatment_duration is not None and self.treatment_duration < 1:
            raise ValueError("treatment_duration must be positive when supplied")
        if self.n_clusters is not None and self.n_clusters < 1:
            raise ValueError("n_clusters must be positive when supplied")
        if self.washout_periods is not None and self.washout_periods < 0:
            raise ValueError("washout_periods cannot be negative")
        if self.treatment_saturation is not None:
            if not isinstance(self.treatment_saturation, Real) or not isfinite(
                float(self.treatment_saturation)
            ):
                raise ValueError("treatment_saturation must be a finite number")
            if not 0 < self.treatment_saturation <= 1:
                raise ValueError("treatment_saturation must lie in (0, 1]")
        if self.budget is not None:
            if not isinstance(self.budget, Real) or not isfinite(float(self.budget)):
                raise ValueError("budget must be a finite number when supplied")
            if self.budget < 0:
                raise ValueError("budget cannot be negative")
        if self.treatment_version is not None:
            object.__setattr__(
                self,
                "treatment_version",
                TreatmentVersion.parse(self.treatment_version),
            )
        if (
            self.treatment_duration is not None
            and self.washout_periods is not None
            and self.washout_periods >= self.treatment_duration
        ):
            raise ValueError("washout_periods must be shorter than treatment_duration")


@dataclass(frozen=True)
class MarketplaceBenchmarkResult:
    records: pd.DataFrame
    summary: pd.DataFrame
    failures: pd.DataFrame
    fit_ledger: pd.DataFrame


def default_sensitivity_scenarios(
    simulation: SimulationConfig,
) -> tuple[SensitivityScenario, ...]:
    """Return a compact, predeclared mechanism and operating-parameter grid.

    The first four cells retain the paired spillover-by-persistence factorial. The
    remaining cells vary one assignment, intervention, or constraint dimension from the
    no-interference reference. A low shared-budget cell is included as an explicit
    *target-mismatch diagnostic*: assignment-specific budget dilution is not treated
    as identification of the feasible all-zone policy effect.
    """

    active_spillover = max(0.15, simulation.spillover_strength)
    active_persistence = max(0.25, simulation.persistence)
    n_zones = max(8, simulation.n_zones)
    base_duration = simulation.design.treatment_duration
    duration_variant = (
        base_duration * 2
        if base_duration * 2 <= simulation.n_periods
        else max(1, base_duration // 2)
    )
    if duration_variant == base_duration:
        duration_variant = base_duration + 1

    base_clusters = min(simulation.design.n_clusters or 4, n_zones)
    cluster_variant = n_zones if base_clusters < n_zones else max(1, base_clusters // 2)
    if cluster_variant == base_clusters:
        cluster_variant = max(1, base_clusters - 1)

    base_saturation = simulation.design.treatment_saturation
    saturation_variant = 0.5 if not np.isclose(base_saturation, 0.5) else 0.75

    washout_duration = max(2, base_duration)
    base_washout = simulation.design.washout_periods
    washout_variant = max(1, washout_duration // 2) if base_washout == 0 else 0
    washout_variant = min(washout_variant, washout_duration - 1)

    # This is intentionally conservative and laptop-safe. For the default calibrated
    # configuration it is below unconstrained spend by a wide margin; every run also
    # records the empirical binding rate rather than assuming the constraint bound.
    nominal_cost_per_cell = 0.0
    if simulation.treatment_version in {
        TreatmentVersion.RIDER_DISCOUNT,
        TreatmentVersion.BUNDLED,
    }:
        nominal_cost_per_cell += (
            simulation.base_demand * simulation.base_fare * simulation.discount_rate
        )
    if simulation.treatment_version in {
        TreatmentVersion.DRIVER_INCENTIVE,
        TreatmentVersion.BUNDLED,
    }:
        nominal_cost_per_cell += simulation.base_supply * simulation.incentive_per_driver
    low_budget = max(
        1.0,
        0.02 * n_zones * simulation.n_periods * nominal_cost_per_cell,
    )
    configured_budget = simulation.effective_budget
    if configured_budget is not None and configured_budget > 0:
        low_budget = min(float(configured_budget), low_budget)

    return (
        SensitivityScenario("no_interference", 0.0, 0.0, varied_dimension="reference"),
        SensitivityScenario(
            "spillover_only",
            active_spillover,
            0.0,
            varied_dimension="spillover_strength",
        ),
        SensitivityScenario(
            "persistence_only",
            0.0,
            active_persistence,
            varied_dimension="persistence",
        ),
        SensitivityScenario(
            "spillover_and_persistence",
            active_spillover,
            active_persistence,
            varied_dimension="spillover_x_persistence",
        ),
        SensitivityScenario(
            "treatment_duration_variant",
            0.0,
            0.0,
            treatment_duration=duration_variant,
            varied_dimension="treatment_duration",
        ),
        SensitivityScenario(
            "cluster_count_variant",
            0.0,
            0.0,
            n_clusters=cluster_variant,
            varied_dimension="cluster_count",
        ),
        SensitivityScenario(
            "partial_saturation",
            0.0,
            0.0,
            treatment_saturation=saturation_variant,
            varied_dimension="treatment_saturation",
        ),
        SensitivityScenario(
            "washout_variant",
            0.0,
            active_persistence,
            treatment_duration=washout_duration,
            washout_periods=washout_variant,
            varied_dimension="washout_periods",
        ),
        SensitivityScenario(
            "shared_budget_low",
            0.0,
            0.0,
            budget=low_budget,
            varied_dimension="budget",
        ),
        SensitivityScenario(
            "rider_discount_only",
            0.0,
            0.0,
            treatment_version=TreatmentVersion.RIDER_DISCOUNT,
            varied_dimension="treatment_version",
        ),
        SensitivityScenario(
            "driver_incentive_only",
            0.0,
            0.0,
            treatment_version=TreatmentVersion.DRIVER_INCENTIVE,
            varied_dimension="treatment_version",
        ),
    )


def _scenario_simulation_config(
    simulation: SimulationConfig,
    scenario: SensitivityScenario,
    *,
    n_zones: int,
    seed: int,
) -> SimulationConfig:
    """Apply a scenario's declared overrides without inheriting the base budget."""

    duration = scenario.treatment_duration or simulation.design.treatment_duration
    washout = (
        simulation.design.washout_periods
        if scenario.washout_periods is None
        else scenario.washout_periods
    )
    if washout >= duration:
        raise ValueError(f"scenario {scenario.name!r} has washout_periods >= treatment_duration")
    design = replace(
        simulation.design,
        treatment_duration=duration,
        washout_periods=washout,
        n_clusters=(
            simulation.design.n_clusters if scenario.n_clusters is None else scenario.n_clusters
        ),
        treatment_saturation=(
            simulation.design.treatment_saturation
            if scenario.treatment_saturation is None
            else scenario.treatment_saturation
        ),
        # The simulation-level scenario budget is the sole shared constraint.
        budget=None,
    )
    return replace(
        simulation,
        n_zones=n_zones,
        budget=scenario.budget,
        seed=seed,
        spillover_strength=scenario.spillover_strength,
        persistence=scenario.persistence,
        rider_substitution=(
            0.0 if scenario.spillover_strength == 0 else simulation.rider_substitution
        ),
        driver_mobility=(0.0 if scenario.spillover_strength == 0 else simulation.driver_mobility),
        treatment_version=(
            simulation.treatment_version
            if scenario.treatment_version is None
            else scenario.treatment_version
        ),
        design=design,
    )


def _budget_scope(budget: float | None) -> str:
    if budget is None:
        return "unconstrained estimator-recovery simulation"
    return (
        f"shared market budget={float(budget):.12g}; assignment-vs-full-policy "
        "comparison is a target-mismatch diagnostic"
    )


def _scenario_n_zones(
    simulation: SimulationConfig,
    scenario: SensitivityScenario,
) -> int:
    """Use two zones per requested geographic cluster, matching dashboard geometry."""

    requested_clusters = scenario.n_clusters or simulation.design.n_clusters or 4
    return max(4, 2 * int(requested_clusters))


_METHOD_ALIASES = {
    "regression_adjusted": "regression_adjustment",
    "regression": "regression_adjustment",
    "cluster_adjusted": "cluster_robust",
    "clustered": "cluster_robust",
    "two_way_cluster": "two_way_cluster_robust",
    "two_way_clustered": "two_way_cluster_robust",
    "did": "difference_in_differences",
    "aipw": "doubly_robust",
    "dr": "doubly_robust",
}

MIN_INFERENCE_CLUSTERS = 8


def _canonical_method(method: str) -> str:
    normalized = method.strip().lower().replace("-", "_").replace(" ", "_")
    return _METHOD_ALIASES.get(normalized, normalized)


def _applicable_methods(design: DesignName, requested: tuple[str, ...]) -> tuple[str, ...]:
    canonical = tuple(dict.fromkeys(_canonical_method(method) for method in requested))
    if design is DesignName.INDIVIDUAL:
        allowed = {"regression_adjustment", "cluster_robust"}
    elif design is DesignName.GEO_CLUSTER:
        allowed = {
            "difference_in_means",
            "regression_adjustment",
            "cluster_robust",
            "doubly_robust",
        }
    elif design is DesignName.GEO_TIME:
        allowed = {
            "difference_in_means",
            "regression_adjustment",
            "cluster_robust",
            "difference_in_differences",
            "doubly_robust",
            "two_way_cluster_robust",
        }
    else:
        # Pure temporal assignments have no stable treated group for conventional
        # DiD; common time fixed effects absorb marketplace-wide treatment.
        allowed = {
            "difference_in_means",
            "regression_adjustment",
            "cluster_robust",
            "doubly_robust",
        }
    return tuple(method for method in canonical if method in allowed)


def _scenario_method_applicability(
    method: str,
    design: DesignName,
    planned_randomization_clusters: int,
    treatment_probability: float,
) -> tuple[bool, str]:
    """Screen estimator requirements known before any Monte Carlo draw."""

    homogeneous_assignment_groups = {
        DesignName.GEO_CLUSTER,
        DesignName.TIME_BLOCK,
        DesignName.GEO_TIME,
    }
    if method == "doubly_robust" and design in homogeneous_assignment_groups:
        treated_clusters = int(
            np.clip(
                round(treatment_probability * planned_randomization_clusters),
                1,
                planned_randomization_clusters - 1,
            )
        )
        control_clusters = planned_randomization_clusters - treated_clusters
        if min(treated_clusters, control_clusters) < 2:
            return (
                False,
                "group-cross-fitted doubly robust estimation requires at least two "
                "planned randomization clusters in each arm",
            )
    return True, "implemented for this assignment geometry"


def _design_config(
    design: DesignName,
    simulation: SimulationConfig,
    *,
    seed: int,
) -> DesignConfig:
    requested_clusters = simulation.design.n_clusters or 4
    n_clusters = min(requested_clusters, simulation.n_zones)
    cluster_size = max(1, int(np.ceil(simulation.n_zones / n_clusters)))
    temporal = design in {DesignName.TIME_BLOCK, DesignName.SWITCHBACK, DesignName.GEO_TIME}
    duration = simulation.design.treatment_duration
    washout = simulation.design.washout_periods if temporal else 0
    return DesignConfig(
        name=design,
        treatment_probability=simulation.design.treatment_probability,
        treatment_saturation=simulation.design.treatment_saturation,
        n_clusters=n_clusters if design in {DesignName.GEO_CLUSTER, DesignName.GEO_TIME} else None,
        cluster_size=cluster_size,
        treatment_duration=duration,
        washout_periods=min(washout, duration - 1),
        budget=None,
        seed=seed + 1,
    )


def _estimator_config(
    method: str,
    design: DesignName,
    target_estimand: str,
    seed: int,
) -> EstimatorConfig:
    treatment = "treatment" if design is DesignName.INDIVIDUAL else "assigned_treatment"
    cluster: str | None = None
    if method == "cluster_robust":
        cluster = "zone_id" if design is DesignName.INDIVIDUAL else "randomization_cluster"
    elif method == "two_way_cluster_robust":
        cluster = "cluster_id"
    elif method == "doubly_robust":
        cluster = "randomization_cluster"
    return EstimatorConfig(
        method=method,
        outcome="outcome",
        treatment=treatment,
        covariates=("baseline_demand", "baseline_supply", "hour_sin", "hour_cos"),
        cluster=cluster,
        propensity="treatment_probability" if method == "doubly_robust" else None,
        unit="zone_id" if method == "difference_in_differences" else None,
        time=(
            "period_id"
            if method == "difference_in_differences"
            else ("time_block" if method == "two_way_cluster_robust" else None)
        ),
        target_estimand=target_estimand,
        alpha=0.05,
        # Canonical simulator truths use the fixed configured horizon. Washout-
        # restricted truths remain separately named analysis_population_* values.
        filter_eligible=False,
        crossfit_folds=3,
        seed=seed,
    )


def _design_identification_flag(
    design: DesignName,
    target_estimand: str,
    scenario: SensitivityScenario,
) -> bool:
    # A shared cap scales the realized mixed assignment and the feasible all-zone
    # policy by different factors. Without a budget-aware exposure mapping, their
    # assignment coefficient is not the declared full-policy estimand.
    if scenario.budget is not None:
        return False
    compatible = design.value in set(get_estimand(target_estimand).compatible_designs)
    screen, _ = identification_assessment(
        target_estimand,
        design=design.value,
        interference_present=scenario.spillover_strength > 0,
        exposure_mapped=False,
        histories_observed=True,
    )
    if not compatible or not screen:
        return False
    if design is DesignName.GEO_CLUSTER and scenario.spillover_strength > 0:
        return False
    if design in {DesignName.TIME_BLOCK, DesignName.SWITCHBACK} and scenario.persistence > 0:
        return False
    if design is DesignName.GEO_TIME and (
        scenario.spillover_strength > 0 or scenario.persistence > 0
    ):
        return False
    return True


def _identification_reason(
    design: DesignName,
    target_estimand: str,
    scenario: SensitivityScenario,
) -> str:
    if _design_identification_flag(design, target_estimand, scenario):
        return "assignment contrast matches the fixed full-horizon target"
    if scenario.budget is not None:
        return (
            "shared-budget scaling couples realized intensity to aggregate assignment, "
            "so the assignment contrast does not identify the feasible all-zone policy"
        )
    if design.value not in set(get_estimand(target_estimand).compatible_designs):
        return "assignment family targets a different causal contrast"
    if design is DesignName.GEO_CLUSTER and scenario.spillover_strength > 0:
        return "cross-cluster spillover prevents isolation of the all-zone policy"
    if design in {DesignName.TIME_BLOCK, DesignName.SWITCHBACK} and scenario.persistence > 0:
        return "carryover makes current assignment differ from full-policy history"
    if design is DesignName.GEO_TIME:
        return "unmodeled spatial or temporal exposure changes the assignment contrast"
    return "conservative identification screen failed"


def _planned_cluster_counts(
    design: DesignName,
    *,
    n_zones: int,
    n_periods: int,
    config: DesignConfig,
) -> tuple[int, int]:
    """Return randomized-unit and estimator-inference cluster counts."""

    time_blocks = int(np.ceil(n_periods / config.treatment_duration))
    geo_clusters = config.n_clusters or int(np.ceil(n_zones / config.cluster_size))
    if design is DesignName.INDIVIDUAL:
        return n_zones * n_periods, n_zones
    if design is DesignName.GEO_CLUSTER:
        return geo_clusters, geo_clusters
    if design is DesignName.TIME_BLOCK:
        return time_blocks, time_blocks
    if design is DesignName.SWITCHBACK:
        pairs = int(np.ceil(time_blocks / 2))
        return pairs, pairs
    return geo_clusters * time_blocks, geo_clusters * time_blocks


def _inference_assessment(
    method: str,
    design: DesignName,
    n_inference_clusters: int,
    *,
    n_geographic_clusters: int | None = None,
    n_time_clusters: int | None = None,
) -> tuple[bool, str]:
    """Assess whether reported uncertainty follows the randomized assignment unit."""

    if method == "two_way_cluster_robust":
        if design is not DesignName.GEO_TIME:
            return False, "two-way geographic-time inference requires geo_time assignment"
        if n_geographic_clusters is None or n_time_clusters is None:
            return False, "two-way inference dimensions were not recorded"
        limiting_clusters = min(n_geographic_clusters, n_time_clusters)
        if limiting_clusters < MIN_INFERENCE_CLUSTERS:
            return (
                False,
                f"few-cluster diagnostic: min({n_geographic_clusters} geographic, "
                f"{n_time_clusters} time) groups is below {MIN_INFERENCE_CLUSTERS}",
            )
        return True, "two-way geographic and time-block cluster-aware uncertainty"

    if design is DesignName.GEO_TIME and method in {
        "cluster_robust",
        "doubly_robust",
        "difference_in_differences",
    }:
        return (
            False,
            "point estimate diagnostic; one-way uncertainty does not cover shared "
            "geographic and time-block dependence",
        )
    if method in {"cluster_robust", "doubly_robust"}:
        if n_inference_clusters < MIN_INFERENCE_CLUSTERS:
            return (
                False,
                f"few-cluster diagnostic: {n_inference_clusters} independent inference "
                f"clusters is below the declared minimum of {MIN_INFERENCE_CLUSTERS}",
            )
        return True, "assignment-cluster-aware uncertainty"
    return False, "point estimate diagnostic; iid uncertainty ignores clustered assignment"


def _cluster_semantics(design: DesignName) -> str:
    descriptions = {
        DesignName.INDIVIDUAL: "zone-period saturation assignments",
        DesignName.GEO_CLUSTER: "geographic assignment clusters",
        DesignName.TIME_BLOCK: "market-wide time-block assignments",
        DesignName.SWITCHBACK: "randomized switchback block pairs",
        DesignName.GEO_TIME: "geographic-cluster-by-time-block assignment cells",
    }
    return descriptions[design]


def run_marketplace_benchmark(
    benchmark: BenchmarkConfig,
    simulation: SimulationConfig,
    *,
    scenarios: tuple[SensitivityScenario, ...] | None = None,
) -> MarketplaceBenchmarkResult:
    """Compare assignment/estimator pairs against matched structural truth.

    The reference recovery cells disable the configured experiment budget. A single
    low-budget sensitivity cell is retained but is explicitly marked as a target
    mismatch because the shared cap dilutes a mixed assignment differently from the
    feasible all-market policy. Operational policy evaluation remains separate in
    ``marketplace_policy``.
    """

    selected_scenarios = (
        default_sensitivity_scenarios(simulation) if scenarios is None else scenarios
    )
    if not selected_scenarios:
        raise ValueError("at least one sensitivity scenario is required")
    scenario_names = [scenario.name for scenario in selected_scenarios]
    if len(scenario_names) != len(set(scenario_names)):
        raise ValueError("sensitivity scenario names must be unique")
    declared_scenario_set = json.dumps(sorted(scenario_names), separators=(",", ":"))
    target = EstimandName.parse(benchmark.target_estimand).value
    if target != EstimandName.MARKET_TOTAL.value:
        raise ValueError(
            "marketplace estimator recovery currently supports only "
            "market_total_effect; cumulative, mechanism, and efficiency targets "
            "require estimand-specific transformations"
        )
    records: list[dict[str, object]] = []
    failures: list[dict[str, object]] = []
    fit_plans: list[dict[str, object]] = []
    master = np.random.SeedSequence(benchmark.seed)
    replication_seeds = [
        int(sequence.generate_state(1)[0]) for sequence in master.spawn(benchmark.replications)
    ]

    for scenario in selected_scenarios:
        # Reuse each replication seed across designs and scenarios. This gives exact
        # common-random-number pairing when panel geometry is equal; the cluster-count
        # cell intentionally changes geometry and is common-seed rather than draw-paired.
        for design_name in benchmark.designs:
            design = DesignName.parse(design_name)
            candidate_methods = _applicable_methods(design, benchmark.estimators)
            n_zones = _scenario_n_zones(simulation, scenario)
            plan_base = _scenario_simulation_config(
                simulation,
                scenario,
                n_zones=n_zones,
                seed=benchmark.seed,
            )
            plan_design = _design_config(
                design,
                plan_base,
                seed=benchmark.seed,
            )
            identified = _design_identification_flag(design, target, scenario)
            identification_scope = _identification_reason(design, target, scenario)
            planned_randomization_clusters, planned_inference_clusters = _planned_cluster_counts(
                design,
                n_zones=n_zones,
                n_periods=simulation.n_periods,
                config=plan_design,
            )
            planned_geo_clusters = (
                int(plan_design.n_clusters or np.ceil(n_zones / plan_design.cluster_size))
                if design is DesignName.GEO_TIME
                else None
            )
            planned_time_clusters = (
                int(np.ceil(simulation.n_periods / plan_design.treatment_duration))
                if design is DesignName.GEO_TIME
                else None
            )
            method_applicability = {
                method: _scenario_method_applicability(
                    method,
                    design,
                    planned_randomization_clusters,
                    plan_design.treatment_probability,
                )
                for method in candidate_methods
            }
            methods = tuple(
                method for method, (applicable, _) in method_applicability.items() if applicable
            )
            for method in candidate_methods:
                applicable, applicability_reason = method_applicability[method]
                inference_valid, inference_scope = _inference_assessment(
                    method,
                    design,
                    planned_inference_clusters,
                    n_geographic_clusters=planned_geo_clusters,
                    n_time_clusters=planned_time_clusters,
                )
                fit_plans.append(
                    {
                        "scenario": scenario.name,
                        "declared_scenario_set": declared_scenario_set,
                        "declared_scenario_count": len(selected_scenarios),
                        "design": design.value,
                        "estimator": method,
                        "target_estimand": target,
                        "varied_dimension": scenario.varied_dimension,
                        "scenario_role": scenario.scenario_role,
                        "spillover_strength": scenario.spillover_strength,
                        "persistence": scenario.persistence,
                        "treatment_duration": plan_design.treatment_duration,
                        "washout_periods": plan_design.washout_periods,
                        "treatment_saturation": plan_design.treatment_saturation,
                        "treatment_probability": plan_design.treatment_probability,
                        "configured_geo_clusters": plan_design.n_clusters,
                        "cluster_size": plan_design.cluster_size,
                        "cluster_semantics": _cluster_semantics(design),
                        "planned_randomization_clusters": planned_randomization_clusters,
                        "inference_clusters": planned_inference_clusters,
                        "inference_geographic_clusters": planned_geo_clusters,
                        "inference_time_clusters": planned_time_clusters,
                        "minimum_inference_clusters": MIN_INFERENCE_CLUSTERS,
                        "applicable": applicable,
                        "applicability_reason": applicability_reason,
                        "planned_fits": benchmark.replications if applicable else 0,
                        "n_zones": n_zones,
                        "n_periods": simulation.n_periods,
                        "identified": identified,
                        "identification_scope": identification_scope,
                        "comparison_status": (
                            "identified_target" if identified else "target_mismatch"
                        ),
                        "inference_valid": inference_valid,
                        "inference_scope": inference_scope,
                        "target_population_id": (
                            f"all_{n_zones}_zones_x_{simulation.n_periods}_periods_"
                            "equal_cell_weight"
                        ),
                        "estimator_population_id": "full_horizon",
                        "budget": scenario.budget,
                        "budget_scope": _budget_scope(scenario.budget),
                        "shared_budget_coupling": scenario.budget is not None,
                        "incentive_per_driver": plan_base.incentive_per_driver,
                        "treatment_version": plan_base.treatment_version.value,
                        "normalized_measurement_cost": (
                            n_zones * simulation.n_periods * benchmark.cost_per_market_period
                        ),
                        "measurement_cost_basis": (
                            "normalized zone-period measurement units; excludes treatment "
                            "and operational spend"
                        ),
                        "operational_cost_included": False,
                        "evidence_type": "semi_synthetic_causal_monte_carlo",
                    }
                )
            if not candidate_methods:
                failures.append(
                    {
                        "scenario": scenario.name,
                        "design": design.value,
                        "estimator": None,
                        "stage": "applicability",
                        "error": "no requested estimator is applicable to this assignment",
                    }
                )
                continue
            if not methods:
                continue
            for replication, seed in enumerate(replication_seeds):
                # Two zones per requested geographic cluster matches the dashboard's
                # scenario geometry. The G=8 cluster-count cell therefore uses 16
                # zones and supplies a declared adequate-cluster inference diagnostic.
                scenario_base = _scenario_simulation_config(
                    simulation,
                    n_zones=n_zones,
                    seed=seed,
                    scenario=scenario,
                )
                design_config = _design_config(
                    design,
                    scenario_base,
                    seed=seed,
                )
                scenario_config = replace(scenario_base, design=design_config)
                try:
                    result = simulate_market(scenario_config)
                except (ValueError, RuntimeError, np.linalg.LinAlgError) as exc:
                    for method in methods:
                        failures.append(
                            {
                                "scenario": scenario.name,
                                "design": design.value,
                                "estimator": method,
                                "replication": replication,
                                "seed": seed,
                                "stage": "simulation",
                                "error": str(exc),
                            }
                        )
                    continue
                truth = result.ground_truth.get(target)
                if truth is None or not np.isfinite(truth):
                    for method in methods:
                        failures.append(
                            {
                                "scenario": scenario.name,
                                "design": design.value,
                                "estimator": method,
                                "replication": replication,
                                "seed": seed,
                                "stage": "ground_truth",
                                "error": f"ground truth {target!r} is unavailable",
                            }
                        )
                    continue
                for method in methods:
                    estimator_config = _estimator_config(method, design, target, seed)
                    try:
                        estimate = estimate_effect(result.panel, estimator_config)
                    except (ValueError, np.linalg.LinAlgError) as exc:
                        failures.append(
                            {
                                "scenario": scenario.name,
                                "design": design.value,
                                "estimator": method,
                                "replication": replication,
                                "seed": seed,
                                "stage": "estimation",
                                "error": str(exc),
                            }
                        )
                        continue
                    inference_cluster_column = estimator_config.cluster
                    if inference_cluster_column is not None:
                        inference_clusters = int(result.panel[inference_cluster_column].nunique())
                    elif method == "difference_in_differences":
                        inference_clusters = int(result.panel["zone_id"].nunique())
                    else:
                        inference_clusters = planned_inference_clusters
                    inference_geographic_clusters = (
                        int(result.panel["cluster_id"].nunique())
                        if design is DesignName.GEO_TIME
                        else None
                    )
                    inference_time_clusters = (
                        int(result.panel["time_block"].nunique())
                        if design is DesignName.GEO_TIME
                        else None
                    )
                    valid_inference, inference_scope = _inference_assessment(
                        method,
                        design,
                        inference_clusters,
                        n_geographic_clusters=inference_geographic_clusters,
                        n_time_clusters=inference_time_clusters,
                    )
                    raw_gap = float(estimate.estimate - truth)
                    records.append(
                        {
                            "scenario": scenario.name,
                            "declared_scenario_set": declared_scenario_set,
                            "declared_scenario_count": len(selected_scenarios),
                            "design": design.value,
                            "estimator": estimate.method,
                            "replication": replication,
                            "seed": seed,
                            "target_estimand": target,
                            "varied_dimension": scenario.varied_dimension,
                            "scenario_role": scenario.scenario_role,
                            "estimate": estimate.estimate,
                            "std_error": estimate.standard_error,
                            "ci_low": estimate.ci_low,
                            "ci_high": estimate.ci_high,
                            "p_value": estimate.p_value,
                            "truth": float(truth),
                            "spillover_strength": scenario.spillover_strength,
                            "persistence": scenario.persistence,
                            "treatment_duration": design_config.treatment_duration,
                            "washout_periods": design_config.washout_periods,
                            "treatment_saturation": design_config.treatment_saturation,
                            "treatment_probability": design_config.treatment_probability,
                            "mean_assignment_propensity": float(
                                result.panel["treatment_probability"].mean()
                            ),
                            "configured_geo_clusters": design_config.n_clusters,
                            "effective_randomization_clusters": (
                                int(result.panel["randomization_cluster"].nunique())
                            ),
                            "cluster_semantics": _cluster_semantics(design),
                            "inference_clusters": inference_clusters,
                            "inference_geographic_clusters": inference_geographic_clusters,
                            "inference_time_clusters": inference_time_clusters,
                            "minimum_inference_clusters": MIN_INFERENCE_CLUSTERS,
                            "cluster_size": design_config.cluster_size,
                            "n_zones": scenario_config.n_zones,
                            "n_periods": scenario_config.n_periods,
                            "identified": identified,
                            "identification_scope": identification_scope,
                            "comparison_status": (
                                "identified_target" if identified else "target_mismatch"
                            ),
                            "inference_valid": valid_inference,
                            "inference_scope": inference_scope,
                            "estimation_error": raw_gap if identified else np.nan,
                            "diagnostic_gap": raw_gap if not identified else np.nan,
                            "target_population_id": result.metadata["target_population_id"],
                            "estimator_population_id": "full_horizon",
                            "budget": scenario_config.effective_budget,
                            "budget_scope": _budget_scope(scenario_config.effective_budget),
                            "shared_budget_coupling": (
                                scenario_config.effective_budget is not None
                            ),
                            "budget_binding": bool(
                                scenario_config.effective_budget is not None
                                and (
                                    float(result.metadata["budget_scale"]) < 1.0 - 1e-9
                                    or float(result.metadata["all_treated_budget_scale"])
                                    < 1.0 - 1e-9
                                )
                            ),
                            "assignment_budget_scale": result.metadata["budget_scale"],
                            "full_policy_budget_scale": result.metadata["all_treated_budget_scale"],
                            "incentive_per_driver": scenario_config.incentive_per_driver,
                            "treatment_version": scenario_config.treatment_version.value,
                            "normalized_measurement_cost": (
                                scenario_config.n_zones
                                * scenario_config.n_periods
                                * benchmark.cost_per_market_period
                            ),
                            # The generic Monte Carlo engine consumes this internal
                            # column; it is renamed before the public result is returned.
                            "design_cost": (
                                scenario_config.n_zones
                                * scenario_config.n_periods
                                * benchmark.cost_per_market_period
                            ),
                            "measurement_cost_basis": (
                                "normalized zone-period measurement units; excludes "
                                "treatment and operational spend"
                            ),
                            "operational_cost_included": False,
                            "full_policy_spend": result.ground_truth.get("full_policy_spend"),
                            "realized_schedule_spend": result.metadata.get("realized_spend"),
                            "target_rows": len(result.panel),
                            "washout_eligible_rows": result.ground_truth.get("analysis_rows"),
                            "evidence_type": "semi_synthetic_causal_monte_carlo",
                        }
                    )

    record_frame = pd.DataFrame(records)
    if record_frame.empty:
        nonbinding_budget_threshold = float("nan")
    else:
        # Only uncapped runs can certify the spend level above which a dashboard
        # budget is nonbinding. A capped path must never prove its own invariance.
        unconstrained = record_frame.loc[record_frame["budget"].isna()]
        spend_values = unconstrained[["full_policy_spend", "realized_schedule_spend"]].to_numpy(
            dtype=float
        )
        if spend_values.size == 0 or not np.isfinite(spend_values).any():
            nonbinding_budget_threshold = float("nan")
        else:
            nonbinding_budget_threshold = float(np.nanmax(spend_values))
        record_frame["nonbinding_budget_threshold"] = nonbinding_budget_threshold
        record_frame["nonbinding_budget_threshold_scope"] = (
            "maximum full-policy or realized-schedule treatment spend across successful "
            "unconstrained benchmark simulations, designs, replications, and scenarios"
        )
    ledger_keys = ["scenario", "design", "estimator"]
    fit_ledger = pd.DataFrame(fit_plans)
    if fit_ledger.empty:
        raise ValueError("no requested estimator is applicable to any selected design")
    if record_frame.empty:
        success_counts = pd.DataFrame(columns=[*ledger_keys, "successful_fits"])
    else:
        success_counts = (
            record_frame.groupby(ledger_keys, dropna=False)
            .size()
            .rename("successful_fits")
            .reset_index()
        )
    fit_ledger = fit_ledger.merge(
        success_counts,
        on=ledger_keys,
        how="left",
        validate="one_to_one",
    )
    fit_ledger["attempted_fits"] = fit_ledger.pop("planned_fits").astype(int)
    fit_ledger["successful_fits"] = fit_ledger["successful_fits"].fillna(0).astype(int)
    fit_ledger["failed_fits"] = fit_ledger["attempted_fits"] - fit_ledger["successful_fits"]
    fit_ledger["fit_success_rate"] = fit_ledger["successful_fits"] / fit_ledger["attempted_fits"]
    fit_ledger["fit_complete"] = fit_ledger["failed_fits"].eq(0)
    fit_ledger["nonbinding_budget_threshold"] = nonbinding_budget_threshold
    fit_ledger["nonbinding_budget_threshold_scope"] = (
        "maximum full-policy or realized-schedule treatment spend across successful "
        "unconstrained benchmark simulations, designs, replications, and scenarios"
    )

    if record_frame.empty:
        summary = fit_ledger.copy()
        for column in (
            "truth",
            "mean_estimate",
            "bias",
            "bias_mcse",
            "variance",
            "rmse",
            "rmse_mcse",
            "coverage",
            "coverage_mcse",
            "power",
            "power_mcse",
            "mean_std_error",
            "normalized_precision_cost",
            "mean_full_policy_spend",
            "max_full_policy_spend",
            "mean_realized_schedule_spend",
            "max_realized_schedule_spend",
            "budget_binding_rate",
            "mean_assignment_budget_scale",
            "mean_full_policy_budget_scale",
            "mean_target_rows",
            "mean_washout_eligible_rows",
            "effective_randomization_clusters",
            "mean_assignment_propensity",
        ):
            summary[column] = np.nan
        summary["replications"] = 0
        summary["mean_normalized_measurement_cost"] = summary["normalized_measurement_cost"]
        summary["confidence_level"] = benchmark.confidence_level
    else:
        metric_summary = summarize_monte_carlo(
            record_frame,
            confidence_level=benchmark.confidence_level,
            group_columns=ledger_keys,
        ).rename(
            columns={
                "mean_design_cost": "mean_normalized_measurement_cost",
                "information_cost": "normalized_precision_cost",
            }
        )
        metric_summary = metric_summary.drop(columns=["evidence_type"])
        summary = fit_ledger.merge(
            metric_summary,
            on=ledger_keys,
            how="left",
            validate="one_to_one",
        )
        supplemental = (
            record_frame.groupby(ledger_keys, dropna=False)
            .agg(
                mean_full_policy_spend=("full_policy_spend", "mean"),
                max_full_policy_spend=("full_policy_spend", "max"),
                mean_realized_schedule_spend=("realized_schedule_spend", "mean"),
                max_realized_schedule_spend=("realized_schedule_spend", "max"),
                budget_binding_rate=("budget_binding", "mean"),
                mean_assignment_budget_scale=("assignment_budget_scale", "mean"),
                mean_full_policy_budget_scale=("full_policy_budget_scale", "mean"),
                mean_target_rows=("target_rows", "mean"),
                mean_washout_eligible_rows=("washout_eligible_rows", "mean"),
                effective_randomization_clusters=(
                    "effective_randomization_clusters",
                    "mean",
                ),
                mean_assignment_propensity=("mean_assignment_propensity", "mean"),
            )
            .reset_index()
        )
        summary = summary.merge(
            supplemental,
            on=ledger_keys,
            how="left",
            validate="one_to_one",
        )
    summary["normalized_precision_cost_definition"] = (
        "mean normalized zone-period measurement units multiplied by MSE; lower is better"
    )
    summary["diagnostic_mean_gap"] = np.where(
        ~summary["identified"].astype(bool), summary["bias"], np.nan
    )
    summary["diagnostic_gap_mcse"] = np.where(
        ~summary["identified"].astype(bool), summary["bias_mcse"], np.nan
    )
    target_mismatch = ~summary["identified"].astype(bool)
    summary.loc[
        target_mismatch,
        [
            "bias",
            "bias_mcse",
            "rmse",
            "rmse_mcse",
            "coverage",
            "coverage_mcse",
            "power",
            "power_mcse",
            "normalized_precision_cost",
        ],
    ] = np.nan
    invalid_inference = ~summary["inference_valid"].astype(bool)
    summary.loc[
        invalid_inference,
        ["coverage", "coverage_mcse", "power", "power_mcse"],
    ] = np.nan
    failure_frame = pd.DataFrame(failures)
    public_records = record_frame.drop(columns=["design_cost"], errors="ignore")
    return MarketplaceBenchmarkResult(public_records, summary, failure_frame, fit_ledger)
