# Decision log

Every non-obvious choice, why it was made, and what it costs. Entries are
append-only; superseded entries are marked, not deleted.

---

### D-001 — Anchor annex parsing on the operative legal sentence

**Decision.** Section 301 product lists are extracted by locating the sentence
*"Heading 9903.88.0X applies to all products of China that are classified in the
following 8-digit subheadings"* and reading the code grid that follows, rather
than by page ranges or by parsing the descriptive annex.

**Why.** That sentence is what imposes the duty. The descriptive annex in the
same notice states that its product descriptions "are provided for informational
purposes only, and are not intended to delimit in any way the scope of the
action". Parsing the informational annex would extract a list the notice itself
disclaims. The Chapter 99 heading in the anchor also identifies the action, so
the action id is read out of the document rather than assumed.

**Cost.** List 4 notices (84 FR 43304) use a different construction and
enumerate 10-digit statistical lines, so this parser raises on them rather than
producing a wrong answer. See D-008.

---

### D-002 — Validate parsed line counts against the count each notice states

**Decision.** After parsing, compare the number of lines found against the count
the notice states in its own preamble ("5,745 full and partial tariff
subheadings"). Mismatches are recorded on the parse result and propagate into the
dataset manifest.

**Why.** Validating against a number the author supplies from memory validates
the memory, not the parser. The notice's own count is an independent check
present in the source.

**Outcome.** All three parsed lists reconcile exactly: List 1 = 818, List 2 =
279, List 3 = 5,745 (5,734 full + 11 partial). Reaching that required D-003,
D-004 and D-005.

---

### D-003 — Exclude Chapter 98 and 99 codes from product lists

**Decision.** Codes in chapters 98 and 99 found inside an annex are recorded as
`special_provision_codes`, not as covered products.

**Why.** 9802.00.80 (articles assembled abroad from U.S. components) and
9903.88.0X (the Section 301 headings themselves) appear in the legal text as
provisions, not as targeted products. Including them overstated List 2 by one
line (280 vs the stated 279).

---

### D-004 — Parse partial statutory lines as first-class records

**Decision.** U.S. note 20(g) to subchapter III of chapter 99 (heading
9903.88.04) covers 11 HS8 lines *except* for named 10-digit statistical
reporting numbers. These are parsed into records with `partial_line=True` and
the carved-out statistical numbers recorded in `partial_line_note`.

**Why.** They are what the notice means by "full and **partial** tariff
subheadings". Without them List 3 parses to 5,734 against a stated 5,745. More
importantly, marking a partially covered line as fully treated introduces
measurement error directly into the treatment variable.

**Cost.** The engine returns `PARTIAL_LINE` for these, which is deliberately not
usable as a scalar treatment, so they leave the main estimation sample.

---

### D-005 — Never repair a truncated code by guessing; resolve it only by deduction

**Decision.** In 83 FR 28710 one code renders as `9033.00`, its final pair lost
in typesetting. The parser reports it as `unresolved_codes` and omits it. A
separate resolver consults the USITC HTS and resolves it **only** when exactly
one 8-digit line under that heading is not already claimed. The resolved record
is marked `Confidence.DERIVED`, not `OFFICIAL_PARSED`.

**Why.** Filling in `.90` because it "looks right" is fabrication. Deducing it
from the HTS, where 9033.00.20 and 9033.00.30 are already in the list and
9033.00.90 is the only other line under the heading, is an argument from an
official source that a reader can check.

**Cost.** Ambiguous truncations stay unresolved and are reported as a known
undercount.

---

### D-006 — Whitespace repair inside codes is allowed; digit invention is not

**Decision.** `_normalize_page` rejoins `9401. 71.0007` into `9401.71.0007`.

**Why.** Joining across whitespace adds no digits — it recovers a code the
source contains. The pattern requires a full 4-digit heading before the break
and 2+2 or 2+4 digits after, so ordinary sentence punctuation ("in 2018. 5,745
lines") cannot match. There is a regression test for exactly that case.

---

### D-007 — Announcement dates are set to the proposal, not the final notice

**Decision.** For List 2, the announcement date is 2018-06-20 (the proposal in
83 FR 28710 Annex C), not 2018-08-16 (the final notice). For List 3 it is
2018-07-17 (83 FR 33608). Effective dates are always the date duties were
collected.

**Why.** Anticipation and front-running respond to the first public signal.
Setting announcement equal to the final notice would understate the anticipation
window by weeks. Setting effective equal to announcement would misplace the cost
shock by months — for the List 3 rate increase, by more than seven, since it was
announced for 2019-01-01, postponed twice, and took effect 2019-05-10.

---

### D-008 — Restrict the vertical slice to Lists 1–3 and end the window 2019-08

**Decision.** List 4A (effective 2019-09-01) is not parsed. The sample window
ends 2019-08.

**Why.** List 4A covers most remaining consumer goods. Running past its
effective date without parsing it would place genuinely treated products in the
never-treated control group, which biases every estimate toward zero and is
worse than a shorter window.

**Cost.** No estimates covering the 2019-09 onward period, and no coverage of the
2020-02-14 reduction to 7.5%. Recorded as a known gap in the episode config.

---

### D-009 — Census API requires a key that is unavailable; use a labelled synthetic generator

> **SUPERSEDED 2026-08-09.** A key was supplied and verified against the live
> endpoint. The panel is now built from official Census data and carries
> provenance `OFFICIAL`. The synthetic generator remains in the codebase and is
> still exercised by the test suite and by `--force-synthetic`, because
> validating estimators against a known data-generating process is worth keeping
> regardless of data availability. The entry below records the state that held
> while no key existed. See D-019 for what the first live pull revealed.

**Decision.** The Census `timeseries/intltrade/imports/hs` endpoint now requires
an API key (an unauthenticated request returns an HTML "Missing Key" page with
HTTP 200). No key is available in this environment. The adapter is fully
implemented and key-gated; when no key is present, the pipeline generates trade
flows from a documented synthetic DGP and tags every downstream artefact
`MIXED` or `SYNTHETIC_PIPELINE_VALIDATION`.

**Why.** The alternative to a labelled simulation is either abandoning the
vertical slice or producing plausible-looking numbers with no provenance. The
second is fabrication. A simulation whose parameters are declared in advance
lets the estimation code be validated against a known answer, which is a real
result about the code even though it is not a result about the world.

**Cost.** No empirical finding about U.S. trade exists in this repository yet.
This is the single binding constraint on the project. The moment
`CENSUS_API_KEY` is set, `make build-trade-panel` uses official data and the
provenance tags flip to `OFFICIAL` with no change to estimation code.

**Detection.** The adapter inspects the payload shape rather than the HTTP
status, because Census returns 200 with an HTML error body.

---

### D-010 — USITC HTS serves the current vintage, not HTS2018

**Decision.** Baseline MFN rates and HS6→HS8 child maps come from the live USITC
HTS endpoint, which serves the current schedule.

**Why.** It is keyless, official and machine-readable, and no archived 2018
vintage is available through the same interface.

**Cost.** A vintage mismatch: Section 301 lists are HTS2018 while baselines are
current. Lines added or retired since 2018 are mismatched. Recorded in the panel
manifest. Fixing it requires an archived HTS2018 release.

---

### D-011 — Census HS-to-NAICS concordance unavailable; use a coarse chapter map

**Decision.** The Census foreign-trade reference concordance URLs returned HTTP
404/403. Industry mapping falls back to a hand-built HS2-chapter → BEA summary
commodity map in `config/io_concordance.yaml`, with `status:
COARSE_APPROXIMATION`.

**Cost.** Within-chapter heterogeneity is lost, so industry exposure is
attenuated and the magnitudes are not usable as elasticities or as welfare
inputs. Exposure results are explicitly labelled a qualitative ordering. Every
report carrying them states the concordance status.

---

### D-012 — Day-weight the tariff rate within a month

**Decision.** The panel carries a day-weighted average statutory rate over each
calendar month, alongside month-start and month-end variants.

**Why.** List 3 took effect on 24 September 2018 — 7 of that month's 30 days.
Assessing at month start labels September untreated; assessing at month end
labels it fully treated. Both errors land on the event-time-zero coefficient,
which is the one readers look at hardest. Day weighting also matters for the
2019-05-10 rate increase.

**Evidence it matters.** Before this change the synthetic ground-truth recovery
was visibly attenuated because the generator and the panel builder disagreed
about May 2019. Both now use the same convention and it is tested.

---

### D-013 — Missing MFN baselines stay null

**Decision.** An HS6 heading containing any HS8 child with a compound or
specific duty has no single ad valorem baseline. Those rows carry a null
`total_modeled_tariff_rate`.

**Why.** An earlier version filled the null with zero when constructing
`log1p_total_tariff`, which asserted "no tariff" for 38% of rows and attenuated
every total-rate estimate. That is exactly the silent fill this project forbids.

**Consequence.** The primary treatment variable is `log1p_additional_tariff`,
which isolates the policy variation and is defined everywhere. The total-rate
specification runs on the subsample with a defined baseline and is reported
beside it rather than merged.

---

### D-014 — Two event-study reference periods, always

**Decision.** Event studies are estimated with reference period −1 and −3, and
both are reported.

**Why.** Event month −1 is the month most exposed to front-running ahead of a
known effective date. If importers pull shipments forward, the reference period
is itself treated and every coefficient shifts. Disagreement between the two is
diagnostic information, not noise to be resolved by picking one.

---

### D-015 — Pre-trend tests report significance and magnitude separately

**Decision.** `pretrend_test` returns a verdict combining statistical
detectability with magnitude relative to the mean post-treatment coefficient.

**Why.** In a large panel, standard errors shrink until economically trivial
pre-period movement is "significant". A rule that discards any design with a
significant pre-coefficient discards good work; a rule that ignores magnitude
accepts bad work. Reporting one number invites the reader to apply whichever
rule suits them.

---

### D-016 — The raw diversion decomposition is not the headline

**Decision.** The pre-versus-post decomposition is reported alongside a
counterfactual-adjusted version that nets out, country by country, the growth of
never-treated products over the same calendar months.

**Why.** The raw comparison credits ordinary trade growth to the tariff. In the
current run it produces a replacement ratio near 10, which is not interpretable.
The adjusted figure is a difference-in-differences version resting on the same
parallel-trends assumption as the event study, stated explicitly.

---

### D-017 — Defer the structural module

**Decision.** No Armington/CES module has been implemented.

**Why.** The brief requires the reduced-form vertical slice to be stable and
passing tests first. It now is, but calibrating a structural model on synthetic
trade flows would produce counterfactuals with no informational content while
carrying the appearance of substance. The module is specified in
`docs/PROJECT_PLAN.md` (M8) and gated behind official data.

---

### D-018 — The claim guard is part of the build, not documentation

**Decision.** `guard_language` raises on causal assertions under non-official
provenance and on quantified welfare claims under any provenance, and it runs on
every generated report.

**Why.** A rule written in a style guide gets violated. A rule that fails the
build does not. During development it caught two of this project's own generated
sentences; both were rephrased rather than the guard weakened.

**Design note.** It distinguishes assertions ("the tariff caused") from
vocabulary used to *discuss* evidential status ("which conclusions are causal"),
because the executive memo is required to answer that question.

---

### D-019 — Census reports no quantity at HS6; the panel moves to HS10

**Decision.** The analytical panel is built at 10-digit statistical lines. An HS6
panel is still produced, by aggregation, for comparison across aggregation
levels.

**Why.** This was discovered on the first live pull after a Census API key
became available, not reasoned about in advance. At ``COMM_LVL=HS6`` the
endpoint returns ``CON_QY1_MO = 0`` and ``UNIT_QY1 = "-"`` for every line,
because the 10-digit lines beneath an HS6 heading carry different units of
measure (pieces, kilograms, dozens) and Census will not add them. Verified
across chapters 39, 73, 84, 87 and 94.

Without quantity there is no unit value, and without unit values the two central
incidence outcomes — the tariff-exclusive customs unit value and the
duty-inclusive landed unit value — do not exist. An HS6 panel can support value
and duty outcomes only, which cannot answer who bears the tariff.

**Second reason, independent of the first.** Section 301 is legislated at HS8,
and 10-digit statistical lines nest exactly within HS8. At HS10 the
partial-coverage problem simply does not arise: the 598 HS6 headings previously
excluded because only some of their HS8 children were covered can all re-enter
the sample, correctly classified. Superseding the exclusion described in
D-013's neighbourhood is a strict improvement in both coverage and precision.

**Cost.** Roughly an order of magnitude more rows, and 320 API calls instead of
32. Mitigated by chapter-prefix wildcard queries (``I_COMMODITY=84*``), one
Parquet partition per chapter-month, and never re-fetching an existing
partition.

**Unexpected benefit.** Census emits explicit zero rows for country-product
combinations with no trade, so the extensive margin is *observed* rather than
inferred from a missing record. This partially retires the ``PANEL_GAPS``
caveat, which previously had to say that absence and true zero were
indistinguishable.

---

### D-020 — HS6 aggregates refuse to sum quantities across unlike units

**Decision.** When aggregating HS10 to HS6, values always add. Quantities add
only when every constituent 10-digit line in that HS6-country-month reports the
same unit of measure. Otherwise the aggregate quantity is null and
``hs6_units_mixed`` is set.

**Why.** Adding pieces to kilograms produces a number, and dividing value by it
produces a unit value that moves with product mix rather than with price. That
is exactly the measurement artefact this project exists to avoid, and it is
precisely how a careless HS6 panel would manufacture a spurious "price" effect.

**Cost.** A meaningful share of HS6-country-months carry no unit value. That is
the honest representation of what the data supports, and it is recorded on the
panel rather than hidden.

---

### D-021 — Tariff assessments are keyed on the 8-digit line, not the observation

**Decision.** ``attach_tariff_treatment`` computes one assessment per distinct
(HS8, country, month) and joins it onto the observations.

**Why.** Correctness first: every HS10 child of an HS8 parent is subject to the
same statute, so keying on HS8 is exact, not an approximation. Performance
follows: on a full HS10 panel this turns roughly 1.4 million engine calls into a
few tens of thousands. ``_month_segments`` was also changed to use the engine's
prebuilt (HS8, country) index instead of scanning all 12,587 records per call,
which was O(n x records) and would not have completed.

A regression test asserts that HS10 siblings under one HS8 parent receive
identical rates and statuses.

---

### D-022 — The quantity "pre-trend" was a design artefact, not a trend; the fix is stacking

**Diagnosis.** The single-wave event study flagged `log_quantity` with
pre-period coefficients as large as its post-treatment effect (ratio 1.02).
Inspecting the coefficient path showed it was not a trend at all: the months
closest to treatment were near zero (−4 through 0: −0.09, 0, −0.03, −0.02,
−0.03) while distant months oscillated between −0.05 and −0.34 with no drift.

**Three hypotheses were tested and all rejected.**

| Added fixed effects | max abs pre-coef | verdict |
|---|---|---|
| flow + month (baseline) | 0.338 | PRETREND_PRESENT |
| + country x month | 0.370 | PRETREND_PRESENT |
| + chapter x month | 0.349 | PRETREND_PRESENT |
| + month-of-year x treated-group | 0.646 | PRETREND_PRESENT (worse) |
| + month-of-year x country | 0.291 | PRETREND_PRESENT |

The month-of-year interaction made it worse because it is itself collinear with
event time.

**Root cause.** With a single treatment date, **event time is calendar time**.
Event month −12 is September 2017 and event month 0 is September 2018, exactly.
The event-study coefficients are therefore just the treated group's month-by-
month deviation from the comparison group, and any treated-group-specific time
variation appears in the pre-period with nothing available to separate it from.
No choice of fixed effects can fix this, because the confound and the object of
interest are the same variable.

**Fix.** Stack one sub-experiment per Section 301 wave. Three waves took effect
on three dates, so event month 0 falls in three different calendar months, and
each sub-experiment draws controls from never-treated products only.

**Result.** `log_landed_unit_value` moved from IMPRECISE to **CLEAN**
(max abs pre-coef 0.025 against a mean post-treatment effect of 0.149, ratio
0.16). `log_quantity` improved from ratio 1.02 to 0.54 but still fails.
`log_customs_unit_value` remains IMPRECISE because the effect itself is near
zero (0.023), so pre-period noise of the same size cannot be ruled out — an
honest "undetermined", not a failure.

This is the first outcome in the project with a licensed causal reading.

---

### D-023 — The stacked design's main justification is the forbidden comparison

**Correction to an earlier claim.** The first version of `build_stacked_design`
led with calendar-time collinearity as the reason for stacking. Writing a test
for that claim showed it is weak here: with waves only weeks apart, averaging
event month k over three nearby calendar months barely helps, and a synthetic
panel built to isolate that mechanism failed the test.

The **primary** justification is the standard one: under staggered adoption with
heterogeneous effects, two-way fixed effects uses already-treated units as
controls for later-treated ones, with weights that need not be positive. Section
301's effects are heterogeneous by construction — Lists 1 and 2 impose 25% while
List 3 began at 10%. Each sub-experiment here draws controls from never-treated
products only, so that comparison is never made.

A regression test asserts that the naive staggered design lands further from a
known average effect than the stacked one does. The docstring was corrected to
lead with this and to describe the calendar-collinearity benefit as partial.

---

### D-024 — All three waves are kept in the panel, not just List 3

**Decision.** Every 10-digit line covered by exactly one Section 301 action is
retained and tagged with its cohort. Lines covered by more than one action would
have no well-defined treatment date and are excluded; in this sample there are
none, because the lists are disjoint.

**Why.** The stacked design needs multiple waves. Restricting to List 3, which
the earlier single-wave design did to avoid biased staggered TWFE, removed
exactly the variation that makes a valid staggered design possible.

**Effect on the sample.** 1,387 List 1 lines, 361 List 2, 2,303 List 3, and
1,153 never-treated controls; the panel grows from 489,733 to 773,929 rows.

---

### D-025 — Two more pre-trend hypotheses tested and refuted

Following D-022, the two candidates named in the plan were tested directly on
`log_quantity` under the stacked design. Both failed, and a third of my own
invention failed too.

| Variant | rms/rms | Outcome |
|---|---|---|
| baseline (effective-date event time) | 0.27 | fails |
| **announcement-date event time** | 1.57 | **worse** |
| balanced lines only (present in all 32 months) | ~0.50 legacy ratio | unchanged |
| flows >= $1M/month pre-period | 0.58 legacy ratio | unchanged |
| stacked PPML in levels | 0.56 legacy ratio | unchanged |

**Announcement dating is wrong for this estimand, not just unhelpful.** Dating
from the announcement puts the announcement-to-effective window (weeks in which
no duty was collected) into the post period, which dilutes the measured effect
from −0.350 to −0.192. It is the right dating for studying anticipation, and the
wrong dating for measuring the duty's effect. Both dates remain in the schedule;
neither is a substitute for the other.

**Composition is not the driver.** 4,048 of 5,204 lines are present in all 32
months; restricting to them barely moves the statistic.

**Small-flow noise is real but not the driver either.** Month-to-month standard
deviation of log quantity is 2.44 for flows under $10k/month and 0.69 for flows
over $1M/month — a 3.5x difference — and flows under $10k/month are 26% of flows
but 0.07% of customs value. Unweighted log-OLS therefore gives a quarter of its
weight to 0.07% of the trade. Trimming to large flows was still expected to help
and did not, which is itself informative: the pre-period movement is present in
the large flows too.

---

### D-026 — The pre-trend statistic was mis-specified; replaced, and the fix does not manufacture a pass

**The defect.** `pretrend_test` compared ``max|pre|`` against ``mean|post|``.
That is apples to oranges: the maximum of a dozen noisy coefficients is
mechanically larger than the mean of another dozen. The statistic flagged
designs whose pre-periods were merely imprecise.

**Why this was safe to change.** Under the corrected like-for-like statistic
(RMS against RMS) `log_quantity` moves from 0.54 to 0.27 — still above the 0.20
threshold, so it still does not pass. A correction that leaves the failing case
failing is not goalpost-moving. Both the new and the legacy ratios are reported
on every result so the change is auditable.

**What was added.** Parallel trends is a claim about *slopes*, not levels. A
constant pre-period offset is absorbed by the reference-period normalisation; a
drift heading into treatment is the threat, because extrapolating it into the
post window biases the estimate. The test now regresses the pre-period
coefficients on event time and reports the slope, its p-value, and the **implied
bias over the post window in the outcome's own units**, which is what a reader
needs in order to judge.

**Result: three tiers, not pass/fail.**

| Outcome (stacked) | rms/rms | slope/month | p | implied bias | verdict |
|---|---|---|---|---|---|
| log landed unit value | 0.11 | +0.0010 | 0.54 | +0.005 | CLEAN |
| log quantity | 0.27 | +0.0134 | 0.068 | +0.067 | NOISY_PRE_PERIOD_NO_SLOPE |
| log customs unit value | 0.55 | +0.0024 | 0.142 | +0.012 | PRETREND_PRESENT |

`log_quantity` has no detectable differential trend. Its implied bias is +0.067
against a post-treatment effect of −0.350: about 19% in magnitude and of the
**opposite sign**, so correcting for it would make the estimated contraction
larger, not smaller. It now earns a *qualified* causal reading with that number
stated.

`log_customs_unit_value` is the outcome genuinely in trouble: its implied bias
is +0.012 against an effect of +0.023, roughly half. The old statistic had it in
the same bucket as quantity; the new one separates them, which is the point.

---

### D-027 — Product exclusions cannot be incorporated; the milestone is closed as not achievable

**Finding.** Across the eleven USTR exclusion notices covering the sample
window, the notices' own stated counts are **16 exclusions expressed as a
10-digit HTSUS subheading against 824 expressed as a "specially prepared
product description"** — 1.9% mappable to trade data.

A product description identifies a subset of a statistical reporting number by
physical characteristics. U.S. import statistics are published at that number
and no finer, so the share of a line's imports that was excluded is not
observable. **This is a property of the data, not a parsing problem.** No amount
of engineering closes it.

**Two further obstacles, recorded so they do not look like open tasks.**

* Every exclusion annex is an embedded raster image in the Federal Register PDF
  (`[GRAPHIC] [TIFF OMITTED]`), with no text layer — unlike the List 1-3
  annexes, which are typeset text. OCR is deliberately not used: it would
  introduce an unvalidatable transcription channel into a legal treatment
  variable, for the same reason a typographically damaged code is never repaired
  by guessing (D-005).
* The USITC HTS exposes the exclusion headings (9903.88.05 onward) but their
  descriptions only reference U.S. notes 20(h), 20(i), ...; the enumerated
  product lists live in note text the export endpoint does not return.

**A third kind of date.** Exclusions apply retroactively from the *effective
date of the underlying action* and expire one year after *publication*. The
first notice, published 2018-12-28, applies from 2018-07-06. Announcement,
publication and effective are three separate facts; the adapter captures all
three.

**What was built instead of an unbuildable adjustment.** The gap is bounded
empirically. Comparing the duty Customs actually calculated against the
statutory rate on treated flows:

| Period | Share of treated customs value more than 3pp short |
|---|---|
| before exclusions were first granted (2018-12) | 4.4% |
| after | 20.1% |

The pre-exclusion figure cannot be caused by exclusions — it reflects preference
programmes, Chapter 98 provisions and duty-free entry — so only the increase is
attributable to them, and even that is an **upper** bound because those other
channels also grew.

> **Corrected by D-048.** The figures in the table above conditioned on a
> positive *total* tariff rate, which includes the baseline MFN duty, so they
> admitted ordinary MFN-dutiable trade carrying no Section 301 duty at all. The
> population is now conditioned on a positive *additional* duty: the baseline is
> **10.9%**, not 4.4%, and the increase is **9.0** percentage points, not 15.7. The timing signature is
right: the gap steps up when exclusions began to be granted.

**Consequence.** Estimates in this project are intention-to-treat with respect
to the statutory list. That is now a documented structural property with a
measured bound, not an outstanding task, and the milestone is closed as **not
achievable from published statistics**.

---

### D-028 — `log_customs_unit_value` was never contaminated; the verdict rule was punishing a small true effect

**Diagnosis.** The two unit-value outcomes differ only by the duty term, so
before treatment they should behave almost identically. Plotting both stacked
event-study paths confirmed it exactly:

| event time | customs | landed | difference |
|---|---|---|---|
| −12 | −0.0215 | −0.0116 | +0.0098 |
| −10 | +0.0066 | +0.0168 | +0.0103 |
| −6 | +0.0148 | +0.0245 | +0.0097 |
| +1 | +0.0233 | +0.1444 | +0.1211 |
| +10 | +0.0034 | +0.1912 | +0.1878 |

The pre-period difference is a near-constant +0.010 — the MFN duty, unchanging.
Post-treatment it jumps to +0.12, the Section 301 duty. Pre-period noise is
essentially the same for both: RMS 0.0183 against 0.0169.

So the two outcomes have **the same clean pre-period**. Their verdicts differed
only because the post-treatment effects differ by 4.7x (RMS 0.155 against
0.033).

**The defect.** A relative-magnitude criterion systematically punishes an
outcome whose true effect is near zero: the denominator is small, so the same
absolute pre-period noise looks enormous. An outcome with a genuinely zero
effect fails such a test however clean the design. `log_customs_unit_value` was
being labelled unusable for having a small effect, which is the opposite of what
the test is for.

**Fix.** A fourth verdict, `PRECISE_NULL_EFFECT_BOUNDED`, fires when the
post-treatment path does not rise clear of the pre-period noise
(`rms_post < 2 x rms_pre`). It reports `effect_bound_abs`, how large the effect
could be given both the observed path and the slope bias. A bound on a near-zero
effect is a finding.

**A false positive the test suite caught.** The first version of the rule fired
on a synthetic panel with a deliberately injected linear pre-trend: a real
pre-trend inflates the pre-period RMS and, by offsetting the effect, deflates
the post-period RMS, pushing the ratio under the threshold and disguising a
contaminated design as a null. The rule is therefore gated on the slope being
**statistically undetectable** (p >= 0.05), not on another ratio. Re-checked:
the injected-pre-trend case is caught again, and the real-data verdicts are
unchanged.

**Verification that the change manufactures nothing.** Only the outcome whose
effect genuinely fails to clear its pre-period noise was reclassified:

| Outcome | rms_post / rms_pre | slope p | verdict |
|---|---|---|---|
| log landed unit value | 9.17 | 0.540 | CLEAN (unchanged) |
| log customs unit value | 1.81 | 0.142 | **PRECISE_NULL_EFFECT_BOUNDED**, bound 0.072 |
| log quantity | 3.68 | 0.068 | NOISY_PRE_PERIOD_NO_SLOPE (unchanged) |

---

### D-029 — The incidence conclusion, and which half of it carries the claim

With the customs unit value restored as a bounded null, the incidence account
closes.

The value-weighted additional duty actually in force on treated flows is
**15.3%**. If the exporter absorbed none of it, the duty-inclusive landed unit
value would rise by log(1.153) = **0.1424**. Observed: landed **+0.1494**,
customs (tariff-exclusive) **+0.0225**, bounded at **0.072**.

**The landed figure is not independent evidence.** It contains the duty by
construction, so most of its rise is arithmetic. Quoting it alone would be
close to quoting the tariff rate back.

**The behavioural quantity is the customs unit value**, which falls only if the
exporter cuts its border price. It did not: the point estimate is slightly
*positive* and the effect is bounded near zero. That bound is what supports the
conclusion that the tariff was passed through to the U.S. importer close to in
full over this window, with no detectable exporter absorption.

The accounting is written into `identification_checks.json` by the estimation
script so the mechanical benchmark is a recorded result rather than an
after-the-fact calculation.

---

### D-030 — List 4A: legal facts verified, parser generalised, list withheld pending validation

**A session-1 assumption was wrong.** The note in D-001 said List 4 notices
"enumerate 10-digit statistical lines" and therefore needed their own parser.
They do not. 84 FR 43304's annexes contain **no 10-digit codes at all** — 3,238
unique 8-digit subheadings in the Annex A region, 560 in the Annex C region. The
only difference from Lists 1-3 is an enumeration prefix in the operative
sentence, because a second clause follows:

    Lists 1-3:  "Heading 9903.88.01 applies to all products of China that are
                 classified in the following 8-digit subheadings:"
    List 4:     "Heading 9903.88.15 applies to: i) all products of China that
                 are classified in the following 8-digit subheadings:"

The `ii)` clause is the same partial-line construction as List 3's note 20(g),
differing only by writing "provided for in **subheading** 4901.99.00". So three
small regex generalisations serve both rather than a second parser that would
drift out of step. Lists 1-3 were re-run as a regression: still 818 / 279 /
5,745 exactly.

**Legal facts, each read from the source.**

| Fact | Value | Source |
|---|---|---|
| List 4A effective | 2019-09-01 | 84 FR 43304 |
| List 4A rate | **15%, never 10%** | 84 FR 45821 |
| List 4A reduced | 7.5% on 2020-02-14 | 85 FR 3741 |
| List 4B scheduled | 2019-12-15 at 15% | 84 FR 43304 + 45821 |
| List 4B status | **suspended indefinitely; never took effect** | 84 FR 69447 |

The rate detail matters. The August notice specified 10%, but 84 FR 45821 states
the rate "will be 15 percent on the current effective date of September 1, 2019"
and "does not change the effective date". So List 4A was 15% from day one;
modelling a 10% → 15% transition would invent a rate change that never happened.

List 4B must not be encoded as a duty at all. It was suspended before its
effective date and never collected.

**Why the list is not yet in the episode config.** D-002 requires validating a
parsed line list against a count the notice states itself. This notice states no
separate count for Annex A. The 3,805 figure in its preamble refers to the May
2019 *proposal* covering the whole $300 billion action — "invited public comment
on ... products from China classified in 3,805 full and partial tariff
subheadings" — which was then split into Annex A and Annex C. The parser's
"closest stated count" heuristic picked it and reported a 565-line shortfall
against the wrong referent.

Annex A (3,238) plus Annex C (560) is 3,798, close to 3,805, which suggests the
right validation is a **combined** check across both annexes. That requires
multi-annex parsing, which `parse_annex` does not yet do — it returns the first
anchor only. Until that check passes, List 4A stays out of the tariff schedule:
shipping an unvalidated statutory list would break the rule that makes the other
three trustworthy.

---

### D-031 — List 4A parsed and validated; List 4B recorded as never effective

Following D-030, `parse_all_annexes` now iterates the operative anchors rather
than assuming one action per notice. 84 FR 43304 carries two: heading 9903.88.15
(List 4A, Annex A) and 9903.88.16 (List 4B, Annex C).

**Validation, since the notice states no count for either annex.** Its 3,805
figure is the May 2019 *proposal* — "invited public comment on ... 3,805 full and
partial tariff subheadings" at "up to an additional 25 percent" — and the final
action differs from it in both scope and rate. Validating an annex against it
reports a phantom shortfall, so per-annex count validation is deferred to the
document level and the parse is corroborated by independent internal checks
instead: no truncated codes, no duplicates, Chapter 98/99 provisions excluded,
annex boundaries verified against the page structure, and each operative annex
cross-checked against its descriptive counterpart.

Every difference in that cross-check was accounted for rather than tolerated.
Two codes (6203.41.05, 8479.89.20) appear only in the descriptive annex, which by
its own terms "is not intended to delimit in any way the scope of the action".
Two others (9603.10.05, 9102.12.80) sit in different annexes between the
operative and descriptive renderings; the operative text governs.

**Facts, each read from the source.** List 4A effective 2019-09-01 at **15%** —
never 10%, because 84 FR 45821 set 15% "on the current effective date of
September 1, 2019" without changing that date — reduced to 7.5% on 2020-02-14 by
85 FR 3741. List 4B was scheduled for 2019-12-15 and **suspended indefinitely**
by 84 FR 69447; no duty was ever collected under it. It is recorded in a
`suspended_actions` block so it is not mistaken for a gap, and deliberately not
encoded as a duty.

---

### D-032 — Two defects that only a second overlapping action could expose

**A boundary regression, caught by re-running Lists 1-3.** Scoping each annex's
partial-line note to whole pages dropped three of List 3's eleven carve-outs,
breaking its exact 5,745 reconciliation. Its note 20(g) runs onto the very page
that carries the ANNEX B header, so the note and the next annex share a page.
The scope is now taken by **text position** — up to the ANNEX header match
within the shared page — and List 3 reconciles exactly again. A regression test
names the three lost codes.

**A real correctness bug in the engine.** Carve-outs were applied *after* the
conflict check and zeroed the rate globally. Once two overlapping actions were
loaded, a statistical number carved out of one action but squarely covered by
another came back as untreated: 9401710008 is named in List 3's note, not List
4A's, and returned a zero rate instead of List 4A's duty.

Carve-outs are now applied **per action, before** the conflict check: an action
whose note names a statistical number does not govern it and contributes no rate
to the comparison. The resulting behaviour on 9401.71.00, a line genuinely
divided across three actions:

| Statistical number | Carved out of | Result |
|---|---|---|
| 9401710001 | both live actions | 0%, OK |
| 9401710008 | List 3 only | List 4A's rate, OK |
| 9401710099 | neither | CONFLICT, no rate assigned |

The CONFLICT case is correct, not a failure: two actions claim the same number at
different rates and the engine declines to choose.

**A test assumption that was wrong.** A first version asserted that List 4A's and
List 4B's carve-out sets for 9401.71.00 were disjoint. They are not. The three
actions' sets overlap because each note excludes the numbers belonging to the
others and the actions were legislated at different times; their union is seven
statistical numbers. The test now asserts the verified sets rather than a tidy
partition that was never checked.

---

### D-033 — Window extended to 2020-02; the endpoint is a COVID judgement, not a tariff one

The window ran to 2019-08 only because List 4A was unparsed and would have put
genuinely treated products in the control group. With List 4A in the schedule
(D-031) that constraint is gone.

**Where to stop is a judgement about the pandemic.** U.S. "imports for
consumption" are recorded when goods enter the United States, so entries lag
Chinese shipment by roughly four to six weeks. February 2020 entries reflect
December-January shipments, before Chinese production was disrupted; March 2020
entries reflect January-February shipments and are unambiguously contaminated.
The window ends 2020-02.

The 2020-02-14 reduction of List 4A from 15% to 7.5% falls inside the final
month; the day-weighted statutory rate handles it.

**The conclusion does not depend on the judgement.** Three window definitions,
stacked design, never-treated-product controls:

| Window | landed | customs | quantity |
|---|---|---|---|
| to 2020-02 | +0.1544 CLEAN | +0.0253 bounded null | −0.3793 |
| to 2019-12 (before the rate cut and any plausible COVID effect) | +0.1562 CLEAN | +0.0263 bounded null | −0.3793 |
| to 2019-08 (before List 4A existed) | +0.1525 CLEAN | +0.0216 bounded null | −0.3567 |

Every verdict identical; every estimate within 0.004. Written to
`data/results/window_sensitivity.json`.

Incidence accounting on the full window: value-weighted duty in force 17.65%,
mechanical log(1+tau) with zero absorption 0.1626, observed landed +0.1544,
customs +0.0253.

---

### D-034 — A fixed classification date silently mislabelled every List 4A product

Extending the window exposed a latent bug. Cohort assignment assessed each line
on **one fixed date, 2018-10-01**. That date predates List 4A, so once the window
ran past 2019-09 every List 4A product was classified never-treated and went into
the control group — exactly the contamination the extension was meant to avoid,
reintroduced by the classifier rather than by the schedule.

Classification is now by the set of actions that **ever** cover a line within the
sample window: covered by exactly one action, that cohort; by more than one,
excluded; by none, control. No magic date.

**Effect.** The never-treated control group falls from 1,174 lines to 379, with
795 moving into a new List 4A cohort and 2 excluded as genuinely conflicted.

**A consequence worth stating rather than burying.** Within these ten chapters,
by September 2019 almost everything had been tariffed. The surviving control
group is 379 lines — 7% of the sample — and they are not a random 7%: they are
what USTR declined to tariff even in the $300 billion round. The stacked design's
counterfactual now rests on a selected set, and that selection is a threat to
identification in its own right, distinct from parallel trends. The result's
stability across the three windows above is reassuring but not dispositive,
because all three share most of that control group.

---

### D-035 — The replication check counted "unvalidatable" as "failed"

Adding List 4A made target T1 report MISMATCH, even though Lists 1-3 still
reconciled exactly. The check treated a null `count_matches_notice` — meaning the
notice states no count for that annex, so the comparison is impossible — as a
failure, via `fill_null(False)`.

It now separates checkable rows from deferred ones and reports both: "exact match
on 3 checkable actions; 1 deferred to internal cross-checks". A test that cannot
be run is not a test that failed, and the same distinction is already enforced in
the data-quality battery, where a check without inputs reports SKIPPED rather
than PASS.

Targets T2 and T3 were also stale: they still read BLOCKED_ON_DATA from the
period before a Census key existed. They now record what was actually estimated,
with the pre-trend verdict attached and the reasons the comparison is conceptual
rather than exact.

---

### D-036 — Not-yet-treated controls answer the selection threat

D-034 recorded a threat rather than solving it: after extending the window, only
379 never-treated lines survived, and they are not a random 7% of the sample —
they are what USTR declined to tariff even in the $300 billion round. The
counterfactual rested on a selected set.

**The fix uses variation already in the panel.** Products tariffed *later* are
untreated during an earlier wave's window, and they are economically far closer
to the treated group than the never-treated residual, because USTR did
eventually target them. A third control definition, ``not_yet_treated``, admits
never-treated products plus any cohort whose own treatment begins strictly after
the sub-experiment's window ends.

**Admissibility is enforced, not assumed.** A cohort qualifies only if its
treatment month falls after the window; admitting one that becomes treated inside
the window would reintroduce the forbidden comparison the stacked design exists
to avoid. Here the arithmetic is favourable: Lists 1, 2 and 3 have windows ending
at month indices 24233-24235 and List 4A begins at 24237, so List 4A's 795 lines
are untreated throughout all three. The List 4A sub-experiment has no later
cohort and correctly falls back to never-treated only. A test asserts that a
cohort treated *on the window boundary* is refused.

**Result.** The control group roughly triples (379 to 1,174 lines) and the sample
grows 35%, and the answer does not move:

| Controls | landed | customs | quantity | n |
|---|---|---|---|---|
| never-treated | +0.1544 CLEAN | +0.0253 bounded null | −0.3793 | 395,468 |
| not-yet-treated | +0.1513 CLEAN | +0.0259 bounded null | −0.3710 | 535,132 |

Every verdict identical, every estimate within 0.008. A completely different
comparison group — one built from products the same agency did choose to tariff —
gives the same answer. The selection concern is real in principle and is not
driving this result.

All three control definitions are now estimated and reported side by side on
every run, so the choice is visible rather than buried in a default.

---

### D-037 — The official HS-to-NAICS concordance exists; my URL guesses were wrong

D-011 recorded that the Census concordance was unavailable because the reference
URLs returned 404/403, and fell back to a hand-built HS2-chapter map labelled
COARSE_APPROXIMATION. That conclusion was wrong in an instructive way: the
resource existed the whole time. The 404s came from guessing URL patterns
(`/naics/concordances/2022_NAICS_to_HS.xlsx`, `/foreign-trade/reference/codes/
naics/`) rather than reading the index Census publishes. Fetching
`/foreign-trade/reference/codes/concordance/index.html` with a browser
user-agent — a plain urllib request is 403'd — lists every file, import and
export, back to 2002.

**What the official file gives.** `impconcord20.xlsx`: 19,137 rows keyed on the
**10-digit commodity code**, each carrying one 6-digit NAICS industry, plus SITC
and end-use codes. Because the key is the same level this project's panel is
built at, there is no weighting assumption at all — the chapter map had to
assign a whole HS2 chapter to one BEA commodity.

NAICS is then mapped to BEA summary industries by BEA's published summary
definitions (334 is NAICS 334; 3361MV is NAICS 3361-3363; 311FT is 311+312, and
so on). That is a documented aggregation, not a judgement.

**Coverage.** 98.8% of concordance lines reach a BEA summary industry; 97.4% of
the panel's customs value is mapped. The 2.5% shortfall is vintage: the 2020
concordance does not carry every code that existed in 2017-2020. Census
publishes one file per year for exactly this reason, and the vintage used is
recorded in the manifest. The 2019 file is `.xls`, which openpyxl cannot read;
the adapter raises rather than silently substituting a different vintage, since
that would misassign renumbered lines.

**Two things the source says that are kept rather than smoothed.** Census writes
an `X` inside a NAICS code where it aggregates detail it will not disclose (198
lines); those are kept verbatim, because truncating to a shorter code would
assert precision the source declines to give. And 237 lines map to NAICS outside
the BEA summary manufacturing and primary groups; they are excluded and counted,
not forced into a bucket.

---

### D-038 — The coarse map was not merely imprecise; it understated exposure systematically

Replacing the chapter map changed the industry results materially, and in one
direction:

| Exposure class | HS2 chapter map | Official concordance |
|---|---|---|
| Both protected and cost-exposed | 9 | **19** |
| Input-cost exposed only | 15 | **29** |
| Little direct exposure | 48 | **24** |

Half the industries the chapter map called barely exposed are exposed. Several
carried a reported output protection of exactly zero and in fact face
substantial protection: chemical products 0 → 0.222, food, beverage and tobacco
0 → 0.250, nonmetallic mineral products 0 → 0.250, other transportation
equipment 0 → 0.222.

The cause is structural rather than random. The chapter map covered eighteen HS2
chapters and sent each to a single BEA commodity, so any product whose industry
differed from its chapter's assigned one was either misassigned or dropped. A
coarse mapping does not add symmetric noise here; it loses coverage, and lost
coverage reads as absence of exposure.

Anyone who read the earlier industry-exposure figures got a materially
understated picture. The chapter map is retained behind `--force-chapter-map`
precisely so this comparison stays reproducible.

Exposure magnitudes are still not elasticities and still do not feed any welfare
statement, but they are no longer merely an ordering: the mapping underneath
them is now official and assumption-free at the product level.

---

### D-039 — "openpyxl cannot read it" was not the same as "it cannot be read"

D-037 used the 2020 concordance for a 2017-2020 panel and recorded a 2.5%
unmapped share, because the 2017-2019 vintages are legacy ``.xls`` and openpyxl
handles only ``.xlsx``. The adapter raised on ``.xls`` deliberately, so the
substitution was at least visible — but the conclusion drawn from it, that
per-year vintages were blocked, was wrong for the same reason D-011 was wrong:
one tool failing is not the resource being unavailable. ``xlrd`` reads ``.xls``
and nothing else, which is exactly the complement. Both readers are now
supported.

**Combining vintages.** Census publishes one file per year because codes are
renumbered and NAICS assignments revised. Two facts decide how to combine them.
The assignment should be **pre-determined**, for the same reason the exposure
weights are: letting the industry assignment drift with later vintages would
reintroduce through the back door what pre-treatment weighting is careful to
avoid. But later vintages still add **coverage**, since codes created after the
primary year exist only there. So the 2017 vintage governs, later vintages
supply only codes 2017 lacks, and the source vintage is recorded per code.

**What this closes and what it measures.**

| | 2020 vintage alone | 2017 primary + 2018-2020 fill |
|---|---|---|
| Panel lines reaching a BEA industry | 5,057 | 5,182 |
| Share of panel customs value mapped | 97.50% | **99.80%** |

450 codes come from later vintages — commodity lines created after 2017. And
172 codes carry a different NAICS in a later vintage than in 2017, concentrated
between the 2018 and 2019 files: 2017 vs 2020 differs for 172 codes, 2018 vs
2020 for 156, but 2019 vs 2020 for only 2. That count is reported rather than
resolved, because it bounds how much the choice of primary vintage matters,
which is the honest form of the answer when two official vintages disagree.

A silent trap worth recording: ``xlrd`` returns numeric cells as floats, so the
commodity code 0101210010 arrives as 101210010.0 and a naive digit check drops
it. Leading zeros are restored explicitly and a test asserts it.

---

### D-040 — BLS PPI: the industry classification, not the commodity one

The PPI is published under two systems, commodity (`WPU...`) and NAICS industry
(`PCU...`). This project's exposure measure is built at NAICS through the
official Census import concordance, so the industry series match it directly.
The commodity series would require a second crosswalk between classifications
that were never designed to align — precisely the "forcing a product
classification onto a broad price series" the project's own data rules warn
against.

Series IDs follow `PCU` + industry + product, each hyphen-padded to six, so
NAICS 325 is `PCU325---325---` and 3361 is `PCU3361--3361--`.

**What is genuinely missing, recorded rather than substituted.** Agriculture and
forestry (NAICS 111-115, BEA `111CA` and `113FF`) have no NAICS-industry PPI at
all; they are absent from the estimation panel. NAICS 316 has no series, so BEA
`315AL` is matched by its 315 component alone. Where a BEA industry aggregates
several NAICS groups the component series are averaged **unweighted**, because
NAICS-component output weights do not exist in the BEA summary tables. Every
industry carries a match-quality flag and a partial match is never presented as
exact.

Result: 29 of 35 requested series, covering 22 of 24 BEA industries over 48
months.

---

### D-041 — Propagation into producer prices: a power result, not a null

The exposure channels have until now been an accounting construct. Whether they
predict anything is a separate question, and this is the first test of it.

| Channel | Coefficient | 95% CI | analytic p | bootstrap p |
|---|---|---|---|---|
| imported-input cost | +1.230 | [−0.450, +2.909] | 0.143 | 0.110 |
| output protection | +0.374 | [−0.050, +0.797] | 0.081 | 0.084 |
| downstream (Leontief) | +0.164 | [−0.050, +0.379] | 0.126 | 0.112 |

**All three carry the expected positive sign and none is distinguishable from
zero.** That is a statement about power, not about the world. The interval on
input-cost exposure spans roughly −1% to +9% of producer prices at mean
exposure: uninformative, not a bound near zero. This is deliberately *not*
labelled `PRECISE_NULL_EFFECT_BOUNDED` — that verdict is earned by a tight
interval around zero, and this interval is the opposite.

Two reasons power is low, both structural:

* **22 clusters.** Cluster-robust standard errors over-reject badly at that
  count, so a wild cluster bootstrap with the null imposed and Rademacher
  weights at the cluster level is reported for every coefficient (D-042). Here
  the two broadly agree, which is itself worth knowing.
* **An aggregation gap.** PPI industry indices cover an entire NAICS group while
  exposure is built from 10-digit trade lines. That attenuates any true
  relationship toward zero, in the same direction for every channel.

**Entering both channels together halves the input-cost coefficient** (+1.23 to
+0.35). The two exposures are positively correlated across industries: an
industry that buys tariffed inputs tends also to sell tariffed output. Reporting
either channel alone attributes the other's variation to it, which is a concrete
reason beyond the distributional one for never netting them.

---

### D-042 — Wild cluster bootstrap, because 22 clusters is not enough

Cluster-robust inference is asymptotic in the number of clusters. The
propagation panel has 22, well under the range where the analytic formula is
trustworthy, and the project's brief lists a wild or clustered bootstrap as the
appropriate remedy.

`wild_cluster_bootstrap` implements the bootstrap-t with **the null imposed**:
residuals come from the restricted model, so the bootstrap distribution is
generated under `beta = 0` rather than around the estimate, and Rademacher
weights are applied at the cluster level to preserve within-cluster dependence.

Both p-values are always returned so they can be compared rather than one
silently replacing the other. Tests check that it does not reject when there is
no effect at 22 clusters, does reject a large true effect, and selects the
right coefficient when several are present.

### D-043 — BEA detail tables: 125 clusters instead of 22, and a hand-coded map vindicated

D-041 recorded the propagation test as a power result, not a null, and named
three ways out: widen the chapter set, drop to a finer NAICS level, or accept
the limit. The finer level turned out to be available in a form that costs
nothing in data quality.

BEA publishes **detail-level** input-output tables (~400 industries against the
summary level's 71) for benchmark years only — 2007, 2012, 2017. The pre-treatment
year of this project is 2017, so the finest published breakdown exists exactly
where a shift-share design needs its weights. The tables were already inside the
`AllTablesSUP.zip` the project had been downloading since session 8; only the
summary members were being read.

**The count.** Mapping the panel's 219 NAICS industry codes into BEA detail
industries reaches 211 of them, covering **97.8%** of panel customs value, across
148 detail industries. Of those, 125 have at least one NAICS-industry PPI series.
That is the cluster count the propagation regression can now use, against 22
before. The wild cluster bootstrap (D-042) stays regardless — it costs little and
its p-value is the honest one to read — but 125 clusters puts cluster-robust
inference back inside the range where it behaves.

**Three things this turned up that were not the point.**

*The hierarchy was already published.* Every detail workbook carries a `NAICS
Codes` sheet giving BEA's own Sector / Summary / U.Summary / Detail nesting and
the NAICS codes each detail industry relates to. `bls_ppi.BEA_TO_NAICS` had been
hand-coded from BEA's summary definitions in session 12 — the same mistake in
kind as D-011 and D-037, where a source was assumed unavailable and substituted
for. Checked against the published sheet, **the hand-coded map agrees exactly**;
no prior exposure result changes. It is now pinned by a test rather than by luck,
and the detail level does not use the hand-coded dict at all.

*The header layout is not stable across BEA's own workbooks.* Summary writes
column codes above the label row; detail writes them below it. The original
parser took them by position, which on the detail file silently returned industry
*titles* where codes were expected. Nothing would have raised: the downstream
join would simply have matched nothing and produced an empty exposure table. The
parser now identifies the code row by content — BEA codes are short and
space-free, titles are prose.

*A footnote had been an industry since session 8.* `Note. Detail may not add to
total due to rounding.` sat in the code column of the Use sheet and became a
72nd row of `industry_tariff_exposure.parquet`, with zero exposure and no PPI
match. It never entered an estimate, but it was in a published result table and
would have appeared in a report as an industry. The summary exposure table is now
71 rows. Re-running the summary level after the parser change leaves all 71 real
industries identical to **1e-17** — floating-point summation order — so nothing
that has been reported moves.

**What is not claimed.** Detail industries are pinned to a benchmark year, so
this level cannot follow a moving IO structure; asking for a non-benchmark year
raises rather than interpolating. Eight NAICS codes in the panel mapped to
nothing, recorded in `io_exposure_quality_detail.json` rather than dropped in
silence. **Correction, made in D-044:** this entry attributed all eight to NAICS
retirement. Six were (333911, 333913, 335221-8); the other two, 910000 and
930000, are Census pseudo-industries for scrap and used or second-hand goods,
which have no producing industry at all and which BEA also carries as special
rows with no NAICS counterpart. They are 0.18% of panel customs value and
essentially untariffed. D-044 repairs the six and leaves the two, and the
figures in the addendum below are the pre-repair ones. NAICS codes claimed by two detail industries at equal
depth are left unassigned instead of being broken by an arbitrary rule; on this
panel there are none.

**Status: the estimate itself is not yet run.** The BLS v1 endpoint allows a
small number of requests per address per day, and the coverage probes above
exhausted it. `estimate_propagation.py --level detail` refused to estimate on the
subset that happened to be cached, because a silently changed sample is worse
than no result. The per-request cache has been replaced with a **per-series**
cache so a re-run fetches only what is genuinely missing rather than re-requesting
every chunk whenever the industry set changes by one code.

**Addendum, what the detail level shows before any estimate is run.** The
summary level classed 19 of 71 industries as exposed on both sides; the detail
level classes **142 of 401**, and turns up two `PROTECTED_ONLY` industries that
could not exist at summary level because aggregation always mixed some tariffed
input into them. Within the single summary industry `3361MV` the detail level
separates heavy-duty truck manufacturing (input cost 0.112, protection 0.162)
from motor-vehicle steering and suspension components (0.094, 0.250) — very
different positions that a 71-industry axis reports as one number.

It also makes an asymmetry visible that the summary level obscured: protection
carries the statutory rate of a single commodity (mean 0.076, max 0.250) while
input cost is an average over the whole purchase basket, most of it untariffed
(mean 0.023, max 0.112). 255 of 402 industries have input cost above protection,
almost all of them industries with no protection at all. The two channels are
therefore not comparable **as levels**, independently of the reason they are
never netted, and the module docstring now says so.

### D-044 — The concordance and the IO table were on different NAICS vintages

D-043's unmapped-code list was the visible symptom of something larger. Census
moved the import concordance from **2012 NAICS to 2017 NAICS with the 2019
vintage**. This project takes 2017 as its primary vintage — deliberately, so the
industry assignment is pre-determined like the weights — which means the primary
concordance is on 2012 NAICS while BEA's 2017 input-output tables are on 2017
NAICS. The two sides of the exposure measure were speaking different
classifications.

The magnitude is bounded and was measured before anything was changed: of 18,749
HS10 lines present in both the 2017 and 2019 vintages, 170 (0.91%) carry a
different NAICS, and those lines hold 2.43% of panel customs value. Ten
2012-vintage codes are absent from the revised classification entirely.

**Why this never showed up at summary level.** The summary BEA mapping
aggregates NAICS at three digits, and every one of the ten retirements is a
consolidation *within* a three-digit group: 335221/2/4/8 into 335220, 333911 and
333913 into 333914, 211111/211112 into 211120/211130, 212231/212234 into 212230.
Rebuilding the summary exposure after the fix leaves all 71 industries identical
to 1e-17. A test now asserts the three-digit invariance rather than leaving it to
be rediscovered, because if it ever stopped holding the summary results would
move underneath the change without anything failing.

**The rule.** "The primary vintage governs" has no meaning when the primary
vintage's answer is not a code in the target classification at all. So for those
lines only, the successor is read off the **same HS10 line** in the revised
vintage. That is still one official source; nothing is mapped forward by hand,
which is the failure mode D-011, D-037 and D-043 each hit in turn. Genuine
reclassifications — where the old code still exists but this product moved, such
as 339999 to 335999 — are left alone and the primary vintage keeps governing.

**What it changed.** Detail-level coverage rises from 97.8% to **99.71%** of
panel customs value. Two industries had been recorded as carrying *zero* output
protection when they are in fact among the most protected in the sample:

| BEA detail industry | protection before | after |
|---|---|---|
| 333914 Measuring, dispensing and other pumping equipment | 0.000 | 0.250 |
| 335220 Major household appliance manufacturing | 0.000 | 0.207 |

Both are exactly the industries whose 2012 codes were retired, so their tariffed
import lines had been mapping nowhere. Industries exposed through both channels
go from 142 to 144 of 401; the aggregate distributions barely move, and the
heavy-duty-truck and steering-component figures quoted in D-043 are unchanged.

**A dead end kept in the record.** The first version of the rule took the live
code universe as the union of NAICS across every vintage *after* the primary.
That looked more conservative and silently did nothing: the union spans the
classification switch, so the 2018 file — still on 2012 NAICS — keeps every
retired code alive and the rule found zero. It was caught by a fixture that
asserted a genuine reclassification survives untouched. The live universe is now
taken from the latest vintage alone, and the limitation that remains is stated
instead of engineered around: "absent from the latest file" is a superset of
"retired by the revision", so every substitution is returned and reported rather
than applied invisibly.


### D-046 — The headline incidence numbers were typed in, not computed

Reading `tariff_incidence_results.md` line by line found the two numbers the
entire incidence conclusion rests on sitting in the generator as string
literals:

```python
f"Observed: landed unit value **+0.1494**, customs (tariff-exclusive) unit "
f"value **+0.0225**"
```

The `f` prefix is there and interpolates nothing. In the same sentence `tau`,
`log(1+tau)` and the effect bound are all computed from the result tables; only
the two observed responses were hand-written. This is exactly what acceptance
criterion 10 forbids — every empirical claim traceable to a reproducible table —
and the failure mode it exists to prevent had already happened: the true values
are **+0.1544** and **+0.0253**, so the report was printing figures that
contradicted the estimates in its own tables further down.

The numbers were never missing. `estimate_incidence.py` already writes a
`stacked_mean_post_effect` row per outcome per control definition into
`incidence_estimates.parquet`; the report simply was not reading them. What was
missing was a way to *select* the headline design: the row carried no
`control_definition`, so the three control definitions could only be told apart
by row order. That column is now written, and the report filters on it.

The conclusion does not change — +0.1544 against a mechanical 0.1626, with the
customs response bounded at 0.076 — and STATUS.md had the right figures
throughout. What changes is that the report can no longer drift from the
estimates behind it.

**Two smaller defects found in the same read-through.**

*The binned endpoints were labelled as post-period.* `is_pre` was computed as
`k is not None and k < 0`, and the endpoints have no single event time, so
`evt_pre_bin_13` — unambiguously a pre-period coefficient — came out `False`.
Every event-study table in the reports printed it as a post row, and unlabelled
at that, because the rendered table selected `event_time` and the endpoints have
none. Both are fixed: the label follows the term name, and the tables print
`<= -13 (binned)` and `>= +11 (binned)`.

*The trend statistics were right for a fragile reason.* `pretrend_test` built its
post set with `(~is_pre) & std_error > 0 & event_time.is_not_null()` and its pre
set with `is_pre & std_error > 0`. The endpoints stayed out of both, but only
because that one extra condition happened to sit on the post side. Anyone
removing it as redundant — it looks redundant — would have silently moved a
binned endpoint into the post average. The condition is now stated on both sides
as what it actually means: only coefficients at a definite event time enter a
trend statistic. Re-running estimation after the change leaves all fifteen
pre-trend tests bit-identical, and a test now pins the invariant with endpoint
estimates large enough that a leak into either statistic would fail it.

### D-048 — The exclusion bound was diluted by trade the tariff never touched

The intention-to-treat bound is the project's substitute for an exclusion
adjustment it established cannot be made. Its whole content is a decomposition:
a baseline share of Section 301-dutied value where the realised duty falls short
of the statutory rate for reasons *other* than exclusions, and an increase after
exclusions began that is attributable to them. Getting the baseline wrong
distorts the only claim the bound makes.

`realised_vs_statutory_bound` conditioned on `total_modeled_tariff_rate > 0`.
That total includes the **baseline MFN rate**, so the population admitted
ordinary MFN-dutiable imports from the treated country carrying no Section 301
duty whatever — including six months before the first action took effect, in
which no flow could possibly fall short of a Section 301 duty because none
applied. Those months contributed **$42.6bn** of customs value to the
denominator and exactly zero to the numerator.

A flow carrying no additional duty cannot be affected by an exclusion from that
duty. The condition is now `additional_tariff_rate > 0`, and the frame begins in
2018-07 rather than 2018-01 as a consequence rather than by a hand-set window.

| | as published | corrected |
|---|---|---|
| baseline, before the first exclusion | 4.4% | **10.9%** |
| after | 18.7% | **20.0%** |
| increase attributable to exclusions | +14.3pp | **+9.0pp** |

The published baseline was understated by a factor of 2.5 and the
exclusion-attributable increase overstated by more than half. The direction is
worth naming plainly: the error made the exclusion problem look **larger** than
it is, so every statement of the form "estimates are intention-to-treat and here
is how far that can be from treatment-on-the-treated" was conceding more than
the data required. The conclusion is unchanged in kind — the gap is real, it is
bounded rather than closed, and the bound remains an upper one because
preference programmes and Chapter 98 entry leave the same signature.

Found by reading `product_exclusions.md` against its own by-month table: six
leading months of exactly 0.0000 in a column whose denominator was supposed to
be tariffed trade.

### D-049 — The specification register claimed the wrong estimation level

Read against the panel it describes, the specification register said every
design was estimated at `hs6 x country x month`. The panel has 923,440 rows,
which is exactly its count of distinct `(hs10, country, month)` cells; the
heading-level count is 353,188. Every regression runs on the 10-digit
statistical reporting number and had done since session 9.

`aggregation_level` was a fixed string in each of the three `DesignSpec`
constructions, written when the panel was keyed on the heading. It is derived
from the panel's own columns now, so a future change of level carries into the
register instead of leaving it behind.

This one matters more than its size suggests. The register is the artefact that
answers "what was estimated, at what level, under what assumption" — it exists so
a reader does not have to trust the prose — and it was off by a factor of 2.6 in
the number of cells behind every coefficient in the project. Clustering is on
`hs6`, which is correct and unchanged: the treatment is assigned at the 8-digit
line, so the heading is the conservative cluster. But the observation is the
10-digit line, and the register now says so.

Found by reading `technical_report.md` and checking the register's claim against
`trade_panel.parquet` rather than against the surrounding prose.

### D-050 — Checking artefacts against each other, not just code against fixtures

Five defects came out of reading the eleven generated reports end to end, and
the test suite was green through all of them. That is not a gap in coverage; it
is a gap in *kind*. A test exercises code against fixtures. Every one of these
was a disagreement between two finished artefacts that no code compared:

* a heterogeneity table summing to 3.16x the totals it partitioned (D-047);
* an exclusion bound whose denominator held six months of trade the tariff never
  touched (D-048);
* a specification register naming a level the panel had not used for four
  sessions (D-049);
* headline incidence figures typed into a report as literals and drifted from
  the estimates printed below them (D-046);
* replication rows reporting "not produced" beside a claim about how the result
  compared to the published one.

The unifying property is a **stated identity that nothing evaluated**. A
partition sums to what it partitions. A register names the level the panel is
keyed on. A bound covers the population it claims to. None of those needs a
fixture — they need two artefacts and a comparison.

`quality/consistency.py` evaluates them, `scripts/check_consistency.py` runs
them between the estimation scripts and the reports, and `make reproduce-sample`
now fails on a blocking inconsistency rather than producing documents that
disagree with each other. Every check is tested by rebuilding the artefact as it
was when the defect was live and asserting the check fails on it: a check that
only passes on corrected data proves nothing.

Two things this deliberately does **not** try to be. It does not parse prose for
numbers — the fix for typed-in figures is that reports read from tables, and the
check asserts the row they read from is present and unique rather than trying to
police English. And it skips rather than fails when an artefact is absent, so a
partial pipeline run is not reported as an inconsistency.

Writing the tests found one defect in the checks themselves: the exclusion-bound
check floored to the month in its pass condition and compared raw dates when
counting flagged rows, so it would have failed correctly and then miscounted why
— July 2018 contains the first effective date and is legitimately in the frame.

### D-051 — The date placebo tested the one outcome that already failed, and said so nowhere

Finishing the report read-through — `tariff_incidence_results.md` had been read
to line 120 of 702, and `replication_protocol.md` not at all, while STATUS
claimed all eleven were read end to end — turned up a placebo reporting a
significant effect with no indication of what it applied to.

`placebo_treatment_date_minus_12m` moves the treatment date twelve months
earlier and estimates on pre-period data alone, where nothing should be found.
It was reporting `any_post_significant_5pct: true`. Two things were wrong with
how that reached a reader:

*It ran on `log_quantity` alone*, hardcoded, and **recorded no outcome**. So the
check appeared in the report as a bare failure. A reader could not tell whether
it threatened the incidence claim, which rests on the two price outcomes, or the
quantity result, which already carries a qualified reading — and had no way to
find out from the artefact.

*It tested the wrong outcome.* `log_quantity` is the outcome that already fails
its own pre-trend magnitude test. The two outcomes carrying the conclusion were
never date-placebo-tested at all. Testing the one that already fails and not the
ones the argument depends on is exactly backwards.

Run on all three, and named:

| outcome | date placebo | max abs post coefficient |
|---|---|---|
| `log_customs_unit_value` | **PASS** | 0.0351 |
| `log_landed_unit_value` | **PASS** | 0.0349 |
| `log_quantity` | **FAIL** | 0.0934 |

**This strengthens the incidence account rather than weakening it.** The failure
is confined to quantity, and it is the same differential trend that the pre-trend
test already reports as `NOISY_PRE_PERIOD_NO_SLOPE`, now visible a second and
independent way — which is a more honest description of the quantity result than
the pre-trend verdict alone. The two price outcomes, on which the pass-through
conclusion rests, were previously untested by this placebo and now pass it.

The per-outcome verdict list at the top of the incidence report states the
placebo result beside the pre-trend verdict, so the two tests of the same
assumption are read together. A consistency check asserts every outcome carrying
a verdict also carries a placebo result naming it, because an outcome licensed by
one test and untested by the other is a gap a reader cannot see.

**Two smaller things in the same pass.** `replication_protocol.md` recorded T4 as
"BLOCKED on data and on a structural module" when the data is official, and its
stamp carried a hardcoded Federal Register range — 2018-06-20 to 2019-05-10 —
that both predated the List 4A parse by two actions and described the wrong
period now that T2 and T3 report trade-based estimates. The period is the trade
sample; the legal range is derived from the schedule and recorded beside it.

### D-052 — Bounding the reclassification risk, and the check catching me doing it

M2's mitigation for product reclassification — the HS concordance engine and
`stable_code_sample()` — was named in the plan's risk table and called by nothing
in the pipeline, not even a test. Identifying *which* 10-digit codes were
renumbered needs a correlation table this project does not have, and guessing at
one would repeat D-011 and D-037. So the risk is bounded rather than closed.

**The bound.** The headline stacked design is re-estimated on codes with an
observation in every month of the window. A code present throughout cannot have
been introduced or retired inside it, so the subsample excludes every renumbering
candidate: 3,937 of 5,253 codes, 94.4% of customs value. It also excludes codes
merely untraded for a month, which makes it conservative rather than exact —
*observed throughout* is not the same claim as *definition stable*, and the
report says so.

| outcome | all codes | observed throughout | change |
|---|---|---|---|
| customs unit value | +0.0253 | **+0.0058** | −0.0195 |
| landed unit value | +0.1544 | **+0.1362** | −0.0182 |
| quantity | −0.3793 | **−0.3732** | +0.0061 |

**The point estimates hold**, and the customs unit value moves *toward* zero,
which supports the bound the incidence claim rests on rather than undermining it.

**The verdicts move in both directions and neither move is a change in kind.**
Landed goes CLEAN → NOISY_PRE_PERIOD_NO_SLOPE as its pre-to-post RMS ratio moves
0.157 → 0.241; quantity goes NOISY → CLEAN as its ratio moves 0.204 → 0.189. Both
are crossings of the same hand-set 0.20 cut, in opposite directions, on moves of
about ±0.05. A verdict that flips on that is a statement about the threshold, not
about the design, and reporting "quantity becomes clean" would be exactly the
over-reading this project's verdict taxonomy exists to prevent. What the numbers
show consistently is narrower and duller: dropping a quarter of the codes costs
precision, and the pre-period is where it shows first.

**The consistency step caught a regression I introduced while writing this.** The
robustness run legitimately writes `term=stacked_mean_post_effect` under
`control_definition=never_treated_products`, because it *is* the headline design
on a subsample. The report's headline selection matched on that pair alone, so it
silently picked up six rows instead of three and printed **+0.1362 and +0.0058 as
the incidence headline** — the robustness figures promoted over the real ones.
`INCIDENCE_HEADLINE_IS_TRACEABLE` (D-050) failed on the ambiguity within minutes
of my creating it, before the numbers reached anyone. Both the report selection
and the check now constrain on `rung`, and a test pins it.

That is the first time a check written for a past defect caught a live one. It is
also the argument for the check's shape: it does not verify a number, it verifies
that exactly one row answers the question the report asks.

### D-053 — The propagation power limit is resolved, and the answer is still no effect

D-041 recorded the domestic-propagation test as a power result rather than a
null, and said the detail-level run "may well still be 'no detectable effect' —
which would then be a result rather than a power limit." It is, and it is.

**256 clusters, against 22.** Every industry with a producer-price series enters,
including those with no tariff exposure: in a continuous-treatment design those
are legitimate controls, not a sample restriction.

| channel | summary β (t) | detail β (t) | detail 95% CI | bootstrap p |
|---|---|---|---|---|
| imported-input cost | +1.2295 (1.52) | **+0.1441** (1.37) | [−0.063, +0.351] | 0.167 |
| output protection | +0.3736 (1.83) | **+0.0416** (1.51) | [−0.013, +0.096] | 0.136 |
| downstream (Leontief) | +0.1642 (1.59) | **−0.0067** (−0.62) | [−0.028, +0.015] | 0.543 |

**What the data can now exclude.** At mean exposure the imported-input cost
channel is bounded within **[−0.14%, +0.81%]** of producer prices and output
protection within **[−0.10%, +0.74%]**. The summary-level interval on input cost
spanned roughly −1% to +9%. That is the difference between an interval that says
nothing and one that rules out anything larger than about one percent — which is
what makes this a bounded null rather than an absence of power, by the same
standard the pre-trend taxonomy applies to `PRECISE_NULL_EFFECT_BOUNDED`.

**What it does not do, recorded because dressing it up would be easy.** The
intervals narrowed roughly eightfold and the point estimates shrank by about the
same factor, so the **t-statistics barely moved**: 1.52 → 1.37 on input cost,
1.83 → 1.51 on protection. The finer axis bought precision in *economic* terms —
which magnitudes are excluded — not in statistical detectability. Had the
coefficient held near its summary-level value while the interval tightened, this
would read as a detected effect. It does not, and the report says so in those
words.

**The downstream channel is the cleanest null of the three**: tightly bounded,
now slightly negative, bootstrap p = 0.54. Whatever the Leontief chain
transmits over this window, it is not visible in producer prices at this
resolution.

**On interpretation.** Producer prices are one margin. An industry facing higher
input costs can absorb them in margins, substitute suppliers, or pass them
downstream, and only the last shows here. A bounded null on prices is not a
statement that tariffs had no domestic effect; it is a statement about this
outcome, at this resolution, over this window. No welfare claim follows and none
is made.

### D-054 — The structural module, built to the identification it actually has

M10 is built. What decided its shape was not ambition but what the data can
identify without putting the answer in by hand.

**One tier, across foreign sources.** The CES nest runs over source countries
within a product. By hat algebra the counterfactual needs only pre-treatment
expenditure shares and the tariff change — no price levels, no estimated demand
system, no domestic expenditure series. A two-tier nest including the domestic
alternative is **not identified from import data**: U.S. import statistics cannot
say how much of a fall in imports went to U.S. producers rather than out of
consumption, and assuming a domestic share would manufacture the number the model
was supposed to produce. The restriction is in the module docstring, the report
and the manifest, as scope rather than as an omission to be quietly filled later.

**No welfare number, and the guard stays on.** The exact CES price index says
what the imported bundle costs at the new tariff-inclusive prices allowing
substitution. That is a *component* of a welfare calculation, not a welfare
figure — it has no domestic nest, no revenue recycling and no labour market
behind it. `guard_language` continues to block welfare assertions under every
provenance, and building a structural module was not treated as licence to
weaken it.

**The premise is a finding, not an assumption.** The algebra holds foreign
producer prices fixed. In most settings that is assumed. Here the reduced-form
work established it: the customs unit value response is a bounded null, at most
0.076 log points. The two halves of the project are therefore *not* independent
readings of the same data, and the report says so where the outputs appear.

**Three routes to sigma, and they disagree in the direction theory predicts.**

| route | sigma |
|---|---|
| fitted to the observed sourcing reallocation | **4.25** |
| inverted from this project's PPML quantity response | **9.36** |
| calibrated grid | 1.5 – 8, reported in full |

The gap is a factor of 2.2 and it is the most informative thing here. A
reduced-form quantity coefficient absorbs two margins: substitution across
sources within a product, and the fall in the product's total imports. The
one-tier model contains only the first, so inverting the coefficient through it
attributes the outer margin to substitution and *must* overstate sigma. It does,
by roughly the amount that says how much of the import response was total demand
rather than reallocation between suppliers. Had the two agreed, that would have
been the surprise.

At the fitted sigma the model reproduces the observed treated-source share to
within 0.001 (0.2520 against 0.2534), which is unsurprising since that share is
what it was fitted to, and is reported as a fit statistic rather than as
validation.

**Two defects found while building it, both caught by contradiction with work
already in the repository.**

*A NaN that still looked like a result.* Products with zero value in a window
give 0/0 in a share. Polars returns NaN, NaN is not null, so `fill_null` left it
to propagate through every weighted mean downstream. The first run reported an
observed share of `NaN` and a fitted sigma of `NaN` — visible only because they
printed. The share is now null where undefined and the caller raises rather than
carrying a non-finite number forward.

*A weighting error that inverted the finding.* The observed treated share was
weighted by the treated country's **own** value in each product, while the model
side weighted by product totals. That over-weights the products the country
already dominated: it turned an observed share of about 0.19 into 0.49 and made
the model appear to have the sign of the reallocation backwards. It was caught
because it contradicted the diversion decomposition, which had China's share
falling. Both sides now weight by product totals, and a test pins the property
with a fixture where the two weightings differ by more than a factor of two.
