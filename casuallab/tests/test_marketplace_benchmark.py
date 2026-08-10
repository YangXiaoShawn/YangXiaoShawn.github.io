import numpy as np
import pandas as pd
import pytest

import casuallab.marketplace_benchmark as marketplace_module
from casuallab.benchmark import BenchmarkConfig
from casuallab.config import DesignConfig, DesignName, SimulationConfig, TreatmentVersion
from casuallab.estimators import estimate_effect as real_estimate_effect
from casuallab.marketplace_benchmark import (
    SensitivityScenario,
    _applicable_methods,
    _design_config,
    _design_identification_flag,
    _estimator_config,
    _identification_reason,
    _inference_assessment,
    _scenario_simulation_config,
    default_sensitivity_scenarios,
    run_marketplace_benchmark,
)


def test_default_scenarios_form_spillover_persistence_factorial() -> None:
    scenarios = default_sensitivity_scenarios(
        SimulationConfig(spillover_strength=0.2, persistence=0.3)
    )

    by_name = {scenario.name: scenario for scenario in scenarios}
    factorial_names = {
        "no_interference",
        "spillover_only",
        "persistence_only",
        "spillover_and_persistence",
    }
    assert factorial_names.issubset(by_name)
    assert {
        (
            by_name[name].spillover_strength > 0,
            by_name[name].persistence > 0,
        )
        for name in factorial_names
    } == {
        (False, False),
        (True, False),
        (False, True),
        (True, True),
    }
    assert {scenario.varied_dimension for scenario in scenarios}.issuperset(
        {
            "treatment_duration",
            "cluster_count",
            "treatment_saturation",
            "washout_periods",
            "budget",
            "treatment_version",
        }
    )
    assert by_name["treatment_duration_variant"].treatment_duration is not None
    assert by_name["cluster_count_variant"].n_clusters is not None
    assert by_name["partial_saturation"].treatment_saturation is not None
    assert by_name["washout_variant"].washout_periods is not None
    assert by_name["shared_budget_low"].budget is not None
    assert by_name["rider_discount_only"].treatment_version is TreatmentVersion.RIDER_DISCOUNT
    assert (
        by_name["driver_incentive_only"].treatment_version
        is TreatmentVersion.DRIVER_INCENTIVE
    )
    assert by_name["no_interference"].scenario_role == "reference"
    assert by_name["spillover_only"].scenario_role == "mechanism_sensitivity"
    assert by_name["partial_saturation"].scenario_role == "operational_sensitivity"
    assert by_name["shared_budget_low"].scenario_role == "target_mismatch_diagnostic"
    assert by_name["rider_discount_only"].scenario_role == "intervention_sensitivity"


def test_sensitivity_scenario_rejects_invalid_operating_overrides() -> None:
    with pytest.raises(ValueError, match="shorter than treatment_duration"):
        SensitivityScenario(
            "bad_washout",
            0.0,
            0.0,
            treatment_duration=2,
            washout_periods=2,
        )
    with pytest.raises(ValueError, match="treatment_saturation"):
        SensitivityScenario("bad_saturation", 0.0, 0.0, treatment_saturation=0.0)
    with pytest.raises(ValueError, match="budget"):
        SensitivityScenario("bad_budget", 0.0, 0.0, budget=-1.0)
    with pytest.raises(ValueError, match="unknown treatment version"):
        SensitivityScenario("bad_version", 0.0, 0.0, treatment_version="mystery")


def test_treatment_version_scenario_changes_the_intervention_without_changing_base() -> None:
    base = SimulationConfig(treatment_version="bundled")
    scenario = SensitivityScenario(
        "rider_only",
        0.0,
        0.0,
        treatment_version="rider_discount",
        varied_dimension="treatment_version",
    )
    configured = _scenario_simulation_config(base, scenario, n_zones=4, seed=99)

    assert base.treatment_version is TreatmentVersion.BUNDLED
    assert configured.treatment_version is TreatmentVersion.RIDER_DISCOUNT
    assert configured.seed == 99


def test_benchmark_fails_closed_for_unsupported_estimator_target() -> None:
    with pytest.raises(ValueError, match="supports only market_total_effect"):
        run_marketplace_benchmark(
            BenchmarkConfig(
                replications=2,
                designs=("geo_cluster",),
                estimators=("cluster_robust",),
                target_estimand="cumulative_effect",
            ),
            SimulationConfig(n_periods=8),
        )


