from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import polars as pl

from macro_nowcast.asof import AS_OF_MODE, LATEST_SAME_MASK_MODE, NAIVE_LATEST_MODE
from macro_nowcast.calendar import (
    DATE_ONLY_TIMING_QUALITY,
    RELEASE_CALENDAR_SCHEMA,
)
from macro_nowcast.census_housing_archive import CENSUS_HOUSING_STARTS_SERIES_ID
from macro_nowcast.census_retail_archive import CENSUS_RETAIL_MOM_SERIES_ID
from macro_nowcast.features import FeatureSpec
from macro_nowcast.fed_g17_archive import FED_G17_MOM_SERIES_ID
from macro_nowcast.models import HistoricalMeanRegressor, NoChangeRegressor
from macro_nowcast.official_pipeline import (
    OFFICIAL_PROVENANCE,
    PILOT_TARGETS,
    OfficialPilotTarget,
    build_official_news_updates,
    build_official_pilot_features,
    build_official_research_datasets,
    build_target_timing_precision_audit,
    official_final_evaluation_metrics,
    official_metrics_by_regime_horizon,
    official_model_stability,
    official_revision_eligible_observations,
    official_target_revision_effects,
    render_official_pilot_report,
    render_official_policy_brief,
    run_official_pilot_backtests,
    tune_official_advanced_models,
)
from macro_nowcast.schema import VintageObservation, observations_to_frame
from macro_nowcast.targets import PAYEMS_TARGET_SPEC, build_targets
from macro_nowcast.treasury_rates_archive import TREASURY_10Y_SERIES_ID


def _next_month(value: date) -> date:
    return date(value.year + (value.month == 12), value.month % 12 + 1, 1)


def _official_payroll_fixture() -> tuple[pl.DataFrame, pl.DataFrame]:
    periods = [date(2020, month, 1) for month in range(1, 11)]
    observations: list[VintageObservation] = []
    releases: list[dict[str, object]] = []
    for vintage_index, current_period in enumerate(periods):
        release_month = _next_month(current_period)
        release_date = release_month.replace(day=5)
        release_timestamp = datetime.combine(release_date, time.max, UTC)
        releases.append(
            {
                "release_id": f"bls-payems-{current_period:%Y-%m}-initial",
                "series_id": "PAYEMS",
                "observation_date": current_period,
                "release_timestamp": release_timestamp,
                "release_type": "initial",
                "timing_quality": DATE_ONLY_TIMING_QUALITY,
                "source": "BLS_EMPLOYMENT_SITUATION_ARCHIVE",
                "provenance_label": OFFICIAL_PROVENANCE,
            }
        )
        for observation_index, observation_period in enumerate(periods[: vintage_index + 1]):
            observations.append(
                VintageObservation(
                    series_id="PAYEMS",
                    observation_date=observation_period,
                    realtime_start=release_date,
                    availability_date=release_date,
                    value=100_000.0 + 10.0 * observation_index + 0.1 * vintage_index,
                    units="thousands_of_persons",
                    frequency="monthly",
                    seasonal_adjustment="seasonally_adjusted",
                    transformation="level",
                    download_timestamp=datetime(2026, 8, 9, tzinfo=UTC),
                    source="BLS_CES_VINTAGE_ARCHIVE",
                    provenance_label=OFFICIAL_PROVENANCE,
                )
            )
    return observations_to_frame(observations), pl.from_dicts(
        releases,
        schema=RELEASE_CALENDAR_SCHEMA,
        strict=True,
    )


def test_default_official_pilot_uses_audited_cross_agency_vintages() -> None:
    feature_series = {
        spec.series_id for definition in PILOT_TARGETS for spec in definition.feature_specs
    }

    assert {
        "CES2000000001",
        "CES3000000001",
        "CES4000000001",
        "CES5000000001",
        "CES5500000001",
        "CES6000000001",
        "CES6500000001",
        "CES7000000001",
    } <= feature_series
    assert [len(definition.feature_specs) for definition in PILOT_TARGETS] == [14, 15, 16]
    assert "DOL_UI_INITIAL_CLAIMS_4WMA_SA" in feature_series
    assert FED_G17_MOM_SERIES_ID in feature_series
    assert CENSUS_RETAIL_MOM_SERIES_ID in feature_series
    assert CENSUS_HOUSING_STARTS_SERIES_ID in feature_series
    assert TREASURY_10Y_SERIES_ID in feature_series


