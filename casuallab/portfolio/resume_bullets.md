# Resume bullets

Choose two or three bullets that match the role. Use generated artifacts to refresh any quantity;
all claims remain explicitly scoped to public-data description, semi-synthetic validation, or a
declared theoretical model.

## Research economist / causal inference

- Built an estimand-first marketplace experimentation platform that distinguishes direct, spillover, market-total, short-run, cumulative, ITT, complier, and budget-efficiency effects under spatial and temporal interference.
- Designed a semi-synthetic two-sided-market framework with configurable rider demand, driver supply, congestion, geographic substitution, spillovers, persistence, treatment saturation, and budget constraints; defined ground truth through paired counterfactual market paths with deterministic seeds.
- Developed a design-and-estimator benchmark spanning individual, geographic, time-block, switchback, and geo × time assignment with transparent baselines and design-aware inference, evaluated against known truth using bias, variance, RMSE, interval coverage, power, and information cost.
- Separated NYC-informed simulator recovery, controlled exposure recovery on fixed NYC OD
  geometry, theoretical fixed-point counterfactuals, and descriptive NOAA weather, ACS area-
  income, and permit-event associations so none is misreported as an NYC treatment effect,
  individual-income result, attendance measure, or structurally estimated response.
- Audited identification for public ride-hailing data, separating descriptive calibration from causal claims and documenting price endogeneity, market-boundary leakage, exposure misspecification, carryover, few-cluster inference, suppression, and transportability limits.
- Translated causal assumptions into an executive experiment strategy: target a market-level rollout policy contrast, keep assignment ITT distinct unless identification aligns them, randomize connected markets when spillovers are material, and decide on incremental marketplace value per dollar with service and budget guardrails.

## Data science / applied science

- Created a budget-constrained policy-learning workflow that compares no-treatment, random, uniform, rule-based, and model-based allocation on disjoint semi-synthetic holdout seeds, enforces budget feasibility before scoring, and penalizes unstable targeting.
- Added a separately manifested rider/driver/bundled policy sensitivity with common training and
  holdout market seeds, preserving its scope as simulator response-function evidence rather than
  an empirical dose-response claim.
- Implemented a reproducible Monte Carlo evaluation layer that preserves replication-level seeds and known truth, computes bias/RMSE/coverage/power from generated estimates, and labels outputs as semi-synthetic rather than empirical treatment effects.
- Built heterogeneous-effect tooling for pre-treatment modifiers; the generated recovery slice uses baseline demand, marketplace tightness, and time features with randomization-cluster holdout, known-truth calibration bins, subgroup recovery, and fold-stability checks.
- Built generated decision reporting that reads machine-computed benchmark and policy artifacts, rejects unlabeled or unsafe rows, selects only within a declared estimand, and records input checksums.

## Research engineering / analytics engineering

- Engineered a laptop-safe Python research workflow with typed YAML configuration, deterministic simulation, reusable data/estimation APIs, pytest and Ruff checks, thin command-line orchestration, and one-command sample reproduction.
- Designed a public-trip data contract with source/query manifests, SHA-256 checksums, schema validation, local-time and geographic normalization, partitioned Parquet outputs, and explicit missingness, suppression, fare-heaping, and timestamp-rounding diagnostics.
- Built a zone-time marketplace panel and reproducible artifact chain from public trip inputs through calibration, simulation, Monte Carlo benchmarking, policy evaluation, generated reporting, and an interactive decision interface.
- Built fail-closed benchmark bundles whose manifests revalidate NYC simulation anchors or OD
  calibration inputs by portable paths, byte counts, and hashes before report generation.
- Built fail-closed official-source contextual bundles for NOAA weather, ACS 2022 five-year
  B19001 neighborhood composition, and January NYC permitted events, with spatial/calendar
  coverage, conservation, exclusion, and noncausal-scope audits.
- Established evidence governance across the repository: every result is labeled empirical/descriptive, semi-synthetic causal, decision projection, or pending; observational fare-demand associations are never presented as causal elasticities.

## Product analytics / experimentation

- Reframed a standard incentive A/B test around the rollout estimand, showing how shared riders, drivers, geography, and carryover can make an individual contrast differ from total marketplace impact.
- Developed an experiment decision framework linking assignment unit, treatment duration, washout, saturation, exposure mapping, cluster-aware estimation, power, guardrails, and post-test budget allocation.
- Defined a practical launch rule that combines incremental trips/contribution/welfare per dollar, uncertainty around an economically meaningful threshold, service and driver guardrails, and robustness to plausible spillover and persistence.
- Created technical, experiment-design, executive, limitations, and interview artifacts that communicate the same causal contract at researcher, engineering, and leadership levels without overstating observational or simulated evidence.

