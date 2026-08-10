from __future__ import annotations

from datetime import UTC, date, datetime

import polars as pl
import pytest

from macro_nowcast.calendar import (
    RELEASE_CALENDAR_SCHEMA,
    build_forecast_origins,
)
from macro_nowcast.features import (
    DEFAULT_FEATURE_SPECS,
    REAL_GDP_FEATURE_SPECS,
    FeatureSpec,
    assert_feature_no_future,
    build_feature_matrix,
    build_feature_vector,
    build_payems_targets,
)
from macro_nowcast.sample_data import build_synthetic_fixture
from macro_nowcast.schema import VintageObservation, observations_to_frame


def _payems(
    observation_date: date,
    available_at: datetime,
    value: float,
) -> VintageObservation:
    return VintageObservation(
        series_id="PAYEMS",
        observation_date=observation_date,
        realtime_start=available_at.date(),
        availability_date=available_at.date(),
        availability_timestamp=available_at,
        release_timestamp=available_at,
        value=value,
        units="thousands_of_persons",
        frequency="monthly",
        seasonal_adjustment="seasonally_adjusted",
        transformation="level",
        download_timestamp=datetime(2026, 8, 7, tzinfo=UTC),
        source="test_fixture",
        provenance_label="synthetic_fixture",
        source_metadata={"fixture_kind": "synthetic_fixture"},
    )


def _level(
    series_id: str,
    observation_date: date,
    available_at: datetime,
    value: float,
    *,
    frequency: str,
) -> VintageObservation:
    return VintageObservation(
        series_id=series_id,
        observation_date=observation_date,
        realtime_start=available_at.date(),
        availability_date=available_at.date(),
        availability_timestamp=available_at,
        release_timestamp=available_at,
        value=value,
        units="index",
        frequency=frequency,
        seasonal_adjustment="seasonally_adjusted",
        transformation="level",
        download_timestamp=datetime(2026, 8, 7, tzinfo=UTC),
        source="test_fixture",
        provenance_label="synthetic_fixture",
        source_metadata={"fixture_kind": "synthetic_fixture"},
    )


def test_monthly_transformation_occurs_after_vintage_selection() -> None:
    observations = observations_to_frame(
        [
            _payems(date(2019, 12, 1), datetime(2020, 1, 10, tzinfo=UTC), 100.0),
            _payems(date(2019, 12, 1), datetime(2020, 3, 10, tzinfo=UTC), 110.0),
            _payems(date(2020, 1, 1), datetime(2020, 2, 10, tzinfo=UTC), 120.0),
        ]
    )
    spec = FeatureSpec(
        "payems_change",
        "PAYEMS",
        "monthly",
        "difference",
        "latest",
    )

    February_view = build_feature_vector(
        observations,
        as_of=datetime(2020, 2, 11, tzinfo=UTC),
        target_period=date(2020, 1, 1),
        specs=[spec],
    )
    March_view = build_feature_vector(
        observations,
        as_of=datetime(2020, 3, 11, tzinfo=UTC),
        target_period=date(2020, 1, 1),
        specs=[spec],
    )

    assert February_view["value"].item() == pytest.approx(20.0)
    assert March_view["value"].item() == pytest.approx(10.0)
    assert (
        February_view["max_source_availability"].item() <= February_view["as_of_timestamp"].item()
    )


def test_fixture_feature_vector_is_long_audited_and_has_no_future_inputs() -> None:
    fixture = build_synthetic_fixture()
    origins = build_forecast_origins(fixture.release_calendar)
    origin = origins.filter(pl.col("target_period") == date(2024, 12, 1)).row(0, named=True)

    features = build_feature_vector(
        fixture.observations,
        as_of=origin["forecast_origin"],
        target_period=origin["target_period"],
    )

    assert features.height == len(DEFAULT_FEATURE_SPECS) == 10
    assert features["feature_name"].n_unique() == 10
    assert set(features["provenance_label"].unique()) == {"synthetic_fixture"}
    assert features.filter(pl.col("max_source_availability") > pl.col("as_of_timestamp")).is_empty()
    assert (
        features.filter(pl.col("source_series_id") == "ICSA")["source_observation_count"].item()
        == 4
    )
    assert (
        features.filter(pl.col("source_series_id") == "DGS10")["source_observation_count"].item()
        == 20
    )
    assert_feature_no_future(features)


