# Causal Marketplace Lab

A reproducible empirical and semi-synthetic laboratory for deciding how a two-sided marketplace should randomize discounts or incentives, estimate effects under interference, and allocate treatment under a fixed budget.

The project is deliberately stricter than a conventional A/B-test demo. The assignment design, exposure mapping, target estimand, estimator, uncertainty, and decision policy are separate objects. The small observational fixture provides an illustrative scale anchor; it is not representative and does **not** identify causal price elasticities. Causal benchmark quantities come from a simulator whose counterfactual ground truth is known.

## What the vertical slice does

```text
documented Chicago public-trip fixture + pinned NYC full-month object
  -> validated and normalized trips
  -> complete NYC pickup-zone × hour and OD panels + diagnostics
  -> NOAA Central Park weather joins and descriptive associations
  -> ACS neighborhood-income and NYC permitted-event descriptive layers
  -> hash-verified descriptive simulation anchor
  -> NYC-informed and NYC-OD-geometry known-truth benchmarks
  -> transparently assumption-augmented marketplace and theoretical fixed-point models
  -> individual / geographic / temporal assignments
  -> estimator Monte Carlo with known truth
  -> budget-constrained policy evaluation on unseen seeds
  -> generated decision table, reports, and dashboard
```

The NYC TLC High Volume For-Hire Vehicle adapter has two verified modes. Bounded mode selects
equal quotas from 96 predeclared date × hour strata by stable hash and records the non-probability
selection. Full mode streams the pinned January 2024 monthly object in 100,000-row batches,
builds a complete zone-hour grid and OD-hour panel, and fails closed on raw-hash, calendar,
conservation, or publication errors. A separately manifested NOAA Central Park join describes
January weather/completed-trip associations; it is observational, uses one station as a citywide
proxy, and is not a weather effect or an instrument. Two further fail-closed descriptive layers
are also verified. The neighborhood layer uses 2022 ACS five-year B19001 household-income bins
and an equal-area Taxi Zone-to-NTA crosswalk; its manifested classified coverage excludes
unsupported and non-residential-dominant zones, and the result is ecological, not rider/driver
individual income and not causal.
The calendar layer retains all 6,007 January-overlapping permit rows representing 951 source
event IDs. Days above the monthly median permit count have 3.055% more published completed trips
in the raw contrast, but all eight weekend days fall in that group and the weekday-only contrast
is -8.198%. Permits do not measure attendance, and neither contrast is an event effect. Transit
disruption remains an unavailable optional enrichment rather than an imputed zero.

## Quick start

Python 3.11 or newer is required.

```bash
make setup
make reproduce-sample
make test
make dashboard
make validate-nyc-sample  # networked 10,000-row stratified NYC validation
make validate-nyc-full    # explicit 451 MiB full-month download/build/analysis
make nyc-simulation-anchor # verify NYC lineage and build a noncausal simulator anchor
make nyc-weather          # descriptive NOAA/NYC associations only
make nyc-income           # ecological ACS/Taxi Zone associations only
make nyc-events           # citywide permit/calendar associations only
.venv/bin/python -m casuallab nyc-benchmark # known truth initialized from the NYC anchor
.venv/bin/python -m casuallab nyc-graph-benchmark # known truth on fixed NYC OD geometry
.venv/bin/python -m casuallab equilibrium-benchmark # theoretical fixed-point benchmark
```

Individual stages are also available:

```bash
make download-sample   # materialize the committed fixture; optional remote refresh is explicit
make build-panel       # normalized Parquet, diagnostics, manifest, and zone-time panel
make simulate          # deterministic semi-synthetic market and ground-truth metadata
make benchmark         # design/estimator Monte Carlo against known structural truth
make interference-benchmark # two-stage saturation + mapped exposure recovery
make report            # generated technical report, executive memo, and decision appendix
make validate-nyc-sample # isolated NYC raw/clean/panel/diagnostics/manifest
make validate-nyc-full   # streamed full-month panels + descriptive validation bundle
make nyc-income          # ACS B19001 + equal-area Taxi Zone/NTA descriptive bundle
make nyc-events          # complete January permit/calendar descriptive bundle
```

