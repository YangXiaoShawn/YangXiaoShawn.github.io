"""Armington sourcing counterfactuals, tested on properties the algebra must have.

A structural module is easy to write and hard to check: it produces numbers for
any input, and a wrong exponent still returns something plausible. So the tests
here assert the closed-form behaviour the CES nest is required to show, at
points where an error cannot hide.
"""

from __future__ import annotations

import polars as pl
import pytest

from tariff_incidence.structural.armington import (
    ParameterType,
    build_counterfactual,
    counterfactual_shares,
    implied_sigma_from_reduced_form,
    price_index_change,
)


def _shares(tau_treated: float = 0.25) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "hs10": ["1" * 10] * 3,
            "country_code": ["5700", "5800", "2010"],
            "share_pre": [0.5, 0.3, 0.2],
            "tariff_change": [tau_treated, 0.0, 0.0],
            "pre_value": [500.0, 300.0, 200.0],
        }
    )


def test_unit_elasticity_leaves_every_share_unchanged():
    """Cobb-Douglas: expenditure shares do not move, whatever the tariff.

    This is the sharpest available check on the exponent. At sigma = 1 the
    weight is (1+tau)^0 = 1, so any sign error or off-by-one in `1 - sigma`
    breaks it immediately.
    """
    out = counterfactual_shares(_shares(), sigma=1.0)
    for pre, post in zip(out["share_pre"], out["share_counterfactual"], strict=True):
        assert post == pytest.approx(pre, abs=1e-12)


def test_shares_always_sum_to_one():
    for sigma in (0.5, 1.0, 2.0, 5.0, 12.0):
        out = counterfactual_shares(_shares(), sigma=sigma)
        assert out["share_counterfactual"].sum() == pytest.approx(1.0, abs=1e-12)


def test_a_tariffed_source_loses_share_when_sources_are_substitutes():
    """sigma > 1 is substitutability; the tariffed source must lose share."""
    out = counterfactual_shares(_shares(), sigma=4.0)
    treated = out.filter(pl.col("country_code") == "5700").row(0, named=True)
    assert treated["share_counterfactual"] < treated["share_pre"]
    for r in out.filter(pl.col("country_code") != "5700").iter_rows(named=True):
        assert r["share_counterfactual"] > r["share_pre"]


def test_a_tariffed_source_gains_share_when_sources_are_complements():
    """sigma < 1 reverses it. Reported rather than excluded: the sign of the
    reallocation is a property of the calibrated elasticity, not of the data."""
    out = counterfactual_shares(_shares(), sigma=0.5)
    treated = out.filter(pl.col("country_code") == "5700").row(0, named=True)
    assert treated["share_counterfactual"] > treated["share_pre"]


def test_reallocation_grows_with_the_elasticity():
    losses = []
    for sigma in (2.0, 4.0, 8.0):
        out = counterfactual_shares(_shares(), sigma=sigma)
        t = out.filter(pl.col("country_code") == "5700").row(0, named=True)
        losses.append(t["share_pre"] - t["share_counterfactual"])
    assert losses[0] < losses[1] < losses[2]


def test_price_index_rises_with_a_tariff_and_is_one_without():
    for sigma in (0.5, 1.0, 2.0, 6.0):
        assert price_index_change(_shares(0.25), sigma=sigma)["price_index_change"][0] > 1.0
        flat = price_index_change(_shares(0.0), sigma=sigma)["price_index_change"][0]
        assert flat == pytest.approx(1.0, abs=1e-12)


def test_price_index_is_continuous_through_unit_elasticity():
    """The 1/(1-sigma) exponent is undefined at sigma = 1.

    The limit is a share-weighted geometric mean. Taking the closed form
    literally would divide by zero and return an infinity that still looks like
    a result, so the limit is coded explicitly and pinned here.
    """
    at_one = price_index_change(_shares(), sigma=1.0)["price_index_change"][0]
    for eps in (1e-4, 1e-5):
        below = price_index_change(_shares(), sigma=1.0 - eps)["price_index_change"][0]
        above = price_index_change(_shares(), sigma=1.0 + eps)["price_index_change"][0]
        assert below == pytest.approx(at_one, rel=1e-3)
        assert above == pytest.approx(at_one, rel=1e-3)


