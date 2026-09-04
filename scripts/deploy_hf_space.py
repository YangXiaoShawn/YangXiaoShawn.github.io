#!/usr/bin/env python3
"""Create or update the public Hugging Face Space."""

from pathlib import Path

from huggingface_hub import HfApi

from build_space_catalog import build_catalogs
from build_research_portfolio import build as build_portfolio

ROOT = Path(__file__).resolve().parents[1]
REPO_ID = "ShawnChamberlain/open-economic-quant-research-observatory"


def main() -> None:
    build_portfolio(check=True)
    counts = build_catalogs()
    api = HfApi()
    api.create_repo(REPO_ID, repo_type="space", space_sdk="static", private=False, exist_ok=True)
    api.upload_folder(
        repo_id=REPO_ID,
        repo_type="space",
        folder_path=ROOT / "apps" / "space",
        commit_message="Deploy Open Quant & Econ Evidence Lab",
        allow_patterns=["README.md", "index.html", "styles.css", "portfolio.css", "app.js", "evidence.json", "microstructure_backtest_reference.json", "favicon.svg", "catalog/*.json", "figures/*.svg"],
        delete_patterns=["*", "**/*"],
    )
    print(
        f"hf-space-deploy-ok repo={REPO_ID} "
        + " ".join(f"{project}={count}" for project, count in counts.items())
    )


if __name__ == "__main__":
    main()