`make reproduce-sample` additionally runs the simulator-evaluated honest-holdout policy comparison and generates the technical report, executive memo, and decision appendix from computed artifacts.

The default Monte Carlo plan is a compact eleven-cell grid: a 2 × 2 spillover/persistence factorial plus predeclared treatment-duration, cluster-count, saturation, washout, low-budget, rider-discount-only, and driver-incentive-only checks. The budget cell is an explicitly unidentified assignment-versus-policy diagnostic; its shared cap and empirical binding rate are recorded rather than presented as estimator recovery. A separate known-truth two-stage saturation benchmark tests controlled own, mapped-neighbor, and exact-history response recovery without relabeling those contrasts as the all-market policy effect.

Six additional layers stay deliberately separate. The NYC-informed benchmark borrows verified
descriptive initialization moments but keeps every behavioral response as an explicit simulator
assumption. The NYC graph benchmark borrows a fixed, pre-treatment OD geometry while declaring
spillover magnitude in the synthetic DGP—the OD weights are relative exposure weights, not causal
strength. The equilibrium benchmark solves paired control/policy fixed points only inside a
declared theoretical model whose parameters are not fitted to NYC. The NOAA layer reports
descriptive Central Park weather associations and makes no causal weather or treatment claim.
The income layer spatially allocates ACS household-income distributions and supports ecological
area description only. The event layer measures permitted-event records—not attendance or
realized event exposure—and its citywide daily contrasts remain calendar-confounded associations.

Generated data and artifacts are ignored by version control. The small source fixture and its provenance/checksum are committed so the default sample path works offline.
`constraints.txt` pins the dependency environment captured for the verified run; the reproduction manifest also records Python/package versions, input hashes, and a source-tree digest.

## Evidence contract

| Label | What it can support | What it cannot support |
|---|---|---|
| **Empirical / descriptive** | Observed fares, completed-trip patterns, OD flows, missingness, rounding, Central Park weather, area-income, and permitted-event associations for the pinned source/window | Latent demand; individual income; attendance; causal weather, event, income, persistence, price, incentive, or rollout effects |
| **NYC-informed semi-synthetic** | Estimator/design recovery against known simulator truth after descriptive NYC initialization | An NYC treatment effect or a structurally estimated NYC response function |
| **NYC-geometry known truth** | Controlled own, neighbor, and history recovery on a fixed pre-treatment NYC OD graph | Treating OD weight as spillover strength or relabeling controlled slopes as the market-total effect |
| **Theoretical fixed point** | Existence/convergence diagnostics and paired counterfactual truth inside the declared equilibrium equations | An empirical equilibrium, NYC structural estimate, or live forecast |
| **Decision projection** | Bias/RMSE/coverage/power and honest-holdout policy comparisons under stated simulator assumptions | A transportable real-world effect without external validation and a valid experiment |

Every benchmark row names the target estimand. Ground truth is generated from counterfactual simulator paths rather than hard-coded result tables.

## Repository map

