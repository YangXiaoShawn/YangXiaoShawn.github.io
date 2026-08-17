# Supply-Chain Propagation

> **DATA PROVENANCE: OFFICIAL SOURCES**
>
> All figures below derive from official statistical or legal sources.
>
> run_id `20260811T201708Z-b1495fb3` · git `3c51a06-dirty` · config `sample_slice.yaml` (sha256 `b1495fb3b363`) · data period 2017-01 to 2020-02 · generated 2026-08-11T20:17:08.149704+00:00


Mapping product-level tariff exposure into U.S. industries using pre-treatment BEA input-output weights. Pre-treatment weights are used so that the exposure measure cannot respond to the shock it is being used to explain.

## Exposure channels, measured separately

Protection on an industry's own output and the cost of its imported inputs pull in opposite directions. They are reported as two numbers. A net figure would hide the distributional question that motivates the analysis, so the `net_contrast_do_not_use_alone` column is present only for contrast and is named accordingly.

**19 industries are exposed through both channels at once.**

**summary by class**

| exposure_class | n_industries | mean_protection | mean_input_cost | mean_downstream |
| --- | --- | --- | --- | --- |
| INPUT_COST_EXPOSED_ONLY | 29 | 0.0000 | 0.0112 | 0.0557 |
| LITTLE_DIRECT_EXPOSURE | 23 | 0.0000 | 0.0024 | 0.0355 |
| BOTH_PROTECTED_AND_COST_EXPOSED | 19 | 0.1904 | 0.0429 | 0.3084 |


## Industries exposed through both channels

**both channels**

| industry_code | industry_name | output_protection_exposure | imported_input_cost_exposure | downstream_total_requirements_exposure |
| --- | --- | --- | --- | --- |
| 3361MV | Motor vehicles, bodies and trailers, and parts | 0.2308 | 0.0912 | 0.4087 |
| 326 | Plastics and rubber products | 0.1902 | 0.0677 | 0.3155 |
| 322 | Paper products | 0.2211 | 0.0642 | 0.4042 |
| 333 | Machinery | 0.2303 | 0.0530 | 0.3225 |
| 311FT | Food and beverage and tobacco products | 0.2500 | 0.0497 | 0.3406 |
| 337 | Furniture and related products | 0.2197 | 0.0488 | 0.2353 |
| 313TT | Textile mills and textile product mills | 0.0752 | 0.0479 | 0.1472 |
| 321 | Wood products | 0.1498 | 0.0469 | 0.2540 |
| 325 | Chemical products | 0.2231 | 0.0451 | 0.6180 |
| 3364OT | Other transportation equipment | 0.2227 | 0.0450 | 0.2820 |
| 335 | Electrical equipment, appliances, and components | 0.2141 | 0.0430 | 0.2616 |
| 332 | Fabricated metal products | 0.2248 | 0.0429 | 0.4690 |
| 331 | Primary metals | 0.1460 | 0.0397 | 0.5155 |
| 323 | Printing and related support activities | 0.2492 | 0.0363 | 0.2649 |
| 327 | Nonmetallic mineral products | 0.2500 | 0.0312 | 0.3133 |
| 339 | Miscellaneous manufacturing | 0.1776 | 0.0265 | 0.2012 |
| 315AL | Apparel and leather and allied products | 0.1784 | 0.0140 | 0.1800 |
| 334 | Computer and electronic products | 0.1296 | 0.0135 | 0.2391 |
| 113FF | Forestry, fishing, and related activities | 0.0359 | 0.0088 | 0.0870 |


## Highest imported-input cost exposure

**input cost**

