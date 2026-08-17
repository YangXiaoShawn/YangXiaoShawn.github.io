# Structural Counterfactuals

> **DATA PROVENANCE: OFFICIAL SOURCES**
>
> All figures below derive from official statistical or legal sources.
>
> run_id `20260811T201708Z-b1495fb3` · git `3c51a06-dirty` · config `sample_slice.yaml` (sha256 `b1495fb3b363`) · data period 2017-01 to 2020-02 · generated 2026-08-11T20:17:08.149704+00:00


A one-tier Armington sourcing model, its calibration, and what it implies. Every model output is labelled as such.

## What this model is, and what it is not

A **one-tier CES nest across foreign source countries** within a product. It says how import sourcing should have reallocated given the tariff, and what the imported bundle cost.

It has **no domestic nest**, and that is a restriction stated rather than a gap to be filled quietly. U.S. import statistics cannot say how much of a fall in imports went to domestic producers rather than out of consumption, so assuming a domestic share would put the answer in by hand. **No welfare number is produced**, none can be derived from these outputs alone, and the guard that blocks welfare claims in this project's prose remains in force.

The counterfactual holds foreign producer prices fixed, so the tariff passes into the buyer's price one-for-one. Normally that is an assumption. Here it is a **finding**: the reduced-form response of the customs unit value — the tariff-exclusive foreign border price — is a bounded null, at most 0.076 log points. The structural and reduced-form parts are therefore not independent readings of the same data; the second supplies a premise of the first.

## Where the elasticity comes from

It is not estimated inside the model and it is never invented. It arrives three ways, reported together because their agreement is the informative quantity:

1. a **calibrated grid**, supplied by configuration;
2. **inverted from this project's own PPML quantity response**, which identifies sigma directly;
3. **fitted to the observed reallocation** of sourcing away from the treated country.

Routes 2 and 3 use different outcomes and different machinery, and they **disagree by a factor of about 2.2**: 4.25 fitted to shares against 9.36 inverted from quantities.

**The direction of that gap is what theory predicts, which is the point of reporting it.** A reduced-form quantity coefficient absorbs two margins at once: substitution across sources within a product, and the fall in total imports of the product. This one-tier model has only the first, so inverting the coefficient through it attributes the outer margin to substitution and must overstate sigma. It does. The gap between the two routes is a rough measure of how much of the import response was the total demand margin rather than reallocation between suppliers — the margin this model deliberately does not contain.

## Model-implied sourcing reallocation and import bundle cost

`treated_share_model` is **model-implied**. `treated_share_observed` is a data moment and is printed beside it so the two are never confused. `log_import_bundle_cost_change` is the exact CES price index of the imported bundle: the cost of buying the same basket at the new tariff-inclusive prices, allowing substitution. It is a component of a welfare calculation, not a welfare number, and the model that would turn it into one has not been built.

**counterfactual**

| sigma | sigma_source | parameter_type | treated_share_pre | treated_share_model | treated_share_observed | log_import_bundle_cost_change |
| --- | --- | --- | --- | --- | --- | --- |
| 1.5000 | calibrated grid | CALIBRATED | 0.3171 | 0.3065 | 0.2534 | 0.0503 |
| 2.0000 | calibrated grid | CALIBRATED | 0.3171 | 0.2962 | 0.2534 | 0.0494 |
| 3.0000 | calibrated grid | CALIBRATED | 0.3171 | 0.2760 | 0.2534 | 0.0476 |
| 4.0000 | calibrated grid | CALIBRATED | 0.3171 | 0.2567 | 0.2534 | 0.0459 |
| 6.0000 | calibrated grid | CALIBRATED | 0.3171 | 0.2207 | 0.2534 | 0.0427 |
| 8.0000 | calibrated grid | CALIBRATED | 0.3171 | 0.1882 | 0.2534 | 0.0397 |
| 9.3559 | inverted from PPML quantity response | MODEL_IMPLIED | 0.3171 | 0.1682 | 0.2534 | 0.0378 |
| 4.2500 | fitted to observed reallocation | MODEL_IMPLIED | 0.3171 | 0.2520 | 0.2534 | 0.0455 |


## Data moments, estimates, calibrated parameters, model outputs

The brief requires these four to be separated rather than mixed into a single table of results. Every row says which it is.

**parameter ledger**

| quantity | value | parameter_type | source |
| --- | --- | --- | --- |
| pre-treatment sourcing shares |  | DATA_MOMENT | trade panel, event months < 0 |
| post-period additional tariff rate |  | DATA_MOMENT | tariff engine; statutory schedule |
| observed treated-source share, post | 0.2534 | DATA_MOMENT | trade panel, event months >= 0 |
| PPML quantity response to log(1+tariff) | -1.7244 | ESTIMATED | this project, rung 5 |
| customs unit value response (bounded null) |  | ESTIMATED | this project, stacked design -- supplies the fixed-foreign-price premise |
| elasticity of substitution sigma |  | CALIBRATED | grid [1.5, 2.0, 3.0, 4.0, 6.0, 8.0], supplied by configuration; not estimated here |
| counterfactual sourcing shares |  | MODEL_IMPLIED | CES hat algebra |
| import bundle cost change |  | MODEL_IMPLIED | exact CES price index |


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
