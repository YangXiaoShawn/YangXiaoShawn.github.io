#!/usr/bin/env bash
set -euo pipefail

: "${GH_USER:?Set GH_USER to your GitHub username}"
: "${GH_REPO:?Set GH_REPO to your repository name}"
: "${MODE:=github_only}"  # github_only | github_hf
: "${HF_USER:=${GH_USER}}"
: "${DRY_RUN_ONLY_GITHUB:=true}"

BASE="/Users/shawn/Documents/intern projects/GithubIO"

cat <<'EOF2'
# Copiable publish command block
# Run from macOS/Linux shell in command mode
EOF2
cat <<EOF2
cd "$BASE"
EOF2

if [[ "$MODE" == "github_hf" ]]; then
cat <<EOF3
GH_USER=$GH_USER \
GH_REPO=$GH_REPO \
HF_USER=$HF_USER \
bash scripts/publish_playbook.sh
EOF3
else
cat <<EOF3
GH_USER=$GH_USER \
GH_REPO=$GH_REPO \
DRY_RUN_ONLY_GITHUB=true \
bash scripts/publish_playbook.sh
EOF3
fi

cat <<EOF2

# Verify commands
python3 scripts/validate_projects.py
python3 scripts/verify_deployment.py
curl -I "https://$GH_USER.github.io/$GH_REPO/"
curl -I "https://$GH_USER.github.io/$GH_REPO/projects/casuallab/index.html"
curl -I "https://$GH_USER.github.io/$GH_REPO/projects/macroeconomics/index.html"
EOF2
