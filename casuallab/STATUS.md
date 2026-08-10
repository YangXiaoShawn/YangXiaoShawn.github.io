# Status

## Current milestone

**Complete and verified:** a reproducible causal-marketplace vertical slice with Chicago fixture
coverage and a full-month NYC empirical backbone. It includes streamed data processing,
descriptive NOAA-weather, calendar/event, and ecological neighborhood-income associations,
deterministic semi-synthetic causal benchmarks,
mapped-interference estimators, honest-holdout policy evaluation, generated reports, and an
interactive dashboard. The NYC layer validates 19,663,930 published HVFHV records, complete
zone-hour and OD panels, a network/calibration bundle, an NYC-informed simulator anchor, a
known-truth benchmark on the observed NYC OD graph, and independently manifested weather,
permit-calendar, and ACS area-income layers. A separate fixed-point benchmark solves a declared
two-sided theoretical market equilibrium and verifies its welfare and budget ledgers.

The completion boundary is the requested causal vertical slice plus descriptive analysis of the
pinned January 2024 NYC published-trip object. NYC-informed and NYC-graph causal quantities remain
known truths from explicitly assumed simulation models, not NYC treatment effects. Latent-demand
representativeness, transit-disruption enrichment, individual income, realized event exposure,
and any live-market causal conclusion remain future work.

## Verification

- `make reproduce-sample` completed after the final source change on 2026-08-09.
- `artifacts/reproduce_manifest.json` hashes 83 generated files and records source-tree digest
  `23554c1b370fe3d953471ff4e4582ee44e166b62fd81907838242245dc864a6d`.
- The recorded digest equals the current source/config/Makefile digest; the incomplete-run marker
  is absent.
- `make validate-nyc-sample` completed twice with the same raw-file SHA-256 and a peak RSS of
  approximately 0.87 GiB on the measured run.
- The NYC manifest hashes all five raw/clean/panel/diagnostic files, and every recorded byte count
  and SHA-256 was independently rechecked.
- `make validate-nyc-full` completed on all 19,663,930 records in 55.18 seconds with maximum RSS
  3,839,901,696 bytes (3.58 GiB) and peak footprint 6,313,925,232 bytes (5.88 GiB).
- Two single-threaded full-month reruns produced identical bytes for all 201 data files. The data
  and analysis manifests independently validate 201/201 and 13/13 entries.
- `make test`: 246 tests passed.
- `make lint`: Ruff passed.
- `pip check`: no broken requirements.
- Streamlit's test runner completed the initial render and an on-demand scenario without an
  exception; cached results are suppressed when controls change. Its lineage-gated evidence panel
  validates the NYC-informed, NYC-graph, theoretical-equilibrium, NOAA-weather,
  calendar/event, and ecological neighborhood-income layers.

## Generated evidence

### Empirical description

- Input: 300 authentic Chicago TNP trips from 2022-01-01, selected as 25 lexical-ID rows at each
  of 12 even-hour timestamps. Fixture SHA-256:
  `84177e5a72548cc4346df99f0a6b671adb50d7762e23abe041f01b2958b85ad7`.
- Output: 170 occupied zone-hour cells. The sample is deliberately nonrepresentative; absent
  cells are unknown rather than zero.
- Trip-weighted observed fare is 22.475. This and mean trips per occupied cell are illustrative
  scale anchors, not population or causal estimates.
- The quota-by-hour fixture cannot identify temporal demand patterns or one-hour persistence;
  it contains zero exact one-hour within-zone pairs.

### Bounded NYC adapter validation

- Input: 10,000 authentic January 2024 NYC TLC high-volume for-hire vehicle trips from the
  official monthly Parquet object. Raw sample SHA-256:
  `b8aeeb5c99ab94306251a22419a894769d1e8801a1080862a47105c19800dfae`.
- Selection: deterministic equal quotas over 96 configured strata: January 1, 10, 19, and 28,
  crossed with every hour of day. Eighty strata contain 104 rows and sixteen contain 105 rows.
  Pickup timestamps span 2024-01-01 00:01:06 through 2024-01-28 23:58:27.
- Output: 10,000 normalized trips, 7,112 occupied zone-hour cells, and 9,852 occupied OD cells;
  both panel trip-count totals reconcile exactly to 10,000. The sample covers 246 pickup and 254
  dropoff zones.
