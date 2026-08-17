#!/usr/bin/env python3
"""Build browser-safe file catalogs for the static Hugging Face Space."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "build" / "hf-dataset" / "dataset_manifest.json"
CATALOG_ROOT = ROOT / "apps" / "space" / "catalog"
PROJECTS = ("CasualLab", "Macroeconomics", "RealEstate", "TariffIncidence")


def build_catalogs() -> dict[str, int]:
    CATALOG_ROOT.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    files = manifest.get("files", [])
    if not files:
        raise ValueError(f"Dataset manifest has no files: {MANIFEST_PATH}")

    for project in PROJECTS:
        rows = [
            {
                "type": "file",
                "path": item["path"],
                "size": item["size_bytes"],
            }
            for item in files
            if item["path"].startswith(f"{project}/")
        ]
        rows.sort(key=lambda item: item["path"])
        (CATALOG_ROOT / f"{project}.json").write_text(
            json.dumps(rows, ensure_ascii=True, separators=(",", ":")),
            encoding="utf-8",
        )
        counts[project] = len(rows)

    return counts


if __name__ == "__main__":
    result = build_catalogs()
    print(
        "space-catalog-ok "
        + " ".join(f"{project}={count}" for project, count in result.items())
    )
