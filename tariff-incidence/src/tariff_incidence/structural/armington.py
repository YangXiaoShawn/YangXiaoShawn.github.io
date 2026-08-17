"""Armington/CES sourcing counterfactuals over foreign supply sources.

Scope, decided before anything was written
------------------------------------------

This is a **one-tier CES nest across source countries within a product**. It is
not a welfare model and it does not have a domestic nest. That is a deliberate
restriction, not an omission to be filled in later without saying so:

* A one-tier nest over foreign sources is **fully identified from import data
  alone**. The counterfactual needs pre-treatment expenditure shares and the
  tariff change, and nothing else -- no price levels, no domestic expenditure
  series, no estimated demand system.
* A two-tier nest that includes the domestic alternative is **not identified
  here**. U.S. import statistics say nothing about domestic expenditure on the
  competing good, so the share of a fall in imports that went to domestic
  producers rather than out of consumption cannot be recovered. Assuming a
  domestic share would put the answer in by hand.

Everything below therefore describes reallocation *among foreign suppliers* and
the cost of the imported bundle. Nothing here is a welfare statement, and the
reporting guard that blocks welfare claims stays in force.

The algebra
-----------

With CES preferences over source countries and expenditure shares :math:`s_j`,
a proportional change in the tariff-inclusive price of each source implies new
shares by the standard hat algebra::

    s_j^1 = s_j^0 (1 + tau_j)^(1 - sigma) / sum_i s_i^0 (1 + tau_i)^(1 - sigma)

and an exact CES price index for the imported bundle::

    P_hat = [ sum_i s_i^0 (1 + tau_i)^(1 - sigma) ]^(1 / (1 - sigma))

Both need only pre-treatment shares and the tariff, which is why this is
identified where a fuller model is not.

The assumption that carries it, and why it is not assumed here
--------------------------------------------------------------

Both expressions hold foreign **producer** prices fixed: the tariff is passed
into the buyer's price one-for-one. That is normally an assumption. In this
project it is a *finding*: the reduced-form estimate of the customs unit value
response -- the tariff-exclusive foreign border price -- is a bounded null, at
most 0.076 log points in absolute value under the stacked design. The structural
module and the reduced-form module are therefore not independent readings of the
same data; the second supplies a premise of the first, and that is stated
wherever the outputs appear.

sigma
-----

The elasticity is **not estimated here and is never fabricated**. It is supplied
by configuration, run over a grid, and every output is labelled ``CALIBRATED``.
Separately, ``implied_sigma_from_reduced_form`` inverts the model against this
project's own PPML quantity response, which gives a value derived from the data
in hand rather than borrowed -- reported beside the grid, not instead of it.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np
import polars as pl


class ParameterType(str, Enum):
    """What kind of number a row is. Required on every structural output."""

    DATA_MOMENT = "DATA_MOMENT"
    """Observed in the data: a pre-treatment share, a statutory rate."""

    ESTIMATED = "ESTIMATED"
    """Produced by an estimator in this project, with a standard error."""

    CALIBRATED = "CALIBRATED"
    """Chosen or borrowed, not estimated here. Carries no standard error."""

    MODEL_IMPLIED = "MODEL_IMPLIED"
    """An output of the model given the three above. Not an observation."""


@dataclass(slots=True)
class SourcingCounterfactual:
    """Model-implied reallocation and bundle cost at one elasticity."""

    sigma: float
    shares: pl.DataFrame
    """product, country, share_pre, share_counterfactual, share_change."""
    price_index: pl.DataFrame
    """product, price_index_change, log_price_index_change, pre_value."""
    aggregate_log_price_index_change: float
    treated_share_pre: float
    treated_share_counterfactual: float


def counterfactual_shares(
    shares: pl.DataFrame,
    *,
    sigma: float,
    product_col: str = "hs10",
    country_col: str = "country_code",
    share_col: str = "share_pre",
    tariff_col: str = "tariff_change",
) -> pl.DataFrame:
    """CES sourcing shares after a tariff change, by hat algebra.

    ``sigma == 1`` is Cobb-Douglas and leaves every share unchanged; that is a
    property of the algebra rather than a special case in the code, and it is
    asserted in the tests so a wrong exponent cannot pass silently.
    """
    if sigma <= 0:
        raise ValueError(f"sigma must be positive, got {sigma}")
    power = 1.0 - sigma
    d = shares.with_columns(
        (pl.col(share_col) * (1.0 + pl.col(tariff_col)).pow(power)).alias("_w")
    )
    return (
        d.with_columns((pl.col("_w") / pl.col("_w").sum().over(product_col)).alias(
            "share_counterfactual"
        ))
        .with_columns(
            (pl.col("share_counterfactual") - pl.col(share_col)).alias("share_change")
        )
        .drop("_w")
    )


def price_index_change(
    shares: pl.DataFrame,
    *,
    sigma: float,
    product_col: str = "hs10",
    share_col: str = "share_pre",
    tariff_col: str = "tariff_change",
) -> pl.DataFrame:
    """Exact CES price index of the imported bundle, per product.

    Holds foreign producer prices fixed. In this project that premise is the
    reduced-form finding that the customs unit value response is a bounded null,
    not a free assumption -- see the module docstring.
    """
    if sigma <= 0:
        raise ValueError(f"sigma must be positive, got {sigma}")
    if abs(sigma - 1.0) < 1e-12:
        # The CES index is a share-weighted geometric mean at sigma = 1; the
        # 1/(1-sigma) exponent is undefined there, so take the limit rather than
        # dividing by zero and returning an infinity that looks like a result.
        return (
            shares.group_by(product_col)
            .agg(
                (pl.col(share_col) * (1.0 + pl.col(tariff_col)).log()).sum().alias(
                    "log_price_index_change"
                )
            )
            .with_columns(pl.col("log_price_index_change").exp().alias("price_index_change"))
        )
    power = 1.0 - sigma
    return (
        shares.group_by(product_col)
        .agg((pl.col(share_col) * (1.0 + pl.col(tariff_col)).pow(power)).sum().alias("_s"))
        .with_columns(pl.col("_s").pow(1.0 / power).alias("price_index_change"))
        .with_columns(pl.col("price_index_change").log().alias("log_price_index_change"))
        .drop("_s")
    )


def build_counterfactual(
    shares: pl.DataFrame,
    *,
    sigma: float,
    treated_country: str,
    product_col: str = "hs10",
    country_col: str = "country_code",
    weight_col: str = "pre_value",
) -> SourcingCounterfactual:
    """Shares, bundle cost and the treated-source aggregate, at one sigma."""
    cf = counterfactual_shares(
        shares, sigma=sigma, product_col=product_col, country_col=country_col
    )
    pi = price_index_change(shares, sigma=sigma, product_col=product_col)

    weights = shares.group_by(product_col).agg(pl.col(weight_col).sum().alias("_w"))
    pi = pi.join(weights, on=product_col, how="left")
    total = pi["_w"].sum()
    agg = (
        float((pi["log_price_index_change"] * pi["_w"]).sum() / total) if total else 0.0
    )

    trt = cf.filter(pl.col(country_col) == treated_country)
    wt = trt.join(weights, on=product_col, how="left")
    tw = wt["_w"].sum()
    pre = float((wt["share_pre"] * wt["_w"]).sum() / tw) if tw else 0.0
    post = float((wt["share_counterfactual"] * wt["_w"]).sum() / tw) if tw else 0.0

    return SourcingCounterfactual(
        sigma=sigma,
        shares=cf,
        price_index=pi.rename({"_w": "pre_value"}),
        aggregate_log_price_index_change=agg,
        treated_share_pre=pre,
        treated_share_counterfactual=post,
    )


def implied_sigma_from_reduced_form(
    log_quantity_response: float,
    mean_log1p_tariff: float,
) -> float | None:
    """The sigma at which the model reproduces this project's own quantity estimate.

    The CES demand for a source facing a tariff change satisfies
    ``d log q = -sigma * d log(1 + tau)`` up to the price-index term, so a
    reduced-form coefficient on ``log(1 + tau)`` identifies sigma directly. This
    is reported **beside** the calibrated grid, never instead of it: it inherits
    every limitation of the estimate it inverts, including that the quantity
    outcome's pre-period is the noisiest of the three.

    Returns ``None`` when the inputs cannot identify it, rather than a number.
    """
    if mean_log1p_tariff == 0 or not np.isfinite(log_quantity_response):
        return None
    sigma = -log_quantity_response / mean_log1p_tariff
    return float(sigma) if np.isfinite(sigma) and sigma > 0 else None
