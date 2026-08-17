# Data dictionary

Column names are load-bearing. `customs_unit_value` and
`landed_unit_value_duty_inclusive` answer different questions, and the naming is
what stops them being confused.

## Analytical panel — `data/analytical/trade_panel.parquet`

Grain: one row per **HS6 product × partner country × month**.

### Keys

| Column | Type | Meaning |
|---|---|---|
| `hs6` | str | 6-digit HS product code |
| `country_code` | str | Census partner country code (5700 = China, mainland only) |
| `country_name` | str | Partner name as reported |
| `month_date` | date | First day of the month; the month is the observation |
| `month_index` | int | `year*12 + month`, for lags and windows |
| `month_key` | str | `YYYY-MM`, used as the time fixed effect |
| `flow_id` | str | `hs6_country`, used as the flow fixed effect |
| `hs2_chapter` | str | First two digits of `hs6` |

### Value concepts — these are **not** interchangeable

| Column | Type | Meaning |
|---|---|---|
| `customs_value` | f64 | Value at the foreign port of export. **Excludes** freight and insurance. Census `CON_VAL_MO`. |
| `general_imports_value` | f64 | All merchandise arriving, including into bonded warehouse/FTZ. Census `GEN_VAL_MO`. |
| `dutiable_value` | f64 | Portion of customs value actually subject to duty. Census `DUT_VAL_MO`. |
| `calculated_duties` | f64 | Duty computed by Customs. Census `CAL_DUT_MO`. |
| `import_charges` | f64 | Freight, insurance and other charges to the U.S. border. Census `CON_CHA_MO`. |
| `cif_value` | f64 | `customs_value + import_charges`. |

### Quantities

| Column | Type | Meaning |
|---|---|---|
| `quantity` | f64 | Primary quantity, in `quantity_unit`. |
| `quantity_unit` | str | Unit of measure. **Can change over time within a flow**; when it does, unit values are not comparable across the break, and `UNIT_CHANGE` flags it. |
| `quantity_2`, `quantity_2_unit` | f64/str | Secondary quantity where reported. |

### Unit values — read the suffix

| Column | Tariff treatment | Freight | Answers |
|---|---|---|---|
| `customs_unit_value` | **excludes** duty | excludes | Did the exporter cut its border price? |
| `landed_unit_value_duty_inclusive` | **includes** duty | excludes | What does the importer pay at the border? |
| `landed_unit_value_full` | **includes** duty | **includes** | Full delivered cost to the border. |

> **A unit value is not a price.** It is value divided by quantity over a
> heterogeneous bundle of transactions within an HS line, country and month. It
> moves with product mix, quality, contract timing and unit-of-measure changes
> as well as with prices. Null when quantity is zero or missing.

Logs: `log_customs_unit_value`, `log_landed_unit_value`, `log_quantity`,
`log_customs_value`.

### Realised duty rates (from the data, not the policy engine)

| Column | Meaning |
|---|---|
| `realised_duty_rate_on_dutiable` | `calculated_duties / dutiable_value` |
| `realised_duty_rate_on_customs` | `calculated_duties / customs_value` |
| `freight_share_of_customs_value` | `import_charges / customs_value` |

Comparing `realised_duty_rate_on_dutiable` against
`total_modeled_tariff_rate` is the `DUTY_VS_ENGINE` quality check: it validates
the policy engine against what Customs actually collected.

### Tariff treatment (from the policy engine)

| Column | Type | Meaning |
|---|---|---|
| `baseline_mfn_rate` | f64? | Column-1 general (MFN) ad valorem rate. **Null** when the heading contains a compound or specific duty line — never zero. |
| `additional_tariff_rate` | f64 | Day-weighted average additional Section 301 duty over the month. |
| `additional_tariff_rate_month_start` | f64 | Statutory rate on the first day. |
| `additional_tariff_rate_month_end` | f64 | Statutory rate on the last day. |
| `tariff_regime_changed_within_month` | bool | An effective or expiry date falls inside this month. |
| `total_modeled_tariff_rate` | f64? | `baseline + additional`. **Null** when the baseline is null. |
| `baseline_mfn_available` | bool | Whether a single ad valorem baseline exists. |
| `log1p_total_tariff` | f64? | `log(1 + total)`. Null-propagating by design. |
| `log1p_additional_tariff` | f64 | `log(1 + additional)`. Primary treatment variable. |
| `tariff_coverage_share` | f64 | Fraction of the queried line covered. 1.0 for a fully covered HS8; between 0 and 1 for a partly covered HS6. |
| `tariff_status` | str | See below. |
| `tariff_usable_for_treatment` | bool | Whether the rate may be used as a scalar treatment without judgement. |
| `tariff_confidence` | str | `OFFICIAL_PARSED`, `OFFICIAL_MANUAL`, `DERIVED`, `UNVERIFIED`. |
| `active_actions` | str | Pipe-separated action ids. |
| `exclusion_active` | bool | An exclusion suppresses the duty. |
| `tariff_source_records` | str | Record ids behind the assessment. |
| `treated` | bool | Positive additional duty actually collected. |

