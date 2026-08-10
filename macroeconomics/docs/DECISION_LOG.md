# Decision Log

## 2026-08-07 — Start from an empty repository

**Context:** The `Macroeconomics` directory contained no files and was not itself initialized as a Git repository.

**Decision:** Build a conventional `src/`-layout Python project and keep all generated sample artifacts reproducible from committed source fixtures.

**Consequence:** There is no legacy behavior to preserve, but all architectural and empirical assumptions must be made explicit.

## 2026-08-07 — Fixture-first, never fixture-as-evidence

**Context:** `FRED_API_KEY` is unavailable in the execution environment and unit tests must not depend on credentials.

**Decision:** Implement live adapters but exercise the vertical slice with committed, deterministic FRED/ALFRED-shaped fixtures. All fixture-derived reports and metrics are labeled `synthetic_fixture`.

**Consequence:** The slice can validate information timing, model orchestration, and reproducibility. It cannot support claims about actual U.S. macroeconomic forecast performance.

## 2026-08-07 — Availability date is a first-class field

**Context:** A real-time period alone does not always capture a defensible release-timing convention.

**Decision:** Store both source real-time fields and an explicit `availability_date`. Eligibility is defined by `availability_date <= as_of_date`. When only dates are known, values become usable at end of the stated release date.

**Consequence:** Intraday pre/post-release experiments require timestamps and are not inferred from date-only data.

## 2026-08-07 — Separate vintage-aware and revised modes

**Context:** Leakage comparisons are only interpretable when data modes cannot be confused.

**Decision:** Carry every information-set mode explicitly into datasets, forecasts, metrics,
charts, briefs, and run manifests. `vintage_aware` is valid; fixed-mask and naive
latest-revised experiments are counterfactuals with distinct names.

**Consequence:** Latest-revised values may be used only in the named counterfactual backtest and never silently mixed into a real-time information set.

## 2026-08-07 — Vertical slice before breadth

**Context:** The complete specification spans three targets, many models, a dashboard, and extensive reporting.

**Decision:** First complete one monthly payroll-change pipeline with 5–10 predictors, an AR baseline, Elastic Net, expanding evaluation, revised-versus-vintage comparison, and a policy brief. Only then expand models and targets.

**Consequence:** Initial GDP/inflation coverage may be structural/configuration support rather than a fully sourced empirical backtest.

## 2026-08-07 — Disable live FRED ingestion pending terms clarification

**Context:** The current FRED services terms linked from the API documentation prohibit using FRED content in software or machine-learning development and prohibit storing, caching, archiving, or incorporating it into a database. An older official API-specific terms page does not contain the same language, creating an official-source inconsistency. The requested cache and model workflow therefore presents a licensing risk.

**Decision:** Implement and mock-test the schema-compatible adapter, but make live transport and persistent storage disabled by default behind explicit authorization controls. Do not call the API or commit API-derived content. Use synthetic fixtures or directly licensed original-provider data until written permission or clarification exists.

**Consequence:** This repository demonstrates the technical contract without claiming authorization to populate it from FRED/ALFRED. This is a conservative project safeguard, not a legal opinion.

## 2026-08-07 — Hold the eligibility mask fixed in the revised counterfactual

**Context:** A naive latest-data matrix can change both the vintage values and which observation periods appear, mixing revision leakage with release-timing leakage.

**Decision:** Determine eligible series/observation cells at each historical origin first, then substitute only their value at the fixed evaluation vintage. Carry the original eligibility timestamp and the counterfactual selected-vintage timestamp separately.

**Consequence:** The main comparison isolates value/target revision effects without admitting
future observation periods. The separately labeled naive latest-history backtest may expose
release-timing leakage but can never pass the strict real-time-information gate.

## 2026-08-07 — Define first-release payroll change from one post-release snapshot

**Context:** A payroll release can publish the current month and revise the prior month simultaneously. Subtracting two independently selected “first” levels would not reproduce the headline change known after the release.

**Decision:** For target month `t`, select both `PAYEMS[t]` and `PAYEMS[t-1]` from the same snapshot immediately after the initial `t` release, then subtract. The latest target uses both levels at one fixed evaluation cutoff.

**Consequence:** Target revision analysis cleanly distinguishes first-release forecast error from error against later economic history.

## 2026-08-07 — Use fixed, fold-local model settings for the sample

**Context:** Hyperparameter tuning on the final evaluation period would leak, while nested time-series tuning adds complexity that is unnecessary for the first engineering slice.

**Decision:** Use predeclared model settings for historical mean, no-change, AR(1), linear bridge, Elastic Net, and histogram gradient boosting. Refit each estimator and its preprocessing inside each expanding fold. Build intervals only from prior released out-of-sample residuals.

**Consequence:** The sample demonstrates valid orchestration and two advanced models without claiming optimal tuning. Directional accuracy is marked unavailable because all synthetic evaluation changes have the same sign.