def test_raw_gdp_levels_are_excluded_from_cross_vintage_revision_analysis() -> None:
    observations, _ = _official_payroll_fixture()
    gdp = observations.head(1).with_columns(
        pl.lit("GDPC1").alias("series_id"),
        pl.lit("chained_2017_dollars").alias("units"),
        pl.lit("quarterly").alias("frequency"),
    )

    eligible = official_revision_eligible_observations(pl.concat([observations, gdp]))

    assert eligible["series_id"].unique().to_list() == ["PAYEMS"]
    assert eligible.height == observations.height


def test_target_timing_precision_audit_compares_origins_features_and_targets() -> None:
    target_period = date(2024, 1, 1)
    conservative_origin = datetime(2024, 2, 1, 4, 59, 59, 999999, tzinfo=UTC)
    evidence_origin = datetime(2024, 2, 2, 13, 29, 59, tzinfo=UTC)
    calendar = pl.from_dicts(
        [
            {
                "release_id": "bls-payems-2024-01-initial",
                "series_id": "PAYEMS",
                "observation_date": target_period,
                "release_timestamp": datetime(2024, 2, 2, 13, 30, tzinfo=UTC),
                "release_type": "initial",
                "timing_quality": "official_embargo_header_clock_America_New_York",
                "source": "BLS_EMPLOYMENT_SITUATION_ARCHIVE",
                "provenance_label": OFFICIAL_PROVENANCE,
            }
        ],
        schema=RELEASE_CALENDAR_SCHEMA,
        strict=True,
    )
    origin_base = {
        "target_series_id": "PAYEMS",
        "target_period": target_period,
    }
    feature_base = {
        **origin_base,
        "feature_name": "example",
        "information_set_mode": AS_OF_MODE,
        "is_missing": False,
        "latest_source_observation_date": date(2023, 12, 1),
        "max_source_availability": datetime(2024, 1, 5, 13, 30, tzinfo=UTC),
        "max_eligibility_availability": datetime(2024, 1, 5, 13, 30, tzinfo=UTC),
        "source_observation_count": 1,
        "non_null_source_observation_count": 1,
        "coverage_ratio": 1.0,
    }
    target_base = {
        **origin_base,
        "realization_mode": "first_release",
        "value": 10.0,
    }

    audit = build_target_timing_precision_audit(
        calendar,
        pl.from_dicts([{**origin_base, "forecast_origin": evidence_origin}]),
        pl.from_dicts([{**feature_base, "value": 2.0}]),
        pl.from_dicts([target_base]),
        pl.from_dicts([{**origin_base, "forecast_origin": conservative_origin}]),
        pl.from_dicts([{**feature_base, "value": 1.0}]),
        pl.from_dicts([target_base]),
    )

    row = audit.row(0, named=True)
    assert row["origin_shift_microseconds"] > 0
    assert row["feature_cells_compared"] == 1
    assert row["changed_feature_value_cells"] == 1
    assert row["changed_feature_selection_cells"] == 0
    assert row["changed_target_value_rows"] == 0


