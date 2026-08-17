"""Industry tariff-exposure measures.

A tariff hits an industry through channels that pull in opposite directions, and
the central requirement here is that they are **measured separately and never
netted into a single "exposure" number**:

``output_protection_exposure``
    The industry's own output competes with imports that are now dutied. This
    channel *helps* the industry.

``imported_input_cost_exposure``
    The industry buys inputs that are now dutied. This channel *hurts* it.

``downstream_total_requirements_exposure``
    Exposure through the full Leontief chain, capturing inputs of inputs.

``direct_import_competition_exposure``
    Import penetration in the industry's own commodity, tariffed or not, which
    sets how much the protection channel can matter.

An industry can be strongly exposed on both sides at once -- U.S. steel-using
manufacturers in 2018 are the textbook case -- and reporting a net figure hides
precisely the distributional question the analysis is for.

The two channels are also **not on a comparable scale**, which is a second and
independent reason never to difference them. Protection is the tariff rate on
one commodity, so it inherits the statutory rate directly and tops out at it
(0.25 at detail level, mean 0.076). Input cost is an average over the industry's
whole purchase basket, most of which -- services, domestic materials, untariffed
imports -- carries no tariff at all, so it is mechanically diluted (max 0.112,
mean 0.023). A larger protection number than cost number therefore says nothing
about which channel dominates. Only the separately estimated coefficients, each
scaled by its own regressor, carry that information, and
``net_contrast_do_not_use_alone`` is named to make misuse deliberate.

All weights come from a **pre-treatment** IO table. Contemporaneous weights would
respond to the tariff and would build the outcome into the exposure measure.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import polars as pl


@dataclass(slots=True)
class ConcordanceQuality:
    """How the HS-to-industry mapping was built, and what it costs."""

    method: str
    level: str
    n_mapped_products: int
    n_unmapped_products: int
    aggregation_loss_note: str
    source: str
    warnings: list[str] = field(default_factory=list)

    def to_row(self) -> dict:
        return {
            "concordance_method": self.method,
            "concordance_level": self.level,
            "n_mapped_products": self.n_mapped_products,
            "n_unmapped_products": self.n_unmapped_products,
            "aggregation_loss": self.aggregation_loss_note,
            "concordance_source": self.source,
            "warnings": " | ".join(self.warnings),
        }


def commodity_tariff_exposure(
    panel: pl.DataFrame,
    hs_to_commodity: dict[str, str],
    *,
    pre_period_end_month_index: int | None = None,
    product_col: str = "hs6",
    value_col: str = "customs_value",
    tariff_col: str = "additional_tariff_rate",
) -> tuple[pl.DataFrame, ConcordanceQuality]:
    """Trade-weighted additional tariff rate per IO commodity.

    Weights are **pre-treatment** import values, so a commodity's exposure does
    not fall merely because tariffed imports collapsed.
    """
    df = panel
    if pre_period_end_month_index is not None:
        pre = df.filter(pl.col("month_index") <= pre_period_end_month_index)
    else:
        pre = df

    weights = (
        pre.group_by(product_col)
        .agg(pl.col(value_col).sum().alias("pre_import_value"))
    )
    peak_tariff = (
        df.group_by(product_col)
        .agg(pl.col(tariff_col).max().alias("peak_additional_tariff"))
    )
    prod = weights.join(peak_tariff, on=product_col, how="inner")

    mapping = pl.DataFrame(
        {"_hs": list(hs_to_commodity), "commodity_code": list(hs_to_commodity.values())}
    )
    joined = prod.join(mapping, left_on=product_col, right_on="_hs", how="left")
    unmapped = joined.filter(pl.col("commodity_code").is_null())
    mapped = joined.filter(pl.col("commodity_code").is_not_null())

    out = (
        mapped.group_by("commodity_code")
        .agg(
            (
                (pl.col("peak_additional_tariff") * pl.col("pre_import_value")).sum()
                / pl.col("pre_import_value").sum()
            ).alias("commodity_tariff_exposure"),
            pl.col("pre_import_value").sum().alias("pre_import_value"),
            pl.len().alias("n_products"),
            (pl.col("peak_additional_tariff") > 0).sum().alias("n_treated_products"),
        )
        .sort("pre_import_value", descending=True)
    )
    q = ConcordanceQuality(
        method="configured HS-to-BEA-commodity map",
        level="HS6 -> BEA summary commodity",
        n_mapped_products=mapped.height,
        n_unmapped_products=unmapped.height,
        aggregation_loss_note=(
            "BEA summary commodities are far broader than HS6 lines. A summary commodity that "
            "contains both tariffed and untariffed HS6 products receives an import-weighted "
            "average rate, so industry-level exposure is attenuated relative to the true "
            "product-level shock, and heterogeneity within a commodity is lost entirely."
        ),
        source="config/io_concordance.yaml",
        warnings=(
            [f"{unmapped.height} products have no commodity mapping and are excluded"]
            if unmapped.height
            else []
        ),
    )
    return out, q


def build_exposures(
    commodity_exposure: pl.DataFrame,
    direct_requirements: pl.DataFrame,
    total_requirements: pl.DataFrame,
    *,
    industry_output_commodity: dict[str, str] | None = None,
    import_penetration: pl.DataFrame | None = None,
) -> pl.DataFrame:
    """Assemble the four exposure channels, kept separate.

    Parameters
    ----------
    commodity_exposure
        ``commodity_code``, ``commodity_tariff_exposure``.
    direct_requirements
        ``commodity_code``, ``industry_code``, ``direct_requirement``.
    total_requirements
        ``industry_code``, ``commodity_code``, ``total_requirement``.
    industry_output_commodity
        Industry -> the commodity it primarily produces. Defaults to the
        identity map that BEA's summary industry/commodity coding already
        implies.
    """
    ce = commodity_exposure.select(["commodity_code", "commodity_tariff_exposure"])

    # Channel 2: cost of imported inputs, direct requirements.
    input_cost = (
        direct_requirements.join(ce, on="commodity_code", how="inner")
        .group_by("industry_code")
        .agg(
            (pl.col("direct_requirement") * pl.col("commodity_tariff_exposure"))
            .sum()
            .alias("imported_input_cost_exposure"),
            pl.col("direct_requirement").sum().alias("_dr_coverage"),
        )
    )

    # Channel 3: same, through the full Leontief chain.
    downstream = (
        total_requirements.join(ce, on="commodity_code", how="inner")
        .group_by("industry_code")
        .agg(
            (pl.col("total_requirement") * pl.col("commodity_tariff_exposure"))
            .sum()
            .alias("downstream_total_requirements_exposure")
        )
    )

    # Channel 1: protection on the industry's own output.
    ind_codes = (
        direct_requirements.select("industry_code").unique().to_series().to_list()
    )
    own = industry_output_commodity or {i: i for i in ind_codes}
    own_df = pl.DataFrame(
        {"industry_code": list(own), "own_commodity_code": list(own.values())}
    )
    protection = (
        own_df.join(
            ce.rename({"commodity_code": "own_commodity_code",
                       "commodity_tariff_exposure": "output_protection_exposure"}),
            on="own_commodity_code",
            how="left",
        )
        .select(["industry_code", "own_commodity_code", "output_protection_exposure"])
    )

    out = (
        protection.join(input_cost, on="industry_code", how="full", coalesce=True)
        .join(downstream, on="industry_code", how="full", coalesce=True)
        .with_columns(
            pl.col("output_protection_exposure").fill_null(0.0),
            pl.col("imported_input_cost_exposure").fill_null(0.0),
            pl.col("downstream_total_requirements_exposure").fill_null(0.0),
        )
    )

    if import_penetration is not None:
        out = out.join(import_penetration, on="industry_code", how="left")
    else:
        out = out.with_columns(pl.lit(None, dtype=pl.Float64).alias("import_penetration"))

    # Classify, without ever collapsing the two channels into one number.
    prot = pl.col("output_protection_exposure")
    cost = pl.col("imported_input_cost_exposure")
    p_thr = 0.01
    c_thr = 0.005
    return out.with_columns(
        (prot > p_thr).alias("protected_channel_active"),
        (cost > c_thr).alias("input_cost_channel_active"),
        pl.when((prot > p_thr) & (cost > c_thr))
        .then(pl.lit("BOTH_PROTECTED_AND_COST_EXPOSED"))
        .when(prot > p_thr)
        .then(pl.lit("PROTECTED_ONLY"))
        .when(cost > c_thr)
        .then(pl.lit("INPUT_COST_EXPOSED_ONLY"))
        .otherwise(pl.lit("LITTLE_DIRECT_EXPOSURE"))
        .alias("exposure_class"),
        # Reported only as a descriptive contrast, never as "the" exposure.
        (prot - cost).alias("net_contrast_do_not_use_alone"),
    ).sort("imported_input_cost_exposure", descending=True)


def summarize(exposure: pl.DataFrame) -> pl.DataFrame:
    return (
        exposure.group_by("exposure_class")
        .agg(
            pl.len().alias("n_industries"),
            pl.col("output_protection_exposure").mean().alias("mean_protection"),
            pl.col("imported_input_cost_exposure").mean().alias("mean_input_cost"),
            pl.col("downstream_total_requirements_exposure").mean().alias("mean_downstream"),
        )
        .sort("n_industries", descending=True)
    )
