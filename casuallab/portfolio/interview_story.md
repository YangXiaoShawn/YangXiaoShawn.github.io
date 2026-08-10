# Interview story: building a causal marketplace lab

## One-sentence positioning

I built a reproducible way to decide not only whether a marketplace incentive “works,” but whether the experiment identifies the rollout effect when riders and drivers spill across geography and time—and how to allocate a fixed budget without evaluating a policy on its training data.

## 90-second version

> The motivating problem was a ride-hailing marketplace considering rider discounts or driver incentives. A normal individual A/B test is tempting, but treated and control users share drivers, congestion, and geography. That means the test can estimate a direct response while missing the system-wide rollout effect the business actually cares about.
>
> I organized the project around an estimand-first evidence hierarchy. Public trip data provide descriptive demand, flow, and calibration moments, but I explicitly do not call fare-demand correlations causal. I then built a deterministic semi-synthetic marketplace where rider demand, driver supply, matching, spillovers, persistence, and budgets are configurable and causal ground truth is available from paired counterfactual paths.
>
> I added six deliberately separate extensions: NYC-informed simulator recovery, known-truth
> exposure recovery on fixed NYC OD geometry, a theoretical fixed-point equilibrium, and
> descriptive NOAA weather, ACS neighborhood-income, and NYC permitted-event joins. The first
> two do not estimate NYC effects, OD weights are not spillover strength, and the equilibrium
> parameters are not fitted to NYC. Weather is a citywide proxy, ACS labels are ecological rather
> than individual income, and permits are not attendance; none of those contextual contrasts is
> causal.
>
> On that common environment, the platform can compare individual, geographic, time-based, switchback, and geo-by-time designs with transparent estimators before adding more flexible methods. It reports bias, RMSE, coverage, power, and information cost against known truth. The allocation layer compares no treatment, random, uniform, rule-based, and model-based policies on unseen simulation draws under the same budget, with an instability penalty.
>
> The generated result reinforces that conditionality: no design-estimator pair survives every
> declared scenario, so the robust rollout recommendation is withheld. The opening dashboard
> preset has an exact benchmark match and conditionally selects time-block assignment with doubly
> robust estimation, but it lists every unmatched declared scenario. Under the modeled $1,000 policy
> cap, uniform allocation beats the learned targeter on disjoint holdout seeds. The project shows
> scientific restraint as well as technical range: negative and withheld results are first-class
> outputs.

## Full STAR story

### Situation

A two-sided ride-hailing marketplace wants to spend a fixed budget on rider discounts or driver incentives. The apparent question—“Does treatment increase trips?”—hides several harder ones:

- A rider offer changes demand, but may also change matching, wait time, and driver behavior.
- A driver incentive can move supply from untreated to treated zones.
- Riders can substitute across zones or defer trips across time.
- Treatment can persist beyond a short experimental block.
- An individually randomized effect may not equal the effect of full-market rollout.

Public trip data show what happened, but price and demand are jointly determined. A naive fare-demand regression would give false causal confidence.

### Task

Create a laptop-safe, portfolio-quality vertical slice that a research, engineering, and product audience could all audit. It needed to:

1. turn public trip records into a reproducible zone-time panel;
2. preserve provenance, missingness, suppression, and rounding information;
3. expose causal ground truth through a configurable two-sided-market simulation;
4. compare design-estimator pairs under interference and persistence;
5. learn a budget-feasible targeting rule without holdout leakage; and
6. translate the results into a decision memo without fabricating numbers.

### Actions

#### 1. I defined the causal question before writing the benchmark

I wrote an estimand registry distinguishing direct, market-total, spillover, short-run, cumulative, ITT, complier, trips-per-dollar, and welfare-per-dollar effects. I represented potential outcomes as (Y(a,e,h)), where outcomes depend on own treatment, neighbor exposure, and history. This made no-interference and no-carryover assumptions visible rather than implicit.

