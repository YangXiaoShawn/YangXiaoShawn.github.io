# Tariff Incidence — Results

> **DATA PROVENANCE: OFFICIAL SOURCES**
>
> All figures below derive from official statistical or legal sources.
>
> run_id `20260811T201708Z-b1495fb3` · git `3c51a06-dirty` · config `sample_slice.yaml` (sha256 `b1495fb3b363`) · data period 2017-01 to 2020-02 · generated 2026-08-11T20:17:08.149704+00:00


Estimates of how the additional duty maps into customs unit values, duty-inclusive landed unit values, quantities and trade values. The customs unit value is tariff-exclusive and is a proxy for the foreign border price; it is a value-over-quantity ratio across a heterogeneous bundle of transactions and is **not** a transaction price. The duty-inclusive landed unit value is what the U.S. importer faces at the border, excluding freight. Reading incidence requires both.

## Which of these outcomes survives its own pre-trend test

The parallel-trends assumption is tested per outcome, and it does not hold uniformly. The verdict below governs how each result may be read; it is placed first so it cannot be skipped.

- `log_customs_unit_value`: **PRECISE_NULL_EFFECT_BOUNDED** under the stacked multi-wave design -> **the effect is bounded near zero**. The post-treatment path does not rise clear of the pre-period noise, so the design cannot separate the effect from zero — which for a near-null outcome is a finding, not a failure. Taking the observed path and the slope bias together, the effect is at most 0.076 log points in absolute value. It **passes the date placebo**: a treatment date moved 12 months earlier on pre-period data alone produces nothing significant (max |post| 0.0351).
- `log_landed_unit_value`: **CLEAN** under the stacked multi-wave design -> a causal reading is supported by this test. It **passes the date placebo**: a treatment date moved 12 months earlier on pre-period data alone produces nothing significant (max |post| 0.0349).
- `log_quantity`: **NOISY_PRE_PERIOD_NO_SLOPE** under the stacked multi-wave design -> **a qualified causal reading** — no differential trend is detectable, but the pre-period is noisy, so the estimate is less precise than the interval alone suggests. The pre-period slope is not statistically distinguishable from zero; extrapolated across the post window it would shift the estimate by +0.033 against a post-treatment RMS of 0.418. It also **fails the date placebo**: moving the treatment date 12 months earlier on pre-period data alone still produces a significant coefficient (max |post| 0.0934), which is the same differential trend showing up a second way.
- `stable_codes_log_customs_unit_value`: **PRECISE_NULL_EFFECT_BOUNDED** under the single-wave design -> **the effect is bounded near zero**. The post-treatment path does not rise clear of the pre-period noise, so the design cannot separate the effect from zero — which for a near-null outcome is a finding, not a failure.
- `stable_codes_log_landed_unit_value`: **NOISY_PRE_PERIOD_NO_SLOPE** under the single-wave design -> **a qualified causal reading** — no differential trend is detectable, but the pre-period is noisy, so the estimate is less precise than the interval alone suggests.
- `stable_codes_log_quantity`: **CLEAN** under the single-wave design -> a causal reading is supported by this test.

## Incidence: who paid

The value-weighted additional duty actually in force on treated flows is **17.7%**. If the exporter absorbed none of it, the duty-inclusive landed unit value would rise by log(1+tau) = **0.1626**.

Observed, as the mean post-treatment coefficient of the stacked design with never_treated_products controls: landed unit value **+0.1544**, customs (tariff-exclusive) unit value **+0.0253**, bounded at 0.076 in absolute value.

The landed measure contains the duty by construction, so its rise is partly arithmetic and is not independent evidence. The behavioural quantity is the **customs unit value**, which falls only if the exporter cuts its border price. It did not: the point estimate is slightly *positive* and the effect is bounded near zero.

Read together, the tariff was passed through to the U.S. importer close to in full over this window, with no detectable exporter absorption. The bound is what carries this claim; the landed figure alone would not.

## Rung 2 — two-way fixed-effects regressions

- **log customs unit value (TARIFF-EXCLUSIVE; foreign border price proxy, not a transaction price)** — `additional_tariff_rate` +0.0138 [95% CI -0.0903, +0.1178] (interval includes zero, so the sign is not resolved), n = 600,283, FE: flow_id|month_key, clustered on hs6
- **log landed unit value (DUTY-INCLUSIVE, excludes freight; U.S. importer border cost)** — `additional_tariff_rate` +0.7424 [95% CI +0.6382, +0.8465]***, n = 600,283, FE: flow_id|month_key, clustered on hs6
- **log import quantity (primary quantity unit)** — `additional_tariff_rate` -1.8340 [95% CI -2.0217, -1.6463]***, n = 600,283, FE: flow_id|month_key, clustered on hs6
- **log customs value** — `additional_tariff_rate` -1.8956 [95% CI -2.0459, -1.7453]***, n = 713,435, FE: flow_id|month_key, clustered on hs6

**estimates**

| outcome | term | estimate | std_error | ci_low | ci_high | p_value | n_obs |
| --- | --- | --- | --- | --- | --- | --- | --- |
| log_customs_unit_value | additional_tariff_rate | 0.0138 | 0.0530 | -0.0903 | 0.1178 | 0.7954 | 600283 |
| log_landed_unit_value | additional_tariff_rate | 0.7424 | 0.0531 | 0.6382 | 0.8465 | 0.0000 | 600283 |
| log_quantity | additional_tariff_rate | -1.8340 | 0.0957 | -2.0217 | -1.6463 | 0.0000 | 600283 |
| log_customs_value | additional_tariff_rate | -1.8956 | 0.0766 | -2.0459 | -1.7453 | 0.0000 | 713435 |


## Rung 5 — PPML on trade flows in levels

- **customs_value (levels, PPML; full sample)** — `log1p_additional_tariff` -2.1971 [95% CI -2.8600, -1.5342]***, n = 923,440, FE: flow_id|month_key, clustered on hs6
- **quantity (levels, PPML; full sample)** — `log1p_additional_tariff` -1.7244 [95% CI -3.4993, +0.0505]* (interval includes zero, so the sign is not resolved), n = 921,390, FE: flow_id|month_key, clustered on hs6
- **customs_value (levels, PPML; subsample with an ad valorem MFN baseline)** — `log1p_total_tariff` -2.5108 [95% CI -3.2613, -1.7604]***, n = 585,510, FE: flow_id|month_key, clustered on hs6
- **quantity (levels, PPML; subsample with an ad valorem MFN baseline)** — `log1p_total_tariff` -1.4559 [95% CI -3.4039, +0.4921] (interval includes zero, so the sign is not resolved), n = 584,754, FE: flow_id|month_key, clustered on hs6

**estimates**

| outcome | term | estimate | std_error | ci_low | ci_high | p_value | n_obs |
| --- | --- | --- | --- | --- | --- | --- | --- |
| customs_value | log1p_additional_tariff | -2.1971 | 0.3380 | -2.8600 | -1.5342 | 0.0000 | 923440 |
| quantity | log1p_additional_tariff | -1.7244 | 0.9048 | -3.4993 | 0.0505 | 0.0569 | 921390 |
| customs_value | log1p_total_tariff | -2.5108 | 0.3826 | -3.2613 | -1.7604 | 0.0000 | 585510 |
| quantity | log1p_total_tariff | -1.4559 | 0.9930 | -3.4039 | 0.4921 | 0.1428 | 584754 |


## Rung 6 — heterogeneity

- **log quantity -- high_pretreatment_dependence (split at median 0.368)** — `additional_tariff_rate` -2.2809 [95% CI -2.5399, -2.0219]***, n = 285,106, FE: flow_id|month_key, clustered on hs6
- **log quantity -- low_pretreatment_dependence (split at median 0.368)** — `additional_tariff_rate` -1.4262 [95% CI -1.6854, -1.1670]***, n = 308,090, FE: flow_id|month_key, clustered on hs6

**estimates**

| outcome | term | estimate | std_error | ci_low | ci_high | p_value | n_obs |
| --- | --- | --- | --- | --- | --- | --- | --- |
| log_quantity | additional_tariff_rate | -2.2809 | 0.1320 | -2.5399 | -2.0219 | 0.0000 | 285106 |
| log_quantity | additional_tariff_rate | -1.4262 | 0.1321 | -1.6854 | -1.1670 | 0.0000 | 308090 |


## Event study — log_customs_unit_value (reference period −1)

Coefficients are relative to event month −1. Pre-period coefficients are the test of the design, not decoration.

**coefficients**

