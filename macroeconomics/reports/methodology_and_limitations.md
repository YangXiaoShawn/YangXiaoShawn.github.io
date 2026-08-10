# Methodology and Limitations

> **TWO EVIDENCE TIERS.** The multi-target fixture validates software only and supports no
> empirical claim. A separate official BLS/BEA target-archive pilot supports narrowly
> scoped historical forecast diagnostics, but not broad-indicator model superiority,
> robust business-cycle-regime, investment, or policy conclusions.

## Targets and transformations

The completed workflow defines three targets without mixing their frequencies, scales, or
annualization conventions:

| Series | Target definition | Formula |
| --- | --- | --- |
| `PAYEMS` | Monthly nonfarm payroll change, thousands of persons | `current_level - prior_level` |
| `CPILFESL` | Monthly core-CPI percent change, explicitly nonannualized | `100 * (current_level / prior_level - 1)` |
| `GDPC1` | Quarterly real-GDP percent change at a seasonally adjusted annual rate | `100 * ((current_level / prior_level) ** 4 - 1)` |

Each realized growth target selects the current and prior levels from the same source
snapshot. The first-release realization uses the explicit synthetic release snapshot; the
fixed-latest realization uses one configured evaluation cutoff. This avoids combining a
current-period first release with a later revision of its prior-period denominator.

For the official pilot, BEA's vintage workbook supplies already annualized q/q SAAR growth
rather than a complete sequence of real-GDP levels. The pilot uses the explicit formula
`official_published_value_already_transformed_no_retransformation`; its value is not
annualized again and its level fields remain null.

The original payroll-only workflow remains available unchanged for the sample policy brief,
release attribution, and legacy reports.

## Vintage selection and leakage controls

Real-time intervals and explicit availability timestamps are separate fields. A date-only
external source would be available under the conservative end-of-day rule documented in
configuration; the synthetic fixture carries exact UTC timestamps. Missing or retracted
latest rows remain missing and do not resurrect an earlier vintage.

At each origin, the as-of resolver admits only source rows with availability at or before
that origin and selects no more than one eligible vintage per observation. Transformations
run only after vintage selection. Feature lineage records the latest contributing
observation and maximum source-availability timestamp. Target lineage records both source
levels, the target release, and the maximum source availability.

The latest-revised counterfactual first freezes the historical eligibility mask and then
substitutes values from the fixed evaluation vintage. It therefore measures a revised-value
counterfactual without silently adding future observations.

The separately labeled `naive_latest_revised` benchmark deliberately skips the historical
eligibility mask. It is expected to admit observation cells first published after the
origin and is never called a valid real-time information set. This makes release-timing
leakage measurable rather than conflating it with later value revisions.

The verified multi-target run contains 5,766 feature cells and 450 target rows. The valid
as-of and fixed-mask eligibility audits report **zero violations**; the naive benchmark
records 893 post-origin first-availability cells by design. Independent hash and DuckDB
queries and the reproducibility integration test agree. This validates the implemented
timing invariants on the fixture, not the accuracy of any untested external timestamp.

## Mixed frequencies and ragged edges

Weekly and daily features aggregate only observations released by the origin. Monthly
indicators can be stale because publication lags differ. Quarterly GDP origins retain
target-specific monthly, weekly, daily, and quarterly coverage/staleness diagnostics rather
than pretending all inputs share a period end. The GDP target uses exact fourth-power
compounding from adjacent quarterly real-GDP levels; already annualized published growth
must not be annualized again.

## Forecast evaluation

Training feature rows preserve their own historical origins, and training targets must
have been released by the test origin. Expanding windows are monotone, preprocessing is
fold-local, interval residuals use strictly prior out-of-sample errors, and the final
evaluation block is not used for tuning.

The completed artifact set contains:

- 5,558 canonical vintage rows across 12 synthetic series.
- 228 target-specific pre-release forecast origins, comprising 98 payroll, 98 core-CPI, and 32 real-GDP origins.
- 47 evaluation months each for PAYEMS and CPILFESL and 16 evaluation quarters for GDPC1.
- 1,980 forecasts across six models and three explicitly labeled information modes:
  846 payroll, 846 core-CPI, and 288 real-GDP forecasts.
