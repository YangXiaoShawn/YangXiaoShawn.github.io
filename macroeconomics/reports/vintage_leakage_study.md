# Vintage Leakage Study

> **Synthetic fixture demonstration.** All dates, releases, observations, forecasts, metrics, and model rankings below validate software behavior only. They are not empirical findings about the U.S. economy.

## Question

How much does a backtest change when later-revised values replace the vintages actually available at each historical origin, holding the eligible series/observation mask fixed?

## Design

`vintage_aware` features use the most recent eligible vintage at each origin. `latest_values_same_eligibility_mask` first determines those same eligible cells and then substitutes their fixed-evaluation-vintage values. Targets and feature modes remain explicitly labeled. This is narrower and more interpretable than a naive revised-data matrix that also admits observations published after the forecast origin.

The multi-target workflow also materializes that wider matrix under the explicit name
`naive_latest_revised`. Its audit records cells first available after the historical
origin, so the result measures intentional release-timing leakage and is never described as
a valid real-time backtest. The fixed-mask experiment remains the primary value-revision
comparison.

## Fixture result

| model_id | vintage_rmse | revised_rmse | rmse_difference | vintage_mae | revised_mae |
| --- | --- | --- | --- | --- | --- |
| ar1 | 27.190 | 13.381 | -13.809 | 21.258 | 11.679 |
| bridge_linear | 29.297 | 13.676 | -15.621 | 24.061 | 11.169 |
| elastic_net | 29.062 | 13.478 | -15.584 | 23.808 | 10.974 |
| hist_gradient_boosting | 31.145 | 14.785 | -16.360 | 25.679 | 11.767 |
| historical_mean | 28.868 | 13.223 | -15.644 | 23.258 | 11.455 |
| no_change | 47.409 | 17.302 | -30.107 | 38.801 | 14.030 |

The sign and size of these synthetic differences are properties of the deterministic fixture. They demonstrate that the comparison is measurable and reproducible; they do not estimate real-world leakage or prove that one model class is superior.

## Revision distribution

| series_id | revision_count | mean_revision | mean_abs_revision | max_abs_revision |
| --- | --- | --- | --- | --- |
| AWHMAN | 99 | -0.002 | 0.020 | 0.058 |
| CCSA | 424 | 567.091 | 5934.469 | 21748.070 |
| DGS10 | 0 | 0.000 | 0.000 | 0.000 |
| HOUST | 99 | -0.310 | 17.242 | 88.384 |
| ICSA | 425 | 8.650 | 1228.198 | 5503.960 |
| INDPRO | 99 | 0.003 | 0.127 | 0.711 |
| PAYEMS | 99 | 0.381 | 16.111 | 54.791 |
| RSAFS | 99 | 82.218 | 468.286 | 1418.349 |
| UMCSENT | 97 | -0.047 | 0.693 | 1.906 |
| UNRATE | 99 | -0.001 | 0.032 | 0.098 |

## Forecast error and target revision

For each vintage-aware forecast, the same prediction is scored once against the synthetic first release and once against the fixed-evaluation-vintage target. The difference therefore isolates target revision from model re-estimation or feature revision.

| model_id | n_forecasts | mae_first_release | mae_latest_revised | mean_target_revision | mean_abs_target_revision | mean_change_in_absolute_error_due_to_target_revision |
| --- | --- | --- | --- | --- | --- | --- |
| ar1 | 47 | 21.258 | 13.236 | 2.156 | 19.256 | -8.022 |
| bridge_linear | 47 | 24.061 | 14.534 | 2.156 | 19.256 | -9.527 |
| elastic_net | 47 | 23.808 | 14.297 | 2.156 | 19.256 | -9.511 |
| hist_gradient_boosting | 47 | 25.679 | 16.452 | 2.156 | 19.256 | -9.227 |
| historical_mean | 47 | 23.258 | 11.588 | 2.156 | 19.256 | -11.670 |
| no_change | 47 | 38.801 | 28.216 | 2.156 | 19.256 | -10.584 |

## Official archive extension

The separate official pilot repeats the comparison on audited BLS CES/core-CPI and BEA
published-GDP archives, augmented with eight genuine CES sector-employment publication-
vintage matrices, CPS unemployment-rate release snapshots, DOL claims releases, and Fed
G.17 industrial-production snapshots plus Census MARTS retail-sales and Census NRC
housing-start releases, together with 6,154 official Treasury 10-year daily par-yield
observations. It uses 544 mixed-precision forecast origins and 23,955 audited feature
cells. Strict as-of and fixed-mask modes have zero future-eligibility violations; the
deliberately naive mode admits 863 cells first available after their origin. Of those, 542
come from treating same-day Treasury observations as though they were known before the
project's conservative end-of-day availability timestamp.

Employment Situation direct-TXT and HTML evidence moves 272 PAYEMS origins and the separate CPI clock inventory
moves all 173 acquired CPI origins from the prior date-only rule to one second before the
verified embargo clock. The BEA inventory does the same for all 98 GDP origins. A persisted
complete counterfactual rebuild finds zero changed
feature values/selections and zero changed target values for the current panel; this is
evidence about this panel, not a general claim that intraday timing is immaterial.

| target | best strict-vintage model | strict RMSE | best fixed-mask model | fixed-mask RMSE | models changing RMSE rank | mean absolute target revision |
| --- | --- | ---: | --- | ---: | ---: | ---: |
| Core CPI m/m, percentage points | AR(1) | 0.1476 | AR(1) | 0.1311 | 3 of 6 | 0.0271 |
| Real GDP q/q SAAR, percentage points | Historical mean | 5.7614 | Historical mean | 5.6649 | 4 of 6 | 1.0885 |
| Payroll change, thousands | Historical mean | 1488.6086 | Historical mean | 1491.8688 | 0 of 6 | 78.8873 |

These are descriptive results from the declared pilot, not evidence of universal model
superiority. Fixed-mask RMSE changes both revised feature values and the scoring target.
The separate `target_revision_summary.parquet` holds each vintage-aware forecast fixed and
changes only its target; `model_stability.parquet` measures prediction/rank sensitivity.
The source-revision table's first value means first present in the acquired archive, which
is not necessarily the original release for reference periods predating archive coverage.
Archived NIPA raw GDP levels are not included in that table because benchmark-year and
scale changes make cross-snapshot level differences invalid. A separate 96-quarter artifact
validates same-snapshot level-derived q/q SAAR against published growth; it does not replace
the published-growth forecasts summarized above.

## Remaining empirical follow-up

Obtain express written permission for University of Michigan sentiment history and audit its
coverage; verify more intraday timing where possible; then extend the delivered two-horizon,
prespecified-tuning design before drawing broader conclusions.
The NBER chronology is now available as ex-post evaluation metadata, but current recession
subsamples remain too small for robust regime conclusions.
The continuous-rate predictor now uses the original-provider Treasury daily par-yield archive
from 2002 onward with conservative New York end-of-day availability. It is a point-in-time
daily series, not a publication-vintage archive: exact publication clocks and later correction
history are not claimed. The H.15 dated-release archive still ends in 2016, and current Fed
DDP history is not relabeled as post-2016 release vintages.