| event_time | estimate | std_error | ci_low | ci_high | p_value | is_pre |
| --- | --- | --- | --- | --- | --- | --- |
| -12 | -0.0147 | 0.0224 | -0.0586 | 0.0293 | 0.5122 | yes |
| -11 | -0.0149 | 0.0229 | -0.0598 | 0.0300 | 0.5148 | yes |
| -10 | 0.0000 | 0.0214 | -0.0421 | 0.0421 | 0.9994 | yes |
| -9 | -0.0195 | 0.0215 | -0.0618 | 0.0227 | 0.3638 | yes |
| -8 | -0.0083 | 0.0226 | -0.0526 | 0.0359 | 0.7122 | yes |
| -7 | -0.0239 | 0.0225 | -0.0680 | 0.0203 | 0.2897 | yes |
| -6 | 0.0329 | 0.0220 | -0.0103 | 0.0761 | 0.1357 | yes |
| -5 | 0.0133 | 0.0207 | -0.0273 | 0.0539 | 0.5197 | yes |
| -4 | 0.0137 | 0.0217 | -0.0288 | 0.0562 | 0.5273 | yes |
| -3 | -0.0022 | 0.0200 | -0.0415 | 0.0371 | 0.9134 | yes |
| -2 | -0.0164 | 0.0203 | -0.0563 | 0.0234 | 0.4186 | yes |
| -1 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |  | yes |
| 0 | 0.0002 | 0.0207 | -0.0404 | 0.0408 | 0.9921 | no |
| 1 | 0.0144 | 0.0198 | -0.0244 | 0.0532 | 0.4657 | no |
| 2 | 0.0178 | 0.0221 | -0.0255 | 0.0610 | 0.4211 | no |
| 3 | -0.0161 | 0.0215 | -0.0582 | 0.0260 | 0.4537 | no |
| 4 | -0.0091 | 0.0235 | -0.0552 | 0.0370 | 0.6992 | no |
| 5 | 0.0204 | 0.0232 | -0.0251 | 0.0659 | 0.3792 | no |
| 6 | 0.0491 | 0.0252 | -0.0004 | 0.0986 | 0.0519 | no |
| 7 | 0.0369 | 0.0227 | -0.0077 | 0.0816 | 0.1046 | no |
| 8 | 0.0334 | 0.0250 | -0.0156 | 0.0823 | 0.1815 | no |
| 9 | -0.0144 | 0.0244 | -0.0622 | 0.0334 | 0.5542 | no |
| 10 | -0.0034 | 0.0238 | -0.0501 | 0.0434 | 0.8877 | no |
| <= -13 (binned) | -0.0013 | 0.0186 | -0.0377 | 0.0352 | 0.9462 | yes |
| >= +11 (binned) | -0.0089 | 0.0202 | -0.0485 | 0.0306 | 0.6577 | no |


## Event study — log_customs_unit_value (reference period −3)

Coefficients are relative to event month −3. Pre-period coefficients are the test of the design, not decoration.

**coefficients**

| event_time | estimate | std_error | ci_low | ci_high | p_value | is_pre |
| --- | --- | --- | --- | --- | --- | --- |
| -12 | -0.0125 | 0.0220 | -0.0556 | 0.0306 | 0.5691 | yes |
| -11 | -0.0127 | 0.0215 | -0.0549 | 0.0294 | 0.5533 | yes |
| -10 | 0.0022 | 0.0211 | -0.0393 | 0.0437 | 0.9173 | yes |
| -9 | -0.0174 | 0.0216 | -0.0596 | 0.0249 | 0.4205 | yes |
| -8 | -0.0061 | 0.0218 | -0.0490 | 0.0367 | 0.7782 | yes |
| -7 | -0.0217 | 0.0231 | -0.0669 | 0.0236 | 0.3475 | yes |
| -6 | 0.0351 | 0.0223 | -0.0087 | 0.0789 | 0.1164 | yes |
| -5 | 0.0155 | 0.0206 | -0.0250 | 0.0560 | 0.4526 | yes |
| -4 | 0.0159 | 0.0207 | -0.0247 | 0.0564 | 0.4426 | yes |
| -3 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |  | yes |
| -2 | -0.0142 | 0.0207 | -0.0549 | 0.0264 | 0.4922 | yes |
| -1 | 0.0022 | 0.0200 | -0.0371 | 0.0415 | 0.9134 | yes |
| 0 | 0.0024 | 0.0214 | -0.0395 | 0.0443 | 0.9112 | no |
| 1 | 0.0166 | 0.0211 | -0.0249 | 0.0581 | 0.4322 | no |
| 2 | 0.0199 | 0.0236 | -0.0264 | 0.0663 | 0.3989 | no |
| 3 | -0.0139 | 0.0226 | -0.0582 | 0.0304 | 0.5381 | no |
| 4 | -0.0069 | 0.0231 | -0.0522 | 0.0384 | 0.7649 | no |
| 5 | 0.0226 | 0.0239 | -0.0243 | 0.0694 | 0.3449 | no |
| 6 | 0.0513 | 0.0260 | 0.0002 | 0.1024 | 0.0491 | no |
| 7 | 0.0391 | 0.0242 | -0.0084 | 0.0867 | 0.1066 | no |
| 8 | 0.0355 | 0.0245 | -0.0125 | 0.0836 | 0.1472 | no |
| 9 | -0.0122 | 0.0252 | -0.0617 | 0.0373 | 0.6278 | no |
| 10 | -0.0012 | 0.0250 | -0.0502 | 0.0479 | 0.9621 | no |
| <= -13 (binned) | 0.0009 | 0.0177 | -0.0339 | 0.0357 | 0.9584 | yes |
| >= +11 (binned) | -0.0068 | 0.0209 | -0.0477 | 0.0342 | 0.7460 | no |


## Event study — log_landed_unit_value (reference period −1)

Coefficients are relative to event month −1. Pre-period coefficients are the test of the design, not decoration.

**coefficients**

| event_time | estimate | std_error | ci_low | ci_high | p_value | is_pre |
| --- | --- | --- | --- | --- | --- | --- |
| -12 | -0.0063 | 0.0225 | -0.0504 | 0.0379 | 0.7808 | yes |
| -11 | -0.0063 | 0.0231 | -0.0515 | 0.0389 | 0.7848 | yes |
| -10 | 0.0092 | 0.0215 | -0.0330 | 0.0514 | 0.6689 | yes |
| -9 | -0.0107 | 0.0217 | -0.0533 | 0.0318 | 0.6212 | yes |
| -8 | 0.0005 | 0.0226 | -0.0438 | 0.0449 | 0.9816 | yes |
| -7 | -0.0152 | 0.0226 | -0.0595 | 0.0290 | 0.4998 | yes |
| -6 | 0.0418 | 0.0220 | -0.0014 | 0.0850 | 0.0580 | yes |
| -5 | 0.0220 | 0.0207 | -0.0186 | 0.0626 | 0.2882 | yes |
| -4 | 0.0212 | 0.0218 | -0.0215 | 0.0639 | 0.3305 | yes |
| -3 | 0.0024 | 0.0201 | -0.0369 | 0.0417 | 0.9051 | yes |
| -2 | -0.0152 | 0.0203 | -0.0550 | 0.0247 | 0.4551 | yes |
| -1 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |  | yes |
| 0 | 0.0560 | 0.0209 | 0.0151 | 0.0969 | 0.0073 | no |
| 1 | 0.1372 | 0.0198 | 0.0982 | 0.1761 | 0.0000 | no |
| 2 | 0.1461 | 0.0224 | 0.1021 | 0.1901 | 0.0000 | no |
| 3 | 0.1110 | 0.0218 | 0.0683 | 0.1536 | 0.0000 | no |
| 4 | 0.1175 | 0.0236 | 0.0712 | 0.1638 | 0.0000 | no |
| 5 | 0.1424 | 0.0233 | 0.0967 | 0.1881 | 0.0000 | no |
| 6 | 0.1765 | 0.0254 | 0.1266 | 0.2264 | 0.0000 | no |
| 7 | 0.1634 | 0.0229 | 0.1184 | 0.2083 | 0.0000 | no |
| 8 | 0.1694 | 0.0252 | 0.1200 | 0.2187 | 0.0000 | no |
| 9 | 0.1674 | 0.0244 | 0.1196 | 0.2151 | 0.0000 | no |
| 10 | 0.1885 | 0.0238 | 0.1418 | 0.2351 | 0.0000 | no |
| <= -13 (binned) | -0.0017 | 0.0186 | -0.0381 | 0.0347 | 0.9283 | yes |
| >= +11 (binned) | 0.1774 | 0.0203 | 0.1376 | 0.2172 | 0.0000 | no |


## Event study — log_landed_unit_value (reference period −3)

Coefficients are relative to event month −3. Pre-period coefficients are the test of the design, not decoration.

**coefficients**

