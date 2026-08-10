"""Monte Carlo metrics for design and estimator comparisons."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd
import yaml


def _jeffreys_binomial_sd(successes: int, trials: int) -> float:
    """Return Jeffreys-posterior uncertainty for a simulated binomial rate."""

    posterior_success = successes + 0.5
    posterior_failure = trials - successes + 0.5
    posterior_total = posterior_success + posterior_failure
    return float(
        np.sqrt(
            posterior_success
            * posterior_failure
            / (posterior_total**2 * (posterior_total + 1.0))
        )
    )


@dataclass(frozen=True)
class BenchmarkConfig:
    """Laptop-safe Monte Carlo configuration."""

    replications: int = 100
    seed: int = 1729
    confidence_level: float = 0.95
    designs: tuple[str, ...] = ("individual", "geo_cluster", "switchback")
    estimators: tuple[str, ...] = ("difference_in_means", "regression_adjusted", "cluster_robust")
    target_estimand: str = "market_total_effect"
    cost_per_market_period: float = 1.0

    def __post_init__(self) -> None:
        if self.replications < 2:
            raise ValueError("replications must be at least 2")
        if not 0.5 < self.confidence_level < 1.0:
            raise ValueError("confidence_level must be between 0.5 and 1")
        if not self.designs:
            raise ValueError("at least one design is required")
        if not self.estimators:
            raise ValueError("at least one estimator is required")
        if self.cost_per_market_period <= 0:
            raise ValueError("cost_per_market_period must be positive")

    @classmethod
    def from_mapping(cls, values: Mapping[str, object]) -> BenchmarkConfig:
        benchmark_values = values.get("benchmark", values)
        if not isinstance(benchmark_values, Mapping):
            raise ValueError("benchmark configuration must be a mapping")
        kwargs = dict(benchmark_values)
        if "designs" in kwargs:
            kwargs["designs"] = tuple(str(value) for value in kwargs["designs"])
        if "estimators" in kwargs:
            kwargs["estimators"] = tuple(str(value) for value in kwargs["estimators"])
        allowed = set(cls.__dataclass_fields__)
        unknown = set(kwargs).difference(allowed)
        if unknown:
            raise ValueError(f"unknown benchmark configuration keys: {sorted(unknown)}")
        return cls(**kwargs)

    @classmethod
    def from_yaml(cls, path: str | Path) -> BenchmarkConfig:
        with Path(path).open(encoding="utf-8") as stream:
            values = yaml.safe_load(stream) or {}
        return cls.from_mapping(values)


def summarize_monte_carlo(
    records: pd.DataFrame,
    *,
    confidence_level: float = 0.95,
    group_columns: Sequence[str] | None = None,
) -> pd.DataFrame:
    """Summarize estimates against row-level known ground truth.

    Required columns are ``design``, ``estimator``, ``estimate``, ``std_error``, and
    ``truth``. Optional grouping columns (target estimand, interference, persistence,
    duration, or budget) are retained. Intervals are normal approximations using the
    estimator's own standard error. ``information_cost`` is defined transparently as
    total design cost times MSE: cost divided by precision (where precision is 1/MSE).
    Coverage and power Monte Carlo uncertainty use the posterior standard deviation
    under Jeffreys' binomial prior.  Unlike the plug-in binomial standard error, this
    remains positive when every simulated interval covers (or every test rejects), so
    a small finite run is not presented as exact knowledge.
    """

    required = {"design", "estimator", "estimate", "std_error", "truth"}
    missing = required.difference(records.columns)
    if missing:
        raise ValueError(f"Monte Carlo records missing columns: {sorted(missing)}")
    if records.empty:
        raise ValueError("Monte Carlo records must not be empty")
    if not 0.5 < confidence_level < 1.0:
        raise ValueError("confidence_level must be between 0.5 and 1")

    numeric = records[["estimate", "std_error", "truth"]].to_numpy(dtype=float)
    if not np.isfinite(numeric).all():
        raise ValueError("estimate, std_error, and truth must be finite")
    if (records["std_error"] < 0).any():
        raise ValueError("std_error cannot be negative")

    alpha = 1.0 - confidence_level
    z = NormalDist().inv_cdf(0.5 + confidence_level / 2.0)
    frame = records.copy()
    frame["error"] = frame["estimate"] - frame["truth"]
    frame["squared_error"] = frame["error"] ** 2
    if {"ci_low", "ci_high"}.issubset(frame.columns):
        frame["covered"] = (frame["ci_low"] <= frame["truth"]) & (
            frame["truth"] <= frame["ci_high"]
        )
    else:
        frame["covered"] = (
            (frame["estimate"] - z * frame["std_error"] <= frame["truth"])
            & (frame["truth"] <= frame["estimate"] + z * frame["std_error"])
        )
    if "p_value" in frame:
        frame["reject_null"] = frame["p_value"] < alpha
    else:
        frame["reject_null"] = (
            np.abs(frame["estimate"] / frame["std_error"].replace(0.0, np.nan)) > z
        )
    frame["design_cost"] = frame.get("design_cost", pd.Series(1.0, index=frame.index)).astype(float)

    if group_columns is None:
        declared_scenario_dimensions = (
            "design",
            "estimator",
            "target_estimand",
            "scenario",
            "spillover_strength",
            "persistence",
            "treatment_duration",
            "washout_periods",
            "treatment_saturation",
            "budget",
            "n_clusters",
            "cluster_size",
            "n_zones",
            "n_periods",
            "identified",
            "evidence_type",
        )
        group_columns = [
            column for column in declared_scenario_dimensions if column in frame.columns
        ]
    else:
        group_columns = list(group_columns)
    required_groups = {"design", "estimator"}
    if not required_groups.issubset(group_columns):
        raise ValueError("group_columns must include design and estimator")

    rows: list[dict[str, object]] = []
    grouped = frame.groupby(group_columns, dropna=False, sort=True)
    for keys, group in grouped:
        if not isinstance(keys, tuple):
            keys = (keys,)
        mse = float(group["squared_error"].mean())
        n_replications = int(len(group))
        rmse = float(np.sqrt(mse))
        bias_mcse = float(group["error"].std(ddof=1) / np.sqrt(n_replications))
        coverage = float(group["covered"].mean())
        power = float(group["reject_null"].mean())
        covered_count = int(group["covered"].sum())
        rejected_count = int(group["reject_null"].sum())

        squared_error_mcse = float(
            group["squared_error"].std(ddof=1) / np.sqrt(n_replications)
        )
        row: dict[str, object] = dict(zip(group_columns, keys, strict=True))
        row.update(
            {
                "truth": float(group["truth"].mean()),
                "mean_estimate": float(group["estimate"].mean()),
                "bias": float(group["error"].mean()),
                "bias_mcse": bias_mcse,
                "variance": float(group["estimate"].var(ddof=1)),
                "rmse": rmse,
                "rmse_mcse": squared_error_mcse / (2.0 * rmse) if rmse > 0 else 0.0,
                "coverage": coverage,
                "coverage_mcse": _jeffreys_binomial_sd(
                    covered_count, n_replications
                ),
                "power": power,
                "power_mcse": _jeffreys_binomial_sd(
                    rejected_count, n_replications
                ),
                "binomial_mcse_method": "jeffreys_posterior_standard_deviation",
                "mean_std_error": float(group["std_error"].mean()),
                "replications": n_replications,
                "mean_design_cost": float(group["design_cost"].mean()),
                "information_cost": float(group["design_cost"].mean()) * mse,
                "confidence_level": confidence_level,
                "evidence_type": "semi_synthetic_causal_monte_carlo",
            }
        )
        rows.append(row)
    return pd.DataFrame(rows).sort_values(group_columns).reset_index(drop=True)


ReplicationFunction = Callable[[str, str, int], Mapping[str, object]]


def run_replications(
    config: BenchmarkConfig,
    replication_function: ReplicationFunction,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run a caller-supplied simulation/estimation function deterministically.

    The callback receives ``(design, estimator, seed)`` and must return at least
    ``estimate``, ``std_error``, and ``truth``. This narrow interface keeps the metric
    engine reusable while simulator-specific orchestration remains explicit.
    """

    rows: list[dict[str, object]] = []
    seed_sequence = np.random.SeedSequence(config.seed)
    # All estimators see the same market draw within a design/replication. This
    # paired Monte Carlo comparison reduces noise in estimator rankings and makes
    # debugging differences substantially easier.
    child_sequences = seed_sequence.spawn(config.replications * len(config.designs))
    sequence_index = 0
    for design in config.designs:
        for replication in range(config.replications):
            seed = int(child_sequences[sequence_index].generate_state(1)[0])
            sequence_index += 1
            for estimator in config.estimators:
                values = dict(replication_function(design, estimator, seed))
                missing = {"estimate", "std_error", "truth"}.difference(values)
                if missing:
                    raise ValueError(f"replication callback missing: {sorted(missing)}")
                values.update(
                    {
                        "design": design,
                        "estimator": estimator,
                        "replication": replication,
                        "seed": seed,
                        "target_estimand": values.get(
                            "target_estimand", config.target_estimand
                        ),
                        "design_cost": values.get(
                            "design_cost", config.cost_per_market_period
                        ),
                    }
                )
                rows.append(values)
    records = pd.DataFrame(rows)
    return records, summarize_monte_carlo(records, confidence_level=config.confidence_level)


