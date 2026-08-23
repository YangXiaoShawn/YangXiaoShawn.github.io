#!/usr/bin/env python3
"""Generate the public catalog and stable section pages from project.yaml files."""

from __future__ import annotations

import argparse
import html
import json
from datetime import date
from pathlib import Path

try:
    import yaml
except ImportError as exc:  # pragma: no cover - actionable CLI failure
    raise SystemExit("Install requirements-dev.txt before building the catalog.") from exc

ROOT = Path(__file__).resolve().parents[1]
SITE_URL = "https://yangxiaoshawn.github.io"

SECTIONS = {
    "research": (
        "Research Portfolio",
        "Five applied research systems with open methods, data, and evidence.",
    ),
    "replications": (
        "Replication Library",
        "Reproduction routes, sources, and validation boundaries.",
    ),
    "updated-results": (
        "Updated Results",
        "Versioned results with complete source and validation records.",
    ),
    "datasets": (
        "Dataset Catalog",
        "Versioned data on Hugging Face; compact fixtures on GitHub.",
    ),
    "methods": (
        "Methods Library",
        "Econometrics, forecasting, data engineering, and reproducibility.",
    ),
    "dashboards": (
        "Interactive Dashboards",
        "Interactive projects, metrics, and evidence.",
    ),
    "comparisons": (
        "Research Comparisons",
        "Matched benchmarks and versioned comparisons.",
    ),
    "daily-reports": (
        "Daily Report Archive",
        "Audited updates and release records.",
    ),
    "about": (
        "About",
        "Five applied economics and quant projects, built end to end.",
    ),
}

DISPLAY_COPY = {
    "casuallab": ("Spillover-Aware Experiments", "An estimand-first lab for experiments and policy tests."),
    "macroeconomics": ("Real-Time Macro", "A vintage-aware engine that reconstructs each forecast date."),
    "realestate": ("Mortgage Lock-In", "A point-in-time system linking rate gaps to housing outcomes."),
    "tariff-incidence": ("Tariff Policy Engine", "A Section 301 engine for incidence, sourcing, and exposure."),
    "microstructure": ("Execution Stress Test", "A leakage-safe framework for fees, latency, fills, and drawdown."),
}


def project_paths() -> list[Path]:
    paths = list(ROOT.glob("*/project.yaml"))
    paths.extend(ROOT.glob("projects/*/project.yaml"))
    return sorted({path.resolve() for path in paths})


def load_projects() -> list[dict]:
    projects = []
    for path in project_paths():
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        slug = payload.get("slug")
        if not slug:
            continue
        catalog = payload.get("catalog") or {}
        projects.append(
            {
                "title": payload.get("title", slug),
                "slug": slug,
                "summary": payload.get("summary", ""),
                "research_question": payload.get("research_question", ""),
                "research_fields": payload.get("research_fields", []),
                "project_type": payload.get("project_type", "research"),
                "status": payload.get("status", "unknown"),
                "last_updated": str(payload.get("last_updated", "")),
                "field": catalog.get("field", slug),
                "accent": catalog.get("accent", "teal"),
                "tags": catalog.get("tags", payload.get("research_fields", [])),
                "metric": catalog.get("metric", "Reproducible package"),
                "site_url": payload.get("site_url", f"{SITE_URL}/projects/{slug}/"),
                "github_url": payload.get("github_url", ""),
                "dataset_url": payload.get("dataset_url", ""),
                "space_url": payload.get("space_url", ""),
            }
        )
    return sorted(projects, key=lambda item: item["slug"])


def project_links(projects: list[dict]) -> str:
    cards = []
    for project in projects:
        display_title, display_summary = DISPLAY_COPY.get(
            project["slug"], (project["title"], project["summary"])
        )
        title = html.escape(display_title)
        summary = html.escape(display_summary)
        slug = html.escape(project["slug"])
        status = "Published"
        fields = " / ".join(html.escape(value) for value in project["research_fields"])
        cards.append(
            f"""<article class="platform-card">
              <div class="section-kicker">{status}</div>
              <h3><a href="../projects/{slug}/">{title}</a></h3>
              <p>{summary}</p>
              <p class="card-note">{fields}</p>
              <a class="text-link" href="../projects/{slug}/">View project</a>
            </article>"""
        )
    return "\n".join(cards)


