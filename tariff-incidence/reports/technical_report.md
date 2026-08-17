# Technical Report

> **DATA PROVENANCE: OFFICIAL SOURCES**
>
> All figures below derive from official statistical or legal sources.
>
> run_id `20260811T201708Z-b1495fb3` · git `3c51a06-dirty` · config `sample_slice.yaml` (sha256 `b1495fb3b363`) · data period 2017-01 to 2020-02 · generated 2026-08-11T20:17:08.149704+00:00


How the system is built and how each component is validated.

## Pipeline

```
Federal Register PDFs ──┐
USITC HTS (MFN, HS6→HS8)┼→ tariff schedule ──┐
                        │                    ├→ analytical panel ─┬→ incidence
Census imports (or the  ┘                    │                    ├→ diversion
synthetic generator) ────────────────────────┘                    └→ reports
BEA Supply-Use ───────────────────────────────→ industry exposure ─┘
```

## Datasets and manifests

**manifests**

| dataset | layer | rows | provenance | vintage | checksum |
| --- | --- | --- | --- | --- | --- |
| industry_tariff_exposure | results | 71 | OFFICIAL | BEA AllTablesSUP.zip, Summary level, year 2017 | 4cffd076ac9c |
| industry_tariff_exposure_detail | results | 402 | OFFICIAL | BEA AllTablesSUP.zip, Detail level, year 2017 | 19e06c2b49b1 |
| propagation_ppi_estimates | results | 5 | OFFICIAL | 2017-2020 | f2efecb7964e |
| propagation_ppi_estimates_detail | results | 5 | OFFICIAL | 2017-2020 | 91384ce5caf0 |
| structural_sourcing_counterfactual | results | 8 | OFFICIAL | sample_slice.yaml | b2e509d45dc0 |
| tariff_schedule_section301_china | normalized | 19053 | OFFICIAL | 83 FR 28710 (2018-13248); 83 FR 40823 (2018-17709); 83 FR 47974 (2018- | 2c22bd730169 |
| trade_panel_hs10_country_month | analytical | 923440 | OFFICIAL | Census live API | bc7bfe9a8132 |
| ustr_exclusion_notice_coverage | results | 11 | OFFICIAL | 2018-28277 (2018-12-28); 2019-05588 (2019-03-25); 2019-07758 (2019-04- | 951591f87a66 |


## Tariff-schedule parse validation

Each notice states how many tariff lines it covers. The parser is validated against that count rather than against an expectation supplied by the author.

**parses**

| document | chapter99_heading | full_lines | partial_lines | parsed_total | stated_in_notice | matches |
| --- | --- | --- | --- | --- | --- | --- |
| 2018-13248 | 9903.88.01 | 818 | 0 | 818 | 818 | yes |
| 2018-17709 | 9903.88.02 | 279 | 0 | 279 | 279 | yes |
| 2018-20610 | 9903.88.03 | 5734 | 11 | 5745 | 5745 | yes |
| 2019-09681 | 9903.88.03 | 5734 | 11 | 5745 | 5745 | yes |
| 2019-17865 | 9903.88.15 | 3229 | 4 | 3233 |  |  |
| 2020-00904 | 9903.88.15 | 3229 | 4 | 3233 |  |  |


## Codes truncated in the source rendering

Resolved only where the USITC HTS leaves exactly one candidate; marked DERIVED, never guessed.

**resolutions**

| document | truncated | resolved_to |
| --- | --- | --- |
| 2018-13248 | 9033.00 | 90330090 |


## Specifications estimated

**register**

| specification | outcome | estimator | treatment_definition | fixed_effects | cluster_vars | sample | weighting | aggregation_level | estimand | identifying_assumption | rung | reference_period | run_id | git_commit | config | data_provenance | data_period |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| twfe_log_customs_unit_value_on_additional_tariff_rate | log_customs_unit_value | OLS-HDFE | additional_tariff_rate | flow_id + month_key | hs6 | non-missing, finite outcome | unweighted | hs10 x country x month | average effect of the additional duty on the outcome | conditional on the absorbed effects, treated and untreated flows would have followed parallel paths | 2_twfe |  | 20260811T201214Z-b1495fb3 | 3c51a06-dirty | sample_slice.yaml | OFFICIAL | 2017-01..2020-02 |
| twfe_log_landed_unit_value_on_additional_tariff_rate | log_landed_unit_value | OLS-HDFE | additional_tariff_rate | flow_id + month_key | hs6 | non-missing, finite outcome | unweighted | hs10 x country x month | average effect of the additional duty on the outcome | conditional on the absorbed effects, treated and untreated flows would have followed parallel paths | 2_twfe |  | 20260811T201214Z-b1495fb3 | 3c51a06-dirty | sample_slice.yaml | OFFICIAL | 2017-01..2020-02 |
| twfe_log_quantity_on_additional_tariff_rate | log_quantity | OLS-HDFE | additional_tariff_rate | flow_id + month_key | hs6 | non-missing, finite outcome | unweighted | hs10 x country x month | average effect of the additional duty on the outcome | conditional on the absorbed effects, treated and untreated flows would have followed parallel paths | 2_twfe |  | 20260811T201214Z-b1495fb3 | 3c51a06-dirty | sample_slice.yaml | OFFICIAL | 2017-01..2020-02 |
| twfe_log_customs_value_on_additional_tariff_rate | log_customs_value | OLS-HDFE | additional_tariff_rate | flow_id + month_key | hs6 | non-missing, finite outcome | unweighted | hs10 x country x month | average effect of the additional duty on the outcome | conditional on the absorbed effects, treated and untreated flows would have followed parallel paths | 2_twfe |  | 20260811T201214Z-b1495fb3 | 3c51a06-dirty | sample_slice.yaml | OFFICIAL | 2017-01..2020-02 |
| event_study_log_customs_unit_value_ols | log_customs_unit_value | OLS-HDFE | event-time indicators interacted with is_treated_country; reference period -3 | flow_id + month_key | hs6 | event window [-12, 10] with binned endpoints | unweighted | hs10 x country x month | dynamic effect of the tariff action relative to the reference month | parallel trends absent treatment, no anticipation before the window | 3_event_study | -3 | 20260811T201214Z-b1495fb3 | 3c51a06-dirty | sample_slice.yaml | OFFICIAL | 2017-01..2020-02 |
| event_study_log_customs_unit_value_ols | log_customs_unit_value | OLS-HDFE | event-time indicators interacted with is_treated_country; reference period -1 | flow_id + month_key | hs6 | event window [-12, 10] with binned endpoints | unweighted | hs10 x country x month | dynamic effect of the tariff action relative to the reference month | parallel trends absent treatment, no anticipation before the window | 3_event_study | -1 | 20260811T201214Z-b1495fb3 | 3c51a06-dirty | sample_slice.yaml | OFFICIAL | 2017-01..2020-02 |
| event_study_log_landed_unit_value_ols | log_landed_unit_value | OLS-HDFE | event-time indicators interacted with is_treated_country; reference period -3 | flow_id + month_key | hs6 | event window [-12, 10] with binned endpoints | unweighted | hs10 x country x month | dynamic effect of the tariff action relative to the reference month | parallel trends absent treatment, no anticipation before the window | 3_event_study | -3 | 20260811T201214Z-b1495fb3 | 3c51a06-dirty | sample_slice.yaml | OFFICIAL | 2017-01..2020-02 |
| event_study_log_landed_unit_value_ols | log_landed_unit_value | OLS-HDFE | event-time indicators interacted with is_treated_country; reference period -1 | flow_id + month_key | hs6 | event window [-12, 10] with binned endpoints | unweighted | hs10 x country x month | dynamic effect of the tariff action relative to the reference month | parallel trends absent treatment, no anticipation before the window | 3_event_study | -1 | 20260811T201214Z-b1495fb3 | 3c51a06-dirty | sample_slice.yaml | OFFICIAL | 2017-01..2020-02 |
| event_study_log_quantity_ols | log_quantity | OLS-HDFE | event-time indicators interacted with is_treated_country; reference period -3 | flow_id + month_key | hs6 | event window [-12, 10] with binned endpoints | unweighted | hs10 x country x month | dynamic effect of the tariff action relative to the reference month | parallel trends absent treatment, no anticipation before the window | 3_event_study | -3 | 20260811T201214Z-b1495fb3 | 3c51a06-dirty | sample_slice.yaml | OFFICIAL | 2017-01..2020-02 |
| event_study_log_quantity_ols | log_quantity | OLS-HDFE | event-time indicators interacted with is_treated_country; reference period -1 | flow_id + month_key | hs6 | event window [-12, 10] with binned endpoints | unweighted | hs10 x country x month | dynamic effect of the tariff action relative to the reference month | parallel trends absent treatment, no anticipation before the window | 3_event_study | -1 | 20260811T201214Z-b1495fb3 | 3c51a06-dirty | sample_slice.yaml | OFFICIAL | 2017-01..2020-02 |
| stacked_event_study_log_landed_unit_value_never_treated_products | log_landed_unit_value | OLS-HDFE | event-time indicators interacted with stack_treated; reference period -3 | flow x stack + calendar month x stack | hs6 | stacked sub-experiments, one per wave, window [-12, 10]; controls = never_treated_products | unweighted | hs10 x country x month | dynamic effect of a wave relative to event month -3, pooled across waves with wave-specific calendar-time effects | within each sub-experiment, treated and control products would have followed parallel paths absent that wave | 4_stacked |  | 20260811T201214Z-b1495fb3 | 3c51a06-dirty | sample_slice.yaml | OFFICIAL | 2017-01..2020-02 |
| stacked_event_study_log_customs_unit_value_never_treated_products | log_customs_unit_value | OLS-HDFE | event-time indicators interacted with stack_treated; reference period -3 | flow x stack + calendar month x stack | hs6 | stacked sub-experiments, one per wave, window [-12, 10]; controls = never_treated_products | unweighted | hs10 x country x month | dynamic effect of a wave relative to event month -3, pooled across waves with wave-specific calendar-time effects | within each sub-experiment, treated and control products would have followed parallel paths absent that wave | 4_stacked |  | 20260811T201214Z-b1495fb3 | 3c51a06-dirty | sample_slice.yaml | OFFICIAL | 2017-01..2020-02 |
| stacked_event_study_log_quantity_never_treated_products | log_quantity | OLS-HDFE | event-time indicators interacted with stack_treated; reference period -3 | flow x stack + calendar month x stack | hs6 | stacked sub-experiments, one per wave, window [-12, 10]; controls = never_treated_products | unweighted | hs10 x country x month | dynamic effect of a wave relative to event month -3, pooled across waves with wave-specific calendar-time effects | within each sub-experiment, treated and control products would have followed parallel paths absent that wave | 4_stacked |  | 20260811T201214Z-b1495fb3 | 3c51a06-dirty | sample_slice.yaml | OFFICIAL | 2017-01..2020-02 |
| stacked_event_study_log_landed_unit_value_not_yet_treated | log_landed_unit_value | OLS-HDFE | event-time indicators interacted with stack_treated; reference period -3 | flow x stack + calendar month x stack | hs6 | stacked sub-experiments, one per wave, window [-12, 10]; controls = not_yet_treated | unweighted | hs10 x country x month | dynamic effect of a wave relative to event month -3, pooled across waves with wave-specific calendar-time effects | within each sub-experiment, treated and control products would have followed parallel paths absent that wave | 4_stacked |  | 20260811T201214Z-b1495fb3 | 3c51a06-dirty | sample_slice.yaml | OFFICIAL | 2017-01..2020-02 |
| stacked_event_study_log_customs_unit_value_not_yet_treated | log_customs_unit_value | OLS-HDFE | event-time indicators interacted with stack_treated; reference period -3 | flow x stack + calendar month x stack | hs6 | stacked sub-experiments, one per wave, window [-12, 10]; controls = not_yet_treated | unweighted | hs10 x country x month | dynamic effect of a wave relative to event month -3, pooled across waves with wave-specific calendar-time effects | within each sub-experiment, treated and control products would have followed parallel paths absent that wave | 4_stacked |  | 20260811T201214Z-b1495fb3 | 3c51a06-dirty | sample_slice.yaml | OFFICIAL | 2017-01..2020-02 |
| stacked_event_study_log_quantity_not_yet_treated | log_quantity | OLS-HDFE | event-time indicators interacted with stack_treated; reference period -3 | flow x stack + calendar month x stack | hs6 | stacked sub-experiments, one per wave, window [-12, 10]; controls = not_yet_treated | unweighted | hs10 x country x month | dynamic effect of a wave relative to event month -3, pooled across waves with wave-specific calendar-time effects | within each sub-experiment, treated and control products would have followed parallel paths absent that wave | 4_stacked |  | 20260811T201214Z-b1495fb3 | 3c51a06-dirty | sample_slice.yaml | OFFICIAL | 2017-01..2020-02 |
| stacked_event_study_log_landed_unit_value_never_treated_products_treated_country_only | log_landed_unit_value | OLS-HDFE | event-time indicators interacted with stack_treated; reference period -3 | flow x stack + calendar month x stack | hs6 | stacked sub-experiments, one per wave, window [-12, 10]; controls = never_treated_products_treated_country_only | unweighted | hs10 x country x month | dynamic effect of a wave relative to event month -3, pooled across waves with wave-specific calendar-time effects | within each sub-experiment, treated and control products would have followed parallel paths absent that wave | 4_stacked |  | 20260811T201214Z-b1495fb3 | 3c51a06-dirty | sample_slice.yaml | OFFICIAL | 2017-01..2020-02 |
| stacked_event_study_log_customs_unit_value_never_treated_products_treated_country_only | log_customs_unit_value | OLS-HDFE | event-time indicators interacted with stack_treated; reference period -3 | flow x stack + calendar month x stack | hs6 | stacked sub-experiments, one per wave, window [-12, 10]; controls = never_treated_products_treated_country_only | unweighted | hs10 x country x month | dynamic effect of a wave relative to event month -3, pooled across waves with wave-specific calendar-time effects | within each sub-experiment, treated and control products would have followed parallel paths absent that wave | 4_stacked |  | 20260811T201214Z-b1495fb3 | 3c51a06-dirty | sample_slice.yaml | OFFICIAL | 2017-01..2020-02 |
| stacked_event_study_log_quantity_never_treated_products_treated_country_only | log_quantity | OLS-HDFE | event-time indicators interacted with stack_treated; reference period -3 | flow x stack + calendar month x stack | hs6 | stacked sub-experiments, one per wave, window [-12, 10]; controls = never_treated_products_treated_country_only | unweighted | hs10 x country x month | dynamic effect of a wave relative to event month -3, pooled across waves with wave-specific calendar-time effects | within each sub-experiment, treated and control products would have followed parallel paths absent that wave | 4_stacked |  | 20260811T201214Z-b1495fb3 | 3c51a06-dirty | sample_slice.yaml | OFFICIAL | 2017-01..2020-02 |
| ppml_customs_value_on_log1p_additional_tariff | customs_value | PPML-HDFE | log1p_additional_tariff | flow_id + month_key | hs6 | full sample | PPML (implicit) | hs10 x country x month | semi-elasticity of the trade flow in levels with respect to the tariff term | correct conditional mean given the absorbed effects; tariff variation is conditionally exogenous | 5_ppml |  | 20260811T201214Z-b1495fb3 | 3c51a06-dirty | sample_slice.yaml | OFFICIAL | 2017-01..2020-02 |
| ppml_quantity_on_log1p_additional_tariff | quantity | PPML-HDFE | log1p_additional_tariff | flow_id + month_key | hs6 | full sample | PPML (implicit) | hs10 x country x month | semi-elasticity of the trade flow in levels with respect to the tariff term | correct conditional mean given the absorbed effects; tariff variation is conditionally exogenous | 5_ppml |  | 20260811T201214Z-b1495fb3 | 3c51a06-dirty | sample_slice.yaml | OFFICIAL | 2017-01..2020-02 |
| ppml_customs_value_on_log1p_total_tariff | customs_value | PPML-HDFE | log1p_total_tariff | flow_id + month_key | hs6 | subsample with an ad valorem MFN baseline | PPML (implicit) | hs10 x country x month | semi-elasticity of the trade flow in levels with respect to the tariff term | correct conditional mean given the absorbed effects; tariff variation is conditionally exogenous | 5_ppml |  | 20260811T201214Z-b1495fb3 | 3c51a06-dirty | sample_slice.yaml | OFFICIAL | 2017-01..2020-02 |
| ppml_quantity_on_log1p_total_tariff | quantity | PPML-HDFE | log1p_total_tariff | flow_id + month_key | hs6 | subsample with an ad valorem MFN baseline | PPML (implicit) | hs10 x country x month | semi-elasticity of the trade flow in levels with respect to the tariff term | correct conditional mean given the absorbed effects; tariff variation is conditionally exogenous | 5_ppml |  | 20260811T201214Z-b1495fb3 | 3c51a06-dirty | sample_slice.yaml | OFFICIAL | 2017-01..2020-02 |


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
