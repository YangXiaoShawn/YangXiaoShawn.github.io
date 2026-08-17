# Project plan

## Research question

When the United States imposes product-level tariffs, who bears the cost, how
quickly do importers reallocate sourcing across countries, and how do those
shocks propagate through domestic production networks?

## Milestones

| ID | Milestone | Depends on | Status |
|---|---|---|---|
| M0 | Repository, environment, data-layer discipline, provenance stamping | — | **done** |
| M1 | Tariff policy engine + Section 301 schedule from Federal Register | M0 | **done** |
| M2 | HS concordance engine (stable-code and weighted samples) | M0 | **built, not wired in** — `concordance/hs.py` and `stable_code_sample()` are imported by nothing in the pipeline; code revisions are handled instead by per-year Census concordance vintages (D-044). See the gap note below the table. |
| M3 | Trade adapter + product×country×month analytical panel | M1, M2 | **done** — official Census HS10×country×month, 2017-01..2020-02, 923,440 rows |
| M4 | Data-quality battery | M3 | **done** |
| M5 | Descriptive analysis + replication benchmark | M3 | **done** — T1 exact; T2 and T3 executed conceptually with estimates; T4 needs M10 |
| M6 | Incidence estimation: model ladder, event studies, PPML, placebos | M3 | **done** |
| M7 | Diversion decomposition incl. counterfactual adjustment | M3 | **done** |
| M8 | Industry exposure via BEA input-output | M3 | **done** — official Census concordance, BEA summary and detail levels (D-043) |
| M9 | Domestic price outcomes (BLS PPI) | M8 | **done at summary level** — 22 clusters, a power result not a null (D-041); the detail-level run at ~125 clusters is pending a BLS quota window |
| M10 | Structural Armington/CES counterfactuals | M6, M7, official data | **done, one tier** (D-054) — sourcing nest across foreign sources; no domestic nest and no welfare, both stated as scope rather than omission |
| M11 | Current-data extension past 2019-08 | List 4A parser | **done** — List 4A parsed, window runs to 2020-02 |
| M12 | Dashboard | M6, M7, M8 | **basic version done** |
| M13 | Portfolio deliverables | M6–M8 | **done** |

## Critical path

The binding constraint is a **Census API key**. M3-official unblocks M5, M9, M10
and turns every `MIXED` artefact into `OFFICIAL`. Nothing else on the list is
close to as valuable.

Second-order: a **List 4A parser** unblocks M11 and extends the usable window by
roughly two years.

### Open gap: M2 is built but not connected

`concordance/hs.py` (the HS concordance engine) and `panel/build.stable_code_sample()`
are imported by nothing outside their own tests. Nothing in the pipeline calls
either. Two consequences, stated rather than left for a reader to discover:

* **Acceptance criterion 3** is credited to a module the pipeline does not run.
  Code revisions *are* handled, but by a different mechanism — per-year Census
  concordance vintages, including the 2012-to-2017 NAICS repair in D-044 — and
  the criterion should point there.
* **The product-reclassification risk is unmitigated.** Its listed mitigation was
  this engine. In the current panel 800 ten-digit codes first appear after the
  window opens and 596 stop before it closes, together 5.7% of customs value.
  Some of that is a product genuinely not imported in a month and some is a code
  renumbered mid-window; nothing separates the two, so a renumbering shows up as
  treated-product exit plus control-product entry, which is the exact pattern the
  diversion decomposition reads as an extensive-margin move.

The window is 2017-01 to 2020-02, entirely inside HS2017, so no *international*
HS revision falls in it. The churn is in the U.S. 10-digit statistical numbers,
which are revised annually. Closing this means either wiring the engine in with a
real correlation table, or restricting the estimation sample to codes present
throughout and reporting how much value that drops.

## Acceptance tests

Mapped to the acceptance criteria in the brief. Each is checked by a test, a
generated artefact, or both.