def test_method_compatibility_uses_known_dr_propensity_and_excludes_temporal_did() -> None:
    requested = ("difference_in_differences", "doubly_robust")
    assert "difference_in_differences" not in _applicable_methods(DesignName.SWITCHBACK, requested)
    assert "difference_in_differences" not in _applicable_methods(DesignName.TIME_BLOCK, requested)
    assert "difference_in_differences" in _applicable_methods(DesignName.GEO_TIME, requested)
    assert "two_way_cluster_robust" in _applicable_methods(
        DesignName.GEO_TIME,
        ("two_way_cluster_robust",),
    )
    assert "two_way_cluster_robust" not in _applicable_methods(
        DesignName.GEO_CLUSTER,
        ("two_way_cluster_robust",),
    )
    config = _estimator_config(
        "doubly_robust",
        DesignName.GEO_CLUSTER,
        "market_total_effect",
        seed=9,
    )
    assert config.propensity == "treatment_probability"
    assert config.filter_eligible is False
    assert not _estimator_config(
        "cluster_robust",
        DesignName.SWITCHBACK,
        "persistent_effect",
        seed=9,
    ).filter_eligible
    two_way = _estimator_config(
        "two_way_cluster_robust",
        DesignName.GEO_TIME,
        "market_total_effect",
        seed=9,
    )
    assert two_way.cluster == "cluster_id"
    assert two_way.time == "time_block"


def test_two_way_geo_time_inference_requires_enough_groups_in_both_dimensions() -> None:
    valid, scope = _inference_assessment(
        "two_way_cluster_robust",
        DesignName.GEO_TIME,
        96,
        n_geographic_clusters=8,
        n_time_clusters=12,
    )
    assert valid
    assert "two-way" in scope
    invalid, warning = _inference_assessment(
        "two_way_cluster_robust",
        DesignName.GEO_TIME,
        48,
        n_geographic_clusters=4,
        n_time_clusters=12,
    )
    assert not invalid
    assert "below" in warning
    assert not _inference_assessment("doubly_robust", DesignName.GEO_TIME, 20)[0]
    assert not _inference_assessment("cluster_robust", DesignName.GEO_TIME, 20)[0]
    assert not _inference_assessment("cluster_robust", DesignName.GEO_CLUSTER, 4)[0]
    assert _inference_assessment("cluster_robust", DesignName.GEO_CLUSTER, 8)[0]


def test_two_way_uncertainty_does_not_promote_unmodeled_exposure_to_market_total() -> None:
    scenario = SensitivityScenario(
        "spatial_and_temporal_exposure",
        spillover_strength=0.3,
        persistence=0.4,
    )
    inference_valid, _ = _inference_assessment(
        "two_way_cluster_robust",
        DesignName.GEO_TIME,
        64,
        n_geographic_clusters=8,
        n_time_clusters=8,
    )

    assert inference_valid
    assert not _design_identification_flag(
        DesignName.GEO_TIME,
        "market_total_effect",
        scenario,
    )
    assert "unmodeled spatial or temporal exposure" in _identification_reason(
        DesignName.GEO_TIME,
        "market_total_effect",
        scenario,
    )


def test_benchmark_design_protocol_honors_configured_duration_and_washout() -> None:
    simulation = SimulationConfig(design=DesignConfig(treatment_duration=3, washout_periods=2))

    temporal = _design_config(DesignName.SWITCHBACK, simulation, seed=8)
    geographic = _design_config(DesignName.GEO_CLUSTER, simulation, seed=8)

    assert temporal.treatment_duration == 3
    assert temporal.washout_periods == 2
    assert geographic.treatment_duration == 3
    assert geographic.washout_periods == 0