- 54 metric rows and 36 target/model stability comparisons across revised-data modes.

The smaller quarterly sample is reported directly. Statistical comparisons that fail
sample-size or variance checks remain invalid. Cross-target metric magnitudes are not
directly comparable, and this report makes no model-ranking claim.

## Official target-archive pilot

The official source layer uses 626,304 canonical rows: 247,115 total-nonfarm CES rows,
331,864 rows across eight sectoral CES series, 1,322 CPS unemployment-rate rows, 2,470 DOL
weekly initial-claims vintage rows, 1,235 directly published DOL four-week averages, 2,241
core-CPI rows, 1,053 BEA published-growth rows, and 8,612 Fed G.17 total-industrial-
production level/change rows, 6,154 U.S. Treasury daily 10-year CMT point observations,
546 Census MARTS retail level/change rows, 276 Census NRC housing-start rows, and 23,416
BEA NIPA `GDPC1` level rows. It
constructs 544 mixed-precision origins, 23,955 feature cells, 1,086
first-release/fixed-latest targets, 3,249 horizon-specific research rows, and 15,264
expanding-window forecasts across the same six-model ladder, three information modes, and
two horizons. Horizon `0` is the target-release nowcast; horizon `1` is one month ahead for
PAYEMS/core CPI and one quarter ahead for GDP. Every future target release follows its
forecast origin. The strict as-of
feature audit reports zero future-information violations.

Advanced-model selection is target- and horizon-specific but information-mode neutral.
Six Elastic Net and four histogram-gradient-boosting candidates per target/horizon produce
60 tuning rows. Only `vintage_aware` tuning-validation forecasts select the 12 frozen
settings; the same setting is then applied to all three information modes. Monthly targets
reserve 24 tuning months and 24 untouched final months; GDP reserves eight tuning quarters
and eight untouched final quarters. The final block contributes zero rows to selection.
`metrics.parquet` remains all-OOS descriptive, while `final_evaluation_metrics.parquet`,
DM diagnostics, and stability ranks use the untouched block.

The official prediction artifact also carries ex-post NBER expansion/recession labels and
the run persists 216 grouped regime/horizon diagnostic rows. The chronology is verified
against NBER's official peak/trough table and is never included in model features. The
recession samples are 16/14 PAYEMS months, 2/2 core-CPI months, and 8/8 GDP quarters for
horizons `0`/`1`, respectively, so these cuts are descriptive rather than evidence of
regime-specific superiority.

Predictors combine own lags, cross-target values, eight genuine sector-employment
publication-vintage matrices, genuine CPS unemployment-rate release snapshots, and exact-
time DOL four-week claims averages, exact-clock G.17 published monthly IP changes,
conservative-EOD Treasury 10-year 20-observation means, and exact-clock MARTS directly
published monthly retail changes and NRC housing starts. This
remains a narrower cross-agency information set than
the synthetic 12-series design. It proves
that genuine vintage selection and revision counterfactuals execute on original-provider
archives. It now estimates with a continuous Treasury-rate predictor, but the rate rows are
point-in-time market observations rather than a correction-vintage archive. It does not
estimate the value of sentiment because written source permission and historical release
snapshots are absent. Eight early MARTS scanned PDFs and six
NRC reference-month gaps (including the 2013 funding-lapse pair) remain missing rather than
receiving later revised values.

The official artifacts also persist 20 source-series revision summaries, 36 horizon-specific
target-revision error summaries, and 72 model-stability comparisons. A source row's “first” value
means the first vintage present in the acquired archive; for reference periods predating
the archive's publication window, it is not claimed to be the original historical release.
The 20-series revision panel deliberately excludes raw `GDPC1` levels: their 96 release
snapshots span six chained-dollar reference years and both billions and millions scales.
They instead support a separate 96-row same-snapshot q/q SAAR validation, with 2002Q1/Q2
retained as missing and all calculated values within 0.06 percentage point of published
growth.

