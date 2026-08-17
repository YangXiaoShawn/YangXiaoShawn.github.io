#!/usr/bin/env python
"""Do the two exposure channels show up in domestic producer prices?

    python scripts/estimate_propagation.py

This is the outcome test the industry-exposure accounting has been waiting for.
Exposure is a construct built from input-output weights; whether it predicts
anything is a separate question, and until now the project could only assert
that the channels exist, not that they bite.

The two channels are estimated **separately**, never netted, because they push
in opposite directions: output protection should raise an industry's own price,
imported-input cost should raise it too but for a different reason, and an
industry exposed to both is the interesting case rather than a wash.

Inference caveat, stated up front. At the BEA summary level there are 22
industries with a matched PPI series, so 22 clusters, and cluster-robust standard
errors over-reject badly at that count. ``--level detail`` raises it to 256. Every
coefficient carries a wild cluster bootstrap p-value regardless, and where the two
disagree the bootstrap is the one to read.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np  # noqa: E402
import polars as pl  # noqa: E402

from tariff_incidence.adapters import bea_io, bls_ppi  # noqa: E402
from tariff_incidence.adapters.base import SourceUnavailable  # noqa: E402
from tariff_incidence.config import load_config  # noqa: E402
from tariff_incidence.econ.hdfe import ols_hdfe, wild_cluster_bootstrap  # noqa: E402
from tariff_incidence.manifest import DatasetManifest  # noqa: E402
from tariff_incidence.paths import ensure_layers, layer_path  # noqa: E402
from tariff_incidence.provenance import DataProvenance, RunStamp  # noqa: E402

CHANNELS = {
    "imported_input_cost_exposure": (
        "imported-input cost exposure -- tariffs on what the industry buys"
    ),
    "output_protection_exposure": (
        "output protection exposure -- tariffs on what competes with what it sells"
    ),
    "downstream_total_requirements_exposure": (
        "downstream exposure through the full Leontief chain"
    ),
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="sample_slice.yaml")
    ap.add_argument("--first-treatment-month", default="2018-07")
    ap.add_argument("--n-boot", type=int, default=999)
    ap.add_argument("--level", choices=["summary", "detail"], default="summary",
                    help="BEA industry granularity of the exposure file to test")
    args = ap.parse_args()
    ensure_layers()
    suffix = "" if args.level == "summary" else f"_{args.level}"

    cfg = load_config(args.config)
    expo_path = layer_path("results", f"industry_tariff_exposure{suffix}.parquet")
    if not expo_path.exists():
        print(f"industry exposure not found at {expo_path.name}; run "
              f"'make build-io-exposure' (level={args.level}) first")
        return 1
    expo = pl.read_parquet(expo_path)

    y0 = int(cfg.sample.start_month.split("-")[0])
    y1 = int(cfg.sample.end_month.split("-")[0])
    industries = expo["industry_code"].unique().to_list()

    # At detail level the industry-to-NAICS relation comes from BEA's own
    # published 'NAICS Codes' sheet rather than the hand-coded summary map.
    components: dict[str, tuple[str, ...]] | None = None
    if args.level == "detail":
        components = bea_io.detail_naics_components(industries)
        print(
            f"{len(components)} of {len(industries)} detail industries have a NAICS relation "
            "in BEA's own sheet"
        )
    try:
        load = bls_ppi.fetch_industry_ppi(industries, y0, y1, components=components)
    except SourceUnavailable as exc:
        print(f"BLS PPI unavailable: {exc}")
        print("Cannot test propagation into domestic prices without it. Nothing written.")
        return 1

    ppi = bls_ppi.to_bea_panel(load)
    if ppi.height == 0:
        print("no PPI observations returned; nothing to estimate")
        return 1

    print(
        f"PPI: {load.n_series_returned}/{load.n_series_requested} series, "
        f"{ppi['bea_industry'].n_unique()} BEA industries x {ppi['month_date'].n_unique()} months"
    )
    for w in load.warnings:
        print(f"  ! {w}")

    yy, mm = (int(x) for x in args.first_treatment_month.split("-"))
    first_idx = yy * 12 + mm

    panel = (
        ppi.join(expo, left_on="bea_industry", right_on="industry_code", how="inner")
        .with_columns(
            (pl.col("month_index") >= first_idx).cast(pl.Float64).alias("post"),
            pl.col("month_date").dt.strftime("%Y-%m").alias("month_key"),
        )
        .drop_nulls(subset=["log_ppi"])
    )
    n_ind = panel["bea_industry"].n_unique()
    print(
        f"\nestimation panel: {panel.height:,} industry-months, {n_ind} industries "
        f"({panel['month_date'].n_unique()} months), post from {args.first_treatment_month}"
    )
    if n_ind < 30:
        print(
            f"  ! only {n_ind} clusters. Cluster-robust standard errors over-reject at this "
            "count, so a wild cluster bootstrap p-value is reported alongside every "
            "analytic one."
        )

    rows: list[dict] = []
    for channel, label in CHANNELS.items():
        if channel not in panel.columns:
            continue
        d = panel.with_columns(
            (pl.col(channel) * pl.col("post")).alias("exposure_x_post")
        ).drop_nulls(subset=["exposure_x_post"])
        y = d["log_ppi"].to_numpy()
        X = d["exposure_x_post"].to_numpy()[:, None]
        fe = {"industry": d["bea_industry"].to_numpy(), "month": d["month_key"].to_numpy()}
        cl = d["bea_industry"].to_numpy()

        fit = ols_hdfe(y, X, ["exposure_x_post"], fe, {"industry": cl})
        boot = wild_cluster_bootstrap(
            y, X, ["exposure_x_post"], fe, cl, n_boot=args.n_boot
        )
        lo, hi = fit.conf_int("exposure_x_post")
        rows.append(
            {
                "channel": channel,
                "channel_label": label,
                "estimate": fit.params["exposure_x_post"],
                "std_error": fit.std_errors["exposure_x_post"],
                "ci_low": lo,
                "ci_high": hi,
                "analytic_p_value": fit.pvalue("exposure_x_post"),
                "bootstrap_p_value": boot["bootstrap_p_value"],
                "n_obs": fit.n_obs,
                "n_clusters": n_ind,
                "n_boot": boot["n_boot"],
            }
        )
        print(
            f"  {channel:42s} beta={fit.params['exposure_x_post']:+.4f} "
            f"[{lo:+.4f}, {hi:+.4f}]  analytic p={fit.pvalue('exposure_x_post'):.3f}  "
            f"bootstrap p={boot['bootstrap_p_value']:.3f}"
        )

    # Both channels together, so an industry exposed on both sides is not forced
    # to load onto whichever one is entered alone.
    both = panel.with_columns(
        (pl.col("imported_input_cost_exposure") * pl.col("post")).alias("input_cost_x_post"),
        (pl.col("output_protection_exposure") * pl.col("post")).alias("protection_x_post"),
    ).drop_nulls(subset=["input_cost_x_post", "protection_x_post"])
    y = both["log_ppi"].to_numpy()
    X = np.column_stack(
        [both["input_cost_x_post"].to_numpy(), both["protection_x_post"].to_numpy()]
    )
    fe = {"industry": both["bea_industry"].to_numpy(), "month": both["month_key"].to_numpy()}
    cl = both["bea_industry"].to_numpy()
    joint = ols_hdfe(y, X, ["input_cost_x_post", "protection_x_post"], fe, {"industry": cl})
    print("\n  both channels entered together (they are never netted):")
    for i, nm in enumerate(["input_cost_x_post", "protection_x_post"]):
        b = wild_cluster_bootstrap(
            y, X, ["input_cost_x_post", "protection_x_post"], fe, cl,
            test_index=i, n_boot=args.n_boot,
        )
        lo, hi = joint.conf_int(nm)
        rows.append(
            {
                "channel": f"joint::{nm}",
                "channel_label": f"{nm} (both channels in one specification)",
                "estimate": joint.params[nm],
                "std_error": joint.std_errors[nm],
                "ci_low": lo,
                "ci_high": hi,
                "analytic_p_value": joint.pvalue(nm),
                "bootstrap_p_value": b["bootstrap_p_value"],
                "n_obs": joint.n_obs,
                "n_clusters": n_ind,
                "n_boot": b["n_boot"],
            }
        )
        print(
            f"    {nm:24s} beta={joint.params[nm]:+.4f} [{lo:+.4f}, {hi:+.4f}]  "
            f"analytic p={joint.pvalue(nm):.3f}  bootstrap p={b['bootstrap_p_value']:.3f}"
        )

    trade_prov = DataProvenance(
        json.loads((layer_path("analytical", "trade_panel.runstamp.json")).read_text())[
            "data_provenance"
        ]
    )
    stamp = RunStamp.create(
        config_name=cfg.config_name,
        config_bytes=cfg.raw_bytes,
        data_provenance=trade_prov,
        data_period_start=cfg.sample.start_month,
        data_period_end=cfg.sample.end_month,
        notes="BLS PPI (NAICS industry classification) x BEA industry exposure",
    )
    res = pl.DataFrame(rows).with_columns(
        pl.lit(stamp.run_id).alias("run_id"),
        pl.lit(stamp.git_commit).alias("git_commit"),
        pl.lit(stamp.data_provenance.value).alias("data_provenance"),
    )
    out = layer_path("results", f"propagation_ppi_estimates{suffix}.parquet")
    res.write_parquet(out)
    ppi.write_parquet(layer_path("results", f"ppi_industry_month_panel{suffix}.parquet"))
    load.industry_match.write_parquet(layer_path("results", f"ppi_industry_match{suffix}.parquet"))
    stamp.write(layer_path("results", f"propagation{suffix}.runstamp.json"))

    (layer_path("results", f"propagation_quality{suffix}.json")).write_text(
        json.dumps(
            {
                "run": stamp.to_dict(),
                "n_industries": n_ind,
                "bea_level": args.level,
                "n_series_requested": load.n_series_requested,
                "n_series_returned": load.n_series_returned,
                "warnings": load.warnings,
                "inference_note": (
                    f"{n_ind} clusters. Cluster-robust standard errors over-reject with few "
                    "clusters, so a wild cluster bootstrap p-value with the null imposed is "
                    "reported for every coefficient. Where the two disagree, read the "
                    "bootstrap."
                ),
                "aggregation_note": (
                    "PPI industry indices are aggregates over an entire NAICS group, while "
                    "tariff exposure is built from 10-digit trade lines. Composite BEA "
                    "industries average their component series unweighted, since NAICS-level "
                    "output weights are unavailable at that granularity. Both facts attenuate "
                    "any true relationship toward zero."
                ),
            },
            indent=2,
            default=str,
        )
        + "\n"
    )

    DatasetManifest.for_file(
        out,
        dataset_id=f"propagation_ppi_estimates{suffix}",
        layer="results",
        source="BLS Producer Price Index (NAICS industry classification), API v1",
        source_url=bls_ppi.BLS_V1,
        source_release_or_vintage=f"{y0}-{y1}",
        schema_version="propagation_v1",
        transformation_version="estimate_propagation.py@v1",
        row_count=res.height,
        data_provenance=trade_prov,
        date_range=(cfg.sample.start_month, cfg.sample.end_month),
        known_limitations=[
            f"{n_ind} clusters; analytic cluster-robust p-values over-reject and a wild "
            "cluster bootstrap is reported alongside.",
            "Agriculture and forestry (BEA 111CA, 113FF) have no NAICS-industry PPI and are "
            "absent from the estimation panel entirely.",
            "Composite BEA industries average component PPI series unweighted, because "
            "NAICS-component output weights are not available in the BEA summary tables.",
            "PPI industry indices cover an entire NAICS group while exposure is built from "
            "10-digit lines; the aggregation gap attenuates any true relationship.",
        ],
        columns={c: str(t) for c, t in zip(res.columns, res.dtypes, strict=True)},
    ).write()

    print(f"\nwrote {out} (run_id={stamp.run_id})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
