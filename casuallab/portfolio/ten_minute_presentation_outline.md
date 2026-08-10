# Ten-minute presentation outline

**Title:** Causal Marketplace Lab: Pricing, Incentives, Interference, and Policy Learning  
**Audience:** Economics, applied science, marketplace/product, and engineering interviewers  
**Rule:** Never type a numerical result into the deck from memory. Populate result visuals only from generated artifacts and retain the evidence label.

## Narrative arc

The presentation answers one question:

> How do you design, estimate, and act on an incentive experiment when treated and control users share the same marketplace?

The story moves from the decision failure in ordinary A/B testing, to an estimand-first evidence stack, to known-ground-truth validation, and finally to a budget allocation rule with honest evaluation.

## Slide 1 — The experiment can be randomized and still answer the wrong question

**Time:** 0:00–0:45  
**Headline:** “A rider-level A/B test is not automatically a marketplace rollout test.”

**Visual:** Two neighboring zones connected by rider and driver arrows. One treated rider pulls a driver toward the treated zone; an untreated rider's wait time changes. Use no chart or number.

**On slide:**

- Rider discount or driver incentive
- Shared supply, geographic substitution, temporal carryover
- Decision: incremental marketplace value per dollar

**Talk track:**

> Imagine randomizing a rider discount. Assignment is clean, but riders and drivers do not live in isolated experimental units. A treated rider can attract supply, reduce someone else's wait, or pull a driver from a control zone. The individual contrast may be a valid direct-response estimate and still be the wrong rollout effect. My project asks what to randomize, how to estimate the effect under interference, and how to spend a fixed budget afterward.

**Transition:** “That means I had to define the decision quantity before choosing an estimator.”

## Slide 2 — Start with the estimand, including exposure and history

**Time:** 0:45–1:50  
**Headline:** “The potential outcome is (Y(a,e,h)), not just (Y(1)) or (Y(0)).”

**Visual:** Three inputs flowing into outcome:

```text
own assignment a ─┐
neighbor exposure e ├─> market outcome over a declared boundary/horizon
treatment history h ┘
```

**On slide:**

- Primary: market-total feasible-policy effect; assignment ITT is separate
- Secondary: direct, spillover, short-run, cumulative
- Decision metric: incremental trips / contribution / welfare per incremental dollar

**Talk track:**

> I wrote the estimand registry first. Own treatment, neighbor exposure, and recent treatment history can all affect outcomes. For rollout, my default is a market-total feasible-policy effect over an explicit boundary and horizon. The assignment ITT, a direct effect, and a spillover effect are separate contrasts; the ITT is a rollout proxy only when exposure, carryover, delivery, and budget assumptions align them. This choice drives the randomization unit, aggregation, and standard errors.

**Callout:** A recipient-versus-nonrecipient comparison is selected; ITT remains primary. Full welfare requires a complete surplus and cost ledger.

**Transition:** “The next issue is which evidence can support that causal statement.”

## Slide 3 — Separate empirical description from causal validation

**Time:** 1:50–3:00  
**Headline:** “Public data calibrate the market; simulation exposes causal truth.”

**Visual:** Compact evidence-scope table.

| Layer | What it contributes | Claim boundary |
|---|---|---|
| NYC TLC + NOAA public data | Completed-trip, OD-flow, and Central Park weather description | No causal price, weather, or incentive effect |
| ACS neighborhood layer | 2022 five-year B19001 allocated by equal-area Taxi Zone/NTA overlap | Ecological area composition, not individual income or an income effect |
| NYC permitted-event layer | Complete January permit/calendar proxy | Permit ≠ attendance; no causal event effect |
| NYC-informed simulator | Known-truth recovery after descriptive initialization | Not an NYC treatment effect or structural fit |
| Fixed NYC OD graph | Known-truth controlled own/neighbor/history recovery | Graph weight is geometry, not spillover strength |
| Fixed-point model | Paired theoretical control/policy equilibrium | Not an empirical NYC equilibrium or live forecast |
| Policy holdout | Conditional value under one declared simulator/budget | Not a guaranteed return |