Employment Situation evidence establishes 276 exact historical clocks: 56 direct official
TXT releases and 220 browser-rendered HTML headers. Within the acquired CES target window,
272 PAYEMS events use T−1-second origins; only the conflicting 2012-12-07 EST/EDT header
remains date-only. A separate 221-event CPI clock
inventory supplies exact origins for all 173 acquired CPI snapshots. A separate 98-event
BEA inventory supplies exact origins for every GDP initial release in the workbook. A
date-only target release is forecast from the previous calendar day at New York EOD. The
persisted 544-row timing counterfactual rebuilds all feature and target panels: the 543
origin changes alter zero feature values/selections and zero target values in the current
panel. DOL claims uses
its verified 8:30 a.m. New York availability timestamp; G.17 preserves each
release file's header clock; MARTS and NRC preserve their Eastern header clocks. One G.17
path/header date mismatch, three G.17 New York zone-label inferences, and 20 MARTS `ET`
zone-label inferences remain explicit rather than normalized away; NRC separately records
one official `fhttps` link repair.

## Attribution and reporting

For each configured target, the multi-target pipeline finds one exact-timestamp synthetic
release that changes the pre-release feature vector, fits one frozen Elastic Net on prior
vintage-aware rows, and exactly decomposes the resulting prediction change into
coefficient-times-feature changes. Each update records prior-residual uncertainty and a
fixture-only comparison against consecutive historical out-of-sample nowcast movements.
One target-specific policy brief is generated for PAYEMS, CPILFESL, and GDPC1. None of this
is causal attribution or an empirical historical analogue. Tree-based replacements remain
order-dependent and are labeled approximate.

The official evidence tier now performs the same frozen-linear accounting on the latest
archived PAYEMS, core-CPI, and GDP events. Each model trains only on targets released before
the event; the before snapshot is prior-New-York-day EOD and the after snapshot is release-
date EOD. The three contribution sums reproduce their nowcast changes to within `7.11e-15`.
Their generated briefs remain scoped pilot evidence because some sources retain date-level
timing and the wider cross-agency vintage panel is incomplete.

Run the multi-target artifacts, generated comparison/limitations report, and dashboard
with:

```bash
make reproduce-multitarget
make dashboard
```

The first command writes the completion manifest,
`data/generated/multitarget/multitarget_report.md`, `news_updates.json`, and three briefs
under `data/generated/multitarget/policy_briefs/`. The dashboard uses that directory only
when the manifest has status `complete` and stage `multitarget_backtest_complete`; otherwise
it falls back to the legacy payroll artifacts. The external Streamlit entry script avoids
shadowing Python's standard-library `calendar` module. The legacy payroll report commands
remain `make reproduce-sample`, `make policy-brief`, and `make report`.

## Data access, credentials, and legal limits

The official pilot uses downloaded public BLS/BEA archive files but makes no API call. The
local `api.txt` is ignored by Git, has filesystem mode `0600`, and was not read or used;
the manifests record `api_txt_read = false`. A credential is not authorization to call a
provider, accept its terms, or persist its data.

The FRED/ALFRED transport remains disabled behind an explicit terms gate because current
and older official terms pages differ in ways material to persistent storage and
model-development use. The verified manifest records no FRED access.

The original-provider BLS and BEA current APIs return current/latest-revised observations
and do not provide a complete historical as-of dimension. Their API-current rows are
therefore locked to `latest_revised`; they cannot be called first release. Historical BLS
CES/CPI and BEA GDP archives have different coverage, revisions, formats, and release
mapping requirements. Archive ingestion is enabled only for the audited target-archive
scope after source review, operator opt-in, coverage/layout checks, and offline parser
fixtures. See [Data Access](../docs/DATA_ACCESS.md) for the
official source links, rate limits, attribution/disclaimer requirements, series/table IDs,
and archive boundaries. This is a research safeguard, not legal advice.

## Statistical and interpretation limitations

The deterministic fixtures cannot estimate real forecast accuracy. The official pilot can
estimate accuracy and revision effects only for its target-archive information set and
declared mixed exact/date-only timing convention. It does not establish broader-indicator rankings,
robust business-cycle regime performance beyond the declared `0`/`1` horizons, fully tuned interval calibration, source reliability,
release-delay behavior, or policy effects. Extending those claims requires genuine vintages
for the broader predictors, horizons and samples beyond the delivered design, and separately
verified release timing where available.
The NIPA level validation does not by itself establish a separately modeled level-derived
GDP result; that tier requires a prespecified 96-quarter design and must preserve the
published-growth benchmark as a cross-check.
