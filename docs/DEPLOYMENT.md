# Deployment

## Destinations

- GitHub Pages: https://yangxiaoshawn.github.io/
- Site repository: https://github.com/YangXiaoShawn/YangXiaoShawn.github.io
- CasualLab repository: https://github.com/YangXiaoShawn/open-economic-quant-casuallab
- Macroeconomics repository: https://github.com/YangXiaoShawn/open-economic-quant-macroeconomics
- Mortgage Rate Lock-In repository: https://github.com/YangXiaoShawn/open-economic-quant-realestate
- Tariff Incidence repository: https://github.com/YangXiaoShawn/open-economic-quant-tariff-incidence
- Microstructure repository: https://github.com/YangXiaoShawn/open-economic-quant-microstructure
- Hugging Face Dataset: https://huggingface.co/datasets/ShawnChamberlain/open-economic-quant-research-data
- Hugging Face Space: https://huggingface.co/spaces/ShawnChamberlain/open-economic-quant-research-observatory

## Release order

1. Run `make build` and `make verify`.
2. Commit and push the site repository.
3. Push each compact project copy to its standalone GitHub repository.
4. Package or synchronize the full research dataset, excluding local environments and caches.
5. Deploy `apps/space/` and confirm its Dataset connection.
6. Run `make verify-online` and record the resulting revisions in `DEPLOYMENT_REPORT.md`.

## Authentication

Use authenticated `gh` and `hf` sessions. Never place a personal access token in a command file, tracked configuration, shell history, or CI log. GitHub Actions uses the `HF_TOKEN` secret and non-secret repository variables.

## GitHub Pages

The repository supports a direct user-site URL and an Actions-based static deployment. All paths are relative so the site remains valid at the root and in local previews.

## Hugging Face

The Dataset and Space deployment scripts are idempotent. The Space supports `HF_DATASET_REPO`, `HF_DATASET_REVISION`, `SITE_URL`, and `GITHUB_REPOSITORY_URL` without storing credentials.
