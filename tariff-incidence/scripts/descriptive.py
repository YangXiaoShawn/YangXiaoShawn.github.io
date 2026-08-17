#!/usr/bin/env python
"""Descriptive trade analysis.

    python scripts/descriptive.py

Nominal value growth and real quantity change are reported separately, because
a rise in customs value is not a rise in quantity.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import polars as pl  # noqa: E402

from tariff_incidence.config import load_config  # noqa: E402
from tariff_incidence.paths import ensure_layers, layer_path  # noqa: E402
from tariff_incidence.provenance import DataProvenance, RunStamp  # noqa: E402


def main() -> int:
    ensure_layers()
    cfg = load_config("sample_slice.yaml")
    panel = pl.read_parquet(layer_path("analytical", "trade_panel.parquet"))
    provenance = DataProvenance(
        json.loads((layer_path("analytical", "trade_panel.runstamp.json")).read_text())[
            "data_provenance"
        ]
    )
    stamp = RunStamp.create(
        config_name=cfg.config_name,
        config_bytes=cfg.raw_bytes,
        data_provenance=provenance,
        data_period_start=cfg.sample.start_month,
        data_period_end=cfg.sample.end_month,
    )
    print(stamp.banner())
    treated_country = cfg.sample.treated_country_code

    def w(df: pl.DataFrame, name: str) -> None:
        df.with_columns(
            pl.lit(stamp.run_id).alias("run_id"),
            pl.lit(stamp.git_commit).alias("git_commit"),
            pl.lit(stamp.data_provenance.value).alias("data_provenance"),
        ).write_parquet(layer_path("results", f"{name}.parquet"))

    # Monthly aggregates: nominal value vs real quantity, kept apart.
    monthly = (
        panel.group_by(["month_date", "is_treated_country"])
        .agg(
            pl.col("customs_value").sum().alias("customs_value"),
            pl.col("quantity").sum().alias("quantity"),
            pl.col("calculated_duties").sum().alias("calculated_duties"),
            pl.col("dutiable_value").sum().alias("dutiable_value"),
            pl.col("hs6").n_unique().alias("n_products"),
        )
        .with_columns(
            pl.when(pl.col("dutiable_value") > 0)
            .then(pl.col("calculated_duties") / pl.col("dutiable_value"))
            .otherwise(None)
            .alias("trade_weighted_realised_duty_rate"),
            pl.when(pl.col("quantity") > 0)
            .then(pl.col("customs_value") / pl.col("quantity"))
            .otherwise(None)
            .alias("aggregate_customs_unit_value"),
        )
        .sort(["month_date", "is_treated_country"])
    )
    w(monthly, "descriptive_monthly_aggregates")

    # Treated-country share over time, by treatment group.
    share = (
        panel.group_by(["month_date", "ever_treated_product"])
        .agg(
            pl.col("customs_value").sum().alias("total_value"),
            pl.when(pl.col("country_code") == treated_country)
            .then(pl.col("customs_value"))
            .otherwise(0.0)
            .sum()
            .alias("treated_country_value"),
        )
        .with_columns(
            (pl.col("treated_country_value") / pl.col("total_value")).alias(
                "treated_country_share"
            )
        )
        .sort(["ever_treated_product", "month_date"])
    )
    w(share, "descriptive_treated_country_share")

    # Trade-weighted tariff rate over time.
    twt = (
        panel.filter(pl.col("country_code") == treated_country)
        .group_by("month_date")
        .agg(
            (
                (pl.col("additional_tariff_rate") * pl.col("customs_value")).sum()
                / pl.col("customs_value").sum()
            ).alias("trade_weighted_additional_tariff"),
            pl.col("customs_value").sum().alias("customs_value"),
        )
        .sort("month_date")
    )
    w(twt, "descriptive_trade_weighted_tariff")

    # Supplier concentration and product variety.
    conc = (
        panel.group_by(["month_date", "ever_treated_product"])
        .agg(
            pl.col("supplier_hhi_in_sample").mean().alias("mean_supplier_hhi_in_sample"),
            pl.col("supplier_count_in_sample").mean().alias("mean_supplier_count"),
            pl.col("flow_entry").sum().alias("flow_entries"),
            pl.col("flow_exit").sum().alias("flow_exits"),
        )
        .sort(["ever_treated_product", "month_date"])
    )
    w(conc, "descriptive_concentration_and_variety")

    # Sector heterogeneity in pre-treatment exposure.
    sector = (
        panel.group_by("hs2_chapter")
        .agg(
            pl.col("hs6").n_unique().alias("n_products"),
            pl.col("ever_treated_product").mean().alias("share_products_treated"),
            pl.col("pretreatment_treated_country_share").mean().alias("mean_pretreat_dependence"),
            pl.col("customs_value").sum().alias("customs_value"),
        )
        .sort("customs_value", descending=True)
    )
    w(sector, "descriptive_sector_heterogeneity")

    print("Monthly aggregates (last 6 rows):")
    print(monthly.tail(6))
    print("\nTrade-weighted additional tariff on the treated country (last 6 months):")
    print(twt.tail(6))
    print("\nSector heterogeneity:")
    print(sector)
    print(
        "\nNote: nominal customs value and real quantity are reported as separate series. "
        "A rise in value is not a rise in volume."
    )
    stamp.write(layer_path("results", "descriptive.runstamp.json"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
