"""Known-truth benchmark for exposure-aware marketplace estimation.

This module deliberately targets a narrower question than the full marketplace
simulator: can a predeclared two-stage saturation design recover controlled own,
neighbor, and lagged exposure-response slopes when the exposure map is correct?
The data-generating process is transparent and additive so every target is known.

A naive coefficient on the stage-one saturation arm is also recorded.  It is a
randomized assignment diagnostic, but it is not relabeled as the all-market policy
effect when neighbor exposure and treatment history are omitted.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from math import isfinite
from numbers import Integral, Real
from typing import Any, Final

import numpy as np
import pandas as pd

from .benchmark import summarize_monte_carlo
from .config import EstimatorConfig
from .estimators import cluster_robust
from .interference import (
    ExposureMappingConfig,
    TwoStageSaturationConfig,
    add_mapped_exposures,
    estimate_exposure_response,
    two_stage_saturation_assignment,
)

MAPPED_TARGETS: Final[Mapping[str, str]] = {
    "treatment": "controlled_zone_direct_effect",
    "neighbor_exposure": "spillover_effect",
    "history_exposure": "controlled_history_exposure_response",
}

ESTIMAND_DEFINITIONS: Final[Mapping[str, str]] = {
    "controlled_zone_direct_effect": (
        "Per-unit own-treatment response holding mapped neighbor and lagged exposure fixed."
    ),
    "spillover_effect": (
        "Per-unit response to the predeclared mapped-neighbor exposure holding own and "
        "lagged exposure fixed."
    ),
    "controlled_history_exposure_response": (
        "Per-unit response to the exact-lag own-treatment history holding current own and "
        "mapped-neighbor exposure fixed."
    ),
    "market_total_effect": (
        "Full-horizon all-zone treatment versus all-zero under the benchmark's additive "
        "exposure mapping and startup history convention."
    ),
}


@dataclass(frozen=True, slots=True)
class InterferenceBenchmarkConfig:
    """Laptop-safe configuration for the mapped-exposure Monte Carlo benchmark.

    The benchmark uses one randomized geographic cluster per zone.  This makes the
    ring exposure map cross randomized arms and keeps cluster counts unambiguous.
    Stage two randomizes individual opportunities within each zone-period cell.
    """

    replications: int = 24
    seed: int = 880_321
    n_zones: int = 32
    n_clusters: int = 32
    n_periods: int = 32
    individuals_per_cell: int = 20
    saturation_levels: tuple[float, ...] = (0.0, 1.0 / 3.0, 2.0 / 3.0, 1.0)
    history_lags: int = 1
    own_effect: float = 2.0
    neighbor_effect: float = 1.5
    history_effect: float = 0.7
    outcome_noise_sd: float = 0.08
    cluster_noise_sd: float = 0.04
    confidence_level: float = 0.95
    minimum_inference_clusters: int = 8

    def __post_init__(self) -> None:
        integer_values = {
            "replications": self.replications,
            "seed": self.seed,
            "n_zones": self.n_zones,
            "n_clusters": self.n_clusters,
            "n_periods": self.n_periods,
            "individuals_per_cell": self.individuals_per_cell,
            "history_lags": self.history_lags,
            "minimum_inference_clusters": self.minimum_inference_clusters,
        }
        for name, value in integer_values.items():
            if isinstance(value, bool) or not isinstance(value, Integral):
                raise ValueError(f"{name} must be an integer")
        if self.replications < 2:
            raise ValueError("replications must be at least two")
        if self.n_zones < 4:
            raise ValueError("n_zones must be at least four for the two-neighbor ring")
        if self.n_clusters != self.n_zones:
            raise ValueError("this benchmark requires one randomized cluster per zone")
        if self.n_periods <= self.history_lags + 1:
            raise ValueError("n_periods must leave at least two complete history periods")
        if self.individuals_per_cell < 1:
            raise ValueError("individuals_per_cell must be positive")
        if self.history_lags < 1:
            raise ValueError("history_lags must be at least one")
        if self.minimum_inference_clusters < 2:
            raise ValueError("minimum_inference_clusters must be at least two")
        if not 0.5 < self.confidence_level < 1.0:
            raise ValueError("confidence_level must lie between 0.5 and 1")

        numeric_values = {
            "own_effect": self.own_effect,
            "neighbor_effect": self.neighbor_effect,
            "history_effect": self.history_effect,
            "outcome_noise_sd": self.outcome_noise_sd,
            "cluster_noise_sd": self.cluster_noise_sd,
        }
        for name, value in numeric_values.items():
            if not isinstance(value, Real) or not isfinite(float(value)):
                raise ValueError(f"{name} must be a finite number")
        if self.outcome_noise_sd < 0 or self.cluster_noise_sd < 0:
            raise ValueError("noise standard deviations must be non-negative")

        levels = tuple(float(value) for value in self.saturation_levels)
        object.__setattr__(self, "saturation_levels", levels)
        # Reuse the assignment contract as the canonical saturation validation.
        TwoStageSaturationConfig(
            n_clusters=self.n_clusters,
            individuals_per_cell=self.individuals_per_cell,
            saturation_levels=levels,
            seed=self.seed,
        )
        if not any(0.0 < level < 1.0 for level in levels):
            raise ValueError(
                "saturation_levels must include an interior arm to separate current "
                "treatment from lagged history in this benchmark"
            )


@dataclass(frozen=True, slots=True)
class InterferenceEstimands:
    """Known controlled slopes and the distinct full-policy market contrast."""

    controlled_zone_direct_effect: float
    spillover_effect: float
    controlled_history_exposure_response: float
    full_horizon_persistent_effect: float
    market_total_effect: float

    def to_dict(self) -> dict[str, float]:
        return {
            name: float(value)
            for name, value in asdict(self).items()
        }


@dataclass(frozen=True)
class InterferenceBenchmarkResult:
    """Replication records, fit audit, summaries, failures, and provenance."""

    records: pd.DataFrame
    summary: pd.DataFrame
    fit_ledger: pd.DataFrame
    failures: pd.DataFrame
    metadata: Mapping[str, Any]


def known_interference_estimands(
    config: InterferenceBenchmarkConfig | None = None,
) -> InterferenceEstimands:
    """Return the benchmark truths without running a Monte Carlo simulation."""

    cfg = config or InterferenceBenchmarkConfig()
    supported_history_periods = cfg.n_periods - cfg.history_lags
    persistent = cfg.history_effect * supported_history_periods / cfg.n_periods
    return InterferenceEstimands(
        controlled_zone_direct_effect=float(cfg.own_effect),
        spillover_effect=float(cfg.neighbor_effect),
        controlled_history_exposure_response=float(cfg.history_effect),
        full_horizon_persistent_effect=float(persistent),
        market_total_effect=float(cfg.own_effect + cfg.neighbor_effect + persistent),
    )


def _ring_edges(n_zones: int) -> pd.DataFrame:
    focal = np.repeat(np.arange(n_zones), 2)
    return pd.DataFrame(
        {
            "focal_zone_id": focal,
            "neighbor_zone_id": np.column_stack(
                [
                    (np.arange(n_zones) - 1) % n_zones,
                    (np.arange(n_zones) + 1) % n_zones,
                ]
            ).reshape(-1),
            "weight": 0.5,
        }
    )


def _replication_seeds(seed: int, replications: int) -> tuple[tuple[int, int], ...]:
    children = np.random.SeedSequence(seed).spawn(replications)
    pairs: list[tuple[int, int]] = []
    for child in children:
        state = child.generate_state(2, dtype=np.uint32)
        pairs.append((int(state[0]), int(state[1])))
    return tuple(pairs)


def _simulate_exposure_dgp(
    config: InterferenceBenchmarkConfig,
    *,
    assignment_seed: int,
    outcome_seed: int,
) -> pd.DataFrame:
    units = pd.MultiIndex.from_product(
        [range(config.n_periods), range(config.n_zones)],
        names=["period_id", "zone_id"],
    ).to_frame(index=False)
    assignment = two_stage_saturation_assignment(
        units,
        TwoStageSaturationConfig(
            n_clusters=config.n_clusters,
            individuals_per_cell=config.individuals_per_cell,
            saturation_levels=config.saturation_levels,
            seed=assignment_seed,
        ),
    )
    frame = add_mapped_exposures(
        assignment,
        _ring_edges(config.n_zones),
        history_lags=config.history_lags,
    )

    zone_angle = 2.0 * np.pi * frame["zone_id"].to_numpy(dtype=float) / config.n_zones
    period_angle = (
        2.0 * np.pi * frame["period_id"].to_numpy(dtype=float) / config.n_periods
    )
    frame["baseline_state"] = np.sin(zone_angle) + 0.25 * np.cos(2.0 * zone_angle)
    frame["period_sin"] = np.sin(period_angle)
    frame["period_cos"] = np.cos(period_angle)

    rng = np.random.default_rng(outcome_seed)
    cluster_shocks = rng.normal(0.0, config.cluster_noise_sd, config.n_clusters)
    history_for_outcome = frame["history_exposure"].fillna(0.0).to_numpy(dtype=float)
    frame["outcome"] = (
        8.0
        + 0.35 * frame["baseline_state"].to_numpy(dtype=float)
        + 0.20 * frame["period_sin"].to_numpy(dtype=float)
        - 0.15 * frame["period_cos"].to_numpy(dtype=float)
        + cluster_shocks[frame["cluster_id"].to_numpy(dtype=int)]
        + config.own_effect * frame["treatment"].to_numpy(dtype=float)
        + config.neighbor_effect * frame["neighbor_exposure"].to_numpy(dtype=float)
        + config.history_effect * history_for_outcome
        + rng.normal(0.0, config.outcome_noise_sd, len(frame))
    )
    frame["dgp_evidence_type"] = "semi_synthetic_exposure_mapped_known_truth"
    frame["assignment_seed"] = int(assignment_seed)
    frame["outcome_seed"] = int(outcome_seed)
    return frame


def _mapped_records(
    frame: pd.DataFrame,
    config: InterferenceBenchmarkConfig,
    truths: InterferenceEstimands,
    *,
    replication: int,
    assignment_seed: int,
    outcome_seed: int,
) -> list[dict[str, Any]]:
    estimates = estimate_exposure_response(
        frame,
        ExposureMappingConfig(
            outcome="outcome",
            own_exposure="treatment",
            neighbor_exposure="neighbor_exposure",
            history_exposure="history_exposure",
            cluster="randomization_cluster",
            covariates=("baseline_state", "period_sin", "period_cos"),
            alpha=1.0 - config.confidence_level,
            minimum_inference_clusters=config.minimum_inference_clusters,
        ),
    )
    truth_values = truths.to_dict()
    records: list[dict[str, Any]] = []
    for estimate in estimates.to_dict("records"):
        target = str(estimate["target_estimand"])
        truth = truth_values[target]
        records.append(
            {
                **estimate,
                "design": "two_stage_saturation",
                "estimator": "exposure_mapped_cluster_regression",
                "replication": replication,
                "seed": assignment_seed,
                "assignment_seed": assignment_seed,
                "outcome_seed": outcome_seed,
                "std_error": float(estimate["standard_error"]),
                "truth": truth,
                "market_total_truth": truths.market_total_effect,
                "estimation_error": float(estimate["estimate"]) - truth,
                "diagnostic_gap_to_market_total": np.nan,
                "identified": True,
                "comparison_status": "identified_controlled_exposure_response",
                "coefficient_inference_cluster_aware": True,
                "inference_valid_for_target": bool(estimate["inference_valid"]),
                "controlled_exposure_not_market_total": True,
                "fit_status": "ok",
                "design_cost": float(config.n_zones * config.n_periods),
                "evidence_type": "semi_synthetic_exposure_mapped_known_truth",
                "estimand_definition": ESTIMAND_DEFINITIONS[target],
            }
        )
    return records


def _naive_record(
    frame: pd.DataFrame,
    config: InterferenceBenchmarkConfig,
    truths: InterferenceEstimands,
    *,
    replication: int,
    assignment_seed: int,
    outcome_seed: int,
) -> dict[str, Any]:
    estimate = cluster_robust(
        frame,
        EstimatorConfig(
            method="cluster_robust",
            outcome="outcome",
            treatment="cluster_saturation",
            covariates=("baseline_state", "period_sin", "period_cos"),
            cluster="randomization_cluster",
            target_estimand="market_total_effect",
            alpha=1.0 - config.confidence_level,
        ),
    )
    return {
        "method": "cluster_robust",
        "exposure_term": "cluster_saturation",
        "target_estimand": "market_total_effect",
        "coefficient_estimand": "stage_one_saturation_assignment_slope",
        "design": "two_stage_saturation",
        "estimator": "naive_assignment_cluster_regression",
        "replication": replication,
        "seed": assignment_seed,
        "assignment_seed": assignment_seed,
        "outcome_seed": outcome_seed,
        "estimate": estimate.estimate,
        "standard_error": estimate.standard_error,
        "std_error": estimate.standard_error,
        "ci_low": estimate.ci_low,
        "ci_high": estimate.ci_high,
        "p_value": estimate.p_value,
        "n_obs": estimate.n_obs,
        "n_clusters": int(estimate.diagnostics["n_clusters"]),
        "truth": truths.market_total_effect,
        "market_total_truth": truths.market_total_effect,
        "estimation_error": np.nan,
        "diagnostic_gap_to_market_total": estimate.estimate - truths.market_total_effect,
        "identified": False,
        "comparison_status": "target_mismatch",
        "coefficient_inference_cluster_aware": True,
        "inference_valid": int(estimate.diagnostics["n_clusters"])
        >= config.minimum_inference_clusters,
        "inference_valid_for_target": False,
        "controlled_exposure_not_market_total": False,
        "fit_status": "ok",
        "design_cost": float(config.n_zones * config.n_periods),
        "effect_scale": "stage-one saturation coefficient; not full-policy market total",
        "identification_scope": (
            "Randomization identifies an assignment-saturation contrast. Omitted mapped "
            "neighbor and history exposures prevent relabeling it as market_total_effect."
        ),
        "evidence_type": "semi_synthetic_assignment_diagnostic_target_mismatch",
        "estimand_definition": ESTIMAND_DEFINITIONS["market_total_effect"],
    }


def _fit_ledger(
    records: pd.DataFrame,
    failures: pd.DataFrame,
    config: InterferenceBenchmarkConfig,
) -> pd.DataFrame:
    plans = [
        {
            "estimator": "exposure_mapped_cluster_regression",
            "target_estimand": target,
            "identified": True,
            "comparison_status": "identified_controlled_exposure_response",
        }
        for target in MAPPED_TARGETS.values()
    ]
    plans.append(
        {
            "estimator": "naive_assignment_cluster_regression",
            "target_estimand": "market_total_effect",
            "identified": False,
            "comparison_status": "target_mismatch",
        }
    )
    ledger = pd.DataFrame(plans)
    keys = ["estimator", "target_estimand"]
    successful = (
        records.loc[records["fit_status"].eq("ok")]
        .groupby(keys)
        .size()
        .rename("successful_fits")
        .reset_index()
    )
    ledger = ledger.merge(successful, on=keys, how="left", validate="one_to_one")
    ledger["attempted_fits"] = int(config.replications)
    ledger["successful_fits"] = ledger["successful_fits"].fillna(0).astype(int)
    ledger["failed_fits"] = ledger["attempted_fits"] - ledger["successful_fits"]
    ledger["fit_complete"] = ledger["failed_fits"].eq(0)
    ledger["fit_success_rate"] = ledger["successful_fits"] / ledger["attempted_fits"]

    inference = (
        records.groupby(keys)["inference_valid_for_target"]
        .mean()
        .rename("target_inference_valid_rate")
        .reset_index()
    )
    ledger = ledger.merge(inference, on=keys, how="left", validate="one_to_one")
    ledger["target_inference_valid_rate"] = (
        ledger["target_inference_valid_rate"].fillna(0.0)
    )
    ledger["decision_eligible"] = (
        ledger["identified"]
        & ledger["fit_complete"]
        & ledger["target_inference_valid_rate"].eq(1.0)
    )
    ledger["recorded_failure_rows"] = int(len(failures))
    ledger["evidence_type"] = "semi_synthetic_benchmark_fit_ledger"
    return ledger.sort_values(keys).reset_index(drop=True)


def _benchmark_summary(
    records: pd.DataFrame,
    fit_ledger: pd.DataFrame,
    config: InterferenceBenchmarkConfig,
    truths: InterferenceEstimands,
) -> pd.DataFrame:
    mapped = records.loc[records["identified"] & records["fit_status"].eq("ok")].copy()
    if mapped.empty:
        mapped_summary = pd.DataFrame()
    else:
        mapped_summary = summarize_monte_carlo(
            mapped,
            confidence_level=config.confidence_level,
            group_columns=["design", "estimator", "target_estimand"],
        )
        mapped_summary["identified"] = True
        mapped_summary["comparison_status"] = "identified_controlled_exposure_response"
        mapped_summary["market_total_truth"] = truths.market_total_effect
        mapped_summary["controlled_exposure_not_market_total"] = True
        mapped_summary["diagnostic_mean_gap_to_market_total"] = np.nan
        mapped_summary["diagnostic_gap_mcse"] = np.nan
        mapped_summary["evidence_type"] = (
            "semi_synthetic_exposure_mapped_known_truth_monte_carlo"
        )

        inference = (
            mapped.groupby(["design", "estimator", "target_estimand"])[
                "inference_valid_for_target"
            ]
            .all()
            .rename("inference_valid_for_target")
            .reset_index()
        )
        mapped_summary = mapped_summary.merge(
            inference,
            on=["design", "estimator", "target_estimand"],
            how="left",
            validate="one_to_one",
        )
        invalid = ~mapped_summary["inference_valid_for_target"].astype(bool)
        mapped_summary.loc[
            invalid,
            ["coverage", "coverage_mcse", "power", "power_mcse"],
        ] = np.nan
        mapped_summary["withheld_reason"] = np.where(
            invalid,
            "cluster count is below the predeclared inference minimum",
            None,
        )

    naive = records.loc[
        records["estimator"].eq("naive_assignment_cluster_regression")
        & records["fit_status"].eq("ok")
    ].copy()
    if naive.empty:
        naive_summary = pd.DataFrame()
    else:
        diagnostic = naive["diagnostic_gap_to_market_total"].astype(float)
        naive_row: dict[str, Any] = {
            "design": "two_stage_saturation",
            "estimator": "naive_assignment_cluster_regression",
            "target_estimand": "market_total_effect",
            "truth": truths.market_total_effect,
            "mean_estimate": float(naive["estimate"].mean()),
            "bias": np.nan,
            "bias_mcse": np.nan,
            "variance": float(naive["estimate"].var(ddof=1)),
            "rmse": np.nan,
            "rmse_mcse": np.nan,
            "coverage": np.nan,
            "coverage_mcse": np.nan,
            "power": np.nan,
            "power_mcse": np.nan,
            "mean_std_error": float(naive["std_error"].mean()),
            "replications": int(len(naive)),
            "mean_design_cost": float(naive["design_cost"].mean()),
            "information_cost": np.nan,
            "confidence_level": config.confidence_level,
            "identified": False,
            "comparison_status": "target_mismatch",
            "market_total_truth": truths.market_total_effect,
            "controlled_exposure_not_market_total": False,
            "diagnostic_mean_gap_to_market_total": float(diagnostic.mean()),
            "diagnostic_gap_mcse": float(
                diagnostic.std(ddof=1) / np.sqrt(len(diagnostic))
            ),
            "inference_valid_for_target": False,
            "withheld_reason": (
                "The stage-one saturation coefficient omits mapped neighbor and history "
                "exposures; bias, RMSE, coverage, and power for market_total_effect are withheld."
            ),
            "evidence_type": "semi_synthetic_assignment_diagnostic_target_mismatch",
        }
        naive_summary = pd.DataFrame([naive_row])

    summary = pd.concat([mapped_summary, naive_summary], ignore_index=True, sort=False)
    fit_columns = [
        "estimator",
        "target_estimand",
        "fit_complete",
        "successful_fits",
        "failed_fits",
        "decision_eligible",
    ]
    summary = summary.merge(
        fit_ledger[fit_columns],
        on=["estimator", "target_estimand"],
        how="left",
        validate="one_to_one",
    )
    return summary.sort_values(["identified", "target_estimand"], ascending=[False, True]).reset_index(
        drop=True
    )


def run_interference_benchmark(
    config: InterferenceBenchmarkConfig | None = None,
) -> InterferenceBenchmarkResult:
    """Run deterministic known-truth exposure and naive-assignment comparisons."""

    cfg = config or InterferenceBenchmarkConfig()
    truths = known_interference_estimands(cfg)
    records: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    for replication, (assignment_seed, outcome_seed) in enumerate(
        _replication_seeds(cfg.seed, cfg.replications)
    ):
        frame = _simulate_exposure_dgp(
            cfg,
            assignment_seed=assignment_seed,
            outcome_seed=outcome_seed,
        )
        try:
            records.extend(
                _mapped_records(
                    frame,
                    cfg,
                    truths,
                    replication=replication,
                    assignment_seed=assignment_seed,
                    outcome_seed=outcome_seed,
                )
            )
        except (ValueError, np.linalg.LinAlgError) as exc:
            for target in MAPPED_TARGETS.values():
                failures.append(
                    {
                        "replication": replication,
                        "assignment_seed": assignment_seed,
                        "outcome_seed": outcome_seed,
                        "estimator": "exposure_mapped_cluster_regression",
                        "target_estimand": target,
                        "stage": "estimation",
                        "error": str(exc),
                    }
                )
        try:
            records.append(
                _naive_record(
                    frame,
                    cfg,
                    truths,
                    replication=replication,
                    assignment_seed=assignment_seed,
                    outcome_seed=outcome_seed,
                )
            )
        except (ValueError, np.linalg.LinAlgError) as exc:
            failures.append(
                {
                    "replication": replication,
                    "assignment_seed": assignment_seed,
                    "outcome_seed": outcome_seed,
                    "estimator": "naive_assignment_cluster_regression",
                    "target_estimand": "market_total_effect",
                    "stage": "estimation",
                    "error": str(exc),
                }
            )

    record_frame = pd.DataFrame(records)
    if record_frame.empty:
        raise RuntimeError("interference benchmark produced no successful fits")
    failure_frame = pd.DataFrame(
        failures,
        columns=[
            "replication",
            "assignment_seed",
            "outcome_seed",
            "estimator",
            "target_estimand",
            "stage",
            "error",
        ],
    )
    fit_ledger = _fit_ledger(record_frame, failure_frame, cfg)
    summary = _benchmark_summary(record_frame, fit_ledger, cfg, truths)
    metadata: dict[str, Any] = {
        "evidence_type": "semi_synthetic_exposure_mapped_known_truth_benchmark",
        "config": asdict(cfg),
        "known_estimands": truths.to_dict(),
        "estimand_definitions": dict(ESTIMAND_DEFINITIONS),
        "assignment_design": (
            "balanced geographic cluster saturation arms followed by independent "
            "within-zone-period opportunity assignment"
        ),
        "exposure_mapping": "two equal-weight ring neighbors declared before outcomes",
        "history_mapping": f"mean of {cfg.history_lags} exact own-treatment lag(s)",
        "market_total_bridge": (
            "Known only because this benchmark declares an additive exposure-response DGP; "
            "controlled coefficients are not individually relabeled as market_total_effect."
        ),
        "naive_assignment_status": (
            "target mismatch; coefficient uncertainty is cluster-aware, but market-total "
            "bias, RMSE, coverage, and power are withheld"
        ),
    }
    return InterferenceBenchmarkResult(
        records=record_frame.sort_values(
            ["replication", "estimator", "target_estimand"]
        ).reset_index(drop=True),
        summary=summary,
        fit_ledger=fit_ledger,
        failures=failure_frame,
        metadata=metadata,
    )


__all__ = [
    "InterferenceBenchmarkConfig",
    "InterferenceBenchmarkResult",
    "InterferenceEstimands",
    "known_interference_estimands",
    "run_interference_benchmark",
]
