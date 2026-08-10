#!/usr/bin/env bash
set -euo pipefail

# Publish playbook for GithubIO
# Usage:
#   GH_USER=your_github_user (required)
#   GH_REPO=your_github_repo (required)
#   HF_USER=your_hf_user (optional if DRY_RUN_ONLY_GITHUB=true)
#   HF_DATASET_REPO=${HF_USER}/open-economic-quant-research-data (optional)
#   HF_SPACE_REPO=${HF_USER}/open-economic-quant-research-observatory (optional)
#   bash scripts/publish_playbook.sh

: "${GH_USER:?set GH_USER}"
: "${GH_REPO:?set GH_REPO}"

HF_USER="${HF_USER:-$GH_USER}"
HF_DATASET_REPO="${HF_DATASET_REPO:-${HF_USER}/open-economic-quant-research-data}"
HF_SPACE_REPO="${HF_SPACE_REPO:-${HF_USER}/open-economic-quant-research-observatory}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
DRY_RUN_ONLY_GITHUB="${DRY_RUN_ONLY_GITHUB:-false}"

cd "$ROOT_DIR"

echo "=== Step 1) local checks ==="
python3 scripts/validate_projects.py
python3 scripts/verify_deployment.py

echo "=== Step 2) GitHub publish ==="
if ! command -v gh >/dev/null 2>&1; then
  echo "gh not found: install GitHub CLI first" >&2
  exit 1
fi

gh auth status

if [ ! -d .git ]; then
  git init
  git config user.name "${GH_USER}" || true
  git config user.email "${GH_USER}@users.noreply.github.com" || true
fi

git add .
if ! git diff --cached --quiet; then
  git commit -m "feat: prepare GithubIO website and publish-ready project copies"
else
  echo "No changes to commit for initial publish step."
fi

git remote remove origin 2>/dev/null || true
git remote add origin "https://github.com/${GH_USER}/${GH_REPO}.git"
git branch -M main

git push -u origin main

echo "=== Step 2b) Ensure GitHub Pages config ==="
if gh repo view "${GH_USER}/${GH_REPO}" >/dev/null 2>&1; then
  echo "Repository exists."
else
  echo "Repository check failed; please confirm repo URL and auth scope." >&2
fi

# Configure Pages source if supported by API
if gh api -H "Accept: application/vnd.github+json" /repos/${GH_USER}/${GH_REPO}/pages >/dev/null 2>&1; then
  if gh api --method PATCH -H "Accept: application/vnd.github+json" /repos/${GH_USER}/${GH_REPO}/pages \
    -f source[branch]=main -f source[path]=/ >/tmp/gh-pages-patch.out 2>/tmp/gh-pages-patch.err; then
    echo "Pages API patch succeeded."
  else
    echo "Pages API patch failed; configure Pages in repo settings manually." >&2
    cat /tmp/gh-pages-patch.err >&2 || true
  fi
  gh api /repos/${GH_USER}/${GH_REPO}/pages || true
else
  echo "Pages API not available for this repository/user role; configure via GitHub UI."
fi

git checkout -B main

git add manifests/deployment_map.yaml manifests/deployed_resources.json DEPLOYMENT_REPORT.md || true
if git diff --cached --quiet; then
  echo "No deployment metadata updates to commit."
else
  git commit -m "chore: record deployment metadata placeholders"
  git push
fi

echo "=== Step 3) Optional Hugging Face upload ==="
if [ "$DRY_RUN_ONLY_GITHUB" = "true" ]; then
  echo "DRY_RUN_ONLY_GITHUB=true, skip HF upload."
  echo "Publish flow completed (GitHub only)."
  exit 0
fi

if ! command -v huggingface-cli >/dev/null 2>&1; then
  echo "huggingface-cli not found; skip HF upload for now."
  echo "Publish flow completed (GitHub only, HF skipped)."
  exit 0
fi

if command -v hf >/dev/null 2>&1; then
  hf auth whoami || true
fi
python3 -m pip install --upgrade "huggingface_hub[cli]" >/tmp/publish_hf_install.log 2>&1 || true

cd /tmp
huggingface-cli repo create "${HF_DATASET_REPO}" --type dataset --exist-ok
huggingface-cli upload "${HF_DATASET_REPO}" "${ROOT_DIR}/upload_ready/casuallab" / --repo-type dataset
huggingface-cli upload "${HF_DATASET_REPO}" "${ROOT_DIR}/upload_ready/macroeconomics" / --repo-type dataset

cat > "$ROOT_DIR/manifests/deployed_resources.json" <<JSON
{
  "repository": {
    "github_repository": "https://github.com/${GH_USER}/${GH_REPO}",
    "github_pages_url": "https://${GH_USER}.github.io/${GH_REPO}"
  },
  "huggingface": {
    "dataset_repo": "https://huggingface.co/datasets/${HF_DATASET_REPO}",
    "space_repo": "${HF_SPACE_REPO}"
  }
}
JSON

echo "Publish playbook finished. Please verify Pages URL and links manually."
echo "Expected Pages URL: https://${GH_USER}.github.io/${GH_REPO}"
