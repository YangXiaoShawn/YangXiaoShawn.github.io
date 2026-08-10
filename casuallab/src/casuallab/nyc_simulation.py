"""Fail-closed NYC descriptive anchors for semi-synthetic simulations.

This module does not fit a causal or structural model.  It verifies a published
NYC calibration bundle and its source-data lineage, then translates a small set
of observable completed-trip moments into transparent simulator initializers.
Every response, interference, persistence, supply, substitution, and welfare
quantity remains an explicit assumption supplied by a :class:`SimulationConfig`
template.
"""

from __future__ import annotations

import calendar
import csv
import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from casuallab.config import SimulationConfig
from casuallab.data import sha256_file

DESCRIPTIVE_EVIDENCE_LABEL = "descriptive_real_data"
ANCHOR_EVIDENCE_LABEL = "semi_synthetic_descriptive_anchor"
ANCHOR_SCHEMA_VERSION = "1.0.0"

CAUSAL_ASSUMPTION_FIELDS = (
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
    "capacity_per_driver",
    "matching_efficiency",
    "rider_value",
    "operating_cost_per_trip",
    "wait_disutility_per_minute",
)

NO_CAUSAL_CLAIM = (
    "NYC published completed trips identify neither latent demand nor available supply "
    "and do not identify treatment response, supply response, spillovers, persistence, "
    "substitution, or welfare. Those quantities remain explicit simulation assumptions."
)

_REQUIRED_CALIBRATION_CHECKS = frozenset(
    {
        "graph_conserves_od",
        "od_conserves_clean",
        "od_counts_positive",
        "od_keys_unique",
        "raw_equals_clean",
        "raw_rows_declared",
        "source_manifest_valid",
        "variance_trip_sum_conserves",
        "zone_conserves_clean",
        "zone_keys_unique",
    }
)
_HASH_PATTERN = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True, slots=True)
class NYCSimulationAnchorSettings:
    """Deterministic target geometry for a semi-synthetic NYC proposal.

    ``None`` preserves the complete observed zone or hourly dimension.  Smaller
    values declare a simulation-size choice; the builder does not claim that it
    selected a representative subset of observed zones or hours.
    """

    target_n_zones: int | None = None
    target_n_periods: int | None = None
    seed: int = 202503

    def __post_init__(self) -> None:
        for name in ("target_n_zones", "target_n_periods"):
            value = getattr(self, name)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value < 1
            ):
                raise ValueError(f"{name} must be a positive integer when supplied")
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise ValueError("seed must be an integer")

    def to_dict(self) -> dict[str, int | None]:
        return {
            "target_n_zones": self.target_n_zones,
            "target_n_periods": self.target_n_periods,
            "seed": self.seed,
        }


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be a JSON object")
    return dict(value)


def _load_object(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    try:
        return _object(json.loads(path.read_text(encoding="utf-8")), label)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} is not valid JSON: {path}") from exc


def _integer(payload: Mapping[str, Any], key: str, label: str, *, positive: bool = False) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label}.{key} must be an integer")
    if positive and value < 1:
        raise ValueError(f"{label}.{key} must be positive")
    return value


def _number(
    payload: Mapping[str, Any],
    key: str,
    label: str,
    *,
    positive: bool = False,
    nonnegative: bool = False,
) -> float:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label}.{key} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{label}.{key} must be finite")
    if positive and result <= 0:
        raise ValueError(f"{label}.{key} must be positive")
    if nonnegative and result < 0:
        raise ValueError(f"{label}.{key} cannot be negative")
    return result


def _relative_path(value: Any, label: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty relative path")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{label} must be portable and cannot escape its manifest root")
    return path


def _resolve_within(root: Path, relative: Path, label: str) -> Path:
    base = root.resolve()
    resolved = (base / relative).resolve()
    try:
        resolved.relative_to(base)
    except ValueError as exc:
        raise ValueError(f"{label} escapes its manifest root") from exc
    return resolved


def _expected_hash(value: Any, label: str) -> str:
    if not isinstance(value, str) or _HASH_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _manifest_entries(payload: Mapping[str, Any], root: Path, label: str) -> dict[Path, dict[str, Any]]:
    entries = payload.get("files")
    if not isinstance(entries, list) or not entries:
        raise ValueError(f"{label}.files must be a non-empty list")
    verified: dict[Path, dict[str, Any]] = {}
    for index, raw_entry in enumerate(entries):
        entry = _object(raw_entry, f"{label}.files[{index}]")
        relative = _relative_path(entry.get("path"), f"{label}.files[{index}].path")
        resolved = _resolve_within(root, relative, f"{label}.files[{index}].path")
        if resolved in verified:
            raise ValueError(f"{label} contains a duplicate file path: {relative}")
        expected_bytes = _integer(entry, "bytes", f"{label}.files[{index}]")
        if expected_bytes < 0:
            raise ValueError(f"{label}.files[{index}].bytes cannot be negative")
        expected_sha = _expected_hash(
            entry.get("sha256"), f"{label}.files[{index}].sha256"
        )
        if not resolved.is_file():
            raise FileNotFoundError(f"{label} file is missing: {resolved}")
        if resolved.stat().st_size != expected_bytes:
            raise ValueError(f"{label} byte mismatch: {relative}")
        if sha256_file(resolved) != expected_sha:
            raise ValueError(f"{label} SHA-256 mismatch: {relative}")
        verified[resolved] = entry
    return verified