def test_official_pilot_accepts_exact_time_g17_without_future_rows() -> None:
    observations, calendar = _official_payroll_fixture()
    new_york = ZoneInfo("America/New_York")
    g17: list[VintageObservation] = []
    for index, observation_period in enumerate(
        [date(2019, 12, 1), *[date(2020, month, 1) for month in range(1, 10)]]
    ):
        release_month = _next_month(observation_period)
        release_date = release_month.replace(day=15)
        available_at = datetime.combine(release_date, time(9, 15), new_york).astimezone(UTC)
        g17.append(
            VintageObservation(
                series_id=FED_G17_MOM_SERIES_ID,
                observation_date=observation_period,
                realtime_start=release_date,
                availability_date=release_date,
                release_timestamp=available_at,
                availability_timestamp=available_at,
                value=0.1 + 0.01 * index,
                units="percent_change_mom",
                frequency="monthly",
                seasonal_adjustment="seasonally_adjusted",
                transformation="already_transformed",
                download_timestamp=datetime(2026, 8, 9, tzinfo=UTC),
                source="FED_G17_RELEASE_ARCHIVE",
                provenance_label=OFFICIAL_PROVENANCE,
            )
        )
    combined = pl.concat([observations, observations_to_frame(g17)])
    definition = OfficialPilotTarget(
        output_series_id="PAYEMS",
        calendar_series_id="PAYEMS",
        frequency="monthly",
        target_spec=PAYEMS_TARGET_SPEC,
        feature_specs=(
            FeatureSpec(
                "industrial_production_mom_lag1",
                FED_G17_MOM_SERIES_ID,
                "monthly",
                "level",
                "latest",
                lag_periods=1,
            ),
        ),
        min_train_size=3,
    )

    _, features = build_official_pilot_features(
        combined,
        calendar,
        targets=(definition,),
        modes=(AS_OF_MODE,),
    )

    assert features.height == 10
    assert features["is_missing"].sum() == 0
    assert features.filter(
        pl.col("max_source_availability") > pl.col("as_of_timestamp")
    ).is_empty()
    assert features.filter(
        pl.col("latest_source_observation_date") > pl.col("source_period_cutoff")
    ).is_empty()


def test_official_pilot_accepts_exact_time_census_retail_without_future_rows() -> None:
    observations, calendar = _official_payroll_fixture()
    new_york = ZoneInfo("America/New_York")
    retail: list[VintageObservation] = []
    for index, observation_period in enumerate(
        [date(2019, 12, 1), *[date(2020, month, 1) for month in range(1, 10)]]
    ):
        release_month = _next_month(observation_period)
        release_date = release_month.replace(day=16)
        available_at = datetime.combine(release_date, time(8, 30), new_york).astimezone(UTC)
        retail.append(
            VintageObservation(
                series_id=CENSUS_RETAIL_MOM_SERIES_ID,
                observation_date=observation_period,
                realtime_start=release_date,
                availability_date=release_date,
                release_timestamp=available_at,
                availability_timestamp=available_at,
                value=0.2 + 0.01 * index,
                units="percent_change_mom",
                frequency="monthly",
                seasonal_adjustment="seasonally_adjusted",
                transformation="already_transformed",
                download_timestamp=datetime(2026, 8, 9, tzinfo=UTC),
                source="CENSUS_MARTS_RELEASE_ARCHIVE",
                provenance_label=OFFICIAL_PROVENANCE,
            )
        )
    combined = pl.concat([observations, observations_to_frame(retail)])
    definition = OfficialPilotTarget(
        output_series_id="PAYEMS",
        calendar_series_id="PAYEMS",
        frequency="monthly",
        target_spec=PAYEMS_TARGET_SPEC,
        feature_specs=(
            FeatureSpec(
                "retail_sales_mom_lag1",
                CENSUS_RETAIL_MOM_SERIES_ID,
                "monthly",
                "level",
                "latest",
                lag_periods=1,
            ),
        ),
        min_train_size=3,
    )

    _, features = build_official_pilot_features(
        combined,
        calendar,
        targets=(definition,),
        modes=(AS_OF_MODE,),
    )

    assert features.height == 10
    assert features["is_missing"].sum() == 0
    assert features.filter(
        pl.col("max_source_availability") > pl.col("as_of_timestamp")
    ).is_empty()
    assert features.filter(
        pl.col("latest_source_observation_date") > pl.col("source_period_cutoff")
    ).is_empty()


