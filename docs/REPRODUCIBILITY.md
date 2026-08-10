# REPRODUCIBILITY.md

## 推荐复现入口

- CasualLab: `make reproduce`（以项目内 Makefile 为准）
- Macroeconomics: `python -m macro_nowcast.pipeline`

## 准备清单

- 固定依赖：每个项目保留 `pyproject.toml`。
- 数据：上传包中保留最小样例 `fixtures` 与 `data/fixtures`。
- 测试：两项目的 `tests/` 均已保留。

## 注意事项

- 发布包中剥离了原始大规模数据与本地环境目录。
- 网络与外部 API 获取过程在部署链路中应在可执行环境中重跑。
