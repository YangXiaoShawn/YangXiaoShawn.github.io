# Ten-Minute Presentation Outline

## 0:00–1:00 — The research trap

Today's revised macro history was not the history available to yesterday's forecaster. Show the central question and the synthetic-data warning.

## 1:00–2:30 — Information-set data model

Explain observation date, release availability, vintage interval, and forecast origin. Demonstrate one observation changing across vintages.

## 2:30–4:00 — No-future-information invariant

Walk through snapshot selection, post-selection transforms, mixed-frequency ragged edges, and lineage validation.

## 4:00–5:30 — Fair leakage comparison

Contrast vintage-aware features with latest values on the same historical eligibility mask. Explain why admitting future periods answers a different question.

## 5:30–7:00 — Model ladder and evaluation

Show historical mean, no-change, AR, bridge, Elastic Net, and gradient boosting on identical expanding folds. Emphasize fold-local preprocessing and prior-residual intervals.

## 7:00–8:15 — Release update and attribution

Show the pre/post nowcast, exact frozen-linear contribution identity, uncertainty, and non-causal interpretation.

## 8:15–9:15 — Production workflow

Trace configuration → official/fixture adapters → Parquet/DuckDB → audited matrices →
forecasts → reports/dashboard. Mention immutable raw hashes, offline tests, and run hashes.

## 9:15–10:00 — What is supported and next

Separate the fixture-only evidence from the 626,304-row official CES/CPI/GDP/CPS/DOL/G.17/Treasury/MARTS/NRC
pilot. Report zero strict timing violations and the observed sensitivity to revisions, but
do not claim universal model superiority. Next: written permission and coverage validation
for historical Michigan sentiment, a clear no-correction-vintage limitation for Treasury
rates, a prespecified use of the 96-quarter NIPA level-derived validation,
horizons beyond the delivered target-release/one-period-ahead pair, and larger-sample
regime/stability analysis while preserving the delivered untouched final block.
