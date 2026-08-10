# Project Plan

## Decision problem

How should a two-sided ride-hailing marketplace randomize rider discounts or driver incentives, estimate effects when treatment spills across markets, and allocate treatment under a fixed budget?

## Delivery sequence

1. **Laptop-safe vertical slice:** documented Chicago public-trip fixture, normalized trip data, zone-hour panel, descriptive calibration moments, deterministic two-zone marketplace, individual and geographic-cluster assignment, difference-in-means and cluster-adjusted estimates, Monte Carlo bias comparison, and an experiment-design memo.
2. **Design and estimator expansion:** time blocks, switchbacks, geo-by-time assignment, washout periods, regression adjustment, DiD, doubly robust estimation, synthetic-control-style comparison, and heterogeneous-effects benchmarks.
3. **Decision layer:** honest-holdout policy learning under a budget, no/random/uniform/rule/model
   baselines, stability penalty, incremental outcome and welfare per dollar, plus a separately
   labeled rider-discount/driver-incentive/bundled response-function sensitivity that reuses the
   same training and holdout market seeds.
4. **Empirical expansion:** verified bounded and full-month NYC TLC high-volume for-hire vehicle
   pipelines, complete zone-hour and OD-hour panels, descriptive validation tables, a portable
   network/calibration bundle, a fail-closed semi-synthetic control-path anchor, and a manifested
   NOAA Central Park join, plus independently manifested ecological neighborhood-income and
   permitted-event/calendar layers through `make nyc-income` and `make nyc-events`. Weather,
   income, and event contrasts remain descriptive; transit disruption and identified empirical
   treatment heterogeneity remain subsequent work.
5. **NYC-shaped and theoretical validation:** run an NYC-informed known-truth marketplace
   benchmark, a two-stage saturation benchmark on a reproducibly selected fixed NYC OD subgraph,
   and a separate theoretical two-sided fixed-point benchmark. Preserve their distinct scopes:
   simulator truth after descriptive initialization, simulator truth on borrowed geometry, and
   truth only within declared equilibrium equations.
6. **Communication:** generated benchmark tables, interactive dashboard, technical report, executive memo, limitations audit, and portfolio materials.

## Phase gates

| Gate | Evidence |
|---|---|
| Reproducible data | Source URL/query, immutable fixture checksum, schema validation, manifest, diagnostics, deterministic panel |
| Valid simulation | Same seed reproduces output; known ground-truth estimands derived from counterfactual runs |
| Design comparison | At least three assignment designs share a documented target estimand |
| Estimator benchmark | Bias, variance, RMSE, coverage, power, and decision-information cost generated from Monte Carlo draws |
| Policy evaluation | Budget feasibility and honest holdout comparison against simple baselines |
| Interference mapping | Pre-treatment exposure map, two-stage saturation support, exact histories, and controlled-effect recovery without market-total relabeling |
| NYC-informed benchmark | Exact anchor reconstruction, known simulator truth, fit ledger, and explicit `nyc_empirical_causal_effect = false` |
| NYC OD graph benchmark | Verified calibration manifest/hashes, pre-treatment-only subset rule, fixed relative graph weights, and controlled-effect recovery without treating flow as spillover strength |
| Theoretical equilibrium | Fixed-point residual and contraction diagnostics, paired control/policy state, and explicit `not_an_empirical_or_nyc_structural_estimate` scope |
| Weather enrichment | Pinned NOAA lineage, complete calendar/panel join, trip conservation, and `causal_claim = false` on every association |
| Neighborhood-income enrichment | Official 2022 ACS five-year B19001, official Taxi Zone/NTA geometries and tract mapping, equal-area allocation, distribution/trip conservation, explicit non-residential/unsupported exclusions, and an ecological noncausal contract |
| Permitted-event enrichment | Complete January-overlap permit snapshot, 6,007 retained source rows/951 source IDs, positive-duration half-open expansion, separate reversed/zero-duration audit, holiday calendar, trip conservation, and explicit citywide-proxy/noncausal scope |
| Portfolio readiness | One-command sample reproduction, tests/lint green, dashboard and reports use generated results |

## Resource strategy

- Sample mode uses a small committed fixture and small Monte Carlo counts.
- The time-stratified fixture is not a census of each zone-hour. Its default panel therefore retains observed cells only: an absent fixture cell is unknown, not zero demand. Complete-grid zero cells are supported and tested, but should be enabled only for a query-complete extract whose missing bins genuinely mean zero observed trips.
- The NYC sample adapter performs bounded DuckDB HTTP range reads across 96 configured
  date-hour strata and writes to `data/nyc_sample/`; its equal-quota sample is deterministic but
  non-probability and non-population-weighted. Full mode writes to `data/nyc_full/`, requires an
  explicit CLI opt-in, normalizes 100,000-row Arrow batches, and uses a 1 GB DuckDB aggregation
  limit. The canonical verified January 2024 run completed in 55.18 seconds with
  3,839,901,696 bytes (3.58 GiB) maximum RSS and 6,313,925,232 bytes (5.88 GiB) peak
  footprint, below the 16 GB target.
- Polars or DuckDB performs aggregation; Pandas is reserved for compact statistical tables.
- The NOAA weather, ACS income, and permitted-event paths are optional, fail-closed descriptive
  enrichments; core reproduction does not require them. Unsupported/non-residential income zones
  remain explicitly unclassified, invalid event intervals remain flagged, and unavailable transit
  disruption data remain visible rather than being imputed as “normal” or zero.

## Risks

- Public schemas and URLs can change: pin source queries and checksums in manifests.
- Chicago and NYC public extracts suppress or round sensitive fields: expose diagnostics and avoid false precision.
- Simulator calibration is not structural identification: describe it as semi-synthetic and use sensitivity analysis.
- Interference changes what naive estimators target: report the exposure mapping and estimand beside every result.
- NYC OD weights can define relative exposure geometry but cannot be converted into spillover
  strength without new causal or structural evidence.
- Central Park weather is a citywide observational proxy; wet/dry or temperature contrasts are
  confounded and must not be used as causal weather effects or instruments by default.
- ACS B19001 describes household income by residence. Equal-area NTA-to-Taxi-Zone allocation
  assumes households are spatially uniform within each NTA, so high/low-area comparisons are
  ecological, not individual rider/driver income or an income effect.
- Permitted-event records include setup/breakdown and do not measure attendance or actual audience
  exposure. In January all eight weekends are above the median permit count, so the raw +3.055%
  completed-trip contrast and the weekday-only -8.198% contrast are descriptive, composition-
  sensitive associations rather than event effects.
- A converged fixed point is a mathematical result inside its declared model, not evidence that
  the model is an empirically estimated NYC equilibrium.