#### `tariff_status` values

| Value | Meaning | Usable as scalar treatment |
|---|---|---|
| `OK` | Single governing duty record | yes |
| `NO_MATCH` | No record covers this line/date; additional duty is zero | yes |
| `EXCLUDED` | An active exclusion suppresses the duty | yes |
| `PARTIAL_LINE` | Statutory line covered only in part | **no** |
| `PARTIAL_HS6_COVERAGE` | Some but not all HS8 children covered | **no** |
| `CONFLICT` | Two actions impose different rates; engine refuses to choose | **no** |
| `AMBIGUOUS_CODE` | Product code unresolvable | **no** |

### Event time and treatment groups

| Column | Meaning |
|---|---|
| `event_time` | Months relative to the product's first treatment. Defined on the **product**, so control-country flows of a treated product have an event time — otherwise there would be no within-product comparison group. |
| `first_treated_month_index` | Month index of first treatment. |
| `ever_treated_product` | Product is treated at some point. |
| `is_treated_country` | Row's partner is the targeted country. |

### Sourcing and concentration

| Column | Meaning |
|---|---|
| `product_month_total_value` | Total customs value across sampled partners. |
| `supplier_value_share` | This partner's share. Sums to 1 within product-month. |
| `treated_country_share` | Treated country's share. |
| `alternative_source_share` | `1 − treated_country_share`. |
| `supplier_count_in_sample` | Partners with positive value. |
| `supplier_hhi_in_sample` | Herfindahl over shares. **Within-sample**, not global. |
| `pretreatment_treated_country_share` | Dependence measured on a fixed pre-period window so it cannot be contaminated by the reallocation it explains. |

### Extensive margin

| Column | Meaning |
|---|---|
| `flow_active` | Positive customs value this month. |
| `flow_entry` / `flow_exit` | Flow became / ceased active relative to the previous month. |

> Absence of a record and a true zero are **not distinguishable** in aggregated
> trade data. `PANEL_GAPS` reports how often this arises.

---

## Tariff schedule — `data/normalized/tariff_schedule.parquet`

One row per (action, product line, effective date, record type).

| Column | Meaning |
|---|---|
| `record_id` | Deterministic id |
| `episode_id` / `action_id` | e.g. `US_SECTION301_CHINA` / `SEC301_LIST3` |
| `record_type` | `ADDITIONAL_DUTY`, `RATE_CHANGE`, `EXCLUSION`, `REINSTATEMENT` |
| `product_code` / `product_code_level` | Digits only; 6, 8 or 10 |
| `product_code_vintage` | e.g. `HTS2018` |
| `partner_country_code` | Targeted partner |
| `announcement_date` | When it became public. **Not** the same fact as below. |
| `effective_date` | When duties were collected |
| `expiry_date` | End of the window, if any |
| `ad_valorem_rate` | Fraction (0.25, not 25) |
| `partial_line` / `partial_line_note` | Line covered only in part; carved-out statistical numbers |
| `confidence` | `OFFICIAL_PARSED` unless deduced |
| `source_*` | Document id, citation, title, URL, publication date, SHA-256, page locator |

---

## Industry exposure — `data/results/industry_tariff_exposure.parquet`

| Column | Meaning |
|---|---|
| `industry_code` / `industry_name` | BEA summary industry |
| `output_protection_exposure` | Tariff on the industry's own output commodity. **Helps.** |
| `imported_input_cost_exposure` | Direct-requirements-weighted tariff on inputs. **Hurts.** |
| `downstream_total_requirements_exposure` | Same through the full Leontief chain |
| `import_penetration` | Import share of the industry's commodity, where available |
| `exposure_class` | `PROTECTED_ONLY`, `INPUT_COST_EXPOSED_ONLY`, `BOTH_PROTECTED_AND_COST_EXPOSED`, `LITTLE_DIRECT_EXPOSURE` |
| `net_contrast_do_not_use_alone` | Protection − cost. Named to discourage the netting the project forbids. |
| `concordance_status` | `COARSE_APPROXIMATION` in the current build |

---

## Provenance columns on every result table

| Column | Meaning |
|---|---|
| `run_id` | Timestamp + config hash |
| `git_commit` | Short commit, `-dirty` if the tree was modified |
| `config` | Configuration file name |
| `data_provenance` | `OFFICIAL`, `MIXED`, `SYNTHETIC_PIPELINE_VALIDATION` |
| `data_period` | Sample window |
