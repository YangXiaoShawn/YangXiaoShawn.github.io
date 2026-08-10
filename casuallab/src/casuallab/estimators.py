"""Transparent causal estimator ladder with a common result contract.

These implementations favor inspectable design matrices and influence functions over
opaque causal-ML packages. Each result names its target estimand; callers remain
responsible for choosing a design that identifies that target.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field, fields, replace
from typing import Any

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy.optimize import minimize
from scipy.stats import norm
from scipy.stats import t as student_t
from sklearn.linear_model import LinearRegression, LogisticRegression
from sklearn.model_selection import StratifiedGroupKFold, StratifiedKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from statsmodels.stats.sandwich_covariance import cov_cluster_2groups

from .config import EstimatorConfig


@dataclass(frozen=True)
class EstimatorResult:
    """Method-agnostic scalar estimate and uncertainty contract."""

    method: str
    target_estimand: str
    estimate: float
    standard_error: float
    ci_low: float
    ci_high: float
    p_value: float
    n_obs: int
    outcome: str
    treatment: str
    alpha: float = 0.05
    diagnostics: Mapping[str, Any] = field(default_factory=dict)

    @property
    def se(self) -> float:
        return self.standard_error

    @property
    def std_error(self) -> float:
        return self.standard_error

    @property
    def ci(self) -> tuple[float, float]:
        return (self.ci_low, self.ci_high)

    def to_dict(self, *, flatten_diagnostics: bool = False) -> dict[str, Any]:
        result = asdict(self)
        result["se"] = result["standard_error"]
        result["std_error"] = result["standard_error"]
        if flatten_diagnostics:
            diagnostics = result.pop("diagnostics")
            result.update({f"diagnostic_{key}": value for key, value in diagnostics.items()})
        return result

    def __getitem__(self, key: str) -> Any:
        if key == "se":
            return self.standard_error
        return getattr(self, key)


def _normal_result(
    *,
    method: str,
    config: EstimatorConfig,
    estimate: float,
    standard_error: float,
    n_obs: int,
    p_value: float | None = None,
    critical_value: float | None = None,
    diagnostics: Mapping[str, Any] | None = None,
    treatment: str | None = None,
) -> EstimatorResult:
    critical = (
        float(norm.ppf(1.0 - config.alpha / 2.0))
        if critical_value is None
        else float(critical_value)
    )
    if p_value is None:
        if standard_error > 0 and np.isfinite(standard_error):
            p_value = float(2.0 * norm.sf(abs(estimate / standard_error)))
        elif standard_error == 0:
            p_value = float(0.0 if estimate != 0 else 1.0)
        else:
            p_value = float("nan")
    return EstimatorResult(
        method=method,
        target_estimand=config.target_estimand,
        estimate=float(estimate),
        standard_error=float(standard_error),
        ci_low=float(estimate - critical * standard_error),
        ci_high=float(estimate + critical * standard_error),
        p_value=float(p_value),
        n_obs=int(n_obs),
        outcome=config.outcome,
        treatment=treatment or config.treatment,
        alpha=config.alpha,
        diagnostics=dict(diagnostics or {}),
    )


def _normalize_method(method: str) -> str:
    normalized = method.strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "dim": "difference_in_means",
        "difference": "difference_in_means",
        "ols": "regression_adjustment",
        "regression": "regression_adjustment",
        "adjusted": "regression_adjustment",
        "regression_adjusted": "regression_adjustment",
        "clustered": "cluster_robust",
        "cluster_robust_ols": "cluster_robust",
        "cluster_adjusted": "cluster_robust",
        "two_way_cluster": "two_way_cluster_robust",
        "two_way_clustered": "two_way_cluster_robust",
        "two_way_cluster_robust_ols": "two_way_cluster_robust",
        "did": "difference_in_differences",
        "diff_in_diff": "difference_in_differences",
        "aipw": "doubly_robust",
        "dr": "doubly_robust",
        "synthetic": "synthetic_control",
        "synthetic_control_style": "synthetic_control",
    }
    return aliases.get(normalized, normalized)


def _coerce_config(
    method: str | EstimatorConfig | None,
    config: EstimatorConfig | Mapping[str, Any] | None,
    overrides: Mapping[str, Any],
) -> EstimatorConfig:
    if isinstance(method, EstimatorConfig):
        if config is not None:
            raise ValueError("provide EstimatorConfig as method or config, not both")
        cfg = method
    elif isinstance(config, EstimatorConfig):
        cfg = config
    elif isinstance(config, Mapping):
        cfg = EstimatorConfig.from_dict(config)
    else:
        cfg = EstimatorConfig()
    updates = dict(overrides)
    if method is not None and not isinstance(method, EstimatorConfig):
        updates["method"] = method
    if updates:
        allowed = {item.name for item in fields(EstimatorConfig) if item.init}
        unknown = set(updates).difference(allowed)
        if unknown:
            raise TypeError(f"unknown estimator options: {sorted(unknown)}")
        cfg = replace(cfg, **updates)
    return replace(cfg, method=_normalize_method(cfg.method))


def _eligible(data: pd.DataFrame, config: EstimatorConfig) -> pd.DataFrame:
    if not isinstance(data, pd.DataFrame):
        raise TypeError("data must be a pandas DataFrame")
    frame = data.copy()
    if config.filter_eligible and "analysis_eligible" in frame:
        frame = frame.loc[frame["analysis_eligible"].astype(bool)].copy()
    if frame.empty:
        raise ValueError("no eligible observations remain")
    return frame


def _complete_cases(frame: pd.DataFrame, columns: Sequence[str]) -> pd.DataFrame:
    missing = set(columns).difference(frame.columns)
    if missing:
        raise ValueError(f"estimator data missing columns: {sorted(missing)}")
    result = frame.dropna(subset=list(dict.fromkeys(columns))).copy()
    if result.empty:
        raise ValueError("no complete observations remain")
    return result


def _numeric_vector(frame: pd.DataFrame, column: str) -> np.ndarray:
    try:
        values = frame[column].to_numpy(dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{column!r} must be numeric") from exc
    if not np.isfinite(values).all():
        raise ValueError(f"{column!r} must be finite after complete-case filtering")
    return values


def _covariate_matrix(frame: pd.DataFrame, covariates: Sequence[str]) -> pd.DataFrame:
    if not covariates:
        return pd.DataFrame(index=frame.index)
    missing = set(covariates).difference(frame.columns)
    if missing:
        raise ValueError(f"estimator data missing covariates: {sorted(missing)}")
    matrix = pd.get_dummies(frame[list(covariates)], drop_first=True, dtype=float)
    if not np.isfinite(matrix.to_numpy(dtype=float)).all():
        raise ValueError("covariates must be finite")
    return matrix


def difference_in_means(
    data: pd.DataFrame,
    config: EstimatorConfig | Mapping[str, Any] | None = None,
) -> EstimatorResult:
    """Welch difference in means for a two-level randomized assignment."""

    cfg = _coerce_config("difference_in_means", config, {})
    frame = _complete_cases(_eligible(data, cfg), [cfg.outcome, cfg.treatment])
    outcome = _numeric_vector(frame, cfg.outcome)
    treatment = _numeric_vector(frame, cfg.treatment)
    levels = np.unique(treatment)
    if len(levels) != 2:
        raise ValueError("difference_in_means requires exactly two treatment levels")
    control_level, treated_level = float(levels[0]), float(levels[1])
    treated = outcome[treatment == treated_level]
    control = outcome[treatment == control_level]
    if len(treated) < 2 or len(control) < 2:
        raise ValueError("each treatment arm needs at least two observations")
    estimate = float(treated.mean() - control.mean())
    treated_component = float(treated.var(ddof=1) / len(treated))
    control_component = float(control.var(ddof=1) / len(control))
    variance = treated_component + control_component
    standard_error = float(np.sqrt(variance))
    denominator = (
        treated_component**2 / (len(treated) - 1)
        + control_component**2 / (len(control) - 1)
    )
    degrees_freedom = variance**2 / denominator if denominator > 0 else len(frame) - 2
    if standard_error > 0:
        statistic = estimate / standard_error
    else:
        statistic = 0.0 if estimate == 0 else np.inf
    p_value = float(2.0 * student_t.sf(abs(statistic), degrees_freedom))
    critical = float(student_t.ppf(1.0 - cfg.alpha / 2.0, degrees_freedom))
    return _normal_result(
        method="difference_in_means",
        config=cfg,
        estimate=estimate,
        standard_error=standard_error,
        n_obs=len(frame),
        p_value=p_value,
        critical_value=critical,
        diagnostics={
            "control_level": control_level,
            "treated_level": treated_level,
            "n_control": int(len(control)),
            "n_treated": int(len(treated)),
            "degrees_freedom": float(degrees_freedom),
            "variance_estimator": "Welch",
        },
    )


def _regression_design(
    frame: pd.DataFrame,
    config: EstimatorConfig,
    *,
    treatment_column: str | None = None,
) -> tuple[pd.Series, pd.DataFrame, str]:
    treatment_name = treatment_column or config.treatment
    columns = [config.outcome, treatment_name, *config.covariates]
    clean = _complete_cases(frame, columns)
    y = pd.Series(_numeric_vector(clean, config.outcome), index=clean.index, name=config.outcome)
    treatment = pd.Series(
        _numeric_vector(clean, treatment_name), index=clean.index, name=treatment_name
    )
    if np.isclose(treatment.var(), 0):
        raise ValueError("treatment must vary")
    covariates = _covariate_matrix(clean, config.covariates)
    design = pd.concat([treatment, covariates], axis=1).astype(float)
    design = sm.add_constant(design, has_constant="add")
    full_rank = np.linalg.matrix_rank(design.to_numpy())
    without_treatment_rank = np.linalg.matrix_rank(
        design.drop(columns=treatment_name).to_numpy()
    )
    if full_rank == without_treatment_rank:
        raise ValueError("treatment coefficient is not identified by the design matrix")
    return y, design, treatment_name


def regression_adjustment(
    data: pd.DataFrame,
    config: EstimatorConfig | Mapping[str, Any] | None = None,
) -> EstimatorResult:
    """OLS adjustment with HC1 heteroskedasticity-robust uncertainty."""

    cfg = _coerce_config("regression_adjustment", config, {})
    frame = _eligible(data, cfg)
    y, design, treatment_name = _regression_design(frame, cfg)
    fit = sm.OLS(y, design).fit(cov_type="HC1")
    estimate = float(fit.params[treatment_name])
    standard_error = float(fit.bse[treatment_name])
    interval = fit.conf_int(alpha=cfg.alpha).loc[treatment_name]
    return EstimatorResult(
        method="regression_adjustment",
        target_estimand=cfg.target_estimand,
        estimate=estimate,
        standard_error=standard_error,
        ci_low=float(interval.iloc[0]),
        ci_high=float(interval.iloc[1]),
        p_value=float(fit.pvalues[treatment_name]),
        n_obs=int(fit.nobs),
        outcome=cfg.outcome,
        treatment=treatment_name,
        alpha=cfg.alpha,
        diagnostics={
            "covariates": list(cfg.covariates),
            "variance_estimator": "HC1",
            "r_squared": float(fit.rsquared),
            "design_rank": int(np.linalg.matrix_rank(design.to_numpy())),
        },
    )


def cluster_robust(
    data: pd.DataFrame,
    config: EstimatorConfig | Mapping[str, Any] | None = None,
) -> EstimatorResult:
    """OLS coefficient with small-sample corrected cluster-robust uncertainty."""

    cfg = _coerce_config("cluster_robust", config, {})
    if cfg.cluster is None:
        raise ValueError("cluster_robust requires config.cluster")
    frame = _eligible(data, cfg)
    required = [cfg.outcome, cfg.treatment, cfg.cluster, *cfg.covariates]
    frame = _complete_cases(frame, required)
    y, design, treatment_name = _regression_design(frame, cfg)
    groups = frame.loc[y.index, cfg.cluster]
    n_clusters = int(groups.nunique())
    if n_clusters < 2:
        raise ValueError("cluster-robust inference requires at least two clusters")
    fit = sm.OLS(y, design).fit(
        cov_type="cluster",
        cov_kwds={"groups": groups, "use_correction": True},
        use_t=True,
    )
    estimate = float(fit.params[treatment_name])
    standard_error = float(fit.bse[treatment_name])
    critical = float(student_t.ppf(1.0 - cfg.alpha / 2.0, n_clusters - 1))
    statistic = (
        estimate / standard_error
        if standard_error > 0
        else (0.0 if estimate == 0 else np.inf)
    )
    p_value = float(2.0 * student_t.sf(abs(statistic), n_clusters - 1))
    return _normal_result(
        method="cluster_robust",
        config=cfg,
        estimate=estimate,
        standard_error=standard_error,
        n_obs=int(fit.nobs),
        p_value=p_value,
        critical_value=critical,
        diagnostics={
            "cluster_column": cfg.cluster,
            "n_clusters": n_clusters,
            "covariates": list(cfg.covariates),
            "variance_estimator": "CR1",
            "degrees_freedom": n_clusters - 1,
        },
    )


def two_way_cluster_robust(
    data: pd.DataFrame,
    config: EstimatorConfig | Mapping[str, Any] | None = None,
) -> EstimatorResult:
    """OLS coefficient with geographic × temporal two-way clustered uncertainty.

    ``config.cluster`` names the geographic/randomization grouping and ``config.time``
    names the temporal grouping. The covariance uses the Cameron-Gelbach-Miller
    inclusion-exclusion form implemented by statsmodels. A t reference distribution
    with ``min(G_geo, G_time) - 1`` degrees of freedom is deliberately conservative.
    """

    cfg = _coerce_config("two_way_cluster_robust", config, {})
    if cfg.cluster is None or cfg.time is None:
        raise ValueError(
            "two_way_cluster_robust requires config.cluster and config.time"
        )
    frame = _eligible(data, cfg)
    required = [cfg.outcome, cfg.treatment, cfg.cluster, cfg.time, *cfg.covariates]
    frame = _complete_cases(frame, required)
    y, design, treatment_name = _regression_design(frame, cfg)
    geo_groups = frame.loc[y.index, cfg.cluster]
    time_groups = frame.loc[y.index, cfg.time]
    n_geo_clusters = int(geo_groups.nunique())
    n_time_clusters = int(time_groups.nunique())
    if min(n_geo_clusters, n_time_clusters) < 2:
        raise ValueError("two-way clustered inference requires at least two groups per dimension")
    fit = sm.OLS(y, design).fit()
    covariance, _, _ = cov_cluster_2groups(
        fit,
        geo_groups,
        time_groups,
        use_correction=True,
    )
    coefficient_index = int(design.columns.get_loc(treatment_name))
    variance = float(covariance[coefficient_index, coefficient_index])
    if not np.isfinite(variance) or variance < 0:
        raise ValueError("two-way clustered treatment variance is negative or non-finite")
    estimate = float(fit.params[treatment_name])
    standard_error = float(np.sqrt(variance))
    degrees_freedom = min(n_geo_clusters, n_time_clusters) - 1
    statistic = (
        estimate / standard_error
        if standard_error > 0
        else (0.0 if estimate == 0 else np.inf)
    )
    p_value = float(2.0 * student_t.sf(abs(statistic), degrees_freedom))
    critical = float(student_t.ppf(1.0 - cfg.alpha / 2.0, degrees_freedom))
    return _normal_result(
        method="two_way_cluster_robust",
        config=cfg,
        estimate=estimate,
        standard_error=standard_error,
        n_obs=int(fit.nobs),
        p_value=p_value,
        critical_value=critical,
        diagnostics={
            "geographic_cluster_column": cfg.cluster,
            "time_cluster_column": cfg.time,
            "n_geographic_clusters": n_geo_clusters,
            "n_time_clusters": n_time_clusters,
            "covariates": list(cfg.covariates),
            "variance_estimator": "two-way cluster CR1 inclusion-exclusion",
            "degrees_freedom": degrees_freedom,
            "inference_warning": (
                "few groups require randomization or small-sample sensitivity analysis"
                if min(n_geo_clusters, n_time_clusters) < 8
                else None
            ),
        },
    )


def _infer_column(
    frame: pd.DataFrame,
    explicit: str | None,
    candidates: Sequence[str],
    role: str,
) -> str:
    if explicit is not None:
        if explicit not in frame:
            raise ValueError(f"{role} column {explicit!r} not found")
        return explicit
    for candidate in candidates:
        if candidate in frame:
            return candidate
    raise ValueError(f"could not infer {role} column; set it in EstimatorConfig")


def difference_in_differences(
    data: pd.DataFrame,
    config: EstimatorConfig | Mapping[str, Any] | None = None,
) -> EstimatorResult:
    """Two-way fixed-effects DiD for a supplied or inferred active treatment.

    If ``config.post`` is supplied, ``config.treatment`` is interpreted as treated
    group membership and their interaction is the coefficient of interest. Without
    ``post``, the treatment column must itself be the active treatment indicator.
    """

    cfg = _coerce_config("difference_in_differences", config, {})
    frame = _eligible(data, cfg)
    unit = _infer_column(frame, cfg.unit, ("zone_id", "unit_id", "cluster_id"), "unit")
    time = _infer_column(frame, cfg.time, ("period_id", "time", "date"), "time")
    required = [cfg.outcome, cfg.treatment, unit, time, *cfg.covariates]
    if cfg.post is not None:
        required.append(cfg.post)
    frame = _complete_cases(frame, required)
    treatment_name = "_did_treatment"
    if cfg.post is not None:
        frame[treatment_name] = (
            _numeric_vector(frame, cfg.treatment) * _numeric_vector(frame, cfg.post)
        )
    else:
        frame[treatment_name] = _numeric_vector(frame, cfg.treatment)
        within_variation = frame.groupby(unit, observed=True)[treatment_name].nunique()
        if int((within_variation > 1).sum()) == 0:
            raise ValueError("DiD treatment must vary within unit or config.post must be supplied")

    y = pd.Series(_numeric_vector(frame, cfg.outcome), index=frame.index)
    active = pd.Series(
        frame[treatment_name].to_numpy(dtype=float), index=frame.index, name=treatment_name
    )
    covariates = _covariate_matrix(frame, cfg.covariates)
    unit_dummies = pd.get_dummies(
        frame[unit].astype("category"), prefix="unit", drop_first=True, dtype=float
    )
    time_dummies = pd.get_dummies(
        frame[time].astype("category"), prefix="time", drop_first=True, dtype=float
    )
    design = pd.concat([active, covariates, unit_dummies, time_dummies], axis=1)
    design = sm.add_constant(design.astype(float), has_constant="add")
    if np.linalg.matrix_rank(design.to_numpy()) == np.linalg.matrix_rank(
        design.drop(columns=treatment_name).to_numpy()
    ):
        raise ValueError("DiD treatment contrast is collinear with fixed effects")
    groups = frame[unit]
    n_clusters = int(groups.nunique())
    if n_clusters < 2:
        raise ValueError("DiD requires at least two panel units")
    fit = sm.OLS(y, design).fit(
        cov_type="cluster",
        cov_kwds={"groups": groups, "use_correction": True},
        use_t=True,
    )
    estimate = float(fit.params[treatment_name])
    standard_error = float(fit.bse[treatment_name])
    critical = float(student_t.ppf(1.0 - cfg.alpha / 2.0, n_clusters - 1))
    statistic = estimate / standard_error if standard_error > 0 else (0.0 if estimate == 0 else np.inf)
    p_value = float(2.0 * student_t.sf(abs(statistic), n_clusters - 1))
    return _normal_result(
        method="difference_in_differences",
        config=cfg,
        estimate=estimate,
        standard_error=standard_error,
        n_obs=int(fit.nobs),
        p_value=p_value,
        critical_value=critical,
        treatment=treatment_name,
        diagnostics={
            "unit_column": unit,
            "time_column": time,
            "post_column": cfg.post,
            "n_units": n_clusters,
            "variance_estimator": "unit-clustered CR1",
            "parallel_trends_required": True,
        },
    )


def _binary_treatment(values: np.ndarray) -> tuple[np.ndarray, tuple[float, float]]:
    levels = np.unique(values)
    if len(levels) != 2:
        raise ValueError("this estimator requires exactly two treatment levels")
    low, high = float(levels[0]), float(levels[1])
    return (values == high).astype(int), (low, high)


def _influence_standard_error(
    scores: np.ndarray,
    clusters: pd.Series | np.ndarray | None,
) -> tuple[float, dict[str, Any]]:
    centered = scores - scores.mean()
    n_obs = len(scores)
    if clusters is None:
        return float(scores.std(ddof=1) / np.sqrt(n_obs)), {
            "variance_estimator": "influence_iid"
        }
    labels = pd.Series(np.asarray(clusters)).reset_index(drop=True)
    unique = labels.unique()
    if len(unique) < 2:
        raise ValueError("clustered influence-function inference needs at least two clusters")
    label_values = labels.to_numpy()
    sums = np.asarray([centered[label_values == label].sum() for label in unique])
    variance = len(unique) / (len(unique) - 1) * float(np.sum(sums**2)) / n_obs**2
    return float(np.sqrt(variance)), {
        "variance_estimator": "clustered_influence_function",
        "n_clusters": int(len(unique)),
    }


def _nuisance_splits(
    frame: pd.DataFrame,
    treatment: np.ndarray,
    config: EstimatorConfig,
) -> tuple[list[tuple[np.ndarray, np.ndarray]], dict[str, Any]]:
    """Construct honest row- or group-level nuisance folds."""

    if config.cluster is None:
        group_counts = np.bincount(treatment, minlength=2)
        n_splits = min(config.crossfit_folds, int(group_counts.min()))
        if n_splits < 2:
            raise ValueError("doubly robust estimation needs at least two observations per arm")
        splitter = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=config.seed)
        splits = list(splitter.split(np.zeros((len(frame), 1)), treatment))
        return splits, {
            "crossfit_folds": n_splits,
            "crossfit_unit": "row",
            "group_leakage_prevented": False,
        }

    groups = frame[config.cluster].to_numpy()
    n_groups = int(pd.Series(groups).nunique())
    for n_splits in range(min(config.crossfit_folds, n_groups), 1, -1):
        splitter = StratifiedGroupKFold(
            n_splits=n_splits,
            shuffle=True,
            random_state=config.seed,
        )
        candidate = list(
            splitter.split(np.zeros((len(frame), 1)), treatment, groups=groups)
        )
        if all(np.unique(treatment[train]).size == 2 for train, _ in candidate):
            for train, test in candidate:
                if np.intersect1d(groups[train], groups[test]).size:
                    raise AssertionError("group-aware cross-fitting leaked a cluster")
            return candidate, {
                "crossfit_folds": n_splits,
                "crossfit_unit": config.cluster,
                "crossfit_groups": n_groups,
                "group_leakage_prevented": True,
            }
    raise ValueError(
        "cluster-aware doubly robust estimation needs enough clusters in both arms"
    )


def doubly_robust(
    data: pd.DataFrame,
    config: EstimatorConfig | Mapping[str, Any] | None = None,
) -> EstimatorResult:
    """Cross-fitted augmented inverse-probability weighted ATE."""

    cfg = _coerce_config("doubly_robust", config, {})
    frame = _eligible(data, cfg)
    required = [cfg.outcome, cfg.treatment, *cfg.covariates]
    if cfg.propensity is not None:
        required.append(cfg.propensity)
    if cfg.cluster is not None:
        required.append(cfg.cluster)
    frame = _complete_cases(frame, required).reset_index(drop=True)
    y = _numeric_vector(frame, cfg.outcome)
    raw_treatment = _numeric_vector(frame, cfg.treatment)
    treatment, levels = _binary_treatment(raw_treatment)
    matrix = _covariate_matrix(frame, cfg.covariates)
    x = matrix.to_numpy(dtype=float) if len(matrix.columns) else np.zeros((len(frame), 1))
    mu0 = np.empty(len(frame), dtype=float)
    mu1 = np.empty(len(frame), dtype=float)
    propensity = np.empty(len(frame), dtype=float)
    splits, split_diagnostics = _nuisance_splits(frame, treatment, cfg)
    supplied_propensity = (
        _numeric_vector(frame, cfg.propensity) if cfg.propensity is not None else None
    )
    if supplied_propensity is not None and (
        (supplied_propensity <= 0).any() or (supplied_propensity >= 1).any()
    ):
        raise ValueError("supplied propensity scores must lie strictly inside (0, 1)")
    for train, test in splits:
        train_control = train[treatment[train] == 0]
        train_treated = train[treatment[train] == 1]
        outcome0 = LinearRegression().fit(x[train_control], y[train_control])
        outcome1 = LinearRegression().fit(x[train_treated], y[train_treated])
        mu0[test] = outcome0.predict(x[test])
        mu1[test] = outcome1.predict(x[test])
        if supplied_propensity is None:
            propensity_model = make_pipeline(
                StandardScaler(),
                LogisticRegression(max_iter=2_000, random_state=cfg.seed, C=1.0),
            )
            propensity_model.fit(x[train], treatment[train])
            propensity[test] = propensity_model.predict_proba(x[test])[:, 1]
        else:
            propensity[test] = supplied_propensity[test]
    unclipped_propensity = propensity.copy()
    propensity = np.clip(propensity, 0.02, 0.98)
    scores = (
        mu1
        - mu0
        + treatment * (y - mu1) / propensity
        - (1 - treatment) * (y - mu0) / (1.0 - propensity)
    )
    estimate = float(scores.mean())
    clusters = frame[cfg.cluster] if cfg.cluster is not None else None
    standard_error, variance_diagnostics = _influence_standard_error(scores, clusters)
    diagnostics: dict[str, Any] = {
        "covariates": list(cfg.covariates),
        **split_diagnostics,
        "control_level": levels[0],
        "treated_level": levels[1],
        "propensity_min_unclipped": float(unclipped_propensity.min()),
        "propensity_max_unclipped": float(unclipped_propensity.max()),
        "propensity_clip": [0.02, 0.98],
        "estimating_equation": "AIPW",
        **variance_diagnostics,
    }
    p_value: float | None = None
    critical_value: float | None = None
    if cfg.cluster is not None:
        n_clusters = int(variance_diagnostics["n_clusters"])
        degrees_freedom = n_clusters - 1
        critical_value = float(student_t.ppf(1.0 - cfg.alpha / 2.0, degrees_freedom))
        statistic = (
            estimate / standard_error
            if standard_error > 0
            else (0.0 if estimate == 0 else np.inf)
        )
        p_value = float(2.0 * student_t.sf(abs(statistic), degrees_freedom))
        diagnostics["degrees_freedom"] = degrees_freedom
        diagnostics["reference_distribution"] = "cluster_t"
    else:
        diagnostics["reference_distribution"] = "normal"
    return _normal_result(
        method="doubly_robust",
        config=cfg,
        estimate=estimate,
        standard_error=standard_error,
        n_obs=len(frame),
        p_value=p_value,
        critical_value=critical_value,
        diagnostics=diagnostics,
    )


def synthetic_control(
    data: pd.DataFrame,
    config: EstimatorConfig | Mapping[str, Any] | None = None,
) -> EstimatorResult:
    """Nonnegative donor-weight synthetic-control-style post-period contrast.

    The interval uses pre-treatment fit residuals as a diagnostic approximation; it
    is not presented as randomization inference. The result records this limitation.
    """

    cfg = _coerce_config("synthetic_control", config, {})
    frame = _eligible(data, cfg)
    unit = _infer_column(frame, cfg.unit, ("zone_id", "unit_id", "cluster_id"), "unit")
    time = _infer_column(frame, cfg.time, ("period_id", "time", "date"), "time")
    required = [cfg.outcome, cfg.treatment, unit, time]
    if cfg.post is not None:
        required.append(cfg.post)
    frame = _complete_cases(frame, required)
    treatment_by_unit = frame.groupby(unit, observed=True)[cfg.treatment].max()
    treated_units = treatment_by_unit[treatment_by_unit > 0].index.tolist()
    donor_units = treatment_by_unit[treatment_by_unit <= 0].index.tolist()
    if not treated_units or not donor_units:
        raise ValueError("synthetic control requires treated units and never-treated donors")

    treated_rows = frame[frame[unit].isin(treated_units)]
    if cfg.post is not None:
        post_mask = _numeric_vector(frame, cfg.post) > 0
        post_times = set(frame.loc[post_mask, time].tolist())
        pre_times = set(frame[time].tolist()).difference(post_times)
    else:
        active = treated_rows.loc[treated_rows[cfg.treatment] > 0, time]
        if active.empty:
            raise ValueError("could not infer a treatment onset")
        onset = active.min()
        pre_times = {value for value in frame[time].unique() if value < onset}
        post_times = {value for value in frame[time].unique() if value >= onset}
    if len(pre_times) < 2 or not post_times:
        raise ValueError("synthetic control requires at least two pre periods and one post period")

    outcome_panel = frame.pivot_table(
        index=time, columns=unit, values=cfg.outcome, aggfunc="mean"
    )
    treated_series = outcome_panel[treated_units].mean(axis=1)
    donor_panel = outcome_panel[donor_units]
    valid_times = outcome_panel.index[treated_series.notna() & donor_panel.notna().all(axis=1)]
    ordered_pre = [value for value in valid_times if value in pre_times]
    ordered_post = [value for value in valid_times if value in post_times]
    if len(ordered_pre) < 2 or not ordered_post:
        raise ValueError("insufficient complete pre/post donor outcomes")
    x_pre = donor_panel.loc[ordered_pre].to_numpy(dtype=float)
    y_pre = treated_series.loc[ordered_pre].to_numpy(dtype=float)
    initial_weights = np.full(len(donor_units), 1.0 / len(donor_units))
    optimization = minimize(
        lambda weights: float(np.mean(np.square(y_pre - x_pre @ weights))),
        initial_weights,
        method="SLSQP",
        bounds=[(0.0, 1.0)] * len(donor_units),
        constraints={"type": "eq", "fun": lambda weights: float(weights.sum() - 1.0)},
    )
    if optimization.success and np.isfinite(optimization.x).all():
        weights = np.clip(optimization.x, 0.0, 1.0)
        weights = weights / weights.sum()
    else:
        # A deterministic single best donor is a transparent fallback when the
        # constrained optimizer cannot converge.
        donor_mse = np.mean(np.square(x_pre - y_pre[:, None]), axis=0)
        weights = np.zeros(len(donor_units), dtype=float)
        weights[int(np.argmin(donor_mse))] = 1.0
    synthetic_values = donor_panel.to_numpy(dtype=float) @ weights
    synthetic_series = pd.Series(synthetic_values, index=donor_panel.index)
    pre_gap = treated_series.loc[ordered_pre] - synthetic_series.loc[ordered_pre]
    post_gap = treated_series.loc[ordered_post] - synthetic_series.loc[ordered_post]
    estimate = float(post_gap.mean())
    pre_rmspe = float(np.sqrt(np.mean(np.square(pre_gap))))
    standard_error = float(pre_gap.std(ddof=1) / np.sqrt(len(ordered_post)))
    return _normal_result(
        method="synthetic_control",
        config=cfg,
        estimate=estimate,
        standard_error=standard_error,
        n_obs=len(frame),
        diagnostics={
            "unit_column": unit,
            "time_column": time,
            "treated_units": [str(value) for value in treated_units],
            "donor_weights": {
                str(donor): float(weight)
                for donor, weight in zip(donor_units, weights, strict=True)
            },
            "n_pre_periods": len(ordered_pre),
            "n_post_periods": len(ordered_post),
            "pre_rmspe": pre_rmspe,
            "weight_optimizer_converged": bool(optimization.success),
            "uncertainty_warning": (
                "pre-fit residual approximation; use placebo or randomization inference "
                "for decisions"
            ),
        },
    )


_ESTIMATORS: dict[str, Callable[[pd.DataFrame, EstimatorConfig], EstimatorResult]] = {
    "difference_in_means": difference_in_means,
    "regression_adjustment": regression_adjustment,
    "cluster_robust": cluster_robust,
    "two_way_cluster_robust": two_way_cluster_robust,
    "difference_in_differences": difference_in_differences,
    "doubly_robust": doubly_robust,
    "synthetic_control": synthetic_control,
}


def estimate_effect(
    data: pd.DataFrame,
    method: str | EstimatorConfig | None = None,
    config: EstimatorConfig | Mapping[str, Any] | None = None,
    **overrides: Any,
) -> EstimatorResult:
    """Dispatch to a named estimator and return the shared scalar result type."""

    cfg = _coerce_config(method, config, overrides)
    try:
        estimator = _ESTIMATORS[cfg.method]
    except KeyError as exc:
        choices = ", ".join(sorted(_ESTIMATORS))
        raise ValueError(f"unknown estimator {cfg.method!r}; choose one of: {choices}") from exc
    return estimator(data, cfg)


def estimate_ladder(
    data: pd.DataFrame,
    methods: Sequence[str] | None = None,
    config: EstimatorConfig | Mapping[str, Any] | None = None,
    *,
    on_error: str = "record",
    **overrides: Any,
) -> pd.DataFrame:
    """Run comparable estimators, recording inapplicable-method diagnostics.

    ``on_error='raise'`` is useful in tests; ``'record'`` keeps a benchmark table
    rectangular when, for example, a design has no pre-period for synthetic control.
    """

    if on_error not in {"record", "raise"}:
        raise ValueError("on_error must be 'record' or 'raise'")
    selected = list(methods or _ESTIMATORS)
    rows: list[dict[str, Any]] = []
    for method_name in selected:
        try:
            result = estimate_effect(data, method_name, config, **overrides)
            row = result.to_dict()
            row["status"] = "ok"
            rows.append(row)
        except (ValueError, np.linalg.LinAlgError) as exc:
            if on_error == "raise":
                raise
            cfg = _coerce_config(method_name, config, overrides)
            rows.append(
                {
                    "method": cfg.method,
                    "target_estimand": cfg.target_estimand,
                    "estimate": np.nan,
                    "standard_error": np.nan,
                    "se": np.nan,
                    "ci_low": np.nan,
                    "ci_high": np.nan,
                    "p_value": np.nan,
                    "n_obs": 0,
                    "outcome": cfg.outcome,
                    "treatment": cfg.treatment,
                    "alpha": cfg.alpha,
                    "diagnostics": {"error": str(exc)},
                    "status": "not_applicable",
                }
            )
    return pd.DataFrame(rows)


def estimate_heterogeneous_effects(
    data: pd.DataFrame,
    covariates: Sequence[str],
    *,
    outcome: str = "outcome",
    treatment: str = "assigned_treatment",
    folds: int = 3,
    seed: int = 202503,
) -> pd.DataFrame:
    """Cross-fitted linear T-learner benchmark for unit-level heterogeneity.

    The learner is intentionally simple. Its predictions are exploratory unless
    treatment is randomized or unconfounded conditional on the supplied covariates.
    """

    if folds < 2:
        raise ValueError("folds must be at least 2")
    columns = [outcome, treatment, *covariates]
    frame = _complete_cases(data, columns).copy()
    frame["_original_index"] = frame.index
    frame = frame.reset_index(drop=True)
    y = _numeric_vector(frame, outcome)
    raw_treatment = _numeric_vector(frame, treatment)
    assigned, levels = _binary_treatment(raw_treatment)
    matrix = _covariate_matrix(frame, covariates)
    x = matrix.to_numpy(dtype=float) if len(matrix.columns) else np.zeros((len(frame), 1))
    counts = np.bincount(assigned, minlength=2)
    n_splits = min(folds, int(counts.min()))
    if n_splits < 2:
        raise ValueError("T-learner needs at least two observations per arm")
    mu0 = np.empty(len(frame), dtype=float)
    mu1 = np.empty(len(frame), dtype=float)
    splitter = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=seed)
    for train, test in splitter.split(x, assigned):
        train_control = train[assigned[train] == 0]
        train_treated = train[assigned[train] == 1]
        model0 = LinearRegression().fit(x[train_control], y[train_control])
        model1 = LinearRegression().fit(x[train_treated], y[train_treated])
        mu0[test] = model0.predict(x[test])
        mu1[test] = model1.predict(x[test])
    return pd.DataFrame(
        {
            "row_index": frame["_original_index"].to_numpy(),
            "predicted_y0": mu0,
            "predicted_y1": mu1,
            "estimated_treatment_effect": mu1 - mu0,
            "control_level": levels[0],
            "treated_level": levels[1],
            "method": "cross_fitted_linear_t_learner",
            "evidence_type": "model_based_heterogeneity_conditional_on_identification",
        }
    )


estimate = estimate_effect
estimate_hte = estimate_heterogeneous_effects