def test_official_pilot_accepts_exact_time_census_housing_without_future_rows() -> None:
    observations, calendar = _official_payroll_fixture()
    new_york = ZoneInfo("America/New_York")
    housing: list[VintageObservation] = []
    for index, observation_period in enumerate(
        [
            date(2019, 11, 1),
            date(2019, 12, 1),
            *[date(2020, month, 1) for month in range(1, 10)],
        ]
    ):
        release_month = _next_month(observation_period)
        release_date = release_month.replace(day=18)
        available_at = datetime.combine(release_date, time(8, 30), new_york).astimezone(UTC)
        housing.append(
            VintageObservation(
                series_id=CENSUS_HOUSING_STARTS_SERIES_ID,
                observation_date=observation_period,
                realtime_start=release_date,
                availability_date=release_date,
                release_timestamp=available_at,
                availability_timestamp=available_at,
                value=1_300.0 + 10.0 * index,
                units="thousands_of_units_saar",
                frequency="monthly",
                seasonal_adjustment="seasonally_adjusted_annual_rate",
                transformation="published_rounded_level",
                download_timestamp=datetime(2026, 8, 9, tzinfo=UTC),
                source="CENSUS_NRC_RELEASE_ARCHIVE",
                provenance_label=OFFICIAL_PROVENANCE,
            )
        )
    combined = pl.concat([observations, observations_to_frame(housing)])
    definition = OfficialPilotTarget(
        output_series_id="PAYEMS",
        calendar_series_id="PAYEMS",
        frequency="monthly",
        target_spec=PAYEMS_TARGET_SPEC,
        feature_specs=(
            FeatureSpec(
                "housing_starts_log_change_lag1",
                CENSUS_HOUSING_STARTS_SERIES_ID,
                "monthly",
                "log_change",
                "latest",
                lag_periods=1,
            ),
        ),
        min_train_size=3,
    )

    _, features = build_official_pilot_features(
        combined,
        calendar,
        targets=(definition,),
        modes=(AS_OF_MODE,),
    )

    assert features.height == 10
    assert features["is_missing"].sum() == 0
    assert features.filter(
        pl.col("max_source_availability") > pl.col("as_of_timestamp")
    ).is_empty()
    assert features.filter(
        pl.col("latest_source_observation_date") > pl.col("source_period_cutoff")
    ).is_empty()


def test_official_pilot_accepts_exact_time_weekly_claims_without_future_rows() -> None:
    observations, calendar = _official_payroll_fixture()
    new_york = ZoneInfo("America/New_York")
    claims: list[VintageObservation] = []
    week = date(2019, 12, 28)
    for index in range(48):
        release_date = week + timedelta(days=5)
        available_at = datetime.combine(release_date, time(8, 30), new_york).astimezone(UTC)
        claims.append(
            VintageObservation(
                series_id="DOL_UI_INITIAL_CLAIMS_4WMA_SA",
                observation_date=week,
                realtime_start=release_date,
                availability_date=release_date,
                release_timestamp=available_at,
                availability_timestamp=available_at,
                value=220_000.0 + index,
                units="claims",
                frequency="weekly",
                seasonal_adjustment="seasonally_adjusted",
                transformation="level",
                download_timestamp=datetime(2026, 8, 9, tzinfo=UTC),
                source="DOL_UI_WEEKLY_CLAIMS_ARCHIVE",
                provenance_label=OFFICIAL_PROVENANCE,
            )
        )
        week += timedelta(days=7)
    combined = pl.concat([observations, observations_to_frame(claims)])
    definition = OfficialPilotTarget(
        output_series_id="PAYEMS",
        calendar_series_id="PAYEMS",
        frequency="monthly",
        target_spec=PAYEMS_TARGET_SPEC,
        feature_specs=(
            FeatureSpec(
                "initial_claims_4w_mean",
                "DOL_UI_INITIAL_CLAIMS_4WMA_SA",
                "weekly",
                "level",
                "latest",
            ),
        ),
        min_train_size=3,
    )

    _, features = build_official_pilot_features(
        combined,
        calendar,
        targets=(definition,),
        modes=(AS_OF_MODE,),
    )

    assert features.height == 10
    assert features["is_missing"].sum() == 0
    assert features.filter(
        pl.col("max_source_availability") > pl.col("as_of_timestamp")
    ).is_empty()
    assert features.filter(
        pl.col("latest_source_observation_date") > pl.col("source_period_cutoff")
    ).is_empty()