| event_time | estimate | std_error | ci_low | ci_high | p_value | is_pre |
| --- | --- | --- | --- | --- | --- | --- |
| -12 | -0.0086 | 0.0220 | -0.0518 | 0.0345 | 0.6946 | yes |
| -11 | -0.0087 | 0.0216 | -0.0510 | 0.0336 | 0.6871 | yes |
| -10 | 0.0068 | 0.0211 | -0.0347 | 0.0483 | 0.7474 | yes |
| -9 | -0.0131 | 0.0216 | -0.0555 | 0.0293 | 0.5444 | yes |
| -8 | -0.0019 | 0.0218 | -0.0447 | 0.0410 | 0.9318 | yes |
| -7 | -0.0176 | 0.0231 | -0.0629 | 0.0277 | 0.4453 | yes |
| -6 | 0.0394 | 0.0223 | -0.0043 | 0.0832 | 0.0775 | yes |
| -5 | 0.0196 | 0.0206 | -0.0208 | 0.0600 | 0.3421 | yes |
| -4 | 0.0188 | 0.0207 | -0.0219 | 0.0594 | 0.3646 | yes |
| -3 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |  | yes |
| -2 | -0.0176 | 0.0208 | -0.0583 | 0.0231 | 0.3973 | yes |
| -1 | -0.0024 | 0.0201 | -0.0417 | 0.0369 | 0.9051 | yes |
| 0 | 0.0536 | 0.0215 | 0.0114 | 0.0958 | 0.0128 | no |
| 1 | 0.1348 | 0.0212 | 0.0932 | 0.1763 | 0.0000 | no |
| 2 | 0.1437 | 0.0240 | 0.0967 | 0.1908 | 0.0000 | no |
| 3 | 0.1086 | 0.0229 | 0.0637 | 0.1534 | 0.0000 | no |
| 4 | 0.1152 | 0.0232 | 0.0696 | 0.1607 | 0.0000 | no |
| 5 | 0.1400 | 0.0240 | 0.0929 | 0.1871 | 0.0000 | no |
| 6 | 0.1741 | 0.0263 | 0.1225 | 0.2257 | 0.0000 | no |
| 7 | 0.1610 | 0.0245 | 0.1130 | 0.2090 | 0.0000 | no |
| 8 | 0.1670 | 0.0248 | 0.1184 | 0.2156 | 0.0000 | no |
| 9 | 0.1650 | 0.0253 | 0.1153 | 0.2146 | 0.0000 | no |
| 10 | 0.1861 | 0.0250 | 0.1370 | 0.2351 | 0.0000 | no |
| <= -13 (binned) | -0.0041 | 0.0178 | -0.0390 | 0.0309 | 0.8199 | yes |
| >= +11 (binned) | 0.1750 | 0.0210 | 0.1338 | 0.2162 | 0.0000 | no |


## Event study — log_quantity (reference period −1)

Coefficients are relative to event month −1. Pre-period coefficients are the test of the design, not decoration.

**coefficients**

| event_time | estimate | std_error | ci_low | ci_high | p_value | is_pre |
| --- | --- | --- | --- | --- | --- | --- |
| -12 | -0.1060 | 0.0319 | -0.1686 | -0.0434 | 0.0009 | yes |
| -11 | -0.0996 | 0.0311 | -0.1607 | -0.0385 | 0.0014 | yes |
| -10 | -0.1669 | 0.0303 | -0.2264 | -0.1074 | 0.0000 | yes |
| -9 | -0.0814 | 0.0310 | -0.1422 | -0.0206 | 0.0087 | yes |
| -8 | -0.0411 | 0.0311 | -0.1021 | 0.0199 | 0.1868 | yes |
| -7 | -0.0204 | 0.0294 | -0.0781 | 0.0372 | 0.4870 | yes |
| -6 | -0.2192 | 0.0314 | -0.2808 | -0.1576 | 0.0000 | yes |
| -5 | -0.2060 | 0.0308 | -0.2665 | -0.1455 | 0.0000 | yes |
| -4 | -0.1171 | 0.0288 | -0.1737 | -0.0606 | 0.0001 | yes |
| -3 | -0.0510 | 0.0262 | -0.1023 | 0.0004 | 0.0519 | yes |
| -2 | 0.0031 | 0.0267 | -0.0493 | 0.0555 | 0.9082 | yes |
| -1 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |  | yes |
| 0 | -0.1082 | 0.0275 | -0.1623 | -0.0542 | 0.0001 | no |
| 1 | -0.2461 | 0.0277 | -0.3005 | -0.1917 | 0.0000 | no |
| 2 | -0.3092 | 0.0310 | -0.3701 | -0.2483 | 0.0000 | no |
| 3 | -0.1206 | 0.0347 | -0.1886 | -0.0525 | 0.0005 | no |
| 4 | -0.3576 | 0.0339 | -0.4241 | -0.2910 | 0.0000 | no |
| 5 | -0.4429 | 0.0341 | -0.5097 | -0.3761 | 0.0000 | no |
| 6 | -0.5762 | 0.0360 | -0.6467 | -0.5056 | 0.0000 | no |
| 7 | -0.5916 | 0.0361 | -0.6625 | -0.5208 | 0.0000 | no |
| 8 | -0.4993 | 0.0374 | -0.5727 | -0.4260 | 0.0000 | no |
| 9 | -0.4870 | 0.0361 | -0.5578 | -0.4162 | 0.0000 | no |
| 10 | -0.5203 | 0.0357 | -0.5904 | -0.4501 | 0.0000 | no |
| <= -13 (binned) | -0.1225 | 0.0284 | -0.1782 | -0.0668 | 0.0000 | yes |
| >= +11 (binned) | -0.6197 | 0.0332 | -0.6849 | -0.5546 | 0.0000 | no |


## Event study — log_quantity (reference period −3)

Coefficients are relative to event month −3. Pre-period coefficients are the test of the design, not decoration.

**coefficients**

| event_time | estimate | std_error | ci_low | ci_high | p_value | is_pre |
| --- | --- | --- | --- | --- | --- | --- |
| -12 | -0.0550 | 0.0312 | -0.1163 | 0.0063 | 0.0784 | yes |
| -11 | -0.0486 | 0.0303 | -0.1081 | 0.0109 | 0.1092 | yes |
| -10 | -0.1159 | 0.0298 | -0.1744 | -0.0574 | 0.0001 | yes |
| -9 | -0.0304 | 0.0305 | -0.0903 | 0.0294 | 0.3188 | yes |
| -8 | 0.0099 | 0.0297 | -0.0483 | 0.0681 | 0.7394 | yes |
| -7 | 0.0305 | 0.0293 | -0.0270 | 0.0880 | 0.2980 | yes |
| -6 | -0.1683 | 0.0309 | -0.2289 | -0.1076 | 0.0000 | yes |
| -5 | -0.1550 | 0.0302 | -0.2143 | -0.0958 | 0.0000 | yes |
| -4 | -0.0662 | 0.0267 | -0.1186 | -0.0137 | 0.0134 | yes |
| -3 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |  | yes |
| -2 | 0.0540 | 0.0268 | 0.0015 | 0.1066 | 0.0438 | yes |
| -1 | 0.0510 | 0.0262 | -0.0004 | 0.1023 | 0.0519 | yes |
| 0 | -0.0573 | 0.0291 | -0.1144 | -0.0001 | 0.0494 | no |
| 1 | -0.1951 | 0.0290 | -0.2520 | -0.1383 | 0.0000 | no |
| 2 | -0.2582 | 0.0320 | -0.3210 | -0.1955 | 0.0000 | no |
| 3 | -0.0696 | 0.0332 | -0.1347 | -0.0045 | 0.0362 | no |
| 4 | -0.3066 | 0.0339 | -0.3731 | -0.2401 | 0.0000 | no |
| 5 | -0.3919 | 0.0359 | -0.4623 | -0.3216 | 0.0000 | no |
| 6 | -0.5252 | 0.0372 | -0.5982 | -0.4522 | 0.0000 | no |
| 7 | -0.5407 | 0.0363 | -0.6119 | -0.4694 | 0.0000 | no |
| 8 | -0.4484 | 0.0350 | -0.5170 | -0.3798 | 0.0000 | no |
| 9 | -0.4361 | 0.0355 | -0.5058 | -0.3664 | 0.0000 | no |
| 10 | -0.4693 | 0.0367 | -0.5413 | -0.3973 | 0.0000 | no |
| <= -13 (binned) | -0.0715 | 0.0278 | -0.1261 | -0.0169 | 0.0103 | yes |
| >= +11 (binned) | -0.5688 | 0.0341 | -0.6357 | -0.5018 | 0.0000 | no |


## Stacked multi-wave event study — log_landed_unit_value (controls: never_treated_products)

One sub-experiment per Section 301 wave, each drawing controls from never-treated products only, with flow-by-stack and calendar-month-by-stack effects. No already-treated unit is ever used as a control.

**coefficients**

