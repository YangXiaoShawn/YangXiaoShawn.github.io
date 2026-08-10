"""Fail-closed NYC-informed known-truth marketplace benchmarks.

The NYC simulation anchor contributes descriptive scale and heterogeneity
initializers.  Causal effects in this benchmark remain structural simulator truths
under explicit assumptions; they are never described as effects estimated from NYC
trip records.  This module is independent of the default marketplace benchmark entry
points so it cannot silently change the Chicago/sample workflow.
"""

from __future__ import annotations

import json
import math
import re
import shutil
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, replace
from numbers import Integral, Real
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from casuallab.benchmark import BenchmarkConfig
from casuallab.config import DesignName, SimulationConfig, load_simulation_config
from casuallab.data import sha256_file
from casuallab.marketplace_benchmark import (
    MarketplaceBenchmarkResult,
    SensitivityScenario,
    run_marketplace_benchmark,
)
from casuallab.nyc_simulation import (
    ANCHOR_EVIDENCE_LABEL,
    ANCHOR_SCHEMA_VERSION,
    CAUSAL_ASSUMPTION_FIELDS,
    NYCSimulationAnchorSettings,
    build_nyc_simulation_anchor,
)

NYC_BENCHMARK_EVIDENCE_TYPE = (
    "semi_synthetic_nyc_informed_known_truth_monte_carlo"
)
NYC_BENCHMARK_SCHEMA_VERSION = "1.0.0"
_VALIDATED_ANCHOR_STATUS = (
    "descriptive_control_path_anchor_validated_not_fitted_structural_model"
)
_HASH_PATTERN = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True, slots=True)
class NYCBenchmarkConfig:
    """Laptop-safe orchestration settings for an NYC-informed benchmark.

    Geometry is an explicit simulation-size override and cannot exceed the anchor
    geometry.  The default 16 x 48 panel supplies eight geographic clusters and
    twelve four-hour blocks for the repository's standard anchor while remaining
    inexpensive enough for focused local runs.
    """

    replications: int = 6
    seed: int = 870221
    confidence_level: float = 0.95
    designs: tuple[str, ...] = ("geo_cluster", "geo_time")
    estimators: tuple[str, ...] = (
        "cluster_robust",
        "two_way_cluster_robust",
    )
    n_zones: int | None = 16
    n_periods: int | None = 48
    cost_per_market_period: float = 1.0
    max_replications: int = 32
    max_panel_cells: int = 4096
    max_planned_fits: int = 256

    def __post_init__(self) -> None:
        integer_fields = (
            "replications",
            "seed",
            "max_replications",
            "max_panel_cells",
            "max_planned_fits",
        )
        for name in integer_fields:
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, Integral):
                raise ValueError(f"{name} must be an integer")
        for name in ("n_zones", "n_periods"):
            value = getattr(self, name)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, Integral)
            ):
                raise ValueError(f"{name} must be an integer when supplied")
        if self.replications < 2:
            raise ValueError("replications must be at least two")
        if self.max_replications < 2 or self.replications > self.max_replications:
            raise ValueError("replications exceed the declared laptop-safe maximum")
        if self.max_panel_cells < 1 or self.max_planned_fits < 1:
            raise ValueError("laptop-safety limits must be positive")
        if self.n_zones is not None and self.n_zones < 4:
            raise ValueError("n_zones must be at least four when supplied")
        if self.n_zones is not None and self.n_zones % 2:
            raise ValueError("n_zones must be even for two-zones-per-cluster geometry")
        if self.n_periods is not None and self.n_periods < 2:
            raise ValueError("n_periods must be at least two when supplied")
        if not isinstance(self.confidence_level, Real) or not math.isfinite(
            float(self.confidence_level)
        ):
            raise ValueError("confidence_level must be finite")
        if not 0.5 < self.confidence_level < 1.0:
            raise ValueError("confidence_level must lie in (0.5, 1)")
        if not isinstance(self.cost_per_market_period, Real) or not math.isfinite(
            float(self.cost_per_market_period)
        ):
            raise ValueError("cost_per_market_period must be finite")
        if self.cost_per_market_period <= 0:
            raise ValueError("cost_per_market_period must be positive")
        if not self.designs or not self.estimators:
            raise ValueError("at least one design and estimator are required")
        canonical_designs = tuple(DesignName.parse(value).value for value in self.designs)
        if len(canonical_designs) != len(set(canonical_designs)):
            raise ValueError("designs must not contain aliases of the same design")
        canonical_estimators = tuple(
            str(value).strip().lower().replace("-", "_").replace(" ", "_")
            for value in self.estimators
        )
        if any(not value for value in canonical_estimators):
            raise ValueError("estimator names must not be empty")
        if len(canonical_estimators) != len(set(canonical_estimators)):
            raise ValueError("estimators must not contain duplicates")
        object.__setattr__(self, "designs", canonical_designs)
        object.__setattr__(self, "estimators", canonical_estimators)

    def to_dict(self) -> dict[str, Any]:
        return {
            "replications": int(self.replications),
            "seed": int(self.seed),
            "confidence_level": float(self.confidence_level),
            "designs": list(self.designs),
            "estimators": list(self.estimators),
            "n_zones": None if self.n_zones is None else int(self.n_zones),
            "n_periods": None if self.n_periods is None else int(self.n_periods),
            "cost_per_market_period": float(self.cost_per_market_period),
            "max_replications": int(self.max_replications),
            "max_panel_cells": int(self.max_panel_cells),
            "max_planned_fits": int(self.max_planned_fits),
        }


