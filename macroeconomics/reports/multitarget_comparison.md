# Synthetic Multi-Target Coverage

> **Synthetic fixture demonstration — no empirical findings.** The values, releases, revisions, forecasts, and diagnostics described here test the research software. They are not evidence about the U.S. economy or model superiority.

## Reproduced scope

`make reproduce-multitarget` completed the configuration in `config/targets.toml` with:

| Target | Formula | Native frequency | Evaluation rows per model/mode |
| --- | --- | --- | ---: |
| `payems_change_mom_thousands` | `PAYEMS[t] - PAYEMS[t-1]` | Monthly | 47 |
| `core_cpi_pct_change_mom` | `100 * (CPILFESL[t] / CPILFESL[t-1] - 1)` | Monthly, nonannualized | 47 |
| `real_gdp_pct_change_qoq_saar` | `100 * ((GDPC1[q] / GDPC1[q-1]) ** 4 - 1)` | Quarterly, SAAR | 16 |

Both adjacent target levels come from one selected snapshot. The run produced 5,558
canonical synthetic vintages across 12 series, 228 target-specific pre-release origins,
5,766 audited feature cells, 450 first/fixed-latest target rows, and 1,980 forecasts from
six models in three labeled information modes. Strict-mode timing violations were zero;
the deliberately invalid naive mode exposed 893 post-origin first-availability cells.

Monthly indicators aligned to a quarterly GDP target retain the quarter-ending cutoff, observed-month count, three-month coverage ratio, and staleness. A missing future month is not filled from a later release. Training feature rows remain at their own historical origins, and preprocessing is fitted inside each expanding fold.

## Interpretation boundary

- RMSE and MAE cannot be compared across these targets because units, transformations, frequencies, and sample sizes differ.
- The quarterly GDP evaluation contains 16 observations. Its Diebold–Mariano comparisons do not meet the predeclared 20-observation minimum and remain explicitly invalid.
- Differences between `vintage_aware/first_release` and `latest_values_same_eligibility_mask/latest_revised` demonstrate that the comparison path is active on the synthetic fixture; they do not estimate real revision leakage.
- `naive_latest_revised` intentionally adds release-timing leakage. Its metrics and rank
  changes are invalid-backtest diagnostics, not attainable forecasts.
- Cross-vintage model stability is recorded for every target/model pair. Each target also
  has one exact frozen-model synthetic release attribution and a generated policy brief.
- The full machine-generated diagnostic is written to `data/generated/multitarget/multitarget_report.md` and is intentionally ignored with the other reproducible artifacts.
- Genuine empirical results remain gated on authorized original-provider archives and verified historical release timing; see `docs/DATA_ACCESS.md`.
