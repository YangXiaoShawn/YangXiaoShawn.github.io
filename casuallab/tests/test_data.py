from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import polars as pl
import pytest

from casuallab.data import (
    CHICAGO_DATASET_ID,
    CLEAN_TRIP_SCHEMA,
    MISSING_ZONE_ID,
    DataConfig,
    build_od_flow_panel,
    build_zone_time_panel,
    chicago_sample_urls,
    data_quality_diagnostics,
    download_sample,
    load_data_config,
    materialize_nyc_hvfhv_sample,
    normalize_trips,
    nyc_hvfhv_urls,
    read_partitioned_parquet,
    run_data_pipeline,
    sha256_file,
    validate_clean_schema,
    write_manifest,
    write_partitioned_parquet,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CHICAGO_FIXTURE = PROJECT_ROOT / "data/fixtures/chicago_tnp_2022-01-01_300.csv"
CHICAGO_FIXTURE_SHA256 = "84177e5a72548cc4346df99f0a6b671adb50d7762e23abe041f01b2958b85ad7"


@pytest.fixture(scope="module")
def chicago_trips() -> pl.DataFrame:
    return normalize_trips(CHICAGO_FIXTURE, "chicago_tnp")


def test_fixture_is_pinned_authentic_extract() -> None:
    assert sha256_file(CHICAGO_FIXTURE) == CHICAGO_FIXTURE_SHA256
    raw = pl.read_csv(CHICAGO_FIXTURE)
    assert raw.height == 300
    assert raw.get_column("trip_id").n_unique() == 300
    assert raw.get_column("trip_start_timestamp").n_unique() == 12
    assert raw.get_column("trip_start_timestamp").min().startswith("2022-01-01T00:00")
    assert raw.get_column("trip_start_timestamp").max().startswith("2022-01-01T22:00")

    fixture_manifest = json.loads(
        (PROJECT_ROOT / "data/fixtures/manifest.json").read_text(encoding="utf-8")
    )
    selection = fixture_manifest["selection"]
    assert selection["query_predicate"] == (
        "trip_start_timestamp = exact reported hourly timestamp"
    )
    assert "%3D" in selection["query_url_template"]
    assert "%3E" not in selection["query_url_template"]


def test_load_config_resolves_paths_from_project_root(tmp_path: Path) -> None:
    config_path = tmp_path / "configs/data.yaml"
    config_path.parent.mkdir()
    config_path.write_text(
        "\n".join(
            [
                "project_root: ..",
                "source: chicago",
                "mode: sample",
                "fixture_path: fixtures/trips.csv",
                "raw_dir: generated/raw",
                "sample_rows: 300",
                "nyc_months: [1, 2]",
                "partition_by: [source, service_year, service_month]",
            ]
        ),
        encoding="utf-8",
    )
    config = load_data_config(config_path)
    assert config.source == "chicago_tnp"
    assert config.project_root == tmp_path.resolve()
    assert config.fixture_path == tmp_path / "fixtures/trips.csv"
    assert config.raw_dir == tmp_path / "generated/raw"
    assert config.nyc_months == (1, 2)


def test_unknown_config_key_fails_fast(tmp_path: Path) -> None:
    config_path = tmp_path / "bad.yaml"
    config_path.write_text("source: chicago\nsampel_rows: 10\n", encoding="utf-8")
    with pytest.raises(ValueError, match="unknown data configuration keys"):
        load_data_config(config_path)


def test_full_config_rejects_misleading_sample_row_bound(tmp_path: Path) -> None:
    config_path = tmp_path / "full.yaml"
    config_path.write_text(
        "source: nyc_hvfhv\nmode: full\nsample_rows: 1000\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="does not bound full mode"):
        load_data_config(config_path)


def test_chicago_sample_urls_are_stratified_and_deterministic() -> None:
    config = DataConfig(sample_rows=300)
    urls = chicago_sample_urls(config)
    assert len(urls) == 12
    limits = []
    timestamps = []
    for url in urls:
        query = parse_qs(urlparse(url).query)
        assert query["$order"] == ["trip_id"]
        limits.append(int(query["$limit"][0]))
        timestamps.append(query["$where"][0])
    assert limits == [25] * 12
    assert timestamps[0].endswith("'2022-01-01T00:00:00'")
    assert timestamps[-1].endswith("'2022-01-01T22:00:00'")


def test_download_sample_is_offline_by_default(tmp_path: Path) -> None:
    def network_must_not_run(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("offline sample unexpectedly attempted network access")

    config = DataConfig(
        fixture_path=CHICAGO_FIXTURE,
        raw_dir=tmp_path / "raw",
        sample_rows=300,
    )
    downloaded = download_sample(config, opener=network_must_not_run)  # type: ignore[arg-type]
    assert downloaded == tmp_path / "raw/chicago_tnp_sample.csv"
    assert sha256_file(downloaded) == CHICAGO_FIXTURE_SHA256


def test_chicago_normalization_preserves_measurement_flags(
    chicago_trips: pl.DataFrame,
) -> None:
    validate_clean_schema(chicago_trips)
    assert chicago_trips.schema == CLEAN_TRIP_SCHEMA
    assert chicago_trips.height == 300
    assert chicago_trips.get_column("source").unique().to_list() == ["chicago_tnp"]
    assert chicago_trips.get_column("source_dataset_id").unique().to_list() == [
        CHICAGO_DATASET_ID
    ]
    assert chicago_trips.get_column("pickup_on_15_minute_grid").all()
    assert chicago_trips.get_column("fare_on_declared_grid").all()
    assert chicago_trips.get_column("reported_timestamp_rounding_minutes").unique().to_list() == [
        15
    ]
    assert chicago_trips.get_column("reported_fare_rounding_increment").unique().to_list() == [
        2.5
    ]
    assert chicago_trips.get_column("pickup_datetime_utc").null_count() == 0
    assert chicago_trips.get_column("pickup_zone_missing").sum() == 13


def test_diagnostics_distinguish_missingness_from_exact_suppression(
    chicago_trips: pl.DataFrame,
) -> None:
    diagnostics = data_quality_diagnostics(chicago_trips)
    assert diagnostics["row_count"] == 300
    assert diagnostics["suppression_or_nonreporting"]["pickup_census_tract_count"] == 131
    assert diagnostics["suppression_or_nonreporting"]["dropoff_census_tract_count"] == 135
    assert "may be privacy-suppressed or outside Chicago" in diagnostics[
        "suppression_or_nonreporting"
    ]["interpretation"]
    assert diagnostics["rounding"]["pickup_on_15_minute_grid_rate"] == 1.0
    assert diagnostics["rounding"]["fare_on_declared_grid_rate"] == 1.0
    assert diagnostics["validity"]["duplicate_trip_id_count"] == 0


def test_zone_time_and_od_panels_preserve_trip_totals(chicago_trips: pl.DataFrame) -> None:
    panel = build_zone_time_panel(chicago_trips, frequency="15m")
    flows = build_od_flow_panel(chicago_trips, frequency="15m")
    assert panel.get_column("trip_count").sum() == 300
    assert flows.get_column("trip_count").sum() == 300
    assert panel.get_column("time_bin").n_unique() == 12
    assert MISSING_ZONE_ID in panel.get_column("zone_id").to_list()
    assert panel.get_column("evidence_label").unique().to_list() == [
        "descriptive_real_data"
    ]
    assert {"avg_fare", "avg_trip_miles", "shared_requested_share"}.issubset(panel.columns)
    assert {"origin_zone_id", "destination_zone_id", "trip_count"}.issubset(flows.columns)


def test_complete_zone_time_grid_adds_explicit_zero_cells(chicago_trips: pl.DataFrame) -> None:
    observed = build_zone_time_panel(chicago_trips, frequency="2h")
    complete = build_zone_time_panel(chicago_trips, frequency="2h", complete_grid=True)
    assert complete.height >= observed.height
    assert complete.get_column("trip_count").sum() == observed.get_column("trip_count").sum()
    synthetic = complete.filter(pl.col("trip_count") == 0)
    assert synthetic.height > 0
    assert synthetic.get_column("distinct_dropoff_zones").eq(0).all()
    assert synthetic.get_column("outbound_trip_count").eq(0).all()
    assert synthetic.get_column("od_pair_observed_count").eq(0).all()
    for column in (
        "service_date",
        "year",
        "month",
        "day_of_week",
        "hour",
        "minute",
        "is_weekend",
        "panel_grain",
        "evidence_label",
    ):
        assert synthetic.get_column(column).null_count() == 0


def _nyc_raw_frame() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "hvfhs_license_num": ["HV0003", "HV0005"],
            "dispatching_base_num": ["B0001", "B0002"],
            "request_datetime": [datetime(2024, 1, 2, 12, 0), datetime(2024, 1, 2, 12, 1)],
            "pickup_datetime": [datetime(2024, 1, 2, 12, 5), datetime(2024, 1, 2, 12, 10)],
            "dropoff_datetime": [datetime(2024, 1, 2, 12, 15), datetime(2024, 1, 2, 12, 30)],
            "PULocationID": [132, 10],
            "DOLocationID": [10, 20],
            "trip_miles": [5.0, 6.0],
            "trip_time": [600, 1_200],
            "base_passenger_fare": [20.0, 30.0],
            "tips": [2.0, 3.0],
            "tolls": [1.0, 0.0],
            "bcf": [0.5, 0.5],
            "sales_tax": [1.0, 2.0],
            "congestion_surcharge": [2.75, 2.75],
            "airport_fee": [2.5, 0.0],
            "cbd_congestion_fee": [0.75, 0.0],
            "driver_pay": [15.0, 20.0],
            "shared_request_flag": ["Y", "N"],
            "shared_match_flag": ["N", "N"],
        }
    )


def _nyc_full_calendar_frame() -> pl.DataFrame:
    """Small row-count fixture with complete January date-hour coverage."""

    template = _nyc_raw_frame().row(0, named=True)
    second_zone_template = _nyc_raw_frame().row(1, named=True)
    rows: list[dict[str, object]] = []
    for day in range(1, 32):
        for hour in range(24):
            pickup = datetime(2024, 1, day, hour, 5)
            row = dict(template)
            row["request_datetime"] = pickup.replace(minute=0)
            row["pickup_datetime"] = pickup
            row["dropoff_datetime"] = pickup.replace(minute=15)
            rows.append(row)
    for pickup in (datetime(2024, 1, 1, 0, 25), datetime(2024, 1, 31, 23, 25)):
        row = dict(second_zone_template)
        row["request_datetime"] = pickup.replace(minute=20)
        row["pickup_datetime"] = pickup
        row["dropoff_datetime"] = pickup.replace(minute=35)
        rows.append(row)
    # Repeat every business field from the first record after many record batches.
    # Only the global source row offset can keep these surrogate IDs distinct.
    rows.append(dict(rows[0]))
    return pl.DataFrame(rows)


def test_nyc_adapter_normalizes_current_and_optional_fields() -> None:
    raw = _nyc_raw_frame()
    trips = normalize_trips(raw, "nyc_hvfhv")
    validate_clean_schema(trips)
    assert trips.height == 2
    assert trips.get_column("record_id_is_surrogate").all()
    assert trips.get_column("trip_id").to_list() == normalize_trips(
        raw, "nyc_hvfhv"
    ).get_column("trip_id").to_list()
    assert trips.get_column("total_amount").to_list() == pytest.approx([30.5, 38.25])
    assert trips.get_column("airport_trip").to_list() == [True, False]
    assert trips.get_column("pickup_datetime_utc")[0].hour == 17
    assert trips.get_column("reported_fare_rounding_increment").null_count() == 2
    assert trips.get_column("pickup_census_tract_missing_or_suppressed").null_count() == 2
    diagnostics = data_quality_diagnostics(trips)
    suppression = diagnostics["suppression_or_nonreporting"]
    assert suppression["pickup_indicator_status"] == "unavailable"
    assert suppression["dropoff_indicator_status"] == "unavailable"
    assert suppression["pickup_indicator_known_count"] == 0
    assert suppression["pickup_census_tract_rate"] is None


def test_nyc_url_adapter_supports_full_month_sequence() -> None:
    config = DataConfig(source="nyc_hvfhv", mode="full", nyc_year=2024, nyc_months=(3, 1))
    assert nyc_hvfhv_urls(config) == (
        "https://d37ci6vzurychx.cloudfront.net/trip-data/fhvhv_tripdata_2024-01.parquet",
        "https://d37ci6vzurychx.cloudfront.net/trip-data/fhvhv_tripdata_2024-03.parquet",
    )


def test_nyc_sample_adapter_materializes_only_bounded_rows(tmp_path: Path) -> None:
    source = tmp_path / "source.parquet"
    raw = pl.concat([_nyc_raw_frame(), _nyc_raw_frame()], how="vertical")
    raw.write_parquet(source)
    config = DataConfig(
        source="nyc_hvfhv",
        mode="sample",
        raw_dir=tmp_path / "raw",
        sample_rows=3,
        nyc_sample_days=(2,),
        nyc_sample_hours=(12,),
    )
    sample = materialize_nyc_hvfhv_sample(config, source_url=str(source))
    assert sample.name.startswith("fhvhv_tripdata_2024-01_stratified_3_")
    assert pl.read_parquet(sample).height == 3


def test_nyc_sample_is_deterministically_balanced_across_day_hours(
    tmp_path: Path,
) -> None:
    rows: list[dict[str, object]] = []
    template = _nyc_raw_frame().row(0, named=True)
    for day in (1, 8):
        for hour in (0, 12):
            for minute in range(5):
                row = dict(template)
                row["request_datetime"] = datetime(2024, 1, day, hour, minute)
                row["pickup_datetime"] = datetime(2024, 1, day, hour, minute, 10)
                row["dropoff_datetime"] = datetime(2024, 1, day, hour, minute, 40)
                row["PULocationID"] = 10 + minute
                rows.append(row)
    source = tmp_path / "strata.parquet"
    pl.DataFrame(rows).write_parquet(source)
    config = DataConfig(
        source="nyc_hvfhv",
        mode="sample",
        raw_dir=tmp_path / "raw",
        sample_rows=8,
        nyc_sample_days=(1, 8),
        nyc_sample_hours=(0, 12),
    )

    first = materialize_nyc_hvfhv_sample(config, source_url=str(source))
    second = materialize_nyc_hvfhv_sample(
        config,
        destination=tmp_path / "second.parquet",
        source_url=str(source),
    )
    sample = pl.read_parquet(first).with_columns(
        pl.col("pickup_datetime").dt.day().alias("day"),
        pl.col("pickup_datetime").dt.hour().alias("hour"),
    )
    counts = sample.group_by("day", "hour").len().sort("day", "hour")
    assert sample.height == 8
    assert counts["len"].to_list() == [2, 2, 2, 2]
    assert sha256_file(first) == sha256_file(second)


def test_nyc_sample_cache_fails_closed_when_content_is_stale(tmp_path: Path) -> None:
    source = tmp_path / "source.parquet"
    raw = pl.concat([_nyc_raw_frame(), _nyc_raw_frame()], how="vertical")
    raw.write_parquet(source)
    config = DataConfig(
        source="nyc_hvfhv",
        mode="sample",
        raw_dir=tmp_path / "raw",
        sample_rows=3,
        nyc_sample_days=(2,),
        nyc_sample_hours=(12,),
    )
    cached = materialize_nyc_hvfhv_sample(config, source_url=str(source))
    pl.read_parquet(cached).head(2).write_parquet(cached)

    with pytest.raises(ValueError, match="has 2 rows, expected 3"):
        download_sample(config)


def test_nyc_sample_configuration_fails_closed_on_ambiguous_scope() -> None:
    with pytest.raises(ValueError, match="exactly one configured month"):
        DataConfig(
            source="nyc_hvfhv",
            mode="sample",
            nyc_months=(1, 2),
        )
    with pytest.raises(ValueError, match="at least the number"):
        DataConfig(
            source="nyc_hvfhv",
            mode="sample",
            sample_rows=2,
            nyc_sample_days=(1,),
            nyc_sample_hours=(0, 1, 2),
        )
    with pytest.raises(ValueError, match="only valid in NYC full mode"):
        DataConfig(source="nyc_hvfhv", mode="sample", nyc_expected_rows=10)


def test_nyc_configs_use_isolated_output_roots() -> None:
    sample = load_data_config(PROJECT_ROOT / "configs/nyc_sample.yaml")
    full = load_data_config(PROJECT_ROOT / "configs/full.yaml")
    chicago = load_data_config(PROJECT_ROOT / "configs/sample.yaml")
    assert sample.raw_dir == PROJECT_ROOT / "data/nyc_sample/raw"
    assert sample.nyc_sample_days == (1, 10, 19, 28)
    assert sample.nyc_sample_hours == tuple(range(24))
    assert full.raw_dir == PROJECT_ROOT / "data/nyc_full/raw"
    assert {sample.raw_dir, full.raw_dir}.isdisjoint({chicago.raw_dir})


def test_nyc_full_pipeline_streams_batches_and_preserves_all_trip_totals(
    tmp_path: Path,
) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    raw_path = raw_dir / "fhvhv_tripdata_2024-01.parquet"
    raw = _nyc_full_calendar_frame()
    raw.write_parquet(raw_path, row_group_size=80)
    config = DataConfig(
        source="nyc_hvfhv",
        mode="full",
        project_root=tmp_path,
        raw_dir=raw_dir,
        clean_dir=tmp_path / "clean",
        panel_dir=tmp_path / "panel",
        manifest_path=tmp_path / "manifest.json",
        diagnostics_path=tmp_path / "diagnostics.json",
        nyc_year=2024,
        nyc_months=(1,),
        nyc_batch_rows=100,
        nyc_expected_rows=raw.height,
        nyc_expected_bytes=raw_path.stat().st_size,
        nyc_expected_sha256=sha256_file(raw_path),
        panel_frequency="1h",
        complete_panel_grid=True,
    )

    artifacts = run_data_pipeline(config)
    clean = read_partitioned_parquet(tmp_path / "clean/trips")
    panel = read_partitioned_parquet(tmp_path / "panel/zone_time")
    od_flow = read_partitioned_parquet(tmp_path / "panel/od_flow")
    diagnostics = json.loads(artifacts.diagnostics_path.read_text(encoding="utf-8"))
    manifest = json.loads(artifacts.manifest_path.read_text(encoding="utf-8"))
    processing = manifest["metadata"]["full_month_processing"]

    assert raw.height == 747
    assert artifacts.trip_rows == raw.height == clean.height
    assert clean.get_column("trip_id").n_unique() == raw.height
    assert len(artifacts.clean_files) == 8
    assert len({path.name for path in artifacts.clean_files}) == 8
    assert panel.get_column("trip_count").sum() == raw.height
    assert od_flow.get_column("trip_count").sum() == raw.height
    assert artifacts.panel_rows == 2 * 31 * 24
    assert processing["observed_zone_time_rows"] == 746
    assert processing["synthesized_zone_time_rows"] == 742
    assert processing["configured_date_hours"] == 31 * 24
    assert processing["observed_date_hours"] == 31 * 24
    assert processing["normalized_batches"] == 8
    assert processing["raw_row_groups"] == 10
    assert processing["row_conservation"]["passes"] is True
    assert diagnostics["row_count"] == raw.height
    assert diagnostics["validity"]["duplicate_trip_id_count"] == 0
    assert diagnostics["suppression_or_nonreporting"]["pickup_indicator_status"] == (
        "unavailable"
    )
    assert manifest["config"]["sample_rows"] is None
    assert manifest["config"]["nyc_sample_days"] is None
    assert "sample_selection" not in manifest["source_metadata"]["known_measurement"]
    assert not (tmp_path / "NYC_FULL_INCOMPLETE.json").exists()

    second_config = DataConfig(
        source="nyc_hvfhv",
        mode="full",
        project_root=tmp_path,
        raw_dir=raw_dir,
        clean_dir=tmp_path / "second_clean",
        panel_dir=tmp_path / "second_panel",
        manifest_path=tmp_path / "second_manifest.json",
        diagnostics_path=tmp_path / "second_diagnostics.json",
        nyc_year=2024,
        nyc_months=(1,),
        nyc_batch_rows=137,
        panel_frequency="1h",
        complete_panel_grid=True,
    )
    second = run_data_pipeline(second_config)
    second_clean = read_partitioned_parquet(tmp_path / "second_clean/trips")
    assert set(second_clean.get_column("trip_id")) == set(clean.get_column("trip_id"))
    assert len(second.clean_files) == 6


def test_nyc_full_pipeline_rejects_readable_but_partial_cached_month(
    tmp_path: Path,
) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    raw_path = raw_dir / "fhvhv_tripdata_2024-01.parquet"
    _nyc_raw_frame().head(1).write_parquet(raw_path)
    config = DataConfig(
        source="nyc_hvfhv",
        mode="full",
        project_root=tmp_path,
        raw_dir=raw_dir,
        clean_dir=tmp_path / "clean",
        panel_dir=tmp_path / "panel",
        manifest_path=tmp_path / "manifest.json",
        diagnostics_path=tmp_path / "diagnostics.json",
        nyc_year=2024,
        nyc_months=(1,),
        nyc_batch_rows=1,
        panel_frequency="1h",
    )

    with pytest.raises(ValueError, match="configured calendar days"):
        run_data_pipeline(config)
    assert not config.manifest_path.exists()
    assert not (config.clean_dir / "trips").exists()
    assert (tmp_path / "NYC_FULL_INCOMPLETE.json").exists()


def test_nyc_full_exact_raw_mismatch_invalidates_old_manifest_and_keeps_marker(
    tmp_path: Path,
) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    raw_path = raw_dir / "fhvhv_tripdata_2024-01.parquet"
    _nyc_raw_frame().head(1).write_parquet(raw_path)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text('{"stale": true}\n', encoding="utf-8")
    config = DataConfig(
        source="nyc_hvfhv",
        mode="full",
        project_root=tmp_path,
        raw_dir=raw_dir,
        clean_dir=tmp_path / "clean",
        panel_dir=tmp_path / "panel",
        manifest_path=manifest_path,
        diagnostics_path=tmp_path / "diagnostics.json",
        nyc_year=2024,
        nyc_months=(1,),
        nyc_expected_rows=2,
        nyc_batch_rows=1,
        panel_frequency="1h",
    )

    with pytest.raises(ValueError, match="raw row-count mismatch"):
        run_data_pipeline(config)
    marker = tmp_path / "NYC_FULL_INCOMPLETE.json"
    assert marker.is_file()
    assert not manifest_path.exists()
    assert json.loads(marker.read_text(encoding="utf-8"))["status"] == "incomplete"


def test_missing_required_raw_columns_fail_before_normalization() -> None:
    with pytest.raises(ValueError, match="missing required columns"):
        normalize_trips(pl.DataFrame({"trip_id": ["x"]}), "chicago_tnp")


def test_partitioned_parquet_and_manifest_have_reproducible_checksums(
    tmp_path: Path,
    chicago_trips: pl.DataFrame,
) -> None:
    files = write_partitioned_parquet(chicago_trips, tmp_path / "clean")
    assert len(files) == 1
    assert "source=chicago_tnp" in str(files[0])
    restored = read_partitioned_parquet(tmp_path / "clean")
    assert restored.height == chicago_trips.height
    manifest = write_manifest(
        files,
        tmp_path / "manifest.json",
        metadata={"evidence_label": "descriptive_real_data", "causal_claim": False},
        root=tmp_path,
    )
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["files"][0]["sha256"] == sha256_file(files[0])
    assert payload["files"][0]["bytes"] == files[0].stat().st_size
    assert payload["metadata"]["causal_claim"] is False


def test_offline_pipeline_writes_clean_panel_diagnostics_and_manifest(tmp_path: Path) -> None:
    config = DataConfig(
        project_root=tmp_path,
        fixture_path=CHICAGO_FIXTURE,
        raw_dir=tmp_path / "raw",
        clean_dir=tmp_path / "clean",
        panel_dir=tmp_path / "panel",
        manifest_path=tmp_path / "manifest.json",
        diagnostics_path=tmp_path / "diagnostics.json",
        sample_rows=300,
    )
    artifacts = run_data_pipeline(config)
    assert artifacts.trip_rows == 300
    assert artifacts.panel_rows > 12
    assert artifacts.raw_files and artifacts.clean_files and artifacts.panel_files
    assert artifacts.od_flow_files
    assert artifacts.manifest_path.is_file()
    diagnostics = json.loads(artifacts.diagnostics_path.read_text(encoding="utf-8"))
    manifest = json.loads(artifacts.manifest_path.read_text(encoding="utf-8"))
    assert diagnostics["row_count"] == 300
    assert manifest["metadata"]["evidence_label"] == "descriptive_real_data"
    assert manifest["metadata"]["causal_claim"] is False


def test_unknown_origin_and_destination_are_not_called_intra_zone(
    chicago_trips: pl.DataFrame,
) -> None:
    unknown_pairs = chicago_trips.filter(
        pl.col("pickup_zone_id").is_null() & pl.col("dropoff_zone_id").is_null()
    )
    assert unknown_pairs.height > 0
    panel = build_zone_time_panel(unknown_pairs, frequency="1h")
    assert panel["intra_zone_share"].null_count() == panel.height
    assert panel["outbound_trip_count"].null_count() == panel.height
    assert panel["distinct_dropoff_zones"].null_count() == panel.height
    assert panel["od_pair_observed_count"].sum() == 0
    assert panel["od_pair_observed_share"].sum() == 0.0

    complete = build_zone_time_panel(unknown_pairs, frequency="1h", complete_grid=True)
    observed_unknown = complete.filter(pl.col("trip_count") > 0)
    assert observed_unknown["intra_zone_share"].null_count() == observed_unknown.height
    assert observed_unknown["outbound_trip_count"].null_count() == observed_unknown.height
    assert observed_unknown["distinct_dropoff_zones"].null_count() == observed_unknown.height


def test_partition_writer_removes_stale_parquet_when_overwriting(tmp_path: Path) -> None:
    first = pl.DataFrame({"source": ["a", "b"], "value": [1, 2]})
    second = pl.DataFrame({"source": ["a"], "value": [3]})
    root = tmp_path / "dataset"
    write_partitioned_parquet(first, root, partition_by=("source",))
    assert len(list(root.rglob("*.parquet"))) == 2
    files = write_partitioned_parquet(second, root, partition_by=("source",))
    assert len(files) == 1
    assert len(list(root.rglob("*.parquet"))) == 1
    assert read_partitioned_parquet(root)["value"].to_list() == [3]