def test_end_to_end_benchmark_is_deterministic_and_labels_target_mismatch() -> None:
    benchmark = BenchmarkConfig(
        replications=2,
        seed=33,
        designs=("individual", "geo_cluster", "switchback"),
        estimators=("difference_in_means", "regression_adjustment", "cluster_robust"),
        target_estimand="market_total_effect",
    )
    simulation = SimulationConfig(
        n_zones=4,
        n_periods=24,
        seed=8,
        budget=None,
        design=DesignConfig(treatment_duration=4),
    )
    scenarios = (SensitivityScenario("none", 0.0, 0.0),)
    first = run_marketplace_benchmark(benchmark, simulation, scenarios=scenarios)
    second = run_marketplace_benchmark(benchmark, simulation, scenarios=scenarios)
    pd.testing.assert_frame_equal(first.records, second.records)
    pd.testing.assert_frame_equal(first.summary, second.summary)
    pd.testing.assert_frame_equal(first.fit_ledger, second.fit_ledger)
    assert len(first.summary) > 0
    assert not first.summary.loc[first.summary["design"] == "individual", "identified"].any()
    assert first.summary.loc[first.summary["design"] == "geo_cluster", "identified"].all()
    assert set(first.summary["evidence_type"]) == {"semi_synthetic_causal_monte_carlo"}
    assert (first.records.groupby(["scenario", "replication"])["seed"].nunique() == 1).all()
    assert (first.fit_ledger["attempted_fits"] == 2).all()
    assert (
        first.fit_ledger["successful_fits"] + first.fit_ledger["failed_fits"]
        == first.fit_ledger["attempted_fits"]
    ).all()
    assert first.fit_ledger["fit_complete"].all()
    assert "normalized_precision_cost" in first.summary
    assert "information_cost" not in first.summary
    assert first.summary["budget"].isna().all()
    assert "n_clusters" not in first.summary
    assert not first.summary["operational_cost_included"].any()
    assert first.summary["measurement_cost_basis"].str.contains("excludes").all()
    threshold = float(first.summary["nonbinding_budget_threshold"].iloc[0])
    assert np.isfinite(threshold)
    assert first.summary["nonbinding_budget_threshold"].eq(threshold).all()
    assert first.records["nonbinding_budget_threshold"].eq(threshold).all()
    assert threshold >= first.records["full_policy_spend"].max()
    assert threshold >= first.records["realized_schedule_spend"].max()
    assert first.summary["incentive_per_driver"].eq(simulation.incentive_per_driver).all()
    assert first.summary["treatment_version"].eq("bundled").all()
    assert first.summary["declared_scenario_set"].eq('["none"]').all()
    assert first.records["declared_scenario_set"].eq('["none"]').all()


def test_geo_time_two_way_cluster_runs_end_to_end_with_valid_dimensions() -> None:
    result = run_marketplace_benchmark(
        BenchmarkConfig(
            replications=2,
            seed=39,
            designs=("geo_time",),
            estimators=("two_way_cluster_robust",),
            target_estimand="market_total_effect",
        ),
        SimulationConfig(
            n_periods=32,
            budget=None,
            design=DesignConfig(
                n_clusters=8,
                treatment_duration=4,
                washout_periods=0,
            ),
        ),
        scenarios=(SensitivityScenario("none", 0.0, 0.0),),
    )

    assert result.failures.empty
    assert len(result.records) == 2
    row = result.summary.iloc[0]
    assert row["estimator"] == "two_way_cluster_robust"
    assert row["inference_geographic_clusters"] == 8
    assert row["inference_time_clusters"] == 8
    assert row["inference_valid"]
    assert row["fit_complete"]
    assert np.isfinite(row["mean_estimate"])
    assert np.isfinite(row["mean_std_error"])


def test_benchmark_honors_and_records_assignment_probability_and_geo_clusters() -> None:
    result = run_marketplace_benchmark(
        BenchmarkConfig(
            replications=2,
            seed=7,
            designs=("geo_cluster",),
            estimators=("cluster_robust",),
        ),
        SimulationConfig(
            n_periods=24,
            design=DesignConfig(
                treatment_probability=0.35,
                n_clusters=3,
                treatment_duration=4,
            ),
        ),
        scenarios=(SensitivityScenario("none", 0.0, 0.0),),
    )

    assert np.isclose(result.summary.iloc[0]["treatment_probability"], 0.35)
    assert np.isclose(result.summary.iloc[0]["mean_assignment_propensity"], 1.0 / 3.0)
    assert result.summary.iloc[0]["configured_geo_clusters"] == 3
    assert result.summary.iloc[0]["n_zones"] == 6
    assert result.summary.iloc[0]["cluster_size"] == 2
    assert result.summary.iloc[0]["cluster_semantics"] == "geographic assignment clusters"
    assert not result.summary.iloc[0]["inference_valid"]
    assert result.summary.iloc[0]["minimum_inference_clusters"] == 8


