# Open Economic & Quant Research Observatory

A public research platform for reproducible economics, finance, quantitative methods, data releases, and interactive project exploration.

## Live resources

- Website: https://yangxiaoshawn.github.io/
- Website source: https://github.com/YangXiaoShawn/YangXiaoShawn.github.io
- CasualLab source: https://github.com/YangXiaoShawn/open-economic-quant-casuallab
- Macroeconomics source: https://github.com/YangXiaoShawn/open-economic-quant-macroeconomics
- Full research dataset: https://huggingface.co/datasets/ShawnChamberlain/open-economic-quant-research-data
- Interactive observatory: https://huggingface.co/spaces/ShawnChamberlain/open-economic-quant-research-observatory

## Published projects

| Project | Research area | Status | Reproduce |
| --- | --- | --- | --- |
| CasualLab | Causal inference, experimental economics, market design | Public live | `make reproduce` |
| Macroeconomics | Real-time macro forecasting and vintage analysis | Public live | `python -m macro_nowcast.pipeline` |

The public GitHub copies are intentionally compact. The full research payload is versioned in the Hugging Face Dataset, while the Space reads from that dataset instead of duplicating it.

## Repository architecture

- `index.html` and section directories contain the GitHub Pages site.
- `projects/` contains permanent project pages.
- `casuallab/` and `macroeconomics/` are compact, upload-ready project copies.
- `apps/space/` contains the Hugging Face Space source.
- `manifests/` records inventory, publication rights, dataset state, and deployed resources.
- `scripts/` generates the catalog, validates releases, packages data, and verifies deployment.
- `docs/` records architecture, governance, reproducibility, security, and deployment policy.

## Quick start

```bash
python3 scripts/build_site_data.py
python3 scripts/validate_projects.py
python3 scripts/verify_deployment.py
```

Use `make verify-online` to include public URL checks. Dataset and Space publishing require an authenticated Hugging Face session; credentials are never stored in this repository.

## Adding a project

Create a project directory and a complete `project.yaml`, then run `python3 scripts/build_site_data.py`. The public catalog JSON, section pages, sitemap, and feed are regenerated from project metadata.

## Data and publication policy

Code, small fixtures, schemas, and documentation belong on GitHub. Full publishable research data belongs in the Hugging Face Dataset. Raw assets with unknown redistribution rights remain marked `RIGHTS_UNKNOWN`; adding a new source requires a publication-rights review.

## Citation and contribution

See `CITATION.cff`, `CONTRIBUTING.md`, and `docs/REPRODUCIBILITY.md`. Security reports should follow `SECURITY.md` and must never include credentials in a public issue.
