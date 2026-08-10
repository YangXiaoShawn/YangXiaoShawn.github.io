#!/usr/bin/env bash
set -euo pipefail

# Interactive one-step launcher for publish_playbook.sh.
# - Requires gh and (for HF upload) huggingface-cli in PATH.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

read -r -p "GitHub 用户名: " GH_USER
read -r -p "GitHub 仓库名: " GH_REPO
read -r -p "是否仅发布 GitHub Pages（不上传 HF，输入 y 跳过）? [y/N]: " SKIP_HF
read -r -p "Hugging Face 用户名（默认与 GitHub 相同）: " HF_USER

if [ -z "${HF_USER}" ]; then
  HF_USER="${GH_USER}"
fi

export GH_USER
export GH_REPO
export HF_USER
export HF_DATASET_REPO="${HF_USER}/open-economic-quant-research-data"
export HF_SPACE_REPO="${HF_USER}/open-economic-quant-research-observatory"

if [[ "${SKIP_HF}" == "y" || "${SKIP_HF}" == "Y" ]]; then
  export DRY_RUN_ONLY_GITHUB=true
else
  export DRY_RUN_ONLY_GITHUB=false
fi

cd "$ROOT_DIR"
echo "启动发布向导："
echo "  GitHub:  https://github.com/${GH_USER}/${GH_REPO}"
echo "  HF数据: https://huggingface.co/datasets/${HF_DATASET_REPO}"

bash "$SCRIPT_DIR/publish_playbook.sh"
