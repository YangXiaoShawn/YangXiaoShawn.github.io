# Project Status

**Last updated:** 2026-08-10

**Stage:** Synthetic acceptance plus timed, two-horizon, holdout-evaluated official pilot complete

**Overall status:** Genuine CES/core-CPI/GDP, sectoral CES, CPS unemployment, DOL claims,
Fed G.17 industrial-production, Census retail-sales, Census housing-start, and 96 BEA NIPA
real-GDP level snapshots verified; broader cross-agency study remains
incomplete

## Delivered

- Implemented a typed 16-column vintage schema, fixture and guarded live adapters, Parquet
  storage, DuckDB views, and deterministic artifact hashing.
- Implemented explicit UTC release events, arbitrary as-of snapshots, fixed-eligibility-mask
  latest-value counterfactuals, a separately labeled naive latest-revised leakage benchmark,
  missing-vintage handling, and no-future-information assertions.
- Added strict configuration and execution for three distinct targets:

  | Series | Target | Formula | Frequency / units |
  | --- | --- | --- | --- |
  | `PAYEMS` | `payems_change_mom_thousands` | `current_level - prior_level` | Monthly; thousands of persons change |
  | `CPILFESL` | `core_cpi_pct_change_mom` | `100 * (current_level / prior_level - 1)` | Monthly; nonannualized percent change |
  | `GDPC1` | `real_gdp_pct_change_qoq_saar` | `100 * ((current_level / prior_level) ** 4 - 1)` | Quarterly; percent change at SAAR |

- Built target-specific ragged-edge feature matrices from monthly, weekly, daily, and
  quarterly synthetic observations only after vintage selection.
- Implemented historical mean, no-change, AR(1), linear bridge, Elastic Net, and
  deterministic histogram gradient boosting for each target.
- Implemented release-aware expanding windows, fold-local preprocessing, RMSE, MAE, bias,
  prior-residual interval coverage, horizon/regime groups, guarded synthetic
  Diebold–Mariano diagnostics, target-revision analysis, and artifact-level timing audits.
- Added a completion-gated multi-target dashboard and a generated comparison/limitations
  report that keep target formulas, samples, frequencies, and units visible.
- Added 36 target/model stability comparisons across both revised-data counterfactuals,
  three exact frozen-linear-model news updates, and one generated policy brief per target.
- Moved the Streamlit entry point outside the package so the project `calendar.py` cannot
  shadow Python's standard-library `calendar` module during dashboard startup.
- Preserved the original payroll-only workflow, simulated release attribution, one-page
  brief, required reports/portfolio files, commands, and dashboard fallback.
- Established a local Git root baseline for all versionable code, configuration, tests,
  documentation, and compact synthetic fixtures. Raw archives, generated empirical
  artifacts, temporary audit files, virtual environments, and credentials remain ignored.
- Added guarded original-provider BLS and BEA latest-data adapters plus archive manifests
  and production parsers; see [Data Access](docs/DATA_ACCESS.md).
- Acquired official CES, CPI, GDP, Employment Situation, DOL weekly-claims, Federal
  Reserve G.17, U.S. Treasury 10-year CMT, Census MARTS, and Census NRC archive evidence,
  added a deterministic offline audit, parsed 626,304
  canonical rows across 21 series including
  eight sectoral CES matrices, CPS unemployment-rate snapshots, and DOL claims, and froze
  Parquet/DuckDB artifacts with hashes.
- Acquired and audited 96 of 98 expected BEA NIPA initial-release Section 1 workbooks,
  parsed 23,416 `GDPC1` level vintages, and persisted a 96-row same-snapshot growth
  validation. The unavailable 2002Q1/Q2 snapshots remain explicit gaps.
- Added event-specific target timing: consistent Employment Situation embargo headers and
  every acquired CPI and GDP target snapshot use exact clocks, while unsupported/
  conflicting PAYEMS events retain the conservative date-only convention. The BEA pilot
  target remains explicitly already transformed.
