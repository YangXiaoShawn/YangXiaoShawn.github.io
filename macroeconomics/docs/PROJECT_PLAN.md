# Project Plan

## Objective

Build a local, reproducible real-time macro nowcasting and policy-shock engine that answers: how well could employment, inflation, and GDP have been forecast using only information released by each historical forecast date, and how much apparent performance disappears when revised-data leakage is removed?

## Research contract

Every model input is resolved against an explicit forecast origin. A vintage-aware row is
eligible only when its availability date is on or before that origin. Latest-revised
experiments use separate modes and labels: one holds the historical eligibility mask fixed,
while the deliberately naive benchmark records the future cells it admits. Fixtures validate
the machinery but do not support claims about historical economic performance.

## Current delivery status (2026-08-10)

Phases 0–4 remain complete for the synthetic payroll vertical slice, and the synthetic
portion of Phase 5 is complete. The configuration-driven continuation builds 5,558
canonical vintages across 12 series, 228 target-specific pre-release origins, 5,766 audited
feature cells, 450 first/fixed-latest target rows, and 1,980 expanding-window predictions
for `PAYEMS`, `CPILFESL`, and `GDPC1`. Parquet, DuckDB, three information modes, 36
cross-vintage stability rows, a target-selectable dashboard, three release updates, three
policy briefs, and a multi-target limitations report all carry `synthetic_fixture`; all
215 tests and the full reproduction report zero strict-mode timing violations. The intentionally
invalid naive benchmark separately records 893 post-origin first-availability cells.

The broad-indicator empirical portion of Phase 5 remains gated. A local credential file is
permission-restricted and ignored, but its content was not read or used because a key is
not source authorization and current FRED terms remain incompatible with the requested
persistent modeling workflow absent clarification. Official BLS CES/CPI and BEA GDP
archive evidence has now been acquired, content-verified, and parsed with hashes and identifiers.
This includes the official CPI inventory from 2012 through June 2026, all 98 initial-growth
rows and all 1,053 dated estimate/revision rows in BEA's GDP/GDI vintage history, complete
CES/CPI release-date mapping, and 96 same-snapshot GDP formula/release cross-checks from
23,416 NIPA level vintages. Ordinary agency APIs remain `latest_revised`. The production
archive path now freezes 626,304 canonical rows across 21 official series. Eight BLS CES
sector-employment vintage matrices,
1,322 BLS CPS unemployment-rate vintage rows, 2,470 DOL weekly-claims vintages, and 1,235
published DOL four-week averages join 8,612 Federal Reserve G.17 total-industrial-
production level/change vintages, 6,154 U.S. Treasury daily 10-year CMT point observations,
546 Census MARTS retail level/change releases, 276 Census
NRC housing-start releases, and the three target archives in a mixed-timing pilot with
23,955 feature cells, 3,249 horizon-specific research rows, 15,264 predictions,
72 stability comparisons, 216 ex-post NBER regime/horizon diagnostic rows, and zero strict
feature-timing violations. Employment Situation evidence proves 276 exact clocks—56 direct
official TXT releases plus 220 browser-rendered HTML headers—and 272 PAYEMS target events
inside the CES window use T−1-second origins. A separate CPI evidence
inventory verifies 221 official clocks and supplies exact origins for all 173 acquired CPI
target snapshots. A 98-page BEA inventory likewise supplies exact origins for every GDP
initial release in the workbook. Only one conflicting 2012 BLS header retains the
conservative date-only rule. A persisted full counterfactual finds no feature-selection/
value or target-value changes for the current panel after moving all 543 evidence-supported
origins. Authorized historical sentiment releases remain pending; direct Treasury rates are
included with conservative EOD availability but no correction-vintage claim, so empirical
claims stay limited to this expanded official pilot. G.17, MARTS, and NRC retain their
separately verified exact predictor clocks. NBER labels are post-hoc evaluation metadata,
not estimator inputs. The pilot now separates the target-release nowcast from one native
period ahead. Sixty vintage-aware tuning-candidate rows select 12 frozen advanced-model
settings before an untouched 108-row final-evaluation metric panel; selection uses zero
final rows. Small recession samples remain a limitation.

## Vertical slice (first delivery)

The first end-to-end slice uses a configurable monthly payroll-change target and a small predictor panel. It includes:

1. Canonical FRED/ALFRED-style fixture rows with multiple vintages and publication lags.
2. A release calendar and strict arbitrary-date as-of resolver.
3. Monthly feature/target construction with ragged edges and explicit transformations.
4. Historical mean, no-change, autoregression, bridge/OLS, Elastic Net, and a tree ensemble when dependencies permit.
5. Deterministic expanding-window backtests in `vintage_aware` and `latest_revised` modes.
6. RMSE, MAE, bias, directional accuracy, interval coverage, regime/horizon summaries, and a guarded Diebold-Mariano-style comparison.
7. Revision statistics, forecast-update attribution, and a generated one-page policy brief.
8. Parquet/DuckDB artifacts, a local dashboard, and fully labeled reports.

## Continuation target contract

Targets remain configuration-driven and must carry a stable target ID, source series, native frequency, formula, units, seasonal-adjustment status, release event, forecast origin, target vintage rule, and evaluation-vintage cutoff. Similar-sounding transformations are not interchangeable.

| Target ID | Source | Definition | Reported unit |
| --- | --- | --- | --- |
| `payems_change_mom_thousands` | `PAYEMS` | `level[t] - level[t-1]`, using the two levels from one snapshot | Thousands of persons, month-over-month change |
| `core_cpi_pct_change_mom` | `CPILFESL` | `100 * (level[t] / level[t-1] - 1)`, using the two levels from one snapshot | Percent, month over month, **not annualized** |
| `real_gdp_pct_change_qoq_saar` | `GDPC1` | `100 * ((level[q] / level[q-1]) ** 4 - 1)`, using the two levels from one snapshot | Percent, quarter over quarter at a seasonally adjusted annual rate |

The GDP power-of-four annualization is part of the target definition. It must not be confused with an unannualized quarterly percent change, year-over-year growth, or a percent change in an already transformed growth series. Core CPI likewise remains a simple non-annualized one-month percent change and is not multiplied by 12.

The official archive contains 96 of 98 expected initial-release `GDPC1` level snapshots
from 2002Q3 through 2026Q2. The absent 2002Q1/Q2 workbooks remain missing. A separate
96-row validation uses both adjacent levels from one snapshot and reconciles every result
within 0.06 percentage point of BEA's published growth. The stable official pilot still
maps BEA's published growth archive to the `GDPC1` output identity with the explicit formula
`official_published_value_already_transformed_no_retransformation`; it does not silently
substitute the new level-derived series. Raw level comparisons across reference-year
definitions are prohibited.

### Forecast origins and target vintages

- Each forecast is made at a configured pre-release origin for the target's initial release event. With a verified timestamp, the origin must be strictly earlier than that timestamp. With only a release date, the conservative origin is end of the preceding calendar day in `America/New_York`; same-day pre-release availability is not inferred.
- A feature is eligible only when `availability_date <= forecast_origin`. Target values used later for scoring are never eligible as training outcomes until their own release event has occurred.
- A `first_release` target uses the earliest recorded post-release snapshot for period `t` or quarter `q` that contains both the newly released level and the preceding-period level. Both levels come from that exact snapshot, so any concurrent revision to the preceding period is reflected in the reported first-release change. Independently selected first vintages must not be subtracted.
- A `latest_revised` target uses both adjacent levels from one fixed, configured evaluation snapshot. The evaluation cutoff is recorded in run metadata and held constant across every origin and model in a comparison; “latest at execution time” is not a reproducible target definition.
- The existing eligibility mask is held fixed when comparing vintage-aware and latest-revised values. The latest-revised counterfactual changes values, not which observation periods were knowable at an origin.
- A second `naive_latest_revised` benchmark intentionally uses every cell present at the fixed evaluation vintage, even when its first availability follows the historical origin. Its leaked-cell count must be nonzero and explicit; it is never accepted by the strict real-time gate.

### Monthly and quarterly alignment

- Observation period, availability date, and forecast origin remain separate fields. Period membership alone never makes a value available.
- Monthly targets use monthly features available by their pre-release origin. A quarterly predictor may be carried only from the latest quarter actually released by that origin, with its age/coverage recorded; it is never backfilled from a later release.
- Quarterly GDP rows align monthly observations to the quarter-ending month only after the origin-availability filter. The current `latest` feature specs use the most recent released month, while the audit still carries observed-month count, three-month coverage ratio, and staleness. Any future period aggregation must likewise use only months released by the GDP forecast origin. Missing future months are never filled with subsequently released values.
- Weekly and daily inputs are aggregated only through the origin cutoff. Any period-to-date statistic is labeled as such and cannot be presented as a complete-month or complete-quarter value.
- Series configuration declares whether transformation occurs before or after temporal aggregation. The pipeline may not silently change that order across modes or folds.
- All alignments retain source-period and selected-vintage lineage so tests can assert that every contributing row was available by the origin.

### Claim boundary during continuation

