# Decision Log

## D001 — Build the Chicago vertical slice before the NYC expansion

- **Status:** Accepted
- **Decision:** Use the requested small Chicago TNP sample for the first end-to-end test, while keeping the ingestion interface able to query NYC TLC HVFHV Parquet for the main empirical expansion.
- **Why:** Chicago exposes geographic-area fields in a compact public API and the objective explicitly prioritizes it for the first slice. This is a portability check, not a claim that Chicago estimates identify NYC effects.

## D002 — Zone-hour is the first panel grain

- **Status:** Accepted
- **Decision:** Aggregate to pickup zone by local clock hour in sample mode; retain a configurable 15-minute option.
- **Why:** Hourly cells remain populated in a small fixture and fit comfortably on a laptop. Finer intervals are available for larger extracts.

## D003 — Calibration is descriptive, not causal

- **Status:** Accepted
- **Decision:** Calibrate baseline arrival and trip moments from the public panel but specify price/incentive response parameters in simulation configs.
- **Why:** Public trip data alone does not identify causal price elasticity because price responds to marketplace state and unobserved demand/supply shocks.

## D004 — Ground truth uses paired potential market paths

- **Status:** Accepted
- **Decision:** Compute simulator ground truth from common-random-number counterfactual paths under defined treatment/exposure regimes.
- **Why:** This makes the causal contrast explicit, reproducible, and less noisy than comparing unrelated random draws.

## D005 — Policy learning uses an honest holdout

- **Status:** Accepted
- **Decision:** Train heterogeneity models on independent simulations and score policies on unseen seeds with the budget constraint enforced before evaluation.
- **Why:** In-sample policy value is optimistically biased and can reward unstable targeting rules.

## D006 — Keep full-policy truth separate from assignment contrasts

- **Status:** Accepted
- **Decision:** Define `market_total_effect` on one fixed full-horizon population under the feasible all-zone policy versus zero. Treat randomized-arm coefficients, realized mixed-schedule effects, and washout-restricted diagnostics as different quantities.
- **Why:** Assignment-specific eligibility masks and partial saturation otherwise make cross-design bias comparisons target different populations while using the same label.

## D007 — Do not invent an individual truth from aggregate simulation

- **Status:** Accepted
- **Decision:** Mark the abstract individual direct effect unavailable in the zone-time simulator. Expose the finite focal-zone saturation contrast as `controlled_zone_direct_effect`.
- **Why:** A zone-level structural intervention cannot validate an individual rider causal contrast that the simulated data do not represent.

## D008 — Treat the public fixture only as an illustrative scale anchor

- **Status:** Accepted
- **Decision:** Match the simulator's control completed-trip scale and observed fare to the compact fixture while leaving behavioral, supply, spillover, persistence, and welfare parameters as explicit assumptions.
- **Why:** The fixed 300-row, time-stratified extract is useful for traceability and integration testing, but its occupied-cell moments are not representative city market-intensity estimates.

## D009 — Withhold a robust recommendation when identification fails

- **Status:** Accepted
- **Decision:** A design-estimator pair must pass the declared identification screen and fit-completeness threshold in every scenario used for robust selection. Otherwise generated reports state that no robustly identified candidate is available.
- **Why:** Dropping adverse unidentified scenarios before ranking would make an easy-case result look robust and would overstate what the benchmark establishes.

## D010 — Make the intervention version explicit

- **Status:** Accepted
- **Decision:** Configure every simulated experiment as `rider_discount`, `driver_incentive`, or `bundled`. Rider-only paths disable incentive/supply-response channels; driver-only paths disable discount/demand-response channels; the bundle activates both at a common assigned intensity.
- **Why:** Treating one bundled policy as if it represented separable discount and incentive experiments would make the assignment, spend, and causal contrast ambiguous. A simultaneous factorial rider-versus-driver experiment remains a distinct future design rather than an implicit simulator feature.

## D011 — Predeclare a compact operating-parameter sensitivity plan

- **Status:** Accepted
- **Decision:** Retain the paired spillover × persistence factorial and add one-at-a-time cells for treatment duration, geographic cluster count, saturation, washout, and a low shared budget. Use two zones per requested geographic cluster so generated benchmark geometry matches dashboard controls; include a `G=8`, 16-zone cell for adequate-cluster inference diagnostics. Equal-geometry cells reuse exact latent draws; the 16-zone cell reuses the deterministic replication seed but is not an exact common-random-number pair. Mark every shared-budget assignment comparison as a target mismatch and report its realized binding rate.
- **Why:** A benchmark that varies only structural interference cannot support duration, cluster,
  dose, washout, treatment-version, or budget decisions. The compact declared plan covers those
  choices without an infeasible Cartesian grid, while explicit target and inference gates prevent
  the extra diagnostics from being mistaken for identified policy effects.

