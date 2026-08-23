#!/usr/bin/env python3
"""Build a clean full-research manifest or staging directory."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_PARTS = {".git", ".venv", ".mypy_cache", ".pytest_cache", ".ruff_cache", "__pycache__"}
EXCLUDED_NAMES = {".DS_Store"}


def included(path: Path, source: Path) -> bool:
    relative = path.relative_to(source)
    return not (set(relative.parts) & EXCLUDED_PARTS or path.name in EXCLUDED_NAMES)


def checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, default=ROOT.parent)
    parser.add_argument("--output", type=Path, default=ROOT / "build" / "hf-dataset")
    parser.add_argument("--copy", action="store_true", help="Copy included files into the staging directory.")
    args = parser.parse_args()
    projects = (
        ("CasualLab", args.workspace / "CasualLab"),
        ("Macroeconomics", args.workspace / "Macroeconomics"),
        ("RealEstate", ROOT / "realestate"),
        ("TariffIncidence", ROOT / "tariff-incidence"),
        ("Microstructure", ROOT / "microstructure"),
    )
    records = []
    for prefix, source in projects:
        if not source.exists():
            raise SystemExit(f"Missing source directory: {source}")
        for path in source.rglob("*"):
            if not path.is_file() or not included(path, source):
                continue
            relative = Path(prefix) / path.relative_to(source)
            records.append({"path": relative.as_posix(), "size_bytes": path.stat().st_size})
            if args.copy:
                destination = args.output / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, destination)
    payload = {
        "dataset": "ShawnChamberlain/open-economic-quant-research-data",
        "projects": [name for name, _ in projects],
        "file_count": len(records),
        "size_bytes": sum(item["size_bytes"] for item in records),
        "excluded_parts": sorted(EXCLUDED_PARTS | EXCLUDED_NAMES),
        "files": records,
    }
    args.output.mkdir(parents=True, exist_ok=True)
    manifest = args.output / "dataset_manifest.json"
    manifest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"dataset-package-ok files={len(records)} bytes={payload['size_bytes']} copied={args.copy}")


if __name__ == "__main__":
    main()