| # | Criterion | How it is checked | Status |
|---|---|---|---|
| 1 | New user can reproduce a small end-to-end run from the README | `make reproduce-sample` | pass |
| 2 | Tariff engine passes tests for dates, rates, exclusions | `tests/test_tariff_engine.py` (21 tests) | pass |
| 3 | HS-code version changes handled explicitly | `concordance/hs.py`; 7 tests | pass |
| 4 | Sample workflow produces a product-country-month panel | `data/analytical/trade_panel.parquet` | pass |
| 5 | Quantity-unit inconsistencies detected | `test_quantity_unit_change_is_detected` | pass |
| 6 | Customs and tariff-inclusive unit values separately labelled | `test_unit_value_concepts_are_separately_labelled_and_ordered` | pass |
| 7 | At least one descriptive replication target attempted | `reports/replication_comparison.md` (statutory coverage) | pass |
| 8 | At least one event-study specification estimated | 6 estimated (3 outcomes × 2 reference periods) | pass |
| 9 | At least one PPML trade-flow specification estimated | 4 estimated | pass |
| 10 | Pre-treatment trends and placebo tests reported | `reports/tariff_incidence_results.md` | pass |
| 11 | China contraction separated from third-country expansion | `econ/diversion.py`; never netted | pass |
| 12 | Direct protection and imported-input exposure separately measured | `reports/supply_chain_propagation.md` | pass |
| 13 | Structural outputs labelled model-implied | `ParameterType` on every row; data moments, estimates, calibrated parameters and model outputs separated in `structural_counterfactuals.md` | pass |
| 14 | Reports generated from code | `scripts/generate_reports.py`; reports carry a do-not-edit notice | pass |
| 15 | Every result records data period, configuration, Git commit | `RunStamp` on every result table | pass |
| 16 | Failed or unstable hypotheses documented | `reports/failed_hypotheses.md` | pass |
| 17 | No unsupported welfare or causal claim | `guard_language` fails the build | pass |

## Risks

### Data-access risks

| Risk | Severity | Status | Mitigation |
|---|---|---|---|
| Census API key required | **critical** | realised | Adapter implemented and key-gated; synthetic generator keeps the pipeline testable; every artefact tagged (D-009) |
| Census returns HTTP 200 with an HTML error body | high | realised | Payload-shape validation, not status-code checking |
| Census HS→NAICS concordance 404/403 | medium | **resolved** | The resource existed; the URL guesses were wrong (D-037) and the `.xls` vintages needed `xlrd` (D-039). Official concordance in use; chapter map is a labelled fallback |
| BLS PPI API in maintenance | medium | **resolved; rate limit realised** | Adapter implemented (D-040). The live constraint is the v1 daily request allowance, mitigated by a per-series-per-year cache |
| USITC HTS serves current vintage only | medium | realised | Documented vintage mismatch (D-010) |
| Federal Register annexes are image-based in XML | medium | realised | Parse the GPO typeset PDF instead |
| Source revisions change a published number | medium | mitigated | Raw bytes cached with checksums; manifests record vintage |

### Identification risks

| Risk | Why it matters | Current handling |
|---|---|---|
| Policy endogeneity | Lists chosen partly on expected domestic impact | Documented; not solved. No instrument claimed |
| Anticipation / front-running | Effective dates known in advance; contaminates event month −1 | Two reference periods (D-014); announcement dates carried separately |
| Concurrent policy (Section 232, retaliation) | Overlaps the window | Documented; chapter-level exposure to Section 232 not yet excluded |
| Exchange-rate movements | RMB depreciation moves customs unit values the same way exporter absorption does | Documented; not separated |
| Transshipment / origin misdeclaration | Third-country gains are not evidence of relocation | Stated in every diversion output |
| Product reclassification | Appears as treated exit plus control entry | **Not mitigated.** `concordance/hs.py` and `stable_code_sample()` are unused by the pipeline. 800 codes enter and 596 leave mid-window, 5.7% of customs value combined; genuine trade entry is not separated from renumbering |
| Exclusions absent from the schedule | Estimates are intention-to-treat, not treatment-on-the-treated | Stated everywhere; engine supports exclusion records |
| Partial HS6 coverage | Assigning a scalar rate would mismeasure treatment | Engine returns `PARTIAL_HS6_COVERAGE`; those headings leave both groups |
| Dominant treated supplier | Common time effects absorb part of the shock | Observed in ground-truth recovery; documented in `failed_hypotheses.md` |

### Computational risks

| Risk | Handling |
|---|---|
| Product-country-month panel exceeds 16 GB | Partitioned Parquet, per-month files, Polars lazy scans; nothing requires the full raw dataset in memory |
| HDFE dummy expansion | Alternating projections; memory is O(n), not O(n × groups) |
| Census rate limits | Incremental month-by-month fetch, on-disk cache, `max_api_calls` in config |
| 14 MB annex PDFs re-parsed each run | Raw cache keyed by document number and checksum |
| PPML non-convergence / separation | Convergence flag and separation check surfaced on every fit, never hidden |

## Next actions, in priority order

1. Obtain a Census API key and re-run `make reproduce-sample`. Everything else is
   secondary.
2. Write the List 4A 10-digit annex parser; extend the window to 2020+.
3. Parse product exclusions into `EXCLUSION` records; report exclusion-adjusted
   and unadjusted estimates side by side.
4. Replace the coarse IO concordance with an official HS→NAICS→BEA mapping.
5. Add the BLS PPI adapter for domestic price outcomes (M9).
6. Only then, the structural module (M10).
