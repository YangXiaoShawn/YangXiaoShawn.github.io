# Deployment Report

## Executive summary

Open Econ × Quant is fully public: the GitHub Pages site, five published project source locations, versioned Hugging Face Dataset, and interactive Hugging Face Space are live and cross-linked.

## Projects discovered and published

- Published: CasualLab, Macroeconomics, Mortgage Rate Lock-In and Housing Market Dynamics, Tariff Incidence, Supply-Chain Reallocation, and Domestic Propagation, and the canonical Microstructure research repository.
- Inventoried but withheld: four frozen Microstructure verification worktrees and SECPolicy.
- Withheld reason: the frozen worktrees are historical verification environments rather than separate projects; SECPolicy publication rights have not been validated.

## Public resources

- Site repository: https://github.com/YangXiaoShawn/YangXiaoShawn.github.io
- Upgraded Pages site: https://yangxiaoshawn.github.io/
- CasualLab repository: https://github.com/YangXiaoShawn/open-economic-quant-casuallab
- Macroeconomics repository: https://github.com/YangXiaoShawn/open-economic-quant-macroeconomics
- Mortgage Rate Lock-In repository: https://github.com/YangXiaoShawn/open-economic-quant-realestate
- Mortgage Rate Lock-In page: https://yangxiaoshawn.github.io/projects/realestate/
- Tariff Incidence repository: https://github.com/YangXiaoShawn/open-economic-quant-tariff-incidence
- Tariff Incidence page: https://yangxiaoshawn.github.io/projects/tariff-incidence/
- Microstructure repository: https://github.com/YangXiaoShawn/open-economic-quant-microstructure
- Microstructure page: https://yangxiaoshawn.github.io/projects/microstructure/
- Full Dataset: https://huggingface.co/datasets/ShawnChamberlain/open-economic-quant-research-data
- Live Space: https://huggingface.co/spaces/ShawnChamberlain/open-economic-quant-research-observatory
- Static runtime: https://shawnchamberlain-open-economic-quant-research-ob-5271962.static.hf.space
- Space revision: `1dcb45aab5d2129ced14c8a46fd82f339ca8069f`
- Evidence-first redesign commit: `87d659519f6a51445b4afe2f2aeeed9ae8520913`.
- GitHub Pages interactive redesign commit: `3ca1907e84d6242bcde6f1b84f83992cfd8196bd`.
- Chart-first release commit: `5cf8b1578683065d2b61c97049f08dc33a2763e2`.
- RealEstate standalone repository release commit: `6d2dc30af09e8d38b50aa50267cd324cf35b4e0d`.
- RealEstate repository release CI: https://github.com/YangXiaoShawn/YangXiaoShawn.github.io/actions/runs/32649726249
- RealEstate repository Pages deployment: https://github.com/YangXiaoShawn/YangXiaoShawn.github.io/actions/runs/32649725687

## Dataset release

- Original full-mirror revision: `59d2444710a105cac663709fdd1050fe47c454e5`
- Cleanup revision: `1202a275873eb61f552a095373f7b3dab0e718ba`
- Before cleanup: 42,779 remote files.
- Current research content: 3,701 project files, approximately 2.85 GB.
- Removed: 39,277 local-environment files plus test caches, bytecode, and operating-system metadata.
- Preserved: project code, data, reports, notebooks, tests, documentation, and research outputs.
- Dataset Card and detailed file manifest: uploaded after cleanup.
- RealEstate addition: 101 tracked public files; registered loan-level data and loan-granular derivatives are excluded.
- TariffIncidence addition: 122 tracked public files (1,476,927 bytes); large raw, intermediate, analytical, and parquet result files are excluded.
- Microstructure addition: 133 tracked public files (3,464,097 bytes); exchange observations, derived tables, fitted states, run bundles, and local environments are excluded.
- Current Dataset revision: `5329ac0f88bae309d6e37eb8fdaefc0f60754f4c`.

## Website improvements published

- Recruiter-first portfolio hierarchy: role positioning, five quantified systems, contribution summaries, capability tags, and direct GitHub routes appear before the detailed evidence layer.
- Positive proof points lead each project while exact findings, limitations, and publication boundaries remain available in secondary evidence views.
- English-only public copy and documentation.
- Catalog generated from `project.yaml` files.
- Ten stable research section routes.
- Complete project narratives covering question, importance, source, sample, methods, evidence status, robustness, reproduction, links, citation, limitations, update time, and status.
- Five equal, question-first project routes with HTE recovery, vintage leakage, mortgage hazard, tariff incidence, and Microstructure strategy evidence.
- The Microstructure view exposes the current 144-scenario distribution, frozen 4 bp fees, net P&L, and turnover-normalized marked drawdown through symbol, phase, horizon, and latency controls.
- The current Microstructure result is labeled “research reference only”; the earlier trade-only `NOT_RUN` data-gate terminal remains separately documented.
- Metric toggles, keyboard/touch chart tooltips, accessible data tables, and direct links to pinned evidence files.
- Space signal, portfolio, file, and evidence-note views with shareable URL state and browser back/forward restoration.
- Live Dataset path search, consistent file-type filters, and directory-size comparisons.
- Canonical metadata, Open Graph card, favicon, Atom feed, sitemap, robots policy, and 404 page.
- Responsive shared visual system with a simplified editorial hierarchy and Open Econ × Quant social preview.
- GitHub Actions for CI, Pages deployment, Hugging Face synchronization, and safe daily validation.

## Security and rights findings

- No embedded GitHub/Hugging Face token or private key marker was detected in the public site tree.
- API key references in source are environment-variable names, not credential values.
- Deployment credentials are supplied only through repository secrets; no access token is committed to the public release.
- Third-party raw data retain provider terms and mixed/unknown redistribution status.

## Validation results

- Catalog generation check: passed, 5 projects, no stale generated output.
- Compact project validation: passed, 5 projects.
- Local deployment verification: passed, 34 required artifacts.
- Python syntax compilation: passed using an isolated writable bytecode cache.
- Hugging Face release-integrity check: passed; the Dataset tree, Space catalog, pinned evidence revision, all 133 Microstructure records, and the bounded 144-scenario summary match exactly.
- Interaction checks: passed for the five-project switching logic, keyboard-focusable chart marks, accessible data tables, shareable URL state, and JavaScript syntax.
- Public homepage, project pages, research routes, dashboard status page, `robots.txt`, and `sitemap.xml`: HTTP 200.
- Automated online verifier: passed, 16 public resources.
- GitHub CI: passed for the 2026-08-23 five-project release.
- GitHub Pages build and deployment: passed for the same release.
- HF Space: successful, public, and running.

## Recoverability

The pre-optimization site snapshot is tagged `backup/pre-publication-20260810-1924` at commit `3fa4c1711868ae9b9a376fb4138c0bd913e01a09`. Hugging Face cleanup is also recoverable from Dataset commit history.

## Remaining blocker

No publication blocker remains. Deployment credentials stay outside the repository and are provided only through the hosting platforms' secret stores.
