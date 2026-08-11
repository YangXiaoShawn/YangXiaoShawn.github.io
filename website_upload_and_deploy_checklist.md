# Website Go-Live and Content Upload Map

| Content | Destination | Current state |
| --- | --- | --- |
| Complete `GithubIO` website repository | `github.com/YangXiaoShawn/YangXiaoShawn.github.io` | Upgraded English release live |
| Compact `casuallab/` package | `github.com/YangXiaoShawn/open-economic-quant-casuallab` | Live |
| Compact `macroeconomics/` package | `github.com/YangXiaoShawn/open-economic-quant-macroeconomics` | Live |
| Clean full CasualLab + Macroeconomics research content | `huggingface.co/datasets/ShawnChamberlain/open-economic-quant-research-data` | Live, cleaned, Dataset Card added |
| `apps/space/` interactive explorer | `huggingface.co/spaces/ShawnChamberlain/open-economic-quant-research-observatory` | Published; static runtime healthy |

## Files uploaded to GitHub Pages

- Site entry points: `index.html`, `404.html`, `robots.txt`, `sitemap.xml`, and `feed.xml`.
- Stable sections: `research/`, `replications/`, `updated-results/`, `datasets/`, `methods/`, `dashboards/`, `comparisons/`, `daily-reports/`, and `about/`.
- Permanent project pages: `projects/casuallab/` and `projects/macroeconomics/`.
- Shared assets and generated catalog: `assets/`.
- Compact public project copies: `casuallab/` and `macroeconomics/`.
- Reproducibility, manifests, governance, deployment scripts, and CI workflows.

## Files uploaded to each standalone GitHub project

Upload the corresponding compact package only. It contains source, tests, documentation, configuration, project metadata, and public fixtures. Do not upload full raw data, `.venv`, caches, credentials, or local system files.

## Files uploaded to Hugging Face Dataset

Upload the clean full research payload under `CasualLab/` and `Macroeconomics/`, plus `README.md` and `dataset_manifest.json`. Exclude local runtime environments and caches; these do not contribute to reproducibility and caused the earlier 42,779-file count.

## Files uploaded to Hugging Face Space

Upload only `apps/space/README.md`, `app.py`, and `requirements.txt`. Do not upload the full Dataset into the Space.

## Verification commands

```bash
make verify
make verify-online
```

The online gate must not pass until the Space exists and the upgraded Pages routes are public.
