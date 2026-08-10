# ARCHITECTURE.md

## 目录结构

- `upload_ready/`：两个目标项目的上传准备包（CasualLab、Macroeconomics）。
- `manifests/`：清单与审计文件。
- `docs/`：治理、发布与部署说明。
- `scripts/`：本地验证与构建脚本占位。
- `projects/`：站点中的项目展示页。
- `index.html`：站点首页。

## 目标数据流

1. 本地盘点生成 `manifests/project_inventory.json`。
2. 将可上传内容整理到 `upload_ready/<slug>/`。
3. 站点使用项目卡片与链接面向外部公开。
4. 后续接入 GitHub 与 Hugging Face 部署。
