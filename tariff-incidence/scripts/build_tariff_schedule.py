#!/usr/bin/env python
"""Build the Section 301 tariff schedule from official Federal Register notices.

Downloads (or reuses cached) GPO PDFs, parses the operative annexes, resolves
truncated codes against the USITC HTS where the deduction is unique, and writes
a normalized-layer Parquet table plus a manifest.

    python scripts/build_tariff_schedule.py [--offline] [--episode FILE]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import polars as pl  # noqa: E402

from tariff_incidence.adapters import usitc_hts  # noqa: E402
from tariff_incidence.adapters.base import SourceUnavailable  # noqa: E402
from tariff_incidence.adapters.federal_register import annex_to_records  # noqa: E402
from tariff_incidence.manifest import DatasetManifest  # noqa: E402
from tariff_incidence.paths import RAW, ensure_layers, layer_path  # noqa: E402
from tariff_incidence.provenance import DataProvenance  # noqa: E402
from tariff_incidence.tariff.records import Confidence, RecordType  # noqa: E402
from tariff_incidence.tariff.schedule import (  # noqa: E402
    build_records_from_episode,
    load_episode,
    parse_summary,
    records_to_frame,
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--episode", default="us_section301_china.yaml")
    ap.add_argument(
        "--offline",
        action="store_true",
        help="use PDFs already cached in data/raw/federal_register instead of downloading",
    )
    ap.add_argument("--no-hts", action="store_true", help="skip the USITC HTS truncation resolver")
    args = ap.parse_args()

    ensure_layers()
    episode = load_episode(args.episode)
    print(f"episode: {episode['episode_id']}  ({episode['label']})")

    offline_dir = RAW / "federal_register" if args.offline else None
    records, parses = build_records_from_episode(episode, offline_pdf_dir=offline_dir)

    # ---- resolve codes truncated in the PDF text layer -------------------
    resolution_log: list[dict] = []
    unresolved_all: list[str] = []
    for p in parses:
        if not p.unresolved_codes:
            continue
        if args.no_hts:
            unresolved_all.extend(p.unresolved_codes)
            continue
        chapters = sorted({c.replace(".", "")[:2] for c in p.unresolved_codes})
        try:
            hts_lines = usitc_hts.load_chapters(chapters)
        except SourceUnavailable as exc:
            print(f"  ! HTS unavailable, leaving {len(p.unresolved_codes)} codes unresolved: {exc}")
            unresolved_all.extend(p.unresolved_codes)
            continue
        resolved, still = usitc_hts.resolve_truncated_codes(
            p.unresolved_codes, set(p.hts8_codes), hts_lines
        )
        unresolved_all.extend(still)
        for trunc, hs8 in resolved.items():
            print(
                f"  + resolved truncated {trunc} -> {hs8} "
                f"(unique unclaimed 8-digit line under this heading in the HTS)"
            )
            resolution_log.append(
                {"document": p.document_number, "truncated": trunc, "resolved_to": hs8}
            )
            p.hts8_codes.append(hs8)
        p.hts8_codes = sorted(set(p.hts8_codes))
        if resolved:
            p.parsed_line_count = p.total_full_and_partial
            p.count_matches_notice = (
                None if p.stated_line_count is None else p.parsed_line_count == p.stated_line_count
            )
            # Re-emit this document's records with the resolved line included.
            action = next(
                a for a in episode["actions"] if a["federal_register_document"] == p.document_number
            )
            from datetime import datetime

            def _d(s: str):  # noqa: ANN202
                return datetime.strptime(str(s), "%Y-%m-%d").date()

            from tariff_incidence.adapters.federal_register import FRDocument

            doc = FRDocument(
                document_number=p.document_number,
                citation=action.get("citation", ""),
                title=action.get("label", ""),
                publication_date=str(action.get("publication_date", "")),
                html_url=f"https://www.federalregister.gov/d/{p.document_number}",
                pdf_url="",
            )
            old = {r.record_id for r in records if r.source.document_id == p.document_number}
            checksum = next(
                (r.source.checksum_sha256 for r in records if r.source.document_id == p.document_number),
                "",
            )
            new = annex_to_records(
                p,
                doc,
                episode_id=episode["episode_id"],
                action_id=action["action_id"],
                effective_date=_d(action["effective_date"]),
                announcement_date=_d(action["announcement_date"]),
                ad_valorem_rate=float(action["ad_valorem_rate"]),
                product_code_vintage=episode.get("product_code_vintage", "UNKNOWN"),
                checksum=checksum,
                partner_country_code=str(episode.get("partner_country_code", "5700")),
                record_type=RecordType[action.get("record_type", "ADDITIONAL_DUTY")],
            )
            added = [r for r in new if r.record_id not in old]
            # Codes deduced from the HTS rather than read from the notice.
            deduced = {v for v in resolved.values()}
            records.extend(
                [
                    (
                        r
                        if r.product_code not in deduced
                        else type(r)(
                            **{
                                **{f: getattr(r, f) for f in r.__slots__},
                                "confidence": Confidence.DERIVED,
                                "notes": (
                                    r.notes
                                    + " | code deduced from USITC HTS: the notice rendering lost "
                                    "the final two digits and exactly one 8-digit line under this "
                                    "heading was unclaimed"
                                ),
                            }
                        )
                    )
                    for r in added
                ]
            )

    df = records_to_frame(records)
    out = layer_path("normalized", "tariff_schedule.parquet")
    df.write_parquet(out)

    summary = parse_summary(parses)
    (layer_path("normalized", "tariff_schedule_parse_report.json")).write_text(
        json.dumps(
            {
                "episode_id": episode["episode_id"],
                "parses": summary,
                "truncation_resolutions": resolution_log,
                "still_unresolved": sorted(set(unresolved_all)),
                "known_gaps": episode.get("known_gaps", []),
            },
            indent=2,
            default=str,
        )
        + "\n"
    )

    limitations = [
        f"{g['id']}: {g['description'].strip()}" for g in episode.get("known_gaps", [])
    ]
    for p in parses:
        if p.count_matches_notice is False:
            limitations.append(
                f"{p.document_number}: parsed {p.parsed_line_count} lines vs "
                f"{p.stated_line_count} stated in the notice"
            )
    if unresolved_all:
        limitations.append(
            f"{len(set(unresolved_all))} code(s) truncated in the source PDF could not be "
            "uniquely resolved and are absent from the covered-line list: "
            + ", ".join(sorted(set(unresolved_all)))
        )

    DatasetManifest.for_file(
        out,
        dataset_id="tariff_schedule_section301_china",
        layer="normalized",
        source="U.S. Federal Register (GPO typeset PDFs) via federalregister.gov API",
        source_url="https://www.federalregister.gov/api/v1/documents",
        source_release_or_vintage="; ".join(
            f"{a.get('citation')} ({a['federal_register_document']})" for a in episode["actions"]
        ),
        schema_version="tariff_schedule_v1",
        transformation_version="build_tariff_schedule.py@v1",
        row_count=df.height,
        data_provenance=DataProvenance.OFFICIAL,
        product_code_vintage=episode.get("product_code_vintage"),
        date_range=(
            str(df["effective_date"].min()),
            str(df["effective_date"].max()),
        ),
        partition_keys=[],
        known_limitations=limitations,
        columns={c: str(t) for c, t in zip(df.columns, df.dtypes, strict=True)},
        extra={"parses": summary, "truncation_resolutions": resolution_log},
    ).write()

    print(f"\nwrote {out}  ({df.height:,} records)")
    print(
        df.group_by(["action_id", "record_type", "effective_date", "ad_valorem_rate"])
        .agg(pl.len().alias("n"), pl.col("partial_line").sum().alias("n_partial"))
        .sort(["effective_date", "action_id"])
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
