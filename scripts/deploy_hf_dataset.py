#!/usr/bin/env python3
"""Upload Dataset Card metadata or a clean staged research payload."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from huggingface_hub import HfApi

ROOT = Path(__file__).resolve().parents[1]
REPO_ID = "ShawnChamberlain/open-economic-quant-research-data"
MICROSTRUCTURE_GENERATED_DIRS = {
    "data/_ingestion_manifests",
    "data/derived",
    "data/m8",
    "data/m8_l2",
    "data/models",
    "data/normalized",
    "data/quality",
}


def validate_microstructure_mirror(folder: Path) -> None:
    """Require the mirror to match the staged Dataset manifest exactly."""
    symlinks = [path.relative_to(folder).as_posix() for path in folder.rglob("*") if path.is_symlink()]
    if symlinks:
        raise SystemExit(f"Microstructure mirror contains symlinks: {', '.join(symlinks[:5])}")

    forbidden: list[str] = []
    for path in folder.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(folder).as_posix()
        if relative.startswith(("data/raw/", "artifacts/runs/")):
            forbidden.append(relative)
            continue
        if any(relative.startswith(f"{prefix}/") for prefix in MICROSTRUCTURE_GENERATED_DIRS):
            if path.name != ".gitkeep":
                forbidden.append(relative)
    if forbidden:
        preview = ", ".join(forbidden[:5])
        raise SystemExit(f"Microstructure mirror contains excluded generated state: {preview}")

    manifest_path = ROOT / "build" / "hf-dataset" / "dataset_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = {
        item["path"].removeprefix("Microstructure/"): item["size_bytes"]
        for item in manifest.get("files", [])
        if item.get("path", "").startswith("Microstructure/")
    }
    actual = {
        path.relative_to(folder).as_posix(): path.stat().st_size
        for path in folder.rglob("*")
        if path.is_file()
    }
    if actual != expected:
        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))
        resized = sorted(path for path in set(actual) & set(expected) if actual[path] != expected[path])
        raise SystemExit(
            "Microstructure mirror differs from the Dataset manifest: "
            f"missing={missing[:3]} extra={extra[:3]} resized={resized[:3]}"
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=ROOT / "build" / "hf-dataset")
    parser.add_argument("--full", action="store_true", help="Upload every file in the clean staging directory.")
    parser.add_argument(
        "--realestate",
        action="store_true",
        help="Upload the publishable RealEstate package under its Dataset prefix.",
    )
    parser.add_argument(
        "--tariff-incidence",
        action="store_true",
        help="Upload the publishable tariff-incidence package under its Dataset prefix.",
    )
    parser.add_argument(
        "--microstructure",
        action="store_true",
        help="Upload the tracked-only Microstructure code and documentation package.",
    )
    args = parser.parse_args()
    api = HfApi()
    api.create_repo(REPO_ID, repo_type="dataset", private=False, exist_ok=True)
    if args.full:
        api.upload_large_folder(repo_id=REPO_ID, repo_type="dataset", folder_path=args.source)
    else:
        if args.realestate:
            api.upload_folder(
                repo_id=REPO_ID,
                repo_type="dataset",
                folder_path=ROOT / "realestate",
                path_in_repo="RealEstate",
                commit_message="Publish Mortgage Rate Lock-In research package",
                ignore_patterns=[
                    "**/.DS_Store",
                    "**/.env*",
                    "**/.pytest_cache/**",
                    "**/.ruff_cache/**",
                    "**/.venv/**",
                    "**/__pycache__/**",
                    "data/raw/**",
                    "data/interim/**",
                    "data/processed/**",
                    "data/cache/**",
                    "outputs/**",
                ],
            )
        if args.tariff_incidence:
            api.upload_folder(
                repo_id=REPO_ID,
                repo_type="dataset",
                folder_path=ROOT / "tariff-incidence",
                path_in_repo="TariffIncidence",
                commit_message="Publish Tariff Incidence research package",
                ignore_patterns=[
                    "**/.DS_Store",
                    "**/.env*",
                    "**/.mypy_cache/**",
                    "**/.pytest_cache/**",
                    "**/.ruff_cache/**",
                    "**/.venv/**",
                    "**/__pycache__/**",
                    "data/raw/**",
                    "data/staged/**",
                    "data/normalized/**",
                    "data/analytical/**",
                    "data/results/**/*.parquet",
                ],
            )
        if args.microstructure:
            microstructure_folder = ROOT / "microstructure"
            validate_microstructure_mirror(microstructure_folder)
            api.upload_folder(
                repo_id=REPO_ID,
                repo_type="dataset",
                folder_path=microstructure_folder,
                path_in_repo="Microstructure",
                commit_message="Publish Microstructure code and documentation package",
                delete_patterns=["*", "**/*"],
                ignore_patterns=[
                    "**/.DS_Store",
                    "**/.env*",
                    "**/.mypy_cache/**",
                    "**/.pytest_cache/**",
                    "**/.ruff_cache/**",
                    "**/.venv/**",
                    "**/__pycache__/**",
                    "data/raw/**",
                    "artifacts/runs/**",
                ],
            )
        for name in ("README.md", "dataset_manifest.json"):
            path = args.source / name
            api.upload_file(path_or_fileobj=path, path_in_repo=name, repo_id=REPO_ID, repo_type="dataset", commit_message=f"Update {name}")
    print(
        f"hf-dataset-deploy-ok repo={REPO_ID} "
        f"full={args.full} realestate={args.realestate} "
        f"tariff_incidence={args.tariff_incidence} "
        f"microstructure={args.microstructure}"
    )


if __name__ == "__main__":
    main()
