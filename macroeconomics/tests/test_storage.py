from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl
import pytest

from macro_nowcast.schema import VintageObservation, observations_to_frame
from macro_nowcast.storage import (
    ArtifactExistsError,
    DuplicateVintageError,
    VintageStore,
)


def _row(*, realtime_start: date, value: float) -> VintageObservation:
    return VintageObservation(
        series_id="PAYEMS",
        observation_date=date(2020, 1, 1),
        realtime_start=realtime_start,
        realtime_end=date(9999, 12, 31),
        availability_date=realtime_start,
        release_timestamp=datetime.combine(realtime_start, datetime.min.time(), UTC),
        availability_timestamp=datetime.combine(realtime_start, datetime.max.time(), UTC),
        value=value,
        units="thousands_of_persons",
        frequency="monthly",
        seasonal_adjustment="seasonally_adjusted",
        transformation="level",
        download_timestamp=datetime(2026, 8, 7, 15, 0, tzinfo=UTC),
        source="alfred",
        provenance_label="synthetic_fixture",
        source_metadata={"fixture": "payroll", "revision": value != 152100.0},
    )


def test_parquet_round_trip_and_duckdb_query(tmp_path: Path) -> None:
    store = VintageStore(tmp_path / "parquet", tmp_path / "catalog.duckdb")
    rows = [
        _row(realtime_start=date(2020, 2, 7), value=152100.0),
        _row(realtime_start=date(2020, 3, 6), value=152120.0),
    ]

    artifact = store.write_observations(rows)
    restored = store.read_observations()
    query = store.query(
        "SELECT count(*) AS n, max(value) AS latest_value FROM vintage_observations"
    )

    assert artifact.is_file()
    assert restored.schema == observations_to_frame(rows).schema
    assert restored["availability_date"].to_list() == [date(2020, 2, 7), date(2020, 3, 6)]
    assert store.read_rows()[1].source_metadata["revision"] is True
    assert query.to_dicts() == [{"n": 2, "latest_value": 152120.0}]
    assert store.list_datasets() == ("vintage_observations",)


def test_writes_are_immutable_by_default(tmp_path: Path) -> None:
    store = VintageStore(tmp_path / "parquet", tmp_path / "catalog.duckdb")
    row = _row(realtime_start=date(2020, 2, 7), value=152100.0)
    store.write_observations([row])

    with pytest.raises(ArtifactExistsError):
        store.write_observations([row])

    store.write_observations([row], overwrite=True)
    assert store.read_observations().height == 1


def test_duplicate_vintage_keys_are_rejected(tmp_path: Path) -> None:
    store = VintageStore(tmp_path / "parquet", tmp_path / "catalog.duckdb")
    row = _row(realtime_start=date(2020, 2, 7), value=152100.0)
    duplicate_frame = pl.concat([observations_to_frame([row]), observations_to_frame([row])])

    with pytest.raises(DuplicateVintageError):
        store.write_observations(duplicate_frame)