@dataclass(frozen=True, slots=True)
class NYCBenchmarkResult:
    """NYC-labeled benchmark tables and serializable provenance metadata."""

    records: pd.DataFrame
    summary: pd.DataFrame
    failures: pd.DataFrame
    fit_ledger: pd.DataFrame
    metadata: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class _VerifiedAnchor:
    payload: Mapping[str, Any]
    simulation: SimulationConfig
    template: SimulationConfig
    hashes: Mapping[str, str]
    project_root: Path


def _load_json(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"{label} is required: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError(f"{label} is not readable valid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _hash(value: Any, label: str) -> str:
    if not isinstance(value, str) or _HASH_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _portable_path(value: Any, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a nonempty path string")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{label} must be project-relative and portable")
    return path


def _project_relative_path(path: Path, root: Path, label: str) -> str:
    """Render one resolved input path relative to its verified project root."""

    resolved = path.resolve()
    try:
        relative = resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"{label} must be contained by the verified project root") from exc
    if not relative.parts or relative == Path("."):
        raise ValueError(f"{label} must identify a file below the project root")
    return relative.as_posix()


def _manifest_root(
    manifest: Mapping[str, Any],
    anchor_path: Path,
    project_root: str | Path | None,
) -> Path:
    entries = manifest.get("files")
    if not isinstance(entries, list) or not entries:
        raise ValueError("NYC anchor manifest has no file entries")
    target = anchor_path.resolve()
    candidate_roots = (
        (Path(project_root).resolve(),)
        if project_root is not None
        else tuple(target.parents)
    )
    matches: list[Path] = []
    for root in candidate_roots:
        for index, raw in enumerate(entries):
            if not isinstance(raw, Mapping):
                raise ValueError("NYC anchor manifest contains a non-object entry")
            relative = _portable_path(
                raw.get("path"), f"NYC anchor manifest.files[{index}].path"
            )
            resolved = (root / relative).resolve()
            try:
                resolved.relative_to(root)
            except ValueError as exc:
                raise ValueError("NYC anchor manifest entry escapes its root") from exc
            if resolved == target:
                matches.append(root)
    unique = tuple(dict.fromkeys(matches))
    if len(unique) != 1:
        raise ValueError("could not resolve one unambiguous NYC anchor manifest root")
    return unique[0]


def _verify_manifest_files(
    manifest: Mapping[str, Any], root: Path
) -> dict[Path, dict[str, Any]]:
    raw_entries = manifest.get("files")
    if not isinstance(raw_entries, list) or not raw_entries:
        raise ValueError("NYC anchor manifest.files must be a nonempty list")
    verified: dict[Path, dict[str, Any]] = {}
    for index, raw in enumerate(raw_entries):
        if not isinstance(raw, Mapping):
            raise ValueError("NYC anchor manifest contains a non-object entry")
        entry = dict(raw)
        relative = _portable_path(
            entry.get("path"), f"NYC anchor manifest.files[{index}].path"
        )
        resolved = (root / relative).resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise ValueError("NYC anchor manifest entry escapes its project root") from exc
        if resolved in verified:
            raise ValueError("NYC anchor manifest contains duplicate paths")
        byte_count = entry.get("bytes")
        if isinstance(byte_count, bool) or not isinstance(byte_count, int) or byte_count < 0:
            raise ValueError("NYC anchor manifest contains an invalid byte count")
        expected_sha = _hash(entry.get("sha256"), "NYC anchor manifest file hash")
        if not resolved.is_file():
            raise FileNotFoundError(f"NYC anchor manifest file is missing: {resolved}")
        if resolved.stat().st_size != byte_count:
            raise ValueError(f"NYC anchor manifest byte mismatch: {relative}")
        if sha256_file(resolved) != expected_sha:
            raise ValueError(f"NYC anchor manifest SHA-256 mismatch: {relative}")
        verified[resolved] = entry
    return verified


def _unique_file_by_hash(
    files: Mapping[Path, Mapping[str, Any]], digest: str, label: str
) -> Path:
    matches = [path for path, entry in files.items() if entry.get("sha256") == digest]
    if len(matches) != 1:
        raise ValueError(f"NYC anchor manifest must identify exactly one {label}")
    return matches[0]


