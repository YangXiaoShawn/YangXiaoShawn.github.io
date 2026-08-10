# Experiment design memo

**To:** Marketplace experimentation, operations, pricing, and finance  
**Subject:** How to test rider discounts or driver incentives when markets interfere  
**Recommendation status:** Generated full-grid benchmark reviewed; no single design-estimator
pair passes every declared scenario. Scenario-conditional evidence is available, while live
duration, washout, power, and value require operational inputs and a randomized pilot.

**Generated evidence:** `artifacts/reports/technical_report_generated.md` and
`artifacts/benchmarks/benchmark_results.csv`.

## Evidence used—and not used—to choose the design

The evidence stack deliberately separates six additions to the core simulator. The
NYC-informed benchmark tests known-truth recovery after descriptive initialization; it does not
estimate an NYC treatment response. The NYC graph benchmark tests two-stage saturation and
controlled own, mapped-neighbor, and exact-history effects on a fixed pre-treatment OD geometry;
OD flow weights define relative exposure, not spillover strength. The fixed-point benchmark is a
theoretical feedback stress test with parameters not fitted to NYC. The NOAA Central Park join
describes weather/completed-trip co-movement and is neither a causal weather effect nor an
instrument. The ACS 2022 five-year B19001 layer assigns household distributions through an
equal-area Taxi Zone/NTA mapping; its supported-zone labels are ecological area characteristics,
not individual income or an income effect. The complete January permit layer retains 6,007 source
rows/951 source event IDs, but permits do not measure attendance. Its raw high-versus-lower
permit-intensity contrast is +3.055%; all eight weekends are in the high group and the
weekday-only contrast is -8.198%, making calendar confounding visible. These layers can motivate
pre-treatment blocking, measurement, and stress tests, but none replaces a live randomized pilot.

## Decision in one paragraph

If the business question is whether an incentive improves the whole marketplace, randomize markets rather than isolated people. Use parallel geographic clusters when connected rider and driver flows can be contained in sufficiently separated clusters. If there are too few independent geographies and the treatment is reversible, use randomized geo × time blocks or a switchback with a washout shown to be adequate under persistence sensitivity. Analyze intent to treat at the assignment level, target market-level incremental completed trips or welfare per incremental dollar, and enforce wait-time, service, driver, geographic, and budget guardrails. Do not set a live duration or rollout threshold from this memo alone; those quantities must come from the reproducible power and sensitivity outputs.

## 1. Decision and target estimand

The decision is whether, where, and when to deploy a rider discount or driver incentive under a fixed budget. The primary estimand should therefore be the **market-total policy effect** of the feasible all-market policy relative to business as usual over a pre-specified horizon. It includes direct response, driver movement, rider substitution, congestion, and measured spillovers inside the declared market boundary. A design-aligned assignment ITT is a separate contrast and equals this rollout target only under stated exposure, carryover, compliance, and budget conditions.

The decision metric should be a policy-level ratio:

\[
\frac{\text{incremental completed trips, contribution, or welfare}}
{\text{incremental incentive and delivery spend}}.
\]

Use incremental totals in both numerator and denominator; do not divide treated trips by coupon spend and call that causal efficiency. If a complete welfare ledger is unavailable, use incremental completed trips or contribution per dollar as the primary operational metric and report welfare as a scenario analysis rather than a measured fact.

An individual direct effect can be a useful secondary estimand for understanding offer response. It should not be substituted for the total effect of rollout.

## 2. Why ordinary individual A/B randomization can mislead

Individual treatment and control units share the same marketplace. Treated riders may attract drivers, change wait times, shift demand across time, or displace untreated riders. Driver incentives can move supply across zone boundaries. Controls are then exposed to treatment indirectly, violating the independent-unit comparison that a standard A/B interpretation assumes.

The resulting difference in means may be:

- diluted because controls benefit from shared supply;
- exaggerated because treated units displace controls;
- correct for a direct effect at one saturation but wrong for total rollout; or
- accompanied by standard errors that are too small because outcomes move together within markets.

This is not an argument that individual randomization is always invalid. It is an argument to match it to a direct-effect question and to measure or randomize market saturation when exposure matters.

## 3. Recommended design hierarchy

### Option A — Parallel geographic clusters

**Use when:** enough weakly connected geographic markets can be constructed, and the intervention or its effects are persistent.

Randomize matched clusters to policy or control for the full experiment. Form clusters using pre-treatment origin-destination flows and driver/rider connectedness rather than administrative boundaries alone. Where practical, add buffers or measure boundary exposure. Block on pre-treatment demand, supply tightness, and major time-pattern predictors.

The fixed NYC OD graph is useful for this pre-treatment design engineering, but its edge weights
must not be read as estimated spillover magnitudes. Pre-specify alternative plausible exposure
maps and report whether the conclusion changes.