## D012 — Tie driver response to the declared incentive dose

- **Status:** Accepted
- **Decision:** Interpret `direct_supply_effect` and driver-side spillover/mobility parameters at `reference_incentive_per_driver`. Scale those log-response channels linearly by the configured incentive divided by that reference; keep payment cost at the configured dollar amount.
- **Why:** A dashboard incentive knob that changed only spend would not represent an incentive-size decision. The linear reference-dose mapping is transparent and testable, but it remains a semi-synthetic assumption—not an elasticity estimated from the public trip fixture—and should be stress-tested before operational use.

## D013 — Validate NYC with balanced day-hour quotas, not a file prefix

- **Status:** Accepted
- **Decision:** For bounded NYC HVFHV validation, select equal quotas by stable hash from all 24
  hours on four month-spanning dates (days 1, 10, 19, and 28). Require one month, encode every
  selection dimension in the cache key, validate cached row/stratum counts, and isolate sample
  and full outputs from the Chicago reproduction.
- **Why:** The upstream file's first 10,000 physical rows all came from one midnight hour, so a
  simple `LIMIT` proved ingestion but could not support temporal or geographic panel validation.
  Equal strata cover the intended schema and panel grain while remaining explicitly
  non-probability and non-population-weighted.

## D014 — Stream and pin the NYC full month before making empirical claims

- **Status:** Accepted and verified
- **Decision:** Pin the January 2024 HVFHV object by exact rows, bytes, and SHA-256; normalize
  100,000-row Arrow batches with global physical-row surrogate IDs; aggregate with single-threaded
  DuckDB under a 1 GB memory limit; publish only after calendar, schema, row-conservation, and
  manifest checks pass. Complete the observed monthly zone universe across all 744 hours, because
  an absent cell in this query-complete published object is a reported zero rather than an unknown
  sample omission.
- **Why:** The former eager path could exceed a 16 GB laptop budget and a failed run could leave
  mixed artifacts. The canonical streamed transaction completed 19,663,930 records in 55.18
  seconds with 3,839,901,696 bytes (3.58 GiB) maximum RSS and 6,313,925,232 bytes
  (5.88 GiB) peak footprint. Two single-threaded reruns produced identical bytes for all 201
  data files. These guarantees support reproducible descriptive analysis of the pinned published
  records, not latent demand or causal marketplace effects.

## D015 — Pair policy sensitivity across treatment versions without treating it as evidence

- **Status:** Accepted
- **Decision:** Preserve the bundled-policy decision table as the primary policy artifact and
  publish a separate rider-discount, driver-incentive, and bundled sensitivity. Reuse the same
  training and holdout market seeds across versions, fit a separate learner inside each version,
  and hash the summary and market ledger under an independent manifest.
- **Why:** Common seeds remove avoidable latent-market noise when comparing configured response
  functions, while separate learners respect the different rider- and driver-side channels. The
  resulting contrast remains semi-synthetic model sensitivity—not an empirical dose response,
  treatment-effect comparison, or live-market ROI estimate.

## D016 — Turn the NYC month into descriptive scale and network inputs, not causal parameters

- **Status:** Accepted and verified
- **Decision:** Build a separately manifested full-month calibration/network bundle from the
  complete January 2024 zone-hour and OD panels. Record request-to-pickup time, driver pay, fare,
  completed-trip variance components, exact-lag associations, and the symmetric monthly OD-flow
  graph. Export the OD weights as a pre-treatment exposure-map candidate, but do not map flow
  strength to spillover magnitude or interpret temporal association as persistence.
- **Why:** The published file supports precise description of completed trips and connectedness,
  but it omits latent demand, available supply, assignment, treatment delivery, and untreated
  counterfactuals. Keeping the bundle descriptive makes it useful for design engineering without
  laundering observational co-movement into a causal parameter.

## D017 — Validate an NYC-informed control path while keeping causal parameters assumed

- **Status:** Accepted and verified
- **Decision:** Translate the verified NYC bundle into a portable semi-synthetic proposal that
  matches the deterministic control path to mean published completed trips, mean nonnegative
  request-to-pickup time, and descriptive between-zone and hour-of-day variance shares. Preserve
  the configured supply ratio and label treatment response, supply response, spillovers,
  persistence, substitution, matching, welfare, and experiment design as explicit assumptions.
- **Why:** This anchors scale and heterogeneity to the main empirical dataset without claiming a
  structural demand/supply fit. The resulting configuration is a validated initialization
  proposal; it does not make the default benchmark an NYC causal estimate or a solved market
  equilibrium.

## D018 — Identify controlled exposure responses with two-stage saturation

