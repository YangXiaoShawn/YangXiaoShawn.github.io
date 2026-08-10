#!/usr/bin/env bash
set -euo pipefail

: "${GH_USER:?Set GH_USER, e.g. your GitHub username}"
: "${GH_REPO:?Set GH_REPO, e.g. repository name}"
: "${HF_USER:=${GH_USER}}"
: "${HF_DATASET_REPO:=${HF_USER}/open-economic-quant-research-data}"
: "${HF_SPACE_REPO:=${HF_USER}/open-economic-quant-research-observatory}"

ROOT_DIR="/Users/shawn/Documents/intern projects/GithubIO"
cd "$ROOT_DIR"

GITHUB_REPO_URL="https://github.com/${GH_USER}/${GH_REPO}"
GITHUB_PAGES_URL="https://${GH_USER}.github.io/${GH_REPO}"
HF_DATASET_URL="https://huggingface.co/datasets/${HF_DATASET_REPO}"
HF_SPACE_URL="https://huggingface.co/spaces/${HF_SPACE_REPO}"

for p in casuallab/project.yaml macroeconomics/project.yaml; do
  python3 - "$p" "$GITHUB_REPO_URL" "$GITHUB_PAGES_URL" "$HF_DATASET_URL" "$HF_SPACE_URL" <<'PY'
import re
import sys
from pathlib import Path
path,github_url,site_url,dataset_url,space_url = sys.argv[1:]
text = Path(path).read_text()
repl = {
    r"^github_url:\s*.*$": f"github_url: {github_url}",
    r"^site_url:\s*.*$": f"site_url: {site_url}",
    r"^dataset_url:\s*.*$": f"dataset_url: {dataset_url}",
    r"^space_url:\s*.*$": f"space_url: {space_url}",
}
for pat, val in repl.items():
    text = re.sub(pat, val, text, flags=re.M)
Path(path).write_text(text)
print(f"updated {path}")
PY
done

a=$(cat <<JSON
{
  "repository": {
    "github_repository": "${GITHUB_REPO_URL}",
    "github_pages_url": "${GITHUB_PAGES_URL}"
  },
  "huggingface": {
    "dataset_repo": "${HF_DATASET_URL}",
    "space_repo": "${HF_SPACE_URL}"
  },
  "commit_hashes": {
    "local_snapshot": "$(git rev-parse HEAD 2>/dev/null || echo N/A)"
  },
  "deployment_status": {
    "github_repository": "DONE",
    "github_pages": "DONE",
    "hf_dataset": "PENDING",
    "hf_space": "PENDING"
  },
  "blocking_reason": ""
}
JSON
)
printf "%s" "$a" > manifests/deployed_resources.json

if [ -f DEPLOYMENT_REPORT.md ]; then
  sed -i '' "s#https://github.com/<你的GitHub用户名>/<你的仓库名>#${GITHUB_REPO_URL}#g" DEPLOYMENT_REPORT.md 2>/dev/null || true
  sed -i '' "s#https://<你的GitHub用户名>.github.io/<你的仓库名>/#${GITHUB_PAGES_URL}/#g" DEPLOYMENT_REPORT.md 2>/dev/null || true
fi

echo "Updated metadata summary:"
echo "  github_url: $GITHUB_REPO_URL"
echo "  github_pages_url: $GITHUB_PAGES_URL"
echo "  dataset_url: $HF_DATASET_URL"
echo "  space_url: $HF_SPACE_URL"
echo "  deployed_resources.json updated"