def _verify_anchor(
    anchor_path: str | Path,
    anchor_manifest_path: str | Path,
    *,
    project_root: str | Path | None,
    expected_anchor_sha256: str | None,
    expected_anchor_manifest_sha256: str | None,
) -> _VerifiedAnchor:
    anchor_file = Path(anchor_path).resolve()
    manifest_file = Path(anchor_manifest_path).resolve()
    anchor_sha = sha256_file(anchor_file)
    manifest_sha = sha256_file(manifest_file)
    if expected_anchor_sha256 is not None and anchor_sha != _hash(
        expected_anchor_sha256, "expected_anchor_sha256"
    ):
        raise ValueError("NYC anchor SHA-256 disagrees with the external pin")
    if expected_anchor_manifest_sha256 is not None and manifest_sha != _hash(
        expected_anchor_manifest_sha256, "expected_anchor_manifest_sha256"
    ):
        raise ValueError("NYC anchor manifest SHA-256 disagrees with the external pin")

    anchor = _load_json(anchor_file, "NYC simulation anchor")
    manifest = _load_json(manifest_file, "NYC simulation anchor manifest")
    metadata = manifest.get("metadata")
    if not isinstance(metadata, Mapping):
        raise ValueError("NYC anchor manifest metadata is missing")
    if (
        anchor.get("schema_version") != ANCHOR_SCHEMA_VERSION
        or anchor.get("evidence_label") != ANCHOR_EVIDENCE_LABEL
        or anchor.get("causal_claim") is not False
        or anchor.get("status") != _VALIDATED_ANCHOR_STATUS
        or metadata.get("evidence_label") != ANCHOR_EVIDENCE_LABEL
        or metadata.get("causal_claim") is not False
        or metadata.get("status") != _VALIDATED_ANCHOR_STATUS
    ):
        raise ValueError("NYC anchor evidence contract is incompatible")

    root = _manifest_root(manifest, anchor_file, project_root)
    files = _verify_manifest_files(manifest, root)
    if anchor_file not in files or files[anchor_file].get("sha256") != anchor_sha:
        raise ValueError("NYC anchor is not covered by its manifest")
    calibration_sha = _hash(
        metadata.get("calibration_sha256"), "NYC anchor calibration_sha256"
    )
    calibration_manifest_sha = _hash(
        metadata.get("calibration_manifest_sha256"),
        "NYC anchor calibration_manifest_sha256",
    )
    template_sha = _hash(
        metadata.get("simulation_config_sha256"),
        "NYC anchor simulation_config_sha256",
    )
    source_manifest_sha = _hash(
        metadata.get("source_data_manifest_sha256"),
        "NYC anchor source_data_manifest_sha256",
    )
    calibration_file = _unique_file_by_hash(files, calibration_sha, "calibration file")
    calibration_manifest_file = _unique_file_by_hash(
        files, calibration_manifest_sha, "calibration manifest"
    )
    template_file = _unique_file_by_hash(files, template_sha, "simulation template")
    template = load_simulation_config(template_file)

    target_panel = anchor.get("target_panel")
    if not isinstance(target_panel, Mapping) or not isinstance(
        target_panel.get("simulation"), Mapping
    ):
        raise ValueError("NYC anchor target simulation geometry is missing")
    target = target_panel["simulation"]
    integer_values: dict[str, int] = {}
    for key in ("n_zones", "n_periods", "seed"):
        value = target.get(key)
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"NYC anchor target_panel.simulation.{key} must be an integer")
        integer_values[key] = value
    integrity = anchor.get("integrity")
    if not isinstance(integrity, Mapping):
        raise ValueError("NYC anchor integrity section is missing")
    root_mode = integrity.get("project_root_resolution")
    if root_mode not in {"explicit", "inferred_from_portable_source_manifest_path"}:
        raise ValueError("NYC anchor project-root provenance is invalid")
    rebuilt = build_nyc_simulation_anchor(
        calibration_file,
        project_root=(root if root_mode == "explicit" else None),
        manifest_path=calibration_manifest_file,
        settings=NYCSimulationAnchorSettings(
            target_n_zones=integer_values["n_zones"],
            target_n_periods=integer_values["n_periods"],
            seed=integer_values["seed"],
        ),
        assumption_template=template,
    )
    if rebuilt != anchor:
        raise ValueError(
            "NYC anchor does not exactly reconstruct from its calibration and template lineage"
        )
    if rebuilt["integrity"]["source_data_manifest_sha256"] != source_manifest_sha:
        raise ValueError("NYC anchor source-data manifest hash disagrees with metadata")
    simulation = SimulationConfig.from_dict(rebuilt["simulation_config"])
    return _VerifiedAnchor(
        payload=rebuilt,
        simulation=simulation,
        template=template,
        hashes={
            "anchor_sha256": anchor_sha,
            "anchor_manifest_sha256": manifest_sha,
            "calibration_sha256": calibration_sha,
            "calibration_manifest_sha256": calibration_manifest_sha,
            "simulation_template_sha256": template_sha,
            "source_data_manifest_sha256": source_manifest_sha,
        },
        project_root=root,
    )