def section_page(slug: str, title: str, description: str, projects: list[dict]) -> str:
    canonical = f"{SITE_URL}/{slug}/"
    cards = project_links(projects)
    extra = ""
    hero_eyebrow = "Yang Xiao · Applied Economics & Quant"
    hero_title = title
    if slug == "datasets":
        extra = '<a class="button button-primary" href="https://huggingface.co/datasets/ShawnChamberlain/open-economic-quant-research-data">Open the full Dataset</a>'
    elif slug == "dashboards":
        extra = '<a class="button button-primary" href="https://huggingface.co/spaces/ShawnChamberlain/open-economic-quant-research-observatory">Open the live interactive lab</a>'
    elif slug == "daily-reports":
        extra = '<a class="button button-secondary" href="../feed.xml">Subscribe to the update feed</a>'
    elif slug == "about":
        hero_title = "Research, built end to end."
        extra = '<a class="button button-primary" href="https://github.com/YangXiaoShawn">GitHub</a><a class="button button-secondary" href="../index.html#research">View work</a>'
    else:
        extra = '<a class="button button-secondary" href="../index.html#research-lab">Browse the project signals</a>'
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{html.escape(title)} | Open Quant &amp; Econ</title>
  <meta name="description" content="{html.escape(description)}" />
  <link rel="canonical" href="{canonical}" />
  <link rel="icon" href="../assets/favicon.svg" type="image/svg+xml" />
  <link rel="stylesheet" href="../assets/css/styles.css" />
</head>
<body>
<a class="skip-link" href="#main">Skip to main content</a>
<header class="site-header"><div class="container header-inner">
  <a class="brand" href="../index.html"><span class="brand-mark">OQ</span><span class="brand-copy"><span class="brand-title">Open Quant &amp; Econ</span><span class="brand-subtitle">Research portfolio</span></span></a>
  <button class="nav-toggle" type="button" aria-expanded="false" aria-controls="site-nav" aria-label="Toggle navigation"><span></span></button>
  <nav class="site-nav" id="site-nav" aria-label="Primary navigation"><a href="../index.html">Home</a><a href="../research/">Research</a><a href="../datasets/">Datasets</a><a href="../methods/">Methods</a><a href="../about/">About</a></nav>
</div></header>
<main id="main">
  <section class="page-hero"><div class="container"><div class="breadcrumbs"><a href="../index.html">Home</a><span>{html.escape(title)}</span></div><div class="eyebrow">{html.escape(hero_eyebrow)}</div><h1>{html.escape(hero_title)}</h1><p class="page-lead">{html.escape(description)}</p><div class="hero-actions">{extra}</div></div></section>
  <section class="section section-border"><div class="container"><div class="section-header"><div><div class="section-kicker">Published work</div><h2 class="section-title">{len(projects)} projects. Open evidence.</h2></div></div><div class="platform-grid">{cards}</div></div></section>
</main>
<footer class="site-footer"><div class="container"><div class="footer-bottom"><span>Open Quant &amp; Econ</span><a class="text-link" href="../index.html">Back to homepage</a></div></div></footer>
<script src="../assets/js/app.js"></script>
</body>
</html>
"""


def sitemap(projects: list[dict], release_date: str) -> str:
    routes = ["", *[f"{slug}/" for slug in SECTIONS]]
    routes.extend(f"projects/{project['slug']}/" for project in projects)
    rows = "\n".join(
        f"  <url><loc>{SITE_URL}/{route}</loc><lastmod>{release_date}</lastmod></url>"
        for route in routes
    )
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{rows}\n</urlset>\n'


def feed(projects: list[dict], release_date: str) -> str:
    updated_at = f"{release_date}T00:00:00Z"
    entries = []
    for project in projects:
        entries.append(
            f"""  <entry><title>{html.escape(project['title'])}</title><id>{SITE_URL}/projects/{project['slug']}/</id><link href="{SITE_URL}/projects/{project['slug']}/"/><updated>{updated_at}</updated><summary>{html.escape(project['summary'])}</summary></entry>"""
        )
    return f'''<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>Open Quant &amp; Econ Updates</title><id>{SITE_URL}/</id><link href="{SITE_URL}/feed.xml" rel="self"/><updated>{updated_at}</updated>{''.join(entries)}</feed>
'''


def emit(path: Path, content: str, check: bool) -> bool:
    current = path.read_text(encoding="utf-8") if path.exists() else None
    if current == content:
        return False
    if check:
        raise SystemExit(f"Generated file is stale: {path.relative_to(ROOT)}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="Fail if generated files are stale.")
    args = parser.parse_args()
    projects = load_projects()
    if not projects:
        raise SystemExit("No project.yaml files were found.")

    changed = 0
    release_date = max((project["last_updated"] for project in projects), default=date.today().isoformat())
    payload = {"generated_at": release_date, "projects": projects}
    changed += emit(
        ROOT / "assets" / "data" / "projects.json",
        json.dumps(payload, indent=2, ensure_ascii=True) + "\n",
        args.check,
    )
    for slug, (title, description) in SECTIONS.items():
        changed += emit(ROOT / slug / "index.html", section_page(slug, title, description, projects), args.check)
    changed += emit(ROOT / "sitemap.xml", sitemap(projects, release_date), args.check)
    changed += emit(ROOT / "feed.xml", feed(projects, release_date), args.check)
    print(f"catalog-ok projects={len(projects)} changed={changed}")


if __name__ == "__main__":
    main()
