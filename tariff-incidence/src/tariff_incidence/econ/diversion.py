"""Trade-diversion decomposition.

Separates the total change in a product's imports into margins that carry
different economic meaning. The central discipline is that a fall in imports
from the treated country and a rise from third countries are **different
quantities** and are never netted before being reported.

Decomposition, comparing a pre-window mean to a post-window mean per product:

    dTotal = dTreatedIntensive + dTreatedExtensive
           + dAltIntensive     + dAltExtensive

where "extensive" is the value carried by product-country flows that were
active in exactly one of the two windows (entry or exit), and "intensive" is the
change among flows active in both.

Interpretation warning carried into every output
------------------------------------------------

A rise in imports from Vietnam is **not** evidence that production moved to
Vietnam. It is consistent with relocation, with rerouting of Chinese-origin
goods through third countries, with pre-existing capacity being redirected to
the U.S. market, and with origin misreporting to avoid the duty. Customs data
records country of origin as declared; it cannot distinguish these.
"""

from __future__ import annotations

import polars as pl


def _window_means(
    panel: pl.DataFrame,
    *,
    lo: int,
    hi: int,
    product_col: str,
    country_col: str,
    value_col: str,
    event_col: str,
) -> pl.DataFrame:
    return (
        panel.filter(
            pl.col(event_col).is_not_null()
            & (pl.col(event_col) >= lo)
            & (pl.col(event_col) <= hi)
        )
        .group_by([product_col, country_col])
        .agg(
            pl.col(value_col).fill_null(0.0).mean().alias("mean_value"),
            (pl.col(value_col).fill_null(0.0) > 0).any().alias("active"),
        )
    )


