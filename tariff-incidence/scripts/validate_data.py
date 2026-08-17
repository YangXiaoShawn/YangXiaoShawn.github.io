#!/usr/bin/env python
"""Run the data-quality battery over the analytical panel.

    python scripts/validate_data.py [--fail-on-error]

Every check reports PASS, FAIL or SKIPPED. A check that could not run is never
reported as passing.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import polars as pl  # noqa: E402

from tariff_incidence.config import load_config  # noqa: E402
from tariff_incidence.paths import ensure_layers, layer_path  # noqa: E402
from tariff_incidence.provenance import DataProvenance, RunStamp  # noqa: E402
from tariff_incidence.quality import checks  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="sample_slice.yaml")
    ap.add_argument("--fail-on-error", action="store_true")
    args = ap.parse_args()
    ensure_layers()

    cfg = load_config(args.config)
    panel_path = layer_path("analytical", "trade_panel.parquet")
    if not panel_path.exists():
        print("no analytical panel found; run make build-trade-panel first")
        return 1
    panel = pl.read_parquet(panel_path)
    provenance = DataProvenance(
        json.loads((layer_path("analytical", "trade_panel.runstamp.json")).read_text())[
            "data_provenance"
        ]
    )
    valid = {cfg.sample.treated_country_code, *cfg.sample.comparison_country_codes}
    # The battery must key on the panel's own product level. Keying an HS10
    # panel on hs6 would report every HS10 sibling as a duplicate.
    product_col = "hs10" if "hs10" in panel.columns else "hs6"
    print(f"panel product level: {product_col}")

    results = checks.run_all(panel, valid_country_codes=valid, product_col=product_col)
    frame = checks.to_frame(results)
    summary = checks.summarize(results)

    stamp = RunStamp.create(
        config_name=cfg.config_name,
        config_bytes=cfg.raw_bytes,
        data_provenance=provenance,
        data_period_start=cfg.sample.start_month,
        data_period_end=cfg.sample.end_month,
    )
    frame.with_columns(
        pl.lit(stamp.run_id).alias("run_id"),
        pl.lit(stamp.git_commit).alias("git_commit"),
        pl.lit(stamp.data_provenance.value).alias("data_provenance"),
    ).write_parquet(layer_path("results", "data_quality_report.parquet"))
    (layer_path("results", "data_quality_summary.json")).write_text(
        json.dumps({"run": stamp.to_dict(), "summary": summary}, indent=2, default=str) + "\n"
    )

    print(stamp.banner())
    with pl.Config(tbl_rows=40, fmt_str_lengths=70, tbl_width_chars=200):
        print(frame.select(["check_id", "status", "severity", "n_flagged", "n_total", "detail"]))
    print(
        f"\n{summary['n_passed']} passed, {summary['n_failed']} failed, "
        f"{summary['n_skipped']} skipped"
    )
    for r in results:
        if r.passed is False and r.examples:
            print(f"\n{r.check_id} examples:")
            for e in r.examples:
                print("   ", e)

    if summary["blocking"]:
        print(f"\nBLOCKING failures (severity ERROR): {summary['blocking']}")
        if args.fail_on_error:
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
