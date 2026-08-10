from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from time import perf_counter

import polars as pl
import pytest

from casuallab import nyc_full_analysis as nyc_full_analysis_module
from casuallab.data import DataConfig, run_data_pipeline, sha256_file
from casuallab.nyc_full_analysis import write_nyc_full_analysis


def _calendar_raw() -> pl.DataFrame:
    pickups = [datetime(2024, 1, 1) + timedelta(hours=index) for index in range(31 * 24)]
    pickups.append(datetime(2024, 1, 1, 0, 30))
    rows = len(pickups)
    origins = [1 + index % 2 for index in range(rows)]
    destinations = [2 - index % 2 for index in range(rows)]
    return pl.DataFrame(
        {
            "hvfhs_license_num": ["HV0003"] * rows,
            "dispatching_base_num": ["B00001"] * rows,
            "request_datetime": pickups,
            "pickup_datetime": pickups,
            "dropoff_datetime": [value + timedelta(minutes=10) for value in pickups],
            "PULocationID": origins,
            "DOLocationID": destinations,
            "trip_miles": [2.5] * rows,
            "trip_time": [600] * rows,
            "base_passenger_fare": [15.0] * (rows - 1) + [20.0],
            "tips": [2.0] * rows,
            "driver_pay": [10.0] * rows,
            "shared_request_flag": ["N"] * rows,
            "shared_match_flag": ["N"] * rows,
        }
    )


def _full_config(tmp_path: Path) -> DataConfig:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    raw_path = raw_dir / "fhvhv_tripdata_2024-01.parquet"
    raw = _calendar_raw()
    raw.write_parquet(raw_path, row_group_size=100)
    config = DataConfig(
        source="nyc_hvfhv",
        mode="full",
        project_root=tmp_path,
        raw_dir=raw_dir,
        clean_dir=tmp_path / "clean",
        panel_dir=tmp_path / "panel",
        manifest_path=tmp_path / "manifest.json",
        diagnostics_path=tmp_path / "diagnostics.json",
        start_datetime=None,
        end_datetime=None,
        nyc_year=2024,
        nyc_months=(1,),
        nyc_batch_rows=200,
        nyc_expected_rows=raw.height,
        nyc_expected_bytes=raw_path.stat().st_size,
        nyc_expected_sha256=sha256_file(raw_path),
        panel_frequency="1h",
        complete_panel_grid=True,
    )
    run_data_pipeline(config)
    return config


def test_full_month_analysis_validates_and_writes_compact_evidence(tmp_path: Path) -> None:
    config = _full_config(tmp_path)

    artifacts = write_nyc_full_analysis(
        config,
        tmp_path / "analysis",
        started_at_monotonic=perf_counter(),
        raw_cached=True,
        command="synthetic-test",
    )
    validation = json.loads(artifacts.validation_path.read_text(encoding="utf-8"))

    assert validation["validation_passed"] is True
    assert validation["causal_claim"] is False
    assert validation["scope"]["population_claim"] is False
    assert validation["coverage"]["date_hours"] == 31 * 24
    assert validation["conservation"]["raw_rows"] == config.nyc_expected_rows
    assert validation["conservation"]["zone_time_rows"] == 2 * 31 * 24
    assert validation["conservation"]["zone_trip_sum"] == config.nyc_expected_rows
    assert validation["conservation"]["od_trip_sum"] == config.nyc_expected_rows
    assert validation["checks"]["manifest_files_valid"] is True
    assert validation["provenance"]["data_manifest"] == "manifest.json"
    assert not Path(validation["provenance"]["data_manifest"]).is_absolute()
    assert sum(1 for _ in artifacts.daily_path.open(encoding="utf-8")) == 32
    assert sum(1 for _ in artifacts.hourly_path.open(encoding="utf-8")) == 25
    assert sum(1 for _ in artifacts.weekday_path.open(encoding="utf-8")) == 8
    assert all(path.is_file() for path in artifacts.paths())
    assert not (
        tmp_path / "analysis" / "NYC_FULL_ANALYSIS_INCOMPLETE.json"
    ).exists()


def test_full_month_analysis_invalidates_manifest_and_marks_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _full_config(tmp_path)
    output = tmp_path / "analysis"
    output.mkdir()
    stale_manifest = output / "manifest.json"
    stale_manifest.write_text('{"stale": true}\n', encoding="utf-8")

    marker = output / "NYC_FULL_ANALYSIS_INCOMPLETE.json"

    def fail_manifest(*_args: object, **_kwargs: object) -> Path:
        assert marker.is_file()
        assert not stale_manifest.exists()
        raise RuntimeError("synthetic analysis failure")

    monkeypatch.setattr(nyc_full_analysis_module, "write_manifest", fail_manifest)
    with pytest.raises(RuntimeError, match="synthetic analysis failure"):
        write_nyc_full_analysis(config, output)

    assert not stale_manifest.exists()
    assert marker.is_file()
    assert json.loads(marker.read_text(encoding="utf-8"))["status"] == "incomplete"