## 2026-08-07 — Fix inflation and GDP target transformations by name

**Context:** Inflation and GDP growth are routinely reported using monthly, quarterly annualized, and year-over-year conventions. An unlabeled “percent change” would make results incomparable and invite accidental unit changes.

**Decision:** Define `core_cpi_pct_change_mom` from `CPILFESL` as `100 * (level[t] / level[t-1] - 1)`, a non-annualized month-over-month percent. Define `real_gdp_pct_change_qoq_saar` from `GDPC1` as `100 * ((level[q] / level[q-1]) ** 4 - 1)`, a quarter-over-quarter percent at a seasonally adjusted annual rate. Keep these target IDs, formulas, and units in configuration and output metadata.

**Consequence:** Core CPI is never silently multiplied by 12, and GDP SAAR is never mixed with unannualized quarterly or year-over-year growth. Any alternative transformation requires a distinct target ID and decision-log entry.

## 2026-08-07 — Anchor all target changes to one snapshot

**Context:** Initial CPI and GDP releases can revise the preceding period, just as payroll releases do. Computing growth from independently selected first-vintage levels would not reproduce the change visible in the initial release snapshot.

**Decision:** For each `first_release` target, take the current and preceding levels from the same earliest post-release snapshot containing both observations. Forecast at a configured origin strictly before that release: use the verified timestamp when available, otherwise end of the preceding calendar day under the date-only convention. For `latest_revised`, take both levels from one fixed evaluation snapshot whose cutoff is recorded before comparison outputs are built.

**Consequence:** First-release, fixed-latest, and forecast-origin semantics are comparable across payroll, core CPI, and real GDP. A target may be used for scoring after release but cannot enter a training fold before its release event.

## 2026-08-07 — Align frequencies by period and availability, not period alone

**Context:** GDP targets are quarterly while much of the information set is monthly, weekly, or daily. A completed-quarter aggregation assembled from data released later would leak through the ragged edge even if observation-period labels looked correct.

**Decision:** Assign observations to native calendar periods, then apply the forecast-origin availability filter before aggregation. Quarterly rows may use only released months and days, with partial-period coverage and staleness recorded. Monthly rows may carry a quarterly value only after that quarter's release. Configuration fixes whether each series is transformed before or after aggregation, and lineage retains every contributing vintage row.

**Consequence:** Partial quarters remain visibly partial, future months cannot enter GDP forecasts, and release lags override convenient calendar joins in both monthly-to-quarterly and quarterly-to-monthly alignment.

## 2026-08-07 — Keep continuation claims synthetic-only until source authorization

**Context:** The continuation can exercise CPI and GDP logic offline, but synthetic levels, revisions, and release calendars are not evidence about the U.S. economy.

**Decision:** Permit committed synthetic fixtures for target formulas, frequency alignment, as-of invariants, evaluation orchestration, and report-label tests. Propagate `synthetic_fixture` to all derivative artifacts. Do not make empirical claims about inflation, GDP, revisions, regimes, relative model performance, historical analogues, forecast accuracy, or policy from those outputs.

**Consequence:** Engineering can continue without credentials or network access while the boundary between demonstrated behavior and genuine-source empirical evidence remains explicit and machine-visible.

## 2026-08-07 — Treat a local credential as a secret, not as source authorization

**Context:** A local `api.txt` was supplied after the fixture slice. Reading it was unnecessary to continue the authorized work, and a syntactically valid key would not resolve the current FRED terms conflict or authorize persistent database/model use.

**Decision:** Add `api.txt`, `.env`, and `.env.*` to `.gitignore`; restrict `api.txt` to owner read/write permissions; do not read, log, copy, or call an API with its content. Keep live FRED transport disabled unless source authorization is separately documented.

**Consequence:** The secret remains outside artifacts, tests, configuration, manifests, and version control. The project progresses through synthetic fixtures and original-provider contracts without confusing credential possession with permission.

## 2026-08-07 — Split original-provider current APIs from historical archives

**Context:** Ordinary BLS and BEA API responses expose current revised history but do not provide the publication-vintage dimension needed for historical as-of reconstruction. Official CES, CPI, and GDP archives exist separately and have different coverage and layout risks.

**Decision:** Label every ordinary BLS/BEA API observation `latest_revised` with retrieval-time availability and no invented initial-release timestamp. Require separate terms authorization, operator opt-in, and a recorded coverage audit before an archive parser may run or assign `first_release`. Use BEA NIPA table `T10106`, line 1, for the real-GDP level input to the configured same-snapshot growth formula; keep already transformed `T10101` growth only as a cross-check and never annualize it again. See `docs/DATA_ACCESS.md` for official sources and notices.

**Consequence:** Current-data benchmarks and genuine vintage-aware experiments cannot be silently conflated. The adapter layer is usable offline and credential-redacted, while empirical archive ingestion remains deliberately disabled.

