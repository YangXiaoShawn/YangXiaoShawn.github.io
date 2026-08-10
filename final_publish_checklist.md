# Final Publish Checklist (GithubIO)

## 1) Preflight before deploy

- [x] Homepage and project pages are created and point to the two publication copies.
- [x] Project directories are prepared for upload:
  - `casuallab/`
  - `macroeconomics/`
- [x] Release manifests and validation scripts exist:
  - `scripts/validate_projects.py`
  - `scripts/verify_deployment.py`
- [x] Local checks were run:
  - `validation-ok`
  - `verify-ok`

## 2) Repository content to publish

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
- `scripts/validate_projects.py`
- `scripts/verify_deployment.py`

## 3) GitHub-only publish (recommended first)

```bash
cd "/Users/shawn/Documents/intern projects/GithubIO"
GH_USER=<YOUR_GITHUB_USERNAME>
GH_REPO=<YOUR_REPOSITORY_NAME>

GH_USER="$GH_USER" \
GH_REPO="$GH_REPO" \
DRY_RUN_ONLY_GITHUB=true \
bash scripts/publish_playbook.sh
```

Acceptance output (minimum):

- `validation-ok`
- `verify-ok`
- `Publish flow completed (GitHub only).`

## 4) GitHub + Hugging Face (optional)

```bash
cd "/Users/shawn/Documents/intern projects/GithubIO"
GH_USER=<YOUR_GITHUB_USERNAME>
GH_REPO=<YOUR_REPOSITORY_NAME>
HF_USER=<YOUR_HF_USERNAME>

GH_USER="$GH_USER" \
GH_REPO="$GH_REPO" \
HF_USER="$HF_USER" \
bash scripts/publish_playbook.sh
```

If HF is unavailable in your environment, the script will safely skip it and continue with GitHub deployment.

## 5) Assisted interactive flow

```bash
cd "/Users/shawn/Documents/intern projects/GithubIO"
bash scripts/publish_quickstart.sh
```

## 6) Site verification after deployment

```bash
# Replace <github_user> and <repo>
curl -I https://<github_user>.github.io/<repo>/
curl -I https://<github_user>.github.io/<repo>/projects/casuallab/index.html
curl -I https://<github_user>.github.io/<repo>/projects/macroeconomics/index.html
```

Checklist:

- [ ] Both project pages return 200
- [ ] `manifests/deployment_map.yaml` and `manifests/project_inventory.json` are published and accessible
- [ ] `scripts/verify_deployment.py` can be re-run in the deployed repository clone

## 7) Post-deploy metadata updates

Run once real URLs are known:

```bash
bash scripts/finalize_publish_metadata.sh
```
