from __future__ import annotations

from datetime import UTC, date, datetime

import polars as pl
import pytest

from macro_nowcast.calendar import RELEASE_CALENDAR_SCHEMA
from macro_nowcast.features import TARGET_SCHEMA as LEGACY_TARGET_SCHEMA
from macro_nowcast.schema import VintageObservation, observations_to_frame
from macro_nowcast.targets import (
    CORE_CPI_TARGET_SPEC,
    DEFAULT_TARGET_SPECS,
    PAYEMS_TARGET_SPEC,
    PUBLISHED_REAL_GDP_TARGET_SPEC,
    REAL_GDP_TARGET_SPEC,
    TARGET_AUDIT_SCHEMA,
    TargetSpec,
    assert_target_audit,
    build_targets,
    build_targets_for_spec,
)


def _observation(
    series_id: str,
    period: date,
    available_at: datetime,
    value: float,
    *,
    units: str = "index",
    frequency: str = "monthly",
) -> VintageObservation:
    return VintageObservation(
        series_id=series_id,
        observation_date=period,
        realtime_start=available_at.date(),
        availability_date=available_at.date(),
        availability_timestamp=available_at,
        release_timestamp=available_at,
        value=value,
        units=units,
        frequency=frequency,
        seasonal_adjustment="seasonally_adjusted",
        transformation="level",
        download_timestamp=available_at,
        source="test_fixture",
        provenance_label="synthetic_fixture",
    )


def _calendar(
    series_id: str,
    target_period: date,
    release_timestamp: datetime,
) -> pl.DataFrame:
    return pl.from_dicts(
        [
            {
                "release_id": f"synthetic-{series_id.lower()}-{target_period}-initial",
                "series_id": series_id,
                "observation_date": target_period,
                "release_timestamp": release_timestamp,
                "release_type": "initial",
                "timing_quality": "synthetic_exact",
                "source": "test_fixture",
                "provenance_label": "synthetic_fixture",
            }
        ],
        schema=RELEASE_CALENDAR_SCHEMA,
        strict=True,
    )


def test_default_specs_have_explicit_noninterchangeable_formulas() -> None:
    assert {spec.series_id for spec in DEFAULT_TARGET_SPECS} == {
        "PAYEMS",
        "CPILFESL",
        "GDPC1",
    }
    assert PAYEMS_TARGET_SPEC.transform_levels(120.0, 105.0) == pytest.approx(15.0)
    assert CORE_CPI_TARGET_SPEC.transform_levels(101.0, 100.0) == pytest.approx(1.0)
    assert REAL_GDP_TARGET_SPEC.transform_levels(101.0, 100.0) == pytest.approx(
        100.0 * (1.01**4 - 1.0)
    )
    assert CORE_CPI_TARGET_SPEC.annualization_factor is None
    assert REAL_GDP_TARGET_SPEC.annualization_factor == 4

    with pytest.raises(ValueError, match="annualization_factor"):
        TargetSpec(
            "X",
            "bad_target",
            "percent",
            "quarterly",
            "compounded_percent_change",
        )


def test_first_release_uses_current_and_revised_prior_from_same_snapshot() -> None:
    earlier = datetime(2020, 1, 10, 13, 30, tzinfo=UTC)
    release = datetime(2020, 2, 7, 13, 30, tzinfo=UTC)
    later = datetime(2020, 3, 6, 13, 30, tzinfo=UTC)
    observations = observations_to_frame(
        [
            _observation("PAYEMS", date(2019, 12, 1), earlier, 100.0),
            _observation("PAYEMS", date(2019, 12, 1), release, 105.0),
            _observation("PAYEMS", date(2020, 1, 1), release, 120.0),
            _observation("PAYEMS", date(2019, 12, 1), later, 107.0),
            _observation("PAYEMS", date(2020, 1, 1), later, 130.0),
        ]
    )
    targets = build_targets_for_spec(
        observations,
        _calendar("PAYEMS", date(2020, 1, 1), release),
        PAYEMS_TARGET_SPEC,
        latest_as_of=datetime(2020, 3, 7, tzinfo=UTC),
        built_at=datetime(2020, 3, 8, tzinfo=UTC),
    )
    first = targets.filter(pl.col("realization_mode") == "first_release").row(
        0, named=True
    )
    latest = targets.filter(pl.col("realization_mode") == "latest_revised").row(
        0, named=True
    )

    assert first["value"] == pytest.approx(15.0)
    assert first["prior_level"] == pytest.approx(105.0)
    assert first["current_level_availability"] == release
    assert first["prior_level_availability"] == release
    assert first["snapshot_timestamp"] == release
    assert latest["value"] == pytest.approx(23.0)
    assert latest["snapshot_timestamp"] == datetime(2020, 3, 7, tzinfo=UTC)
    assert first["provenance_label"] == "synthetic_fixture"
    assert_target_audit(targets)


