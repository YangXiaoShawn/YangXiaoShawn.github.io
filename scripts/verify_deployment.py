#!/usr/bin/env python3
"""Verify local release artifacts and, optionally, public deployment URLs."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from huggingface_hub import HfApi
from huggingface_hub.hf_api import RepoFile

ROOT = Path(__file__).resolve().parents[1]
DATASET_ID = "ShawnChamberlain/open-economic-quant-research-data"
SPACE_ID = "ShawnChamberlain/open-economic-quant-research-observatory"
ROUTES = (
    "research",
    "replications",
    "updated-results",
    "datasets",
    "methods",
    "dashboards",
    "comparisons",
    "daily-reports",
    "about",
)
PUBLIC_URLS = (
    "https://yangxiaoshawn.github.io/",
    "https://yangxiaoshawn.github.io/projects/casuallab/",
    "https://yangxiaoshawn.github.io/projects/macroeconomics/",
    "https://yangxiaoshawn.github.io/projects/realestate/",
    "https://yangxiaoshawn.github.io/projects/tariff-incidence/",
    "https://yangxiaoshawn.github.io/projects/microstructure/",
    "https://yangxiaoshawn.github.io/assets/data/microstructure_backtest_reference.json",
    "https://yangxiaoshawn.github.io/robots.txt",
    "https://yangxiaoshawn.github.io/sitemap.xml",
    "https://github.com/YangXiaoShawn/open-economic-quant-casuallab",
    "https://github.com/YangXiaoShawn/open-economic-quant-macroeconomics",
    "https://github.com/YangXiaoShawn/open-economic-quant-realestate",
    "https://github.com/YangXiaoShawn/open-economic-quant-tariff-incidence",
    "https://github.com/YangXiaoShawn/open-economic-quant-microstructure",
    "https://huggingface.co/datasets/ShawnChamberlain/open-economic-quant-research-data",
    "https://huggingface.co/spaces/ShawnChamberlain/open-economic-quant-research-observatory",
)


def online_status(url: str) -> int:
    request = Request(url, headers={"User-Agent": "observatory-deployment-verifier"})
    try:
        with urlopen(request, timeout=20) as response:
            return response.status
    except HTTPError as exc:
        return exc.code
    except URLError:
        return 0


def online_json(url: str):
    request = Request(url, headers={"User-Agent": "observatory-deployment-verifier"})
    with urlopen(request, timeout=20) as response:
        return json.load(response)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--online", action="store_true")
    parser.add_argument("--hf-only", action="store_true", help="Verify the pinned Hugging Face release without checking Pages or GitHub URLs.")
    args = parser.parse_args()
    required = [
        ROOT / "index.html",
        ROOT / "404.html",
        ROOT / "robots.txt",
        ROOT / "sitemap.xml",
        ROOT / "feed.xml",
        ROOT / "assets" / "css" / "styles.css",
        ROOT / "assets" / "js" / "app.js",
        ROOT / "assets" / "data" / "evidence.json",
        ROOT / "assets" / "data" / "microstructure_backtest_reference.json",
        ROOT / "assets" / "data" / "projects.json",
        ROOT / "assets" / "og-visual-2026.png",
        ROOT / "projects" / "casuallab" / "index.html",
        ROOT / "projects" / "macroeconomics" / "index.html",
        ROOT / "projects" / "realestate" / "index.html",
        ROOT / "projects" / "tariff-incidence" / "index.html",
        ROOT / "projects" / "microstructure" / "index.html",
        ROOT / "apps" / "space" / "app.py",
        ROOT / "apps" / "space" / "README.md",
        ROOT / "apps" / "space" / "index.html",
        ROOT / "apps" / "space" / "styles.css",
        ROOT / "apps" / "space" / "app.js",
        ROOT / "apps" / "space" / "evidence.json",
        ROOT / "apps" / "space" / "microstructure_backtest_reference.json",
        ROOT / "apps" / "space" / "favicon.svg",
        ROOT / "apps" / "space" / "catalog" / "Microstructure.json",
    ]
    required.extend(ROOT / route / "index.html" for route in ROUTES)
    missing = [str(path.relative_to(ROOT)) for path in required if not path.exists()]
    failures = [f"missing {path}" for path in missing]

    catalog_path = ROOT / "assets" / "data" / "projects.json"
    if catalog_path.exists():
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        expected_projects = {
            "casuallab",
            "macroeconomics",
            "realestate",
            "tariff-incidence",
            "microstructure",
        }
        if {item.get("slug") for item in catalog.get("projects", [])} != expected_projects:
            failures.append("generated catalog does not contain exactly the five published projects")

    evidence_path = ROOT / "assets" / "data" / "evidence.json"
    if evidence_path.exists():
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        portfolio = evidence.get("portfolio", {})
        portfolio_projects = portfolio.get("projects", {})
        expected_projects = {
            "casuallab",
            "macroeconomics",
            "realestate",
            "tariff-incidence",
            "microstructure",
        }
        if set(portfolio_projects) != expected_projects or set(evidence.get("projects", {})) != expected_projects:
            failures.append("evidence catalog does not contain exactly the five published projects")
        if sum(item.get("files", 0) for item in portfolio_projects.values()) != portfolio.get("total_files"):
            failures.append("portfolio project file counts do not sum to total_files")
        if sum(portfolio.get("categories", {}).values()) != portfolio.get("total_files"):
            failures.append("portfolio category counts do not sum to total_files")
        for slug, item in portfolio_projects.items():
            if sum(item.get(category, 0) for category in ("code", "data", "reports", "tests")) != item.get("files"):
                failures.append(f"portfolio category counts do not sum for {slug}")
        for slug, project in evidence.get("projects", {}).items():
            for field in ("question", "method", "finding", "note", "chart_caption", "source"):
                if not str(project.get(field, "")).strip():
                    failures.append(f"evidence story omits {field} for {slug}")
            metric_ids = {item.get("id") for item in project.get("metrics", [])}
            if not project.get("series") or project.get("default_metric") not in metric_ids:
                failures.append(f"evidence series or default metric is invalid for {slug}")
            for row in project.get("series", []):
                if not metric_ids.issubset(row):
                    failures.append(f"evidence series omits a metric for {slug}")
                    break
        micro = evidence.get("projects", {}).get("microstructure", {})
        if micro.get("headline", {}).get("value") != "0 / 144" or micro.get("default_metric") != "net_edge_bps":
            failures.append("microstructure evidence does not lead with the current fee-adjusted scenario result")
        tariff = evidence.get("projects", {}).get("tariff-incidence", {})
        if tariff.get("default_metric") != "customs" or not tariff.get("reference", {}).get("customs_bound"):
            failures.append("tariff evidence does not lead with the customs-value bound")
        space_evidence = ROOT / "apps" / "space" / "evidence.json"
        if space_evidence.exists() and json.loads(space_evidence.read_text(encoding="utf-8")) != evidence:
            failures.append("website and Space evidence catalogs differ")

    reference_path = ROOT / "assets" / "data" / "microstructure_backtest_reference.json"
    space_reference_path = ROOT / "apps" / "space" / "microstructure_backtest_reference.json"
    if reference_path.exists() and space_reference_path.exists():
        reference = json.loads(reference_path.read_text(encoding="utf-8"))
        space_reference = json.loads(space_reference_path.read_text(encoding="utf-8"))
        if space_reference != reference:
            failures.append("website and Space microstructure reference summaries differ")
        scenarios = reference.get("scenarios", [])
        overview = reference.get("overview", {})
        if len(scenarios) != 144 or overview.get("scenario_count") != 144:
            failures.append("microstructure reference summary does not contain exactly 144 scenarios")
        if overview.get("gross_positive_count") != 110 or overview.get("net_positive_count") != 0:
            failures.append("microstructure reference summary has unexpected gross/net positive counts")
        if {row.get("fee_edge_bps") for row in scenarios} != {4.0}:
            failures.append("microstructure reference summary does not preserve the frozen 4 bp fee")
        if any(abs(row.get("gross_pnl_usdt", 0) - row.get("fees_usdt", 0) - row.get("net_pnl_usdt", 0)) > 2e-6 for row in scenarios):
            failures.append("microstructure reference summary violates gross minus fees equals net P&L")
        if any(reference.get("claim_boundary", {}).values()):
            failures.append("microstructure reference summary authorizes a prohibited claim")
        if reference.get("provenance", {}).get("source_commit") != "b918673405226467d6e5c2fa1f2fac59cca19d03":
            failures.append("microstructure reference summary source commit changed unexpectedly")
        disclaimer = str(reference.get("disclaimer", "")).lower()
        if "research reference only" not in disclaimer or "not live trading" not in disclaimer or "must not be summed" not in disclaimer:
            failures.append("microstructure reference summary is missing required public warnings")

    home_path = ROOT / "index.html"
    if home_path.exists() and "assets/og-visual-2026.png" not in home_path.read_text(encoding="utf-8"):
        failures.append("homepage does not reference the current social preview")

    public_text = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in required
        if path.exists() and path.suffix in {".html", ".md", ".json", ".txt", ".xml"}
    )
    if re.search(r"[\u3400-\u9fff]", public_text):
        failures.append("public website artifacts contain non-English CJK text")

    if args.online:
        for url in PUBLIC_URLS:
            status = online_status(url)
            if status < 200 or status >= 400:
                failures.append(f"public URL returned {status}: {url}")
    if args.online or args.hf_only:
        try:
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            revision = evidence["dataset_revision"]
            local_microstructure_catalog = json.loads(
                (ROOT / "apps" / "space" / "catalog" / "Microstructure.json").read_text(encoding="utf-8")
            )
            api = HfApi()
            remote_nodes = api.list_repo_tree(
                DATASET_ID,
                path_in_repo="Microstructure",
                repo_type="dataset",
                revision=revision,
                recursive=True,
                expand=False,
            )
            remote_microstructure_catalog = sorted(
                (
                    {
                        "type": "file",
                        "path": node.path,
                        "size": node.size,
                        "category": next(
                            item["category"]
                            for item in local_microstructure_catalog
                            if item["path"] == node.path
                        ),
                    }
                    for node in remote_nodes
                    if isinstance(node, RepoFile)
                ),
                key=lambda item: item["path"],
            )
            if remote_microstructure_catalog != local_microstructure_catalog:
                failures.append("remote Dataset Microstructure tree differs from the 133-file release catalog")

            space_base = f"https://huggingface.co/spaces/{SPACE_ID}/resolve/main"
            remote_space_catalog = online_json(f"{space_base}/catalog/Microstructure.json")
            if remote_space_catalog != local_microstructure_catalog:
                failures.append("remote Space Microstructure catalog differs from the release catalog")
            remote_space_evidence = online_json(f"{space_base}/evidence.json")
            if remote_space_evidence != evidence:
                failures.append("remote Space evidence does not match the website or pinned Dataset revision")
            remote_space_reference = online_json(f"{space_base}/microstructure_backtest_reference.json")
            if remote_space_reference != reference:
                failures.append("remote Space microstructure reference differs from the verified local summary")
            status_url = f"https://huggingface.co/datasets/{DATASET_ID}/resolve/{revision}/Microstructure/STATUS.md"
            if online_status(status_url) != 200:
                failures.append("pinned Microstructure STATUS evidence is not available from the Dataset")
        except Exception as exc:
            failures.append(f"Hugging Face release-integrity check failed: {type(exc).__name__}: {exc}")

    if failures:
        raise SystemExit("Verification failed:\n- " + "\n- ".join(failures))
    print(
        f"verify-ok local={len(required)} "
        f"online={len(PUBLIC_URLS) if args.online else 0} "
        f"hf_integrity={int(args.online or args.hf_only)}"
    )


if __name__ == "__main__":
    main()
