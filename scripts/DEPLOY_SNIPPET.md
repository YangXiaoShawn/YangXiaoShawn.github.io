# 立即可粘贴执行示例（占位替换版）

你只需要替换 3 个占位：
- `<your_github_user>`
- `<your_repo_name>`
- `<your_hf_user>`（若只做 GitHub 可省略并跳过 HF）

## 方式 A：最小化替换（优先）——直接发布到 GitHub Pages

```bash
cd "/Users/shawn/Documents/intern projects/GithubIO"

GH_USER=<your_github_user> \
GH_REPO=<your_repo_name> \
DRY_RUN_ONLY_GITHUB=true \
bash scripts/publish_playbook.sh
```

## 方式 B：发布 GitHub + HF 数据集（可选）

```bash
cd "/Users/shawn/Documents/intern projects/GithubIO"

GH_USER=<your_github_user> \
GH_REPO=<your_repo_name> \
HF_USER=<your_hf_user> \
bash scripts/publish_playbook.sh
```

## 方式 C：交互式（推荐）

```bash
cd "/Users/shawn/Documents/intern projects/GithubIO"
bash scripts/publish_quickstart.sh
```

## 运行后关键输出（快速判断是否成功）
- 看到：`validation-ok` 与 `verify-ok`
- 看到：`Pages API patch succeeded.` 或 `Pages API not available...`（如后者请手动在 GitHub 后台开 Pages）
- 若仅 GitHub 模式，应看到：`Publish flow completed (GitHub only).`
- 若完整 HF 模式，应看到两次 `upload` 上传记录

## 常见卡点
- `gh not found`：先安装 GitHub CLI
- `gh auth status` 失败：先运行 `gh auth login`
- `huggingface-cli not found`：说明未安装/未登录 HF，可先执行 GitHub-only 模式
- `Cannot find repository`：确认 `GH_USER/GH_REPO` 的拼写与权限