- `src/casuallab/data.py` — public-data acquisition, validation, diagnostics, manifests, and panel construction.
- `src/casuallab/nyc_calibration.py` and `nyc_simulation.py` — full-month descriptive/network evidence and a fail-closed semi-synthetic simulator anchor.
- `src/casuallab/nyc_weather.py` — hash-verified NOAA Central Park joins and explicitly noncausal completed-trip associations.
- `src/casuallab/nyc_income.py` — ACS 2022 B19001 aggregation and equal-area Taxi Zone/NTA allocation with ecological, noncausal contrasts.
- `src/casuallab/nyc_events.py` — complete January permit/holiday normalization and explicitly noncausal citywide associations.
- `src/casuallab/nyc_benchmark.py` — NYC-informed known-truth design/estimator validation; not an NYC effect estimate.
- `src/casuallab/nyc_graph_benchmark.py` — two-stage saturation recovery on fixed NYC OD geometry, with graph weights separated from spillover strength.
- `src/casuallab/equilibrium.py` — theoretical two-sided fixed-point counterfactuals with convergence and uniqueness diagnostics.
- `src/casuallab/simulator.py` — deterministic two-sided marketplace with explicit rider-discount, driver-incentive, or bundled treatment versions and counterfactual ground truth.
- `src/casuallab/designs.py` — individual, geographic, time-block, switchback, and geo-by-time assignment.
- `src/casuallab/interference.py` and `interference_benchmark.py` — two-stage saturation, pre-treatment exposure maps, exact histories, and controlled exposure-response recovery.
- `src/casuallab/estimands.py` — causal targets and identification requirements.
- `src/casuallab/estimators.py` — transparent estimator ladder.
- `src/casuallab/benchmark.py` and `marketplace_benchmark.py` — Monte Carlo metrics and simulator-to-estimator sensitivity comparisons.
- `src/casuallab/marketplace_policy.py` — budget-feasible policies re-evaluated through the marketplace simulator on honest holdout seeds.
- `src/casuallab/policy.py` — a separately labeled pedagogical independent-unit response-surface benchmark.
- `src/casuallab/dashboard.py` — interactive decision interface.
- `configs/` — sample, full-data, simulation, and benchmark inputs.
- `tests/` — reproducibility, recovery, interference, estimator, data, and policy tests.
- `reports/` and `portfolio/` — technical, executive, limitations, and interview materials.
- `docs/DECISION_LOG.md` — consequential modeling and identification decisions.
- `STATUS.md` — current evidence and verification state.

## Data provenance and measurement cautions

The initial fixture comes from the City of Chicago's [Transportation Network Providers Trips (2018–2022)](https://data.cityofchicago.org/Transportation/Transportation-Network-Providers-Trips-2018-2022-/m6dm-c72p) dataset, Socrata ID `m6dm-c72p`. Its public metadata documents rounded timestamps/fares and possible geographic suppression. The main expansion uses [NYC TLC Trip Record Data](https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page), which is published monthly and can undergo schema changes.

The pipeline records these limitations in machine-readable diagnostics. A fixture is a reproducible integration sample, not a representative probability sample of all trips.

The committed NYC sample configuration uses January 1, 10, 19, and 28 of 2024 and all 24 hours,
allocating 10,000 rows evenly across the resulting 96 strata. Stable within-stratum hashing makes
the bounded extract reproducible for a fixed upstream object. Equal quota sampling deliberately
does not estimate month-level trip shares without design weights.

The full configuration pins January 2024 by row count, byte size, and SHA-256. Its complete
published-object analysis covers 19,663,930 completed-trip records and is reproducible with
`make validate-nyc-full`. It describes the records TLC received and published; it does not cover
latent or unserved demand and does not identify causal fare, incentive, persistence, or spatial
substitution effects. See `artifacts/nyc_full/full_month_report.md` and
`artifacts/nyc_full/validation.json`.

The corresponding contextual bundles are independently manifested under
`artifacts/nyc_full/weather/`, `artifacts/nyc_full/income/`, and
`artifacts/nyc_full/events/`. Their joins conserve the 19,663,930 published completed trips.
Income coverage and event-calendar completeness make the descriptions auditable; they do not
create exogenous variation or upgrade either comparison to a treatment-effect estimate.

## Reading results responsibly

1. Check `evidence_type` and `target_estimand` first.
2. Confirm that the assignment and exposure mapping identify that estimand under the stated interference assumptions.
3. Inspect bias, RMSE, interval coverage, and power together; a precise answer to the wrong estimand is not useful.
4. Treat policy values as holdout simulation performance conditional on the configured model.
5. Stress-test spillover, persistence, cluster count, washout, and budget before making a design recommendation.
6. Read weather, neighborhood-income, and permit-event joins as descriptive associations; read NYC graph weights as geometry and equilibrium outputs as within-model theoretical quantities.

Start with `STATUS.md` for the verified run. Current machine-generated results are in
`artifacts/reports/technical_report_generated.md` and
`artifacts/reports/product_decision_memo_generated.md`; the source companions in `reports/`
explain the design and limitations.
