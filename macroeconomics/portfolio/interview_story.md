# Interview Story

## Macroeconomic research

I built the project around a deceptively simple question: what did a forecaster actually know at the time? For monthly payroll change, nonannualized monthly core inflation, and quarterly real-GDP growth at SAAR, I represented every observation with its release availability and revision interval, then reconstructed each forecast origin rather than using today's cleaned history. Each target keeps a distinct formula, frequency, unit, and evaluation window.

## Econometric discipline

The central comparison holds the historical eligibility mask fixed and swaps only later
revisions. A third, explicitly invalid naive benchmark then shows the extra leakage from
cells that had not yet been published; the audit catches 893 such cells while strict modes
stay at zero. Fold-local preprocessing, expanding windows, first-release versus final
targets, guarded statistical tests, and explicit uncertainty keep the exercise honest.

## Research engineering

The workflow runs offline from deterministic fixtures through Parquet and DuckDB to models,
metrics, cross-vintage stability, exact release attribution, one policy brief per target,
reports, and a target-selectable Streamlit dashboard. Strict tests fail if any valid derived
feature carries post-origin eligibility. Monthly inputs to quarterly GDP retain
observed-month coverage and staleness. Guarded BLS/BEA current-data adapters are explicitly
latest-revised; archive ingestion and live FRED access remain gated.

## Honest outcome

I keep two evidence tiers separate. The synthetic tier validates software only. The scoped
official tier freezes 626,304 original-provider archive rows across 21 series—CES/core CPI,
published GDP, 96 NIPA real-GDP level snapshots, CPS unemployment, DOL claims, Fed G.17 industrial production, and Census
MARTS retail sales, NRC housing starts, and Treasury 10-year daily par yields—and
produces 15,264 expanding-window forecasts across two distinct horizons with zero strict
timing violations. It shows that
rankings and errors can move when revisions are handled correctly, but it does not prove a
universally superior model or support causal, investment, or policy conclusions. The next
research step is to obtain written permission for historical Michigan sentiment, document
the Treasury series' lack of a correction-vintage dimension, prespecify whether the
96-quarter level-derived GDP validation should become a separate model tier, then extend the delivered
two-horizon, holdout-evaluated design and enlarge genuine regime samples.
