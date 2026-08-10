"""Pre-specified estimands and simulator ground-truth calculations.

An estimand is a causal contrast; an estimator is only a procedure used to learn it.
Keeping this registry separate prevents a convenient regression coefficient from
quietly becoming the scientific target.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import numpy as np
import pandas as pd

from .config import DesignName


class EstimandName(StrEnum):
    DIRECT = "direct_effect"
    CONTROLLED_ZONE_DIRECT = "controlled_zone_direct_effect"
    MARKET_TOTAL = "market_total_effect"
    SPILLOVER = "spillover_effect"
    SHORT_RUN = "short_run_effect"
    PERSISTENT = "persistent_effect"
    CUMULATIVE = "cumulative_effect"
    ITT = "intent_to_treat"
    TOT = "treatment_on_treated"
    TRIPS_PER_DOLLAR = "incremental_trips_per_dollar"
    WELFARE_PER_DOLLAR = "incremental_welfare_per_dollar"

    @classmethod
    def parse(cls, value: str | EstimandName) -> EstimandName:
        if isinstance(value, cls):
            return value
        normalized = str(value).strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "direct": cls.DIRECT.value,
            "controlled_zone_direct": cls.CONTROLLED_ZONE_DIRECT.value,
            "ate": cls.MARKET_TOTAL.value,
            "total": cls.MARKET_TOTAL.value,
            "market_total": cls.MARKET_TOTAL.value,
            "market_level_total": cls.MARKET_TOTAL.value,
            "market_level_total_effect": cls.MARKET_TOTAL.value,
            "spillover": cls.SPILLOVER.value,
            "short_run": cls.SHORT_RUN.value,
            "persistent": cls.PERSISTENT.value,
            "cumulative": cls.CUMULATIVE.value,
            "itt": cls.ITT.value,
            "tot": cls.TOT.value,
            "late": cls.TOT.value,
            "trips_per_dollar": cls.TRIPS_PER_DOLLAR.value,
            "welfare_per_dollar": cls.WELFARE_PER_DOLLAR.value,
        }
        try:
            return cls(aliases.get(normalized, normalized))
        except ValueError as exc:
            choices = ", ".join(item.value for item in cls)
            raise ValueError(f"unknown estimand {value!r}; choose one of: {choices}") from exc


@dataclass(frozen=True, slots=True)
class EstimandDefinition:
    """Human- and machine-readable causal target definition."""

    name: EstimandName
    label: str
    unit: str
    contrast: str
    identified_when: tuple[str, ...]
    not_identified_when: tuple[str, ...]
    compatible_designs: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name.value,
            "label": self.label,
            "unit": self.unit,
            "contrast": self.contrast,
            "identified_when": list(self.identified_when),
            "not_identified_when": list(self.not_identified_when),
            "compatible_designs": list(self.compatible_designs),
        }


ESTIMANDS: dict[EstimandName, EstimandDefinition] = {
    EstimandName.DIRECT: EstimandDefinition(
        EstimandName.DIRECT,
        "Individual direct effect",
        "eligible rider opportunity",
        "Individual outcome with own treatment versus own control at a fixed mapped exposure",
        (
            "own assignment is randomized",
            "the relevant neighbor and lag exposure is measured or absent",
            "consistency holds for the specified treatment intensity",
        ),
        (
            "unmapped interference changes outcomes",
            "assignment affects who enters the observed sample",
        ),
        ("individual",),
    ),
    EstimandName.MARKET_TOTAL: EstimandDefinition(
        EstimandName.MARKET_TOTAL,
        "Market-level total effect",
        "configured zone-time marketplace horizon",
        (
            "Mean zone-period outcome under the feasible all-zone policy versus all-zero "
            "over the fixed configured horizon, including modeled direct, "
            "cross-zone, and congestion pathways"
        ),
        (
            "policy schedules or sufficiently isolated market clusters are randomized",
            "cross-cluster interference is absent, bounded, or included in the target",
        ),
        ("only individuals within a connected market are randomized",),
        ("geo_cluster", "time_block", "switchback", "geo_time"),
    ),
    EstimandName.CONTROLLED_ZONE_DIRECT: EstimandDefinition(
        EstimandName.CONTROLLED_ZONE_DIRECT,
        "Controlled own-zone saturation effect",
        "zone-time marketplace cell",
        (
            "Outcome with the focal zone treated at the configured saturation versus "
            "focal-zone control while mapped neighbors are held at zero"
        ),
        (
            "zone assignment or saturation is randomized",
            "mapped neighbor exposure and policy horizon are fixed",
        ),
        ("only aggregate outcomes are observed but the claim is interpreted as individual",),
        ("geo_cluster", "geo_time"),
    ),
    EstimandName.SPILLOVER: EstimandDefinition(
        EstimandName.SPILLOVER,
        "Spillover effect",
        "untreated or fixed-own-treatment market cell",
        "Neighbor exposure versus no neighbor exposure at fixed own treatment",
        (
            "assignment induces independent variation in mapped neighbor exposure",
            "the exposure mapping is pre-specified",
        ),
        ("neighbor exposure is perfectly collinear with own treatment",),
        ("individual", "geo_time"),
    ),
    EstimandName.SHORT_RUN: EstimandDefinition(
        EstimandName.SHORT_RUN,
        "Short-run effect",
        "zone-time marketplace",
        (
            "Mean all-zone policy versus all-zero over the fixed configured horizon with "
            "the persistence state disabled"
        ),
        ("current assignment varies independently of prior exposure",),
        ("all treated observations follow treated histories",),
        ("time_block", "switchback", "geo_time"),
    ),
    EstimandName.PERSISTENT: EstimandDefinition(
        EstimandName.PERSISTENT,
        "Persistent effect",
        "zone-time marketplace",
        "Full-policy total effect minus the same policy effect with persistence disabled",
        (
            "treatment histories vary",
            "carryover horizon or state transition is specified",
        ),
        ("the experiment is shorter than the relevant carryover horizon",),
        ("switchback", "geo_time", "time_block"),
    ),
    EstimandName.CUMULATIVE: EstimandDefinition(
        EstimandName.CUMULATIVE,
        "Cumulative market effect",
        "experiment horizon",
        "Sum of full-policy-versus-zero outcome differences over the full decision horizon",
        ("the evaluation horizon is fixed before analysis",),
        ("post-experiment displacement outside the horizon is ignored",),
        ("geo_cluster", "time_block", "switchback", "geo_time"),
    ),
    EstimandName.ITT: EstimandDefinition(
        EstimandName.ITT,
        "Intent-to-treat effect",
        "assigned market cell",
        "Assignment to an encouragement schedule versus assignment to control",
        ("assignment is randomized and analyzed as assigned",),
        ("post-randomization exposure replaces assignment without adjustment",),
        ("individual", "geo_cluster", "time_block", "switchback", "geo_time"),
    ),
    EstimandName.TOT: EstimandDefinition(
        EstimandName.TOT,
        "Treatment-on-the-treated effect",
        "exposed complier-equivalent unit",
        "ITT divided by the assignment-induced exposure first stage",
        (
            "assignment is a valid instrument",
            "exclusion, monotonicity, and a nonzero first stage hold",
        ),
        ("assignment affects outcomes through channels other than received treatment",),
        ("individual", "geo_cluster", "time_block", "switchback", "geo_time"),
    ),
    EstimandName.TRIPS_PER_DOLLAR: EstimandDefinition(
        EstimandName.TRIPS_PER_DOLLAR,
        "Incremental trips per dollar",
        "experiment or policy horizon",
        "Full-horizon incremental served trips divided by feasible full-policy spend",
        ("incremental trips and all treatment costs are measured on the same horizon",),
        ("zero spend or omitted operational costs",),
        ("individual", "geo_cluster", "time_block", "switchback", "geo_time"),
    ),
    EstimandName.WELFARE_PER_DOLLAR: EstimandDefinition(
        EstimandName.WELFARE_PER_DOLLAR,
        "Incremental welfare per dollar",
        "experiment or policy horizon",
        "Full-horizon modeled welfare gain divided by feasible full-policy spend",
        ("the welfare function and transfer treatment are pre-specified",),
        ("unmeasured externalities or distributional weights are decision relevant",),
        ("individual", "geo_cluster", "time_block", "switchback", "geo_time"),
    ),
}


def get_estimand(name: str | EstimandName) -> EstimandDefinition:
    """Return a pre-specified estimand definition."""

    return ESTIMANDS[EstimandName.parse(name)]


def list_estimands() -> list[dict[str, Any]]:
    """Return serializable definitions for a dashboard or report."""

    return [definition.to_dict() for definition in ESTIMANDS.values()]


def identification_assessment(
    name: str | EstimandName,
    *,
    design: str,
    interference_present: bool,
    exposure_mapped: bool = False,
    histories_observed: bool = True,
    first_stage: float | None = None,
) -> tuple[bool, tuple[str, ...]]:
    """Apply a conservative, explicit identification screen.

    This is a guardrail rather than a proof.  A ``True`` result says the supplied
    design metadata does not immediately contradict the estimand's core conditions.
    """

    target = EstimandName.parse(name)
    normalized_design = DesignName.parse(design).value
    reasons: list[str] = []
    definition = get_estimand(target)
    if normalized_design not in set(definition.compatible_designs):
        reasons.append(
            f"{normalized_design} assignment is not compatible with {target.value}"
        )
    if (
        target in {EstimandName.DIRECT, EstimandName.CONTROLLED_ZONE_DIRECT}
        and interference_present
        and not exposure_mapped
    ):
        reasons.append("direct effects require a mapped neighbor exposure under interference")
    if (
        target is EstimandName.MARKET_TOTAL
        and normalized_design in {"individual", "geo_cluster"}
        and interference_present
        and not exposure_mapped
    ):
        reasons.append(
            f"{normalized_design} assignment within one connected market does not isolate "
            "the all-zone total effect under unmapped cross-arm interference"
        )
    if target is EstimandName.SPILLOVER and not exposure_mapped:
        reasons.append("spillover effects require a pre-specified exposure mapping")
    if target in {EstimandName.SHORT_RUN, EstimandName.PERSISTENT} and not histories_observed:
        reasons.append("temporal effects require observed assignment histories")
    if target is EstimandName.TOT and (first_stage is None or abs(first_stage) < 1e-8):
        reasons.append("treatment-on-treated requires a nonzero exposure first stage")
    return not reasons, tuple(reasons)


Estimand = EstimandDefinition


@dataclass(frozen=True)
class GroundTruth(Mapping[str, float]):
    """Scalar targets plus row-level structural counterfactual contrasts."""

    effects: Mapping[str, float]
    unit_effects: pd.DataFrame
    evidence_type: str = "semi_synthetic_known_ground_truth"

    def __getitem__(self, key: str | EstimandName) -> float:
        normalized = key.value if isinstance(key, EstimandName) else str(key)
        return float(self.effects[normalized])

    def __iter__(self) -> Iterator[str]:
        return iter(self.effects)

    def __len__(self) -> int:
        return len(self.effects)

    def get(self, key: str | EstimandName, default: float | None = None) -> float | None:
        normalized = key.value if isinstance(key, EstimandName) else str(key)
        value = self.effects.get(normalized, default)
        return None if value is None else float(value)

    def to_dict(self) -> dict[str, float]:
        return {key: float(value) for key, value in self.effects.items()}

    def to_json_dict(self) -> dict[str, float | None]:
        """Return strict-JSON-safe truth metadata (unavailable targets become null)."""

        return {
            key: (float(value) if np.isfinite(value) else None)
            for key, value in self.effects.items()
        }

    @property
    def market_total_effect(self) -> float:
        return self[EstimandName.MARKET_TOTAL]


def _array(frame: pd.DataFrame, column: str) -> np.ndarray:
    if column not in frame:
        raise ValueError(f"counterfactual frame missing {column!r}")
    values = frame[column].to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise ValueError(f"counterfactual column {column!r} must be finite")
    return values


def compute_ground_truth(
    observed: pd.DataFrame,
    control: pd.DataFrame,
    *,
    direct_only: pd.DataFrame | None = None,
    short_run: pd.DataFrame | None = None,
    all_treated: pd.DataFrame | None = None,
    all_treated_short_run: pd.DataFrame | None = None,
    controlled_direct_effects: np.ndarray | pd.Series | None = None,
    controlled_spillover_effects: np.ndarray | pd.Series | None = None,
    all_treated_received: np.ndarray | pd.Series | None = None,
    analysis_eligible: np.ndarray | pd.Series | None = None,
    assignment_itt_effects: np.ndarray | pd.Series | None = None,
    assignment_first_stage: float | None = None,
    individual_direct_effects: np.ndarray | pd.Series | None = None,
    assigned_treatment: np.ndarray | pd.Series | None = None,
    received_treatment: np.ndarray | pd.Series | None = None,
    outcome: str = "trips",
    cost: str = "treatment_cost",
    welfare: str = "welfare",
) -> GroundTruth:
    """Calculate named truths from structural paths sharing exogenous shocks."""

    if len(observed) != len(control):
        raise ValueError("observed and control paths must have the same length")
    y = _array(observed, outcome)
    y0 = _array(control, outcome)
    realized_total = y - y0
    realized_mechanism_direct = (
        _array(direct_only, outcome) - y0
        if direct_only is not None
        else realized_total.copy()
    )
    realized_mechanism_spillover = realized_total - realized_mechanism_direct
    realized_short = (
        _array(short_run, outcome) - y0 if short_run is not None else realized_total.copy()
    )
    realized_persistent = realized_total - realized_short

    full_policy_effect = (
        _array(all_treated, outcome) - y0 if all_treated is not None else realized_total.copy()
    )
    full_policy_short = (
        _array(all_treated_short_run, outcome) - y0
        if all_treated_short_run is not None
        else full_policy_effect.copy()
    )
    full_policy_persistent = full_policy_effect - full_policy_short
    controlled_direct = (
        np.asarray(controlled_direct_effects, dtype=float)
        if controlled_direct_effects is not None
        else realized_mechanism_direct.copy()
    )
    controlled_spillover = (
        np.asarray(controlled_spillover_effects, dtype=float)
        if controlled_spillover_effects is not None
        else realized_mechanism_spillover.copy()
    )
    for name, values_array in {
        "controlled_direct_effects": controlled_direct,
        "controlled_spillover_effects": controlled_spillover,
    }.items():
        if values_array.shape != y.shape or not np.isfinite(values_array).all():
            raise ValueError(f"{name} must be finite and align with counterfactual rows")
    if individual_direct_effects is None:
        individual_direct = np.full(len(observed), np.nan)
    else:
        individual_direct = np.asarray(individual_direct_effects, dtype=float)
        if individual_direct.shape != y.shape or not np.isfinite(individual_direct).all():
            raise ValueError("individual_direct_effects must be finite and align with rows")

    if analysis_eligible is None:
        analysis_mask = np.ones(len(observed), dtype=bool)
    else:
        analysis_mask = np.asarray(analysis_eligible, dtype=bool)
        if analysis_mask.shape != y.shape:
            raise ValueError("analysis_eligible must align with counterfactual rows")
        if not analysis_mask.any():
            raise ValueError("analysis_eligible must retain at least one row")

    assignment = (
        np.asarray(assigned_treatment, dtype=float)
        if assigned_treatment is not None
        else np.ones(len(observed), dtype=float)
    )
    received = (
        np.asarray(received_treatment, dtype=float)
        if received_treatment is not None
        else assignment.copy()
    )
    if assignment.shape != y.shape or received.shape != y.shape:
        raise ValueError("assignment and received treatment must align with counterfactual rows")
    assigned_mask = (assignment > 0) & analysis_mask
    realized_assigned_effect = (
        float(np.mean(realized_total[assigned_mask])) if assigned_mask.any() else 0.0
    )
    if all_treated_received is not None:
        full_policy_received = np.asarray(all_treated_received, dtype=float)
        if full_policy_received.shape != y.shape:
            raise ValueError("all_treated_received must align with counterfactual rows")
        full_policy_mean_exposure = float(np.mean(full_policy_received))
    else:
        full_policy_mean_exposure = (
            1.0 if all_treated is not None else float(np.mean(received))
        )
    if assignment_itt_effects is None:
        # A within-market assignment coefficient is generally not the all-policy
        # contrast under interference, carryover, or a shared budget. Leave ITT
        # unavailable rather than relabeling a different structural contrast.
        itt = float("nan")
        first_stage = float("nan")
    else:
        itt_effects = np.asarray(assignment_itt_effects, dtype=float)
        if itt_effects.shape != y.shape or not np.isfinite(itt_effects).all():
            raise ValueError("assignment_itt_effects must be finite and align with rows")
        if assignment_first_stage is None or not np.isfinite(assignment_first_stage):
            raise ValueError("assignment_first_stage is required with assignment_itt_effects")
        itt = float(np.mean(itt_effects))
        first_stage = float(assignment_first_stage)
    tot = itt / first_stage if first_stage > 1e-12 else float("nan")

    policy_frame = all_treated if all_treated is not None else observed
    spend = float(_array(policy_frame, cost).sum()) if cost in policy_frame else 0.0
    incremental_trips = float(full_policy_effect.sum())
    if welfare in policy_frame and welfare in control:
        incremental_welfare = float(
            (_array(policy_frame, welfare) - _array(control, welfare)).sum()
        )
    else:
        incremental_welfare = float("nan")

    values: dict[str, float] = {
        EstimandName.DIRECT.value: (
            float(np.mean(individual_direct[analysis_mask]))
            if np.isfinite(individual_direct[analysis_mask]).all()
            else float("nan")
        ),
        EstimandName.CONTROLLED_ZONE_DIRECT.value: float(np.mean(controlled_direct)),
        # The canonical total effect is the market-wide policy contrast, which is
        # the quantity a between-market experiment estimates in the no-interference
        # case.  The realized mixed schedule is reported separately below.
        EstimandName.MARKET_TOTAL.value: float(np.mean(full_policy_effect)),
        EstimandName.SPILLOVER.value: float(np.mean(controlled_spillover)),
        EstimandName.SHORT_RUN.value: float(np.mean(full_policy_short)),
        EstimandName.PERSISTENT.value: float(np.mean(full_policy_persistent)),
        EstimandName.CUMULATIVE.value: incremental_trips,
        EstimandName.ITT.value: itt,
        EstimandName.TOT.value: float(tot),
        EstimandName.TRIPS_PER_DOLLAR.value: (
            incremental_trips / spend if spend > 1e-12 else float("nan")
        ),
        EstimandName.WELFARE_PER_DOLLAR.value: (
            incremental_welfare / spend if spend > 1e-12 else float("nan")
        ),
        "first_stage": first_stage,
        "assignment_first_stage": first_stage,
        "itt_available": float(np.isfinite(itt)),
        "full_policy_mean_exposure": full_policy_mean_exposure,
        "full_policy_spend": spend,
        "incremental_trips": incremental_trips,
        "incremental_welfare": incremental_welfare,
        "full_horizon_incremental_trips": incremental_trips,
        "full_horizon_incremental_welfare": incremental_welfare,
        "analysis_rows": float(analysis_mask.sum()),
        "analysis_share": float(analysis_mask.mean()),
        "analysis_population_market_total_effect": float(
            np.mean(full_policy_effect[analysis_mask])
        ),
        "analysis_population_controlled_zone_direct_effect": float(
            np.mean(controlled_direct[analysis_mask])
        ),
        "analysis_population_spillover_effect": float(
            np.mean(controlled_spillover[analysis_mask])
        ),
        "analysis_population_short_run_effect": float(
            np.mean(full_policy_short[analysis_mask])
        ),
        "analysis_population_persistent_effect": float(
            np.mean(full_policy_persistent[analysis_mask])
        ),
        "full_horizon_market_total_effect": float(np.mean(full_policy_effect)),
        "analysis_horizon_cumulative_effect": float(full_policy_effect[analysis_mask].sum()),
        "realized_schedule_mean_effect": float(np.mean(realized_total)),
        "realized_schedule_cumulative_effect": float(realized_total.sum()),
        "realized_schedule_assigned_mean_effect": realized_assigned_effect,
        "realized_schedule_mechanism_direct_component": float(
            np.mean(realized_mechanism_direct)
        ),
        "realized_schedule_mechanism_spillover_component": float(
            np.mean(realized_mechanism_spillover)
        ),
        "realized_schedule_short_run_component": float(np.mean(realized_short)),
        "realized_schedule_persistent_component": float(np.mean(realized_persistent)),
    }
    if all_treated is not None:
        values["all_treated_market_total_effect"] = float(np.mean(full_policy_effect))
        values["average_treatment_effect"] = float(np.mean(full_policy_effect))

    identifiers = [column for column in ("unit_id", "zone_id", "period_id") if column in observed]
    unit_effects = observed[identifiers].copy()
    unit_effects["y0"] = y0
    unit_effects["y_observed"] = y
    unit_effects["realized_schedule_effect"] = realized_total
    unit_effects["full_policy_total_effect"] = full_policy_effect
    unit_effects["individual_direct_effect"] = individual_direct
    unit_effects["controlled_direct_effect"] = controlled_direct
    unit_effects["controlled_spillover_effect"] = controlled_spillover
    unit_effects["full_policy_short_run_effect"] = full_policy_short
    unit_effects["full_policy_persistent_effect"] = full_policy_persistent
    return GroundTruth(effects=values, unit_effects=unit_effects)
