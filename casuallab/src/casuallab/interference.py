"""Design and estimation helpers for mapped marketplace interference.

The canonical marketplace benchmark deliberately withholds a full-policy recommendation
when a plain assignment coefficient does not identify the all-market policy contrast.  This
module supplies a narrower, explicit alternative: randomize geographic clusters to treatment
saturations, map neighboring exposure with pre-treatment weights, and estimate controlled
own/neighbor exposure-response slopes.  Those slopes are *not* relabeled as the full-policy
market-total effect.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from math import isclose, isfinite
from numbers import Integral
from typing import Any

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy.stats import t as student_t


@dataclass(frozen=True, slots=True)
class TwoStageSaturationConfig:
    """Configuration for a geographic two-stage saturation experiment.

    Stage one assigns geographic clusters to one of ``saturation_levels`` using a
    balanced complete randomization. Stage two independently assigns the configured
    number of opportunities inside each zone-period cell at that cluster's saturation.
    Aggregate cells therefore retain a transparent randomized treated share.
    """

    n_clusters: int = 8
    individuals_per_cell: int = 100
    saturation_levels: tuple[float, ...] = (0.0, 0.5, 1.0)
    saturation_probabilities: tuple[float, ...] | None = None
    seed: int = 202503

    def __post_init__(self) -> None:
        for name, value in {
            "n_clusters": self.n_clusters,
            "individuals_per_cell": self.individuals_per_cell,
            "seed": self.seed,
        }.items():
            if isinstance(value, bool) or not isinstance(value, Integral):
                raise ValueError(f"{name} must be an integer")
        if self.n_clusters < 2:
            raise ValueError("n_clusters must be at least two")
        if self.individuals_per_cell < 1:
            raise ValueError("individuals_per_cell must be positive")
        levels = tuple(float(value) for value in self.saturation_levels)
        if len(levels) < 2 or len(set(levels)) != len(levels):
            raise ValueError("saturation_levels must contain at least two unique values")
        if any(not isfinite(value) or not 0 <= value <= 1 for value in levels):
            raise ValueError("saturation_levels must lie in [0, 1]")
        if self.n_clusters < len(levels):
            raise ValueError("n_clusters must be at least the number of saturation levels")
        object.__setattr__(self, "saturation_levels", levels)

        if self.saturation_probabilities is None:
            return
        probabilities = tuple(float(value) for value in self.saturation_probabilities)
        if len(probabilities) != len(levels):
            raise ValueError("saturation_probabilities must align with saturation_levels")
        if any(not isfinite(value) or value <= 0 for value in probabilities):
            raise ValueError("saturation_probabilities must be finite and positive")
        if not isclose(sum(probabilities), 1.0, rel_tol=0.0, abs_tol=1e-9):
            raise ValueError("saturation_probabilities must sum to one")
        object.__setattr__(self, "saturation_probabilities", probabilities)


@dataclass(frozen=True, slots=True)
class ExposureMappingConfig:
    """Column and inference contract for a mapped exposure-response regression."""

    outcome: str = "outcome"
    own_exposure: str = "treatment"
    neighbor_exposure: str = "neighbor_exposure"
    history_exposure: str | None = "history_exposure"
    cluster: str = "randomization_cluster"
    covariates: tuple[str, ...] = ()
    alpha: float = 0.05
    minimum_inference_clusters: int = 8

    def __post_init__(self) -> None:
        if not 0 < self.alpha < 1:
            raise ValueError("alpha must lie strictly between zero and one")
        if (
            isinstance(self.minimum_inference_clusters, bool)
            or not isinstance(self.minimum_inference_clusters, Integral)
            or self.minimum_inference_clusters < 2
        ):
            raise ValueError("minimum_inference_clusters must be an integer of at least two")
        if len({self.own_exposure, self.neighbor_exposure}) != 2:
            raise ValueError("own and neighbor exposure columns must be distinct")
        if self.history_exposure in {self.own_exposure, self.neighbor_exposure}:
            raise ValueError("history exposure must be distinct from current exposures")


def _balanced_arm_counts(n_clusters: int, probabilities: np.ndarray) -> np.ndarray:
    """Return positive fixed arm counts with largest-remainder allocation."""

    raw = probabilities * n_clusters
    counts = np.floor(raw).astype(int)
    counts[counts == 0] = 1
    while int(counts.sum()) > n_clusters:
        candidates = np.flatnonzero(counts > 1)
        if not len(candidates):
            raise ValueError("not enough clusters to represent every saturation arm")
        remove = candidates[np.argmax(counts[candidates] - raw[candidates])]
        counts[remove] -= 1
    while int(counts.sum()) < n_clusters:
        add = int(np.argmax(raw - counts))
        counts[add] += 1
    return counts


def two_stage_saturation_assignment(
    units: pd.DataFrame,
    config: TwoStageSaturationConfig | None = None,
) -> pd.DataFrame:
    """Generate a deterministic two-stage geographic saturation assignment.

    The input must contain one row per ``zone_id`` × ``period_id`` cell. Geographic
    clusters are deterministic functions of sorted zone IDs; cluster saturation arms
    and within-cell opportunity assignments are randomized with the recorded seed.
    """

    cfg = config or TwoStageSaturationConfig()
    if not isinstance(units, pd.DataFrame):
        raise TypeError("units must be a pandas DataFrame")
    required = {"zone_id", "period_id"}
    missing = required.difference(units.columns)
    if missing:
        raise ValueError(f"assignment units missing columns: {sorted(missing)}")
    frame = units.copy().reset_index(drop=True)
    if frame.empty:
        raise ValueError("assignment units must not be empty")
    if frame[["zone_id", "period_id"]].isna().any().any():
        raise ValueError("zone_id and period_id cannot contain missing values")
    if frame.duplicated(["zone_id", "period_id"]).any():
        raise ValueError("assignment units must be unique by zone_id and period_id")

    zones = np.asarray(sorted(frame["zone_id"].unique()))
    if cfg.n_clusters > len(zones):
        raise ValueError("n_clusters cannot exceed the number of observed zones")
    cluster_rank = np.floor(np.arange(len(zones)) * cfg.n_clusters / len(zones)).astype(int)
    zone_to_cluster = dict(zip(zones.tolist(), cluster_rank.tolist(), strict=True))
    frame["cluster_id"] = frame["zone_id"].map(zone_to_cluster).astype(int)

    levels = np.asarray(cfg.saturation_levels, dtype=float)
    probabilities = (
        np.full(len(levels), 1.0 / len(levels), dtype=float)
        if cfg.saturation_probabilities is None
        else np.asarray(cfg.saturation_probabilities, dtype=float)
    )
    arm_counts = _balanced_arm_counts(cfg.n_clusters, probabilities)
    saturation_arms = np.repeat(levels, arm_counts)
    rng = np.random.default_rng(cfg.seed)
    saturation_arms = saturation_arms[rng.permutation(cfg.n_clusters)]
    cluster_to_saturation = dict(enumerate(saturation_arms.tolist()))
    realized_stage_one_probability = {
        float(level): float(count / cfg.n_clusters)
        for level, count in zip(levels, arm_counts, strict=True)
    }
    frame["cluster_saturation"] = frame["cluster_id"].map(cluster_to_saturation).astype(float)
    frame["saturation_arm"] = frame["cluster_saturation"]
    frame["saturation_assignment_probability"] = frame["cluster_saturation"].map(
        realized_stage_one_probability
    )
    frame["unit_count"] = int(cfg.individuals_per_cell)
    frame["treated_units"] = rng.binomial(
        cfg.individuals_per_cell,
        frame["cluster_saturation"].to_numpy(dtype=float),
    )
    frame["assigned_treatment"] = frame["treated_units"] / cfg.individuals_per_cell
    frame["treatment"] = frame["assigned_treatment"]
    frame["treatment_intensity"] = frame["treatment"]
    frame["treatment_probability"] = frame["cluster_saturation"]
    frame["planned_treatment"] = frame["treatment"]
    frame["randomization_cluster"] = "saturation_geo_" + frame["cluster_id"].astype(str)
    frame["design"] = "two_stage_saturation"
    frame["assignment_seed"] = int(cfg.seed)
    frame["analysis_eligible"] = 1
    frame["washout"] = 0
    frame["evidence_type"] = "randomized_design_assignment"
    return frame


def _mapping_digest(edges: pd.DataFrame) -> str:
    records = edges.sort_values(["focal_zone_id", "neighbor_zone_id"]).to_dict("records")
    payload = json.dumps(records, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(payload.encode("utf-8")).hexdigest()


def add_mapped_exposures(
    assignments: pd.DataFrame,
    edges: pd.DataFrame,
    *,
    zone_column: str = "zone_id",
    time_column: str = "period_id",
    treatment_column: str = "treatment",
    history_lags: int = 0,
) -> pd.DataFrame:
    """Attach normalized neighbor and exact-lag own-treatment exposures.

    ``edges`` must contain ``focal_zone_id``, ``neighbor_zone_id``, and nonnegative
    ``weight``. Weights are normalized within focal zone. A focal zone with no mapped
    neighbors receives a missing exposure—not a fabricated zero. Exact lag support is
    obtained by key joins, so gaps in the time index are never treated as adjacent.
    """

    if not isinstance(assignments, pd.DataFrame) or not isinstance(edges, pd.DataFrame):
        raise TypeError("assignments and edges must be pandas DataFrames")
    if isinstance(history_lags, bool) or not isinstance(history_lags, Integral) or history_lags < 0:
        raise ValueError("history_lags must be a non-negative integer")
    required_assignment = {zone_column, time_column, treatment_column}
    missing_assignment = required_assignment.difference(assignments.columns)
    if missing_assignment:
        raise ValueError(f"assignment data missing columns: {sorted(missing_assignment)}")
    required_edges = {"focal_zone_id", "neighbor_zone_id", "weight"}
    missing_edges = required_edges.difference(edges.columns)
    if missing_edges:
        raise ValueError(f"exposure map missing columns: {sorted(missing_edges)}")
    frame = assignments.copy().reset_index(drop=True)
    if frame.duplicated([zone_column, time_column]).any():
        raise ValueError("assignment data must be unique by zone and time")
    try:
        treatment = frame[treatment_column].to_numpy(dtype=float)
        periods = frame[time_column].to_numpy(dtype=int)
    except (TypeError, ValueError) as exc:
        raise ValueError("treatment and time columns must be numeric") from exc
    if not np.isfinite(treatment).all():
        raise ValueError("treatment must be finite")
    if not np.allclose(periods, frame[time_column].to_numpy(dtype=float)):
        raise ValueError("time values must be integer-like for exact-lag mapping")

    mapping = edges[["focal_zone_id", "neighbor_zone_id", "weight"]].copy()
    if mapping.empty:
        raise ValueError("exposure map must not be empty")
    if mapping.duplicated(["focal_zone_id", "neighbor_zone_id"]).any():
        raise ValueError("exposure map must be unique by focal-neighbor pair")
    weights = pd.to_numeric(mapping["weight"], errors="coerce")
    if weights.isna().any() or (weights < 0).any() or not np.isfinite(weights).all():
        raise ValueError("exposure-map weights must be finite and non-negative")
    if (mapping["focal_zone_id"] == mapping["neighbor_zone_id"]).any():
        raise ValueError("neighbor exposure map must not contain self edges")
    mapping["weight"] = weights.astype(float)
    weight_sum = mapping.groupby("focal_zone_id")["weight"].transform("sum")
    if (weight_sum <= 0).any():
        raise ValueError("every mapped focal zone must have positive total neighbor weight")
    mapping["normalized_weight"] = mapping["weight"] / weight_sum

    neighbor_values = frame[[zone_column, time_column, treatment_column]].rename(
        columns={zone_column: "neighbor_zone_id", treatment_column: "neighbor_treatment"}
    )
    expanded = mapping.merge(neighbor_values, on="neighbor_zone_id", how="left", validate="m:m")
    expanded["weighted_neighbor_treatment"] = (
        expanded["normalized_weight"] * expanded["neighbor_treatment"]
    )
    exposure = (
        expanded.groupby(["focal_zone_id", time_column], as_index=False)
        .agg(
            neighbor_exposure=("weighted_neighbor_treatment", "sum"),
            mapped_neighbor_count=("neighbor_treatment", "count"),
            mapped_neighbor_weight=("normalized_weight", "sum"),
        )
        .rename(columns={"focal_zone_id": zone_column})
    )
    expected_neighbors = mapping.groupby("focal_zone_id")["neighbor_zone_id"].nunique()
    exposure["expected_neighbor_count"] = exposure[zone_column].map(expected_neighbors)
    incomplete = exposure["mapped_neighbor_count"] != exposure["expected_neighbor_count"]
    exposure.loc[incomplete, ["neighbor_exposure", "mapped_neighbor_weight"]] = np.nan
    result = frame.merge(exposure, on=[zone_column, time_column], how="left", validate="1:1")

    result["history_support"] = 0
    lag_columns: list[str] = []
    for lag in range(1, int(history_lags) + 1):
        lag_name = f"own_history_lag_{lag}"
        prior = frame[[zone_column, time_column, treatment_column]].copy()
        prior[time_column] = prior[time_column].astype(int) + lag
        prior = prior.rename(columns={treatment_column: lag_name})
        result = result.merge(prior, on=[zone_column, time_column], how="left", validate="1:1")
        lag_columns.append(lag_name)
    if lag_columns:
        result["history_support"] = result[lag_columns].notna().sum(axis=1)
        result["history_exposure"] = result[lag_columns].mean(axis=1, skipna=False)
    else:
        result["history_exposure"] = np.nan
    result["exposure_mapping_id"] = _mapping_digest(mapping)
    result["exposure_mapping_evidence"] = "pre_treatment_user_supplied_weight_map"
    return result


def estimate_exposure_response(
    data: pd.DataFrame,
    config: ExposureMappingConfig | None = None,
) -> pd.DataFrame:
    """Estimate controlled own and neighbor exposure-response slopes jointly.

    The returned rows name controlled exposure-response targets. They do not identify
    the all-zone policy effect unless an external identification argument supplies that
    bridge. Cluster-robust CR1/t inference follows the supplied randomization cluster.
    """

    cfg = config or ExposureMappingConfig()
    if not isinstance(data, pd.DataFrame):
        raise TypeError("data must be a pandas DataFrame")
    exposure_terms = [cfg.own_exposure, cfg.neighbor_exposure]
    if cfg.history_exposure is not None:
        if cfg.history_exposure not in data.columns:
            raise ValueError(
                "exposure estimator data missing configured history column: "
                f"{cfg.history_exposure!r}; set history_exposure=None only when history "
                "is deliberately excluded from the estimand"
            )
        exposure_terms.append(cfg.history_exposure)
    required = [cfg.outcome, cfg.cluster, *exposure_terms, *cfg.covariates]
    missing = set(required).difference(data.columns)
    if missing:
        raise ValueError(f"exposure estimator data missing columns: {sorted(missing)}")
    frame = data.dropna(subset=list(dict.fromkeys(required))).copy()
    if frame.empty:
        raise ValueError("no complete exposure-mapped observations remain")
    mapping_ids = (
        sorted(frame["exposure_mapping_id"].dropna().astype(str).unique().tolist())
        if "exposure_mapping_id" in frame
        else []
    )
    if len(mapping_ids) > 1:
        raise ValueError(
            "exposure estimator requires one predeclared exposure mapping; "
            f"found {len(mapping_ids)} exposure_mapping_id values"
        )

    numeric = frame[[cfg.outcome, *exposure_terms]].apply(pd.to_numeric, errors="coerce")
    if numeric.isna().any().any() or not np.isfinite(numeric.to_numpy(dtype=float)).all():
        raise ValueError("outcome and exposure columns must be finite numeric values")
    covariates = (
        pd.get_dummies(frame[list(cfg.covariates)], drop_first=True, dtype=float)
        if cfg.covariates
        else pd.DataFrame(index=frame.index)
    )
    if not np.isfinite(covariates.to_numpy(dtype=float)).all():
        raise ValueError("covariates must be finite")
    design = pd.concat([numeric[exposure_terms], covariates], axis=1).astype(float)
    design = sm.add_constant(design, has_constant="add")
    matrix = design.to_numpy(dtype=float)
    if np.linalg.matrix_rank(matrix) < matrix.shape[1]:
        raise ValueError("mapped exposure design matrix is rank deficient")
    groups = frame[cfg.cluster]
    n_clusters = int(groups.nunique())
    if n_clusters < 2:
        raise ValueError("cluster-aware exposure inference requires at least two clusters")
    fit = sm.OLS(numeric[cfg.outcome], design).fit(
        cov_type="cluster",
        cov_kwds={"groups": groups, "use_correction": True},
        use_t=True,
    )
    degrees_freedom = n_clusters - 1
    critical = float(student_t.ppf(1.0 - cfg.alpha / 2.0, degrees_freedom))
    target_for_term = {
        cfg.own_exposure: "controlled_zone_direct_effect",
        cfg.neighbor_exposure: "spillover_effect",
    }
    if cfg.history_exposure is not None:
        target_for_term[cfg.history_exposure] = "controlled_history_exposure_response"
    rows: list[dict[str, Any]] = []
    for term in exposure_terms:
        estimate = float(fit.params[term])
        standard_error = float(fit.bse[term])
        statistic = estimate / standard_error if standard_error > 0 else np.inf
        rows.append(
            {
                "method": "exposure_mapped_cluster_regression",
                "exposure_term": term,
                "target_estimand": target_for_term[term],
                "estimate": estimate,
                "standard_error": standard_error,
                "ci_low": estimate - critical * standard_error,
                "ci_high": estimate + critical * standard_error,
                "p_value": float(2.0 * student_t.sf(abs(statistic), degrees_freedom)),
                "n_obs": int(fit.nobs),
                "n_clusters": n_clusters,
                "degrees_freedom": degrees_freedom,
                "inference_valid": n_clusters >= cfg.minimum_inference_clusters,
                "minimum_inference_clusters": int(cfg.minimum_inference_clusters),
                "variance_estimator": "CR1 cluster-t",
                "effect_scale": "per-unit exposure slope; not the full-policy market total",
                "identification_scope": (
                    "conditional on randomized support, a correct pre-treatment exposure map, "
                    "and no unmapped interference or omitted exposure history"
                ),
                "evidence_type": "exposure_mapped_response_conditional_on_design_validity",
                "mapping_ids": mapping_ids,
                "covariates": list(cfg.covariates),
                "r_squared": float(fit.rsquared),
            }
        )
    return pd.DataFrame(rows)


__all__ = [
    "ExposureMappingConfig",
    "TwoStageSaturationConfig",
    "add_mapped_exposures",
    "estimate_exposure_response",
    "two_stage_saturation_assignment",
]