## Verified quantified bullets

- Streamed and validated 19.7 million January 2024 NYC TLC HVFHV records into a complete
  194,928-cell zone-hour panel and 6.88-million-row OD-hour panel; enforced exact row
  conservation and byte-level reproducibility while keeping maximum RSS to 3.58 GiB and peak
  memory footprint to 5.88 GiB.
- Converted the verified NYC month into a hash-manifested descriptive network and simulation
  anchor: a 262-node OD exposure-map candidate plus a reduced control path matching completed-trip
  and wait-time means and zone/hour variance shares, while retaining all treatment-response and
  welfare parameters as explicit assumptions.
- Allocated all sixteen ACS B19001 household-income bins through an equal-area Taxi Zone/NTA
  crosswalk with household conservation and explicit unsupported/non-residential exclusions;
  retained 6,007 January-overlap permit rows/951 source event IDs and exposed the +3.055% raw
  versus -8.198% weekday-only trip contrast as calendar confounding, not an event effect.
- Validated a two-stage saturation design under known interference truth: controlled own,
  neighbor, and history estimates recovered 2.006/1.495/0.691 against truths 2.000/1.500/0.700,
  while the target-mismatched naive market-total diagnostic was excluded from causal scoring.

- Benchmarked five randomization designs and six estimator labels across a predeclared
  semi-synthetic sensitivity plan; preserved a fit ledger that reports every attempted,
  successful, failed, and inapplicable fit rather than selecting on silent attrition.
- Built a fail-closed decision rule that withheld a universal design because no
  design-estimator pair was identified, inference-valid, applicable, and complete across the
  full scenario grid; for the exact 16-zone/eight-cluster no-interference dashboard cell, the
  conditional selection was time-block assignment with doubly robust estimation.
- Evaluated five budget-matched policies on eight unseen semi-synthetic markets; under the
  configured $1,000 cap, uniform allocation generated 68.4967 mean incremental trips per modeled
  market (SE 0.1050, p10 68.1030), while model targeting underperformed random allocation.
- Processed 300 checksummed public Chicago TNP trips into 170 occupied zone-hour cells, preserving
  4.33% missing/outside pickup geography and declared rounding/suppression metadata without
  interpreting unobserved cells as zero demand.
- Shipped a one-command manifested reproduction bundle with automated quality gates and a
  dashboard that rejects stale, unlabeled, or only partially matched benchmark evidence; current
  verification counts remain in the generated manifest.

## Compact two-bullet combinations

### Economics role

- Built an estimand-first, semi-synthetic ride-hailing marketplace lab to compare individual, geographic, switchback, and geo × time incentive experiments under spillovers and persistence using known causal ground truth.
- Developed budget-constrained policy evaluation and executive decision rules around market-level rollout effects and incremental value per dollar, while explicitly separating assignment ITT, public-data associations, and simulated causal results.

### Applied scientist role

- Built deterministic Monte Carlo and honest-holdout policy pipelines for interference-aware marketplace experiments, benchmarking design/estimator recovery and budget-matched targeting baselines on known semi-synthetic truth.
- Operationalized causal rigor with typed configs, traceable seeds/checksums, cluster-aware inference, instability penalties, and generated reports that reject unlabeled or scientifically unsafe result rows.

### Research engineering role

- Engineered an end-to-end Python platform from checksummed public trip data and zone-time panels through deterministic marketplace simulation, experiment benchmarking, policy learning, reporting, and dashboard workflows.
- Added reproducibility and evidence controls—schema/rounding diagnostics, typed configuration, tests/lint, replication-level outputs, honest holdouts, and explicit empirical-versus-simulation labels—to make every decision claim auditable.

## Integrity checklist before using a bullet

- [ ] The named component exists in the repository and its tests pass.
- [ ] Any count comes from the current code or a generated artifact.
- [ ] Any performance metric includes its target estimand and scenario.
- [ ] “Causal” refers to randomized live evidence or known simulator truth, not the public panel.
- [ ] Policy results come from disjoint training and holdout seeds and the budget is enforced.
- [ ] A Chicago vertical-slice fact is not generalized to NYC or a live platform.
- [ ] Quantified bullets still match the current reproduction manifest and generated artifacts.
