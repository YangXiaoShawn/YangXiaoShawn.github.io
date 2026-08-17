#!/usr/bin/env python
"""Fetch official source documents into ``data/raw`` and report what is reachable.

    python scripts/download_sources.py [--skip-bea]

Every source is probed and its status reported, including the ones that are
unavailable. Nothing is silently skipped.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tariff_incidence.adapters import bea_io, census_trade, usitc_hts  # noqa: E402
from tariff_incidence.adapters.base import SourceUnavailable  # noqa: E402
from tariff_incidence.adapters.federal_register import (  # noqa: E402
    fetch_document_metadata,
    fetch_notice_pdf,
)
from tariff_incidence.config import load_config  # noqa: E402
from tariff_incidence.paths import ensure_layers  # noqa: E402
from tariff_incidence.tariff.schedule import load_episode  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--episode", default="us_section301_china.yaml")
    ap.add_argument("--config", default="sample_slice.yaml")
    ap.add_argument("--skip-bea", action="store_true", help="skip the 20 MB BEA archive")
    args = ap.parse_args()
    ensure_layers()

    status: list[tuple[str, str, str]] = []

    print("== Federal Register (no key required) ==")
    episode = load_episode(args.episode)
    for action in episode["actions"]:
        doc_num = action["federal_register_document"]
        try:
            doc = fetch_document_metadata(doc_num)
            res = fetch_notice_pdf(doc)
            print(
                f"  {doc_num} {doc.citation:<14} {res.n_bytes:>10,} bytes "
                f"{'(cached)' if res.from_cache else '(downloaded)'}"
            )
            status.append(("federal_register", doc_num, "OK"))
        except SourceUnavailable as exc:
            print(f"  {doc_num}: UNAVAILABLE — {exc}")
            status.append(("federal_register", doc_num, "UNAVAILABLE"))

    print("\n== USITC HTS (no key required) ==")
    cfg = load_config(args.config)
    try:
        lines = usitc_hts.load_chapters(cfg.sample.hs2_chapters)
        print(
            f"  chapters {cfg.sample.hs2_chapters}: {len(lines):,} 8-digit lines, "
            f"{len(usitc_hts.hs6_children(lines)):,} HS6 headings"
        )
        status.append(("usitc_hts", ",".join(cfg.sample.hs2_chapters), "OK"))
    except SourceUnavailable as exc:
        print(f"  UNAVAILABLE — {exc}")
        status.append(("usitc_hts", "chapters", "UNAVAILABLE"))

    print("\n== BEA input-output (no key required) ==")
    if args.skip_bea:
        print("  skipped by request")
        status.append(("bea", "AllTablesSUP.zip", "SKIPPED"))
    else:
        try:
            p = bea_io.fetch_bea_zip()
            print(f"  {p.name}: {p.stat().st_size:,} bytes")
            status.append(("bea", "AllTablesSUP.zip", "OK"))
        except SourceUnavailable as exc:
            print(f"  UNAVAILABLE — {exc}")
            status.append(("bea", "AllTablesSUP.zip", "UNAVAILABLE"))

    print("\n== U.S. Census international trade (API KEY REQUIRED) ==")
    if census_trade.available():
        try:
            valid, unknown = census_trade.verify_schema(census_trade.DEFAULT_VARIABLES)
            print(f"  key present. {len(valid)} variables verified against the live schema.")
            if unknown:
                print(f"  WARNING: unknown variables (schema may have changed): {unknown}")
            status.append(("census", "imports/hs", "OK"))
        except SourceUnavailable as exc:
            print(f"  key present but the endpoint rejected it — {exc}")
            status.append(("census", "imports/hs", "ERROR"))
    else:
        print(f"  NO KEY. Set {census_trade.KEY_ENV} to use official trade data.")
        print(f"  Free registration: {census_trade.KEY_SIGNUP}")
        print("  Without it the pipeline runs in labelled synthetic mode and no output")
        print("  is an empirical finding about U.S. trade.")
        status.append(("census", "imports/hs", "BLOCKED_NO_KEY"))

    print("\n== Summary ==")
    for src, item, st in status:
        print(f"  {st:<16} {src:<18} {item}")
    blocked = [s for s in status if s[2] not in ("OK", "SKIPPED")]
    print(f"\n{len(status) - len(blocked)}/{len(status)} sources reachable.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
