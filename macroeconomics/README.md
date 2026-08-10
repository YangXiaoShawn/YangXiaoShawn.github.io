# Real-Time Macro Nowcasting and Policy Shock Engine

This project reconstructs the information that was actually available at historical
forecast origins, then compares valid vintage-aware forecasts with a deliberately
counterfactual latest-revised-data backtest. A second, explicitly invalid naive benchmark
also admits not-yet-released cells so value-revision leakage and release-timing leakage can
be measured separately rather than buried in a notebook.

> **Current data status:** the fixture workflows remain deterministic software
> demonstrations. A separate official-archive empirical pilot now uses audited BLS CES,
> BLS core-CPI, and BEA published real-GDP vintages, plus eight BLS sector-employment
> publication-vintage series, BLS CPS unemployment-rate release snapshots, and DOL weekly
> initial-claims releases, plus Federal Reserve G.17 industrial-production release
> snapshots, Census MARTS retail-sales releases, Census NRC housing-start releases, and a
> separately audited 96-snapshot BEA NIPA real-GDP level archive. It supports
> findings only within this still-incomplete
> cross-agency predictor scope; it does not validate the full synthetic indicator set or
> support policy/model-superiority claims.

## Implemented targets

The completed multi-target workflow keeps each target's formula, frequency, and units
explicit:

| Target | Configured formula | Frequency and units |
| --- | --- | --- |
| `PAYEMS` / `payems_change_mom_thousands` | `current_level - prior_level` | Monthly change, thousands of persons |
| `CPILFESL` / `core_cpi_pct_change_mom` | `100 * (current_level / prior_level - 1)` | Monthly percent change, nonannualized |
| `GDPC1` / `real_gdp_pct_change_qoq_saar` | `100 * ((current_level / prior_level) ** 4 - 1)` | Quarterly percent change, seasonally adjusted annual rate |

Every growth target selects its current and prior levels from one information snapshot.
The system never pools these targets as though their scales or frequencies were
interchangeable.

The official pilot preserves the same payroll and core-CPI definitions. Its primary GDP
benchmark continues to use BEA's historical workbook of already annualized published
growth estimates and is explicitly
`official_published_value_already_transformed_no_retransformation`. It is never annualized
a second time or represented as level-derived `GDPC1`. A separate validation layer now
computes 96 first-release growth values from adjacent real-GDP levels selected from the
same archived NIPA snapshot; it does not silently replace the published-growth benchmark.

The original payroll-only vertical slice remains supported. It uses the same six-model
ladder, ten mixed-frequency predictors, expanding-window evaluation, revision analysis,
simulated release attribution, policy brief, reports, and dashboard.

The multi-target workflow now performs one audited frozen-model release update and writes
one target-specific policy brief for each configured target.

## Verified offline multi-target reproduction

The completed `data/generated/multitarget/run_manifest.json` records:

- Status `complete`, stage `multitarget_backtest_complete`, fixture label
  `synthetic_fixture`, no network use, and no empirical findings supported.
- 5,558 canonical vintage rows across 12 synthetic series.
- 228 target-specific pre-release forecast origins: 98 for payroll, 98 for core CPI, and 32 for real GDP.
- 5,766 audited feature cells and 450 first-release/fixed-latest target rows.
- 1,980 forecasts: 846 payroll, 846 core-CPI, and 288 real-GDP forecasts across six
  models and three explicitly labeled information modes.
- 54 metric rows, 36 model-stability rows, and zero violations in the valid as-of or
  fixed-eligibility modes.
- 893 feature cells intentionally exposed as unavailable at their historical origin by
  `naive_latest_revised`; these are recorded leakage, not valid real-time inputs.
- Three exact frozen-linear-model release updates, three target-specific policy briefs,
  and hashes for all 24 generated data/report artifacts.

The generated numerical diagnostics are intentionally not summarized as economic results.
They establish that the configured formulas, mixed-frequency alignment, vintage labels,
and leakage guards execute reproducibly on the fixture—nothing more.

## Verified official-archive empirical pilot

The completed `data/generated/official_pilot/run_manifest.json` records:

