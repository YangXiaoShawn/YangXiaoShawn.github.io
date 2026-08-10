from __future__ import annotations

from datetime import UTC, date, datetime

import polars as pl
import pytest

from macro_nowcast.asof import (
    assert_no_future_information,
    select_as_of,
    select_latest_values_same_eligibility_mask,
)
from macro_nowcast.sample_data import SERIES_IDS, build_synthetic_fixture
from macro_nowcast.schema import VintageObservation, observations_to_frame


def _observation(
    observation_date: date,
    available_at: datetime,
    value: float | None,
    *,
    series_id: str = "TEST",
    exact_time: bool = True,
) -> VintageObservation:
    return VintageObservation(
        series_id=series_id,
        observation_date=observation_date,
        realtime_start=available_at.date(),
        availability_date=available_at.date(),
        availability_timestamp=available_at if exact_time else None,
        release_timestamp=available_at if exact_time else None,
        value=value,
        units="index",
        frequency="monthly",
        seasonal_adjustment="not_applicable",
        transformation="level",
        download_timestamp=datetime(2026, 8, 7, tzinfo=UTC),
        source="test_fixture",
        provenance_label="synthetic_fixture",
        source_metadata={"fixture_kind": "synthetic_fixture"},
    )


def test_synthetic_fixture_spans_mixed_frequencies_with_prominent_provenance() -> None:
    fixture = build_synthetic_fixture()

    assert set(fixture.observations["series_id"].unique()) == set(SERIES_IDS)
    assert fixture.observations["observation_date"].min() == date(2017, 1, 1)
    assert fixture.observations["observation_date"].max() >= date(2025, 3, 1)
    assert set(fixture.observations["frequency"].unique()) == {
        "daily",
        "monthly",
        "weekly",
    }
    assert set(fixture.observations["provenance_label"].unique()) == {
        "synthetic_fixture"
    }
    assert fixture.observations["availability_timestamp"].null_count() == 0
    assert fixture.observations.schema["availability_timestamp"] == pl.Datetime("us", "UTC")


def test_asof_uses_exact_utc_boundary_and_excludes_future_release() -> None:
    first = datetime(2020, 2, 3, 13, 30, tzinfo=UTC)
    second = datetime(2020, 3, 6, 13, 30, tzinfo=UTC)
    observations = observations_to_frame(
        [
            _observation(date(2020, 1, 1), first, 100.0),
            _observation(date(2020, 2, 1), second, 200.0),
        ]
    )

    before = select_as_of(observations, datetime(2020, 2, 3, 13, 29, 59, tzinfo=UTC))
    at_release = select_as_of(observations, first)

    assert before.is_empty()
    assert at_release["value"].to_list() == [100.0]
    assert at_release["observation_date"].to_list() == [date(2020, 1, 1)]
    assert_no_future_information(at_release)


def test_date_only_availability_uses_conservative_end_of_day() -> None:
    available_date = datetime(2020, 2, 3, tzinfo=UTC)
    observations = observations_to_frame(
        [_observation(date(2020, 1, 1), available_date, 100.0, exact_time=False)]
    )

    midday = select_as_of(observations, datetime(2020, 2, 3, 12, 0, tzinfo=UTC))
    next_day = select_as_of(observations, datetime(2020, 2, 4, 0, 0, tzinfo=UTC))

    assert midday.is_empty()
    assert next_day["value"].to_list() == [100.0]


def test_latest_missing_vintage_is_ranked_without_resurrecting_old_value() -> None:
    observations = observations_to_frame(
        [
            _observation(
                date(2020, 1, 1), datetime(2020, 2, 3, 13, 30, tzinfo=UTC), 100.0
            ),
            _observation(
                date(2020, 1, 1), datetime(2020, 3, 6, 13, 30, tzinfo=UTC), None
            ),
        ]
    )

    snapshot = select_as_of(observations, datetime(2020, 3, 7, tzinfo=UTC))

    assert snapshot.height == 1
    assert snapshot["value"].to_list() == [None]
    assert snapshot["realtime_start"].to_list() == [date(2020, 3, 6)]


def test_latest_values_counterfactual_preserves_historical_eligibility_mask() -> None:
    observations = observations_to_frame(
        [
            _observation(
                date(2020, 1, 1), datetime(2020, 2, 3, 13, 30, tzinfo=UTC), 100.0
            ),
            _observation(
                date(2020, 1, 1), datetime(2020, 3, 6, 13, 30, tzinfo=UTC), 110.0
            ),
            _observation(
                date(2020, 2, 1), datetime(2020, 3, 6, 13, 30, tzinfo=UTC), 200.0
            ),
        ]
    )
    cutoff = datetime(2020, 2, 4, tzinfo=UTC)

    counterfactual = select_latest_values_same_eligibility_mask(observations, cutoff)

    assert counterfactual["observation_date"].to_list() == [date(2020, 1, 1)]
    assert counterfactual["value"].to_list() == [110.0]
    assert counterfactual["eligibility_timestamp"].item() <= cutoff
    assert counterfactual["selected_vintage_availability_timestamp"].item() > cutoff
    assert counterfactual["is_counterfactual"].item() is True
    with pytest.raises(ValueError, match="counterfactual"):
        assert_no_future_information(counterfactual)


def test_naive_asof_datetime_is_rejected() -> None:
    observations = observations_to_frame(
        [
            _observation(
                date(2020, 1, 1), datetime(2020, 2, 3, 13, 30, tzinfo=UTC), 100.0
            )
        ]
    )
    with pytest.raises(ValueError, match="timezone"):
        select_as_of(observations, datetime(2020, 2, 4))
