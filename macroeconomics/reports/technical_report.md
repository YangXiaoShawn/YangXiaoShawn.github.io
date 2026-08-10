# Technical Report

> **Synthetic fixture demonstration.** All dates, releases, observations, forecasts, metrics, and model rankings below validate software behavior only. They are not empirical findings about the U.S. economy.

## System delivered

The repository implements a typed, configuration-driven pipeline for canonical vintages, explicit release events, arbitrary historical as-of reconstruction, audited mixed-frequency features, expanding-window forecasts, revision analysis, release-news attribution, Parquet/DuckDB persistence, automated reporting, and a local dashboard.

The sample target is `payems_change_mom_thousands` at horizon `0`. The fixed evaluation vintage is `2025-03-31` and the run identifier is `synthetic-abbcf2f59b-1fe94118b1`.

## Information-set discipline

For vintage-aware rows, a raw observation is eligible only when its availability timestamp is no later than the forecast origin. Selection occurs before transformations, aggregations, or missing-value handling. Each derived feature records the maximum availability timestamp of its inputs, and validation rejects any value later than its origin.

The counterfactual revised matrix preserves the historical eligibility mask and substitutes only the value at the fixed evaluation vintage. This isolates revisions from the separate error of adding observation periods that had not yet been released.

## Models and evaluation

Preprocessing is fitted within each expanding fold. Hyperparameters are fixed in the sample configuration; the final evaluation period is not used for tuning. Prediction intervals use prior out-of-sample residuals and remain missing until the minimum residual history exists.

| model_id | data_mode | n_forecasts | rmse | mae | bias | directional_accuracy | directional_accuracy_meaningful | interval_coverage |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| historical_mean | latest_values_same_eligibility_mask | 47 | 13.223 | 11.455 | -0.501 | not available | False | 0.787 |
| ar1 | latest_values_same_eligibility_mask | 47 | 13.381 | 11.679 | -0.391 | not available | False | 0.766 |
| elastic_net | latest_values_same_eligibility_mask | 47 | 13.478 | 10.974 | 1.072 | not available | False | 0.851 |
| bridge_linear | latest_values_same_eligibility_mask | 47 | 13.676 | 11.169 | 1.326 | not available | False | 0.872 |
| hist_gradient_boosting | latest_values_same_eligibility_mask | 47 | 14.785 | 11.767 | 0.315 | not available | False | 0.809 |
| no_change | latest_values_same_eligibility_mask | 47 | 17.302 | 14.030 | 0.108 | not available | False | 0.915 |
| ar1 | vintage_aware | 47 | 27.190 | 21.258 | 0.547 | not available | False | 0.723 |
| historical_mean | vintage_aware | 47 | 28.868 | 23.258 | 0.984 | not available | False | 0.723 |
| elastic_net | vintage_aware | 47 | 29.062 | 23.808 | -4.692 | not available | False | 0.787 |
| bridge_linear | vintage_aware | 47 | 29.297 | 24.061 | -4.874 | not available | False | 0.787 |
| hist_gradient_boosting | vintage_aware | 47 | 31.145 | 25.679 | 4.224 | not available | False | 0.766 |
| no_change | vintage_aware | 47 | 47.409 | 38.801 | 0.917 | not available | False | 0.681 |

Directional accuracy is omitted when the evaluation target never changes sign, because a constant positive-sign forecast would make that statistic uninformative.

## Reproducibility

The run manifest records the fixture label, configuration hash, input hash, series list, sample dates, target, horizon, seed, and package versions. `make reproduce-sample` recreates every generated analytical artifact from the deterministic source fixture.

## Scope

These results validate the research-engineering path. Genuine empirical conclusions require authorized data, verified historical timestamps, and a substantially larger real-time sample.

## Official archive implementation update

The production path now parses and freezes 626,304 original-provider archive rows in
Parquet and DuckDB: PAYEMS, core CPI, published real-GDP growth, 23,416 archived `GDPC1`
levels, and eight BLS CES sector-
employment series plus BLS CPS unemployment rate, two DOL claims series, and two Federal
Reserve G.17 industrial-production series, one U.S. Treasury 10-year CMT series, two Census
MARTS retail-sales series, and one Census NRC housing-start series. The official release
calendar contains 544 target events
plus 2,247 predictor/validation releases, using a mixed timing rule: 272 PAYEMS, 173 CPI, and 98 GDP
events use T−1 second from verified release headers, while only the conflicting
2012-12-07 PAYEMS event uses prior-New-York-day EOD.

The sector/CPS/DOL/G.17/Treasury/MARTS/NRC-expanded official run produces 23,955 long-form feature cells, 1,086 target
rows, 3,249 horizon-specific research rows, 15,264 expanding-window predictions, 108 metric
rows, 90 guarded DM comparisons, 72 model-stability rows, 216 ex-post NBER regime/horizon
rows, 60 tuning candidates, 12 frozen selections, 108 untouched final-evaluation metric
rows, 20 source-revision summaries, and 36 target-revision summaries.
Independent checks find no
duplicate vintage keys, future reference periods, invalid real-time ends, duplicate
predictions, or strict timing violations. The 544-row target-clock counterfactual finds zero
feature-value, feature-selection, or target-value changes after moving the 543 verified
origins. All 22 pilot report/data artifacts have verified
SHA-256 hashes in the run manifest.

The BEA NIPA level layer covers 96 of 98 expected initial releases from 2002Q3 through
2026Q2 and keeps the absent 2002Q1/Q2 snapshots missing. Its 96-row validation computes
q/q SAAR from adjacent levels in one snapshot: 94 round exactly to published growth and all
96 are within 0.06 percentage point. Because six chained-dollar reference years and two
scales appear across vintages, `GDPC1` raw levels are excluded from cross-vintage revision
summaries. The main official pilot remains the stable published-growth benchmark.

Advanced-model selection uses only prespecified `vintage_aware` tuning blocks and freezes
one setting per target/horizon across all modes. No final-evaluation row participates in
selection; DM diagnostics and stability ranks use the untouched final block.

The same run generates three official archive release updates and three one-page briefs.
Each attribution freezes an Elastic Net trained only on previously released targets; the
largest contribution-sum residual is `7.11e-15`. Target update windows use verified clocks
where present and retain explicit date-only labels elsewhere.

This advances the central research question from a target-only pilot to a genuine
establishment-plus-household-plus-claims labor-information pilot with genuine production,
daily Treasury-rate, retail-demand, and housing-supply indicators. It still lacks authorized
historical sentiment releases and therefore does not support claims about their incremental
value. Treasury rates are point-in-time observations with conservative EOD eligibility, not
successive correction vintages. The MARTS/NRC archives retain all documented gaps and
never fill them with later revised observations.