**Strength:** most direct design for the market-total policy effect and avoids repeated carryover between treatment and control.

**Risk:** cross-boundary movement contaminates clusters; few independent clusters limit power and asymptotic inference.

### Option B — Geo × time randomized blocks or switchback

**Use when:** the treatment is reversible, geography is scarce, and persistence is short enough to allow a defensible washout.

Randomize treatment sequences within geographic clusters, balance treatment across important demand cycles, and separate assigned analysis blocks with washout or exclude contaminated transition windows. The exposure history, not just current treatment, must be retained.

**Strength:** within-market comparisons can remove stable geographic differences and use scarce markets efficiently.

**Risk:** anticipation, driver repositioning, deferred demand, learning, or persistent effects can contaminate later control blocks.

### Option C — Two-stage saturation or individual assignment

**Use when:** the direct response and spillover curve are explicit targets.

Randomize cluster saturation first and individual eligibility second. This creates exogenous variation in own treatment and surrounding exposure. A simple individual-only A/B test is acceptable for a direct response when spillovers are negligible or held fixed, but it is not the recommended default for a market-total rollout decision.

## 4. Choosing between designs

| Diagnostic question | If yes | If no |
|---|---|---|
| Can the dominant rider/driver network be partitioned into enough weakly connected clusters? | Prefer parallel geographic clusters | Consider geo × time assignment |
| Can treatment be reversed operationally and ethically? | Switchback remains feasible | Use parallel assignment |
| Does the outcome or supply state persist beyond candidate blocks? | Lengthen blocks/washout or abandon switchback | Shorter randomized blocks may be considered |
| Is direct response at different saturation levels itself a product question? | Add two-stage saturation | Keep total-effect design primary |
| Are there too few effective clusters for reliable asymptotics? | Use randomization-based/small-sample inference and reconsider scope | Cluster-robust inference is more credible |

The benchmark should compare designs at the same expected budget and target estimand. A design does not become more informative merely by producing more row-level observations.

## 5. Duration and washout

No universal number of days or hours is defensible before the configured persistence, cluster count, intracluster correlation, minimum decision-relevant effect, and operational cycle are known.

Set duration using the following sequence:

1. Choose the primary outcome and smallest effect that would change the product decision.
2. Estimate baseline variability and temporal dependence from pre-treatment panel data, labeling these as descriptive inputs.
3. Simulate credible low, baseline, and high interference/persistence scenarios.
4. Choose a horizon that covers the relevant demand cycles and yields acceptable power under the adverse credible scenario, not only the baseline.
5. For switchbacks, select a washout long enough that residual effects are small relative to the decision threshold; run analyses excluding one or more transition windows.
6. Pre-specify a reassessment rule based on blinded variance and operational integrity, not observed treatment lift.

**Current generated result:** duration and washout sensitivity cells were run, but no candidate
survives the complete identification/inference gate across all declared scenarios. The benchmark
therefore supports this procedure, not a universal numerical duration or washout for a live test.

## 6. Outcomes and success criteria

### Primary outcome

Use a market-level outcome connected to the decision:

- incremental completed trips per incremental dollar; or
- incremental contribution/welfare per incremental dollar when the required cost and surplus components are measured credibly.

If requests and supply data are available, a served-request or marketplace welfare measure may be more robust than completed trips alone because incentives can change both the numerator and opportunity set.

### Guardrails

Pre-specify acceptable ranges for:

- wait time, cancellation, and service probability;
- driver utilization, earnings, and repositioning burden when observed;
- geographic distribution and underserved-market outcomes;
- rider cost or experience;
- gross and incremental spend; and
- operational failures, eligibility leakage, and treatment delivery.

### Decision rule

Launch only when the decision metric clears a pre-specified practical threshold with uncertainty that rules out an unacceptable downside, guardrails remain acceptable, and the conclusion is stable to credible exposure and persistence definitions. A small p-value without a useful and stable effect is not a launch criterion.

## 7. Assignment and implementation details

Before randomization:

- freeze eligible zones, time blocks, treatment versions, and market boundary;
- construct clusters only from pre-treatment information;
- calculate adjacency and flow-based exposure maps;
- stratify or match on baseline demand, supply tightness, ecological area characteristics,
  pre-treatment calendar proxies, airport exposure, and time-cycle variables as available;
- record randomization probabilities and deterministic seed;
- validate budget feasibility for every permitted assignment; and
- reserve treatment/control labels from analysts during pipeline checks when possible.

During the experiment:

- log assignment, eligibility, delivery, redemption/receipt, incentive cost, and policy version separately;
- preserve all assignment histories and transition windows;
- track cross-boundary flows and realized neighbor saturation;
- monitor data completeness and guardrails without repeatedly testing the primary outcome; and
- document outages, overrides, and budget throttling as protocol deviations.

