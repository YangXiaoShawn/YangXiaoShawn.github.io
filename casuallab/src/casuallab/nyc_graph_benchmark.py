"""Known-truth interference benchmark on a validated NYC OD graph.

The NYC calibration bundle contributes only a fixed, pre-treatment exposure
geometry.  Its completed-trip weights determine relative neighbor weights after
row normalization; they are not estimates of spillover strength.  Treatment is
then randomized by a two-stage saturation design and outcomes are generated from
an explicit additive DGP with known controlled own, neighbor, and history slopes.

Consequently, benchmark recovery is semi-synthetic evidence about an estimator on
NYC-shaped geometry.  It is not an empirical estimate of a NYC treatment effect.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from hashlib import sha256
from math import isfinite
from numbers import Integral, Real
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd

from .benchmark import summarize_monte_carlo
from .config import EstimatorConfig
from .data import sha256_file
from .estimators import cluster_robust
from .interference import (
    ExposureMappingConfig,
    TwoStageSaturationConfig,
    add_mapped_exposures,
    estimate_exposure_response,
    two_stage_saturation_assignment,
)

CALIBRATION_EVIDENCE: Final = "descriptive_real_data"
BENCHMARK_EVIDENCE: Final = "semi_synthetic_known_truth_on_descriptive_nyc_graph"
MAPPING_FILENAME: Final = "exposure_mapping_edges.csv"
CALIBRATION_FILENAME: Final = "calibration.json"
MANIFEST_FILENAME: Final = "manifest.json"
NYC_GRAPH_BENCHMARK_ARTIFACT_SCHEMA_VERSION: Final = "1.0.0"
SELECTION_RULE: Final = (
    "Within a connected component large enough for the requested sample, start at "
    "the zone with greatest raw OD weighted degree, then greedily add the zone with "
    "greatest raw OD weight to already selected zones; break ties by full-graph "
    "weighted degree, neighbor count, and lexical zone ID. Only pre-treatment graph "
    "fields are used."
)

TARGET_DEFINITIONS: Final[Mapping[str, str]] = {
    "controlled_zone_direct_effect": (
        "Per-unit own-treatment response holding NYC-graph neighbor exposure and "
        "lagged own exposure fixed."
    ),
    "spillover_effect": (
        "Per-unit response to row-normalized NYC OD-neighbor exposure holding own and "
        "lagged exposure fixed; the coefficient is declared by the DGP, not learned "
        "from OD weights."
    ),
    "controlled_history_exposure_response": (
        "Per-unit response to exact-lag own-treatment history holding current own and "
        "NYC-graph neighbor exposure fixed."
    ),
    "market_total_effect": (
        "Full-horizon all-selected-zone treatment versus all-zero under the declared "
        "additive DGP and startup-history convention."
    ),
}


@dataclass(frozen=True, slots=True)
class NYCGraphBenchmarkConfig:
    """Laptop-safe Monte Carlo settings for the NYC-geometry benchmark."""

    replications: int = 12
    seed: int = 912_731
    n_zones: int = 16
    n_periods: int = 24
    individuals_per_cell: int = 20
    saturation_levels: tuple[float, ...] = (0.0, 1.0 / 3.0, 2.0 / 3.0, 1.0)
    history_lags: int = 1
    own_effect: float = 2.0
    neighbor_effect: float = 1.5
    history_effect: float = 0.7
    outcome_noise_sd: float = 0.06
    cluster_noise_sd: float = 0.04
    confidence_level: float = 0.95
    minimum_inference_clusters: int = 8

    def __post_init__(self) -> None:
        integer_values = {
            "replications": self.replications,
            "seed": self.seed,
            "n_zones": self.n_zones,
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
            raise ValueError("n_zones must be at least four")
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
        TwoStageSaturationConfig(
            n_clusters=self.n_zones,
            individuals_per_cell=self.individuals_per_cell,
            saturation_levels=levels,
            seed=self.seed,
        )
        if not any(0.0 < level < 1.0 for level in levels):
            raise ValueError(
                "saturation_levels must include an interior arm to separate current "
                "treatment from lagged history"
            )


@dataclass(frozen=True, slots=True)
class NYCGraphEstimands:
    """Known DGP slopes and the distinct full-policy contrast."""

    controlled_zone_direct_effect: float
    spillover_effect: float
    controlled_history_exposure_response: float
    full_horizon_history_contribution: float
    market_total_effect: float

    def to_dict(self) -> dict[str, float]:
        return {name: float(value) for name, value in asdict(self).items()}


@dataclass(frozen=True)
class ValidatedNYCGraphBundle:
    """Validated fixed graph plus calibration provenance."""

    directory: Path
    edges: pd.DataFrame
    manifest: Mapping[str, Any]
    calibration: Mapping[str, Any]
    manifest_sha256: str
    mapping_sha256: str
    verified_files: Mapping[str, str]


@dataclass(frozen=True)
class NYCGraphBenchmarkResult:
    """Replication records, summaries, fit audit, failures, and graph provenance."""

    records: pd.DataFrame
    summary: pd.DataFrame
    fit_ledger: pd.DataFrame
    failures: pd.DataFrame
    metadata: Mapping[str, Any]


def _portable_bundle_directory(directory: Path) -> str:
    """Record the calibration directory relative to the repository when possible."""

    resolved = directory.resolve()
    candidate_roots = (
        Path(__file__).resolve().parents[2],
        Path.cwd().resolve(),
    )
    for root in dict.fromkeys(candidate_roots):
        try:
            relative = resolved.relative_to(root)
        except ValueError:
            continue
        if relative.parts and relative != Path("."):
            return relative.as_posix()
    # Synthetic fixtures conventionally put the named bundle directly below the
    # project_root later supplied to the artifact writer.
    return resolved.name


def known_nyc_graph_estimands(
    config: NYCGraphBenchmarkConfig | None = None,
) -> NYCGraphEstimands:
    """Return known truths without reading a calibration bundle."""

    cfg = config or NYCGraphBenchmarkConfig()
    supported_history_periods = cfg.n_periods - cfg.history_lags
    history_contribution = (
        cfg.history_effect * supported_history_periods / cfg.n_periods
    )
    return NYCGraphEstimands(
        controlled_zone_direct_effect=float(cfg.own_effect),
        spillover_effect=float(cfg.neighbor_effect),
        controlled_history_exposure_response=float(cfg.history_effect),
        full_horizon_history_contribution=float(history_contribution),
        market_total_effect=float(
            cfg.own_effect + cfg.neighbor_effect + history_contribution
        ),
    )


def _load_json(path: Path, label: str) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid {label}: {path}") from exc
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must contain a JSON object")
    return value


def _require_descriptive_header(payload: Mapping[str, Any], label: str) -> None:
    if payload.get("schema_version") != "1.0.0":
        raise ValueError(f"{label} has unsupported schema_version")
    if payload.get("evidence_label") != CALIBRATION_EVIDENCE:
        raise ValueError(f"{label} must be labeled descriptive_real_data")
    if payload.get("causal_claim") is not False:
        raise ValueError(f"{label} must explicitly set causal_claim=false")


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value.lower())
    )


def _validate_source_attestation(source: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(source, Mapping):
        raise ValueError(f"{label} source_data_manifest must be an object")
    required_true = (
        "all_valid",
        "hashes_recomputed",
        "queried_files_listed",
        "scope_is_full_nyc_descriptive",
    )
    if any(source.get(key) is not True for key in required_true):
        raise ValueError(f"{label} source-data attestation is not fully valid")
    if source.get("mismatches") != []:
        raise ValueError(f"{label} source-data attestation records mismatches")
    source_hash = source.get("sha256")
    if not _is_sha256(source_hash):
        raise ValueError(f"{label} source-data attestation lacks a SHA-256 digest")
    if not _is_sha256(source.get("declared_file_set_sha256")):
        raise ValueError(f"{label} source-data attestation lacks a file-set digest")
    entries = source.get("entries")
    if isinstance(entries, bool) or not isinstance(entries, Integral) or entries < 1:
        raise ValueError(f"{label} source-data attestation has no declared files")
    source_path = source.get("path")
    if not isinstance(source_path, str) or not source_path.strip():
        raise ValueError(f"{label} source-data attestation lacks a manifest path")
    return source


def _validate_manifest_files(
    directory: Path,
    manifest: Mapping[str, Any],
) -> tuple[dict[str, Path], dict[str, str]]:
    entries = manifest.get("files")
    if not isinstance(entries, list) or not entries:
        raise ValueError("calibration manifest files must be a nonempty list")
    paths: dict[str, Path] = {}
    hashes: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise ValueError("calibration manifest contains a malformed file entry")
        name = entry.get("path")
        if not isinstance(name, str) or Path(name).name != name or Path(name).is_absolute():
            raise ValueError("calibration manifest file paths must be portable basenames")
        if name == MANIFEST_FILENAME or name in paths:
            raise ValueError("calibration manifest contains a duplicate or recursive path")
        path = directory / name
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"calibration bundle file is missing or unsafe: {name}")
        declared_bytes = entry.get("bytes")
        declared_hash = entry.get("sha256")
        if (
            isinstance(declared_bytes, bool)
            or not isinstance(declared_bytes, Integral)
            or int(declared_bytes) < 0
        ):
            raise ValueError(f"calibration manifest has invalid bytes for {name}")
        if not _is_sha256(declared_hash):
            raise ValueError(f"calibration manifest has invalid SHA-256 for {name}")
        if path.stat().st_size != int(declared_bytes):
            raise ValueError(f"calibration bundle byte-size mismatch: {name}")
        actual_hash = sha256_file(path)
        if actual_hash != declared_hash:
            raise ValueError(f"calibration bundle SHA-256 mismatch: {name}")
        paths[name] = path
        hashes[name] = actual_hash

    actual_files = {
        path.name
        for path in directory.iterdir()
        if path.is_file() and path.name != MANIFEST_FILENAME
    }
    if actual_files != set(paths):
        raise ValueError("calibration bundle file set differs from its manifest")
    return paths, hashes


def _validate_mapping(path: Path) -> pd.DataFrame:
    required = {
        "focal_zone_id",
        "neighbor_zone_id",
        "weight",
        "evidence_label",
        "weight_definition",
        "interpretation_warning",
    }
    try:
        frame = pd.read_csv(
            path,
            dtype={"focal_zone_id": "string", "neighbor_zone_id": "string"},
        )
    except (OSError, ValueError, pd.errors.ParserError) as exc:
        raise ValueError("invalid NYC exposure mapping CSV") from exc
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"NYC exposure mapping missing columns: {sorted(missing)}")
    if frame.empty:
        raise ValueError("NYC exposure mapping must not be empty")
    if frame[list(required)].isna().any().any():
        raise ValueError("NYC exposure mapping contains missing required values")
    frame["focal_zone_id"] = frame["focal_zone_id"].astype(str)
    frame["neighbor_zone_id"] = frame["neighbor_zone_id"].astype(str)
    if (frame["focal_zone_id"].str.strip() == "").any() or (
        frame["neighbor_zone_id"].str.strip() == ""
    ).any():
        raise ValueError("NYC exposure mapping contains blank zone IDs")
    if frame.duplicated(["focal_zone_id", "neighbor_zone_id"]).any():
        raise ValueError("NYC exposure mapping contains duplicate directed edges")
    if (frame["focal_zone_id"] == frame["neighbor_zone_id"]).any():
        raise ValueError("NYC exposure mapping must not contain self edges")
    weights = pd.to_numeric(frame["weight"], errors="coerce")
    if weights.isna().any() or not np.isfinite(weights.to_numpy(dtype=float)).all():
        raise ValueError("NYC exposure mapping weights must be finite numeric values")
    if (weights <= 0).any():
        raise ValueError("NYC exposure mapping weights must be strictly positive")
    frame["weight"] = weights.astype(float)
    if not frame["evidence_label"].eq(CALIBRATION_EVIDENCE).all():
        raise ValueError("NYC exposure mapping evidence labels are not descriptive_real_data")
    if not frame["weight_definition"].str.contains(
        "row-normalizes weight", case=False, regex=False
    ).all():
        raise ValueError("NYC exposure mapping lacks its row-normalization definition")
    if not frame["interpretation_warning"].str.contains(
        "not an estimated spillover effect", case=False, regex=False
    ).all():
        raise ValueError("NYC graph weights are not explicitly separated from spillover effects")

    indexed = frame.set_index(["focal_zone_id", "neighbor_zone_id"])["weight"]
    reverse_index = pd.MultiIndex.from_arrays(
        [frame["neighbor_zone_id"], frame["focal_zone_id"]],
        names=["focal_zone_id", "neighbor_zone_id"],
    )
    reverse = indexed.reindex(reverse_index)
    if reverse.isna().any() or not np.allclose(
        frame["weight"].to_numpy(dtype=float),
        reverse.to_numpy(dtype=float),
        rtol=0.0,
        atol=1e-12,
    ):
        raise ValueError("NYC exposure mapping must be symmetric with equal reverse weights")
    return frame.sort_values(
        ["focal_zone_id", "neighbor_zone_id"]
    ).reset_index(drop=True)


def validate_nyc_graph_bundle(
    bundle_directory: str | Path,
) -> ValidatedNYCGraphBundle:
    """Fail closed unless every calibration artifact and evidence contract validates."""

    directory = Path(bundle_directory).resolve()
    if not directory.is_dir():
        raise FileNotFoundError(directory)
    manifest_path = directory / MANIFEST_FILENAME
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise FileNotFoundError(manifest_path)
    manifest = _load_json(manifest_path, "calibration manifest")
    _require_descriptive_header(manifest, "calibration manifest")
    if manifest.get("portable_paths") is not True:
        raise ValueError("calibration manifest must declare portable_paths=true")
    manifest_config = manifest.get("config")
    if not isinstance(manifest_config, Mapping):
        raise ValueError("calibration manifest lacks its generating configuration")
    data_config = manifest_config.get("data")
    calibration_config = manifest_config.get("calibration")
    if (
        not isinstance(data_config, Mapping)
        or data_config.get("source") != "nyc_hvfhv"
        or data_config.get("mode") != "full"
    ):
        raise ValueError("calibration manifest is not scoped to full-mode NYC HVFHV data")
    if not isinstance(calibration_config, Mapping) or (
        calibration_config.get("verify_source_hashes") is not True
    ):
        raise ValueError("calibration manifest did not require source hash verification")
    warning = manifest.get("interpretation_warning")
    if not isinstance(warning, str) or "do not identify" not in warning:
        raise ValueError("calibration manifest lacks its causal interpretation warning")
    manifest_source = _validate_source_attestation(
        manifest.get("source_data_manifest"), "calibration manifest"
    )
    paths, hashes = _validate_manifest_files(directory, manifest)
    if {CALIBRATION_FILENAME, MAPPING_FILENAME}.difference(paths):
        raise ValueError("calibration manifest omits required graph benchmark inputs")

    calibration = _load_json(paths[CALIBRATION_FILENAME], "calibration payload")
    _require_descriptive_header(calibration, "calibration payload")
    if calibration.get("bundle_valid") is not True:
        raise ValueError("calibration payload does not declare bundle_valid=true")
    scope = calibration.get("scope")
    if (
        not isinstance(scope, Mapping)
        or scope.get("source") != "nyc_hvfhv"
        or scope.get("population_claim") is not False
    ):
        raise ValueError("calibration payload is not a descriptive NYC HVFHV scope")
    checks = calibration.get("checks")
    if not isinstance(checks, Mapping) or not checks or any(
        value is not True for value in checks.values()
    ):
        raise ValueError("calibration payload contains failed conservation checks")
    critical_warning = calibration.get("critical_warning")
    if not isinstance(critical_warning, str) or "do not identify" not in critical_warning:
        raise ValueError("calibration payload lacks its causal interpretation warning")
    provenance = calibration.get("provenance")
    if not isinstance(provenance, Mapping):
        raise ValueError("calibration payload lacks provenance")
    calibration_source = _validate_source_attestation(
        provenance.get("source_data_manifest"), "calibration payload"
    )
    if dict(calibration_source) != dict(manifest_source):
        raise ValueError("manifest and calibration source attestations disagree")

    graph = calibration.get("od_flow_graph")
    if not isinstance(graph, Mapping):
        raise ValueError("calibration payload lacks od_flow_graph metadata")
    if graph.get("evidence_label") != CALIBRATION_EVIDENCE:
        raise ValueError("OD graph metadata is not labeled descriptive_real_data")
    if graph.get("exposure_mapping_file") != MAPPING_FILENAME:
        raise ValueError("OD graph points to an unexpected exposure mapping file")
    if graph.get("exposure_mapping_schema") != [
        "focal_zone_id",
        "neighbor_zone_id",
        "weight",
    ]:
        raise ValueError("OD graph exposure mapping schema is incompatible")
    interpretation = graph.get("interpretation")
    if not isinstance(interpretation, str) or (
        "do not estimate interference" not in interpretation
    ):
        raise ValueError("OD graph metadata does not separate weights from interference")

    edges = _validate_mapping(paths[MAPPING_FILENAME])
    return ValidatedNYCGraphBundle(
        directory=directory,
        edges=edges,
        manifest=manifest,
        calibration=calibration,
        manifest_sha256=sha256_file(manifest_path),
        mapping_sha256=hashes[MAPPING_FILENAME],
        verified_files=hashes,
    )


def _selected_graph(
    edges: pd.DataFrame,
    n_zones: int,
) -> tuple[pd.DataFrame, list[str], dict[str, Any], dict[str, float]]:
    nodes = sorted(
        set(edges["focal_zone_id"]).union(edges["neighbor_zone_id"])
    )
    weighted_degree = edges.groupby("focal_zone_id")["weight"].sum().to_dict()
    neighbor_count = edges.groupby("focal_zone_id")["neighbor_zone_id"].nunique().to_dict()
    adjacency: dict[str, dict[str, float]] = {node: {} for node in nodes}
    for row in edges.itertuples(index=False):
        adjacency[str(row.focal_zone_id)][str(row.neighbor_zone_id)] = float(row.weight)

    components: list[list[str]] = []
    unvisited = set(nodes)
    while unvisited:
        start = min(unvisited)
        stack = [start]
        component: list[str] = []
        unvisited.remove(start)
        while stack:
            node = stack.pop()
            component.append(node)
            unseen_neighbors = sorted(set(adjacency[node]).intersection(unvisited), reverse=True)
            for neighbor in unseen_neighbors:
                unvisited.remove(neighbor)
                stack.append(neighbor)
        components.append(sorted(component))
    eligible = [component for component in components if len(component) >= n_zones]
    if not eligible:
        largest = max((len(component) for component in components), default=0)
        raise ValueError(
            f"NYC graph has no connected component with {n_zones} zones; largest has {largest}"
        )
    component = min(
        eligible,
        key=lambda values: (
            -sum(float(weighted_degree[node]) for node in values),
            -len(values),
            values[0],
        ),
    )
    first = min(
        component,
        key=lambda node: (
            -float(weighted_degree[node]),
            -int(neighbor_count[node]),
            node,
        ),
    )
    selected = [first]
    selected_set = {first}
    while len(selected) < n_zones:
        candidates = set(component).difference(selected_set)
        connected_candidates = [
            node
            for node in candidates
            if any(neighbor in selected_set for neighbor in adjacency[node])
        ]
        if not connected_candidates:
            raise RuntimeError("connected-zone selector lost graph support")
        chosen = min(
            connected_candidates,
            key=lambda node: (
                -sum(
                    weight
                    for neighbor, weight in adjacency[node].items()
                    if neighbor in selected_set
                ),
                -float(weighted_degree[node]),
                -int(neighbor_count[node]),
                node,
            ),
        )
        selected.append(chosen)
        selected_set.add(chosen)

    subset = edges.loc[
        edges["focal_zone_id"].isin(selected_set)
        & edges["neighbor_zone_id"].isin(selected_set),
        ["focal_zone_id", "neighbor_zone_id", "weight"],
    ].copy()
    if subset.empty or set(subset["focal_zone_id"]) != selected_set:
        raise RuntimeError("selected NYC graph does not map every focal zone")
    canonical = [
        {
            "focal_zone_id": str(row.focal_zone_id),
            "neighbor_zone_id": str(row.neighbor_zone_id),
            "weight": format(float(row.weight), ".17g"),
        }
        for row in subset.sort_values(
            ["focal_zone_id", "neighbor_zone_id"]
        ).itertuples(index=False)
    ]
    subset_digest = sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    log_degree = np.log1p(
        np.asarray([float(weighted_degree[node]) for node in selected], dtype=float)
    )
    scale = float(log_degree.std(ddof=0))
    graph_score_values = (
        np.zeros_like(log_degree)
        if scale == 0
        else (log_degree - float(log_degree.mean())) / scale
    )
    graph_score = dict(zip(selected, graph_score_values.tolist(), strict=True))
    possible_directed_edges = n_zones * (n_zones - 1)
    metadata = {
        "selection_rule": SELECTION_RULE,
        "selection_uses_only_pre_treatment_graph_fields": True,
        "selected_zone_ids_in_order": selected,
        "selected_zone_count": len(selected),
        "selected_directed_edges": int(len(subset)),
        "selected_directed_density": float(len(subset) / possible_directed_edges),
        "subset_raw_mapping_sha256": subset_digest,
        "subset_weight_handling": (
            "Raw completed-trip weights are restricted to the selected induced graph and "
            "row-normalized by add_mapped_exposures."
        ),
        "selection_scores": [
            {
                "zone_id": node,
                "full_graph_raw_weighted_degree": float(weighted_degree[node]),
                "full_graph_neighbor_count": int(neighbor_count[node]),
            }
            for node in selected
        ],
    }
    return subset.reset_index(drop=True), selected, metadata, graph_score


def _replication_seeds(seed: int, replications: int) -> tuple[tuple[int, int], ...]:
    children = np.random.SeedSequence(seed).spawn(replications)
    return tuple(
        tuple(int(value) for value in child.generate_state(2, dtype=np.uint32))
        for child in children
    )


def _simulate(
    config: NYCGraphBenchmarkConfig,
    edges: pd.DataFrame,
    selected_zones: list[str],
    graph_score: Mapping[str, float],
    *,
    assignment_seed: int,
    outcome_seed: int,
) -> pd.DataFrame:
    units = pd.MultiIndex.from_product(
        [range(config.n_periods), selected_zones],
        names=["period_id", "zone_id"],
    ).to_frame(index=False)
    assignment = two_stage_saturation_assignment(
        units,
        TwoStageSaturationConfig(
            n_clusters=config.n_zones,
            individuals_per_cell=config.individuals_per_cell,
            saturation_levels=config.saturation_levels,
            seed=assignment_seed,
        ),
    )
    frame = add_mapped_exposures(
        assignment,
        edges,
        history_lags=config.history_lags,
    )
    frame["graph_baseline_score"] = frame["zone_id"].map(graph_score).astype(float)
    period_angle = (
        2.0 * np.pi * frame["period_id"].to_numpy(dtype=float) / config.n_periods
    )
    frame["period_sin"] = np.sin(period_angle)
    frame["period_cos"] = np.cos(period_angle)
    rng = np.random.default_rng(outcome_seed)
    cluster_shocks = rng.normal(0.0, config.cluster_noise_sd, config.n_zones)
    history_for_outcome = frame["history_exposure"].fillna(0.0).to_numpy(dtype=float)
    frame["outcome"] = (
        8.0
        + 0.30 * frame["graph_baseline_score"].to_numpy(dtype=float)
        + 0.20 * frame["period_sin"].to_numpy(dtype=float)
        - 0.15 * frame["period_cos"].to_numpy(dtype=float)
        + cluster_shocks[frame["cluster_id"].to_numpy(dtype=int)]
        + config.own_effect * frame["treatment"].to_numpy(dtype=float)
        + config.neighbor_effect * frame["neighbor_exposure"].to_numpy(dtype=float)
        + config.history_effect * history_for_outcome
        + rng.normal(0.0, config.outcome_noise_sd, len(frame))
    )
    frame["dgp_evidence_type"] = BENCHMARK_EVIDENCE
    return frame


def _mapped_records(
    frame: pd.DataFrame,
    config: NYCGraphBenchmarkConfig,
    truths: NYCGraphEstimands,
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
            covariates=("graph_baseline_score", "period_sin", "period_cos"),
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
                "design": "two_stage_saturation_on_fixed_nyc_od_graph",
                "estimator": "nyc_graph_exposure_mapped_cluster_regression",
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
                "inference_valid_for_target": bool(estimate["inference_valid"]),
                "coefficient_inference_cluster_aware": True,
                "controlled_exposure_not_market_total": True,
                "graph_weight_is_spillover_strength": False,
                "fit_status": "ok",
                "design_cost": float(config.n_zones * config.n_periods),
                "evidence_type": BENCHMARK_EVIDENCE,
                "input_graph_evidence_label": CALIBRATION_EVIDENCE,
                "estimand_definition": TARGET_DEFINITIONS[target],
            }
        )
    return records


def _naive_record(
    frame: pd.DataFrame,
    config: NYCGraphBenchmarkConfig,
    truths: NYCGraphEstimands,
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
            covariates=("graph_baseline_score", "period_sin", "period_cos"),
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
        "design": "two_stage_saturation_on_fixed_nyc_od_graph",
        "estimator": "nyc_graph_naive_assignment_cluster_regression",
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
        "inference_valid": int(estimate.diagnostics["n_clusters"])
        >= config.minimum_inference_clusters,
        "inference_valid_for_target": False,
        "coefficient_inference_cluster_aware": True,
        "controlled_exposure_not_market_total": False,
        "graph_weight_is_spillover_strength": False,
        "fit_status": "ok",
        "design_cost": float(config.n_zones * config.n_periods),
        "effect_scale": "stage-one saturation coefficient; not full-policy market total",
        "identification_scope": (
            "Randomization identifies an assignment-saturation contrast. Omitted NYC-graph "
            "neighbor exposure and history prevent relabeling it market_total_effect."
        ),
        "evidence_type": "semi_synthetic_nyc_graph_target_mismatch_diagnostic",
        "input_graph_evidence_label": CALIBRATION_EVIDENCE,
        "estimand_definition": TARGET_DEFINITIONS["market_total_effect"],
    }


def _fit_ledger(
    records: pd.DataFrame,
    failures: pd.DataFrame,
    config: NYCGraphBenchmarkConfig,
) -> pd.DataFrame:
    plans = [
        {
            "estimator": "nyc_graph_exposure_mapped_cluster_regression",
            "target_estimand": target,
            "identified": True,
            "comparison_status": "identified_controlled_exposure_response",
        }
        for target in (
            "controlled_zone_direct_effect",
            "spillover_effect",
            "controlled_history_exposure_response",
        )
    ]
    plans.append(
        {
            "estimator": "nyc_graph_naive_assignment_cluster_regression",
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
    inference = (
        records.groupby(keys)["inference_valid_for_target"]
        .mean()
        .rename("target_inference_valid_rate")
        .reset_index()
    )
    ledger = ledger.merge(inference, on=keys, how="left", validate="one_to_one")
    ledger["target_inference_valid_rate"] = ledger[
        "target_inference_valid_rate"
    ].fillna(0.0)
    ledger["decision_eligible"] = (
        ledger["identified"]
        & ledger["fit_complete"]
        & ledger["target_inference_valid_rate"].eq(1.0)
    )
    ledger["recorded_failure_rows"] = int(len(failures))
    ledger["evidence_type"] = "semi_synthetic_nyc_graph_fit_ledger"
    return ledger.sort_values(keys).reset_index(drop=True)


def _summary(
    records: pd.DataFrame,
    ledger: pd.DataFrame,
    config: NYCGraphBenchmarkConfig,
    truths: NYCGraphEstimands,
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
        mapped_summary["graph_weight_is_spillover_strength"] = False
        mapped_summary["diagnostic_mean_gap_to_market_total"] = np.nan
        mapped_summary["diagnostic_gap_mcse"] = np.nan
        mapped_summary["evidence_type"] = (
            "semi_synthetic_nyc_graph_known_truth_monte_carlo"
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
            invalid, ["coverage", "coverage_mcse", "power", "power_mcse"]
        ] = np.nan
        mapped_summary["withheld_reason"] = np.where(
            invalid,
            "cluster count is below the predeclared inference minimum",
            None,
        )

    naive = records.loc[
        records["estimator"].eq("nyc_graph_naive_assignment_cluster_regression")
        & records["fit_status"].eq("ok")
    ].copy()
    if naive.empty:
        naive_summary = pd.DataFrame()
    else:
        diagnostic = naive["diagnostic_gap_to_market_total"].astype(float)
        naive_summary = pd.DataFrame(
            [
                {
                    "design": "two_stage_saturation_on_fixed_nyc_od_graph",
                    "estimator": "nyc_graph_naive_assignment_cluster_regression",
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
                    "graph_weight_is_spillover_strength": False,
                    "diagnostic_mean_gap_to_market_total": float(diagnostic.mean()),
                    "diagnostic_gap_mcse": float(
                        diagnostic.std(ddof=1) / np.sqrt(len(diagnostic))
                    ),
                    "inference_valid_for_target": False,
                    "withheld_reason": (
                        "The assignment coefficient omits mapped NYC-graph neighbor and "
                        "history exposure; market-total bias, RMSE, coverage, and power "
                        "are withheld."
                    ),
                    "evidence_type": (
                        "semi_synthetic_nyc_graph_target_mismatch_diagnostic"
                    ),
                }
            ]
        )
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
        ledger[fit_columns],
        on=["estimator", "target_estimand"],
        how="left",
        validate="one_to_one",
    )
    return summary.sort_values(
        ["identified", "target_estimand"], ascending=[False, True]
    ).reset_index(drop=True)


def run_nyc_graph_benchmark(
    bundle_directory: str | Path,
    config: NYCGraphBenchmarkConfig | None = None,
) -> NYCGraphBenchmarkResult:
    """Validate a calibration bundle and run the known-truth NYC-graph benchmark."""

    cfg = config or NYCGraphBenchmarkConfig()
    bundle = validate_nyc_graph_bundle(bundle_directory)
    edges, selected_zones, selection_metadata, graph_score = _selected_graph(
        bundle.edges, cfg.n_zones
    )
    truths = known_nyc_graph_estimands(cfg)
    records: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for replication, seed_pair in enumerate(_replication_seeds(cfg.seed, cfg.replications)):
        assignment_seed, outcome_seed = seed_pair
        frame = _simulate(
            cfg,
            edges,
            selected_zones,
            graph_score,
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
            for target in (
                "controlled_zone_direct_effect",
                "spillover_effect",
                "controlled_history_exposure_response",
            ):
                failures.append(
                    {
                        "replication": replication,
                        "assignment_seed": assignment_seed,
                        "outcome_seed": outcome_seed,
                        "estimator": "nyc_graph_exposure_mapped_cluster_regression",
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
                    "estimator": "nyc_graph_naive_assignment_cluster_regression",
                    "target_estimand": "market_total_effect",
                    "stage": "estimation",
                    "error": str(exc),
                }
            )

    record_frame = pd.DataFrame(records)
    if record_frame.empty:
        raise RuntimeError("NYC graph benchmark produced no successful fits")
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
    ledger = _fit_ledger(record_frame, failure_frame, cfg)
    summary = _summary(record_frame, ledger, cfg, truths)
    metadata: dict[str, Any] = {
        "evidence_type": BENCHMARK_EVIDENCE,
        "causal_claim_from_nyc_data": False,
        "input_graph_evidence_label": CALIBRATION_EVIDENCE,
        "config": asdict(cfg),
        "known_estimands": truths.to_dict(),
        "estimand_definitions": dict(TARGET_DEFINITIONS),
        "calibration_bundle": {
            "directory_name": _portable_bundle_directory(bundle.directory),
            "manifest_sha256": bundle.manifest_sha256,
            "exposure_mapping_sha256": bundle.mapping_sha256,
            "verified_file_sha256": dict(bundle.verified_files),
            "manifest_source_data_attestation": dict(
                bundle.manifest["source_data_manifest"]
            ),
        },
        "zone_subset": selection_metadata,
        "assignment_design": (
            "one randomized geographic cluster per selected zone; balanced saturation "
            "arms followed by within-zone-period binomial opportunity assignment"
        ),
        "graph_weight_role": (
            "Completed-trip OD weights define relative neighbor exposure geometry only. "
            "They are row-normalized and are not spillover strength, a causal effect, "
            "substitution, mobility, or equilibrium response."
        ),
        "history_mapping": f"mean of {cfg.history_lags} exact own-treatment lag(s)",
        "market_total_bridge": (
            "Known only because the benchmark declares an additive DGP. Controlled "
            "exposure slopes remain separate from market_total_effect."
        ),
        "naive_assignment_status": (
            "target mismatch; cluster-aware coefficient uncertainty does not justify "
            "market-total bias, RMSE, coverage, or power"
        ),
    }
    return NYCGraphBenchmarkResult(
        records=record_frame.sort_values(
            ["replication", "estimator", "target_estimand"]
        ).reset_index(drop=True),
        summary=summary,
        fit_ledger=ledger,
        failures=failure_frame,
        metadata=metadata,
    )


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


def _artifact_portable_input_path(value: Any, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a nonempty path string")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or path == Path("."):
        raise ValueError(f"{label} must be project-relative and portable")
    return path


def _artifact_input_entry(
    path: Path,
    *,
    project_root: Path,
    expected_sha256: Any,
    role: str,
    media_type: str,
) -> dict[str, Any]:
    if not _is_sha256(expected_sha256):
        raise ValueError(f"{role} declared SHA-256 is invalid")
    resolved = path.resolve()
    try:
        portable = resolved.relative_to(project_root).as_posix()
    except ValueError as exc:
        raise ValueError(f"{role} must be contained by project_root") from exc
    if not resolved.is_file():
        raise FileNotFoundError(f"{role} is required: {resolved}")
    actual = sha256_file(resolved)
    if actual != expected_sha256:
        raise ValueError(f"{role} SHA-256 disagrees with result metadata")
    return {
        "path": portable,
        "role": role,
        "media_type": media_type,
        "bytes": resolved.stat().st_size,
        "sha256": actual,
        "evidence_types": [CALIBRATION_EVIDENCE],
    }


def _artifact_calibration_inputs(
    metadata: Mapping[str, Any], project_root: Path
) -> list[dict[str, Any]]:
    calibration = metadata.get("calibration_bundle")
    if not isinstance(calibration, Mapping):
        raise ValueError("result metadata lacks calibration_bundle provenance")
    relative_directory = _artifact_portable_input_path(
        calibration.get("directory_name"),
        "result metadata calibration_bundle.directory_name",
    )
    directory = (project_root / relative_directory).resolve()
    try:
        directory.relative_to(project_root)
    except ValueError as exc:
        raise ValueError("calibration bundle must be contained by project_root") from exc

    reverified = validate_nyc_graph_bundle(directory)
    expected_manifest = calibration.get("manifest_sha256")
    expected_mapping = calibration.get("exposure_mapping_sha256")
    if (
        reverified.manifest_sha256 != expected_manifest
        or reverified.mapping_sha256 != expected_mapping
    ):
        raise ValueError("revalidated calibration hashes disagree with result metadata")
    declared_files = calibration.get("verified_file_sha256")
    if not isinstance(declared_files, Mapping) or dict(
        reverified.verified_files
    ) != dict(declared_files):
        raise ValueError("revalidated calibration file set disagrees with result metadata")

    return [
        _artifact_input_entry(
            directory / MANIFEST_FILENAME,
            project_root=project_root,
            expected_sha256=expected_manifest,
            role="calibration_manifest",
            media_type="application/json",
        ),
        _artifact_input_entry(
            directory / MAPPING_FILENAME,
            project_root=project_root,
            expected_sha256=expected_mapping,
            role="exposure_mapping",
            media_type="text/csv",
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


def write_nyc_graph_benchmark_artifacts(
    result: NYCGraphBenchmarkResult,
    output_dir: str | Path,
    *,
    project_root: str | Path | None = None,
) -> dict[str, Path]:
    """Atomically publish a self-contained NYC-graph benchmark bundle.

    The bundle keeps descriptive input-graph provenance separate from semi-synthetic
    known-truth results. Equal result objects produce byte-identical artifacts.
    """

    if not isinstance(result, NYCGraphBenchmarkResult):
        raise TypeError("result must be an NYCGraphBenchmarkResult")
    if not isinstance(result.metadata, Mapping):
        raise TypeError("result.metadata must be a mapping")
    artifact_root = _artifact_project_root(project_root)
    inputs = _artifact_calibration_inputs(result.metadata, artifact_root)
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
            "schema_version": NYC_GRAPH_BENCHMARK_ARTIFACT_SCHEMA_VERSION,
            "artifact_type": "nyc_graph_interference_benchmark",
            "portable_output_directory": portable_output,
            "portable_paths": True,
            "bundle_valid": True,
            "evidence_type": BENCHMARK_EVIDENCE,
            "causal_claim": False,
            "causal_claim_from_nyc_data": False,
            "input_graph_evidence_label": CALIBRATION_EVIDENCE,
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
                        frame, BENCHMARK_EVIDENCE
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
                "evidence_types": [BENCHMARK_EVIDENCE],
            }
        )
        manifest = {
            "schema_version": NYC_GRAPH_BENCHMARK_ARTIFACT_SCHEMA_VERSION,
            "artifact_type": "nyc_graph_interference_benchmark",
            "evidence_type": BENCHMARK_EVIDENCE,
            "causal_claim": False,
            "causal_claim_from_nyc_data": False,
            "input_graph_evidence_label": CALIBRATION_EVIDENCE,
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
    "NYCGraphBenchmarkConfig",
    "NYCGraphBenchmarkResult",
    "NYCGraphEstimands",
    "ValidatedNYCGraphBundle",
    "known_nyc_graph_estimands",
    "run_nyc_graph_benchmark",
    "validate_nyc_graph_bundle",
    "write_nyc_graph_benchmark_artifacts",
]