- Basic validity diagnostics found no missing or duplicate surrogate trip IDs, no negative
  distance, no nonpositive duration, and no UTC-conversion failure. One negative fare is retained
  and flagged rather than silently censored. Census-tract fields are correctly marked unavailable
  in this NYC schema instead of being mislabeled as zero suppression.
- Descriptive, equal-stratum sample means are fare 24.8393, distance 5.2648 miles, duration
  17.8259 minutes, airport share 0.0951, shared-request share 0.0428, and shared-match share
  0.0153. These are validation summaries, not population-weighted monthly estimates.

### Full-month NYC descriptive analysis

- Input: all 19,663,930 completed-trip records in the pinned January 2024 NYC TLC HVFHV Parquet;
  raw bytes 472,757,547 and SHA-256
  `9897de352aa52cea36b70348cc6721b8d4494327ce39c85f0dba83d86ecaa098`.
- Coverage: every one of 31 pickup dates, all 24 hours, and all 744 date-hours; pickup timestamps
  run from 2024-01-01 00:00:00 through 2024-01-31 23:59:59.
- Output: 197 streamed clean parts, 194,928 complete zone-hour cells over 262 observed monthly
  pickup zones (186,822 occupied plus 8,106 reported-zero grid cells), and 6,877,734 OD-hour rows.
  Raw, clean, zone-panel, and OD-panel counts all reconcile exactly to 19,663,930.
- Descriptive values among published trips: mean/median fare 23.9592/18.0000; mean distance 4.8386
  miles; mean duration 18.5078 minutes; airport share 0.07883; shared-request share 0.03732; and
  shared-match share 0.01159. The exact one-hour zone-demand association is 0.9488 over 194,666
  adjacent-hour pairs; it is not a causal persistence parameter.
- Quality diagnostics retain and flag 191 negative fares, 7,143 zero fares, two nonpositive
  durations, and zero negative-distance, reverse-timestamp, or pickup-month-boundary violations.

### Full-month NYC calibration and network inputs

- The separately manifested descriptive bundle verifies all 7 files against the 201-file source
  manifest. Of 19,663,930 records, 19,475,679 have nonnegative request-to-pickup elapsed time;
  188,251 negative differences are reported rather than silently treated as waits. Valid wait
  time has median 3.688 minutes and p90 7.340 minutes.
- Mean published driver pay is $18.269 and mean base passenger fare is $23.959. These do not
  identify driver opportunity cost, platform revenue, price elasticity, or incentive response.
- The monthly completed-trip graph contains 262 nodes and 30,535 undirected cross-zone edges;
  92.55% of records cross pickup/dropoff zones. A symmetric weighted exposure-map candidate is
  exported, but OD connectivity is not interpreted as causal spillover or substitution.
- The NYC simulation proposal verifies the complete source hash chain and initializes a 32-zone ×
  168-period model. Its deterministic control path matches mean completed trips and mean wait
  exactly and matches descriptive between-zone and hour-of-day variance shares within 0.01.
  Behavioral response, supply, interference, persistence, substitution, and welfare remain
  explicit assumptions; the default design benchmark still uses its offline vertical-slice
  calibration rather than claiming NYC causal magnitudes.

### Full-month NYC weather association

- An official NOAA NCEI Daily Summaries extract for Central Park station `USW00094728` covers all
  31 January 2024 dates and joins to all 744 NYC panel date-hours. The committed raw file has
  SHA-256 `fa9a5486dfa37e1ab61ad853d1811369f25e8c71ebf9dd0d56217f8231a0ee04`.
- The joined panel conserves all 19,663,930 published completed trips. Fifteen dates meet the
  predeclared wet-day threshold and sixteen are dry; mean daily published trips are 641,763.3 and
  627,342.5 respectively, a descriptive difference of 14,420.8 or 2.30% relative to dry days.
- This is a one-month, citywide-station association confounded by calendar and other shocks. It is
  not a weather elasticity, instrument, demand effect, or causal estimate.

### Full-month NYC calendar and permitted-event association

- The pinned NYC Open Data permit extract retains all 6,007 January-overlap rows and 951 source
  event IDs. Of these, 5,998 positive-duration rows representing 949 IDs are usable for daily
  expansion. One reversed interval and eight zero-duration intervals are retained and flagged but
  excluded; half-open `[start, end)` expansion yields 6,711 unique event-days.
