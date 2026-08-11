# Content Upload Checklist

Updated: 2026-08-10

## GitHub Pages repository

- [x] Upload the complete `GithubIO` repository to `YangXiaoShawn/YangXiaoShawn.github.io`.
- [x] Include the static website, project pages, compact project copies, manifests, governance documents, scripts, and workflows.
- [x] Exclude credentials, `.env*`, `.venv`, caches, `.DS_Store`, and private keys.
- [ ] Push the prepared optimization release after the Space URL is live.
- [ ] Confirm the homepage, both project pages, ten section routes, `robots.txt`, `sitemap.xml`, `feed.xml`, assets, and 404 page return successfully.

## Standalone GitHub repositories

- [x] Upload `casuallab/` to `YangXiaoShawn/open-economic-quant-casuallab`.
- [x] Upload `macroeconomics/` to `YangXiaoShawn/open-economic-quant-macroeconomics`.
- [x] Keep these repositories compact: source, tests, docs, configs, schemas, and public fixtures.
- [x] Do not add full raw data or local Python environments to GitHub.

## Hugging Face Dataset

- [x] Publish the full research content from the original CasualLab and Macroeconomics projects.
- [x] Preserve code, data, reports, notebooks, tests, docs, and research outputs.
- [x] Remove only `.venv`, `.pytest_cache`, `.ruff_cache`, `__pycache__`, and `.DS_Store` artifacts.
- [x] Upload the Dataset Card and detailed clean-content manifest.
- [x] Confirm both project prefixes and approximately 2.85 GB of research content remain available.
- [ ] Reconfirm the final Dataset revision after metadata publication.

## Hugging Face Space

- [x] Prepare `apps/space/README.md`, `app.py`, requirements, and tests.
- [x] Configure project selection, search, Dataset browsing, status chart, methodology, fallbacks, and cross-platform links.
- [x] Run Space tests in the pinned Python 3.12 / Gradio environment: 2 passed.
- [ ] Obtain explicit authorization to create the new public Space.
- [ ] Deploy and confirm build, runtime, Dataset connection, and both projects.

## Final gate

- [x] `python3 scripts/build_site_data.py --check`
- [x] `python3 scripts/validate_projects.py`
- [x] `python3 scripts/verify_deployment.py`
- [ ] `python3 scripts/verify_deployment.py --online`
- [ ] Record final site, Dataset, and Space revisions in `manifests/deployed_resources.json`.
