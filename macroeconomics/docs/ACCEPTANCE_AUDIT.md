# Requirement-by-Requirement Acceptance Audit

**Audit date:** 2026-08-10

**Verified runs:** synthetic multi-target acceptance plus official target-archive pilot

**Artifact stages:** `multitarget_backtest_complete`, `official_archive_empirical_pilot_complete`

**Evidence classes:** deterministic `synthetic_fixture`; scoped `official_agency_archive`

## Scope conclusion

The software and synthetic acceptance scope is complete: the three configured targets run
from canonical vintage rows through historical information sets, three separately labeled
data modes, six models, expanding-window evaluation, revision/stability analysis, release
attribution, per-target briefs, Parquet/DuckDB artifacts, reports, and the dashboard.

The official pilot now answers a broader but still scoped version of the empirical question
using genuine CES, core-CPI, and published GDP target archives plus eight sectoral CES
employment vintage predictors, CPS unemployment-rate release snapshots, and DOL weekly
claims releases, Fed G.17 industrial-production release snapshots, and Census MARTS
retail-sales plus Census NRC housing-start releases, together with official Treasury
10-year daily par-yield observations. It
does not answer the broad-indicator question represented by the synthetic configuration.
Live FRED remains disabled and ordinary BLS/BEA APIs remain latest-revised only. Broad
ranking, robust regime, historical-analogue, and policy claims remain gated on genuine vintages
for the wider predictor set and a prespecified empirical design.

## Required components A–J

| Requirement | Status | Verifiable implementation/evidence |
| --- | --- | --- |
| A. Data-source adapters | Complete for declared archives; live use gated | Typed adapters, fixtures, retry/throttle/redaction, guarded BLS/BEA current paths, and production CES/CPI/GDP-growth/NIPA-level, Employment Situation A-1, DOL claims, Fed G.17, Census MARTS, and Census NRC archive parsers. Canonical rows retain all requested timing, value, metadata, download, and provenance fields. |
| B. Vintage-aware model | Complete | `select_as_of`, fixed-mask latest substitution, intentionally naive latest selection, mixed-frequency feature construction, null-vintage rules, lineage, and strict future-information tests. |
| C. Release calendar | Complete with one declared source conflict | Exact synthetic calendars plus official mixed-precision mappings. Two hundred seventy-two PAYEMS, 173 CPI, and 98 GDP target events use T−1-second origins from verified release headers; only the conflicting 2012-12-07 PAYEMS event uses previous-New-York-day EOD. The 544-row target-clock counterfactual is persisted. |
| D. Research datasets | Complete for fixture and official pilot | `vintage_aware/first_release`, fixed-mask revised-value, and deliberately invalid naive latest datasets remain separate in all official-pilot artifacts. |
| E. Model ladder | Complete | Historical mean, no-change, AR(1), linear bridge, Elastic Net, and deterministic histogram gradient boosting. |
| F. Real-time evaluation | Complete for horizons `0` and `1`; farther horizons remain | Expanding windows, fold-local preprocessing, release-aware targets, 108 all-OOS descriptive rows, 108 untouched final-evaluation rows, 90 final-block DM diagnostics with persisted HAC lags, and 216 official ex-post NBER regime/horizon rows. Sixty candidate rows select 12 frozen settings with zero final rows; NBER labels never enter features. |
| G. Revision analysis | Complete on fixture and declared official pilot | Official pilot persists comparable source/target revision distributions, 72 horizon-specific stability rows, valid/fixed-mask/naive modes, and 863 intentional naive post-origin eligibility cells. NIPA raw levels are deliberately excluded because reference-year and scale changes make cross-snapshot level differences invalid; their same-snapshot growth validation is separate. |
| H. News and attribution | Complete on fixture and scoped official pilot | Both tiers persist previous/updated nowcasts, exact frozen-linear contributions, prior-residual uncertainty, historical scale comparisons, and guarded interpretation. Official models train only on targets released before the event; maximum official residual is `7.11e-15`. |
| I. Policy brief generator | Complete on fixture and scoped official pilot | Three target-specific briefs per tier state the release, information change, assessment, uncertainty, risks, comparison limits, and evidence that would change the conclusion. Official briefs explicitly reject causal, investment, and monetary-policy interpretation. |
| J. Dashboard | Complete for synthetic and official evidence tiers | The UI detects completed official and synthetic artifacts separately, defaults to the official tier, and retains explicit evidence-scope banners. |

## Acceptance criteria

| # | Criterion | Evidence |
| ---: | --- | --- |
| 1 | Arbitrary historical as-of reconstruction | Public `select_as_of`/feature builders accept timezone-aware arbitrary origins; unit and integration tests cover historical snapshots. |
| 2 | Tests prevent future releases | Strict as-of and fixed-mask first-eligibility violations are both zero; tests fail on future information or ambiguous timestamps. |
| 3 | Revised and vintage backtests separately labeled | Three explicit modes appear in every combined artifact and the manifest; the naive mode is labeled invalid. |
| 4 | Two simple and two advanced models | Four transparent baselines plus Elastic Net and histogram gradient boosting. |
| 5 | Reproducible rolling evaluation | Expanding folds, fixed settings/seeds, deterministic hashes, 1,980 OOS forecasts, and 54 metric rows. |
| 6 | Revision effects measured | Raw/target revisions, rank changes, mean absolute prediction differences, target-revision error effects, and leakage-cell counts are persisted. |
| 7 | Policy brief from outputs | Three hashed briefs are generated from `news_updates.json` and recorded in the manifest. |
| 8 | Chart context recorded | Dashboard titles/captions include series or release series, target/formula, fixture/mode or vintage, horizon, and displayed sample. |
| 9 | Missing credentials do not break tests | Full offline suite passes without any live source access; manifests record all source APIs as unused. |
| 10 | Synthetic results labeled | Manifest, Parquet provenance, JSON, reports, briefs, dashboard banner, and portfolio documentation all state `synthetic_fixture` and no empirical findings. |

