from __future__ import annotations

from datetime import UTC, date, datetime

import polars as pl
import pytest

from macro_nowcast.asof import select_as_of
from macro_nowcast.calendar import (
    build_all_target_release_calendars,
    build_forecast_origins,
    build_target_release_calendar,
)
from macro_nowcast.sample_data import (
    ALL_SERIES_IDS,
    build_multitarget_synthetic_fixture,
)


@pytest.fixture(scope="module")
def fixture():
    return build_multitarget_synthetic_fixture()


def test_fixture_adds_monthly_core_cpi_and_quarterly_real_gdp_levels(fixture) -> None:
    observations = fixture.observations
    assert {"CPILFESL", "GDPC1"}.issubset(ALL_SERIES_IDS)

    cpi = observations.filter(pl.col("series_id") == "CPILFESL")
    gdp = observations.filter(pl.col("series_id") == "GDPC1")

    assert cpi["observation_date"].min() == date(2017, 1, 1)
    assert cpi["observation_date"].max() == date(2025, 3, 1)
    assert cpi["observation_date"].n_unique() == 99
    assert set(cpi.group_by("observation_date").len()["len"]) == {2}
    assert set(cpi["frequency"].unique()) == {"monthly"}
    assert set(cpi["transformation"].unique()) == {"level"}
    assert set(cpi["units"].unique()) == {"index_1982_1984_100"}

    assert gdp["observation_date"].min() == date(2017, 1, 1)
    assert gdp["observation_date"].max() == date(2025, 1, 1)
    assert gdp["observation_date"].n_unique() == 33
    assert set(gdp.group_by("observation_date").len()["len"]) == {3}
    assert set(gdp["frequency"].unique()) == {"quarterly"}
    assert set(gdp["transformation"].unique()) == {"level"}
    assert set(gdp["units"].unique()) == {"billions_of_chained_2017_dollars"}

    new_targets = pl.concat([cpi, gdp])
    assert new_targets["availability_timestamp"].null_count() == 0
    assert new_targets.schema["availability_timestamp"] == pl.Datetime("us", "UTC")
    assert set(new_targets["provenance_label"].unique()) == {"synthetic_fixture"}


def test_target_calendars_match_first_vintage_and_build_strict_origins(fixture) -> None:
    assert fixture.cpi_release_calendar is not None
    assert fixture.gdp_release_calendar is not None
    combined = fixture.all_target_release_calendar

    assert set(fixture.release_calendar["series_id"].unique()) == {"PAYEMS"}
    assert set(combined["series_id"].unique()) == {"PAYEMS", "CPILFESL", "GDPC1"}
    assert combined.height == 99 + 99 + 33
    assert set(combined["provenance_label"].unique()) == {"synthetic_fixture"}
    assert combined.schema["release_timestamp"] == pl.Datetime("us", "UTC")

    first_vintages = (
        fixture.observations.filter(pl.col("series_id").is_in(["CPILFESL", "GDPC1"]))
        .group_by(["series_id", "observation_date"])
        .agg(pl.col("availability_timestamp").min().alias("first_availability"))
    )
    calendar_check = combined.filter(
        pl.col("series_id").is_in(["CPILFESL", "GDPC1"])
    ).join(first_vintages, on=["series_id", "observation_date"], validate="1:1")
    assert calendar_check.filter(
        pl.col("release_timestamp") != pl.col("first_availability")
    ).is_empty()

    origins = build_forecast_origins(combined)
    assert origins.height == combined.height
    assert origins.filter(
        pl.col("forecast_origin") >= pl.col("target_release_timestamp")
    ).is_empty()
    assert set(origins["target_series_id"].unique()) == {"PAYEMS", "CPILFESL", "GDPC1"}


def test_generic_calendar_dispatch_is_deterministic_and_explicitly_synthetic() -> None:
    start = date(2020, 1, 1)
    end = date(2020, 6, 1)
    cpi = build_target_release_calendar("cpilfesl", start, end)
    gdp = build_target_release_calendar("GDPC1", start, end)

    assert cpi.height == 6
    assert gdp.height == 2
    assert cpi["release_timestamp"].to_list()[0] == datetime(
        2020, 2, 12, 13, 30, tzinfo=UTC
    )
    assert gdp["release_timestamp"].to_list()[0] == datetime(
        2020, 4, 28, 12, 30, tzinfo=UTC
    )
    assert set(pl.concat([cpi, gdp])["timing_quality"].unique()) == {"synthetic_exact"}
    with pytest.raises(ValueError, match="unsupported target series"):
        build_target_release_calendar("NOT_A_TARGET", start, end)


def test_new_target_vintages_are_deterministic_and_asof_selectable() -> None:
    first = build_multitarget_synthetic_fixture(
        start=date(2017, 1, 1), end=date(2018, 3, 1)
    )
    second = build_multitarget_synthetic_fixture(
        start=date(2017, 1, 1), end=date(2018, 3, 1)
    )
    target_filter = pl.col("series_id").is_in(["CPILFESL", "GDPC1"])
    assert first.observations.filter(target_filter).equals(
        second.observations.filter(target_filter)
    )
    assert build_all_target_release_calendars(
        date(2017, 1, 1), date(2018, 3, 1)
    ).equals(first.all_target_release_calendar)

    cpi_period = date(2017, 1, 1)
    cpi_rows = first.observations.filter(
        (pl.col("series_id") == "CPILFESL")
        & (pl.col("observation_date") == cpi_period)
    ).sort("availability_timestamp")
    initial_time, revised_time = cpi_rows["availability_timestamp"].to_list()
    initial = select_as_of(first.observations, initial_time).filter(
        (pl.col("series_id") == "CPILFESL")
        & (pl.col("observation_date") == cpi_period)
    )
    revised = select_as_of(first.observations, revised_time).filter(
        (pl.col("series_id") == "CPILFESL")
        & (pl.col("observation_date") == cpi_period)
    )
    assert initial["realtime_start"].item() != revised["realtime_start"].item()
    assert initial["selected_vintage_availability_timestamp"].item() == initial_time
    assert revised["selected_vintage_availability_timestamp"].item() == revised_time