def test_counterfactual_features_are_labeled_and_keep_eligible_cells_only() -> None:
    observations = observations_to_frame(
        [
            _payems(date(2019, 12, 1), datetime(2020, 1, 10, tzinfo=UTC), 100.0),
            _payems(date(2019, 12, 1), datetime(2020, 3, 10, tzinfo=UTC), 110.0),
            _payems(date(2020, 1, 1), datetime(2020, 2, 10, tzinfo=UTC), 120.0),
        ]
    )
    spec = FeatureSpec("payems_level", "PAYEMS", "monthly", "level", "latest")
    cutoff = datetime(2020, 1, 11, tzinfo=UTC)

    feature = build_feature_vector(
        observations,
        as_of=cutoff,
        target_period=date(2019, 12, 1),
        specs=[spec],
        mode="latest_values_same_eligibility_mask",
    )

    assert feature["value"].item() == 110.0
    assert feature["is_counterfactual"].item() is True
    assert feature["max_source_availability"].item() > cutoff
    assert feature["max_eligibility_availability"].item() <= cutoff
    assert_feature_no_future(feature)


def test_naive_latest_benchmark_exposes_and_labels_release_timing_leakage() -> None:
    origin = datetime(2020, 1, 31, 13, 29, 59, tzinfo=UTC)
    observations = observations_to_frame(
        [
            _payems(date(2019, 12, 1), datetime(2020, 1, 10, tzinfo=UTC), 100.0),
            _payems(date(2020, 1, 1), datetime(2020, 2, 7, 13, 30, tzinfo=UTC), 120.0),
            _payems(date(2020, 1, 1), datetime(2020, 3, 6, 13, 30, tzinfo=UTC), 125.0),
        ]
    )
    spec = FeatureSpec("payems_change", "PAYEMS", "monthly", "difference", "latest")

    feature = build_feature_vector(
        observations,
        as_of=origin,
        target_period=date(2020, 1, 1),
        specs=[spec],
        mode="naive_latest_revised",
    )

    assert feature["value"].item() == pytest.approx(25.0)
    assert feature["information_set_mode"].item() == "naive_latest_revised"
    assert feature["is_counterfactual"].item() is True
    assert feature["max_eligibility_availability"].item() > origin
    assert feature["max_source_availability"].item() > origin
    assert_feature_no_future(feature)


def test_feature_matrix_uses_each_explicit_historical_origin() -> None:
    fixture = build_synthetic_fixture(start=date(2019, 1, 1), end=date(2020, 6, 1))
    origins = build_forecast_origins(fixture.release_calendar).tail(2)
    specs = [FeatureSpec("unrate", "UNRATE", "monthly", "level", "latest")]

    matrix = build_feature_matrix(fixture.observations, origins, specs=specs)

    assert matrix.height == 2
    assert matrix["forecast_id"].n_unique() == 2
    expected_origins = set(origins["forecast_origin"].to_list())
    assert set(matrix["as_of_timestamp"].to_list()) == expected_origins


