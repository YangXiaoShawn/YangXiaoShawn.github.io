from __future__ import annotations

import numpy as np
import pytest

from macro_nowcast.models import (
    AR1Regressor,
    DeterministicHistGradientBoostingRegressor,
    FixedElasticNetRegressor,
    HistoricalMeanRegressor,
    LinearBridgeRegressor,
    NoChangeRegressor,
)


def test_transparent_baselines_are_deterministic() -> None:
    X = np.arange(5, dtype=float).reshape(-1, 1)
    y = np.array([1.0, 2.0, 3.0, 4.0, 5.0])

    mean_model = HistoricalMeanRegressor().fit(X, y)
    np.testing.assert_allclose(mean_model.predict([[8.0], [9.0]]), [3.0, 3.0])

    no_change = NoChangeRegressor().fit(X, y)
    np.testing.assert_allclose(no_change.predict([[8.0], [9.0]]), [5.0, 5.0])

    lag_no_change = NoChangeRegressor(lag_column=0).fit(X, y)
    np.testing.assert_allclose(lag_no_change.predict([[7.0], [8.0]]), [7.0, 8.0])


def test_ar1_recurses_from_last_training_target() -> None:
    y = [0.0]
    for _ in range(7):
        y.append(1.0 + 0.5 * y[-1])
    X = np.zeros((len(y), 1))
    model = AR1Regressor().fit(X, y)

    assert model.intercept_ == pytest.approx(1.0)
    assert model.phi_ == pytest.approx(0.5)
    expected_first = 1.0 + 0.5 * y[-1]
    expected_second = 1.0 + 0.5 * expected_first
    np.testing.assert_allclose(model.predict(np.zeros((2, 1))), [expected_first, expected_second])


def test_linear_bridge_handles_ragged_features() -> None:
    X = np.column_stack([np.arange(12, dtype=float), np.linspace(-1, 1, 12)])
    X[3, 1] = np.nan
    y = 4.0 + 2.0 * X[:, 0]
    model = LinearBridgeRegressor().fit(X, y)

    prediction = model.predict([[12.0, 1.2]])
    assert prediction.shape == (1,)
    assert np.isfinite(prediction[0])


def test_elastic_net_preprocessing_is_fitted_only_on_training_rows() -> None:
    X_train = np.array([[0.0], [1.0], [2.0], [3.0], [4.0]])
    y_train = np.array([0.0, 1.0, 2.0, 3.0, 4.0])
    model = FixedElasticNetRegressor(alpha=0.01, min_train_samples=3).fit(X_train, y_train)

    scaler = model.pipeline_.named_steps["scaler"]
    assert scaler.mean_[0] == pytest.approx(2.0)
    assert scaler.mean_[0] != pytest.approx(np.mean(np.append(X_train[:, 0], 10_000.0)))
    assert np.isfinite(model.predict([[10_000.0]])[0])


def test_hist_gradient_boosting_enforces_minimum_and_is_reproducible() -> None:
    rng = np.random.default_rng(7)
    X = rng.normal(size=(40, 3))
    y = X[:, 0] ** 2 - X[:, 1] + rng.normal(scale=0.01, size=40)
    parameters = {
        "min_train_samples": 20,
        "min_samples_leaf": 3,
        "max_iter": 30,
        "random_state": 9,
    }
    first = DeterministicHistGradientBoostingRegressor(**parameters).fit(X, y)
    second = DeterministicHistGradientBoostingRegressor(**parameters).fit(X, y)
    np.testing.assert_allclose(first.predict(X[:5]), second.predict(X[:5]))

    ragged = np.column_stack([X[:, 0], np.full(X.shape[0], np.nan)])
    ragged_model = DeterministicHistGradientBoostingRegressor(**parameters).fit(
        ragged,
        y,
    )
    assert np.isfinite(ragged_model.predict([[0.5, np.nan]])[0])

    with pytest.raises(ValueError, match="at least 20"):
        DeterministicHistGradientBoostingRegressor(**parameters).fit(X[:10], y[:10])
