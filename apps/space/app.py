"""Interactive explorer for Open Quant & Econ."""

from __future__ import annotations

import os
from dataclasses import dataclass

import gradio as gr
import pandas as pd
from huggingface_hub import HfApi

DATASET_REPO = os.getenv("HF_DATASET_REPO", "ShawnChamberlain/open-economic-quant-research-data")
DATASET_REVISION = os.getenv("HF_DATASET_REVISION", "5329ac0f88bae309d6e37eb8fdaefc0f60754f4c")
SITE_URL = os.getenv("SITE_URL", "https://yangxiaoshawn.github.io")
GITHUB_URL = os.getenv("GITHUB_REPOSITORY_URL", "https://github.com/YangXiaoShawn/YangXiaoShawn.github.io")


@dataclass(frozen=True)
class Project:
    title: str
    slug: str
    prefix: str
    field: str
    question: str
    summary: str
    methodology: str
    source_url: str


PROJECTS = {
    "CasualLab": Project(
        title="CasualLab",
        slug="casuallab",
        prefix="CasualLab",
        field="Causal inference",
        question="How do causal mechanisms and heterogeneous treatment effects shape market outcomes and policy interventions?",
        summary="Known-truth HTE RMSE is 0.0417 versus 0.0247 for the oracle; the recovery gate is not met.",
        methodology="Define an estimand, document identification assumptions, recover effects on fixtures or authorized public data, validate estimator behavior, and publish a traceable result manifest.",
        source_url="https://github.com/YangXiaoShawn/open-economic-quant-casuallab",
    ),
    "Macroeconomics": Project(
        title="Macroeconomics",
        slug="macroeconomics",
        prefix="Macroeconomics",
        field="Macroeconomic forecasting",
        question="How do release revisions and the information available at each vintage affect real-time forecast quality?",
        summary="Valid modes use zero future cells; the naive revised-data benchmark changes model rankings.",
        methodology="Record source availability, align observations to their real-time vintage, prevent revised-data leakage, backtest models on comparable information sets, and label current revised APIs honestly.",
        source_url="https://github.com/YangXiaoShawn/open-economic-quant-macroeconomics",
    ),
    "RealEstate": Project(
        title="Mortgage Rate Lock-In and Housing Market Dynamics",
        slug="realestate",
        prefix="RealEstate",
        field="Housing economics and mortgage finance",
        question="How does the gap between existing mortgage rates and current market rates affect mortgage exits, local activity, prices, and construction?",
        summary="Each +1 pp rate gap is associated with a 0.817 exit-hazard ratio; the estimate is not causal.",
        methodology="Construct point-in-time lock-in measures, model mortgage-exit hazards, freeze predetermined local exposure for event studies, auto-demote results when diagnostics fail, and label counterfactuals as simulations rather than forecasts.",
        source_url="https://github.com/YangXiaoShawn/open-economic-quant-realestate",
    ),
    "TariffIncidence": Project(
        title="Tariff Incidence, Supply-Chain Reallocation, and Domestic Propagation",
        slug="tariff-incidence",
        prefix="TariffIncidence",
        field="International trade and applied econometrics",
        question="How did U.S. product-level tariffs on imports from China pass through to importers, reshape sourcing, and propagate through domestic input-output linkages?",
        summary="Customs values stay near +0.025 within ±0.076; landed values track the tariff.",
        methodology="Parse legal notices against their stated line counts, construct a provenance-stamped HS10 panel, estimate each outcome under a stacked design, require pre-trend and placebo diagnostics before causal language, and keep observed evidence separate from model-implied counterfactuals.",
        source_url="https://github.com/YangXiaoShawn/open-economic-quant-tariff-incidence",
    ),
    "Microstructure": Project(
        title="Order Flow to Price Impact",
        slug="microstructure",
        prefix="Microstructure",
        field="Market microstructure and quantitative finance",
        question="Can a short-horizon order-flow signal survive explicit fees, latency, fills, inventory, and drawdown?",
        summary="Research reference only: 110 of 144 scenarios are gross-positive; none remain net-positive after the 4 bp fee.",
        methodology="Preserve event ordering, prevent temporal leakage, evaluate pseudoheldout phases separately, and expose fees and turnover-normalized marked drawdown. Research reference only—not live performance.",
        source_url="https://github.com/YangXiaoShawn/open-economic-quant-microstructure",
    ),
}