**Talk track:**

> The public-data layer produces a reproducible zone-time panel, provenance, and diagnostics. A
> pinned Central Park join adds descriptive weather association. The ACS layer allocates household-
> income bins across area overlap but describes neighborhoods, not riders or drivers. The complete
> January permit snapshot contains 6,007 rows/951 source IDs, but permits do not measure attendance:
> the raw high-intensity-day contrast is +3.055%, every weekend is high-intensity, and the weekday-
> only contrast is -8.198%. Those are confounding diagnostics, not causal effects. Causal method
> validation happens against known simulator truth. I use NYC in two carefully bounded causal-
> method checks: descriptive initialization and fixed pre-treatment OD geometry. The latter does
> not estimate spillover strength. I also solve a theoretical fixed point, but its parameters were
> not fitted to NYC. The decision layer remains a conditional projection, not a promise of lift.

**Evidence footer:** “Descriptive association ≠ semi-synthetic recovery ≠ theoretical fixed point ≠ live forecast.”

**Transition:** “The simulator is designed to make the marketplace failure modes testable.”

## Slide 4 — A deterministic marketplace with paired potential paths

**Time:** 3:00–4:15  
**Headline:** “Make spillovers, persistence, and budgets parameters—not footnotes.”

**Visual:** Compact system diagram:

```text
rider demand + driver supply
        ↓
matching / capacity / wait
        ↓
trips, spend, platform and welfare outcomes
        ↘
zone substitution + driver movement + carryover
```

**On slide:**

- Zones × time, rider and driver treatment channels
- Matching/congestion, movement, substitution
- Spillover and persistence sensitivity
- Paired counterfactual paths with common random numbers
- Deterministic seeds and typed configuration

**Talk track:**

> The semi-synthetic environment is deliberately small enough for a laptop but rich enough to break an ordinary A/B interpretation. Treatment affects demand or supply, capacity limits completed matches, drivers and riders can move, and treatment can spill into neighboring zones or persist. I compute ground truth from paired counterfactual policy paths under common latent shocks. Reusing the same seed reproduces the same market; the estimator never receives the truth.

**Limitation sentence:** “Calibration improves plausibility, but assumed treatment-response parameters remain assumptions.”

**Transition:** “With truth available, I can compare experimental strategies on the same target.”

## Slide 5 — Compare designs and estimators on a common causal target

**Time:** 4:15–5:35  
**Headline:** “More rows do not mean more independent experimental information.”

**Visual:** A small design matrix.

| Design | Decision strength | Principal threat |
|---|---|---|
| Individual | Direct response | Shared-market contamination |
| Geographic cluster | Market-total effect | Boundary leakage / few clusters |
| Time block | Short-run effect | Time shocks / carryover |
| Switchback | Within-market efficiency | Inadequate washout |
| Geo × time | Flexible spatial-temporal contrast | Complex support and inference |

**On slide footer:** Difference in means → regression adjustment → cluster-aware inference → design-specific extensions.

**Talk track:**

> I benchmark transparent estimators before causal machine learning. The unadjusted randomized contrast shows what the design alone learns. Regression adjustment can improve precision with pre-treatment features. Cluster-aware or randomization-based uncertainty respects the actual assignment. Difference in differences, doubly robust methods, or synthetic-control-style comparisons are useful only when their additional assumptions fit the design. No estimator fixes an exposure map that omits the real spillover channel.

**Transition:** “The benchmark asks not which estimate looks best, but which one recovers known truth.”

## Slide 6 — Benchmark against truth, not against a preferred story

**Time:** 5:35–7:05  
**Headline:** “The full grid withholds a winner; exact scenarios can support conditional choices.”

**Preferred visual after generation:** Four aligned panels by design and estimator:

- bias around zero;
- RMSE;
- interval coverage with nominal reference line; and
- power or information cost.