- Added one exact frozen-model official archive update and one guarded brief per target;
  maximum contribution-sum residual is `7.11e-15` target units.
- Added separate target-release-nowcast and one-native-period-ahead official research
  datasets, models, rankings, DM comparisons, stability results, and Dashboard controls.
  The future target is never released by its origin, and DM HAC lag is persisted by horizon.
- Added ex-post NBER expansion/recession labels to official predictions and 216 grouped
  horizon/regime diagnostics. The labels are evaluation metadata only, are absent from
  every feature matrix, and are explicitly too sparse for broad regime conclusions.
- Added prespecified advanced-model tuning blocks and untouched final evaluation: 60
  candidate rows, 12 frozen selections, 108 final metric rows, and zero final-evaluation
  rows used for selection. DM diagnostics and stability ranks now use the final block;
  all-OOS metrics remain separately labeled descriptive.

## Synthetic acceptance workflow

The acceptance workflow remains synthetic; its figures are not empirical findings.

- Provenance: `synthetic_fixture` only.
- Modeling workflow network used: `false`. Official archive HTTPS acquisition was performed
  separately on 2026-08-09.
- BLS, BEA, and FRED APIs accessed: `false`.
- Canonical vintage rows: 5,558.
- Series: 12 — `AWHMAN`, `CCSA`, `CPILFESL`, `DGS10`, `GDPC1`, `HOUST`,
  `ICSA`, `INDPRO`, `PAYEMS`, `RSAFS`, `UMCSENT`, and `UNRATE`.
- Pre-release forecast origins: 228 — PAYEMS 98, CPILFESL 98, GDPC1 32.
- Audited feature cells: 5,766 — PAYEMS 2,940, CPILFESL 2,058, GDPC1 768.
- Target rows: 450 — PAYEMS 194, CPILFESL 194, GDPC1 62.
- Evaluation forecasts: 1,980 — PAYEMS 846, CPILFESL 846, GDPC1 288.
- Model/metric coverage: six models, 54 metric rows, and three information modes:
  `vintage_aware/as_of/first_release`,
  `latest_values_same_eligibility_mask/latest_revised`, and the deliberately invalid
  `naive_latest_revised/latest_revised` leakage benchmark.
- Evaluation samples: 47 months each for PAYEMS and CPILFESL; 16 quarters for GDPC1.

These counts come from `data/generated/multitarget/run_manifest.json` and direct grouped
reads of its named Parquet artifacts. They describe a deterministic software fixture, not
the U.S. economy.

## Official-archive empirical pilot

- Provenance: `official_agency_archive` only.
- Canonical source rows: 626,304 across 21 series — PAYEMS 247,115, eight CES sectors
  331,864, CPS unemployment rate 1,322, DOL claims 2,470, DOL published four-week averages
  1,235, Fed G.17 total industrial production 4,306, G.17 published monthly IP changes
  4,306, Census retail levels 273, Census published monthly retail changes 273, core CPI
  housing starts 276, Treasury 10-year CMT 6,154, core CPI 2,241, published real-GDP
  growth 1,053, and `GDPC1` levels 23,416.
- Mixed-precision pre-release origins: 544 — PAYEMS 273, CPILFESL 173, GDP 98. Of these,
  272 PAYEMS, all 173 CPI, and all 98 GDP origins are exactly one second before verified
  release clocks; only the conflicting 2012-12-07 PAYEMS event retains the
  prior-New-York-day EOD convention.
- Audited feature cells: 23,955; target rows: 1,086; horizon-specific research rows: 3,249.
- Expanding-window forecasts: 15,264 across six models, three information modes, and
  horizons `0` and `1`.
- Metrics: 108 rows; ex-post NBER regime/horizon diagnostics: 216 rows; guarded DM
  comparisons: 90 rows; model-stability rows: 72;
  source-revision summaries: 20; target-revision summaries: 36.
