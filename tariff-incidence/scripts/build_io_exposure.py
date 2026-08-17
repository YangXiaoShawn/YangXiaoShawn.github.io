#!/usr/bin/env python
"""Map product-level tariff exposure into U.S. industries via BEA input-output tables.

    python scripts/build_io_exposure.py [--year 2017]

Produces the four exposure channels separately. Protection and imported-input
cost are never combined into a single number.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import polars as pl  # noqa: E402
import yaml  # noqa: E402

from tariff_incidence.adapters import bea_io, census_concordance  # noqa: E402
from tariff_incidence.adapters.base import SourceUnavailable  # noqa: E402
from tariff_incidence.config import load_config  # noqa: E402
from tariff_incidence.io_exposure.exposure import (  # noqa: E402
    build_exposures,
    commodity_tariff_exposure,
    summarize,
)
from tariff_incidence.manifest import DatasetManifest  # noqa: E402
from tariff_incidence.paths import CONFIG, ensure_layers, layer_path  # noqa: E402
from tariff_incidence.provenance import DataProvenance, RunStamp  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="sample_slice.yaml")
    ap.add_argument("--year", type=int, default=2017, help="pre-treatment IO table year")
    ap.add_argument("--concordance-years", type=int, nargs="+",
                    default=[2017, 2018, 2019, 2020],
                    help="Census import concordance vintages to combine")
    ap.add_argument("--concordance-primary", type=int, default=2017,
                    help="vintage that governs the assignment (should be pre-treatment)")
    ap.add_argument("--force-chapter-map", action="store_true",
                    help="use the coarse HS2-chapter fallback even if the official file loads")
    ap.add_argument("--level", choices=["summary", "detail"], default="summary",
                    help="BEA industry granularity; detail is benchmark-year only (~400 "
                         "industries) and exists to give the propagation test enough clusters")
    args = ap.parse_args()
    suffix = "" if args.level == "summary" else f"_{args.level}"
    ensure_layers()

    cfg = load_config(args.config)
    conc = yaml.safe_load((CONFIG / "io_concordance.yaml").read_bytes())
    hs2_map: dict[str, str] = conc["hs2_to_bea_commodity"]

    panel = pl.read_parquet(layer_path("analytical", "trade_panel.parquet"))

    # Prefer the official Census import concordance, which is keyed on the
    # 10-digit commodity code -- exactly the level this panel is built at -- so
    # each line carries one NAICS industry and no weighting assumption is
    # involved. The hand-built HS2-chapter map remains only as a fallback, and
    # which one was used is recorded rather than left implicit.
    concordance_method = "HS2_CHAPTER_COARSE_APPROXIMATION"
    concordance_quality: dict = {}
    detail_map_quality: dict = {}
    hs_to_commodity: dict[str, str] = {}
    if not args.force_chapter_map:
        try:
            stack = census_concordance.load_vintages(
                args.concordance_years, primary_year=args.concordance_primary
            )
            panel_codes = (
                set(panel["hs10"].unique().to_list()) if "hs10" in panel.columns else set()
            )
            if args.level == "detail":
                # HS10 -> NAICS from Census, then NAICS -> BEA detail from BEA's
                # own published relation. Both legs are official; nothing here is
                # hand-assigned.
                in_panel = stack.mapping.filter(pl.col("hs10").is_in(list(panel_codes)))
                dmap = bea_io.naics_to_bea_detail(in_panel["naics"].unique().to_list())
                naics_to_detail = dict(
                    zip(dmap.mapping["naics"], dmap.mapping["bea_detail"], strict=True)
                )
                hs_to_commodity = {
                    r["hs10"]: naics_to_detail[r["naics"]]
                    for r in in_panel.iter_rows(named=True)
                    if r["naics"] in naics_to_detail
                }
                detail_map_quality = {
                    "n_naics_mapped": dmap.mapping.height,
                    "n_naics_unmapped": len(dmap.unmapped_naics),
                    "unmapped_naics": dmap.unmapped_naics,
                    "n_naics_ambiguous": dmap.ambiguous.height,
                    "ambiguous": dmap.ambiguous.to_dicts(),
                    "match_depth_counts": dmap.mapping.group_by("match_depth")
                    .len().sort("match_depth").to_dicts(),
                    "note": (
                        "NAICS industry codes are assigned to BEA detail industries by longest "
                        "matching prefix from BEA's published 'Related 2017 NAICS Codes' column. "
                        "Codes claimed by two industries at equal depth are left unassigned "
                        "rather than broken by an arbitrary rule. Codes that reach no industry "
                        "have two distinct causes and are not one category: a 2012-vintage NAICS "
                        "the revision retired on a line with no successor in the revised file, "
                        "and Census pseudo-industries 91xxxx/93xxxx for scrap and used goods, "
                        "which have no producing industry at all and which BEA likewise carries "
                        "as special rows with no NAICS counterpart."
                    ),
                }
                print(
                    f"NAICS -> BEA detail: {dmap.mapping.height} mapped, "
                    f"{len(dmap.unmapped_naics)} unmapped, {dmap.ambiguous.height} ambiguous; "
                    f"{dmap.mapping['bea_detail'].n_unique()} detail industries"
                )
                if dmap.unmapped_naics:
                    print(f"  ! retired/unmatched NAICS: {', '.join(dmap.unmapped_naics)}")
            else:
                official = {
                    r["hs10"]: r["bea_summary"]
                    for r in stack.mapping.iter_rows(named=True)
                    if r["bea_summary"]
                }
                hs_to_commodity = {k: v for k, v in official.items() if k in panel_codes}
            concordance_quality = {
                "primary_vintage": stack.primary_year,
                "vintages_used": stack.years,
                "n_from_primary": stack.n_from_primary,
                "n_from_later_vintages": stack.n_from_fallback,
                "n_reclassified_vs_primary": stack.n_reclassified_vs_primary,
                "reclassified_examples": stack.reclassified_examples,
                "n_panel_lines_matched": len(hs_to_commodity),
                "n_panel_lines": len(panel_codes),
                "warnings": list(stack.warnings),
                "method": (
                    "Official Census import concordances, one file per year, keyed on the "
                    "10-digit commodity code. The pre-treatment vintage governs the industry "
                    "assignment so it is pre-determined like the weights; later vintages only "
                    "supply codes created after that year."
                ),
            }
            concordance_method = (
                f"CENSUS_IMPORT_CONCORDANCE_{stack.primary_year}_PRIMARY_"
                f"{min(stack.years)}_{max(stack.years)}_HS10_TO_NAICS_TO_BEA"
            )
            print(
                f"official concordances {stack.years}, primary {stack.primary_year}: "
                f"{stack.n_from_primary:,} codes from primary + {stack.n_from_fallback:,} "
                f"from later; {len(hs_to_commodity):,} of {len(panel_codes):,} panel lines matched"
            )
            for w in stack.warnings:
                print(f"  ! {w}")
        except (SourceUnavailable, ValueError, OSError) as exc:
            print(f"! official concordance unavailable ({exc}); falling back to the chapter map")

    if not hs_to_commodity:
        product_col = "hs10" if "hs10" in panel.columns else "hs6"
        hs_to_commodity = {
            c: hs2_map[c[:2]]
            for c in panel[product_col].unique().to_list()
            if c[:2] in hs2_map
        }
        concordance_method = "HS2_CHAPTER_COARSE_APPROXIMATION"
    trade_prov = DataProvenance(
        json.loads((layer_path("analytical", "trade_panel.runstamp.json")).read_text())[
            "data_provenance"
        ]
    )

    try:
        tables = bea_io.load_tables(args.year, level=args.level)
    except (SourceUnavailable, ValueError, KeyError) as exc:
        print(f"BEA input-output tables unavailable: {exc}")
        print("Cannot build industry exposure without them. Nothing written.")
        return 1

    print(
        f"BEA {args.year} {args.level} tables: "
        f"{tables.direct_requirements['industry_code'].n_unique()} industries, "
        f"{tables.direct_requirements['commodity_code'].n_unique()} commodities, "
        f"{tables.total_requirements.height:,} total-requirement cells"
    )

    # Pre-treatment weight window ends the month before the first action takes
    # effect, so exposure weights cannot respond to the tariff.
    first_treated = panel.filter(pl.col("treated"))["month_index"].min()
    pre_idx = (
        int(first_treated) - 1 if first_treated is not None else int(panel["month_index"].max())
    )
    product_col = "hs10" if "hs10" in panel.columns else "hs6"
    ce, quality = commodity_tariff_exposure(
        panel, hs_to_commodity, pre_period_end_month_index=pre_idx,
        product_col=product_col,
    )
    if concordance_quality:
        quality.method = concordance_method
        quality.level = f"HS10 -> NAICS 6-digit -> BEA {args.level} industry"
        quality.source = (
            f"Census import concordances {concordance_quality['vintages_used']}, "
            f"primary {concordance_quality['primary_vintage']}"
        )
        quality.aggregation_loss_note = (
            "Each 10-digit commodity line carries exactly one NAICS industry in the "
            "official concordance, so no within-line weighting assumption is made. "
            "Aggregation loss remains only where Census itself writes an 'X' in a NAICS "
            "code to hide undisclosed detail, and where a line's NAICS falls outside the "
            "BEA summary manufacturing and primary groups. "
            f"{concordance_quality['n_reclassified_vs_primary']} codes carry a different "
            "NAICS in a later vintage; the pre-treatment assignment governs, and that "
            "count bounds how much the choice matters."
        )
    print(
        f"commodity exposure: {ce.height} BEA commodities from "
        f"{quality.n_mapped_products} mapped products "
        f"({quality.n_unmapped_products} unmapped)"
    )

    exposure = build_exposures(
        ce, tables.direct_requirements, tables.total_requirements
    ).with_columns(
        pl.col("industry_code")
        .replace_strict(tables.industry_names, default=None)
        .alias("industry_name"),
        pl.lit(concordance_method).alias("concordance_status"),
    )

    stamp = RunStamp.create(
        config_name=cfg.config_name,
        config_bytes=cfg.raw_bytes,
        data_provenance=(
            DataProvenance.OFFICIAL
            if trade_prov is DataProvenance.OFFICIAL
            else DataProvenance.MIXED
        ),
        data_period_start=str(args.year),
        data_period_end=str(args.year),
        notes=f"BEA {args.year} {args.level} IO; concordance status {conc['status']}",
    )
    out = layer_path("results", f"industry_tariff_exposure{suffix}.parquet")
    exposure.with_columns(
        pl.lit(stamp.run_id).alias("run_id"),
        pl.lit(stamp.git_commit).alias("git_commit"),
        pl.lit(stamp.data_provenance.value).alias("data_provenance"),
    ).write_parquet(out)
    ce.write_parquet(layer_path("results", f"commodity_tariff_exposure{suffix}.parquet"))
    summarize(exposure).write_parquet(layer_path("results", f"industry_exposure_summary{suffix}.parquet"))
    stamp.write(layer_path("results", f"io_exposure{suffix}.runstamp.json"))

    (layer_path("results", f"io_exposure_quality{suffix}.json")).write_text(
        json.dumps({"run": stamp.to_dict(), "concordance": quality.to_row(),
                    "concordance_config_status": concordance_method,
                    "official_concordance": concordance_quality,
                    "bea_level": args.level,
                    "naics_to_bea_detail": detail_map_quality}, indent=2, default=str) + "\n"
    )

    DatasetManifest.for_file(
        out,
        dataset_id=f"industry_tariff_exposure{suffix}",
        layer="results",
        source=f"BEA Supply-Use {args.level} tables {args.year} + project tariff schedule",
        source_url=bea_io.BEA_ZIP_URL,
        source_release_or_vintage=tables.source_release,
        schema_version="io_exposure_v1",
        transformation_version="build_io_exposure.py@v1",
        row_count=exposure.height,
        data_provenance=stamp.data_provenance,
        date_range=(str(args.year), str(args.year)),
        known_limitations=[
            quality.aggregation_loss_note,
            f"HS-to-commodity concordance: {concordance_method}.",
            "Direct requirements are normalised by the intermediate-input column total, not by "
            "total industry output including value added, so shares are input shares of "
            "intermediate purchases.",
        ],
        columns={c: str(t) for c, t in zip(exposure.columns, exposure.dtypes, strict=True)},
    ).write()

    print("\nexposure classes:")
    print(summarize(exposure))
    both = exposure.filter(pl.col("exposure_class") == "BOTH_PROTECTED_AND_COST_EXPOSED")
    print(f"\nindustries exposed through BOTH channels: {both.height}")
    print(
        both.select(
            ["industry_code", "industry_name", "output_protection_exposure",
             "imported_input_cost_exposure", "downstream_total_requirements_exposure"]
        ).head(12)
    )
    print("\ntop imported-input cost exposure:")
    print(
        exposure.select(
            ["industry_code", "industry_name", "imported_input_cost_exposure",
             "output_protection_exposure", "exposure_class"]
        ).head(12)
    )
    print(f"\nwrote {out} (run_id={stamp.run_id})")
    print(f"NOTE: concordance = {concordance_method}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