- **Status:** Accepted and verified in known-truth simulation
- **Decision:** Add a balanced two-stage geographic saturation design, a normalized pre-treatment
  neighbor map, exact-lag treatment history, and cluster-t exposure regression. Benchmark the
  controlled own, neighbor, and history response slopes against known truth. Report a naive
  stage-one saturation coefficient only as a target-mismatch diagnostic when it omits mapped
  exposures; withhold its bias, coverage, and power against `market_total_effect`.
- **Why:** Under interference, a randomized assignment coefficient can be precise for the wrong
  contrast. Saturation support and an explicit exposure mapping make narrower controlled effects
  estimable while preserving the distinction from the feasible all-zone policy effect.

## D019 — Keep the two NYC-shaped known-truth benchmarks scientifically distinct

- **Status:** Accepted and verified in semi-synthetic benchmarks
- **Decision:** Use the NYC-informed marketplace benchmark to test design and estimator recovery
  after a hash-verified descriptive scale/heterogeneity initialization. Use a separate NYC-graph
  benchmark to test controlled own, neighbor, and history recovery under two-stage saturation on
  a fixed pre-treatment OD geometry. Revalidate each source manifest and hash at artifact publish
  and report time. Never interpret either benchmark as an NYC treatment-effect estimate.
- **Why:** Borrowing descriptive moments and borrowing graph geometry answer different validation
  questions. In particular, OD edge weights set relative exposure geometry; the synthetic DGP
  still declares spillover strength. Keeping the layers and their target estimands separate avoids
  turning simulator recovery into an empirical or structural claim.

## D020 — Treat fixed-point equilibrium as a theoretical benchmark

- **Status:** Accepted and verified in the declared model
- **Decision:** Solve paired control and policy fixed points for the explicit two-sided equations,
  record convergence, residual, and contraction/uniqueness diagnostics, and label resulting
  counterfactuals `not_an_empirical_or_nyc_structural_estimate`. Do not calibrate or claim the
  behavioral response parameters from NYC trip records.
- **Why:** A converged fixed point demonstrates internal mathematical coherence and exposes how
  feedback can change a policy contrast. It does not establish that the equations or parameters
  describe the live NYC marketplace.

## D021 — Use Central Park weather only as a descriptive enrichment

- **Status:** Accepted and verified for the pinned January window
- **Decision:** Join a separately pinned NOAA Central Park daily weather source to the full-month
  NYC panel, preserve source hashes and join/conservation checks, and report only descriptive
  wet/dry and temperature associations in completed trips. Do not use station weather as a causal
  weather effect, an incentive effect, or an instrument by default.
- **Why:** One station is an imperfect citywide proxy and weather co-moves with calendar,
  mobility, and service conditions. The join improves empirical description, but it supplies no
  identifying variation for marketplace treatment effects without an additional design.

## D022 — Treat ACS income as an ecological area characteristic

- **Status:** Accepted and verified for the pinned source/window
- **Decision:** Use the official 2022 ACS five-year B19001 household-income distribution, the
  official 2020 tract-to-NTA mapping, and official NTA/Taxi Zone geometries. Compute NTA income
  distributions from the sixteen bins, intersect geometries in equal-area EPSG:6933, and allocate
  bin counts across Taxi Zones with within-NTA normalization so every bin and household total is
  conserved. Classify only zones with supported residential distributions; keep unsupported and
  non-residential-dominant zones visibly unclassified. Compare area groups descriptively and
  never substitute a median of tract/NTA medians for the grouped household distribution.
- **Why:** ACS B19001 measures household income by residence, not individual rider or driver
  income. Area allocation assumes households are uniformly distributed within each NTA and land
  use, population, employment, transit, and trip composition confound high/low-area comparisons.
  The manifested layer supports ecological marketplace description, not an income effect,
  discrimination claim, population claim, or individual behavioral response.

## D023 — Treat permitted events as a citywide calendar proxy, not realized exposure

- **Status:** Accepted and verified for the pinned January window
- **Decision:** Preserve the complete official January-overlap snapshot—6,007 permit rows and 951
  source event IDs—along with official holiday dates. Expand only the 5,998 positive-duration
  rows/949 IDs under half-open `[start, end)` semantics; retain and separately flag the one
  reversed and eight zero-duration rows. Define high permit intensity from the source-only monthly
  median, and join the resulting daily citywide signal to every date-hour without pretending it
  is zone- or event-hour exposure. Report raw and weekday-only associations together.
- **Why:** Permit timestamps can include setup and breakdown, duplicate locations within an event,
  and no attendance or realized severity. In this month all eight weekend days are above the
  permit-count median: the raw high-versus-lower completed-trip contrast is +3.055%, whereas the
  weekday-only contrast is -8.198%. That reversal exposes calendar composition and rules out a
  causal event interpretation; neither contrast identifies an attendance, demand, or treatment
  effect.
