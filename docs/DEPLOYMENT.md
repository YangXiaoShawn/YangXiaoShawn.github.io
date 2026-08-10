# DEPLOYMENT.md

## 当前状态

- GitHub Pages 站点文件已本地搭建（`index.html` 与项目展示页）。
- `GithubIO` 仍未实际执行 GitHub/Hugging Face 远端部署。

## 外部认证

- GitHub CLI 授权与 Hugging Face 登录在当前环境不可直接执行/验证。

## 发布步骤（待执行）

1. 创建/定位目标 GitHub 仓库。
2. 将 `GithubIO` 仓库内容推送。
3. 启用 GitHub Pages（建议 `gh-pages` 或默认分支 + Pages）。
4. 使用 `scripts/verify_deployment.py` 检查站点文件完整性。
5. 配置并上传 HF dataset / space（授权后进行）。
