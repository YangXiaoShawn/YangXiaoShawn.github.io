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
  - market-microstructure
---

# Open Economic & Quant Research Data

Versioned research data for CasualLab, Macroeconomics, Mortgage Rate Lock-In and Housing Market Dynamics, Tariff Incidence, Order Flow to Price Impact, Emerging-Market Factor Timing, Polymarket Cross-Sectional Factor Study, and Crypto Factor Zoo and Post-Publication Audit, including publishable data, fixtures, reports, and reproducibility documentation.

Project code, tests, and run configuration live in the GitHub repositories listed under Related resources. `dataset_manifest.json` describes the 8-project release.

## Repository structure

- `CasualLab/`: causal inference and policy-simulation research content.
- `Macroeconomics/`: vintage-aware forecasting and public-source adapter research content.
- `RealEstate/`: housing-finance research on mortgage lock-in, mortgage exits, local activity, prices, and construction. Registered loan-level records and loan-granular derivatives are excluded.
- `TariffIncidence/`: official-data research on U.S. Section 301 tariff pass-through, sourcing reallocation, and domestic input-output propagation. Large raw, intermediate, analytical, and parquet result files are excluded from the public package.
- `Microstructure/`: research-only market-microstructure protocols, reports, and documentation. Exchange observations, normalized or derived tables, fitted states, ingestion authorities, and generated run bundles are excluded.
- `EMFactorTiming/`: emerging-market factor timing out-of-sample evaluation tables, JKP coverage metadata, and shrinkage benchmark reports across 21 emerging and 23 developed markets.
- `PolymarketFactors/`: binary contract artifact funnel tables, price-neutralized factor IC summaries, category reversal diagnostics, and sample market fixtures.
- `CryptoFactors/`: equity-to-perpetual factor transfer tables, Benjamini-Hochberg FDR summaries, post-publication out-of-sample decay diagnostics, and sample perpetual panel fixtures.
- `dataset_manifest.json`: file counts, exclusions, and release metadata for the 8-project release.

## Supported uses

Reproducibility review, economics and quantitative-method research, public fixture exploration, and development of documented derivatives. The repository is not a single homogeneous machine-learning table; inspect each project README and schema before loading files.

## Sources and processing

Each project retains its own provenance notes. Raw third-party sources remain subject to provider terms. Local Python environments, package installations, caches, bytecode, and operating-system metadata are excluded because they are not research data.

## Licensing

Project-owned fixtures and documentation follow project-local terms; code terms are in each GitHub repository. Third-party data and dependencies retain their original terms. Inclusion in this versioned mirror does not grant a new license. Assets without confirmed redistribution terms remain marked `RIGHTS_UNKNOWN` in the observatory governance records.

## Limitations

- File types and schemas vary by project.
- Some raw source rights require independent review.
- Updated numerical comparisons are published only with benchmark and validation evidence.
- Use a pinned Dataset revision for reproducible analysis.

## Related resources

- Website: https://yangxiaoshawn.github.io/
- Unified monorepo: https://github.com/YangXiaoShawn/open-economic-quant
- CasualLab repository: https://github.com/YangXiaoShawn/open-economic-quant-casuallab
- Macroeconomics repository: https://github.com/YangXiaoShawn/open-economic-quant-macroeconomics
- Mortgage Rate Lock-In repository: https://github.com/YangXiaoShawn/open-economic-quant-realestate
- Tariff Incidence repository: https://github.com/YangXiaoShawn/open-economic-quant-tariff-incidence
- Microstructure repository: https://github.com/YangXiaoShawn/open-economic-quant-microstructure
- Emerging-Market Factor Timing repository: https://github.com/YangXiaoShawn/open-economic-quant-em-factor-timing
- Polymarket Factors repository: https://github.com/YangXiaoShawn/open-economic-quant-polymarket-factors
- Crypto Factors repository: https://github.com/YangXiaoShawn/open-economic-quant-crypto-factors
- Website repository: https://github.com/YangXiaoShawn/YangXiaoShawn.github.io
- Interactive observatory: https://huggingface.co/spaces/ShawnChamberlain/open-economic-quant-research-observatory

## Citation

Cite the observatory, this Dataset revision, the relevant project, and every original data provider used in an analysis.
