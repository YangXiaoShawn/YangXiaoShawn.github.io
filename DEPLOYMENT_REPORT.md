# Deployment Report

## Executive summary

The Open Economic & Quant Research Observatory is fully public: the GitHub Pages site, four published project source locations, versioned Hugging Face Dataset, and interactive Hugging Face Space are live and cross-linked.

## Projects discovered and published

- Published: CasualLab, Macroeconomics, Mortgage Rate Lock-In and Housing Market Dynamics, and Tariff Incidence, Supply-Chain Reallocation, and Domestic Propagation.
- Inventoried but withheld: Microstructure variants and SECPolicy.
- Withheld reason: their publication rights and release scope have not been validated.

## Public resources

- Site repository: https://github.com/YangXiaoShawn/YangXiaoShawn.github.io
- Upgraded Pages site: https://yangxiaoshawn.github.io/
- CasualLab repository: https://github.com/YangXiaoShawn/open-economic-quant-casuallab
- Macroeconomics repository: https://github.com/YangXiaoShawn/open-economic-quant-macroeconomics
- Mortgage Rate Lock-In source: https://github.com/YangXiaoShawn/YangXiaoShawn.github.io/tree/main/realestate
- Mortgage Rate Lock-In page: https://yangxiaoshawn.github.io/projects/realestate/
- Tariff Incidence repository: https://github.com/YangXiaoShawn/open-economic-quant-tariff-incidence
- Tariff Incidence page: https://yangxiaoshawn.github.io/projects/tariff-incidence/
- Full Dataset: https://huggingface.co/datasets/ShawnChamberlain/open-economic-quant-research-data
- Live Space: https://huggingface.co/spaces/ShawnChamberlain/open-economic-quant-research-observatory
- Static runtime: https://shawnchamberlain-open-economic-quant-research-ob-5271962.static.hf.space
- Space revision: `6692d6263974b39b4ea1c5e3c6aae475bf5707c8`
- GitHub Pages interactive redesign commit: `3ca1907e84d6242bcde6f1b84f83992cfd8196bd`.
- CI verification: https://github.com/YangXiaoShawn/YangXiaoShawn.github.io/actions/runs/32052100067
- Pages deployment: https://github.com/YangXiaoShawn/YangXiaoShawn.github.io/actions/runs/32052098987

## Dataset release

- Original full-mirror revision: `59d2444710a105cac663709fdd1050fe47c454e5`
- Cleanup revision: `1202a275873eb61f552a095373f7b3dab0e718ba`
- Before cleanup: 42,779 remote files.
- Current research content: 3,568 project files, approximately 2.85 GB.
- Removed: 39,277 local-environment files plus test caches, bytecode, and operating-system metadata.
- Preserved: project code, data, reports, notebooks, tests, documentation, and research outputs.
- Dataset Card and detailed file manifest: uploaded after cleanup.
- RealEstate addition: 101 tracked public files; registered loan-level data and loan-granular derivatives are excluded.
- TariffIncidence addition: 122 tracked public files (1,476,927 bytes); large raw, intermediate, analytical, and parquet result files are excluded.
- Current Dataset revision: `38e373a5df14afb0cf10c1f008c188f4000ca8df`.

## Website improvements published

- English-only public copy and documentation.
- Catalog generated from `project.yaml` files.
- Ten stable research section routes.
- Complete project narratives covering question, importance, source, sample, methods, evidence status, robustness, reproduction, links, citation, limitations, update time, and status.
- Question-led project switching with interactive question, design, evidence, and boundary views.
- Space research-map navigation plus live Dataset path search and file-type filters.
- Canonical metadata, Open Graph card, favicon, Atom feed, sitemap, robots policy, and 404 page.
- Responsive shared visual system with a simplified editorial hierarchy and new social preview card.
- GitHub Actions for CI, Pages deployment, Hugging Face synchronization, and safe daily validation.

## Security and rights findings

- No embedded GitHub/Hugging Face token or private key marker was detected in the public site tree.
- API key references in source are environment-variable names, not credential values.
- Tokens previously pasted into chat should be revoked and replaced.
- Third-party raw data retain provider terms and mixed/unknown redistribution status.

## Validation results

- Catalog generation check: passed, 4 projects, no stale generated output.
- Compact project validation: passed, 4 projects.
- Local deployment verification: passed, 24 required artifacts.
- Python syntax compilation: passed using an isolated writable bytecode cache.
- Hugging Face Space: static runtime returned HTTP 200 and exposes 414 CasualLab, 2,931 Macroeconomics, 101 RealEstate, and 122 TariffIncidence file records.
- Public homepage, project pages, research routes, dashboard status page, `robots.txt`, and `sitemap.xml`: HTTP 200.
- Automated online verifier: passed, 13 public resources.
- GitHub CI: passed on release content commit `d1805eceff65f1f3ec6b5b22c7e2c7e070e3e895`.
- GitHub Pages build and deployment: passed on the same release content commit.
- HF Space: successful, public, and running.

## Recoverability

The pre-optimization site snapshot is tagged `backup/pre-publication-20260810-1924` at commit `3fa4c1711868ae9b9a376fb4138c0bd913e01a09`. Hugging Face cleanup is also recoverable from Dataset commit history.

## Remaining blocker

No publication blocker remains. Previously pasted access tokens should be revoked and replaced because chat messages are not an appropriate long-term credential store.