## Verified artifact counts

- 12 series and 5,558 canonical vintage rows.
- 228 pre-release origins: 98 PAYEMS, 98 CPILFESL, and 32 GDPC1.
- 5,766 audited feature cells and 450 target rows.
- 1,980 OOS forecasts: 846 PAYEMS, 846 CPILFESL, and 288 GDPC1.
- Six models, 54 metric rows, and 36 stability rows.
- Zero strict-mode future-eligibility violations; 893 intentional naive-mode leaked cells.
- 5,558 all-series release events with both `initial` and `revision` labels.
- Three exact news updates and three policy briefs.
- 24 manifest-hashed artifacts with no independent SHA-256 mismatch.

Official pilot:

- 626,304 canonical official rows across 21 series and 544 mixed-precision forecast origins.
- 23,955 feature cells, 1,086 target rows, and 3,249 horizon-specific research rows.
- 15,264 OOS forecasts, six models, 108 metric rows, 216 ex-post NBER regime/horizon rows,
  and 90 guarded DM rows.
- Sixty tuning-candidate rows, 12 frozen selections, 108 untouched final-evaluation metric
  rows, and zero final-evaluation rows used for selection.
- Twenty source-revision summary rows, 36 target-revision summary rows, and 72 model-
  stability rows.
- Zero strict feature-timing violations; 863 intentional naive first-eligibility leaks.
- Five hundred forty-three origins change relative to the prior all-date-only target convention;
  the full rebuild finds zero changed feature values/selections and zero changed target values
  for this panel.
- G.17 contributes 367 exact-clock release events and 8,612 canonical rows; all keys and
  release hashes are unique. The audit retains one archive-path/header-date discrepancy
  and three explicitly labeled New York zone inferences.
- Treasury contributes 6,154 daily 10-year CMT point observations and 1,632 complete
  20-observation feature windows. Strict/fixed-mask Treasury leakage is zero; the naive
  mode exposes 542 same-day observations before conservative New York EOD availability.
- MARTS contributes 273 exact-clock release events and 546 canonical rows; all accepted
  hashes and keys are unique. Eight early scanned PDFs without a text layer remain explicit
  gaps, and 20 `ET` labels remain explicit New York zone inferences.
- NRC contributes 276 exact-clock housing-start events/rows. Six months remain explicit
  gaps, including two 2013 funding-lapse exclusions; one official `fhttps` link typo is
  repaired and logged.
- NIPA contributes 23,416 `GDPC1` level vintages from 96 initial-release workbooks and 96
  exact clocks. The separate target-validation artifact uses same-snapshot adjacent levels;
  94 values round exactly to published growth and all 96 are within 0.06 percentage point.
  The absent 2002Q1/Q2 workbooks remain missing and raw cross-vintage level comparisons are
  excluded.
- Twenty-two hashed pilot artifacts, including the target-clock precision audit, ex-post
  NBER grouped metrics, tuning candidates, final-evaluation metrics, three briefs,
  and `news_updates.json`, plus the
  ingestion Parquet/DuckDB artifacts.

## Commands verified

```text
make reproduce-multitarget
make acquire-dol-claims
make acquire-fed-g17
make acquire-treasury-rates
make acquire-census-retail
make acquire-census-housing
make index-empsit-clocks
make acquire-bea-nipa-levels
make audit-bea-nipa-levels
make ingest-agency-vintages
make reproduce-official-pilot
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check .
.venv/bin/python scripts/dashboard_entry.py
.venv/bin/python -m streamlit run scripts/dashboard_entry.py --server.headless true --server.port 8765
make -n dashboard
```

The full suite passed 215 tests with one non-failing joblib CPU-detection
warning. The actual Streamlit server reached its ready state through the external entry
point and was then stopped normally.

## Remaining empirical milestones

1. Obtain express written permission for University of Michigan historical sentiment
   releases, then complete their coverage audit. Eight CES sector series, CPS unemployment,
   DOL claims, Fed G.17, Treasury 10-year daily observations, Census retail, and housing are
   complete. Treasury rows retain a no-correction-vintage limitation; current H.15 DDP
   history is not relabeled as dated snapshots.
2. Add horizons beyond the implemented target-release nowcast/one-native-period-ahead pair;
   retain the delivered prespecified tuning/final holdout, keep NBER chronology ex-post,
   and expand recession samples before drawing regime conclusions.
3. Extend official updates as new authorized cross-agency vintages arrive; the local Git
   root baseline is complete and excludes raw/generated evidence and credentials.

The NIPA acquisition/model-choice milestone is closed: 96 available level snapshots are
verified as a reconstruction sensitivity, while directly published initial growth remains
the authoritative pilot target. A parallel model tier would require a new prespecified
question rather than being added as a redundant acceptance exercise.