def validate_nyc_benchmark_anchor(
    anchor_path: str | Path,
    anchor_manifest_path: str | Path,
    *,
    project_root: str | Path | None = None,
    expected_anchor_sha256: str | None = None,
    expected_anchor_manifest_sha256: str | None = None,
) -> dict[str, Any]:
    """Validate and exactly reconstruct an NYC anchor for benchmark use."""

    verified = _verify_anchor(
        anchor_path,
        anchor_manifest_path,
        project_root=project_root,
        expected_anchor_sha256=expected_anchor_sha256,
        expected_anchor_manifest_sha256=expected_anchor_manifest_sha256,
    )
    return {
        "schema_version": NYC_BENCHMARK_SCHEMA_VERSION,
        "evidence_label": ANCHOR_EVIDENCE_LABEL,
        "causal_claim": False,
        "exact_reconstruction_passed": True,
        "hashes": dict(verified.hashes),
        "simulation_config": verified.simulation.to_dict(),
    }


def default_nyc_benchmark_scenarios(
    anchor_simulation: SimulationConfig,
) -> tuple[SensitivityScenario, ...]:
    """Return one anchor-assumption scenario and one identification reference."""

    return (
        SensitivityScenario(
            "anchor_explicit_assumptions",
            spillover_strength=anchor_simulation.spillover_strength,
            persistence=anchor_simulation.persistence,
            varied_dimension="anchor_explicit_causal_assumptions",
        ),
        SensitivityScenario(
            "no_interference_no_carryover",
            spillover_strength=0.0,
            persistence=0.0,
            varied_dimension="reference",
        ),
    )


def _effective_base(
    anchor: SimulationConfig,
    config: NYCBenchmarkConfig,
) -> tuple[SimulationConfig, dict[str, Any]]:
    n_zones = min(16, anchor.n_zones) if config.n_zones is None else int(config.n_zones)
    n_periods = (
        min(48, anchor.n_periods) if config.n_periods is None else int(config.n_periods)
    )
    if n_zones > anchor.n_zones or n_periods > anchor.n_periods:
        raise ValueError("NYC benchmark geometry cannot exceed the validated anchor geometry")
    if n_zones < 4 or n_zones % 2:
        raise ValueError("effective NYC benchmark n_zones must be even and at least four")
    if n_zones * n_periods > config.max_panel_cells:
        raise ValueError("NYC benchmark panel exceeds max_panel_cells")
    geographic_clusters = n_zones // 2
    design = replace(
        anchor.design,
        n_clusters=geographic_clusters,
        cluster_size=2,
        budget=None,
        seed=config.seed + 1,
    )
    effective = replace(
        anchor,
        n_zones=n_zones,
        n_periods=n_periods,
        budget=None,
        seed=config.seed,
        design=design,
    )
    for field in CAUSAL_ASSUMPTION_FIELDS:
        if getattr(effective, field) != getattr(anchor, field):
            raise RuntimeError(f"NYC benchmark changed causal anchor field {field!r}")
    overrides = {
        "n_zones": {
            "anchor": anchor.n_zones,
            "effective": n_zones,
            "scope": "laptop_safe_geometry_override",
        },
        "n_periods": {
            "anchor": anchor.n_periods,
            "effective": n_periods,
            "scope": "laptop_safe_geometry_override",
        },
        "seed": {
            "anchor": anchor.seed,
            "effective": config.seed,
            "scope": "benchmark_monte_carlo_seed",
        },
        "budget": {
            "anchor": anchor.effective_budget,
            "effective": None,
            "scope": "unconstrained_estimator_recovery",
        },
        "design.n_clusters": {
            "anchor": anchor.design.n_clusters,
            "effective": geographic_clusters,
            "scope": "two_zones_per_geographic_cluster",
        },
        "design.cluster_size": {
            "anchor": anchor.design.cluster_size,
            "effective": 2,
            "scope": "two_zones_per_geographic_cluster",
        },
        "design.seed": {
            "anchor": anchor.design.seed,
            "effective": config.seed + 1,
            "scope": "benchmark_assignment_seed",
        },
    }
    return effective, overrides


def _scenario_causal_values(
    base: SimulationConfig, scenario: SensitivityScenario
) -> dict[str, Any]:
    values = {field: getattr(base, field) for field in CAUSAL_ASSUMPTION_FIELDS}
    values["spillover_strength"] = scenario.spillover_strength
    values["persistence"] = scenario.persistence
    if scenario.spillover_strength == 0:
        values["rider_substitution"] = 0.0
        values["driver_mobility"] = 0.0
    if scenario.treatment_version is not None:
        values["treatment_version"] = scenario.treatment_version
    return {
        key: (value.value if hasattr(value, "value") else value)
        for key, value in values.items()
    }


