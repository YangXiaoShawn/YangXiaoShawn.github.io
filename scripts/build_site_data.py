#!/usr/bin/env python3
"""Generate the public catalog and stable section pages from project.yaml files."""

from __future__ import annotations

import argparse
import html
import json
from datetime import date
from pathlib import Path

from build_research_portfolio import STORIES, build_architecture_and_monitor_html

try:
    import yaml
except ImportError:
    yaml = None

ROOT = Path(__file__).resolve().parents[1]
SITE_URL = "https://yangxiaoshawn.github.io"

SECTIONS = {
    "research": (
        "Research Portfolio",
        "Eight applied research projects with open methods, data, and evidence.",
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
        "Eight applied economics and quant projects, built end to end.",
    ),
}

DISPLAY_COPY = {slug: (story['title'], story['finding']) for slug, story in STORIES.items()}


def _simple_yaml_load(text: str) -> dict:
    """Fallback parser for flat/nested project.yaml files when PyYAML is absent."""
    result: dict = {}
    current_key: str | None = None
    current_subkey: str | None = None
    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        line = raw_line.strip()
        if indent == 0 and ":" in line:
            k, v = line.split(":", 1)
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            current_key = k
            current_subkey = None
            if v:
                result[k] = v
            else:
                result[k] = None
        elif indent == 2 and current_key:
            if line.startswith("- "):
                if not isinstance(result.get(current_key), list):
                    result[current_key] = []
                result[current_key].append(line[2:].strip().strip('"').strip("'"))
            elif ":" in line:
                sk, sv = line.split(":", 1)
                sk = sk.strip()
                sv = sv.strip().strip('"').strip("'")
                if not isinstance(result.get(current_key), dict):
                    result[current_key] = {}
                current_subkey = sk
                if sv:
                    result[current_key][sk] = sv
                else:
                    result[current_key][sk] = []
        elif indent == 4 and current_key and current_subkey and line.startswith("- "):
            if not isinstance(result[current_key].get(current_subkey), list):
                result[current_key][current_subkey] = []
            result[current_key][current_subkey].append(line[2:].strip().strip('"').strip("'"))
    return result


def parse_yaml(text: str) -> dict:
    if yaml is not None:
        return yaml.safe_load(text) or {}
    return _simple_yaml_load(text)


def project_paths() -> list[Path]:
    paths = list(ROOT.glob("*/project.yaml"))
    paths.extend(ROOT.glob("projects/*/project.yaml"))
    return sorted({path.resolve() for path in paths})


