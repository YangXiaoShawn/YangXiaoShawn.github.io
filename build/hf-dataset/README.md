---
pretty_name: Open Economic and Quant Research Data
language:
  - en
license: other
task_categories:
  - tabular-classification
tags:
  - economics
  - quantitative-finance
  - causal-inference
  - macroeconomics
  - housing-economics
---

# Open Economic & Quant Research Data

Versioned research content for CasualLab, Macroeconomics, Mortgage Rate Lock-In and Housing Market Dynamics, and Tariff Incidence, including project code, publishable data, fixtures, reports, tests, and reproducibility documentation.

## Repository structure

- `CasualLab/`: causal inference and policy-simulation research content.
- `Macroeconomics/`: vintage-aware forecasting and public-source adapter research content.
- `RealEstate/`: housing-finance research on mortgage lock-in, mortgage exits, local activity, prices, and construction. Registered loan-level records and loan-granular derivatives are excluded.
- `TariffIncidence/`: official-data research on U.S. Section 301 tariff pass-through, sourcing reallocation, and domestic input-output propagation. Large raw, intermediate, analytical, and parquet result files are excluded from the public package.
- `dataset_manifest.json`: file counts, exclusions, and release metadata.

## Supported uses

Reproducibility review, economics and quantitative-method research, public fixture exploration, and development of documented derivatives. The repository is not a single homogeneous machine-learning table; inspect each project README and schema before loading files.

## Sources and processing

Each project retains its own provenance notes. Raw third-party sources remain subject to provider terms. Local Python environments, package installations, caches, bytecode, and operating-system metadata are excluded because they are not research data.

## Licensing

Project-owned code and fixtures follow project-local terms. Third-party data and dependencies retain their original terms. Inclusion in this versioned mirror does not grant a new license. Assets without confirmed redistribution terms remain marked `RIGHTS_UNKNOWN` in the observatory governance records.

## Limitations

- File types and schemas vary by project.
- Some raw source rights require independent review.
- Updated numerical comparisons are published only with benchmark and validation evidence.
- Use a pinned Dataset revision for reproducible analysis.

## Related resources

- Website: https://yangxiaoshawn.github.io/
- CasualLab repository: https://github.com/YangXiaoShawn/open-economic-quant-casuallab
- Macroeconomics repository: https://github.com/YangXiaoShawn/open-economic-quant-macroeconomics
- Mortgage Rate Lock-In repository: https://github.com/YangXiaoShawn/open-economic-quant-realestate
- Tariff Incidence repository: https://github.com/YangXiaoShawn/open-economic-quant-tariff-incidence
- Website repository: https://github.com/YangXiaoShawn/YangXiaoShawn.github.io
- Interactive observatory: https://huggingface.co/spaces/ShawnChamberlain/open-economic-quant-research-observatory

## Citation

Cite the observatory, this Dataset revision, the relevant project, and every original data provider used in an analysis.
