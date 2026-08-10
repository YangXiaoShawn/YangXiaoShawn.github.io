"""Typed, serializable configuration for the causal marketplace lab.

The configuration objects intentionally contain assumptions, not results.  They can
be created directly in Python or loaded from YAML without requiring a global config
singleton, which keeps simulations and Monte Carlo runs reproducible.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field, fields
from enum import Enum, StrEnum
from math import isfinite
from numbers import Integral, Real
from pathlib import Path
from typing import Any, ClassVar, Self, get_type_hints

import yaml


class DesignName(StrEnum):
    """Supported assignment mechanisms."""

    INDIVIDUAL = "individual"
    GEO_CLUSTER = "geo_cluster"
    TIME_BLOCK = "time_block"
    SWITCHBACK = "switchback"
    GEO_TIME = "geo_time"

    @classmethod
    def parse(cls, value: str | DesignName) -> DesignName:
        if isinstance(value, cls):
            return value
        normalized = str(value).strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "geo": cls.GEO_CLUSTER.value,
            "geographic": cls.GEO_CLUSTER.value,
            "geographic_cluster": cls.GEO_CLUSTER.value,
            "cluster": cls.GEO_CLUSTER.value,
            "time": cls.TIME_BLOCK.value,
            "temporal": cls.TIME_BLOCK.value,
            "geo_x_time": cls.GEO_TIME.value,
            "geo_by_time": cls.GEO_TIME.value,
            "geotime": cls.GEO_TIME.value,
            "geo_time_clustered": cls.GEO_TIME.value,
        }
        try:
            return cls(aliases.get(normalized, normalized))
        except ValueError as exc:
            choices = ", ".join(member.value for member in cls)
            raise ValueError(f"unknown design {value!r}; choose one of: {choices}") from exc


class TreatmentVersion(StrEnum):
    """Supported marketplace intervention versions."""

    RIDER_DISCOUNT = "rider_discount"
    DRIVER_INCENTIVE = "driver_incentive"
    BUNDLED = "bundled"

    @classmethod
    def parse(cls, value: str | TreatmentVersion) -> TreatmentVersion:
        if isinstance(value, cls):
            return value
        normalized = str(value).strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "rider": cls.RIDER_DISCOUNT.value,
            "discount": cls.RIDER_DISCOUNT.value,
            "rider_only": cls.RIDER_DISCOUNT.value,
            "driver": cls.DRIVER_INCENTIVE.value,
            "incentive": cls.DRIVER_INCENTIVE.value,
            "driver_only": cls.DRIVER_INCENTIVE.value,
            "both": cls.BUNDLED.value,
            "bundle": cls.BUNDLED.value,
        }
        try:
            return cls(aliases.get(normalized, normalized))
        except ValueError as exc:
            choices = ", ".join(member.value for member in cls)
            raise ValueError(
                f"unknown treatment version {value!r}; choose one of: {choices}"
            ) from exc


class _ConfigMixin:
    """Small dataclass serialization helper used by all public configs."""

    _ALIASES: ClassVar[Mapping[str, str]] = {}

    @classmethod
    def from_dict(cls, values: Mapping[str, Any]) -> Self:
        if not isinstance(values, Mapping):
            raise TypeError(f"{cls.__name__}.from_dict expects a mapping")
        known = {item.name for item in fields(cls) if item.init}
        normalized: dict[str, Any] = {}
        for raw_key, value in values.items():
            key = cls._ALIASES.get(str(raw_key), str(raw_key))
            if key not in known:
                raise ValueError(f"unknown {cls.__name__} field: {raw_key!r}")
            normalized[key] = value

        hints = get_type_hints(cls)
        if "design" in normalized and isinstance(normalized["design"], Mapping):
            normalized["design"] = DesignConfig.from_dict(normalized["design"])
        if "name" in normalized and hints.get("name") in {DesignName, "DesignName"}:
            normalized["name"] = DesignName.parse(normalized["name"])
        if "treatment_version" in normalized:
            normalized["treatment_version"] = TreatmentVersion.parse(
                normalized["treatment_version"]
            )
        if "covariates" in normalized and isinstance(normalized["covariates"], list):
            normalized["covariates"] = tuple(str(item) for item in normalized["covariates"])
        return cls(**normalized)

    @classmethod
    def from_yaml(cls, path: str | Path, *, section: str | None = None) -> Self:
        source = Path(path)
        payload = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
        if not isinstance(payload, Mapping):
            raise ValueError(f"YAML root in {source} must be a mapping")
        if section is not None:
            try:
                payload = payload[section]
            except KeyError as exc:
                raise ValueError(f"YAML file {source} has no {section!r} section") from exc
            if not isinstance(payload, Mapping):
                raise ValueError(f"YAML section {section!r} must be a mapping")
        return cls.from_dict(payload)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key, value in tuple(payload.items()):
            if isinstance(value, Enum):
                payload[key] = value.value
        if isinstance(payload.get("design"), dict):
            name = payload["design"].get("name")
            if isinstance(name, Enum):
                payload["design"]["name"] = name.value
        return payload


@dataclass(frozen=True, slots=True)
class DesignConfig(_ConfigMixin):
    """Assignment settings shared by design generators and the simulator.

    ``treatment_probability`` controls assignment to the treatment arm.
    ``treatment_saturation`` controls the exposure intensity inside treated arms.
    They are separate so partial-saturation experiments remain explicit.
    """

    name: DesignName = DesignName.GEO_CLUSTER
    treatment_probability: float = 0.5
    treatment_saturation: float = 1.0
    n_clusters: int | None = None
    cluster_size: int = 1
    treatment_duration: int = 4
    washout_periods: int = 0
    budget: float | None = None
    seed: int | None = None

    _ALIASES: ClassVar[Mapping[str, str]] = {
        "design": "name",
        "design_name": "name",
        "randomization_unit": "name",
        "probability": "treatment_probability",
        "treatment_share": "treatment_probability",
        "saturation": "treatment_saturation",
        "block_length": "treatment_duration",
        "washout": "washout_periods",
    }

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", DesignName.parse(self.name))
        numeric_values = {
            "treatment_probability": self.treatment_probability,
            "treatment_saturation": self.treatment_saturation,
        }
        if self.budget is not None:
            numeric_values["budget"] = self.budget
        for name, value in numeric_values.items():
            if not isinstance(value, Real) or not isfinite(float(value)):
                raise ValueError(f"{name} must be a finite number")
        integer_values = {
            "cluster_size": self.cluster_size,
            "treatment_duration": self.treatment_duration,
            "washout_periods": self.washout_periods,
        }
        if self.n_clusters is not None:
            integer_values["n_clusters"] = self.n_clusters
        if self.seed is not None:
            integer_values["seed"] = self.seed
        for name, value in integer_values.items():
            if isinstance(value, bool) or not isinstance(value, Integral):
                raise ValueError(f"{name} must be an integer")
        if not 0 < self.treatment_probability < 1:
            raise ValueError("treatment_probability must be strictly between 0 and 1")
        if not 0 <= self.treatment_saturation <= 1:
            raise ValueError("treatment_saturation must lie in [0, 1]")
        if self.n_clusters is not None and self.n_clusters < 1:
            raise ValueError("n_clusters must be positive when supplied")
        if self.cluster_size < 1:
            raise ValueError("cluster_size must be positive")
        if self.treatment_duration < 1:
            raise ValueError("treatment_duration must be positive")
        if self.washout_periods < 0:
            raise ValueError("washout_periods cannot be negative")
        if self.washout_periods >= self.treatment_duration:
            raise ValueError("washout_periods must be shorter than treatment_duration")
        if self.budget is not None and self.budget < 0:
            raise ValueError("budget cannot be negative")


@dataclass(frozen=True, slots=True)
class SimulationConfig(_ConfigMixin):
    """Structural assumptions for a deterministic semi-synthetic market.

    Effects are log changes in latent demand or available supply.  Monetary fields
    are expressed in arbitrary but internally consistent currency units.  The model
    is deliberately compact enough for a laptop while retaining congestion,
    cross-zone movement, temporal persistence, and a binding-spend mechanism.
    A common assignment intensity scales the selected treatment version: rider
    discount, driver incentive, or their bundle. This makes the intervention version
    explicit while retaining a single binary/partial-saturation arm per experiment.
    """

    n_zones: int = 4
    n_periods: int = 48
    periods_per_day: int = 24
    individuals_per_cell: int = 100
    base_demand: float = 80.0
    base_supply: float = 62.0
    capacity_per_driver: float = 1.35
    matching_efficiency: float = 0.94
    base_fare: float = 18.0
    rider_value: float = 28.0
    operating_cost_per_trip: float = 8.0
    base_wait_minutes: float = 5.0
    wait_disutility_per_minute: float = 0.25
    treatment_version: TreatmentVersion = TreatmentVersion.BUNDLED
    discount_rate: float = 0.10
    incentive_per_driver: float = 1.50
    reference_incentive_per_driver: float = 1.50
    direct_demand_effect: float = 0.16
    direct_supply_effect: float = 0.10
    spillover_strength: float = 0.0
    persistence: float = 0.0
    rider_substitution: float = 0.04
    driver_mobility: float = 0.06
    zone_heterogeneity_sd: float = 0.12
    demand_noise_sd: float = 0.06
    supply_noise_sd: float = 0.05
    time_pattern_strength: float = 0.22
    budget: float | None = None
    seed: int = 202503
    design: DesignConfig = field(default_factory=DesignConfig)

    _ALIASES: ClassVar[Mapping[str, str]] = {
        "zones": "n_zones",
        "periods": "n_periods",
        "n_times": "n_periods",
        "riders_per_cell": "individuals_per_cell",
        "driver_incentive": "incentive_per_driver",
        "incentive": "incentive_per_driver",
        "discount": "discount_rate",
        "demand_effect": "direct_demand_effect",
        "supply_effect": "direct_supply_effect",
        "interference": "spillover_strength",
        "persistence_rate": "persistence",
        "driver_movement": "driver_mobility",
        "random_seed": "seed",
    }

    def __post_init__(self) -> None:
        if isinstance(self.design, Mapping):
            object.__setattr__(self, "design", DesignConfig.from_dict(self.design))
        object.__setattr__(
            self,
            "treatment_version",
            TreatmentVersion.parse(self.treatment_version),
        )
        positive_ints = {
            "n_zones": self.n_zones,
            "n_periods": self.n_periods,
            "periods_per_day": self.periods_per_day,
            "individuals_per_cell": self.individuals_per_cell,
        }
        for name, value in positive_ints.items():
            if isinstance(value, bool) or not isinstance(value, Integral):
                raise ValueError(f"{name} must be an integer")
            if value < 1:
                raise ValueError(f"{name} must be positive")
        if isinstance(self.seed, bool) or not isinstance(self.seed, Integral):
            raise ValueError("seed must be an integer")
        numeric_values = {
            item.name: getattr(self, item.name)
            for item in fields(self)
            if item.init
            and item.name not in {*positive_ints, "seed", "design", "treatment_version"}
        }
        for name, value in numeric_values.items():
            if value is not None and (
                not isinstance(value, Real) or not isfinite(float(value))
            ):
                raise ValueError(f"{name} must be a finite number")
        positive = {
            "base_demand": self.base_demand,
            "base_supply": self.base_supply,
            "capacity_per_driver": self.capacity_per_driver,
            "matching_efficiency": self.matching_efficiency,
            "base_fare": self.base_fare,
            "rider_value": self.rider_value,
            "base_wait_minutes": self.base_wait_minutes,
            "reference_incentive_per_driver": self.reference_incentive_per_driver,
        }
        for name, value in positive.items():
            if value <= 0:
                raise ValueError(f"{name} must be positive")
        nonnegative = {
            "operating_cost_per_trip": self.operating_cost_per_trip,
            "wait_disutility_per_minute": self.wait_disutility_per_minute,
            "incentive_per_driver": self.incentive_per_driver,
            "spillover_strength": self.spillover_strength,
            "persistence": self.persistence,
            "rider_substitution": self.rider_substitution,
            "driver_mobility": self.driver_mobility,
            "zone_heterogeneity_sd": self.zone_heterogeneity_sd,
            "demand_noise_sd": self.demand_noise_sd,
            "supply_noise_sd": self.supply_noise_sd,
            "time_pattern_strength": self.time_pattern_strength,
        }
        for name, value in nonnegative.items():
            if value < 0:
                raise ValueError(f"{name} cannot be negative")
        if not 0 < self.matching_efficiency <= 1:
            raise ValueError("matching_efficiency must lie in (0, 1]")
        if not 0 <= self.discount_rate <= 1:
            raise ValueError("discount_rate must lie in [0, 1]")
        if not 0 <= self.persistence < 1:
            raise ValueError("persistence must lie in [0, 1)")
        if self.budget is not None and self.budget < 0:
            raise ValueError("budget cannot be negative")

    @property
    def effective_budget(self) -> float | None:
        """Simulation-level budget takes precedence over the design budget."""

        return self.budget if self.budget is not None else self.design.budget


# Common names retained as explicit aliases for a compact public API.
MarketConfig = SimulationConfig
SimulatorConfig = SimulationConfig


@dataclass(frozen=True, slots=True)
class EstimatorConfig(_ConfigMixin):
    """Configuration for the transparent estimator dispatcher."""

    method: str = "difference_in_means"
    outcome: str = "outcome"
    treatment: str = "assigned_treatment"
    covariates: tuple[str, ...] = ()
    cluster: str | None = None
    unit: str | None = None
    time: str | None = None
    post: str | None = None
    propensity: str | None = None
    target_estimand: str = "intent_to_treat"
    alpha: float = 0.05
    filter_eligible: bool = True
    crossfit_folds: int = 2
    seed: int = 202503

    _ALIASES: ClassVar[Mapping[str, str]] = {
        "estimator": "method",
        "outcome_col": "outcome",
        "treatment_col": "treatment",
        "cluster_col": "cluster",
        "unit_col": "unit",
        "time_col": "time",
        "post_col": "post",
        "estimand": "target_estimand",
    }

    def __post_init__(self) -> None:
        object.__setattr__(self, "covariates", tuple(self.covariates))
        if not isinstance(self.alpha, Real) or not isfinite(float(self.alpha)):
            raise ValueError("alpha must be a finite number")
        for name, value in {"crossfit_folds": self.crossfit_folds, "seed": self.seed}.items():
            if isinstance(value, bool) or not isinstance(value, Integral):
                raise ValueError(f"{name} must be an integer")
        if not self.method.strip():
            raise ValueError("method cannot be empty")
        if not self.outcome or not self.treatment:
            raise ValueError("outcome and treatment column names are required")
        if not 0 < self.alpha < 1:
            raise ValueError("alpha must lie in (0, 1)")
        if self.crossfit_folds < 2:
            raise ValueError("crossfit_folds must be at least 2")


def load_simulation_config(path: str | Path, *, section: str | None = None) -> SimulationConfig:
    """Load a simulation config, accepting a conventional ``simulation`` section."""

    source = Path(path)
    payload = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, Mapping):
        raise ValueError(f"YAML root in {source} must be a mapping")
    if section is not None:
        payload = payload.get(section, {})
    elif "simulation" in payload:
        payload = payload["simulation"]
    if not isinstance(payload, Mapping):
        raise ValueError("simulation configuration must be a mapping")
    return SimulationConfig.from_dict(payload)
