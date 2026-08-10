import numpy as np
import pandas as pd

from casuallab.heterogeneity import cross_fitted_s_learner, subgroup_effect_summary


def test_cross_fitted_s_learner_is_deterministic_and_complete() -> None:
    rng = np.random.default_rng(17)
    n = 240
    baseline = rng.normal(size=n)
    treatment = rng.binomial(1, 0.5, size=n)
    data = pd.DataFrame(
        {
            "unit_id": np.arange(n),
            "baseline_demand": baseline,
            "market_tightness": rng.uniform(size=n),
            "hour_sin": rng.uniform(-1, 1, size=n),
            "hour_cos": rng.uniform(-1, 1, size=n),
            "assigned_treatment": treatment,
            "outcome": 2.0 * baseline + treatment * (1.0 + baseline) + rng.normal(0, 0.2, n),
        }
    )
    first = cross_fitted_s_learner(data, folds=3, trees=20, min_samples_leaf=5, seed=4)
    second = cross_fitted_s_learner(data, folds=3, trees=20, min_samples_leaf=5, seed=4)
    pd.testing.assert_frame_equal(first.predictions, second.predictions)
    assert first.predictions["estimated_cate"].notna().all()
    assert set(first.predictions["crossfit_fold"]) == {0, 1, 2}


def test_subgroup_summary_uses_pretreatment_modifier_bins() -> None:
    data = pd.DataFrame({"baseline_demand": np.arange(20, dtype=float)})
    summary = subgroup_effect_summary(
        data,
        0.1 * data["baseline_demand"].to_numpy(),
        modifier="baseline_demand",
        bins=4,
    )
    assert summary["rows"].sum() == 20
    assert summary["mean_estimated_cate"].is_monotonic_increasing

