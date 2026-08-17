#!/usr/bin/env python
"""Armington sourcing counterfactuals, labelled model-implied throughout.

    python scripts/structural_counterfactual.py [--sigma 2 4 6 ...]

What this is, and is not
------------------------

A one-tier CES nest across **foreign source countries** within a product. It says
how import sourcing should have reallocated given the tariff, and what the
imported bundle cost. It is not a welfare model: there is no domestic nest, no
labour market and no revenue recycling, so no welfare number is produced and the
reporting guard that blocks welfare claims stays in force.

The elasticity is never fabricated. It arrives three ways, reported side by side
because agreement between them is the interesting quantity:

1. **Calibrated grid** -- supplied by ``--sigma``, labelled ``CALIBRATED``.
2. **Inverted from this project's own reduced form** -- the PPML quantity
   response on ``log(1 + tariff)`` identifies sigma directly.
3. **Fitted to the observed reallocation** -- the sigma whose counterfactual
   shares best match what sourcing actually did.

Route 2 and route 3 use different data (quantities against shares) and different
machinery, so they are close to independent. If they land in the same region the
model is doing something; if they do not, that is the finding and it is reported
as one.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np  # noqa: E402
import polars as pl  # noqa: E402

from tariff_incidence.config import load_config  # noqa: E402
from tariff_incidence.manifest import DatasetManifest  # noqa: E402
from tariff_incidence.paths import ensure_layers, layer_path  # noqa: E402
from tariff_incidence.provenance import DataProvenance, RunStamp  # noqa: E402
from tariff_incidence.structural.armington import (  # noqa: E402
    ParameterType,
    build_counterfactual,
    implied_sigma_from_reduced_form,
)


def _pre_post_shares(panel: pl.DataFrame, treated_country: str) -> tuple[pl.DataFrame, float]:
    """Pre-treatment sourcing shares, the tariff change, and observed post shares.

    The tariff change is the post-period average additional rate on the line, so
    a product tariffed mid-window carries the rate it actually faced rather than
    its statutory peak.
    """
    pre = panel.filter(pl.col("event_time") < 0)
    post = panel.filter(pl.col("event_time") >= 0)

    def _shares(d: pl.DataFrame, name: str) -> pl.DataFrame:
        # A product with zero value in the window gives 0/0. Polars returns NaN
        # there, and NaN is not null, so fill_null leaves it in place to
        # propagate silently through every weighted mean downstream -- which is
        # exactly what it did on the first run. Produce a null instead and let
        # the caller decide, rather than carrying a NaN that still looks numeric.
        g = d.group_by(["hs10", "country_code"]).agg(
            pl.col("customs_value").sum().alias("_v")
        )
        total = pl.col("_v").sum().over("hs10")
        return g.with_columns(
            pl.when(total > 0).then(pl.col("_v") / total).otherwise(None).alias(name)
        ).rename({"_v": f"{name}_value"})

    s_pre = _shares(pre, "share_pre")
    s_post = _shares(post, "share_post")

    tau = (
        post.group_by(["hs10", "country_code"])
        .agg(pl.col("additional_tariff_rate").mean().alias("tariff_change"))
        .with_columns(pl.col("tariff_change").fill_null(0.0))
    )

    shares = (
        s_pre.join(tau, on=["hs10", "country_code"], how="left")
        .join(s_post.select(["hs10", "country_code", "share_post"]),
              on=["hs10", "country_code"], how="left")
        .with_columns(
            pl.col("tariff_change").fill_null(0.0),
            pl.col("share_post").fill_null(0.0),
            pl.col("share_pre_value").alias("pre_value"),
        )
    )
    # Only products where the treated source was actually present pre-treatment
    # can speak to reallocation away from it.
    keep = (
        shares.filter((pl.col("country_code") == treated_country) & (pl.col("share_pre") > 0))
        ["hs10"].unique().to_list()
    )
    shares = shares.filter(pl.col("hs10").is_in(keep))

    mean_log1p = float(
        (
            post.filter(pl.col("country_code") == treated_country)
            .select((1.0 + pl.col("additional_tariff_rate")).log().mean())
            .item()
        )
        or 0.0
    )
    return shares, mean_log1p


def _fit_sigma(shares: pl.DataFrame, treated_country: str, grid: np.ndarray) -> tuple[float, float]:
    """The sigma whose counterfactual treated share best matches the observed one.

    Fitted on the value-weighted treated-source share, not on every cell: a
    per-cell fit would chase composition noise in small products, and the share
    of sourcing that left the treated country is the moment the model is meant
    to speak to.
    """
    # Weight by the product's TOTAL pre-treatment value, not the treated source's
    # own value in it. Weighting a country's share by that country's own value
    # over-weights the products it already dominated: on the first run it turned
    # an observed treated share of 0.19 into 0.49 and made the model look as
    # though it had the sign of the reallocation backwards. `build_counterfactual`
    # weights by product totals, so anything compared against it must too.
    totals = shares.group_by("hs10").agg(pl.col("pre_value").sum().alias("_tot"))
    trt = (
        shares.filter(
            (pl.col("country_code") == treated_country) & pl.col("share_post").is_not_null()
        )
        .join(totals, on="hs10", how="left")
    )
    w = trt["_tot"].to_numpy()
    observed = float((trt["share_post"].to_numpy() * w).sum() / w.sum()) if w.sum() else 0.0
    if not np.isfinite(observed):
        raise ValueError(
            "observed treated-source share is not finite; a share was NaN rather than "
            "null and propagated through the weighted mean"
        )

    best_s, best_err = float("nan"), float("inf")
    for s in grid:
        cf = build_counterfactual(shares, sigma=float(s), treated_country=treated_country)
        err = abs(cf.treated_share_counterfactual - observed)
        if err < best_err:
            best_s, best_err = float(s), err
    return best_s, observed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="sample_slice.yaml")
    ap.add_argument(
        "--sigma", type=float, nargs="+", default=[1.5, 2.0, 3.0, 4.0, 6.0, 8.0],
        help="calibrated elasticity grid; every output is labelled CALIBRATED",
    )
    args = ap.parse_args()
    ensure_layers()

    cfg = load_config(args.config)
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
        notes="one-tier Armington sourcing counterfactual; no domestic nest, no welfare",
    )
    print(stamp.banner())

    treated = cfg.sample.treated_country_code
    shares, mean_log1p = _pre_post_shares(panel, treated)
    print(
        f"calibration sample: {shares['hs10'].n_unique():,} products x "
        f"{shares['country_code'].n_unique()} sources, "
        f"{shares.height:,} cells; mean log(1+tau) on treated flows = {mean_log1p:.4f}"
    )

    # ---- route 2: invert this project's own reduced-form quantity response ----
    est_path = layer_path("results", "incidence_estimates.parquet")
    implied = None
    ppml_beta = None
    if est_path.exists():
        e = pl.read_parquet(est_path)
        q = e.filter(
            (pl.col("term") == "log1p_additional_tariff") & (pl.col("outcome") == "quantity")
        )
        if q.height:
            ppml_beta = float(q["estimate"][0])
            implied = implied_sigma_from_reduced_form(ppml_beta, mean_log1p)

    # ---- route 3: fit to the observed reallocation ----
    fine = np.arange(0.25, 20.01, 0.25)
    fitted, observed_treated_post = _fit_sigma(shares, treated, fine)

    rows: list[dict] = []
    for s in args.sigma:
        cf = build_counterfactual(shares, sigma=float(s), treated_country=treated)
        rows.append(
            {
                "sigma": float(s),
                "sigma_source": "calibrated grid",
                "parameter_type": ParameterType.CALIBRATED.value,
                "treated_share_pre": cf.treated_share_pre,
                "treated_share_model": cf.treated_share_counterfactual,
                "treated_share_observed": observed_treated_post,
                "model_minus_observed": cf.treated_share_counterfactual - observed_treated_post,
                "log_import_bundle_cost_change": cf.aggregate_log_price_index_change,
            }
        )
    for s, label in ((implied, "inverted from PPML quantity response"),
                     (fitted, "fitted to observed reallocation")):
        if s is None or not np.isfinite(s):
            continue
        cf = build_counterfactual(shares, sigma=float(s), treated_country=treated)
        rows.append(
            {
                "sigma": float(s),
                "sigma_source": label,
                "parameter_type": ParameterType.MODEL_IMPLIED.value,
                "treated_share_pre": cf.treated_share_pre,
                "treated_share_model": cf.treated_share_counterfactual,
                "treated_share_observed": observed_treated_post,
                "model_minus_observed": cf.treated_share_counterfactual - observed_treated_post,
                "log_import_bundle_cost_change": cf.aggregate_log_price_index_change,
            }
        )

    res = pl.DataFrame(rows).with_columns(
        pl.lit(stamp.run_id).alias("run_id"),
        pl.lit(stamp.git_commit).alias("git_commit"),
        pl.lit(stamp.data_provenance.value).alias("data_provenance"),
    )
    out = layer_path("results", "structural_sourcing_counterfactual.parquet")
    res.write_parquet(out)

    ledger = pl.DataFrame(
        [
            {"quantity": "pre-treatment sourcing shares", "value": None,
             "parameter_type": ParameterType.DATA_MOMENT.value,
             "source": "trade panel, event months < 0"},
            {"quantity": "post-period additional tariff rate", "value": None,
             "parameter_type": ParameterType.DATA_MOMENT.value,
             "source": "tariff engine; statutory schedule"},
            {"quantity": "observed treated-source share, post", "value": observed_treated_post,
             "parameter_type": ParameterType.DATA_MOMENT.value,
             "source": "trade panel, event months >= 0"},
            {"quantity": "PPML quantity response to log(1+tariff)", "value": ppml_beta,
             "parameter_type": ParameterType.ESTIMATED.value,
             "source": "this project, rung 5"},
            {"quantity": "customs unit value response (bounded null)", "value": None,
             "parameter_type": ParameterType.ESTIMATED.value,
             "source": "this project, stacked design -- supplies the fixed-foreign-price premise"},
            {"quantity": "elasticity of substitution sigma", "value": None,
             "parameter_type": ParameterType.CALIBRATED.value,
             "source": f"grid {args.sigma}, supplied by configuration; not estimated here"},
            {"quantity": "counterfactual sourcing shares", "value": None,
             "parameter_type": ParameterType.MODEL_IMPLIED.value,
             "source": "CES hat algebra"},
            {"quantity": "import bundle cost change", "value": None,
             "parameter_type": ParameterType.MODEL_IMPLIED.value,
             "source": "exact CES price index"},
        ]
    )
    ledger.write_parquet(layer_path("results", "structural_parameter_ledger.parquet"))

    summary = {
        "run": stamp.to_dict(),
        "scope": (
            "One-tier CES nest across foreign source countries within a product. No "
            "domestic nest: U.S. import statistics cannot say how much of a fall in "
            "imports went to domestic producers rather than out of consumption, so that "
            "margin is outside the model rather than assumed. No welfare number is "
            "produced and none can be derived from these outputs alone."
        ),
        "premise": (
            "Foreign producer prices are held fixed, so the tariff passes into the "
            "buyer's price one-for-one. In this project that is a reduced-form finding "
            "-- the customs unit value response is a bounded null, at most 0.076 log "
            "points -- rather than a free assumption. The structural and reduced-form "
            "modules are therefore not independent readings of the same data."
        ),
        "sigma_routes": {
            "calibrated_grid": args.sigma,
            "inverted_from_ppml_quantity_response": implied,
            "fitted_to_observed_reallocation": fitted,
            "ppml_beta_used": ppml_beta,
            "mean_log1p_tariff_on_treated_flows": mean_log1p,
        },
        "observed_treated_share_post": observed_treated_post,
        "n_products": int(shares["hs10"].n_unique()),
    }
    (layer_path("results", "structural_summary.json")).write_text(
        json.dumps(summary, indent=2, default=str) + "\n"
    )
    stamp.write(layer_path("results", "structural.runstamp.json"))

    DatasetManifest.for_file(
        out,
        dataset_id="structural_sourcing_counterfactual",
        layer="results",
        source="Armington/CES one-tier sourcing model over this project's trade panel",
        source_url="",
        source_release_or_vintage=cfg.config_name,
        schema_version="structural_v1",
        transformation_version="structural_counterfactual.py@v1",
        row_count=res.height,
        data_provenance=provenance,
        date_range=(cfg.sample.start_month, cfg.sample.end_month),
        known_limitations=[
            "One-tier nest over foreign sources only. No domestic alternative, so the "
            "model cannot say whether displaced imports went to U.S. producers or out of "
            "consumption.",
            "sigma is calibrated, not estimated. Every quantity scales with it and the "
            "grid is reported rather than a single preferred value.",
            "Holds foreign producer prices fixed. Supported here by the reduced-form "
            "bounded null on the customs unit value, which is itself an estimate with an "
            "interval, not a certainty.",
            "No welfare, deadweight loss or consumer-cost number is produced. The import "
            "bundle cost change is one component of such a calculation, not the result.",
        ],
        columns={c: str(t) for c, t in zip(res.columns, res.dtypes, strict=True)},
    ).write()

    with pl.Config(tbl_rows=20, fmt_str_lengths=40, tbl_width_chars=200):
        print("\n" + str(res.select([
            "sigma", "sigma_source", "treated_share_pre", "treated_share_model",
            "treated_share_observed", "log_import_bundle_cost_change",
        ])))
    print(f"\nsigma inverted from the PPML quantity response : {implied}")
    print(f"sigma fitted to the observed reallocation      : {fitted}")
    print(f"\nwrote {out} (run_id={stamp.run_id})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
