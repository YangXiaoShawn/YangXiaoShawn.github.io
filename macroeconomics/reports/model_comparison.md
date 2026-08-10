# Model Comparison

> **Synthetic fixture demonstration.** All dates, releases, observations, forecasts, metrics, and model rankings below validate software behavior only. They are not empirical findings about the U.S. economy.

## Separate official-archive pilot

The generated official report at
`data/generated/official_pilot/official_pilot_report.md` is a different evidence tier. It
uses 19 official series, including eight sectoral CES vintage matrices, CPS
unemployment-rate release snapshots, DOL claims releases, and Fed G.17 industrial-
production, Census MARTS retail-sales, and Census NRC housing-start snapshots, and produces 213
payroll, 136 core-CPI, and 78 GDP out-of-sample forecasts per model and information mode.
The best strict-vintage RMSE rows in that fixed design are:

| target | model | n | RMSE | MAE | interval coverage |
| --- | --- | ---: | ---: | ---: | ---: |
| Core CPI m/m | AR(1) | 136 | 0.1476 | 0.1041 | 0.6371 |
| Real GDP q/q SAAR | Historical mean | 78 | 5.7614 | 2.2968 | 0.7727 |
| Payroll change | Historical mean | 213 | 1488.6086 | 318.0544 | 0.7662 |

COVID-era extremes materially affect payroll and GDP squared-error metrics. The pilot runs
45 DM diagnostics; unadjusted p-values are not promoted to multiple-testing-adjusted model
claims. Core-CPI and GDP rankings change under the fixed-mask counterfactual, while payroll
rank order does not, demonstrating why a single revised-data leaderboard is insufficient.

The tables below remain the original synthetic payroll acceptance evidence.

## Expanding-window results

| model_id | data_mode | feature_mode | target_mode | horizon | fixture_label | n_forecasts | rmse | mae | bias | directional_accuracy | n_intervals | interval_coverage | mean_interval_width | directional_accuracy_meaningful | sample_start | sample_end | rmse_rank |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| historical_mean | latest_values_same_eligibility_mask | latest_values_same_eligibility_mask | latest_revised | 0 | synthetic_fixture | 47 | 13.223 | 11.455 | -0.501 | not available | 47 | 0.787 | 36.727 | False | 2021-02-01 | 2024-12-01 | 1 |
| ar1 | latest_values_same_eligibility_mask | latest_values_same_eligibility_mask | latest_revised | 0 | synthetic_fixture | 47 | 13.381 | 11.679 | -0.391 | not available | 47 | 0.766 | 36.842 | False | 2021-02-01 | 2024-12-01 | 2 |
| elastic_net | latest_values_same_eligibility_mask | latest_values_same_eligibility_mask | latest_revised | 0 | synthetic_fixture | 47 | 13.478 | 10.974 | 1.072 | not available | 47 | 0.851 | 42.504 | False | 2021-02-01 | 2024-12-01 | 3 |
| bridge_linear | latest_values_same_eligibility_mask | latest_values_same_eligibility_mask | latest_revised | 0 | synthetic_fixture | 47 | 13.676 | 11.169 | 1.326 | not available | 47 | 0.872 | 42.471 | False | 2021-02-01 | 2024-12-01 | 4 |
| hist_gradient_boosting | latest_values_same_eligibility_mask | latest_values_same_eligibility_mask | latest_revised | 0 | synthetic_fixture | 47 | 14.785 | 11.767 | 0.315 | not available | 47 | 0.809 | 41.817 | False | 2021-02-01 | 2024-12-01 | 5 |
| no_change | latest_values_same_eligibility_mask | latest_values_same_eligibility_mask | latest_revised | 0 | synthetic_fixture | 47 | 17.302 | 14.030 | 0.108 | not available | 47 | 0.915 | 59.592 | False | 2021-02-01 | 2024-12-01 | 6 |
| ar1 | vintage_aware | as_of | first_release | 0 | synthetic_fixture | 47 | 27.190 | 21.258 | 0.547 | not available | 47 | 0.723 | 64.976 | False | 2021-02-01 | 2024-12-01 | 1 |
| historical_mean | vintage_aware | as_of | first_release | 0 | synthetic_fixture | 47 | 28.868 | 23.258 | 0.984 | not available | 47 | 0.723 | 67.009 | False | 2021-02-01 | 2024-12-01 | 2 |
| elastic_net | vintage_aware | as_of | first_release | 0 | synthetic_fixture | 47 | 29.062 | 23.808 | -4.692 | not available | 47 | 0.787 | 74.426 | False | 2021-02-01 | 2024-12-01 | 3 |
| bridge_linear | vintage_aware | as_of | first_release | 0 | synthetic_fixture | 47 | 29.297 | 24.061 | -4.874 | not available | 47 | 0.787 | 75.362 | False | 2021-02-01 | 2024-12-01 | 4 |
| hist_gradient_boosting | vintage_aware | as_of | first_release | 0 | synthetic_fixture | 47 | 31.145 | 25.679 | 4.224 | not available | 47 | 0.766 | 78.223 | False | 2021-02-01 | 2024-12-01 | 5 |
| no_change | vintage_aware | as_of | first_release | 0 | synthetic_fixture | 47 | 47.409 | 38.801 | 0.917 | not available | 47 | 0.681 | 117.496 | False | 2021-02-01 | 2024-12-01 | 6 |