def test_official_pilot_uses_only_available_daily_treasury_rows() -> None:
    observations, calendar = _official_payroll_fixture()
    new_york = ZoneInfo("America/New_York")
    rates: list[VintageObservation] = []
    observation_date = date(2019, 12, 1)
    for index in range(380):
        available_at = datetime.combine(
            observation_date,
            time.max,
            new_york,
        ).astimezone(UTC)
        rates.append(
            VintageObservation(
                series_id=TREASURY_10Y_SERIES_ID,
                observation_date=observation_date,
                realtime_start=observation_date,
                availability_date=available_at.date(),
                release_timestamp=None,
                availability_timestamp=available_at,
                value=1.5 + index / 10_000,
                units="percent_per_annum_bond_equivalent_yield",
                frequency="daily",
                seasonal_adjustment="not_applicable",
                transformation="level",
                download_timestamp=datetime(2026, 8, 10, tzinfo=UTC),
                source="US_TREASURY_DAILY_PAR_YIELD_CURVE",
                provenance_label=OFFICIAL_PROVENANCE,
            )
        )
        observation_date += timedelta(days=1)
    combined = pl.concat([observations, observations_to_frame(rates)])
    definition = OfficialPilotTarget(
        output_series_id="PAYEMS",
        calendar_series_id="PAYEMS",
        frequency="monthly",
        target_spec=PAYEMS_TARGET_SPEC,
        feature_specs=(
            FeatureSpec(
                "treasury_10y_20d_mean",
                TREASURY_10Y_SERIES_ID,
                "daily",
                "level",
                "trailing_mean",
                window=20,
            ),
        ),
        min_train_size=3,
    )

    _, features = build_official_pilot_features(
        combined,
        calendar,
        targets=(definition,),
        modes=(AS_OF_MODE,),
    )

    assert features.height == 10
    assert features["is_missing"].sum() == 0
    assert features["source_observation_count"].unique().to_list() == [20]
    assert features.filter(
        pl.col("max_source_availability") > pl.col("as_of_timestamp")
    ).is_empty()


