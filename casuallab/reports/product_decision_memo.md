# Product decision memo: testing marketplace incentives without fooling ourselves

**For:** Marketplace leadership  
**Decision:** How to test and allocate rider discounts or driver incentives  
**Current status:** The reproducible benchmark and policy holdout are complete. They support no
universal design across the full scenario grid and no live expected-lift or return claim. A
scenario-conditional dashboard recommendation is available only for exact artifact matches.

**Generated executive output:** `artifacts/reports/product_decision_memo_generated.md`.

## How to read the NYC, equilibrium, and contextual layers

- The NYC-informed and NYC-graph benchmarks are **known-truth simulation checks**. One borrows
  descriptive initialization moments; the other borrows fixed OD geometry. Neither estimates an
  NYC incentive effect, and OD flow weight is not spillover strength.
- The equilibrium benchmark is **theoretical**. It demonstrates feedback inside declared
  fixed-point equations whose parameters were not fitted to NYC.
- The NOAA Central Park result is **descriptive**. It reports weather/completed-trip association
  for the pinned month, not a weather effect, treatment effect, or valid instrument.
- The ACS neighborhood result is **ecological and descriptive**. It uses the 2022 five-year
  B19001 household-income distribution and an equal-area Taxi Zone/NTA mapping. Supported zones
  are area categories, not the income of riders or drivers, and the contrast is not an income
  effect.
- The permitted-event result is **a citywide calendar proxy**. The complete January snapshot has
  6,007 permit rows/951 source IDs, but permits do not measure attendance. The raw high-versus-
  lower permit-intensity trip contrast is +3.055%; all eight weekends are high-intensity, and the
  weekday-only contrast is -8.198%. Neither number is an event effect.

These layers improve design discipline and failure-mode coverage. They do not supply a launch
lift, a city-specific return, or a substitute for randomized platform evidence.

## Recommendation

Randomize connected geographic markets, not isolated riders, when the goal is to learn whether an incentive improves the whole marketplace. Riders and drivers share supply: an offer to one group can change wait time, service, and behavior for everyone nearby. A normal rider-level A/B test can therefore measure the direct response while missing displacement or spillovers that determine rollout value.

Use one of two designs:

- **Parallel geographic test:** best when we can form enough weakly connected market clusters and expect effects to persist.
- **Geographic switchback:** use randomized treatment periods within markets only when the intervention is reversible and simulations show that a practical washout removes meaningful carryover.

Analyze everyone according to the market assignment they received, even when an offer was not redeemed. The primary success metric should be **market-level incremental completed trips or credible welfare per incremental dollar spent**, with service, driver, geographic, and budget guardrails.

Do not choose a rollout policy from point estimates alone. After the experiment, compare simple and model-based allocations under the same budget on an honest holdout, then prefer the simplest stable rule that creates decision-relevant value.

## The six product questions

### What should be randomized?

Randomize geographic clusters built from actual rider and driver connections, not administrative boundaries alone. If there are too few independent geographies, randomize treatment sequences across geography and time. Preserve a clear control condition and measure cross-boundary exposure.

Use individual randomization only when the question is explicitly, “Does an eligible person respond to the offer at this market saturation?” That is not the same as, “What happens if we launch across the market?”

### For how long?

Long enough to cover the important weekly and demand cycles, achieve power for the smallest effect that would change the decision, and observe the configured persistence horizon. A switchback also needs washout time long enough for driver location, delayed trips, and learning effects to decay.

There is no honest universal duration. Generated duration, persistence, and washout sensitivities
do not yield one design that passes the full-grid gate. A live duration must be chosen after the
target market's cluster count, pre-period variability, minimum useful effect, and carryover are
measured.

### What metric should determine success?

Primary metric:

> Incremental market-level completed trips, contribution, or welfare divided by total incremental incentive and delivery spend.

Use completed trips per dollar when a complete welfare ledger is unavailable. Do not call gross treated trips “incremental,” and do not exclude unused or cross-market program costs.

Guardrails should cover:

- wait time, service rate, and cancellation;
- driver earnings, utilization, and repositioning burden when measured;
- rider experience and cost;
- geographic distribution, especially service losses in neighboring areas;
- total and incremental spend; and
- operational delivery failures.

Agree in advance on the smallest benefit worth shipping and the largest downside we are unwilling to accept. Statistical significance by itself is not a product decision.

### Which estimator should be used?

Use a cluster-aware **intent-to-treat** estimate aligned with the randomization, with pre-treatment adjustment for precision and randomization-based or small-sample inference when clusters are few. Report the simple design-based difference beside any adjusted model.

Do not control away the mechanism. Realized price, offer redemption, wait time, and driver supply can be changed by treatment; adjusting for them can remove part of the total effect we want to measure.

### What could make the result misleading?

- Treated zones pull riders or drivers from control zones.
- Effects last into later control periods.
- The measured market boundary excludes the source of displaced trips.
- Too few randomized markets make confidence intervals unreliable.
- Budget caps change who actually receives treatment.
- Pricing, dispatch, marketing, events, or outages coincide with treatment.
- The offer or eligibility rule changes during the test.
- A Chicago scale-anchored simulation is treated as if it were a representative live-market forecast.
- A fare-demand correlation in public data is called causal.
- A Central Park weather association is called a causal weather effect or used as an instrument.
- An ACS area label is called a rider's or driver's income, or its completed-trip contrast is
  called an income effect.
- A permit count is called attendance or realized event exposure; the weekend-confounded raw
  contrast is called an event effect.
- NYC OD weight is called an estimated spillover effect.
- A theoretical fixed point is called an empirically estimated NYC equilibrium.
- A targeting model is evaluated on the same scenarios used to train it.

The experiment log should record assignment, delivery, receipt, cost, policy version, neighboring exposure, and operational overrides separately.

### How should treatment be allocated after the experiment?

Compare five policies under exactly the same budget:

1. no treatment;
2. random allocation;
3. uniform allocation;
4. a simple pre-specified rule based on baseline market conditions; and
5. model-based targeting using only information available before treatment.

Evaluate all five on unseen simulation seeds or a genuine holdout. Score incremental outcome, spend, efficiency, guardrails, and stability when spillover, persistence, and cost assumptions change. Use the model-based policy only if it clearly improves on the simple rule after uncertainty and instability are considered. Keep an exploration/control share if effects may drift after launch.

In the verified semi-synthetic holdout it does not: uniform allocation wins the predeclared
conservative rule, and model-based targeting underperforms random allocation.

## Proposed decision gates

| Gate | Evidence required | Current status |
|---|---|---|
| Design | Benchmark shows acceptable bias, uncertainty, and coverage across credible interference/persistence scenarios | Withheld across the full declared grid; conditional matches only |
| Duration | Power for the minimum decision-relevant effect and adequate persistence horizon | Sensitivity generated; live operational choice unresolved |
| Measurement | Assignment, delivery, cost, outcome, and exposure logging pass audit | Pending operational validation |
| Launch | Practical benefit clears threshold; downside is bounded; guardrails pass | No live estimate available |
| Allocation | Holdout policy beats budget-matched simple baselines and remains stable | Uniform wins the configured $1,000 semi-synthetic holdout; not a live rollout rule |

## What leadership can decide now

- Approve market-level total effect as the primary rollout question.
- Require geography-aware randomization and exposure logging.
- Require duration and washout to be justified by power and persistence analysis.
- Define the cost ledger, primary marketplace outcome, guardrails, and minimum useful effect.
- Reserve a holdout for policy evaluation.

## What leadership should not decide yet

- an exact experiment duration or washout;
- a numerical expected lift, confidence interval, or return;
- the final geographic versus switchback design;
- which zones should receive treatment after launch; or
- that simulated effect sizes transport to a live marketplace;
- that OD connectivity identifies spillover magnitude; or
- that a theoretical equilibrium or descriptive weather, income-area, or permit-event contrast
  predicts live response.

The artifacts resolve what the configured simulator says, including a negative HTE result and a
withheld robust design recommendation. The remaining decisions depend on operational inputs and
live randomized evidence, not on another reading of the same simulator output.