def load_projects() -> list[dict]:
    projects = []
    for path in project_paths():
        payload = parse_yaml(path.read_text(encoding="utf-8"))
        slug = payload.get("slug")
        if not slug:
            continue
        catalog = payload.get("catalog") or {}
        projects.append(
            {
                "title": payload.get("title", slug),
                "slug": slug,
                "summary": STORIES.get(slug, {}).get("finding", payload.get("summary", "")),
                "research_question": STORIES.get(slug, {}).get("title", payload.get("research_question", "")),
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
        status = html.escape(STORIES.get(project['slug'], {}).get('topic', 'Research'))
        fields = html.escape(STORIES.get(project['slug'], {}).get('method', ''))
        cards.append(
            f"""<article class="platform-card">
              <div class="section-kicker">{status}</div>
              <h3><a href="../projects/{slug}/">{title}</a></h3>
              <p>{summary}</p>
              <p class="card-note">{fields}</p>
              <a class="text-link" href="../projects/{slug}/">Read the study &amp; evidence →</a>
            </article>"""
        )
    return "\n".join(cards)


def section_page(slug: str, title: str, description: str, projects: list[dict]) -> str:
    canonical = f"{SITE_URL}/{slug}/"
    cards = project_links(projects)
    extra = ""
    hero_eyebrow = "Yang Xiao · Applied Economics & Quant"
    hero_title = title
    page_lead = description
    monitor_subpage = ""
    if slug == "datasets":
        extra = '<a class="button button-primary" href="https://huggingface.co/datasets/ShawnChamberlain/open-economic-quant-research-data">Open the full Dataset</a>'
    elif slug == "dashboards":
        extra = '<a class="button button-primary" href="https://huggingface.co/spaces/ShawnChamberlain/open-economic-quant-research-observatory">Open the live interactive lab</a>'
    elif slug == "daily-reports":
        hero_title = "Daily Trading & Release Archive"
        page_lead = "Day-by-day out-of-sample trading results, pre-registered signal books, and live-readiness stress audits across CryptoFactors and EMFactorTiming."
        extra = '<a class="button button-primary" href="#daily-monitor">Jump to daily tables ↓</a><a class="button button-secondary" href="../feed.xml">Subscribe to the update feed</a>'
        monitor_subpage = f"<!-- DAILY MONITOR SUBPAGE START -->{build_architecture_and_monitor_html('../')}<!-- DAILY MONITOR SUBPAGE END -->\n"
    elif slug == "updated-results":
        hero_title = "Updated Out-of-Sample & Daily Results"
        page_lead = "Versioned out-of-sample extensions, implementation shortfall stress tests, and daily trading comparisons."
        extra = '<a class="button button-primary" href="#daily-monitor">Jump to daily tables ↓</a><a class="button button-secondary" href="../index.html#research-lab">Browse the project signals</a>'
        monitor_subpage = f"<!-- DAILY MONITOR SUBPAGE START -->{build_architecture_and_monitor_html('../')}<!-- DAILY MONITOR SUBPAGE END -->\n"
    elif slug == "about":
        hero_title = "Yang Xiao"
        description = "I study how economic incentives, public policy, and information shape market outcomes."
        page_lead = description
        extra = '<a class="button button-primary" href="https://github.com/YangXiaoShawn">GitHub</a><a class="button button-secondary" href="../index.html#research">View work</a>'
    else:
        extra = '<a class="button button-secondary" href="../index.html#research-lab">Browse the project signals</a>'
    section_content = f'<div class="section-header"><div><div class="section-kicker">Selected research</div><h2 class="section-title">Eight questions, with the evidence in view.</h2></div></div><div class="platform-grid">{cards}</div>'
    if slug == 'about':
        section_content = '''<article class="about-narrative"><h2>Questions first. Evidence throughout.</h2><p>My work connects applied economics with quantitative research: who responds to an incentive, how data revisions affect a forecast, why mortgage loans stay in place, who bears a tariff, how much edge order flow carries, and whether factor premia hold across emerging markets, prediction markets, and crypto perpetuals.</p><p>All eight studies are consolidated into the unified <a href="https://github.com/YangXiaoShawn/open-economic-quant">open-economic-quant</a> monorepo, backed by <code>oeq-core v0.2.0</code> (shared Empirical Bayes shrinkage, Ledoit-Wolf covariance, Newey-West HAC, Politis-Romano bootstrap, and Deflated Sharpe Ratio primitives) and a live out-of-sample daily trading monitor tracking 105 crypto perpetuals and 49 US-listed emerging/developed market ETFs.</p><p>Each study starts with its central question and a plain-language conclusion. The figures show the supporting results; the notes explain the research design, assumptions, and remaining uncertainty. Exact values and published sources sit beside the charts.</p><p>The website is a guided introduction to the research. The interactive Space lets you compare metrics, inspect simulation scenarios, and browse the public evidence. Source repositories contain the methods and reproduction routes.</p><a class="text-link" href="../index.html#daily-monitor">Inspect the live daily trading monitor →</a> · <a class="text-link" href="../index.html#research">Explore the research studies →</a></article>'''
    if slug == 'methods':
        section_content = '<div class="platform-grid">' + ''.join(f'<article class="platform-card"><div class="section-kicker">{html.escape(story["topic"])}</div><h3>{html.escape(story["title"])}</h3><p>{html.escape(story["method"])}</p><p class="card-note">{html.escape(story["boundary"])}</p><a class="text-link" href="../projects/{key}/#method">Read the research design →</a></article>' for key, story in STORIES.items()) + '</div>'
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
  <link rel="stylesheet" href="../assets/css/portfolio.css" />
</head>
<body>
<a class="skip-link" href="#main">Skip to main content</a>
<header class="site-header"><div class="container header-inner">
  <a class="brand" href="../index.html"><span class="brand-mark">YX</span><span class="brand-copy"><span class="brand-title">Yang Xiao</span><span class="brand-subtitle">Research portfolio</span></span></a>
  <button class="nav-toggle" type="button" aria-expanded="false" aria-controls="site-nav" aria-label="Toggle navigation"><span></span></button>
  <nav class="site-nav" id="site-nav" aria-label="Primary navigation"><a href="../index.html">Home</a><a href="../research/">Research</a><a href="../datasets/">Datasets</a><a href="../methods/">Methods</a><a href="../about/">About</a></nav>
</div></header>
<main id="main">
  <section class="page-hero"><div class="container"><div class="breadcrumbs"><a href="../index.html">Home</a><span>{html.escape(title)}</span></div><div class="eyebrow">{html.escape(hero_eyebrow)}</div><h1>{html.escape(hero_title)}</h1><p class="page-lead">{html.escape(page_lead)}</p><div class="hero-actions">{extra}</div></div></section>
{monitor_subpage}  <section class="section section-border"><div class="container">{section_content}</div></section>
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
