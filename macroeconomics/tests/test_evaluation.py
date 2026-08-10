from __future__ import annotations

import math

import numpy as np
import pytest

from macro_nowcast.evaluation import (
    diebold_mariano,
    iter_expanding_folds,
    regression_metrics,
    residual_prediction_interval,
    run_expanding_backtest,
)
from macro_nowcast.models import HistoricalMeanRegressor


def _daily_dates(n: int) -> np.ndarray:
    return np.datetime64("2020-01-01") + np.arange(n)


def test_expanding_folds_exclude_targets_not_released_by_origin() -> None:
    origins = _daily_dates(7)
    releases = np.array(
        ["2020-01-02", "2020-01-03", "2020-01-10", "2020-01-05", "2020-01-06",
         "2020-01-07", "2020-01-08"],
        dtype="datetime64[D]",
    )
    folds = list(
        iter_expanding_folds(
            len(origins),
            origins=origins,
            target_release_dates=releases,
            min_train_size=2,
        )
    )

    fold_at_jan_5 = next(fold for fold in folds if fold.origin == np.datetime64("2020-01-05"))
    assert 2 not in fold_at_jan_5.train_indices
    assert 2 in fold_at_jan_5.excluded_unreleased_indices
    assert np.all(releases[fold_at_jan_5.train_indices] <= fold_at_jan_5.origin)


def test_backtest_refits_historical_mean_and_emits_group_hooks() -> None:
    n = 10
    origins = _daily_dates(n)
    releases = origins + np.timedelta64(1, "D")
    X = np.arange(n, dtype=float).reshape(-1, 1)
    y = np.arange(1, n + 1, dtype=float)
    horizons = np.array(["nowcast" if i % 2 == 0 else "one_month" for i in range(n)])
    regimes = np.array(["calm"] * 7 + ["stress"] * 3)

    result = run_expanding_backtest(
        HistoricalMeanRegressor(),
        X,
        y,
        origins=origins,
        target_release_dates=releases,
        min_train_size=3,
        horizon=horizons,
        regimes=regimes,
        interval_min_residuals=2,
    )

    assert result.records[0].row_index == 3
    assert result.records[0].forecast == pytest.approx(2.0)
    assert result.records[0].train_size == 3
    assert set(result.grouped_metrics("horizon")) == {"nowcast", "one_month"}
    assert set(result.grouped_metrics("regime")) == {"calm", "stress"}
    assert result.metrics()["n_obs"] == len(result.records)


def test_metrics_and_residual_intervals_have_explicit_conventions() -> None:
    metrics = regression_metrics(
        [1.0, -2.0, 3.0],
        [2.0, -1.0, 2.0],
        lower=[0.0, -3.0, 1.0],
        upper=[3.0, 0.0, 4.0],
    )
    assert metrics["rmse"] == pytest.approx(1.0)
    assert metrics["mae"] == pytest.approx(1.0)
    assert metrics["bias"] == pytest.approx(1.0 / 3.0)
    assert metrics["directional_accuracy"] == pytest.approx(1.0)
    assert metrics["interval_coverage"] == pytest.approx(1.0)

    lower, upper = residual_prediction_interval([10.0], [-2.0, -1.0, 1.0, 2.0], min_residuals=4)
    assert lower[0] < 10.0 < upper[0]
    missing_lower, missing_upper = residual_prediction_interval([10.0], [1.0], min_residuals=2)
    assert math.isnan(missing_lower[0]) and math.isnan(missing_upper[0])


def test_guarded_dm_style_comparison() -> None:
    actual = np.linspace(-2.0, 2.0, 40)
    pattern = np.sin(np.arange(40, dtype=float))
    forecast_a = actual + 1.0 + 0.5 * pattern
    forecast_b = actual + 0.1 * pattern

    comparison = diebold_mariano(actual, forecast_a, forecast_b, min_observations=20)
    assert comparison.valid
    assert comparison.statistic > 0
    assert comparison.p_value < 0.05

    degenerate = diebold_mariano(actual, actual + 1.0, actual - 1.0)
    assert not degenerate.valid
    assert degenerate.reason == "degenerate_loss_differential_variance"
