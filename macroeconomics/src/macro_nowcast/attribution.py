"""Fixed-model nowcast news attribution.

Linear attributions are exact coefficient decompositions in the fitted model's
transformed feature space.  Tree attributions use deterministic sequential
feature replacement and are always labeled approximate because interaction
credit depends on replacement order.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray
from sklearn.pipeline import Pipeline
from sklearn.utils.validation import check_is_fitted

FloatArray = NDArray[np.float64]


@dataclass(frozen=True)
class AttributionResult:
    """Auditable change decomposition for a fixed fitted model."""

    previous_prediction: float
    updated_prediction: float
    total_change: float
    contributions: Mapping[str, float]
    feature_changes: Mapping[str, float]
    unattributed_residual: float
    method: str
    approximate: bool

    @property
    def is_exact(self) -> bool:
        return not self.approximate

    @property
    def label(self) -> str:
        return "approximate" if self.approximate else "exact"


def _raw_row_and_names(
    values: Any,
    *,
    feature_names: Sequence[str] | None,
) -> tuple[FloatArray, tuple[str, ...]]:
    if isinstance(values, Mapping):
        inferred_names = tuple(str(name) for name in values)
        row = np.asarray([values[name] for name in values], dtype=float).reshape(1, -1)
    else:
        if hasattr(values, "to_numpy"):
            raw = values.to_numpy()
            columns = getattr(values, "columns", None)
            inferred_names = tuple(str(name) for name in columns) if columns is not None else ()
        else:
            raw = np.asarray(values)
            inferred_names = ()
        row = np.asarray(raw, dtype=float)
        if row.ndim == 1:
            row = row.reshape(1, -1)
        if row.ndim != 2 or row.shape[0] != 1:
            raise ValueError("Features must describe exactly one observation")

    if feature_names is not None:
        names = tuple(str(name) for name in feature_names)
    elif inferred_names:
        names = inferred_names
    else:
        names = tuple(f"x{index}" for index in range(row.shape[1]))
    if len(names) != row.shape[1] or len(set(names)) != len(names):
        raise ValueError("feature_names must be unique and match the feature count")
    return row, names


def _aligned_rows(
    previous_features: Any,
    updated_features: Any,
    feature_names: Sequence[str] | None,
) -> tuple[FloatArray, FloatArray, tuple[str, ...]]:
    if isinstance(previous_features, Mapping) and isinstance(updated_features, Mapping):
        previous_keys = tuple(str(key) for key in previous_features)
        updated_keys = tuple(str(key) for key in updated_features)
        if set(previous_keys) != set(updated_keys):
            raise ValueError("Previous and updated feature mappings must have identical keys")
        names = tuple(str(name) for name in feature_names) if feature_names else previous_keys
        try:
            previous = np.asarray(
                [previous_features[name] for name in names], dtype=float
            ).reshape(1, -1)
            updated = np.asarray(
                [updated_features[name] for name in names], dtype=float
            ).reshape(1, -1)
        except KeyError as exc:
            raise ValueError("feature_names contains a key missing from a feature mapping") from exc
        return previous, updated, names

    previous, names = _raw_row_and_names(
        previous_features,
        feature_names=feature_names,
    )
    updated, updated_names = _raw_row_and_names(
        updated_features,
        feature_names=names,
    )
    if previous.shape != updated.shape or names != updated_names:
        raise ValueError("Previous and updated features must have identical shape and order")
    return previous, updated, names


def _predict_one(model: Any, row: FloatArray) -> float:
    prediction = np.asarray(model.predict(row), dtype=float).reshape(-1)
    if prediction.size != 1 or not np.isfinite(prediction[0]):
        raise ValueError("Model must return one finite prediction per attribution row")
    return float(prediction[0])


def _pipeline_and_linear_estimator(model: Any) -> tuple[Any, Any]:
    fitted = getattr(model, "pipeline_", model)
    if isinstance(fitted, Pipeline):
        check_is_fitted(fitted)
        estimator = fitted.steps[-1][1]
        transformer = fitted[:-1]
    else:
        estimator = fitted
        transformer = None
    check_is_fitted(estimator, attributes=["coef_"])
    return transformer, estimator


def _dense_2d(values: Any) -> FloatArray:
    if hasattr(values, "toarray"):
        values = values.toarray()
    result = np.asarray(values, dtype=float)
    if result.ndim == 1:
        result = result.reshape(1, -1)
    if result.ndim != 2:
        raise ValueError("Transformed features must be two-dimensional")
    return result


def linear_news_attribution(
    model: Any,
    previous_features: Any,
    updated_features: Any,
    *,
    feature_names: Sequence[str] | None = None,
    atol: float = 1e-9,
) -> AttributionResult:
    """Exactly decompose a fixed fitted linear model's prediction revision.

    For an imputer/scaler/linear pipeline, contributions are coefficients times
    changes in the transformed features.  The transformer and model are never
    refitted during attribution.
    """

    previous, updated, raw_names = _aligned_rows(
        previous_features,
        updated_features,
        feature_names,
    )
    transformer, estimator = _pipeline_and_linear_estimator(model)
    if transformer is None:
        previous_transformed = previous
        updated_transformed = updated
        transformed_names = raw_names
    else:
        previous_transformed = _dense_2d(transformer.transform(previous))
        updated_transformed = _dense_2d(transformer.transform(updated))
        try:
            transformed_names = tuple(
                str(name) for name in transformer.get_feature_names_out(raw_names)
            )
        except (AttributeError, TypeError, ValueError):
            transformed_names = raw_names

    coefficients = np.asarray(estimator.coef_, dtype=float)
    if coefficients.ndim == 2 and coefficients.shape[0] == 1:
        coefficients = coefficients[0]
    if coefficients.ndim != 1:
        raise ValueError("Only single-output linear estimators are supported")
    if previous_transformed.shape != updated_transformed.shape:
        raise ValueError("Preprocessing changed feature dimensions between snapshots")
    if coefficients.size != previous_transformed.shape[1]:
        raise ValueError("Linear coefficient count does not match transformed features")
    if len(transformed_names) != coefficients.size:
        transformed_names = tuple(f"transformed_x{i}" for i in range(coefficients.size))

    previous_prediction = _predict_one(model, previous)
    updated_prediction = _predict_one(model, updated)
    contribution_values = coefficients * (updated_transformed[0] - previous_transformed[0])
    total_change = updated_prediction - previous_prediction
    residual = total_change - float(np.sum(contribution_values))
    tolerance = atol * max(1.0, abs(total_change))
    if not math.isfinite(residual) or abs(residual) > tolerance:
        raise RuntimeError(
            "Linear contribution sum does not reproduce the fixed-model prediction change"
        )
    contributions = {
        name: float(value)
        for name, value in zip(transformed_names, contribution_values, strict=True)
    }
    feature_changes = {
        name: float(value)
        for name, value in zip(raw_names, updated[0] - previous[0], strict=True)
    }
    return AttributionResult(
        previous_prediction=previous_prediction,
        updated_prediction=updated_prediction,
        total_change=total_change,
        contributions=contributions,
        feature_changes=feature_changes,
        unattributed_residual=residual,
        method="exact_linear_fixed_model",
        approximate=False,
    )


def approximate_tree_news_attribution(
    model: Any,
    previous_features: Any,
    updated_features: Any,
    *,
    feature_names: Sequence[str] | None = None,
    feature_order: Sequence[str] | None = None,
) -> AttributionResult:
    """Approximate nonlinear attribution by sequential feature replacement.

    The deterministic contributions telescope to the prediction change, but the
    allocation of interactions is order-dependent.  The result therefore remains
    explicitly approximate even when its numerical residual is zero.
    """

    previous, updated, names = _aligned_rows(
        previous_features,
        updated_features,
        feature_names,
    )
    if feature_order is None:
        order = names
    else:
        order = tuple(str(name) for name in feature_order)
        if len(order) != len(names) or set(order) != set(names):
            raise ValueError("feature_order must contain every feature exactly once")

    previous_prediction = _predict_one(model, previous)
    updated_prediction = _predict_one(model, updated)
    current = previous.copy()
    current_prediction = previous_prediction
    contributions: dict[str, float] = {name: 0.0 for name in names}
    positions = {name: index for index, name in enumerate(names)}
    for name in order:
        position = positions[name]
        current[0, position] = updated[0, position]
        next_prediction = _predict_one(model, current)
        contributions[name] = next_prediction - current_prediction
        current_prediction = next_prediction

    total_change = updated_prediction - previous_prediction
    residual = total_change - float(sum(contributions.values()))
    feature_changes = {
        name: float(value)
        for name, value in zip(names, updated[0] - previous[0], strict=True)
    }
    return AttributionResult(
        previous_prediction=previous_prediction,
        updated_prediction=updated_prediction,
        total_change=total_change,
        contributions=contributions,
        feature_changes=feature_changes,
        unattributed_residual=residual,
        method="approximate_sequential_feature_replacement",
        approximate=True,
    )


exact_linear_attribution = linear_news_attribution
tree_news_attribution = approximate_tree_news_attribution


__all__ = [
    "AttributionResult",
    "approximate_tree_news_attribution",
    "exact_linear_attribution",
    "linear_news_attribution",
    "tree_news_attribution",
]
