# Trade Diversion — Results

> **DATA PROVENANCE: OFFICIAL SOURCES**
>
> All figures below derive from official statistical or legal sources.
>
> run_id `20260811T201708Z-b1495fb3` · git `3c51a06-dirty` · config `sample_slice.yaml` (sha256 `b1495fb3b363`) · data period 2017-01 to 2020-02 · generated 2026-08-11T20:17:08.149704+00:00


How much sourcing moved away from the treated country, and where it went. The contraction of treated-country imports and the expansion of third-country imports are distinct quantities measured separately.

## Raw decomposition (monthly-average customs value)

- Treated-country change: **-2,073,786,984** (intensive -2,068,881,140, extensive -4,905,844)
- Alternative-source change: **720,472,276** (intensive 774,670,184, extensive -54,197,908)
- Net change in total imports of the treated products: **-1,353,314,707**

The two directions are reported separately and are never netted into one 'diversion' figure.

**totals**

| treated_intensive | treated_extensive | alternative_intensive | alternative_extensive | treated_total | alternative_total | total_change | pre_treated_value | pre_alternative_value | pre_total_value | post_total_value | n_alt_suppliers_entered | n_alt_suppliers_exited | n_treated_flows_exited | treated_pct_change | replacement_ratio | run_id | git_commit | data_provenance | data_period |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| -2,068,881,139.5702 | -4,905,844.3526 | 774,670,184.4313 | -54,197,907.9828 | -2,073,786,983.9228 | 720,472,276.4485 | -1,353,314,707.4743 | 6,629,075,527.6650 | 18,459,725,817.0216 | 25,088,801,344.6866 | 23,735,486,637.2124 | 528 | 693 | 25 | -0.3128 | 0.3474 | 20260811T201500Z-b1495fb3 | 3c51a06-dirty | OFFICIAL | 2017-01..2020-02 |


## Why the raw replacement ratio is not the headline

A raw pre-versus-post comparison credits ordinary trade growth to the tariff. Over this window that inflates apparent third-country expansion and can push the replacement ratio above one when nothing was replaced. The counterfactual-adjusted table below nets out the growth of never-treated products, country by country, and is the figure to read.

## Counterfactual-adjusted decomposition

**by partner**

| country_code | pre_monthly_value | post_monthly_value | counterfactual_post_value | excess_change | control_growth_factor | is_treated_country | excess_pct_vs_counterfactual | run_id | git_commit | data_provenance | data_period |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 5800 | 1,670,235,072.4787 | 1,929,192,076.6250 | 1,276,009,494.1085 | 653,182,582.5166 | 0.7640 | no | 0.5119 | 20260811T201500Z-b1495fb3 | 3c51a06-dirty | OFFICIAL | 2017-01..2020-02 |
| 5880 | 2,902,026,140.5053 | 3,052,541,533.7203 | 2,857,122,847.6234 | 195,418,686.0969 | 0.9845 | no | 0.0684 | 20260811T201500Z-b1495fb3 | 3c51a06-dirty | OFFICIAL | 2017-01..2020-02 |
| 5590 | 387,809,669.0460 | 337,500,302.5100 | 295,944,857.7682 | 41,555,444.7418 | 0.7631 | no | 0.1404 | 20260811T201500Z-b1495fb3 | 3c51a06-dirty | OFFICIAL | 2017-01..2020-02 |
| 5330 | 331,650,025.5026 | 362,261,397.2462 | 334,911,857.7849 | 27,349,539.4612 | 1.0098 | no | 0.0817 | 20260811T201500Z-b1495fb3 | 3c51a06-dirty | OFFICIAL | 2017-01..2020-02 |
| 5490 | 583,538,833.6064 | 584,206,411.0553 | 599,269,325.4480 | -15,062,914.3927 | 1.0270 | no | -0.0251 | 20260811T201500Z-b1495fb3 | 3c51a06-dirty | OFFICIAL | 2017-01..2020-02 |
| 5520 | 587,636,590.5950 | 601,314,813.7489 | 674,777,990.1173 | -73,463,176.3684 | 1.1483 | no | -0.1089 | 20260811T201500Z-b1495fb3 | 3c51a06-dirty | OFFICIAL | 2017-01..2020-02 |
| 2010 | 7,802,609,601.5136 | 8,215,574,073.9560 | 8,380,678,177.2023 | -165,104,103.2463 | 1.0741 | no | -0.0197 | 20260811T201500Z-b1495fb3 | 3c51a06-dirty | OFFICIAL | 2017-01..2020-02 |
| 1220 | 4,194,219,883.7740 | 4,097,607,484.6085 | 4,509,820,612.5206 | -412,213,127.9122 | 1.0752 | no | -0.0914 | 20260811T201500Z-b1495fb3 | 3c51a06-dirty | OFFICIAL | 2017-01..2020-02 |
| 5700 | 6,629,075,527.6651 | 4,555,288,543.7422 | 6,810,805,467.0086 | -2,255,516,923.2664 | 1.0274 | yes | -0.3312 | 20260811T201500Z-b1495fb3 | 3c51a06-dirty | OFFICIAL | 2017-01..2020-02 |