| industry_code | industry_name | imported_input_cost_exposure | output_protection_exposure | exposure_class |
| --- | --- | --- | --- | --- |
| 3361MV | Motor vehicles, bodies and trailers, and parts | 0.0912 | 0.2308 | BOTH_PROTECTED_AND_COST_EXPOSED |
| 326 | Plastics and rubber products | 0.0677 | 0.1902 | BOTH_PROTECTED_AND_COST_EXPOSED |
| 322 | Paper products | 0.0642 | 0.2211 | BOTH_PROTECTED_AND_COST_EXPOSED |
| 333 | Machinery | 0.0530 | 0.2303 | BOTH_PROTECTED_AND_COST_EXPOSED |
| 311FT | Food and beverage and tobacco products | 0.0497 | 0.2500 | BOTH_PROTECTED_AND_COST_EXPOSED |
| 337 | Furniture and related products | 0.0488 | 0.2197 | BOTH_PROTECTED_AND_COST_EXPOSED |
| 313TT | Textile mills and textile product mills | 0.0479 | 0.0752 | BOTH_PROTECTED_AND_COST_EXPOSED |
| 321 | Wood products | 0.0469 | 0.1498 | BOTH_PROTECTED_AND_COST_EXPOSED |
| 325 | Chemical products | 0.0451 | 0.2231 | BOTH_PROTECTED_AND_COST_EXPOSED |
| 3364OT | Other transportation equipment | 0.0450 | 0.2227 | BOTH_PROTECTED_AND_COST_EXPOSED |
| 335 | Electrical equipment, appliances, and components | 0.0430 | 0.2141 | BOTH_PROTECTED_AND_COST_EXPOSED |
| 332 | Fabricated metal products | 0.0429 | 0.2248 | BOTH_PROTECTED_AND_COST_EXPOSED |
| 331 | Primary metals | 0.0397 | 0.1460 | BOTH_PROTECTED_AND_COST_EXPOSED |
| 323 | Printing and related support activities | 0.0363 | 0.2492 | BOTH_PROTECTED_AND_COST_EXPOSED |
| 23 | Construction | 0.0330 | 0.0000 | INPUT_COST_EXPOSED_ONLY |


## Highest output protection

**protection**

| industry_code | industry_name | output_protection_exposure | imported_input_cost_exposure | exposure_class |
| --- | --- | --- | --- | --- |
| 311FT | Food and beverage and tobacco products | 0.2500 | 0.0497 | BOTH_PROTECTED_AND_COST_EXPOSED |
| 327 | Nonmetallic mineral products | 0.2500 | 0.0312 | BOTH_PROTECTED_AND_COST_EXPOSED |
| 323 | Printing and related support activities | 0.2492 | 0.0363 | BOTH_PROTECTED_AND_COST_EXPOSED |
| 3361MV | Motor vehicles, bodies and trailers, and parts | 0.2308 | 0.0912 | BOTH_PROTECTED_AND_COST_EXPOSED |
| 333 | Machinery | 0.2303 | 0.0530 | BOTH_PROTECTED_AND_COST_EXPOSED |
| 332 | Fabricated metal products | 0.2248 | 0.0429 | BOTH_PROTECTED_AND_COST_EXPOSED |
| 325 | Chemical products | 0.2231 | 0.0451 | BOTH_PROTECTED_AND_COST_EXPOSED |
| 3364OT | Other transportation equipment | 0.2227 | 0.0450 | BOTH_PROTECTED_AND_COST_EXPOSED |
| 322 | Paper products | 0.2211 | 0.0642 | BOTH_PROTECTED_AND_COST_EXPOSED |
| 337 | Furniture and related products | 0.2197 | 0.0488 | BOTH_PROTECTED_AND_COST_EXPOSED |
| 335 | Electrical equipment, appliances, and components | 0.2141 | 0.0430 | BOTH_PROTECTED_AND_COST_EXPOSED |
| 326 | Plastics and rubber products | 0.1902 | 0.0677 | BOTH_PROTECTED_AND_COST_EXPOSED |
| 315AL | Apparel and leather and allied products | 0.1784 | 0.0140 | BOTH_PROTECTED_AND_COST_EXPOSED |
| 339 | Miscellaneous manufacturing | 0.1776 | 0.0265 | BOTH_PROTECTED_AND_COST_EXPOSED |
| 321 | Wood products | 0.1498 | 0.0469 | BOTH_PROTECTED_AND_COST_EXPOSED |