- All 19,663,930 published completed trips reconcile across the 31-day/744-hour join. Above-median
  permit-intensity days average 19,097.4 more trips/day than lower-intensity days (+3.055%), but all
  eight weekends are in the high-intensity group and none are in the comparison group. Among
  weekdays only, the descriptive difference reverses to -51,244.9 trips/day (-8.198%).
- Permit records do not measure attendance or realized event scale, and the signal is citywide by
  day rather than zone/hour exposure. These contrasts are calendar-confounded associations, not
  event effects.

### Full-month NYC ecological neighborhood-income association

- Official 2022 ACS five-year B19001 counts are aggregated from Census tracts to NTAs before any
  grouped median is calculated, then allocated to Taxi Zones by EPSG:6933 equal-area overlap. All
  3,282,804 households and all sixteen income bins reconcile exactly.
- The primary rule was fixed before examining trip contrasts: the dominant NTA must be residential
  (`NTAType == 0`), residential overlap must cover at least 50% of Taxi Zone area, and at least one
  household must be allocated. It classifies 234 observed zones and covers 18,770,536 trips
  (95.4567%). Mean published completed trips per zone-hour are 110.6387 in high-income areas and
  103.9695 in low-income areas, a descriptive difference of 6.6692 (ratio 1.0641).
- A legacy all-zone sensitivity gives a larger difference of 11.3520 but classifies 19
  dominant-nonresidential zones representing 881,840 trips; it is explicitly not the primary
  result. Area labels are ecological point estimates—not rider/driver income—and neither the main
  contrast nor the sensitivity identifies an income effect.

### NYC-informed and NYC-graph known-truth validation

- The NYC-informed benchmark verifies the full anchor/calibration/source hash chain, then evaluates
  two declared simulator scenarios with six replications and three design-estimator rows each. In
  the no-interference/no-carryover reference, the geo-cluster estimate is 13.3385 against simulator
  truth 13.3049. Rows with assumed interference or persistence are retained as target-mismatch
  diagnostics rather than relabeled as NYC effects.
- A separate 12-replication benchmark uses the fixed, pre-treatment January NYC OD graph solely as
  exposure geometry. It estimates controlled own exposure at 2.0105 (truth 2.0000), mapped-neighbor
  exposure at 1.5422 (truth 1.5000), and exact-history exposure at 0.6921 (truth 0.7000).
- The naive assignment coefficient is 2.5660 versus market-total simulator truth 4.1708. Its
  market-total bias, RMSE, coverage, and power are withheld because the coefficient targets the
  wrong contrast. OD weights do not estimate spillover strength or substitution.

### Semi-synthetic causal validation

- The eleven-scenario Monte Carlo grid produced 220 summary rows and 5,030 successful fits from
  5,040 planned attempts across five designs and six estimator labels. Ten failed fits are fully
  logged: one geo-time DiD collinearity case and nine two-way clustered fits with nonpositive
  inclusion-exclusion variance. Ten few-cluster geo-DR cells are predeclared inapplicable rather
  than counted as attempted failures.
- No design-estimator pair is identified, inference-valid, applicable, and complete across the
  entire declared grid. The robust rollout recommendation is therefore withheld.
- The dashboard's opening preset exactly matches the 16-zone/eight-cluster, no-interference,
  no-carryover benchmark cell. Conditional on that cell, it selects time-block assignment with
  doubly robust estimation and lists all ten unmatched scenarios.
- In a separate 24-replication known-truth two-stage saturation benchmark, mapped regression
  estimates are 2.006 for controlled own exposure (truth 2.000), 1.495 for neighbor exposure
  (truth 1.500), and 0.691 for exact-history exposure (truth 0.700). The naive saturation
  coefficient is 2.635 versus market-total truth 4.178, but market-total bias/coverage/power are
  deliberately withheld because it targets the wrong contrast.
- The HTE learner has RMSE 0.0417 versus an oracle constant-effect RMSE of 0.0247, with truth-rank
  correlation 0.2239. It fails the predeclared recovery gate and is not decision-ready.

### Semi-synthetic policy decision

- Five policies were evaluated on eight holdout market seeds disjoint from training, with a
  shared $1,000 cap and joint simulator re-evaluation.
- The predeclared conservative rule selects uniform allocation: mean incremental trips 68.4967,
  SE 0.1050, and holdout p10 68.1030 per modeled market. The model-based policy underperforms
  random allocation in this run.
- These are conditional simulator results, not forecasts of live lift, welfare, or return.

### Theoretical fixed-point equilibrium benchmark