def test_first_release_target_uses_both_levels_from_same_release_snapshot() -> None:
    first_release = datetime(2020, 2, 7, 13, 30, tzinfo=UTC)
    later_vintage = datetime(2020, 3, 6, 13, 30, tzinfo=UTC)
    observations = observations_to_frame(
        [
            _payems(date(2019, 12, 1), datetime(2020, 1, 10, tzinfo=UTC), 100.0),
            _payems(date(2019, 12, 1), first_release, 105.0),
            _payems(date(2020, 1, 1), first_release, 120.0),
            _payems(date(2019, 12, 1), later_vintage, 107.0),
            _payems(date(2020, 1, 1), later_vintage, 130.0),
        ]
    )
    calendar = pl.from_dicts(
        [
            {
                "release_id": "synthetic-payems-2020-01-initial",
                "series_id": "PAYEMS",
                "observation_date": date(2020, 1, 1),
                "release_timestamp": first_release,
                "release_type": "initial",
                "timing_quality": "synthetic_exact",
                "source": "test_fixture",
                "provenance_label": "synthetic_fixture",
            }
        ],
        schema=RELEASE_CALENDAR_SCHEMA,
        strict=True,
    )

    targets = build_payems_targets(
        observations,
        calendar,
        latest_as_of=datetime(2020, 3, 7, tzinfo=UTC),
    )
    first = targets.filter(pl.col("realization_mode") == "first_release").row(0, named=True)
    latest = targets.filter(pl.col("realization_mode") == "latest_revised").row(0, named=True)

    assert first["value"] == pytest.approx(15.0)  # 120 - same-release revised 105
    assert first["prior_level_availability"] == first_release
    assert first["current_level_availability"] == first_release
    assert latest["value"] == pytest.approx(23.0)
    assert latest["realization_as_of_timestamp"] == datetime(2020, 3, 7, tzinfo=UTC)


def test_quarterly_feature_uses_quarter_lag_and_exact_saar_transform() -> None:
    available_at = datetime(2020, 1, 30, 13, 30, tzinfo=UTC)
    observations = observations_to_frame(
        [
            _level(
                "GDPC1",
                date(2019, 7, 1),
                datetime(2019, 10, 30, 13, 30, tzinfo=UTC),
                100.0,
                frequency="quarterly",
            ),
            _level(
                "GDPC1",
                date(2019, 10, 1),
                available_at,
                101.0,
                frequency="quarterly",
            ),
        ]
    )

    feature = build_feature_vector(
        observations,
        as_of=datetime(2020, 4, 28, 12, 29, 59, tzinfo=UTC),
        target_period=date(2020, 1, 1),
        target_frequency="quarterly",
        target_series_id="GDPC1",
        specs=[REAL_GDP_FEATURE_SPECS[0]],
    ).row(0, named=True)

    assert feature["value"] == pytest.approx(((101.0 / 100.0) ** 4 - 1.0) * 100.0)
    assert feature["source_period_cutoff"] == date(2019, 10, 1)
    assert feature["source_staleness_periods"] == 0
    assert feature["staleness_unit"] == "quarters"
    assert feature["is_partial_period"] is False


def test_monthly_indicator_for_gdp_exposes_partial_quarter_staleness() -> None:
    observations = observations_to_frame(
        [
            _level(
                "INDPRO",
                date(2020, 1, 1),
                datetime(2020, 2, 16, 14, 15, tzinfo=UTC),
                100.0,
                frequency="monthly",
            ),
            _level(
                "INDPRO",
                date(2020, 2, 1),
                datetime(2020, 3, 16, 14, 15, tzinfo=UTC),
                101.0,
                frequency="monthly",
            ),
            _level(
                "INDPRO",
                date(2020, 3, 1),
                datetime(2020, 4, 30, 14, 15, tzinfo=UTC),
                102.0,
                frequency="monthly",
            ),
        ]
    )

    feature = build_feature_vector(
        observations,
        as_of=datetime(2020, 4, 28, 12, 29, 59, tzinfo=UTC),
        target_period=date(2020, 1, 1),
        target_frequency="quarterly",
        target_series_id="GDPC1",
        specs=[FeatureSpec("indpro_level", "INDPRO", "monthly", "level", "latest")],
    ).row(0, named=True)

    assert feature["value"] == 101.0
    assert feature["source_period_cutoff"] == date(2020, 3, 1)
    assert feature["latest_source_observation_date"] == date(2020, 2, 1)
    assert feature["source_staleness_periods"] == 1
    assert feature["is_partial_period"] is True
    assert feature["period_observation_count"] == 2
    assert feature["expected_period_observation_count"] == 3
    assert feature["coverage_ratio"] == pytest.approx(2 / 3)
    assert feature["max_source_availability"] <= feature["as_of_timestamp"]
