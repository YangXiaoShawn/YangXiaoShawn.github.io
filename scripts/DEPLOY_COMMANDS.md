# GithubIO 上线与上传命令（最小替换版）

## 1) 先准备参数
- `GH_USER`：GitHub 用户名
- `GH_REPO`：GitHub 仓库名（建议：`open-economic-quant-research`）
- `HF_USER`：Hugging Face 用户名（如先只发 GitHub，可留空）
- `DRY_RUN_ONLY_GITHUB=true`：仅发 GitHub Pages，不上传 HF

## 2) 直接执行（推荐）

```bash
cd "/Users/shawn/Documents/intern projects/GithubIO"
GH_USER=<你的GitHub用户名> \
GH_REPO=<你的GitHub仓库名> \
HF_USER=<你的HF用户名或与你GitHub一致> \
bash scripts/publish_playbook.sh
```

## 3) 仅 GitHub（不上传 HF）

```bash
cd "/Users/shawn/Documents/intern projects/GithubIO"
GH_USER=<你的GitHub用户名> \
GH_REPO=<你的GitHub仓库名> \
DRY_RUN_ONLY_GITHUB=true \
bash scripts/publish_playbook.sh
```

## 4) 交互式向导（不想手工替换参数）

```bash
cd "/Users/shawn/Documents/intern projects/GithubIO"
bash scripts/publish_quickstart.sh
```

## 5) 备注
- 脚本在执行前会先跑本地校验：
  - `python3 scripts/validate_projects.py`
  - `python3 scripts/verify_deployment.py`
- 站点入口路径已包含两项目：
  - `projects/casuallab/index.html`
  - `projects/macroeconomics/index.html`

## 6) 本地上传前手工检查
- 参照：[upload_checklist.md](/Users/shawn/Documents/intern%20projects/GithubIO/upload_checklist.md)