def test_operating_sensitivity_overrides_are_recorded_and_budget_is_target_mismatch() -> None:
    scenario = SensitivityScenario(
        "joint_operating_check",
        0.0,
        0.0,
        treatment_duration=6,
        n_clusters=8,
        treatment_saturation=0.4,
        washout_periods=2,
        budget=100.0,
        varied_dimension="test_joint_override",
    )
    result = run_marketplace_benchmark(
        BenchmarkConfig(
            replications=2,
            seed=17,
            designs=("geo_cluster", "switchback"),
            estimators=("difference_in_means",),
        ),
        SimulationConfig(n_periods=24, budget=5000.0),
        scenarios=(scenario,),
    )

    summary = result.summary.set_index("design")
    assert summary["varied_dimension"].eq("test_joint_override").all()
    assert summary["scenario_role"].eq("target_mismatch_diagnostic").all()
    assert summary["treatment_duration"].eq(6).all()
    assert summary["treatment_saturation"].eq(0.4).all()
    assert summary["budget"].eq(100.0).all()
    assert summary["n_zones"].eq(16).all()
    assert summary.loc["geo_cluster", "configured_geo_clusters"] == 8
    assert np.isnan(summary.loc["switchback", "configured_geo_clusters"])
    assert summary.loc["geo_cluster", "washout_periods"] == 0
    assert summary.loc["switchback", "washout_periods"] == 2
    assert not bool(summary.loc["geo_cluster", "inference_valid"])
    assert not summary["identified"].any()
    assert summary["identification_scope"].str.contains("shared-budget").all()
    assert summary["comparison_status"].eq("target_mismatch").all()
    assert summary["budget_binding_rate"].eq(1.0).all()
    assert result.records["budget_binding"].all()
    assert result.fit_ledger["declared_scenario_count"].eq(1).all()


def test_cluster_count_cell_supplies_eight_cluster_geometry_and_valid_inference() -> None:
    simulation = SimulationConfig(
        n_periods=24,
        design=DesignConfig(n_clusters=2, treatment_duration=4),
    )
    cluster_scenario = next(
        scenario
        for scenario in default_sensitivity_scenarios(simulation)
        if scenario.varied_dimension == "cluster_count"
    )
    result = run_marketplace_benchmark(
        BenchmarkConfig(
            replications=2,
            seed=91,
            designs=("geo_cluster",),
            estimators=("cluster_robust",),
        ),
        simulation,
        scenarios=(cluster_scenario,),
    )

    row = result.summary.iloc[0]
    assert row["configured_geo_clusters"] == 8
    assert row["n_zones"] == 16
    assert row["cluster_size"] == 2
    assert row["inference_clusters"] == 8
    assert row["inference_valid"]


def test_capped_runs_cannot_self_certify_a_nonbinding_budget_threshold() -> None:
    result = run_marketplace_benchmark(
        BenchmarkConfig(
            replications=2,
            seed=92,
            designs=("geo_cluster",),
            estimators=("difference_in_means",),
        ),
        SimulationConfig(n_periods=12),
        scenarios=(SensitivityScenario("only_capped", 0.0, 0.0, budget=1.0),),
    )

    assert result.summary["nonbinding_budget_threshold"].isna().all()
    assert result.records["nonbinding_budget_threshold"].isna().all()


def test_impossible_group_crossfit_is_predeclared_not_counted_as_fit_failure() -> None:
    result = run_marketplace_benchmark(
        BenchmarkConfig(
            replications=2,
            seed=93,
            designs=("geo_cluster",),
            estimators=("doubly_robust",),
        ),
        SimulationConfig(n_periods=12, design=DesignConfig(n_clusters=2)),
        scenarios=(SensitivityScenario("two_clusters", 0.0, 0.0),),
    )

    row = result.fit_ledger.iloc[0]
    assert not row["applicable"]
    assert row["attempted_fits"] == 0
    assert row["successful_fits"] == 0
    assert row["failed_fits"] == 0
    assert row["fit_complete"]
    assert "two" in row["applicability_reason"]
    assert result.records.empty
    assert result.failures.empty

    imbalanced = run_marketplace_benchmark(
        BenchmarkConfig(
            replications=2,
            seed=94,
            designs=("geo_cluster",),
            estimators=("doubly_robust",),
        ),
        SimulationConfig(
            n_periods=12,
            design=DesignConfig(n_clusters=8, treatment_probability=0.1),
        ),
        scenarios=(SensitivityScenario("imbalanced_arms", 0.0, 0.0),),
    )
    imbalanced_row = imbalanced.fit_ledger.iloc[0]
    assert not imbalanced_row["applicable"]
    assert imbalanced_row["attempted_fits"] == 0
    assert "each arm" in imbalanced_row["applicability_reason"]


