#!/usr/bin/env bash
set -euo pipefail

# Interactive one-shot launcher for GitHub Pages + optional Hugging Face publish.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "$ROOT_DIR"

echo "=== Step 0) Local pre-check ==="
python3 scripts/validate_projects.py
python3 scripts/verify_deployment.py

echo
read -r -p "GitHub 用户名 (GH_USER): " GH_USER
read -r -p "GitHub 仓库名 (GH_REPO): " GH_REPO
read -r -p "是否仅发布 GitHub（不上传 HF）? [y/N]: " SKIP_HF
read -r -p "Hugging Face 用户名 [默认同 GH 用户]: " HF_USER

if [ -z "${HF_USER}" ]; then
  HF_USER="$GH_USER"
fi

export GH_USER
export GH_REPO
export HF_USER

if [[ "${SKIP_HF}" == "y" || "${SKIP_HF}" == "Y" ]]; then
  export DRY_RUN_ONLY_GITHUB=true
  echo "Mode: GitHub only"
else
  export DRY_RUN_ONLY_GITHUB=false
  echo "Mode: GitHub + Hugging Face"
fi

printf '\nStarting publish...\n'
bash scripts/publish_playbook.sh

if [ "$DRY_RUN_ONLY_GITHUB" = "true" ]; then
  echo "\nGitHub only mode completed." 
else
  echo "\nGitHub + HF mode completed." 
fi

echo "\nSuggested post-checks:"
echo "  git status"
echo "  curl -I https://github.com/${GH_USER}/${GH_REPO}" 
echo "  curl -I https://${GH_USER}.github.io/${GH_REPO}/"

echo "\nDone."
