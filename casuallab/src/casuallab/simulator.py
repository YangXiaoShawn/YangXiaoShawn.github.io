"""Deterministic semi-synthetic two-sided marketplace simulator.

The simulator is structural rather than a table of canned effects.  A seed creates a
fixed set of zone heterogeneity and demand/supply shocks.  Observed and
counterfactual assignment schedules are evaluated against those same shocks, so the
returned ground truth is known for each generated market.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, replace
from typing import Any

import numpy as np
import pandas as pd
from scipy.optimize import brentq

from .config import DesignConfig, DesignName, SimulationConfig, TreatmentVersion
from .designs import generate_assignment
from .estimands import GroundTruth, compute_ground_truth


@dataclass(frozen=True)
class SimulationResult:
    """A simulated panel, assignment record, counterfactual truth, and provenance."""

    panel: pd.DataFrame
    ground_truth: GroundTruth
    assignment: pd.DataFrame
    metadata: Mapping[str, Any]
    counterfactuals: Mapping[str, pd.DataFrame]

    @property
    def data(self) -> pd.DataFrame:
        """Alias used by estimator and benchmark callers."""

        return self.panel

    @property
    def truth(self) -> GroundTruth:
        return self.ground_truth

    def __iter__(self) -> Iterator[pd.DataFrame | GroundTruth]:
        """Allow ``panel, truth = simulate_market(...)`` without hiding metadata."""

        yield self.panel
        yield self.ground_truth


def _coerce_config(config: SimulationConfig | Mapping[str, Any] | None) -> SimulationConfig:
    if config is None:
        return SimulationConfig()
    if isinstance(config, SimulationConfig):
        return config
    if isinstance(config, Mapping):
        return SimulationConfig.from_dict(config)
    raise TypeError("config must be SimulationConfig, a mapping, or None")


def _adjacency(n_zones: int) -> np.ndarray:
    """Row-normalized ring adjacency used as the declared exposure mapping."""

    weights = np.zeros((n_zones, n_zones), dtype=float)
    if n_zones == 1:
        return weights
    if n_zones == 2:
        weights[0, 1] = weights[1, 0] = 1.0
        return weights
    for zone in range(n_zones):
        weights[zone, (zone - 1) % n_zones] = 0.5
        weights[zone, (zone + 1) % n_zones] = 0.5
    return weights


def _make_exogenous_state(config: SimulationConfig) -> pd.DataFrame:
    rng = np.random.default_rng(config.seed)
    n_zones, n_periods = config.n_zones, config.n_periods

    zone_demand_log = rng.normal(
        -0.5 * config.zone_heterogeneity_sd**2,
        config.zone_heterogeneity_sd,
        size=n_zones,
    )
    zone_supply_log = (
        0.35 * zone_demand_log
        + rng.normal(
            -0.5 * config.zone_heterogeneity_sd**2,
            config.zone_heterogeneity_sd,
            size=n_zones,
        )
    )
    zone_demand_factor = np.exp(zone_demand_log)
    zone_supply_factor = np.exp(zone_supply_log)

    periods = np.arange(n_periods)
    hour = periods % config.periods_per_day
    angle = 2.0 * np.pi * hour / config.periods_per_day
    # A deterministic two-harmonic cycle creates peaks without using observed
    # outcomes to decide treatment.
    demand_cycle = np.exp(
        config.time_pattern_strength * (0.75 * np.sin(angle - 0.8) - 0.35 * np.cos(2 * angle))
    )
    supply_cycle = np.exp(0.45 * config.time_pattern_strength * np.sin(angle - 1.1))
    demand_shock = np.exp(
        rng.normal(
            -0.5 * config.demand_noise_sd**2,
            config.demand_noise_sd,
            size=(n_periods, n_zones),
        )
    )
    supply_shock = np.exp(
        rng.normal(
            -0.5 * config.supply_noise_sd**2,
            config.supply_noise_sd,
            size=(n_periods, n_zones),
        )
    )

    baseline_demand = (
        config.base_demand
        * demand_cycle[:, None]
        * zone_demand_factor[None, :]
        * demand_shock
    )
    baseline_supply = (
        config.base_supply
        * supply_cycle[:, None]
        * zone_supply_factor[None, :]
        * supply_shock
    )

    grid = pd.MultiIndex.from_product(
        [range(n_periods), range(n_zones)], names=["period_id", "zone_id"]
    ).to_frame(index=False)
    grid["unit_id"] = np.arange(len(grid), dtype=int)
    grid["hour"] = np.repeat(hour, n_zones)
    grid["day"] = grid["period_id"] // config.periods_per_day
    grid["hour_sin"] = np.sin(2.0 * np.pi * grid["hour"] / config.periods_per_day)
    grid["hour_cos"] = np.cos(2.0 * np.pi * grid["hour"] / config.periods_per_day)
    grid["baseline_demand"] = baseline_demand.reshape(-1)
    grid["baseline_supply"] = baseline_supply.reshape(-1)
    grid["market_tightness"] = grid["baseline_demand"] / (
        config.capacity_per_driver * grid["baseline_supply"]
    )
    grid["zone_demand_factor"] = np.tile(zone_demand_factor, n_periods)
    grid["zone_supply_factor"] = np.tile(zone_supply_factor, n_periods)
    return grid


def _validate_assignment(
    assignment: pd.DataFrame,
    base: pd.DataFrame,
    config: SimulationConfig,
) -> pd.DataFrame:
    frame = assignment.copy()
    rename: dict[str, str] = {}
    if "zone_id" not in frame and "zone" in frame:
        rename["zone"] = "zone_id"
    if "period_id" not in frame and "period" in frame:
        rename["period"] = "period_id"
    frame = frame.rename(columns=rename)
    missing_keys = {"zone_id", "period_id"}.difference(frame.columns)
    if missing_keys:
        raise ValueError(f"assignments missing columns: {sorted(missing_keys)}")
    if frame.duplicated(["zone_id", "period_id"]).any():
        raise ValueError("assignments must contain one row per zone-period")
    if "treatment" not in frame:
        for candidate in ("treatment_intensity", "assigned_treatment", "assignment"):
            if candidate in frame:
                frame["treatment"] = frame[candidate]
                break
        else:
            raise ValueError("assignments require treatment or assigned_treatment")
    if "assigned_treatment" not in frame:
        frame["assigned_treatment"] = frame["treatment"]

    keys = base[["zone_id", "period_id", "unit_id"]]
    frame = keys.merge(frame.drop(columns="unit_id", errors="ignore"), on=["zone_id", "period_id"], how="left")
    if frame["treatment"].isna().any():
        raise ValueError("assignments do not cover every configured zone-period")
    for column in ("treatment", "assigned_treatment"):
        values = frame[column].to_numpy(dtype=float)
        if not np.isfinite(values).all() or ((values < 0) | (values > 1)).any():
            raise ValueError(f"{column} must be finite and lie in [0, 1]")

    defaults: dict[str, Any] = {
        "design": config.design.name.value,
        "cluster_id": frame["zone_id"],
        "time_block": frame["period_id"],
        "randomization_cluster": frame["zone_id"].astype(str),
        "treatment_probability": config.design.treatment_probability,
        "analysis_eligible": 1,
        "washout": 0,
        "assignment_seed": config.design.seed if config.design.seed is not None else config.seed + 1,
    }
    for column, value in defaults.items():
        if column not in frame:
            frame[column] = value
    frame["planned_treatment"] = frame["treatment"].astype(float)
    return frame.sort_values(["period_id", "zone_id"]).reset_index(drop=True)


def _persistent_state(treatment: np.ndarray, persistence: float) -> np.ndarray:
    state = np.zeros_like(treatment, dtype=float)
    carry = np.zeros(treatment.shape[1], dtype=float)
    for period in range(treatment.shape[0]):
        carry = treatment[period] + persistence * carry
        state[period] = carry
    return state


def _evaluate_path(
    base: pd.DataFrame,
    treatment: np.ndarray,
    config: SimulationConfig,
    *,
    cross_zone: bool = True,
    persistence: float | None = None,
) -> pd.DataFrame:
    n_periods, n_zones = config.n_periods, config.n_zones
    schedule = np.asarray(treatment, dtype=float).reshape(n_periods, n_zones)
    persistence_value = config.persistence if persistence is None else persistence
    state = _persistent_state(schedule, persistence_value)
    weights = _adjacency(n_zones)
    neighbor_treatment = schedule @ weights.T
    neighbor_state = state @ weights.T
    rider_active = config.treatment_version in {
        TreatmentVersion.RIDER_DISCOUNT,
        TreatmentVersion.BUNDLED,
    }
    driver_active = config.treatment_version in {
        TreatmentVersion.DRIVER_INCENTIVE,
        TreatmentVersion.BUNDLED,
    }
    driver_dose_scale = (
        config.incentive_per_driver / config.reference_incentive_per_driver
        if driver_active
        else 0.0
    )

    if cross_zone:
        demand_cross = (
            config.spillover_strength * neighbor_state
            if rider_active
            else np.zeros_like(state)
        )
        supply_cross = (
            0.5 * config.spillover_strength * driver_dose_scale * neighbor_state
            if driver_active
            else np.zeros_like(state)
        )
        rider_reallocation_signal = (
            config.rider_substitution * (state - neighbor_state)
            if rider_active
            else np.zeros_like(state)
        )
        driver_reallocation_signal = (
            config.driver_mobility * driver_dose_scale * (state - neighbor_state)
            if driver_active
            else np.zeros_like(state)
        )
    else:
        demand_cross = np.zeros_like(state)
        supply_cross = np.zeros_like(state)
        rider_reallocation_signal = np.zeros_like(state)
        driver_reallocation_signal = np.zeros_like(state)

    demand_log_change = (
        config.direct_demand_effect * state if rider_active else np.zeros_like(state)
    ) + demand_cross
    supply_log_change = (
        config.direct_supply_effect * driver_dose_scale * state
        if driver_active
        else np.zeros_like(state)
    ) + supply_cross
    # This numerical guard is intentionally far outside ordinary configurations; it
    # prevents accidental overflow in stress tests without changing default paths.
    demand_multiplier = np.exp(np.clip(demand_log_change, -10.0, 10.0))
    supply_multiplier = np.exp(np.clip(supply_log_change, -10.0, 10.0))
    baseline_demand = base["baseline_demand"].to_numpy().reshape(n_periods, n_zones)
    baseline_supply = base["baseline_supply"].to_numpy().reshape(n_periods, n_zones)
    demand_before_substitution = baseline_demand * demand_multiplier
    supply_before_movement = baseline_supply * supply_multiplier
    latent_demand = demand_before_substitution * np.exp(
        np.clip(rider_reallocation_signal, -10.0, 10.0)
    )
    available_drivers = supply_before_movement * np.exp(
        np.clip(driver_reallocation_signal, -10.0, 10.0)
    )
    # Substitution and movement redistribute mass within a period. Direct response
    # and spillover parameters may expand/contract totals, but the relocation
    # channels themselves do not create riders or drivers.
    latent_demand *= (
        demand_before_substitution.sum(axis=1) / np.maximum(latent_demand.sum(axis=1), 1e-12)
    )[:, None]
    available_drivers *= (
        supply_before_movement.sum(axis=1) / np.maximum(available_drivers.sum(axis=1), 1e-12)
    )[:, None]
    service_capacity = (
        available_drivers * config.capacity_per_driver * config.matching_efficiency
    )
    capacity_ratio = service_capacity / np.maximum(latent_demand, 1e-12)
    service_probability = -np.expm1(-capacity_ratio)
    trips = latent_demand * service_probability
    wait_minutes = config.base_wait_minutes * np.power(
        latent_demand / np.maximum(service_capacity, 1e-12), 0.70
    )
    wait_minutes = np.clip(wait_minutes, 0.25, 120.0)
    rider_schedule = schedule if rider_active else np.zeros_like(schedule)
    driver_schedule = schedule if driver_active else np.zeros_like(schedule)
    fare = config.base_fare * (1.0 - config.discount_rate * rider_schedule)
    rider_discount_cost = trips * config.base_fare * config.discount_rate * rider_schedule
    driver_incentive_cost = (
        available_drivers * config.incentive_per_driver * driver_schedule
    )
    treatment_cost = rider_discount_cost + driver_incentive_cost
    gross_bookings = trips * fare
    platform_net_revenue = gross_bookings - driver_incentive_cost
    welfare = (
        trips * (config.rider_value - config.operating_cost_per_trip)
        - latent_demand * wait_minutes * config.wait_disutility_per_minute
    )

    result = base.copy()
    result["treatment_version"] = config.treatment_version.value
    result["treatment"] = schedule.reshape(-1)
    result["treatment_intensity"] = result["treatment"]
    result["neighbor_treatment"] = neighbor_treatment.reshape(-1)
    result["persistent_treatment"] = state.reshape(-1)
    result["neighbor_persistent_treatment"] = neighbor_state.reshape(-1)
    result["latent_demand"] = latent_demand.reshape(-1)
    result["available_drivers"] = available_drivers.reshape(-1)
    result["demand_before_substitution"] = demand_before_substitution.reshape(-1)
    result["supply_before_movement"] = supply_before_movement.reshape(-1)
    result["rider_reallocation_signal"] = rider_reallocation_signal.reshape(-1)
    result["driver_reallocation_signal"] = driver_reallocation_signal.reshape(-1)
    result["service_capacity"] = service_capacity.reshape(-1)
    result["service_probability"] = service_probability.reshape(-1)
    result["trips"] = trips.reshape(-1)
    result["outcome"] = result["trips"]
    result["wait_minutes"] = wait_minutes.reshape(-1)
    result["fare"] = fare.reshape(-1)
    result["rider_discount_cost"] = rider_discount_cost.reshape(-1)
    result["driver_incentive_cost"] = driver_incentive_cost.reshape(-1)
    result["treatment_cost"] = treatment_cost.reshape(-1)
    result["gross_bookings"] = gross_bookings.reshape(-1)
    result["platform_net_revenue"] = platform_net_revenue.reshape(-1)
    result["welfare"] = welfare.reshape(-1)
    return result


def _apply_realized_budget(
    base: pd.DataFrame,
    planned_treatment: np.ndarray,
    config: SimulationConfig,
    budget: float | None,
) -> tuple[np.ndarray, float, pd.DataFrame]:
    planned = np.asarray(planned_treatment, dtype=float)
    full_path = _evaluate_path(base, planned, config)
    if budget is None or float(full_path["treatment_cost"].sum()) <= budget:
        return planned, 1.0, full_path
    if budget == 0 or np.allclose(planned, 0):
        zero = np.zeros_like(planned)
        return zero, 0.0, _evaluate_path(base, zero, config)

    def excess_spend(scale: float) -> float:
        path = _evaluate_path(base, planned * scale, config)
        return float(path["treatment_cost"].sum() - budget)

    root = float(brentq(excess_spend, 0.0, 1.0, xtol=1e-10, rtol=1e-10, maxiter=60))
    low = max(0.0, root - 1e-10)
    realized = planned * low
    feasible_path = _evaluate_path(base, realized, config)
    # Protect against floating-point pennies above the declared constraint.
    spend = float(feasible_path["treatment_cost"].sum())
    if spend > budget + 1e-8:
        low *= budget / spend
        realized = planned * low
        feasible_path = _evaluate_path(base, realized, config)
    return realized, float(low), feasible_path


def _controlled_zone_contrasts(
    base: pd.DataFrame,
    control: pd.DataFrame,
    config: SimulationConfig,
    saturation: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Compute own-only and neighbor-only controlled exposure contrasts.

    For each focal zone, the direct schedule treats that zone at the configured
    saturation over the policy horizon while holding mapped neighbors at zero. The
    spillover schedule leaves the focal zone untreated while treating its ring
    neighbors. These controlled exposure contrasts deliberately do not apply the
    shared market budget: applying it separately to each focal schedule would change
    the treatment version across zones. Effects are extracted only for the focal zone.
    """

    shape = (config.n_periods, config.n_zones)
    controlled_direct = np.zeros(len(base), dtype=float)
    controlled_spillover = np.zeros(len(base), dtype=float)
    y0 = control["trips"].to_numpy(dtype=float)
    neighbors = _adjacency(config.n_zones)
    for focal_zone in range(config.n_zones):
        focal_rows = base["zone_id"].to_numpy(dtype=int) == focal_zone

        own_schedule = np.zeros(shape, dtype=float)
        own_schedule[:, focal_zone] = saturation
        own_path = _evaluate_path(base, own_schedule.reshape(-1), config)
        controlled_direct[focal_rows] = (
            own_path["trips"].to_numpy(dtype=float)[focal_rows] - y0[focal_rows]
        )

        neighbor_schedule = np.zeros(shape, dtype=float)
        neighbor_zones = np.flatnonzero(neighbors[focal_zone] > 0)
        neighbor_schedule[:, neighbor_zones] = saturation
        neighbor_path = _evaluate_path(base, neighbor_schedule.reshape(-1), config)
        controlled_spillover[focal_rows] = (
            neighbor_path["trips"].to_numpy(dtype=float)[focal_rows] - y0[focal_rows]
        )
    return controlled_direct, controlled_spillover