def _declared_file_set_sha256(entries: Sequence[Mapping[str, Any]]) -> str:
    canonical = json.dumps(
        [
            {
                "path": str(entry.get("path")),
                "bytes": int(entry.get("bytes", -1)),
                "sha256": str(entry.get("sha256")),
            }
            for entry in entries
        ],
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def _require_descriptive_scope(payload: Mapping[str, Any], label: str) -> None:
    if payload.get("evidence_label") != DESCRIPTIVE_EVIDENCE_LABEL:
        raise ValueError(f"{label} must be labeled {DESCRIPTIVE_EVIDENCE_LABEL}")
    if payload.get("causal_claim") is not False:
        raise ValueError(f"{label} must declare causal_claim=false")


def _validate_source_record(record: Mapping[str, Any], label: str) -> None:
    required_true = (
        "all_valid",
        "hashes_recomputed",
        "queried_files_listed",
        "scope_is_full_nyc_descriptive",
    )
    invalid = [key for key in required_true if record.get(key) is not True]
    if invalid:
        raise ValueError(f"{label} has invalid lineage flags: {invalid}")
    if record.get("mismatches") != []:
        raise ValueError(f"{label}.mismatches must be empty")
    _relative_path(record.get("path"), f"{label}.path")
    _expected_hash(record.get("sha256"), f"{label}.sha256")
    _expected_hash(
        record.get("declared_file_set_sha256"),
        f"{label}.declared_file_set_sha256",
    )
    _integer(record, "entries", label, positive=True)


def _source_project_root(
    calibration_path: Path,
    source_manifest_relative: Path,
    project_root: str | Path | None,
) -> tuple[Path, str]:
    if project_root is not None:
        root = Path(project_root).resolve()
        if not root.is_dir():
            raise FileNotFoundError(root)
        return root, "explicit"

    candidates = (calibration_path.parent, *calibration_path.parents)
    for candidate in candidates:
        root = candidate.resolve()
        resolved = _resolve_within(root, source_manifest_relative, "source manifest path")
        if resolved.is_file():
            return root, "inferred_from_portable_source_manifest_path"
    raise FileNotFoundError(
        "could not infer project_root from the portable source-data manifest path; "
        "supply project_root explicitly"
    )


def _verify_integrity(
    calibration_path: Path,
    manifest_path: Path,
    project_root: str | Path | None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    calibration = _load_object(calibration_path, "NYC calibration")
    bundle_manifest = _load_object(manifest_path, "NYC calibration manifest")

    for payload, label in (
        (calibration, "NYC calibration"),
        (bundle_manifest, "NYC calibration manifest"),
    ):
        if payload.get("schema_version") != ANCHOR_SCHEMA_VERSION:
            raise ValueError(f"{label} has an unsupported schema_version")
        _require_descriptive_scope(payload, label)
    if bundle_manifest.get("portable_paths") is not True:
        raise ValueError("NYC calibration manifest must declare portable_paths=true")
    if calibration.get("bundle_valid") is not True:
        raise ValueError("NYC calibration bundle_valid is not true")

    incomplete_marker = calibration_path.parent.with_name(
        f"{calibration_path.parent.name}_INCOMPLETE.json"
    )
    if incomplete_marker.exists():
        raise RuntimeError("NYC calibration bundle is marked incomplete")

    bundle_files = _manifest_entries(
        bundle_manifest, manifest_path.parent, "NYC calibration manifest"
    )
    if calibration_path.resolve() not in bundle_files:
        raise ValueError("NYC calibration is not covered by its bundle manifest")

    calibration_provenance = _object(
        calibration.get("provenance"), "NYC calibration.provenance"
    )
    calibration_source = _object(
        calibration_provenance.get("source_data_manifest"),
        "NYC calibration.provenance.source_data_manifest",
    )
    manifest_source = _object(
        bundle_manifest.get("source_data_manifest"),
        "NYC calibration manifest.source_data_manifest",
    )
    _validate_source_record(calibration_source, "NYC calibration source lineage")
    _validate_source_record(manifest_source, "NYC calibration manifest source lineage")
    if calibration_source != manifest_source:
        raise ValueError("calibration and bundle manifest source lineage records disagree")

    source_relative = _relative_path(
        calibration_source["path"], "NYC calibration source lineage.path"
    )
    root, root_resolution = _source_project_root(
        calibration_path, source_relative, project_root
    )
    source_manifest_path = _resolve_within(root, source_relative, "source manifest path")
    if source_manifest_path.parent.joinpath("NYC_FULL_INCOMPLETE.json").exists():
        raise RuntimeError("NYC source-data pipeline is marked incomplete")
    actual_source_manifest_sha = sha256_file(source_manifest_path)
    if actual_source_manifest_sha != calibration_source["sha256"]:
        raise ValueError("NYC source-data manifest SHA-256 disagrees with calibration lineage")

    source_manifest = _load_object(source_manifest_path, "NYC source-data manifest")
    if source_manifest.get("schema_version") != ANCHOR_SCHEMA_VERSION:
        raise ValueError("NYC source-data manifest has an unsupported schema_version")
    source_config = _object(source_manifest.get("config"), "NYC source-data manifest.config")
    source_metadata = _object(
        source_manifest.get("metadata"), "NYC source-data manifest.metadata"
    )
    if source_config.get("source") != "nyc_hvfhv" or source_config.get("mode") != "full":
        raise ValueError("NYC source-data manifest must declare source=nyc_hvfhv and mode=full")
    if source_metadata.get("evidence_label") != DESCRIPTIVE_EVIDENCE_LABEL:
        raise ValueError("NYC source-data manifest has an incompatible evidence label")
    if source_metadata.get("causal_claim") is not False:
        raise ValueError("NYC source-data manifest must declare causal_claim=false")

    source_entries = source_manifest.get("files")
    if not isinstance(source_entries, list):
        raise ValueError("NYC source-data manifest.files must be a list")
    declared_digest = _declared_file_set_sha256(
        [_object(item, "NYC source-data manifest file entry") for item in source_entries]
    )
    if declared_digest != calibration_source["declared_file_set_sha256"]:
        raise ValueError("NYC source-data declared file-set SHA-256 disagrees with lineage")
    if len(source_entries) != calibration_source["entries"]:
        raise ValueError("NYC source-data manifest entry count disagrees with lineage")
    source_files = _manifest_entries(source_manifest, root, "NYC source-data manifest")

    integrity = {
        "all_valid": True,
        "bundle_manifest_sha256": sha256_file(manifest_path),
        "calibration_sha256": sha256_file(calibration_path),
        "bundle_files_verified": len(bundle_files),
        "source_data_manifest_sha256": actual_source_manifest_sha,
        "source_declared_file_set_sha256": declared_digest,
        "source_files_verified": len(source_files),
        "project_root_resolution": root_resolution,
        "hashes_recomputed": True,
    }
    return calibration, source_manifest, integrity, bundle_files


def _validate_full_month_scope(
    calibration: Mapping[str, Any], source_manifest: Mapping[str, Any]
) -> tuple[int, int, int, int]:
    scope = _object(calibration.get("scope"), "NYC calibration.scope")
    if scope.get("source") != "nyc_hvfhv" or scope.get("population_claim") is not False:
        raise ValueError("NYC calibration scope is not full descriptive HVFHV evidence")
    if scope.get("unit") != "published_completed_trip_record_and_pickup_zone_hour":
        raise ValueError("NYC calibration has an incompatible unit of observation")
    try:
        pickup_min = datetime.fromisoformat(str(scope["pickup_min"]))
        pickup_max = datetime.fromisoformat(str(scope["pickup_max"]))
    except (KeyError, ValueError) as exc:
        raise ValueError("NYC calibration pickup coverage is malformed") from exc
    final_day = calendar.monthrange(pickup_min.year, pickup_min.month)[1]
    full_calendar_month = (
        pickup_min.year == pickup_max.year
        and pickup_min.month == pickup_max.month
        and pickup_min.day == 1
        and pickup_min.hour == pickup_min.minute == pickup_min.second == 0
        and pickup_max.day == final_day
        and pickup_max.hour == 23
        and pickup_max.minute == pickup_max.second == 59
    )
    if not full_calendar_month:
        raise ValueError("NYC calibration does not cover one complete calendar month")
    calendar_hours = final_day * 24

    checks = _object(calibration.get("checks"), "NYC calibration.checks")
    missing_checks = sorted(_REQUIRED_CALIBRATION_CHECKS.difference(checks))
    if missing_checks:
        raise ValueError(f"NYC calibration checks are incomplete: {missing_checks}")
    failed_checks = sorted(key for key, value in checks.items() if value is not True)
    if failed_checks:
        raise ValueError(f"NYC calibration checks failed: {failed_checks}")

    conservation = _object(
        calibration.get("conservation"), "NYC calibration.conservation"
    )
    zones = _integer(conservation, "zones", "NYC calibration.conservation", positive=True)
    periods = _integer(
        conservation, "periods", "NYC calibration.conservation", positive=True
    )
    panel_cells = _integer(
        conservation, "zone_rows", "NYC calibration.conservation", positive=True
    )
    clean_rows = _integer(
        conservation, "clean_rows", "NYC calibration.conservation", positive=True
    )
    if periods != calendar_hours or panel_cells != zones * periods:
        raise ValueError("NYC calibration panel geometry is inconsistent with calendar coverage")
    conserved = (
        _integer(conservation, "raw_rows_declared", "NYC calibration.conservation")
        == clean_rows
        == _integer(conservation, "zone_trip_sum", "NYC calibration.conservation")
        == _integer(conservation, "od_trip_sum", "NYC calibration.conservation")
    )
    if not conserved:
        raise ValueError("NYC calibration row conservation is inconsistent")

    source_config = _object(source_manifest.get("config"), "NYC source-data manifest.config")
    source_metadata = _object(
        source_manifest.get("metadata"), "NYC source-data manifest.metadata"
    )
    full_month = _object(
        source_metadata.get("full_month_processing"),
        "NYC source-data manifest.metadata.full_month_processing",
    )
    row_conservation = _object(
        full_month.get("row_conservation"),
        "NYC source-data manifest full-month row_conservation",
    )
    if (
        source_config.get("panel_frequency") != "1h"
        or source_config.get("complete_panel_grid") is not True
        or source_config.get("nyc_year") != pickup_min.year
        or source_config.get("nyc_months") != [pickup_min.month]
        or full_month.get("complete_calendar_coverage") is not True
        or full_month.get("configured_date_hours") != periods
        or full_month.get("observed_date_hours") != periods
        or row_conservation.get("passes") is not True
    ):
        raise ValueError("NYC source-data manifest does not certify complete hourly-month scope")
    return zones, periods, panel_cells, clean_rows


def _temporal_diagnostics(
    calibration: Mapping[str, Any],
    calibration_path: Path,
    bundle_files: Mapping[Path, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    associations = _object(
        calibration.get("temporal_associations"), "NYC calibration.temporal_associations"
    )
    if associations.get("evidence_label") != DESCRIPTIVE_EVIDENCE_LABEL:
        raise ValueError("NYC temporal associations have an incompatible evidence label")
    relative = _relative_path(
        associations.get("file"), "NYC calibration.temporal_associations.file"
    )
    source = _resolve_within(
        calibration_path.parent, relative, "NYC temporal associations file"
    )
    if source not in bundle_files:
        raise ValueError("NYC temporal associations are not covered by the bundle manifest")
    declared_lags = associations.get("lags_hours")
    if not isinstance(declared_lags, list) or not declared_lags:
        raise ValueError("NYC temporal association lags_hours must be a non-empty list")

    required = {
        "lag_hours",
        "exact_lag_support_pairs",
        "support_share",
        "pooled_trip_count_correlation",
        "within_zone_centered_correlation",
        "evidence_label",
        "interpretation_warning",
    }
    diagnostics: list[dict[str, Any]] = []
    with source.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            raise ValueError("NYC temporal association CSV has an incompatible schema")
        for row in reader:
            if row["evidence_label"] != DESCRIPTIVE_EVIDENCE_LABEL:
                raise ValueError("NYC temporal association row has an incompatible evidence label")
            try:
                lag = int(row["lag_hours"])
                support = int(row["exact_lag_support_pairs"])
                support_share = float(row["support_share"])
                pooled = float(row["pooled_trip_count_correlation"])
                within_zone = float(row["within_zone_centered_correlation"])
            except (TypeError, ValueError) as exc:
                raise ValueError("NYC temporal association row contains malformed numbers") from exc
            values = (support_share, pooled, within_zone)
            if (
                lag < 1
                or support < 1
                or not all(math.isfinite(value) for value in values)
                or not 0 <= support_share <= 1
                or not -1 <= pooled <= 1
                or not -1 <= within_zone <= 1
            ):
                raise ValueError("NYC temporal association row contains invalid values")
            diagnostics.append(
                {
                    "lag_hours": lag,
                    "exact_lag_support_pairs": support,
                    "support_share": support_share,
                    "pooled_trip_count_correlation": pooled,
                    "within_zone_centered_correlation": within_zone,
                    "evidence_label": DESCRIPTIVE_EVIDENCE_LABEL,
                    "interpretation": row["interpretation_warning"],
                    "assigned_to_simulator_persistence": False,
                }
            )
    if sorted(item["lag_hours"] for item in diagnostics) != sorted(declared_lags):
        raise ValueError("NYC temporal association rows disagree with declared lags")
    return sorted(diagnostics, key=lambda item: item["lag_hours"])


def _anchor_moments(
    calibration: Mapping[str, Any], zones: int, periods: int, panel_cells: int, trips: int
) -> dict[str, float | int]:
    moments = _object(
        calibration.get("trip_level_descriptive_moments"),
        "NYC calibration.trip_level_descriptive_moments",
    )
    if _integer(moments, "trip_rows", "NYC calibration trip moments") != trips:
        raise ValueError("NYC trip moments disagree with conserved trip rows")
    fare = _object(moments.get("fare"), "NYC calibration fare moments")
    wait = _object(
        moments.get("request_to_pickup_wait_minutes"), "NYC calibration wait moments"
    )
    if (
        fare.get("evidence_label") != DESCRIPTIVE_EVIDENCE_LABEL
        or wait.get("evidence_label") != DESCRIPTIVE_EVIDENCE_LABEL
        or wait.get("available") is not True
    ):
        raise ValueError("NYC fare or wait moments have incompatible evidence metadata")
    base_fare = _number(fare, "mean", "NYC calibration fare moments", positive=True)
    wait_mean = _number(wait, "mean", "NYC calibration wait moments", positive=True)
    wait_median = _number(wait, "p50", "NYC calibration wait moments", positive=True)

    variance = _object(
        calibration.get("zone_hour_variance_decomposition"),
        "NYC calibration.zone_hour_variance_decomposition",
    )
    if variance.get("evidence_label") != DESCRIPTIVE_EVIDENCE_LABEL:
        raise ValueError("NYC variance decomposition has an incompatible evidence label")
    if (
        _integer(variance, "zones", "NYC variance decomposition") != zones
        or _integer(variance, "periods", "NYC variance decomposition") != periods
        or _integer(variance, "panel_cells", "NYC variance decomposition") != panel_cells
        or _integer(variance, "total_completed_trips", "NYC variance decomposition") != trips
    ):
        raise ValueError("NYC variance decomposition disagrees with panel conservation")
    occupied = _integer(variance, "occupied_cells", "NYC variance decomposition")
    if not 0 < occupied <= panel_cells:
        raise ValueError("NYC occupied-cell count is invalid")
    mean_trips = _number(
        variance,
        "mean_completed_trips_per_zone_hour",
        "NYC variance decomposition",
        positive=True,
    )
    between_zone = _number(
        variance,
        "between_zone_component",
        "NYC variance decomposition",
        nonnegative=True,
    )
    between_hour = _number(
        variance,
        "between_hour_of_day_component",
        "NYC variance decomposition",
        nonnegative=True,
    )
    total_variance = _number(
        variance, "total_cell_variance", "NYC variance decomposition", nonnegative=True
    )
    zone_share = _number(
        variance,
        "icc_like_between_zone_share",
        "NYC variance decomposition",
        nonnegative=True,
    )
    hour_share = _number(
        variance,
        "between_hour_of_day_share",
        "NYC variance decomposition",
        nonnegative=True,
    )
    if zone_share > 1 or hour_share > 1:
        raise ValueError("NYC descriptive variance shares must lie in [0, 1]")
    if not math.isclose(mean_trips * panel_cells, trips, rel_tol=1e-10, abs_tol=1e-6):
        raise ValueError("NYC mean completed-trip scale does not conserve monthly trips")
    if total_variance > 0 and (
        not math.isclose(between_zone / total_variance, zone_share, rel_tol=1e-8)
        or not math.isclose(between_hour / total_variance, hour_share, rel_tol=1e-8)
    ):
        raise ValueError("NYC descriptive variance components and shares disagree")

    zone_relative_sd = math.sqrt(between_zone) / mean_trips
    zone_lognormal_sd_proxy = math.sqrt(math.log1p(zone_relative_sd**2))
    return {
        "base_demand_completed_trip_proxy": mean_trips,
        "base_fare_published_mean": base_fare,
        "base_wait_published_mean": wait_mean,
        "base_wait_published_median": wait_median,
        "zone_relative_completed_trip_sd": zone_relative_sd,
        "zone_lognormal_sd_initialization_proxy": zone_lognormal_sd_proxy,
        "hour_of_day_relative_completed_trip_sd": math.sqrt(between_hour) / mean_trips,
        "total_cell_relative_completed_trip_sd": math.sqrt(total_variance) / mean_trips,
        "icc_like_between_zone_share": zone_share,
        "between_hour_of_day_share": hour_share,
        "occupied_cells": occupied,
    }


def _simulated_control_moments(config: SimulationConfig) -> dict[str, float]:
    """Return deterministic zero-treatment scale and variance shares.

    This is the zero-treatment specialization of the simulator equations.  It
    intentionally avoids constructing randomized assignments and the many
    treatment counterfactuals produced by ``simulate_market``: none of those can
    affect the control path, and doing so makes the full 262 x 744 NYC geometry
    unnecessarily expensive.
    """

    from casuallab.simulator import _make_exogenous_state

    frame = _make_exogenous_state(config)
    latent_demand = frame["baseline_demand"].to_numpy(dtype=float)
    available_drivers = frame["baseline_supply"].to_numpy(dtype=float)
    service_capacity = (
        available_drivers * config.capacity_per_driver * config.matching_efficiency
    )
    capacity_ratio = service_capacity / np.maximum(latent_demand, 1e-12)
    trips = latent_demand * -np.expm1(-capacity_ratio)
    wait_minutes = config.base_wait_minutes * np.power(
        latent_demand / np.maximum(service_capacity, 1e-12), 0.70
    )
    wait_minutes = np.clip(wait_minutes, 0.25, 120.0)
    grand_mean = float(np.mean(trips))
    total_variance = float(np.var(trips, ddof=0))

    def between_share(group: str) -> float:
        grouped = frame.assign(_trips=trips).groupby(group, observed=True)["_trips"].agg(
            ["size", "mean"]
        )
        component = float(
            (grouped["size"] * (grouped["mean"] - grand_mean) ** 2).sum()
            / len(frame)
        )
        return component / total_variance if total_variance > 0 else 0.0

    return {
        "mean_completed_trips": grand_mean,
        "mean_wait_minutes": float(np.mean(wait_minutes)),
        "between_zone_share": between_share("zone_id"),
        "between_hour_of_day_share": between_share("hour"),
    }


def _match_control_variance_share(
    config: SimulationConfig,
    *,
    field: str,
    target: float,
    moment: str,
    iterations: int = 10,
) -> tuple[SimulationConfig, float, str]:
    """Tune one noncausal dispersion initializer to a descriptive share."""

    low = 0.0
    high = 2.0

    def evaluate(value: float) -> float:
        return _simulated_control_moments(replace(config, **{field: value}))[moment]

    low_value = evaluate(low)
    high_value = evaluate(high)
    while high_value < target and high < 8.0:
        high *= 2.0
        high_value = evaluate(high)
    if target <= low_value:
        return replace(config, **{field: low}), low_value, "lower_boundary"
    if target >= high_value:
        return replace(config, **{field: high}), high_value, "upper_boundary"
    for _ in range(iterations):
        midpoint = 0.5 * (low + high)
        midpoint_value = evaluate(midpoint)
        if midpoint_value < target:
            low = midpoint
        else:
            high = midpoint
    value = 0.5 * (low + high)
    configured = replace(config, **{field: value})
    return configured, _simulated_control_moments(configured)[moment], "interior_solution"


def _coerce_template(
    assumption_template: SimulationConfig | Mapping[str, Any] | None,
) -> SimulationConfig:
    if assumption_template is None:
        return SimulationConfig()
    if isinstance(assumption_template, SimulationConfig):
        return assumption_template
    if isinstance(assumption_template, Mapping):
        return SimulationConfig.from_dict(assumption_template)
    raise TypeError("assumption_template must be SimulationConfig, a mapping, or None")


def _field_record(
    value: Any, source: str, evidence_label: str, interpretation: str
) -> dict[str, Any]:
    return {
        "value": value,
        "source": source,
        "evidence_label": evidence_label,
        "causal_claim": False,
        "interpretation": interpretation,
    }


def build_nyc_simulation_anchor(
    calibration_path: str | Path,
    *,
    project_root: str | Path | None = None,
    manifest_path: str | Path | None = None,
    settings: NYCSimulationAnchorSettings | None = None,
    assumption_template: SimulationConfig | Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a serializable, non-causal NYC simulation initialization proposal.

    Integrity validation is intentionally not optional: every bundle file and every
    file declared by the source-data manifest has its byte count and SHA-256
    recomputed before a proposal is returned.
    """

    calibration_file = Path(calibration_path).resolve()
    manifest_file = (
        Path(manifest_path).resolve()
        if manifest_path is not None
        else calibration_file.with_name("manifest.json")
    )
    runtime = settings or NYCSimulationAnchorSettings()
    template = _coerce_template(assumption_template)
    calibration, source_manifest, integrity, bundle_files = _verify_integrity(
        calibration_file, manifest_file, project_root
    )
    observed_zones, observed_periods, observed_cells, observed_trips = (
        _validate_full_month_scope(calibration, source_manifest)
    )
    moments = _anchor_moments(
        calibration,
        observed_zones,
        observed_periods,
        observed_cells,
        observed_trips,
    )
    temporal = _temporal_diagnostics(calibration, calibration_file, bundle_files)

    target_zones = runtime.target_n_zones or observed_zones
    target_periods = runtime.target_n_periods or observed_periods
    if target_zones > observed_zones or target_periods > observed_periods:
        raise ValueError("target panel geometry cannot exceed the observed NYC panel")
    target_cells = target_zones * target_periods
    periods_per_day = 24
    supply_ratio_assumption = template.base_supply / template.base_demand
    design = replace(
        template.design,
        seed=template.design.seed if template.design.seed is not None else runtime.seed + 1,
    )
    config = replace(
        template,
        n_zones=target_zones,
        n_periods=target_periods,
        periods_per_day=periods_per_day,
        base_demand=float(moments["base_demand_completed_trip_proxy"]),
        base_supply=(
            float(moments["base_demand_completed_trip_proxy"])
            * supply_ratio_assumption
        ),
        base_fare=float(moments["base_fare_published_mean"]),
        base_wait_minutes=float(moments["base_wait_published_mean"]),
        zone_heterogeneity_sd=float(
            moments["zone_lognormal_sd_initialization_proxy"]
        ),
        seed=runtime.seed,
        design=design,
    )
    target_zone_share = float(moments["icc_like_between_zone_share"])
    target_hour_share = float(moments["between_hour_of_day_share"])
    zone_tuning_status = "not_attempted_insufficient_target_geometry"
    hour_tuning_status = "not_attempted_insufficient_target_geometry"
    initial_variance_moments = _simulated_control_moments(config)
    achieved_zone_share = initial_variance_moments["between_zone_share"]
    achieved_hour_share = initial_variance_moments["between_hour_of_day_share"]
    # Coordinate the two descriptive dispersion matches because geographic and
    # hourly components share the same total cell variance denominator.
    for _ in range(3):
        if target_zones >= 2:
            config, achieved_zone_share, zone_tuning_status = (
                _match_control_variance_share(
                    config,
                    field="zone_heterogeneity_sd",
                    target=target_zone_share,
                    moment="between_zone_share",
                )
            )
        if target_periods >= periods_per_day:
            config, achieved_hour_share, hour_tuning_status = (
                _match_control_variance_share(
                    config,
                    field="time_pattern_strength",
                    target=target_hour_share,
                    moment="between_hour_of_day_share",
                )
            )
    # Completed trips are an equilibrium-path output of the reduced-form simulator,
    # not latent demand.  Match the observed completed-trip scale on the deterministic
    # control path by jointly rescaling demand and the explicitly assumed supply ratio.
    # This is a semi-synthetic initialization step, never an estimate of either side
    # of the market.
    control_target = float(moments["base_demand_completed_trip_proxy"])
    pre_scale_moments = _simulated_control_moments(config)
    initial_control_mean = pre_scale_moments["mean_completed_trips"]
    if not math.isfinite(initial_control_mean) or initial_control_mean <= 0:
        raise ValueError("NYC anchor simulator control path has non-positive completed trips")
    control_scale = control_target / initial_control_mean
    config = replace(
        config,
        base_demand=config.base_demand * control_scale,
        base_supply=config.base_supply * control_scale,
    )
    post_scale_moments = _simulated_control_moments(config)
    observed_wait_target = float(moments["base_wait_published_mean"])
    if post_scale_moments["mean_wait_minutes"] <= 0:
        raise ValueError("NYC anchor control path has non-positive mean wait")
    wait_scale = observed_wait_target / post_scale_moments["mean_wait_minutes"]
    config = replace(config, base_wait_minutes=config.base_wait_minutes * wait_scale)
    final_control_moments = _simulated_control_moments(config)
    achieved_control_mean = final_control_moments["mean_completed_trips"]
    if not math.isfinite(achieved_control_mean) or achieved_control_mean <= 0:
        raise ValueError("NYC anchor rescaled control path has non-positive completed trips")
    control_calibration_error = achieved_control_mean - control_target
    achieved_wait_mean = final_control_moments["mean_wait_minutes"]
    wait_calibration_error = achieved_wait_mean - observed_wait_target
    achieved_zone_share = final_control_moments["between_zone_share"]
    achieved_hour_share = final_control_moments["between_hour_of_day_share"]
    variance_share_tolerance = 0.01
    broad_moment_match_passed = (
        abs(control_calibration_error) <= 1e-8
        and abs(wait_calibration_error) <= 1e-8
        and abs(achieved_zone_share - target_zone_share) <= variance_share_tolerance
        and abs(achieved_hour_share - target_hour_share) <= variance_share_tolerance
    )
    if not broad_moment_match_passed:
        raise ValueError(
            "NYC anchor control-path broad-moment gate failed: "
            f"completed_trip_error={control_calibration_error:.12g}, "
            f"wait_error={wait_calibration_error:.12g}, "
            f"between_zone_share_error={achieved_zone_share - target_zone_share:.12g}, "
            f"between_hour_share_error={achieved_hour_share - target_hour_share:.12g}, "
            f"variance_share_tolerance={variance_share_tolerance:.12g}"
        )
    config_payload = config.to_dict()

    derived: dict[str, dict[str, Any]] = {
        "periods_per_day": _field_record(
            periods_per_day,
            "complete hourly calendar panel",
            DESCRIPTIVE_EVIDENCE_LABEL,
            "Exact panel timing geometry; not a persistence estimate.",
        ),
        "base_demand": _field_record(
            config.base_demand,
            "joint demand/supply rescaling to the observed completed-trip control target",
            ANCHOR_EVIDENCE_LABEL,
            (
                "Semi-synthetic control-path scale parameter; completed trips are not "
                "latent rider requests and this value is not an empirical demand estimate."
            ),
        ),
        "base_fare": _field_record(
            config.base_fare,
            "mean published base passenger fare per completed trip",
            ANCHOR_EVIDENCE_LABEL,
            "Nominal fare-scale initializer; not total rider payment or platform revenue.",
        ),
        "base_wait_minutes": _field_record(
            config.base_wait_minutes,
            "control-path rescaling to mean nonnegative request-to-pickup elapsed time",
            ANCHOR_EVIDENCE_LABEL,
            (
                "Semi-synthetic service-process scale; not a randomized wait outcome "
                "or rider-utility estimate."
            ),
        ),
        "zone_heterogeneity_sd": _field_record(
            config.zone_heterogeneity_sd,
            "deterministic control-path match to the descriptive between-zone variance share",
            ANCHOR_EVIDENCE_LABEL,
            (
                "Reduced-form dispersion initializer that does not identify latent demand "
                "or supply heterogeneity."
            ),
        ),
        "time_pattern_strength": _field_record(
            config.time_pattern_strength,
            "deterministic control-path match to the descriptive hour-of-day variance share",
            ANCHOR_EVIDENCE_LABEL,
            (
                "Harmonic timing initializer; it is neither causal persistence nor a "
                "seasonality estimate beyond the observed month."
            ),
        ),
    }
    assumptions: dict[str, dict[str, Any]] = {}
    if target_zones == observed_zones:
        derived["n_zones"] = _field_record(
            target_zones,
            "complete observed pickup-zone panel",
            DESCRIPTIVE_EVIDENCE_LABEL,
            "Observed TLC LocationID count represented in the complete panel.",
        )
    else:
        assumptions["n_zones"] = _field_record(
            target_zones,
            "NYCSimulationAnchorSettings.target_n_zones",
            "explicit_sample_design_assumption",
            "Simulation-size choice; no representative zone subset is selected here.",
        )
    if target_periods == observed_periods:
        derived["n_periods"] = _field_record(
            target_periods,
            "complete observed hourly month",
            DESCRIPTIVE_EVIDENCE_LABEL,
            "Observed complete hourly calendar geometry.",
        )
    else:
        assumptions["n_periods"] = _field_record(
            target_periods,
            "NYCSimulationAnchorSettings.target_n_periods",
            "explicit_sample_design_assumption",
            "Simulation-size choice; no representative time subset is selected here.",
        )

    assumption_interpretations = {
        "base_supply": (
            "Scaled by the template baseline supply-to-demand ratio; available drivers "
            "are not observed in completed-trip records."
        ),
        "time_pattern_strength": (
            "Simulator harmonic amplitude is not inferred from the observed hourly profile."
        ),
        "demand_noise_sd": "Latent demand shock dispersion is not observed.",
        "supply_noise_sd": "Latent supply shock dispersion is not observed.",
        "individuals_per_cell": "Simulation population size is a design choice.",
        "budget": "Experiment budget is a policy/design assumption.",
        "seed": "Deterministic simulation seed chosen by the caller.",
        "design": (
            "Assignment mechanism is a template assumption; when its seed is absent, "
            "the deterministic assignment seed is the anchor seed plus one."
        ),
    }
    for field, value in config_payload.items():
        if field in derived or field in assumptions:
            continue
        interpretation = assumption_interpretations.get(
            field,
            (
                "Explicit structural or policy assumption; it is not estimated from "
                "the NYC completed-trip records."
            ),
        )
        source = {
            "base_supply": "assumption_template baseline_supply/base_demand ratio",
            "seed": "NYCSimulationAnchorSettings.seed",
            "design": (
                "assumption_template.design with deterministic assignment-seed fallback "
                "from NYCSimulationAnchorSettings.seed"
            ),
        }.get(field, "assumption_template")
        assumptions[field] = _field_record(
            value, source, "explicit_assumption", interpretation
        )

    causal_groups = {
        "intervention_version_and_dose": [
            "treatment_version",
            "discount_rate",
            "incentive_per_driver",
            "reference_incentive_per_driver",
        ],
        "treatment_and_supply_response": [
            "direct_demand_effect",
            "direct_supply_effect",
        ],
        "interference_and_substitution": [
            "spillover_strength",
            "rider_substitution",
            "driver_mobility",
        ],
        "temporal_carryover": ["persistence"],
        "latent_supply_and_matching": [
            "base_supply",
            "capacity_per_driver",
            "matching_efficiency",
            "supply_noise_sd",
        ],
        "welfare_accounting": [
            "rider_value",
            "operating_cost_per_trip",
            "wait_disutility_per_minute",
        ],
    }
    if not set(CAUSAL_ASSUMPTION_FIELDS).issubset(assumptions):
        raise RuntimeError("causal fields escaped explicit-assumption provenance")

    return {
        "schema_version": ANCHOR_SCHEMA_VERSION,
        "evidence_label": ANCHOR_EVIDENCE_LABEL,
        "causal_claim": False,
        "status": "descriptive_control_path_anchor_validated_not_fitted_structural_model",
        "city": "New York City",
        "source_scope": {
            "dataset": "NYC TLC High Volume For-Hire Vehicle published trip records",
            "pickup_min": calibration["scope"]["pickup_min"],
            "pickup_max": calibration["scope"]["pickup_max"],
            "evidence_label": DESCRIPTIVE_EVIDENCE_LABEL,
            "causal_claim": False,
            "published_completed_trips": observed_trips,
        },
        "integrity": integrity,
        "target_panel": {
            "observed": {
                "n_zones": observed_zones,
                "n_periods": observed_periods,
                "periods_per_day": periods_per_day,
                "panel_cells": observed_cells,
            },
            "simulation": {
                "n_zones": target_zones,
                "n_periods": target_periods,
                "periods_per_day": periods_per_day,
                "panel_cells": target_cells,
                "seed": runtime.seed,
                "assignment_seed": design.seed,
            },
            "sample_scaling": {
                "zone_fraction": target_zones / observed_zones,
                "period_fraction": target_periods / observed_periods,
                "cell_fraction": target_cells / observed_cells,
                "completed_trip_volume_proxy": (
                    float(moments["base_demand_completed_trip_proxy"]) * target_cells
                ),
                "selection_performed": False,
                "interpretation": (
                    "Geometry scaling is a simulation-size decision. The builder does "
                    "not select or claim a representative observed subsample."
                ),
            },
        },
        "observable_anchor": {
            "evidence_label": DESCRIPTIVE_EVIDENCE_LABEL,
            "causal_claim": False,
            "scale_and_heterogeneity": moments,
            "temporal_associations": temporal,
            "interpretation": (
                "Observable completed-trip scale, timing, and dispersion only; temporal "
                "correlations are not mapped to persistence."
            ),
        },
        "control_path_scale_validation": {
            "evidence_label": ANCHOR_EVIDENCE_LABEL,
            "causal_claim": False,
            "target_mean_published_completed_trips_per_zone_hour": control_target,
            "initial_simulated_control_completed_trips": initial_control_mean,
            "joint_demand_supply_scale_factor": control_scale,
            "achieved_simulated_control_completed_trips": achieved_control_mean,
            "calibration_error": control_calibration_error,
            "target_mean_nonnegative_request_to_pickup_minutes": observed_wait_target,
            "achieved_simulated_control_mean_wait_minutes": achieved_wait_mean,
            "wait_scale_factor": wait_scale,
            "wait_calibration_error": wait_calibration_error,
            "target_between_zone_variance_share": target_zone_share,
            "achieved_between_zone_variance_share": achieved_zone_share,
            "zone_dispersion_tuning_status": zone_tuning_status,
            "target_between_hour_of_day_variance_share": target_hour_share,
            "achieved_between_hour_of_day_variance_share": achieved_hour_share,
            "hour_pattern_tuning_status": hour_tuning_status,
            "variance_share_absolute_tolerance": variance_share_tolerance,
            "broad_moment_match_passed": broad_moment_match_passed,
            "preserved_assumed_supply_to_demand_ratio": supply_ratio_assumption,
            "simulation_seed": runtime.seed,
            "interpretation": (
                "Matches one descriptive control-path scale under the declared reduced-form "
                "simulator assumptions; it does not identify latent demand or supply."
            ),
        },
        "simulation_config": config_payload,
        "field_provenance": {
            "derived_initializers": derived,
            "explicit_assumptions": assumptions,
            "partition_complete": (
                set(config_payload) == set(derived).union(assumptions)
                and not set(derived).intersection(assumptions)
            ),
        },
        "causal_parameter_assumptions": {
            "status": "explicit_assumptions_not_estimated_from_nyc_trip_records",
            "groups": causal_groups,
            "fields": list(CAUSAL_ASSUMPTION_FIELDS),
            "calibration_embedded_template_assumptions_used": False,
        },
        "required_validation_before_design_use": [
            "fit or stress-test the simulated control path against held-out descriptive cells",
            "check zone and hourly distributions, not only the grand mean",
            "run sensitivity grids over every structural and causal assumption",
            "do not treat temporal correlation as causal persistence",
            "do not treat OD connectivity as spillover strength or substitution",
        ],
        "warnings": [
            NO_CAUSAL_CLAIM,
            (
                "The base_demand, base_wait_minutes, zone_heterogeneity_sd, and "
                "time_pattern_strength values are semi-synthetic initialization proxies, "
                "not structural estimates."
            ),
            (
                "A reduced target geometry is not an empirical sample until an explicit "
                "pre-treatment-only selection rule and representativeness audit are applied."
            ),
            (
                "One observed month does not establish seasonality or transportability "
                "to other months, products, or cities."
            ),
        ],
    }


def validate_nyc_simulation_anchor_integrity(
    calibration_path: str | Path,
    *,
    project_root: str | Path | None = None,
    manifest_path: str | Path | None = None,
) -> dict[str, Any]:
    """Recompute the complete calibration-bundle and source-data hash chain."""

    calibration_file = Path(calibration_path).resolve()
    manifest_file = (
        Path(manifest_path).resolve()
        if manifest_path is not None
        else calibration_file.with_name("manifest.json")
    )
    _, _, integrity, _ = _verify_integrity(
        calibration_file,
        manifest_file,
        project_root,
    )
    return integrity


__all__ = [
    "ANCHOR_EVIDENCE_LABEL",
    "ANCHOR_SCHEMA_VERSION",
    "CAUSAL_ASSUMPTION_FIELDS",
    "DESCRIPTIVE_EVIDENCE_LABEL",
    "NO_CAUSAL_CLAIM",
    "NYCSimulationAnchorSettings",
    "build_nyc_simulation_anchor",
    "validate_nyc_simulation_anchor_integrity",
]