def test_official_pilot_builds_audited_modes_and_release_aware_backtests() -> None:
    observations, calendar = _official_payroll_fixture()
    definition = OfficialPilotTarget(
        output_series_id="PAYEMS",
        calendar_series_id="PAYEMS",
        frequency="monthly",
        target_spec=PAYEMS_TARGET_SPEC,
        feature_specs=(
            FeatureSpec(
                "payems_level_lag1",
                "PAYEMS",
                "monthly",
                "level",
                "latest",
                lag_periods=1,
            ),
        ),
        min_train_size=3,
        horizons=(0, 1),
        tuning_periods=2,
        final_evaluation_periods=2,
    )
    latest_as_of = calendar["release_timestamp"].max()
    targets = build_targets(
        observations,
        calendar,
        latest_as_of=latest_as_of,
        specs=(PAYEMS_TARGET_SPEC,),
        built_at=datetime(2026, 8, 9, tzinfo=UTC),
    )
    origins, features = build_official_pilot_features(
        observations,
        calendar,
        targets=(definition,),
        modes=(AS_OF_MODE, LATEST_SAME_MASK_MODE, NAIVE_LATEST_MODE),
    )
    datasets = build_official_research_datasets(
        features,
        targets,
        definitions=(definition,),
    )
    tuning, selected_parameters = tune_official_advanced_models(
        datasets,
        definitions=(definition,),
    )
    predictions, metrics, dm = run_official_pilot_backtests(
        datasets,
        definitions=(definition,),
        models={
            "historical_mean": HistoricalMeanRegressor(),
            "no_change": NoChangeRegressor(),
        },
    )

    assert origins.height == 10
    assert features.height == 30
    assert features.filter(
        (pl.col("information_set_mode") == AS_OF_MODE)
        & (pl.col("max_source_availability") > pl.col("as_of_timestamp"))
    ).is_empty()
    assert (
        features.filter(
            (pl.col("information_set_mode") == NAIVE_LATEST_MODE)
            & (pl.col("max_source_availability") > pl.col("as_of_timestamp"))
        ).height
        > 0
    )
    assert datasets["data_mode"].n_unique() == 3
    assert datasets.filter(
        (pl.col("horizon") == 0)
        & (pl.col("target_period") != pl.col("origin_target_period"))
    ).is_empty()
    assert datasets.filter(
        (pl.col("horizon") == 1)
        & (
            pl.col("target_period")
            != pl.col("origin_target_period").dt.offset_by("1mo")
        )
    ).is_empty()
    assert datasets.filter(
        pl.col("target_release_timestamp") <= pl.col("as_of_timestamp")
    ).is_empty()
    assert predictions["model_id"].n_unique() == 2
    assert set(predictions["horizon"]) == {0, 1}
    assert metrics.height == 12
    assert dm.height == 6
    assert dm.filter(pl.col("horizon") == 0)["hac_lag"].unique().to_list() == [0]
    assert dm.filter(pl.col("horizon") == 1)["hac_lag"].unique().to_list() == [1]
    assert dm["evaluation_block"].unique().to_list() == ["final_evaluation"]
    assert tuning.height == 20
    assert tuning.filter(pl.col("selected")).height == 4
    assert tuning["final_evaluation_rows_used_for_selection"].sum() == 0
    assert len(selected_parameters) == 4
    final_metrics = official_final_evaluation_metrics(predictions)
    assert final_metrics.height == 12
    assert final_metrics["n_forecasts"].unique().to_list() == [2]
    # This tiny OOS fixture starts after the April 2020 trough; recession
    # boundary behavior is covered directly in test_regimes.py.
    assert set(predictions["regime"]) == {"nber_expansion"}
    grouped = official_metrics_by_regime_horizon(predictions)
    assert grouped.height == 12
    assert set(grouped["regime"]) == {"nber_expansion"}
    assert grouped["regime_is_forecast_input"].unique().to_list() == [False]
    assert grouped["horizon"].unique().sort().to_list() == [0, 1]
    stability = official_model_stability(predictions, final_metrics)
    revision_details, revision_summary = official_target_revision_effects(
        targets,
        predictions,
    )
    assert stability.height == 8
    assert set(stability["comparison_mode"]) == {
        LATEST_SAME_MASK_MODE,
        NAIVE_LATEST_MODE,
    }
    assert (
        revision_details.height == predictions.filter(pl.col("data_mode") == "vintage_aware").height
    )
    assert revision_summary.height == 4
    updates = build_official_news_updates(
        observations,
        calendar,
        datasets,
        predictions,
        definitions=(definition,),
        advanced_model_parameters=selected_parameters,
    )
    assert len(updates) == 1
    update = updates[0]
    assert update["attribution_label"] == "exact"
    assert update["horizon"] == 1
    assert update["model_hyperparameters"] == selected_parameters[
        ("PAYEMS", 1, "elastic_net")
    ]
    assert update["release_timing_quality"] == DATE_ONLY_TIMING_QUALITY
    assert update["previous_as_of_timestamp"] < update["updated_as_of_timestamp"]
    contribution_total = sum(row["contribution"] for row in update["contributions"])
    assert abs(contribution_total - update["forecast_revision"]) < 1e-9
    brief = render_official_policy_brief(update)
    assert "SCOPED EMPIRICAL PILOT" in brief
    assert "not causal" in brief
    assert predictions["data_provenance"].unique().to_list() == [OFFICIAL_PROVENANCE]
    report = render_official_pilot_report(
        metrics,
        features.group_by(["target_series_id", "information_set_mode"]).agg(
            pl.len().alias("feature_cells"),
            (pl.col("max_source_availability") > pl.col("as_of_timestamp"))
            .sum()
            .alias("selected_vintage_after_origin_cells"),
            (pl.col("max_eligibility_availability") > pl.col("as_of_timestamp"))
            .sum()
            .alias("first_eligibility_after_origin_cells"),
            pl.col("is_missing").sum().alias("missing_feature_cells"),
        ),
        dm,
        metrics_by_regime_horizon=grouped,
        final_evaluation_metrics=final_metrics,
        hyperparameter_tuning=tuning,
    )
    assert "SCOPED EMPIRICAL EVIDENCE" in report
    assert "already transformed published q/q SAAR" in report
    assert "ex-post NBER regime" in report
    assert "Horizon `0` is the target-release nowcast" in report
    assert "untouched final evaluation" in report