- 626,304 canonical official archive rows across 21 series and 544 mixed-precision
  pre-release origins.
- 23,955 audited target/cross-target/sector/household-survey/claims/production/rate/retail/housing
  feature cells, 1,086
  first-release/fixed-latest target
  rows, 3,249 horizon-specific research rows, and 15,264 expanding-window forecasts.
- Six models, three declared information modes, two real forecast horizons, 108 metric
  rows, 90 guarded Diebold–Mariano comparisons, 72 model-stability rows, 36 target-revision
  summary rows, 216 horizon/NBER-regime diagnostic rows, and zero strict feature-timing
  violations.
- Sixty prespecified advanced-model candidate evaluations use only `vintage_aware`
  tuning blocks; 12 target/horizon/model settings are frozen before 108 untouched
  final-evaluation metric rows. Final-evaluation rows used for selection: **0**.
- Eight genuine CES sector matrices contribute construction, manufacturing, trade/
  transportation/utilities, information, financial activities, professional/business
  services, education/health services, and leisure/hospitality employment.
- The official BLS CPS series `LNS14000000` contributes 1,322 seasonally adjusted
  unemployment-rate vintage rows from 221 complete Employment Situation DOM exports;
  table A-1 coverage spans release dates 2008-02-01 through 2026-07-02. Printed embargo
  headers prove 220 exact clocks; the 2012-12-07 page's winter `EDT` label conflicts with
  `America/New_York` and remains explicitly date-only.
- A separate direct-text inventory preserves all 56 official Employment Situation TXT
  releases needed by the acquired CES target window from 2003-06-06 through 2008-01-04.
  Their printed weekday, date, 8:30 a.m. clock, and `EST`/`EDT` labels all verify; each
  original byte stream and SHA-256 is recorded in `release-index.json`.
- DOL contributes 1,235 hashed weekly news releases from 2002-10-17 through 2026-08-06,
  yielding 2,470 initial-claims vintage rows and 1,235 directly published four-week-average
  rows. All have exact 8:30 a.m. `America/New_York` availability timestamps.
- Federal Reserve G.17 contributes 367 dated ASCII releases from 1997-12-15 through
  2026-07-17: 343 monthly releases and 24 annual revisions. They produce 4,306 total-IP
  level rows and 4,306 directly published month-over-month percentage-change rows, with
  exact file-header clocks and six retained historical base periods.
- U.S. Treasury contributes 6,154 official daily 10-year CMT point observations from
  2002-01-02 through 2026-08-07. Every target/origin/mode feature has a complete 20-
  observation window. Because the XML feed has no exact publication clock, valid modes
  use conservative source-date New York EOD eligibility; no correction-vintage dimension
  is claimed.
- Census MARTS contributes 273 parsed advance retail releases covering reference months
  2003-01 through 2026-05. The 546 canonical rows retain the published seasonally adjusted
  level and directly published month-over-month change separately; eight scanned early
  PDFs without a machine-readable text layer remain explicit gaps rather than imputed data.
- Census NRC contributes 276 parsed housing-start releases covering reference months
  2003-01 through 2026-06. Six months remain explicit archive gaps, including the 2013
  federal-funding lapse; the official April 2009 `fhttps` index typo is repaired and logged.
- BEA NIPA contributes 23,416 `GDPC1` level vintages from 96 official initial-release
  Section 1 workbooks covering 2002Q3–2026Q2. The official directory has no initial-release
  workbook for 2002Q1 or 2002Q2, so both remain missing. The parallel
  `gdp_level_target_validation.parquet` contains 96 same-snapshot q/q SAAR values: 94 round
  exactly to the published tenth and all 96 are within 0.06 percentage point; the maximum
  difference is 0.0519308 point. Raw levels span six chained-dollar reference years and
  two scales, so cross-vintage raw-level revision comparisons are explicitly excluded.
- The deliberately naive mode admits 863 post-origin eligibility cells; strict as-of and
  fixed-mask modes admit none. Of the new total, 542 expose same-day Treasury observations
  before their conservative EOD availability.
