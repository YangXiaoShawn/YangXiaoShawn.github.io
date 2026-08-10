# GithubIO publish command snippets

Replace placeholders and run directly.

## 1) GitHub Pages first (recommended)

```bash
cd "/Users/shawn/Documents/intern projects/GithubIO"
GH_USER=<YOUR_GITHUB_USERNAME>
GH_REPO=<YOUR_REPO_NAME>

GH_USER="$GH_USER" \
GH_REPO="$GH_REPO" \
DRY_RUN_ONLY_GITHUB=true \
bash scripts/publish_playbook.sh
```

## 2) GitHub + Hugging Face (optional)

```bash
cd "/Users/shawn/Documents/intern projects/GithubIO"
GH_USER=<YOUR_GITHUB_USERNAME>
GH_REPO=<YOUR_REPO_NAME>
HF_USER=<YOUR_HF_USERNAME>

GH_USER="$GH_USER" \
GH_REPO="$GH_REPO" \
HF_USER="$HF_USER" \
bash scripts/publish_playbook.sh
```

## 3) Single-command orchestration (interactive)

```bash
cd "/Users/shawn/Documents/intern projects/GithubIO"
bash scripts/run_publish_live.sh
```

## 4) Generate command list without execution

```bash
cd "/Users/shawn/Documents/intern projects/GithubIO"
GH_USER=<YOUR_GITHUB_USERNAME> \
GH_REPO=<YOUR_REPO_NAME> \
MODE=github_only \
bash scripts/emit_publish_commands.sh
```

HF variant:

```bash
cd "/Users/shawn/Documents/intern projects/GithubIO"
GH_USER=<YOUR_GITHUB_USERNAME> \
GH_REPO=<YOUR_REPO_NAME> \
HF_USER=<YOUR_HF_USERNAME> \
MODE=github_hf \
bash scripts/emit_publish_commands.sh
```

## 5) Post-publish sanity checks

```bash
curl -I https://<github_user>.github.io/<repo_name>/
curl -I https://<github_user>.github.io/<repo_name>/projects/casuallab/index.html
curl -I https://<github_user>.github.io/<repo_name>/projects/macroeconomics/index.html
```

## 6) Fill metadata after public URLs are known

```bash
cd "/Users/shawn/Documents/intern projects/GithubIO"
GH_USER=<YOUR_GITHUB_USERNAME>
GH_REPO=<YOUR_REPO_NAME>
HF_USER=<YOUR_HF_USERNAME>  # optional

GH_USER="$GH_USER" \
GH_REPO="$GH_REPO" \
HF_USER="${HF_USER:-$GH_USER}" \
bash scripts/finalize_publish_metadata.sh
```

Useful references:

- [scripts/DEPLOY_COMMANDS.md](/Users/shawn/Documents/intern%20projects/GithubIO/scripts/DEPLOY_COMMANDS.md)
- [scripts/DEPLOY_SNIPPET.md](/Users/shawn/Documents/intern%20projects/GithubIO/scripts/DEPLOY_SNIPPET.md)
- [scripts/publish_playbook.sh](/Users/shawn/Documents/intern%20projects/GithubIO/scripts/publish_playbook.sh)