## The same exposure at ten times the industry resolution

BEA publishes detail-level input-output tables for benchmark years only -- 2007, 2012, 2017 -- and 2017 is this project's pre-treatment year, so the finest published industry breakdown is available exactly where a shift-share measure needs its weights. Asking for a non-benchmark year raises rather than interpolating, because interpolated weights would be invented ones.

The coarser axis was not merely less precise. It reported as one number positions that differ substantially within a single summary industry:

inside summary industry `332`, which the detail level splits into 20 industries, all other forging, stamping, and sintering carries output protection 0.250 against input cost 0.037, while ammunition, arms, ordnance, and accessories manufacturing carries 0.000 against 0.026 — reported as one number by a 71-industry axis.

**granularity**

| measure | summary_level | detail_level |
| --- | --- | --- |
| BEA industries in the input-output table | 71 | 402 |
| industries exposed through both channels | 19 | 144 |
| industries with any protection exposure | 19 | 146 |
| mean output protection exposure | 0.0510 | 0.0775 |
| mean imported-input cost exposure | 0.0168 | 0.0230 |


## Why the two channels cannot be compared as levels

Output protection is the tariff rate on one commodity, so it inherits the statutory rate and tops out at it. Imported-input cost is an average over the industry's whole purchase basket, most of which -- services, domestic materials, untariffed imports -- carries no tariff at all, so it is mechanically diluted. At detail level protection averages 0.077 with a maximum of 0.250; input cost averages 0.023 with a maximum of 0.112.

A larger protection number than cost number therefore says nothing about which channel dominates for an industry. Only the separately estimated coefficients, each scaled by its own regressor, carry that information. This is a second reason not to difference the two, independent of the distributional reason given above.

**highest imported-input cost, detail level**

| industry_code | industry_name | imported_input_cost_exposure | output_protection_exposure | exposure_class |
| --- | --- | --- | --- | --- |
| 336120 | Heavy duty truck manufacturing | 0.1123 | 0.1624 | BOTH_PROTECTED_AND_COST_EXPOSED |
| 336310 | Motor vehicle gasoline engine and engine parts manufacturing | 0.1085 | 0.2480 | BOTH_PROTECTED_AND_COST_EXPOSED |
| 336112 | Light truck and utility vehicle manufacturing | 0.0983 | 0.2170 | BOTH_PROTECTED_AND_COST_EXPOSED |
| 3363A0 | Motor vehicle steering, suspension component (except spring), and brake systems manufacturing | 0.0940 | 0.2500 | BOTH_PROTECTED_AND_COST_EXPOSED |
| 333618 | Other engine equipment manufacturing | 0.0924 | 0.2498 | BOTH_PROTECTED_AND_COST_EXPOSED |
| 336212 | Truck trailer manufacturing | 0.0904 | 0.2300 | BOTH_PROTECTED_AND_COST_EXPOSED |
| 336320 | Motor vehicle electrical and electronic equipment manufacturing | 0.0896 | 0.2498 | BOTH_PROTECTED_AND_COST_EXPOSED |
| 336111 | Automobile manufacturing | 0.0895 | 0.2319 | BOTH_PROTECTED_AND_COST_EXPOSED |
| 336390 | Other motor vehicle parts manufacturing | 0.0874 | 0.2465 | BOTH_PROTECTED_AND_COST_EXPOSED |
| 336999 | All other transportation equipment manufacturing | 0.0857 | 0.2015 | BOTH_PROTECTED_AND_COST_EXPOSED |
| 326110 | Plastics packaging materials and unlaminated film and sheet manufacturing | 0.0846 | 0.2500 | BOTH_PROTECTED_AND_COST_EXPOSED |
| 336612 | Boat building | 0.0842 | 0.0000 | INPUT_COST_EXPOSED_ONLY |