## 2026-08-07 — Evaluate each target on its native frequency and sample

**Context:** Payroll and core CPI supply monthly evaluation rows, while quarterly GDP has materially fewer origins. Pooling their errors or forcing identical statistical-test decisions would mix units, frequencies, and sample sizes.

**Decision:** Run the same six-model ladder and three labeled information modes separately
for each target, with target-specific expanding-window minimums and evaluation windows.
Carry target ID, formula, units, frequency, mode, and sample through predictions and
metrics. Keep GDP Diebold–Mariano comparisons invalid when the predeclared minimum
observation count is not met.

**Consequence:** The combined dashboard and report can compare workflow coverage without pretending cross-target RMSE values are commensurate or turning a 16-quarter synthetic sample into a model-superiority claim.

## 2026-08-08 — Materialize the naive revised-data benchmark as intentional leakage

**Context:** The required research datasets call for both a valid real-time backtest and a
naive revised-data backtest. The fixed-eligibility comparison is the better revision-value
counterfactual, but by design it cannot measure the additional error from admitting cells
that had not yet been released.

**Decision:** Add `naive_latest_revised` using values at the fixed evaluation vintage without
the historical eligibility mask. Retain each cell's first-availability and selected-vintage
timestamps, write a target/mode leakage audit, require zero future eligibility in strict
modes, and require a positive leaked-cell count in the naive mode.

**Consequence:** The full synthetic run measures 893 intentional post-origin eligibility
cells while both strict modes remain at zero. Naive metrics are an invalid-backtest
diagnostic, not evidence of attainable forecast performance.

## 2026-08-08 — Generate release attribution and a brief for every configured target

**Context:** A single payroll brief did not establish that the news/communication layer
worked for employment, inflation, and GDP with their different formulas and units.

**Decision:** For each configured target, locate one exact-timestamp synthetic pre-target
release that changes its feature vector, freeze an Elastic Net fitted only on earlier
vintage-aware rows, exactly decompose the before/after nowcast change, attach a prior-error
interval and a fixture-only historical scale comparison, and generate a target-specific
one-page brief.

**Consequence:** PAYEMS, CPILFESL, and GDPC1 each have a hashed news update and policy brief.
All three are mechanical synthetic demonstrations with explicit noncausal, nonpolicy, and
noninvestment guardrails.

## 2026-08-08 — Launch Streamlit through an external entry point

**Context:** Running the package's `dashboard.py` as a script placed
`src/macro_nowcast/` on `sys.path`, allowing the project module `calendar.py` to shadow
Python's standard-library `calendar` during pandas import.

**Decision:** Keep dashboard logic in the tested package but make Streamlit execute
`scripts/dashboard_entry.py`.

**Consequence:** `make dashboard` imports the installed package without standard-library
shadowing; the bare-mode smoke test reaches every completed multi-target tab successfully.

## 2026-08-09 — Separate official-file verification from production vintage readiness

**Context:** The user explicitly requested acquisition and verification of CES, CPI, and
GDP historical-vintage evidence. Official archives are public original-provider sources,
but a valid container and plausible values do not by themselves prove complete coverage or
the timestamp and revision type of every historical publication.

**Decision:** Acquire only from official BLS/BEA URLs, record hashes and source URLs, and
verify source-specific content offline. Prefer the valid CES raw CSV ZIP after the optional
XLSX download arrived incomplete. For CPI, acquire the full official listing from 2012
through June 2026, verify every modern XLSX core-CPI row, preserve the documented October
2025 gap, and temporarily convert all 35 legacy XLS workbooks to verify their core row
without claiming that production value extraction exists. For GDP, verify one dated
initial estimate in every quarter of the GDP/GDI workbook and verify all 1,053 numeric,
dated estimate/revision rows. Treat that workbook as a published-growth source rather than
a source of real-GDP levels; use archived NIPA 1.1.6 snapshots for level targets. Preserve
the BEA directory-label date
discrepancy and use the date/time supported by workbook metadata and the official release.
Normalize the official BLS news-release indexes to map all CES/CPI reference periods to
release dates, including the shared October/November 2025 CES release, while keeping exact
intraday verification as a separate gate. Keep `historical_ingestion_ready = false` until
target-compatible coverage, intraday timing, and parser fixtures pass.

**Consequence:** The repository now has reproducible evidence that the selected official
files contain the expected series and one exact GDP reconciliation, without converting a
partial content audit into an unsupported empirical-vintage claim. No API key or local
credential file was needed or used.

## 2026-08-09 — Enable a conservative official target-archive empirical pilot

**Context:** Production parsers now successfully expand the audited CES matrix, all 173
core-CPI snapshots including 35 legacy XLS files, and all 1,053 BEA published-growth rows.
The historical indexes prove release dates but not every intraday embargo instant. The BEA
workbook supplies already annualized growth rather than a complete set of NIPA levels.