| event_time | estimate | std_error | ci_low | ci_high | p_value | is_pre |
| --- | --- | --- | --- | --- | --- | --- |
| -12 | -0.0330 | 0.0246 | -0.0814 | 0.0153 | 0.1806 | yes |
| -11 | -0.0213 | 0.0238 | -0.0681 | 0.0254 | 0.3703 | yes |
| -10 | -0.0053 | 0.0232 | -0.0508 | 0.0401 | 0.8175 | yes |
| -9 | -0.0387 | 0.0242 | -0.0860 | 0.0087 | 0.1097 | yes |
| -8 | -0.0052 | 0.0243 | -0.0529 | 0.0426 | 0.8319 | yes |
| -7 | -0.0355 | 0.0258 | -0.0861 | 0.0150 | 0.1683 | yes |
| -6 | 0.0294 | 0.0245 | -0.0187 | 0.0775 | 0.2309 | yes |
| -5 | 0.0049 | 0.0232 | -0.0406 | 0.0503 | 0.8334 | yes |
| -4 | 0.0209 | 0.0233 | -0.0248 | 0.0665 | 0.3701 | yes |
| -3 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |  | yes |
| -2 | -0.0276 | 0.0229 | -0.0725 | 0.0173 | 0.2281 | yes |
| -1 | 0.0190 | 0.0220 | -0.0241 | 0.0621 | 0.3870 | yes |
| 0 | 0.0621 | 0.0236 | 0.0158 | 0.1083 | 0.0086 | no |
| 1 | 0.1597 | 0.0232 | 0.1142 | 0.2052 | 0.0000 | no |
| 2 | 0.1550 | 0.0254 | 0.1052 | 0.2048 | 0.0000 | no |
| 3 | 0.1353 | 0.0245 | 0.0873 | 0.1833 | 0.0000 | no |
| 4 | 0.1255 | 0.0253 | 0.0759 | 0.1751 | 0.0000 | no |
| 5 | 0.1469 | 0.0261 | 0.0958 | 0.1981 | 0.0000 | no |
| 6 | 0.1863 | 0.0294 | 0.1286 | 0.2440 | 0.0000 | no |
| 7 | 0.1842 | 0.0272 | 0.1310 | 0.2375 | 0.0000 | no |
| 8 | 0.1803 | 0.0267 | 0.1279 | 0.2327 | 0.0000 | no |
| 9 | 0.1709 | 0.0269 | 0.1181 | 0.2237 | 0.0000 | no |
| 10 | 0.1926 | 0.0268 | 0.1400 | 0.2452 | 0.0000 | no |
| <= -13 (binned) | 0.0000 | 0.0000 | 0.0000 | 0.0000 |  | yes |
| >= +11 (binned) | 0.0000 | 0.0000 | 0.0000 | 0.0000 |  | no |


## Stacked multi-wave event study — log_customs_unit_value (controls: never_treated_products)

One sub-experiment per Section 301 wave, each drawing controls from never-treated products only, with flow-by-stack and calendar-month-by-stack effects. No already-treated unit is ever used as a control.

**coefficients**

| event_time | estimate | std_error | ci_low | ci_high | p_value | is_pre |
| --- | --- | --- | --- | --- | --- | --- |
| -12 | -0.0307 | 0.0246 | -0.0790 | 0.0176 | 0.2127 | yes |
| -11 | -0.0196 | 0.0238 | -0.0663 | 0.0272 | 0.4115 | yes |
| -10 | -0.0038 | 0.0231 | -0.0492 | 0.0415 | 0.8681 | yes |
| -9 | -0.0367 | 0.0242 | -0.0841 | 0.0107 | 0.1292 | yes |
| -8 | -0.0032 | 0.0243 | -0.0509 | 0.0445 | 0.8962 | yes |
| -7 | -0.0333 | 0.0257 | -0.0838 | 0.0172 | 0.1960 | yes |
| -6 | 0.0313 | 0.0245 | -0.0167 | 0.0793 | 0.2013 | yes |
| -5 | 0.0068 | 0.0232 | -0.0386 | 0.0523 | 0.7679 | yes |
| -4 | 0.0217 | 0.0233 | -0.0240 | 0.0673 | 0.3521 | yes |
| -3 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |  | yes |
| -2 | -0.0275 | 0.0229 | -0.0724 | 0.0174 | 0.2298 | yes |
| -1 | 0.0193 | 0.0220 | -0.0238 | 0.0624 | 0.3804 | yes |
| 0 | 0.0100 | 0.0233 | -0.0357 | 0.0558 | 0.6670 | no |
| 1 | 0.0372 | 0.0232 | -0.0083 | 0.0828 | 0.1089 | no |
| 2 | 0.0279 | 0.0250 | -0.0211 | 0.0769 | 0.2641 | no |
| 3 | 0.0093 | 0.0242 | -0.0381 | 0.0567 | 0.6995 | no |
| 4 | -0.0001 | 0.0251 | -0.0494 | 0.0492 | 0.9967 | no |
| 5 | 0.0261 | 0.0259 | -0.0247 | 0.0769 | 0.3136 | no |
| 6 | 0.0602 | 0.0292 | 0.0030 | 0.1174 | 0.0392 | no |
| 7 | 0.0602 | 0.0269 | 0.0073 | 0.1130 | 0.0256 | no |
| 8 | 0.0481 | 0.0264 | -0.0037 | 0.1000 | 0.0688 | no |
| 9 | -0.0064 | 0.0269 | -0.0591 | 0.0463 | 0.8123 | no |
| 10 | 0.0055 | 0.0269 | -0.0472 | 0.0583 | 0.8370 | no |
| <= -13 (binned) | 0.0000 | 0.0000 | 0.0000 | 0.0000 |  | yes |
| >= +11 (binned) | 0.0000 | 0.0000 | 0.0000 | 0.0000 |  | no |


## Stacked multi-wave event study — log_quantity (controls: never_treated_products)

One sub-experiment per Section 301 wave, each drawing controls from never-treated products only, with flow-by-stack and calendar-month-by-stack effects. No already-treated unit is ever used as a control.

**coefficients**

| event_time | estimate | std_error | ci_low | ci_high | p_value | is_pre |
| --- | --- | --- | --- | --- | --- | --- |
| -12 | -0.0617 | 0.0349 | -0.1302 | 0.0067 | 0.0769 | yes |
| -11 | -0.0708 | 0.0334 | -0.1363 | -0.0052 | 0.0344 | yes |
| -10 | -0.1372 | 0.0338 | -0.2035 | -0.0709 | 0.0001 | yes |
| -9 | -0.0054 | 0.0346 | -0.0734 | 0.0625 | 0.8751 | yes |
| -8 | 0.0000 | 0.0325 | -0.0637 | 0.0638 | 0.9990 | yes |
| -7 | 0.0421 | 0.0329 | -0.0226 | 0.1067 | 0.2020 | yes |
| -6 | -0.1536 | 0.0339 | -0.2201 | -0.0871 | 0.0000 | yes |
| -5 | -0.1402 | 0.0335 | -0.2059 | -0.0746 | 0.0000 | yes |
| -4 | -0.0693 | 0.0298 | -0.1278 | -0.0108 | 0.0202 | yes |
| -3 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |  | yes |
| -2 | 0.0473 | 0.0295 | -0.0106 | 0.1052 | 0.1094 | yes |
| -1 | 0.0070 | 0.0292 | -0.0504 | 0.0643 | 0.8117 | yes |
| 0 | -0.0636 | 0.0321 | -0.1266 | -0.0007 | 0.0476 | no |
| 1 | -0.2514 | 0.0320 | -0.3141 | -0.1887 | 0.0000 | no |
| 2 | -0.3116 | 0.0348 | -0.3798 | -0.2433 | 0.0000 | no |
| 3 | -0.1080 | 0.0360 | -0.1786 | -0.0375 | 0.0027 | no |
| 4 | -0.3176 | 0.0370 | -0.3901 | -0.2450 | 0.0000 | no |
| 5 | -0.4202 | 0.0385 | -0.4958 | -0.3446 | 0.0000 | no |
| 6 | -0.5716 | 0.0399 | -0.6498 | -0.4934 | 0.0000 | no |
| 7 | -0.6077 | 0.0391 | -0.6844 | -0.5310 | 0.0000 | no |
| 8 | -0.5145 | 0.0375 | -0.5880 | -0.4410 | 0.0000 | no |
| 9 | -0.4827 | 0.0380 | -0.5572 | -0.4081 | 0.0000 | no |
| 10 | -0.5237 | 0.0385 | -0.5992 | -0.4482 | 0.0000 | no |
| <= -13 (binned) | 0.0000 | 0.0000 | 0.0000 | 0.0000 |  | yes |
| >= +11 (binned) | 0.0000 | 0.0000 | 0.0000 | 0.0000 |  | no |


## Stacked multi-wave event study — log_landed_unit_value (controls: not_yet_treated)

One sub-experiment per Section 301 wave, each drawing controls from never-treated products only, with flow-by-stack and calendar-month-by-stack effects. No already-treated unit is ever used as a control.

**coefficients**

