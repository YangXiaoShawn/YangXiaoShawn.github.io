"""High-dimensional fixed-effects absorption, OLS and Poisson pseudo-ML.

Trade panels need many fixed effects (product-country, product-time,
country-time) whose dummy expansion is far larger than the data. Both estimators
here absorb fixed effects by **alternating projections** (iteratively demeaning
within each effect until convergence) rather than by materialising dummies, so
memory stays proportional to the number of observations.

``ppml_hdfe`` implements Poisson pseudo-maximum-likelihood by iteratively
reweighted least squares, with the fixed effects absorbed inside each IRLS step
using the current Poisson weights. PPML is the right estimator for trade flows:
it is consistent under heteroskedasticity in levels and, unlike log-linear OLS,
it uses observations with zero trade — which is exactly where the extensive
margin of tariff-driven sourcing changes lives.

Inference is cluster-robust (one-way or multi-way via the
inclusion-exclusion/Cameron-Gelbach-Miller formula). Clusters are chosen by the
caller; the default in this project is the product, because treatment is
assigned at the product level and that is the level at which the errors are
plausibly correlated.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy import stats


@dataclass(slots=True)
class FitResult:
    """Estimation output with everything needed to report it honestly."""

    params: dict[str, float]
    std_errors: dict[str, float]
    n_obs: int
    n_params: int
    estimator: str
    cluster_vars: list[str]
    n_clusters: dict[str, int]
    converged: bool
    iterations: int
    absorbed_effects: list[str]
    dof_resid: int
    pseudo_r2: float | None = None
    notes: list[str] = field(default_factory=list)

    def tstat(self, name: str) -> float:
        se = self.std_errors[name]
        return float("nan") if se == 0 else self.params[name] / se

    def pvalue(self, name: str) -> float:
        df = max(min(self.n_clusters.values()) - 1, 1) if self.n_clusters else self.dof_resid
        return float(2 * stats.t.sf(abs(self.tstat(name)), df))

    def conf_int(self, name: str, level: float = 0.95) -> tuple[float, float]:
        df = max(min(self.n_clusters.values()) - 1, 1) if self.n_clusters else self.dof_resid
        crit = float(stats.t.ppf(0.5 + level / 2, df))
        b, se = self.params[name], self.std_errors[name]
        return b - crit * se, b + crit * se

    def to_rows(self, level: float = 0.95) -> list[dict]:
        rows = []
        for k in self.params:
            lo, hi = self.conf_int(k, level)
            rows.append(
                {
                    "term": k,
                    "estimate": self.params[k],
                    "std_error": self.std_errors[k],
                    "t_stat": self.tstat(k),
                    "p_value": self.pvalue(k),
                    "ci_low": lo,
                    "ci_high": hi,
                    "estimator": self.estimator,
                    "n_obs": self.n_obs,
                    "absorbed_effects": "|".join(self.absorbed_effects),
                    "cluster_vars": "|".join(self.cluster_vars),
                    "n_clusters_min": min(self.n_clusters.values()) if self.n_clusters else None,
                }
            )
        return rows


def _factorize(values: np.ndarray) -> np.ndarray:
    """Map arbitrary group labels to contiguous integer codes."""
    _, codes = np.unique(values, return_inverse=True)
    return codes.astype(np.int64)


def absorb(
    M: np.ndarray,
    groups: list[np.ndarray],
    weights: np.ndarray | None = None,
    tol: float = 1e-10,
    max_iter: int = 400,
) -> tuple[np.ndarray, int, bool]:
    """Demean columns of ``M`` within every fixed effect by alternating projections.

    With one effect this converges in a single pass. With two or more it is the
    Gauss-Seidel iteration underlying ``reghdfe``/``ppmlhdfe``.
    """
    if not groups:
        return M.copy(), 0, True

    X = np.asarray(M, dtype=np.float64).copy()
    if X.ndim == 1:
        X = X[:, None]
    n = X.shape[0]
    w = np.ones(n) if weights is None else np.asarray(weights, dtype=np.float64)

    codes = [_factorize(g) for g in groups]
    sums_w = [np.bincount(c, weights=w) for c in codes]
    for s in sums_w:
        s[s == 0] = 1.0

    prev = X.copy()
    for it in range(1, max_iter + 1):
        for c, sw in zip(codes, sums_w, strict=True):
            for j in range(X.shape[1]):
                num = np.bincount(c, weights=w * X[:, j], minlength=sw.size)
                X[:, j] -= (num / sw)[c]
        delta = np.max(np.abs(X - prev))
        scale = max(np.max(np.abs(X)), 1.0)
        if delta / scale < tol:
            return X, it, True
        prev = X.copy()
    return X, max_iter, False


def _cluster_meat(X: np.ndarray, resid_score: np.ndarray, cluster: np.ndarray) -> np.ndarray:
    codes = _factorize(cluster)
    k = X.shape[1]
    meat = np.zeros((k, k))
    u = X * resid_score[:, None]
    for g in range(codes.max() + 1):
        sel = codes == g
        if not sel.any():
            continue
        s = u[sel].sum(axis=0)
        meat += np.outer(s, s)
    return meat


def _multiway_meat(
    X: np.ndarray, score: np.ndarray, clusters: dict[str, np.ndarray]
) -> np.ndarray:
    """Cameron-Gelbach-Miller multi-way cluster variance meat matrix."""
    names = list(clusters)
    if len(names) == 1:
        return _cluster_meat(X, score, clusters[names[0]])
    meat = np.zeros((X.shape[1], X.shape[1]))
    # Inclusion-exclusion over non-empty subsets.
    from itertools import combinations

    for r in range(1, len(names) + 1):
        sign = (-1) ** (r + 1)
        for combo in combinations(names, r):
            joint = np.array(
                ["\x1f".join(str(clusters[c][i]) for c in combo) for i in range(X.shape[0])]
            )
            meat += sign * _cluster_meat(X, score, joint)
    return meat


def ols_hdfe(
    y: np.ndarray,
    X: np.ndarray,
    names: list[str],
    fe_groups: dict[str, np.ndarray],
    clusters: dict[str, np.ndarray],
    weights: np.ndarray | None = None,
) -> FitResult:
    """Weighted OLS with absorbed fixed effects and cluster-robust inference."""
    y = np.asarray(y, dtype=np.float64).ravel()
    X = np.asarray(X, dtype=np.float64)
    n = y.size
    w = np.ones(n) if weights is None else np.asarray(weights, dtype=np.float64)

    fe_list = list(fe_groups.values())
    yt, it_y, ok_y = absorb(y[:, None], fe_list, w)
    Xt, it_x, ok_x = absorb(X, fe_list, w)
    yt = yt.ravel()

    sw = np.sqrt(w)
    Xw, yw = Xt * sw[:, None], yt * sw
    XtX = Xw.T @ Xw
    XtX_inv = np.linalg.pinv(XtX)
    beta = XtX_inv @ (Xw.T @ yw)
    resid = yt - Xt @ beta

    n_fe_params = sum(len(np.unique(g)) for g in fe_list)
    # Each additional absorbed effect after the first shares the intercept.
    n_fe_params -= max(len(fe_list) - 1, 0)
    dof = max(n - X.shape[1] - n_fe_params, 1)

    score = w * resid
    meat = _multiway_meat(Xt, score, clusters) if clusters else np.diag(
        (Xt * (score**2)[:, None]).sum(axis=0)
    )
    G = min(len(np.unique(v)) for v in clusters.values()) if clusters else n
    adj = (G / max(G - 1, 1)) * ((n - 1) / dof)
    V = XtX_inv @ meat @ XtX_inv * adj
    se = np.sqrt(np.clip(np.diag(V), 0, None))

    tss = float(np.sum(w * (yt - np.average(yt, weights=w)) ** 2))
    rss = float(np.sum(w * resid**2))
    return FitResult(
        params=dict(zip(names, beta, strict=True)),
        std_errors=dict(zip(names, se, strict=True)),
        n_obs=n,
        n_params=X.shape[1],
        estimator="OLS-HDFE",
        cluster_vars=list(clusters),
        n_clusters={k: int(len(np.unique(v))) for k, v in clusters.items()},
        converged=bool(ok_y and ok_x),
        iterations=max(it_y, it_x),
        absorbed_effects=list(fe_groups),
        dof_resid=dof,
        pseudo_r2=(1 - rss / tss) if tss > 0 else None,
    )


def ppml_hdfe(
    y: np.ndarray,
    X: np.ndarray,
    names: list[str],
    fe_groups: dict[str, np.ndarray],
    clusters: dict[str, np.ndarray],
    tol: float = 1e-9,
    max_iter: int = 200,
) -> FitResult:
    """Poisson pseudo-maximum-likelihood with absorbed high-dimensional fixed effects.

    IRLS: at each step form the Poisson working response and weights, absorb the
    fixed effects under those weights, and take a weighted least-squares step.
    Zero-valued observations are retained -- that is the point of using PPML for
    trade flows.
    """
    y = np.asarray(y, dtype=np.float64).ravel()
    X = np.asarray(X, dtype=np.float64)
    if np.any(y < 0):
        raise ValueError("PPML requires a non-negative dependent variable")
    n = y.size
    fe_list = list(fe_groups.values())
    notes: list[str] = []

    n_zero = int((y == 0).sum())
    if n_zero:
        notes.append(f"{n_zero} zero-valued observations retained ({n_zero / n:.1%} of sample)")

    # Separation check: a regressor perfectly predicting zeros breaks PPML.
    if n_zero:
        pos = y > 0
        for j, nm in enumerate(names):
            xv = X[:, j]
            if np.ptp(xv[pos]) == 0 and np.ptp(xv[~pos]) == 0 and xv[pos][0] != xv[~pos][0]:
                notes.append(f"possible separation on {nm}: constant within zero/positive groups")

    mu = np.maximum(y, 0.0) + 0.1
    eta = np.log(mu)
    beta = np.zeros(X.shape[1])
    converged = False
    it = 0
    dev_old = np.inf

    for it in range(1, max_iter + 1):
        w = mu
        z = eta + (y - mu) / mu
        zt, _, _ = absorb(z[:, None], fe_list, w)
        Xt, _, _ = absorb(X, fe_list, w)
        zt = zt.ravel()

        sw = np.sqrt(w)
        Xw, zw = Xt * sw[:, None], zt * sw
        XtX_inv = np.linalg.pinv(Xw.T @ Xw)
        beta_new = XtX_inv @ (Xw.T @ zw)

        # Recover eta including the absorbed effects: eta = z - (zt - Xt b).
        eta = z - (zt - Xt @ beta_new)
        eta = np.clip(eta, -80, 80)
        mu = np.exp(eta)

        with np.errstate(divide="ignore", invalid="ignore"):
            dev = 2 * np.sum(np.where(y > 0, y * np.log(np.where(y > 0, y / mu, 1.0)), 0.0) - (y - mu))
        if np.isfinite(dev) and abs(dev_old - dev) / (abs(dev) + 0.1) < tol:
            beta = beta_new
            converged = True
            break
        dev_old = dev
        beta = beta_new

    if not converged:
        notes.append(f"IRLS did not meet the convergence tolerance in {max_iter} iterations")

    w = mu
    Xt, _, _ = absorb(X, fe_list, w)
    sw = np.sqrt(w)
    Xw = Xt * sw[:, None]
    bread = np.linalg.pinv(Xw.T @ Xw)
    score = y - mu
    meat = _multiway_meat(Xt, score, clusters) if clusters else np.diag(
        (Xt * (score**2)[:, None]).sum(axis=0)
    )
    G = min(len(np.unique(v)) for v in clusters.values()) if clusters else n
    adj = G / max(G - 1, 1)
    V = bread @ meat @ bread * adj
    se = np.sqrt(np.clip(np.diag(V), 0, None))

    n_fe_params = sum(len(np.unique(g)) for g in fe_list) - max(len(fe_list) - 1, 0)
    ybar = y.mean()
    with np.errstate(divide="ignore", invalid="ignore"):
        ll = np.sum(y * np.log(np.where(mu > 0, mu, 1)) - mu)
        ll0 = np.sum(y * np.log(ybar) - ybar) if ybar > 0 else np.nan
    pr2 = float(1 - ll / ll0) if np.isfinite(ll0) and ll0 != 0 else None

    return FitResult(
        params=dict(zip(names, beta, strict=True)),
        std_errors=dict(zip(names, se, strict=True)),
        n_obs=n,
        n_params=X.shape[1],
        estimator="PPML-HDFE",
        cluster_vars=list(clusters),
        n_clusters={k: int(len(np.unique(v))) for k, v in clusters.items()},
        converged=converged,
        iterations=it,
        absorbed_effects=list(fe_groups),
        dof_resid=max(n - X.shape[1] - n_fe_params, 1),
        pseudo_r2=pr2,
        notes=notes,
    )


def wild_cluster_bootstrap(
    y: np.ndarray,
    X: np.ndarray,
    names: list[str],
    fe_groups: dict[str, np.ndarray],
    cluster: np.ndarray,
    test_index: int = 0,
    n_boot: int = 999,
    seed: int = 20180924,
    weights: np.ndarray | None = None,
) -> dict:
    """Wild cluster bootstrap-t p-value for one coefficient.

    Cluster-robust standard errors rely on the number of clusters being large.
    With a couple of dozen they over-reject badly, and this project has designs
    with exactly that problem: the domestic-propagation panel has one cluster per
    industry, of which there are 22. The wild cluster bootstrap (Cameron, Gelbach
    and Miller) is the standard remedy.

    Imposing the null when resampling is what makes it work: residuals come from
    the restricted model, so the bootstrap distribution is generated under
    ``beta = 0`` rather than around the estimate. Rademacher weights are applied
    at the **cluster** level, which is what preserves within-cluster dependence.

    Returns the bootstrap p-value alongside the analytic one, so the two can be
    compared rather than one quietly replacing the other.
    """
    y = np.asarray(y, dtype=np.float64).ravel()
    X = np.asarray(X, dtype=np.float64)
    fe_list = list(fe_groups.values())
    codes = _factorize(cluster)
    n_clusters = int(codes.max() + 1)

    full = ols_hdfe(y, X, names, fe_groups, {"cluster": cluster}, weights)
    t_obs = full.tstat(names[test_index])

    # Restricted model: drop the tested regressor and impose the null.
    keep = [j for j in range(X.shape[1]) if j != test_index]
    if keep:
        Xr = X[:, keep]
        rnames = [names[j] for j in keep]
        restricted = ols_hdfe(y, Xr, rnames, fe_groups, {"cluster": cluster}, weights)
        beta_r = np.array([restricted.params[nm] for nm in rnames])
        Xr_t, _, _ = absorb(Xr, fe_list, weights)
        fitted = Xr_t @ beta_r
    else:
        Xr_t = np.zeros((y.size, 0))
        fitted = np.zeros_like(y)

    yt, _, _ = absorb(y[:, None], fe_list, weights)
    resid_r = yt.ravel() - fitted

    rng = np.random.default_rng(seed)
    t_boot = np.empty(n_boot)
    n_failed = 0
    for b in range(n_boot):
        signs = rng.choice((-1.0, 1.0), size=n_clusters)[codes]
        y_star = fitted + resid_r * signs
        try:
            fit_b = ols_hdfe(
                y_star, X, names, {"_none": np.zeros_like(codes)}, {"cluster": cluster}, weights
            )
            t_boot[b] = fit_b.tstat(names[test_index])
        except (np.linalg.LinAlgError, ValueError):
            t_boot[b] = np.nan
            n_failed += 1

    valid = t_boot[np.isfinite(t_boot)]
    p_boot = (
        float((np.abs(valid) >= abs(t_obs)).mean()) if valid.size else float("nan")
    )
    return {
        "coefficient": names[test_index],
        "estimate": full.params[names[test_index]],
        "analytic_std_error": full.std_errors[names[test_index]],
        "analytic_p_value": full.pvalue(names[test_index]),
        "t_observed": t_obs,
        "bootstrap_p_value": p_boot,
        "n_clusters": n_clusters,
        "n_boot": int(valid.size),
        "n_boot_failed": n_failed,
        "caveat": (
            "Wild cluster bootstrap-t with the null imposed and Rademacher weights at the "
            "cluster level. With few clusters the analytic p-value over-rejects; where the "
            "two disagree, the bootstrap is the one to read."
        ),
    }