**Decision:** Freeze the parsed rows in immutable-by-default Parquet with DuckDB views and
source hashes. For any release with date-only timing, set the forecast origin to the prior
calendar day at New York EOD. Preserve payroll and core-CPI level-derived targets; represent
BEA GDP as `official_published_value_already_transformed_no_retransformation`, mapped to the
configured `GDPC1` output identity but never described as level-derived. Run all six fixed
models across valid as-of, fixed-eligibility revised-value, and intentionally leaky naive
latest-revised modes. Limit predictors to lagged/cross-target CES, core-CPI, and GDP archive
values until genuine broader-indicator vintages are acquired.

**Consequence:** The repository now contains a genuine-data pilot with 250,409 canonical
source rows, 544 conservative origins, 7,686 out-of-sample predictions, and zero strict
feature-timing violations. Its findings are valid only within the declared target-archive
scope; exact intraday, broader-indicator, level-derived GDP, regime, and policy claims remain
out of scope.

## 2026-08-09 — Expand the official pilot with sectoral CES publication vintages

**Context:** The already acquired BLS `cesvinall.zip` contains official seasonally adjusted
publication-vintage matrices not only for total nonfarm employment but also for every CES
supersector and industries through the three-digit level. This is stronger historical
evidence than inserting current-history API values for unrelated indicators. The source
uses the same audited Employment Situation release mapping as PAYEMS.

**Decision:** Parse eight supersector matrices—construction, manufacturing, trade/
transportation/utilities, information, financial activities, professional/business
services, education/health services, and leisure/hospitality—using their official BLS
series identifiers. Retain all publication vintages but restrict these predictor reference
periods to 2002 onward for laptop-scale storage. Add target-appropriate sector changes to
the three official feature sets, always selecting the vintage before transformation. Keep
the pilot's target release calendar unchanged because sector rows are predictors from the
same Employment Situation events, not new target events.

**Consequence:** Official storage grows to 582,273 rows across 11 series and the feature
audit to 14,163 cells. All 7,686 expanding-window predictions are regenerated with zero
strict timing violations. The naive mode exposes 73 post-origin eligibility cells. Source
revision distributions, 36 model-stability rows, and 18 target-revision summaries are now
persisted. The project still does not claim that claims, production, retail, housing,
sentiment, or rates have historical-vintage coverage.

## 2026-08-09 — Generate official archive updates only at defensible date resolution

**Context:** The attribution and brief engines were proven on exact-timestamp fixtures, but
the official archive indexes establish historical release dates rather than every embargo
time. The official research datasets nevertheless provide enough released-target history
to fit a frozen model before the latest archived release for each target.

**Decision:** For PAYEMS, core CPI, and GDP, train one fixed Elastic Net using only targets
whose release timestamp is no later than the conservative pre-event origin. Compare the
next target period's feature vector at prior-New-York-day EOD and release-date EOD. Decompose
the nowcast change exactly in transformed feature space, estimate an 80% interval from
prior out-of-sample residuals, and generate a brief that labels the timing as date-only and
the accounting as predictive rather than causal.

**Consequence:** The official run now emits three updates and three briefs. The maximum
contribution-sum residual is `2.14e-14`. These outputs close the official pipeline's
release-to-communication loop without asserting exact intraday trading availability,
economic causality, investment conclusions, or monetary-policy recommendations.

## 2026-08-09 — Add CPS unemployment-rate publication snapshots without relabeling current history

**Context:** The official Employment Situation archive exposes table A-1 in two historical
HTML layouts: early releases use preformatted tables and later releases use structured
HTML. Both preserve the seasonally adjusted civilian unemployment rate and recent-month
history visible at that release. Command-line access is blocked by BLS, while the public
pages remain accessible in a normal browser.

**Decision:** Export the complete rendered DOM for every archive event that the official
index marks HTML-available, record this acquisition format explicitly, and never describe
it as the server's original response bytes. Require a one-to-one inventory, complete HTML,
table A-1 presence, and unique SHA-256 hashes. Parse both layouts to original-provider
series `LNS14000000`, preserve all visible seasonally adjusted monthly values as genuine
release vintages, and keep date-only timing. Add lagged/current/quarter-edge unemployment
features to PAYEMS, core-CPI, and GDP respectively; selection still precedes transformation.

**Consequence:** The audited inventory contains 221 releases from 2008-02-01 through
2026-07-02 and parses to 1,322 rows across 233 observation months. Official storage grows
to 583,595 rows across 12 series and the feature audit to 15,795 cells. Strict timing
violations remain zero; the intentionally naive mode now exposes 90 post-origin eligibility
cells. The official run still has 7,686 predictions, and exact release-update attribution
residuals remain at most `2.84e-14`. This strengthens the predictor panel with an
independent household survey but does not yet constitute a cross-agency panel.