## Does exposure show up in domestic producer prices?

Exposure is an accounting construct built from input-output weights. Whether it predicts anything is a separate question, tested here against BLS producer prices in the **NAICS industry** classification — the same classification the exposure measure is built in, so no second undocumented crosswalk is involved.

**All three channels carry the expected positive sign and none is statistically distinguishable from zero.** At this level that is a power result rather than evidence of no effect: the confidence interval on imported-input cost exposure spans roughly −1% to +9% of producer prices at mean exposure, which is uninformative rather than a bound near zero. The detail-level run below is the answer to it.

Why power is low here is not a mystery. There are 22 industries with a matched series, so 22 clusters; cluster-robust standard errors over-reject at that count, so every coefficient also carries a wild cluster bootstrap p-value with the null imposed. And PPI industry indices cover an entire NAICS group while exposure is built from 10-digit trade lines, which attenuates any true relationship toward zero.

Entering both channels together halves the input-cost coefficient, because the two exposures are correlated across industries: an industry that buys tariffed inputs tends also to sell tariffed output. Reporting either alone would attribute the other's variation to it.

**estimates**

| channel | estimate | ci_low | ci_high | analytic_p_value | bootstrap_p_value | n_obs | n_clusters |
| --- | --- | --- | --- | --- | --- | --- | --- |
| imported_input_cost_exposure | 1.2295 | -0.4496 | 2.9087 | 0.1427 | 0.1141 | 1056 | 22 |
| output_protection_exposure | 0.3736 | -0.0502 | 0.7973 | 0.0810 | 0.0841 | 1056 | 22 |
| downstream_total_requirements_exposure | 0.1642 | -0.0504 | 0.3788 | 0.1264 | 0.1081 | 1056 | 22 |
| joint::input_cost_x_post | 0.3473 | -0.4319 | 1.1266 | 0.3645 | 0.5646 | 1056 | 22 |
| joint::protection_x_post | 0.3221 | -0.0546 | 0.6989 | 0.0899 | 0.1752 | 1056 | 22 |


## The same test at ten times the industry resolution

The summary level gives 22 clusters. BEA's detail tables give **256**, because every industry with a producer-price series enters — those with no tariff exposure are legitimate controls in a continuous-treatment design, not a sample restriction.

**The power limit is resolved, and the answer is still no detectable effect.** That is now a result rather than a limitation. At mean exposure the imported-input cost channel is bounded within **[−0.14%, +0.81%]** of producer prices and output protection within **[−0.10%, +0.74%]** — against a summary-level interval spanning roughly −1% to +9%. The downstream Leontief channel is the tightest and now sits slightly negative, bounded within ±0.03 in coefficient terms.

**One thing this does not do, stated because it would be easy to dress up.** The intervals narrowed about eightfold, but the point estimates shrank by about the same factor, so the t-statistics barely moved: 1.52 to 1.37 on input cost, 1.83 to 1.51 on protection. The finer axis bought precision in **economic** terms — what magnitudes the data can exclude — not in statistical detectability. Had the coefficient held at its summary-level value while the interval tightened, this would read as a detected effect; it does not.

**detail-level estimates**

| channel | estimate | ci_low | ci_high | bootstrap_p | t_stat | at_mean_exposure_pct | at_mean_ci_pct |
| --- | --- | --- | --- | --- | --- | --- | --- |
| imported_input_cost_exposure | 0.1441 | -0.0625 | 0.3506 | 0.1670 | 1.3700 | 0.3310 | [-0.14%, +0.81%] |
| output_protection_exposure | 0.0416 | -0.0127 | 0.0958 | 0.1360 | 1.5100 | 0.3220 | [-0.10%, +0.74%] |
| downstream_total_requirements_exposure | -0.0067 | -0.0279 | 0.0145 | 0.5430 | -0.6200 |  |  |


## Which industries have a producer-price series at all

