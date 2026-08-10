"""Code-generated technical and executive reports from machine-readable artifacts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from casuallab.config import load_simulation_config
from casuallab.equilibrium import (
    CAUSAL_SCOPE as EQUILIBRIUM_CAUSAL_SCOPE,
)
from casuallab.equilibrium import (
    EMPIRICAL_STATUS as EQUILIBRIUM_EMPIRICAL_STATUS,
)
from casuallab.equilibrium import (
    EVIDENCE_TYPE as EQUILIBRIUM_EVIDENCE_TYPE,
)
from casuallab.nyc_benchmark import (
    NYC_BENCHMARK_EVIDENCE_TYPE,
    NYC_BENCHMARK_SCHEMA_VERSION,
)
from casuallab.nyc_events import EVENT_EVIDENCE_LABEL, EVENT_SCHEMA_VERSION
from casuallab.nyc_graph_benchmark import (
    BENCHMARK_EVIDENCE as NYC_GRAPH_EVIDENCE_TYPE,
)
from casuallab.nyc_graph_benchmark import (
    validate_nyc_graph_bundle,
)
from casuallab.nyc_income import INCOME_EVIDENCE_LABEL, INCOME_SCHEMA_VERSION
from casuallab.nyc_simulation import (
    CAUSAL_ASSUMPTION_FIELDS,
    validate_nyc_simulation_anchor_integrity,
)
from casuallab.nyc_weather import WEATHER_EVIDENCE_LABEL
from casuallab.reporting import (
    _strict_boolean,
    _validate_policy_provenance,
    choose_recommendation,
    markdown_table,
    sha256_file,
)


def _validate_benchmark(frame: pd.DataFrame) -> None:
    required = {
        "design",
        "estimator",
        "target_estimand",
        "scenario",
        "declared_scenario_set",
        "declared_scenario_count",
        "rmse",
        "coverage",
        "power",
        "identified",
        "inference_valid",
        "fit_complete",
        "applicable",
        "attempted_fits",
        "successful_fits",
        "bias",
        "evidence_type",
    }
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"benchmark results missing columns: {sorted(missing)}")
    if frame.empty:
        raise ValueError("benchmark results are empty")
    if not frame["evidence_type"].astype(str).str.startswith("semi_synthetic").all():
        raise ValueError("benchmark rows must be labeled semi-synthetic")


def _optional_hash(path: str | Path | None, label: str) -> str:
    if path is None:
        return f"- {label}: not supplied"
    source = Path(path)
    if not source.is_file():
        return f"- {label}: not supplied"
    return f"- {label} SHA-256: `{sha256_file(source)}`"


def _counted(count: int, singular: str, plural: str | None = None) -> str:
    """Render a count without producing strings such as ``1 trips``."""

    return f"{count:,} {singular if count == 1 else plural or singular + 's'}"


def _load_json_object(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"{label} is required: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError(f"{label} is not readable valid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be a JSON object")
    return payload


def _portable_manifest_path(raw_path: object, label: str) -> Path:
    if not isinstance(raw_path, str) or not raw_path:
        raise ValueError(f"{label} must be a nonempty path string")
    path = Path(raw_path)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{label} must be project-relative and portable")
    return path


def _manifest_root_for_artifact(
    manifest: dict[str, Any], artifact_path: Path, label: str
) -> Path:
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError(f"{label} manifest has no file entries")
    target = artifact_path.resolve()
    for entry in files:
        if not isinstance(entry, dict):
            raise ValueError(f"{label} manifest contains a non-object entry")
        rendered = _portable_manifest_path(
            entry.get("path"), f"{label} manifest entry path"
        )
        for candidate_root in target.parents:
            if (candidate_root / rendered).resolve() == target:
                return candidate_root.resolve()
    raise ValueError(
        f"{label} manifest does not contain the supplied artifact"
    )


def _validate_manifest_files(
    manifest: dict[str, Any], manifest_root: Path, label: str
) -> dict[Path, dict[str, Any]]:
    validated: dict[Path, dict[str, Any]] = {}
    for raw_entry in manifest["files"]:
        if not isinstance(raw_entry, dict):
            raise ValueError(f"{label} manifest contains a non-object entry")
        rendered = _portable_manifest_path(
            raw_entry.get("path"), f"{label} manifest entry path"
        )
        expected_bytes = raw_entry.get("bytes")
        expected_sha256 = raw_entry.get("sha256")
        if (
            isinstance(expected_bytes, bool)
            or not isinstance(expected_bytes, int)
            or expected_bytes < 0
            or not isinstance(expected_sha256, str)
            or len(expected_sha256) != 64
        ):
            raise ValueError(f"{label} manifest has an invalid hash entry")
        resolved = (manifest_root / rendered).resolve()
        try:
            resolved.relative_to(manifest_root)
        except ValueError as exc:
            raise ValueError(
                f"{label} manifest entry escapes its project root"
            ) from exc
        if resolved in validated:
            raise ValueError(f"{label} manifest contains duplicate paths")
        if not resolved.is_file():
            raise FileNotFoundError(f"{label} manifest file is missing: {resolved}")
        if resolved.stat().st_size != expected_bytes:
            raise ValueError(f"{label} manifest byte mismatch: {rendered}")
        if sha256_file(resolved) != expected_sha256:
            raise ValueError(f"{label} manifest SHA-256 mismatch: {rendered}")
        validated[resolved] = raw_entry
    return validated


@dataclass(frozen=True, slots=True)
class _ManifestBundle:
    """One manifest whose portable file set has been independently verified."""

    path: Path
    root: Path
    payload: dict[str, Any]
    files: dict[Path, dict[str, Any]]
    inputs: dict[Path, dict[str, Any]]


def _manifest_bundle(
    manifest_path: str | Path | None,
    label: str,
) -> _ManifestBundle | None:
    """Resolve a manifest-only optional input without assuming a repository location."""

    if manifest_path is None:
        return None
    manifest_file = Path(manifest_path).resolve()
    payload = _load_json_object(manifest_file, f"{label} manifest")
    raw_files = payload.get("files")
    if not isinstance(raw_files, list) or not raw_files:
        raise ValueError(f"{label} manifest has no file entries")
    rendered: list[Path] = []
    for entry in raw_files:
        if not isinstance(entry, dict):
            raise ValueError(f"{label} manifest contains a non-object entry")
        rendered.append(
            _portable_manifest_path(entry.get("path"), f"{label} manifest entry path")
        )
    roots = [
        root.resolve()
        for root in manifest_file.parents
        if all((root / relative).resolve().is_file() for relative in rendered)
    ]
    if len(roots) != 1:
        raise ValueError(
            f"{label} manifest portable root is "
            f"{'ambiguous' if roots else 'unresolvable'}"
        )
    incomplete = sorted(manifest_file.parent.glob("*INCOMPLETE*.json"))
    if incomplete:
        raise ValueError(f"{label} evidence is marked incomplete")
    root = roots[0]
    files = _validate_manifest_files(payload, root, label)
    raw_inputs = payload.get("inputs", [])
    if not isinstance(raw_inputs, list):
        raise ValueError(f"{label} manifest inputs must be a list")
    inputs: dict[Path, dict[str, Any]] = {}
    if raw_inputs:
        rendered_inputs: list[Path] = []
        for entry in raw_inputs:
            if not isinstance(entry, dict):
                raise ValueError(f"{label} manifest contains a non-object input")
            rendered_inputs.append(
                _portable_manifest_path(
                    entry.get("path"), f"{label} manifest input path"
                )
            )
        input_roots = [
            candidate.resolve()
            for candidate in manifest_file.parents
            if all(
                (candidate / relative).resolve().is_file()
                for relative in rendered_inputs
            )
        ]
        if len(input_roots) != 1:
            raise ValueError(
                f"{label} manifest input root is "
                f"{'ambiguous' if input_roots else 'unresolvable'}"
            )
        inputs = _validate_manifest_files(
            {"files": raw_inputs}, input_roots[0], f"{label} input"
        )
    declared_digest = payload.get("declared_file_set_sha256")
    if declared_digest is not None:
        actual_digest = hashlib.sha256(
            json.dumps(raw_files, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        if declared_digest != actual_digest:
            raise ValueError(f"{label} declared file-set digest is inconsistent")
    declared_input_digest = payload.get("declared_input_set_sha256")
    if declared_input_digest is not None:
        actual_input_digest = hashlib.sha256(
            json.dumps(raw_inputs, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        if declared_input_digest != actual_input_digest:
            raise ValueError(f"{label} declared input-set digest is inconsistent")
    return _ManifestBundle(manifest_file, root, payload, files, inputs)


def _require_manifest_evidence(
    bundle: _ManifestBundle,
    expected: str,
    label: str,
) -> None:
    metadata = bundle.payload.get("metadata")
    values = {
        bundle.payload.get("evidence_type"),
        bundle.payload.get("evidence_label"),
    }
    if isinstance(metadata, dict):
        values.update({metadata.get("evidence_type"), metadata.get("evidence_label")})
    values.discard(None)
    if expected not in values:
        raise ValueError(f"{label} manifest has an incompatible evidence label")


def _json_objects(bundle: _ManifestBundle, label: str) -> dict[Path, dict[str, Any]]:
    objects: dict[Path, dict[str, Any]] = {}
    for path in bundle.files:
        if path.suffix.lower() == ".json":
            objects[path] = _load_json_object(path, f"{label} JSON artifact")
    return objects


def _unique_json_object(
    bundle: _ManifestBundle,
    predicate: Callable[[dict[str, Any]], bool],
    artifact_label: str,
) -> tuple[Path, dict[str, Any]]:
    candidates = [
        (path, payload)
        for path, payload in _json_objects(bundle, artifact_label).items()
        if predicate(payload)
    ]
    if len(candidates) != 1:
        raise ValueError(
            f"{artifact_label} manifest must identify exactly one matching JSON artifact"
        )
    return candidates[0]


def _csv_header(path: Path, label: str) -> set[str]:
    try:
        return set(pd.read_csv(path, nrows=0).columns)
    except (OSError, pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
        raise ValueError(f"{label} is not a readable CSV artifact") from exc


def _unique_csv(
    bundle: _ManifestBundle,
    required_columns: set[str],
    artifact_label: str,
    *,
    excluded_columns: set[str] | None = None,
) -> tuple[Path, pd.DataFrame]:
    excluded = excluded_columns or set()
    candidates = [
        path
        for path in bundle.files
        if path.suffix.lower() == ".csv"
        and required_columns.issubset(_csv_header(path, artifact_label))
        and not excluded.intersection(_csv_header(path, artifact_label))
    ]
    if len(candidates) != 1:
        raise ValueError(
            f"{artifact_label} manifest must identify exactly one matching CSV artifact"
        )
    return candidates[0], pd.read_csv(candidates[0])


def _valid_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _file_with_declared_hash(
    bundle: _ManifestBundle,
    digest: object,
    label: str,
) -> Path:
    if not _valid_sha256(digest):
        raise ValueError(f"{label} is not a valid SHA-256 digest")
    declared = {**bundle.files, **bundle.inputs}
    matches = [path for path, entry in declared.items() if entry.get("sha256") == digest]
    if len(matches) != 1:
        raise ValueError(f"{label} is not uniquely covered by the evidence manifest")
    return matches[0]


def _bundle_file_by_role(
    bundle: _ManifestBundle,
    role: str,
    label: str,
) -> Path:
    matches = [path for path, entry in bundle.files.items() if entry.get("role") == role]
    if len(matches) != 1:
        raise ValueError(f"{label} manifest must identify exactly one {role!r} file")
    return matches[0]


def _bundle_input_by_role(
    bundle: _ManifestBundle,
    role: str,
    label: str,
) -> Path:
    matches = [path for path, entry in bundle.inputs.items() if entry.get("role") == role]
    if len(matches) != 1:
        raise ValueError(f"{label} manifest must identify exactly one {role!r} input")
    return matches[0]


def _required_string_list(value: object, label: str) -> list[str]:
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(item, str) and item.strip() for item in value)
    ):
        raise ValueError(f"{label} must be a nonempty string list")
    return value


def _required_int(mapping: dict[str, Any], key: str, label: str) -> int:
    value = mapping.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"NYC full validation {label}.{key} must be a nonnegative integer")
    return value


def _required_positive_number(mapping: dict[str, Any], key: str, label: str) -> float:
    value = mapping.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"NYC full validation {label}.{key} must be numeric")
    numeric = float(value)
    if not np.isfinite(numeric) or numeric <= 0:
        raise ValueError(f"NYC full validation {label}.{key} must be positive and finite")
    return numeric


@dataclass(frozen=True, slots=True)
class _NYCFullEvidence:
    summary: str
    limitations: str
    provenance: str
    validation_path: Path
    manifest_path: Path
    data_manifest_path: Path


def _nyc_full_status(
    validation_path: str | Path | None,
    manifest_path: str | Path | None,
) -> _NYCFullEvidence | None:
    """Validate and summarize an optional full-month NYC evidence bundle.

    Supplying either path activates a fail-closed contract: both artifacts, every
    analysis-manifest file, and the source-data lineage must agree before report
    text is generated.
    """

    if validation_path is None and manifest_path is None:
        return None
    if validation_path is None or manifest_path is None:
        raise ValueError(
            "NYC full evidence requires both validation.json and its analysis manifest"
        )
    validation_file = Path(validation_path)
    manifest_file = Path(manifest_path)
    validation = _load_json_object(validation_file, "NYC full validation")
    manifest = _load_json_object(manifest_file, "NYC full analysis manifest")
    if validation.get("evidence_label") != "descriptive_real_data":
        raise ValueError("NYC full validation must be labeled descriptive_real_data")
    if validation.get("causal_claim") is not False:
        raise ValueError("NYC full validation must declare causal_claim=false")
    if validation.get("validation_passed") is not True:
        raise ValueError("NYC full validation did not pass")
    checks = validation.get("checks")
    if not isinstance(checks, dict) or not checks:
        raise ValueError("NYC full validation checks are missing")
    required_checks = {
        "raw_equals_clean",
        "zone_conserves_clean",
        "od_conserves_clean",
        "calendar_complete",
        "manifest_files_valid",
        "manifest_scope_valid",
        "resource_limit_passed",
    }
    missing_checks = sorted(required_checks.difference(checks))
    if missing_checks:
        raise ValueError(f"NYC full validation checks are incomplete: {missing_checks}")
    invalid_checks = sorted(
        key for key, value in checks.items() if value is not True
    )
    if invalid_checks:
        raise ValueError(
            f"NYC full validation checks did not all pass: {invalid_checks}"
        )

    metadata = manifest.get("metadata")
    if not isinstance(metadata, dict):
        raise ValueError("NYC full analysis manifest metadata is missing")
    if metadata.get("evidence_label") != "descriptive_real_data":
        raise ValueError("NYC full analysis manifest has an incompatible evidence label")
    if metadata.get("causal_claim") is not False:
        raise ValueError("NYC full analysis manifest must declare causal_claim=false")
    if metadata.get("validation_passed") is not True:
        raise ValueError("NYC full analysis manifest does not record a passing validation")

    manifest_root = _manifest_root_for_artifact(
        manifest, validation_file, "NYC full analysis"
    )
    if (validation_file.parent / "NYC_FULL_ANALYSIS_INCOMPLETE.json").exists():
        raise ValueError("NYC full analysis is marked incomplete")
    validated_files = _validate_manifest_files(
        manifest, manifest_root, "NYC full analysis"
    )
    resolved_validation = validation_file.resolve()
    if resolved_validation not in validated_files:
        raise ValueError("NYC full validation is not covered by the analysis manifest")

    provenance = validation.get("provenance")
    if not isinstance(provenance, dict):
        raise ValueError("NYC full validation provenance is missing")
    rendered_data_manifest = _portable_manifest_path(
        provenance.get("data_manifest"), "NYC full validation data_manifest"
    )
    data_manifest_file = (manifest_root / rendered_data_manifest).resolve()
    if (data_manifest_file.parent / "NYC_FULL_INCOMPLETE.json").exists():
        raise ValueError("NYC full source-data pipeline is marked incomplete")
    if data_manifest_file not in validated_files:
        raise ValueError(
            "NYC full source-data manifest is not covered by the analysis manifest"
        )
    expected_data_sha = provenance.get("data_manifest_sha256")
    actual_data_sha = sha256_file(data_manifest_file)
    if (
        not isinstance(expected_data_sha, str)
        or expected_data_sha != actual_data_sha
        or metadata.get("source_data_manifest_sha256") != actual_data_sha
        or validated_files[data_manifest_file].get("sha256") != actual_data_sha
    ):
        raise ValueError("NYC full source-data manifest lineage hashes do not agree")

    data_manifest = _load_json_object(data_manifest_file, "NYC full source-data manifest")
    data_config = data_manifest.get("config")
    data_metadata = data_manifest.get("metadata")
    analysis_config = manifest.get("config")
    scope = validation.get("scope")
    if (
        not isinstance(data_config, dict)
        or not isinstance(data_metadata, dict)
        or not isinstance(analysis_config, dict)
    ):
        raise ValueError("NYC full source-data manifest scope metadata is missing")
    if not isinstance(scope, dict):
        raise ValueError("NYC full validation scope is missing")
    if (
        data_config.get("source") != "nyc_hvfhv"
        or data_config.get("mode") != "full"
        or data_metadata.get("causal_claim") is not False
        or data_metadata.get("evidence_label") != "descriptive_real_data"
        or scope.get("source") != "nyc_hvfhv"
        or scope.get("population_claim") is not False
        or scope.get("unit") != "published_completed_trip_record"
    ):
        raise ValueError("NYC full validation and source-data manifest scopes are incompatible")
    compatibility_keys = (
        "source",
        "mode",
        "nyc_year",
        "nyc_months",
        "nyc_expected_rows",
        "nyc_expected_bytes",
        "nyc_expected_sha256",
        "manifest_path",
    )
    if any(
        analysis_config.get(key) != data_config.get(key)
        for key in compatibility_keys
    ):
        raise ValueError("NYC full analysis and source-data manifests use different configs")
    months = data_config.get("nyc_months")
    year = data_config.get("nyc_year")
    expected_scope_month = (
        f"{year}-{months[0]:02d}"
        if isinstance(year, int)
        and isinstance(months, list)
        and len(months) == 1
        and isinstance(months[0], int)
        else None
    )
    if scope.get("pickup_month") != expected_scope_month:
        raise ValueError("NYC full validation month does not match the source-data manifest")
    configured_manifest = data_config.get("manifest_path")
    if configured_manifest != str(rendered_data_manifest):
        raise ValueError("NYC full validation points to a different configured data manifest")

    coverage = validation.get("coverage")
    conservation = validation.get("conservation")
    resources = validation.get("resources")
    limitations = validation.get("limitations")
    if not isinstance(coverage, dict) or not isinstance(conservation, dict):
        raise ValueError("NYC full validation coverage or conservation facts are missing")
    if not isinstance(resources, dict):
        raise ValueError("NYC full validation resources are missing")
    if (
        not isinstance(limitations, list)
        or not limitations
        or not all(isinstance(item, str) and item.strip() for item in limitations)
    ):
        raise ValueError("NYC full validation limitations are missing")

    raw_rows = _required_int(conservation, "raw_rows", "conservation")
    clean_rows = _required_int(coverage, "clean_rows", "coverage")
    zone_rows = _required_int(conservation, "zone_time_rows", "conservation")
    od_rows = _required_int(conservation, "od_rows", "conservation")
    zone_sum = _required_int(conservation, "zone_trip_sum", "conservation")
    od_sum = _required_int(conservation, "od_trip_sum", "conservation")
    service_dates = _required_int(coverage, "service_dates", "coverage")
    hours = _required_int(coverage, "hours_of_day", "coverage")
    date_hours = _required_int(coverage, "date_hours", "coverage")
    if raw_rows == 0 or not (raw_rows == clean_rows == zone_sum == od_sum):
        raise ValueError("NYC full validation row-conservation facts are inconsistent")
    if service_dates == 0 or hours != 24 or date_hours != service_dates * hours:
        raise ValueError("NYC full validation calendar facts are inconsistent")
    expected_rows = data_config.get("nyc_expected_rows")
    raw_hashes = provenance.get("sha256")
    if expected_rows is not None and expected_rows != raw_rows:
        raise ValueError("NYC full validation row count disagrees with the pinned source")
    if (
        not isinstance(raw_hashes, list)
        or not raw_hashes
        or not all(isinstance(value, str) and len(value) == 64 for value in raw_hashes)
    ):
        raise ValueError("NYC full validation raw-object hashes are missing")
    expected_raw_sha = data_config.get("nyc_expected_sha256")
    if expected_raw_sha is not None and raw_hashes != [expected_raw_sha]:
        raise ValueError("NYC full validation raw-object hash disagrees with the pin")

    elapsed = _required_positive_number(resources, "elapsed_seconds", "resources")
    max_rss = int(_required_positive_number(resources, "max_rss_bytes", "resources"))
    memory_limit = int(
        _required_positive_number(resources, "memory_limit_bytes", "resources")
    )
    if max_rss >= memory_limit:
        raise ValueError("NYC full validation resource facts exceed the declared limit")
    peak_footprint_value = resources.get("peak_memory_footprint_bytes")
    footprint_text = ""
    if peak_footprint_value is not None:
        peak_footprint = int(
            _required_positive_number(
                resources, "peak_memory_footprint_bytes", "resources"
            )
        )
        footprint_text = (
            f", and peak memory footprint {peak_footprint:,} bytes "
            f"({peak_footprint / 1024**3:.2f} GiB)"
        )

    validation_sha = sha256_file(validation_file)
    manifest_sha = sha256_file(manifest_file)
    summary = (
        f"The verified NYC TLC HVFHV full-month bundle covers **{scope['pickup_month']}**: "
        f"{_counted(raw_rows, 'published completed-trip record')}, "
        f"{service_dates} service days × {hours} hours = {date_hours} date-hours, "
        f"{zone_rows:,} complete zone-hour rows, and {od_rows:,} observed OD-hour rows. "
        f"Raw, clean, zone-panel, and OD-panel trip totals all equal {raw_rows:,}. "
        f"The cached-raw end-to-end validation completed in {elapsed:.2f} seconds with "
        f"maximum RSS {max_rss:,} bytes ({max_rss / 1024**3:.2f} GiB)"
        f"{footprint_text}, below the {memory_limit / 1024**3:.0f} GiB envelope. "
        "These are descriptive facts about published completed trips, not a causal "
        "effect, price elasticity, latent-demand estimate, or population claim."
    )
    limitation_text = "\n".join(f"- {item}" for item in limitations)
    provenance_text = "\n".join(
        [
            f"- NYC full validation SHA-256: `{validation_sha}`",
            f"- NYC full analysis manifest SHA-256: `{manifest_sha}`",
            f"- NYC full source-data manifest SHA-256: `{actual_data_sha}`",
            "- NYC pinned raw object SHA-256: "
            + ", ".join(f"`{value}`" for value in raw_hashes),
        ]
    )
    return _NYCFullEvidence(
        summary=summary,
        limitations=limitation_text,
        provenance=provenance_text,
        validation_path=validation_file,
        manifest_path=manifest_file,
        data_manifest_path=data_manifest_file,
    )


@dataclass(frozen=True, slots=True)
class _NYCAnchorEvidence:
    summary: str
    limitations: str
    provenance: str


def _nyc_anchor_status(
    anchor_path: str | Path | None,
    manifest_path: str | Path | None,
) -> _NYCAnchorEvidence | None:
    """Validate the NYC descriptive simulation anchor and its full source hash chain."""

    if anchor_path is None and manifest_path is None:
        return None
    if anchor_path is None or manifest_path is None:
        raise ValueError("NYC simulation anchor requires both anchor and manifest")
    anchor_file = Path(anchor_path)
    manifest_file = Path(manifest_path)
    anchor = _load_json_object(anchor_file, "NYC simulation anchor")
    manifest = _load_json_object(manifest_file, "NYC simulation anchor manifest")
    if (
        anchor.get("schema_version") != "1.0.0"
        or anchor.get("evidence_label") != "semi_synthetic_descriptive_anchor"
        or anchor.get("causal_claim") is not False
        or anchor.get("status")
        != "descriptive_control_path_anchor_validated_not_fitted_structural_model"
    ):
        raise ValueError("NYC simulation anchor has an incompatible evidence contract")
    metadata = manifest.get("metadata")
    if (
        not isinstance(metadata, dict)
        or metadata.get("evidence_label") != "semi_synthetic_descriptive_anchor"
        or metadata.get("causal_claim") is not False
        or metadata.get("status") != anchor.get("status")
    ):
        raise ValueError("NYC simulation anchor manifest metadata is incompatible")
    manifest_root = _manifest_root_for_artifact(
        manifest, anchor_file, "NYC simulation anchor"
    )
    validated = _validate_manifest_files(
        manifest, manifest_root, "NYC simulation anchor"
    )
    if anchor_file.resolve() not in validated:
        raise ValueError("NYC simulation anchor is not covered by its manifest")
    calibration_candidates = [
        path
        for path, entry in validated.items()
        if entry.get("sha256") == metadata.get("calibration_sha256")
    ]
    calibration_manifest_candidates = [
        path
        for path, entry in validated.items()
        if entry.get("sha256") == metadata.get("calibration_manifest_sha256")
    ]
    simulation_config_candidates = [
        path
        for path, entry in validated.items()
        if entry.get("sha256") == metadata.get("simulation_config_sha256")
    ]
    if (
        len(calibration_candidates) != 1
        or len(calibration_manifest_candidates) != 1
        or len(simulation_config_candidates) != 1
    ):
        raise ValueError("NYC simulation anchor manifest has incomplete declared inputs")
    calibration_file = calibration_candidates[0]
    calibration_manifest_file = calibration_manifest_candidates[0]
    simulation_config_file = simulation_config_candidates[0]
    if (
        metadata.get("calibration_sha256") != sha256_file(calibration_file)
        or metadata.get("calibration_manifest_sha256")
        != sha256_file(calibration_manifest_file)
        or metadata.get("simulation_config_sha256")
        != sha256_file(simulation_config_file)
    ):
        raise ValueError("NYC simulation anchor declared input hashes disagree")
    recomputed_integrity = validate_nyc_simulation_anchor_integrity(
        calibration_file,
        project_root=manifest_root,
        manifest_path=calibration_manifest_file,
    )
    integrity = anchor.get("integrity")
    if (
        not isinstance(integrity, dict)
        or integrity != recomputed_integrity
        or integrity.get("all_valid") is not True
        or integrity.get("hashes_recomputed") is not True
        or metadata.get("source_data_manifest_sha256")
        != integrity.get("source_data_manifest_sha256")
    ):
        raise ValueError("NYC simulation anchor integrity is stale or inconsistent")

    control = anchor.get("control_path_scale_validation")
    field_provenance = anchor.get("field_provenance")
    causal_assumptions = anchor.get("causal_parameter_assumptions")
    source_scope = anchor.get("source_scope")
    target_panel = anchor.get("target_panel")
    simulation_config = anchor.get("simulation_config")
    warnings = anchor.get("warnings")
    if not all(
        isinstance(value, dict)
        for value in (
            control,
            field_provenance,
            causal_assumptions,
            source_scope,
            target_panel,
            simulation_config,
        )
    ):
        raise ValueError("NYC simulation anchor is missing required sections")
    assert isinstance(control, dict)
    assert isinstance(field_provenance, dict)
    assert isinstance(causal_assumptions, dict)
    assert isinstance(source_scope, dict)
    assert isinstance(target_panel, dict)
    assert isinstance(simulation_config, dict)
    if (
        control.get("evidence_label") != "semi_synthetic_descriptive_anchor"
        or control.get("causal_claim") is not False
        or control.get("broad_moment_match_passed") is not True
        or field_provenance.get("partition_complete") is not True
        or causal_assumptions.get("status")
        != "explicit_assumptions_not_estimated_from_nyc_trip_records"
        or causal_assumptions.get("calibration_embedded_template_assumptions_used")
        is not False
        or source_scope.get("evidence_label") != "descriptive_real_data"
        or source_scope.get("causal_claim") is not False
        or not isinstance(warnings, list)
        or not warnings
    ):
        raise ValueError("NYC simulation anchor fails the noncausal provenance gate")
    explicit_assumptions = field_provenance.get("explicit_assumptions")
    if not isinstance(explicit_assumptions, dict):
        raise ValueError("NYC simulation anchor explicit assumptions are missing")
    template_config = load_simulation_config(simulation_config_file).to_dict()
    for field in CAUSAL_ASSUMPTION_FIELDS:
        record = explicit_assumptions.get(field)
        if (
            not isinstance(record, dict)
            or field not in simulation_config
            or simulation_config[field] != template_config[field]
            or record.get("value") != simulation_config[field]
            or record.get("evidence_label") != "explicit_assumption"
        ):
            raise ValueError(
                "NYC simulation anchor causal assumptions disagree with the declared template"
            )
    numeric_keys = (
        "target_mean_published_completed_trips_per_zone_hour",
        "achieved_simulated_control_completed_trips",
        "target_mean_nonnegative_request_to_pickup_minutes",
        "achieved_simulated_control_mean_wait_minutes",
        "target_between_zone_variance_share",
        "achieved_between_zone_variance_share",
        "target_between_hour_of_day_variance_share",
        "achieved_between_hour_of_day_variance_share",
        "variance_share_absolute_tolerance",
    )
    numeric = {key: float(control.get(key, np.nan)) for key in numeric_keys}
    if not np.isfinite(list(numeric.values())).all():
        raise ValueError("NYC simulation anchor validation values must be finite")
    tolerance = numeric["variance_share_absolute_tolerance"]
    if (
        tolerance <= 0
        or not np.isclose(
            numeric["target_mean_published_completed_trips_per_zone_hour"],
            numeric["achieved_simulated_control_completed_trips"],
            atol=1e-8,
        )
        or not np.isclose(
            numeric["target_mean_nonnegative_request_to_pickup_minutes"],
            numeric["achieved_simulated_control_mean_wait_minutes"],
            atol=1e-8,
        )
        or abs(
            numeric["target_between_zone_variance_share"]
            - numeric["achieved_between_zone_variance_share"]
        )
        > tolerance
        or abs(
            numeric["target_between_hour_of_day_variance_share"]
            - numeric["achieved_between_hour_of_day_variance_share"]
        )
        > tolerance
    ):
        raise ValueError("NYC simulation anchor broad-moment validation is inconsistent")

    observed = target_panel.get("observed")
    simulation = target_panel.get("simulation")
    scaling = target_panel.get("sample_scaling")
    if not all(isinstance(value, dict) for value in (observed, simulation, scaling)):
        raise ValueError("NYC simulation anchor panel geometry is malformed")
    assert isinstance(observed, dict)
    assert isinstance(simulation, dict)
    assert isinstance(scaling, dict)
    for label, geometry in (("observed", observed), ("simulation", simulation)):
        if any(
            isinstance(geometry.get(key), bool)
            or not isinstance(geometry.get(key), int)
            or int(geometry[key]) < 1
            for key in ("n_zones", "n_periods", "panel_cells")
        ):
            raise ValueError(f"NYC simulation anchor {label} geometry is invalid")
        if geometry["panel_cells"] != geometry["n_zones"] * geometry["n_periods"]:
            raise ValueError(f"NYC simulation anchor {label} geometry does not conserve")
    if scaling.get("selection_performed") is not False:
        raise ValueError("NYC simulation anchor cannot claim an empirical sample selection")

    summary = (
        f"The validated NYC anchor uses {source_scope['published_completed_trips']:,} "
        "published January 2024 completed trips and a complete "
        f"{observed['n_zones']}-zone × {observed['n_periods']}-hour panel to initialize a "
        f"{simulation['n_zones']}-zone × {simulation['n_periods']}-period semi-synthetic "
        "market. Its deterministic control path matches mean completed trips and mean "
        "request-to-pickup time, and matches the descriptive between-zone and hour-of-day "
        f"variance shares within {tolerance:.3f}. Treatment response, supply response, "
        "spillovers, persistence, substitution, and welfare remain explicit assumptions, "
        "not NYC estimates. This is a separate initialization proposal; the default design "
        "benchmark retains its documented offline vertical-slice calibration, so its causal "
        "magnitudes are not NYC effect estimates."
    )
    limitations = "\n".join(f"- {item}" for item in warnings)
    provenance = "\n".join(
        [
            f"- NYC simulation anchor SHA-256: `{sha256_file(anchor_file)}`",
            f"- NYC simulation anchor manifest SHA-256: `{sha256_file(manifest_file)}`",
            f"- NYC calibration SHA-256: `{sha256_file(calibration_file)}`",
            f"- NYC anchor assumption template SHA-256: `{sha256_file(simulation_config_file)}`",
            "- NYC calibration source-data manifest SHA-256: "
            f"`{integrity['source_data_manifest_sha256']}`",
        ]
    )
    return _NYCAnchorEvidence(
        summary=summary,
        limitations=limitations,
        provenance=provenance,
    )


def _recommendation_status(
    benchmark: pd.DataFrame,
    target_estimand: str,
) -> tuple[pd.Series | None, str]:
    try:
        recommendation = choose_recommendation(benchmark, target_estimand)
    except ValueError as exc:
        return None, (
            "No robust design recommendation is issued. "
            f"The generated selection gate reports: {exc}."
        )
    return recommendation, (
        f"Conditional on all declared simulator scenarios, the selection rule chooses "
        f"**{recommendation['design']}** with **{recommendation['estimator']}**. "
        "This is a semi-synthetic design result, not a production-effect forecast."
    )


def _policy_table(policy_path: str | Path | None) -> tuple[str, str]:
    if policy_path is None or not Path(policy_path).is_file():
        return (
            "Policy results were not supplied; no allocation recommendation is issued.",
            "No policy artifact was available.",
        )
    policy = pd.read_csv(policy_path)
    required = {
        "policy",
        "expected_incremental_outcome",
        "incremental_outcome_se",
        "incremental_outcome_p10",
        "budget_spent",
        "budget_efficiency",
        "budget_feasible",
        "evaluation_complete",
        "policy_eligible",
        "decision_instability",
        "training_market_seeds",
        "holdout_market_seeds",
        "training_signal",
        "evaluation_engine",
        "planning_cost_basis",
        "target_estimand",
        "evidence_type",
        "training_markets",
        "holdout_markets",
        "target_population_id",
        "n_zones",
        "n_periods",
        "weighting",
        "simulation_config",
        "policy_config",
    }
    missing = required.difference(policy.columns)
    if missing:
        raise ValueError(f"policy results missing columns: {sorted(missing)}")
    if not policy["evidence_type"].astype(str).str.startswith("semi_synthetic").all():
        raise ValueError("policy rows must be labeled semi-synthetic")
    if not policy["training_signal"].astype(str).str.contains("no structural truth").all():
        raise ValueError("policy artifact does not establish truth-free training")
    if not policy["evaluation_engine"].astype(str).str.contains("simulator rerun").all():
        raise ValueError("policy artifact does not establish full simulator evaluation")
    if not policy["planning_cost_basis"].astype(str).str.contains(
        "no treated holdout"
    ).all():
        raise ValueError("policy artifact uses an unsafe or undocumented holdout cost basis")
    _validate_policy_provenance(policy)
    for column in ("budget_feasible", "evaluation_complete", "policy_eligible"):
        policy[column] = _strict_boolean(policy[column], column)
    columns = [
        column
        for column in (
            "policy",
            "expected_incremental_outcome",
            "incremental_outcome_se",
            "incremental_outcome_p10",
            "incremental_outcome_vs_random",
            "paired_difference_se_vs_random",
            "incremental_welfare",
            "budget_spent",
            "budget_efficiency",
            "mean_model_instability",
            "decision_instability",
            "budget_feasible",
            "evaluation_complete",
            "holdout_markets",
        )
        if column in policy
    ]
    table = markdown_table(
        policy.sort_values("expected_incremental_outcome", ascending=False),
        columns,
    )
    eligible = policy.loc[
        policy["budget_feasible"]
        & policy["evaluation_complete"]
        & policy["policy_eligible"]
        & np.isfinite(policy["expected_incremental_outcome"])
        & np.isfinite(policy["incremental_outcome_p10"])
    ].copy()
    if eligible.empty:
        summary = "No policy passes the budget, holdout-completeness, and stability gates."
    else:
        ordered = eligible.sort_values(
            [
                "incremental_outcome_p10",
                "decision_instability",
                "expected_incremental_outcome",
                "policy",
            ],
            ascending=[False, True, False, True],
        )
        best = ordered.iloc[0]
        unique_winner = True
        if len(ordered) > 1:
            runner_up = ordered.iloc[1]
            p10_margin = float(
                best["incremental_outcome_p10"]
                - runner_up["incremental_outcome_p10"]
            )
            uncertainty_buffer = 1.96 * float(
                np.hypot(
                    best["incremental_outcome_se"],
                    runner_up["incremental_outcome_se"],
                )
            )
            unique_winner = p10_margin > uncertainty_buffer
        if unique_winner:
            summary = (
                "The predeclared conservative policy rule—maximize the holdout "
                "10th-percentile incremental trips, require separation beyond a 1.96-SE "
                "two-policy uncertainty buffer, then minimize decision instability—chooses "
                f"**{best['policy']}**. Its generated mean is "
                f"{float(best['expected_incremental_outcome']):.4f} trips per holdout market "
                f"(SE {float(best['incremental_outcome_se']):.4f}; p10 "
                f"{float(best['incremental_outcome_p10']):.4f}). This is conditional on the "
                "modeled marketplace and fixed budget."
            )
        else:
            summary = (
                "No unique policy winner is issued. The top two holdout p10 values are not "
                "separated by the predeclared 1.96-SE uncertainty buffer, so their ordering "
                "is treated as a tie; prefer the simpler eligible policy or collect more "
                "holdout markets."
            )
    return table, summary


@dataclass(frozen=True, slots=True)
class _TreatmentVersionPolicyEvidence:
    summary: str
    table: str
    provenance: str


def _treatment_version_policy_status(
    summary_path: str | Path | None,
    manifest_path: str | Path | None,
) -> _TreatmentVersionPolicyEvidence | None:
    """Validate paired rider/driver/bundled policy sensitivity evidence."""

    if summary_path is None and manifest_path is None:
        return None
    if summary_path is None or manifest_path is None:
        raise ValueError(
            "treatment-version policy evidence requires both summary and manifest"
        )
    summary_file = Path(summary_path)
    manifest_file = Path(manifest_path)
    if not summary_file.is_file():
        raise FileNotFoundError(f"treatment-version policy summary is required: {summary_file}")
    manifest = _load_json_object(
        manifest_file, "treatment-version policy manifest"
    )
    metadata = manifest.get("metadata")
    expected_versions = {"rider_discount", "driver_incentive", "bundled"}
    pairing_contract = (
        "common training/holdout market seeds across intervention versions"
    )
    if not isinstance(metadata, dict):
        raise ValueError("treatment-version policy manifest metadata is missing")
    declared_versions = metadata.get("treatment_versions")
    if (
        metadata.get("evidence_type")
        != "semi_synthetic_treatment_version_policy_sensitivity"
        or not isinstance(declared_versions, list)
        or not all(isinstance(value, str) for value in declared_versions)
        or set(declared_versions) != expected_versions
        or metadata.get("version_pairing") != pairing_contract
    ):
        raise ValueError("treatment-version policy manifest metadata is incompatible")
    manifest_root = _manifest_root_for_artifact(
        manifest, summary_file, "treatment-version policy"
    )
    validated_files = _validate_manifest_files(
        manifest, manifest_root, "treatment-version policy"
    )
    if summary_file.resolve() not in validated_files:
        raise ValueError(
            "treatment-version policy summary is not covered by its manifest"
        )
    ledger_candidates = [
        path
        for path in validated_files
        if path.name == "treatment_version_policy_market_ledger.csv"
    ]
    if len(ledger_candidates) != 1:
        raise ValueError(
            "treatment-version policy manifest must cover exactly one market ledger"
        )

    policy = pd.read_csv(summary_file)
    required = {
        "policy",
        "treatment_version",
        "version_pairing",
        "version_evidence_scope",
        "expected_incremental_outcome",
        "incremental_outcome_se",
        "incremental_outcome_p10",
        "budget_spent",
        "budget_feasible",
        "evaluation_complete",
        "policy_eligible",
        "training_market_seeds",
        "holdout_market_seeds",
        "training_markets",
        "holdout_markets",
        "target_estimand",
        "target_population_id",
        "n_zones",
        "n_periods",
        "weighting",
        "simulation_config",
        "policy_config",
        "evidence_type",
    }
    missing = required.difference(policy.columns)
    if missing or policy.empty:
        raise ValueError(
            f"treatment-version policy summary missing columns: {sorted(missing)}"
        )
    if set(policy["treatment_version"].astype(str)) != expected_versions:
        raise ValueError("treatment-version policy summary has incomplete versions")
    if not policy["evidence_type"].eq("semi_synthetic_policy_holdout").all():
        raise ValueError("treatment-version policy rows have an incompatible evidence type")
    if not policy["version_pairing"].eq(pairing_contract).all():
        raise ValueError("treatment-version policy rows do not establish paired seeds")
    if not policy["version_evidence_scope"].astype(str).str.contains(
        "not an empirical dose response", regex=False
    ).all():
        raise ValueError("treatment-version policy evidence scope is unsafe")
    for column in ("budget_feasible", "evaluation_complete", "policy_eligible"):
        policy[column] = _strict_boolean(policy[column], column)
    numeric_columns = [
        "expected_incremental_outcome",
        "incremental_outcome_se",
        "incremental_outcome_p10",
        "budget_spent",
    ]
    numeric_values = policy[numeric_columns].apply(pd.to_numeric, errors="coerce")
    if not np.isfinite(numeric_values.to_numpy(dtype=float)).all():
        raise ValueError("treatment-version policy summary has non-finite decision values")

    common_training_seeds: set[int] | None = None
    common_holdout_seeds: set[int] | None = None
    for version, group in policy.groupby("treatment_version", sort=True):
        training_seeds, holdout_seeds = _validate_policy_provenance(group)
        try:
            configs = [json.loads(value) for value in group["simulation_config"]]
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError(
                "treatment-version policy simulation config is malformed"
            ) from exc
        if any(
            not isinstance(config, dict)
            or config.get("treatment_version") != version
            for config in configs
        ):
            raise ValueError(
                "treatment-version policy rows disagree with their simulation configs"
            )
        if common_training_seeds is None:
            common_training_seeds = training_seeds
            common_holdout_seeds = holdout_seeds
        elif (
            training_seeds != common_training_seeds
            or holdout_seeds != common_holdout_seeds
        ):
            raise ValueError(
                "treatment-version policy versions do not share market seeds"
            )
    assert common_training_seeds is not None
    assert common_holdout_seeds is not None
    if (
        metadata.get("training_markets") not in (None, len(common_training_seeds))
        or metadata.get("holdout_markets") not in (None, len(common_holdout_seeds))
    ):
        raise ValueError(
            "treatment-version policy manifest market counts disagree with the summary"
        )

    ledger = pd.read_csv(ledger_candidates[0])
    ledger_required = {
        "policy",
        "treatment_version",
        "version_pairing",
        "holdout_market_seed",
        "evidence_type",
    }
    missing_ledger = ledger_required.difference(ledger.columns)
    if missing_ledger or ledger.empty:
        raise ValueError(
            f"treatment-version policy ledger missing columns: {sorted(missing_ledger)}"
        )
    if (
        set(ledger["treatment_version"].astype(str)) != expected_versions
        or not ledger["version_pairing"].eq(pairing_contract).all()
        or not ledger["evidence_type"].eq(
            "semi_synthetic_policy_holdout_market"
        ).all()
    ):
        raise ValueError("treatment-version policy ledger has incompatible scope")
    expected_policies = set(policy["policy"].astype(str))
    for _keys, group in ledger.groupby(
        ["treatment_version", "policy"], sort=True
    ):
        if (
            set(group["holdout_market_seed"].astype(int)) != common_holdout_seeds
            or len(group) != len(common_holdout_seeds)
        ):
            raise ValueError(
                "treatment-version policy ledger has incomplete holdout pairing"
            )
    if set(ledger["policy"].astype(str)) != expected_policies:
        raise ValueError("treatment-version policy ledger has incomplete policies")

    display = policy.sort_values(["treatment_version", "policy"])
    table = markdown_table(
        display,
        [
            "treatment_version",
            "policy",
            "expected_incremental_outcome",
            "incremental_outcome_se",
            "incremental_outcome_p10",
            "budget_spent",
            "budget_feasible",
            "evaluation_complete",
            "policy_eligible",
        ],
    )
    summary = (
        f"A separate paired sensitivity evaluates "
        f"{_counted(len(expected_policies), 'policy', 'policies')} "
        "under rider-discount, driver-incentive, and bundled simulator response functions. "
        f"Every version reuses the same {len(common_training_seeds)} training and "
        f"{len(common_holdout_seeds)} holdout market seeds, while fitting its own learner. "
        "The table is a semi-synthetic response-function sensitivity—not an empirical "
        "dose response, treatment comparison, or live-market ROI estimate—and it does not "
        "replace the primary bundled-policy decision gate."
    )
    provenance = "\n".join(
        [
            f"- Treatment-version policy summary SHA-256: `{sha256_file(summary_file)}`",
            f"- Treatment-version policy manifest SHA-256: `{sha256_file(manifest_file)}`",
            f"- Treatment-version policy ledger SHA-256: `{sha256_file(ledger_candidates[0])}`",
        ]
    )
    return _TreatmentVersionPolicyEvidence(
        summary=summary,
        table=table,
        provenance=provenance,
    )


@dataclass(frozen=True, slots=True)
class _InterferenceEvidence:
    summary: str
    table: str
    provenance: str


def _interference_status(
    summary_path: str | Path | None,
    manifest_path: str | Path | None,
) -> _InterferenceEvidence | None:
    """Validate the known-truth mapped-exposure benchmark fail closed."""

    if summary_path is None and manifest_path is None:
        return None
    if summary_path is None or manifest_path is None:
        raise ValueError("interference evidence requires both summary and manifest")
    summary_file = Path(summary_path)
    manifest_file = Path(manifest_path)
    manifest = _load_json_object(manifest_file, "interference benchmark manifest")
    metadata = manifest.get("metadata")
    if (
        not isinstance(metadata, dict)
        or metadata.get("evidence_type")
        != "semi_synthetic_exposure_mapped_known_truth_benchmark"
        or metadata.get("controlled_exposure_not_market_total") is not True
        or not isinstance(metadata.get("benchmark_config"), dict)
        or not isinstance(metadata.get("known_estimands"), dict)
    ):
        raise ValueError("interference benchmark manifest metadata is incompatible")
    manifest_root = _manifest_root_for_artifact(
        manifest, summary_file, "interference benchmark"
    )
    validated = _validate_manifest_files(
        manifest, manifest_root, "interference benchmark"
    )
    if summary_file.resolve() not in validated:
        raise ValueError("interference summary is not covered by its manifest")
    expected_names = {
        "interference_records.csv",
        "interference_summary.csv",
        "interference_failures.csv",
        "interference_fit_ledger.csv",
        "interference_metadata.json",
    }
    by_name = {path.name: path for path in validated}
    if set(by_name) != expected_names:
        raise ValueError("interference manifest has an unexpected file set")

    config = metadata["benchmark_config"]
    replications = config.get("replications")
    if isinstance(replications, bool) or not isinstance(replications, int) or replications < 2:
        raise ValueError("interference benchmark replication count is invalid")
    benchmark_metadata = _load_json_object(
        by_name["interference_metadata.json"], "interference benchmark metadata"
    )
    if (
        benchmark_metadata.get("evidence_type")
        != "semi_synthetic_exposure_mapped_known_truth_benchmark"
        or benchmark_metadata.get("config") != config
        or benchmark_metadata.get("known_estimands") != metadata["known_estimands"]
    ):
        raise ValueError("interference benchmark metadata and manifest disagree")

    summary_frame = pd.read_csv(summary_file)
    required = {
        "estimator",
        "target_estimand",
        "truth",
        "mean_estimate",
        "bias",
        "rmse",
        "coverage",
        "power",
        "identified",
        "inference_valid_for_target",
        "fit_complete",
        "decision_eligible",
        "successful_fits",
        "comparison_status",
        "evidence_type",
        "diagnostic_mean_gap_to_market_total",
    }
    missing = required.difference(summary_frame.columns)
    if missing or summary_frame.empty:
        raise ValueError(f"interference summary missing columns: {sorted(missing)}")
    for column in (
        "identified",
        "inference_valid_for_target",
        "fit_complete",
        "decision_eligible",
    ):
        summary_frame[column] = _strict_boolean(summary_frame[column], column)
    mapped_targets = {
        "controlled_zone_direct_effect",
        "spillover_effect",
        "controlled_history_exposure_response",
    }
    mapped = summary_frame.loc[summary_frame["target_estimand"].isin(mapped_targets)].copy()
    naive = summary_frame.loc[
        summary_frame["estimator"].eq("naive_assignment_cluster_regression")
    ].copy()
    if set(mapped["target_estimand"]) != mapped_targets or len(mapped) != 3 or len(naive) != 1:
        raise ValueError("interference summary has incomplete controlled or naive targets")
    mapped_numeric = mapped[
        ["truth", "mean_estimate", "bias", "rmse", "coverage", "power"]
    ].apply(pd.to_numeric, errors="coerce")
    if not np.isfinite(mapped_numeric.to_numpy(dtype=float)).all():
        raise ValueError("interference mapped recovery metrics must be finite")
    if not (
        mapped["identified"].all()
        and mapped["inference_valid_for_target"].all()
        and mapped["fit_complete"].all()
        and mapped["decision_eligible"].all()
        and mapped["successful_fits"].eq(replications).all()
        and mapped["evidence_type"].eq(
            "semi_synthetic_exposure_mapped_known_truth_monte_carlo"
        ).all()
        and mapped["coverage"].between(0.0, 1.0).all()
        and mapped["power"].between(0.0, 1.0).all()
    ):
        raise ValueError("interference mapped recovery rows fail the evidence gate")
    known_estimands = metadata["known_estimands"]
    for row in mapped.itertuples(index=False):
        expected = known_estimands.get(row.target_estimand)
        if not isinstance(expected, (int, float)) or not np.isclose(row.truth, expected):
            raise ValueError("interference summary truth disagrees with metadata")
    withheld = naive[["bias", "rmse", "coverage", "power"]].apply(
        pd.to_numeric, errors="coerce"
    )
    diagnostic = pd.to_numeric(
        naive["diagnostic_mean_gap_to_market_total"], errors="coerce"
    )
    if (
        bool(naive["identified"].iloc[0])
        or bool(naive["decision_eligible"].iloc[0])
        or not withheld.isna().all().all()
        or not np.isfinite(diagnostic.to_numpy(dtype=float)).all()
        or naive["comparison_status"].iloc[0] != "target_mismatch"
    ):
        raise ValueError("interference naive target-mismatch row is unsafe")

    ledger = pd.read_csv(by_name["interference_fit_ledger.csv"])
    if len(ledger) != 4:
        raise ValueError("interference fit ledger must contain four declared targets")
    for column in ("identified", "fit_complete", "decision_eligible"):
        ledger[column] = _strict_boolean(ledger[column], column)
    if (
        not ledger["fit_complete"].all()
        or not ledger["successful_fits"].eq(replications).all()
        or int(ledger["failed_fits"].sum()) != 0
        or int(ledger["attempted_fits"].sum()) != replications * 4
    ):
        raise ValueError("interference fit ledger is incomplete")
    records = pd.read_csv(by_name["interference_records.csv"])
    if len(records) != replications * 4:
        raise ValueError("interference records do not match the declared fit plan")
    failures = pd.read_csv(by_name["interference_failures.csv"])
    if not failures.empty:
        raise ValueError("interference benchmark contains failed fits")

    table = markdown_table(
        summary_frame.sort_values(["identified", "target_estimand"], ascending=[False, True]),
        [
            "estimator",
            "target_estimand",
            "truth",
            "mean_estimate",
            "bias",
            "rmse",
            "coverage",
            "power",
            "identified",
            "inference_valid_for_target",
            "decision_eligible",
            "diagnostic_mean_gap_to_market_total",
        ],
    )
    naive_gap = float(diagnostic.iloc[0])
    summary = (
        f"A separate {replications}-replication known-truth benchmark uses "
        "two-stage geographic saturation, a predeclared neighbor map, and exact treatment "
        "history. The mapped cluster regression reports controlled own, neighbor, and "
        "history effects with target-aligned bias, RMSE, coverage, and power. The naive "
        f"saturation coefficient differs from the full-policy truth by {naive_gap:.4f}; "
        "because that coefficient omits mapped exposures, its market-total bias, RMSE, "
        "coverage, and power are deliberately withheld."
    )
    provenance = "\n".join(
        [
            f"- Interference summary SHA-256: `{sha256_file(summary_file)}`",
            f"- Interference manifest SHA-256: `{sha256_file(manifest_file)}`",
            f"- Interference records SHA-256: `{sha256_file(by_name['interference_records.csv'])}`",
            f"- Interference fit ledger SHA-256: `{sha256_file(by_name['interference_fit_ledger.csv'])}`",
        ]
    )
    return _InterferenceEvidence(summary=summary, table=table, provenance=provenance)


@dataclass(frozen=True, slots=True)
class _NYCInformedBenchmarkEvidence:
    summary: str
    table: str
    limitations: str
    provenance: str


def _nyc_informed_benchmark_status(
    manifest_path: str | Path | None,
) -> _NYCInformedBenchmarkEvidence | None:
    """Validate the NYC-informed known-truth benchmark and its anchor lineage."""

    bundle = _manifest_bundle(manifest_path, "NYC-informed benchmark")
    if bundle is None:
        return None
    _require_manifest_evidence(
        bundle, NYC_BENCHMARK_EVIDENCE_TYPE, "NYC-informed benchmark"
    )
    if (
        bundle.payload.get("evidence_type") != NYC_BENCHMARK_EVIDENCE_TYPE
        or bundle.payload.get("causal_claim") is not False
        or bundle.payload.get("causal_claim_from_nyc_data") is not False
        or bundle.payload.get("simulator_known_truth") is not True
        or bundle.payload.get("bundle_valid") is not True
        or bundle.payload.get("portable_paths") is not True
    ):
        raise ValueError("NYC-informed benchmark manifest metadata is incompatible")
    metadata_path, metadata = _unique_json_object(
        bundle,
        lambda value: value.get("evidence_type") == NYC_BENCHMARK_EVIDENCE_TYPE
        and "target_gates" in value,
        "NYC-informed benchmark metadata",
    )
    if (
        metadata.get("schema_version") != NYC_BENCHMARK_SCHEMA_VERSION
        or metadata.get("nyc_empirical_causal_effect") is not False
        or metadata.get("simulator_known_truth") is not True
        or metadata.get("known_truth_estimand") != "market_total_effect"
        or "not an NYC causal estimate" not in str(metadata.get("known_truth_scope", ""))
    ):
        raise ValueError("NYC-informed benchmark metadata has an unsafe evidence contract")
    limitations = _required_string_list(
        metadata.get("limitations"), "NYC-informed benchmark limitations"
    )
    gates = metadata.get("target_gates")
    if (
        not isinstance(gates, dict)
        or not gates
        or gates.get("all_passed") is not True
        or any(value is not True for value in gates.values())
    ):
        raise ValueError("NYC-informed benchmark target gates did not all pass")
    config = metadata.get("benchmark_config")
    if not isinstance(config, dict):
        raise ValueError("NYC-informed benchmark configuration is missing")
    replications = config.get("replications")
    if isinstance(replications, bool) or not isinstance(replications, int) or replications < 2:
        raise ValueError("NYC-informed benchmark replication count is invalid")
    scenarios = metadata.get("scenario_causal_provenance")
    if not isinstance(scenarios, dict) or not scenarios:
        raise ValueError("NYC-informed benchmark scenario provenance is missing")
    for value in scenarios.values():
        if (
            not isinstance(value, dict)
            or not isinstance(value.get("causal_overrides"), dict)
            or "none is an NYC causal estimate"
            not in str(value.get("interpretation", ""))
        ):
            raise ValueError("NYC-informed benchmark scenario provenance is unsafe")

    anchor = metadata.get("anchor")
    hashes = anchor.get("hashes") if isinstance(anchor, dict) else None
    if (
        not isinstance(anchor, dict)
        or anchor.get("evidence_label") != "semi_synthetic_descriptive_anchor"
        or anchor.get("exact_reconstruction_passed") is not True
        or not isinstance(hashes, dict)
    ):
        raise ValueError("NYC-informed benchmark anchor provenance is incomplete")
    anchor_file = _file_with_declared_hash(
        bundle, hashes.get("anchor_sha256"), "NYC-informed benchmark anchor hash"
    )
    anchor_manifest_file = _file_with_declared_hash(
        bundle,
        hashes.get("anchor_manifest_sha256"),
        "NYC-informed benchmark anchor-manifest hash",
    )
    _nyc_anchor_status(anchor_file, anchor_manifest_file)

    summary_path, summary = _unique_csv(
        bundle,
        {
            "scenario",
            "design",
            "estimator",
            "target_estimand",
            "mean_estimate",
            "bias",
            "rmse",
            "coverage",
            "power",
            "fit_complete",
            "inference_valid",
            "nyc_empirical_causal_effect",
            "simulator_known_truth",
            "target_gate_all_passed",
        },
        "NYC-informed benchmark summary",
    )
    records_path, records = _unique_csv(
        bundle,
        {
            "scenario",
            "design",
            "estimator",
            "replication",
            "estimate",
            "std_error",
            "truth",
            "nyc_empirical_causal_effect",
            "simulator_known_truth",
            "target_gate_all_passed",
        },
        "NYC-informed benchmark records",
    )
    ledger_path, ledger = _unique_csv(
        bundle,
        {
            "scenario",
            "design",
            "estimator",
            "attempted_fits",
            "successful_fits",
            "failed_fits",
            "fit_complete",
            "applicable",
            "nyc_empirical_causal_effect",
            "target_gate_all_passed",
        },
        "NYC-informed benchmark fit ledger",
        excluded_columns={"mean_estimate"},
    )
    selected_paths = {summary_path, records_path, ledger_path}
    failure_candidates = [
        path
        for path in bundle.files
        if path.suffix.lower() == ".csv"
        and path not in selected_paths
        and {
            "evidence_type",
            "nyc_empirical_causal_effect",
            "target_gate_all_passed",
        }.issubset(_csv_header(path, "NYC-informed benchmark failures"))
    ]
    if len(failure_candidates) != 1:
        raise ValueError(
            "NYC-informed benchmark manifest must identify exactly one failures CSV"
        )
    failures_path = failure_candidates[0]
    failures = pd.read_csv(failures_path)
    if summary.empty or records.empty or ledger.empty or not failures.empty:
        raise ValueError("NYC-informed benchmark outputs are incomplete or contain failures")

    for frame_label, frame in (
        ("summary", summary),
        ("records", records),
        ("fit ledger", ledger),
    ):
        if not frame["evidence_type"].eq(NYC_BENCHMARK_EVIDENCE_TYPE).all():
            raise ValueError(f"NYC-informed benchmark {frame_label} evidence label is invalid")
        for column, expected in (
            ("nyc_empirical_causal_effect", False),
            ("simulator_known_truth", True),
            ("target_gate_all_passed", True),
        ):
            values = _strict_boolean(frame[column], column)
            if not values.eq(expected).all():
                raise ValueError(
                    f"NYC-informed benchmark {frame_label} violates {column}"
                )
        if not frame["target_estimand"].eq("market_total_effect").all():
            raise ValueError("NYC-informed benchmark target estimand changed")
        for key, digest in hashes.items():
            column = f"nyc_{key}"
            if column not in frame or not frame[column].eq(digest).all():
                raise ValueError("NYC-informed benchmark anchor hashes disagree")

    declared_sets = summary["declared_scenario_set"].dropna().astype(str).unique()
    if len(declared_sets) != 1:
        raise ValueError("NYC-informed benchmark declared scenario set is inconsistent")
    try:
        declared_scenarios = json.loads(declared_sets[0])
    except json.JSONDecodeError as exc:
        raise ValueError("NYC-informed benchmark scenario declaration is malformed") from exc
    if (
        not isinstance(declared_scenarios, list)
        or set(declared_scenarios) != set(scenarios)
        or set(summary["scenario"].astype(str)) != set(scenarios)
    ):
        raise ValueError("NYC-informed benchmark scenario coverage is incomplete")
    if not pd.to_numeric(summary["replications"], errors="coerce").eq(replications).all():
        raise ValueError("NYC-informed benchmark summary replication counts disagree")

    for column in ("identified", "inference_valid", "fit_complete", "applicable"):
        summary[column] = _strict_boolean(summary[column], column)
    identified = summary["identified"]
    valid = identified & summary["inference_valid"]
    if not valid.any() or not summary.loc[summary["applicable"], "fit_complete"].all():
        raise ValueError("NYC-informed benchmark has no complete identified target cell")
    identified_metrics = summary.loc[identified, ["truth", "bias", "rmse"]].apply(
        pd.to_numeric, errors="coerce"
    )
    valid_inference = summary.loc[valid, ["coverage", "power"]].apply(
        pd.to_numeric, errors="coerce"
    )
    if (
        not np.isfinite(identified_metrics.to_numpy(dtype=float)).all()
        or not np.isfinite(valid_inference.to_numpy(dtype=float)).all()
        or not ((valid_inference >= 0.0) & (valid_inference <= 1.0)).all().all()
        or not summary.loc[
            ~identified, ["bias", "rmse", "coverage", "power"]
        ].isna().all().all()
    ):
        raise ValueError("NYC-informed benchmark recovery metrics violate target alignment")
    if not np.isfinite(pd.to_numeric(records["truth"], errors="coerce")).all():
        raise ValueError("NYC-informed benchmark record truth is non-finite")
    for column in ("fit_complete", "applicable"):
        ledger[column] = _strict_boolean(ledger[column], column)
    applicable_ledger = ledger.loc[ledger["applicable"]]
    if (
        not applicable_ledger["fit_complete"].all()
        or not pd.to_numeric(
            applicable_ledger["attempted_fits"], errors="coerce"
        ).eq(replications).all()
        or not pd.to_numeric(
            applicable_ledger["successful_fits"], errors="coerce"
        ).eq(replications).all()
        or pd.to_numeric(ledger["failed_fits"], errors="coerce").sum() != 0
        or len(records) != int(pd.to_numeric(summary["successful_fits"]).sum())
    ):
        raise ValueError("NYC-informed benchmark fit plan is incomplete")

    table = markdown_table(
        summary.sort_values(["scenario", "design", "estimator"]),
        [
            "scenario",
            "design",
            "estimator",
            "spillover_strength",
            "persistence",
            "truth",
            "mean_estimate",
            "bias",
            "rmse",
            "coverage",
            "power",
            "identified",
            "inference_valid",
            "fit_complete",
        ],
    )
    summary_text = (
        f"The validated NYC-informed benchmark uses the descriptive NYC anchor to set "
        f"scale and heterogeneity for {config.get('n_zones')} zones × "
        f"{config.get('n_periods')} periods. It evaluates "
        f"{_counted(len(scenarios), 'predeclared scenario')} with {replications} Monte "
        f"Carlo replications; {int(valid.sum())} summary cells pass both identification "
        "and inference gates. Every reported truth is a structural simulator "
        "counterfactual under explicit assumptions—not a treatment effect estimated "
        "from NYC trips."
    )
    provenance = "\n".join(
        [
            f"- NYC-informed benchmark manifest SHA-256: `{sha256_file(bundle.path)}`",
            f"- NYC-informed benchmark metadata SHA-256: `{sha256_file(metadata_path)}`",
            f"- NYC-informed benchmark summary SHA-256: `{sha256_file(summary_path)}`",
            f"- NYC-informed benchmark records SHA-256: `{sha256_file(records_path)}`",
            f"- NYC-informed benchmark fit ledger SHA-256: `{sha256_file(ledger_path)}`",
            f"- NYC-informed benchmark failures SHA-256: `{sha256_file(failures_path)}`",
            f"- Revalidated NYC anchor SHA-256: `{hashes['anchor_sha256']}`",
            f"- Revalidated NYC anchor manifest SHA-256: `{hashes['anchor_manifest_sha256']}`",
        ]
    )
    return _NYCInformedBenchmarkEvidence(
        summary=summary_text,
        table=table,
        limitations="\n".join(f"- {item}" for item in limitations),
        provenance=provenance,
    )


@dataclass(frozen=True, slots=True)
class _NYCGraphEvidence:
    summary: str
    table: str
    limitations: str
    provenance: str


def _nyc_graph_status(
    manifest_path: str | Path | None,
) -> _NYCGraphEvidence | None:
    """Validate mapped known-truth recovery on the descriptive NYC OD graph."""

    bundle = _manifest_bundle(manifest_path, "NYC graph benchmark")
    if bundle is None:
        return None
    _require_manifest_evidence(bundle, NYC_GRAPH_EVIDENCE_TYPE, "NYC graph benchmark")
    if (
        bundle.payload.get("evidence_type") != NYC_GRAPH_EVIDENCE_TYPE
        or bundle.payload.get("causal_claim") is not False
        or bundle.payload.get("causal_claim_from_nyc_data") is not False
        or bundle.payload.get("input_graph_evidence_label") != "descriptive_real_data"
        or bundle.payload.get("bundle_valid") is not True
        or bundle.payload.get("portable_paths") is not True
    ):
        raise ValueError("NYC graph benchmark manifest metadata is incompatible")
    metadata_path, metadata = _unique_json_object(
        bundle,
        lambda value: value.get("evidence_type") == NYC_GRAPH_EVIDENCE_TYPE
        and "calibration_bundle" in value,
        "NYC graph benchmark metadata",
    )
    if (
        metadata.get("causal_claim_from_nyc_data") is not False
        or metadata.get("input_graph_evidence_label") != "descriptive_real_data"
        or "not spillover strength" not in str(metadata.get("graph_weight_role", ""))
        or "target mismatch" not in str(metadata.get("naive_assignment_status", ""))
    ):
        raise ValueError("NYC graph benchmark metadata has an unsafe evidence contract")
    config = metadata.get("config")
    truths = metadata.get("known_estimands")
    calibration = metadata.get("calibration_bundle")
    subset = metadata.get("zone_subset")
    if not all(isinstance(value, dict) for value in (config, truths, calibration, subset)):
        raise ValueError("NYC graph benchmark metadata is incomplete")
    replications = config.get("replications")
    if isinstance(replications, bool) or not isinstance(replications, int) or replications < 2:
        raise ValueError("NYC graph benchmark replication count is invalid")
    if (
        subset.get("selection_uses_only_pre_treatment_graph_fields") is not True
        or subset.get("selected_zone_count") != config.get("n_zones")
        or not isinstance(subset.get("selected_zone_ids_in_order"), list)
        or len(subset["selected_zone_ids_in_order"]) != config.get("n_zones")
        or not _valid_sha256(subset.get("subset_raw_mapping_sha256"))
    ):
        raise ValueError("NYC graph benchmark zone selection provenance is invalid")
    attestation = calibration.get("manifest_source_data_attestation")
    if (
        not isinstance(attestation, dict)
        or attestation.get("all_valid") is not True
        or attestation.get("hashes_recomputed") is not True
        or attestation.get("queried_files_listed") is not True
        or attestation.get("scope_is_full_nyc_descriptive") is not True
        or attestation.get("mismatches") != []
        or not _valid_sha256(attestation.get("sha256"))
    ):
        raise ValueError("NYC graph benchmark source-data attestation is invalid")
    calibration_manifest_path = _file_with_declared_hash(
        bundle,
        calibration.get("manifest_sha256"),
        "NYC graph calibration-manifest hash",
    )
    mapping_path = _file_with_declared_hash(
        bundle,
        calibration.get("exposure_mapping_sha256"),
        "NYC graph exposure-mapping hash",
    )
    validated_graph = validate_nyc_graph_bundle(calibration_manifest_path.parent)
    if (
        validated_graph.manifest_sha256 != calibration.get("manifest_sha256")
        or validated_graph.mapping_sha256 != calibration.get("exposure_mapping_sha256")
        or validated_graph.mapping_sha256 != sha256_file(mapping_path)
        or dict(validated_graph.manifest["source_data_manifest"]) != dict(attestation)
    ):
        raise ValueError("NYC graph benchmark calibration lineage disagrees")

    summary_path, summary = _unique_csv(
        bundle,
        {
            "estimator",
            "target_estimand",
            "truth",
            "mean_estimate",
            "bias",
            "rmse",
            "coverage",
            "power",
            "identified",
            "inference_valid_for_target",
            "fit_complete",
            "decision_eligible",
            "comparison_status",
            "diagnostic_mean_gap_to_market_total",
            "evidence_type",
        },
        "NYC graph benchmark summary",
    )
    records_path, records = _unique_csv(
        bundle,
        {
            "replication",
            "estimator",
            "target_estimand",
            "estimate",
            "truth",
            "identified",
            "comparison_status",
            "inference_valid_for_target",
            "input_graph_evidence_label",
            "evidence_type",
        },
        "NYC graph benchmark records",
        excluded_columns={"mean_estimate"},
    )
    ledger_path, ledger = _unique_csv(
        bundle,
        {
            "estimator",
            "target_estimand",
            "identified",
            "attempted_fits",
            "successful_fits",
            "failed_fits",
            "fit_complete",
            "decision_eligible",
            "evidence_type",
        },
        "NYC graph benchmark fit ledger",
        excluded_columns={"estimate", "mean_estimate"},
    )
    failures_path, failures = _unique_csv(
        bundle,
        {
            "replication",
            "assignment_seed",
            "outcome_seed",
            "estimator",
            "target_estimand",
            "stage",
            "error",
        },
        "NYC graph benchmark failures",
        excluded_columns={"estimate"},
    )
    if summary.empty or records.empty or ledger.empty or not failures.empty:
        raise ValueError("NYC graph benchmark outputs are incomplete or contain failures")
    if len(summary) != 4 or len(ledger) != 4 or len(records) != replications * 4:
        raise ValueError("NYC graph benchmark does not match its declared fit plan")
    for column in (
        "identified",
        "inference_valid_for_target",
        "fit_complete",
        "decision_eligible",
    ):
        summary[column] = _strict_boolean(summary[column], column)
    for column in ("identified", "fit_complete", "decision_eligible"):
        ledger[column] = _strict_boolean(ledger[column], column)
    mapped_targets = {
        "controlled_zone_direct_effect",
        "spillover_effect",
        "controlled_history_exposure_response",
    }
    mapped = summary.loc[summary["target_estimand"].isin(mapped_targets)].copy()
    naive = summary.loc[
        summary["estimator"].eq("nyc_graph_naive_assignment_cluster_regression")
    ].copy()
    if set(mapped["target_estimand"]) != mapped_targets or len(mapped) != 3 or len(naive) != 1:
        raise ValueError("NYC graph benchmark controlled and naive targets are incomplete")
    mapped_metrics = mapped[
        ["truth", "mean_estimate", "bias", "rmse", "coverage", "power"]
    ].apply(pd.to_numeric, errors="coerce")
    if (
        not np.isfinite(mapped_metrics.to_numpy(dtype=float)).all()
        or not ((mapped_metrics[["coverage", "power"]] >= 0.0) & (
            mapped_metrics[["coverage", "power"]] <= 1.0
        )).all().all()
        or not mapped["identified"].all()
        or not mapped["inference_valid_for_target"].all()
        or not mapped["fit_complete"].all()
        or not mapped["decision_eligible"].all()
        or not mapped["successful_fits"].eq(replications).all()
        or not mapped["evidence_type"].eq(
            "semi_synthetic_nyc_graph_known_truth_monte_carlo"
        ).all()
    ):
        raise ValueError("NYC graph benchmark mapped recovery rows fail the evidence gate")
    for row in mapped.itertuples(index=False):
        expected = truths.get(row.target_estimand)
        if not isinstance(expected, (int, float)) or not np.isclose(row.truth, expected):
            raise ValueError("NYC graph benchmark truth disagrees with metadata")
    withheld = naive[["bias", "rmse", "coverage", "power"]].apply(
        pd.to_numeric, errors="coerce"
    )
    diagnostic = pd.to_numeric(
        naive["diagnostic_mean_gap_to_market_total"], errors="coerce"
    )
    if (
        bool(naive["identified"].iloc[0])
        or bool(naive["decision_eligible"].iloc[0])
        or naive["comparison_status"].iloc[0] != "target_mismatch"
        or naive["evidence_type"].iloc[0]
        != "semi_synthetic_nyc_graph_target_mismatch_diagnostic"
        or not withheld.isna().all().all()
        or not np.isfinite(diagnostic.to_numpy(dtype=float)).all()
    ):
        raise ValueError("NYC graph naive target-mismatch metrics were not safely withheld")
    if (
        not ledger["fit_complete"].all()
        or int(pd.to_numeric(ledger["failed_fits"], errors="coerce").sum()) != 0
        or not pd.to_numeric(ledger["attempted_fits"], errors="coerce").eq(
            replications
        ).all()
        or not pd.to_numeric(ledger["successful_fits"], errors="coerce").eq(
            replications
        ).all()
    ):
        raise ValueError("NYC graph benchmark fit ledger is incomplete")
    mapped_records = records.loc[
        records["estimator"].eq("nyc_graph_exposure_mapped_cluster_regression")
    ]
    naive_records = records.loc[
        records["estimator"].eq("nyc_graph_naive_assignment_cluster_regression")
    ]
    if (
        len(mapped_records) != replications * 3
        or len(naive_records) != replications
        or not mapped_records["evidence_type"].eq(NYC_GRAPH_EVIDENCE_TYPE).all()
        or not naive_records["evidence_type"].eq(
            "semi_synthetic_nyc_graph_target_mismatch_diagnostic"
        ).all()
        or not records["input_graph_evidence_label"].eq("descriptive_real_data").all()
    ):
        raise ValueError("NYC graph benchmark record evidence labels are incompatible")

    table = markdown_table(
        summary.sort_values(["identified", "target_estimand"], ascending=[False, True]),
        [
            "estimator",
            "target_estimand",
            "truth",
            "mean_estimate",
            "bias",
            "rmse",
            "coverage",
            "power",
            "identified",
            "inference_valid_for_target",
            "decision_eligible",
            "diagnostic_mean_gap_to_market_total",
        ],
    )
    gap = float(diagnostic.iloc[0])
    summary_text = (
        f"A {replications}-replication known-truth benchmark applies two-stage saturation "
        f"to {config.get('n_zones')} zones selected solely from the pre-treatment NYC "
        "completed-trip OD graph. It separately recovers controlled own, mapped-neighbor, "
        "and exact-history responses. The naive saturation coefficient differs from the "
        f"declared market-total truth by {gap:.4f}; its market-total bias, RMSE, coverage, "
        "and power are therefore withheld. NYC OD weights define exposure geometry only—"
        "they are not estimated spillover strength or a causal effect."
    )
    limitations = [
        str(metadata.get("graph_weight_role")),
        str(metadata.get("market_total_bridge")),
        "Known response coefficients are declared by the benchmark DGP and are not learned from NYC trips.",
    ]
    provenance = "\n".join(
        [
            f"- NYC graph benchmark manifest SHA-256: `{sha256_file(bundle.path)}`",
            f"- NYC graph benchmark metadata SHA-256: `{sha256_file(metadata_path)}`",
            f"- NYC graph benchmark summary SHA-256: `{sha256_file(summary_path)}`",
            f"- NYC graph benchmark records SHA-256: `{sha256_file(records_path)}`",
            f"- NYC graph benchmark fit ledger SHA-256: `{sha256_file(ledger_path)}`",
            f"- Revalidated NYC calibration manifest SHA-256: `{validated_graph.manifest_sha256}`",
            f"- Revalidated NYC exposure map SHA-256: `{validated_graph.mapping_sha256}`",
        ]
    )
    return _NYCGraphEvidence(
        summary=summary_text,
        table=table,
        limitations="\n".join(f"- {item}" for item in limitations),
        provenance=provenance,
    )


@dataclass(frozen=True, slots=True)
class _EquilibriumEvidence:
    summary: str
    table: str
    limitations: str
    provenance: str


def _equilibrium_status(
    manifest_path: str | Path | None,
) -> _EquilibriumEvidence | None:
    """Validate a converged paired fixed-point equilibrium benchmark."""

    bundle = _manifest_bundle(manifest_path, "equilibrium benchmark")
    if bundle is None:
        return None
    _require_manifest_evidence(
        bundle, EQUILIBRIUM_EVIDENCE_TYPE, "equilibrium benchmark"
    )
    if (
        bundle.payload.get("evidence_type") != EQUILIBRIUM_EVIDENCE_TYPE
        or bundle.payload.get("causal_scope") != EQUILIBRIUM_CAUSAL_SCOPE
        or bundle.payload.get("empirical_calibration_status")
        != EQUILIBRIUM_EMPIRICAL_STATUS
        or bundle.payload.get("is_nyc_structural_estimate") is not False
        or bundle.payload.get("portable_paths") is not True
        or not isinstance(bundle.payload.get("checks"), dict)
        or any(value is not True for value in bundle.payload["checks"].values())
    ):
        raise ValueError("equilibrium benchmark manifest metadata is incompatible")
    metadata_path, metadata = _unique_json_object(
        bundle,
        lambda value: value.get("evidence_type") == EQUILIBRIUM_EVIDENCE_TYPE
        and "control_diagnostics" in value,
        "equilibrium benchmark metadata",
    )
    truth_path = metadata_path
    truth = metadata.get("ground_truth")
    if (
        metadata.get("schema_version") != 1
        or metadata.get("evidence_type") != EQUILIBRIUM_EVIDENCE_TYPE
        or metadata.get("causal_scope") != EQUILIBRIUM_CAUSAL_SCOPE
        or metadata.get("empirical_calibration_status")
        != EQUILIBRIUM_EMPIRICAL_STATUS
        or metadata.get("is_nyc_structural_estimate") is not False
        or metadata.get("common_random_numbers") is not True
        or metadata.get("ground_truth_status")
        != "known_exactly_for_the_paired_model_counterfactuals"
        or not isinstance(metadata.get("state_id"), str)
        or not metadata.get("state_id")
    ):
        raise ValueError("equilibrium benchmark metadata has an unsafe evidence contract")
    limitations = _required_string_list(
        metadata.get("limitations"), "equilibrium benchmark limitations"
    )
    equations = metadata.get("equations")
    required_equations = {
        "rider_demand",
        "driver_supply",
        "wait_fixed_point",
        "service_probability",
        "served_trips",
        "welfare",
        "uniqueness_and_convergence",
    }
    if not isinstance(equations, dict) or not required_equations.issubset(equations):
        raise ValueError("equilibrium benchmark equations are incomplete")

    uniqueness = metadata.get("uniqueness_diagnostics")
    if (
        not isinstance(uniqueness, dict)
        or uniqueness.get("sufficient_condition_satisfied") is not True
    ):
        raise ValueError("equilibrium benchmark uniqueness condition did not pass")
    contraction = uniqueness.get("contraction_bound")
    effective_bound = uniqueness.get("effective_iteration_bound")
    if (
        not isinstance(contraction, (int, float))
        or not isinstance(effective_bound, (int, float))
        or not np.isfinite([contraction, effective_bound]).all()
        or not 0 <= float(contraction) < 1
        or not 0 <= float(effective_bound) < 1
    ):
        raise ValueError("equilibrium benchmark contraction diagnostics are invalid")

    def validate_diagnostics(value: object, path_label: str) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError(f"equilibrium benchmark {path_label} diagnostics are missing")
        residual = value.get("residual_sup_norm")
        tolerance = value.get("tolerance")
        if (
            value.get("converged") is not True
            or value.get("uniqueness_condition_satisfied") is not True
            or value.get("termination_reason") != "residual_tolerance_satisfied"
            or not isinstance(residual, (int, float))
            or not isinstance(tolerance, (int, float))
            or not np.isfinite([residual, tolerance]).all()
            or residual < 0
            or tolerance <= 0
            or residual > tolerance
            or not np.isclose(value.get("contraction_bound"), contraction)
            or not np.isclose(value.get("effective_iteration_bound"), effective_bound)
        ):
            raise ValueError(
                f"equilibrium benchmark {path_label} solution did not converge safely"
            )
        return value

    control_diagnostics = validate_diagnostics(
        metadata.get("control_diagnostics"), "control"
    )
    treatment_diagnostics = validate_diagnostics(
        metadata.get("treatment_diagnostics"), "treatment"
    )
    budget = metadata.get("budget_diagnostics")
    if not isinstance(budget, dict) or budget.get("budget_feasible") is not True:
        raise ValueError("equilibrium benchmark budget feasibility did not pass")
    budget_scale = budget.get("budget_scale")
    realized_spend = budget.get("realized_treatment_spend")
    declared_budget = budget.get("budget")
    if (
        not isinstance(budget_scale, (int, float))
        or not isinstance(realized_spend, (int, float))
        or not np.isfinite([budget_scale, realized_spend]).all()
        or not 0 <= float(budget_scale) <= 1
        or realized_spend < 0
        or not np.isclose(metadata.get("realized_budget_scale"), budget_scale)
    ):
        raise ValueError("equilibrium benchmark budget diagnostics are invalid")
    if declared_budget is not None and (
        not isinstance(declared_budget, (int, float))
        or not np.isfinite(declared_budget)
        or realized_spend > declared_budget + 1e-7
    ):
        raise ValueError("equilibrium benchmark exceeds the declared budget")

    effects_path, effects = _unique_csv(
        bundle,
        {
            "zone_id",
            "control_trips",
            "treatment_trips",
            "trip_effect",
            "control_wait_minutes",
            "treatment_wait_minutes",
            "wait_effect_minutes",
            "control_welfare",
            "treatment_welfare",
            "welfare_effect",
            "realized_treatment_intensity",
            "state_id",
            "evidence_type",
        },
        "equilibrium benchmark zone effects",
    )
    ledger_path, ledger = _unique_csv(
        bundle,
        {
            "scenario",
            "equilibrium_converged",
            "equilibrium_residual_sup_norm",
            "trips",
            "treatment_spend",
            "rider_surplus",
            "driver_surplus",
            "platform_net_revenue",
            "total_welfare",
            "welfare_accounting_residual",
            "budget_binding",
            "budget_scale",
        },
        "equilibrium benchmark ledger",
    )
    if effects.empty or ledger.empty or len(ledger) != 2:
        raise ValueError("equilibrium benchmark effects or ledger are incomplete")
    if set(ledger["scenario"].astype(str)) != {"control", "treatment"}:
        raise ValueError("equilibrium benchmark ledger must contain control and treatment")
    if (
        not effects["evidence_type"].eq(EQUILIBRIUM_EVIDENCE_TYPE).all()
        or not effects["state_id"].eq(metadata["state_id"]).all()
    ):
        raise ValueError("equilibrium benchmark zone-effect provenance is incompatible")
    numeric_effects = effects[
        [
            "control_trips",
            "treatment_trips",
            "trip_effect",
            "control_wait_minutes",
            "treatment_wait_minutes",
            "wait_effect_minutes",
            "control_welfare",
            "treatment_welfare",
            "welfare_effect",
            "realized_treatment_intensity",
        ]
    ].apply(pd.to_numeric, errors="coerce")
    if not np.isfinite(numeric_effects.to_numpy(dtype=float)).all():
        raise ValueError("equilibrium benchmark zone effects contain non-finite values")
    if (
        not np.allclose(
            numeric_effects["trip_effect"],
            numeric_effects["treatment_trips"] - numeric_effects["control_trips"],
        )
        or not np.allclose(
            numeric_effects["wait_effect_minutes"],
            numeric_effects["treatment_wait_minutes"]
            - numeric_effects["control_wait_minutes"],
        )
        or not np.allclose(
            numeric_effects["welfare_effect"],
            numeric_effects["treatment_welfare"] - numeric_effects["control_welfare"],
        )
    ):
        raise ValueError("equilibrium benchmark zone-effect arithmetic is inconsistent")

    ledger["equilibrium_converged"] = _strict_boolean(
        ledger["equilibrium_converged"], "equilibrium_converged"
    )
    ledger["budget_binding"] = _strict_boolean(
        ledger["budget_binding"], "budget_binding"
    )
    ledger_numeric_columns = [
        "equilibrium_residual_sup_norm",
        "trips",
        "treatment_spend",
        "rider_surplus",
        "driver_surplus",
        "platform_net_revenue",
        "total_welfare",
        "welfare_accounting_residual",
        "budget_scale",
    ]
    ledger_numeric = ledger[ledger_numeric_columns].apply(pd.to_numeric, errors="coerce")
    if (
        not ledger["equilibrium_converged"].all()
        or not np.isfinite(ledger_numeric.to_numpy(dtype=float)).all()
        or (ledger_numeric["equilibrium_residual_sup_norm"] < 0).any()
        or ledger_numeric["equilibrium_residual_sup_norm"].iloc[0]
        > control_diagnostics["tolerance"]
        or ledger_numeric["equilibrium_residual_sup_norm"].iloc[1]
        > treatment_diagnostics["tolerance"]
        or not np.allclose(ledger_numeric["welfare_accounting_residual"], 0.0, atol=1e-8)
    ):
        raise ValueError("equilibrium benchmark ledger fails convergence or accounting checks")
    ordered = ledger.set_index("scenario")
    required_truth = {
        "market_total_effect",
        "market_total_trip_effect",
        "mean_zone_trip_effect",
        "market_total_welfare_effect",
        "mean_zone_wait_effect_minutes",
        "mean_zone_service_probability_effect",
        "treatment_spend",
        "incremental_trips_per_dollar",
        "incremental_welfare_per_dollar",
    }
    if not isinstance(truth, dict) or not required_truth.issubset(truth):
        raise ValueError("equilibrium benchmark ground truth is incomplete")
    finite_truth = [
        value for value in truth.values() if value is not None and not isinstance(value, bool)
    ]
    if not finite_truth or not np.isfinite(finite_truth).all():
        raise ValueError("equilibrium benchmark ground truth contains non-finite values")
    trip_effect = float(numeric_effects["trip_effect"].sum())
    welfare_effect = float(numeric_effects["welfare_effect"].sum())
    treatment_spend = float(ordered.loc["treatment", "treatment_spend"])
    if (
        not np.isclose(truth["market_total_effect"], trip_effect)
        or not np.isclose(truth["market_total_trip_effect"], trip_effect)
        or not np.isclose(truth["market_total_welfare_effect"], welfare_effect)
        or not np.isclose(truth["treatment_spend"], treatment_spend)
        or not np.isclose(realized_spend, treatment_spend)
        or not np.isclose(
            float(ordered.loc["treatment", "trips"])
            - float(ordered.loc["control", "trips"]),
            trip_effect,
        )
        or not np.isclose(
            float(ordered.loc["treatment", "total_welfare"])
            - float(ordered.loc["control", "total_welfare"]),
            welfare_effect,
        )
    ):
        raise ValueError("equilibrium benchmark ground truth disagrees with its ledger")
    if treatment_spend > 1e-12:
        if (
            not np.isclose(truth["incremental_trips_per_dollar"], trip_effect / treatment_spend)
            or not np.isclose(
                truth["incremental_welfare_per_dollar"], welfare_effect / treatment_spend
            )
        ):
            raise ValueError("equilibrium benchmark efficiency ratios are inconsistent")
    elif (
        truth["incremental_trips_per_dollar"] is not None
        or truth["incremental_welfare_per_dollar"] is not None
    ):
        raise ValueError("equilibrium benchmark zero-spend ratios must be withheld")

    table = markdown_table(
        ledger.sort_values("scenario"),
        [
            "scenario",
            "treatment_version",
            "trips",
            "mean_wait_minutes",
            "mean_service_probability",
            "treatment_spend",
            "rider_surplus",
            "driver_surplus",
            "platform_net_revenue",
            "total_welfare",
            "equilibrium_converged",
            "equilibrium_residual_sup_norm",
            "budget_binding",
            "budget_scale",
        ],
    )
    budget_text = (
        f"The configured budget is {float(declared_budget):,.2f}; the solver re-solves "
        f"the equilibrium at a feasible intensity scale of {float(budget_scale):.4f}. "
        if declared_budget is not None
        else "No binding budget was configured for this benchmark. "
    )
    summary_text = (
        "The theoretical two-sided-market benchmark solves paired control and policy "
        "fixed points for the same seeded exogenous state. Both paths satisfy the "
        f"declared residual tolerance and the sufficient contraction bound "
        f"({float(contraction):.4f} < 1). {budget_text}The within-model policy contrast "
        f"is {trip_effect:.4f} trips and {welfare_effect:.4f} units of modeled welfare. "
        "These are exact counterfactuals only inside the declared equilibrium model; "
        "parameters are not estimated from NYC data and this is not an NYC structural estimate."
    )
    provenance = "\n".join(
        [
            f"- Equilibrium benchmark manifest SHA-256: `{sha256_file(bundle.path)}`",
            f"- Equilibrium benchmark metadata SHA-256: `{sha256_file(metadata_path)}`",
            f"- Equilibrium benchmark ground truth SHA-256: `{sha256_file(truth_path)}`",
            f"- Equilibrium benchmark zone effects SHA-256: `{sha256_file(effects_path)}`",
            f"- Equilibrium benchmark ledger SHA-256: `{sha256_file(ledger_path)}`",
            f"- Equilibrium seeded state ID: `{metadata['state_id']}`",
        ]
    )
    return _EquilibriumEvidence(
        summary=summary_text,
        table=table,
        limitations="\n".join(f"- {item}" for item in limitations),
        provenance=provenance,
    )


@dataclass(frozen=True, slots=True)
class _NYCWeatherEvidence:
    summary: str
    table: str
    limitations: str
    provenance: str


def _nyc_weather_status(
    manifest_path: str | Path | None,
) -> _NYCWeatherEvidence | None:
    """Validate descriptive NOAA weather associations against NYC panel lineage."""

    bundle = _manifest_bundle(manifest_path, "NYC NOAA weather")
    if bundle is None:
        return None
    _require_manifest_evidence(bundle, WEATHER_EVIDENCE_LABEL, "NYC NOAA weather")
    checks = bundle.payload.get("checks")
    if (
        bundle.payload.get("schema_version") != "1.0.0"
        or bundle.payload.get("evidence_label") != WEATHER_EVIDENCE_LABEL
        or bundle.payload.get("causal_claim") is not False
        or bundle.payload.get("portable_paths") is not True
        or not isinstance(checks, dict)
        or checks.get("noaa_raw_hash_matches") is not True
        or checks.get("calendar_complete") is not True
        or checks.get("nyc_source_manifest_valid") is not True
        or checks.get("trip_conservation") is not True
        or isinstance(checks.get("panel_files_verified"), bool)
        or not isinstance(checks.get("panel_files_verified"), int)
        or checks["panel_files_verified"] < 1
    ):
        raise ValueError("NYC NOAA weather manifest checks did not all pass")
    summary_path, payload = _unique_json_object(
        bundle,
        lambda value: value.get("evidence_label") == WEATHER_EVIDENCE_LABEL
        and "associations" in value,
        "NYC NOAA weather association summary",
    )
    if (
        payload.get("schema_version") != "1.0.0"
        or payload.get("causal_claim") is not False
    ):
        raise ValueError("NYC NOAA weather summary has an unsafe evidence contract")
    scope = payload.get("scope")
    coverage = payload.get("coverage")
    conservation = payload.get("conservation")
    associations = payload.get("associations")
    provenance_payload = payload.get("provenance")
    if not all(
        isinstance(value, dict)
        for value in (scope, coverage, conservation, associations, provenance_payload)
    ):
        raise ValueError("NYC NOAA weather summary is incomplete")
    if (
        scope.get("city") != "New York City"
        or scope.get("population_claim") is not False
        or not isinstance(scope.get("pickup_month"), str)
        or not isinstance(scope.get("weather_station_id"), str)
        or not scope.get("weather_station_id")
    ):
        raise ValueError("NYC NOAA weather scope is incompatible")
    weather_rows = coverage.get("weather_rows")
    joined_days = coverage.get("joined_days")
    date_hours = coverage.get("joined_date_hours")
    wet_days = coverage.get("wet_days")
    dry_days = coverage.get("dry_days")
    counts = (weather_rows, joined_days, date_hours, wet_days, dry_days)
    if (
        any(isinstance(value, bool) or not isinstance(value, int) for value in counts)
        or weather_rows <= 1
        or weather_rows != joined_days
        or date_hours != joined_days * 24
        or wet_days <= 0
        or dry_days <= 0
        or wet_days + dry_days != joined_days
        or scope.get("published_completed_trip_days") != joined_days
    ):
        raise ValueError("NYC NOAA weather calendar coverage is inconsistent")
    daily_sum = conservation.get("daily_trip_sum")
    zone_sum = conservation.get("zone_time_trip_sum")
    if (
        conservation.get("passes") is not True
        or isinstance(daily_sum, bool)
        or not isinstance(daily_sum, int)
        or daily_sum <= 0
        or daily_sum != zone_sum
    ):
        raise ValueError("NYC NOAA weather trip conservation is inconsistent")

    raw_path = (
        bundle.root
        / _portable_manifest_path(
            provenance_payload.get("noaa_raw_path"), "NYC NOAA raw path"
        )
    ).resolve()
    data_manifest_path = (
        bundle.root
        / _portable_manifest_path(
            provenance_payload.get("nyc_data_manifest_path"),
            "NYC weather source-data manifest path",
        )
    ).resolve()
    if (
        raw_path not in bundle.files
        or data_manifest_path not in bundle.files
        or sha256_file(raw_path) != provenance_payload.get("noaa_raw_sha256")
        or sha256_file(data_manifest_path)
        != provenance_payload.get("nyc_data_manifest_sha256")
        or provenance_payload.get("hashes_recomputed") is not True
        or provenance_payload.get("panel_files_verified")
        != checks["panel_files_verified"]
    ):
        raise ValueError("NYC NOAA weather provenance hashes disagree")
    source_manifest = _load_json_object(
        data_manifest_path, "NYC weather source-data manifest"
    )
    source_config = source_manifest.get("config")
    source_metadata = source_manifest.get("metadata")
    if (
        not isinstance(source_config, dict)
        or not isinstance(source_metadata, dict)
        or source_config.get("source") != "nyc_hvfhv"
        or source_config.get("mode") != "full"
        or source_metadata.get("evidence_label") != "descriptive_real_data"
        or source_metadata.get("causal_claim") is not False
    ):
        raise ValueError("NYC NOAA weather source-data manifest is incompatible")
    source_trip_sum = (
        source_metadata.get("full_month_processing", {})
        .get("row_conservation", {})
        .get("zone_time_trip_sum")
    )
    if source_trip_sum != daily_sum:
        raise ValueError("NYC NOAA weather total disagrees with the NYC source manifest")

    normalized_path, normalized = _unique_csv(
        bundle,
        {
            "service_date",
            "station_id",
            "precipitation_mm",
            "temperature_midrange_c",
            "wet_day",
            "evidence_label",
            "causal_claim",
            "raw_sha256",
        },
        "NYC NOAA normalized weather",
        excluded_columns={"published_completed_trips"},
    )
    daily_path, daily = _unique_csv(
        bundle,
        {
            "service_date",
            "published_completed_trips",
            "wet_day",
            "precipitation_mm",
            "evidence_label",
            "causal_claim",
        },
        "NYC NOAA daily trip-weather panel",
    )
    hourly_path, hourly = _unique_csv(
        bundle,
        {
            "hour",
            "days_wet",
            "days_dry",
            "wet_minus_dry_mean_published_completed_trips",
            "evidence_label",
            "causal_claim",
        },
        "NYC NOAA hourly contrasts",
    )
    if len(normalized) != weather_rows or len(daily) != joined_days or len(hourly) != 24:
        raise ValueError("NYC NOAA weather table coverage disagrees with its summary")
    for frame in (normalized, daily, hourly):
        if (
            not frame["evidence_label"].eq(WEATHER_EVIDENCE_LABEL).all()
            or _strict_boolean(frame["causal_claim"], "causal_claim").any()
        ):
            raise ValueError("NYC NOAA weather tables contain an unsafe evidence label")
    if (
        not normalized["station_id"].astype(str).eq(scope["weather_station_id"]).all()
        or not normalized["raw_sha256"].eq(provenance_payload["noaa_raw_sha256"]).all()
        or int(pd.to_numeric(daily["published_completed_trips"], errors="coerce").sum())
        != daily_sum
    ):
        raise ValueError("NYC NOAA weather table provenance or trip totals disagree")

    required_associations = {
        "mean_daily_published_completed_trips_wet",
        "mean_daily_published_completed_trips_dry",
        "wet_minus_dry_mean_daily_published_completed_trips",
        "wet_minus_dry_relative_to_dry",
        "precipitation_daily_trip_correlation",
        "temperature_midrange_daily_trip_correlation",
    }
    if not required_associations.issubset(associations):
        raise ValueError("NYC NOAA weather associations are incomplete")
    wet_mean = associations["mean_daily_published_completed_trips_wet"]
    dry_mean = associations["mean_daily_published_completed_trips_dry"]
    difference = associations["wet_minus_dry_mean_daily_published_completed_trips"]
    relative = associations["wet_minus_dry_relative_to_dry"]
    primary = [wet_mean, dry_mean, difference, relative]
    if (
        not all(isinstance(value, (int, float)) for value in primary)
        or not np.isfinite(primary).all()
        or dry_mean <= 0
        or not np.isclose(difference, wet_mean - dry_mean)
        or not np.isclose(relative, difference / dry_mean)
    ):
        raise ValueError("NYC NOAA wet-dry association arithmetic is inconsistent")
    for key in (
        "precipitation_daily_trip_correlation",
        "temperature_midrange_daily_trip_correlation",
    ):
        value = associations[key]
        if value is not None and (
            not isinstance(value, (int, float))
            or not np.isfinite(value)
            or not -1 <= value <= 1
        ):
            raise ValueError("NYC NOAA weather correlation is invalid")
    limitations = _required_string_list(
        payload.get("limitations"), "NYC NOAA weather limitations"
    )
    if "confound" not in " ".join(limitations).lower() or "not" not in " ".join(
        limitations
    ).lower():
        raise ValueError("NYC NOAA weather limitations omit the noncausal boundary")

    table_frame = pd.DataFrame(
        [
            {"metric": "Mean daily published completed trips — wet", "value": wet_mean},
            {"metric": "Mean daily published completed trips — dry", "value": dry_mean},
            {"metric": "Wet minus dry mean daily trips", "value": difference},
            {"metric": "Wet minus dry relative to dry", "value": relative},
            {
                "metric": "Precipitation / daily trips correlation",
                "value": associations["precipitation_daily_trip_correlation"],
            },
            {
                "metric": "Temperature midrange / daily trips correlation",
                "value": associations["temperature_midrange_daily_trip_correlation"],
            },
        ]
    )
    table = markdown_table(table_frame, ["metric", "value"])
    summary_text = (
        f"The verified NOAA Daily Summaries join covers {joined_days} days and "
        f"{date_hours} NYC date-hours using station `{scope['weather_station_id']}`. "
        f"Mean published completed trips were {float(wet_mean):,.1f} on wet days and "
        f"{float(dry_mean):,.1f} on dry days, a descriptive difference of "
        f"{float(difference):,.1f} ({float(relative):.2%} of the dry-day mean). "
        "This is an observational weather-demand association for published completed "
        "trips, not a causal weather effect, treatment effect, instrument, or latent-demand estimate."
    )
    provenance = "\n".join(
        [
            f"- NYC NOAA weather manifest SHA-256: `{sha256_file(bundle.path)}`",
            f"- NYC NOAA association summary SHA-256: `{sha256_file(summary_path)}`",
            f"- NYC NOAA raw response SHA-256: `{sha256_file(raw_path)}`",
            f"- NYC weather source-data manifest SHA-256: `{sha256_file(data_manifest_path)}`",
            f"- NYC NOAA normalized weather SHA-256: `{sha256_file(normalized_path)}`",
            f"- NYC NOAA daily trip-weather panel SHA-256: `{sha256_file(daily_path)}`",
            f"- NYC NOAA hourly contrasts SHA-256: `{sha256_file(hourly_path)}`",
        ]
    )
    return _NYCWeatherEvidence(
        summary=summary_text,
        table=table,
        limitations="\n".join(f"- {item}" for item in limitations),
        provenance=provenance,
    )


@dataclass(frozen=True, slots=True)
class _NYCDescriptiveEnrichmentEvidence:
    summary: str
    table: str
    limitations: str
    provenance: str


def _read_descriptive_role_csv(
    bundle: _ManifestBundle,
    role: str,
    *,
    evidence_label: str,
    label: str,
) -> tuple[Path, pd.DataFrame]:
    path = _bundle_file_by_role(bundle, role, label)
    try:
        frame = pd.read_csv(path)
    except (OSError, pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
        raise ValueError(f"{label} {role} is not a readable CSV") from exc
    if frame.empty or not {"evidence_label", "causal_claim"}.issubset(frame.columns):
        raise ValueError(f"{label} {role} has an incomplete descriptive schema")
    if (
        not frame["evidence_label"].astype(str).eq(evidence_label).all()
        or _strict_boolean(frame["causal_claim"], "causal_claim").any()
    ):
        raise ValueError(f"{label} {role} violates the non-causal evidence contract")
    return path, frame


def _validate_nyc_panel_source_manifest(
    source_manifest_path: Path,
    *,
    bundle: _ManifestBundle,
    expected_panel_files: int,
    directly_declared_panel_inputs: set[Path] | None = None,
) -> tuple[int, set[Path]]:
    source = _load_json_object(source_manifest_path, "NYC full source-data manifest")
    config = source.get("config")
    metadata = source.get("metadata")
    if (
        not isinstance(config, dict)
        or not isinstance(metadata, dict)
        or config.get("source") != "nyc_hvfhv"
        or config.get("mode") != "full"
        or metadata.get("evidence_label") != "descriptive_real_data"
        or metadata.get("causal_claim") is not False
    ):
        raise ValueError("NYC enrichment source-data manifest is incompatible")
    raw_files = source.get("files")
    if not isinstance(raw_files, list):
        raise ValueError("NYC enrichment source-data manifest has no files list")
    panel_entries: list[dict[str, Any]] = []
    panel_paths: set[Path] = set()
    for entry in raw_files:
        if not isinstance(entry, dict):
            raise ValueError("NYC source-data manifest contains a non-object file entry")
        rendered = _portable_manifest_path(
            entry.get("path"), "NYC source-data manifest file path"
        )
        if (
            rendered.suffix.lower() != ".parquet"
            or "panel" not in rendered.parts
            or "zone_time" not in rendered.parts
        ):
            continue
        path = (bundle.root / rendered).resolve()
        try:
            path.relative_to(bundle.root)
        except ValueError as exc:
            raise ValueError("NYC panel source path escapes the project root") from exc
        panel_entries.append(entry)
        panel_paths.add(path)
    if len(panel_entries) != expected_panel_files or len(panel_paths) != expected_panel_files:
        raise ValueError("NYC enrichment panel file count disagrees with source lineage")
    _validate_manifest_files(
        {"files": panel_entries}, bundle.root, "NYC enrichment panel source"
    )
    if (
        directly_declared_panel_inputs is not None
        and directly_declared_panel_inputs != panel_paths
    ):
        raise ValueError("NYC enrichment panel inputs disagree with source lineage")
    trip_sum = (
        metadata.get("full_month_processing", {})
        .get("row_conservation", {})
        .get("zone_time_trip_sum")
    )
    if isinstance(trip_sum, bool) or not isinstance(trip_sum, int) or trip_sum <= 0:
        raise ValueError("NYC enrichment source trip total is unavailable")
    return trip_sum, panel_paths


def _nyc_events_status(
    manifest_path: str | Path | None,
) -> _NYCDescriptiveEnrichmentEvidence | None:
    """Validate official-calendar and permitted-event descriptive evidence."""

    label = "NYC calendar/event enrichment"
    bundle = _manifest_bundle(manifest_path, label)
    if bundle is None:
        return None
    _require_manifest_evidence(bundle, EVENT_EVIDENCE_LABEL, label)
    checks = bundle.payload.get("checks")
    required_true_checks = {
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
        bundle.payload.get("schema_version") != EVENT_SCHEMA_VERSION
        or bundle.payload.get("evidence_label") != EVENT_EVIDENCE_LABEL
        or bundle.payload.get("causal_claim") is not False
        or bundle.payload.get("portable_paths") is not True
        or not isinstance(checks, dict)
        or any(checks.get(key) is not True for key in required_true_checks)
        or checks.get("major_event_contrast_separately_identified") is not False
    ):
        raise ValueError("NYC calendar/event manifest has an unsafe evidence schema")
    joined_days = checks.get("joined_days")
    joined_hours = checks.get("joined_date_hours")
    panel_files_verified = checks.get("panel_files_verified")
    if (
        any(
            isinstance(value, bool) or not isinstance(value, int) or value < 1
            for value in (joined_days, joined_hours, panel_files_verified)
        )
        or joined_hours != joined_days * 24
    ):
        raise ValueError("NYC calendar/event manifest coverage checks are inconsistent")

    expected_file_roles = {
        "normalized_daily_calendar",
        "normalized_permit_records",
        "daily_permit_type_counts",
        "joined_daily_trip_panel",
        "descriptive_hourly_profiles",
        "descriptive_summary",
    }
    observed_file_roles = [entry.get("role") for entry in bundle.files.values()]
    if set(observed_file_roles) != expected_file_roles or len(observed_file_roles) != 6:
        raise ValueError("NYC calendar/event manifest has an incomplete file-role set")
    input_roles = [entry.get("role") for entry in bundle.inputs.values()]
    singleton_input_roles = {
        "official_holiday_snapshot",
        "official_nyc_permitted_events_snapshot",
        "nyc_full_data_manifest",
    }
    if (
        any(input_roles.count(role) != 1 for role in singleton_input_roles)
        or input_roles.count("nyc_full_zone_time_panel") != panel_files_verified
        or set(input_roles) != singleton_input_roles | {"nyc_full_zone_time_panel"}
    ):
        raise ValueError("NYC calendar/event manifest has an incomplete input-role set")

    summary_path = _bundle_file_by_role(bundle, "descriptive_summary", label)
    summary = _load_json_object(summary_path, "NYC calendar/event summary")
    scope = summary.get("scope")
    definitions = summary.get("definitions")
    coverage = summary.get("coverage")
    associations = summary.get("associations")
    identification = summary.get("identification_checks")
    conservation = summary.get("conservation")
    provenance_payload = summary.get("provenance")
    if not all(
        isinstance(value, dict)
        for value in (
            scope,
            definitions,
            coverage,
            associations,
            identification,
            conservation,
            provenance_payload,
        )
    ):
        raise ValueError("NYC calendar/event summary is incomplete")
    major_definition = definitions.get("researcher_defined_major_permitted_event")
    if (
        summary.get("schema_version") != EVENT_SCHEMA_VERSION
        or summary.get("evidence_label") != EVENT_EVIDENCE_LABEL
        or summary.get("causal_claim") is not False
        or scope.get("city") != "New York City"
        or scope.get("population_claim") is not False
        or scope.get("event_signal_spatial_granularity") != "citywide"
        or scope.get("event_signal_temporal_granularity") != "service_date"
        or not isinstance(major_definition, dict)
        or major_definition.get("official_severity_classification") is not False
        or identification.get("causal_effect_identified") is not False
        or identification.get("permit_intensity_assignment_is_randomized") is not False
        or identification.get("major_event_contrast_separately_identifies_event_effect")
        is not False
        or identification.get("major_event_days_are_subset_of_holiday_days") is not True
        or identification.get("all_weekend_days_are_above_median_permit_intensity")
        is not True
    ):
        raise ValueError("NYC calendar/event summary violates its non-causal scope")

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
    event_days = coverage.get("expanded_unique_event_days")
    above_days = coverage.get("above_median_permit_intensity_days")
    comparison_days = coverage.get("at_or_below_median_permit_intensity_days")
    major_days = coverage.get("researcher_defined_major_event_days")
    weekend_days = coverage.get("weekend_days")
    above_weekend_days = coverage.get("above_median_permit_intensity_weekend_days")
    lower_weekend_days = coverage.get(
        "at_or_below_median_permit_intensity_weekend_days"
    )
    numeric_coverage = (
        permit_rows,
        unique_ids,
        invalid_rows,
        zero_duration_rows,
        nonpositive_rows,
        valid_rows,
        valid_unique_ids,
        event_days,
        above_days,
        comparison_days,
        major_days,
        weekend_days,
        above_weekend_days,
        lower_weekend_days,
    )
    if (
        any(isinstance(value, bool) or not isinstance(value, int) for value in numeric_coverage)
        or permit_rows < unique_ids
        or unique_ids < 1
        or invalid_rows < 0
        or zero_duration_rows < 0
        or nonpositive_rows != invalid_rows + zero_duration_rows
        or valid_rows != permit_rows - nonpositive_rows
        or not 1 <= valid_unique_ids <= unique_ids
        or event_days < valid_unique_ids
        or above_days < 1
        or comparison_days < 1
        or above_days + comparison_days != joined_days
        or major_days < 1
        or weekend_days < 0
        or above_weekend_days != weekend_days
        or lower_weekend_days != 0
        or coverage.get("joined_days") != joined_days
        or coverage.get("joined_date_hours") != joined_hours
    ):
        raise ValueError("NYC calendar/event summary coverage is inconsistent")

    contrast_specs = (
        (
            "above_vs_at_or_below_median_permit_intensity",
            "Above-median permit intensity vs lower-intensity days",
            joined_days,
        ),
        (
            "above_vs_at_or_below_median_permit_intensity_weekdays_only",
            "Weekday-only: above-median vs lower permit intensity",
            joined_days - weekend_days,
        ),
        (
            "official_holiday_vs_nonholiday",
            "Official holiday vs nonholiday days",
            joined_days,
        ),
    )
    table_rows: list[dict[str, Any]] = []
    for key, rendered_label, expected_days in contrast_specs:
        contrast = associations.get(key)
        if not isinstance(contrast, dict):
            raise ValueError(f"NYC calendar/event association {key} is missing")
        exposed = contrast.get("exposed_days")
        comparison = contrast.get("comparison_days")
        exposed_mean = contrast.get("mean_daily_published_completed_trips_exposed")
        comparison_mean = contrast.get(
            "mean_daily_published_completed_trips_comparison"
        )
        difference = contrast.get(
            "exposed_minus_comparison_mean_daily_published_completed_trips"
        )
        relative = contrast.get("exposed_minus_comparison_relative_to_comparison")
        numbers = (exposed_mean, comparison_mean, difference, relative)
        if (
            isinstance(exposed, bool)
            or not isinstance(exposed, int)
            or isinstance(comparison, bool)
            or not isinstance(comparison, int)
            or exposed + comparison != expected_days
            or not all(isinstance(value, (int, float)) for value in numbers)
            or not np.isfinite(numbers).all()
            or comparison_mean <= 0
            or not np.isclose(difference, exposed_mean - comparison_mean)
            or not np.isclose(relative, difference / comparison_mean)
        ):
            raise ValueError("NYC calendar/event association arithmetic is inconsistent")
        table_rows.append(
            {
                "descriptive contrast": rendered_label,
                "exposed days": exposed,
                "comparison days": comparison,
                "mean exposed trips": exposed_mean,
                "mean comparison trips": comparison_mean,
                "difference": difference,
                "relative difference": relative,
            }
        )
    major_contrast = associations.get("major_permitted_event_day_vs_other_days")
    if not isinstance(major_contrast, dict) or major_contrast.get("exposed_days") != major_days:
        raise ValueError("NYC calendar/event major-day diagnostic is inconsistent")
    weekday_demeaned_correlation = associations.get(
        "weekday_demeaned_active_permit_count_daily_trip_correlation"
    )
    if weekday_demeaned_correlation is not None and (
        not isinstance(weekday_demeaned_correlation, (int, float))
        or not np.isfinite(weekday_demeaned_correlation)
        or not -1 <= weekday_demeaned_correlation <= 1
    ):
        raise ValueError("NYC calendar/event weekday-demeaned correlation is invalid")
    if (
        conservation.get("passes") is not True
        or conservation.get("daily_trip_sum") != conservation.get("zone_time_trip_sum")
        or isinstance(conservation.get("daily_trip_sum"), bool)
        or not isinstance(conservation.get("daily_trip_sum"), int)
        or conservation["daily_trip_sum"] <= 0
    ):
        raise ValueError("NYC calendar/event trip conservation is inconsistent")

    role_frames: dict[str, tuple[Path, pd.DataFrame]] = {}
    for role in expected_file_roles - {"descriptive_summary"}:
        role_frames[role] = _read_descriptive_role_csv(
            bundle,
            role,
            evidence_label=EVENT_EVIDENCE_LABEL,
            label=label,
        )
    if (
        len(role_frames["normalized_daily_calendar"][1]) != joined_days
        or len(role_frames["normalized_permit_records"][1]) != permit_rows
        or len(role_frames["descriptive_hourly_profiles"][1]) != 24
        or len(role_frames["joined_daily_trip_panel"][1]) != joined_days
        or int(
            pd.to_numeric(
                role_frames["joined_daily_trip_panel"][1][
                    "published_completed_trips"
                ],
                errors="coerce",
            ).sum()
        )
        != conservation["daily_trip_sum"]
    ):
        raise ValueError("NYC calendar/event tables disagree with their summary")

    source_manifest_path = _bundle_input_by_role(
        bundle, "nyc_full_data_manifest", label
    )
    direct_panels = {
        path
        for path, entry in bundle.inputs.items()
        if entry.get("role") == "nyc_full_zone_time_panel"
    }
    source_trip_sum, _ = _validate_nyc_panel_source_manifest(
        source_manifest_path,
        bundle=bundle,
        expected_panel_files=panel_files_verified,
        directly_declared_panel_inputs=direct_panels,
    )
    if source_trip_sum != conservation["daily_trip_sum"]:
        raise ValueError("NYC calendar/event trips disagree with source lineage")
    for role, path_key, hash_key in (
        ("official_holiday_snapshot", "holiday_snapshot_path", "holiday_snapshot_sha256"),
        (
            "official_nyc_permitted_events_snapshot",
            "event_snapshot_path",
            "event_snapshot_sha256",
        ),
        ("nyc_full_data_manifest", "nyc_data_manifest_path", "nyc_data_manifest_sha256"),
    ):
        input_path = _bundle_input_by_role(bundle, role, label)
        if (
            _portable_manifest_path(provenance_payload.get(path_key), path_key)
            != input_path.relative_to(bundle.root)
            or provenance_payload.get(hash_key) != sha256_file(input_path)
        ):
            raise ValueError("NYC calendar/event provenance disagrees with inputs")
    if (
        provenance_payload.get("hashes_recomputed") is not True
        or provenance_payload.get("panel_files_verified") != panel_files_verified
    ):
        raise ValueError("NYC calendar/event provenance checks are incomplete")
    limitations = _required_string_list(
        summary.get("limitations"), "NYC calendar/event limitations"
    )
    limitation_text = " ".join(limitations).lower()
    if (
        "confound" not in limitation_text
        or "attendance" not in limitation_text
        or "weekend" not in limitation_text
    ):
        raise ValueError("NYC calendar/event limitations omit key evidence boundaries")

    permit_contrast = associations["above_vs_at_or_below_median_permit_intensity"]
    weekday_contrast = associations[
        "above_vs_at_or_below_median_permit_intensity_weekdays_only"
    ]
    holiday_contrast = associations["official_holiday_vs_nonholiday"]
    summary_text = (
        f"The verified January calendar/event join covers {joined_days} days and "
        f"{joined_hours} date-hours from {permit_rows:,} permit rows representing "
        f"{unique_ids:,} event IDs. Above-median permit-intensity days differed from "
        f"lower-intensity days by {float(permit_contrast['exposed_minus_comparison_mean_daily_published_completed_trips']):,.1f} "
        f"published completed trips/day ({float(permit_contrast['exposed_minus_comparison_relative_to_comparison']):.2%}), "
        f"but all {weekend_days} weekend days are in the above-median group and none "
        f"are in the comparison group. Restricting to weekdays reverses the descriptive "
        f"difference to {float(weekday_contrast['exposed_minus_comparison_mean_daily_published_completed_trips']):,.1f}/day "
        f"({float(weekday_contrast['exposed_minus_comparison_relative_to_comparison']):.2%}); "
        f"official holidays differed from nonholidays by "
        f"{float(holiday_contrast['exposed_minus_comparison_mean_daily_published_completed_trips']):,.1f}/day "
        f"({float(holiday_contrast['exposed_minus_comparison_relative_to_comparison']):.2%}). "
        "These are observational citywide daily associations. Permit windows are not "
        "attendance or zone/hour exposure, and the researcher-defined major-event day "
        "is holiday-confounded rather than separately identified."
    )
    provenance = "\n".join(
        [
            f"- NYC calendar/event manifest SHA-256: `{sha256_file(bundle.path)}`",
            f"- NYC calendar/event summary SHA-256: `{sha256_file(summary_path)}`",
            *[
                f"- NYC calendar/event input `{entry.get('role')}` SHA-256: `{sha256_file(path)}`"
                for path, entry in bundle.inputs.items()
            ],
        ]
    )
    return _NYCDescriptiveEnrichmentEvidence(
        summary=summary_text,
        table=markdown_table(pd.DataFrame(table_rows), list(table_rows[0])),
        limitations="\n".join(f"- {item}" for item in limitations),
        provenance=provenance,
    )


def _nyc_income_status(
    manifest_path: str | Path | None,
) -> _NYCDescriptiveEnrichmentEvidence | None:
    """Validate ecological Taxi Zone income descriptions and their official lineage."""

    label = "NYC neighborhood-income enrichment"
    bundle = _manifest_bundle(manifest_path, label)
    if bundle is None:
        return None
    _require_manifest_evidence(bundle, INCOME_EVIDENCE_LABEL, label)
    checks = bundle.payload.get("checks")
    required_true_checks = {
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
        bundle.payload.get("schema_version") != INCOME_SCHEMA_VERSION
        or bundle.payload.get("artifact_type") != "nyc_income_descriptive_bundle"
        or bundle.payload.get("evidence_label") != INCOME_EVIDENCE_LABEL
        or bundle.payload.get("causal_claim") is not False
        or bundle.payload.get("portable_paths") is not True
        or not isinstance(checks, dict)
        or any(checks.get(key) is not True for key in required_true_checks)
        or checks.get("median_of_medians_used") is not False
        or checks.get("equal_area_crs") != "EPSG:6933"
        or checks.get("dominant_nonresidential_primary_classified_zones") != 0
        or checks.get("minimum_allocated_households") != 1.0
        or checks.get("minimum_residential_taxi_zone_area_share") != 0.5
        or checks.get("residential_nta_type_codes") != ["0"]
        or checks.get("zone_grouped_medians_are_point_estimates") is not True
        or checks.get("zone_level_margin_of_error_propagated") is not False
    ):
        raise ValueError("NYC neighborhood-income manifest has an unsafe evidence schema")
    panel_files_verified = checks.get("panel_files_verified")
    declared_coverage = checks.get("classified_trip_coverage")
    if (
        isinstance(panel_files_verified, bool)
        or not isinstance(panel_files_verified, int)
        or panel_files_verified < 1
        or isinstance(declared_coverage, bool)
        or not isinstance(declared_coverage, (int, float))
        or not np.isfinite(declared_coverage)
        or not 0 < declared_coverage <= 1
    ):
        raise ValueError("NYC neighborhood-income manifest coverage checks are invalid")

    expected_file_roles = {
        "taxi_zone_nta_crosswalk",
        "nta_b19001_distribution_summary",
        "taxi_zone_income_and_trip_summary",
        "daily_income_group_description",
        "monthly_income_group_description",
        "income_association_summary",
    }
    observed_file_roles = [entry.get("role") for entry in bundle.files.values()]
    if set(observed_file_roles) != expected_file_roles or len(observed_file_roles) != 6:
        raise ValueError("NYC neighborhood-income manifest has an incomplete file-role set")
    if any(
        entry.get("evidence_label") != INCOME_EVIDENCE_LABEL
        or entry.get("causal_claim") is not False
        for entry in bundle.files.values()
    ):
        raise ValueError("NYC neighborhood-income files have unsafe evidence metadata")
    expected_input_types = {
        "official_tlc_taxi_zone_geometry": "official_observed_geometry",
        "official_nyc_nta2020_geometry": "official_observed_geometry",
        "official_nyc_tract2020_to_nta2020_mapping": "official_observed_crosswalk",
        "official_census_acs_2022_5yr_b19001_nyc_tract_slice": (
            "official_observed_estimates"
        ),
        "verified_nyc_full_data_manifest": "descriptive_real_data_lineage",
    }
    observed_inputs = {
        str(entry.get("role")): entry
        for entry in bundle.inputs.values()
        if entry.get("role") != "nyc_full_zone_time_panel"
    }
    panel_inputs = {
        path
        for path, entry in bundle.inputs.items()
        if entry.get("role") == "nyc_full_zone_time_panel"
    }
    if (
        set(observed_inputs) != set(expected_input_types)
        or len(panel_inputs) != panel_files_verified
        or len(bundle.inputs) != 5 + panel_files_verified
    ):
        raise ValueError("NYC neighborhood-income manifest has an incomplete input-role set")
    if any(
        observed_inputs[role].get("source_type") != source_type
        for role, source_type in expected_input_types.items()
    ) or any(
        entry.get("source_type") != "descriptive_real_data_panel"
        for path, entry in bundle.inputs.items()
        if path in panel_inputs
    ):
        raise ValueError("NYC neighborhood-income input evidence types are invalid")

    summary_path = _bundle_file_by_role(bundle, "income_association_summary", label)
    summary = _load_json_object(summary_path, "NYC neighborhood-income summary")
    scope = summary.get("scope")
    definitions = summary.get("definitions")
    coverage = summary.get("coverage")
    associations = summary.get("associations")
    conservation = summary.get("conservation")
    spatial = summary.get("spatial_mapping")
    acs = summary.get("acs_aggregation")
    allocation = summary.get("zone_allocation")
    primary_classification = summary.get("primary_classification")
    uncertainty = summary.get("classification_uncertainty")
    sensitivity = summary.get("sensitivity")
    provenance_payload = summary.get("provenance")
    if not all(
        isinstance(value, dict)
        for value in (
            scope,
            definitions,
            coverage,
            associations,
            conservation,
            spatial,
            acs,
            allocation,
            primary_classification,
            uncertainty,
            sensitivity,
            provenance_payload,
        )
    ):
        raise ValueError("NYC neighborhood-income summary is incomplete")
    if (
        summary.get("schema_version") != INCOME_SCHEMA_VERSION
        or summary.get("evidence_label") != INCOME_EVIDENCE_LABEL
        or summary.get("causal_claim") is not False
        or scope.get("city") != "New York City"
        or scope.get("population_claim") is not False
        or scope.get("individual_income_claim") is not False
        or "never a median" not in str(definitions.get("income_measure", ""))
        or spatial.get("equal_area_crs") != "EPSG:6933"
        or acs.get("median_of_medians_used") is not False
        or acs.get("totals_equal_sum_of_bins") is not True
        or allocation.get("all_sixteen_bins_conserved") is not True
        or allocation.get("households_conserved") is not True
        or allocation.get("median_of_medians_used") is not False
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
    ):
        raise ValueError("NYC neighborhood-income summary violates its ecological scope")
    total_trips = coverage.get("published_completed_trips")
    classified_trips = coverage.get("classified_published_completed_trips")
    unclassified_trips = coverage.get("unclassified_published_completed_trips")
    classified_zones = coverage.get("classified_panel_zones")
    observed_days = coverage.get("observed_days")
    panel_zone_rows = coverage.get("panel_zone_rows")
    nonresidential_panel_zones = coverage.get("dominant_nonresidential_panel_zones")
    nonresidential_trips = coverage.get(
        "dominant_nonresidential_published_completed_trips"
    )
    allocated_classified_zones = allocation.get("classified_zone_rows")
    allocated_high_zones = allocation.get("high_income_zone_rows")
    allocated_low_zones = allocation.get("low_income_zone_rows")
    ratio = coverage.get("classified_trip_coverage")
    if (
        any(
            isinstance(value, bool) or not isinstance(value, int)
            for value in (
                total_trips,
                classified_trips,
                unclassified_trips,
                classified_zones,
                observed_days,
                panel_zone_rows,
                nonresidential_panel_zones,
                nonresidential_trips,
                allocated_classified_zones,
                allocated_high_zones,
                allocated_low_zones,
            )
        )
        or total_trips <= 0
        or classified_trips <= 0
        or classified_trips + unclassified_trips != total_trips
        or classified_zones < 1
        or observed_days < 1
        or panel_zone_rows < classified_zones
        or not 0 <= nonresidential_panel_zones <= panel_zone_rows
        or not 0 <= nonresidential_trips <= total_trips
        or isinstance(ratio, bool)
        or not isinstance(ratio, (int, float))
        or not np.isfinite(ratio)
        or not np.isclose(ratio, classified_trips / total_trips)
        or not np.isclose(ratio, declared_coverage)
        or allocated_classified_zones != classified_zones
        or allocated_high_zones + allocated_low_zones != classified_zones
        or conservation.get("primary_classified_plus_unclassified_trip_sum")
        != total_trips
        or conservation.get("primary_nonresidential_classified_zones") != 0
    ):
        raise ValueError("NYC neighborhood-income coverage is inconsistent")
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
    association_numbers = (high_rate, low_rate, difference, rate_ratio)
    if (
        any(isinstance(value, bool) for value in association_numbers)
        or not all(isinstance(value, (int, float)) for value in association_numbers)
        or not np.isfinite(association_numbers).all()
        or low_rate <= 0
        or not np.isclose(difference, high_rate - low_rate)
        or not np.isclose(rate_ratio, high_rate / low_rate)
    ):
        raise ValueError("NYC neighborhood-income association arithmetic is inconsistent")

    primary_groups = primary_classification.get("groups")
    if not isinstance(primary_groups, dict) or set(primary_groups) != {
        "high_income_area",
        "low_income_area",
        "unclassified",
    }:
        raise ValueError("NYC neighborhood-income primary groups are incomplete")
    primary_group_values: dict[str, tuple[int, int, float]] = {}
    for group_name, group in primary_groups.items():
        if not isinstance(group, dict):
            raise ValueError("NYC neighborhood-income primary group is invalid")
        zones = group.get("panel_zones")
        trips = group.get("published_completed_trips")
        mean_rate = group.get("mean_published_completed_trips_per_zone_hour")
        trip_share = group.get("share_of_all_published_completed_trips")
        count_schema_invalid = (
            isinstance(zones, bool)
            or not isinstance(zones, int)
            or isinstance(trips, bool)
            or not isinstance(trips, int)
            or zones < 0
            or trips < 0
        )
        empty_group = not count_schema_invalid and zones == 0 and trips == 0
        mean_schema_valid = mean_rate is None and empty_group
        if isinstance(mean_rate, (int, float)) and not isinstance(mean_rate, bool):
            mean_schema_valid = bool(np.isfinite(mean_rate))
        if (
            count_schema_invalid
            or not mean_schema_valid
            or isinstance(trip_share, bool)
            or not isinstance(trip_share, (int, float))
            or not np.isfinite(trip_share)
            or not np.isclose(trip_share, trips / total_trips)
        ):
            raise ValueError("NYC neighborhood-income primary group is inconsistent")
        primary_group_values[group_name] = (
            zones,
            trips,
            float(mean_rate) if mean_rate is not None else float("nan"),
        )
    primary_high = primary_group_values["high_income_area"]
    primary_low = primary_group_values["low_income_area"]
    primary_unclassified = primary_group_values["unclassified"]
    if (
        primary_high[0] + primary_low[0] != classified_zones
        or primary_high[1] + primary_low[1] != classified_trips
        or primary_high[0] + primary_low[0] + primary_unclassified[0]
        != panel_zone_rows
        or primary_high[1] + primary_low[1] + primary_unclassified[1]
        != total_trips
        or not np.isclose(primary_high[2], high_rate)
        or not np.isclose(primary_low[2], low_rate)
    ):
        raise ValueError("NYC neighborhood-income primary arithmetic is inconsistent")

    proximity = uncertainty.get("threshold_proximity")
    proximity_keys = (
        "within_1000_usd",
        "within_2500_usd",
        "within_5000_usd",
        "within_10000_usd",
    )
    if not isinstance(proximity, dict) or not all(
        isinstance(proximity.get(key), dict) for key in proximity_keys
    ):
        raise ValueError("NYC neighborhood-income uncertainty audit is incomplete")
    prior_zones = -1
    prior_trips = -1
    prior_share = -1.0
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
            or share < prior_share
            or not np.isclose(share, trips / classified_trips)
        ):
            raise ValueError("NYC neighborhood-income uncertainty audit is inconsistent")
        prior_zones, prior_trips, prior_share = zones, trips, float(share)

    all_zone_sensitivity = sensitivity.get("all_zone_area_allocation")
    if not isinstance(all_zone_sensitivity, dict):
        raise ValueError("NYC neighborhood-income sensitivity is incomplete")
    sensitivity_groups = all_zone_sensitivity.get("groups")
    if not isinstance(sensitivity_groups, dict) or set(sensitivity_groups) != {
        "high_income_area",
        "low_income_area",
        "unclassified",
    }:
        raise ValueError("NYC neighborhood-income sensitivity groups are incomplete")
    sensitivity_group_values: dict[str, tuple[int, int, float, float]] = {}
    for group_name, group in sensitivity_groups.items():
        if not isinstance(group, dict):
            raise ValueError("NYC neighborhood-income sensitivity group is invalid")
        zones = group.get("panel_zones")
        trips = group.get("published_completed_trips")
        mean_rate = group.get("mean_published_completed_trips_per_zone_hour")
        trip_share = group.get("share_of_all_published_completed_trips")
        count_schema_invalid = (
            isinstance(zones, bool)
            or not isinstance(zones, int)
            or isinstance(trips, bool)
            or not isinstance(trips, int)
            or zones < 0
            or trips < 0
        )
        empty_group = not count_schema_invalid and zones == 0 and trips == 0
        mean_schema_valid = mean_rate is None and empty_group
        if isinstance(mean_rate, (int, float)) and not isinstance(mean_rate, bool):
            mean_schema_valid = bool(np.isfinite(mean_rate))
        if (
            count_schema_invalid
            or not mean_schema_valid
            or isinstance(trip_share, bool)
            or not isinstance(trip_share, (int, float))
            or not np.isfinite(trip_share)
            or not np.isclose(trip_share, trips / total_trips)
        ):
            raise ValueError("NYC neighborhood-income sensitivity group is inconsistent")
        sensitivity_group_values[group_name] = (
            zones,
            trips,
            float(mean_rate) if mean_rate is not None else float("nan"),
            float(trip_share),
        )
    sensitivity_classified_zones = all_zone_sensitivity.get("classified_panel_zones")
    sensitivity_classified_trips = all_zone_sensitivity.get(
        "classified_published_completed_trips"
    )
    sensitivity_coverage = all_zone_sensitivity.get("classified_trip_coverage")
    sensitivity_high_rate = all_zone_sensitivity.get(
        "mean_published_completed_trips_per_zone_hour_high_income_area"
    )
    sensitivity_low_rate = all_zone_sensitivity.get(
        "mean_published_completed_trips_per_zone_hour_low_income_area"
    )
    sensitivity_difference = all_zone_sensitivity.get(
        "high_minus_low_mean_published_completed_trips_per_zone_hour"
    )
    sensitivity_ratio = all_zone_sensitivity.get(
        "high_to_low_mean_published_completed_trips_per_zone_hour_ratio"
    )
    sensitivity_nonresidential_zones = all_zone_sensitivity.get(
        "dominant_nonresidential_zones_classified"
    )
    sensitivity_nonresidential_trips = all_zone_sensitivity.get(
        "dominant_nonresidential_classified_published_completed_trips"
    )
    sensitivity_numbers = (
        sensitivity_coverage,
        sensitivity_high_rate,
        sensitivity_low_rate,
        sensitivity_difference,
        sensitivity_ratio,
    )
    high_group = sensitivity_group_values["high_income_area"]
    low_group = sensitivity_group_values["low_income_area"]
    unclassified_group = sensitivity_group_values["unclassified"]
    if (
        all_zone_sensitivity.get("primary_result") is not False
        or all_zone_sensitivity.get(
            "ignored_primary_residential_taxi_zone_area_share_threshold"
        )
        != 0.5
        or isinstance(sensitivity_classified_zones, bool)
        or not isinstance(sensitivity_classified_zones, int)
        or isinstance(sensitivity_classified_trips, bool)
        or not isinstance(sensitivity_classified_trips, int)
        or isinstance(sensitivity_nonresidential_zones, bool)
        or not isinstance(sensitivity_nonresidential_zones, int)
        or isinstance(sensitivity_nonresidential_trips, bool)
        or not isinstance(sensitivity_nonresidential_trips, int)
        or sensitivity_nonresidential_zones < 0
        or sensitivity_nonresidential_trips < 0
        or any(isinstance(value, bool) for value in sensitivity_numbers)
        or not all(isinstance(value, (int, float)) for value in sensitivity_numbers)
        or not np.isfinite(sensitivity_numbers).all()
        or sensitivity_low_rate <= 0
        or sensitivity_classified_zones != high_group[0] + low_group[0]
        or sensitivity_classified_trips != high_group[1] + low_group[1]
        or panel_zone_rows != high_group[0] + low_group[0] + unclassified_group[0]
        or total_trips != high_group[1] + low_group[1] + unclassified_group[1]
        or not np.isclose(sensitivity_coverage, sensitivity_classified_trips / total_trips)
        or not np.isclose(sensitivity_high_rate, high_group[2])
        or not np.isclose(sensitivity_low_rate, low_group[2])
        or not np.isclose(sensitivity_difference, sensitivity_high_rate - sensitivity_low_rate)
        or not np.isclose(sensitivity_ratio, sensitivity_high_rate / sensitivity_low_rate)
        or sensitivity_nonresidential_zones
        != allocation.get("dominant_nonresidential_zones_classified_only_in_sensitivity")
        or conservation.get("sensitivity_group_trip_sum") != total_trips
    ):
        raise ValueError("NYC neighborhood-income sensitivity arithmetic is inconsistent")
    if (
        conservation.get("passes") is not True
        or any(
            conservation.get(key) != total_trips
            for key in ("zone_trip_sum", "daily_group_trip_sum", "monthly_group_trip_sum")
        )
    ):
        raise ValueError("NYC neighborhood-income trip conservation is inconsistent")

    role_frames: dict[str, tuple[Path, pd.DataFrame]] = {}
    for role in expected_file_roles - {"income_association_summary"}:
        role_frames[role] = _read_descriptive_role_csv(
            bundle,
            role,
            evidence_label=INCOME_EVIDENCE_LABEL,
            label=label,
        )
    monthly = role_frames["monthly_income_group_description"][1]
    daily = role_frames["daily_income_group_description"][1]
    required_groups = {"high_income_area", "low_income_area"}
    if (
        not required_groups.issubset(set(monthly["income_group"].astype(str)))
        or int(pd.to_numeric(monthly["published_completed_trips"], errors="coerce").sum())
        != total_trips
        or int(pd.to_numeric(daily["published_completed_trips"], errors="coerce").sum())
        != total_trips
    ):
        raise ValueError("NYC neighborhood-income tables disagree with their summary")

    source_manifest_path = _bundle_input_by_role(
        bundle, "verified_nyc_full_data_manifest", label
    )
    source_trip_sum, _ = _validate_nyc_panel_source_manifest(
        source_manifest_path,
        bundle=bundle,
        expected_panel_files=panel_files_verified,
        directly_declared_panel_inputs=panel_inputs,
    )
    if source_trip_sum != total_trips:
        raise ValueError("NYC neighborhood-income trips disagree with source lineage")
    provenance_roles = (
        (
            "official_tlc_taxi_zone_geometry",
            "tlc_taxi_zone_path",
            "tlc_taxi_zone_sha256",
        ),
        ("official_nyc_nta2020_geometry", "nyc_nta2020_path", "nyc_nta2020_sha256"),
        (
            "official_nyc_tract2020_to_nta2020_mapping",
            "nyc_tract_to_nta_path",
            "nyc_tract_to_nta_sha256",
        ),
        (
            "official_census_acs_2022_5yr_b19001_nyc_tract_slice",
            "acs_nyc_slice_path",
            "acs_nyc_slice_sha256",
        ),
        (
            "verified_nyc_full_data_manifest",
            "nyc_data_manifest_path",
            "nyc_data_manifest_sha256",
        ),
    )
    for role, path_key, hash_key in provenance_roles:
        input_path = _bundle_input_by_role(bundle, role, label)
        if (
            _portable_manifest_path(provenance_payload.get(path_key), path_key)
            != input_path.relative_to(bundle.root)
            or provenance_payload.get(hash_key) != sha256_file(input_path)
        ):
            raise ValueError("NYC neighborhood-income provenance disagrees with inputs")
    if (
        provenance_payload.get("hashes_recomputed") is not True
        or provenance_payload.get("panel_files_verified") != panel_files_verified
    ):
        raise ValueError("NYC neighborhood-income provenance checks are incomplete")
    limitations = _required_string_list(
        summary.get("limitations"), "NYC neighborhood-income limitations"
    )
    limitation_text = " ".join(limitations).lower()
    if "observational" not in limitation_text or "individual income" not in limitation_text:
        raise ValueError("NYC neighborhood-income limitations omit ecological boundaries")

    table_rows = pd.DataFrame(
        [
            {
                "area group": "High-income Taxi Zones",
                "mean published completed trips / zone-hour": high_rate,
            },
            {
                "area group": "Low-income Taxi Zones",
                "mean published completed trips / zone-hour": low_rate,
            },
            {
                "area group": "High minus low",
                "mean published completed trips / zone-hour": difference,
            },
            {
                "area group": "High / low ratio",
                "mean published completed trips / zone-hour": rate_ratio,
            },
        ]
    )
    summary_text = (
        f"The verified Taxi Zone→NTA→ACS B19001 enrichment classifies "
        f"{classified_zones:,} observed Taxi Zones and covers {float(ratio):.2%} of "
        f"{total_trips:,} published completed trips. Mean completed trips per zone-hour "
        f"were {float(high_rate):,.2f} in high-income areas and {float(low_rate):,.2f} "
        f"in low-income areas, a descriptive difference of {float(difference):,.2f} "
        f"(ratio {float(rate_ratio):.3f}). Income is an area-level, equal-area-allocated "
        "household distribution—not rider or driver income. Allocation assumes households "
        "are uniform within each NTA; ACS margins of error are retained at NTA level, but "
        "there is no exact margin of error for allocated Taxi Zone grouped medians. This "
        "ecological contrast does not identify a causal income effect. The explicitly "
        "non-primary all-zone allocation sensitivity reports a high-minus-low difference "
        f"of {float(sensitivity_difference):,.2f}, but it classifies "
        f"{sensitivity_nonresidential_zones:,} "
        "dominant-nonresidential zones representing "
        f"{sensitivity_nonresidential_trips:,} "
        "published completed trips. Because that sensitivity intentionally ignores the "
        "primary residential-eligibility gate, it is not the primary result."
    )
    provenance = "\n".join(
        [
            f"- NYC neighborhood-income manifest SHA-256: `{sha256_file(bundle.path)}`",
            f"- NYC neighborhood-income summary SHA-256: `{sha256_file(summary_path)}`",
            *[
                f"- NYC neighborhood-income input `{entry.get('role')}` SHA-256: `{sha256_file(path)}`"
                for path, entry in bundle.inputs.items()
            ],
        ]
    )
    return _NYCDescriptiveEnrichmentEvidence(
        summary=summary_text,
        table=markdown_table(table_rows, list(table_rows.columns)),
        limitations="\n".join(f"- {item}" for item in limitations),
        provenance=provenance,
    )


def _descriptive_status(path: str | Path | None) -> str:
    if path is None or not Path(path).is_file():
        return "Descriptive artifact not supplied."
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("evidence_type") != "empirical_association":
        raise ValueError("descriptive moments must be labeled empirical_association")
    panel_rows = payload.get("panel_rows")
    observed_trips = payload.get("total_observed_trips")
    panel_label = (
        _counted(int(panel_rows), "observed zone-time cell")
        if isinstance(panel_rows, int) and not isinstance(panel_rows, bool)
        else f"{panel_rows or '—'} observed zone-time cells"
    )
    trip_label = (
        _counted(int(observed_trips), "trip")
        if isinstance(observed_trips, int) and not isinstance(observed_trips, bool)
        else f"{observed_trips or '—'} trips"
    )
    return (
        f"The supplied public-data panel contains {panel_label} and {trip_label}. These are "
        "descriptive fixture quantities, not causal treatment effects or representative city totals."
    )


def _hte_status(
    summary_path: str | Path | None,
    calibration_path: str | Path | None,
    stability_path: str | Path | None,
) -> tuple[str, str]:
    """Validate and summarize known-truth heterogeneous-effect recovery artifacts."""

    if summary_path is None or not Path(summary_path).is_file():
        return (
            "HTE recovery artifacts were not supplied; no heterogeneous-effect claim is issued.",
            "No HTE calibration table was available.",
        )
    payload = json.loads(Path(summary_path).read_text(encoding="utf-8"))
    if payload.get("evidence_type") != "semi_synthetic_hte_known_truth_recovery":
        raise ValueError("HTE summary must be labeled semi_synthetic_hte_known_truth_recovery")
    if payload.get("target_estimand") != "controlled_zone_direct_effect":
        raise ValueError("HTE summary has an unsupported or missing target estimand")
    required_summary = {
        "rows",
        "bias",
        "rmse",
        "fold_mean_cate_sd",
        "known_truth_sd",
        "oracle_constant_effect_rmse",
        "predicted_truth_correlation",
        "predicted_truth_rank_correlation",
        "hte_beats_oracle_constant",
        "recovery_gate",
        "crossfit_group",
        "interference",
        "persistence",
    }
    missing_summary = required_summary.difference(payload)
    if missing_summary:
        raise ValueError(f"HTE summary missing fields: {sorted(missing_summary)}")
    if payload["crossfit_group"] != "geographic_randomization_cluster":
        raise ValueError("HTE recovery must hold out geographic randomization clusters")
    numeric_summary = {
        key: float(payload[key])
        for key in (
            "rows",
            "bias",
            "rmse",
            "fold_mean_cate_sd",
            "known_truth_sd",
            "oracle_constant_effect_rmse",
            "predicted_truth_correlation",
            "predicted_truth_rank_correlation",
            "interference",
            "persistence",
        )
    }
    if not all(np.isfinite(value) for value in numeric_summary.values()):
        raise ValueError("HTE recovery summary contains non-finite diagnostics")
    if numeric_summary["rows"] <= 0 or not numeric_summary["rows"].is_integer():
        raise ValueError("HTE recovery rows must be a positive integer")
    if numeric_summary["interference"] != 0.0 or numeric_summary["persistence"] != 0.0:
        raise ValueError(
            "HTE recovery is validated only with interference and persistence disabled"
        )
    if not isinstance(payload["hte_beats_oracle_constant"], bool):
        raise ValueError("HTE recovery gate must be a JSON boolean")
    if payload["recovery_gate"] != "rmse_below_oracle_constant_effect_rmse":
        raise ValueError("HTE recovery summary has an unsupported recovery gate")
    expected_gate = (
        numeric_summary["rmse"]
        < numeric_summary["oracle_constant_effect_rmse"]
    )
    if payload["hte_beats_oracle_constant"] != expected_gate:
        raise ValueError("HTE recovery gate is inconsistent with the supplied RMSE values")
    if calibration_path is None or not Path(calibration_path).is_file():
        raise ValueError("HTE calibration artifact is required when an HTE summary is supplied")
    if stability_path is None or not Path(stability_path).is_file():
        raise ValueError("HTE fold-stability artifact is required when an HTE summary is supplied")

    calibration = pd.read_csv(calibration_path)
    calibration_required = {
        "score_bin",
        "mean_predicted_cate",
        "mean_known_truth",
        "mean_error",
        "rmse",
        "rows",
    }
    missing_calibration = calibration_required.difference(calibration.columns)
    if missing_calibration or calibration.empty:
        raise ValueError(
            f"HTE calibration artifact missing columns: {sorted(missing_calibration)}"
        )
    stability = pd.read_csv(stability_path)
    stability_required = {
        "crossfit_fold",
        "mean_predicted_cate",
        "mean_known_truth",
        "mean_error",
        "rmse",
        "rows",
    }
    missing_stability = stability_required.difference(stability.columns)
    if missing_stability or stability.empty:
        raise ValueError(
            f"HTE stability artifact missing columns: {sorted(missing_stability)}"
        )
    expected_rows = int(numeric_summary["rows"])
    for label, frame in (("calibration", calibration), ("stability", stability)):
        counts = pd.to_numeric(frame["rows"], errors="coerce")
        numeric_columns = [
            "mean_predicted_cate",
            "mean_known_truth",
            "mean_error",
            "rmse",
        ]
        numeric_values = frame[numeric_columns].apply(pd.to_numeric, errors="coerce")
        if (
            counts.isna().any()
            or int(counts.sum()) != expected_rows
            or not np.isfinite(numeric_values.to_numpy(dtype=float)).all()
        ):
            raise ValueError(f"HTE {label} artifact has inconsistent rows or diagnostics")
    recovery_conclusion = (
        "It clears the predeclared oracle-constant RMSE gate, but remains conditional on "
        "this simulator."
        if payload["hte_beats_oracle_constant"]
        else "It does not beat the oracle constant-effect baseline and is not decision-ready."
    )
    summary = (
        "The cross-fitted semi-synthetic HTE benchmark targets the aggregate "
        "`controlled_zone_direct_effect` with geographic randomization clusters held "
        f"out. Across {int(payload.get('rows', 0))} held-out rows, generated bias is "
        f"{float(payload.get('bias', np.nan)):.4f} and RMSE is "
        f"{float(payload.get('rmse', np.nan)):.4f}. The SD of fold-level mean CATE is "
        f"{float(payload.get('fold_mean_cate_sd', np.nan)):.4f}. The oracle constant-effect "
        f"RMSE is {float(payload.get('oracle_constant_effect_rmse', np.nan)):.4f}; Pearson "
        f"and rank correlations with truth are "
        f"{float(payload.get('predicted_truth_correlation', np.nan)):.4f} and "
        f"{float(payload.get('predicted_truth_rank_correlation', np.nan)):.4f}. "
        f"{recovery_conclusion} These are known-truth model-recovery diagnostics, not "
        "public-data causal estimates."
    )
    table = markdown_table(
        calibration.sort_values("score_bin"),
        [
            "score_bin",
            "mean_predicted_cate",
            "mean_known_truth",
            "mean_error",
            "rmse",
            "rows",
        ],
    )
    return summary, table


def generate_report_bundle(
    benchmark_path: str | Path,
    *,
    output_directory: str | Path,
    policy_path: str | Path | None = None,
    descriptive_path: str | Path | None = None,
    calibration_path: str | Path | None = None,
    failures_path: str | Path | None = None,
    hte_summary_path: str | Path | None = None,
    hte_calibration_path: str | Path | None = None,
    hte_stability_path: str | Path | None = None,
    nyc_full_validation_path: str | Path | None = None,
    nyc_full_manifest_path: str | Path | None = None,
    treatment_version_policy_path: str | Path | None = None,
    treatment_version_policy_manifest_path: str | Path | None = None,
    interference_summary_path: str | Path | None = None,
    interference_manifest_path: str | Path | None = None,
    nyc_simulation_anchor_path: str | Path | None = None,
    nyc_simulation_anchor_manifest_path: str | Path | None = None,
    nyc_benchmark_manifest_path: str | Path | None = None,
    nyc_graph_benchmark_manifest_path: str | Path | None = None,
    equilibrium_manifest_path: str | Path | None = None,
    nyc_weather_manifest_path: str | Path | None = None,
    nyc_events_manifest_path: str | Path | None = None,
    nyc_income_manifest_path: str | Path | None = None,
    target_estimand: str | None = None,
) -> dict[str, Path]:
    """Generate technical, executive, and appendix artifacts from computed inputs."""

    benchmark_file = Path(benchmark_path)
    benchmark = pd.read_csv(benchmark_file)
    _validate_benchmark(benchmark)
    available_targets = sorted(benchmark["target_estimand"].dropna().astype(str).unique())
    selected_target = target_estimand or available_targets[0]
    relevant = benchmark.loc[benchmark["target_estimand"] == selected_target].copy()
    if relevant.empty:
        raise ValueError(f"no benchmark rows target {selected_target!r}")

    recommendation, recommendation_text = _recommendation_status(benchmark, selected_target)
    policy_table, policy_summary = _policy_table(policy_path)
    treatment_version_evidence = _treatment_version_policy_status(
        treatment_version_policy_path,
        treatment_version_policy_manifest_path,
    )
    treatment_version_summary = (
        treatment_version_evidence.summary
        if treatment_version_evidence is not None
        else (
            "Paired rider/driver/bundled policy sensitivity artifacts were not supplied; "
            "no cross-version policy claim is issued."
        )
    )
    treatment_version_table = (
        treatment_version_evidence.table
        if treatment_version_evidence is not None
        else "No treatment-version sensitivity table was available."
    )
    interference_evidence = _interference_status(
        interference_summary_path,
        interference_manifest_path,
    )
    interference_summary = (
        interference_evidence.summary
        if interference_evidence is not None
        else (
            "A verified exposure-aware benchmark was not supplied; no claim is issued "
            "about recovery under mapped interference or treatment history."
        )
    )
    interference_table = (
        interference_evidence.table
        if interference_evidence is not None
        else "No mapped-interference recovery table was available."
    )
    descriptive_summary = _descriptive_status(descriptive_path)
    nyc_full_evidence = _nyc_full_status(
        nyc_full_validation_path,
        nyc_full_manifest_path,
    )
    nyc_full_summary = (
        nyc_full_evidence.summary
        if nyc_full_evidence is not None
        else (
            "Verified NYC full-month artifacts were not supplied; no full-month empirical "
            "scale or laptop-resource claim is issued."
        )
    )
    nyc_full_limitations = (
        nyc_full_evidence.limitations
        if nyc_full_evidence is not None
        else (
            "- No verified NYC full-month evidence was supplied to this report; the "
            "bounded fixture remains the only empirical input represented here."
        )
    )
    nyc_anchor_evidence = _nyc_anchor_status(
        nyc_simulation_anchor_path,
        nyc_simulation_anchor_manifest_path,
    )
    nyc_anchor_summary = (
        nyc_anchor_evidence.summary
        if nyc_anchor_evidence is not None
        else (
            "A validated NYC simulation anchor was not supplied. Simulator scale and "
            "heterogeneity parameters therefore remain disconnected from the full-month "
            "descriptive bundle in this report."
        )
    )
    nyc_anchor_limitations = (
        nyc_anchor_evidence.limitations
        if nyc_anchor_evidence is not None
        else "- No validated NYC semi-synthetic simulation anchor was supplied."
    )
    nyc_benchmark_evidence = _nyc_informed_benchmark_status(
        nyc_benchmark_manifest_path
    )
    nyc_benchmark_summary = (
        nyc_benchmark_evidence.summary
        if nyc_benchmark_evidence is not None
        else (
            "A verified NYC-informed known-truth benchmark was not supplied; no claim "
            "is issued about estimator recovery under NYC-anchored simulator scale."
        )
    )
    nyc_benchmark_table = (
        nyc_benchmark_evidence.table
        if nyc_benchmark_evidence is not None
        else "No NYC-informed known-truth recovery table was available."
    )
    nyc_benchmark_limitations = (
        nyc_benchmark_evidence.limitations
        if nyc_benchmark_evidence is not None
        else "- NYC-informed known-truth benchmark: not supplied."
    )
    nyc_graph_evidence = _nyc_graph_status(nyc_graph_benchmark_manifest_path)
    nyc_graph_summary = (
        nyc_graph_evidence.summary
        if nyc_graph_evidence is not None
        else (
            "A verified NYC OD-graph known-truth benchmark was not supplied; no claim "
            "is issued about mapped exposure recovery on NYC graph geometry."
        )
    )
    nyc_graph_table = (
        nyc_graph_evidence.table
        if nyc_graph_evidence is not None
        else "No NYC OD-graph recovery table was available."
    )
    nyc_graph_limitations = (
        nyc_graph_evidence.limitations
        if nyc_graph_evidence is not None
        else "- NYC OD-graph known-truth benchmark: not supplied."
    )
    equilibrium_evidence = _equilibrium_status(equilibrium_manifest_path)
    equilibrium_summary = (
        equilibrium_evidence.summary
        if equilibrium_evidence is not None
        else (
            "A verified fixed-point equilibrium benchmark was not supplied; no "
            "equilibrium, welfare, or market-clearing claim is issued."
        )
    )
    equilibrium_table = (
        equilibrium_evidence.table
        if equilibrium_evidence is not None
        else "No fixed-point equilibrium ledger was available."
    )
    equilibrium_limitations = (
        equilibrium_evidence.limitations
        if equilibrium_evidence is not None
        else "- Fixed-point equilibrium benchmark: not supplied."
    )
    nyc_weather_evidence = _nyc_weather_status(nyc_weather_manifest_path)
    nyc_weather_summary = (
        nyc_weather_evidence.summary
        if nyc_weather_evidence is not None
        else (
            "Verified NYC NOAA weather artifacts were not supplied; no weather-demand "
            "association or weather-effect claim is issued."
        )
    )
    nyc_weather_table = (
        nyc_weather_evidence.table
        if nyc_weather_evidence is not None
        else "No NYC NOAA weather association table was available."
    )
    nyc_weather_limitations = (
        nyc_weather_evidence.limitations
        if nyc_weather_evidence is not None
        else "- NYC NOAA weather evidence: not supplied."
    )
    nyc_events_evidence = _nyc_events_status(nyc_events_manifest_path)
    nyc_events_summary = (
        nyc_events_evidence.summary
        if nyc_events_evidence is not None
        else (
            "Verified NYC calendar/event artifacts were not supplied; no permitted-event, "
            "holiday, attendance, or event-effect claim is issued."
        )
    )
    nyc_events_table = (
        nyc_events_evidence.table
        if nyc_events_evidence is not None
        else "No NYC calendar/event association table was available."
    )
    nyc_events_limitations = (
        nyc_events_evidence.limitations
        if nyc_events_evidence is not None
        else "- NYC official-calendar and permitted-event evidence: not supplied."
    )
    nyc_income_evidence = _nyc_income_status(nyc_income_manifest_path)
    nyc_income_summary = (
        nyc_income_evidence.summary
        if nyc_income_evidence is not None
        else (
            "Verified NYC neighborhood-income artifacts were not supplied; no high/low-"
            "income-area heterogeneity or income-effect claim is issued."
        )
    )
    nyc_income_table = (
        nyc_income_evidence.table
        if nyc_income_evidence is not None
        else "No NYC neighborhood-income descriptive table was available."
    )
    nyc_income_limitations = (
        nyc_income_evidence.limitations
        if nyc_income_evidence is not None
        else "- NYC neighborhood-income evidence: not supplied."
    )
    hte_summary, hte_table = _hte_status(
        hte_summary_path,
        hte_calibration_path,
        hte_stability_path,
    )
    benchmark_columns = [
        column
        for column in (
            "scenario",
            "varied_dimension",
            "treatment_version",
            "spillover_strength",
            "persistence",
            "treatment_duration",
            "washout_periods",
            "treatment_saturation",
            "configured_geo_clusters",
            "cluster_size",
            "n_zones",
            "budget",
            "budget_binding_rate",
            "design",
            "estimator",
            "identified",
            "inference_valid",
            "fit_complete",
            "applicable",
            "applicability_reason",
            "attempted_fits",
            "successful_fits",
            "bias",
            "diagnostic_mean_gap",
            "rmse",
            "coverage",
            "power",
        )
        if column in relevant
    ]
    benchmark_table = markdown_table(
        relevant.sort_values(["scenario", "design", "estimator"]),
        benchmark_columns,
    )
    provenance = "\n".join(
        [
            f"- Benchmark SHA-256: `{sha256_file(benchmark_file)}`",
            _optional_hash(policy_path, "Policy"),
            _optional_hash(descriptive_path, "Descriptive moments"),
            _optional_hash(calibration_path, "Calibration"),
            _optional_hash(failures_path, "Fit failures"),
            _optional_hash(hte_summary_path, "HTE recovery summary"),
            _optional_hash(hte_calibration_path, "HTE calibration"),
            _optional_hash(hte_stability_path, "HTE fold stability"),
            (
                nyc_full_evidence.provenance
                if nyc_full_evidence is not None
                else "- NYC full-month evidence: not supplied"
            ),
            (
                treatment_version_evidence.provenance
                if treatment_version_evidence is not None
                else "- Treatment-version policy sensitivity: not supplied"
            ),
            (
                interference_evidence.provenance
                if interference_evidence is not None
                else "- Exposure-aware interference benchmark: not supplied"
            ),
            (
                nyc_anchor_evidence.provenance
                if nyc_anchor_evidence is not None
                else "- NYC semi-synthetic simulation anchor: not supplied"
            ),
            (
                nyc_benchmark_evidence.provenance
                if nyc_benchmark_evidence is not None
                else "- NYC-informed known-truth benchmark: not supplied"
            ),
            (
                nyc_graph_evidence.provenance
                if nyc_graph_evidence is not None
                else "- NYC OD-graph known-truth benchmark: not supplied"
            ),
            (
                equilibrium_evidence.provenance
                if equilibrium_evidence is not None
                else "- Fixed-point equilibrium benchmark: not supplied"
            ),
            (
                nyc_weather_evidence.provenance
                if nyc_weather_evidence is not None
                else "- NYC NOAA weather evidence: not supplied"
            ),
            (
                nyc_events_evidence.provenance
                if nyc_events_evidence is not None
                else "- NYC official-calendar and permitted-event evidence: not supplied"
            ),
            (
                nyc_income_evidence.provenance
                if nyc_income_evidence is not None
                else "- NYC neighborhood-income evidence: not supplied"
            ),
        ]
    )
    fit_failures = (
        int(pd.to_numeric(relevant["failed_fits"], errors="coerce").fillna(0).sum())
        if "failed_fits" in relevant
        else 0
    )
    fit_failure_label = _counted(fit_failures, "failed attempted fit")
    identified_rows = (
        int(relevant["identified"].fillna(False).astype(bool).sum())
        if "identified" in relevant
        else 0
    )
    valid_rows = (
        int(relevant["inference_valid"].fillna(False).astype(bool).sum())
        if "inference_valid" in relevant
        else 0
    )
    selection_details = (
        "No row passed the complete cross-scenario recommendation gate."
        if recommendation is None
        else (
            f"The displayed worst case is `{recommendation.get('scenario', '—')}` with "
            f"generated RMSE {float(recommendation['rmse']):.4f}, coverage "
            f"{float(recommendation['coverage']):.4f}, and power "
            f"{float(recommendation['power']):.4f}."
        )
    )

    technical = f"""# Generated Technical Report