## 2026-08-09 — Add DOL weekly claims from release documents, not revised history

**Context:** DOL's Employment and Training Administration exposes an official weekly news-
release archive beginning in October 2002. Each release identifies its 8:30 a.m. Eastern
embargo, the current advance seasonally adjusted initial-claims value, the prior week's
reported value, and the directly published four-week moving average. Current history alone
cannot reproduce these information sets because weekly seasonal-adjustment factors and
methods can change.

**Decision:** Enumerate the official year calendars, preserve every server response byte,
and require an immutable URL/hash inventory before parsing. Accept HTML, ASP, and PDF
layouts only when the current value, prior reported value, published four-week average,
reference week, arithmetic, and release date validate. Preserve `revised`, `unrevised`, and
source-unlabeled prior statuses instead of homogenizing them. Retain two byte-identical
cross-year aliases and one official dummy placeholder as explicit exclusions. Use the
directly published four-week average in all three official feature sets with exact
`08:30 America/New_York` availability, rather than approximating it from an incomplete
set of weekly revisions.

**Consequence:** The audit verifies 1,235 actual releases from 2002-10-17 through
2026-08-06: 105 HTML, 494 ASP, and 636 PDF files. They produce 2,470 weekly claims vintage
rows and 1,235 published-average rows. Official storage grows to 587,300 rows across 14
series, the release calendar to 1,779 events, and the feature audit to 17,427 cells. All
7,686 forecasts are regenerated with zero strict timing violations; the deliberately naive
mode now exposes 301 post-origin eligibility cells. The DOL source has exact intraday
availability, while BLS/BEA target origins remain conservative date-only events.

## 2026-08-09 — Reject current H.15 DDP history as a continuous publication-vintage source

**Context:** The Federal Reserve's H.15 archive exposes dated weekly release snapshots from
1997 through September 2016. From October 2016 onward, the public DDP download presents a
current historical series rather than a dated snapshot for each publication event.
Announcements and corrections do not reconstruct the missing sequence of information
sets.

**Decision:** Do not assign current DDP observations to historical post-2016 release dates
and do not combine the pre-2016 dated archive with current history under one `vintage_aware`
label. Retain H.15 as a documented rejected option until a continuous original-provider
snapshot source is found. Current values may only enter a separately labeled
`latest_revised` path.

**Consequence:** The official pilot does not yet contain a continuous interest-rate
vintage. This preserves the no-fabrication rule at the cost of leaving the rates predictor
pending.

## 2026-08-09 — Add Federal Reserve G.17 industrial-production release snapshots

**Context:** Unlike H.15, the Board's G.17 index provides dated ASCII release files from
December 1997 onward plus annual revision files. Historical releases print the release
clock and index base period. Because the index is periodically rebased, deriving a monthly
change across snapshots could mix incompatible bases; the release also directly publishes
the comparable month-over-month percentage change.

**Decision:** Acquire every dated monthly and annual-revision ASCII file, freeze its
official URL and SHA-256, parse the total-IP level and directly published monthly change as
separate canonical series, and carry the release-header clock through availability. Add
the published-change series to all three target feature sets only after as-of selection.
Preserve the 2000-02-15 path whose file header states 2000-02-16. For three 2026 headers
that print AM/PM instead of EST/EDT, use `America/New_York` as an explicit continuity
inference rather than claiming the zone label was printed.

**Consequence:** The audit verifies 367 releases—343 monthly and 24 annual revisions—with
367 unique hashes, six historical base periods, and 8,612 canonical rows. Official storage
grows to 595,912 rows across 16 series and 2,146 release events. The pilot feature audit
grows to 19,059 cells; all 7,686 forecasts are regenerated with zero strict timing
violations. The deliberately naive mode records 303 post-origin first-eligibility cells,
including two G.17 cells, while strict as-of and fixed-mask modes record none.

## 2026-08-09 — Add Census MARTS historical retail-release snapshots

**Context:** Census publishes a historical MARTS page whose PDFs preserve the advance
retail and food-services release as it appeared at publication time. The release narrative
prints a seasonally adjusted level rounded to one decimal billion dollars and separately
publishes the month-over-month percentage change. Recomputing the percentage from rounded
levels would not reproduce the published statistic. Eight early PDFs are scans without a
machine-readable text layer.

**Decision:** Enumerate one official PDF per reference month, freeze its URL, bytes, and
SHA-256, parse the printed header timestamp, and retain the published level and monthly
change as separate canonical series. Use the directly published change in all three target
feature sets after as-of selection. Interpret a header that prints only `ET` using
`America/New_York` while labeling that zone choice as inference. Preserve the eight
no-text PDFs as explicit exclusions; do not use OCR, interpolate, or substitute current
history without a separately audited decision.

