# Research Conclusions

> **DATA PROVENANCE: OFFICIAL SOURCES**
>
> All figures below derive from official statistical or legal sources.
>
> run_id `20260811T201708Z-b1495fb3` · git `3c51a06-dirty` · config `sample_slice.yaml` (sha256 `b1495fb3b363`) · data period 2017-01 to 2020-02 · generated 2026-08-11T20:17:08.149704+00:00


What the project concludes, each claim with the evidential status that licenses it. Generated from the result tables, so no figure here can drift from the estimate behind it.

## 1. The tariff was paid by the importer, not the exporter

The value-weighted additional duty actually in force on treated flows was **17.7%**. Had the exporter absorbed none of it, the duty-inclusive landed unit value would have risen by log(1+tau) = **0.1626**. It rose by **+0.1544**.

That figure alone proves nothing: the landed measure contains the duty by construction, so most of its rise is arithmetic. The behavioural quantity is the **customs unit value**, the tariff-exclusive price at the foreign border, which falls only if the exporter cuts its price. It did not — the estimate is **+0.0253**, slightly *positive*, and bounded at **0.076** log points in absolute value. It is that bound, not the landed figure, that carries the conclusion.

**Status: strongest claim in the project.** The landed outcome is CLEAN on its pre-trend test and passes the date placebo; the customs outcome is a bounded null and also passes. Both survive re-estimation on codes observed throughout the window, and the customs response moves closer to zero when they do.

## 2. Sourcing left China and mostly did not arrive anywhere else

Against a never-treated-product counterfactual, imports from the treated country ran **$2.26bn per month** below where they would otherwise have been. Third countries ran **$252mn per month above** theirs — an adjusted replacement ratio of **0.11**. Roughly a ninth of what left the treated country reappeared from other suppliers inside this window.

Substitutability was worst exactly where exposure was largest. Products the United States relied on the treated country for most replaced **14%** of the lost value from elsewhere; those it relied on least replaced **57%**.

**Status: qualified.** The quantity outcome's pre-period is noisy and it fails the date placebo, so this is read as a strong descriptive pattern with a qualified causal reading rather than a clean one. A third-country increase in customs data is also consistent with rerouting and origin misdeclaration, which these statistics cannot separate from relocated production.

## 3. Protection and input cost land on the same industries

Of 402 industries at BEA's detail level, **144** face tariff protection on their output *and* higher costs on their imported inputs at the same time. At the 71-industry summary level the count is 19: the coarser axis was averaging the distinction away.

The two channels are never netted, and they are not comparable as levels: protection is the statutory rate on one commodity, input cost is diluted across a purchase basket that is mostly untariffed.

**Status: accounting, not estimation.** These are constructs from pre-treatment input-output weights. They say which industries are positioned to be helped or hurt, not by how much.

## 4. It does not show up in domestic producer prices

Tested on 256 industries with a matched producer-price series. All three exposure channels remain statistically indistinguishable from zero, and at this resolution that is a **result rather than a limitation**: at mean exposure the imported-input cost channel is bounded within **[−0.14%, +0.81%]** of producer prices and output protection within **[−0.10%, +0.74%]**. The summary-level interval spanned roughly −1% to +9% and excluded nothing.

**Status: a bounded null on one margin.** Producer prices are one place a cost shock can go. An industry can absorb it in margins or substitute suppliers instead of passing it on, and neither is visible here. This is a statement about this outcome at this resolution over this window.

## 5. What the model adds, and what it refuses to say

A one-tier Armington nest across foreign sources reproduces the observed reallocation at an elasticity of about **4.25**. Inverting the project's own quantity estimate through the same model gives **9.36** — a gap in the direction theory predicts, because a quantity coefficient absorbs the fall in a product's total imports as well as substitution between its suppliers, and this model contains only the second. The size of that gap is a rough measure of how much of the import response was total demand rather than reallocation.

**No welfare number exists anywhere in this project**, and none can be derived from these outputs. The model has no domestic nest, because U.S. import statistics cannot say whether displaced imports went to domestic producers or out of consumption; it has no revenue recycling and no labour market. The guard that blocks welfare claims in generated prose remains in force, and building the model was not treated as licence to weaken it.

## 6. What this data cannot answer, stated as findings

- **Whether domestic producers gained.** Import data cannot separate domestic substitution from lower final demand. This is the binding constraint on everything the project could not answer, and the reason the structural model stops where it does.

- **How much of the statutory tariff was actually collected.** Exclusions are granted at a finer granularity than import statistics are published, so the excluded share of a line is not observable at any parsing effort. Bounded instead: realised duty falls short of the statutory schedule on **10.9%** of Section 301-dutied value before the first exclusion and **20.0%** after, and the difference is an upper bound because preference programmes leave the same signature.

- **Whether third-country gains are real production.** Rerouting, transshipment and origin misdeclaration produce the same pattern in customs data.

- **Which products were renumbered mid-window.** 800 codes enter and 596 leave, 5.7% of customs value. Bounded by re-estimating on codes observed throughout; not identified, which would need a correlation table this project does not have.

- **The exchange-rate channel.** RMB depreciation moves customs unit values in the same direction as exporter absorption and is not separated here.

---

## Reproducibility

- run id: `20260811T201708Z-b1495fb3`
- git commit: `3c51a06-dirty`
- configuration: `sample_slice.yaml` (sha256 `b1495fb3b363c158ae3b162babd17a515adfc9a8c26038b6c09edb9ec55652a3`)
- data provenance: `OFFICIAL`
- data period: 2017-01 to 2020-02
- generated: 2026-08-11T20:17:08.149704+00:00
- python 3.12.13 on macOS-26.6.1-arm64-arm-64bit

_This document is generated by `scripts/generate_reports.py`. Do not edit it by hand; edit the generator or the underlying result tables._
