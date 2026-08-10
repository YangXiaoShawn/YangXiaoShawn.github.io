#!/usr/bin/env bash
set -euo pipefail

: "${GH_USER:?Set GH_USER to your GitHub username}"
: "${GH_REPO:?Set GH_REPO to your repository name}"
: "${HF_USER:=${GH_USER}}"
: "${MODE:=github_only}"
: "${DO_POST_METADATA:=true}"

cd '/Users/shawn/Documents/intern projects/GithubIO'

echo "== Step 1: local checks =="
python3 scripts/validate_projects.py
python3 scripts/verify_deployment.py

echo "== Step 2: publish to GitHub (and optionally HF) =="
if [[ "${MODE}" == "github_hf" ]]; then
  export GH_USER
  export GH_REPO
  export HF_USER
  export DRY_RUN_ONLY_GITHUB=false
else
  export GH_USER
  export GH_REPO
  export DRY_RUN_ONLY_GITHUB=true
fi

bash scripts/publish_playbook.sh

echo "== Step 3: finalize metadata URLs =="
if [[ "${DO_POST_METADATA}" == "true" ]]; then
  bash scripts/finalize_publish_metadata.sh
fi

echo "== Step 4: post-checks =="
python3 scripts/validate_projects.py
python3 scripts/verify_deployment.py

echo "== Done. Suggested external checks =="
echo "curl -I https://${GH_USER}.github.io/${GH_REPO}/"
echo "curl -I https://${GH_USER}.github.io/${GH_REPO}/projects/casuallab/index.html"
echo "curl -I https://${GH_USER}.github.io/${GH_REPO}/projects/macroeconomics/index.html"