The same treatment label must not conceal different amounts, eligibility rules, or delivery mechanisms. If versions change, either redefine the treatment and estimand or treat the change as a protocol deviation.

## 8. Primary estimator and inference

Use a design-aligned **intent-to-treat** estimate. A transparent specification is a weighted cluster/time contrast with pre-treatment or stratum adjustment, where weights and fixed effects are pre-specified. Treatment receipt is a mechanism variable, not a replacement for assignment.

Uncertainty must follow the assignment:

- cluster by the geographic assignment unit for parallel cluster designs;
- account for both geographic and temporal dependence in geo × time designs;
- prefer randomization inference when assignment probabilities are known;
- use small-sample corrections or a justified bootstrap when clusters are few; and
- report the number of randomized units, not only trips or zone-time rows.

Regression adjustment can improve precision using pre-treatment covariates. Do not control for post-treatment price, wait time, realized driver supply, redemption, or market tightness when estimating the total policy effect; these are possible mediators.

Report alongside the primary estimate:

- unadjusted design-based contrast;
- adjusted estimate;
- confidence interval and practical decision threshold;
- exposure-specific and persistence sensitivity;
- assignment/protocol integrity; and
- incremental spend and budget compliance.

Difference in differences, doubly robust, or synthetic-control-style analyses are robustness or design-specific methods, not automatic upgrades. Their additional assumptions must be audited separately.

## 9. Power and design benchmark

The design benchmark must be generated, not narrated into existence. At minimum it should report, by spillover and persistence scenario:

| Quantity | Interpretation | Status |
|---|---|---|
| Bias | Average estimate minus matched ground truth | Generated by scenario/design/estimator |
| RMSE | Combined error from bias and variance | Generated by scenario/design/estimator |
| Interval coverage | Frequency with which intervals include truth | Generated only where inference is declared valid |
| Power | Rejection probability under a declared effect | Generated only where inference is declared valid |
| Effective randomized units | Information-bearing clusters/blocks | Recorded; fewer than eight clusters fail the benchmark inference gate |
| Normalized precision cost | Mean measurement cost multiplied by MSE; not operational cost | Generated |

The preferred design is the one that performs acceptably across the credible scenario set, not necessarily the one with the best baseline-scenario RMSE.

## 10. Threats that could reverse the conclusion

1. **Boundary leakage:** treatment moves trips into measured zones from outside the outcome ledger.
2. **Carryover:** an earlier treated period changes a later control period.
3. **Differential measurement:** treatment changes whether a request, cancellation, price, or trip is recorded.
4. **Budget throttling:** delivery depends on realized demand, so assigned treatment is not the actual policy under study.
5. **Concurrent interventions:** pricing, dispatch, marketing, events, or outages line up with assignment.
6. **Few clusters:** conventional cluster standard errors are unreliable.
7. **Treatment version drift:** the incentive amount or eligibility rule changes mid-test.
8. **Exposure-map failure:** administrative neighbors do not represent actual rider/driver flows.
9. **Full-market scaling:** a partial-saturation result does not automatically transport to full rollout.
10. **Selective targeting evaluation:** the policy is judged on the same simulations used to learn it.
11. **Context-proxy misuse:** ecological ACS area labels are treated as individual income, or
    permit counts are treated as attendance/realized exposure; January weekend composition can
    then masquerade as an event response.

These are design and interpretation risks, not items that a more flexible outcome model automatically fixes.

## 11. Post-experiment allocation

Do not rank zones by raw treated outcomes or subgroup point estimates. Compare budget-feasible policies on an honest holdout:

- no treatment;
- random allocation;
- uniform allocation;
- a pre-specified simple rule; and
- model-based targeting using only features available before assignment.

Score policy-level incremental outcome, welfare if measurable, spend, efficiency, guardrails, and stability under scenario perturbations. Prefer the simpler rule if the model-based policy's incremental advantage is within uncertainty or disappears under modest misspecification. Retain an exploration or control share after launch when effects can drift.

## 12. Pre-launch checklist

- [ ] Primary estimand, outcome, horizon, and weights are signed off.
- [ ] Cluster/exposure map is built from pre-treatment data and reviewed operationally.
- [ ] Interference and persistence scenario ranges are documented.
- [ ] Generated power supports the minimum decision-relevant effect.
- [ ] Switchback washout, if used, passes sensitivity checks.
- [ ] Randomization seed, probabilities, and balance checks are archived.
- [ ] Treatment delivery, receipt, and cost logging are tested.
- [ ] Cluster-aware/randomization inference code passes null and recovery tests.
- [ ] Guardrails and stopping rules are pre-specified.
- [ ] Policy evaluation uses unseen seeds or a true holdout.
- [ ] Numerical benchmark tables are generated and reviewed; none are copied from illustrative text.
