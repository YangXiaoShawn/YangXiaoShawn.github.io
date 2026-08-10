"""Transparent fixed-point equilibrium benchmark for a two-sided ride-hailing market.

This module is deliberately a small theoretical benchmark, not an empirical or
NYC structural estimate.  Conditional on one seeded exogenous market state, it
solves control and policy counterfactuals with common random numbers.

For zone ``z``, let ``x_z = log(wait_z / base_wait)``.  At a candidate state,

``D_z(x) = A_z exp(beta_p * discount_z - eta_d * x_z)``

``S_z(x) = B_z exp(beta_i * incentive_z / reference_incentive + eta_s * x_z)``

``F_z(x) = gamma * [(1-kappa) log(D_z / (capacity*S_z))
                    + kappa sum_j W_zj log(D_j / (capacity*S_j))]``.

An equilibrium satisfies ``x = F(x)``.  ``W`` is a row-normalized ring network
and ``kappa`` can disable or activate the cross-zone congestion channel.  Because
the network mixture is non-expansive in the sup norm, a transparent sufficient
condition for a unique equilibrium and convergence is
``gamma * (eta_d + eta_s) < 1``.  The solver fails closed when this condition is
not met or when the reported residual does not reach the configured tolerance.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, fields
from math import isfinite
from numbers import Integral, Real
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .config import TreatmentVersion

EVIDENCE_TYPE = "theoretical_simulation_known_ground_truth"
CAUSAL_SCOPE = "within_declared_equilibrium_model_only"
EMPIRICAL_STATUS = "not_an_empirical_or_nyc_structural_estimate"


@dataclass(frozen=True, slots=True)
class EquilibriumConfig:
    """Assumptions and numerical tolerances for the equilibrium benchmark."""

    n_zones: int = 2
    seed: int = 202_503
    base_demand: float = 100.0
    base_drivers: float = 72.0
    demand_shock_sd: float = 0.08
    supply_shock_sd: float = 0.06
    base_fare: float = 20.0
    base_wait_minutes: float = 5.0
    capacity_per_driver: float = 1.30
    demand_price_semielasticity: float = 1.20
    demand_wait_elasticity: float = 0.28
    supply_incentive_semielasticity: float = 0.30
    supply_wait_elasticity: float = 0.14
    congestion_elasticity: float = 0.70
    cross_zone_enabled: bool = True
    cross_zone_share: float = 0.20
    treatment_version: TreatmentVersion = TreatmentVersion.BUNDLED
    discount_rate: float = 0.10
    incentive_per_driver: float = 2.00
    reference_incentive_per_driver: float = 2.00
    rider_value_per_trip: float = 32.0
    wait_disutility_per_minute: float = 0.25
    platform_take_rate: float = 0.25
    driver_operating_cost_per_trip: float = 9.0
    driver_opportunity_cost_per_active_driver: float = 0.50
    budget: float | None = None
    tolerance: float = 1e-10
    max_iterations: int = 500
    relaxation: float = 0.75
    budget_tolerance: float = 1e-8
    budget_max_iterations: int = 80

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "treatment_version",
            TreatmentVersion.parse(self.treatment_version),
        )
        for name in ("n_zones", "seed", "max_iterations", "budget_max_iterations"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, Integral):
                raise ValueError(f"{name} must be an integer")
        if self.n_zones < 1:
            raise ValueError("n_zones must be positive")
        if self.max_iterations < 1 or self.budget_max_iterations < 1:
            raise ValueError("iteration limits must be positive")
        if not isinstance(self.cross_zone_enabled, bool):
            raise ValueError("cross_zone_enabled must be boolean")

        numeric_names = (
            "base_demand",
            "base_drivers",
            "demand_shock_sd",
            "supply_shock_sd",
            "base_fare",
            "base_wait_minutes",
            "capacity_per_driver",
            "demand_price_semielasticity",
            "demand_wait_elasticity",
            "supply_incentive_semielasticity",
            "supply_wait_elasticity",
            "congestion_elasticity",
            "cross_zone_share",
            "discount_rate",
            "incentive_per_driver",
            "reference_incentive_per_driver",
            "rider_value_per_trip",
            "wait_disutility_per_minute",
            "platform_take_rate",
            "driver_operating_cost_per_trip",
            "driver_opportunity_cost_per_active_driver",
            "tolerance",
            "relaxation",
            "budget_tolerance",
        )
        for name in numeric_names:
            value = getattr(self, name)
            if not isinstance(value, Real) or not isfinite(float(value)):
                raise ValueError(f"{name} must be a finite number")
        if self.budget is not None and (
            not isinstance(self.budget, Real) or not isfinite(float(self.budget))
        ):
            raise ValueError("budget must be finite when supplied")

        for name in (
            "base_demand",
            "base_drivers",
            "base_fare",
            "base_wait_minutes",
            "capacity_per_driver",
            "reference_incentive_per_driver",
            "rider_value_per_trip",
            "tolerance",
            "budget_tolerance",
        ):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        for name in (
            "demand_shock_sd",
            "supply_shock_sd",
            "demand_price_semielasticity",
            "demand_wait_elasticity",
            "supply_incentive_semielasticity",
            "supply_wait_elasticity",
            "congestion_elasticity",
            "incentive_per_driver",
            "wait_disutility_per_minute",
            "driver_operating_cost_per_trip",
            "driver_opportunity_cost_per_active_driver",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} cannot be negative")
        if not 0 <= self.discount_rate <= 1:
            raise ValueError("discount_rate must lie in [0, 1]")
        if not 0 <= self.cross_zone_share <= 1:
            raise ValueError("cross_zone_share must lie in [0, 1]")
        if not 0 <= self.platform_take_rate <= 1:
            raise ValueError("platform_take_rate must lie in [0, 1]")
        if not 0 < self.relaxation <= 1:
            raise ValueError("relaxation must lie in (0, 1]")
        if self.budget is not None and self.budget < 0:
            raise ValueError("budget cannot be negative")

    @property
    def contraction_bound(self) -> float:
        """Sup-norm Lipschitz bound for the raw fixed-point map ``F``."""

        return float(
            self.congestion_elasticity
            * (self.demand_wait_elasticity + self.supply_wait_elasticity)
        )

    @property
    def effective_iteration_bound(self) -> float:
        """Conservative bound after applying the configured relaxation."""

        return float(
            1.0
            - self.relaxation
            + self.relaxation * self.contraction_bound
        )

    @classmethod
    def from_mapping(cls, values: Mapping[str, object]) -> EquilibriumConfig:
        """Create a config while rejecting misspelled or unsupported fields."""

        if not isinstance(values, Mapping):
            raise TypeError("equilibrium configuration must be a mapping")
        allowed = {item.name for item in fields(cls)}
        unknown = set(values).difference(allowed)
        if unknown:
            raise ValueError(f"unknown equilibrium configuration keys: {sorted(unknown)}")
        return cls(**dict(values))


@dataclass(frozen=True, slots=True)
class EquilibriumState:
    """One immutable exogenous state shared by all counterfactual policy paths."""

    baseline_rider_arrivals: tuple[float, ...]
    baseline_driver_pool: tuple[float, ...]
    seed: int
    state_id: str

    def __post_init__(self) -> None:
        demand = tuple(float(value) for value in self.baseline_rider_arrivals)
        supply = tuple(float(value) for value in self.baseline_driver_pool)
        object.__setattr__(self, "baseline_rider_arrivals", demand)
        object.__setattr__(self, "baseline_driver_pool", supply)
        if len(demand) == 0 or len(demand) != len(supply):
            raise ValueError("exogenous demand and driver state must have equal positive length")
        values = np.asarray([*demand, *supply], dtype=float)
        if not np.isfinite(values).all() or (values <= 0).any():
            raise ValueError("exogenous demand and driver state must be finite and positive")
        if isinstance(self.seed, bool) or not isinstance(self.seed, Integral):
            raise ValueError("state seed must be an integer")
        if not self.state_id:
            raise ValueError("state_id cannot be empty")


@dataclass(frozen=True, slots=True)
class EquilibriumDiagnostics:
    """Auditable numerical and identification diagnostics for one solution."""

    converged: bool
    iterations: int
    initial_residual_sup_norm: float | None
    residual_sup_norm: float | None
    step_sup_norm: float | None
    tolerance: float
    contraction_bound: float
    effective_iteration_bound: float
    uniqueness_condition_satisfied: bool
    termination_reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class EquilibriumConvergenceError(RuntimeError):
    """Raised instead of returning an unverified or non-unique equilibrium."""

    def __init__(self, message: str, diagnostics: EquilibriumDiagnostics) -> None:
        super().__init__(message)
        self.diagnostics = diagnostics


class EquilibriumBudgetError(RuntimeError):
    """Raised when a monotone, budget-feasible treatment scale cannot be certified."""


@dataclass(frozen=True)
class EquilibriumOutcome:
    """One solved market path and its convergence evidence."""

    panel: pd.DataFrame
    diagnostics: EquilibriumDiagnostics
    metadata: Mapping[str, Any]


@dataclass(frozen=True)
class EquilibriumBenchmarkResult:
    """Paired equilibrium counterfactuals, exact model truth, and accounting ledger."""

    control: EquilibriumOutcome
    treatment: EquilibriumOutcome
    zone_effects: pd.DataFrame
    ledger: pd.DataFrame
    ground_truth: Mapping[str, float | None]
    metadata: Mapping[str, Any]

    @property
    def truth(self) -> Mapping[str, float | None]:
        """Compact alias for callers that treat this as a simulation benchmark."""

        return self.ground_truth


@dataclass(frozen=True, slots=True)
class EquilibriumArtifacts:
    """Portable files published by :func:`write_equilibrium_artifacts`."""

    summary_path: Path
    zone_effects_path: Path
    ledger_path: Path
    manifest_path: Path

    def paths(self) -> tuple[Path, ...]:
        """Return every published path, with the manifest last."""

        return (
            self.summary_path,
            self.zone_effects_path,
            self.ledger_path,
            self.manifest_path,
        )


def _coerce_config(
    config: EquilibriumConfig | Mapping[str, object] | None,
) -> EquilibriumConfig:
    if config is None:
        return EquilibriumConfig()
    if isinstance(config, EquilibriumConfig):
        return config
    if isinstance(config, Mapping):
        return EquilibriumConfig.from_mapping(config)
    raise TypeError("config must be EquilibriumConfig, a mapping, or None")


def _state_id(seed: int, demand: np.ndarray, supply: np.ndarray) -> str:
    digest = hashlib.sha256()
    digest.update(str(seed).encode("ascii"))
    digest.update(np.asarray(demand, dtype="<f8").tobytes())
    digest.update(np.asarray(supply, dtype="<f8").tobytes())
    return digest.hexdigest()


def draw_equilibrium_state(
    config: EquilibriumConfig | Mapping[str, object] | None = None,
) -> EquilibriumState:
    """Draw the one seeded exogenous state used for paired counterfactuals."""

    cfg = _coerce_config(config)
    rng = np.random.default_rng(cfg.seed)
    demand_multiplier = np.exp(
        rng.normal(-0.5 * cfg.demand_shock_sd**2, cfg.demand_shock_sd, cfg.n_zones)
    )
    supply_multiplier = np.exp(
        rng.normal(-0.5 * cfg.supply_shock_sd**2, cfg.supply_shock_sd, cfg.n_zones)
    )
    demand = cfg.base_demand * demand_multiplier
    supply = cfg.base_drivers * supply_multiplier
    return EquilibriumState(
        baseline_rider_arrivals=tuple(float(value) for value in demand),
        baseline_driver_pool=tuple(float(value) for value in supply),
        seed=cfg.seed,
        state_id=_state_id(cfg.seed, demand, supply),
    )


def _ring_adjacency(n_zones: int) -> np.ndarray:
    weights = np.zeros((n_zones, n_zones), dtype=float)
    if n_zones == 1:
        return weights
    if n_zones == 2:
        weights[0, 1] = 1.0
        weights[1, 0] = 1.0
        return weights
    for zone in range(n_zones):
        weights[zone, (zone - 1) % n_zones] = 0.5
        weights[zone, (zone + 1) % n_zones] = 0.5
    return weights


def _coerce_intensity(
    treatment_intensity: float | Sequence[float] | np.ndarray,
    n_zones: int,
) -> np.ndarray:
    if isinstance(treatment_intensity, Real) and not isinstance(treatment_intensity, bool):
        intensity = np.full(n_zones, float(treatment_intensity), dtype=float)
    else:
        intensity = np.asarray(treatment_intensity, dtype=float)
        if intensity.ndim != 1 or len(intensity) != n_zones:
            raise ValueError("treatment_intensity must be scalar or have one value per zone")
    if not np.isfinite(intensity).all() or ((intensity < 0) | (intensity > 1)).any():
        raise ValueError("treatment_intensity must be finite and lie in [0, 1]")
    return intensity


def _active_doses(
    intensity: np.ndarray,
    config: EquilibriumConfig,
) -> tuple[np.ndarray, np.ndarray]:
    rider_active = config.treatment_version in {
        TreatmentVersion.RIDER_DISCOUNT,
        TreatmentVersion.BUNDLED,
    }
    driver_active = config.treatment_version in {
        TreatmentVersion.DRIVER_INCENTIVE,
        TreatmentVersion.BUNDLED,
    }
    rider = intensity if rider_active else np.zeros_like(intensity)
    driver = intensity if driver_active else np.zeros_like(intensity)
    return rider, driver


def _market_map(
    log_wait_ratio: np.ndarray,
    state: EquilibriumState,
    intensity: np.ndarray,
    config: EquilibriumConfig,
) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    rider_dose, driver_dose = _active_doses(intensity, config)
    discount = config.discount_rate * rider_dose
    incentive = config.incentive_per_driver * driver_dose
    baseline_demand = np.asarray(state.baseline_rider_arrivals, dtype=float)
    baseline_supply = np.asarray(state.baseline_driver_pool, dtype=float)
    log_demand = (
        np.log(baseline_demand)
        + config.demand_price_semielasticity * discount
        - config.demand_wait_elasticity * log_wait_ratio
    )
    log_supply = (
        np.log(baseline_supply)
        + config.supply_incentive_semielasticity
        * incentive
        / config.reference_incentive_per_driver
        + config.supply_wait_elasticity * log_wait_ratio
    )
    log_tightness = log_demand - np.log(config.capacity_per_driver) - log_supply
    cross_share = (
        config.cross_zone_share
        if config.cross_zone_enabled and config.n_zones > 1
        else 0.0
    )
    neighbor_tightness = _ring_adjacency(config.n_zones) @ log_tightness
    mapped_tightness = (
        (1.0 - cross_share) * log_tightness + cross_share * neighbor_tightness
    )
    target = config.congestion_elasticity * mapped_tightness
    components = {
        "rider_dose": rider_dose,
        "driver_dose": driver_dose,
        "discount": discount,
        "incentive": incentive,
        "log_demand": log_demand,
        "log_supply": log_supply,
        "log_tightness": log_tightness,
        "neighbor_log_tightness": neighbor_tightness,
        "mapped_log_tightness": mapped_tightness,
    }
    return target, components


def _equations_metadata() -> dict[str, str]:
    return {
        "equilibrium_variable": "x_z = log(wait_z / base_wait_minutes)",
        "rider_demand": (
            "D_z = A_z * exp(demand_price_semielasticity * discount_z "
            "- demand_wait_elasticity * x_z)"
        ),
        "driver_supply": (
            "S_z = B_z * exp(supply_incentive_semielasticity * "
            "incentive_z/reference_incentive + supply_wait_elasticity * x_z)"
        ),
        "wait_fixed_point": (
            "x_z = congestion_elasticity * ((1-cross_zone_share)*log(D_z/(capacity*S_z)) "
            "+ cross_zone_share*sum_j W_zj*log(D_j/(capacity*S_j)))"
        ),
        "service_probability": "p_z = 1 - exp(-capacity_per_driver*S_z/D_z)",
        "served_trips": "Q_z = D_z * p_z",
        "uniqueness_and_convergence": (
            "Banach sufficient condition: congestion_elasticity * "
            "(demand_wait_elasticity + supply_wait_elasticity) < 1"
        ),
        "welfare": (
            "rider_surplus + driver_surplus + platform_net_revenue; monetary transfers "
            "cancel, while waiting, driver opportunity, and trip operating costs remain"
        ),
    }


def _failed_diagnostics(
    config: EquilibriumConfig,
    *,
    reason: str,
    iterations: int,
    initial_residual: float | None,
    residual: float | None,
    step: float | None,
) -> EquilibriumDiagnostics:
    return EquilibriumDiagnostics(
        converged=False,
        iterations=iterations,
        initial_residual_sup_norm=initial_residual,
        residual_sup_norm=residual,
        step_sup_norm=step,
        tolerance=config.tolerance,
        contraction_bound=config.contraction_bound,
        effective_iteration_bound=config.effective_iteration_bound,
        uniqueness_condition_satisfied=config.contraction_bound < 1.0,
        termination_reason=reason,
    )


def solve_market_equilibrium(
    config: EquilibriumConfig | Mapping[str, object] | None = None,
    treatment_intensity: float | Sequence[float] | np.ndarray = 0.0,
    *,
    state: EquilibriumState | None = None,
) -> EquilibriumOutcome:
    """Solve one intervention path, refusing uncertified or imprecise results."""

    cfg = _coerce_config(config)
    market_state = draw_equilibrium_state(cfg) if state is None else state
    if len(market_state.baseline_rider_arrivals) != cfg.n_zones:
        raise ValueError("state length must equal config.n_zones")
    intensity = _coerce_intensity(treatment_intensity, cfg.n_zones)
    if not cfg.contraction_bound < 1.0:
        diagnostics = _failed_diagnostics(
            cfg,
            reason="sufficient_contraction_condition_failed",
            iterations=0,
            initial_residual=None,
            residual=None,
            step=None,
        )
        raise EquilibriumConvergenceError(
            "equilibrium not solved: the declared sufficient uniqueness and convergence "
            "condition is not satisfied",
            diagnostics,
        )

    log_wait = np.zeros(cfg.n_zones, dtype=float)
    target, _ = _market_map(log_wait, market_state, intensity, cfg)
    initial_residual = float(np.max(np.abs(target - log_wait)))
    residual = initial_residual
    step = 0.0
    iterations = 0
    converged = residual <= cfg.tolerance
    while not converged and iterations < cfg.max_iterations:
        candidate = (1.0 - cfg.relaxation) * log_wait + cfg.relaxation * target
        if not np.isfinite(candidate).all():
            diagnostics = _failed_diagnostics(
                cfg,
                reason="nonfinite_fixed_point_iterate",
                iterations=iterations + 1,
                initial_residual=initial_residual,
                residual=None,
                step=None,
            )
            raise EquilibriumConvergenceError(
                "equilibrium iteration produced a non-finite state", diagnostics
            )
        step = float(np.max(np.abs(candidate - log_wait)))
        log_wait = candidate
        iterations += 1
        target, _ = _market_map(log_wait, market_state, intensity, cfg)
        residual = float(np.max(np.abs(target - log_wait)))
        converged = residual <= cfg.tolerance

    if not converged:
        diagnostics = _failed_diagnostics(
            cfg,
            reason="maximum_iterations_reached_before_residual_tolerance",
            iterations=iterations,
            initial_residual=initial_residual,
            residual=residual,
            step=step,
        )
        raise EquilibriumConvergenceError(
            "equilibrium not returned because the residual tolerance was not reached",
            diagnostics,
        )

    target, components = _market_map(log_wait, market_state, intensity, cfg)
    residual = float(np.max(np.abs(target - log_wait)))
    diagnostics = EquilibriumDiagnostics(
        converged=True,
        iterations=iterations,
        initial_residual_sup_norm=initial_residual,
        residual_sup_norm=residual,
        step_sup_norm=step,
        tolerance=cfg.tolerance,
        contraction_bound=cfg.contraction_bound,
        effective_iteration_bound=cfg.effective_iteration_bound,
        uniqueness_condition_satisfied=True,
        termination_reason="residual_tolerance_satisfied",
    )

    log_demand = components["log_demand"]
    log_supply = components["log_supply"]
    if (
        np.max(np.abs(log_demand)) > 300
        or np.max(np.abs(log_supply)) > 300
        or np.max(np.abs(log_wait)) > 300
    ):
        failed = _failed_diagnostics(
            cfg,
            reason="equilibrium_quantities_outside_numerically_safe_range",
            iterations=iterations,
            initial_residual=initial_residual,
            residual=residual,
            step=step,
        )
        raise EquilibriumConvergenceError(
            "equilibrium quantities exceed the declared numerical safety range", failed
        )

    latent_demand = np.exp(log_demand)
    available_drivers = np.exp(log_supply)
    wait_minutes = cfg.base_wait_minutes * np.exp(log_wait)
    log_capacity_ratio = (
        np.log(cfg.capacity_per_driver) + log_supply - log_demand
    )
    capacity_ratio = np.exp(np.clip(log_capacity_ratio, -745.0, 50.0))
    service_probability = -np.expm1(-capacity_ratio)
    trips = latent_demand * service_probability
    rider_price = cfg.base_fare * (1.0 - components["discount"])
    rider_discount_spend = trips * (cfg.base_fare - rider_price)
    driver_incentive_spend = available_drivers * components["incentive"]
    treatment_spend = rider_discount_spend + driver_incentive_spend

    driver_base_payout = trips * (1.0 - cfg.platform_take_rate) * cfg.base_fare
    trip_operating_cost = trips * cfg.driver_operating_cost_per_trip
    driver_opportunity_cost = (
        available_drivers * cfg.driver_opportunity_cost_per_active_driver
    )
    wait_disutility = (
        latent_demand * wait_minutes * cfg.wait_disutility_per_minute
    )
    rider_surplus = trips * (cfg.rider_value_per_trip - rider_price) - wait_disutility
    driver_surplus = (
        driver_base_payout
        + driver_incentive_spend
        - trip_operating_cost
        - driver_opportunity_cost
    )
    platform_net_revenue = (
        trips * rider_price - driver_base_payout - driver_incentive_spend
    )
    total_welfare = (
        trips * cfg.rider_value_per_trip
        - trip_operating_cost
        - wait_disutility
        - driver_opportunity_cost
    )
    welfare_accounting_residual = (
        rider_surplus + driver_surplus + platform_net_revenue - total_welfare
    )

    panel = pd.DataFrame(
        {
            "zone_id": np.arange(cfg.n_zones, dtype=int),
            "treatment_version": cfg.treatment_version.value,
            "treatment_intensity": intensity,
            "rider_treatment_dose": components["rider_dose"],
            "driver_treatment_dose": components["driver_dose"],
            "baseline_rider_arrivals": market_state.baseline_rider_arrivals,
            "baseline_driver_pool": market_state.baseline_driver_pool,
            "rider_price": rider_price,
            "driver_incentive_per_driver": components["incentive"],
            "log_wait_ratio": log_wait,
            "wait_minutes": wait_minutes,
            "latent_demand": latent_demand,
            "available_drivers": available_drivers,
            "log_tightness": components["log_tightness"],
            "mapped_log_tightness": components["mapped_log_tightness"],
            "service_probability": service_probability,
            "trips": trips,
            "rider_discount_spend": rider_discount_spend,
            "driver_incentive_spend": driver_incentive_spend,
            "treatment_spend": treatment_spend,
            "rider_surplus": rider_surplus,
            "driver_surplus": driver_surplus,
            "platform_net_revenue": platform_net_revenue,
            "total_welfare": total_welfare,
            "welfare_accounting_residual": welfare_accounting_residual,
            "evidence_type": EVIDENCE_TYPE,
            "causal_scope": CAUSAL_SCOPE,
            "empirical_calibration_status": EMPIRICAL_STATUS,
            "is_nyc_structural_estimate": False,
            "simulation_seed": cfg.seed,
            "state_id": market_state.state_id,
        }
    )
    numeric = panel.select_dtypes(include=[np.number]).to_numpy(dtype=float)
    if not np.isfinite(numeric).all():
        failed = _failed_diagnostics(
            cfg,
            reason="nonfinite_equilibrium_output",
            iterations=iterations,
            initial_residual=initial_residual,
            residual=residual,
            step=step,
        )
        raise EquilibriumConvergenceError(
            "equilibrium output contains non-finite quantities", failed
        )

    metadata: dict[str, Any] = {
        "schema_version": 1,
        "evidence_type": EVIDENCE_TYPE,
        "causal_scope": CAUSAL_SCOPE,
        "empirical_calibration_status": EMPIRICAL_STATUS,
        "is_nyc_structural_estimate": False,
        "simulation_seed": cfg.seed,
        "state_id": market_state.state_id,
        "treatment_version": cfg.treatment_version.value,
        "cross_zone_channel": bool(cfg.cross_zone_enabled and cfg.n_zones > 1),
        "cross_zone_share": (
            cfg.cross_zone_share
            if cfg.cross_zone_enabled and cfg.n_zones > 1
            else 0.0
        ),
        "equations": _equations_metadata(),
        "diagnostics": diagnostics.to_dict(),
        "configuration": asdict(cfg),
    }
    metadata["configuration"]["treatment_version"] = cfg.treatment_version.value
    return EquilibriumOutcome(panel=panel, diagnostics=diagnostics, metadata=metadata)


_LEDGER_COLUMNS = (
    "trips",
    "latent_demand",
    "available_drivers",
    "rider_discount_spend",
    "driver_incentive_spend",
    "treatment_spend",
    "rider_surplus",
    "driver_surplus",
    "platform_net_revenue",
    "total_welfare",
    "welfare_accounting_residual",
)


def _ledger_row(scenario: str, outcome: EquilibriumOutcome) -> dict[str, Any]:
    panel = outcome.panel
    row: dict[str, Any] = {
        "scenario": scenario,
        "treatment_version": str(panel["treatment_version"].iloc[0]),
        "mean_wait_minutes": float(panel["wait_minutes"].mean()),
        "mean_service_probability": float(panel["service_probability"].mean()),
        "equilibrium_converged": outcome.diagnostics.converged,
        "equilibrium_iterations": outcome.diagnostics.iterations,
        "equilibrium_residual_sup_norm": outcome.diagnostics.residual_sup_norm,
    }
    row.update({column: float(panel[column].sum()) for column in _LEDGER_COLUMNS})
    return row


def _budget_feasible_treatment(
    config: EquilibriumConfig,
    state: EquilibriumState,
    planned: np.ndarray,
    control: EquilibriumOutcome,
) -> tuple[EquilibriumOutcome, float, dict[str, Any]]:
    unconstrained = solve_market_equilibrium(config, planned, state=state)
    unconstrained_spend = float(unconstrained.panel["treatment_spend"].sum())
    budget = config.budget
    if budget is None or unconstrained_spend <= budget + config.budget_tolerance:
        return unconstrained, 1.0, {
            "budget": budget,
            "binding": False,
            "planned_treatment_spend": unconstrained_spend,
            "realized_treatment_spend": unconstrained_spend,
            "budget_scale": 1.0,
            "budget_search_iterations": 0,
            "budget_residual": None if budget is None else budget - unconstrained_spend,
            "budget_feasible": True,
        }
    if budget <= config.budget_tolerance:
        return control, 0.0, {
            "budget": budget,
            "binding": True,
            "planned_treatment_spend": unconstrained_spend,
            "realized_treatment_spend": 0.0,
            "budget_scale": 0.0,
            "budget_search_iterations": 0,
            "budget_residual": budget,
            "budget_feasible": True,
        }

    low = 0.0
    high = 1.0
    low_spend = 0.0
    high_spend = unconstrained_spend
    feasible = control
    iterations = 0
    for iteration in range(1, config.budget_max_iterations + 1):
        iterations = iteration
        midpoint = 0.5 * (low + high)
        candidate = solve_market_equilibrium(config, planned * midpoint, state=state)
        spend = float(candidate.panel["treatment_spend"].sum())
        if (
            spend < low_spend - config.budget_tolerance
            or spend > high_spend + config.budget_tolerance
        ):
            raise EquilibriumBudgetError(
                "treatment spend was not monotone in the common intensity scale; "
                "a budget-feasible policy was not asserted"
            )
        if spend <= budget:
            low = midpoint
            low_spend = spend
            feasible = candidate
        else:
            high = midpoint
            high_spend = spend
        if abs(spend - budget) <= config.budget_tolerance or high - low <= 1e-12:
            break

    realized_spend = float(feasible.panel["treatment_spend"].sum())
    if realized_spend > budget + config.budget_tolerance:
        raise EquilibriumBudgetError(
            "budget search ended without a certified feasible treatment path"
        )
    return feasible, low, {
        "budget": budget,
        "binding": True,
        "planned_treatment_spend": unconstrained_spend,
        "realized_treatment_spend": realized_spend,
        "budget_scale": low,
        "budget_search_iterations": iterations,
        "budget_residual": budget - realized_spend,
        "budget_feasible": True,
    }


def run_equilibrium_benchmark(
    config: EquilibriumConfig | Mapping[str, object] | None = None,
    planned_treatment_intensity: float | Sequence[float] | np.ndarray = 1.0,
    *,
    state: EquilibriumState | None = None,
) -> EquilibriumBenchmarkResult:
    """Solve paired control/policy equilibria and expose exact within-model truth.

    The same exogenous state is passed to both paths.  When a budget is supplied,
    the planned policy is uniformly scaled via a deterministic bisection and the
    realized equilibrium is re-solved at every candidate scale.
    """

    cfg = _coerce_config(config)
    market_state = draw_equilibrium_state(cfg) if state is None else state
    planned = _coerce_intensity(planned_treatment_intensity, cfg.n_zones)
    control = solve_market_equilibrium(cfg, 0.0, state=market_state)
    treatment, budget_scale, budget_diagnostics = _budget_feasible_treatment(
        cfg, market_state, planned, control
    )
    if control.metadata["state_id"] != treatment.metadata["state_id"]:
        raise AssertionError("counterfactual paths did not use common random numbers")

    control_panel = control.panel.sort_values("zone_id").reset_index(drop=True)
    treatment_panel = treatment.panel.sort_values("zone_id").reset_index(drop=True)
    zone_effects = pd.DataFrame(
        {
            "zone_id": control_panel["zone_id"],
            "control_trips": control_panel["trips"],
            "treatment_trips": treatment_panel["trips"],
            "trip_effect": treatment_panel["trips"] - control_panel["trips"],
            "control_wait_minutes": control_panel["wait_minutes"],
            "treatment_wait_minutes": treatment_panel["wait_minutes"],
            "wait_effect_minutes": (
                treatment_panel["wait_minutes"] - control_panel["wait_minutes"]
            ),
            "control_service_probability": control_panel["service_probability"],
            "treatment_service_probability": treatment_panel["service_probability"],
            "service_probability_effect": (
                treatment_panel["service_probability"]
                - control_panel["service_probability"]
            ),
            "control_welfare": control_panel["total_welfare"],
            "treatment_welfare": treatment_panel["total_welfare"],
            "welfare_effect": (
                treatment_panel["total_welfare"] - control_panel["total_welfare"]
            ),
            "realized_treatment_intensity": treatment_panel["treatment_intensity"],
            "state_id": market_state.state_id,
            "evidence_type": EVIDENCE_TYPE,
        }
    )

    ledger = pd.DataFrame(
        [_ledger_row("control", control), _ledger_row("treatment", treatment)]
    )
    ledger["budget"] = cfg.budget
    ledger["budget_binding"] = bool(budget_diagnostics["binding"])
    ledger["budget_scale"] = [0.0, budget_scale]
    treatment_spend = float(treatment_panel["treatment_spend"].sum())
    trip_effect = float(zone_effects["trip_effect"].sum())
    welfare_effect = float(zone_effects["welfare_effect"].sum())
    ground_truth: dict[str, float | None] = {
        "market_total_effect": trip_effect,
        "market_total_trip_effect": trip_effect,
        "mean_zone_trip_effect": float(zone_effects["trip_effect"].mean()),
        "market_total_welfare_effect": welfare_effect,
        "mean_zone_wait_effect_minutes": float(zone_effects["wait_effect_minutes"].mean()),
        "mean_zone_service_probability_effect": float(
            zone_effects["service_probability_effect"].mean()
        ),
        "treatment_spend": treatment_spend,
        "incremental_trips_per_dollar": (
            trip_effect / treatment_spend if treatment_spend > 1e-12 else None
        ),
        "incremental_welfare_per_dollar": (
            welfare_effect / treatment_spend if treatment_spend > 1e-12 else None
        ),
    }

    metadata: dict[str, Any] = {
        "schema_version": 1,
        "evidence_type": EVIDENCE_TYPE,
        "causal_scope": CAUSAL_SCOPE,
        "ground_truth_status": "known_exactly_for_the_paired_model_counterfactuals",
        "empirical_calibration_status": EMPIRICAL_STATUS,
        "is_nyc_structural_estimate": False,
        "common_random_numbers": True,
        "simulation_seed": cfg.seed,
        "state_id": market_state.state_id,
        "control_state_id": control.metadata["state_id"],
        "treatment_state_id": treatment.metadata["state_id"],
        "treatment_version": cfg.treatment_version.value,
        "planned_treatment_intensity": planned.tolist(),
        "realized_budget_scale": budget_scale,
        "cross_zone_channel": bool(cfg.cross_zone_enabled and cfg.n_zones > 1),
        "equations": _equations_metadata(),
        "uniqueness_diagnostics": {
            "sufficient_condition_satisfied": cfg.contraction_bound < 1.0,
            "contraction_bound": cfg.contraction_bound,
            "effective_iteration_bound": cfg.effective_iteration_bound,
            "condition": (
                "congestion_elasticity * (demand_wait_elasticity + "
                "supply_wait_elasticity) < 1"
            ),
        },
        "control_diagnostics": control.diagnostics.to_dict(),
        "treatment_diagnostics": treatment.diagnostics.to_dict(),
        "budget_diagnostics": budget_diagnostics,
        "ground_truth_definition": (
            "feasible policy equilibrium minus all-zero equilibrium for the identical "
            "seeded exogenous market state"
        ),
        "limitations": [
            "This is a theoretical simulation benchmark, not an empirical causal estimate.",
            "Parameters are declared assumptions and are not estimated from NYC data.",
            "The model is a static fixed point and omits forward-looking entry and relocation.",
            "The contraction condition is sufficient; paths failing it are withheld.",
            "Welfare inherits the declared value, waiting-cost, and driver-cost assumptions.",
        ],
    }
    return EquilibriumBenchmarkResult(
        control=control,
        treatment=treatment,
        zone_effects=zone_effects,
        ledger=ledger,
        ground_truth=ground_truth,
        metadata=metadata,
    )


def _strict_json_value(value: Any) -> Any:
    """Convert numpy scalars while refusing non-finite values and filesystem paths."""

    if isinstance(value, Path):
        raise ValueError("artifact JSON must not embed filesystem Path objects")
    if isinstance(value, Mapping):
        return {str(key): _strict_json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_strict_json_value(item) for item in value]
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not isfinite(value):
        raise ValueError("artifact JSON must not contain non-finite numbers")
    return value


def _assert_no_absolute_path_strings(value: Any) -> None:
    if isinstance(value, Mapping):
        for item in value.values():
            _assert_no_absolute_path_strings(item)
    elif isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            _assert_no_absolute_path_strings(item)
    elif isinstance(value, str) and Path(value).is_absolute():
        raise ValueError(f"artifact payload contains an absolute path: {value}")


def _atomic_text(text: str, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            prefix=f".{destination.stem}-",
            suffix=destination.suffix,
            dir=destination.parent,
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(text)
        temporary.replace(destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return destination


def _atomic_artifact_json(payload: Mapping[str, Any], destination: Path) -> Path:
    safe = _strict_json_value(payload)
    _assert_no_absolute_path_strings(safe)
    rendered = json.dumps(safe, indent=2, sort_keys=True, allow_nan=False) + "\n"
    return _atomic_text(rendered, destination)


def _atomic_artifact_csv(frame: pd.DataFrame, destination: Path) -> Path:
    if frame.select_dtypes(include=[np.number]).isna().any().any():
        raise ValueError(f"numeric artifact columns contain missing values: {destination.name}")
    numeric = frame.select_dtypes(include=[np.number]).to_numpy(dtype=float)
    if numeric.size and not np.isfinite(numeric).all():
        raise ValueError(f"numeric artifact columns are non-finite: {destination.name}")
    return _atomic_text(frame.to_csv(index=False, lineterminator="\n"), destination)


def _artifact_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _portable_artifact_path(path: Path, project_root: Path) -> str:
    try:
        return path.resolve().relative_to(project_root).as_posix()
    except ValueError as exc:
        raise ValueError(f"equilibrium artifact is outside project_root: {path}") from exc


def _validate_equilibrium_artifact_result(result: EquilibriumBenchmarkResult) -> None:
    if not isinstance(result, EquilibriumBenchmarkResult):
        raise TypeError("result must be an EquilibriumBenchmarkResult")
    metadata = result.metadata
    expected_labels = {
        "evidence_type": EVIDENCE_TYPE,
        "causal_scope": CAUSAL_SCOPE,
        "empirical_calibration_status": EMPIRICAL_STATUS,
        "is_nyc_structural_estimate": False,
        "common_random_numbers": True,
    }
    for key, expected in expected_labels.items():
        if metadata.get(key) != expected:
            raise ValueError(f"equilibrium result has invalid {key}")
    state_id = metadata.get("state_id")
    if (
        not isinstance(state_id, str)
        or not state_id
        or metadata.get("control_state_id") != state_id
        or metadata.get("treatment_state_id") != state_id
    ):
        raise ValueError("equilibrium counterfactuals do not share one declared state")

    expected_zones: np.ndarray | None = None
    for scenario, outcome in (("control", result.control), ("treatment", result.treatment)):
        diagnostics = outcome.diagnostics
        if (
            not diagnostics.converged
            or not diagnostics.uniqueness_condition_satisfied
            or diagnostics.residual_sup_norm is None
            or diagnostics.residual_sup_norm > diagnostics.tolerance
        ):
            raise ValueError(f"{scenario} equilibrium is not convergence-certified")
        if outcome.metadata.get("state_id") != state_id:
            raise ValueError(f"{scenario} equilibrium state does not match benchmark state")
        panel = outcome.panel.sort_values("zone_id")
        zones = panel["zone_id"].to_numpy(dtype=int)
        if len(zones) == 0 or len(np.unique(zones)) != len(zones):
            raise ValueError(f"{scenario} equilibrium zones must be unique and nonempty")
        if expected_zones is None:
            expected_zones = zones
        elif not np.array_equal(zones, expected_zones):
            raise ValueError("control and treatment zone sets do not match")
        if set(panel["evidence_type"].astype(str)) != {EVIDENCE_TYPE}:
            raise ValueError(f"{scenario} panel has an invalid evidence label")
        if panel["state_id"].astype(str).nunique() != 1 or str(
            panel["state_id"].iloc[0]
        ) != state_id:
            raise ValueError(f"{scenario} panel does not preserve the shared state id")

    zone_effects = result.zone_effects.sort_values("zone_id")
    if expected_zones is None or not np.array_equal(
        zone_effects["zone_id"].to_numpy(dtype=int), expected_zones
    ):
        raise ValueError("zone effect rows do not match the solved counterfactual zones")
    if set(zone_effects["evidence_type"].astype(str)) != {EVIDENCE_TYPE}:
        raise ValueError("zone effects have an invalid evidence label")
    if set(zone_effects["state_id"].astype(str)) != {state_id}:
        raise ValueError("zone effects do not preserve the shared state id")

    scenarios = result.ledger["scenario"].astype(str)
    if len(scenarios) != 2 or set(scenarios) != {"control", "treatment"}:
        raise ValueError("equilibrium ledger must contain one control and one treatment row")
    if float(result.ledger["welfare_accounting_residual"].abs().max()) > 1e-8:
        raise ValueError("equilibrium welfare ledger does not balance")
    budget_diagnostics = metadata.get("budget_diagnostics")
    if not isinstance(budget_diagnostics, Mapping) or not budget_diagnostics.get(
        "budget_feasible"
    ):
        raise ValueError("equilibrium budget feasibility is not certified")

    trip_effect = float(zone_effects["trip_effect"].sum())
    welfare_effect = float(zone_effects["welfare_effect"].sum())
    treatment_spend = float(result.treatment.panel["treatment_spend"].sum())
    truth_checks = {
        "market_total_trip_effect": trip_effect,
        "market_total_welfare_effect": welfare_effect,
        "treatment_spend": treatment_spend,
    }
    for key, recomputed in truth_checks.items():
        declared = result.ground_truth.get(key)
        if declared is None or not np.isclose(float(declared), recomputed, atol=1e-10):
            raise ValueError(f"equilibrium ground truth failed recomputation: {key}")


def write_equilibrium_artifacts(
    result: EquilibriumBenchmarkResult,
    output_dir: str | Path,
    project_root: str | Path,
) -> EquilibriumArtifacts:
    """Atomically publish a portable, hash-manifested equilibrium evidence bundle.

    The conventional destination is ``artifacts/benchmarks/equilibrium`` beneath
    ``project_root``.  The function enforces containment rather than embedding an
    absolute machine-specific path.  A manifest is published last and an incomplete
    marker remains if any content write or validation fails.
    """

    _validate_equilibrium_artifact_result(result)
    root = Path(project_root).resolve()
    if not root.is_dir():
        raise ValueError("project_root must be an existing directory")
    output = Path(output_dir).resolve()
    _portable_artifact_path(output, root)
    output.mkdir(parents=True, exist_ok=True)

    summary_path = output / "summary.json"
    zone_effects_path = output / "zone_effects.csv"
    ledger_path = output / "ledger.csv"
    manifest_path = output / "manifest.json"
    marker_path = output / "EQUILIBRIUM_INCOMPLETE.json"
    manifest_path.unlink(missing_ok=True)
    _atomic_artifact_json(
        {"schema_version": 1, "status": "incomplete", "manifest_published": False},
        marker_path,
    )

    summary: dict[str, Any] = {
        "schema_version": 1,
        "evidence_type": EVIDENCE_TYPE,
        "causal_scope": CAUSAL_SCOPE,
        "ground_truth_status": result.metadata["ground_truth_status"],
        "empirical_calibration_status": EMPIRICAL_STATUS,
        "is_nyc_structural_estimate": False,
        "common_random_numbers": True,
        "simulation_seed": result.metadata["simulation_seed"],
        "state_id": result.metadata["state_id"],
        "treatment_version": result.metadata["treatment_version"],
        "planned_treatment_intensity": result.metadata["planned_treatment_intensity"],
        "realized_budget_scale": result.metadata["realized_budget_scale"],
        "cross_zone_channel": result.metadata["cross_zone_channel"],
        "ground_truth": dict(result.ground_truth),
        "equations": result.metadata["equations"],
        "uniqueness_diagnostics": result.metadata["uniqueness_diagnostics"],
        "control_diagnostics": result.control.diagnostics.to_dict(),
        "treatment_diagnostics": result.treatment.diagnostics.to_dict(),
        "budget_diagnostics": result.metadata["budget_diagnostics"],
        "configuration": result.control.metadata["configuration"],
        "limitations": result.metadata["limitations"],
    }
    _atomic_artifact_json(summary, summary_path)
    _atomic_artifact_csv(
        result.zone_effects.sort_values("zone_id").reset_index(drop=True),
        zone_effects_path,
    )
    _atomic_artifact_csv(
        result.ledger.sort_values("scenario").reset_index(drop=True), ledger_path
    )

    content_paths = (summary_path, zone_effects_path, ledger_path)
    entries = [
        {
            "path": _portable_artifact_path(path, root),
            "bytes": path.stat().st_size,
            "sha256": _artifact_sha256(path),
        }
        for path in sorted(content_paths)
    ]
    declared_file_set_sha256 = hashlib.sha256(
        json.dumps(entries, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "bundle_type": "two_sided_fixed_point_equilibrium_benchmark",
        "evidence_type": EVIDENCE_TYPE,
        "causal_scope": CAUSAL_SCOPE,
        "empirical_calibration_status": EMPIRICAL_STATUS,
        "is_nyc_structural_estimate": False,
        "portable_paths": True,
        "files": entries,
        "declared_file_set_sha256": declared_file_set_sha256,
        "metadata": {
            "simulation_seed": result.metadata["simulation_seed"],
            "state_id": result.metadata["state_id"],
            "treatment_version": result.metadata["treatment_version"],
            "common_random_numbers": True,
            "ground_truth_status": result.metadata["ground_truth_status"],
        },
        "checks": {
            "control_equilibrium_converged": True,
            "treatment_equilibrium_converged": True,
            "residuals_within_tolerance": True,
            "sufficient_uniqueness_condition_satisfied": True,
            "common_random_numbers_verified": True,
            "budget_feasible": True,
            "welfare_accounting_balanced": True,
            "ground_truth_recomputed": True,
            "hashes_recomputed": True,
        },
    }
    _atomic_artifact_json(manifest, manifest_path)
    marker_path.unlink(missing_ok=True)
    return EquilibriumArtifacts(
        summary_path=summary_path,
        zone_effects_path=zone_effects_path,
        ledger_path=ledger_path,
        manifest_path=manifest_path,
    )


__all__ = [
    "CAUSAL_SCOPE",
    "EMPIRICAL_STATUS",
    "EVIDENCE_TYPE",
    "EquilibriumBenchmarkResult",
    "EquilibriumArtifacts",
    "EquilibriumBudgetError",
    "EquilibriumConfig",
    "EquilibriumConvergenceError",
    "EquilibriumDiagnostics",
    "EquilibriumOutcome",
    "EquilibriumState",
    "draw_equilibrium_state",
    "run_equilibrium_benchmark",
    "solve_market_equilibrium",
    "write_equilibrium_artifacts",
]