- Tuning/final evaluation: 60 candidate rows, 12 selected settings, 108 final metric rows,
  and 0 final rows used for hyperparameter selection. Monthly final groups contain 24
  forecasts; GDP final groups contain eight quarters.
- Strict feature timing violations: **0**. Naive latest-revised mode contains 863 cells whose
  first eligibility followed the origin; this is intentional leakage, not a valid input.
  Treasury contributes 542 of those invalid same-day pre-EOD selections; both valid modes
  contribute zero.
- Predictors include target lags/cross-target values, eight official CES sector-employment
  vintages, BLS CPS `LNS14000000` unemployment-rate vintages, and the directly published
  DOL initial-claims four-week average, Fed G.17 directly published monthly industrial-
  production changes, U.S. Treasury 10-year CMT 20-observation means, Census MARTS directly
  published monthly retail changes, and Census NRC published housing starts. The remaining
  cross-agency synthetic indicator list is not treated as genuine historical data.
- Employment Situation evidence verifies 276 exact clocks: 56 direct official TXT
  releases from 2003-06-06 through 2008-01-04 plus 220 browser-rendered HTML headers from
  2008-02-01 through 2026-07-02. The 2012-12-07 page prints `EDT` during New York standard
  time and therefore remains date-only. The acquired CES target window uses 272 exact
  PAYEMS events and one date-only PAYEMS event. A separate CPI inventory verifies 221 official clocks from
  2008-02-20 through 2026-07-14 and supplies exact clocks for all 173 acquired CPI target
  snapshots. A BEA inventory verifies all 98 GDP initial-release clocks from 2002-04-26
  through 2026-07-30. DOL claims, G.17, MARTS, and NRC retain their separately verified
  exact predictor clocks. Treasury observations use conservative source-date New York EOD
  because an exact publication clock is not stated.
- `target_timing_precision_audit.parquet` rebuilds the complete date-only counterfactual:
  all 543 exact PAYEMS/CPI/GDP origins move by 30,599.000001 seconds, while zero of 23,955
  feature value/selection cells and zero of 1,086 target values change for the current
  panel.
- Official release updates: 3; generated official-pilot briefs: 3. Training uses only
  targets released before each event, and the Dashboard exposes the contribution tables.
- Artifact manifest: `data/generated/official_pilot/run_manifest.json`; source ingestion
  manifest: `data/generated/official_vintages/ingestion_manifest.json`.

The pilot can support narrowly scoped descriptive forecast comparisons by information mode,
two prespecified horizons, and ex-post NBER expansion/recession cuts. It does not yet
support broad model-superiority, robust business-cycle-regime, fully tuned calibration,
investment, or policy claims.

## Official archive evidence acquired

- BLS CES: verified `cesvinall.zip`, including the `CES0000000001` total-nonfarm CSV
  matrix with 273 vintage rows spanning May 2003–January 2026. They map to 272 official
  release dates; October and November 2025 correctly share one release event.
- BLS CPS: acquired and hashed 221 complete Employment Situation browser-rendered DOM
  exports covering releases from 2008-02-01 through 2026-07-02. The parser handles 24
  preformatted and 197 structured A-1 tables and produces 1,322 publication-vintage rows
  across 233 unemployment-rate observation months. DOM exports are not represented as
  original HTTP response bytes.
- BLS Employment Situation clocks: acquired the 56 direct TXT releases needed to cover
  the CES window before the DOM archive, from 2003-06-06 through 2008-01-04. The audit
  verifies every printed weekday/date, 8:30 a.m. clock, and `EST`/`EDT` label; 32 releases
  are `EDT`, 24 are `EST`, 52 decode as UTF-8, and four require `cp1252`. Original bytes,
  URLs, encodings, byte counts, and SHA-256 values are preserved in `release-index.json`.