def write_benchmark_outputs(
    records: pd.DataFrame,
    summary: pd.DataFrame,
    output_directory: str | Path,
) -> tuple[Path, Path]:
    """Write stable CSV outputs with explicit evidence labels."""

    directory = Path(output_directory)
    directory.mkdir(parents=True, exist_ok=True)
    records_path = directory / "monte_carlo_records.csv"
    summary_path = directory / "benchmark_results.csv"
    records.sort_values(["design", "estimator", "replication"]).to_csv(records_path, index=False)
    summary.to_csv(summary_path, index=False)
    return records_path, summary_path


def best_design_by_rmse(
    summary: pd.DataFrame,
    *,
    target_estimand: str,
    allowed_designs: Sequence[str] | None = None,
) -> pd.Series:
    """Select the lowest-RMSE design/estimator for one declared estimand."""

    required = {"design", "estimator", "target_estimand", "rmse"}
    missing = required.difference(summary.columns)
    if missing:
        raise ValueError(f"benchmark summary missing columns: {sorted(missing)}")
    eligible = summary.loc[summary["target_estimand"] == target_estimand]
    if allowed_designs is not None:
        eligible = eligible.loc[eligible["design"].isin(allowed_designs)]
    if eligible.empty:
        raise ValueError(f"no benchmark rows for target estimand {target_estimand!r}")
    return eligible.sort_values(["rmse", "information_cost", "design", "estimator"]).iloc[0]
