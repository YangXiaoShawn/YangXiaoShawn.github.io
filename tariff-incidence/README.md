# Tariff Incidence, Supply-Chain Reallocation, and Domestic Propagation

A reproducible research system measuring how U.S. product-level tariffs affect
import prices, landed costs, quantities, sourcing countries, supplier
concentration, and downstream domestic industries.

**Setting:** the 2018–2019 U.S. Section 301 actions against China. New tariff
episodes are added through configuration, not code.

## Public release

- [Source repository](https://github.com/YangXiaoShawn/open-economic-quant-tariff-incidence)
- [Permanent project page](https://yangxiaoshawn.github.io/projects/tariff-incidence/)
- [Versioned research package](https://huggingface.co/datasets/ShawnChamberlain/open-economic-quant-research-data/tree/main/TariffIncidence)
- [Interactive research explorer](https://huggingface.co/spaces/ShawnChamberlain/open-economic-quant-research-observatory)

The public GitHub repository contains code, tests, configuration, documentation,
small official excerpts used as fixtures, manifests, and generated narrative
reports. Large raw and analytical data remain excluded by `.gitignore`; the
repository records how to reconstruct them from the documented official sources.

> ### Read this before reading any number
>
> The pipeline runs on **official U.S. Census data** (provenance `OFFICIAL`).
> 923,440 HS10 × country × month observations, 2017-01 to 2020-02, covering all
> four Section 301 actions.
>
> Under a **stacked multi-wave design**, each outcome is licensed separately and
> the reports say which, first, before any number:
>
> | Outcome | Pre-trend verdict | Date placebo | Reading |
> |---|---|---|---|
> | landed unit value (duty-inclusive) | **CLEAN** | pass | causal reading supported |
> | customs unit value (tariff-exclusive) | **bounded near zero** (≤0.076) | pass | a finding, not a failure |
> | quantity | noisy pre-period, no slope | **fail** | qualified; read with care |
>
> Estimates are **intention-to-treat** with respect to the statutory list, and
> that is a property of published data rather than unfinished work: USTR grants
> exclusions at a finer granularity than import statistics are published, so the
> excluded share of a line is not observable at any parsing effort. The gap is
> bounded instead — realised duty falls short of the statutory schedule on 10.9%
> of Section 301-dutied value before the first exclusion and 20.0% after.

---

## Quick start

```bash
make setup
```

```bash
make reproduce-sample
```

That runs the whole pipeline — tariff schedule → panel → validation →
descriptives → replication → incidence → diversion → industry exposure →
reports — in a few minutes on a laptop, and writes to `reports/`.

To use official trade data:

```bash
export CENSUS_API_KEY=your_key_here && make build-trade-panel report
```

## What has actually been verified

### The Section 301 schedule reconciles exactly against the source notices

The parser anchors on the operative legal sentence (*"Heading 9903.88.0X applies
to all products of China that are classified in the following 8-digit
subheadings"*) rather than on page layout, and validates its output against the
line count each notice states in its own preamble:

| Action | Citation | Effective | Rate | Notice states | Parsed | Match |
|---|---|---|---|---|---|---|
| List 1 | 83 FR 28710 | 2018-07-06 | 25% | 818 | 818 | ✅ |
| List 2 | 83 FR 40823 | 2018-08-23 | 25% | 279 | 279 | ✅ |
| List 3 | 83 FR 47974 | 2018-09-24 | 10% | 5,745 | 5,734 full + 11 partial | ✅ |
| List 3 ↑ | 84 FR 20459 | 2019-05-10 | 25% | — | inherited | ✅ |
| List 4A | 84 FR 43304 | 2019-09-01 | 15% | — | 3,229 full + 4 partial | — |
| List 4A ↓ | 85 FR 3741 | 2020-02-14 | 7.5% | — | inherited | ✅ |

Reaching an exact match required three things a naive parse misses:

1. **Excluding Chapter 98/99 provisions.** 9802.00.80 and the 9903.88.0X
   headings are legal machinery, not targeted products. List 2 was over by one.
2. **Parsing partial statutory lines.** U.S. note 20(g) covers 11 HS8 lines
   *except* named 10-digit statistical numbers. List 3 was short by 11.
3. **Resolving one truncated code without guessing.** A code renders as
   `9033.00` with its final digits lost in typesetting. It is resolved only
   because the USITC HTS contains exactly one unclaimed 8-digit line under that
   heading, and the record is marked `DERIVED`, not `OFFICIAL_PARSED`.

### Estimates on official data, under a design that survives its own test

The single-wave event study failed for a structural reason: with one effective
date, **event time is calendar time** (event −12 *is* 2017-09), so
treated-group-specific time variation cannot be separated from treatment
dynamics. Country-by-month, chapter-by-month and month-of-year effects were all
tried; none removed it, one made it worse.

The fix is a **stacked design** — one sub-experiment per Section 301 wave,
controls drawn from never-treated products only, so no already-treated unit is
ever used as a control:

| Outcome | Mean post effect | Verdict |
|---|---|---|
| log landed unit value (duty-**inclusive**) | **+0.154** | **CLEAN** |
| log customs unit value (tariff-**exclusive**) | +0.025 | PRECISE_NULL, bounded at 0.076 |
| log quantity | −0.379 | NOISY_PRE_PERIOD_NO_SLOPE (qualified) |

### Incidence: who paid

The value-weighted additional duty actually in force on treated flows is
**17.7%**. If the exporter absorbed none of it, the duty-inclusive landed unit
value would rise by log(1.177) = **0.1626**. Observed: **+0.1544**.

But that figure is **not independent evidence** — the landed measure contains
the duty by construction, so most of its rise is arithmetic, and quoting it
alone is close to quoting the tariff rate back.

The behavioural quantity is the **customs unit value**, which falls only if the
exporter cuts its border price. It did not: the point estimate is +0.025,
slightly *positive*, and the effect is bounded at 0.076 in absolute value.

**The tariff was passed through to the U.S. importer close to in full over this
window, with no detectable exporter absorption.** It is the bound that carries
that claim.

A note on the verdicts: a relative-magnitude pre-trend test systematically
punishes an outcome whose true effect is near zero, because the denominator is
small. The customs unit value was mislabelled unusable for exactly that reason
until its pre-period was plotted against the landed measure's and found to be
identical (RMS 0.0183 against 0.0169, differing by a constant +0.010 — the MFN
duty). A near-null effect now gets a **bound** rather than a failing grade.

### Sourcing did not visibly relocate in this sample

Against a never-treated-product counterfactual, China ran **−$2.26bn/month**
below counterfactual on the targeted products. Third countries ran
**+$252mn/month above** their own counterfactual, giving an adjusted replacement
ratio of **0.11**: roughly a ninth of what China lost reappeared from other
suppliers within this window.

Substitutability was worst where exposure was largest. Splitting products by
pre-tariff dependence on China, those the U.S. relied on most replaced **14%** of
the lost value from elsewhere; those it relied on least replaced **57%**.

Read with its caveats: 10 chapters, 8 partners, and a counterfactual doing real
work. A third-country increase in customs data is also consistent with rerouting
and origin misdeclaration, which these statistics cannot separate from relocated
production.

### Estimator validation against a known data-generating process

Still run, via `--force-synthetic`, because knowing the right answer is the only
way to test an estimator. It surfaced a design problem: third-country suppliers
of a treated product are **not untreated bystanders**, so using them as controls
violates no-interference and biased the quantity elasticity by 26% while leaving
the price elasticity untouched. Both control groups are now reported on every
run.

### Industries are exposed through two channels that are never netted

Using pre-treatment BEA input-output weights: at the summary level 19 of 71
industries face **both** output protection and higher imported-input costs at
once; at BEA's detail level, **144 of 402**. The coarser axis was averaging the
distinction away — inside the single summary industry `3361MV`, travel trailer
manufacturing carries protection 0.250 while motor home manufacturing carries
0.000. A
single "net exposure" number would hide exactly the distributional question the
analysis exists to answer, so the column that computes it is named
`net_contrast_do_not_use_alone`.

## Design commitments

These are enforced by code and tests, not by good intentions.

**Ambiguity is surfaced, never resolved silently.** The tariff engine returns a
`ValidationStatus` with every answer. Conflicting records return no rate at all.
Working at HS10 removes the ambiguity rather than papering over it: **0 of
923,440 observations** carry an unusable status, because HS10 nests exactly
inside the HS8 line the statute names, and the 11 partial lines are resolved
against the specific 10-digit numbers U.S. note 20(g) carves out.

**Value concepts stay distinct.** `customs_unit_value` (tariff-exclusive) and
`landed_unit_value_duty_inclusive` answer different questions; incidence cannot
be read without both. Neither is ever called a price — a unit value is
value-over-quantity across a heterogeneous bundle.

**Announcement ≠ effective.** Both are carried through the pipeline. The List 3
increase to 25% was announced for 2019-01-01, postponed twice, and took effect
2019-05-10; conflating the dates would misplace the shock by seven months.

**Mid-month effective dates are day-weighted.** List 3 took effect on 24
September — 7 of 30 days. Month-start assessment says untreated, month-end says
fully treated, and both errors land on the event-time-zero coefficient.

**Nulls are never filled silently.** A line whose column-1 general rate is
compound or specific has no single ad-valorem baseline; those rows (42.5% of the
panel) carry a null, not a zero. An earlier version filled them and attenuated
every total-rate estimate. Census's own "no quantity collected" convention
(`UNIT_QY1 = "-"`, quantity 0) is likewise read as null, not as zero — treating
it as zero would make those unit values infinite.

**Reports cannot make claims the data cannot support.** `guard_language` raises
on causal assertions under non-official provenance and on quantified welfare
claims under any provenance, and it runs on every generated report. It caught
two of this project's own sentences during development; both were rephrased.

**Contradicting evidence is reported.** `reports/failed_hypotheses.md` is
generated from the pipeline, not curated.

## Repository layout

```
src/tariff_incidence/
  adapters/      Federal Register, USITC HTS, Census, BEA; fetch and parse split
  tariff/        records, point-in-time policy engine, schedule builder
  concordance/   versioned HS mappings (stable-code + weighted samples)
  panel/         analytical panel; synthetic generator
  quality/       12-check data-quality battery
  econ/          HDFE absorption, OLS, PPML, designs, diversion
  io_exposure/   BEA-based industry exposure
  reporting/     rendering + the claim guard
config/          episodes, samples, concordances
data/            raw → staged → normalized → analytical → results
reports/         GENERATED — never edit by hand
```

## Documentation

| Document | What it covers |
|---|---|
| [AGENTS.md](AGENTS.md) | Rules for anyone working in the repo |
| [docs/RESEARCH_DESIGN.md](docs/RESEARCH_DESIGN.md) | Identification, estimands, what would falsify them |
| [docs/PROJECT_PLAN.md](docs/PROJECT_PLAN.md) | Milestones, acceptance tests, risk register |
| [docs/DECISION_LOG.md](docs/DECISION_LOG.md) | Every non-obvious choice and what it costs |
| [data/DATA_ACCESS.md](data/DATA_ACCESS.md) | Source-by-source access status |
| [data/DATA_DICTIONARY.md](data/DATA_DICTIONARY.md) | Every column, precisely defined |
| [STATUS.md](STATUS.md) | Current state |

## Commands

```bash
make help
```

`setup` · `download-sample` · `build-tariff-schedule` · `build-trade-panel` ·
`validate-data` · `descriptive` · `replicate` · `estimate-incidence` ·
`estimate-diversion` · `build-io-exposure` · `build-io-exposure-detail` ·
`estimate-propagation` · `estimate-propagation-detail` · `structural` ·
`check-consistency` · `test` · `lint` · `typecheck` · `reproduce-sample` ·
`report` · `dashboard`

## Known gaps

| Gap | Consequence |
|---|---|
| **No domestic output or price series** | A fall in imports cannot be split between domestic substitution and lower demand. The binding constraint now, and why the structural model has no domestic nest. |
| Quantity's pre-period is noisy and it fails the date placebo | Sourcing and diversion results carry a qualified reading, not a clean causal one |
| Product exclusions cannot be mapped to statistical lines | Estimates are intention-to-treat; the gap is bounded (10.9% → 20.0%), not closed |
| Product reclassification | 800 codes enter and 596 leave mid-window, 5.7% of value; bounded by re-running on codes observed throughout, not identified |
| USITC HTS serves current vintage | Baseline MFN rates come from a later vintage than the HTS2018 lists |
| Structural model is one tier | Sourcing across foreign suppliers only. **No welfare number exists**, by construction |
| BLS PPI daily request allowance | Detail-level propagation needs a quota window; results cached per series per year |

Requires Python 3.12. Runs on Apple Silicon in ~16 GB; no GPU.
