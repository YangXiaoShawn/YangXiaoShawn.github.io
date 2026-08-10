from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml
from test_nyc_simulation import write_nyc_calibration_test_bundle

import casuallab.nyc_benchmark as nyc_benchmark_module
from casuallab.config import DesignConfig, SimulationConfig
from casuallab.data import sha256_file
from casuallab.nyc_benchmark import (
    NYC_BENCHMARK_EVIDENCE_TYPE,
    NYCBenchmarkConfig,
    run_nyc_informed_marketplace_benchmark,
    validate_nyc_benchmark_anchor,
    write_nyc_benchmark_artifacts,
)
from casuallab.nyc_simulation import (
    CAUSAL_ASSUMPTION_FIELDS,
    NYCSimulationAnchorSettings,
    build_nyc_simulation_anchor,
)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _entry(path: Path, root: Path) -> dict[str, object]:
    return {
        "path": str(path.relative_to(root)),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def _verified_anchor_artifacts(tmp_path: Path) -> dict[str, object]:
    calibration_bundle = write_nyc_calibration_test_bundle(tmp_path)
    calibration_path = calibration_bundle["calibration"]
    calibration = json.loads(calibration_path.read_text(encoding="utf-8"))
    zones = 16
    periods = 744
    panel_cells = zones * periods
    trips = panel_cells * 5
    calibration["conservation"].update(
        {
            "raw_rows_declared": trips,
            "clean_rows": trips,
            "zone_trip_sum": trips,
            "od_trip_sum": trips,
            "zones": zones,
            "periods": periods,
            "zone_rows": panel_cells,
        }
    )
    calibration["trip_level_descriptive_moments"]["trip_rows"] = trips
    calibration["zone_hour_variance_decomposition"].update(
        {
            "zones": zones,
            "periods": periods,
            "panel_cells": panel_cells,
            "occupied_cells": panel_cells - 4,
            "total_completed_trips": trips,
            "mean_completed_trips_per_zone_hour": 5.0,
        }
    )
    _write_json(calibration_path, calibration)
    calibration_manifest_path = calibration_bundle["bundle_manifest"]
    calibration_manifest = json.loads(
        calibration_manifest_path.read_text(encoding="utf-8")
    )
    for index, entry in enumerate(calibration_manifest["files"]):
        if entry["path"] == "calibration.json":
            calibration_manifest["files"][index] = _entry(
                calibration_path, calibration_path.parent
            )
    _write_json(calibration_manifest_path, calibration_manifest)

    template = SimulationConfig(
        n_zones=4,
        n_periods=48,
        spillover_strength=0.15,
        persistence=0.25,
        budget=5000.0,
        seed=202503,
        design=DesignConfig(
            n_clusters=2,
            treatment_duration=4,
            budget=5000.0,
            seed=202503,
        ),
    )
    template_path = tmp_path / "configs" / "simulation.yaml"
    template_path.parent.mkdir(parents=True)
    template_path.write_text(
        yaml.safe_dump({"simulation": template.to_dict()}, sort_keys=False),
        encoding="utf-8",
    )
    anchor = build_nyc_simulation_anchor(
        calibration_path,
        project_root=tmp_path,
        manifest_path=calibration_manifest_path,
        settings=NYCSimulationAnchorSettings(
            target_n_zones=16,
            target_n_periods=48,
            seed=202503,
        ),
        assumption_template=template,
    )
    anchor_path = tmp_path / "artifacts" / "simulation_anchor" / "anchor.json"
    _write_json(anchor_path, anchor)
    anchor_manifest_path = anchor_path.with_name("manifest.json")
    _write_json(
        anchor_manifest_path,
        {
            "files": [
                _entry(calibration_path, tmp_path),
                _entry(calibration_manifest_path, tmp_path),
                _entry(anchor_path, tmp_path),
                _entry(template_path, tmp_path),
            ],
            "metadata": {
                "evidence_label": anchor["evidence_label"],
                "causal_claim": False,
                "status": anchor["status"],
                "calibration_sha256": sha256_file(calibration_path),
                "calibration_manifest_sha256": sha256_file(
                    calibration_manifest_path
                ),
                "simulation_config_sha256": sha256_file(template_path),
                "source_data_manifest_sha256": anchor["integrity"][
                    "source_data_manifest_sha256"
                ],
            },
        },
    )
    return {
        "root": tmp_path,
        "anchor": anchor,
        "anchor_path": anchor_path,
        "anchor_manifest_path": anchor_manifest_path,
        "template": template,
    }


def _laptop_config() -> NYCBenchmarkConfig:
    return NYCBenchmarkConfig(
        replications=2,
        seed=7701,
        n_zones=16,
        n_periods=32,
        max_planned_fits=64,
    )


def test_nyc_benchmark_is_deterministic_and_passes_known_truth_target_gates(
    tmp_path: Path,
) -> None:
    artifacts = _verified_anchor_artifacts(tmp_path)
    kwargs = {
        "config": _laptop_config(),
        "project_root": tmp_path,
    }
    first = run_nyc_informed_marketplace_benchmark(
        artifacts["anchor_path"], artifacts["anchor_manifest_path"], **kwargs
    )
    second = run_nyc_informed_marketplace_benchmark(
        artifacts["anchor_path"], artifacts["anchor_manifest_path"], **kwargs
    )

    pd.testing.assert_frame_equal(first.records, second.records)
    pd.testing.assert_frame_equal(first.summary, second.summary)
    pd.testing.assert_frame_equal(first.failures, second.failures)
    pd.testing.assert_frame_equal(first.fit_ledger, second.fit_ledger)
    assert first.metadata == second.metadata
    json.dumps(first.metadata, allow_nan=False)
    assert first.metadata["anchor"]["anchor_path"] == str(
        Path(artifacts["anchor_path"]).relative_to(tmp_path)
    )
    assert first.metadata["anchor"]["anchor_manifest_path"] == str(
        Path(artifacts["anchor_manifest_path"]).relative_to(tmp_path)
    )
    assert first.failures.empty
    assert first.metadata["target_gates"]["all_passed"] is True
    assert all(first.metadata["target_gates"].values())
    assert set(first.records["evidence_type"]) == {NYC_BENCHMARK_EVIDENCE_TYPE}
    assert set(first.summary["evidence_type"]) == {NYC_BENCHMARK_EVIDENCE_TYPE}
    assert first.records["nyc_empirical_causal_effect"].eq(False).all()
    assert first.records["simulator_known_truth"].all()
    assert np.isfinite(first.records["truth"]).all()
    assert first.records["target_estimand"].eq("market_total_effect").all()
    assert first.records["n_zones"].eq(16).all()
    assert first.records["n_periods"].eq(32).all()
    assert first.summary.loc[
        first.summary["identified"].astype(bool), "rmse"
    ].notna().all()
    assert first.summary.loc[
        ~first.summary["identified"].astype(bool),
        ["bias", "rmse", "coverage", "power"],
    ].isna().all().all()
    assert (
        first.summary["identified"].astype(bool)
        & first.summary["inference_valid"].astype(bool)
    ).any()


def test_causal_assumptions_remain_explicit_and_are_never_labeled_nyc_effects(
    tmp_path: Path,
) -> None:
    artifacts = _verified_anchor_artifacts(tmp_path)
    result = run_nyc_informed_marketplace_benchmark(
        artifacts["anchor_path"],
        artifacts["anchor_manifest_path"],
        project_root=tmp_path,
        config=_laptop_config(),
    )
    anchor_config = result.metadata["anchor"]["simulation_config"]
    base_config = result.metadata["benchmark_base_simulation_config"]
    for field in CAUSAL_ASSUMPTION_FIELDS:
        assert base_config[field] == anchor_config[field]
    scenarios = result.metadata["scenario_causal_provenance"]
    assert scenarios["anchor_explicit_assumptions"][
        "anchor_causal_assumptions_preserved"
    ] is True
    reference_overrides = scenarios["no_interference_no_carryover"][
        "causal_overrides"
    ]
    assert set(reference_overrides) == {
        "spillover_strength",
        "persistence",
        "rider_substitution",
        "driver_mobility",
    }
    assert result.metadata["nyc_empirical_causal_effect"] is False
    assert result.metadata["simulator_known_truth"] is True
    assert "not an NYC causal estimate" in result.metadata["known_truth_scope"]
    assert result.metadata["effective_overrides"]["n_periods"]["effective"] == 32
    assert result.metadata["effective_overrides"]["budget"]["effective"] is None


def test_anchor_file_tampering_is_rejected_by_manifest_hash(tmp_path: Path) -> None:
    artifacts = _verified_anchor_artifacts(tmp_path)
    anchor_path = artifacts["anchor_path"]
    original = anchor_path.read_text(encoding="utf-8")
    tampered = original.replace('"base_fare": 20.0', '"base_fare": 21.0', 1)
    assert tampered != original
    assert len(tampered.encode()) == len(original.encode())
    anchor_path.write_text(tampered, encoding="utf-8")

    with pytest.raises(ValueError, match="anchor manifest SHA-256 mismatch"):
        validate_nyc_benchmark_anchor(
            anchor_path,
            artifacts["anchor_manifest_path"],
            project_root=tmp_path,
        )


def test_coordinated_causal_tampering_fails_exact_reconstruction(tmp_path: Path) -> None:
    artifacts = _verified_anchor_artifacts(tmp_path)
    anchor_path = artifacts["anchor_path"]
    anchor = json.loads(anchor_path.read_text(encoding="utf-8"))
    anchor["simulation_config"]["direct_demand_effect"] = 0.91
    anchor["field_provenance"]["explicit_assumptions"]["direct_demand_effect"][
        "value"
    ] = 0.91
    _write_json(anchor_path, anchor)
    manifest_path = artifacts["anchor_manifest_path"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for index, entry in enumerate(manifest["files"]):
        if entry["path"] == str(anchor_path.relative_to(tmp_path)):
            manifest["files"][index] = _entry(anchor_path, tmp_path)
    _write_json(manifest_path, manifest)

    with pytest.raises(ValueError, match="does not exactly reconstruct"):
        run_nyc_informed_marketplace_benchmark(
            anchor_path,
            manifest_path,
            project_root=tmp_path,
            config=_laptop_config(),
        )


def test_laptop_safety_limits_fail_before_monte_carlo(tmp_path: Path) -> None:
    artifacts = _verified_anchor_artifacts(tmp_path)

    with pytest.raises(ValueError, match="max_panel_cells"):
        run_nyc_informed_marketplace_benchmark(
            artifacts["anchor_path"],
            artifacts["anchor_manifest_path"],
            project_root=tmp_path,
            config=NYCBenchmarkConfig(
                replications=2,
                n_zones=16,
                n_periods=48,
                max_panel_cells=100,
            ),
        )


def test_nyc_benchmark_artifact_bundle_is_atomic_portable_and_hashed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    anchor = _verified_anchor_artifacts(tmp_path)
    result = run_nyc_informed_marketplace_benchmark(
        anchor["anchor_path"],
        anchor["anchor_manifest_path"],
        project_root=tmp_path,
        config=_laptop_config(),
    )
    output = tmp_path / "published" / "nyc_benchmark"
    paths = write_nyc_benchmark_artifacts(
        result,
        output,
        project_root=tmp_path,
    )

    assert set(paths) == {
        "output_directory",
        "records",
        "summary",
        "fit_ledger",
        "failures",
        "metadata",
        "manifest",
    }
    assert all(path.is_file() for key, path in paths.items() if key != "output_directory")
    manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
    metadata = json.loads(paths["metadata"].read_text(encoding="utf-8"))
    assert manifest["artifact_type"] == "nyc_informed_marketplace_benchmark"
    assert manifest["portable_paths"] is True
    assert manifest["causal_claim"] is False
    assert manifest["causal_claim_from_nyc_data"] is False
    assert manifest["simulator_known_truth"] is True
    assert manifest["artifact_directory"] == "published/nyc_benchmark"
    assert metadata["artifact_bundle"]["portable_paths"] is True
    assert metadata["artifact_bundle"]["nyc_empirical_causal_effect"] is False
    assert metadata["artifact_bundle"]["inputs"] == manifest["inputs"]
    assert str(tmp_path) not in json.dumps({"manifest": manifest, "metadata": metadata})

    input_entries = {entry["role"]: entry for entry in manifest["inputs"]}
    assert set(input_entries) == {"anchor", "anchor_manifest"}
    for role, source in (
        ("anchor", anchor["anchor_path"]),
        ("anchor_manifest", anchor["anchor_manifest_path"]),
    ):
        source_path = Path(source)
        entry = input_entries[role]
        assert entry["path"] == source_path.relative_to(tmp_path).as_posix()
        assert entry["bytes"] == source_path.stat().st_size
        assert entry["sha256"] == sha256_file(source_path)
        assert not Path(entry["path"]).is_absolute()

    tables = {
        "records": result.records,
        "summary": result.summary,
        "fit_ledger": result.fit_ledger,
        "failures": result.failures,
    }
    entries = {entry["role"]: entry for entry in manifest["files"]}
    assert set(entries) == {*tables, "metadata"}
    for role, frame in tables.items():
        entry = entries[role]
        path = paths[role]
        assert entry["path"] == f"{role}.csv"
        assert entry["rows"] == len(frame)
        assert entry["bytes"] == path.stat().st_size
        assert entry["sha256"] == sha256_file(path)
        assert Path(entry["path"]).name == entry["path"]
    assert entries["metadata"]["bytes"] == paths["metadata"].stat().st_size
    assert entries["metadata"]["sha256"] == sha256_file(paths["metadata"])

    first_hashes = {
        key: sha256_file(path)
        for key, path in paths.items()
        if key != "output_directory"
    }
    rewritten = write_nyc_benchmark_artifacts(
        result,
        output,
        project_root=tmp_path,
    )
    assert first_hashes == {
        key: sha256_file(path)
        for key, path in rewritten.items()
        if key != "output_directory"
    }

    sentinel = output / "previous_bundle_sentinel.txt"
    sentinel.write_text("preserve\n", encoding="utf-8")
    original_manifest = paths["manifest"].read_bytes()

    def fail_staged_write(*_args: object, **_kwargs: object) -> Path:
        raise RuntimeError("synthetic staged write failure")

    monkeypatch.setattr(
        nyc_benchmark_module,
        "_artifact_write_table",
        fail_staged_write,
    )
    with pytest.raises(RuntimeError, match="synthetic staged write failure"):
        write_nyc_benchmark_artifacts(result, output, project_root=tmp_path)
    assert sentinel.read_text(encoding="utf-8") == "preserve\n"
    assert paths["manifest"].read_bytes() == original_manifest
    assert not list(output.parent.glob(f".{output.name}-stage-*"))

    anchor_path = Path(anchor["anchor_path"])
    anchor_path.write_bytes(anchor_path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="anchor SHA-256"):
        write_nyc_benchmark_artifacts(result, output, project_root=tmp_path)
    assert sentinel.read_text(encoding="utf-8") == "preserve\n"
    assert paths["manifest"].read_bytes() == original_manifest
    assert not list(output.parent.glob(f".{output.name}-stage-*"))