def _scenario_provenance(
    anchor: SimulationConfig,
    scenarios: tuple[SensitivityScenario, ...],
) -> dict[str, dict[str, Any]]:
    anchor_values = {
        field: (
            getattr(anchor, field).value
            if hasattr(getattr(anchor, field), "value")
            else getattr(anchor, field)
        )
        for field in CAUSAL_ASSUMPTION_FIELDS
    }
    result: dict[str, dict[str, Any]] = {}
    for scenario in scenarios:
        effective = _scenario_causal_values(anchor, scenario)
        overrides = {
            field: {"anchor": anchor_values[field], "effective": effective[field]}
            for field in CAUSAL_ASSUMPTION_FIELDS
            if effective[field] != anchor_values[field]
        }
        result[scenario.name] = {
            "anchor_causal_assumptions_preserved": not overrides,
            "causal_overrides": overrides,
            "interpretation": (
                "All causal quantities are explicit simulator assumptions, including "
                "declared sensitivity overrides; none is an NYC causal estimate."
            ),
        }
    return result


def _validate_scenario_geometry(
    base: SimulationConfig,
    anchor: SimulationConfig,
    config: NYCBenchmarkConfig,
    scenarios: tuple[SensitivityScenario, ...],
) -> None:
    planned_fits = (
        config.replications
        * len(scenarios)
        * len(config.designs)
        * len(config.estimators)
    )
    if planned_fits > config.max_planned_fits:
        raise ValueError("NYC benchmark plan exceeds max_planned_fits")
    for scenario in scenarios:
        clusters = scenario.n_clusters or base.design.n_clusters or 4
        n_zones = max(4, 2 * int(clusters))
        if n_zones > anchor.n_zones:
            raise ValueError(
                f"scenario {scenario.name!r} exceeds the validated anchor zone geometry"
            )
        if n_zones * base.n_periods > config.max_panel_cells:
            raise ValueError(f"scenario {scenario.name!r} exceeds max_panel_cells")


def _target_gates(
    result: MarketplaceBenchmarkResult,
    config: NYCBenchmarkConfig,
    anchor: SimulationConfig,
) -> dict[str, bool]:
    records = result.records
    summary = result.summary
    ledger = result.fit_ledger
    no_runtime_failures = bool(result.failures.empty)
    records_present = bool(not records.empty and not summary.empty)
    target_consistent = bool(
        records_present
        and records["target_estimand"].eq("market_total_effect").all()
        and summary["target_estimand"].eq("market_total_effect").all()
    )
    known_truth_finite = bool(
        records_present
        and np.isfinite(records["truth"].to_numpy(dtype=float)).all()
    )
    applicable = ledger.loc[ledger["applicable"].astype(bool)]
    complete_fits = bool(
        not applicable.empty
        and applicable["fit_complete"].astype(bool).all()
        and applicable["attempted_fits"].eq(config.replications).all()
        and applicable["successful_fits"].eq(config.replications).all()
    )
    identified = summary["identified"].astype(bool) if records_present else pd.Series(dtype=bool)
    inference_valid = (
        summary["inference_valid"].astype(bool)
        if records_present
        else pd.Series(dtype=bool)
    )
    at_least_one_valid_target = bool((identified & inference_valid).any())
    identified_metrics_finite = bool(
        identified.any()
        and np.isfinite(
            summary.loc[identified, ["bias", "rmse", "truth"]].to_numpy(dtype=float)
        ).all()
    )
    mismatch = ~identified
    mismatch_metrics_masked = bool(
        not mismatch.any()
        or summary.loc[mismatch, ["bias", "rmse", "coverage", "power"]]
        .isna()
        .all()
        .all()
    )
    geometry_bounded = bool(
        records_present
        and records["n_zones"].le(anchor.n_zones).all()
        and records["n_periods"].le(anchor.n_periods).all()
        and (
            records["n_zones"].astype(int) * records["n_periods"].astype(int)
        ).le(config.max_panel_cells).all()
    )
    gates = {
        "no_runtime_failures": no_runtime_failures,
        "records_present": records_present,
        "target_estimand_is_market_total_effect": target_consistent,
        "known_truth_finite": known_truth_finite,
        "applicable_fit_plan_complete": complete_fits,
        "at_least_one_identified_inference_valid_cell": at_least_one_valid_target,
        "identified_target_metrics_finite": identified_metrics_finite,
        "target_mismatch_metrics_masked": mismatch_metrics_masked,
        "effective_geometry_within_anchor_and_laptop_limit": geometry_bounded,
    }
    gates["all_passed"] = all(gates.values())
    return gates