The default rollout target is the market-total feasible-policy effect over a declared boundary and horizon. The assignment ITT is a separate contrast and represents that rollout effect only when exposure, history, delivery, and budget assumptions align. That choice determines the assignment unit, outcome aggregation, and uncertainty method.

#### 2. I separated empirical description from causal validation

The empirical layer uses an authentic, checksummed 300-row public Chicago TNP vertical slice for
the offline causal-research workflow, plus a separately pinned January 2024 NYC HVFHV object with
19.7 million published trips for full-month descriptive validation. The NYC build streams under a
16 GB laptop budget and produces complete zone-hour and OD-hour panels. Neither source contains a
randomized intervention: fare, supply, demand, and trip mix are jointly determined, so price,
flow, and one-hour persistence patterns remain explicitly noncausal.

A separately pinned NOAA Central Park join describes January weather/completed-trip associations.
It is one station used as a citywide proxy, not a causal weather effect or an instrument. The NYC
calibration and simulation-anchor chain borrows scale and heterogeneity while leaving behavioral
treatment responses as explicit assumptions.

I also built two independently manifested contextual joins. The neighborhood layer aggregates
the 2022 ACS five-year B19001 household-income distribution to NTAs, allocates all sixteen bins to
Taxi Zones using equal-area overlap, conserves every bin, and keeps unsupported/non-residential-
dominant zones unclassified. That is ecological area composition—not rider or driver income and
not an income effect. The event layer retains the complete January-overlap permit snapshot: 6,007
rows and 951 source event IDs. The raw high-intensity-day trip contrast is +3.055%, but every one
of the eight weekends is high-intensity and the weekday-only contrast is -8.198%. Permits do not
measure attendance, so the reversal is a confounding diagnostic rather than an event effect.

The pipeline contract includes source/query metadata, checksums, normalized geography and local time, partitioned outputs, and diagnostics for missingness, suppression, fare heaping, and timestamp rounding. Optional context sources are not allowed to fail silently or masquerade as observed zeros.

#### 3. I used paired potential market paths to define ground truth

The simulator makes rider demand, driver supply, matching capacity, geographic movement, spillover, temporal persistence, treatment intensity, and budget configurable. Identical seeds reproduce identical stochastic inputs. Ground truth is a policy contrast under common random numbers, not a number typed into a report.

This distinction matters: the simulator can validate an estimator internally, but its effect magnitude is still conditional on assumed response parameters. Calibration does not make it a structural estimate of a live platform.

I also split two questions that are easy to conflate. The NYC-informed benchmark asks whether the
marketplace design/estimator stack recovers known simulator truth after descriptive
initialization. The NYC graph benchmark asks whether two-stage saturation and a pre-treatment OD
exposure map recover controlled own, neighbor, and history effects. OD weights set relative graph
geometry; the synthetic DGP declares spillover strength, and controlled slopes remain distinct
from the market-total effect. A separate fixed-point solver is explicitly theoretical: it checks
paired equilibrium feedback and convergence inside equations whose parameters were not estimated
from NYC.

#### 4. I built a transparent method ladder

The design layer considers individual, geographic cluster, time block, switchback, and geo × time assignment. The estimator ladder starts with difference in means, regression adjustment, and cluster-aware inference before design-specific extensions such as difference in differences or doubly robust estimation.

For every benchmark row, the target estimand, design, estimator, truth, estimate, standard error, scenario, and seed are meant to remain traceable. The summary computes bias, variance, RMSE, coverage, power, and a documented information-cost measure from replication-level results.

#### 5. I made policy learning an out-of-sample decision problem

The policy layer fits on one set of semi-synthetic markets and scores frozen allocations on disjoint holdout seeds. It enforces the budget before evaluation and compares model-based targeting with no treatment, random, uniform, and a simple rule. Multiple model fits estimate instability, which is penalized before ranking candidate units. A separate paired sensitivity repeats that workflow for rider discounts, driver incentives, and the bundled intervention on common market seeds; it is labeled model-response sensitivity rather than an empirical comparison of treatments.

