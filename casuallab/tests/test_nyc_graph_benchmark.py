from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import casuallab.nyc_graph_benchmark as nyc_graph_benchmark_module
from casuallab.data import sha256_file
from casuallab.nyc_graph_benchmark import (
    NYCGraphBenchmarkConfig,
    known_nyc_graph_estimands,
    run_nyc_graph_benchmark,
    validate_nyc_graph_bundle,
    write_nyc_graph_benchmark_artifacts,
)

REAL_BUNDLE = (
    Path(__file__).resolve().parents[1]
    / "artifacts"
    / "nyc_full"
    / "calibration_network"
)


def _source_attestation() -> dict[str, object]:
    return {
        "all_valid": True,
        "hashes_recomputed": True,
        "queried_files_listed": True,
        "scope_is_full_nyc_descriptive": True,
        "mismatches": [],
        "sha256": "a" * 64,
        "entries": 3,
        "declared_file_set_sha256": "b" * 64,
        "path": "data/nyc_full/manifest.json",
    }


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _synthetic_bundle(tmp_path: Path, n_zones: int = 12) -> Path:
    bundle = tmp_path / "calibration_network"
    bundle.mkdir()
    rows: list[dict[str, object]] = []
    for left in range(n_zones):
        for right in range(left + 1, n_zones):
            # Symmetric pre-treatment graph geometry with heterogeneous raw weights.
            weight = float(1 + ((left + 3) * (right + 5)) % 17)
            for focal, neighbor in ((left, right), (right, left)):
                rows.append(
                    {
                        "focal_zone_id": str(focal),
                        "neighbor_zone_id": str(neighbor),
                        "weight": weight,
                        "evidence_label": "descriptive_real_data",
                        "weight_definition": (
                            "Symmetric monthly completed-trip flow; downstream "
                            "row-normalizes weight."
                        ),
                        "interpretation_warning": (
                            "Pre-treatment exposure-map input; not an estimated "
                            "spillover effect."
                        ),
                    }
                )
    mapping_path = bundle / "exposure_mapping_edges.csv"
    pd.DataFrame(rows).sort_values(
        ["focal_zone_id", "neighbor_zone_id"]
    ).to_csv(mapping_path, index=False)

    source = _source_attestation()
    calibration = {
        "schema_version": "1.0.0",
        "evidence_label": "descriptive_real_data",
        "causal_claim": False,
        "bundle_valid": True,
        "scope": {
            "source": "nyc_hvfhv",
            "population_claim": False,
        },
        "checks": {"synthetic_conservation": True},
        "critical_warning": (
            "Published completed-trip associations are descriptive and do not identify "
            "treatment response, spillovers, persistence, substitution, or welfare."
        ),
        "provenance": {"source_data_manifest": source},
        "od_flow_graph": {
            "evidence_label": "descriptive_real_data",
            "exposure_mapping_file": "exposure_mapping_edges.csv",
            "exposure_mapping_schema": [
                "focal_zone_id",
                "neighbor_zone_id",
                "weight",
            ],
            "interpretation": (
                "Observed OD weights define a candidate exposure graph but do not "
                "estimate interference, rider substitution, or driver movement."
            ),
        },
    }
    calibration_path = bundle / "calibration.json"
    _write_json(calibration_path, calibration)

    files = [
        {
            "path": path.name,
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in (calibration_path, mapping_path)
    ]
    manifest = {
        "schema_version": "1.0.0",
        "evidence_label": "descriptive_real_data",
        "causal_claim": False,
        "portable_paths": True,
        "files": files,
        "source_data_manifest": source,
        "config": {
            "data": {"source": "nyc_hvfhv", "mode": "full"},
            "calibration": {"verify_source_hashes": True},
        },
        "interpretation_warning": (
            "Published completed-trip associations are descriptive and do not identify "
            "treatment response, spillovers, persistence, substitution, or welfare."
        ),
    }
    _write_json(bundle / "manifest.json", manifest)
    return bundle


def test_real_and_synthetic_calibration_bundles_validate_and_run(
    tmp_path: Path,
) -> None:
    synthetic_path = _synthetic_bundle(tmp_path)
    real = validate_nyc_graph_bundle(REAL_BUNDLE)
    synthetic = validate_nyc_graph_bundle(synthetic_path)

    assert len(real.edges) > 60_000
    assert len(synthetic.edges) == 12 * 11
    assert real.mapping_sha256 == sha256_file(
        REAL_BUNDLE / "exposure_mapping_edges.csv"
    )
    assert set(real.edges["evidence_label"]) == {"descriptive_real_data"}
    assert set(synthetic.edges["evidence_label"]) == {"descriptive_real_data"}

    config = NYCGraphBenchmarkConfig(
        replications=2,
        n_zones=12,
        n_periods=12,
        seed=447,
    )
    real_result = run_nyc_graph_benchmark(REAL_BUNDLE, config)
    synthetic_result = run_nyc_graph_benchmark(synthetic_path, config)
    assert real_result.failures.empty
    assert synthetic_result.failures.empty
    assert real_result.fit_ledger["fit_complete"].all()
    assert synthetic_result.fit_ledger["fit_complete"].all()


def test_real_nyc_graph_benchmark_is_deterministic_and_records_selection() -> None:
    config = NYCGraphBenchmarkConfig(
        replications=3,
        n_zones=12,
        n_periods=12,
        seed=551,
    )
    first = run_nyc_graph_benchmark(REAL_BUNDLE, config)
    second = run_nyc_graph_benchmark(REAL_BUNDLE, config)

    pd.testing.assert_frame_equal(first.records, second.records)
    pd.testing.assert_frame_equal(first.summary, second.summary)
    pd.testing.assert_frame_equal(first.fit_ledger, second.fit_ledger)
    pd.testing.assert_frame_equal(first.failures, second.failures)
    assert first.metadata == second.metadata
    subset = first.metadata["zone_subset"]
    assert subset["selection_uses_only_pre_treatment_graph_fields"] is True
    assert len(subset["selected_zone_ids_in_order"]) == config.n_zones
    assert len(subset["subset_raw_mapping_sha256"]) == 64
    assert "not spillover strength" in first.metadata["graph_weight_role"]
    assert first.metadata["causal_claim_from_nyc_data"] is False
    assert (
        first.metadata["calibration_bundle"]["directory_name"]
        == "artifacts/nyc_full/calibration_network"
    )


def test_bundle_validation_rejects_mapping_tampering(tmp_path: Path) -> None:
    bundle = _synthetic_bundle(tmp_path)
    mapping_path = bundle / "exposure_mapping_edges.csv"
    tampered = mapping_path.read_bytes().replace(
        b"descriptive_real_data",
        b"xescriptive_real_data",
        1,
    )
    mapping_path.write_bytes(tampered)

    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        validate_nyc_graph_bundle(bundle)


def test_bundle_validation_rejects_non_descriptive_evidence(tmp_path: Path) -> None:
    bundle = _synthetic_bundle(tmp_path)
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["evidence_label"] = "causal_estimate"
    _write_json(manifest_path, manifest)

    with pytest.raises(ValueError, match="descriptive_real_data"):
        validate_nyc_graph_bundle(bundle)


def test_real_nyc_geometry_recovers_controlled_targets_and_withholds_naive_total() -> None:
    config = NYCGraphBenchmarkConfig(
        replications=8,
        n_zones=16,
        n_periods=20,
        seed=991,
    )
    result = run_nyc_graph_benchmark(REAL_BUNDLE, config)
    truth = known_nyc_graph_estimands(config)
    mapped = result.summary.loc[result.summary["identified"]].set_index(
        "target_estimand"
    )

    assert mapped.loc[
        "controlled_zone_direct_effect", "mean_estimate"
    ] == pytest.approx(truth.controlled_zone_direct_effect, abs=0.10)
    assert mapped.loc["spillover_effect", "mean_estimate"] == pytest.approx(
        truth.spillover_effect, abs=0.12
    )
    assert mapped.loc[
        "controlled_history_exposure_response", "mean_estimate"
    ] == pytest.approx(
        truth.controlled_history_exposure_response, abs=0.10
    )
    assert mapped["inference_valid_for_target"].all()
    assert mapped["controlled_exposure_not_market_total"].all()
    assert not mapped["graph_weight_is_spillover_strength"].any()

    naive = result.summary.loc[
        result.summary["estimator"].eq(
            "nyc_graph_naive_assignment_cluster_regression"
        )
    ].iloc[0]
    assert naive["target_estimand"] == "market_total_effect"
    assert naive["comparison_status"] == "target_mismatch"
    assert not bool(naive["identified"])
    assert naive["diagnostic_mean_gap_to_market_total"] < -1.0
    assert np.isnan(naive["bias"])
    assert np.isnan(naive["rmse"])
    assert np.isnan(naive["coverage"])
    assert np.isnan(naive["power"])
    assert "withheld" in naive["withheld_reason"]
    assert truth.market_total_effect != truth.controlled_zone_direct_effect


def test_config_requires_history_identifying_saturation_support() -> None:
    with pytest.raises(ValueError, match="interior arm"):
        NYCGraphBenchmarkConfig(saturation_levels=(0.0, 1.0))


def test_nyc_graph_artifact_bundle_is_atomic_portable_and_hashed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _synthetic_bundle(tmp_path)
    result = run_nyc_graph_benchmark(
        bundle,
        NYCGraphBenchmarkConfig(
            replications=2,
            n_zones=12,
            n_periods=12,
            seed=731,
        ),
    )
    output = tmp_path / "published" / "nyc_graph_benchmark"
    paths = write_nyc_graph_benchmark_artifacts(
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
    assert manifest["artifact_type"] == "nyc_graph_interference_benchmark"
    assert manifest["portable_paths"] is True
    assert manifest["causal_claim"] is False
    assert manifest["causal_claim_from_nyc_data"] is False
    assert manifest["input_graph_evidence_label"] == "descriptive_real_data"
    assert manifest["artifact_directory"] == "published/nyc_graph_benchmark"
    artifact_metadata = metadata["artifact_bundle"]
    assert artifact_metadata["portable_paths"] is True
    assert artifact_metadata["causal_claim_from_nyc_data"] is False
    assert artifact_metadata["input_graph_evidence_label"] == "descriptive_real_data"
    assert artifact_metadata["inputs"] == manifest["inputs"]
    assert "not spillover strength" in metadata["graph_weight_role"]
    assert str(tmp_path) not in json.dumps({"manifest": manifest, "metadata": metadata})

    input_entries = {entry["role"]: entry for entry in manifest["inputs"]}
    assert set(input_entries) == {"calibration_manifest", "exposure_mapping"}
    for role, source in (
        ("calibration_manifest", bundle / "manifest.json"),
        ("exposure_mapping", bundle / "exposure_mapping_edges.csv"),
    ):
        entry = input_entries[role]
        assert entry["path"] == source.relative_to(tmp_path).as_posix()
        assert entry["bytes"] == source.stat().st_size
        assert entry["sha256"] == sha256_file(source)
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
    rewritten = write_nyc_graph_benchmark_artifacts(
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
        nyc_graph_benchmark_module,
        "_artifact_write_table",
        fail_staged_write,
    )
    with pytest.raises(RuntimeError, match="synthetic staged write failure"):
        write_nyc_graph_benchmark_artifacts(result, output, project_root=tmp_path)
    assert sentinel.read_text(encoding="utf-8") == "preserve\n"
    assert paths["manifest"].read_bytes() == original_manifest
    assert not list(output.parent.glob(f".{output.name}-stage-*"))

    mapping_path = bundle / "exposure_mapping_edges.csv"
    mapping_path.write_bytes(
        mapping_path.read_bytes().replace(
            b"descriptive_real_data",
            b"xescriptive_real_data",
            1,
        )
    )
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        write_nyc_graph_benchmark_artifacts(result, output, project_root=tmp_path)
    assert sentinel.read_text(encoding="utf-8") == "preserve\n"
    assert paths["manifest"].read_bytes() == original_manifest
    assert not list(output.parent.glob(f".{output.name}-stage-*"))