def _label_frame(
    frame: pd.DataFrame,
    *,
    hashes: Mapping[str, str],
    anchor: SimulationConfig,
    base: SimulationConfig,
    overrides: Mapping[str, Any],
    scenario_provenance: Mapping[str, Mapping[str, Any]],
) -> pd.DataFrame:
    labeled = frame.copy()
    labeled["evidence_type"] = NYC_BENCHMARK_EVIDENCE_TYPE
    labeled["anchor_evidence_label"] = ANCHOR_EVIDENCE_LABEL
    labeled["nyc_empirical_causal_effect"] = False
    labeled["simulator_known_truth"] = True
    labeled["known_truth_scope"] = (
        "structural simulator counterfactual under explicit assumptions; not an NYC causal estimate"
    )
    for key, value in hashes.items():
        labeled[f"nyc_{key}"] = value
    labeled["anchor_config_n_zones"] = anchor.n_zones
    labeled["anchor_config_n_periods"] = anchor.n_periods
    labeled["benchmark_base_n_zones"] = base.n_zones
    labeled["benchmark_base_n_periods"] = base.n_periods
    labeled["benchmark_base_overrides"] = json.dumps(
        overrides, sort_keys=True, separators=(",", ":")
    )
    if "scenario" in labeled:
        labeled["scenario_causal_provenance"] = labeled["scenario"].map(
            {
                name: json.dumps(value, sort_keys=True, separators=(",", ":"))
                for name, value in scenario_provenance.items()
            }
        )
        if labeled["scenario_causal_provenance"].isna().any():
            raise RuntimeError("NYC benchmark result contains an undeclared scenario")
    labeled["target_gate_all_passed"] = True
    return labeled


def run_nyc_informed_marketplace_benchmark(
    anchor_path: str | Path,
    anchor_manifest_path: str | Path,
    *,
    config: NYCBenchmarkConfig | None = None,
    scenarios: tuple[SensitivityScenario, ...] | None = None,
    project_root: str | Path | None = None,
    expected_anchor_sha256: str | None = None,
    expected_anchor_manifest_sha256: str | None = None,
) -> NYCBenchmarkResult:
    """Run a deterministic NYC-informed benchmark after exact anchor reconstruction."""

    runtime = config or NYCBenchmarkConfig()
    verified = _verify_anchor(
        anchor_path,
        anchor_manifest_path,
        project_root=project_root,
        expected_anchor_sha256=expected_anchor_sha256,
        expected_anchor_manifest_sha256=expected_anchor_manifest_sha256,
    )
    base, overrides = _effective_base(verified.simulation, runtime)
    selected = (
        default_nyc_benchmark_scenarios(verified.simulation)
        if scenarios is None
        else tuple(scenarios)
    )
    if not selected:
        raise ValueError("at least one NYC benchmark scenario is required")
    names = [scenario.name for scenario in selected]
    if len(names) != len(set(names)):
        raise ValueError("NYC benchmark scenario names must be unique")
    _validate_scenario_geometry(base, verified.simulation, runtime, selected)
    scenario_provenance = _scenario_provenance(verified.simulation, selected)
    benchmark = BenchmarkConfig(
        replications=runtime.replications,
        seed=runtime.seed,
        confidence_level=runtime.confidence_level,
        designs=runtime.designs,
        estimators=runtime.estimators,
        target_estimand="market_total_effect",
        cost_per_market_period=runtime.cost_per_market_period,
    )
    raw = run_marketplace_benchmark(benchmark, base, scenarios=selected)
    gates = _target_gates(raw, runtime, verified.simulation)
    if not gates["all_passed"]:
        failed = sorted(key for key, passed in gates.items() if not passed)
        details = (
            raw.failures.to_dict(orient="records")[:3]
            if not raw.failures.empty
            else []
        )
        raise RuntimeError(
            f"NYC benchmark target gates failed: {failed}; failures={details}"
        )

    label_kwargs = {
        "hashes": verified.hashes,
        "anchor": verified.simulation,
        "base": base,
        "overrides": overrides,
        "scenario_provenance": scenario_provenance,
    }
    records = _label_frame(raw.records, **label_kwargs)
    summary = _label_frame(raw.summary, **label_kwargs)
    failures = _label_frame(raw.failures, **label_kwargs)
    fit_ledger = _label_frame(raw.fit_ledger, **label_kwargs)
    metadata = {
        "schema_version": NYC_BENCHMARK_SCHEMA_VERSION,
        "evidence_type": NYC_BENCHMARK_EVIDENCE_TYPE,
        "nyc_empirical_causal_effect": False,
        "simulator_known_truth": True,
        "known_truth_estimand": "market_total_effect",
        "known_truth_scope": (
            "structural simulator counterfactual under explicit assumptions; "
            "not an NYC causal estimate"
        ),
        "anchor": {
            "evidence_label": ANCHOR_EVIDENCE_LABEL,
            "exact_reconstruction_passed": True,
            "anchor_path": _project_relative_path(
                Path(anchor_path), verified.project_root, "anchor_path"
            ),
            "anchor_manifest_path": _project_relative_path(
                Path(anchor_manifest_path),
                verified.project_root,
                "anchor_manifest_path",
            ),
            "hashes": dict(verified.hashes),
            "simulation_config": verified.simulation.to_dict(),
        },
        "benchmark_config": runtime.to_dict(),
        "benchmark_base_simulation_config": base.to_dict(),
        "effective_overrides": overrides,
        "scenario_causal_provenance": scenario_provenance,
        "target_gates": gates,
        "limitations": [
            "NYC records supply descriptive initialization moments, not causal effects.",
            "Known truth exists only inside the declared structural simulator.",
            "Geometry reduction is a computational design choice, not an empirical sample.",
            "Sensitivity overrides are explicit assumptions and are not learned from NYC data.",
        ],
    }
    return NYCBenchmarkResult(records, summary, failures, fit_ledger, metadata)