Agriculture and forestry have no NAICS-industry PPI. They are reported unmatched rather than substituted from the commodity classification, which would be a second crosswalk presented as a measurement.

**PPI match quality**

| bea_industry | naics_components | matched_components | n_components | n_matched | match_quality |
| --- | --- | --- | --- | --- | --- |
| 322 | 322 | 322 | 1 | 1 | EXACT |
| 3361MV | 3361|3362|3363 | 3361|3362|3363 | 3 | 3 | COMPOSITE_UNWEIGHTED |
| 332 | 332 | 332 | 1 | 1 | EXACT |
| 211 | 211 | 211 | 1 | 1 | EXACT |
| 339 | 339 | 339 | 1 | 1 | EXACT |
| 323 | 323 | 323 | 1 | 1 | EXACT |
| 113FF | 113|114|115 |  | 3 | 0 | NONE |
| 313TT | 313|314 | 313|314 | 2 | 2 | COMPOSITE_UNWEIGHTED |
| 324 | 324 | 324 | 1 | 1 | EXACT |
| 326 | 326 | 326 | 1 | 1 | EXACT |
| 337 | 337 | 337 | 1 | 1 | EXACT |
| 333 | 333 | 333 | 1 | 1 | EXACT |
| 213 | 213 | 213 | 1 | 1 | EXACT |
| 212 | 212 | 212 | 1 | 1 | EXACT |
| 315AL | 315|316 | 315 | 2 | 1 | PARTIAL_COMPOSITE |
| 327 | 327 | 327 | 1 | 1 | EXACT |
| 334 | 334 | 334 | 1 | 1 | EXACT |
| 311FT | 311|312 | 311|312 | 2 | 2 | COMPOSITE_UNWEIGHTED |
| 331 | 331 | 331 | 1 | 1 | EXACT |
| 325 | 325 | 325 | 1 | 1 | EXACT |
| 111CA | 111|112 |  | 2 | 0 | NONE |
| 3364OT | 3364|3365|3366|3369 | 3364|3365|3366|3369 | 4 | 4 | COMPOSITE_UNWEIGHTED |
| 335 | 335 | 335 | 1 | 1 | EXACT |
| 321 | 321 | 321 | 1 | 1 | EXACT |


## Concordance quality and aggregation loss

Concordance status: **CENSUS_IMPORT_CONCORDANCE_2017_PRIMARY_2017_2020_HS10_TO_NAICS_TO_BEA**.

Each 10-digit commodity line carries exactly one NAICS industry in the official concordance, so no within-line weighting assumption is made. Aggregation loss remains only where Census itself writes an 'X' in a NAICS code to hide undisclosed detail, and where a line's NAICS falls outside the BEA summary manufacturing and primary groups. 172 codes carry a different NAICS in a later vintage; the pre-treatment assignment governs, and that count bounds how much the choice matters.

These exposure numbers are a qualitative ordering of industries. They are not elasticities and must not be used as inputs to a welfare calculation.

**concordance**

| concordance_method | concordance_level | n_mapped_products | n_unmapped_products | aggregation_loss | concordance_source | warnings |
| --- | --- | --- | --- | --- | --- | --- |
| CENSUS_IMPORT_CONCORDANCE_2017_PRIMARY_2017_2020_HS10_TO_NAICS_TO_BEA | HS10 -> NAICS 6-digit -> BEA summary industry | 4892 | 64 | Each 10-digit commodity line carries exactly one NAICS industry in the official concordance, so no within-line weighting assumption is made. Aggregation loss remains only where Census itself writes an 'X' in a NAICS code to hide undisclosed detail, and where a line's NAICS falls outside the BEA summary manufacturing and primary groups. 172 codes carry a different NAICS in a later vintage; the pre-treatment assignment governs, and that count bounds how much the choice matters. | Census import concordances [2017, 2018, 2019, 2020], primary 2017 | 64 products have no commodity mapping and are excluded |


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