That design protects against two common portfolio mistakes: presenting in-sample uplift as policy value and letting a complex model avoid comparison with a strong simple baseline.

#### 6. I designed communication as part of the research system

The technical report, experiment memo, executive memo, limitations audit, and generated appendix
use explicit evidence labels. Machine-generated quantities come from checked artifacts and carry
reproducibility metadata; source narratives link to those artifacts rather than inventing an
illustrative result.

### Result

The defensible result is a research platform and decision procedure, not a claimed live treatment effect.

What the project can establish after a successful reproducible run:

- whether design-estimator pairs recover the configured market-total truth;
- how interference and persistence change bias, coverage, power, and design choice;
- whether controlled exposure effects are recovered on a fixed NYC OD geometry without treating
  the graph as a causal effect;
- whether a declared theoretical fixed-point model converges and how its within-model policy
  counterfactual changes;
- descriptive Central Park weather/completed-trip associations for the pinned NYC month;
- ecological ACS neighborhood-income and citywide permit-event associations for their pinned
  sources/window, with explicit exclusions and conservation checks;
- whether a holdout targeting policy improves on budget-matched simple baselines; and
- which limitations make the recommendation conditional.

What it cannot establish from the current source materials alone:

- a causal price elasticity from public trips;
- a causal weather effect from the Central Park join;
- individual rider/driver income or a causal income effect from the ACS area allocation;
- attendance, realized event exposure, or a causal event effect from permit records;
- spillover strength from NYC OD weights;
- an empirical NYC equilibrium or structurally estimated treatment response;
- a live-market incentive effect or return;
- that a Chicago-calibrated effect transports to NYC or another platform; or
- a universal winning design.

**Verified result card:**

- Automated verification covers the data, simulation, benchmark, lineage, and reporting contracts;
  current counts remain in generated manifests rather than this narrative.
- The empirical fixture contains 300 authentic 2022-01-01 Chicago TNP trips and produces 170
  occupied zone-hour cells; it is nonrepresentative and has no exact one-hour pairs.
- The NYC contextual audit preserves 6,007 January-overlap permit rows/951 source event IDs and
  shows why +3.055% raw versus -8.198% weekday-only permit-intensity contrasts cannot be causal;
  the income layer conserves the ACS B19001 household distribution and reports its classified-
  trip coverage rather than assigning unsupported/non-residential-dominant zones an income label.
- Each applicable benchmark cell uses the predeclared replication count. Across the declared
  sensitivity plan, the full-grid rule issues no robust design recommendation.
- The exact dashboard preset conditionally selects time-block plus doubly robust estimation:
  RMSE 0.00249, coverage 1.00 (Jeffreys Monte Carlo SD 0.0275), and power 1.00 under that modeled
  no-interference cell. Those values do not transport to scenarios excluded by the match.
- On eight holdout markets under a $1,000 modeled cap, uniform allocation has mean incremental
  trips 68.4967 (SE 0.1050; p10 68.1030); model targeting underperforms random.
- The HTE learner fails its recovery gate: RMSE 0.0417 versus a 0.0247 oracle constant baseline.

## The economic insight to emphasize

The important insight is not “clusters are always better.” It is that interference changes the target.

Suppose an individual offer attracts drivers into a treated rider's area. Untreated riders nearby may benefit from shorter waits, diluting the treated-control contrast even though the market improves. Or treated zones may pull drivers from control zones, exaggerating a local gain while total trips barely change. Both cases can make an individual A/B result a poor rollout statistic without making randomization itself defective.

The fix starts with the decision estimand: market-total outcome over a boundary large enough to include displacement. Then choose the randomization and exposure measurement that can identify it.

## The engineering insight to emphasize

Reproducibility is part of identification. A deterministic seed alone is insufficient. The platform also needs:

- a pinned input/query and checksum;
- typed and validated configuration;
- explicit timezone and geographic normalization;
- replication-level benchmark records;
- ground truth computed separately from the estimator;
- evidence labels embedded in outputs; and
- report numbers generated from machine-readable artifacts.

Without those pieces, it is easy to benchmark a different scenario than the one described or to copy a result into a memo after the code changes.

## A tradeoff I would discuss

Parallel geographic clusters are attractive for persistent market effects, but geographic clusters may be few and leaky. Switchbacks create more within-market contrasts, but every switch risks contamination if drivers reposition or riders wait for the next offer.

I would not decide this from nominal row counts. I would compare both under the same market-total estimand and budget, vary spillover and persistence across credible ranges, and assess bias, interval coverage, power, and operational feasibility. If the recommendation reverses under plausible persistence, I would either collect a persistence pilot, lengthen blocks/washout, or use parallel assignment.

## Questions an interviewer may ask

### “Why not just add fixed effects to the public data?”

Zone and time fixed effects remove stable zone differences and common time patterns. They do not remove time-varying supply tightness, event shocks, endogenous pricing, selection into completed trips, or simultaneity. Fixed effects can improve description, but they do not create exogenous price variation.

### “Why is the simulator semi-synthetic?”

Baseline market moments can be anchored to observed public data, while treatment responses and reduced-form market-system mechanisms are configured. Ground truth is known because the latter are generated. “Semi-synthetic” is a reminder that internal causal truth and external realism are different properties.

### “How do you know the exposure mapping is right?”

I do not assume one map is known. I would define adjacency-, distance-, and pre-treatment-flow-based mappings before examining outcomes, inspect support, and test sensitivity. If conclusions differ materially, that is identification uncertainty and should constrain the recommendation.

### “Why ITT instead of effect on people who redeem?”

Redemption is selected: people redeem when the trip, price, or need makes treatment attractive. ITT preserves randomization and estimates the effect of the policy the platform can assign. A complier effect needs a strong first stage plus exclusion and monotonicity, and exclusion is fragile when offer availability changes the market even without redemption.

### “What would make you stop the experiment?”

An operational or safety guardrail breach, assignment corruption, uncontrolled treatment-version change, severe budget-delivery failure, or data loss that prevents the primary outcome from being reconstructed. I would not use an unplanned peek at noisy lift as the default stopping rule.

### “Why penalize policy instability?”

Two models with similar predicted value can select very different markets. That is a warning that targeting depends on sample noise. Penalizing instability makes the rule more conservative and gives a transparent simple baseline a fair chance to win.

### “What would you do next with live platform access?”

I would replace broad calibration with platform request, supply, wait, dispatch, delivery, redemption, and cost logs; build flow-defined clusters; run a small persistence and contamination pilot; pre-register the estimand and decision threshold; then generate the design/power comparison using the target market's pre-period dependence.

## Honest language guide

Use:

- “The public panel shows an association.”
- “The semi-synthetic benchmark recovers known simulator truth.”
- “NYC OD weights supply pre-treatment exposure geometry, not spillover strength.”
- “The fixed-point result is theoretical, and the weather result is descriptive.”
- “The ACS labels describe areas, not people; the permit signal describes records, not attendance.”
- “The design recommendation is conditional on the scenario range.”
- “The live magnitude is unknown until a randomized experiment.”
- “The generated artifact withholds the claim because the evidence gate fails.”

Avoid:

- “We estimated the causal effect of price from public trips.”
- “Central Park weather caused the observed trip difference.”
- “High-income riders take more trips” from the ecological Taxi Zone comparison.
- “Events caused the raw permit-intensity difference” or “permit count measures attendance.”
- “The NYC graph estimated spillovers” or “the fixed point estimated NYC equilibrium.”
- “Simulation proves the treatment will work.”
- “The model found the best markets” without a holdout and budget-matched baselines.
- “There is no interference” based only on an imprecise test.
- Any effect size, confidence interval, or return not traceable to a generated output.
