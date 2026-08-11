#!/usr/bin/env python3
"""Remove non-research runtime artifacts from the versioned full Dataset."""

from __future__ import annotations

from huggingface_hub import CommitOperationDelete, HfApi

REPO_ID = "ShawnChamberlain/open-economic-quant-research-data"
FOLDERS = (
    "CasualLab/.pytest_cache/",
    "CasualLab/.ruff_cache/",
    "CasualLab/tests/__pycache__/",
    "CasualLab/.venv/",
    "CasualLab/src/casuallab/__pycache__/",
    "Macroeconomics/.pytest_cache/",
    "Macroeconomics/.ruff_cache/",
    "Macroeconomics/tests/__pycache__/",
    "Macroeconomics/.venv/",
    "Macroeconomics/src/macro_nowcast/__pycache__/",
)
FILES = (
    "CasualLab/artifacts/.DS_Store",
    "CasualLab/.DS_Store",
    "CasualLab/data/.DS_Store",
    "Macroeconomics/.DS_Store",
)


def main() -> None:
    api = HfApi()
    remote_files = api.list_repo_files(REPO_ID, repo_type="dataset")
    operations = []
    for folder in FOLDERS:
        if any(path.startswith(folder) for path in remote_files):
            operations.append(CommitOperationDelete(path_in_repo=folder))
    for path in FILES:
        if path in remote_files:
            operations.append(CommitOperationDelete(path_in_repo=path))
    if not operations:
        print(f"hf-dataset-clean-ok before={len(remote_files)} operations=0")
        return
    commit = api.create_commit(
        repo_id=REPO_ID,
        repo_type="dataset",
        operations=operations,
        commit_message="Remove local environments and cache artifacts",
    )
    print(f"hf-dataset-clean-ok before={len(remote_files)} operations={len(operations)} commit={commit.oid}")


if __name__ == "__main__":
    main()
