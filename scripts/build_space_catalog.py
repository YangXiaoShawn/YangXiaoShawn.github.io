#!/usr/bin/env python3
"""Build browser-safe file catalogs for the static Hugging Face Space."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "build" / "hf-dataset" / "dataset_manifest.json"
CATALOG_ROOT = ROOT / "apps" / "space" / "catalog"
EVIDENCE_SOURCE = ROOT / "assets" / "data" / "evidence.json"
EVIDENCE_TARGET = ROOT / "apps" / "space" / "evidence.json"
PROJECTS = ("CasualLab", "Macroeconomics", "RealEstate", "TariffIncidence", "Microstructure")
SLUGS = {
    "CasualLab": "casuallab",
    "Macroeconomics": "macroeconomics",
    "RealEstate": "realestate",
    "TariffIncidence": "tariff-incidence",
    "Microstructure": "microstructure",
}


def file_category(path: str) -> str:
    """Match the published portfolio taxonomy used by the website charts."""
    value = path.lower()
    if "/tests/" in value or value.endswith("/tests"):
        return "tests"
    if "/reports/" in value or "/docs/" in value:
        return "reports"
    if "/data/" in value or "fixture" in value:
        return "data"
    return "code"


def build_catalogs() -> dict[str, int]:
    CATALOG_ROOT.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    files = manifest.get("files", [])
    if not files:
        raise ValueError(f"Dataset manifest has no files: {MANIFEST_PATH}")

    category_counts: dict[str, dict[str, int]] = {}
    for project in PROJECTS:
        rows = [
            {
                "type": "file",
                "path": item["path"],
                "size": item["size_bytes"],
                "category": file_category(item["path"]),
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
        category_counts[project] = {
            category: sum(row["category"] == category for row in rows)
            for category in ("code", "data", "reports", "tests")
        }

    evidence = json.loads(EVIDENCE_SOURCE.read_text(encoding="utf-8"))
    for project, observed in category_counts.items():
        expected = evidence["portfolio"]["projects"][SLUGS[project]]
        if any(observed[category] != expected[category] for category in observed):
            raise ValueError(
                f"Space category counts differ from evidence for {project}: "
                f"observed={observed} expected={expected}"
            )
    EVIDENCE_TARGET.write_text(
        json.dumps(evidence, ensure_ascii=True, separators=(",", ":")),
        encoding="utf-8",
    )

    return counts


if __name__ == "__main__":
    result = build_catalogs()
    print(
        "space-catalog-ok "
        + " ".join(f"{project}={count}" for project, count in result.items())
    )
