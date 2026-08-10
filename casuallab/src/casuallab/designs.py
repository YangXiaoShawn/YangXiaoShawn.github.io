"""Randomization mechanisms for marketplace experiments.

Every generator returns the same explicit assignment schema.  In particular,
``assigned_treatment`` records the randomized arm (the ITT instrument), while
``treatment`` records realized exposure after partial saturation.  The simulator may
subsequently attenuate ``treatment`` to respect a budget, but never rewrites the arm.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

import numpy as np
import pandas as pd

from .config import DesignConfig, DesignName

ASSIGNMENT_COLUMNS = (
    "zone_id",
    "period_id",
    "design",
    "cluster_id",
    "time_block",
    "randomization_cluster",
    "assigned_treatment",
    "treatment",
    "treatment_probability",
    "analysis_eligible",
    "washout",
    "assignment_seed",
)


def _coerce_config(config: DesignConfig | str | None) -> DesignConfig:
    if config is None:
        return DesignConfig()
    if isinstance(config, DesignConfig):
        return config
    return DesignConfig(name=DesignName.parse(config))


def _prepare_units(
    units: pd.DataFrame | int,
    n_periods: int | None = None,
) -> pd.DataFrame:
    if isinstance(units, (int, np.integer)):
        n_zones = int(units)
        if n_zones < 1 or n_periods is None or n_periods < 1:
            raise ValueError("positive n_zones and n_periods are required")
        grid = pd.MultiIndex.from_product(
            [range(n_periods), range(n_zones)],
            names=["period_id", "zone_id"],
        ).to_frame(index=False)
        grid["unit_id"] = np.arange(len(grid), dtype=int)
        return grid

    frame = units.copy().reset_index(drop=True)
    rename: dict[str, str] = {}
    if "zone_id" not in frame and "zone" in frame:
        rename["zone"] = "zone_id"
    if "period_id" not in frame and "period" in frame:
        rename["period"] = "period_id"
    frame = frame.rename(columns=rename)
    missing = {"zone_id", "period_id"}.difference(frame.columns)
    if missing:
        raise ValueError(f"assignment units missing columns: {sorted(missing)}")
    if frame.empty:
        raise ValueError("assignment units must not be empty")
    if frame[["zone_id", "period_id"]].isna().any().any():
        raise ValueError("zone_id and period_id cannot contain missing values")
    if "unit_id" not in frame:
        frame["unit_id"] = np.arange(len(frame), dtype=int)
    return frame


def _complete_randomization(
    n_groups: int,
    probability: float,
    rng: np.random.Generator,
) -> np.ndarray:
    """Balanced complete randomization with a Bernoulli fallback for one group."""

    if n_groups < 1:
        raise ValueError("at least one randomization group is required")
    if n_groups == 1:
        return np.asarray([float(rng.random() < probability)])
    n_treated = int(np.rint(probability * n_groups))
    n_treated = min(max(n_treated, 1), n_groups - 1)
    result = np.zeros(n_groups, dtype=float)
    result[rng.permutation(n_groups)[:n_treated]] = 1.0
    return result


def _marginal_probability(arms: np.ndarray, configured_probability: float) -> float:
    """Return fixed-count inclusion probability or Bernoulli p for one group."""

    return (
        float(configured_probability)
        if len(arms) == 1
        else float(np.asarray(arms, dtype=float).mean())
    )


def _zone_clusters(frame: pd.DataFrame, config: DesignConfig) -> pd.Series:
    zones = np.asarray(sorted(frame["zone_id"].unique()))
    n_zones = len(zones)
    if config.n_clusters is not None:
        if config.n_clusters > n_zones:
            raise ValueError("n_clusters cannot exceed the number of observed zones")
        cluster_for_rank = np.floor(np.arange(n_zones) * config.n_clusters / n_zones).astype(int)
    else:
        cluster_for_rank = np.arange(n_zones) // config.cluster_size
    mapping = dict(zip(zones.tolist(), cluster_for_rank.tolist(), strict=True))
    return frame["zone_id"].map(mapping).astype(int)


def _mark_washout(frame: pd.DataFrame, periods: int, *, by_cluster: bool) -> pd.DataFrame:
    result = frame.copy()
    result["washout"] = 0
    if periods == 0:
        result["analysis_eligible"] = 1
        return result

    group_columns = ["cluster_id"] if by_cluster else []
    schedules = (
        result[[*group_columns, "period_id", "assigned_treatment"]]
        .drop_duplicates()
        .sort_values([*group_columns, "period_id"])
    )
    if group_columns:
        grouped = schedules.groupby(group_columns, sort=False, dropna=False)
    else:
        grouped = [(None, schedules)]
    washout_keys: set[tuple[int, int] | int] = set()
    for group, schedule in grouped:
        prior: float | None = None
        ordered = schedule.sort_values("period_id")
        for row in ordered.itertuples(index=False):
            current = float(row.assigned_treatment)
            period = int(row.period_id)
            if prior is not None and current != prior:
                for offset in range(periods):
                    if by_cluster:
                        cluster = int(group[0] if isinstance(group, tuple) else group)
                        washout_keys.add((cluster, period + offset))
                    else:
                        washout_keys.add(period + offset)
            prior = current

    if by_cluster:
        keys = list(
            zip(
                result["cluster_id"].astype(int),
                result["period_id"].astype(int),
                strict=True,
            )
        )
        result["washout"] = [int(key in washout_keys) for key in keys]
    else:
        result["washout"] = result["period_id"].astype(int).isin(washout_keys).astype(int)
    result["analysis_eligible"] = 1 - result["washout"]
    return result


def _finalize(
    frame: pd.DataFrame,
    config: DesignConfig,
    seed: int,
    *,
    washout_by_cluster: bool = False,
) -> pd.DataFrame:
    result = frame.copy()
    result["assigned_treatment"] = result["assigned_treatment"].astype(float)
    result["treatment"] = (
        result["assigned_treatment"].to_numpy(dtype=float) * config.treatment_saturation
    )
    result["treatment_intensity"] = result["treatment"]
    result["assignment"] = result["assigned_treatment"]
    if "treatment_probability" not in result:
        result["treatment_probability"] = float(config.treatment_probability)
    result["design"] = config.name.value
    result["assignment_seed"] = int(seed)
    if "cluster_id" not in result:
        result["cluster_id"] = result["unit_id"]
    if "time_block" not in result:
        result["time_block"] = result["period_id"]
    if "randomization_cluster" not in result:
        result["randomization_cluster"] = result["cluster_id"].astype(str)
    temporal_designs = {DesignName.TIME_BLOCK, DesignName.SWITCHBACK, DesignName.GEO_TIME}
    if config.name in temporal_designs:
        result = _mark_washout(
            result,
            config.washout_periods,
            by_cluster=washout_by_cluster,
        )
    else:
        # Washout is a temporal carryover exclusion. Contemporaneous differences
        # between geographic arms are not switches and must never trigger it.
        result["washout"] = 0
        result["analysis_eligible"] = 1
    return result


def individual_randomization(
    units: pd.DataFrame | int,
    config: DesignConfig | None = None,
    *,
    n_periods: int | None = None,
    seed: int | None = None,
) -> pd.DataFrame:
    """Randomize individual rows, or binomial shares for aggregated cells.

    If ``unit_count`` is present, each row is interpreted as an aggregated cell and
    the returned assignment is its randomized individual share.  Otherwise rows are
    individual experimental units and receive binary arms.
    """

    cfg = _coerce_config(config or DesignConfig(name=DesignName.INDIVIDUAL))
    cfg = replace(cfg, name=DesignName.INDIVIDUAL)
    actual_seed = cfg.seed if seed is None and cfg.seed is not None else (0 if seed is None else seed)
    rng = np.random.default_rng(actual_seed)
    frame = _prepare_units(units, n_periods)
    if "unit_count" in frame:
        counts = frame["unit_count"].to_numpy(dtype=int)
        if (counts < 1).any():
            raise ValueError("unit_count must contain positive integers")
        treated = rng.binomial(counts, cfg.treatment_probability)
        frame["treated_units"] = treated
        frame["assigned_treatment"] = treated / counts
        frame["treatment_probability"] = cfg.treatment_probability
        frame["cluster_id"] = frame["unit_id"]
        frame["randomization_cluster"] = "individuals_in_" + frame["unit_id"].astype(str)
    else:
        frame["assigned_treatment"] = _complete_randomization(
            len(frame), cfg.treatment_probability, rng
        )
        frame["treatment_probability"] = _marginal_probability(
            frame["assigned_treatment"].to_numpy(dtype=float),
            cfg.treatment_probability,
        )
        frame["cluster_id"] = frame["unit_id"]
        frame["randomization_cluster"] = frame["unit_id"].astype(str)
    return _finalize(frame, cfg, int(actual_seed))


def geo_cluster_randomization(
    units: pd.DataFrame | int,
    config: DesignConfig | None = None,
    *,
    n_periods: int | None = None,
    seed: int | None = None,
) -> pd.DataFrame:
    """Assign geographic clusters once and hold their arm over all periods."""

    cfg = _coerce_config(config or DesignConfig(name=DesignName.GEO_CLUSTER))
    cfg = replace(cfg, name=DesignName.GEO_CLUSTER)
    actual_seed = cfg.seed if seed is None and cfg.seed is not None else (0 if seed is None else seed)
    rng = np.random.default_rng(actual_seed)
    frame = _prepare_units(units, n_periods)
    frame["cluster_id"] = _zone_clusters(frame, cfg)
    clusters = np.asarray(sorted(frame["cluster_id"].unique()))
    arms = _complete_randomization(len(clusters), cfg.treatment_probability, rng)
    mapping = dict(zip(clusters.tolist(), arms.tolist(), strict=True))
    frame["assigned_treatment"] = frame["cluster_id"].map(mapping)
    frame["treatment_probability"] = _marginal_probability(
        arms, cfg.treatment_probability
    )
    frame["randomization_cluster"] = "geo_" + frame["cluster_id"].astype(str)
    return _finalize(frame, cfg, int(actual_seed))


def time_block_randomization(
    units: pd.DataFrame | int,
    config: DesignConfig | None = None,
    *,
    n_periods: int | None = None,
    seed: int | None = None,
) -> pd.DataFrame:
    """Randomize common marketplace-wide time blocks."""

    cfg = _coerce_config(config or DesignConfig(name=DesignName.TIME_BLOCK))
    cfg = replace(cfg, name=DesignName.TIME_BLOCK)
    actual_seed = cfg.seed if seed is None and cfg.seed is not None else (0 if seed is None else seed)
    rng = np.random.default_rng(actual_seed)
    frame = _prepare_units(units, n_periods)
    period_rank = {period: rank for rank, period in enumerate(sorted(frame["period_id"].unique()))}
    frame["time_block"] = frame["period_id"].map(period_rank).astype(int) // cfg.treatment_duration
    blocks = np.asarray(sorted(frame["time_block"].unique()))
    arms = _complete_randomization(len(blocks), cfg.treatment_probability, rng)
    mapping = dict(zip(blocks.tolist(), arms.tolist(), strict=True))
    frame["assigned_treatment"] = frame["time_block"].map(mapping)
    frame["treatment_probability"] = _marginal_probability(
        arms, cfg.treatment_probability
    )
    frame["cluster_id"] = frame["time_block"]
    frame["randomization_cluster"] = "time_" + frame["time_block"].astype(str)
    return _finalize(frame, cfg, int(actual_seed))


def switchback_randomization(
    units: pd.DataFrame | int,
    config: DesignConfig | None = None,
    *,
    n_periods: int | None = None,
    seed: int | None = None,
) -> pd.DataFrame:
    """Alternate the entire marketplace between treatment and control blocks."""

    cfg = _coerce_config(config or DesignConfig(name=DesignName.SWITCHBACK))
    cfg = replace(cfg, name=DesignName.SWITCHBACK)
    actual_seed = cfg.seed if seed is None and cfg.seed is not None else (0 if seed is None else seed)
    rng = np.random.default_rng(actual_seed)
    frame = _prepare_units(units, n_periods)
    period_rank = {period: rank for rank, period in enumerate(sorted(frame["period_id"].unique()))}
    frame["time_block"] = frame["period_id"].map(period_rank).astype(int) // cfg.treatment_duration
    frame["switchback_pair"] = frame["time_block"].astype(int) // 2
    pairs = np.asarray(sorted(frame["switchback_pair"].unique()))
    first_arms = rng.binomial(1, cfg.treatment_probability, size=len(pairs))
    first_mapping = dict(zip(pairs.tolist(), first_arms.tolist(), strict=True))
    pair_first = frame["switchback_pair"].map(first_mapping).astype(int)
    within_pair = frame["time_block"].astype(int) % 2
    frame["assigned_treatment"] = (pair_first + within_pair) % 2
    frame["treatment_probability"] = np.where(
        within_pair == 0,
        cfg.treatment_probability,
        1.0 - cfg.treatment_probability,
    )
    frame["cluster_id"] = frame["switchback_pair"]
    frame["randomization_cluster"] = "switch_pair_" + frame["switchback_pair"].astype(str)
    return _finalize(frame, cfg, int(actual_seed))


def geo_time_randomization(
    units: pd.DataFrame | int,
    config: DesignConfig | None = None,
    *,
    n_periods: int | None = None,
    seed: int | None = None,
) -> pd.DataFrame:
    """Randomize geographic-cluster by time-block cells."""

    cfg = _coerce_config(config or DesignConfig(name=DesignName.GEO_TIME))
    cfg = replace(cfg, name=DesignName.GEO_TIME)
    actual_seed = cfg.seed if seed is None and cfg.seed is not None else (0 if seed is None else seed)
    rng = np.random.default_rng(actual_seed)
    frame = _prepare_units(units, n_periods)
    frame["cluster_id"] = _zone_clusters(frame, cfg)
    period_rank = {period: rank for rank, period in enumerate(sorted(frame["period_id"].unique()))}
    frame["time_block"] = frame["period_id"].map(period_rank).astype(int) // cfg.treatment_duration
    cells = frame[["cluster_id", "time_block"]].drop_duplicates().sort_values(
        ["time_block", "cluster_id"]
    )
    arms = _complete_randomization(len(cells), cfg.treatment_probability, rng)
    mapping = {
        (int(row.cluster_id), int(row.time_block)): float(arm)
        for row, arm in zip(cells.itertuples(index=False), arms, strict=True)
    }
    keys = zip(frame["cluster_id"].astype(int), frame["time_block"].astype(int), strict=True)
    frame["assigned_treatment"] = [mapping[key] for key in keys]
    frame["treatment_probability"] = _marginal_probability(
        arms, cfg.treatment_probability
    )
    frame["randomization_cluster"] = (
        "geo_" + frame["cluster_id"].astype(str) + "_time_" + frame["time_block"].astype(str)
    )
    return _finalize(frame, cfg, int(actual_seed), washout_by_cluster=True)


_GENERATORS: dict[DesignName, Callable[..., pd.DataFrame]] = {
    DesignName.INDIVIDUAL: individual_randomization,
    DesignName.GEO_CLUSTER: geo_cluster_randomization,
    DesignName.TIME_BLOCK: time_block_randomization,
    DesignName.SWITCHBACK: switchback_randomization,
    DesignName.GEO_TIME: geo_time_randomization,
}


def assign_treatment(
    units: pd.DataFrame,
    config: DesignConfig | str,
    *,
    seed: int | None = None,
) -> pd.DataFrame:
    """Assign treatment to an existing unit frame using a named design."""

    cfg = _coerce_config(config)
    return _GENERATORS[cfg.name](units, cfg, seed=seed)


def generate_assignment(
    n_zones: int,
    n_periods: int,
    config: DesignConfig | str | None = None,
    *,
    seed: int | None = None,
    individuals_per_cell: int | None = None,
) -> pd.DataFrame:
    """Generate a canonical zone-period assignment frame.

    ``individuals_per_cell`` activates a binomial partial-saturation assignment for
    the individual design; other designs ignore it because their assignment unit is
    a market cluster or time block.
    """

    cfg = _coerce_config(config)
    frame = _prepare_units(n_zones, n_periods)
    if cfg.name is DesignName.INDIVIDUAL and individuals_per_cell is not None:
        if individuals_per_cell < 1:
            raise ValueError("individuals_per_cell must be positive")
        frame["unit_count"] = int(individuals_per_cell)
    return _GENERATORS[cfg.name](frame, cfg, seed=seed)


def assignment_for_design(
    design: DesignName | str,
    n_zones: int,
    n_periods: int,
    **kwargs: object,
) -> pd.DataFrame:
    """Convenience keyed dispatcher for interactive callers."""

    config_fields = {
        key: value
        for key, value in kwargs.items()
        if key
        in {
            "treatment_probability",
            "treatment_saturation",
            "n_clusters",
            "cluster_size",
            "treatment_duration",
            "washout_periods",
            "budget",
            "seed",
        }
    }
    cfg = DesignConfig(name=DesignName.parse(design), **config_fields)
    seed = kwargs.get("seed")
    individuals = kwargs.get("individuals_per_cell")
    return generate_assignment(
        n_zones,
        n_periods,
        cfg,
        seed=None if seed is None else int(seed),
        individuals_per_cell=None if individuals is None else int(individuals),
    )


def enforce_budget(
    assignments: pd.DataFrame,
    cost_per_full_treatment: np.ndarray | pd.Series | float,
    budget: float | None,
) -> pd.DataFrame:
    """Uniformly attenuate exposure to satisfy an expected-spend constraint.

    Uniform attenuation preserves the randomized ordering and avoids post-outcome
    selection.  The simulator refines this scale using structural realized spend.
    """

    result = assignments.copy()
    if "treatment" not in result:
        raise ValueError("assignments must contain treatment")
    costs = np.broadcast_to(np.asarray(cost_per_full_treatment, dtype=float), len(result))
    if not np.isfinite(costs).all() or (costs < 0).any():
        raise ValueError("cost_per_full_treatment must be finite and non-negative")
    if budget is not None and budget < 0:
        raise ValueError("budget cannot be negative")
    planned = result["treatment"].to_numpy(dtype=float)
    gross_cost = float(np.dot(planned, costs))
    scale = 1.0 if budget is None or gross_cost <= budget else float(budget / gross_cost)
    result["planned_treatment"] = planned
    result["treatment"] = planned * scale
    result["treatment_intensity"] = result["treatment"]
    result["budget_scale"] = scale
    result["expected_treatment_cost"] = result["treatment"] * costs
    return result


# Short aliases are useful in notebooks while the explicit names remain discoverable.
individual = individual_randomization
geo_cluster = geo_cluster_randomization
time_block = time_block_randomization
switchback = switchback_randomization
geo_time = geo_time_randomization