FALLBACK_ROWS = pd.DataFrame(
    [
        {"path": "data/fixtures/", "kind": "sample data", "status": "available"},
        {"path": "src/", "kind": "research code", "status": "available"},
        {"path": "tests/", "kind": "validation", "status": "available"},
    ]
)


def _dataset_rows(project: Project) -> tuple[pd.DataFrame, str]:
    api = HfApi()
    try:
        info = api.dataset_info(DATASET_REPO, revision=DATASET_REVISION, files_metadata=False)
        nodes = api.list_repo_tree(
            DATASET_REPO,
            path_in_repo=project.prefix,
            repo_type="dataset",
            revision=DATASET_REVISION,
            recursive=False,
            expand=False,
        )
        rows = []
        for node in list(nodes)[:50]:
            path = getattr(node, "path", "")
            rows.append(
                {
                    "path": path,
                    "kind": "file" if hasattr(node, "size") else "directory",
                    "size_bytes": getattr(node, "size", None),
                }
            )
        frame = pd.DataFrame(rows) if rows else FALLBACK_ROWS.copy()
        return frame, info.sha
    except Exception as exc:  # Space must keep a useful fallback state.
        return FALLBACK_ROWS.copy(), f"fallback ({type(exc).__name__})"


def explore(project_name: str, search: str = ""):
    project = PROJECTS[project_name]
    rows, revision = _dataset_rows(project)
    query = search.strip().lower()
    if query and "path" in rows:
        rows = rows[rows["path"].astype(str).str.lower().str.contains(query, regex=False)]
    summary = f"""## {project.title}

**Field:** {project.field}  
**Research question:** {project.question}

{project.summary}

**Dataset revision:** `{revision}`

[Permanent project page]({SITE_URL}/projects/{project.slug}/) | [GitHub source]({project.source_url}) | [Full Dataset](https://huggingface.co/datasets/{DATASET_REPO})
"""
    methodology = f"""### Methodology and evidence boundary

{project.methodology}

The interface does not invent original-versus-replicated numbers. A comparison becomes publishable only after its benchmark, sample period, configuration, output manifest, and validation record are available.
"""
    chart = pd.DataFrame(
        {
            "stage": ["Source", "Standardize", "Validate", "Publish"],
            "coverage": [100, 100, 100, 100],
            "project": [project.title] * 4,
        }
    )
    return summary, rows, chart, methodology


CSS = """
.gradio-container { max-width: 1220px !important; }
.hero-panel { border: 1px solid #d6e4e1; border-radius: 24px; padding: 28px; background: linear-gradient(135deg,#f4fbf9,#eef5fb); }
.hero-panel h1 { font-family: Georgia, serif; letter-spacing: -0.04em; }
"""

with gr.Blocks(title="Open Quant & Econ — Evidence Lab", css=CSS) as demo:
    gr.Markdown(
        f"""<div class="hero-panel"><p>Yang Xiao · Applied Economics &amp; Quant</p><h1>Open Quant &amp; Econ</h1><p>Explore the work. Verify the evidence.</p><p>Five questions, methods, and evidence-backed findings.</p><p><a href="{SITE_URL}">Website</a> &middot; <a href="{GITHUB_URL}">GitHub</a> &middot; <a href="https://huggingface.co/datasets/{DATASET_REPO}">Dataset</a></p></div>"""
    )
    with gr.Row():
        project_input = gr.Dropdown(list(PROJECTS), value="CasualLab", label="Project")
        search_input = gr.Textbox(label="Filter representative paths", placeholder="data, tests, reports...")
        refresh = gr.Button("Explore", variant="primary")
    with gr.Tabs():
        with gr.Tab("Project summary"):
            summary_output = gr.Markdown()
        with gr.Tab("Dataset browser"):
            files_output = gr.Dataframe(interactive=False, wrap=True)
        with gr.Tab("Replication status"):
            chart_output = gr.BarPlot(x="stage", y="coverage", color="project", y_lim=[0, 110], title="Documented release-stage coverage")
        with gr.Tab("Methodology"):
            method_output = gr.Markdown()
    outputs = [summary_output, files_output, chart_output, method_output]
    refresh.click(explore, [project_input, search_input], outputs)
    project_input.change(explore, [project_input, search_input], outputs)
    demo.load(explore, [project_input, search_input], outputs)


if __name__ == "__main__":
    demo.launch()