- BLS CPI: acquired all 13 annual ZIPs for 2012–2024 and all 17 current monthly files listed
  through June 2026. The audit inventories 173 workbooks, verifies the core-CPI row in 138
  XLSX and 35 converted legacy XLS files, maps all 173 snapshots to official release dates,
  and preserves the documented October 2025 gap. A separate 221-event official CPI release
  inventory verifies 49 `EST`, 101 `EDT`, and 71 `ET` embargo headers. It retains 220
  browser-rendered header-text extracts and one official-PDF extract, explicitly claiming
  neither complete DOM capture nor original server bytes.
- DOL UI claims: acquired 1,238 official archive links, retained 1,235 actual releases,
  and explicitly excluded two byte-identical year-directory aliases plus one official dummy
  placeholder. The 105 HTML, 494 ASP, and 636 PDF releases yield 2,470 current/prior weekly
  vintage rows plus 1,235 directly published four-week averages. Coverage is 2002-10-17
  through 2026-08-06; every included file has a verified SHA-256 and parses under the
  official 8:30 a.m. Eastern schedule.
- Federal Reserve G.17: acquired and hashed 367 dated ASCII snapshots covering
  1997-12-15 through 2026-07-17: 343 monthly releases and 24 annual revisions. The parser
  retains 4,306 total-IP level vintages and 4,306 directly published monthly percent-change
  vintages, six historical base periods, and exact file-header clocks. All release hashes
  are unique and all 8,612 canonical keys are unique. The audit preserves the official
  `20000215` path whose header states 2000-02-16, and labels three 2026 AM/PM zone readings
  as `America/New_York` continuity inferences rather than direct zone-label verification.
- Census MARTS: enumerated 281 reference-month PDFs and accepted 273 releases covering
  reference months 2003-01 through 2026-05. They yield 273 seasonally adjusted retail/
  food-services levels and 273 directly published monthly changes. Eight early scanned
  PDFs have no text layer and remain explicit gaps (`2003-02`, `2003-04`, `2004-01`,
  `2004-11`, `2005-05`, `2005-08`, `2005-11`, `2005-12`). All accepted hashes and
  canonical keys are unique; 20 `ET` header labels are explicitly interpreted with
  `America/New_York`, and all 8:30 a.m. clocks are verified.
- Census NRC: enumerated 278 historical-release PDFs and accepted 276 housing-start
  releases covering 2003-01 through 2026-06. Six reference months remain explicit gaps:
  `2012-08`, `2013-09`, `2013-10`, `2025-09`, `2025-11`, and `2026-02`. The 2013 pair is
  excluded with official funding-lapse/link-mismatch evidence; the official April 2009
  `fhttps` link typo is repaired and recorded. All accepted keys and exact EST/EDT clocks
  verify.
- BEA GDP: verified all 98 quarterly sections and exactly one dated initial estimate per
  quarter in the GDP/GDI growth summary. All 1,053 estimate/revision rows have numeric
  growth and release dates. The official NIPA directory supplies 96 initial-release
  Section 1 workbooks for 2002Q3–2026Q2; 2002Q1/Q2 are absent and remain missing. Sixty
  legacy XLS and 36 XLSX files yield 23,416 `GDPC1` level vintages. All 96 target/prior
  level pairs come from one snapshot; 94 derived q/q SAAR values round exactly to the
  published tenth and all 96 differ by no more than 0.06 percentage point. A separate
  98-page news-release inventory
  verifies 96 `Advance` and two shutdown-affected `Initial` clocks: 70 `EDT`, 28 `EST`,
  all at 8:30 a.m. Eastern. It records four wire-transmission, one embargoed-for-release,
  and 93 embargoed-until-release header styles.
- Thirty-one BEA NIPA archive-directory date labels conflict with the verified workbook/
  news-release date. The audit preserves every conflict and uses the independently verified
  release clock. Raw levels span six chained-dollar reference years and both billions and
  millions scales, so only same-snapshot adjacent-level growth is supported; cross-vintage
  raw-level revision comparison is not.
