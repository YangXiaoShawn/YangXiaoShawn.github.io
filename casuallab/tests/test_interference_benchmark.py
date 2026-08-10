import numpy as np
import pandas as pd
import pytest

from casuallab.interference_benchmark import (
    InterferenceBenchmarkConfig,
    known_interference_estimands,
    run_interference_benchmark,
)


@pytest.fixture(scope="module")
def benchmark_result():
    return run_interference_benchmark()


def test_known_estimands_keep_controlled_slopes_separate_from_market_total() -> None:
    config = InterferenceBenchmarkConfig()
    truth = known_interference_estimands(config)

    assert truth.controlled_zone_direct_effect == 2.0
    assert truth.spillover_effect == 1.5
    assert truth.controlled_history_exposure_response == 0.7
    assert truth.full_horizon_persistent_effect == pytest.approx(0.7 * 31 / 32)
    assert truth.market_total_effect == pytest.approx(2.0 + 1.5 + 0.7 * 31 / 32)
    assert truth.market_total_effect != truth.controlled_zone_direct_effect


def test_benchmark_is_deterministic_and_uses_two_stage_saturation() -> None:
    config = InterferenceBenchmarkConfig(
        replications=4,
        n_zones=8,
        n_clusters=8,
        n_periods=12,
        seed=901,
    )
    first = run_interference_benchmark(config)
    second = run_interference_benchmark(config)

    pd.testing.assert_frame_equal(first.records, second.records)
    pd.testing.assert_frame_equal(first.summary, second.summary)
    pd.testing.assert_frame_equal(first.fit_ledger, second.fit_ledger)
    pd.testing.assert_frame_equal(first.failures, second.failures)
    assert first.metadata == second.metadata
    assert set(first.records["design"]) == {"two_stage_saturation"}
    assert first.records["assignment_seed"].nunique() == config.replications
    assert first.records["outcome_seed"].nunique() == config.replications
    assert first.failures.empty


def test_mapped_benchmark_recovers_own_neighbor_and_history_truths(
    benchmark_result,
) -> None:
    mapped = benchmark_result.summary.loc[benchmark_result.summary["identified"]].set_index(
        "target_estimand"
    )

    assert mapped.loc["controlled_zone_direct_effect", "mean_estimate"] == pytest.approx(
        2.0, abs=0.08
    )
    assert mapped.loc["spillover_effect", "mean_estimate"] == pytest.approx(1.5, abs=0.08)
    assert mapped.loc[
        "controlled_history_exposure_response", "mean_estimate"
    ] == pytest.approx(0.7, abs=0.08)
    assert mapped["bias"].abs().lt(0.08).all()
    assert mapped["inference_valid_for_target"].all()
    assert mapped["controlled_exposure_not_market_total"].all()
    assert set(mapped["evidence_type"]) == {
        "semi_synthetic_exposure_mapped_known_truth_monte_carlo"
    }

    mapped_records = benchmark_result.records.loc[
        benchmark_result.records["estimator"].eq("exposure_mapped_cluster_regression")
    ]
    assert mapped_records["coefficient_inference_cluster_aware"].all()
    assert mapped_records["inference_valid_for_target"].all()
    assert mapped_records["n_clusters"].eq(32).all()
    assert mapped_records["variance_estimator"].eq("CR1 cluster-t").all()
    assert set(mapped_records["target_estimand"]) == {
        "controlled_zone_direct_effect",
        "spillover_effect",
        "controlled_history_exposure_response",
    }


def test_naive_assignment_coefficient_is_an_honest_market_total_mismatch(
    benchmark_result,
) -> None:
    naive = benchmark_result.summary.loc[
        benchmark_result.summary["estimator"].eq("naive_assignment_cluster_regression")
    ].iloc[0]

    assert naive["target_estimand"] == "market_total_effect"
    assert not bool(naive["identified"])
    assert naive["comparison_status"] == "target_mismatch"
    assert naive["diagnostic_mean_gap_to_market_total"] < -1.0
    assert np.isnan(naive["bias"])
    assert np.isnan(naive["rmse"])
    assert np.isnan(naive["coverage"])
    assert np.isnan(naive["power"])
    assert "withheld" in naive["withheld_reason"]

    naive_records = benchmark_result.records.loc[
        benchmark_result.records["estimator"].eq("naive_assignment_cluster_regression")
    ]
    assert naive_records["coefficient_inference_cluster_aware"].all()
    assert naive_records["estimation_error"].isna().all()
    assert naive_records["diagnostic_gap_to_market_total"].notna().all()
    assert set(naive_records["evidence_type"]) == {
        "semi_synthetic_assignment_diagnostic_target_mismatch"
    }


def test_fit_ledger_is_complete_and_never_promotes_naive_target_mismatch(
    benchmark_result,
) -> None:
    ledger = benchmark_result.fit_ledger
    assert len(ledger) == 4
    assert ledger["fit_complete"].all()
    assert ledger["successful_fits"].eq(24).all()
    assert ledger["failed_fits"].eq(0).all()
    assert set(ledger["evidence_type"]) == {"semi_synthetic_benchmark_fit_ledger"}

    naive = ledger.loc[ledger["estimator"].eq("naive_assignment_cluster_regression")].iloc[0]
    assert not bool(naive["identified"])
    assert not bool(naive["decision_eligible"])
    assert naive["target_inference_valid_rate"] == 0.0
    assert ledger.loc[ledger["identified"], "decision_eligible"].all()


def test_too_few_clusters_withholds_inferential_recovery_metrics() -> None:
    result = run_interference_benchmark(
        InterferenceBenchmarkConfig(
            replications=4,
            n_zones=6,
            n_clusters=6,
            n_periods=16,
            minimum_inference_clusters=8,
            seed=188,
        )
    )
    mapped = result.summary.loc[result.summary["identified"]]

    assert not mapped["inference_valid_for_target"].any()
    assert mapped["bias"].notna().all()
    assert mapped["coverage"].isna().all()
    assert mapped["power"].isna().all()
    assert mapped["withheld_reason"].str.contains("below").all()
    assert not result.fit_ledger["decision_eligible"].any()


def test_config_rejects_ambiguous_cluster_and_history_geometry() -> None:
    with pytest.raises(ValueError, match="one randomized cluster per zone"):
        InterferenceBenchmarkConfig(n_zones=8, n_clusters=4)
    with pytest.raises(ValueError, match="history_lags"):
        InterferenceBenchmarkConfig(history_lags=0)
    with pytest.raises(ValueError, match="interior arm"):
        InterferenceBenchmarkConfig(saturation_levels=(0.0, 1.0))
