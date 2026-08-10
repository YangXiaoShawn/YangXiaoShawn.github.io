from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import polars as pl
import pytest

from casuallab import nyc_calibration as calibration_module
from casuallab.data import DataConfig, write_manifest
from casuallab.interference import add_mapped_exposures
from casuallab.nyc_calibration import (
    NYCCalibrationSettings,
    write_nyc_calibration_bundle,
)


def _synthetic_full_data(tmp_path: Path) -> DataConfig:
    clean_dir = tmp_path / "clean" / "trips"
    zone_dir = tmp_path / "panel" / "zone_time"
    od_dir = tmp_path / "panel" / "od_flow"
    clean_dir.mkdir(parents=True)
    zone_dir.mkdir(parents=True)
    od_dir.mkdir(parents=True)

    start = datetime(2024, 1, 1)
    zone_counts = {
        "1": (2, 3, 4, 5),
        "2": (1, 1, 2, 2),
    }
    trip_rows: list[dict[str, object]] = []
    sequence = 0
    for zone_id, counts in zone_counts.items():
        for hour, count in enumerate(counts):
            pickup = start + timedelta(hours=hour)
            for within_cell in range(count):
                wait_minutes = 1 + sequence % 5
                trip_rows.append(
                    {
                        "request_datetime": pickup - timedelta(minutes=wait_minutes),
                        "pickup_datetime": pickup,
                        "pickup_zone_id": zone_id,
                        "dropoff_zone_id": (
                            zone_id if within_cell == 0 else ("2" if zone_id == "1" else "1")
                        ),
                        "fare": 10.0 + sequence,
                        "driver_pay": 6.0 + sequence / 2,
                    }
                )
                sequence += 1
    clean = pl.DataFrame(trip_rows)
    clean_path = clean_dir / "part-00000.parquet"
    clean.write_parquet(clean_path)

    zone_rows = [
        {
            "zone_id": zone_id,
            "time_bin": start + timedelta(hours=hour),
            "trip_count": count,
        }
        for zone_id, counts in zone_counts.items()
        for hour, count in enumerate(counts)
    ]
    zone_path = zone_dir / "part-00000.parquet"
    pl.DataFrame(zone_rows).write_parquet(zone_path)

    od_path = od_dir / "part-00000.parquet"
    (
        clean.group_by("pickup_zone_id", "dropoff_zone_id", "pickup_datetime")
        .agg(pl.len().cast(pl.Int64).alias("trip_count"))
        .rename(
            {
                "pickup_zone_id": "origin_zone_id",
                "dropoff_zone_id": "destination_zone_id",
                "pickup_datetime": "time_bin",
            }
        )
        .write_parquet(od_path)
    )

    diagnostics_path = tmp_path / "diagnostics.json"
    diagnostics_path.write_text(
        json.dumps({"row_count": clean.height}, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    config = DataConfig(
        source="nyc_hvfhv",
        mode="full",
        project_root=tmp_path,
        raw_dir=tmp_path / "raw",
        clean_dir=clean_dir.parent,
        panel_dir=tmp_path / "panel",
        manifest_path=tmp_path / "manifest.json",
        diagnostics_path=diagnostics_path,
        start_datetime=None,
        end_datetime=None,
        nyc_expected_rows=clean.height,
        panel_frequency="1h",
        complete_panel_grid=True,
    )
    write_manifest(
        (clean_path, zone_path, od_path, diagnostics_path),
        config.manifest_path,
        config=config,
        root=tmp_path,
        metadata={
            "causal_claim": False,
            "evidence_label": "descriptive_real_data",
            "full_month_processing": {"raw_rows": clean.height},
        },
    )
    return config


def _csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_writes_streamed_descriptive_calibration_and_network_bundle(
    tmp_path: Path,
) -> None:
    config = _synthetic_full_data(tmp_path)
    artifacts = write_nyc_calibration_bundle(
        config,
        tmp_path / "calibration_network",
        settings=NYCCalibrationSettings(
            exact_lag_hours=(1, 2),
            target_cluster_count=2,
        ),
    )

    calibration = json.loads(artifacts.calibration_path.read_text(encoding="utf-8"))
    assert calibration["bundle_valid"] is True
    assert calibration["causal_claim"] is False
    assert all(calibration["checks"].values())
    assert calibration["conservation"]["clean_rows"] == 20
    assert calibration["conservation"]["zone_trip_sum"] == 20
    assert calibration["conservation"]["od_trip_sum"] == 20

    moments = calibration["trip_level_descriptive_moments"]
    assert moments["request_to_pickup_wait_minutes"]["valid_rows"] == 20
    assert moments["request_to_pickup_wait_minutes"]["mean"] == pytest.approx(3.0)
    assert moments["fare"]["mean"] == pytest.approx(19.5)
    assert moments["driver_pay"]["mean"] == pytest.approx(10.75)

    variance = calibration["zone_hour_variance_decomposition"]
    assert variance["panel_cells"] == 8
    assert variance["zones"] == 2
    assert 0 < variance["icc_like_between_zone_share"] < 1
    assert variance["zone_decomposition_residual"] == pytest.approx(0.0)
    assert "not a fitted random-effects ICC" in variance["interpretation"]

    lags = _csv_rows(artifacts.autocorrelation_path)
    assert [int(row["lag_hours"]) for row in lags] == [1, 2]
    assert [int(row["exact_lag_support_pairs"]) for row in lags] == [6, 4]
    assert all(float(row["support_share"]) == pytest.approx(1.0) for row in lags)

    mapping = _csv_rows(artifacts.exposure_mapping_path)
    assert mapping
    assert {"focal_zone_id", "neighbor_zone_id", "weight"} <= mapping[0].keys()
    assert {(row["focal_zone_id"], row["neighbor_zone_id"]) for row in mapping} == {
        ("1", "2"),
        ("2", "1"),
    }
    assert all(float(row["weight"]) > 0 for row in mapping)
    assignments = pd.DataFrame(
        {
            "zone_id": ["1", "2", "1", "2"],
            "period_id": [0, 0, 1, 1],
            "treatment": [1.0, 0.0, 0.0, 1.0],
        }
    )
    mapped = add_mapped_exposures(
        assignments,
        pd.DataFrame(mapping)[["focal_zone_id", "neighbor_zone_id", "weight"]],
    )
    assert mapped["neighbor_exposure"].tolist() == [0.0, 1.0, 1.0, 0.0]
    assert mapped["mapped_neighbor_weight"].tolist() == [1.0] * 4

    proposal = calibration["simulator_scale_calibration_proposal"]
    assert proposal["status"].endswith("not_fitted_structural_model")
    assert "spillover_strength" in proposal["not_estimated_from_trip_records"]
    assert "persistence" in proposal["not_estimated_from_trip_records"]
    assert "welfare_function_or_welfare_effect" in proposal[
        "not_estimated_from_trip_records"
    ]
    assert all(path.is_file() for path in artifacts.paths())
    assert not (tmp_path / "calibration_network_INCOMPLETE.json").exists()

    manifest = json.loads(artifacts.manifest_path.read_text(encoding="utf-8"))
    assert manifest["portable_paths"] is True
    assert len(manifest["files"]) == 7
    serialized = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (artifacts.calibration_path, artifacts.manifest_path)
    )
    assert str(tmp_path) not in serialized


def test_failure_keeps_previous_bundle_and_leaves_fail_closed_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _synthetic_full_data(tmp_path)
    output = tmp_path / "calibration_network"
    output.mkdir()
    sentinel = output / "previous_success.txt"
    sentinel.write_text("previous\n", encoding="utf-8")

    def fail_copy(*_args: object, **_kwargs: object) -> Path:
        raise RuntimeError("synthetic publication failure")

    monkeypatch.setattr(calibration_module, "_copy_csv", fail_copy)
    with pytest.raises(RuntimeError, match="synthetic publication failure"):
        write_nyc_calibration_bundle(config, output)

    assert sentinel.read_text(encoding="utf-8") == "previous\n"
    marker = tmp_path / "calibration_network_INCOMPLETE.json"
    assert marker.is_file()
    assert json.loads(marker.read_text(encoding="utf-8"))["status"] == "incomplete"


def test_source_hash_mismatch_fails_before_publishing(tmp_path: Path) -> None:
    config = _synthetic_full_data(tmp_path)
    clean_path = next((config.clean_dir / "trips").glob("*.parquet"))
    clean_path.write_bytes(clean_path.read_bytes() + b"corrupt")

    output = tmp_path / "calibration_network"
    with pytest.raises(ValueError, match="source data manifest validation failed"):
        write_nyc_calibration_bundle(config, output)

    assert not output.exists()
    assert (tmp_path / "calibration_network_INCOMPLETE.json").is_file()