## Diebold–Mariano-style comparisons

| data_mode | baseline_model | comparison_model | statistic | p_value | mean_loss_differential | n_obs | valid | reason | fixture_label |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| latest_values_same_eligibility_mask | historical_mean | ar1 | -0.940 | 0.352 | -4.181 | 47 | True | not available | synthetic_fixture |
| latest_values_same_eligibility_mask | historical_mean | bridge_linear | -0.448 | 0.656 | -12.176 | 47 | True | not available | synthetic_fixture |
| latest_values_same_eligibility_mask | historical_mean | elastic_net | -0.266 | 0.792 | -6.799 | 47 | True | not available | synthetic_fixture |
| latest_values_same_eligibility_mask | historical_mean | hist_gradient_boosting | -1.122 | 0.268 | -43.740 | 47 | True | not available | synthetic_fixture |
| latest_values_same_eligibility_mask | historical_mean | no_change | -2.285 | 0.027 | -124.494 | 47 | True | not available | synthetic_fixture |
| vintage_aware | historical_mean | ar1 | 1.650 | 0.106 | 94.041 | 47 | True | not available | synthetic_fixture |
| vintage_aware | historical_mean | bridge_linear | -0.233 | 0.817 | -24.992 | 47 | True | not available | synthetic_fixture |
| vintage_aware | historical_mean | elastic_net | -0.109 | 0.914 | -11.281 | 47 | True | not available | synthetic_fixture |
| vintage_aware | historical_mean | hist_gradient_boosting | -0.935 | 0.355 | -136.665 | 47 | True | not available | synthetic_fixture |
| vintage_aware | historical_mean | no_change | -4.976 | 0.000 | -1414.298 | 47 | True | not available | synthetic_fixture |

## Performance by configured regime and horizon

The fixture regimes are deterministic calendar partitions for exercising grouped evaluation; they are not identified economic regimes.