- A separate two-zone, two-sided fixed-point model solves rider demand, driver supply, service
  probability, congestion-linked wait, and cross-zone tightness under common random numbers. Both
  control and bundled-treatment paths satisfy the declared contraction and numerical convergence
  checks with residuals below the configured tolerance.
- Within that declared model, bundled treatment produces 30.6775 incremental trips, 668.7300 units
  of modeled welfare, and 685.2729 of treatment spend: 0.04477 trips and 0.97586 welfare units per
  dollar. The ledger reconciles rider, driver, and platform components.
- These are exact paired counterfactuals for an unfitted theoretical model. They are neither an NYC
  structural estimate nor evidence of live welfare, elasticity, entry, relocation, or strategic
  behavior.

## Explicit unresolved scope

- The bounded NYC sample is nonprobability and not population-weighted. The full-month file covers
  TLC's pinned published completed-trip records, not latent demand, unserved requests, or a
  probability sample of all marketplace opportunities.
- The NYC sample has an exact 10,000-row output bound, but that is not a hard bound on remote
  bytes scanned or peak memory; it relies on Parquet predicate/range pruning. The measured run
  stayed below 1 GiB RSS, but upstream layout changes could alter resource use.
- Weather, permit-calendar, and ecological neighborhood-income enrichments are now pinned,
  manifested, and joined. A verified transit-disruption layer is still unavailable. One month of
  citywide weather/event proxies and area-level ACS allocation does not identify causal shocks,
  attendance, individual income, or cross-season transportability.
- The primary marketplace simulator remains a reduced-form market-system path with congestion and
  cross-zone channels. The separate fixed-point equilibrium benchmark is solved and verified, but
  its behavioral parameters are declared rather than estimated, it is static, and it does not make
  the primary simulator or NYC evidence structural. Welfare remains model-dependent.
- The implemented intervention versions are rider discount, driver incentive, or their bundle;
  the primary decision artifact uses the bundle and a separately manifested common-seed
  sensitivity covers all three. Driver response to incentive size is a declared linear
  sensitivity, not an empirical dose-response estimate or treatment comparison.
- Controlled exposure-response slopes still require an external structural or equilibrium bridge
  before they can be interpreted as the all-market policy effect. The known-truth ring benchmark
  does not validate the NYC OD map, exposure-specific two-way inference, decaying/anticipated
  histories, or exposure-map measurement error.
- A live pilot still requires exposure logging, enough randomized clusters, operational guardrail
  definitions, and a design whose assumptions survive the target market's interference and
  persistence audit.

## Primary handoff artifacts

- `artifacts/reports/technical_report_generated.md`
- `artifacts/reports/product_decision_memo_generated.md`
- `artifacts/reports/generated_decision_appendix.md`
- `artifacts/benchmarks/benchmark_results.csv`
- `artifacts/benchmarks/interference_summary.csv`
- `artifacts/benchmarks/nyc_informed/summary.csv`
- `artifacts/benchmarks/nyc_informed/manifest.json`
- `artifacts/benchmarks/nyc_graph/summary.csv`
- `artifacts/benchmarks/nyc_graph/manifest.json`
- `artifacts/benchmarks/equilibrium/summary.json`
- `artifacts/benchmarks/equilibrium/manifest.json`
- `artifacts/benchmarks/policy_results.csv`
- `artifacts/benchmarks/treatment_version_policy_results.csv`
- `artifacts/benchmarks/heterogeneity/hte_recovery.json`
- `artifacts/reproduce_manifest.json`
- `data/nyc_sample/manifest.json`
- `data/nyc_sample/diagnostics.json`
- `data/nyc_full/manifest.json`
- `data/nyc_full/diagnostics.json`
- `artifacts/nyc_full/validation.json`
- `artifacts/nyc_full/full_month_report.md`
- `artifacts/nyc_full/manifest.json`
- `artifacts/nyc_full/calibration_network/calibration.json`
- `artifacts/nyc_full/calibration_network/manifest.json`
- `artifacts/nyc_full/simulation_anchor/nyc_simulation_anchor.json`
- `artifacts/nyc_full/simulation_anchor/manifest.json`
- `artifacts/nyc_full/weather/weather_associations.json`
- `artifacts/nyc_full/weather/manifest.json`
- `artifacts/nyc_full/events/event_associations.json`
- `artifacts/nyc_full/events/manifest.json`
- `artifacts/nyc_full/income/income_associations.json`
- `artifacts/nyc_full/income/manifest.json`