> Evidence separation: public trip quantities are empirical/descriptive; benchmark and policy quantities are semi-synthetic causal results under known simulator assumptions. No observational fare association is interpreted causally.

## Target and decision gate

Primary generated target: `{selected_target}`.

{recommendation_text}

{selection_details}

## Public-data scale anchor

{descriptive_summary}

The calibration artifact is an illustrative scale anchor. Available drivers, behavioral response, spillovers, persistence, and welfare are not identified by the public fixture.

### Verified NYC full-month descriptive evidence

{nyc_full_summary}

### Verified NYC NOAA weather associations

{nyc_weather_summary}

{nyc_weather_table}

### Verified NYC calendar and permitted-event associations

{nyc_events_summary}

{nyc_events_table}

### Verified NYC neighborhood-income heterogeneity

{nyc_income_summary}

{nyc_income_table}

### NYC-informed semi-synthetic scale anchor

{nyc_anchor_summary}

### NYC-informed known-truth design benchmark

{nyc_benchmark_summary}

{nyc_benchmark_table}

### NYC OD-graph mapped-interference benchmark

{nyc_graph_summary}

{nyc_graph_table}

## Monte Carlo results

The artifact contains {_counted(len(relevant), 'summary row')}; {identified_rows} pass the row-level identification screen, {valid_rows} pass the assignment-aware inference screen, and the fit ledger records {fit_failure_label}. Bias is populated only for rows whose estimate and structural truth share the declared target; other differences are labeled diagnostic gaps.