**Consequence:** The audit enumerates 281 reference months, accepts 273 releases, and
produces 546 canonical rows from 2003-01 through 2026-05. Accepted release hashes and
canonical keys are unique; exact 8:30 a.m. clocks verify, with 20 `ET` zone inferences.
Official storage grows to 596,458 rows across 18 series and 2,419 release events. The pilot
feature audit grows to 20,691 cells; all 7,686 forecasts are regenerated with zero strict
timing violations. The deliberately naive mode records 309 post-origin first-eligibility
cells, while strict as-of and fixed-mask modes record none.

## 2026-08-09 — Add Census NRC housing starts from historical release PDFs

**Context:** Census's New Residential Construction historical page exposes dated report
PDFs with an exact Eastern release clock and the preliminary total privately-owned
housing-starts SAAR. The official index contains a literal `fhttps` typo for April 2009,
points the September 2013 entry at an October-titled file, and the October 2013 release
states that funding-lapse collection delays prevented housing-start publication. Several
later government-shutdown periods combine months rather than listing every reference month.

**Decision:** Freeze each official PDF and index snapshot with hashes, repair only the
single provable `fhttps` scheme typo while recording it, parse the headline preliminary
starts level into thousands of units SAAR, and carry the printed EST/EDT clock through
availability. Apply log changes only after as-of selection. Preserve six reference-month
gaps and explicitly exclude the two 2013 funding-lapse/link-mismatch entries; do not use
current revised HOUST history to fill them.

**Consequence:** The audit enumerates 278 releases, accepts 276 from 2003-01 through
2026-06, and produces 276 canonical rows with exact clocks and unique keys. Official
storage grows to 596,734 rows across 19 series and 2,695 release events. The pilot feature
audit grows to 22,323 cells; all 7,686 forecasts are regenerated with zero strict timing
violations. The deliberately naive mode records 321 post-origin first-eligibility cells,
while strict as-of and fixed-mask modes record none.

## 2026-08-09 — Use Employment Situation header clocks with an explicit conflict fallback

**Decision:** Parse the embargo header from every acquired Employment Situation DOM export.
Require its printed date and weekday to agree with the archive filename and require explicit
`EST`/`EDT` labels to agree with `America/New_York`; generic `ET` resolves through that named
zone. Use T−1 second for a target event only after those checks. Preserve the 2012-12-07
page as date-only because it prints `EDT` during standard time. Keep pre-2008 PAYEMS and all
current CPI/GDP target events date-only until equivalent original-page evidence is acquired.

**Consequence:** Of 221 acquired pages, 220 clocks verify and one conflict is retained. The
CES target window contains 216 exact PAYEMS events and 57 date-only PAYEMS events; combined
with 173 CPI and 98 GDP date-only events, the official pilot has 544 mixed-precision origins.
The exact PAYEMS origins are 30,599.000001 seconds later than the prior date-only origin. A
persisted 544-row counterfactual rebuild compares all 22,323 feature cells and 1,086 target
rows and finds zero value/selection changes for the current predictor panel. This observed
zero does not authorize treating intraday precision as irrelevant for future indicators.

## 2026-08-10 — Use audited CPI embargo-header clocks without overstating capture fidelity

**Context:** The official CPI archive exposes 221 historical release links from 2008-02-20
through 2026-07-14. BLS rejects the project's direct command-line retrieval, but the
in-application browser renders the official pages. Modern pages cannot be represented as
losslessly saved original response bytes through that route, and one historical HTML page
renders blank while its official PDF remains available.

**Decision:** Inventory every link from the official CPI archive index and persist only the
embargo-header text, official URL/label, evidence format, and a hash of each header. Require
the printed date, optional weekday, and explicit `EST`/`EDT` offset to agree with
`America/New_York`; resolve generic `ET` through that named zone. Use the official PDF header
for the single blank HTML page. Fail closed on index/hash drift or incomplete coverage. Mark
the artifact as neither complete DOM capture nor original server bytes.

**Consequence:** All 221 clocks verify—49 `EST`, 101 `EDT`, and 71 `ET`—and all 173 acquired
CPI target snapshots now use T−1-second origins. Combined with 216 exact PAYEMS origins, the
pilot has 389 exact and 155 date-only target events. The rebuilt 544-row timing
counterfactual moves all 389 exact origins by 30,599.000001 seconds but changes zero of
22,323 feature value/selection cells and zero of 1,086 target values in the current panel.
GDP, pre-2008 PAYEMS, and the retained 2012 PAYEMS source conflict remain date-only.

## 2026-08-10 — Use all 98 BEA GDP initial-release page clocks and retain index conflicts

**Context:** The GDP/GDI vintage workbook contains 98 quarterly initial releases from
2002Q1 through 2026Q2: 96 labeled `Advance` and two shutdown-affected releases labeled
`Initial`. BEA's news archive exposes the corresponding pages, but its list labels the
2009Q3 and 2018Q3 pages one day earlier than both their page headers and the workbook.
Historical pages also use three different header phrases.

