"""Interactive experiment-design decision interface.

The Streamlit renderer in this module is deliberately thin.  Configuration,
simulation, benchmark matching, and recommendation logic are ordinary Python
functions so they can be tested without starting a web server.  Every numerical
quantity shown by the app is either read from a provenance-labelled benchmark
artifact or generated on demand by the semi-synthetic simulator.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd

from casuallab.config import (
    DesignConfig,
    DesignName,
    EstimatorConfig,
    SimulationConfig,
    TreatmentVersion,
)
from casuallab.estimands import EstimandName, get_estimand, identification_assessment
from casuallab.reporting import choose_recommendation, design_limitations
from casuallab.simulator import SimulationResult, simulate_market

TARGET_ESTIMAND: Final[str] = EstimandName.MARKET_TOTAL.value
SUPPORTED_DESIGNS: Final[tuple[str, ...]] = tuple(member.value for member in DesignName)
DESIGN_LABELS: Final[Mapping[str, str]] = {
    DesignName.INDIVIDUAL.value: "Individual assignment",
    DesignName.GEO_CLUSTER.value: "Geographic clusters",
    DesignName.TIME_BLOCK.value: "Marketplace time blocks",
    DesignName.SWITCHBACK.value: "Marketplace switchback",
    DesignName.GEO_TIME.value: "Geo × time clusters",
}
TREATMENT_VERSION_LABELS: Final[Mapping[str, str]] = {
    TreatmentVersion.RIDER_DISCOUNT.value: "Rider discount only",
    TreatmentVersion.DRIVER_INCENTIVE.value: "Driver incentive only",
    TreatmentVersion.BUNDLED.value: "Bundled rider + driver treatment",
}
CALIBRATION_EVIDENCE_TYPES: Final[frozenset[str]] = frozenset(
    {
        "empirical_association_for_semisynthetic_calibration",
        "illustrative_empirical_scale_anchor",
    }
)


@dataclass(frozen=True, slots=True)
class DashboardControls:
    """User-editable assumptions for one decision scenario.

    ``experiment_duration`` is the full evaluation horizon, while
    ``treatment_duration`` is the assignment-block length used by temporal designs.
    Geographic scenarios use two zones per requested cluster so that the number of
    independent assignment groups is explicit without adding another UI control.
    """

    randomization_unit: str = DesignName.GEO_CLUSTER.value
    treatment_version: str = TreatmentVersion.BUNDLED.value
    experiment_duration: int = 48
    # These defaults deliberately match the precomputed ``cluster_count_variant``
    # benchmark cell.  The dashboard therefore opens with auditable recovery
    # evidence instead of an arbitrary scenario for which no Monte Carlo artifact
    # exists; every control remains editable.
    n_clusters: int = 8
    spillover_strength: float = 0.0
    persistence: float = 0.0
    incentive_size: float = 1.50
    budget: float = 10_000.0
    treatment_duration: int = 4
    washout_periods: int = 0
    treatment_saturation: float = 1.0
    treatment_probability: float = 0.5
    replications: int = 5
    seed: int = 202_503
    target_estimand: str = TARGET_ESTIMAND

    def __post_init__(self) -> None:
        design = DesignName.parse(self.randomization_unit).value
        target = EstimandName.parse(self.target_estimand).value
        treatment_version = TreatmentVersion.parse(self.treatment_version).value
        object.__setattr__(self, "randomization_unit", design)
        object.__setattr__(self, "target_estimand", target)
        object.__setattr__(self, "treatment_version", treatment_version)
        if target != TARGET_ESTIMAND:
            raise ValueError(
                "the dashboard benchmark currently targets market_total_effect; "
                "other structural truths remain available through casuallab.estimands"
            )
        if self.experiment_duration < 4:
            raise ValueError("experiment_duration must be at least 4 periods")
        if self.n_clusters < 2:
            raise ValueError("n_clusters must be at least 2")
        if self.treatment_duration < 1:
            raise ValueError("treatment_duration must be positive")
        if self.treatment_duration * 2 > self.experiment_duration:
            raise ValueError("experiment_duration must contain at least two treatment blocks")
        if not 0 <= self.washout_periods < self.treatment_duration:
            raise ValueError("washout_periods must be shorter than treatment_duration")
        if not 0 <= self.spillover_strength <= 1:
            raise ValueError("spillover_strength must lie in [0, 1]")
        if not 0 <= self.persistence < 1:
            raise ValueError("persistence must lie in [0, 1)")
        if self.incentive_size < 0:
            raise ValueError("incentive_size cannot be negative")
        if self.budget < 0:
            raise ValueError("budget cannot be negative")
        if not 0 < self.treatment_saturation <= 1:
            raise ValueError("treatment_saturation must lie in (0, 1]")
        if not 0 < self.treatment_probability < 1:
            raise ValueError("treatment_probability must lie in (0, 1)")
        if self.replications < 2:
            raise ValueError("replications must be at least 2")


@dataclass(frozen=True)
class ScenarioBenchmark:
    """On-demand structural outcomes and assignment-contrast diagnostics."""

    controls: DashboardControls
    records: pd.DataFrame
    summary: pd.DataFrame
    limitations: tuple[str, ...]
    calibration_path: Path | None = None
    calibration_sha256: str | None = None
    evidence_type: str = "semi_synthetic_structural_scenario"

    @property
    def selected(self) -> pd.Series:
        rows = self.summary.loc[self.summary["design"] == self.controls.randomization_unit]
        if len(rows) != 1:
            raise ValueError("scenario summary must contain one row for the selected design")
        return rows.iloc[0]


@dataclass(frozen=True)
class BenchmarkArtifact:
    """A validated generated benchmark and its file provenance."""

    path: Path
    summary: pd.DataFrame
    declared_scenarios: tuple[str, ...]
    lineage_validated: bool = False


@dataclass(frozen=True)
class ArtifactDecision:
    """Artifact rows matched on available fields and an identification-safe choice."""

    rows: pd.DataFrame
    recommendation: pd.Series
    missing_dimensions: tuple[str, ...]
    recommendation_scope: str
    matched_scenarios: tuple[str, ...]
    unmatched_scenarios: tuple[str, ...]


@dataclass(frozen=True)
class CalibrationTemplate:
    """Validated descriptive calibration used as a simulation template."""

    path: Path
    config: SimulationConfig
    sha256: str
    evidence_type: str


@dataclass(frozen=True, slots=True)
class EvidenceLayerStatus:
    """Read-only availability and interpretation of one lineage-verified evidence layer."""

    key: str
    title: str
    classification: str
    interpretation: str
    available: bool
    detail: str
    manifest_path: Path | None = None
    manifest_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class _EvidenceLayerSpec:
    key: str
    title: str
    relative_manifest: str
    classification: str
    interpretation: str


_EVIDENCE_LAYER_SPECS: Final[tuple[_EvidenceLayerSpec, ...]] = (
    _EvidenceLayerSpec(
        key="nyc_informed",
        title="NYC-informed marketplace benchmark",
        relative_manifest="artifacts/benchmarks/nyc_informed/manifest.json",
        classification="Semi-synthetic known truth",
        interpretation=(
            "NYC descriptive moments initialize the simulator; treatment effects are known "
            "only inside the declared simulator and are not NYC causal estimates."
        ),
    ),
    _EvidenceLayerSpec(
        key="nyc_graph",
        title="NYC OD-graph interference benchmark",
        relative_manifest="artifacts/benchmarks/nyc_graph/manifest.json",
        classification="Semi-synthetic known truth",
        interpretation=(
            "Observed NYC OD weights define exposure geometry only; spillover coefficients "
            "and outcomes come from a declared known-truth DGP."
        ),
    ),
    _EvidenceLayerSpec(
        key="equilibrium",
        title="Two-sided fixed-point equilibrium benchmark",
        relative_manifest="artifacts/benchmarks/equilibrium/manifest.json",
        classification="Theoretical equilibrium known truth",
        interpretation=(
            "A transparent theoretical fixed point under assumed parameters; explicitly not "
            "an NYC structural estimate."
        ),
    ),
    _EvidenceLayerSpec(
        key="weather",
        title="NYC observed weather enrichment",
        relative_manifest="artifacts/nyc_full/weather/manifest.json",
        classification="Descriptive observed data — non-causal",
        interpretation=(
            "Verified NOAA weather is joined to published NYC completed trips for descriptive "
            "associations only; it does not identify a causal weather shock."
        ),
    ),
    _EvidenceLayerSpec(
        key="events",
        title="NYC official-calendar and permitted-event enrichment",
        relative_manifest="artifacts/nyc_full/events/manifest.json",
        classification="Descriptive observed data — non-causal",
        interpretation=(
            "Official holiday dates and permitted-event windows define citywide daily "
            "descriptors only. Permits are not attendance or zone/hour exposure, and "
            "weekend composition confounds the raw contrast."
        ),
    ),
    _EvidenceLayerSpec(
        key="income",
        title="NYC neighborhood-income heterogeneity",
        relative_manifest="artifacts/nyc_full/income/manifest.json",
        classification="Descriptive ecological data — non-causal",
        interpretation=(
            "Official geometry and ACS B19001 distributions describe Taxi Zone groups. "
            "Area income is not rider or driver income and does not identify an income effect."
        ),
    ),
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _source_tree_sha256(project_root: Path) -> str:
    """Hash executable source/config inputs using the reproduction contract."""

    digest = hashlib.sha256()
    candidates = [
        *project_root.joinpath("src").rglob("*.py"),
        *project_root.joinpath("configs").rglob("*.yaml"),
        project_root / "pyproject.toml",
        project_root / "constraints.txt",
        project_root / "Makefile",
    ]
    for path in sorted({item for item in candidates if item.is_file()}):
        digest.update(str(path.relative_to(project_root)).encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


@lru_cache(maxsize=4)
def load_calibration_template(
    path: str | Path | None = None,
) -> CalibrationTemplate | None:
    """Load the generated descriptive calibration without treating it as causal evidence."""

    source = (
        _project_root() / "artifacts" / "reports" / "calibration.json"
        if path is None
        else Path(path)
    )
    if not source.is_file():
        return None
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("calibration artifact root must be a mapping")
    evidence_type = str(payload.get("evidence_type", ""))
    if evidence_type not in CALIBRATION_EVIDENCE_TYPES:
        raise ValueError(
            "calibration artifact must carry an approved descriptive scale-anchor label"
        )
    raw_config = payload.get("simulation_config")
    if not isinstance(raw_config, Mapping):
        raise ValueError("calibration artifact has no simulation_config mapping")
    return CalibrationTemplate(
        path=source.resolve(),
        config=SimulationConfig.from_dict(raw_config),
        sha256=_sha256(source),
        evidence_type=evidence_type,
    )


def build_simulation_config(
    controls: DashboardControls,
    *,
    design: str | DesignName | None = None,
    seed: int | None = None,
    base_config: SimulationConfig | None = None,
) -> SimulationConfig:
    """Translate inputs onto a calibrated template, or package defaults if absent."""

    design_name = DesignName.parse(design or controls.randomization_unit)
    simulation_seed = controls.seed if seed is None else int(seed)
    if base_config is None:
        calibration = load_calibration_template()
        base_config = calibration.config if calibration is not None else SimulationConfig()
    n_zones = max(4, controls.n_clusters * 2)
    cluster_size = max(1, int(np.ceil(n_zones / controls.n_clusters)))
    effective_washout = (
        controls.washout_periods
        if design_name in {DesignName.TIME_BLOCK, DesignName.SWITCHBACK, DesignName.GEO_TIME}
        else 0
    )
    design_config = DesignConfig(
        name=design_name,
        treatment_probability=controls.treatment_probability,
        treatment_saturation=controls.treatment_saturation,
        n_clusters=controls.n_clusters,
        cluster_size=cluster_size,
        treatment_duration=controls.treatment_duration,
        washout_periods=effective_washout,
        budget=controls.budget,
        seed=simulation_seed + 1,
    )
    return replace(
        base_config,
        n_zones=n_zones,
        n_periods=controls.experiment_duration,
        treatment_version=TreatmentVersion.parse(controls.treatment_version),
        incentive_per_driver=controls.incentive_size,
        spillover_strength=controls.spillover_strength,
        persistence=controls.persistence,
        budget=controls.budget,
        seed=simulation_seed,
        design=design_config,
    )


def _estimator_config(design: str, target_estimand: str, seed: int) -> EstimatorConfig:
    """Use assignment-scale regression for individual saturation and clustered ITT otherwise."""

    if design == DesignName.INDIVIDUAL.value:
        return EstimatorConfig(
            method="regression_adjustment",
            outcome="outcome",
            treatment="assigned_treatment",
            covariates=(
                "baseline_demand",
                "baseline_supply",
                "hour_sin",
                "hour_cos",
            ),
            target_estimand=target_estimand,
            seed=seed,
        )
    return EstimatorConfig(
        method="cluster_robust",
        outcome="outcome",
        treatment="assigned_treatment",
        cluster="randomization_cluster",
        target_estimand=target_estimand,
        seed=seed,
    )


def _estimate_simulation(
    result: SimulationResult, controls: DashboardControls
) -> Mapping[str, Any]:
    """Return structural truth and a separate, target-mismatched assignment diagnostic."""

    # Import lazily so reading configuration or benchmark artifacts does not require
    # the estimation stack to initialize (and keeps dashboard import side-effect free).
    from casuallab.estimators import estimate_effect

    design = str(result.metadata["design"])
    config = _estimator_config(
        design, controls.target_estimand, int(result.metadata["simulation_seed"])
    )
    estimate = estimate_effect(result.panel, config)
    full_policy_effect = result.ground_truth.get(controls.target_estimand)
    if full_policy_effect is None or not np.isfinite(full_policy_effect):
        raise ValueError(f"simulator did not produce finite truth for {controls.target_estimand!r}")
    standard_error = float(estimate.standard_error)
    if not np.isfinite(standard_error) or standard_error <= 0:
        raise ValueError(
            f"{estimate.method} produced invalid uncertainty for {design}; "
            "increase clusters or experiment duration"
        )

    incremental = float(result.ground_truth["incremental_trips"])
    incremental_welfare = float(result.ground_truth["incremental_welfare"])
    full_policy_spend = float(result.ground_truth["full_policy_spend"])
    efficiency = incremental / full_policy_spend if full_policy_spend > 1e-12 else np.nan
    welfare_efficiency = (
        incremental_welfare / full_policy_spend if full_policy_spend > 1e-12 else np.nan
    )
    realized_spend = float(result.metadata["realized_spend"])
    return {
        "assignment_estimate": float(estimate.estimate),
        "assignment_std_error": standard_error,
        "assignment_p_value": float(estimate.p_value),
        "full_policy_truth": float(full_policy_effect),
        "target_estimand": controls.target_estimand,
        "treatment_version": str(result.metadata["treatment_version"]),
        "treatment_version_limitation": str(
            result.metadata["treatment_version_limitation"]
        ),
        "estimator": str(estimate.method),
        "expected_incremental_outcome": incremental,
        "modeled_incremental_welfare": incremental_welfare,
        "full_policy_spend": full_policy_spend,
        "realized_schedule_spend": realized_spend,
        "budget_efficiency": efficiency,
        "modeled_welfare_per_dollar": welfare_efficiency,
        "realized_schedule_budget_scale": float(result.metadata["budget_scale"]),
        "full_policy_budget_scale": float(result.metadata["all_treated_budget_scale"]),
        "effective_clusters": int(estimate.diagnostics.get("n_clusters", estimate.n_obs)),
        "target_alignment": "target_mismatch_assignment_diagnostic",
        "evidence_type": "semi_synthetic_structural_known_truth",
    }


def _paired_replication_seeds(seed: int, replications: int) -> tuple[int, ...]:
    sequence = np.random.SeedSequence(seed)
    return tuple(
        int(child.generate_state(1, dtype=np.uint32)[0]) for child in sequence.spawn(replications)
    )


def _roll_up_decision_metrics(records: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, float | int | str]] = []
    for design, group in records.groupby("design", sort=True):
        mean_spend = float(group["full_policy_spend"].mean())
        mean_incremental = float(group["expected_incremental_outcome"].mean())
        mean_welfare = float(group["modeled_incremental_welfare"].mean())
        rejection_rate = float((group["assignment_p_value"] < 0.05).mean())
        n_replications = int(len(group))
        rows.append(
            {
                "design": str(design),
                "target_estimand": str(group["target_estimand"].iloc[0]),
                "treatment_version": str(group["treatment_version"].iloc[0]),
                "treatment_version_limitation": str(
                    group["treatment_version_limitation"].iloc[0]
                ),
                "estimator": str(group["estimator"].iloc[0]),
                "full_policy_truth": float(group["full_policy_truth"].mean()),
                "expected_incremental_outcome": mean_incremental,
                "incremental_outcome_mc_sd": float(
                    group["expected_incremental_outcome"].std(ddof=1)
                ),
                "mean_full_policy_spend": mean_spend,
                "budget_efficiency": (
                    mean_incremental / mean_spend if mean_spend > 1e-12 else np.nan
                ),
                "modeled_incremental_welfare": mean_welfare,
                "modeled_welfare_mc_sd": float(group["modeled_incremental_welfare"].std(ddof=1)),
                "modeled_welfare_per_dollar": (
                    mean_welfare / mean_spend if mean_spend > 1e-12 else np.nan
                ),
                "mean_full_policy_budget_scale": float(group["full_policy_budget_scale"].mean()),
                "mean_realized_schedule_budget_scale": float(
                    group["realized_schedule_budget_scale"].mean()
                ),
                "mean_assignment_estimate": float(group["assignment_estimate"].mean()),
                "assignment_estimate_mc_sd": float(group["assignment_estimate"].std(ddof=1)),
                "mean_assignment_std_error": float(group["assignment_std_error"].mean()),
                "assignment_rejection_rate": rejection_rate,
                "assignment_rejection_mcse": float(
                    np.sqrt(rejection_rate * (1.0 - rejection_rate) / n_replications)
                ),
                "effective_clusters": int(round(group["effective_clusters"].mean())),
                "replications": n_replications,
                "target_alignment": "target_mismatch_assignment_diagnostic",
                "scenario_evidence": "on_demand_semi_synthetic_known_truth",
            }
        )
    return pd.DataFrame(rows)


def run_scenario_benchmark(
    controls: DashboardControls,
    *,
    designs: Sequence[str | DesignName] | None = None,
) -> ScenarioBenchmark:
    """Run an on-demand structural scenario and assignment diagnostic.

    The full-policy outcomes are known simulator counterfactuals.  The observed
    assignment coefficient has its own uncertainty and rejection diagnostic, but is
    deliberately *not* compared with full-policy truth as if that gap were bias.
    """

    designs = (controls.randomization_unit,) if designs is None else designs
    normalized_designs = tuple(dict.fromkeys(DesignName.parse(item).value for item in designs))
    if controls.randomization_unit not in normalized_designs:
        normalized_designs = (*normalized_designs, controls.randomization_unit)
    seeds = _paired_replication_seeds(controls.seed, controls.replications)
    rows: list[dict[str, Any]] = []
    for design in normalized_designs:
        for replication, seed in enumerate(seeds):
            config = build_simulation_config(controls, design=design, seed=seed)
            simulation = simulate_market(config)
            metrics = dict(_estimate_simulation(simulation, controls))
            metrics.update(
                {
                    "design": design,
                    "replication": replication,
                    "seed": seed,
                    "spillover_strength": controls.spillover_strength,
                    "persistence": controls.persistence,
                    "duration": controls.experiment_duration,
                    "budget": controls.budget,
                }
            )
            rows.append(metrics)

    records = pd.DataFrame(rows)
    summary = _roll_up_decision_metrics(records)
    summary["compatible_with_estimand"] = summary["design"].map(
        lambda design: _design_is_compatible(str(design), controls)
    )
    limitations = scenario_limitations(controls, summary)
    calibration = load_calibration_template()
    return ScenarioBenchmark(
        controls=controls,
        records=records,
        summary=summary,
        limitations=limitations,
        calibration_path=calibration.path if calibration is not None else None,
        calibration_sha256=calibration.sha256 if calibration is not None else None,
        evidence_type=(
            "semi_synthetic_structural_scenario"
            if calibration is not None
            else "configured_synthetic_structural_scenario"
        ),
    )


def _interference_present(config: SimulationConfig) -> bool:
    return any(
        value > 0
        for value in (
            config.spillover_strength,
            config.rider_substitution,
            config.driver_mobility,
        )
    )


def _design_is_compatible(design: str, controls: DashboardControls) -> bool:
    definition = get_estimand(controls.target_estimand)
    if design not in definition.compatible_designs:
        return False
    config = build_simulation_config(controls, design=design)
    identified, _ = identification_assessment(
        controls.target_estimand,
        design=design,
        interference_present=_interference_present(config),
        exposure_mapped=design == DesignName.GEO_TIME.value,
        histories_observed=True,
    )
    return identified


def recommend_design(
    summary: pd.DataFrame,
    controls: DashboardControls,
    *,
    require_declared_scenarios: bool = True,
) -> pd.Series:
    """Choose only among complete, identified rows with valid finite inference."""

    required = {
        "declared_scenario_count",
        "declared_scenario_set",
        "design",
        "estimator",
        "target_estimand",
        "bias",
        "rmse",
        "coverage",
        "power",
        "identified",
        "inference_valid",
        "fit_complete",
        "applicable",
        "attempted_fits",
        "successful_fits",
    }
    missing = required.difference(summary.columns)
    if missing:
        raise ValueError(f"scenario summary missing recommendation columns: {sorted(missing)}")
    eligible = summary.loc[summary["target_estimand"] == controls.target_estimand].copy()
    for column in ("bias", "rmse", "coverage", "power"):
        eligible[column] = pd.to_numeric(eligible[column], errors="coerce")
    return choose_recommendation(
        eligible,
        controls.target_estimand,
        require_declared_scenarios=require_declared_scenarios,
    )


def scenario_limitations(
    controls: DashboardControls,
    summary: pd.DataFrame,
) -> tuple[str, ...]:
    """Return scenario-specific caveats, never numerical causal claims."""

    design = controls.randomization_unit
    selected = summary.loc[summary["design"] == design]
    if len(selected) != 1:
        raise ValueError("scenario limitations require one selected-design summary row")
    selected_row = selected.iloc[0]
    limitations = [
        (
            "All displayed causal quantities are semi-synthetic outputs under the declared "
            "structural model; public trip data only calibrate broad moments and do not supply "
            "an empirical treatment effect."
        ),
        (
            "The simulator uses a row-normalized ring exposure map. Production leakage, "
            "platform equilibrium responses, and strategic behavior can differ."
        ),
        (
            "The incentive control changes payment cost and linearly scales the configured "
            "driver-response channels relative to the reference dose. That mapping is a "
            "semi-synthetic assumption, not an empirically estimated dose-response curve."
        ),
        (
            "The observed assignment coefficient is a design diagnostic, not automatically the "
            "full-policy market-total estimand; the dashboard therefore never labels their gap "
            "as bias."
        ),
        (
            "Modeled welfare is incomplete: its configured rider value, operating cost, wait "
            "disutility, and transfers omit distributional weights and externalities."
        ),
    ]
    treatment_version = TreatmentVersion.parse(controls.treatment_version)
    limitations.append(str(selected_row["treatment_version_limitation"]))
    if treatment_version is TreatmentVersion.RIDER_DISCOUNT:
        limitations.append(
            "The driver-incentive size control is inactive for rider-discount-only treatment; "
            "the configured discount rate is the operative monetary dose."
        )
    elif treatment_version is TreatmentVersion.DRIVER_INCENTIVE:
        limitations.append(
            "Driver-incentive-only treatment activates the supply and incentive-cost pathways; "
            "the rider discount and direct demand pathway are inactive."
        )
    else:
        limitations.append(
            "The bundled arm identifies only the joint rider-plus-driver intervention. A "
            "factorial experiment is required to separate component effects or interactions."
        )
    if controls.n_clusters < 8 and design in {
        DesignName.GEO_CLUSTER.value,
        DesignName.GEO_TIME.value,
    }:
        limitations.append(
            "Fewer than eight geographic clusters make cluster-robust uncertainty and power "
            "especially fragile; use randomization inference and small-cluster corrections."
        )
    if (
        controls.persistence > 0
        and controls.washout_periods == 0
        and design
        in {
            DesignName.TIME_BLOCK.value,
            DesignName.SWITCHBACK.value,
            DesignName.GEO_TIME.value,
        }
    ):
        limitations.append(
            "Positive persistence with no washout can contaminate post-switch observations."
        )
    if controls.treatment_saturation < 1:
        limitations.append(
            "Partial saturation identifies the selected exposure policy; extrapolation to full "
            "market saturation requires additional structural assumptions."
        )
    if float(selected_row.get("mean_full_policy_budget_scale", 1.0)) < 0.999:
        limitations.append(
            "The budget binds in generated assignments, so randomized assignment and received "
            "intensity differ; report both the ITT and the exposure first stage."
        )
    if controls.replications < 100:
        limitations.append(
            "The on-demand structural averages use fewer than 100 simulator draws and retain "
            "material Monte Carlo error; benchmark bias, coverage, and power come only from the "
            "separately generated artifact."
        )
    if not selected.empty and not bool(selected.iloc[0]["compatible_with_estimand"]):
        limitations.append(
            f"{DESIGN_LABELS[controls.randomization_unit]} is not eligible for the selected "
            "market-total estimand under the registry's identification screen."
        )
    return tuple(dict.fromkeys(limitations))


_ARTIFACT_CANDIDATES: Final[tuple[str, ...]] = (
    "benchmark_results.csv",
    "monte_carlo_summary.csv",
    "benchmark_summary.csv",
)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _manifest_file_entries(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    raw = payload.get("files", payload.get("artifacts", []))
    if isinstance(raw, list):
        return [entry for entry in raw if isinstance(entry, Mapping)]
    if isinstance(raw, Mapping):
        entries: list[Mapping[str, Any]] = []
        for path, metadata in raw.items():
            if isinstance(metadata, Mapping):
                entries.append({"path": path, **metadata})
        return entries
    return []


def _validate_reproduce_lineage(source: Path, *, project_root: Path | None = None) -> None:
    """Require a complete top-level reproduction manifest for default artifacts."""

    root = _project_root() if project_root is None else project_root
    artifact_root = root / "artifacts"
    incomplete = artifact_root / "REPRODUCE_INCOMPLETE.json"
    if incomplete.exists():
        raise ValueError(
            "reproduction is marked incomplete; generated benchmark artifacts are unavailable"
        )
    manifest_path = artifact_root / "reproduce_manifest.json"
    if not manifest_path.is_file():
        raise ValueError("top-level artifacts/reproduce_manifest.json is missing")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("top-level reproduction manifest root must be a mapping")
    metadata = payload.get("metadata")
    if not isinstance(metadata, Mapping):
        raise ValueError("top-level reproduction manifest has no metadata mapping")
    expected_source_hash = str(metadata.get("source_tree_sha256", ""))
    if not expected_source_hash:
        raise ValueError("top-level reproduction manifest has no source-tree SHA-256")
    actual_source_hash = _source_tree_sha256(root)
    if actual_source_hash != expected_source_hash:
        raise ValueError(
            "current source/config tree differs from the completed reproduction manifest"
        )

    resolved_source = source.resolve()
    matched: Mapping[str, Any] | None = None
    for entry in _manifest_file_entries(payload):
        raw_path = entry.get("path")
        if raw_path is None:
            continue
        declared = Path(str(raw_path))
        candidates = (
            (declared.resolve(),)
            if declared.is_absolute()
            else ((root / declared).resolve(), (artifact_root / declared).resolve())
        )
        if resolved_source in candidates:
            matched = entry
            break
    if matched is None:
        raise ValueError("benchmark artifact has no entry in the top-level reproduction manifest")

    expected_hash = str(matched.get("sha256", ""))
    raw_bytes = matched.get("bytes", matched.get("size"))
    try:
        expected_bytes = int(raw_bytes)
    except (TypeError, ValueError) as exc:
        raise ValueError("benchmark manifest entry has no valid byte count") from exc
    if not expected_hash:
        raise ValueError("benchmark manifest entry has no SHA-256")
    actual_bytes = resolved_source.stat().st_size
    if actual_bytes != expected_bytes:
        raise ValueError(
            f"benchmark artifact byte count differs from reproduction manifest "
            f"({actual_bytes} != {expected_bytes})"
        )
    if _sha256(resolved_source) != expected_hash:
        raise ValueError("benchmark artifact SHA-256 differs from reproduction manifest")


def _read_json_mapping(path: Path, label: str) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not readable strict JSON") from exc
    if not isinstance(payload, Mapping):
        raise ValueError(f"{label} root must be a mapping")
    return payload


def _resolve_child_entry_path(
    raw_path: object,
    *,
    manifest_path: Path,
    project_root: Path,
) -> Path:
    if not isinstance(raw_path, str) or not raw_path:
        raise ValueError("child manifest file entry has no path")
    declared = Path(raw_path)
    if declared.is_absolute() or ".." in declared.parts:
        raise ValueError("child manifest paths must be portable and traversal-free")
    candidates = {
        (project_root / declared).resolve(),
        (manifest_path.parent / declared).resolve(),
    }
    contained: list[Path] = []
    for candidate in candidates:
        try:
            candidate.relative_to(project_root)
        except ValueError as exc:
            raise ValueError("child manifest file resolves outside project root") from exc
        if candidate.is_file():
            contained.append(candidate)
    unique = sorted(set(contained))
    if not unique:
        raise ValueError(f"child manifest file is missing: {declared.as_posix()}")
    if len(unique) != 1:
        raise ValueError(f"child manifest file path is ambiguous: {declared.as_posix()}")
    return unique[0]


def _validated_child_files(
    payload: Mapping[str, Any],
    *,
    manifest_path: Path,
    project_root: Path,
) -> tuple[tuple[Mapping[str, Any], Path], ...]:
    if payload.get("portable_paths") is not True:
        raise ValueError("child manifest does not certify portable paths")
    raw_entries = payload.get("files")
    if not isinstance(raw_entries, list) or not raw_entries:
        raise ValueError("child manifest must declare a nonempty files list")
    entries: list[tuple[Mapping[str, Any], Path]] = []
    declared_paths: set[str] = set()
    resolved_paths: set[Path] = set()
    for raw_entry in raw_entries:
        if not isinstance(raw_entry, Mapping):
            raise ValueError("child manifest file entries must be mappings")
        raw_path = raw_entry.get("path")
        if not isinstance(raw_path, str) or raw_path in declared_paths:
            raise ValueError("child manifest file paths must be unique strings")
        declared_paths.add(raw_path)
        path = _resolve_child_entry_path(
            raw_path,
            manifest_path=manifest_path,
            project_root=project_root,
        )
        if path in resolved_paths:
            raise ValueError("child manifest paths resolve to a duplicate file")
        resolved_paths.add(path)
        raw_bytes = raw_entry.get("bytes")
        if isinstance(raw_bytes, bool):
            raise ValueError("child manifest file has no valid byte count")
        try:
            expected_bytes = int(raw_bytes)
        except (TypeError, ValueError) as exc:
            raise ValueError("child manifest file has no valid byte count") from exc
        expected_hash = raw_entry.get("sha256")
        if (
            not isinstance(expected_hash, str)
            or len(expected_hash) != 64
            or any(character not in "0123456789abcdef" for character in expected_hash)
        ):
            raise ValueError("child manifest file has no valid SHA-256")
        if path.stat().st_size != expected_bytes:
            raise ValueError("child manifest file byte count mismatch")
        if _sha256(path) != expected_hash:
            raise ValueError("child manifest file SHA-256 mismatch")
        entries.append((raw_entry, path))

    declared_digest = payload.get("declared_file_set_sha256")
    if declared_digest is not None:
        if not isinstance(declared_digest, str) or len(declared_digest) != 64:
            raise ValueError("child manifest declared file-set digest is invalid")
        recomputed = hashlib.sha256(
            json.dumps(raw_entries, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest()
        if recomputed != declared_digest:
            raise ValueError("child manifest declared file-set digest mismatch")
    return tuple(entries)


def _validated_child_inputs(
    payload: Mapping[str, Any],
    *,
    project_root: Path,
) -> tuple[tuple[Mapping[str, Any], Path], ...]:
    """Validate immutable upstream inputs declared by a child manifest.

    Unlike bundle files, inputs are always interpreted relative to the project root;
    accepting manifest-relative fallbacks here could silently validate the wrong
    upstream artifact after a bundle is moved.
    """

    raw_entries = payload.get("inputs", [])
    if not isinstance(raw_entries, list):
        raise ValueError("child manifest inputs must be a list")
    entries: list[tuple[Mapping[str, Any], Path]] = []
    declared_paths: set[str] = set()
    resolved_paths: set[Path] = set()
    for raw_entry in raw_entries:
        if not isinstance(raw_entry, Mapping):
            raise ValueError("child manifest input entries must be mappings")
        raw_path = raw_entry.get("path")
        if not isinstance(raw_path, str) or not raw_path or raw_path in declared_paths:
            raise ValueError("child manifest input paths must be unique strings")
        declared = Path(raw_path)
        if declared.is_absolute() or ".." in declared.parts:
            raise ValueError(
                "child manifest input paths must be project-root relative and traversal-free"
            )
        declared_paths.add(raw_path)
        path = (project_root / declared).resolve()
        try:
            path.relative_to(project_root)
        except ValueError as exc:
            raise ValueError("child manifest input resolves outside project root") from exc
        if not path.is_file():
            raise ValueError(f"child manifest input is missing: {declared.as_posix()}")
        if path in resolved_paths:
            raise ValueError("child manifest input paths resolve to a duplicate file")
        resolved_paths.add(path)

        role = raw_entry.get("role")
        if not isinstance(role, str) or not role:
            raise ValueError("child manifest input roles must be nonempty strings")
        evidence_types = raw_entry.get("evidence_types")
        if evidence_types is not None and (
            not isinstance(evidence_types, list)
            or not evidence_types
            or any(not isinstance(value, str) or not value for value in evidence_types)
        ):
            raise ValueError("child manifest input has invalid evidence labels")

        raw_bytes = raw_entry.get("bytes")
        if isinstance(raw_bytes, bool):
            raise ValueError("child manifest input has no valid byte count")
        try:
            expected_bytes = int(raw_bytes)
        except (TypeError, ValueError) as exc:
            raise ValueError("child manifest input has no valid byte count") from exc
        expected_hash = raw_entry.get("sha256")
        if (
            not isinstance(expected_hash, str)
            or len(expected_hash) != 64
            or any(character not in "0123456789abcdef" for character in expected_hash)
        ):
            raise ValueError("child manifest input has no valid SHA-256")
        if path.stat().st_size != expected_bytes:
            raise ValueError("child manifest input byte count mismatch")
        if _sha256(path) != expected_hash:
            raise ValueError("child manifest input SHA-256 mismatch")
        entries.append((raw_entry, path))
    declared_digest = payload.get("declared_input_set_sha256")
    if declared_digest is not None:
        if not isinstance(declared_digest, str) or len(declared_digest) != 64:
            raise ValueError("child manifest declared input-set digest is invalid")
        recomputed = hashlib.sha256(
            json.dumps(raw_entries, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest()
        if recomputed != declared_digest:
            raise ValueError("child manifest declared input-set digest mismatch")
    return tuple(entries)


def _child_file_by_role(
    files: Sequence[tuple[Mapping[str, Any], Path]], role: str
) -> tuple[Mapping[str, Any], Path]:
    matches = [(entry, path) for entry, path in files if entry.get("role") == role]
    if len(matches) != 1:
        raise ValueError(f"child manifest must declare exactly one {role} file")
    return matches[0]


def _child_file_by_name(
    files: Sequence[tuple[Mapping[str, Any], Path]], name: str
) -> tuple[Mapping[str, Any], Path]:
    matches = [(entry, path) for entry, path in files if path.name == name]
    if len(matches) != 1:
        raise ValueError(f"child manifest must declare exactly one {name}")
    return matches[0]


def _validate_nyc_informed_layer(
    payload: Mapping[str, Any],
    files: Sequence[tuple[Mapping[str, Any], Path]],
    _inputs: Sequence[tuple[Mapping[str, Any], Path]],
    _project_root: Path,
) -> str:
    evidence = "semi_synthetic_nyc_informed_known_truth_monte_carlo"
    if (
        payload.get("schema_version") != "1.0.0"
        or payload.get("artifact_type") != "nyc_informed_marketplace_benchmark"
        or payload.get("evidence_type") != evidence
        or payload.get("causal_claim") is not False
        or payload.get("causal_claim_from_nyc_data") is not False
        or payload.get("simulator_known_truth") is not True
    ):
        raise ValueError("NYC-informed benchmark manifest has invalid scientific schema")
    roles = {str(entry.get("role")) for entry, _ in files}
    if roles != {"records", "summary", "fit_ledger", "failures", "metadata"}:
        raise ValueError("NYC-informed benchmark manifest has an incomplete file-role set")
    summary_entry, summary_path = _child_file_by_role(files, "summary")
    evidence_types = summary_entry.get("evidence_types")
    if not isinstance(evidence_types, list) or evidence not in evidence_types:
        raise ValueError("NYC-informed summary has no known-truth evidence label")
    summary = pd.read_csv(summary_path)
    if summary.empty or set(summary["evidence_type"].astype(str)) != {evidence}:
        raise ValueError("NYC-informed summary evidence labels are invalid")
    _, metadata_path = _child_file_by_role(files, "metadata")
    metadata = _read_json_mapping(metadata_path, "NYC-informed benchmark metadata")
    bundle = metadata.get("artifact_bundle")
    if (
        metadata.get("evidence_type") != evidence
        or metadata.get("nyc_empirical_causal_effect") is not False
        or metadata.get("simulator_known_truth") is not True
        or not isinstance(bundle, Mapping)
        or bundle.get("schema_version") != "1.0.0"
        or bundle.get("evidence_type") != evidence
    ):
        raise ValueError("NYC-informed benchmark metadata has invalid evidence provenance")
    return f"{len(summary):,} verified summary rows; simulator truth, not NYC effects"


def _validate_nyc_graph_layer(
    payload: Mapping[str, Any],
    files: Sequence[tuple[Mapping[str, Any], Path]],
    _inputs: Sequence[tuple[Mapping[str, Any], Path]],
    _project_root: Path,
) -> str:
    evidence = "semi_synthetic_known_truth_on_descriptive_nyc_graph"
    summary_evidence = "semi_synthetic_nyc_graph_known_truth_monte_carlo"
    if (
        payload.get("schema_version") != "1.0.0"
        or payload.get("artifact_type") != "nyc_graph_interference_benchmark"
        or payload.get("evidence_type") != evidence
        or payload.get("causal_claim") is not False
        or payload.get("causal_claim_from_nyc_data") is not False
        or payload.get("input_graph_evidence_label") != "descriptive_real_data"
    ):
        raise ValueError("NYC graph benchmark manifest has invalid scientific schema")
    roles = {str(entry.get("role")) for entry, _ in files}
    if roles != {"records", "summary", "fit_ledger", "failures", "metadata"}:
        raise ValueError("NYC graph benchmark manifest has an incomplete file-role set")
    summary_entry, summary_path = _child_file_by_role(files, "summary")
    evidence_types = summary_entry.get("evidence_types")
    if not isinstance(evidence_types, list) or summary_evidence not in evidence_types:
        raise ValueError("NYC graph summary has no known-truth evidence label")
    summary = pd.read_csv(summary_path)
    observed_labels = set(summary["evidence_type"].dropna().astype(str))
    if (
        summary.empty
        or summary_evidence not in observed_labels
        or any(not value.startswith("semi_synthetic") for value in observed_labels)
    ):
        raise ValueError("NYC graph summary evidence labels are invalid")
    _, metadata_path = _child_file_by_role(files, "metadata")
    metadata = _read_json_mapping(metadata_path, "NYC graph benchmark metadata")
    bundle = metadata.get("artifact_bundle")
    if (
        metadata.get("evidence_type") != evidence
        or metadata.get("causal_claim_from_nyc_data") is not False
        or metadata.get("input_graph_evidence_label") != "descriptive_real_data"
        or not isinstance(bundle, Mapping)
        or bundle.get("schema_version") != "1.0.0"
        or bundle.get("evidence_type") != evidence
    ):
        raise ValueError("NYC graph benchmark metadata has invalid evidence provenance")
    return f"{len(summary):,} verified summary rows on descriptive NYC OD geometry"


def _validate_equilibrium_layer(
    payload: Mapping[str, Any],
    files: Sequence[tuple[Mapping[str, Any], Path]],
    _inputs: Sequence[tuple[Mapping[str, Any], Path]],
    _project_root: Path,
) -> str:
    evidence = "theoretical_simulation_known_ground_truth"
    if (
        payload.get("schema_version") != 1
        or payload.get("bundle_type")
        != "two_sided_fixed_point_equilibrium_benchmark"
        or payload.get("evidence_type") != evidence
        or payload.get("causal_scope") != "within_declared_equilibrium_model_only"
        or payload.get("empirical_calibration_status")
        != "not_an_empirical_or_nyc_structural_estimate"
        or payload.get("is_nyc_structural_estimate") is not False
    ):
        raise ValueError("equilibrium manifest has invalid theoretical evidence schema")
    required_names = {"summary.json", "zone_effects.csv", "ledger.csv"}
    if {path.name for _, path in files} != required_names:
        raise ValueError("equilibrium manifest has an incomplete file set")
    checks = payload.get("checks")
    required_checks = {
        "control_equilibrium_converged",
        "treatment_equilibrium_converged",
        "residuals_within_tolerance",
        "sufficient_uniqueness_condition_satisfied",
        "common_random_numbers_verified",
        "budget_feasible",
        "welfare_accounting_balanced",
        "ground_truth_recomputed",
        "hashes_recomputed",
    }
    if not isinstance(checks, Mapping) or any(
        checks.get(key) is not True for key in required_checks
    ):
        raise ValueError("equilibrium manifest has an unpassed scientific check")
    _, summary_path = _child_file_by_name(files, "summary.json")
    summary = _read_json_mapping(summary_path, "equilibrium summary")
    equations = summary.get("equations")
    if (
        summary.get("schema_version") != 1
        or summary.get("evidence_type") != evidence
        or summary.get("common_random_numbers") is not True
        or summary.get("is_nyc_structural_estimate") is not False
        or not isinstance(equations, Mapping)
        or not {"rider_demand", "driver_supply", "wait_fixed_point"}.issubset(
            equations
        )
    ):
        raise ValueError("equilibrium summary has invalid evidence or equation schema")
    return "fixed-point residual, budget, welfare, and common-state checks verified"


def _validate_weather_layer(
    payload: Mapping[str, Any],
    files: Sequence[tuple[Mapping[str, Any], Path]],
    _inputs: Sequence[tuple[Mapping[str, Any], Path]],
    _project_root: Path,
) -> str:
    evidence = "descriptive_observed_external_weather"
    if (
        payload.get("schema_version") != "1.0.0"
        or payload.get("evidence_label") != evidence
        or payload.get("causal_claim") is not False
    ):
        raise ValueError("weather manifest has invalid descriptive evidence schema")
    checks = payload.get("checks")
    if not isinstance(checks, Mapping) or any(
        checks.get(key) is not True
        for key in (
            "noaa_raw_hash_matches",
            "calendar_complete",
            "nyc_source_manifest_valid",
            "trip_conservation",
        )
    ):
        raise ValueError("weather manifest has an unpassed source or conservation check")
    _, summary_path = _child_file_by_name(files, "weather_associations.json")
    summary = _read_json_mapping(summary_path, "weather association summary")
    scope = summary.get("scope")
    if (
        summary.get("schema_version") != "1.0.0"
        or summary.get("evidence_label") != evidence
        or summary.get("causal_claim") is not False
        or not isinstance(scope, Mapping)
        or scope.get("city") != "New York City"
        or scope.get("population_claim") is not False
    ):
        raise ValueError("weather summary has invalid descriptive scope")
    return f"{scope.get('pickup_month', 'NYC month')} observed weather-trip associations"


def _validate_events_layer(
    payload: Mapping[str, Any],
    files: Sequence[tuple[Mapping[str, Any], Path]],
    inputs: Sequence[tuple[Mapping[str, Any], Path]],
    _project_root: Path,
) -> str:
    evidence = "descriptive_observed_external_calendar_events"
    checks = payload.get("checks")
    required_true = {
        "holiday_snapshot_hash_matches",
        "event_snapshot_hash_matches",
        "calendar_complete",
        "holiday_schedule_coverage_complete",
        "event_source_rows_verified",
        "event_source_unique_ids_verified",
        "invalid_source_intervals_retained_and_excluded",
        "zero_duration_source_intervals_retained_and_excluded",
        "daily_signal_is_citywide_not_zone_exposure",
        "hourly_profiles_repeat_daily_signal_not_event_hour_exposure",
        "major_event_is_researcher_defined",
        "nyc_source_manifest_valid",
        "trip_conservation",
        "causal_claim_is_false",
    }
    if (
        payload.get("schema_version") != "1.0.0"
        or payload.get("evidence_label") != evidence
        or payload.get("causal_claim") is not False
        or not isinstance(checks, Mapping)
        or any(checks.get(key) is not True for key in required_true)
        or checks.get("major_event_contrast_separately_identified") is not False
    ):
        raise ValueError("calendar/event manifest has invalid descriptive evidence schema")
    expected_files = {
        "normalized_daily_calendar",
        "normalized_permit_records",
        "daily_permit_type_counts",
        "joined_daily_trip_panel",
        "descriptive_hourly_profiles",
        "descriptive_summary",
    }
    file_roles = [str(entry.get("role")) for entry, _ in files]
    if set(file_roles) != expected_files or len(file_roles) != 6:
        raise ValueError("calendar/event manifest has an incomplete file-role set")
    input_roles = [str(entry.get("role")) for entry, _ in inputs]
    singleton_roles = {
        "official_holiday_snapshot",
        "official_nyc_permitted_events_snapshot",
        "nyc_full_data_manifest",
    }
    panel_count = checks.get("panel_files_verified")
    if (
        isinstance(panel_count, bool)
        or not isinstance(panel_count, int)
        or panel_count < 1
        or any(input_roles.count(role) != 1 for role in singleton_roles)
        or input_roles.count("nyc_full_zone_time_panel") != panel_count
        or set(input_roles) != singleton_roles | {"nyc_full_zone_time_panel"}
    ):
        raise ValueError("calendar/event manifest has an incomplete input-role set")
    summary_matches = [
        path for entry, path in files if entry.get("role") == "descriptive_summary"
    ]
    if len(summary_matches) != 1:
        raise ValueError("calendar/event manifest has no unique descriptive summary")
    summary = _read_json_mapping(summary_matches[0], "calendar/event summary")
    scope = summary.get("scope")
    coverage = summary.get("coverage")
    associations = summary.get("associations")
    identification = summary.get("identification_checks")
    conservation = summary.get("conservation")
    if not all(
        isinstance(value, Mapping)
        for value in (scope, coverage, associations, identification, conservation)
    ):
        raise ValueError("calendar/event summary is incomplete")
    weekday = associations.get(
        "above_vs_at_or_below_median_permit_intensity_weekdays_only"
    )
    if (
        summary.get("schema_version") != "1.0.0"
        or summary.get("evidence_label") != evidence
        or summary.get("causal_claim") is not False
        or scope.get("city") != "New York City"
        or scope.get("event_signal_spatial_granularity") != "citywide"
        or scope.get("event_signal_temporal_granularity") != "service_date"
        or scope.get("population_claim") is not False
        or identification.get("causal_effect_identified") is not False
        or identification.get("major_event_contrast_separately_identifies_event_effect")
        is not False
        or identification.get("all_weekend_days_are_above_median_permit_intensity")
        is not True
        or coverage.get("above_median_permit_intensity_weekend_days")
        != coverage.get("weekend_days")
        or coverage.get("at_or_below_median_permit_intensity_weekend_days") != 0
        or not isinstance(weekday, Mapping)
        or conservation.get("passes") is not True
        or conservation.get("daily_trip_sum") != conservation.get("zone_time_trip_sum")
    ):
        raise ValueError("calendar/event summary violates its non-causal scope")
    permit_rows = coverage.get("source_permit_rows")
    unique_ids = coverage.get("source_unique_event_ids")
    invalid_rows = coverage.get("invalid_interval_rows_retained_but_not_expanded")
    zero_duration_rows = coverage.get(
        "zero_duration_interval_rows_retained_but_not_expanded"
    )
    nonpositive_rows = coverage.get(
        "all_nonpositive_interval_rows_retained_but_not_expanded"
    )
    valid_rows = coverage.get("valid_interval_rows")
    valid_unique_ids = coverage.get("valid_unique_event_ids")
    expanded_event_days = coverage.get("expanded_unique_event_days")
    count_values = (
        permit_rows,
        unique_ids,
        invalid_rows,
        zero_duration_rows,
        nonpositive_rows,
        valid_rows,
        valid_unique_ids,
        expanded_event_days,
    )
    if (
        any(
            isinstance(value, bool) or not isinstance(value, int)
            for value in count_values
        )
        or permit_rows < unique_ids
        or unique_ids < 1
        or invalid_rows < 0
        or zero_duration_rows < 0
        or nonpositive_rows != invalid_rows + zero_duration_rows
        or valid_rows != permit_rows - nonpositive_rows
        or not 1 <= valid_unique_ids <= unique_ids
        or expanded_event_days < valid_unique_ids
    ):
        raise ValueError("calendar/event summary has inconsistent interval counts")
    return (
        f"{permit_rows} permit rows / {unique_ids} IDs; {zero_duration_rows} zero-duration "
        "intervals retained but excluded; weekend composition "
        "and weekday-only diagnostic verified"
    )


def _validate_income_layer(
    payload: Mapping[str, Any],
    files: Sequence[tuple[Mapping[str, Any], Path]],
    inputs: Sequence[tuple[Mapping[str, Any], Path]],
    project_root: Path,
) -> str:
    evidence = "descriptive_observed_external_neighborhood_income"
    checks = payload.get("checks")
    required_true = {
        "official_source_hashes_match",
        "taxi_location_ids_unique_and_complete",
        "tract_b19001_totals_equal_sixteen_bins",
        "household_distribution_conserved",
        "published_trip_conservation",
        "ecological_noncausal_contract",
        "dominant_nonresidential_primary_unclassified",
        "all_zone_classification_is_sensitivity_only",
    }
    if (
        payload.get("schema_version") != "1.0.0"
        or payload.get("artifact_type") != "nyc_income_descriptive_bundle"
        or payload.get("evidence_label") != evidence
        or payload.get("causal_claim") is not False
        or not isinstance(checks, Mapping)
        or any(checks.get(key) is not True for key in required_true)
        or checks.get("median_of_medians_used") is not False
        or checks.get("equal_area_crs") != "EPSG:6933"
        or checks.get("dominant_nonresidential_primary_classified_zones") != 0
        or checks.get("minimum_allocated_households") != 1.0
        or checks.get("minimum_residential_taxi_zone_area_share") != 0.5
        or checks.get("residential_nta_type_codes") != ["0"]
        or checks.get("zone_grouped_medians_are_point_estimates") is not True
        or checks.get("zone_level_margin_of_error_propagated") is not False
    ):
        raise ValueError("income manifest has invalid ecological evidence schema")
    expected_files = {
        "taxi_zone_nta_crosswalk",
        "nta_b19001_distribution_summary",
        "taxi_zone_income_and_trip_summary",
        "daily_income_group_description",
        "monthly_income_group_description",
        "income_association_summary",
    }
    if (
        {str(entry.get("role")) for entry, _ in files} != expected_files
        or len(files) != 6
        or any(
            entry.get("evidence_label") != evidence
            or entry.get("causal_claim") is not False
            for entry, _ in files
        )
    ):
        raise ValueError("income manifest has an incomplete or unsafe file-role set")
    expected_input_types = {
        "official_tlc_taxi_zone_geometry": "official_observed_geometry",
        "official_nyc_nta2020_geometry": "official_observed_geometry",
        "official_nyc_tract2020_to_nta2020_mapping": "official_observed_crosswalk",
        "official_census_acs_2022_5yr_b19001_nyc_tract_slice": (
            "official_observed_estimates"
        ),
        "verified_nyc_full_data_manifest": "descriptive_real_data_lineage",
    }
    input_by_role = {
        str(entry.get("role")): (entry, path)
        for entry, path in inputs
        if entry.get("role") != "nyc_full_zone_time_panel"
    }
    panel_inputs = [
        (entry, path)
        for entry, path in inputs
        if entry.get("role") == "nyc_full_zone_time_panel"
    ]
    panel_count = checks.get("panel_files_verified")
    if (
        set(input_by_role) != set(expected_input_types)
        or isinstance(panel_count, bool)
        or not isinstance(panel_count, int)
        or len(panel_inputs) != panel_count
        or len(inputs) != 5 + panel_count
    ):
        raise ValueError("income manifest has an incomplete input-role set")
    if any(
        input_by_role[role][0].get("source_type") != source_type
        for role, source_type in expected_input_types.items()
    ) or any(
        entry.get("source_type") != "descriptive_real_data_panel"
        for entry, _ in panel_inputs
    ):
        raise ValueError("income manifest has invalid input evidence types")
    summary_matches = [
        path for entry, path in files if entry.get("role") == "income_association_summary"
    ]
    if len(summary_matches) != 1:
        raise ValueError("income manifest has no unique association summary")
    summary = _read_json_mapping(summary_matches[0], "income association summary")
    scope = summary.get("scope")
    coverage = summary.get("coverage")
    associations = summary.get("associations")
    conservation = summary.get("conservation")
    spatial = summary.get("spatial_mapping")
    acs = summary.get("acs_aggregation")
    allocation = summary.get("zone_allocation")
    primary_classification = summary.get("primary_classification")
    uncertainty = summary.get("classification_uncertainty")
    sensitivity = summary.get("sensitivity")
    if not all(
        isinstance(value, Mapping)
        for value in (
            scope,
            coverage,
            associations,
            conservation,
            spatial,
            acs,
            allocation,
            primary_classification,
            uncertainty,
            sensitivity,
        )
    ):
        raise ValueError("income association summary is incomplete")
    if (
        summary.get("schema_version") != "1.0.0"
        or summary.get("evidence_label") != evidence
        or summary.get("causal_claim") is not False
        or scope.get("city") != "New York City"
        or scope.get("population_claim") is not False
        or scope.get("individual_income_claim") is not False
        or spatial.get("equal_area_crs") != "EPSG:6933"
        or acs.get("median_of_medians_used") is not False
        or allocation.get("all_sixteen_bins_conserved") is not True
        or allocation.get("households_conserved") is not True
        or allocation.get("minimum_allocated_households") != 1.0
        or allocation.get("minimum_residential_taxi_zone_area_share") != 0.5
        or allocation.get("residential_nta_type_codes") != ["0"]
        or primary_classification.get("primary_result") is not True
        or primary_classification.get("minimum_allocated_households") != 1.0
        or primary_classification.get("minimum_residential_taxi_zone_area_share")
        != 0.5
        or primary_classification.get("residential_nta_type_codes") != ["0"]
        or uncertainty.get("nta_b19001_margins_of_error_retained") is not True
        or uncertainty.get("zone_grouped_medians_are_point_estimates") is not True
        or uncertainty.get("zone_level_margin_of_error_propagated") is not False
        or "not a confidence interval"
        not in str(uncertainty.get("interpretation", "")).lower()
        or conservation.get("passes") is not True
    ):
        raise ValueError("income association summary violates its ecological scope")
    total = coverage.get("published_completed_trips")
    classified = coverage.get("classified_published_completed_trips")
    unclassified = coverage.get("unclassified_published_completed_trips")
    classified_zones = coverage.get("classified_panel_zones")
    panel_zones = coverage.get("panel_zone_rows")
    allocated_high_zones = allocation.get("high_income_zone_rows")
    allocated_low_zones = allocation.get("low_income_zone_rows")
    ratio = coverage.get("classified_trip_coverage")
    if (
        isinstance(total, bool)
        or not isinstance(total, int)
        or total <= 0
        or isinstance(classified, bool)
        or not isinstance(classified, int)
        or isinstance(unclassified, bool)
        or not isinstance(unclassified, int)
        or classified + unclassified != total
        or isinstance(classified_zones, bool)
        or not isinstance(classified_zones, int)
        or isinstance(panel_zones, bool)
        or not isinstance(panel_zones, int)
        or isinstance(allocated_high_zones, bool)
        or not isinstance(allocated_high_zones, int)
        or isinstance(allocated_low_zones, bool)
        or not isinstance(allocated_low_zones, int)
        or not 0 < classified_zones <= panel_zones
        or isinstance(ratio, bool)
        or not isinstance(ratio, (int, float))
        or not np.isfinite(ratio)
        or not np.isclose(ratio, classified / total)
        or allocation.get("classified_zone_rows") != classified_zones
        or allocated_high_zones + allocated_low_zones != classified_zones
        or conservation.get("primary_classified_plus_unclassified_trip_sum") != total
        or conservation.get("primary_nonresidential_classified_zones") != 0
        or any(
            conservation.get(key) != total
            for key in ("zone_trip_sum", "daily_group_trip_sum", "monthly_group_trip_sum")
        )
    ):
        raise ValueError("income association summary has inconsistent coverage")
    high_rate = associations.get(
        "mean_published_completed_trips_per_zone_hour_high_income_area"
    )
    low_rate = associations.get(
        "mean_published_completed_trips_per_zone_hour_low_income_area"
    )
    difference = associations.get(
        "high_minus_low_mean_published_completed_trips_per_zone_hour"
    )
    rate_ratio = associations.get(
        "high_to_low_mean_published_completed_trips_per_zone_hour_ratio"
    )
    association_values = (high_rate, low_rate, difference, rate_ratio)
    if (
        any(isinstance(value, bool) for value in association_values)
        or not all(isinstance(value, (int, float)) for value in association_values)
        or not np.isfinite(association_values).all()
        or low_rate <= 0
        or not np.isclose(difference, high_rate - low_rate)
        or not np.isclose(rate_ratio, high_rate / low_rate)
    ):
        raise ValueError("income association summary has inconsistent primary arithmetic")
    primary_groups = primary_classification.get("groups")
    if (
        not isinstance(primary_groups, Mapping)
        or set(primary_groups)
        != {"high_income_area", "low_income_area", "unclassified"}
        or any(not isinstance(group, Mapping) for group in primary_groups.values())
    ):
        raise ValueError("income association summary has incomplete primary groups")
    primary_high = primary_groups["high_income_area"]
    primary_low = primary_groups["low_income_area"]
    primary_unclassified = primary_groups["unclassified"]
    primary_group_zones = tuple(
        group.get("panel_zones")
        for group in (primary_high, primary_low, primary_unclassified)
    )
    primary_group_trips = tuple(
        group.get("published_completed_trips")
        for group in (primary_high, primary_low, primary_unclassified)
    )
    primary_high_mean = primary_high.get(
        "mean_published_completed_trips_per_zone_hour"
    )
    primary_low_mean = primary_low.get(
        "mean_published_completed_trips_per_zone_hour"
    )
    if (
        any(
            isinstance(value, bool) or not isinstance(value, int)
            for value in (*primary_group_zones, *primary_group_trips)
        )
        or any(value < 0 for value in (*primary_group_zones, *primary_group_trips))
        or any(
            isinstance(value, bool) or not isinstance(value, (int, float))
            for value in (primary_high_mean, primary_low_mean)
        )
        or not np.isfinite([primary_high_mean, primary_low_mean]).all()
        or sum(primary_group_zones[:2]) != classified_zones
        or sum(primary_group_trips[:2]) != classified
        or sum(primary_group_zones) != panel_zones
        or sum(primary_group_trips) != total
        or not np.isclose(primary_high_mean, high_rate)
        or not np.isclose(primary_low_mean, low_rate)
    ):
        raise ValueError("income association summary has inconsistent primary groups")
    proximity = uncertainty.get("threshold_proximity")
    proximity_keys = (
        "within_1000_usd",
        "within_2500_usd",
        "within_5000_usd",
        "within_10000_usd",
    )
    if not isinstance(proximity, Mapping) or any(
        not isinstance(proximity.get(key), Mapping) for key in proximity_keys
    ):
        raise ValueError("income association summary has an incomplete uncertainty audit")
    prior_zones = -1
    prior_trips = -1
    for key in proximity_keys:
        item = proximity[key]
        zones = item.get("primary_eligible_panel_zones")
        trips = item.get("published_completed_trips")
        share = item.get("share_of_primary_classified_trips")
        if (
            isinstance(zones, bool)
            or not isinstance(zones, int)
            or isinstance(trips, bool)
            or not isinstance(trips, int)
            or isinstance(share, bool)
            or not isinstance(share, (int, float))
            or zones < prior_zones
            or trips < prior_trips
            or not np.isfinite(share)
            or not 0 <= share <= 1
            or not np.isclose(share, trips / classified)
        ):
            raise ValueError("income association summary has an unsafe uncertainty audit")
        prior_zones, prior_trips = zones, trips

    all_zone_sensitivity = sensitivity.get("all_zone_area_allocation")
    groups = (
        all_zone_sensitivity.get("groups")
        if isinstance(all_zone_sensitivity, Mapping)
        else None
    )
    if (
        not isinstance(all_zone_sensitivity, Mapping)
        or not isinstance(groups, Mapping)
        or set(groups) != {"high_income_area", "low_income_area", "unclassified"}
        or any(not isinstance(group, Mapping) for group in groups.values())
    ):
        raise ValueError("income association summary has an incomplete sensitivity")
    high_group = groups["high_income_area"]
    low_group = groups["low_income_area"]
    unclassified_group = groups["unclassified"]
    group_zone_counts = tuple(
        group.get("panel_zones") for group in (high_group, low_group, unclassified_group)
    )
    group_trip_counts = tuple(
        group.get("published_completed_trips")
        for group in (high_group, low_group, unclassified_group)
    )
    sensitivity_classified_zones = all_zone_sensitivity.get("classified_panel_zones")
    sensitivity_classified_trips = all_zone_sensitivity.get(
        "classified_published_completed_trips"
    )
    sensitivity_coverage = all_zone_sensitivity.get("classified_trip_coverage")
    sensitivity_high = all_zone_sensitivity.get(
        "mean_published_completed_trips_per_zone_hour_high_income_area"
    )
    sensitivity_low = all_zone_sensitivity.get(
        "mean_published_completed_trips_per_zone_hour_low_income_area"
    )
    sensitivity_difference = all_zone_sensitivity.get(
        "high_minus_low_mean_published_completed_trips_per_zone_hour"
    )
    sensitivity_ratio = all_zone_sensitivity.get(
        "high_to_low_mean_published_completed_trips_per_zone_hour_ratio"
    )
    high_group_mean = high_group.get("mean_published_completed_trips_per_zone_hour")
    low_group_mean = low_group.get("mean_published_completed_trips_per_zone_hour")
    sensitivity_numeric = (
        sensitivity_coverage,
        sensitivity_high,
        sensitivity_low,
        sensitivity_difference,
        sensitivity_ratio,
        high_group_mean,
        low_group_mean,
    )
    if (
        all_zone_sensitivity.get("primary_result") is not False
        or all_zone_sensitivity.get(
            "ignored_primary_residential_taxi_zone_area_share_threshold"
        )
        != 0.5
        or any(
            isinstance(value, bool) or not isinstance(value, int)
            for value in (
                *group_zone_counts,
                *group_trip_counts,
                sensitivity_classified_zones,
                sensitivity_classified_trips,
            )
        )
        or any(isinstance(value, bool) for value in sensitivity_numeric)
        or not all(isinstance(value, (int, float)) for value in sensitivity_numeric)
        or not np.isfinite(sensitivity_numeric).all()
        or any(value < 0 for value in (*group_zone_counts, *group_trip_counts))
        or sensitivity_low <= 0
        or sensitivity_classified_zones != sum(group_zone_counts[:2])
        or sensitivity_classified_trips != sum(group_trip_counts[:2])
        or panel_zones != sum(group_zone_counts)
        or total != sum(group_trip_counts)
        or not np.isclose(sensitivity_coverage, sensitivity_classified_trips / total)
        or not np.isclose(sensitivity_high, high_group_mean)
        or not np.isclose(sensitivity_low, low_group_mean)
        or not np.isclose(sensitivity_difference, sensitivity_high - sensitivity_low)
        or not np.isclose(sensitivity_ratio, sensitivity_high / sensitivity_low)
        or conservation.get("sensitivity_group_trip_sum") != total
    ):
        raise ValueError("income association summary has inconsistent sensitivity arithmetic")
    source_entry, source_path = input_by_role["verified_nyc_full_data_manifest"]
    source = _read_json_mapping(source_path, "income source-data manifest")
    source_metadata = source.get("metadata")
    source_config = source.get("config")
    if (
        not isinstance(source_metadata, Mapping)
        or not isinstance(source_config, Mapping)
        or source_config.get("source") != "nyc_hvfhv"
        or source_config.get("mode") != "full"
        or source_metadata.get("evidence_label") != "descriptive_real_data"
        or source_metadata.get("causal_claim") is not False
    ):
        raise ValueError("income source-data manifest has unsafe evidence metadata")
    panel_entries = [
        entry
        for entry in source.get("files", [])
        if isinstance(entry, Mapping)
        and isinstance(entry.get("path"), str)
        and "panel/zone_time" in entry["path"]
        and entry["path"].endswith(".parquet")
    ]
    if (
        len(panel_entries) != panel_count
    ):
        raise ValueError("income source-data panel file set is incomplete")
    for entry in panel_entries:
        declared = Path(str(entry["path"]))
        if declared.is_absolute() or ".." in declared.parts:
            raise ValueError("income source-data panel path is nonportable")
        panel_path = (project_root / declared).resolve()
        try:
            panel_path.relative_to(project_root)
        except ValueError as exc:
            raise ValueError("income source-data panel path escapes project root") from exc
        if (
            not panel_path.is_file()
            or panel_path.stat().st_size != entry.get("bytes")
            or _sha256(panel_path) != entry.get("sha256")
        ):
            raise ValueError("income source-data panel lineage mismatch")
    source_trip_sum = (
        source_metadata.get("full_month_processing", {})
        .get("row_conservation", {})
        .get("zone_time_trip_sum")
    )
    if (
        {path for _, path in panel_inputs}
        != {(project_root / Path(str(entry["path"]))).resolve() for entry in panel_entries}
        or source_trip_sum != total
        or source_entry.get("source_type") != "descriptive_real_data_lineage"
    ):
        raise ValueError("income trip total disagrees with source lineage")
    return (
        f"{classified_zones} primary residential-eligible zones; "
        f"{float(ratio):.2%} of published trips covered; nonresidential zones remain "
        "unclassified in the primary result and all-zone allocation is sensitivity-only"
    )


_EVIDENCE_LAYER_VALIDATORS: Final[
    Mapping[
        str,
        Any,
    ]
] = {
    "nyc_informed": _validate_nyc_informed_layer,
    "nyc_graph": _validate_nyc_graph_layer,
    "equilibrium": _validate_equilibrium_layer,
    "weather": _validate_weather_layer,
    "events": _validate_events_layer,
    "income": _validate_income_layer,
}

_EVIDENCE_LAYER_INPUT_ROLES: Final[Mapping[str, Mapping[str, str]]] = {
    "nyc_informed": {
        "anchor": "semi_synthetic_descriptive_anchor",
        "anchor_manifest": "semi_synthetic_descriptive_anchor",
    },
    "nyc_graph": {
        "calibration_manifest": "descriptive_real_data",
        "exposure_mapping": "descriptive_real_data",
    },
}


def load_evidence_layers(
    project_root: str | Path | None = None,
) -> tuple[EvidenceLayerStatus, ...]:
    """Load read-only evidence layers through top and child lineage gates.

    Missing, stale, malformed, or scientifically mislabeled artifacts are returned
    as unavailable.  These statuses are informational and are never passed into the
    experiment-design recommendation functions.
    """

    root = (_project_root() if project_root is None else Path(project_root)).resolve()
    statuses: list[EvidenceLayerStatus] = []
    for spec in _EVIDENCE_LAYER_SPECS:
        manifest_path = (root / spec.relative_manifest).resolve()
        if not manifest_path.is_file():
            statuses.append(
                EvidenceLayerStatus(
                    key=spec.key,
                    title=spec.title,
                    classification=spec.classification,
                    interpretation=spec.interpretation,
                    available=False,
                    detail="unavailable: manifest is absent",
                )
            )
            continue
        try:
            _validate_reproduce_lineage(manifest_path, project_root=root)
            if list(manifest_path.parent.glob("*INCOMPLETE*.json")):
                raise ValueError("child bundle is marked incomplete")
            payload = _read_json_mapping(manifest_path, f"{spec.title} manifest")
            files = _validated_child_files(
                payload,
                manifest_path=manifest_path,
                project_root=root,
            )
            inputs = _validated_child_inputs(payload, project_root=root)
            expected_inputs = _EVIDENCE_LAYER_INPUT_ROLES.get(spec.key)
            if expected_inputs is not None:
                observed_inputs = {
                    str(entry.get("role")): entry for entry, _ in inputs
                }
                if set(observed_inputs) != set(expected_inputs):
                    raise ValueError("child manifest has an incomplete input-role set")
                if any(
                    entry.get("evidence_types") != [evidence]
                    for role, evidence in expected_inputs.items()
                    for entry in (observed_inputs[role],)
                ):
                    raise ValueError("child manifest input evidence labels are invalid")
            detail = _EVIDENCE_LAYER_VALIDATORS[spec.key](payload, files, inputs, root)
        except (KeyError, OSError, TypeError, ValueError) as exc:
            statuses.append(
                EvidenceLayerStatus(
                    key=spec.key,
                    title=spec.title,
                    classification=spec.classification,
                    interpretation=spec.interpretation,
                    available=False,
                    detail=f"unavailable: {exc}",
                )
            )
        else:
            statuses.append(
                EvidenceLayerStatus(
                    key=spec.key,
                    title=spec.title,
                    classification=spec.classification,
                    interpretation=spec.interpretation,
                    available=True,
                    detail=detail,
                    manifest_path=manifest_path,
                    manifest_sha256=_sha256(manifest_path),
                )
            )
    return tuple(statuses)


def evidence_layer_rows(
    statuses: Sequence[EvidenceLayerStatus],
) -> tuple[Mapping[str, str], ...]:
    """Return a deterministic display schema without changing decision state."""

    return tuple(
        {
            "Evidence layer": status.title,
            "Status": "Available" if status.available else "Unavailable",
            "Classification": status.classification,
            "Interpretation": status.interpretation,
            "Validation": status.detail,
        }
        for status in statuses
    )


def _validate_declared_scenario_coverage(frame: pd.DataFrame) -> tuple[str, ...]:
    """Validate that the artifact contains every predeclared sensitivity scenario."""

    required = {"scenario", "declared_scenario_set", "declared_scenario_count"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"benchmark artifact missing columns: {sorted(missing)}")
    declarations = frame["declared_scenario_set"].dropna().astype(str).unique()
    if len(declarations) != 1 or frame["declared_scenario_set"].isna().any():
        raise ValueError("benchmark rows do not share one declared scenario set")
    try:
        raw_declared = json.loads(declarations[0])
    except json.JSONDecodeError as exc:
        raise ValueError("benchmark declared scenario set is malformed JSON") from exc
    if (
        not isinstance(raw_declared, list)
        or not raw_declared
        or not all(isinstance(item, str) and item for item in raw_declared)
        or len(raw_declared) != len(set(raw_declared))
    ):
        raise ValueError("benchmark declared scenario set must be a nonempty unique string list")
    declared = tuple(raw_declared)
    counts = pd.to_numeric(frame["declared_scenario_count"], errors="coerce")
    if counts.isna().any() or not counts.eq(len(declared)).all():
        raise ValueError("benchmark declared scenario count is inconsistent")
    observed_values = frame["scenario"].dropna().astype(str)
    if len(observed_values) != len(frame) or set(observed_values) != set(declared):
        raise ValueError("benchmark rows do not cover the complete declared scenario set")
    return declared


def load_benchmark_artifact(path: str | Path | None = None) -> BenchmarkArtifact | None:
    """Load a generated benchmark, rejecting missing causal provenance labels."""

    lineage_validated = path is None
    if path is None:
        directory = _project_root() / "artifacts" / "benchmarks"
        incomplete = _project_root() / "artifacts" / "REPRODUCE_INCOMPLETE.json"
        manifest = _project_root() / "artifacts" / "reproduce_manifest.json"
        if incomplete.exists():
            raise ValueError(
                "reproduction is marked incomplete; generated benchmark artifacts are unavailable"
            )
        if not manifest.is_file():
            raise ValueError("top-level artifacts/reproduce_manifest.json is missing")
        source = next(
            (directory / name for name in _ARTIFACT_CANDIDATES if (directory / name).is_file()),
            None,
        )
        if source is None:
            return None
        _validate_reproduce_lineage(source)
    else:
        source = Path(path)
        if not source.is_file():
            return None

    frame = pd.read_csv(source)
    required = {
        "declared_scenario_count",
        "declared_scenario_set",
        "design",
        "estimator",
        "target_estimand",
        "bias",
        "rmse",
        "coverage",
        "power",
        "scenario",
        "identified",
        "inference_valid",
        "fit_complete",
        "applicable",
        "attempted_fits",
        "successful_fits",
        "evidence_type",
    }
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"benchmark artifact missing columns: {sorted(missing)}")
    if frame.empty:
        raise ValueError("benchmark artifact is empty")
    provenance = frame["evidence_type"].astype(str)
    if not provenance.str.startswith("semi_synthetic").all():
        raise ValueError("dashboard causal benchmarks must be explicitly labelled semi-synthetic")
    declared_scenarios = _validate_declared_scenario_coverage(frame)
    return BenchmarkArtifact(
        path=source.resolve(),
        summary=frame,
        declared_scenarios=declared_scenarios,
        lineage_validated=lineage_validated,
    )


_SCENARIO_COLUMNS: Final[Mapping[str, tuple[str, ...]]] = {
    "treatment_version": ("treatment_version", "intervention_version"),
    "spillover_strength": ("spillover_strength",),
    "persistence": ("persistence",),
    "experiment_duration": ("duration", "experiment_duration", "n_periods"),
    "n_zones": ("n_zones",),
    "treatment_duration": ("treatment_duration", "block_length"),
    "n_clusters": ("configured_geo_clusters", "n_clusters"),
    "treatment_saturation": ("treatment_saturation", "saturation"),
    "washout_periods": ("washout_periods", "washout"),
    "incentive_size": ("incentive_size", "incentive_per_driver"),
    "treatment_probability": ("treatment_probability", "assignment_probability"),
}

_TEMPORAL_DESIGNS: Final[frozenset[str]] = frozenset(
    {DesignName.TIME_BLOCK.value, DesignName.SWITCHBACK.value, DesignName.GEO_TIME.value}
)
_GEO_DESIGNS: Final[frozenset[str]] = frozenset(
    {DesignName.GEO_CLUSTER.value, DesignName.GEO_TIME.value}
)


def match_benchmark_artifact(
    artifact: BenchmarkArtifact,
    controls: DashboardControls,
) -> tuple[pd.DataFrame, tuple[str, ...]]:
    """Filter an artifact and report scenario dimensions absent from its metadata."""

    frame = artifact.summary.loc[
        artifact.summary["target_estimand"].astype(str) == controls.target_estimand
    ].copy()
    missing_dimensions: list[str] = []
    for field, aliases in _SCENARIO_COLUMNS.items():
        column = next((candidate for candidate in aliases if candidate in frame.columns), None)
        if column is None:
            missing_dimensions.append(field)
            continue
        if field == "treatment_version":
            version = artifact.summary[column].dropna().astype(str)
            if version.empty:
                missing_dimensions.append(field)
                continue
            expected_version = TreatmentVersion.parse(controls.treatment_version).value
            normalized_version = (
                frame[column]
                .astype(str)
                .str.strip()
                .str.lower()
                .str.replace("-", "_", regex=False)
                .str.replace(" ", "_", regex=False)
            )
            frame = frame.loc[normalized_version == expected_version]
            continue
        artifact_numeric = pd.to_numeric(artifact.summary[column], errors="coerce")
        if (
            field == "n_clusters"
            and not artifact.summary["design"].astype(str).isin(_GEO_DESIGNS).any()
        ):
            # Cluster count is explicitly not applicable to purely temporal or
            # individual assignment families.
            continue
        if not artifact_numeric.notna().any():
            missing_dimensions.append(field)
            continue
        numeric = pd.to_numeric(frame[column], errors="coerce")
        if field == "n_clusters":
            geo = frame["design"].astype(str).isin(_GEO_DESIGNS)
            matches = ~geo | np.isclose(numeric, float(controls.n_clusters), rtol=1e-9, atol=1e-9)
        elif field == "washout_periods":
            temporal = frame["design"].astype(str).isin(_TEMPORAL_DESIGNS)
            expected = np.where(temporal, controls.washout_periods, 0.0)
            matches = np.isclose(numeric, expected, rtol=1e-9, atol=1e-9)
        elif field == "n_zones":
            expected = float(max(4, controls.n_clusters * 2))
            matches = np.isclose(numeric, expected, rtol=1e-9, atol=1e-9)
        else:
            expected = float(getattr(controls, field))
            matches = np.isclose(numeric, expected, rtol=1e-9, atol=1e-9)
        frame = frame.loc[matches]

    budget = (
        pd.to_numeric(frame["budget"], errors="coerce")
        if "budget" in frame
        else pd.Series(np.nan, index=frame.index, dtype=float)
    )
    finite_budget = np.isfinite(budget)
    budget_matches = finite_budget & np.isclose(
        budget,
        float(controls.budget),
        rtol=1e-9,
        atol=1e-9,
    )
    interpretable_budget = bool(finite_budget.any())
    if {"budget_scope", "nonbinding_budget_threshold"}.issubset(frame.columns):
        threshold = pd.to_numeric(frame["nonbinding_budget_threshold"], errors="coerce")
        if {"max_full_policy_spend", "max_realized_schedule_spend"}.issubset(
            frame.columns
        ):
            local_threshold = pd.concat(
                [
                    pd.to_numeric(frame["max_full_policy_spend"], errors="coerce"),
                    pd.to_numeric(frame["max_realized_schedule_spend"], errors="coerce"),
                ],
                axis=1,
            ).max(axis=1, skipna=True)
            # Per-scenario/design maxima are both safer and less over-conservative
            # than a global maximum driven by a different market geometry. The
            # global threshold remains the fail-safe fallback for legacy artifacts.
            threshold = local_threshold.where(np.isfinite(local_threshold), threshold)
        scope = frame["budget_scope"].astype(str).str.lower()
        certified_unconstrained = (
            ~finite_budget
            & scope.str.contains("unconstrained", na=False)
            & np.isfinite(threshold)
        )
        interpretable_budget = interpretable_budget or bool(certified_unconstrained.any())
        budget_matches |= certified_unconstrained & (
            float(controls.budget) + 1e-9 >= threshold
        )
    if not interpretable_budget:
        missing_dimensions.append("budget")
    frame = frame.loc[budget_matches]
    return frame.reset_index(drop=True), tuple(dict.fromkeys(missing_dimensions))


def artifact_decision(
    artifact: BenchmarkArtifact,
    controls: DashboardControls,
) -> ArtifactDecision | None:
    """Return an identification-safe recommendation for the artifact's declared scenario."""

    try:
        declared_scenarios = _validate_declared_scenario_coverage(artifact.summary)
    except ValueError:
        return None
    rows, missing = match_benchmark_artifact(artifact, controls)
    if rows.empty or missing:
        return None
    matched_scenarios = tuple(sorted(rows["scenario"].dropna().astype(str).unique()))
    unmatched_scenarios = tuple(
        sorted(set(declared_scenarios).difference(matched_scenarios))
    )
    is_conditional = bool(unmatched_scenarios)
    if is_conditional and not artifact.lineage_validated:
        # A subset recommendation is safe only when the complete source artifact
        # was tied to the current source/config tree by the top reproduction manifest.
        return None
    try:
        recommendation = recommend_design(
            rows,
            controls,
            require_declared_scenarios=not is_conditional,
        )
    except ValueError:
        return None
    return ArtifactDecision(
        rows=rows,
        recommendation=recommendation,
        missing_dimensions=missing,
        recommendation_scope=(
            "selected_scenario_conditional"
            if is_conditional
            else "declared_sensitivity_set"
        ),
        matched_scenarios=matched_scenarios,
        unmatched_scenarios=unmatched_scenarios,
    )