| data_mode | model_id | horizon | regime | n_forecasts | rmse | mae | bias | directional_accuracy | n_intervals | interval_coverage | mean_interval_width | directional_accuracy_meaningful | sample_start | sample_end | fixture_label |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| latest_values_same_eligibility_mask | ar1 | 0 | synthetic_regime_a | 18 | 14.455 | 12.603 | 8.889 | not available | 18 | 0.667 | 38.448 | False | 2022-01-01 | 2023-06-01 | synthetic_fixture |
| latest_values_same_eligibility_mask | ar1 | 0 | synthetic_regime_b | 29 | 12.668 | 11.105 | -6.151 | not available | 29 | 0.828 | 35.845 | False | 2021-02-01 | 2024-12-01 | synthetic_fixture |
| latest_values_same_eligibility_mask | bridge_linear | 0 | synthetic_regime_a | 18 | 13.264 | 11.011 | 6.924 | not available | 18 | 0.944 | 46.830 | False | 2022-01-01 | 2023-06-01 | synthetic_fixture |
| latest_values_same_eligibility_mask | bridge_linear | 0 | synthetic_regime_b | 29 | 13.926 | 11.268 | -2.149 | not available | 29 | 0.828 | 39.765 | False | 2021-02-01 | 2024-12-01 | synthetic_fixture |
| latest_values_same_eligibility_mask | elastic_net | 0 | synthetic_regime_a | 18 | 13.077 | 10.836 | 6.697 | not available | 18 | 0.889 | 46.875 | False | 2022-01-01 | 2023-06-01 | synthetic_fixture |
| latest_values_same_eligibility_mask | elastic_net | 0 | synthetic_regime_b | 29 | 13.721 | 11.060 | -2.419 | not available | 29 | 0.828 | 39.791 | False | 2021-02-01 | 2024-12-01 | synthetic_fixture |
| latest_values_same_eligibility_mask | hist_gradient_boosting | 0 | synthetic_regime_a | 18 | 15.129 | 12.659 | 5.676 | not available | 18 | 0.778 | 43.645 | False | 2022-01-01 | 2023-06-01 | synthetic_fixture |
| latest_values_same_eligibility_mask | hist_gradient_boosting | 0 | synthetic_regime_b | 29 | 14.568 | 11.214 | -3.012 | not available | 29 | 0.828 | 40.682 | False | 2021-02-01 | 2024-12-01 | synthetic_fixture |
| latest_values_same_eligibility_mask | historical_mean | 0 | synthetic_regime_a | 18 | 14.109 | 12.214 | 8.047 | not available | 18 | 0.722 | 38.132 | False | 2022-01-01 | 2023-06-01 | synthetic_fixture |
| latest_values_same_eligibility_mask | historical_mean | 0 | synthetic_regime_b | 29 | 12.642 | 10.984 | -5.807 | not available | 29 | 0.828 | 35.854 | False | 2021-02-01 | 2024-12-01 | synthetic_fixture |
| latest_values_same_eligibility_mask | no_change | 0 | synthetic_regime_a | 18 | 18.991 | 15.014 | -1.475 | not available | 18 | 0.833 | 59.325 | False | 2022-01-01 | 2023-06-01 | synthetic_fixture |
| latest_values_same_eligibility_mask | no_change | 0 | synthetic_regime_b | 29 | 16.165 | 13.419 | 1.090 | not available | 29 | 0.966 | 59.758 | False | 2021-02-01 | 2024-12-01 | synthetic_fixture |
| vintage_aware | ar1 | 0 | synthetic_regime_a | 18 | 29.611 | 23.627 | 9.549 | not available | 18 | 0.722 | 63.564 | False | 2022-01-01 | 2023-06-01 | synthetic_fixture |
| vintage_aware | ar1 | 0 | synthetic_regime_b | 29 | 25.573 | 19.787 | -5.041 | not available | 29 | 0.724 | 65.852 | False | 2021-02-01 | 2024-12-01 | synthetic_fixture |
| vintage_aware | bridge_linear | 0 | synthetic_regime_a | 18 | 28.450 | 24.665 | -0.649 | not available | 18 | 0.722 | 76.605 | False | 2022-01-01 | 2023-06-01 | synthetic_fixture |
| vintage_aware | bridge_linear | 0 | synthetic_regime_b | 29 | 29.811 | 23.686 | -7.497 | not available | 29 | 0.828 | 74.590 | False | 2021-02-01 | 2024-12-01 | synthetic_fixture |
| vintage_aware | elastic_net | 0 | synthetic_regime_a | 18 | 28.314 | 24.391 | -0.391 | not available | 18 | 0.722 | 75.781 | False | 2022-01-01 | 2023-06-01 | synthetic_fixture |
| vintage_aware | elastic_net | 0 | synthetic_regime_b | 29 | 29.517 | 23.446 | -7.362 | not available | 29 | 0.828 | 73.586 | False | 2021-02-01 | 2024-12-01 | synthetic_fixture |
| vintage_aware | hist_gradient_boosting | 0 | synthetic_regime_a | 18 | 27.455 | 23.455 | 4.913 | not available | 18 | 0.833 | 81.046 | False | 2022-01-01 | 2023-06-01 | synthetic_fixture |
| vintage_aware | hist_gradient_boosting | 0 | synthetic_regime_b | 29 | 33.230 | 27.060 | 3.796 | not available | 29 | 0.724 | 76.471 | False | 2021-02-01 | 2024-12-01 | synthetic_fixture |
| vintage_aware | historical_mean | 0 | synthetic_regime_a | 18 | 33.758 | 28.638 | 7.084 | not available | 18 | 0.611 | 65.077 | False | 2022-01-01 | 2023-06-01 | synthetic_fixture |
| vintage_aware | historical_mean | 0 | synthetic_regime_b | 29 | 25.362 | 19.918 | -2.802 | not available | 29 | 0.793 | 68.208 | False | 2021-02-01 | 2024-12-01 | synthetic_fixture |
| vintage_aware | no_change | 0 | synthetic_regime_a | 18 | 57.980 | 52.554 | -2.543 | not available | 18 | 0.500 | 114.832 | False | 2022-01-01 | 2023-06-01 | synthetic_fixture |
| vintage_aware | no_change | 0 | synthetic_regime_b | 29 | 39.448 | 30.264 | 3.064 | not available | 29 | 0.793 | 119.149 | False | 2021-02-01 | 2024-12-01 | synthetic_fixture |

## Stability across vintage modes

| model_id | n_aligned | prediction_correlation | mean_abs_prediction_difference | vintage_rmse_rank | revised_rmse_rank | rank_change | fixture_label |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ar1 | 47 | 0.461 | 6.694 | 1 | 2 | 1 | synthetic_fixture |
| bridge_linear | 47 | 0.513 | 10.547 | 4 | 4 | 0 | synthetic_fixture |
| elastic_net | 47 | 0.462 | 10.232 | 3 | 3 | 0 | synthetic_fixture |
| hist_gradient_boosting | 47 | 0.221 | 14.628 | 5 | 5 | 0 | synthetic_fixture |
| historical_mean | 47 | 0.948 | 0.693 | 2 | 1 | -1 | synthetic_fixture |
| no_change | 47 | 0.645 | 18.722 | 6 | 6 | 0 | synthetic_fixture |

Simple baselines and advanced estimators use the same origins and eligibility masks. The sample keeps hyperparameters fixed and fits imputers/scalers only inside each training fold. Any comparison with an insufficient loss history is reported as such rather than assigned a significance claim.

No model-ranking claim should be carried outside this synthetic fixture.
