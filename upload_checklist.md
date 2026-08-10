# Website Go-live and Content Upload Checklist (GithubIO)

> Generated: 2026-08-10

## 1) Repository readiness

- [x] Homepage entry page created: `index.html`
- [x] Project pages created:
  - `projects/casuallab/index.html`
  - `projects/macroeconomics/index.html`
- [x] Release manifest files exist and are readable:
  - `manifests/project_inventory.json`
  - `manifests/asset_inventory.csv`
  - `manifests/publication_rights.csv`
- [x] Validation scripts are prepared:
  - `scripts/validate_projects.py`
  - `scripts/verify_deployment.py`

## 2) Upload package preparation (complete)

### `casuallab`

- [x] Project directory copied and normalized: `GithubIO/casuallab`
- [x] Key folders kept: `src/`, `tests/`, `reports/`, `scripts/`, `configs/`, `fixtures/`, `data/fixtures/`, `data/nyc_sample/`, `portfolio/`
- [x] Project descriptors kept: `README.md`, `project.yaml`, `STATUS.md`, `.gitignore`
- [x] Non-upload folders removed/blocked:
  - `raw/`
  - `artifacts/`
  - `generated/`
  - `tmp/`
  - `.git/`
  - `.venv/`

### `macroeconomics`

- [x] Project directory copied and normalized: `GithubIO/macroeconomics`
- [x] Key folders kept: `src/`, `tests/`, `reports/`, `scripts/`, `configs/`, `fixtures/`, `data/fixtures/`, `portfolio/`
- [x] Project descriptors kept: `README.md`, `project.yaml`, `STATUS.md`, `.gitignore`
- [x] Non-upload folders removed/blocked:
  - `raw/`
  - `artifacts/`
  - `generated/`
  - `tmp/`
  - `.git/`
  - `.venv/`

## 3) Sensitive or excluded paths (do not publish)

- [x] `casuallab/.venv`, `.pytest_cache`, `.ruff_cache`, `__pycache__`
- [x] `macroeconomics/.venv`, `.pytest_cache`, `.ruff_cache`, `__pycache__`
- [x] Removed and excluded raw/intermediate content (`raw`, `artifacts`, `generated`, `tmp`)
- [x] Git directories removed from project copies

## 4) Mirror verification

- [x] Archive mirror directories preserved:
  - `upload_ready/casuallab`
  - `upload_ready/macroeconomics`
- [x] `upload_ready/` follows same prune rules as public directories

## 5) Local pre-publish validation (run before each release)

```bash
cd "/Users/shawn/Documents/intern projects/GithubIO"
python3 scripts/validate_projects.py
python3 scripts/verify_deployment.py
```

## 6) Human confirmations required before release

- [ ] Replace placeholder URLs in both project `project.yaml` files:
  - `github_url`
  - `site_url`
  - `dataset_url`
  - `space_url`
- [ ] Confirm data and code license compatibility for publishable files
- [ ] Confirm HF auth token/credential context is not committed in source
- [ ] Verify links from homepage to project pages and docs after deployment

## 7) Publish workflow (shortest path)

1. Run local validation and confirm `validation-ok` and `verify-ok`.
2. Open `index.html` in a browser and confirm links to:
   - `projects/casuallab/index.html`
   - `projects/macroeconomics/index.html`
3. If Git is configured:
   ```bash
   cd "/Users/shawn/Documents/intern projects/GithubIO"
   git init
   git add .
   git commit -m "Init GithubIO publication site and upload-ready copies"
   git remote add origin <YOUR_GITHUB_REPO_URL>
   git branch -M main
   git push -u origin main
   ```
4. Enable GitHub Pages: branch `main`, folder `/ (root)`.
5. Publish all project entries and project pages:
   - `casuallab/`
   - `macroeconomics/`
   - `projects/casuallab/index.html`
   - `projects/macroeconomics/index.html`
6. Confirm post-publish assets and metadata:
   - Homepage and both project pages reachable
   - `casuallab/project.yaml`, `macroeconomics/project.yaml`
   - `.gitignore` files for upload boundaries
7. Optional external platform uploads (requires separate auth):
   - `gh auth status`, `hf auth whoami`
   - HF dataset/space uploads if needed

## 8) Expected post-release checks

- [ ] Site homepage returns HTTP 200
- [ ] Both project pages return HTTP 200
- [ ] Project cards and links work on the published site
- [ ] `git status` contains no excluded or sensitive large paths

## 9) Upload scope by directory

- [ ] Upload at repository root (required):
  - `index.html`
  - `projects/casuallab/index.html`
  - `projects/macroeconomics/index.html`
  - `casuallab/`
  - `macroeconomics/`
  - `manifests/`
  - `docs/`
  - `upload_checklist.md`
  - `final_publish_checklist.md`
  - `website_upload_and_deploy_checklist.md`
  - `README.md`
- [ ] Upload at repository root (supporting scripts):
  - `scripts/validate_projects.py`
  - `scripts/verify_deployment.py`

- [ ] Do not upload:
  - `upload_ready/` (mirror only)
  - `.DS_Store`
  - `.codex/`, `.agents/`
  - `.venv/` and command-line temporary files

## 10) Optional one-off packaging command

```bash
cd "/Users/shawn/Documents/intern projects/GithubIO"
tar -czf githubio-site-and-projects-$(date +%Y%m%d).tar.gz \
  index.html upload_checklist.md final_publish_checklist.md website_upload_and_deploy_checklist.md \
  projects casuallab macroeconomics manifests docs scripts
```

## 11) One-click execution flow (when auth is available)

If `gh` / `hf` credentials are available in the shell environment, run:

```bash
cd "/Users/shawn/Documents/intern projects/GithubIO"
bash scripts/publish_quickstart.sh
```

Or use the command helper templates:
- [`scripts/publish_playbook.sh`](/Users/shawn/Documents/intern%20projects/GithubIO/scripts/publish_playbook.sh)
- [`scripts/emit_publish_commands.sh`](/Users/shawn/Documents/intern%20projects/GithubIO/scripts/emit_publish_commands.sh)
