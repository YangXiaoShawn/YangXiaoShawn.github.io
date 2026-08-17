#!/usr/bin/env python
"""Do the result tables agree with each other?

    python scripts/check_consistency.py [--fail-on-error]

The data-quality battery validates the panel against itself, and the test suite
exercises code against fixtures. Neither compares one finished artefact against
another, and that is where every defect found by reading the eleven generated
reports end to end actually lived: a heterogeneity table that summed to 3.16x
the totals it partitioned, an exclusion bound whose denominator held six months
of trade the tariff never touched, a specification register naming a level the
panel had not used for four sessions, headline figures typed into a report as
literals and drifted from the tables below them.

Each was a stated identity that nothing evaluated. This step evaluates them, so
the next one fails a run instead of waiting to be read.

Runs after the estimation scripts and before the reports, since it is the
reports that would otherwise carry the disagreement to a reader.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import polars as pl  # noqa: E402

from tariff_incidence.config import load_config  # noqa: E402
from tariff_incidence.paths import RESULTS, ensure_layers, layer_path  # noqa: E402
from tariff_incidence.provenance import DataProvenance, RunStamp  # noqa: E402
from tariff_incidence.quality import checks, consistency  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="sample_slice.yaml")
    ap.add_argument("--fail-on-error", action="store_true")
    args = ap.parse_args()
    ensure_layers()

    cfg = load_config(args.config)
    panel_path = layer_path("analytical", "trade_panel.parquet")
    panel = pl.read_parquet(panel_path) if panel_path.exists() else None
    prov_path = layer_path("analytical", "trade_panel.runstamp.json")
    provenance = (
        DataProvenance(json.loads(prov_path.read_text())["data_provenance"])
        if prov_path.exists()
        else DataProvenance.SYNTHETIC_PIPELINE_VALIDATION
    )

    results = consistency.run_all(RESULTS, panel)
    frame = checks.to_frame(results)
    summary = checks.summarize(results)

    stamp = RunStamp.create(
        config_name=cfg.config_name,
        config_bytes=cfg.raw_bytes,
        data_provenance=provenance,
        data_period_start=cfg.sample.start_month,
        data_period_end=cfg.sample.end_month,
        notes="cross-artefact consistency of the result tables",
    )
    frame.with_columns(
        pl.lit(stamp.run_id).alias("run_id"),
        pl.lit(stamp.git_commit).alias("git_commit"),
        pl.lit(stamp.data_provenance.value).alias("data_provenance"),
    ).write_parquet(layer_path("results", "consistency_report.parquet"))
    (layer_path("results", "consistency_summary.json")).write_text(
        json.dumps({"run": stamp.to_dict(), "summary": summary}, indent=2, default=str) + "\n"
    )

    print(stamp.banner())
    with pl.Config(tbl_rows=40, fmt_str_lengths=90, tbl_width_chars=220):
        print(frame.select(["check_id", "status", "detail"]))
    print(
        f"\n{summary['n_passed']} passed, {summary['n_failed']} failed, "
        f"{summary['n_skipped']} skipped"
    )

    if summary["blocking"]:
        print(f"\nBLOCKING inconsistencies: {summary['blocking']}")
        print(
            "Two artefacts disagree. Fix the one that is wrong rather than loosening "
            "the check: the identity is what makes the reports trustworthy."
        )
        if args.fail_on_error:
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