| event_time | estimate | std_error | ci_low | ci_high | p_value | is_pre |
| --- | --- | --- | --- | --- | --- | --- |
| -12 | -0.0138 | 0.0240 | -0.0609 | 0.0332 | 0.5639 | yes |
| -11 | -0.0031 | 0.0231 | -0.0484 | 0.0422 | 0.8924 | yes |
| -10 | 0.0091 | 0.0226 | -0.0353 | 0.0535 | 0.6871 | yes |
| -9 | -0.0203 | 0.0236 | -0.0666 | 0.0260 | 0.3898 | yes |
| -8 | 0.0011 | 0.0239 | -0.0457 | 0.0479 | 0.9635 | yes |
| -7 | -0.0198 | 0.0252 | -0.0693 | 0.0297 | 0.4329 | yes |
| -6 | 0.0377 | 0.0239 | -0.0093 | 0.0846 | 0.1156 | yes |
| -5 | 0.0164 | 0.0223 | -0.0274 | 0.0603 | 0.4623 | yes |
| -4 | 0.0217 | 0.0224 | -0.0223 | 0.0657 | 0.3339 | yes |
| -3 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |  | yes |
| -2 | -0.0263 | 0.0223 | -0.0701 | 0.0174 | 0.2381 | yes |
| -1 | 0.0128 | 0.0214 | -0.0292 | 0.0547 | 0.5507 | yes |
| 0 | 0.0561 | 0.0231 | 0.0107 | 0.1015 | 0.0154 | no |
| 1 | 0.1518 | 0.0229 | 0.1068 | 0.1968 | 0.0000 | no |
| 2 | 0.1511 | 0.0253 | 0.1014 | 0.2007 | 0.0000 | no |
| 3 | 0.1292 | 0.0246 | 0.0811 | 0.1774 | 0.0000 | no |
| 4 | 0.1218 | 0.0244 | 0.0738 | 0.1697 | 0.0000 | no |
| 5 | 0.1481 | 0.0258 | 0.0974 | 0.1987 | 0.0000 | no |
| 6 | 0.1843 | 0.0287 | 0.1281 | 0.2406 | 0.0000 | no |
| 7 | 0.1808 | 0.0266 | 0.1286 | 0.2330 | 0.0000 | no |
| 8 | 0.1805 | 0.0269 | 0.1277 | 0.2333 | 0.0000 | no |
| 9 | 0.1690 | 0.0273 | 0.1155 | 0.2225 | 0.0000 | no |
| 10 | 0.1922 | 0.0273 | 0.1386 | 0.2458 | 0.0000 | no |
| <= -13 (binned) | 0.0000 | 0.0000 | 0.0000 | 0.0000 |  | yes |
| >= +11 (binned) | 0.0000 | 0.0000 | 0.0000 | 0.0000 |  | no |


## Stacked multi-wave event study — log_customs_unit_value (controls: not_yet_treated)

One sub-experiment per Section 301 wave, each drawing controls from never-treated products only, with flow-by-stack and calendar-month-by-stack effects. No already-treated unit is ever used as a control.

**coefficients**

| event_time | estimate | std_error | ci_low | ci_high | p_value | is_pre |
| --- | --- | --- | --- | --- | --- | --- |
| -12 | -0.0200 | 0.0239 | -0.0668 | 0.0268 | 0.4013 | yes |
| -11 | -0.0097 | 0.0230 | -0.0547 | 0.0354 | 0.6736 | yes |
| -10 | 0.0021 | 0.0226 | -0.0422 | 0.0463 | 0.9272 | yes |
| -9 | -0.0268 | 0.0235 | -0.0728 | 0.0192 | 0.2537 | yes |
| -8 | -0.0055 | 0.0238 | -0.0522 | 0.0412 | 0.8180 | yes |
| -7 | -0.0260 | 0.0252 | -0.0753 | 0.0234 | 0.3016 | yes |
| -6 | 0.0313 | 0.0239 | -0.0156 | 0.0782 | 0.1905 | yes |
| -5 | 0.0114 | 0.0224 | -0.0325 | 0.0553 | 0.6114 | yes |
| -4 | 0.0178 | 0.0224 | -0.0262 | 0.0618 | 0.4279 | yes |
| -3 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |  | yes |
| -2 | -0.0236 | 0.0223 | -0.0673 | 0.0202 | 0.2914 | yes |
| -1 | 0.0181 | 0.0213 | -0.0238 | 0.0599 | 0.3968 | yes |
| 0 | 0.0090 | 0.0229 | -0.0360 | 0.0539 | 0.6958 | no |
| 1 | 0.0335 | 0.0229 | -0.0114 | 0.0783 | 0.1434 | no |
| 2 | 0.0281 | 0.0249 | -0.0208 | 0.0770 | 0.2596 | no |
| 3 | 0.0073 | 0.0242 | -0.0403 | 0.0548 | 0.7646 | no |
| 4 | 0.0000 | 0.0243 | -0.0476 | 0.0476 | 0.9996 | no |
| 5 | 0.0307 | 0.0257 | -0.0196 | 0.0811 | 0.2311 | no |
| 6 | 0.0628 | 0.0284 | 0.0071 | 0.1186 | 0.0272 | no |
| 7 | 0.0613 | 0.0264 | 0.0096 | 0.1131 | 0.0203 | no |
| 8 | 0.0522 | 0.0267 | -0.0001 | 0.1045 | 0.0506 | no |
| 9 | -0.0060 | 0.0272 | -0.0593 | 0.0474 | 0.8267 | no |
| 10 | 0.0062 | 0.0274 | -0.0475 | 0.0600 | 0.8195 | no |
| <= -13 (binned) | 0.0000 | 0.0000 | 0.0000 | 0.0000 |  | yes |
| >= +11 (binned) | 0.0000 | 0.0000 | 0.0000 | 0.0000 |  | no |


## Stacked multi-wave event study — log_quantity (controls: not_yet_treated)

One sub-experiment per Section 301 wave, each drawing controls from never-treated products only, with flow-by-stack and calendar-month-by-stack effects. No already-treated unit is ever used as a control.

**coefficients**

| event_time | estimate | std_error | ci_low | ci_high | p_value | is_pre |
| --- | --- | --- | --- | --- | --- | --- |
| -12 | -0.0999 | 0.0347 | -0.1679 | -0.0319 | 0.0040 | yes |
| -11 | -0.1037 | 0.0330 | -0.1684 | -0.0390 | 0.0017 | yes |
| -10 | -0.1681 | 0.0328 | -0.2324 | -0.1037 | 0.0000 | yes |
| -9 | -0.0448 | 0.0344 | -0.1123 | 0.0227 | 0.1928 | yes |
| -8 | -0.0239 | 0.0328 | -0.0883 | 0.0404 | 0.4656 | yes |
| -7 | 0.0118 | 0.0327 | -0.0523 | 0.0759 | 0.7176 | yes |
| -6 | -0.1784 | 0.0337 | -0.2444 | -0.1123 | 0.0000 | yes |
| -5 | -0.1626 | 0.0322 | -0.2258 | -0.0993 | 0.0000 | yes |
| -4 | -0.0786 | 0.0290 | -0.1355 | -0.0218 | 0.0067 | yes |
| -3 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |  | yes |
| -2 | 0.0502 | 0.0286 | -0.0059 | 0.1063 | 0.0795 | yes |
| -1 | 0.0203 | 0.0280 | -0.0347 | 0.0752 | 0.4689 | yes |
| 0 | -0.0675 | 0.0312 | -0.1287 | -0.0062 | 0.0308 | no |
| 1 | -0.2491 | 0.0312 | -0.3102 | -0.1880 | 0.0000 | no |
| 2 | -0.3129 | 0.0344 | -0.3804 | -0.2455 | 0.0000 | no |
| 3 | -0.1060 | 0.0354 | -0.1754 | -0.0365 | 0.0028 | no |
| 4 | -0.3205 | 0.0361 | -0.3913 | -0.2497 | 0.0000 | no |
| 5 | -0.4141 | 0.0376 | -0.4879 | -0.3402 | 0.0000 | no |
| 6 | -0.5560 | 0.0394 | -0.6332 | -0.4788 | 0.0000 | no |
| 7 | -0.5862 | 0.0381 | -0.6610 | -0.5114 | 0.0000 | no |
| 8 | -0.4973 | 0.0369 | -0.5698 | -0.4248 | 0.0000 | no |
| 9 | -0.4644 | 0.0374 | -0.5378 | -0.3911 | 0.0000 | no |
| 10 | -0.5069 | 0.0387 | -0.5827 | -0.4311 | 0.0000 | no |
| <= -13 (binned) | 0.0000 | 0.0000 | 0.0000 | 0.0000 |  | yes |
| >= +11 (binned) | 0.0000 | 0.0000 | 0.0000 | 0.0000 |  | no |


## Stacked multi-wave event study — log_landed_unit_value (controls: never_treated_products_treated_country_only)

One sub-experiment per Section 301 wave, each drawing controls from never-treated products only, with flow-by-stack and calendar-month-by-stack effects. No already-treated unit is ever used as a control.

**coefficients**