def _artifact_json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _artifact_json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_artifact_json_safe(item) for item in value]
    if isinstance(value, (np.integer, np.floating, np.bool_)):
        return value.item()
    if hasattr(value, "value"):
        return _artifact_json_safe(value.value)
    return value


def _artifact_output_path(
    output_dir: str | Path,
    project_root: str | Path | None,
) -> tuple[Path, str]:
    root = (
        Path(project_root).resolve()
        if project_root is not None
        else Path.cwd().resolve()
    )
    raw = Path(output_dir)
    output = ((root / raw) if not raw.is_absolute() else raw).resolve()
    if output.parent == output:
        raise ValueError("artifact output_dir must not be a filesystem root")
    if output == Path.cwd().resolve():
        raise ValueError("artifact output_dir must not overwrite the current workspace")
    if output == root:
        raise ValueError("artifact output_dir must not overwrite project_root")
    try:
        portable = output.relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError("artifact output_dir must be contained by project_root") from exc
    if output.exists() and not output.is_dir():
        raise ValueError("artifact output_dir exists and is not a directory")
    return output, portable


def _artifact_project_root(project_root: str | Path | None) -> Path:
    return (
        Path(project_root).resolve()
        if project_root is not None
        else Path.cwd().resolve()
    )


def _artifact_input_entry(
    path: Path,
    *,
    project_root: Path,
    expected_sha256: Any,
    role: str,
    evidence_type: str,
) -> dict[str, Any]:
    expected = _hash(expected_sha256, f"{role} declared SHA-256")
    portable = _project_relative_path(path, project_root, role)
    resolved = (project_root / portable).resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"{role} is required: {resolved}")
    actual = sha256_file(resolved)
    if actual != expected:
        raise ValueError(f"{role} SHA-256 disagrees with result metadata")
    return {
        "path": portable,
        "role": role,
        "media_type": "application/json",
        "bytes": resolved.stat().st_size,
        "sha256": actual,
        "evidence_types": [evidence_type],
    }


def _artifact_anchor_inputs(
    metadata: Mapping[str, Any], project_root: Path
) -> list[dict[str, Any]]:
    anchor = metadata.get("anchor")
    if not isinstance(anchor, Mapping):
        raise ValueError("result metadata lacks anchor provenance")
    hashes = anchor.get("hashes")
    if not isinstance(hashes, Mapping):
        raise ValueError("result metadata lacks anchor hashes")
    anchor_relative = _portable_path(
        anchor.get("anchor_path"), "result metadata anchor.anchor_path"
    )
    manifest_relative = _portable_path(
        anchor.get("anchor_manifest_path"),
        "result metadata anchor.anchor_manifest_path",
    )
    anchor_file = (project_root / anchor_relative).resolve()
    manifest_file = (project_root / manifest_relative).resolve()
    reverified = _verify_anchor(
        anchor_file,
        manifest_file,
        project_root=project_root,
        expected_anchor_sha256=_hash(
            hashes.get("anchor_sha256"), "result metadata anchor_sha256"
        ),
        expected_anchor_manifest_sha256=_hash(
            hashes.get("anchor_manifest_sha256"),
            "result metadata anchor_manifest_sha256",
        ),
    )
    if dict(reverified.hashes) != dict(hashes):
        raise ValueError("revalidated anchor lineage disagrees with result metadata")
    return [
        _artifact_input_entry(
            anchor_file,
            project_root=project_root,
            expected_sha256=hashes.get("anchor_sha256"),
            role="anchor",
            evidence_type=ANCHOR_EVIDENCE_LABEL,
        ),
        _artifact_input_entry(
            manifest_file,
            project_root=project_root,
            expected_sha256=hashes.get("anchor_manifest_sha256"),
            role="anchor_manifest",
            evidence_type=ANCHOR_EVIDENCE_LABEL,
        ),
    ]


def _artifact_write_table(frame: pd.DataFrame, destination: Path) -> Path:
    if not isinstance(frame, pd.DataFrame):
        raise TypeError("benchmark artifact tables must be pandas DataFrames")
    frame.to_csv(destination, index=False, lineterminator="\n")
    return destination