Facet or annotate by spillover and persistence scenario. Include the target estimand, replication count, and “semi-synthetic causal benchmark” in the chart subtitle.

**Generated result card:**

- Target: fixed-horizon `market_total_effect`.
- Full declared sensitivity grid: no robust design-estimator winner.
- Exact opening preset: 16 zones, eight clusters, no interference or persistence.
- Conditional selection: time-block plus doubly robust estimation, 24 replications.
- Bias -0.00005; RMSE 0.00249; coverage and power 1.00, each with Jeffreys Monte Carlo SD 0.0275.

**Talk track:**

> The platform generated replication-level estimates and matched truths, then applied the same
> identification, inference, coverage, applicability, and completeness gates to every candidate.
> No pair passes the full declared sensitivity grid, so I do not claim a universal winner. For the exact
> no-interference opening preset, time-block assignment with doubly robust estimation is the
> conditional choice. Its strong recovery metrics are simulator findings for that cell, not live
> treatment effects and not evidence for the unmatched declared scenarios.

**Transition:** “Estimation is only useful if it changes how the budget is allocated.”

## Slide 7 — Learn the policy on one sample; decide on another

**Time:** 7:05–8:20  
**Headline:** “Every policy competes under the same budget on an honest holdout.”

**Visual after generation:** Bar chart of expected incremental outcome for five policies with a second encoding or companion table for spend, efficiency, and instability.

**On slide:**

1. No treatment
2. Random
3. Uniform
4. Simple rule
5. Stability-penalized model

**Talk track:**

> A treatment-effect model is not yet a policy. I train on one set of semi-synthetic markets, freeze the allocation, enforce the budget, and score it on disjoint holdout seeds. The model has to beat random, uniform, and a simple baseline. Multiple fits expose unstable rankings, and I penalize that instability before allocation. If the model's advantage is within uncertainty or disappears under modest scenario changes, I ship the simpler rule—or no treatment.

**Generated result:** Under the shared $1,000 cap and eight disjoint holdout seeds, uniform
allocation generates 68.4967 mean incremental trips per modeled market (SE 0.1050; p10 68.1030).
The stability-penalized model underperforms random, and the HTE learner fails the oracle-constant
recovery gate. The honest recommendation is the simpler uniform policy for this simulator—not a
live targeting claim.

**Transition:** “That produces a recommendation with explicit conditions, not a universal answer.”

## Slide 8 — Recommendation, failure modes, and next experiment

**Time:** 8:20–10:00  
**Headline:** “Randomize the market when the decision is about the market.”

**Visual:** Conditional decision tree.

```text
Material cross-unit spillovers?
├─ No / direct-response target -> individual assignment can be appropriate
└─ Yes / market-total target
   ├─ enough weakly connected markets -> parallel geographic clusters
   └─ scarce geography + reversible treatment
      ├─ washout supported -> geo-time / switchback
      └─ persistent effect -> parallel clusters or longer blocks
```

**On slide:**

- Primary: market-level rollout policy effect and incremental value per dollar; assignment ITT is a separate contrast unless assumptions align them
- Estimator: design-aligned, cluster-aware; report transparent baseline
- Launch: practical threshold + uncertainty + guardrails + robustness
- Allocate: honest holdout; simplest stable budget-feasible rule

**Talk track:**

> My conditional recommendation is to randomize connected geographies when spillovers matter. If persistent effects are likely, keep markets in one arm; if treatment is reversible and a practical washout is supported, a geo-time switchback can use scarce markets more efficiently. Keep the assignment ITT separate from the market-level rollout policy contrast unless exposure and history assumptions align them, use assignment-level uncertainty, and decide on incremental value per dollar with service, driver, geographic, and spend guardrails.
>
> The biggest risks are boundary leakage, carryover, too few clusters, treatment-version drift, incomplete welfare accounting, and assuming a Chicago-calibrated simulation transports to a live platform. The next step with platform access is a flow-based cluster and persistence pilot, followed by a pre-registered live design. The work demonstrates the point I care about most: causal inference is not selecting the fanciest estimator—it is aligning the decision, estimand, design, data, and uncertainty.