| event_time | estimate | std_error | ci_low | ci_high | p_value | is_pre |
| --- | --- | --- | --- | --- | --- | --- |
| -12 | -0.0728 | 0.0416 | -0.1545 | 0.0089 | 0.0807 | yes |
| -11 | -0.0470 | 0.0417 | -0.1288 | 0.0348 | 0.2597 | yes |
| -10 | -0.0484 | 0.0390 | -0.1248 | 0.0281 | 0.2146 | yes |
| -9 | -0.0373 | 0.0350 | -0.1059 | 0.0313 | 0.2866 | yes |
| -8 | -0.0458 | 0.0375 | -0.1194 | 0.0277 | 0.2220 | yes |
| -7 | -0.0073 | 0.0331 | -0.0723 | 0.0577 | 0.8255 | yes |
| -6 | 0.0065 | 0.0469 | -0.0856 | 0.0985 | 0.8902 | yes |
| -5 | -0.0045 | 0.0348 | -0.0728 | 0.0637 | 0.8963 | yes |
| -4 | 0.0090 | 0.0308 | -0.0514 | 0.0694 | 0.7700 | yes |
| -3 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |  | yes |
| -2 | -0.0136 | 0.0271 | -0.0668 | 0.0396 | 0.6158 | yes |
| -1 | 0.0064 | 0.0295 | -0.0515 | 0.0643 | 0.8282 | yes |
| 0 | 0.0460 | 0.0350 | -0.0227 | 0.1147 | 0.1894 | no |
| 1 | 0.1575 | 0.0361 | 0.0867 | 0.2282 | 0.0000 | no |
| 2 | 0.1742 | 0.0370 | 0.1015 | 0.2468 | 0.0000 | no |
| 3 | 0.1528 | 0.0400 | 0.0742 | 0.2313 | 0.0001 | no |
| 4 | 0.1501 | 0.0404 | 0.0708 | 0.2294 | 0.0002 | no |
| 5 | 0.1903 | 0.0401 | 0.1117 | 0.2690 | 0.0000 | no |
| 6 | 0.2448 | 0.0544 | 0.1382 | 0.3515 | 0.0000 | no |
| 7 | 0.2647 | 0.0500 | 0.1667 | 0.3627 | 0.0000 | no |
| 8 | 0.2621 | 0.0512 | 0.1616 | 0.3625 | 0.0000 | no |
| 9 | 0.2583 | 0.0481 | 0.1639 | 0.3527 | 0.0000 | no |
| 10 | 0.2760 | 0.0446 | 0.1885 | 0.3635 | 0.0000 | no |
| <= -13 (binned) | 0.0000 | 0.0000 | 0.0000 | 0.0000 |  | yes |
| >= +11 (binned) | 0.0000 | 0.0000 | 0.0000 | 0.0000 |  | no |


## Stacked multi-wave event study — log_customs_unit_value (controls: never_treated_products_treated_country_only)

One sub-experiment per Section 301 wave, each drawing controls from never-treated products only, with flow-by-stack and calendar-month-by-stack effects. No already-treated unit is ever used as a control.

**coefficients**

| event_time | estimate | std_error | ci_low | ci_high | p_value | is_pre |
| --- | --- | --- | --- | --- | --- | --- |
| -12 | -0.0736 | 0.0416 | -0.1553 | 0.0080 | 0.0771 | yes |
| -11 | -0.0509 | 0.0416 | -0.1326 | 0.0307 | 0.2211 | yes |
| -10 | -0.0518 | 0.0390 | -0.1283 | 0.0247 | 0.1845 | yes |
| -9 | -0.0398 | 0.0349 | -0.1083 | 0.0288 | 0.2552 | yes |
| -8 | -0.0485 | 0.0376 | -0.1222 | 0.0252 | 0.1967 | yes |
| -7 | -0.0100 | 0.0331 | -0.0749 | 0.0549 | 0.7630 | yes |
| -6 | 0.0036 | 0.0469 | -0.0884 | 0.0956 | 0.9393 | yes |
| -5 | -0.0075 | 0.0349 | -0.0760 | 0.0610 | 0.8299 | yes |
| -4 | 0.0058 | 0.0308 | -0.0547 | 0.0662 | 0.8511 | yes |
| -3 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |  | yes |
| -2 | -0.0122 | 0.0271 | -0.0654 | 0.0411 | 0.6540 | yes |
| -1 | 0.0078 | 0.0296 | -0.0502 | 0.0658 | 0.7915 | yes |
| 0 | -0.0169 | 0.0349 | -0.0854 | 0.0516 | 0.6284 | no |
| 1 | 0.0248 | 0.0360 | -0.0459 | 0.0955 | 0.4913 | no |
| 2 | 0.0343 | 0.0370 | -0.0382 | 0.1068 | 0.3533 | no |
| 3 | 0.0141 | 0.0399 | -0.0642 | 0.0924 | 0.7243 | no |
| 4 | 0.0122 | 0.0404 | -0.0670 | 0.0915 | 0.7619 | no |
| 5 | 0.0604 | 0.0400 | -0.0181 | 0.1388 | 0.1315 | no |
| 6 | 0.1017 | 0.0542 | -0.0047 | 0.2081 | 0.0609 | no |
| 7 | 0.1234 | 0.0499 | 0.0254 | 0.2213 | 0.0136 | no |
| 8 | 0.1150 | 0.0511 | 0.0146 | 0.2153 | 0.0247 | no |
| 9 | 0.0818 | 0.0481 | -0.0125 | 0.1760 | 0.0891 | no |
| 10 | 0.0969 | 0.0446 | 0.0095 | 0.1843 | 0.0299 | no |
| <= -13 (binned) | 0.0000 | 0.0000 | 0.0000 | 0.0000 |  | yes |
| >= +11 (binned) | 0.0000 | 0.0000 | 0.0000 | 0.0000 |  | no |


## Stacked multi-wave event study — log_quantity (controls: never_treated_products_treated_country_only)

One sub-experiment per Section 301 wave, each drawing controls from never-treated products only, with flow-by-stack and calendar-month-by-stack effects. No already-treated unit is ever used as a control.

**coefficients**

| event_time | estimate | std_error | ci_low | ci_high | p_value | is_pre |
| --- | --- | --- | --- | --- | --- | --- |
| -12 | -0.1257 | 0.0725 | -0.2678 | 0.0165 | 0.0831 | yes |
| -11 | -0.1491 | 0.0663 | -0.2792 | -0.0190 | 0.0247 | yes |
| -10 | -0.2324 | 0.0655 | -0.3609 | -0.1039 | 0.0004 | yes |
| -9 | -0.1597 | 0.0547 | -0.2671 | -0.0523 | 0.0036 | yes |
| -8 | -0.1118 | 0.0504 | -0.2107 | -0.0129 | 0.0267 | yes |
| -7 | -0.0834 | 0.0447 | -0.1710 | 0.0042 | 0.0620 | yes |
| -6 | -0.0715 | 0.0504 | -0.1702 | 0.0273 | 0.1562 | yes |
| -5 | -0.0411 | 0.0443 | -0.1281 | 0.0458 | 0.3534 | yes |
| -4 | 0.0234 | 0.0432 | -0.0613 | 0.1081 | 0.5882 | yes |
| -3 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |  | yes |
| -2 | -0.0376 | 0.0396 | -0.1152 | 0.0401 | 0.3424 | yes |
| -1 | -0.1032 | 0.0457 | -0.1928 | -0.0137 | 0.0239 | yes |
| 0 | -0.2487 | 0.0620 | -0.3703 | -0.1271 | 0.0001 | no |
| 1 | -0.4485 | 0.0684 | -0.5827 | -0.3143 | 0.0000 | no |
| 2 | -0.5716 | 0.0702 | -0.7092 | -0.4339 | 0.0000 | no |
| 3 | -0.4439 | 0.0683 | -0.5779 | -0.3098 | 0.0000 | no |
| 4 | -0.5167 | 0.0596 | -0.6337 | -0.3997 | 0.0000 | no |
| 5 | -0.5558 | 0.0596 | -0.6727 | -0.4389 | 0.0000 | no |
| 6 | -0.5741 | 0.0653 | -0.7022 | -0.4460 | 0.0000 | no |
| 7 | -0.6669 | 0.0626 | -0.7898 | -0.5441 | 0.0000 | no |
| 8 | -0.5627 | 0.0715 | -0.7031 | -0.4224 | 0.0000 | no |
| 9 | -0.6234 | 0.0661 | -0.7531 | -0.4938 | 0.0000 | no |
| 10 | -0.7294 | 0.0712 | -0.8691 | -0.5897 | 0.0000 | no |
| <= -13 (binned) | 0.0000 | 0.0000 | 0.0000 | 0.0000 |  | yes |
| >= +11 (binned) | 0.0000 | 0.0000 | 0.0000 | 0.0000 |  | no |


## Robustness: does product reclassification drive any of this?

A renumbered 10-digit line looks exactly like one product exiting and another entering, which is the pattern the diversion decomposition reads as an extensive-margin move. Identifying which codes were renumbered needs a correlation table this project does not have, so the risk is **bounded instead**: the headline design is re-estimated on codes with an observation in every month of the window, which cannot have been introduced or retired inside it — 3,937 of 5,253 codes, 94.4% of customs value. It also drops codes that were merely untraded for a month, so it is conservative rather than exact: *observed throughout* is not the same claim as *definition stable*.

**The point estimates hold.** None reverses sign and none moves enough to change what the incidence account says: the customs unit value sits even closer to zero on this subsample, which is the direction that supports the bound rather than undermining it.

