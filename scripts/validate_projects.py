#!/usr/bin/env python3
"""Validate compact project packages and publication metadata."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECTS = ("casuallab", "macroeconomics", "realestate", "tariff-incidence", "microstructure")
REQUIRED_KEYS = {
    "title",
    "slug",
    "summary",
    "research_question",
    "research_fields",
    "project_type",
    "status",
    "data_sources",
    "reproduction_command",
    "github_url",
    "site_url",
    "dataset_url",
    "space_url",
    "last_updated",
    "limitations",
}
BANNED_DIRS = {"raw", "artifacts", "generated", "tmp", ".venv", ".pytest_cache", ".ruff_cache", "__pycache__"}
BANNED_FILES = {".DS_Store", ".env", ".env.local"}


def top_level_keys(text: str) -> set[str]:
    return set(re.findall(r"^([a-zA-Z][a-zA-Z0-9_]*):", text, flags=re.MULTILINE))


def main() -> None:
    failures: list[str] = []
    for slug in PROJECTS:
        project = ROOT / slug
        metadata = project / "project.yaml"
        if not metadata.exists():
            failures.append(f"missing {slug}/project.yaml")
            continue
        text = metadata.read_text(encoding="utf-8")
        missing = REQUIRED_KEYS - top_level_keys(text)
        if missing:
            failures.append(f"{slug}/project.yaml missing {sorted(missing)}")
        if re.search(r"\b(TBD|TDB|pending)\b", text, flags=re.IGNORECASE):
            failures.append(f"{slug}/project.yaml contains a placeholder")
        for path in project.rglob("*"):
            if path.is_dir() and path.name in BANNED_DIRS:
                failures.append(f"banned directory {path.relative_to(ROOT)}")
            if path.is_file() and path.name in BANNED_FILES:
                failures.append(f"banned file {path.relative_to(ROOT)}")
    for required in (
        ROOT / "manifests" / "project_inventory.json",
        ROOT / "manifests" / "asset_inventory.csv",
        ROOT / "manifests" / "publication_rights.csv",
    ):
        if not required.exists():
            failures.append(f"missing {required.relative_to(ROOT)}")
    if failures:
        raise SystemExit("Validation failed:\n- " + "\n- ".join(failures))
    print(f"validation-ok projects={len(PROJECTS)}")


if __name__ == "__main__":
    main()