- The official predictions carry ex-post NBER expansion/recession labels solely for
  evaluation. `metrics_by_regime_horizon.parquet` contains 216 descriptive rows; the
  labels are absent from model features. Horizon `0` is the target-release nowcast;
  horizon `1` is one native period ahead—one month for PAYEMS/core CPI and one quarter for
  GDP. Recession samples—especially two core-CPI months per horizon—remain too small for
  broad regime claims.
- Three latest-archive release updates use frozen Elastic Net models trained only on
  already released targets; exact contribution residuals are at most `7.11e-15`. Three
  guarded official-pilot briefs are generated under `official_pilot/policy_briefs/`.
- The 272 PAYEMS target events supported by consistent Employment Situation headers, all
  173 acquired CPI target snapshots, and all 98 GDP initial releases use an origin one
  second before the exact clock. Only the conflicting 2012-12-07 PAYEMS event retains the
  prior-New-York-day EOD rule. A persisted full date-only counterfactual moves those 543
  evidence-supported origins by 30,599.000001 seconds and finds zero changed feature
  values, feature selections, or target values for the current panel. This zero is
  measured, not assumed.
- The broader cross-agency indicator set is still incomplete because authorized historical
  consumer-sentiment releases are not yet included. Direct Treasury rates replace the
  invalid idea of relabeling post-2016 H.15 DDP current history, but they are daily point
  observations rather than successive correction vintages.

This is a real-data pilot, not the final broad-indicator nowcasting study. Its artifacts
remain Git-ignored and retain source hashes, release mappings, provenance, candidate
results, final-evaluation metrics, and hashes for all 22 report/data artifacts.

## Quick start

Python 3.12 or newer is required.

```bash
make setup RUNTIME_PYTHON=/path/to/python3.12
make acquire-dol-claims
make acquire-fed-g17
make acquire-census-retail
make acquire-census-housing
make index-empsit-clocks
make acquire-bea-nipa-levels
make audit-bea-nipa-levels
make audit-agency-vintages
make ingest-agency-vintages
make reproduce-official-pilot
make reproduce-multitarget
make test
make dashboard
```

`make reproduce-multitarget` uses `config/targets.toml` and writes the completed artifact
set, manifest, and `multitarget_report.md` under `data/generated/multitarget/`. After a
completed official and synthetic run, `make dashboard` exposes them as separate evidence
tiers, with the official archive pilot selected first. If neither completed manifest is
available, it falls back to the legacy payroll artifacts.

The three generated briefs are written under
`data/generated/multitarget/policy_briefs/` and the multi-target contribution tab selects
the matching release update for the chosen target.

The legacy payroll workflow and its individual stages remain available:

```bash
make reproduce-sample
make download-sample
make build-vintages
make validate-asof
make backtest
make policy-brief
make report
```

`make report` is the legacy payroll report command; the multi-target report is produced by
`make reproduce-multitarget`. Generated analytical artifacts are reproducible and ignored.
The compact source fixture under `data/fixtures/synthetic_payroll/` remains the versioned
offline input for the legacy workflow and contains no source-provider observations.

## Research design

The canonical vintage table records observation date, real-time interval, explicit
availability time, value, units, frequency, transformation, download time, and source
metadata. For an origin `t`, the as-of resolver selects at most one eligible vintage per
series and observation with `availability <= t`. Transformations occur only after
selection, and every derived feature and target retains auditable source-availability
lineage.

The revised-data counterfactual first fixes the cells eligible at the historical origin,
then substitutes their values at a common evaluation vintage. The availability mask stays
constant, so the comparison does not admit observations that were unavailable at the
origin. The separate `naive_latest_revised` benchmark uses the same fixed evaluation
vintage but does not hold that eligibility mask fixed; its post-origin first-availability
count is an intentional leakage diagnostic. The completed multi-target run reports zero
timing violations for strict modes and 893 intentionally leaked naive cells.

The research output includes [the technical report](reports/technical_report.md),
[vintage-leakage study](reports/vintage_leakage_study.md),
[model comparison](reports/model_comparison.md),
[sample policy brief](reports/sample_policy_brief.md), and
[methodology/limitations](reports/methodology_and_limitations.md). The generated
multi-target report is written to `data/generated/multitarget/multitarget_report.md`.

