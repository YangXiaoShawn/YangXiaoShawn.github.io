from __future__ import annotations

import numpy as np
import pytest
from sklearn.linear_model import LinearRegression

from macro_nowcast.attribution import (
    approximate_tree_news_attribution,
    linear_news_attribution,
)
from macro_nowcast.models import (
    DeterministicHistGradientBoostingRegressor,
    FixedElasticNetRegressor,
)


def test_linear_news_attribution_is_exact_for_fixed_linear_model() -> None:
    X = np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0], [1.0, 1.0]])
    y = 2.0 + 3.0 * X[:, 0] - 4.0 * X[:, 1]
    model = LinearRegression().fit(X, y)

    result = linear_news_attribution(
        model,
        [0.0, 0.0],
        [2.0, 1.0],
        feature_names=["employment", "inflation"],
    )
    assert result.is_exact
    assert result.method == "exact_linear_fixed_model"
    assert result.contributions["employment"] == pytest.approx(6.0)
    assert result.contributions["inflation"] == pytest.approx(-4.0)
    assert sum(result.contributions.values()) == pytest.approx(result.total_change)
    assert result.unattributed_residual == pytest.approx(0.0, abs=1e-12)


def test_pipeline_linear_attribution_uses_fitted_preprocessing() -> None:
    X = np.column_stack([np.arange(20, dtype=float), np.linspace(-2, 2, 20)])
    y = 1.0 + 0.5 * X[:, 0] - X[:, 1]
    model = FixedElasticNetRegressor(alpha=0.01).fit(X, y)

    result = linear_news_attribution(
        model,
        [10.0, 0.0],
        [11.0, 0.5],
        feature_names=["payroll", "claims"],
    )
    assert result.is_exact
    assert sum(result.contributions.values()) == pytest.approx(result.total_change)


def test_tree_attribution_is_explicitly_approximate_and_deterministic() -> None:
    rng = np.random.default_rng(3)
    X = rng.normal(size=(50, 2))
    y = X[:, 0] * X[:, 1] + X[:, 0] ** 2
    model = DeterministicHistGradientBoostingRegressor(
        min_train_samples=20,
        min_samples_leaf=3,
        max_iter=40,
    ).fit(X, y)

    result = approximate_tree_news_attribution(
        model,
        [0.1, -0.2],
        [1.0, 0.8],
        feature_names=["activity", "financial_conditions"],
    )
    assert result.approximate
    assert result.label == "approximate"
    assert result.method.startswith("approximate_")
    assert sum(result.contributions.values()) == pytest.approx(result.total_change)
