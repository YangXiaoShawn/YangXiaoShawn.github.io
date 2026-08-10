"""Leakage-aware expanding-window forecast evaluation.

Training targets are eligible only when their release timestamp is no later
than the fold origin.  Test targets are, of course, used after forecasting to
score the result; they never enter that fold's fit or interval calibration.
"""

from __future__ import annotations

import copy
import math
from collections.abc import Hashable, Iterable, Iterator, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, Literal

import numpy as np
from numpy.typing import ArrayLike, NDArray
from scipy.stats import t as student_t
from sklearn.base import clone

FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]
DateArray = NDArray[np.datetime64]


def _as_1d(values: Any, *, name: str) -> NDArray[Any]:
    array = values.to_numpy() if hasattr(values, "to_numpy") else np.asarray(values)
    result = np.asarray(array).reshape(-1)
    if result.ndim != 1:
        raise ValueError(f"{name} must be one-dimensional")
    return result


def _as_float_1d(values: ArrayLike, *, name: str) -> FloatArray:
    try:
        return np.asarray(_as_1d(values, name=name), dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must contain numeric values") from exc


def _as_2d_float(values: Any, *, name: str = "X") -> FloatArray:
    array = values.to_numpy() if hasattr(values, "to_numpy") else np.asarray(values)
    result = np.asarray(array, dtype=float)
    if result.ndim == 1:
        result = result.reshape(-1, 1)
    if result.ndim != 2:
        raise ValueError(f"{name} must be two-dimensional")
    return result


def _as_datetimes(values: Any, *, name: str) -> DateArray:
    raw = _as_1d(values, name=name)
    normalized = [
        value.astimezone(UTC).replace(tzinfo=None)
        if isinstance(value, datetime) and value.tzinfo is not None
        else value
        for value in raw
    ]
    try:
        result = np.asarray(normalized, dtype="datetime64[ns]")
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must contain datetime-like values") from exc
    return result


def _validate_lengths(expected: int, **arrays: Any) -> None:
    for name, values in arrays.items():
        if values is not None and len(values) != expected:
            raise ValueError(f"{name} has {len(values)} rows; expected {expected}")


@dataclass(frozen=True)
class ExpandingWindowFold:
    """One chronological fold and its release-date eligibility audit."""

    fold: int
    origin: np.datetime64
    train_indices: IntArray
    test_indices: IntArray
    excluded_unreleased_indices: IntArray

    @property
    def train_size(self) -> int:
        return int(self.train_indices.size)

    @property
    def test_size(self) -> int:
        return int(self.test_indices.size)


def iter_expanding_folds(
    n_samples: int,
    *,
    origins: Any,
    target_release_dates: Any,
    min_train_size: int,
    test_size: int = 1,
    step: int = 1,
    gap: int = 0,
    allow_partial_test: bool = False,
) -> Iterator[ExpandingWindowFold]:
    """Yield expanding folds with unreleased training targets removed.

    A target with a missing release date is conservatively treated as
    unavailable.  ``min_train_size`` applies after the release-date filter.
    Date-only releases should already have been normalized to the repository's
    documented end-of-day convention by the caller.
    """

    if n_samples < 1:
        raise ValueError("n_samples must be positive")
    if min_train_size < 1:
        raise ValueError("min_train_size must be positive")
    if test_size < 1 or step < 1:
        raise ValueError("test_size and step must be positive")
    if gap < 0:
        raise ValueError("gap cannot be negative")

    origin_array = _as_datetimes(origins, name="origins")
    release_array = _as_datetimes(target_release_dates, name="target_release_dates")
    _validate_lengths(
        n_samples,
        origins=origin_array,
        target_release_dates=release_array,
    )
    if np.any(np.isnat(origin_array)):
        raise ValueError("origins cannot contain missing timestamps")
    if np.any(origin_array[1:] < origin_array[:-1]):
        raise ValueError("origins must be in nondecreasing chronological order")

    first_test = min_train_size + gap
    fold_number = 0
    for test_start in range(first_test, n_samples, step):
        test_stop = min(test_start + test_size, n_samples)
        if test_stop - test_start < test_size and not allow_partial_test:
            break
        train_stop = test_start - gap
        candidates = np.arange(train_stop, dtype=np.int64)
        fold_origin = origin_array[test_start]
        released = ~np.isnat(release_array[candidates])
        released &= release_array[candidates] <= fold_origin
        train_indices = candidates[released]
        if train_indices.size < min_train_size:
            continue
        excluded = candidates[~released]
        yield ExpandingWindowFold(
            fold=fold_number,
            origin=fold_origin,
            train_indices=train_indices,
            test_indices=np.arange(test_start, test_stop, dtype=np.int64),
            excluded_unreleased_indices=excluded,
        )
        fold_number += 1


def expanding_window_splits(
    n_samples: int,
    *,
    origins: Any,
    target_release_dates: Any,
    min_train_size: int,
    test_size: int = 1,
    step: int = 1,
    gap: int = 0,
    allow_partial_test: bool = False,
) -> Iterator[tuple[IntArray, IntArray]]:
    """Tuple-based convenience wrapper around :func:`iter_expanding_folds`."""

    for fold in iter_expanding_folds(
        n_samples,
        origins=origins,
        target_release_dates=target_release_dates,
        min_train_size=min_train_size,
        test_size=test_size,
        step=step,
        gap=gap,
        allow_partial_test=allow_partial_test,
    ):
        yield fold.train_indices, fold.test_indices


class ExpandingWindowSplitter:
    """Reusable expanding-window split configuration.

    Unlike generic scikit-learn splitters, ``split`` requires both forecast
    origins and target release dates so information availability cannot be
    silently ignored.
    """

    def __init__(
        self,
        min_train_size: int,
        *,
        test_size: int = 1,
        step: int = 1,
        gap: int = 0,
        allow_partial_test: bool = False,
    ) -> None:
        self.min_train_size = min_train_size
        self.test_size = test_size
        self.step = step
        self.gap = gap
        self.allow_partial_test = allow_partial_test

    def iter_folds(
        self,
        X: Any,
        *,
        origins: Any,
        target_release_dates: Any,
    ) -> Iterator[ExpandingWindowFold]:
        return iter_expanding_folds(
            len(X),
            origins=origins,
            target_release_dates=target_release_dates,
            min_train_size=self.min_train_size,
            test_size=self.test_size,
            step=self.step,
            gap=self.gap,
            allow_partial_test=self.allow_partial_test,
        )

    def split(
        self,
        X: Any,
        y: Any = None,
        groups: Any = None,
        *,
        origins: Any,
        target_release_dates: Any,
    ) -> Iterator[tuple[IntArray, IntArray]]:
        del y, groups
        for fold in self.iter_folds(
            X,
            origins=origins,
            target_release_dates=target_release_dates,
        ):
            yield fold.train_indices, fold.test_indices


def root_mean_squared_error(y_true: ArrayLike, y_pred: ArrayLike) -> float:
    actual, predicted = _paired_finite(y_true, y_pred)
    return float(np.sqrt(np.mean(np.square(predicted - actual))))


def mean_absolute_error(y_true: ArrayLike, y_pred: ArrayLike) -> float:
    actual, predicted = _paired_finite(y_true, y_pred)
    return float(np.mean(np.abs(predicted - actual)))


def forecast_bias(y_true: ArrayLike, y_pred: ArrayLike) -> float:
    """Mean ``forecast - actual``; positive values indicate overprediction."""

    actual, predicted = _paired_finite(y_true, y_pred)
    return float(np.mean(predicted - actual))


def directional_accuracy(
    y_true: ArrayLike,
    y_pred: ArrayLike,
    *,
    reference: ArrayLike | None = None,
) -> float:
    """Share of signs correctly forecast, optionally relative to a reference level."""

    actual = _as_float_1d(y_true, name="y_true")
    predicted = _as_float_1d(y_pred, name="y_pred")
    _validate_lengths(len(actual), y_pred=predicted)
    if reference is None:
        benchmark = np.zeros_like(actual)
    else:
        benchmark = _as_float_1d(reference, name="reference")
        _validate_lengths(len(actual), reference=benchmark)
    valid = np.isfinite(actual) & np.isfinite(predicted) & np.isfinite(benchmark)
    if not np.any(valid):
        return math.nan
    return float(np.mean(np.sign(actual[valid] - benchmark[valid]) == np.sign(
        predicted[valid] - benchmark[valid]
    )))


def interval_coverage(
    y_true: ArrayLike,
    lower: ArrayLike,
    upper: ArrayLike,
) -> float:
    actual = _as_float_1d(y_true, name="y_true")
    lower_array = _as_float_1d(lower, name="lower")
    upper_array = _as_float_1d(upper, name="upper")
    _validate_lengths(len(actual), lower=lower_array, upper=upper_array)
    valid = np.isfinite(actual) & np.isfinite(lower_array) & np.isfinite(upper_array)
    if not np.any(valid):
        return math.nan
    if np.any(lower_array[valid] > upper_array[valid]):
        raise ValueError("lower interval bounds cannot exceed upper bounds")
    covered = (actual[valid] >= lower_array[valid]) & (actual[valid] <= upper_array[valid])
    return float(np.mean(covered))


def _paired_finite(y_true: ArrayLike, y_pred: ArrayLike) -> tuple[FloatArray, FloatArray]:
    actual = _as_float_1d(y_true, name="y_true")
    predicted = _as_float_1d(y_pred, name="y_pred")
    _validate_lengths(len(actual), y_pred=predicted)
    valid = np.isfinite(actual) & np.isfinite(predicted)
    if not np.any(valid):
        raise ValueError("At least one finite actual/forecast pair is required")
    return actual[valid], predicted[valid]


def regression_metrics(
    y_true: ArrayLike,
    y_pred: ArrayLike,
    *,
    lower: ArrayLike | None = None,
    upper: ArrayLike | None = None,
    direction_reference: ArrayLike | None = None,
    include_directional_accuracy: bool = True,
) -> dict[str, int | float]:
    """Compute deterministic point and optional interval forecast metrics."""

    actual_all = _as_float_1d(y_true, name="y_true")
    predicted_all = _as_float_1d(y_pred, name="y_pred")
    _validate_lengths(len(actual_all), y_pred=predicted_all)
    valid = np.isfinite(actual_all) & np.isfinite(predicted_all)
    if not np.any(valid):
        raise ValueError("At least one finite actual/forecast pair is required")
    actual = actual_all[valid]
    predicted = predicted_all[valid]
    result: dict[str, int | float] = {
        "n_obs": int(actual.size),
        "rmse": float(np.sqrt(np.mean(np.square(predicted - actual)))),
        "mae": float(np.mean(np.abs(predicted - actual))),
        "bias": float(np.mean(predicted - actual)),
    }
    if include_directional_accuracy:
        if direction_reference is None:
            reference = None
        else:
            reference_all = _as_float_1d(direction_reference, name="direction_reference")
            _validate_lengths(len(actual_all), direction_reference=reference_all)
            reference = reference_all[valid]
        result["directional_accuracy"] = directional_accuracy(
            actual,
            predicted,
            reference=reference,
        )

    if (lower is None) != (upper is None):
        raise ValueError("lower and upper must be supplied together")
    if lower is not None and upper is not None:
        lower_all = _as_float_1d(lower, name="lower")
        upper_all = _as_float_1d(upper, name="upper")
        _validate_lengths(len(actual_all), lower=lower_all, upper=upper_all)
        interval_valid = valid & np.isfinite(lower_all) & np.isfinite(upper_all)
        result["n_intervals"] = int(np.count_nonzero(interval_valid))
        if np.any(interval_valid):
            result["interval_coverage"] = interval_coverage(
                actual_all[interval_valid],
                lower_all[interval_valid],
                upper_all[interval_valid],
            )
            result["mean_interval_width"] = float(
                np.mean(upper_all[interval_valid] - lower_all[interval_valid])
            )
        else:
            result["interval_coverage"] = math.nan
            result["mean_interval_width"] = math.nan
    return result


def residual_prediction_interval(
    point_forecast: ArrayLike,
    residuals: ArrayLike,
    *,
    coverage: float = 0.9,
    min_residuals: int = 10,
) -> tuple[FloatArray, FloatArray]:
    """Apply empirical signed-residual quantiles to point forecasts.

    The caller is responsible for passing only residuals whose targets were
    released by the current origin.  Insufficient history produces explicit
    ``NaN`` bounds rather than a fabricated uncertainty estimate.
    """

    if not 0 < coverage < 1:
        raise ValueError("coverage must lie strictly between 0 and 1")
    if min_residuals < 1:
        raise ValueError("min_residuals must be positive")
    forecasts = _as_float_1d(point_forecast, name="point_forecast")
    history = _as_float_1d(residuals, name="residuals")
    history = history[np.isfinite(history)]
    if history.size < min_residuals:
        missing = np.full(forecasts.shape, np.nan, dtype=float)
        return missing.copy(), missing
    tail = (1.0 - coverage) / 2.0
    low_error, high_error = np.quantile(history, [tail, 1.0 - tail], method="linear")
    return forecasts + low_error, forecasts + high_error


@dataclass(frozen=True)
class ForecastRecord:
    """Auditable out-of-sample prediction at one forecast origin."""

    fold: int
    row_index: int
    model: str
    origin: np.datetime64
    target_release_date: np.datetime64
    actual: float
    forecast: float
    lower: float
    upper: float
    train_size: int
    horizon: Hashable | None = None
    regime: Hashable | None = None


@dataclass(frozen=True)
class BacktestResult:
    """Immutable forecast records plus metric/grouping conveniences."""

    records: tuple[ForecastRecord, ...]
    interval_coverage_target: float

    def to_dicts(self) -> list[dict[str, Any]]:
        return [asdict(record) for record in self.records]

    @property
    def actuals(self) -> FloatArray:
        return np.asarray([record.actual for record in self.records], dtype=float)

    @property
    def forecasts(self) -> FloatArray:
        return np.asarray([record.forecast for record in self.records], dtype=float)

    @property
    def lower_bounds(self) -> FloatArray:
        return np.asarray([record.lower for record in self.records], dtype=float)

    @property
    def upper_bounds(self) -> FloatArray:
        return np.asarray([record.upper for record in self.records], dtype=float)

    def metrics(self) -> dict[str, int | float]:
        if not self.records:
            raise ValueError("No forecast records are available")
        return regression_metrics(
            self.actuals,
            self.forecasts,
            lower=self.lower_bounds,
            upper=self.upper_bounds,
        )

    def grouped_metrics(
        self,
        by: str | Sequence[str],
    ) -> dict[Hashable, dict[str, int | float]]:
        return grouped_metrics(self.records, by=by)


def _metadata_array(values: Any, *, n_samples: int, name: str) -> NDArray[Any]:
    if values is None:
        return np.full(n_samples, None, dtype=object)
    if isinstance(values, (str, bytes)) or not hasattr(values, "__len__"):
        return np.full(n_samples, values, dtype=object)
    result = _as_1d(values, name=name)
    _validate_lengths(n_samples, **{name: result})
    return result


def _fresh_clone(estimator: Any) -> Any:
    try:
        return clone(estimator)
    except (TypeError, RuntimeError):
        return copy.deepcopy(estimator)


def run_expanding_backtest(
    estimator: Any,
    X: Any,
    y: ArrayLike,
    *,
    origins: Any,
    target_release_dates: Any,
    min_train_size: int,
    test_size: int = 1,
    step: int = 1,
    gap: int = 0,
    horizon: Any = None,
    regimes: Any = None,
    model_name: str | None = None,
    interval_coverage_target: float = 0.9,
    interval_min_residuals: int = 10,
) -> BacktestResult:
    """Fit a fresh estimator per fold and return release-aware OOS forecasts.

    Residual intervals use only earlier out-of-sample residuals whose target
    releases have occurred by the forecast origin.  Hyperparameter selection is
    intentionally outside this function; pass an already configured estimator.
    """

    features = _as_2d_float(X)
    target = _as_float_1d(y, name="y")
    origin_array = _as_datetimes(origins, name="origins")
    release_array = _as_datetimes(target_release_dates, name="target_release_dates")
    n_samples = len(target)
    _validate_lengths(
        n_samples,
        X=features,
        origins=origin_array,
        target_release_dates=release_array,
    )
    horizon_array = _metadata_array(horizon, n_samples=n_samples, name="horizon")
    regime_array = _metadata_array(regimes, n_samples=n_samples, name="regimes")
    label = model_name or type(estimator).__name__

    records: list[ForecastRecord] = []
    residual_history: list[tuple[float, np.datetime64]] = []
    for fold in iter_expanding_folds(
        n_samples,
        origins=origin_array,
        target_release_dates=release_array,
        min_train_size=min_train_size,
        test_size=test_size,
        step=step,
        gap=gap,
    ):
        finite_train = np.isfinite(target[fold.train_indices])
        train_indices = fold.train_indices[finite_train]
        if train_indices.size < min_train_size:
            continue
        fitted = _fresh_clone(estimator)
        fitted.fit(features[train_indices], target[train_indices])
        predictions = np.asarray(
            fitted.predict(features[fold.test_indices]), dtype=float
        ).reshape(-1)
        if len(predictions) != len(fold.test_indices):
            raise ValueError("Estimator returned the wrong number of predictions")

        for row_index, prediction in zip(fold.test_indices, predictions, strict=True):
            origin = origin_array[row_index]
            eligible_residuals = [
                residual
                for residual, release_date in residual_history
                if not np.isnat(release_date) and release_date <= origin
            ]
            lower_array, upper_array = residual_prediction_interval(
                [prediction],
                eligible_residuals,
                coverage=interval_coverage_target,
                min_residuals=interval_min_residuals,
            )
            actual = float(target[row_index])
            record = ForecastRecord(
                fold=fold.fold,
                row_index=int(row_index),
                model=label,
                origin=origin,
                target_release_date=release_array[row_index],
                actual=actual,
                forecast=float(prediction),
                lower=float(lower_array[0]),
                upper=float(upper_array[0]),
                train_size=int(train_indices.size),
                horizon=horizon_array[row_index],
                regime=regime_array[row_index],
            )
            records.append(record)
            if np.isfinite(actual) and np.isfinite(prediction):
                residual_history.append((actual - float(prediction), release_array[row_index]))

    return BacktestResult(
        records=tuple(records),
        interval_coverage_target=interval_coverage_target,
    )


def grouped_metrics(
    records: Iterable[ForecastRecord | Mapping[str, Any]],
    *,
    by: str | Sequence[str],
) -> dict[Hashable, dict[str, int | float]]:
    """Group forecast metrics by hooks such as ``horizon`` and ``regime``."""

    fields = (by,) if isinstance(by, str) else tuple(by)
    if not fields:
        raise ValueError("At least one grouping field is required")
    allowed = set(ForecastRecord.__dataclass_fields__)
    unknown = set(fields) - allowed
    if unknown:
        raise ValueError(f"Unknown grouping fields: {sorted(unknown)}")

    groups: dict[Hashable, list[ForecastRecord | Mapping[str, Any]]] = {}
    for record in records:
        if isinstance(record, Mapping):
            values = tuple(record[field] for field in fields)
        else:
            values = tuple(getattr(record, field) for field in fields)
        key: Hashable = values[0] if len(values) == 1 else values
        groups.setdefault(key, []).append(record)

    result: dict[Hashable, dict[str, int | float]] = {}
    for key, group in groups.items():
        if isinstance(group[0], Mapping):
            actual = [item["actual"] for item in group]  # type: ignore[index]
            forecast = [item["forecast"] for item in group]  # type: ignore[index]
            lower = [item["lower"] for item in group]  # type: ignore[index]
            upper = [item["upper"] for item in group]  # type: ignore[index]
        else:
            actual = [item.actual for item in group]  # type: ignore[union-attr]
            forecast = [item.forecast for item in group]  # type: ignore[union-attr]
            lower = [item.lower for item in group]  # type: ignore[union-attr]
            upper = [item.upper for item in group]  # type: ignore[union-attr]
        result[key] = regression_metrics(
            actual,
            forecast,
            lower=lower,
            upper=upper,
        )
    return result


@dataclass(frozen=True)
class DMResult:
    """Guarded Diebold-Mariano-style equal-predictive-accuracy result."""

    statistic: float
    p_value: float
    mean_loss_differential: float
    n_obs: int
    hac_lag: int
    valid: bool
    reason: str | None = None


def diebold_mariano(
    y_true: ArrayLike,
    forecast_a: ArrayLike,
    forecast_b: ArrayLike,
    *,
    loss: Literal["squared", "absolute"] = "squared",
    horizon: int = 1,
    min_observations: int = 20,
    alternative: Literal["two-sided", "less", "greater"] = "two-sided",
    small_sample_correction: bool = True,
) -> DMResult:
    """Compare two forecasts with a Bartlett-HAC loss differential variance.

    The differential is ``loss(a) - loss(b)``.  A positive statistic therefore
    favors forecast B.  Degenerate or short samples return ``valid=False`` and
    NaN inferential values instead of a misleading significance claim.
    """

    if horizon < 1:
        raise ValueError("horizon must be positive")
    if min_observations < 3:
        raise ValueError("min_observations must be at least 3")
    if loss not in {"squared", "absolute"}:
        raise ValueError("loss must be 'squared' or 'absolute'")
    if alternative not in {"two-sided", "less", "greater"}:
        raise ValueError("Unsupported alternative")

    actual = _as_float_1d(y_true, name="y_true")
    first = _as_float_1d(forecast_a, name="forecast_a")
    second = _as_float_1d(forecast_b, name="forecast_b")
    _validate_lengths(len(actual), forecast_a=first, forecast_b=second)
    valid_rows = np.isfinite(actual) & np.isfinite(first) & np.isfinite(second)
    actual = actual[valid_rows]
    first = first[valid_rows]
    second = second[valid_rows]
    n_obs = len(actual)
    hac_lag = horizon - 1
    if n_obs < max(min_observations, hac_lag + 3):
        return DMResult(
            statistic=math.nan,
            p_value=math.nan,
            mean_loss_differential=math.nan,
            n_obs=n_obs,
            hac_lag=hac_lag,
            valid=False,
            reason="insufficient_observations",
        )

    error_a = actual - first
    error_b = actual - second
    if loss == "squared":
        differential = np.square(error_a) - np.square(error_b)
    else:
        differential = np.abs(error_a) - np.abs(error_b)
    mean_difference = float(np.mean(differential))
    centered = differential - mean_difference
    long_run_variance = float(np.dot(centered, centered) / n_obs)
    for lag in range(1, hac_lag + 1):
        covariance = float(np.dot(centered[lag:], centered[:-lag]) / n_obs)
        bartlett_weight = 1.0 - lag / (hac_lag + 1.0)
        long_run_variance += 2.0 * bartlett_weight * covariance

    if not np.isfinite(long_run_variance) or long_run_variance <= np.finfo(float).eps:
        return DMResult(
            statistic=math.nan,
            p_value=math.nan,
            mean_loss_differential=mean_difference,
            n_obs=n_obs,
            hac_lag=hac_lag,
            valid=False,
            reason="degenerate_loss_differential_variance",
        )
    statistic = mean_difference / math.sqrt(long_run_variance / n_obs)
    if small_sample_correction:
        correction_term = (
            n_obs + 1 - 2 * horizon + horizon * (horizon - 1) / n_obs
        ) / n_obs
        if correction_term <= 0:
            return DMResult(
                statistic=math.nan,
                p_value=math.nan,
                mean_loss_differential=mean_difference,
                n_obs=n_obs,
                hac_lag=hac_lag,
                valid=False,
                reason="invalid_small_sample_correction",
            )
        statistic *= math.sqrt(correction_term)

    if alternative == "two-sided":
        p_value = float(2.0 * student_t.sf(abs(statistic), df=n_obs - 1))
    elif alternative == "greater":
        p_value = float(student_t.sf(statistic, df=n_obs - 1))
    else:
        p_value = float(student_t.cdf(statistic, df=n_obs - 1))
    return DMResult(
        statistic=float(statistic),
        p_value=p_value,
        mean_loss_differential=mean_difference,
        n_obs=n_obs,
        hac_lag=hac_lag,
        valid=True,
    )


dm_test = diebold_mariano
evaluate_forecasts = regression_metrics


__all__ = [
    "BacktestResult",
    "DMResult",
    "ExpandingWindowFold",
    "ExpandingWindowSplitter",
    "ForecastRecord",
    "diebold_mariano",
    "directional_accuracy",
    "dm_test",
    "evaluate_forecasts",
    "expanding_window_splits",
    "forecast_bias",
    "grouped_metrics",
    "interval_coverage",
    "iter_expanding_folds",
    "mean_absolute_error",
    "regression_metrics",
    "residual_prediction_interval",
    "root_mean_squared_error",
    "run_expanding_backtest",
]
