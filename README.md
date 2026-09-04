# Open Quant & Econ

Yang Xiao's portfolio of five reproducible applied economics and quantitative research systems.

The portfolio introduces each project through its question, method, finding, and
direct evidence. Ten source-linked figures are shared by the website, project
pages, and static Space; each study includes exact values, interpretation, and
its evidence limits. The Space retains metric comparisons, scenario controls,
file search, and shareable project/metric views.

## Live resources

- Website: https://yangxiaoshawn.github.io/
- Website source: https://github.com/YangXiaoShawn/YangXiaoShawn.github.io
- CasualLab source: https://github.com/YangXiaoShawn/open-economic-quant-casuallab
- Macroeconomics source: https://github.com/YangXiaoShawn/open-economic-quant-macroeconomics
- Mortgage Rate Lock-In repository: https://github.com/YangXiaoShawn/open-economic-quant-realestate
- Tariff Incidence source: https://github.com/YangXiaoShawn/open-economic-quant-tariff-incidence
- Microstructure source: https://github.com/YangXiaoShawn/open-economic-quant-microstructure
- Full research dataset: https://huggingface.co/datasets/ShawnChamberlain/open-economic-quant-research-data
- Interactive Hugging Face Space: https://huggingface.co/spaces/ShawnChamberlain/open-economic-quant-research-observatory
- Static runtime revision: `e23e25623decf7621a38582cbc96fa7236cf3ffb`

## Published projects

| Project | Research area | Status | Reproduce |
| --- | --- | --- | --- |
| CasualLab | Causal inference, experimental economics, market design | Public live | `make reproduce` |
| Macroeconomics | Real-time macro forecasting and vintage analysis | Public live | `python -m macro_nowcast.pipeline` |
| Mortgage Rate Lock-In | Housing economics, mortgage finance, applied econometrics | Public live | `make reproduce-sample` |
| Tariff Incidence | International trade, tariff pass-through, supply-chain propagation | Public live | `make reproduce-sample` |
| Order Flow to Price Impact | Market microstructure, exploratory execution simulation | Public live · reference only | `make reproduce-sample` |

GitHub hosts compact public code, while Hugging Face provides the full research data and interactive evidence. Findings and publication boundaries remain explicit, including a checksum-verified Microstructure scenario summary.

## Repository architecture

- `index.html` and section directories contain the GitHub Pages site.
- `projects/` contains permanent project pages.
- `casuallab/`, `macroeconomics/`, `realestate/`, `tariff-incidence/`, and `microstructure/` are compact, upload-ready project copies.
- `apps/space/` contains the Hugging Face Space source.
- `manifests/` records inventory, publication rights, dataset state, and deployed resources.
- `scripts/` generates the catalog, validates releases, packages data, and verifies deployment.
- `docs/` records architecture, governance, reproducibility, security, and deployment policy.

## Quick start

```bash
python3 scripts/build_site_data.py
python3 scripts/build_research_portfolio.py
python3 scripts/validate_projects.py
python3 scripts/verify_deployment.py
```

Use `make verify-online` to include public URL checks. Dataset and Space publishing require an authenticated Hugging Face session; credentials are never stored in this repository.

## Adding a project

Create a project directory and a complete `project.yaml`, then run `python3 scripts/build_site_data.py`. The public catalog JSON, section pages, sitemap, and feed are regenerated from project metadata.

Research narration and figure generation live in `scripts/build_research_portfolio.py`.
`assets/data/research_details.json` holds compact, published aggregate extracts
with their source paths; `assets/data/evidence.json` supplies the existing metric
catalog. Run `make build` after editing the shared narration, CSS, or evidence.
Generated regions preserve the technical notes and interactive explorer. Do not
edit the generated SVGs or the Space copy of `portfolio.css` directly.

Housing figures distinguish adjusted complementary log-log associations from
unweighted, exit-enriched estimation-sample shares (2021–2023). Macro comparisons
distinguish strict as-of data from later revisions, and the GDP rank comparison
uses eight final-holdout forecasts. No licensed loan records are published.

## Data and publication policy

Code, small fixtures, schemas, and documentation belong on GitHub. Full publishable research data belongs in the Hugging Face Dataset. Raw assets with unknown redistribution rights remain marked `RIGHTS_UNKNOWN`; adding a new source requires a publication-rights review.

## Citation and contribution

See `CITATION.cff`, `CONTRIBUTING.md`, and `docs/REPRODUCIBILITY.md`. Security reports should follow `SECURITY.md` and must never include credentials in a public issue.