**Decision:** Inventory the 91 relevant initial pages from the 2002–2024 year filters and
the seven 2025–2026 pages from the current archive/home page. Persist the official URL,
archive-list date, page title, release-header text, header hash, and capture limitations.
Require every header's date, weekday, `EST`/`EDT` label, and 8:30 a.m. time to verify against
`America/New_York`, and reconcile every date and `Advance`/`Initial` type to the vintage
workbook. Preserve the two archive-list conflicts rather than normalizing them silently;
use the following-day page-header/workbook date because those independent sources agree.

**Consequence:** All 98 initial clocks verify—70 `EDT`, 28 `EST`; four wire-transmission,
one embargoed-for-release, and 93 embargoed-until-release headers. GDP now joins 216 PAYEMS
and 173 CPI exact events, producing 487 exact and 57 date-only origins. The rebuilt 544-row
counterfactual moves every exact origin by 30,599.000001 seconds but changes zero of 22,323
feature value/selection cells and zero of 1,086 target values. Full NIPA level-vintage
coverage remains a separate requirement; exact clocks do not turn the published-growth
pilot into a level-derived `GDPC1` study.

## 2026-08-10 — Use NBER chronology only as ex-post evaluation metadata

**Context:** The official pilot previously wrote `not_preclassified` for every prediction,
so its production artifacts could not satisfy the requested performance-by-economic-regime
evaluation. NBER's official chronology, last updated 2023-03-14 and rechecked for this run,
identifies December 2007/June 2009 and February 2020/April 2020 as the relevant peak/trough
pairs. NBER assigns the peak month to expansion and the trough month to recession.

**Decision:** Label target periods `nber_expansion` or `nber_recession` only after forecast
generation, persist the source and definition with every grouped metric, and set
`regime_is_forecast_input = false`. Monthly periods follow NBER's month convention;
quarterly periods follow its published peak/trough quarters. Do not tune, filter, or train
on these labels.

**Consequence:** The initial implementation wrote 108 grouped rows across three targets,
three information modes, six models, horizon `0`, and two NBER states. The feature matrix
has no regime column. The subsequent multi-horizon decision below doubles the grouped
contract while preserving this ex-post-only rule.

## 2026-08-10 — Separate target-release nowcasts from one-native-period-ahead forecasts

**Context:** A single horizon label exercises grouping code but cannot satisfy a substantive
performance-by-forecast-horizon comparison. Duplicating a target under a new label would be
invalid; the target period itself must move while the historical origin and its information
set remain fixed.

**Decision:** For each official target release origin, retain horizon `0` for the target
being released and construct horizon `1` by shifting the realized target one native period:
one month for PAYEMS/core CPI and one quarter for GDP. Reuse the exact same as-of feature
vector at that origin, join the genuinely later target realization, and require its release
timestamp to follow the origin. Train, rank, calculate intervals, revision effects, and run
DM diagnostics separately by horizon. Use DM HAC lag `0`/`1` for horizons `0`/`1`, persist
the lag, and train official news updates on horizon `1` examples.

**Consequence:** The run now contains 3,249 research rows and 15,264 OOS forecasts, with
108 main metric rows, 216 NBER regime/horizon rows, 90 DM rows, 72 model-stability rows, and
36 target-revision summaries. There are no future targets at origins, duplicate prediction
keys, decreasing training counts, or strict feature-timing violations. The underlying
22,323 information-set feature cells and 321 deliberately naive leaked cells are unchanged.

## 2026-08-10 — Tune advanced models before an untouched final evaluation block

**Context:** Leaving advanced-model hyperparameters fixed does not exercise a production
selection path, while selecting settings on the final evaluation block would contaminate
the reported holdout results. Selecting settings independently for revised-data modes would
also make their comparison with the vintage-aware mode less interpretable.

**Decision:** Prespecify six Elastic Net and four histogram-gradient-boosting candidates
per target and horizon. Select one setting for each advanced model using only
`vintage_aware` tuning-validation forecasts, then freeze that setting across all three
information modes. Reserve 24 tuning and 24 final months for PAYEMS/core CPI, and eight
tuning and eight final quarters for GDP. Keep the final block out of selection; use it for
the primary final metrics, DM diagnostics, and stability ranks.

**Consequence:** Sixty candidate rows select 12 frozen target/horizon/model settings, and
108 final-evaluation metric rows have zero overlap with hyperparameter selection. The run
now hashes 22 report/data artifacts. Official horizon-1 news updates use the selected
Elastic Net setting for their target, and persist that setting with the attribution.

## 2026-08-10 — Use direct Treasury daily rates and gate Michigan sentiment