{benchmark_table}

### Exposure-aware interference recovery

{interference_summary}

{interference_table}

## Theoretical fixed-point equilibrium benchmark

{equilibrium_summary}

{equilibrium_table}

## Heterogeneous-effect recovery

{hte_summary}

{hte_table}

## Honest-holdout policy evaluation

{policy_table}

{policy_summary}

Each nonzero policy is re-evaluated through the marketplace simulator on unseen seeds. The policy learner does not fit on structural truth, and independent summation of unit effects is not used as the decision value.

### Treatment-version policy sensitivity

{treatment_version_summary}

{treatment_version_table}

## Identification and limitations

- Interference and persistence are varied factorially, with additional one-at-a-time duration, cluster-count, saturation, washout, and shared-budget diagnostics; failure of a design in any declared scenario blocks a robust recommendation.
- Few-cluster or incorrectly clustered uncertainty is excluded from selection even when a point estimate is shown.
- The Chicago fixture is deterministic and nonrepresentative; it validates the pipeline but not transportability.
- The time-stratified fixture panel contains occupied cells only; absent zone-hours are unknown rather than zero-demand observations.
{nyc_full_limitations}
{nyc_anchor_limitations}
{nyc_weather_limitations}
{nyc_events_limitations}
{nyc_income_limitations}
{nyc_benchmark_limitations}
{nyc_graph_limitations}
{equilibrium_limitations}
- Simulator welfare and policy value are conditional on the configured reduced-form marketplace model.