Core CPI and GDP configuration, transformation, alignment, and leakage tests may be
developed with committed synthetic fixtures, which retain the `synthetic_fixture` label
and cannot support empirical claims. The separate official pilot may support only scoped
descriptive accuracy/revision findings from its BLS/BEA target archives and conservative
mixed exact/date-only timing. Ex-post NBER group diagnostics are permitted only with their
small-sample warning. Broader model, regime, analogue, and policy language remains gated on
genuine vintages for the broader predictor set and a separately prespecified design.

## Phases and gates

### Phase 0 — Repository contract

- Create persistent instructions, this plan, a decision log, and status tracking.
- Gate: the empirical-integrity rules and fixture limitations are explicit.

### Phase 1 — Data foundation

- Add typed configuration and canonical schemas.
- Implement cached FRED and ALFRED observation adapters with an optional API key.
- Commit a compact deterministic fixture panel with 5–10 predictors, release dates, and selected revisions.
- Persist canonical tables to Parquet and register them in DuckDB.
- Gate: offline tests pass and every row has provenance.

### Phase 2 — Information-set reconstruction

- Implement release-calendar semantics and `as_of(date, mode)` resolution.
- Handle multiple vintages, missing releases, transformations, mixed frequency, and ragged edges.
- Gate: tests prove no post-origin availability can enter any vintage-aware feature matrix.

### Phase 3 — Forecasting and evaluation

- Implement the transparent baseline ladder before advanced models.
- Run expanding-window forecasts with fixed, predeclared model settings.
- Produce mode-separated metrics and revision/leakage comparisons.
- Gate: a reproducible sample backtest runs from raw fixtures to labeled outputs.

### Phase 4 — Communication layer

- Implement defensible exact/approximate attribution labeling.
- Generate one target-specific release brief for each configured target plus the
  technical/research reports.
- Add the local dashboard for vintages, revisions, nowcasts, metrics, calendar, and health.
- Gate: all outputs carry target, mode, horizon, vintage convention, and sample labels.

### Phase 5 — Empirical expansion

- Obtain written permission for historical University of Michigan sentiment, then acquire
  and coverage-audit preliminary/final releases without weakening the existing as-of
  invariant.
- Maintain the completed 2003–2008 direct-TXT PAYEMS clock inventory and the audited BEA
  NIPA level inventory. Keep published initial growth as the primary target; use the
  96-quarter level reconstruction as validation only unless a new sensitivity question is
  prespecified. Retain 2002Q1/Q2 as missing.
- Extend beyond horizons `0`/`1` and enlarge regime/calibration samples while preserving
  prespecified tuning and the untouched final evaluation block.
- Add richer MIDAS/factor/shrinkage models only when a justified empirical design requires
  them; the required simple/advanced model ladder is already complete.
- Maintain the completed local Git root baseline. Raw archives, generated empirical
  artifacts, temporary audit files, and credentials remain excluded; only authorized
  genuine-source results may be described as empirical findings.

**Current gate status:** synthetic acceptance passes. Official archive parsing, freezing,
mixed exact/date-only origins, target construction, eight sectoral CES predictors and
CPS unemployment-rate release snapshots, DOL weekly initial-claims releases and exact
8:30 a.m. Eastern availability,
revision/stability analysis, a six-model empirical pilot, three exact official release
updates/briefs, ex-post NBER evaluation groups, and a separate official dashboard tier also
pass. Treasury 10-year daily point observations are included with a conservative end-of-day
timing rule and an explicit no-correction-vintage limitation. The 96-quarter NIPA level
validation also passes, with two documented prearchive gaps and no unsupported raw-level
revision comparisons. The published-growth target choice is closed for the current pilot.
Remaining authorized sentiment history,
horizons beyond `0`/`1`, larger-sample calibration/regime work, and broad empirical
interpretation remain open.

## Verification strategy

- Unit tests: schema validation, adapter parsing, transformation semantics, release selection, ragged edges, model interfaces, metrics, and report labeling.
- Invariant/property tests: selected rows always satisfy `availability_date <= as_of_date`; feature lineage also satisfies the invariant.
- Integration test: run the complete fixture reproduction in a temporary directory.
- Smoke tests: CLI commands, DuckDB queries, generated brief/report, and dashboard import.
- Reproducibility: fixed seeds, stable row ordering, serialized run metadata, and configuration hashes.

## Resource strategy

The project targets a 16 GB laptop. It uses small partitioned Parquet files, predicate-pushed DuckDB queries, bounded caches, and CPU-only estimators. Downloads are cached and explicit; unit tests never require network access.
