"""Deterministic estimators for the real-time nowcasting model ladder.

The estimators in this module deliberately do not perform cross-validation or
hyperparameter search.  Their parameters are fixed before a backtest and every
preprocessing step is fitted on the training fold by :mod:`macro_nowcast.evaluation`.
This is the central defense against full-sample preprocessing leakage.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
from numpy.typing import ArrayLike, NDArray
from sklearn.base import BaseEstimator, RegressorMixin
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import ElasticNet, LinearRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.utils.validation import check_is_fitted

FloatArray = NDArray[np.float64]


def _as_2d_float(X: Any) -> FloatArray:
    """Convert a numpy/pandas/polars-like feature matrix without importing pandas."""

    array = X.to_numpy() if hasattr(X, "to_numpy") else np.asarray(X)
    result = np.asarray(array, dtype=float)
    if result.ndim == 1:
        result = result.reshape(-1, 1)
    if result.ndim != 2:
        raise ValueError("X must be a two-dimensional feature matrix")
    return result


def _as_1d_float(y: ArrayLike) -> FloatArray:
    array = y.to_numpy() if hasattr(y, "to_numpy") else np.asarray(y)
    result = np.asarray(array, dtype=float).reshape(-1)
    if result.ndim != 1:
        raise ValueError("y must be one-dimensional")
    return result


def _feature_names(X: Any, n_features: int) -> tuple[str, ...]:
    columns = getattr(X, "columns", None)
    if columns is None:
        return tuple(f"x{index}" for index in range(n_features))
    names = tuple(str(column) for column in columns)
    if len(names) != n_features:
        raise ValueError("Feature-name count does not match X")
    return names


def _validate_predict_features(
    estimator: Any,
    X: Any,
) -> FloatArray:
    array = _as_2d_float(X)
    if array.shape[1] != estimator.n_features_in_:
        raise ValueError(
            f"Expected {estimator.n_features_in_} features, received {array.shape[1]}"
        )
    columns = getattr(X, "columns", None)
    if columns is not None:
        names = tuple(str(column) for column in columns)
        if names != estimator.feature_names_in_tuple_:
            raise ValueError("Prediction columns must match the fitted columns and order")
    return array


def _column_values(X: Any, column: str | int) -> FloatArray:
    array = _as_2d_float(X)
    if isinstance(column, int):
        index = column
    else:
        columns = getattr(X, "columns", None)
        if columns is None:
            raise ValueError("A string lag_column requires a DataFrame-like X with columns")
        names = tuple(str(name) for name in columns)
        try:
            index = names.index(column)
        except ValueError as exc:
            raise ValueError(f"Unknown lag_column: {column!r}") from exc
    try:
        return array[:, index]
    except IndexError as exc:
        raise ValueError(f"lag_column index {index} is outside X") from exc


class HistoricalMeanRegressor(RegressorMixin, BaseEstimator):
    """Forecast every row with the mean target observed in the training fold."""

    def fit(self, X: Any, y: ArrayLike) -> HistoricalMeanRegressor:
        features = _as_2d_float(X)
        target = _as_1d_float(y)
        if len(features) != len(target):
            raise ValueError("X and y must have the same number of rows")
        observed = target[np.isfinite(target)]
        if observed.size == 0:
            raise ValueError("HistoricalMeanRegressor requires at least one finite target")
        self.mean_ = float(np.mean(observed))
        self.n_features_in_ = features.shape[1]
        self.feature_names_in_tuple_ = _feature_names(X, features.shape[1])
        self.feature_names_in_ = np.asarray(self.feature_names_in_tuple_, dtype=object)
        return self

    def predict(self, X: Any) -> FloatArray:
        check_is_fitted(self, attributes=["mean_", "n_features_in_"])
        features = _validate_predict_features(self, X)
        return np.full(features.shape[0], self.mean_, dtype=float)


class NoChangeRegressor(RegressorMixin, BaseEstimator):
    """No-change forecast using an explicit lag feature or the final training target.

    ``lag_column`` is preferred for multi-origin prediction because it represents
    the latest target value actually available at each origin.  With no lag column,
    the estimator emits the last finite target in the training fold as a constant.
    """

    def __init__(self, lag_column: str | int | None = None) -> None:
        self.lag_column = lag_column

    def fit(self, X: Any, y: ArrayLike) -> NoChangeRegressor:
        features = _as_2d_float(X)
        target = _as_1d_float(y)
        if len(features) != len(target):
            raise ValueError("X and y must have the same number of rows")
        observed = target[np.isfinite(target)]
        if observed.size == 0:
            raise ValueError("NoChangeRegressor requires at least one finite target")
        if self.lag_column is not None:
            _column_values(X, self.lag_column)
        self.last_value_ = float(observed[-1])
        self.n_features_in_ = features.shape[1]
        self.feature_names_in_tuple_ = _feature_names(X, features.shape[1])
        self.feature_names_in_ = np.asarray(self.feature_names_in_tuple_, dtype=object)
        return self

    def predict(self, X: Any) -> FloatArray:
        check_is_fitted(self, attributes=["last_value_", "n_features_in_"])
        features = _validate_predict_features(self, X)
        if self.lag_column is None:
            return np.full(features.shape[0], self.last_value_, dtype=float)
        values = _column_values(X, self.lag_column)
        if not np.all(np.isfinite(values)):
            raise ValueError("No-change lag values must be finite at every forecast origin")
        return values.astype(float, copy=True)


class AR1Regressor(RegressorMixin, BaseEstimator):
    """An AR(1) benchmark with an intercept.

    When ``lag_column`` is omitted, adjacent training targets estimate the model
    and multi-row predictions are recursive from the final observed target.  An
    explicit lag column instead produces row-specific one-step forecasts.
    """

    def __init__(
        self,
        lag_column: str | int | None = None,
        *,
        min_pairs: int = 2,
    ) -> None:
        self.lag_column = lag_column
        self.min_pairs = min_pairs

    def fit(self, X: Any, y: ArrayLike) -> AR1Regressor:
        features = _as_2d_float(X)
        target = _as_1d_float(y)
        if len(features) != len(target):
            raise ValueError("X and y must have the same number of rows")
        if self.min_pairs < 2:
            raise ValueError("min_pairs must be at least 2")

        if self.lag_column is None:
            lagged = target[:-1]
            outcomes = target[1:]
        else:
            lagged = _column_values(X, self.lag_column)
            outcomes = target
        valid = np.isfinite(lagged) & np.isfinite(outcomes)
        if np.count_nonzero(valid) < self.min_pairs:
            raise ValueError(f"AR1Regressor requires at least {self.min_pairs} finite pairs")
        lagged = lagged[valid]
        outcomes = outcomes[valid]

        if np.ptp(lagged) <= np.finfo(float).eps:
            self.intercept_ = float(np.mean(outcomes))
            self.phi_ = 0.0
        else:
            regression = LinearRegression().fit(lagged.reshape(-1, 1), outcomes)
            self.intercept_ = float(regression.intercept_)
            self.phi_ = float(regression.coef_[0])
        finite_target = target[np.isfinite(target)]
        self.last_value_ = float(finite_target[-1])
        self.coef_ = np.asarray([self.phi_], dtype=float)
        self.n_features_in_ = features.shape[1]
        self.feature_names_in_tuple_ = _feature_names(X, features.shape[1])
        self.feature_names_in_ = np.asarray(self.feature_names_in_tuple_, dtype=object)
        return self

    def predict(self, X: Any) -> FloatArray:
        check_is_fitted(self, attributes=["phi_", "intercept_", "last_value_"])
        features = _validate_predict_features(self, X)
        if self.lag_column is not None:
            lagged = _column_values(X, self.lag_column)
            if not np.all(np.isfinite(lagged)):
                raise ValueError("AR(1) lag values must be finite at every forecast origin")
            return self.intercept_ + self.phi_ * lagged

        predictions = np.empty(features.shape[0], dtype=float)
        previous = self.last_value_
        for index in range(features.shape[0]):
            previous = self.intercept_ + self.phi_ * previous
            predictions[index] = previous
        return predictions


def make_bridge_pipeline(*, fit_intercept: bool = True) -> Pipeline:
    """Return a fold-local median-imputed, standardized OLS bridge equation."""

    return Pipeline(
        steps=[
            (
                "imputer",
                SimpleImputer(strategy="median", keep_empty_features=True),
            ),
            ("scaler", StandardScaler()),
            ("model", LinearRegression(fit_intercept=fit_intercept)),
        ]
    )


class LinearBridgeRegressor(RegressorMixin, BaseEstimator):
    """Transparent linear bridge equation with fold-local preprocessing."""

    def __init__(self, *, fit_intercept: bool = True, min_train_samples: int = 3) -> None:
        self.fit_intercept = fit_intercept
        self.min_train_samples = min_train_samples

    def fit(self, X: Any, y: ArrayLike) -> LinearBridgeRegressor:
        features = _as_2d_float(X)
        target = _as_1d_float(y)
        if len(features) != len(target):
            raise ValueError("X and y must have the same number of rows")
        valid = np.isfinite(target)
        if np.count_nonzero(valid) < self.min_train_samples:
            raise ValueError(
                f"LinearBridgeRegressor requires {self.min_train_samples} finite targets"
            )
        self.pipeline_ = make_bridge_pipeline(fit_intercept=self.fit_intercept)
        self.pipeline_.fit(features[valid], target[valid])
        self.n_features_in_ = features.shape[1]
        self.feature_names_in_tuple_ = _feature_names(X, features.shape[1])
        self.feature_names_in_ = np.asarray(self.feature_names_in_tuple_, dtype=object)
        return self

    def predict(self, X: Any) -> FloatArray:
        check_is_fitted(self, attributes=["pipeline_", "n_features_in_"])
        features = _validate_predict_features(self, X)
        return np.asarray(self.pipeline_.predict(features), dtype=float)

    @property
    def coef_(self) -> FloatArray:
        check_is_fitted(self, attributes=["pipeline_"])
        return np.asarray(self.pipeline_.named_steps["model"].coef_, dtype=float)

    @property
    def intercept_(self) -> float:
        check_is_fitted(self, attributes=["pipeline_"])
        return float(self.pipeline_.named_steps["model"].intercept_)


def make_elastic_net_pipeline(
    *,
    alpha: float = 0.05,
    l1_ratio: float = 0.5,
    fit_intercept: bool = True,
    max_iter: int = 10_000,
    tol: float = 1e-6,
) -> Pipeline:
    """Create the fixed-parameter Elastic Net pipeline used inside each fold.

    Calling this factory on a training fold, rather than fitting an imputer or
    scaler before splitting, keeps all preprocessing time-aware.
    """

    if alpha < 0:
        raise ValueError("alpha must be non-negative")
    if not 0 <= l1_ratio <= 1:
        raise ValueError("l1_ratio must lie in [0, 1]")
    return Pipeline(
        steps=[
            (
                "imputer",
                SimpleImputer(strategy="median", keep_empty_features=True),
            ),
            ("scaler", StandardScaler()),
            (
                "model",
                ElasticNet(
                    alpha=alpha,
                    l1_ratio=l1_ratio,
                    fit_intercept=fit_intercept,
                    max_iter=max_iter,
                    tol=tol,
                    selection="cyclic",
                ),
            ),
        ]
    )


class FixedElasticNetRegressor(RegressorMixin, BaseEstimator):
    """Elastic Net with fixed parameters and training-fold-only preprocessing."""

    def __init__(
        self,
        *,
        alpha: float = 0.05,
        l1_ratio: float = 0.5,
        fit_intercept: bool = True,
        max_iter: int = 10_000,
        tol: float = 1e-6,
        min_train_samples: int = 3,
    ) -> None:
        self.alpha = alpha
        self.l1_ratio = l1_ratio
        self.fit_intercept = fit_intercept
        self.max_iter = max_iter
        self.tol = tol
        self.min_train_samples = min_train_samples

    def fit(self, X: Any, y: ArrayLike) -> FixedElasticNetRegressor:
        features = _as_2d_float(X)
        target = _as_1d_float(y)
        if len(features) != len(target):
            raise ValueError("X and y must have the same number of rows")
        valid = np.isfinite(target)
        if np.count_nonzero(valid) < self.min_train_samples:
            raise ValueError(
                f"FixedElasticNetRegressor requires {self.min_train_samples} finite targets"
            )
        self.pipeline_ = make_elastic_net_pipeline(
            alpha=self.alpha,
            l1_ratio=self.l1_ratio,
            fit_intercept=self.fit_intercept,
            max_iter=self.max_iter,
            tol=self.tol,
        )
        self.pipeline_.fit(features[valid], target[valid])
        self.n_features_in_ = features.shape[1]
        self.feature_names_in_tuple_ = _feature_names(X, features.shape[1])
        self.feature_names_in_ = np.asarray(self.feature_names_in_tuple_, dtype=object)
        return self

    def predict(self, X: Any) -> FloatArray:
        check_is_fitted(self, attributes=["pipeline_", "n_features_in_"])
        features = _validate_predict_features(self, X)
        return np.asarray(self.pipeline_.predict(features), dtype=float)

    @property
    def coef_(self) -> FloatArray:
        check_is_fitted(self, attributes=["pipeline_"])
        return np.asarray(self.pipeline_.named_steps["model"].coef_, dtype=float)

    @property
    def intercept_(self) -> float:
        check_is_fitted(self, attributes=["pipeline_"])
        return float(self.pipeline_.named_steps["model"].intercept_)


class DeterministicHistGradientBoostingRegressor(RegressorMixin, BaseEstimator):
    """Guarded nonlinear benchmark with deterministic settings and no early stop."""

    def __init__(
        self,
        *,
        learning_rate: float = 0.05,
        max_iter: int = 150,
        max_leaf_nodes: int = 15,
        max_depth: int | None = 3,
        min_samples_leaf: int = 5,
        l2_regularization: float = 1.0,
        min_train_samples: int = 20,
        random_state: int = 0,
    ) -> None:
        self.learning_rate = learning_rate
        self.max_iter = max_iter
        self.max_leaf_nodes = max_leaf_nodes
        self.max_depth = max_depth
        self.min_samples_leaf = min_samples_leaf
        self.l2_regularization = l2_regularization
        self.min_train_samples = min_train_samples
        self.random_state = random_state

    def fit(self, X: Any, y: ArrayLike) -> DeterministicHistGradientBoostingRegressor:
        features = _as_2d_float(X)
        target = _as_1d_float(y)
        if len(features) != len(target):
            raise ValueError("X and y must have the same number of rows")
        valid = np.isfinite(target)
        n_valid = int(np.count_nonzero(valid))
        if n_valid < self.min_train_samples:
            raise ValueError(
                "DeterministicHistGradientBoostingRegressor requires at least "
                f"{self.min_train_samples} finite targets; received {n_valid}"
            )
        if self.min_samples_leaf < 1:
            raise ValueError("min_samples_leaf must be positive")
        self.imputer_ = SimpleImputer(strategy="median", keep_empty_features=True)
        prepared = self.imputer_.fit_transform(features[valid])
        self.model_ = HistGradientBoostingRegressor(
            learning_rate=self.learning_rate,
            max_iter=self.max_iter,
            max_leaf_nodes=self.max_leaf_nodes,
            max_depth=self.max_depth,
            min_samples_leaf=self.min_samples_leaf,
            l2_regularization=self.l2_regularization,
            early_stopping=False,
            random_state=self.random_state,
        )
        self.model_.fit(prepared, target[valid])
        self.n_features_in_ = features.shape[1]
        self.feature_names_in_tuple_ = _feature_names(X, features.shape[1])
        self.feature_names_in_ = np.asarray(self.feature_names_in_tuple_, dtype=object)
        return self

    def predict(self, X: Any) -> FloatArray:
        check_is_fitted(self, attributes=["model_", "n_features_in_"])
        features = _validate_predict_features(self, X)
        prepared = self.imputer_.transform(features)
        return np.asarray(self.model_.predict(prepared), dtype=float)


def make_hist_gradient_boosting_regressor(
    **kwargs: Any,
) -> DeterministicHistGradientBoostingRegressor:
    """Create the guarded deterministic tree estimator."""

    return DeterministicHistGradientBoostingRegressor(**kwargs)


def default_model_ladder() -> Mapping[str, BaseEstimator]:
    """Return fresh, unfitted estimators with stable portfolio-facing names."""

    return {
        "historical_mean": HistoricalMeanRegressor(),
        "no_change": NoChangeRegressor(),
        "ar1": AR1Regressor(),
        "bridge_linear": LinearBridgeRegressor(),
        "elastic_net": FixedElasticNetRegressor(),
        "hist_gradient_boosting": DeterministicHistGradientBoostingRegressor(),
    }


__all__ = [
    "AR1Regressor",
    "DeterministicHistGradientBoostingRegressor",
    "FixedElasticNetRegressor",
    "HistoricalMeanRegressor",
    "LinearBridgeRegressor",
    "NoChangeRegressor",
    "default_model_ladder",
    "make_bridge_pipeline",
    "make_elastic_net_pipeline",
    "make_hist_gradient_boosting_regressor",
]
