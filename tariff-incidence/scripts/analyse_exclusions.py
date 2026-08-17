#!/usr/bin/env python
"""Quantify how far exclusions can move the intention-to-treat estimates.

    python scripts/analyse_exclusions.py [--offline]

Exclusion adjustment cannot be performed from published trade statistics, for
reasons that are structural rather than technical (see the adapter docstring).
This script establishes that quantitatively rather than asserting it, and then
bounds the resulting gap empirically.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import polars as pl  # noqa: E402

from tariff_incidence.adapters import ustr_exclusions as ux  # noqa: E402
from tariff_incidence.adapters.base import SourceUnavailable  # noqa: E402
from tariff_incidence.config import load_config  # noqa: E402
from tariff_incidence.manifest import DatasetManifest  # noqa: E402
from tariff_incidence.paths import RAW, ensure_layers, layer_path  # noqa: E402
from tariff_incidence.provenance import DataProvenance, RunStamp  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="sample_slice.yaml")
    ap.add_argument("--offline", action="store_true")
    args = ap.parse_args()
    ensure_layers()

    cfg = load_config(args.config)
    try:
        notices = ux.load_notices(
            ux.SAMPLE_WINDOW_NOTICES,
            offline_dir=(RAW / "federal_register") if args.offline else None,
        )
    except (SourceUnavailable, FileNotFoundError) as exc:
        print(f"exclusion notices unavailable: {exc}")
        return 1

    frame = pl.DataFrame([n.to_row() for n in notices])
    summary = ux.coverage_summary(notices)

    print("Exclusion notices covering the sample window\n")
    print(
        frame.select(
            ["document_number", "publication_date", "n_ten_digit_exclusions",
             "n_prose_exclusions", "retroactive_to", "expires", "annex_is_image_only"]
        )
    )
    print(
        f"\n{summary['n_ten_digit_exclusions']} exclusions expressed as a 10-digit subheading; "
        f"{summary['n_prose_exclusions']} as a product description."
    )
    print(
        f"Mappable to trade data: {summary['mappable_share']:.1%}. "
        f"All annexes image-only: {summary['all_annexes_image_only']}."
    )
    print(f"\n{summary['conclusion']}")

    panel_path = layer_path("analytical", "trade_panel.parquet")
    bound = None
    if panel_path.exists():
        panel = pl.read_parquet(panel_path)
        bound = ux.realised_vs_statutory_bound(panel)

    provenance = DataProvenance.OFFICIAL
    if panel_path.exists():
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
        notes="USTR exclusion notices; coverage and intention-to-treat bound",
    )

    def _w(df: pl.DataFrame, name: str) -> Path:
        out = layer_path("results", f"{name}.parquet")
        df.with_columns(
            pl.lit(stamp.run_id).alias("run_id"),
            pl.lit(stamp.git_commit).alias("git_commit"),
            pl.lit(stamp.data_provenance.value).alias("data_provenance"),
        ).write_parquet(out)
        return out

    out = _w(frame, "exclusion_notice_coverage")
    if bound is not None:
        _w(bound, "exclusion_itt_bound_by_month")
        first = ux.first_exclusion_effective_month(notices)
        pre = bound.filter(pl.col("month_date") < first)
        post = bound.filter(pl.col("month_date") >= first)
        print(
            "\nIntention-to-treat bound (share of treated customs value where the realised "
            "duty rate falls more than 3pp short of the statutory rate):"
        )
        print(
            f"  before first exclusions were granted ({first}): "
            f"{pre['customs_value_short'].sum() / max(pre['customs_value'].sum(), 1):.1%}"
        )
        print(
            f"  after: "
            f"{post['customs_value_short'].sum() / max(post['customs_value'].sum(), 1):.1%}"
        )
        print(
            "  A gap present before exclusions existed cannot be caused by exclusions; it "
            "reflects preference programmes, Chapter 98 provisions and duty-free entry. "
            "Only the increase is attributable to exclusions, and even that is an upper bound."
        )
        summary["itt_bound_before_first_exclusion"] = float(
            pre["customs_value_short"].sum() / max(pre["customs_value"].sum(), 1)
        )
        summary["itt_bound_after_first_exclusion"] = float(
            post["customs_value_short"].sum() / max(post["customs_value"].sum(), 1)
        )
        summary["first_exclusion_month"] = str(first)

    (layer_path("results", "exclusion_coverage_summary.json")).write_text(
        json.dumps({"run": stamp.to_dict(), "summary": summary}, indent=2, default=str) + "\n"
    )
    stamp.write(layer_path("results", "exclusions.runstamp.json"))

    DatasetManifest.for_file(
        out,
        dataset_id="ustr_exclusion_notice_coverage",
        layer="results",
        source="U.S. Federal Register (GPO typeset PDFs), USTR product-exclusion notices",
        source_url="https://www.federalregister.gov/api/v1/documents",
        source_release_or_vintage="; ".join(
            f"{n.document_number} ({n.publication_date})" for n in notices
        ),
        schema_version="exclusion_coverage_v1",
        transformation_version="analyse_exclusions.py@v1",
        row_count=frame.height,
        data_provenance=DataProvenance.OFFICIAL,
        date_range=(min(n.publication_date for n in notices),
                    max(n.publication_date for n in notices)),
        known_limitations=[
            "Only the notices' self-reported counts are extracted. The annexes listing the "
            "excluded products are embedded raster images with no text layer, and OCR is not "
            "used because it would introduce an unvalidatable transcription channel into a "
            "legal treatment variable.",
            f"{summary['mappable_share']:.1%} of exclusions are expressed as a 10-digit "
            "subheading; the rest are product descriptions identifying a subset of a "
            "statistical reporting number, which published trade data cannot resolve.",
            "The realised-versus-statutory gap is an UPPER bound on the exclusion effect: "
            "preference programmes and duty-free entry produce the same signature.",
        ],
        columns={c: str(t) for c, t in zip(frame.columns, frame.dtypes, strict=True)},
        extra=summary,
    ).write()

    print(f"\nwrote {out} (run_id={stamp.run_id})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
