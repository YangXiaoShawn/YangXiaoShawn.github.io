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
    "https://yangxiaoshawn.github.io/robots.txt",
    "https://yangxiaoshawn.github.io/sitemap.xml",
    "https://github.com/YangXiaoShawn/open-economic-quant-casuallab",
    "https://github.com/YangXiaoShawn/open-economic-quant-macroeconomics",
    "https://github.com/YangXiaoShawn/open-economic-quant-realestate",
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
        ROOT / "assets" / "data" / "projects.json",
        ROOT / "projects" / "casuallab" / "index.html",
        ROOT / "projects" / "macroeconomics" / "index.html",
        ROOT / "projects" / "realestate" / "index.html",
        ROOT / "apps" / "space" / "app.py",
        ROOT / "apps" / "space" / "README.md",
        ROOT / "apps" / "space" / "index.html",
    ]
    required.extend(ROOT / route / "index.html" for route in ROUTES)
    missing = [str(path.relative_to(ROOT)) for path in required if not path.exists()]
    failures = [f"missing {path}" for path in missing]

    catalog_path = ROOT / "assets" / "data" / "projects.json"
    if catalog_path.exists():
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        expected_projects = {"casuallab", "macroeconomics", "realestate"}
        if {item.get("slug") for item in catalog.get("projects", [])} != expected_projects:
            failures.append("generated catalog does not contain exactly the three published projects")

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