def _artifact_write_json(payload: Mapping[str, Any], destination: Path) -> Path:
    destination.write_text(
        json.dumps(
            _artifact_json_safe(payload),
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    return destination


def _artifact_evidence_types(frame: pd.DataFrame, default: str) -> list[str]:
    if "evidence_type" not in frame or frame.empty:
        return [default]
    values = sorted(frame["evidence_type"].dropna().astype(str).unique().tolist())
    return values or [default]


def _artifact_publish_directory(stage: Path, output: Path, temporary_root: Path) -> None:
    backup = temporary_root / "previous_bundle"
    if output.exists():
        output.replace(backup)
    try:
        stage.replace(output)
    except BaseException:
        if backup.exists() and not output.exists():
            backup.replace(output)
        raise
    if backup.exists():
        shutil.rmtree(backup)


def write_nyc_benchmark_artifacts(
    result: NYCBenchmarkResult,
    output_dir: str | Path,
    *,
    project_root: str | Path | None = None,
) -> dict[str, Path]:
    """Atomically publish a self-contained NYC-informed benchmark bundle.

    The manifest hashes the four result tables and metadata payload. All serialized
    paths are portable, and no wall-clock timestamp is added, so equal results produce
    byte-identical bundles.
    """

    if not isinstance(result, NYCBenchmarkResult):
        raise TypeError("result must be an NYCBenchmarkResult")
    if not isinstance(result.metadata, Mapping):
        raise TypeError("result.metadata must be a mapping")
    artifact_root = _artifact_project_root(project_root)
    inputs = _artifact_anchor_inputs(result.metadata, artifact_root)
    output, portable_output = _artifact_output_path(output_dir, project_root)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_root = Path(
        tempfile.mkdtemp(prefix=f".{output.name}-stage-", dir=output.parent)
    )
    stage = temporary_root / "bundle"
    stage.mkdir()
    tables = {
        "records": result.records,
        "summary": result.summary,
        "fit_ledger": result.fit_ledger,
        "failures": result.failures,
    }
    filenames = {name: f"{name}.csv" for name in tables}
    try:
        for name, frame in tables.items():
            _artifact_write_table(frame, stage / filenames[name])

        metadata = dict(result.metadata)
        if "artifact_bundle" in metadata:
            raise ValueError("result metadata already contains reserved artifact_bundle")
        metadata["artifact_bundle"] = {
            "schema_version": NYC_BENCHMARK_SCHEMA_VERSION,
            "artifact_type": "nyc_informed_marketplace_benchmark",
            "portable_output_directory": portable_output,
            "portable_paths": True,
            "bundle_valid": True,
            "evidence_type": NYC_BENCHMARK_EVIDENCE_TYPE,
            "causal_claim": False,
            "nyc_empirical_causal_effect": False,
            "simulator_known_truth": True,
            "inputs": inputs,
            "tables": {
                name: {"path": filenames[name], "rows": int(len(frame))}
                for name, frame in tables.items()
            },
        }
        metadata_path = _artifact_write_json(metadata, stage / "metadata.json")

        files: list[dict[str, Any]] = []
        for name, frame in tables.items():
            path = stage / filenames[name]
            files.append(
                {
                    "path": path.name,
                    "role": name,
                    "media_type": "text/csv",
                    "rows": int(len(frame)),
                    "bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                    "evidence_types": _artifact_evidence_types(
                        frame, NYC_BENCHMARK_EVIDENCE_TYPE
                    ),
                }
            )
        files.append(
            {
                "path": metadata_path.name,
                "role": "metadata",
                "media_type": "application/json",
                "bytes": metadata_path.stat().st_size,
                "sha256": sha256_file(metadata_path),
                "evidence_types": [NYC_BENCHMARK_EVIDENCE_TYPE],
            }
        )
        manifest = {
            "schema_version": NYC_BENCHMARK_SCHEMA_VERSION,
            "artifact_type": "nyc_informed_marketplace_benchmark",
            "evidence_type": NYC_BENCHMARK_EVIDENCE_TYPE,
            "causal_claim": False,
            "causal_claim_from_nyc_data": False,
            "simulator_known_truth": True,
            "portable_paths": True,
            "bundle_valid": True,
            "artifact_directory": portable_output,
            "metadata_file": metadata_path.name,
            "files": files,
            "inputs": inputs,
        }
        _artifact_write_json(manifest, stage / "manifest.json")
        _artifact_publish_directory(stage, output, temporary_root)
    finally:
        if temporary_root.exists():
            shutil.rmtree(temporary_root)

    return {
        "output_directory": output,
        **{name: output / filename for name, filename in filenames.items()},
        "metadata": output / "metadata.json",
        "manifest": output / "manifest.json",
    }


__all__ = [
    "NYC_BENCHMARK_EVIDENCE_TYPE",
    "NYC_BENCHMARK_SCHEMA_VERSION",
    "NYCBenchmarkConfig",
    "NYCBenchmarkResult",
    "default_nyc_benchmark_scenarios",
    "run_nyc_informed_marketplace_benchmark",
    "validate_nyc_benchmark_anchor",
    "write_nyc_benchmark_artifacts",
]