**Context:** The Federal Reserve H.15 dated-release archive ends in 2016, while the current
DDP history does not preserve post-2016 publication snapshots. Treasury provides official
year-specific daily par-yield feeds. The University of Michigan public-data FAQ permits use
with citation, but its usage agreement also restricts reproduction and redistribution
without express written consent.

**Decision:** Acquire the Treasury 10-year par-yield XML feeds for 2002–2026 directly from
the original provider, freeze and hash the raw files, and assign each observation a
conservative New York end-of-day availability time. Use a trailing 20-observation mean in
all three official target panels. Do not claim an exact publication clock, a publication-
vintage dimension, or later-correction history. Keep Michigan sentiment ingestion disabled
until written permission explicitly covers the organization, intended analysis, storage,
and publication scope.

**Consequence:** The official source panel grows by 6,154 rate observations to 602,888 rows
across 20 series, and the official feature audit grows to 23,955 cells. Strict as-of and
fixed-mask modes still have zero future-information violations; the intentionally naive
mode has 863, including 542 same-day Treasury cells before conservative end-of-day
availability. Michigan sentiment remains an external authorization milestone rather than
an inferred permission.

## 2026-08-10 — Complete PAYEMS target clocks with official BLS text archives

**Context:** The CES vintage window began with 56 Employment Situation events from
2003-06-06 through 2008-01-04 whose target origins still used a date-only convention. The
official BLS Employment Situation archive exposes original TXT and PDF releases for those
dates, and every release header prints its embargo weekday, date, time, and `EST` or `EDT`
label. Automated command-line retrieval was denied by BLS, while the ordinary visible
archive links remained available through browser download.

**Decision:** Download exactly the 56 official TXT files linked by the visible BLS archive,
preserve their original bytes, URLs, sizes, encodings, and SHA-256 hashes, and index them
offline without a network request. Parse the printed header with strict weekday/date/time/
zone validation against `America/New_York`; do not infer a clock from a filename. Retain
the existing 2012-12-07 HTML release as date-only because its printed `EDT` label conflicts
with New York standard time. Visually cross-check the first, middle, and final portions of
the TXT interval against representative official PDFs.

**Consequence:** Employment Situation evidence now contains 276 exact clocks—56 direct TXT
files plus 220 browser-rendered HTML headers. The acquired target calendar uses exact
T−1-second origins for 272 PAYEMS, 173 CPI, and 98 GDP events, or 543 of 544 events; only
the documented 2012 conflict remains date-only. Rebuilding the full date-only
counterfactual changes all 543 supported origins by 30,599.000001 seconds and changes zero
of 23,955 feature values/selections and zero of 1,086 target values in the current panel.

## 2026-08-10 — Acquire NIPA levels but separate same-snapshot growth from raw revisions

**Context:** The published GDP/GDI vintage-history workbook contains 98 initial q/q SAAR
growth estimates but not the two real-GDP levels required by the configured `GDPC1`
formula. BEA's official historical-data directory exposes release-specific Section 1
workbooks in several XLS/XLSX layouts. Earlier URL probing incorrectly treated 2014Q3 as
missing because the archive path is lowercase; enumerating the official directory rather
than guessing filenames resolves it. The directory genuinely has no initial-release
workbook for 2002Q1 or 2002Q2.

**Decision:** Enumerate official release directories and direct-child file lists, preserve
the original workbook bytes and inventory hashes, and acquire the 96 available initial
Section 1 snapshots for 2002Q3–2026Q2. Convert 60 legacy XLS files only in isolated
temporary LibreOffice profiles; parse 36 XLSX files directly. Reconcile workbook metadata
to the separately verified release clocks and published growth. Compute q/q SAAR only from
adjacent levels in the same snapshot. Never impute the two gaps, use current API history,
or compare raw levels across snapshots: the archive spans chained-dollar reference years
1996, 2000, 2005, 2009, 2012, and 2017 and uses both billions and millions scales.
Keep BEA's directly published initial growth as the primary empirical target: it is the
authoritative released statistic, covers two additional quarters, and is not subject to
reconstruction error from rounded published levels. Do not add a duplicate level-derived
model tier without a separately prespecified sensitivity question.

**Consequence:** The archive audit passes with `verified_with_archive_gaps`: 96/98
snapshots, 23,416 canonical `GDPC1` level rows, 96 exact clocks, 31 preserved directory-date
conflicts, and complete target/prior level pairs. Ninety-four calculated growth values
round exactly to BEA's published tenth; all 96 are within 0.06 percentage point, with a
maximum difference of 0.0519308 caused by published-level rounding. Official ingestion
grows to 626,304 rows across 21 series and 2,791 release events and writes a 96-row
`gdp_level_target_validation.parquet`. The existing empirical pilot keeps published growth
as its stable target; level-derived targets remain a parallel validation layer rather than
an open acceptance requirement, and
`GDPC1` raw levels are excluded from cross-vintage revision summaries.
