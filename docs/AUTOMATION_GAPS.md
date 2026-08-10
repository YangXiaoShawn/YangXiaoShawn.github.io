# AUTOMATION_GAPS.md

## 缺失/受限功能

- 未接入 `daily-refresh` 与定期更新工作流（未见稳定可靠的原始数据更新命令）。
- HF dataset/space 自动同步暂未完成（缺少在线认证凭据）。
- 站点生成仍为手工静态 HTML，未接入模板化构建器。

## 下一步建议

- 将 `scripts/` 下的脚本扩展为 CI job 的稳定接口。
- 补齐 `.github/workflows` 以实现自动化发布。
