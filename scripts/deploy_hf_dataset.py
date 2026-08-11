#!/usr/bin/env python3
"""Upload Dataset Card metadata or a clean staged research payload."""

from __future__ import annotations

import argparse
from pathlib import Path

from huggingface_hub import HfApi

ROOT = Path(__file__).resolve().parents[1]
REPO_ID = "ShawnChamberlain/open-economic-quant-research-data"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=ROOT / "build" / "hf-dataset")
    parser.add_argument("--full", action="store_true", help="Upload every file in the clean staging directory.")
    args = parser.parse_args()
    api = HfApi()
    api.create_repo(REPO_ID, repo_type="dataset", private=False, exist_ok=True)
    if args.full:
        api.upload_large_folder(repo_id=REPO_ID, repo_type="dataset", folder_path=args.source)
    else:
        for name in ("README.md", "dataset_manifest.json"):
            path = args.source / name
            api.upload_file(path_or_fileobj=path, path_in_repo=name, repo_id=REPO_ID, repo_type="dataset", commit_message=f"Update {name}")
    print(f"hf-dataset-deploy-ok repo={REPO_ID} full={args.full}")


if __name__ == "__main__":
    main()
