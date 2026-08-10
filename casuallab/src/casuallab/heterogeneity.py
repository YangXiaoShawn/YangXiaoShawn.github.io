"""Transparent heterogeneous-effect summaries and a cross-fitted S-learner."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import GroupKFold, KFold

DEFAULT_HTE_FEATURES = (
    "baseline_demand",
    "market_tightness",
    "hour_sin",
    "hour_cos",
)


@dataclass(frozen=True)
class HTEResult:
    predictions: pd.DataFrame
    feature_importance: pd.DataFrame
    method: str
    evidence_type: str = "model_based_conditional_contrast"


def cross_fitted_s_learner(
    data: pd.DataFrame,
    *,
    outcome: str = "outcome",
    treatment: str = "assigned_treatment",
    features: Sequence[str] = DEFAULT_HTE_FEATURES,
    group: str | None = None,
    folds: int = 5,
    trees: int = 160,
    min_samples_leaf: int = 10,
    seed: int = 202503,
    evidence_type: str = "model_based_conditional_contrast",
) -> HTEResult:
    """Estimate conditional contrasts with honest cross-fitted predictions.

    This benchmark follows simpler aggregate estimators in the method ladder. It is
    not used as evidence that a causal forest is necessary or superior. If a cluster
    column is supplied, entire clusters are held out together.
    """

    required = {outcome, treatment, *features}
    if group is not None:
        required.add(group)
    missing = required.difference(data.columns)
    if missing:
        raise ValueError(f"HTE data missing columns: {sorted(missing)}")
    if len(data) < 2 * folds:
        raise ValueError("HTE data need at least two rows per fold")
    if folds < 2:
        raise ValueError("folds must be at least 2")
    if trees < 10:
        raise ValueError("trees must be at least 10")

    frame = data.reset_index(drop=True).copy()
    numeric_columns = [outcome, treatment, *features]
    numeric = frame[numeric_columns].apply(pd.to_numeric, errors="coerce")
    if not np.isfinite(numeric.to_numpy(dtype=float)).all():
        raise ValueError("HTE outcome, treatment, and features must be finite")
    treatment_values = numeric[treatment].to_numpy(dtype=float)
    if ((treatment_values < 0) | (treatment_values > 1)).any():
        raise ValueError("treatment must lie in [0, 1]")
    if np.ptp(treatment_values) <= 1e-12:
        raise ValueError("treatment must vary")

    if group is None:
        splitter = KFold(n_splits=folds, shuffle=True, random_state=seed)
        splits = splitter.split(frame)
    else:
        unique_groups = frame[group].nunique()
        if unique_groups < folds:
            raise ValueError("number of cross-fitting groups must be at least folds")
        splitter = GroupKFold(n_splits=folds)
        splits = splitter.split(frame, groups=frame[group])

    cate = np.full(len(frame), np.nan, dtype=float)
    y1 = np.full(len(frame), np.nan, dtype=float)
    y0 = np.full(len(frame), np.nan, dtype=float)
    fold_id = np.full(len(frame), -1, dtype=int)
    importances: list[np.ndarray] = []
    model_columns = [*features, treatment]
    for fold, (train_indices, test_indices) in enumerate(splits):
        train = numeric.iloc[train_indices]
        test = numeric.iloc[test_indices]
        if np.ptp(train[treatment].to_numpy(dtype=float)) <= 1e-12:
            raise ValueError(f"treatment does not vary in training fold {fold}")
        model = RandomForestRegressor(
            n_estimators=trees,
            min_samples_leaf=min_samples_leaf,
            max_depth=8,
            max_features="sqrt",
            random_state=seed + fold,
            n_jobs=1,
        )
        model.fit(train[model_columns], train[outcome])
        treated_features = test[model_columns].copy()
        control_features = test[model_columns].copy()
        treated_features[treatment] = 1.0
        control_features[treatment] = 0.0
        y1[test_indices] = model.predict(treated_features)
        y0[test_indices] = model.predict(control_features)
        cate[test_indices] = y1[test_indices] - y0[test_indices]
        fold_id[test_indices] = fold
        importances.append(model.feature_importances_)

    if not np.isfinite(cate).all() or (fold_id < 0).any():
        raise AssertionError("cross-fitting did not produce every holdout prediction")
    predictions = frame[[column for column in ("unit_id", "zone_id", "period_id") if column in frame]].copy()
    predictions["predicted_y1"] = y1
    predictions["predicted_y0"] = y0
    predictions["estimated_cate"] = cate
    predictions["crossfit_fold"] = fold_id
    predictions["evidence_type"] = evidence_type
    importance = pd.DataFrame(
        {
            "feature": model_columns,
            "mean_importance": np.vstack(importances).mean(axis=0),
            "importance_sd_across_folds": np.vstack(importances).std(axis=0, ddof=1),
            "evidence_type": "model_diagnostic",
        }
    ).sort_values("mean_importance", ascending=False, ignore_index=True)
    return HTEResult(
        predictions,
        importance,
        method="cross_fitted_random_forest_s_learner",
        evidence_type=evidence_type,
    )


def subgroup_effect_summary(
    data: pd.DataFrame,
    estimated_cate: Sequence[float] | pd.Series,
    *,
    modifier: str,
    bins: int = 4,
) -> pd.DataFrame:
    """Summarize predicted heterogeneity across pre-treatment modifier bins."""

    if modifier not in data:
        raise ValueError(f"modifier {modifier!r} is missing")
    if bins < 2:
        raise ValueError("bins must be at least 2")
    values = pd.to_numeric(data[modifier], errors="coerce")
    cate = np.asarray(estimated_cate, dtype=float)
    if len(cate) != len(data):
        raise ValueError("estimated_cate must align with data")
    if not np.isfinite(cate).all():
        raise ValueError("estimated_cate must be finite")
    valid = values.notna()
    if valid.sum() < bins:
        raise ValueError("too few observed modifier values for requested bins")
    labels = pd.qcut(values.loc[valid], q=bins, duplicates="drop")
    summary = (
        pd.DataFrame({"modifier_bin": labels, "estimated_cate": cate[valid.to_numpy()]})
        .groupby("modifier_bin", observed=True)["estimated_cate"]
        .agg(mean_estimated_cate="mean", sd_estimated_cate="std", rows="size")
        .reset_index()
    )
    summary.insert(0, "modifier", modifier)
    summary["modifier_bin"] = summary["modifier_bin"].astype(str)
    summary["evidence_type"] = "model_based_conditional_contrast_summary"
    return summary