def test_price_index_falls_as_substitution_gets_easier():
    """Easier substitution means the tariff costs the buyer less."""
    prev = None
    for sigma in (1.5, 3.0, 6.0, 12.0):
        p = price_index_change(_shares(), sigma=sigma)["price_index_change"][0]
        if prev is not None:
            assert p < prev
        prev = p


def test_price_index_never_exceeds_the_tariff_on_the_treated_source():
    """Substituting away cannot cost more than paying the duty on everything."""
    for sigma in (1.5, 4.0, 9.0):
        p = price_index_change(_shares(), sigma=sigma)["price_index_change"][0]
        assert p <= 1.25 + 1e-12


def test_build_counterfactual_reports_the_treated_share_both_ways():
    cf = build_counterfactual(_shares(), sigma=4.0, treated_country="5700")
    assert cf.treated_share_pre == pytest.approx(0.5)
    assert cf.treated_share_counterfactual < 0.5
    assert cf.aggregate_log_price_index_change > 0


def test_a_non_positive_elasticity_raises_rather_than_returning_a_number():
    for bad in (0.0, -1.0):
        with pytest.raises(ValueError, match="sigma must be positive"):
            counterfactual_shares(_shares(), sigma=bad)
        with pytest.raises(ValueError, match="sigma must be positive"):
            price_index_change(_shares(), sigma=bad)


def test_implied_sigma_inverts_the_reduced_form_and_declines_to_guess():
    assert implied_sigma_from_reduced_form(-2.0, 0.5) == pytest.approx(4.0)
    # A positive quantity response implies a negative elasticity: not a number
    # this model can use, so it returns None instead of one.
    assert implied_sigma_from_reduced_form(+2.0, 0.5) is None
    assert implied_sigma_from_reduced_form(-2.0, 0.0) is None


def test_parameter_types_are_the_four_the_brief_requires():
    assert {p.value for p in ParameterType} == {
        "DATA_MOMENT",
        "ESTIMATED",
        "CALIBRATED",
        "MODEL_IMPLIED",
    }


def test_a_source_share_must_be_weighted_by_total_value_not_its_own():
    """Weighting a country's share by that country's own value inflates it.

    On the first run this turned an observed treated share of about 0.19 into
    0.49 and made the model look as though it had the sign of the reallocation
    backwards -- a spectacular false finding that only failed because it
    contradicted the diversion decomposition. The model side weights by product
    totals, so anything compared against it must too.
    """
    cells = pl.DataFrame(
        {
            "hs10": ["A", "A", "B", "B"],
            "country_code": ["5700", "2010", "5700", "2010"],
            # China dominates the small product and is marginal in the big one.
            "share_post": [0.90, 0.10, 0.10, 0.90],
            "own_value": [90.0, 10.0, 100.0, 900.0],
        }
    )
    totals = cells.group_by("hs10").agg(pl.col("own_value").sum().alias("total"))
    trt = cells.filter(pl.col("country_code") == "5700").join(totals, on="hs10")

    own_weighted = float(
        (trt["share_post"] * trt["own_value"]).sum() / trt["own_value"].sum()
    )
    total_weighted = float(
        (trt["share_post"] * trt["total"]).sum() / trt["total"].sum()
    )
    # The correct figure is the aggregate share: 190 of 1100.
    aggregate = float(
        cells.filter(pl.col("country_code") == "5700")["own_value"].sum()
        / cells["own_value"].sum()
    )
    assert total_weighted == pytest.approx(aggregate, abs=1e-12)
    assert own_weighted > total_weighted * 2
