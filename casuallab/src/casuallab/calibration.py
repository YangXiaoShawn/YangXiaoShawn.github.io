"""Illustrative simulator scale anchoring from a descriptive real-data panel."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from casuallab.config import SimulationConfig


@dataclass(frozen=True)
class CalibrationResult:
    """Calibrated config plus an audit trail of empirical and assumed quantities."""

    config: SimulationConfig
    empirical_targets: dict[str, float | int | None]
    unchanged_structural_assumptions: tuple[str, ...]
    evidence_type: str = "illustrative_empirical_scale_anchor"

    def to_dict(self) -> dict[str, object]:
        return {
            "evidence_type": self.evidence_type,
            "empirical_targets": self.empirical_targets,
            "unchanged_structural_assumptions": list(self.unchanged_structural_assumptions),
            "simulation_config": self.config.to_dict(),
            "warning": (
                "This stratified engineering fixture anchors scale but is not representative "
                "of city market intensity. It does not identify structural price, incentive, "
                "interference, substitution, or persistence parameters."
            ),
        }


def _to_pandas(frame: Any) -> pd.DataFrame:
    if isinstance(frame, pd.DataFrame):
        return frame.copy()
    if hasattr(frame, "to_pandas"):
        return frame.to_pandas()
    raise TypeError("expected a pandas or Polars DataFrame")


def _find(frame: pd.DataFrame, candidates: tuple[str, ...]) -> str | None:
    return next((column for column in candidates if column in frame.columns), None)


def _finite_mean(frame: pd.DataFrame, column: str | None) -> float | None:
    if column is None:
        return None
    values = pd.to_numeric(frame[column], errors="coerce")
    result = float(values.mean())
    return result if np.isfinite(result) else None


def _finite_weighted_mean(
    frame: pd.DataFrame,
    column: str | None,
    weight_column: str,
) -> float | None:
    if column is None:
        return None
    values = pd.to_numeric(frame[column], errors="coerce")
    weights = pd.to_numeric(frame[weight_column], errors="coerce")
    valid = values.notna() & weights.notna() & (weights > 0)
    if not valid.any():
        return None
    result = float(np.average(values.loc[valid], weights=weights.loc[valid]))
    return result if np.isfinite(result) else None


def calibrate_simulation(
    panel: Any,
    template: SimulationConfig | None = None,
) -> CalibrationResult:
    """Anchor baseline scale and fare while preserving causal assumptions.

    The public panel can provide observed trip and fare scale anchors. It cannot identify
    latent requests, available drivers, demand response, supply response, spillovers,
    persistence, substitution, or welfare, so those values remain config assumptions.
    """

    frame = _to_pandas(panel)
    if frame.empty:
        raise ValueError("calibration panel must not be empty")
    base = template or SimulationConfig()
    demand_column = _find(frame, ("trip_count", "completed_trips", "demand", "outcome"))
    if demand_column is None:
        raise ValueError("panel has no trip-count column for calibration")
    fare_column = _find(frame, ("average_fare", "avg_fare", "mean_fare", "fare"))
    duration_column = _find(
        frame,
        ("average_trip_seconds", "avg_trip_seconds", "mean_trip_seconds", "trip_seconds"),
    )
    distance_column = _find(
        frame,
        ("average_trip_miles", "avg_trip_miles", "mean_trip_miles", "trip_miles"),
    )
    pooled_column = _find(
        frame,
        (
            "pooled_trip_share",
            "pooled_share",
            "shared_trip_share",
            "shared_matched_share",
            "shared_requested_share",
        ),
    )

    mean_demand = _finite_mean(frame, demand_column)
    if mean_demand is None or mean_demand <= 0:
        raise ValueError("mean panel trip count must be positive")
    mean_fare = _finite_weighted_mean(frame, fare_column, demand_column)
    # Rescale supply with demand so the configured (assumed) baseline tightness is
    # preserved. Trip records do not observe available drivers, so the ratio itself
    # is not estimated from this panel.
    scale = mean_demand / base.base_demand
    updates: dict[str, float] = {
        "base_demand": mean_demand,
        "base_supply": base.base_supply * scale,
    }
    if mean_fare is not None and mean_fare > 0:
        updates["base_fare"] = mean_fare

    calibrated = replace(base, **updates)
    # Completed trips are a matched-market outcome, not latent requests. Run the
    # structural control path once, then proportionally rescale demand and supply so
    # the achieved mean completed trips matches the empirical target while preserving
    # the explicitly assumed supply-to-demand ratio.
    from casuallab.simulator import simulate_market

    initial_control = simulate_market(calibrated).counterfactuals["control"]
    initial_completed = float(initial_control["trips"].mean())
    if not np.isfinite(initial_completed) or initial_completed <= 0:
        raise ValueError("simulator control path has non-positive completed trips")
    market_scale = mean_demand / initial_completed
    calibrated = replace(
        calibrated,
        base_demand=calibrated.base_demand * market_scale,
        base_supply=calibrated.base_supply * market_scale,
    )
    achieved_control = float(
        simulate_market(calibrated).counterfactuals["control"]["trips"].mean()
    )
    empirical_targets: dict[str, float | int | None] = {
        "panel_rows": int(len(frame)),
        "mean_completed_trips_per_observed_cell": mean_demand,
        "mean_observed_fare": mean_fare,
        "equal_observed_cell_mean_fare": _finite_mean(frame, fare_column),
        "mean_observed_trip_seconds": _finite_weighted_mean(
            frame, duration_column, demand_column
        ),
        "mean_observed_trip_miles": _finite_weighted_mean(
            frame, distance_column, demand_column
        ),
        "mean_observed_pooled_trip_share": _finite_weighted_mean(
            frame, pooled_column, demand_column
        ),
        "preserved_assumed_supply_to_demand_ratio": base.base_supply / base.base_demand,
        "achieved_simulated_control_completed_trips": achieved_control,
        "completed_trip_calibration_error": achieved_control - mean_demand,
    }
    structural = (
        "baseline_supply_to_demand_ratio",
        "capacity_per_driver",
        "matching_efficiency",
        "rider_value",
        "operating_cost_per_trip",
        "wait_disutility_per_minute",
        "treatment_version",
        "discount_rate",
        "incentive_per_driver",
        "reference_incentive_per_driver",
        "direct_demand_effect",
        "direct_supply_effect",
        "spillover_strength",
        "persistence",
        "rider_substitution",
        "driver_mobility",
        "zone_heterogeneity_sd",
        "demand_noise_sd",
        "supply_noise_sd",
        "time_pattern_strength",
    )
    return CalibrationResult(calibrated, empirical_targets, structural)


def write_calibration(result: CalibrationResult, path: str | Path) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return destination