**Final line:** “A clean estimate of the wrong marketplace contrast is still the wrong decision.”

## Optional appendix slides for Q&A

### A. Estimand registry

Show direct, total, spillover, short-run, cumulative, ITT, complier, and efficiency effects with one-line identification conditions.

### B. Exposure maps

Compare adjacency, distance-decay, and pre-treatment-flow mappings. Explain that material sensitivity across maps is identification uncertainty.

### C. Estimator assumptions

Map difference in means, regression adjustment, cluster-robust inference, DiD, doubly robust, and synthetic-control-style methods to their assumptions and failure modes.

### D. Data provenance

Show source/query, checksum, schema, timezone normalization, row reconciliation, panel grain, missingness, suppression, and rounding diagnostics. All counts must come from the manifest.

### E. Policy mechanics

Show training/holdout seed separation, budget enforcement, instability penalty, and why independently summing unit-level effects can fail under jointly modeled spillovers and congestion.

### F. NYC, context, and equilibrium scopes

Show the six distinct evidence labels: NYC-informed known truth, known truth on fixed NYC OD
geometry, theoretical fixed point, descriptive NOAA association, ecological ACS neighborhood
composition, and descriptive permitted-event/calendar association. State one prohibited claim
for each. For income, show that unsupported/non-residential-dominant zones remain unclassified;
for events, pair +3.055% raw with -8.198% weekdays and the all-eight-weekends confounding flag.

## Likely Q&A and concise answers

### “Why not use causal forests from the start?”

Because flexible heterogeneity cannot repair the wrong estimand, contaminated controls, or invalid uncertainty. I first require a transparent design-based benchmark; a forest has to improve honest policy value rather than just in-sample fit.

### “Can the public data identify elasticity?”

Not by itself. Fare responds to distance, product mix, demand, congestion, and supply tightness. I treat those relationships as descriptive unless a randomized or otherwise credible exogenous price shift is available.

### “Do NYC OD flows identify spillovers?”

No. They provide a pre-treatment candidate exposure geometry. The known-truth benchmark declares
spillover strength in its synthetic DGP and checks controlled exposure recovery; a live spillover
magnitude still requires identified variation and a defensible mapping.

### “Is the fixed-point result an NYC equilibrium estimate?”

No. It is a theoretical counterfactual inside explicit equations with convergence and residual
diagnostics. The parameters were not structurally estimated from NYC.

### “How do you choose washout?”

From the target persistence horizon, lag/transition diagnostics, and sensitivity/power simulation. If credible persistence exceeds an operational washout, I would not use a short switchback for that target.

### “What if there are only a few markets?”

I would emphasize randomization inference and small-sample uncertainty, consider matched geo-time sequences if reversibility is credible, and acknowledge that no estimator creates independent clusters we do not have.

### “Does the simulator prove the experiment will work?”

No. It proves whether methods recover a known effect under declared scenarios. Live magnitude and transport require platform data and randomized validation.

### “What result would make you choose no treatment?”

Failure to clear the practical value threshold after uncertainty, any unacceptable guardrail breach, instability across credible exposure/persistence assumptions, or no holdout advantage over budget-matched baselines.

## Delivery checklist

- [ ] Practice to 9:30, leaving 30 seconds for pacing variation.
- [ ] Name the estimand by Slide 2.
- [ ] Say “association” for the public panel and “semi-synthetic causal” for simulator results.
- [ ] Call weather descriptive, ACS labels ecological areas, permits non-attendance calendar
      proxies, OD weights geometry, and equilibrium theoretical.
- [ ] Use only generated values and show scenario/replication metadata.
- [ ] State one identification failure on every result slide.
- [ ] Do not let architecture detail crowd out the product decision.
- [ ] End with the conditional recommendation and the next live-data step.