def test_benchmark_rejects_duplicate_or_empty_declared_scenario_plans() -> None:
    benchmark = BenchmarkConfig(
        replications=2,
        designs=("geo_cluster",),
        estimators=("difference_in_means",),
    )
    simulation = SimulationConfig(n_periods=8)
    duplicate = SensitivityScenario("duplicate", 0.0, 0.0)

    with pytest.raises(ValueError, match="at least one sensitivity scenario"):
        run_marketplace_benchmark(benchmark, simulation, scenarios=())
    with pytest.raises(ValueError, match="names must be unique"):
        run_marketplace_benchmark(
            benchmark,
            simulation,
            scenarios=(duplicate, duplicate),
        )


def test_spillover_scenario_is_generated_not_hard_coded() -> None:
    benchmark = BenchmarkConfig(
        replications=2,
        seed=19,
        designs=("geo_cluster",),
        estimators=("difference_in_means", "regression_adjustment"),
    )
    simulation = SimulationConfig(n_periods=24, budget=None)
    result = run_marketplace_benchmark(
        benchmark,
        simulation,
        scenarios=(
            SensitivityScenario("none", 0.0, 0.0),
            SensitivityScenario("spillover", 0.45, 0.0),
        ),
    )
    assert set(result.records["scenario"]) == {"none", "spillover"}
    assert result.records.groupby("replication")["seed"].nunique().eq(1).all()
    scenario_truth = result.records.groupby("scenario")["truth"].mean()
    assert scenario_truth["spillover"] != scenario_truth["none"]
    assert not result.records.loc[result.records["scenario"] == "spillover", "identified"].any()


def test_no_interference_cluster_estimator_recovers_truth_with_mc_uncertainty() -> None:
    benchmark = BenchmarkConfig(
        replications=40,
        seed=123,
        designs=("geo_cluster",),
        estimators=("cluster_robust",),
    )
    result = run_marketplace_benchmark(
        benchmark,
        SimulationConfig(
            n_periods=24,
            budget=None,
            design=DesignConfig(n_clusters=8),
        ),
        scenarios=(SensitivityScenario("none", 0.0, 0.0),),
    )
    row = result.summary.iloc[0]
    assert abs(row["bias"]) <= 3.0 * row["bias_mcse"]
    assert row["coverage"] >= 0.80


def test_naive_cluster_estimator_misses_full_policy_target_under_spillover() -> None:
    benchmark = BenchmarkConfig(
        replications=30,
        seed=321,
        designs=("geo_cluster",),
        estimators=("cluster_robust",),
    )
    result = run_marketplace_benchmark(
        benchmark,
        SimulationConfig(n_periods=24, budget=None),
        scenarios=(SensitivityScenario("spillover", 0.45, 0.0),),
    )
    row = result.summary.iloc[0]
    assert not row["identified"]
    assert np.isnan(row["bias"])
    assert abs(row["diagnostic_mean_gap"]) > 5.0 * row["diagnostic_gap_mcse"]
    assert row["comparison_status"] == "target_mismatch"


def test_fit_failures_remain_in_ledger_and_make_candidate_incomplete(monkeypatch) -> None:
    calls = 0

    def fail_once(panel, config):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ValueError("deliberate fit failure")
        return real_estimate_effect(panel, config)

    monkeypatch.setattr(marketplace_module, "estimate_effect", fail_once)
    result = run_marketplace_benchmark(
        BenchmarkConfig(
            replications=3,
            seed=17,
            designs=("geo_cluster",),
            estimators=("cluster_robust",),
        ),
        SimulationConfig(n_periods=24, budget=None),
        scenarios=(SensitivityScenario("none", 0.0, 0.0),),
    )

    ledger = result.fit_ledger.iloc[0]
    assert ledger["attempted_fits"] == 3
    assert ledger["successful_fits"] == 2
    assert ledger["failed_fits"] == 1
    assert not ledger["fit_complete"]
    assert not result.summary.iloc[0]["fit_complete"]
    assert result.failures.iloc[0]["stage"] == "estimation"


def test_unavailable_individual_truth_target_fails_before_fitting() -> None:
    with pytest.raises(ValueError, match="supports only market_total_effect"):
        run_marketplace_benchmark(
            BenchmarkConfig(
                replications=2,
                seed=27,
                designs=("individual",),
                estimators=("regression_adjustment",),
                target_estimand="direct_effect",
            ),
            SimulationConfig(n_periods=12, budget=None),
            scenarios=(SensitivityScenario("none", 0.0, 0.0),),
        )
