#!/usr/bin/env python3
"""Verify local release artifacts and, optionally, public deployment URLs."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
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
    "https://yangxiaoshawn.github.io/robots.txt",
    "https://yangxiaoshawn.github.io/sitemap.xml",
    "https://github.com/YangXiaoShawn/open-economic-quant-casuallab",
    "https://github.com/YangXiaoShawn/open-economic-quant-macroeconomics",
    "https://github.com/YangXiaoShawn/open-economic-quant-realestate",
    "https://github.com/YangXiaoShawn/open-economic-quant-tariff-incidence",
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--online", action="store_true")
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
        ROOT / "assets" / "data" / "projects.json",
        ROOT / "assets" / "og-visual-2026.png",
        ROOT / "projects" / "casuallab" / "index.html",
        ROOT / "projects" / "macroeconomics" / "index.html",
        ROOT / "projects" / "realestate" / "index.html",
        ROOT / "projects" / "tariff-incidence" / "index.html",
        ROOT / "apps" / "space" / "app.py",
        ROOT / "apps" / "space" / "README.md",
        ROOT / "apps" / "space" / "index.html",
        ROOT / "apps" / "space" / "styles.css",
        ROOT / "apps" / "space" / "app.js",
        ROOT / "apps" / "space" / "evidence.json",
        ROOT / "apps" / "space" / "favicon.svg",
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
        }
        if {item.get("slug") for item in catalog.get("projects", [])} != expected_projects:
            failures.append("generated catalog does not contain exactly the four published projects")

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
        }
        if set(portfolio_projects) != expected_projects or set(evidence.get("projects", {})) != expected_projects:
            failures.append("evidence catalog does not contain exactly the four published projects")
        if sum(item.get("files", 0) for item in portfolio_projects.values()) != portfolio.get("total_files"):
            failures.append("portfolio project file counts do not sum to total_files")
        if sum(portfolio.get("categories", {}).values()) != portfolio.get("total_files"):
            failures.append("portfolio category counts do not sum to total_files")
        for slug, item in portfolio_projects.items():
            if sum(item.get(category, 0) for category in ("code", "data", "reports", "tests")) != item.get("files"):
                failures.append(f"portfolio category counts do not sum for {slug}")
        for slug, project in evidence.get("projects", {}).items():
            metric_ids = {item.get("id") for item in project.get("metrics", [])}
            if not project.get("series") or project.get("default_metric") not in metric_ids:
                failures.append(f"evidence series or default metric is invalid for {slug}")
            for row in project.get("series", []):
                if not metric_ids.issubset(row):
                    failures.append(f"evidence series omits a metric for {slug}")
                    break
        space_evidence = ROOT / "apps" / "space" / "evidence.json"
        if space_evidence.exists() and json.loads(space_evidence.read_text(encoding="utf-8")) != evidence:
            failures.append("website and Space evidence catalogs differ")

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

    if failures:
        raise SystemExit("Verification failed:\n- " + "\n- ".join(failures))
    print(f"verify-ok local={len(required)} online={len(PUBLIC_URLS) if args.online else 0}")


if __name__ == "__main__":
    main()