See [the project plan](docs/PROJECT_PLAN.md), [decision log](docs/DECISION_LOG.md),
[requirement audit](docs/ACCEPTANCE_AUDIT.md), [data-access policy](docs/DATA_ACCESS.md),
and [status](STATUS.md) for the implementation record.

## Live data, credentials, and authorization

The official pilot uses only downloaded public BLS/BEA/DOL/Federal Reserve/Census archive files;
it makes no live data API request. The local `api.txt` is ignored by Git, has filesystem
mode `0600`, and was not read or used. A credential's presence is not authorization to
call a provider or to persist its data.

The guarded FRED/ALFRED path remains disabled by default because current and older official
terms pages differ in ways material to persistent storage and model-development use. The
project makes no FRED request unless a separate explicit terms-authorization gate is
satisfied; the verified run records `fred_api_accessed = false`.

Original-provider BLS and BEA adapters are also fail-closed and use only their dedicated
environment variables. Their current-data APIs expose latest-revised observations, not a
historical as-of dimension, so API-current rows are always labeled `latest_revised` and
cannot be relabeled as first release. The user explicitly opted into acquiring official
archive evidence. The local audit verified BLS CES raw vintages, all CPI supplemental files
listed from 2012 through June 2026, BEA's 98-quarter GDP/GDI vintage summary, and 96 of 98
expected initial-release NIPA Section 1 workbooks. The two absent prearchive quarters,
2002Q1 and 2002Q2, remain explicit gaps. It also verifies 221 unique, complete BLS Employment
Situation DOM exports and both preformatted and structured table A-1 layouts. These are
recorded as browser-rendered DOM exports, not falsely represented as original HTTP response
bytes. The same audit verifies 367 original Federal Reserve G.17 ASCII snapshots, all with
unique hashes. It preserves one 2000 archive-path/header-date discrepancy and records three
2026 AM/PM header-zone interpretations as `America/New_York` continuity inferences. The
audit also verifies 281 Census MARTS reference-month entries: 273 parseable PDFs with
unique hashes and exact header clocks plus eight explicitly excluded scanned PDFs with no
text layer. Published retail levels and published monthly changes remain separate; the
monthly changes are not recomputed from rounded narrative levels. The
audit additionally verifies 278 Census NRC index entries, 276 parseable housing-start
releases with exact EST/EDT header clocks, two explicit 2013 funding-lapse exclusions, four
other months not separately listed by the official index, and the repaired April 2009
`fhttps` link typo. The
audit manifest is at
`data/generated/agency_vintages/audit_manifest.json`. Production parsing now writes frozen
Parquet plus DuckDB artifacts under `data/generated/official_vintages/`; the pilot writes
its separate artifact set under `data/generated/official_pilot/`. All acquired pre-2008
PAYEMS clocks are verified; the conflicting 2012 BLS header remains the target-timing
limitation. CPI
uses 221 audited official header clocks, including all 173 acquired target snapshots; its
evidence is a hashed browser-rendered header-text inventory rather than claimed original
server bytes, with one blank HTML page recovered from the corresponding official PDF. The
GDP target uses 98 audited BEA header clocks reconciled to every workbook initial release;
two BEA archive-list dates that are one day early remain explicit conflicts because the
page headers and vintage workbook agree on the following day. The configured level-derived
GDP path is validated for the 96 available same-snapshot quarters. The pilot continues to
use BEA's explicitly labeled published growth values as its stable benchmark, while
retaining the level-derived validation as a separate artifact. See
[Data Access](docs/DATA_ACCESS.md) for the exact findings, official links, attribution
requirements, and remaining gates. This is a project safeguard, not legal advice.

## Repository layout

```text
config/                  series, target, and run configuration
data/fixtures/           committed offline source fixtures
data/generated/          reproducible Parquet/DuckDB artifacts (ignored)
docs/                    plan, decision log, and data-access policy
portfolio/               interview and resume narratives
reports/                 required reports and generated sample output
src/macro_nowcast/       tested production package
tests/                   unit and end-to-end tests
```