def simulate_market(
    config: SimulationConfig | Mapping[str, Any] | None = None,
    design: DesignConfig | DesignName | str | pd.DataFrame | None = None,
    assignments: pd.DataFrame | None = None,
) -> SimulationResult:
    """Simulate a randomized market and matching structural counterfactuals.

    Parameters
    ----------
    config:
        Typed config or a compatible mapping.
    design:
        Optional design override or, for convenience, an assignment frame.
    assignments:
        Optional caller-supplied zone-period schedule.  Assignment values are
        validated and never generated from outcomes.
    """

    cfg = _coerce_config(config)
    if isinstance(design, pd.DataFrame):
        if assignments is not None:
            raise ValueError("provide assignments either as design or assignments, not both")
        assignments = design
        design = None
    if isinstance(design, DesignConfig):
        cfg = replace(cfg, design=design)
    elif design is not None:
        cfg = replace(cfg, design=replace(cfg.design, name=DesignName.parse(design)))

    base = _make_exogenous_state(cfg)
    if assignments is None:
        assignment_seed = cfg.design.seed if cfg.design.seed is not None else cfg.seed + 1
        generated = generate_assignment(
            cfg.n_zones,
            cfg.n_periods,
            cfg.design,
            seed=assignment_seed,
            individuals_per_cell=cfg.individuals_per_cell,
        )
    else:
        generated = assignments
    assignment = _validate_assignment(generated, base, cfg)

    planned = assignment["planned_treatment"].to_numpy(dtype=float)
    realized, budget_scale, observed = _apply_realized_budget(
        base, planned, cfg, cfg.effective_budget
    )
    assignment["treatment"] = realized
    assignment["treatment_intensity"] = realized
    assignment["budget_scale"] = budget_scale

    zero = np.zeros_like(realized)
    control = _evaluate_path(base, zero, cfg)
    direct_only = _evaluate_path(base, realized, cfg, cross_zone=False)
    short_run = _evaluate_path(base, realized, cfg, persistence=0.0)
    full_market_schedule = np.full_like(
        realized, cfg.design.treatment_saturation, dtype=float
    )
    all_treated_schedule, all_treated_budget_scale, all_treated = _apply_realized_budget(
        base, full_market_schedule, cfg, cfg.effective_budget
    )
    all_treated_short_run = _evaluate_path(
        base, all_treated_schedule, cfg, persistence=0.0
    )
    controlled_direct, controlled_spillover = _controlled_zone_contrasts(
        base,
        control,
        cfg,
        cfg.design.treatment_saturation,
    )
    no_cross_zone_interference = cfg.n_zones == 1 or all(
        value == 0
        for value in (
            cfg.spillover_strength,
            cfg.rider_substitution,
            cfg.driver_mobility,
        )
    )
    itt_available = (
        cfg.design.name is not DesignName.INDIVIDUAL
        and no_cross_zone_interference
        and cfg.persistence == 0
        and cfg.effective_budget is None
    )
    assignment_itt_effects = (
        all_treated["trips"].to_numpy(dtype=float)
        - control["trips"].to_numpy(dtype=float)
        if itt_available
        else None
    )

    truth = compute_ground_truth(
        observed,
        control,
        direct_only=direct_only,
        short_run=short_run,
        all_treated=all_treated,
        all_treated_short_run=all_treated_short_run,
        controlled_direct_effects=controlled_direct,
        controlled_spillover_effects=controlled_spillover,
        all_treated_received=all_treated_schedule,
        analysis_eligible=assignment["analysis_eligible"].to_numpy(dtype=bool),
        assignment_itt_effects=assignment_itt_effects,
        assignment_first_stage=(
            cfg.design.treatment_saturation if itt_available else None
        ),
        assigned_treatment=assignment["assigned_treatment"].to_numpy(dtype=float),
        received_treatment=realized,
    )

    assignment_columns = [
        column
        for column in assignment.columns
        if column not in {"unit_id", "zone_id", "period_id", "treatment", "treatment_intensity"}
    ]
    panel = observed.merge(
        assignment[["unit_id", *assignment_columns]], on="unit_id", how="left", validate="one_to_one"
    )
    panel["assigned"] = panel["assigned_treatment"]
    panel["zone"] = panel["zone_id"]
    panel["period"] = panel["period_id"]
    panel["cluster"] = panel["cluster_id"]
    panel["y0"] = control["trips"].to_numpy(dtype=float)
    panel["y_observed"] = panel["trips"]
    panel["true_effect"] = truth.unit_effects["realized_schedule_effect"].to_numpy(dtype=float)
    panel["true_full_policy_effect"] = truth.unit_effects[
        "full_policy_total_effect"
    ].to_numpy(dtype=float)
    panel["true_direct_effect"] = truth.unit_effects["individual_direct_effect"].to_numpy(
        dtype=float
    )
    panel["true_controlled_zone_direct_effect"] = truth.unit_effects[
        "controlled_direct_effect"
    ].to_numpy(dtype=float)
    panel["true_spillover_effect"] = truth.unit_effects[
        "controlled_spillover_effect"
    ].to_numpy(dtype=float)
    panel["true_short_run_effect"] = truth.unit_effects[
        "full_policy_short_run_effect"
    ].to_numpy(dtype=float)
    panel["true_persistent_effect"] = truth.unit_effects[
        "full_policy_persistent_effect"
    ].to_numpy(dtype=float)
    panel["evidence_type"] = "semi_synthetic_causal"
    panel["simulation_seed"] = cfg.seed

    spend = float(panel["treatment_cost"].sum())
    full_policy_spend = float(all_treated["treatment_cost"].sum())
    budget = cfg.effective_budget
    metadata: dict[str, Any] = {
        "evidence_type": "semi_synthetic_known_ground_truth",
        "simulation_seed": cfg.seed,
        "assignment_seed": int(assignment["assignment_seed"].iloc[0]),
        "design": cfg.design.name.value,
        "n_zones": cfg.n_zones,
        "n_periods": cfg.n_periods,
        "exposure_mapping": "row-normalized ring adjacency",
        "budget": budget,
        "realized_spend": spend,
        "full_policy_spend": full_policy_spend,
        "budget_scale": budget_scale,
        "all_treated_budget_scale": all_treated_budget_scale,
        "budget_feasible": budget is None or spend <= budget + 1e-8,
        "treatment_version": cfg.treatment_version.value,
        "treatment_version_description": {
            TreatmentVersion.RIDER_DISCOUNT: (
                "rider discount with demand response; driver incentive and supply response disabled"
            ),
            TreatmentVersion.DRIVER_INCENTIVE: (
                "driver incentive with supply response; rider discount and demand response disabled"
            ),
            TreatmentVersion.BUNDLED: (
                "rider discount and driver incentive delivered at one common intensity"
            ),
        }[cfg.treatment_version],
        "driver_incentive_response_scale": (
            cfg.incentive_per_driver / cfg.reference_incentive_per_driver
            if cfg.treatment_version
            in {TreatmentVersion.DRIVER_INCENTIVE, TreatmentVersion.BUNDLED}
            else 0.0
        ),
        "reference_incentive_per_driver": cfg.reference_incentive_per_driver,
        "treatment_version_limitation": (
            "each experiment has one selected treatment version; simultaneous factorial "
            "rider-versus-driver arms require separate randomized assignments"
        ),
        "ground_truth": truth.to_json_dict(),
        "ground_truth_definitions": {
            "market_total_effect": (
                "all-zone treatment policy versus all-zero, averaged per zone-period "
                "over the fixed configured horizon"
            ),
            "analysis_population_market_total_effect": (
                "the same policy contrast restricted to assignment-specific analysis_eligible rows"
            ),
            "direct_effect": (
                "individual rider direct effect is unavailable in this aggregate zone-time simulator"
            ),
            "controlled_zone_direct_effect": (
                "unconstrained focal-zone saturation policy versus zone control with mapped "
                "neighbors at zero; the shared market budget is not re-scaled separately "
                "for each focal contrast"
            ),
            "spillover_effect": (
                "untreated focal zone with mapped neighbors treated at configured saturation "
                "versus all-zero; the shared market budget is not applied to this controlled "
                "exposure contrast"
            ),
            "short_run_effect": "all-zone policy with persistence disabled versus all-zero",
            "persistent_effect": "all-zone total effect minus its no-persistence path",
            "intent_to_treat": (
                "randomized-arm assignment contrast when no interference, carryover, or "
                "shared-budget coupling is configured; unavailable (NaN) otherwise"
            ),
            "true_effect_panel_column": "realized mixed-schedule effect versus all-zero",
            "full_horizon_incremental_trips": (
                "sum of all-zone policy versus zero effects over every configured zone-period"
            ),
            "full_policy_spend": "treatment spend for the feasible all-zone policy path",
        },
        "ground_truth_availability": {
            "direct_effect": {
                "available": False,
                "reason": "individual rider outcomes are not represented in the aggregate panel",
            },
            "controlled_zone_direct_effect": {"available": True, "reason": None},
            "intent_to_treat": {
                "available": itt_available,
                "reason": (
                    None
                    if itt_available
                    else "assignment contrast differs from the structural full-policy contrast"
                ),
            },
        },
        "analysis_rows": int(assignment["analysis_eligible"].sum()),
        "analysis_share": float(assignment["analysis_eligible"].mean()),
        "target_population_id": (
            f"all_{cfg.n_zones}_zones_x_{cfg.n_periods}_periods_equal_cell_weight"
        ),
        "estimation_population_id": (
            "full_horizon"
            if bool(assignment["analysis_eligible"].astype(bool).all())
            else "assignment_specific_washout_exclusions"
        ),
        "itt_available": itt_available,
        "config": cfg.to_dict(),
    }
    return SimulationResult(
        panel=panel,
        ground_truth=truth,
        assignment=assignment,
        metadata=metadata,
        counterfactuals={
            "control": control,
            "direct_only": direct_only,
            "short_run": short_run,
            "all_treated": all_treated,
            "all_treated_short_run": all_treated_short_run,
        },
    )


def simulate_panel(
    config: SimulationConfig | Mapping[str, Any] | None = None,
    design: DesignConfig | DesignName | str | pd.DataFrame | None = None,
    assignments: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Return only the panel for callers that do not need truth metadata."""

    return simulate_market(config, design, assignments).panel


run_simulation = simulate_market