def _format_number(value: Any, *, digits: int = 3) -> str:
    if value is None:
        return "—"
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return str(value)
    if not np.isfinite(numeric):
        return "—"
    return f"{numeric:,.{digits}f}"


def _recommended_design_caveat(decision: ArtifactDecision) -> str:
    """Build the caveat shown alongside the artifact-recommended design."""

    design = DesignName.parse(str(decision.recommendation["design"])).value
    return f"Recommended-design caveat ({DESIGN_LABELS[design]}): {design_limitations(design)}"


def _same_dashboard_controls(left: object, right: DashboardControls) -> bool:
    """Compare cached controls across Streamlit script-class reloads."""

    try:
        return all(
            getattr(left, field) == getattr(right, field)
            for field in DashboardControls.__dataclass_fields__
        )
    except AttributeError:
        return False


def _render_controls(st: Any) -> DashboardControls:
    defaults = DashboardControls()
    st.sidebar.header("Experiment scenario")
    design = st.sidebar.selectbox(
        "Randomization unit",
        options=SUPPORTED_DESIGNS,
        index=SUPPORTED_DESIGNS.index(defaults.randomization_unit),
        format_func=lambda value: DESIGN_LABELS[value],
    )
    treatment_version = st.sidebar.selectbox(
        "Treatment version",
        options=tuple(version.value for version in TreatmentVersion),
        index=tuple(version.value for version in TreatmentVersion).index(
            defaults.treatment_version
        ),
        format_func=lambda value: TREATMENT_VERSION_LABELS[value],
    )
    duration = int(
        st.sidebar.slider(
            "Experiment duration (periods)",
            12,
            168,
            defaults.experiment_duration,
            step=4,
        )
    )
    clusters = int(
        st.sidebar.slider(
            "Geographic clusters",
            2,
            16,
            defaults.n_clusters,
            help=(
                "Controls independent geographic assignment groups for geo designs. "
                "For individual or temporal designs it controls simulated market size, not "
                "their effective randomized-unit count."
            ),
        )
    )
    spillover = float(
        st.sidebar.slider(
            "Neighbor spillover strength", 0.0, 0.6, defaults.spillover_strength, 0.05
        )
    )
    persistence = float(
        st.sidebar.slider("Persistence", 0.0, 0.9, defaults.persistence, 0.05)
    )
    incentive = float(
        st.sidebar.number_input(
            "Driver incentive per treated driver (driver/bundled)",
            0.0,
            10.0,
            defaults.incentive_size,
            0.5,
        )
    )
    budget = float(
        st.sidebar.number_input(
            "Experiment budget", 0.0, 100_000.0, defaults.budget, 500.0
        )
    )

    with st.sidebar.expander("Assignment details"):
        max_block = max(1, duration // 2)
        block = int(
            st.slider(
                "Treatment block duration",
                1,
                max_block,
                min(defaults.treatment_duration, max_block),
            )
        )
        washout = int(
            st.slider(
                "Washout periods",
                0,
                max(0, block - 1),
                min(defaults.washout_periods, block - 1),
            )
        )
        saturation = float(
            st.slider(
                "Treatment saturation",
                0.1,
                1.0,
                defaults.treatment_saturation,
                0.05,
            )
        )
        treatment_probability = float(
            st.slider(
                "Treatment probability",
                0.1,
                0.9,
                defaults.treatment_probability,
                0.05,
            )
        )
        replications = int(
            st.slider("Scenario replications", 2, 100, defaults.replications, 1)
        )
        seed = int(
            st.number_input("Deterministic seed", 0, 2**31 - 1, defaults.seed, 1)
        )

    return DashboardControls(
        randomization_unit=design,
        treatment_version=treatment_version,
        experiment_duration=duration,
        n_clusters=clusters,
        spillover_strength=spillover,
        persistence=persistence,
        incentive_size=incentive,
        budget=budget,
        treatment_duration=block,
        washout_periods=washout,
        treatment_saturation=saturation,
        treatment_probability=treatment_probability,
        replications=replications,
        seed=seed,
    )


def _render_estimand(st: Any, controls: DashboardControls) -> None:
    definition = get_estimand(controls.target_estimand)
    registry_compatible = controls.randomization_unit in definition.compatible_designs
    implemented_reasons: list[str] = []
    if controls.randomization_unit == DesignName.INDIVIDUAL.value:
        implemented_reasons.append(
            "individual assignment does not target a connected market's full-policy total effect"
        )
    if controls.spillover_strength > 0 and controls.randomization_unit in {
        DesignName.GEO_CLUSTER.value,
        DesignName.GEO_TIME.value,
    }:
        implemented_reasons.append(
            "the displayed assignment regression has no modeled neighbor-exposure term or "
            "isolated-market contrast"
        )
    if controls.persistence > 0 and controls.randomization_unit in _TEMPORAL_DESIGNS:
        implemented_reasons.append(
            "the displayed assignment regression has no treatment-history or carryover term"
        )
    st.subheader("Pre-specified target estimand")
    st.markdown(f"**{definition.label}** (`{definition.name.value}`)  ")
    st.write(definition.contrast)
    st.caption(
        f"Unit: {definition.unit}. Registry-level design compatibility: "
        f"{'compatible' if registry_compatible else 'incompatible'}. This registry screen is "
        "theoretical and is not evidence that the implemented estimator identifies the target."
    )
    if implemented_reasons:
        st.error(
            "Implemented target-identification check fails for this scenario: "
            + "; ".join(implemented_reasons)
            + "."
        )
    else:
        st.warning(
            "The on-demand estimator is displayed only as an assignment diagnostic. Target "
            "identification and inferential validity must come from an exact-scenario benchmark "
            "row that passes all artifact safety gates."
        )


def _render_evidence_layers(st: Any) -> None:
    statuses = load_evidence_layers()
    st.subheader("Evidence layers")
    st.caption(
        "Read-only provenance view. Availability requires the current source/config hash, "
        "top-manifest bytes and SHA-256, and every child-manifest scientific and file-hash "
        "gate. These layers do not alter the design recommendation."
    )
    st.dataframe(
        pd.DataFrame(evidence_layer_rows(statuses)),
        use_container_width=True,
        hide_index=True,
    )


def _best_artifact_row(
    decision: ArtifactDecision,
    controls: DashboardControls,
    design: str,
) -> pd.Series | None:
    candidates = decision.rows.loc[decision.rows["design"].astype(str) == design]
    if candidates.empty:
        return None
    try:
        return recommend_design(
            candidates,
            controls,
            require_declared_scenarios=(
                decision.recommendation_scope != "selected_scenario_conditional"
            ),
        )
    except ValueError:
        return None


def _render_artifact_status(
    st: Any,
    controls: DashboardControls,
) -> ArtifactDecision | None:
    try:
        artifact = load_benchmark_artifact()
    except ValueError as exc:
        st.error(f"Generated benchmark artifact was rejected: {exc}")
        return None
    if artifact is None:
        st.info(
            "No generated benchmark artifact is available for this scenario. "
            "Bias, uncertainty, power, and a benchmark-ranked recommendation remain unavailable; "
            "the dashboard will not invent them."
        )
        return None
    matched_rows, missing_dimensions = match_benchmark_artifact(artifact, controls)
    decision = artifact_decision(artifact, controls)
    if decision is None:
        if missing_dimensions:
            st.info(
                f"Benchmark artifact `{artifact.path.name}` cannot support this dashboard "
                "scenario because it omits causally relevant dimensions: "
                f"{', '.join(missing_dimensions)}. Recovery benchmarks with an unconstrained "
                "budget are not reused for a binding-budget decision."
            )
        elif matched_rows.empty:
            st.info(
                f"Benchmark artifact `{artifact.path.name}` contains no exact row for all "
                "declared scenario controls."
            )
        else:
            st.info(
                f"Benchmark artifact `{artifact.path.name}` has exact scenario rows, but none "
                "passes identification, inference-validity, complete-fit, finite-metric, and "
                "coverage gates."
            )
        return None
    if decision.missing_dimensions:
        st.warning(
            f"`{artifact.path.name}` matches available fields but omits scenario metadata for: "
            f"{', '.join(decision.missing_dimensions)}. Its inferential metrics and recommendation "
            "are conditional on the artifact's declared scenario, not an exact match to every "
            "dashboard control."
        )
    else:
        if decision.recommendation_scope == "selected_scenario_conditional":
            st.warning(
                f"Loaded an exact-control benchmark subset from `{artifact.path.name}`. The "
                "recommendation is conditional on the matched scenario(s), not robust across "
                "the artifact's full declared sensitivity set. Matched: "
                f"{', '.join(decision.matched_scenarios)}. Unmatched mechanisms/scenarios: "
                f"{', '.join(decision.unmatched_scenarios)}."
            )
        else:
            st.success(
                f"Loaded an exact-scenario generated benchmark covering its full declared "
                f"sensitivity set: `{artifact.path.name}`"
            )
        if "nonbinding_budget_threshold" in decision.rows:
            threshold = float(
                pd.to_numeric(decision.rows["nonbinding_budget_threshold"], errors="coerce").max()
            )
            st.caption(
                f"The recovery run disabled budget enforcement, but its recorded maximum "
                f"treatment spend was {_format_number(threshold, digits=0)} at the same incentive "
                f"dose. The selected budget {_format_number(controls.budget, digits=0)} is at or "
                "above that conservative nonbinding threshold."
            )
    with st.expander("Generated benchmark artifact rows"):
        st.dataframe(decision.rows, use_container_width=True, hide_index=True)
    return decision


def _render_result(
    st: Any,
    scenario: ScenarioBenchmark,
    benchmark_decision: ArtifactDecision | None,
) -> None:
    selected = scenario.selected
    st.markdown(
        "> **Evidence separation:** on-demand values below are structural simulator "
        "counterfactuals with known truth. The calibration uses descriptive public-trip moments; "
        "it does not identify any treatment, spillover, persistence, or dose-response parameter."
    )

    st.subheader("Validated Monte Carlo benchmark evidence")
    selected_artifact = (
        _best_artifact_row(
            benchmark_decision,
            scenario.controls,
            scenario.controls.randomization_unit,
        )
        if benchmark_decision is not None
        else None
    )
    inference = st.columns(3)
    if selected_artifact is None:
        inference[0].metric("Estimated bias", "Unavailable")
        inference[1].metric("Estimated uncertainty", "Unavailable")
        inference[2].metric("Estimated power", "Unavailable")
        st.caption(
            "No identified generated benchmark row matches the selected design and recorded "
            "scenario fields. On-demand assignment diagnostics are not relabelled as bias or "
            "power for the market-total target."
        )
    else:
        inference[0].metric("Estimated bias", _format_number(selected_artifact["bias"]))
        inference[1].metric(
            "Mean standard error",
            _format_number(selected_artifact.get("mean_std_error")),
        )
        inference[2].metric(
            "Estimated power",
            _format_number(selected_artifact["power"], digits=3),
        )
        st.caption(
            f"Artifact estimator `{selected_artifact['estimator']}`; bias MCSE "
            f"{_format_number(selected_artifact.get('bias_mcse'))}; "
            f"{int(selected_artifact.get('replications', 0)) or '—'} replications; "
            f"evidence `{selected_artifact['evidence_type']}`."
        )

    st.subheader("On-demand full-policy structural scenario")
    st.caption(
        f"Treatment version: {TREATMENT_VERSION_LABELS[str(selected['treatment_version'])]}. "
        "Only the declared market-side pathways and costs are active."
    )
    structural = st.columns(4)
    structural[0].metric(
        "Target effect per zone-period",
        _format_number(selected["full_policy_truth"]),
    )
    structural[1].metric(
        "Expected incremental trips",
        _format_number(selected["expected_incremental_outcome"], digits=1),
    )
    structural[2].metric(
        "Full-policy spend",
        _format_number(selected["mean_full_policy_spend"], digits=0),
    )
    structural[3].metric(
        "Incremental trips per dollar",
        _format_number(selected["budget_efficiency"], digits=4),
    )
    welfare = st.columns(2)
    welfare[0].metric(
        "Modeled incremental welfare",
        _format_number(selected["modeled_incremental_welfare"], digits=1),
    )
    welfare[1].metric(
        "Modeled welfare per dollar",
        _format_number(selected["modeled_welfare_per_dollar"], digits=4),
    )
    st.caption(
        f"Averages over {int(selected['replications'])} configured simulator draws. Incremental "
        f"outcome MC SD: {_format_number(selected['incremental_outcome_mc_sd'])}; mean full-policy "
        f"budget scale: {_format_number(selected['mean_full_policy_budget_scale'])}. The numerator "
        "and denominator both use the feasible all-zone policy, never the mixed experiment path."
    )
    st.caption(
        "Welfare is an incomplete modeled construct using configured rider value, operating cost, "
        "wait disutility, and transfers. It omits distributional weights and unmodeled externalities."
    )

    st.subheader("Conditional experiment recommendation")
    if benchmark_decision is None:
        st.warning(
            "No benchmark-supported design recommendation is available. Generate an identified "
            "Monte Carlo artifact for the declared estimand before choosing a launch design."
        )
    else:
        recommendation = benchmark_decision.recommendation
        recommendation_text = (
            f"For the exactly matched scenario, conditionally prefer "
            f"**{DESIGN_LABELS[str(recommendation['design'])]}** with "
            f"`{recommendation['estimator']}` for `{scenario.controls.target_estimand}`. "
            "This is not a sensitivity-robust recommendation. Unmatched declared "
            f"mechanisms/scenarios: {', '.join(benchmark_decision.unmatched_scenarios)}."
            if benchmark_decision.recommendation_scope
            == "selected_scenario_conditional"
            else f"Across the artifact's full declared sensitivity set, prefer "
            f"**{DESIGN_LABELS[str(recommendation['design'])]}** with "
            f"`{recommendation['estimator']}` for `{scenario.controls.target_estimand}`."
        )
        st.success(recommendation_text)
        st.warning(_recommended_design_caveat(benchmark_decision))
        qualifier = (
            " Missing dashboard dimensions: "
            + ", ".join(benchmark_decision.missing_dimensions)
            + "."
            if benchmark_decision.missing_dimensions
            else ""
        )
        st.caption(
            "The ranking minimizes generated RMSE with a coverage penalty after excluding "
            f"unidentified and estimand-incompatible rows. Recommendation scope: "
            f"`{benchmark_decision.recommendation_scope}`.{qualifier}"
        )

    st.subheader("Observed assignment diagnostic — not the target estimand")
    diagnostic = st.columns(4)
    diagnostic[0].metric(
        "Mean assignment coefficient",
        _format_number(selected["mean_assignment_estimate"]),
    )
    diagnostic[1].metric(
        "Mean assignment SE",
        _format_number(selected["mean_assignment_std_error"]),
    )
    diagnostic[2].metric(
        "Assignment coefficient MC SD",
        _format_number(selected["assignment_estimate_mc_sd"]),
    )
    diagnostic[3].metric(
        "Null-rejection diagnostic",
        _format_number(selected["assignment_rejection_rate"], digits=3),
    )
    st.warning(
        "This coefficient generally does not equal the feasible full-policy market-total effect "
        "under interference, carryover, nonlinear saturation, washout filtering, or a binding "
        "shared budget. Its coefficient-minus-truth gap is therefore not reported as bias, and "
        "its rejection rate is not reported as power for the target estimand."
    )
    st.caption(
        f"Effective randomized clusters/units recorded by the estimator: "
        f"{int(selected['effective_clusters'])}. The geographic-cluster control changes this "
        "count only for geo-randomized designs."
    )

    st.subheader("Limitations and decision guardrails")
    for limitation in scenario.limitations:
        st.markdown(f"- {limitation}")

    with st.expander("Reproducibility metadata"):
        st.json(
            {
                "evidence_type": scenario.evidence_type,
                "target_estimand": scenario.controls.target_estimand,
                "calibration_path": (
                    str(scenario.calibration_path) if scenario.calibration_path else None
                ),
                "calibration_sha256": scenario.calibration_sha256,
                "controls": {
                    field: getattr(scenario.controls, field)
                    for field in scenario.controls.__dataclass_fields__
                },
            }
        )


def render_dashboard() -> None:
    """Render the Streamlit app; importing this module never starts the UI."""

    try:
        import streamlit as st
    except ImportError as exc:  # pragma: no cover - depends on optional installation
        raise RuntimeError(
            "The dashboard extra is not installed. Install the project with '[dashboard]'."
        ) from exc

    st.set_page_config(page_title="Causal Marketplace Lab", page_icon="🧪", layout="wide")
    st.title("Causal Marketplace Lab")
    st.write(
        "Stress-test marketplace experiment designs under configurable interference, "
        "persistence, and incentive budgets."
    )
    _render_evidence_layers(st)
    controls = _render_controls(st)
    _render_estimand(st, controls)
    benchmark_decision = _render_artifact_status(st, controls)

    run = st.button("Run on-demand structural scenario", type="primary")
    if run:
        with st.spinner(
            f"Generating {controls.replications} deterministic-seed draws for "
            f"{DESIGN_LABELS[controls.randomization_unit]}…"
        ):
            try:
                scenario = run_scenario_benchmark(controls)
            except (ValueError, RuntimeError) as exc:
                st.error(f"Scenario could not be estimated: {exc}")
            else:
                st.session_state["casuallab_scenario"] = scenario
    cached = st.session_state.get("casuallab_scenario")
    if cached is not None and hasattr(cached, "controls") and hasattr(cached, "summary"):
        if not _same_dashboard_controls(cached.controls, controls):
            st.warning(
                "Controls changed after the prior run. Cached structural results and the current "
                "artifact recommendation are hidden until you rerun this scenario."
            )
        else:
            _render_result(st, cached, benchmark_decision)


def main() -> None:
    """Console-friendly entry point used by ``streamlit run`` and tests."""

    render_dashboard()


if __name__ == "__main__":  # pragma: no cover - Streamlit execution path
    main()