**The verdicts move in both directions, and neither move should be read as a change in kind.** Both are threshold crossings: the pre-to-post RMS ratio is compared against 0.20, and here it moves from 0.157 to 0.241 for the landed outcome and from 0.204 to 0.189 for quantity. A verdict that flips on a ±0.05 move around a hand-set cut is a statement about the cut, not about the design, which is why the ratio is printed beside the verdict below. What the numbers do show consistently is that dropping a quarter of the codes costs precision, and the pre-period is where that shows first.

**headline vs codes observed throughout**

| outcome | all_codes | codes_observed_throughout | change | verdict_all | verdict_stable | rms_pre_over_post_all | rms_pre_over_post_stable |
| --- | --- | --- | --- | --- | --- | --- | --- |
| log_customs_unit_value | 0.0253 | 0.0058 | -0.0195 | PRECISE_NULL_EFFECT_BOUNDED | PRECISE_NULL_EFFECT_BOUNDED | 0.7120 | 1.4280 |
| log_landed_unit_value | 0.1544 | 0.1362 | -0.0182 | CLEAN | NOISY_PRE_PERIOD_NO_SLOPE | 0.1570 | 0.2410 |
| log_quantity | -0.3793 | -0.3732 | 0.0061 | NOISY_PRE_PERIOD_NO_SLOPE | CLEAN | 0.2040 | 0.1890 |


## Stacked design composition

How much weight each wave carries, reported rather than buried.

**stacks**

| stack_id | n_obs | n_treated_obs | n_products | treatment_month_index | run_id | git_commit | config | data_provenance | data_period |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| SEC301_LIST1 | 184262 | 26245 | 1742 | 24223 | 20260811T201214Z-b1495fb3 | 3c51a06-dirty | sample_slice.yaml | OFFICIAL | 2017-01..2020-02 |
| SEC301_LIST2 | 72860 | 7348 | 723 | 24224 | 20260811T201214Z-b1495fb3 | 3c51a06-dirty | sample_slice.yaml | OFFICIAL | 2017-01..2020-02 |
| SEC301_LIST3 | 278091 | 44825 | 2667 | 24225 | 20260811T201214Z-b1495fb3 | 3c51a06-dirty | sample_slice.yaml | OFFICIAL | 2017-01..2020-02 |
| SEC301_LIST4A | 83708 | 11209 | 1168 | 24237 | 20260811T201214Z-b1495fb3 | 3c51a06-dirty | sample_slice.yaml | OFFICIAL | 2017-01..2020-02 |


## Pre-treatment trend tests

Two criteria are reported. Statistical detectability alone is a poor guide in a large panel, where standard errors shrink until economically trivial pre-period movement becomes significant; the verdict field combines significance with magnitude relative to the post-treatment coefficients.

**pre-trend tests**

| test | n_pre_coefs | approx_chi2 | approx_p_value | any_pre_significant_5pct | max_abs_pre_coef | rms_pre_coef | mean_abs_post_coef | rms_post_coef | max_abs_post_coef | rms_pre_relative_to_rms_post | max_pre_relative_to_max_post | max_pre_relative_to_mean_post | pre_slope_per_month | pre_slope_se | pre_slope_p_value | implied_bias_over_post_window | slope_material | economically_small | effect_separable_from_pre_noise | slope_detectable | effect_bound_abs | null_multiple | relative_threshold | verdict | reference_period | design | control_definition | sample |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| pretrend_log_customs_unit_value_ref3 | 11 | 6.4037 | 0.8451 | no | 0.0351 | 0.0167 | 0.0202 | 0.0252 | 0.0513 | 0.6613 | 0.6838 | 1.7404 | 0.0015 | 0.0015 | 0.3333 | 0.0075 | yes | no | no | no | 0.0588 | 2.0000 | 0.2000 | PRECISE_NULL_EFFECT_BOUNDED | -3 |  |  |  |
| pretrend_log_customs_unit_value_ref1 | 11 | 6.6462 | 0.8270 | no | 0.0329 | 0.0170 | 0.0196 | 0.0241 | 0.0491 | 0.7055 | 0.6697 | 1.6819 | 0.0016 | 0.0016 | 0.3668 | 0.0078 | yes | no | no | no | 0.0569 | 2.0000 | 0.2000 | PRECISE_NULL_EFFECT_BOUNDED | -1 |  |  |  |
| pretrend_log_landed_unit_value_ref3 | 11 | 6.9563 | 0.8026 | no | 0.0394 | 0.0173 | 0.1408 | 0.1453 | 0.1861 | 0.1190 | 0.2118 | 0.2799 | 0.0008 | 0.0016 | 0.6369 | 0.0039 | no | yes | yes | no |  | 2.0000 | 0.2000 | CLEAN | -3 |  |  |  |
| pretrend_log_landed_unit_value_ref1 | 11 | 7.2847 | 0.7756 | no | 0.0418 | 0.0176 | 0.1432 | 0.1476 | 0.1885 | 0.1195 | 0.2218 | 0.2919 | 0.0010 | 0.0018 | 0.5874 | 0.0050 | no | yes | yes | no |  | 2.0000 | 0.2000 | CLEAN | -1 |  |  |  |
| pretrend_log_quantity_ref3 | 11 | 92.9244 | 0.0000 | yes | 0.1683 | 0.0869 | 0.3362 | 0.3742 | 0.5407 | 0.2322 | 0.3112 | 0.5004 | 0.0078 | 0.0066 | 0.2694 | 0.0389 | no | no | yes | no |  | 2.0000 | 0.2000 | NOISY_PRE_PERIOD_NO_SLOPE | -3 |  |  |  |
| pretrend_log_quantity_ref1 | 11 | 174.3550 | 0.0000 | yes | 0.2192 | 0.1223 | 0.3872 | 0.4206 | 0.5916 | 0.2908 | 0.3705 | 0.5662 | 0.0057 | 0.0070 | 0.4394 | 0.0283 | no | no | yes | no |  | 2.0000 | 0.2000 | NOISY_PRE_PERIOD_NO_SLOPE | -1 |  |  |  |
| pretrend_stacked_log_landed_unit_value_never_treated_products | 11 | 11.6452 | 0.3909 | no | 0.0387 | 0.0249 | 0.1544 | 0.1585 | 0.1926 | 0.1569 | 0.2008 | 0.2503 | 0.0033 | 0.0019 | 0.1145 | 0.0167 | no | yes | yes | no |  | 2.0000 | 0.2000 | CLEAN |  | stacked_multi_wave | never_treated_products |  |
| pretrend_stacked_log_customs_unit_value_never_treated_products | 11 | 11.0541 | 0.4387 | no | 0.0367 | 0.0242 | 0.0265 | 0.0339 | 0.0602 | 0.7124 | 0.6094 | 1.3857 | 0.0032 | 0.0019 | 0.1331 | 0.0158 | yes | no | no | no | 0.0760 | 2.0000 | 0.2000 | PRECISE_NULL_EFFECT_BOUNDED |  | stacked_multi_wave | never_treated_products |  |
| pretrend_stacked_log_quantity_never_treated_products | 11 | 71.8141 | 0.0000 | yes | 0.1536 | 0.0852 | 0.3793 | 0.4179 | 0.6077 | 0.2038 | 0.2527 | 0.4048 | 0.0065 | 0.0062 | 0.3211 | 0.0326 | no | no | yes | no |  | 2.0000 | 0.2000 | NOISY_PRE_PERIOD_NO_SLOPE |  | stacked_multi_wave | never_treated_products |  |
| pretrend_stacked_log_landed_unit_value_not_yet_treated | 11 | 7.5743 | 0.7509 | no | 0.0377 | 0.0193 | 0.1513 | 0.1559 | 0.1922 | 0.1240 | 0.1960 | 0.2488 | 0.0012 | 0.0018 | 0.5050 | 0.0061 | no | yes | yes | no |  | 2.0000 | 0.2000 | CLEAN |  | stacked_multi_wave | not_yet_treated |  |
| pretrend_stacked_log_customs_unit_value_not_yet_treated | 11 | 7.7510 | 0.7354 | no | 0.0313 | 0.0196 | 0.0270 | 0.0350 | 0.0628 | 0.5598 | 0.4983 | 1.1592 | 0.0022 | 0.0017 | 0.2154 | 0.0111 | yes | no | no | no | 0.0740 | 2.0000 | 0.2000 | PRECISE_NULL_EFFECT_BOUNDED |  | stacked_multi_wave | not_yet_treated |  |
| pretrend_stacked_log_quantity_not_yet_treated | 11 | 111.1936 | 0.0000 | yes | 0.1784 | 0.1040 | 0.3710 | 0.4071 | 0.5862 | 0.2556 | 0.3042 | 0.4808 | 0.0112 | 0.0063 | 0.1109 | 0.0559 | no | no | yes | no |  | 2.0000 | 0.2000 | NOISY_PRE_PERIOD_NO_SLOPE |  | stacked_multi_wave | not_yet_treated |  |
| pretrend_stacked_log_landed_unit_value_never_treated_products_treated_country_only | 11 | 8.9660 | 0.6250 | no | 0.0728 | 0.0354 | 0.1979 | 0.2091 | 0.2760 | 0.1691 | 0.2637 | 0.3678 | 0.0059 | 0.0013 | 0.0016 | 0.0295 | no | yes | yes | yes |  | 2.0000 | 0.2000 | CLEAN |  | stacked_multi_wave | never_treated_products_treated_country_only |  |
| pretrend_stacked_log_customs_unit_value_never_treated_products_treated_country_only | 11 | 9.8038 | 0.5481 | no | 0.0736 | 0.0370 | 0.0619 | 0.0744 | 0.1234 | 0.4969 | 0.5968 | 1.1886 | 0.0063 | 0.0012 | 0.0006 | 0.0314 | yes | no | yes | yes |  | 2.0000 | 0.2000 | PRETREND_PRESENT |  | stacked_multi_wave | never_treated_products_treated_country_only |  |
| pretrend_stacked_log_quantity_never_treated_products_treated_country_only | 11 | 46.7457 | 0.0000 | yes | 0.2324 | 0.1192 | 0.5402 | 0.5539 | 0.7294 | 0.2153 | 0.3186 | 0.4303 | 0.0123 | 0.0050 | 0.0371 | 0.0613 | no | no | yes | yes |  | 2.0000 | 0.2000 | NOISY_PRE_PERIOD_NO_SLOPE |  | stacked_multi_wave | never_treated_products_treated_country_only |  |
| pretrend_stable_codes_log_landed_unit_value | 11 | 21.2848 | 0.0305 | yes | 0.0551 | 0.0339 | 0.1362 | 0.1404 | 0.1794 | 0.2411 | 0.3069 | 0.4043 | 0.0038 | 0.0018 | 0.0581 | 0.0191 | no | no | yes | no |  | 2.0000 | 0.2000 | NOISY_PRE_PERIOD_NO_SLOPE |  | stacked_multi_wave | never_treated_products | codes_observed_in_every_month |
| pretrend_stable_codes_log_customs_unit_value | 11 | 19.9993 | 0.0454 | yes | 0.0532 | 0.0328 | 0.0176 | 0.0230 | 0.0434 | 1.4276 | 1.2270 | 3.0215 | 0.0037 | 0.0018 | 0.0693 | 0.0183 | yes | no | no | no | 0.0617 | 2.0000 | 0.2000 | PRECISE_NULL_EFFECT_BOUNDED |  | stacked_multi_wave | never_treated_products | codes_observed_in_every_month |
| pretrend_stable_codes_log_quantity | 11 | 61.8087 | 0.0000 | yes | 0.1390 | 0.0782 | 0.3732 | 0.4127 | 0.5986 | 0.1894 | 0.2323 | 0.3725 | 0.0067 | 0.0063 | 0.3142 | 0.0335 | no | yes | yes | no |  | 2.0000 | 0.2000 | CLEAN |  | stacked_multi_wave | never_treated_products | codes_observed_in_every_month |