def decompose(
    panel: pl.DataFrame,
    *,
    treated_country_code: str,
    pre_window: tuple[int, int] = (-12, -1),
    post_window: tuple[int, int] = (1, 10),
    product_col: str = "hs6",
    country_col: str = "country_code",
    value_col: str = "customs_value",
    event_col: str = "event_time",
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Decompose the pre-to-post change in imports by margin.

    Returns ``(by_product, totals)``. Values are average monthly customs value,
    so the two windows are comparable even when they differ in length.
    """
    pre = _window_means(
        panel,
        lo=pre_window[0],
        hi=pre_window[1],
        product_col=product_col,
        country_col=country_col,
        value_col=value_col,
        event_col=event_col,
    ).rename({"mean_value": "pre_value", "active": "pre_active"})
    post = _window_means(
        panel,
        lo=post_window[0],
        hi=post_window[1],
        product_col=product_col,
        country_col=country_col,
        value_col=value_col,
        event_col=event_col,
    ).rename({"mean_value": "post_value", "active": "post_active"})

    j = pre.join(post, on=[product_col, country_col], how="full", coalesce=True).with_columns(
        pl.col("pre_value").fill_null(0.0),
        pl.col("post_value").fill_null(0.0),
        pl.col("pre_active").fill_null(False),  # noqa: FBT003
        pl.col("post_active").fill_null(False),  # noqa: FBT003
    )

    j = j.with_columns(
        (pl.col(country_col) == treated_country_code).alias("is_treated_country"),
        (pl.col("post_value") - pl.col("pre_value")).alias("delta"),
    ).with_columns(
        (pl.col("pre_active") & pl.col("post_active")).alias("continuing"),
        (~pl.col("pre_active") & pl.col("post_active")).alias("entered"),
        (pl.col("pre_active") & ~pl.col("post_active")).alias("exited"),
    )

    def margin(is_treated: bool, kind: str) -> pl.Expr:  # noqa: FBT001
        base = pl.col("is_treated_country") if is_treated else ~pl.col("is_treated_country")
        if kind == "intensive":
            cond = base & pl.col("continuing")
            return pl.when(cond).then(pl.col("delta")).otherwise(0.0)
        cond = base & (pl.col("entered") | pl.col("exited"))
        return pl.when(cond).then(pl.col("delta")).otherwise(0.0)

    by_product = (
        j.group_by(product_col)
        .agg(
            margin(True, "intensive").sum().alias("treated_intensive"),
            margin(True, "extensive").sum().alias("treated_extensive"),
            margin(False, "intensive").sum().alias("alternative_intensive"),
            margin(False, "extensive").sum().alias("alternative_extensive"),
            pl.col("delta").sum().alias("total_change"),
            pl.when(pl.col("is_treated_country")).then(pl.col("pre_value")).otherwise(0.0).sum().alias("pre_treated_value"),
            pl.when(~pl.col("is_treated_country")).then(pl.col("pre_value")).otherwise(0.0).sum().alias("pre_alternative_value"),
            pl.col("pre_value").sum().alias("pre_total_value"),
            pl.col("post_value").sum().alias("post_total_value"),
            (pl.col("entered") & ~pl.col("is_treated_country")).sum().alias("n_alt_suppliers_entered"),
            (pl.col("exited") & ~pl.col("is_treated_country")).sum().alias("n_alt_suppliers_exited"),
            (pl.col("exited") & pl.col("is_treated_country")).sum().alias("n_treated_flows_exited"),
        )
        .with_columns(
            (pl.col("treated_intensive") + pl.col("treated_extensive")).alias("treated_total"),
            (pl.col("alternative_intensive") + pl.col("alternative_extensive")).alias(
                "alternative_total"
            ),
        )
        .with_columns(
            pl.when(pl.col("pre_treated_value") > 0)
            .then(pl.col("treated_total") / pl.col("pre_treated_value"))
            .otherwise(None)
            .alias("treated_pct_change"),
            # How much of the treated-country decline was picked up elsewhere.
            pl.when(pl.col("treated_total") < 0)
            .then(-pl.col("alternative_total") / pl.col("treated_total"))
            .otherwise(None)
            .alias("replacement_ratio"),
        )
        .sort("pre_total_value", descending=True)
    )

    cols = [
        "treated_intensive",
        "treated_extensive",
        "alternative_intensive",
        "alternative_extensive",
        "treated_total",
        "alternative_total",
        "total_change",
        "pre_treated_value",
        "pre_alternative_value",
        "pre_total_value",
        "post_total_value",
        "n_alt_suppliers_entered",
        "n_alt_suppliers_exited",
        "n_treated_flows_exited",
    ]
    totals = by_product.select([pl.col(c).sum().alias(c) for c in cols]).with_columns(
        pl.when(pl.col("pre_treated_value") > 0)
        .then(pl.col("treated_total") / pl.col("pre_treated_value"))
        .otherwise(None)
        .alias("treated_pct_change"),
        pl.when(pl.col("treated_total") < 0)
        .then(-pl.col("alternative_total") / pl.col("treated_total"))
        .otherwise(None)
        .alias("replacement_ratio"),
        pl.lit(
            "A rise in third-country imports is not evidence of production relocation; "
            "rerouting, transshipment and origin misdeclaration produce the same pattern "
            "in customs data."
        ).alias("interpretation_warning"),
    )
    return by_product, totals


def counterfactual_adjusted(
    panel: pl.DataFrame,
    *,
    treated_country_code: str,
    pre_window: tuple[int, int] = (-12, -1),
    post_window: tuple[int, int] = (1, 10),
    product_col: str = "hs6",
    country_col: str = "country_code",
    value_col: str = "customs_value",
    event_col: str = "event_time",
    treated_product_flag: str = "ever_treated_product",
) -> tuple[pl.DataFrame, dict]:
    """Decomposition net of the growth never-treated products experienced.

    A raw pre-versus-post decomposition attributes ordinary trade growth to the
    tariff. Over a two-year window with nominal growth and a common demand
    trend, that alone can make third-country "diversion" look enormous and can
    even make a replacement ratio exceed one when nothing was replaced.

    This function forms a counterfactual by applying, country by country, the
    growth rate observed for **never-treated products over the same calendar
    months** to each treated product's pre-period value. The reported margins are
    deviations from that counterfactual, which is a difference-in-differences
    version of the decomposition.

    The identifying assumption is the same one the event study makes: absent the
    tariff, treated and never-treated products would have grown at the same rate
    within a partner country. It is stated, not assumed away, and the raw
    decomposition is reported alongside so the adjustment's size is visible.
    """
    treated_products = panel.filter(pl.col(treated_product_flag))
    control_products = panel.filter(~pl.col(treated_product_flag))

    if control_products.height == 0:
        return pl.DataFrame(), {"status": "SKIPPED", "reason": "no never-treated products"}

    # Calendar months spanned by the treated products' event windows.
    span = treated_products.filter(
        pl.col(event_col).is_not_null()
        & (pl.col(event_col) >= pre_window[0])
        & (pl.col(event_col) <= post_window[1])
    )
    pre_months = span.filter(pl.col(event_col) <= pre_window[1])["month_index"].unique()
    post_months = span.filter(pl.col(event_col) >= post_window[0])["month_index"].unique()

    ctrl_pre = (
        control_products.filter(pl.col("month_index").is_in(pre_months))
        .group_by(country_col)
        .agg(pl.col(value_col).fill_null(0.0).mean().alias("ctrl_pre"))
    )
    ctrl_post = (
        control_products.filter(pl.col("month_index").is_in(post_months))
        .group_by(country_col)
        .agg(pl.col(value_col).fill_null(0.0).mean().alias("ctrl_post"))
    )
    growth = (
        ctrl_pre.join(ctrl_post, on=country_col, how="inner")
        .with_columns(
            pl.when(pl.col("ctrl_pre") > 0)
            .then(pl.col("ctrl_post") / pl.col("ctrl_pre"))
            .otherwise(None)
            .alias("counterfactual_growth")
        )
        .select([country_col, "counterfactual_growth", "ctrl_pre", "ctrl_post"])
    )

    pre = _window_means(
        treated_products, lo=pre_window[0], hi=pre_window[1],
        product_col=product_col, country_col=country_col,
        value_col=value_col, event_col=event_col,
    ).rename({"mean_value": "pre_value"})
    post = _window_means(
        treated_products, lo=post_window[0], hi=post_window[1],
        product_col=product_col, country_col=country_col,
        value_col=value_col, event_col=event_col,
    ).rename({"mean_value": "post_value"})

    j = (
        pre.join(post, on=[product_col, country_col], how="full", coalesce=True)
        .with_columns(pl.col("pre_value").fill_null(0.0), pl.col("post_value").fill_null(0.0))
        .join(growth, on=country_col, how="left")
        .with_columns(
            (pl.col("pre_value") * pl.col("counterfactual_growth")).alias("counterfactual_post"),
        )
        .with_columns(
            (pl.col("post_value") - pl.col("counterfactual_post")).alias("excess_change"),
            (pl.col(country_col) == treated_country_code).alias("is_treated_country"),
        )
    )

    by_country = (
        j.group_by(country_col)
        .agg(
            pl.col("pre_value").sum().alias("pre_monthly_value"),
            pl.col("post_value").sum().alias("post_monthly_value"),
            pl.col("counterfactual_post").sum().alias("counterfactual_post_value"),
            pl.col("excess_change").sum().alias("excess_change"),
            pl.col("counterfactual_growth").first().alias("control_growth_factor"),
            pl.col("is_treated_country").first().alias("is_treated_country"),
        )
        .with_columns(
            pl.when(pl.col("counterfactual_post_value") > 0)
            .then(pl.col("excess_change") / pl.col("counterfactual_post_value"))
            .otherwise(None)
            .alias("excess_pct_vs_counterfactual")
        )
        .sort("excess_change", descending=True)
    )

    treated_excess = float(
        by_country.filter(pl.col("is_treated_country"))["excess_change"].sum()
    )
    alt_excess = float(by_country.filter(~pl.col("is_treated_country"))["excess_change"].sum())
    summary = {
        "treated_country_excess_change": treated_excess,
        "alternative_countries_excess_change": alt_excess,
        "net_excess_change": treated_excess + alt_excess,
        "adjusted_replacement_ratio": (
            -alt_excess / treated_excess if treated_excess < 0 else None
        ),
        "counterfactual": (
            "country-specific growth of never-treated products over the same calendar months"
        ),
        "identifying_assumption": (
            "absent the tariff, treated and never-treated products would have grown at the "
            "same rate within each partner country"
        ),
    }
    return by_country, summary


def country_gains(
    panel: pl.DataFrame,
    *,
    treated_country_code: str,
    pre_window: tuple[int, int] = (-12, -1),
    post_window: tuple[int, int] = (1, 10),
    product_col: str = "hs6",
    country_col: str = "country_code",
    value_col: str = "customs_value",
    event_col: str = "event_time",
) -> pl.DataFrame:
    """Which alternative suppliers gained, in monthly-average value terms."""
    pre = _window_means(
        panel, lo=pre_window[0], hi=pre_window[1],
        product_col=product_col, country_col=country_col,
        value_col=value_col, event_col=event_col,
    ).rename({"mean_value": "pre_value"})
    post = _window_means(
        panel, lo=post_window[0], hi=post_window[1],
        product_col=product_col, country_col=country_col,
        value_col=value_col, event_col=event_col,
    ).rename({"mean_value": "post_value"})
    j = pre.join(post, on=[product_col, country_col], how="full", coalesce=True).with_columns(
        pl.col("pre_value").fill_null(0.0), pl.col("post_value").fill_null(0.0)
    )
    out = (
        j.group_by(country_col)
        .agg(
            pl.col("pre_value").sum().alias("pre_monthly_value"),
            pl.col("post_value").sum().alias("post_monthly_value"),
        )
        .with_columns(
            (pl.col("post_monthly_value") - pl.col("pre_monthly_value")).alias("change"),
            pl.when(pl.col("pre_monthly_value") > 0)
            .then(
                (pl.col("post_monthly_value") - pl.col("pre_monthly_value"))
                / pl.col("pre_monthly_value")
            )
            .otherwise(None)
            .alias("pct_change"),
            (pl.col(country_col) == treated_country_code).alias("is_treated_country"),
        )
        .sort("change", descending=True)
    )
    tot_pre = out["pre_monthly_value"].sum()
    tot_post = out["post_monthly_value"].sum()
    return out.with_columns(
        (pl.col("pre_monthly_value") / tot_pre).alias("pre_share") if tot_pre else pl.lit(None).alias("pre_share"),
        (pl.col("post_monthly_value") / tot_post).alias("post_share") if tot_post else pl.lit(None).alias("post_share"),
    ).with_columns((pl.col("post_share") - pl.col("pre_share")).alias("share_change"))