## Reproducibility inputs

{provenance}

This report was generated from the machine-readable artifacts above; numerical results are not embedded in the template.
"""

    executive = f"""# Generated Product Decision Memo

## Decision

{recommendation_text}

{policy_summary}

{treatment_version_summary}

## Heterogeneity evidence

{hte_summary}

## Exposure-aware design evidence

{interference_summary}

### NYC OD-graph evidence

{nyc_graph_summary}

### NYC-informed known-truth recovery

{nyc_benchmark_summary}

## Theoretical equilibrium evidence

{equilibrium_summary}

## Success metric

Use full-horizon incremental completed trips, modeled contribution, and credible welfare per incremental dollar as decision metrics. Track wait time, rider service, driver earnings/utilization, geographic displacement, compliance, and budget delivery as guardrails.

## Experiment conditions

The primary causal target is `{selected_target}` over a fixed all-zone, full-horizon population. Duration, block size, and washout must be predeclared from persistence sensitivity and operational constraints; they are not chosen from observational public-trip associations.

## Go/no-go rule

Proceed to an operational pilot only after assignment integrity, exposure logging, enough effective randomized clusters, valid uncertainty, budget feasibility, and holdout policy stability are demonstrated. If no candidate passes every declared scenario, the generated decision is **no robust rollout recommendation**.