- The BEA archive list dates two releases one day early—2009-10-28 and 2018-10-25—while
  the page headers and GDP vintage workbook agree on 2009-10-29 and 2018-10-26. Both source
  conflicts and their resolution basis are retained in audit and row-level metadata.
- Source audit status remains `verified_with_limitations` because one conflicting BLS
  header and the two prearchive NIPA quarters remain incomplete. The downstream ingestion manifest
  records `historical_ingestion_ready =
  true` under the mixed exact/date-only convention.
- No BLS, BEA, or FRED API was called, no API credential was used, and `api.txt` was not
  read. Raw evidence and derived empirical artifacts are Git-ignored.

## Verified behavior and supported findings

- The completed manifest reports artifact stage `multitarget_backtest_complete`, status
  `complete`, 24 hashed report/data artifacts, and `empirical_findings_supported = false`.
- Feature and target timing audit violations: **0**. Independent DuckDB queries and the
  reproducibility integration test also passed.
- The naive benchmark records 893 feature cells whose first availability followed the
  historical origin. This is intentional measured leakage; neither strict mode has one.
- Monthly-to-quarterly coverage, staleness, source availability, target realization
  availability, and fixed-latest eligibility masks remain explicitly auditable.
- Every target carries its own formula, frequency, units, evaluation window, and
  annualization declaration.
- Quarterly GDP's smaller sample remains visible, and insufficient statistical comparisons
  remain invalid rather than being promoted to findings.
- All three release updates use an exact fixed-linear-model decomposition; the maximum
  independent contribution-sum residual is `1.78e-14` in target units.

No synthetic metric, comparison, revision size, attribution, or model ordering is an
empirical finding about real forecast accuracy, the U.S. economy, or policy.

## Reproduction and validation record

- `make reproduce-multitarget` — passed with 3 targets, 12 series, 5,558 vintage rows, 228
  pre-release forecast origins, 5,766 feature cells, 450 target rows, 1,980 forecasts,
  54 metric rows, 893 intentionally leaked naive cells, three news updates, three briefs,
  and zero strict-mode timing violations.
- `.venv/bin/pytest -q` — **215 passed**, with one non-failing joblib
  physical-core detection warning.
- `.venv/bin/ruff check .` — passed.
- Independent DuckDB artifact/count/timing audit — passed.
- Dashboard bare-mode smoke test through `scripts/dashboard_entry.py` — passed with expected
  Streamlit context warnings; the prior standard-library shadowing failure is fixed.
- Actual headless Streamlit server startup through the same entry point — reached ready
  state on a temporary local port and stopped normally.
- `make reproduce-sample` — the legacy payroll workflow remains supported with its original
  10-series, 5,261-row, 564-forecast acceptance slice.
- `make acquire-dol-claims` — acquired and verified 1,235 actual releases and 3,705
  canonical DOL rows without credentials.
- `make audit-agency-vintages` — passed the original four artifact checks plus the complete
  Employment Situation and DOL claims inventories and wrote the
  fail-closed manifest under `data/generated/agency_vintages/`; 276 Employment Situation
  clocks passed (56 TXT plus 220 HTML) and one known header conflict remained date-only.
  The CPI clock artifact
  also passed for 221 events, including all 173 acquired CPI target snapshots; the GDP
  artifact passed for all 98 workbook initial releases.
- `make acquire-fed-g17` — verified 367 releases, 8,612 canonical rows, six base periods,
  unique hashes, and exact release clocks.
- `make acquire-treasury-rates` — verified 25 official year feeds and 6,154 daily 10-year
  CMT rows through 2026-08-07, with unique hashes and conservative New York EOD eligibility.
- `make acquire-census-retail` — verified 273 accepted releases, eight explicit no-text
  exclusions, 546 canonical rows, unique hashes/keys, and exact 8:30 a.m. release clocks.
- `make acquire-census-housing` — verified 276 accepted releases, two explicit 2013
  exclusions, 276 canonical rows, exact clocks, six retained gaps, and one logged index typo.
