# GithubIO Website Release and Content Upload Checklist

> Generated on: 2026-08-10

## Status

- [x] New folder created: `GithubIO`
- [x] Homepage added: `index.html`
- [x] Two project pages added:
  - `projects/casuallab/index.html`
  - `projects/macroeconomics/index.html`
- [x] Two upload-ready project copies prepared:
  - `casuallab/`
  - `macroeconomics/`
- [x] Style and interaction assets are in place under `assets/`
- [x] Upload-ready validation command set prepared

## A) Publish-ready files (root-level)

- `index.html`
- `projects/casuallab/index.html`
- `projects/macroeconomics/index.html`
- `casuallab/`
- `macroeconomics/`
- `manifests/project_inventory.json`
- `manifests/asset_inventory.csv`
- `manifests/publication_rights.csv`
- `manifests/deployment_map.yaml`
- `manifests/dataset_manifest.json`
- `manifests/deployed_resources.json`
- `docs/`
- `scripts/validate_projects.py`
- `scripts/verify_deployment.py`
- `upload_checklist.md`
- `final_publish_checklist.md`
- `website_upload_and_deploy_checklist.md`
- `README.md`

## B) Do not upload by default

- `upload_ready/` (local mirror only)
- `.DS_Store`
- temporary execution artifacts and `.venv/`
- private handoff notes if needed: `AUTH_HANDOFF.md`

## C) Local pre-launch checks

```bash
cd "/Users/shawn/Documents/intern projects/GithubIO"
python3 scripts/validate_projects.py
python3 scripts/verify_deployment.py
```

Expect:

- `validation-ok`
- `verify-ok`

## D) Deployment execution

### 1) GitHub-first

```bash
cd "/Users/shawn/Documents/intern projects/GithubIO"
GH_USER=<YOUR_GITHUB_USERNAME>
GH_REPO=<YOUR_REPO_NAME>

GH_USER="$GH_USER" GH_REPO="$GH_REPO" DRY_RUN_ONLY_GITHUB=true bash scripts/publish_playbook.sh
```

### 2) GitHub + Hugging Face (optional)

```bash
cd "/Users/shawn/Documents/intern projects/GithubIO"
GH_USER=<YOUR_GITHUB_USERNAME>
GH_REPO=<YOUR_REPO_NAME>
HF_USER=<YOUR_HF_USERNAME>

GH_USER="$GH_USER" GH_REPO="$GH_REPO" HF_USER="$HF_USER" bash scripts/publish_playbook.sh
```

### 3) One-click helper

```bash
cd "/Users/shawn/Documents/intern projects/GithubIO"
bash scripts/publish_quickstart.sh
```

## E) Post-deployment checks

- Confirm homepage and both project pages return 200.
- Confirm `project.yaml` and manifest links are correct.
- Confirm excluded directories are not deployed.
- Run `python3 scripts/verify_deployment.py` after cloning the published repository.

## F) Final release blockers

- GitHub Pages not enabled yet.
- External platform credentials (`gh`, `huggingface-cli`) were not completed during preparation.
- Verify `github_url/site_url/dataset_url/space_url` in project metadata with real URLs.