## Evidence boundary

Public data provide descriptive demand, fare, geography, and measurement-quality facts only. All causal performance values here are semi-synthetic and require validation in a properly randomized live experiment before launch.

## Verified NYC full-month descriptive evidence

{nyc_full_summary}

## Verified NYC NOAA weather associations

{nyc_weather_summary}

## Verified NYC calendar and permitted-event associations

{nyc_events_summary}

## Verified NYC neighborhood-income heterogeneity

{nyc_income_summary}

## NYC-informed semi-synthetic scale anchor

{nyc_anchor_summary}

## Reproducibility inputs

{provenance}
"""

    appendix = f"""# Generated Decision Appendix

## Selected estimand

`{selected_target}`

## Recommendation gate

{recommendation_text}

## Benchmark table

{benchmark_table}

## Exposure-aware interference recovery

{interference_summary}

{interference_table}

## NYC-informed known-truth design benchmark

{nyc_benchmark_summary}

{nyc_benchmark_table}

## NYC OD-graph mapped-interference benchmark

{nyc_graph_summary}

{nyc_graph_table}

## Theoretical fixed-point equilibrium benchmark

{equilibrium_summary}

{equilibrium_table}

## Policy table

{policy_table}

## Treatment-version policy sensitivity

{treatment_version_summary}

{treatment_version_table}

## HTE known-truth recovery

{hte_summary}

{hte_table}

## Verified NYC full-month descriptive evidence

{nyc_full_summary}

## Verified NYC NOAA weather associations

{nyc_weather_summary}

{nyc_weather_table}

## Verified NYC calendar and permitted-event associations

{nyc_events_summary}

{nyc_events_table}

## Verified NYC neighborhood-income heterogeneity

{nyc_income_summary}

{nyc_income_table}

## NYC-informed semi-synthetic scale anchor

{nyc_anchor_summary}

## Input hashes

{provenance}
"""

    destination = Path(output_directory)
    destination.mkdir(parents=True, exist_ok=True)
    paths = {
        "technical": destination / "technical_report_generated.md",
        "executive": destination / "product_decision_memo_generated.md",
        "appendix": destination / "generated_decision_appendix.md",
    }
    paths["technical"].write_text(technical, encoding="utf-8")
    paths["executive"].write_text(executive, encoding="utf-8")
    paths["appendix"].write_text(appendix, encoding="utf-8")
    return paths