@pytest.mark.parametrize(
    ("spec", "series_id", "prior_period", "target_period", "prior", "current", "expected"),
    [
        (
            CORE_CPI_TARGET_SPEC,
            "CPILFESL",
            date(2024, 1, 1),
            date(2024, 2, 1),
            100.0,
            101.0,
            1.0,
        ),
        (
            REAL_GDP_TARGET_SPEC,
            "GDPC1",
            date(2023, 10, 1),
            date(2024, 1, 1),
            100.0,
            101.0,
            100.0 * (1.01**4 - 1.0),
        ),
    ],
)
def test_configured_cpi_and_gdp_target_math(
    spec: TargetSpec,
    series_id: str,
    prior_period: date,
    target_period: date,
    prior: float,
    current: float,
    expected: float,
) -> None:
    release = datetime(2024, 4, 25, 12, 30, tzinfo=UTC)
    frequency = "quarterly" if series_id == "GDPC1" else "monthly"
    observations = observations_to_frame(
        [
            _observation(series_id, prior_period, release, prior, frequency=frequency),
            _observation(series_id, target_period, release, current, frequency=frequency),
        ]
    )
    targets = build_targets_for_spec(
        observations,
        _calendar(series_id, target_period, release),
        spec,
        latest_as_of=release,
        modes=("first_release",),
        built_at=release,
    )

    assert targets.height == 1
    assert targets["value"].item() == pytest.approx(expected)
    assert targets["target_units"].item() == spec.target_units
    assert targets["is_annualized"].item() is spec.is_annualized
    assert targets["target_formula"].item() == spec.formula


def test_latest_revised_never_selects_a_post_cutoff_target_vintage() -> None:
    release = datetime(2024, 2, 1, 13, 30, tzinfo=UTC)
    cutoff = datetime(2024, 2, 15, 0, 0, tzinfo=UTC)
    after_cutoff = datetime(2024, 3, 1, 13, 30, tzinfo=UTC)
    observations = observations_to_frame(
        [
            _observation("CPILFESL", date(2023, 12, 1), release, 100.0),
            _observation("CPILFESL", date(2024, 1, 1), release, 101.0),
            _observation("CPILFESL", date(2023, 12, 1), after_cutoff, 50.0),
            _observation("CPILFESL", date(2024, 1, 1), after_cutoff, 150.0),
        ]
    )
    targets = build_targets_for_spec(
        observations,
        _calendar("CPILFESL", date(2024, 1, 1), release),
        CORE_CPI_TARGET_SPEC,
        latest_as_of=cutoff,
        modes=("latest_revised",),
        built_at=cutoff,
    )

    assert targets["value"].item() == pytest.approx(1.0)
    assert targets["max_source_availability"].item() <= cutoff
    assert targets["realization_as_of_timestamp"].item() == cutoff
    assert_target_audit(targets)


def test_published_gdp_target_is_not_retransformed_or_reannualized() -> None:
    release = datetime(2025, 1, 30, 23, 59, 59, 999999, tzinfo=UTC)
    revision = datetime(2025, 2, 27, 23, 59, 59, 999999, tzinfo=UTC)
    series_id = PUBLISHED_REAL_GDP_TARGET_SPEC.series_id
    observations = observations_to_frame(
        [
            _observation(
                series_id,
                date(2024, 10, 1),
                release,
                2.3,
                units="percent_change_qoq_saar",
                frequency="quarterly",
            ),
            _observation(
                series_id,
                date(2024, 10, 1),
                revision,
                2.5,
                units="percent_change_qoq_saar",
                frequency="quarterly",
            ),
        ]
    )
    targets = build_targets_for_spec(
        observations,
        _calendar(series_id, date(2024, 10, 1), release),
        PUBLISHED_REAL_GDP_TARGET_SPEC,
        latest_as_of=revision,
        built_at=revision,
    )

    assert targets["target_series_id"].unique().to_list() == ["GDPC1"]
    assert targets["value"].to_list() == [2.3, 2.5]
    assert targets["target_formula"].unique().to_list() == [
        "official_published_value_already_transformed_no_retransformation"
    ]
    assert targets["is_annualized"].all()
    assert targets["annualization_factor"].null_count() == 2
    assert targets["current_level"].null_count() == 2
    assert targets["prior_level"].null_count() == 2
    assert_target_audit(targets)


def test_future_release_is_not_built_and_calendar_must_be_explicit_utc() -> None:
    release = datetime(2024, 2, 1, 13, 30, tzinfo=UTC)
    observations = observations_to_frame(
        [
            _observation("CPILFESL", date(2023, 12, 1), release, 100.0),
            _observation("CPILFESL", date(2024, 1, 1), release, 101.0),
        ]
    )
    calendar = _calendar("CPILFESL", date(2024, 1, 1), release)
    targets = build_targets(
        observations,
        calendar,
        latest_as_of=datetime(2024, 1, 31, tzinfo=UTC),
        specs=(CORE_CPI_TARGET_SPEC,),
        built_at=release,
    )
    assert targets.is_empty()

    naive_calendar = calendar.with_columns(
        pl.col("release_timestamp").dt.replace_time_zone(None)
    )
    with pytest.raises(ValueError, match="explicit UTC"):
        build_targets(
            observations,
            naive_calendar,
            latest_as_of=release,
            specs=(CORE_CPI_TARGET_SPEC,),
            built_at=release,
        )


def test_extended_target_schema_preserves_legacy_columns_and_types() -> None:
    for column, dtype in LEGACY_TARGET_SCHEMA.items():
        assert TARGET_AUDIT_SCHEMA[column] == dtype