## Placebo and stability checks

Each check is reported whether or not it is favourable.

**checks**

| check | outcome | description | n_obs | max_abs_post_coef | any_post_significant_5pct | status | interpretation | note | treatment_used | label | n_variants | estimate_spread | min | max |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| placebo_treatment_date_minus_12m | log_customs_unit_value | treatment date moved 12 months earlier, pre-period sample only | 268029 | 0.0351 | no | PASS | a significant 'effect' here means the design picks up differential trends rather than the tariff, for this outcome |  |  |  |  |  |  |  |
| placebo_treatment_date_minus_12m | log_landed_unit_value | treatment date moved 12 months earlier, pre-period sample only | 268029 | 0.0349 | no | PASS | a significant 'effect' here means the design picks up differential trends rather than the tariff, for this outcome |  |  |  |  |  |  |  |
| placebo_treatment_date_minus_12m | log_quantity | treatment date moved 12 months earlier, pre-period sample only | 268029 | 0.0934 | yes | FAIL | a significant 'effect' here means the design picks up differential trends rather than the tariff, for this outcome |  |  |  |  |  |  |  |
| placebo_product_group |  | half the never-treated products labelled treated at the real date | 37035 | 0.2286 | no |  |  |  |  |  |  |  |  |  |
| announcement_vs_effective |  |  |  |  |  | PARTIAL |  | the tariff schedule stores announcement and effective dates separately and the event study uses the effective date; an announcement-dated variant requires re-deriving event time from announcement_date and is listed as a remaining milestone | additional_tariff_rate | effective_date_treatment |  |  |  |  |
| leave_one_chapter_out |  |  |  |  |  |  |  |  |  |  | 10 | 0.2253 | -1.9512 | -1.7259 |
| leave_one_country_out |  |  |  |  |  |  |  |  |  |  | 8 |  |  |  |


## Leave-one-chapter-out

**Leave-one-chapter-out**

| dropped_chapter | estimate | std_error | n_obs | run_id | git_commit | config | data_provenance | data_period |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 39 | -1.7357 | 0.1008 | 546665 | 20260811T201214Z-b1495fb3 | 3c51a06-dirty | sample_slice.yaml | OFFICIAL | 2017-01..2020-02 |
| 40 | -1.8282 | 0.0963 | 569735 | 20260811T201214Z-b1495fb3 | 3c51a06-dirty | sample_slice.yaml | OFFICIAL | 2017-01..2020-02 |
| 44 | -1.8423 | 0.0974 | 575929 | 20260811T201214Z-b1495fb3 | 3c51a06-dirty | sample_slice.yaml | OFFICIAL | 2017-01..2020-02 |
| 48 | -1.8462 | 0.0992 | 571760 | 20260811T201214Z-b1495fb3 | 3c51a06-dirty | sample_slice.yaml | OFFICIAL | 2017-01..2020-02 |
| 73 | -1.9128 | 0.1012 | 528068 | 20260811T201214Z-b1495fb3 | 3c51a06-dirty | sample_slice.yaml | OFFICIAL | 2017-01..2020-02 |
| 76 | -1.8403 | 0.0965 | 583266 | 20260811T201214Z-b1495fb3 | 3c51a06-dirty | sample_slice.yaml | OFFICIAL | 2017-01..2020-02 |
| 84 | -1.9512 | 0.1214 | 423070 | 20260811T201214Z-b1495fb3 | 3c51a06-dirty | sample_slice.yaml | OFFICIAL | 2017-01..2020-02 |
| 85 | -1.7259 | 0.1084 | 472615 | 20260811T201214Z-b1495fb3 | 3c51a06-dirty | sample_slice.yaml | OFFICIAL | 2017-01..2020-02 |
| 87 | -1.8904 | 0.0987 | 556899 | 20260811T201214Z-b1495fb3 | 3c51a06-dirty | sample_slice.yaml | OFFICIAL | 2017-01..2020-02 |
| 94 | -1.7949 | 0.0952 | 574540 | 20260811T201214Z-b1495fb3 | 3c51a06-dirty | sample_slice.yaml | OFFICIAL | 2017-01..2020-02 |


## Leave-one-country-out

**Leave-one-country-out**

| dropped_country | estimate | std_error | n_obs | run_id | git_commit | config | data_provenance | data_period |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1220 | -1.9766 | 0.0983 | 500201 | 20260811T201214Z-b1495fb3 | 3c51a06-dirty | sample_slice.yaml | OFFICIAL | 2017-01..2020-02 |
| 2010 | -1.8373 | 0.0982 | 520487 | 20260811T201214Z-b1495fb3 | 3c51a06-dirty | sample_slice.yaml | OFFICIAL | 2017-01..2020-02 |
| 5330 | -1.7561 | 0.0957 | 544622 | 20260811T201214Z-b1495fb3 | 3c51a06-dirty | sample_slice.yaml | OFFICIAL | 2017-01..2020-02 |
| 5490 | -1.7864 | 0.0955 | 559330 | 20260811T201214Z-b1495fb3 | 3c51a06-dirty | sample_slice.yaml | OFFICIAL | 2017-01..2020-02 |
| 5520 | -1.6898 | 0.0940 | 567820 | 20260811T201214Z-b1495fb3 | 3c51a06-dirty | sample_slice.yaml | OFFICIAL | 2017-01..2020-02 |
| 5590 | -1.8550 | 0.0970 | 578901 | 20260811T201214Z-b1495fb3 | 3c51a06-dirty | sample_slice.yaml | OFFICIAL | 2017-01..2020-02 |
| 5800 | -1.8500 | 0.0973 | 535633 | 20260811T201214Z-b1495fb3 | 3c51a06-dirty | sample_slice.yaml | OFFICIAL | 2017-01..2020-02 |
| 5880 | -1.9438 | 0.0976 | 516324 | 20260811T201214Z-b1495fb3 | 3c51a06-dirty | sample_slice.yaml | OFFICIAL | 2017-01..2020-02 |


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
