#!/usr/bin/env python3
"""Create or update the public Hugging Face Space."""

from pathlib import Path

from huggingface_hub import HfApi

ROOT = Path(__file__).resolve().parents[1]
REPO_ID = "ShawnChamberlain/open-economic-quant-research-observatory"


def main() -> None:
    api = HfApi()
    api.create_repo(REPO_ID, repo_type="space", space_sdk="gradio", private=False, exist_ok=True)
    api.upload_folder(
        repo_id=REPO_ID,
        repo_type="space",
        folder_path=ROOT / "apps" / "space",
        commit_message="Deploy interactive research observatory",
        ignore_patterns=["tests/**", "__pycache__/**"],
    )
    print(f"hf-space-deploy-ok repo={REPO_ID}")


if __name__ == "__main__":
    main()
