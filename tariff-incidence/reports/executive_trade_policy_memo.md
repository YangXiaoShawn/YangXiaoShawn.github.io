# Executive Trade-Policy Memo

> **DATA PROVENANCE: OFFICIAL SOURCES**
>
> All figures below derive from official statistical or legal sources.
>
> run_id `20260811T201708Z-b1495fb3` · git `3c51a06-dirty` · config `sample_slice.yaml` (sha256 `b1495fb3b363`) · data period 2017-01 to 2020-02 · generated 2026-08-11T20:17:08.149704+00:00


A short answer to each policy question this project was built to address, with the evidential status of each answer stated rather than implied.

## Questions and answers

**Who appears to bear the tariff?**

See the incidence table: compare the customs unit value response (exporter absorption) with the duty-inclusive landed unit value response (importer cost).

In this run the customs unit value coefficient is +0.0138 [95% CI -0.0903, +0.1178] (interval includes zero, so the sign is not resolved) and the duty-inclusive landed unit value coefficient is +0.7424 [95% CI +0.6382, +0.8465]***.

**How much sourcing moved away from the treated country?**

Treated-country imports of the targeted products changed by -2,073,786,984 in monthly-average customs value (-31.3% of the pre-period level). Against a never-treated-product counterfactual, the largest third-country gains were: 5800 (+653,182,583), 5880 (+195,418,686), 5590 (+41,555,445).

**Which alternative countries gained?**

Treated-country imports of the targeted products changed by -2,073,786,984 in monthly-average customs value (-31.3% of the pre-period level). Against a never-treated-product counterfactual, the largest third-country gains were: 5800 (+653,182,583), 5880 (+195,418,686), 5590 (+41,555,445).

A third-country increase in customs data is consistent with relocated production, with rerouting of treated-origin goods, and with origin misdeclaration. Customs statistics cannot separate these.

**Which U.S. industries received protection?**

0 industries show output protection without material input-cost exposure; 29 face input-cost exposure without protection; **19 face both at once**, including Motor vehicles, bodies and trailers, and parts, Plastics and rubber products, Paper products, Machinery. These are accounting constructs from pre-treatment input-output weights, not estimates: they say which industries are positioned to be helped or hurt, not by how much. Protection and input cost are also not comparable as levels -- protection carries one commodity's statutory rate while input cost is averaged over a purchase basket that is mostly untariffed.

**Which U.S. industries faced higher input costs?**

See the imported-input cost exposure table in `supply_chain_propagation.md`. The industries with the largest input-cost exposure are mostly the same manufacturing sectors that also receive protection, which is why the two channels are never netted.

**Which conclusions are causal?**

Outcome by outcome, according to each one's own pre-trend test:

- `log_customs_unit_value`: **PRECISE_NULL_EFFECT_BOUNDED** under the stacked multi-wave design -> **the effect is bounded near zero**. The post-treatment path does not rise clear of the pre-period noise, so the design cannot separate the effect from zero — which for a near-null outcome is a finding, not a failure. Taking the observed path and the slope bias together, the effect is at most 0.076 log points in absolute value. It **passes the date placebo**: a treatment date moved 12 months earlier on pre-period data alone produces nothing significant (max |post| 0.0351).
- `log_landed_unit_value`: **CLEAN** under the stacked multi-wave design -> a causal reading is supported by this test. It **passes the date placebo**: a treatment date moved 12 months earlier on pre-period data alone produces nothing significant (max |post| 0.0349).
- `log_quantity`: **NOISY_PRE_PERIOD_NO_SLOPE** under the stacked multi-wave design -> **a qualified causal reading** — no differential trend is detectable, but the pre-period is noisy, so the estimate is less precise than the interval alone suggests. The pre-period slope is not statistically distinguishable from zero; extrapolated across the post window it would shift the estimate by +0.033 against a post-treatment RMS of 0.418. It also **fails the date placebo**: moving the treatment date 12 months earlier on pre-period data alone still produces a significant coefficient (max |post| 0.0934), which is the same differential trend showing up a second way.
- `stable_codes_log_customs_unit_value`: **PRECISE_NULL_EFFECT_BOUNDED** under the single-wave design -> **the effect is bounded near zero**. The post-treatment path does not rise clear of the pre-period noise, so the design cannot separate the effect from zero — which for a near-null outcome is a finding, not a failure.
- `stable_codes_log_landed_unit_value`: **NOISY_PRE_PERIOD_NO_SLOPE** under the single-wave design -> **a qualified causal reading** — no differential trend is detectable, but the pre-period is noisy, so the estimate is less precise than the interval alone suggests.
- `stable_codes_log_quantity`: **CLEAN** under the single-wave design -> a causal reading is supported by this test.

Every estimate is intention-to-treat with respect to the statutory list, and that is a property of the published data rather than an outstanding task: exclusions are granted at a finer granularity than U.S. import statistics are published, so the excluded share of a reporting number is not observable at any parsing effort. The gap is bounded instead of closed: observations whose realised duty falls short of the statutory schedule are 10.9% of dutiable observations before the first exclusion took effect (2018-12-01) and 20.0% after. The difference is what exclusions plausibly add; the pre-exclusion level is what other causes account for.

**Which conclusions are descriptive or model-dependent?**

The sourcing shares, supplier concentration and entry/exit counts are descriptive. The industry exposure measures are constructed from pre-treatment input-output weights and the official Census concordance; they are accounting constructs, not estimates. No structural counterfactual has been run, so no model-implied welfare number exists in this project.

**What evidence would change the recommendation?**

- A resolution of the exclusion gap from a source other than the notices. The annexes are raster images and 98% of exclusions name a subset of a statistical reporting number, so the intention-to-treat gap is currently bounded rather than closed.
- Domestic output and price data, without which a fall in imports cannot be attributed to domestic substitution rather than lower demand. This is now the binding one.

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