- `make acquire-bea-nipa-levels` / `make audit-bea-nipa-levels` — acquired and verified 96
  original NIPA workbooks, 23,416 canonical level rows, 96 exact clocks, and two explicit
  prearchive gaps without an API credential.
- `make ingest-agency-vintages` — wrote 626,304 canonical rows, 2,791 release events, three
  Parquet files, three DuckDB views, and a hashed ingestion manifest.
- `make reproduce-official-pilot` — completed 23,955 feature cells, 15,264 real-data
  expanding-window predictions, three exact official release updates, and three briefs
  with zero strict timing violations. It also wrote a 544-row target-clock precision audit;
  543 origins changed relative to date-only, while feature/target values did not. After the
  NIPA level extension, feature, prediction, metric, and comparable-source revision hashes
  remain unchanged; the manifest records the 96-row validation without replacing the
  published-growth pilot target.

Run the current multi-target workflow and dashboard with:

```bash
make ingest-agency-vintages
make reproduce-official-pilot
make reproduce-multitarget
make dashboard
```

The multi-target command creates `data/generated/multitarget/multitarget_report.md` as part
of the completed artifact set. `make dashboard` selects that set only when its manifest is
complete; otherwise it falls back to the payroll output. The legacy payroll report path
remains `make reproduce-sample`, `make policy-brief`, and `make report`.

Target-specific generated briefs are at
`data/generated/multitarget/policy_briefs/{PAYEMS,CPILFESL,GDPC1}_policy_brief.md`.
The complete A–J and acceptance-criteria evidence map is in
[Requirement-by-Requirement Acceptance Audit](docs/ACCEPTANCE_AUDIT.md).

## Data-access and interpretation limitations

- `api.txt` is ignored by Git, has filesystem mode `0600`, and was not read or used. The
  completed manifest independently records `api_txt_read = false`.
- Possession of any credential is not authorization to access a provider or persist its
  data. Terms approval is a separate, explicit, fail-closed gate.
- The FRED/ALFRED live path remains disabled because current and older official terms pages
  differ in ways material to caching/database and model-development use. No FRED request
  was attempted.
- BLS and BEA current APIs provide current/latest-revised data, not complete historical
  as-of vintages. Their API rows cannot be labeled first release.
- Operator opt-in and the official-file inventory/content audit are recorded. BLS CES/CPI
  and BEA GDP archive ingestion is enabled only for the declared mixed-timing pilot.
  All acquired pre-2008 PAYEMS target events now have direct-TXT exact clocks; one
  conflicting BLS event remains date-only. Level-derived NIPA GDP is a separate verified
  96-quarter validation layer rather than a silent replacement for the published-growth
  pilot. CPI clocks are evidence-backed but the saved clock artifact
  is rendered header text rather than claimed original HTTP bytes. Official sources
  and attribution requirements are documented in
  [Data Access](docs/DATA_ACCESS.md).
- Synthetic dates, values, revisions, regimes, release timing, metrics, and comparisons
  cannot support economic-regime, significance, calibration, investment, monetary-policy,
  or model-superiority claims.

## Remaining milestones

1. Obtain express written permission for historical University of Michigan sentiment
   releases, then acquire and audit preliminary/final snapshots. Eight CES sectors, CPS
   unemployment, DOL claims, industrial production, Treasury 10-year point observations,
   retail, and housing are complete. Treasury rates are not labeled correction vintages;
   post-2016 H.15 DDP current history is still not substituted for dated snapshots.
2. Add horizons beyond the implemented target-release nowcast and one-native-period-ahead
   design and larger-sample regime/stability/interval analysis. Prespecified tuning and an
   untouched final block are now implemented; NBER recession samples remain descriptive.

The NIPA acquisition milestone is closed rather than left as an implicit modeling gap.
Published initial growth remains the authoritative pilot target; the 96-quarter level path
is a verified reconstruction/rounding sensitivity and will become a model tier only under a
separately prespecified research question.