## Partner-country detail

**countries**

| country_code | pre_monthly_value | post_monthly_value | change | pct_change | is_treated_country | pre_share | post_share | share_change | run_id | git_commit | data_provenance | data_period |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2010 | 7,802,609,601.5136 | 8,215,574,073.9560 | 412,964,472.4424 | 0.0529 | no | 0.3110 | 0.3461 | 0.0351 | 20260811T201500Z-b1495fb3 | 3c51a06-dirty | OFFICIAL | 2017-01..2020-02 |
| 5800 | 1,670,235,072.4787 | 1,929,192,076.6250 | 258,957,004.1463 | 0.1550 | no | 0.0666 | 0.0813 | 0.0147 | 20260811T201500Z-b1495fb3 | 3c51a06-dirty | OFFICIAL | 2017-01..2020-02 |
| 5880 | 2,902,026,140.5053 | 3,052,541,533.7203 | 150,515,393.2150 | 0.0519 | no | 0.1157 | 0.1286 | 0.0129 | 20260811T201500Z-b1495fb3 | 3c51a06-dirty | OFFICIAL | 2017-01..2020-02 |
| 5330 | 331,650,025.5026 | 362,261,397.2462 | 30,611,371.7436 | 0.0923 | no | 0.0132 | 0.0153 | 0.0020 | 20260811T201500Z-b1495fb3 | 3c51a06-dirty | OFFICIAL | 2017-01..2020-02 |
| 5520 | 587,636,590.5950 | 601,314,813.7489 | 13,678,223.1539 | 0.0233 | no | 0.0234 | 0.0253 | 0.0019 | 20260811T201500Z-b1495fb3 | 3c51a06-dirty | OFFICIAL | 2017-01..2020-02 |
| 5490 | 583,538,833.6064 | 584,206,411.0553 | 667,577.4488 | 0.0011 | no | 0.0233 | 0.0246 | 0.0014 | 20260811T201500Z-b1495fb3 | 3c51a06-dirty | OFFICIAL | 2017-01..2020-02 |
| 5590 | 387,809,669.0460 | 337,500,302.5100 | -50,309,366.5360 | -0.1297 | no | 0.0155 | 0.0142 | -0.0012 | 20260811T201500Z-b1495fb3 | 3c51a06-dirty | OFFICIAL | 2017-01..2020-02 |
| 1220 | 4,194,219,883.7740 | 4,097,607,484.6085 | -96,612,399.1655 | -0.0230 | no | 0.1672 | 0.1726 | 0.0055 | 20260811T201500Z-b1495fb3 | 3c51a06-dirty | OFFICIAL | 2017-01..2020-02 |
| 5700 | 6,629,075,527.6650 | 4,555,288,543.7422 | -2,073,786,983.9228 | -0.3128 | yes | 0.2642 | 0.1919 | -0.0723 | 20260811T201500Z-b1495fb3 | 3c51a06-dirty | OFFICIAL | 2017-01..2020-02 |


## Heterogeneity by pre-treatment dependence

**groups**

| dependence_group | n_products | treated_change | alternative_change | pre_treated_value | median_replacement_ratio | treated_pct_change | run_id | git_commit | data_provenance | data_period |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| high_dependence | 685 | -1,606,237,029.8969 | 392,958,267.0805 | 5,195,350,110.2640 | 0.1410 | -0.3092 | 20260811T201500Z-b1495fb3 | 3c51a06-dirty | OFFICIAL | 2017-01..2020-02 |
| low_dependence | 686 | -467,551,251.1371 | 327,514,009.3680 | 1,433,725,417.4010 | 0.5694 | -0.3261 | 20260811T201500Z-b1495fb3 | 3c51a06-dirty | OFFICIAL | 2017-01..2020-02 |


## Interpretation limits

- The RAW pre-versus-post decomposition attributes ordinary trade growth to the tariff and its replacement ratio is not interpretable on its own. Use the counterfactual-adjusted figures.
- An increase in imports from a third country is not evidence of production relocation. Rerouting of treated-origin goods, transshipment, and origin misdeclaration produce the same pattern in customs data.
- The replacement ratio compares value flows only. It says nothing about whether the replacing goods are the same quality or the same variety.
- Domestic substitution is invisible in import data. A fall in imports that is not matched by third-country gains may reflect domestic production, lower final demand, or inventory drawdown, and these cannot be separated without domestic output data.
- The supplier set is the configured comparison group, not the world. Concentration measures are within-sample.

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
