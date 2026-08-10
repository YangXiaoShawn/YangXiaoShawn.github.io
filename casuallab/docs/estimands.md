# Estimand registry

This document is the causal contract for Causal Marketplace Lab. An estimator is not considered valid merely because it runs: it must be paired with one of the targets below, the randomization that identifies that target, and the assumptions that connect observed outcomes to potential outcomes.

## Evidence labels used throughout the project

Every table, chart, and statement should carry one of these labels.

| Label | What it can support | What it cannot support |
|---|---|---|
| **Empirical association** | Descriptive facts and calibration moments computed from public trip records | A causal price elasticity, treatment effect, or welfare claim |
| **Semi-synthetic causal result** | Recovery of a causal quantity defined by the simulator, whose data-generating process and ground truth are known | A claim that the same magnitude will occur in a live marketplace |
| **Decision projection** | A scenario calculation conditional on stated effect, cost, and market assumptions | An unconditional forecast or guaranteed return |
| **Pending / not generated** | A pre-specified output that will be populated by a reproducible run | Any numerical conclusion |

Public trip data in this project are observational. Prices, supply, demand, location, and time are jointly determined, so a regression of trips on fare is an empirical association unless a separate, credible source of exogenous price variation is supplied.

## Units, treatments, and exposure

Let $i$ index a rider opportunity or trip request, $z$ a geographic market, and $t$ a time block. The implementation may aggregate outcomes to zone-time cells, but the target population and weights must still be stated.

- $Z_i$ or $Z_{zt}$: randomized assignment.
- $D_i$ or $D_{zt}$: treatment received, such as a redeemed rider offer or a delivered driver incentive.
- $A_{zt}$: assigned treatment intensity or saturation in market $z,t$.
- $E_{zt}$: a pre-specified exposure mapping for contemporaneous treatment in connected markets, for example a weighted share of treated neighbors.
- $H_{zt}$: treatment history relevant for carryover, including recent assignments and washout time.
- $Y_{zt}$: a market outcome such as completed trips, served-request rate, wait time, or welfare.
- $C_{zt}$: incremental platform spend attributable to the policy.

A useful potential-outcome representation is

\[
Y_{zt}(a,e,h),
\]

which permits an area's result to depend on its own treatment, neighboring exposure, and treatment history. Writing only $Y(1)$ and $Y(0)$ silently imposes no interference and no carryover; those assumptions are inappropriate defaults for a two-sided marketplace.

The exposure mapping is part of the estimand, not a nuisance modeling choice. Distance, origin-destination flow, and adjacency mappings answer different questions and can produce different exposure contrasts.

## Primary estimands

### 1. Individual controlled direct effect

At fixed spillover exposure $e$ and history $h$,

\[
\tau_{\mathrm{direct}}(e,h)
=
\mathbb{E}\left[Y_i(1,e,h)-Y_i(0,e,h)\right].
\]

This asks what assignment changes for an individual while the surrounding market exposure is held fixed. It is useful for offer response or mechanism diagnosis, but it is not generally the marketplace-wide effect of launching the offer.

Identification requires randomized own assignment within the relevant exposure and history strata, consistency, non-differential outcome measurement, positivity for both assignments, and a correct exposure mapping. Ordinary individual randomization identifies the direct effect only under no interference or under an analysis that explicitly conditions on randomized exposure. It does not identify the system-wide rollout effect when riders or drivers move between treated and untreated markets.

The current simulator is aggregated to zone-time cells and does not represent individual rider outcomes, so it deliberately reports this individual direct-effect truth as unavailable. Its separate `controlled_zone_direct_effect` is a market-cell contrast: treating the focal zone at the configured saturation versus controlling that zone while mapped neighbors are held at zero. That aggregate contrast must not be relabeled as an individual direct effect.

### 2. Market-level total effect

For two market policies $g_1$ and $g_0$ over a fixed set of $N_{\mathcal M}$ zone-time cells, define the primary average-per-cell target

\[
\tau_{\mathrm{total}}(g_1,g_0)
=
\mathbb{E}\left[
\frac{1}{N_{\mathcal M}}
\sum_{z,t\in\mathcal{M}}
\left\{Y_{zt}\{g_1\}-Y_{zt}\{g_0\}\right\}
\right].
\]

This includes the specified direct responses, cross-side responses, geographic substitution, congestion, and spillover pathways inside the stated market boundary $\mathcal{M}$. It is the default decision estimand for a marketplace rollout. The current simulator is a reduced-form forward market-system model, not a solved strategic or market-clearing equilibrium.

The simulator's canonical `market_total_effect` uses the feasible all-zone treatment policy versus all-zero and averages over every cell in the fixed configured horizon, independent of assignment-specific washout exclusions. `cumulative_effect` is the corresponding full-horizon sum. An additional analysis-population diagnostic may restrict the same contrast to assignment-specific eligible rows, but it is not used to rank designs with different exclusion masks.

Identification is most credible when whole markets or sufficiently separated geographic clusters are randomized, treatment policies are well defined, cross-cluster exposure is negligible or measured by design, and outcomes are observed for the complete affected market and horizon. It fails when treatment moves activity across an unobserved boundary, when clusters interact strongly, or when the analysis counts gains in treated cells but omits offsetting losses elsewhere.

### 3. Spillover effect

For untreated units, a simple exposure contrast is

\[
\tau_{\mathrm{spill}}(e_1,e_0;h)
=
\mathbb{E}\left[Y_i(0,e_1,h)-Y_i(0,e_0,h)\right].
\]

The sign is not known in advance. Neighboring treatment may create positive network effects, pull riders or drivers away, or increase congestion.

Identification requires exogenous variation in exposure among units with the same own assignment. A two-stage or saturation design is a direct route. Geographic randomization can also be informative when boundary exposure is measured and the allocation generates overlap. A post hoc comparison of units near and far from treated zones is not automatically causal because boundary location and market connectedness are not random.

The implemented `two_stage_saturation_assignment` first randomizes geographic clusters to
predeclared saturation arms and then randomizes opportunities within zone-time cells at the
assigned saturation. `add_mapped_exposures` computes normalized neighbor treatment from a
pre-treatment edge-weight table and uses exact time-key joins for lagged exposure. The companion
`estimate_exposure_response` jointly estimates own, neighbor, and optional history slopes with
randomization-cluster-aware uncertainty. Its own and neighbor coefficients target controlled
exposure-response contrasts; the history coefficient is labeled
`controlled_history_exposure_response`. None is silently promoted to the feasible all-zone
`market_total_effect`.

### 4. Short-run effect

For a pre-specified immediate horizon $h=0$,

\[
\tau_{0}=\mathbb{E}\left[Y_{zt}(1,E_{zt},H_{zt})-Y_{zt}(0,E_{zt},H_{zt})\right].
\]

This is appropriate for an acute operational response, such as completed trips during the assigned block. It is identified by contemporaneous randomized contrasts only if anticipation and carryover from earlier blocks are absent or controlled by design. A short switchback block with inadequate washout can mix the short-run response with residual treatment.

### 5. Persistent or cumulative effect

For horizon $K$ and optional discount factor $\delta$,

\[
\tau_{\mathrm{cum}}(K)
=
\mathbb{E}\left[
\sum_{k=0}^{K}\delta^k
\left\{Y_{z,t+k}(\mathbf{1})-Y_{z,t+k}(\mathbf{0})\right\}
\right].
\]

The assignment path, horizon, and treatment cessation rule must be part of the definition. This estimand captures delayed demand, driver repositioning, learning, and decay after treatment.

Identification requires randomized treatment histories with adequate support, an observation window that covers $K$, no unmeasured exposure outside the history mapping, and a stable outcome definition over time. It is not identified by treating post-period observations as independent replicates. Long persistence relative to the washout period invalidates a naive switchback analysis.

### 6. Intent-to-treat effect

For randomized assignment $Z$,

\[
\tau_{\mathrm{ITT}}
=
\mathbb{E}[Y\mid Z=1]-\mathbb{E}[Y\mid Z=0],
\]

with the aggregation level, exposure condition, and horizon stated. ITT is the preferred operational effect because assignment is controlled by the platform even when treatment is not redeemed or fully delivered.

Identification follows from the actual randomization protocol, consistency, correct analysis of the randomized unit, and complete or appropriately handled outcomes. Noncompliance does not invalidate ITT, but interference changes which ITT is being estimated. Standard errors must respect the assignment and repeated-measure structure.

In the simulator, this randomized-arm ITT is available only for an unconstrained binary design with no cross-zone interference, rider substitution, driver movement, or persistence. It is reported as unavailable—not silently substituted with a full-policy structural contrast—when aggregate individual saturation, a shared budget, interference, or carryover changes the target.

### 7. Treatment-on-the-treated / complier effect

When assignment $Z$ changes actual receipt $D$, a complier average causal effect can be written as

\[
\tau_{\mathrm{CACE}}
=
\frac{\mathbb{E}[Y\mid Z=1]-\mathbb{E}[Y\mid Z=0]}
{\mathbb{E}[D\mid Z=1]-\mathbb{E}[D\mid Z=0]}.
\]

The ratio is meaningful only when the first stage is nonzero and assignment satisfies relevance, independence, exclusion, and monotonicity. In a marketplace, exclusion is especially fragile: merely making an offer available can affect search, expectations, or equilibrium conditions even without redemption. Comparing recipients with nonrecipients is not a treatment-on-the-treated estimate because receipt is selected. The project should report this estimand only when receipt is explicitly simulated or credibly measured and the instrument assumptions are defended.

### 8. Incremental trips per dollar spent

For policy $g$ relative to no treatment $g_0$,

\[
\eta_{\mathrm{trips}}(g)
=
\frac{
\mathbb{E}[\sum Y_{zt}\{g\}-\sum Y_{zt}\{g_0\}]
}{
\mathbb{E}[\sum C_{zt}\{g\}-\sum C_{zt}\{g_0\}]
}.
\]

This is a ratio of policy-level incremental totals, not an average of cell-level ratios. Its numerator should use incremental completed trips, not gross treated trips. Its denominator must include all incremental incentive or discount expense and any pre-specified delivery costs. The ratio is undefined or operationally unhelpful when incremental spend is zero or when the denominator is weakly estimated; numerator and denominator uncertainty should be propagated jointly.

### 9. Incremental welfare per dollar

For a declared welfare measure $W$,

\[
\eta_{W}(g)
=
\frac{\mathbb{E}[W\{g\}-W\{g_0\}]}{\mathbb{E}[C\{g\}-C\{g_0\}]}.
\]

The welfare ledger should state which components are included: rider surplus, driver earnings net of effort and repositioning costs, platform margin, wait-time or congestion costs, and externalities. Trip records alone do not identify consumer surplus, driver opportunity cost, or full welfare. Therefore empirical welfare claims require additional price variation or structural assumptions; simulator welfare is a semi-synthetic causal quantity conditional on its behavioral model.

## Supporting decision estimands

### Heterogeneous treatment effects

A conditional effect such as

\[
\tau(x)=\mathbb{E}[Y(1)-Y(0)\mid X=x]
\]

must use pre-treatment $X$. Candidate modifiers include baseline demand, market tightness, time of day, weather, neighborhood characteristics, and event intensity. Exploratory subgroup estimates should be labeled exploratory, adjusted for multiplicity where used for claims, and validated on held-out simulations. A predictive association between $X$ and outcomes is not evidence that targeting on $X$ improves causal policy value.

### Policy value under a budget

For allocation rule $\pi(x)\in[0,1]$ and budget $B$,

\[
V(\pi)=\mathbb{E}[Y\{\pi(X)\}],
\qquad
\mathbb{E}[C\{\pi(X)\}]\le B.
\]

Evaluate $V(\pi)$ on independent simulation seeds or an honest holdout set and compare it with no treatment, random allocation, uniform allocation, and a simple rule. Training and evaluating on the same simulated markets overstates policy value. The policy must be evaluated through the full modeled market system: independently summing unit-level effects can violate the budget and ignore interference. This joint forward evaluation should not be described as a solved equilibrium.

## Mapping designs to targets

| Design | Most defensible primary target | Main identification condition | Important failure mode |
|---|---|---|---|
| Individual randomization | Direct ITT at the realized market saturation | Interference absent, fixed, or randomized and modeled | Control units are exposed through the same market; total effect is not learned |
| Two-stage saturation | Controlled own- and neighbor-exposure response | Cluster saturation and within-cluster assignment are randomized; exposure map is pre-specified | Saturation arms have weak overlap, or the mapped network omits important interference |
| Geographic cluster | Market or cluster total ITT | Clusters contain the relevant spillovers, or exposure is measured | Drivers, riders, or trips cross cluster boundaries |
| Time-block randomization | Short-run market ITT | No anticipation; limited carryover | Persistence aliases treatment histories with current assignment |
| Switchback | Short-run policy contrast | Randomized sequence, adequate washout, valid time adjustment | Time trends, learning, and carryover contaminate alternating blocks |
| Geo × time clustered | Market-time total effect or exposure-specific effect | Assignment probabilities known; spatial and temporal dependence respected | Too few effective clusters or unsupported exposure histories |

The analysis must follow the randomization. For example, individual observations do not create individual-level independent information when assignment occurred by geographic cluster.

## Outcome, aggregation, and weighting rules

1. Pre-specify one primary marketplace outcome. Completed trips is transparent for the vertical slice; served-request rate or a balanced marketplace metric is preferable when request and supply data are available.
2. Report guardrails separately, including wait time, driver utilization or earnings, cancellation or service rate, geographic distribution, and spend. A trip lift purchased through unacceptable service degradation is not success.
3. State whether the target weights zones equally, weights zone-time opportunity equally, or targets total marketplace volume. Trip-weighted analysis answers a different question from a market-weighted policy effect.
4. Use the ratio of aggregate incremental outcomes to aggregate incremental cost for efficiency.
5. Do not treat privacy-suppressed counts, rounded fares, or rounded timestamps as exact. Run sensitivity analyses at coarser aggregation when rounding is material.

## Pre-analysis estimand card

Before a benchmark or live experiment is interpreted, record:

- decision and target population;
- assignment unit and assignment probabilities;
- treatment version, intensity, and delivery rule;
- outcome, aggregation, weights, and horizon;
- spatial exposure mapping and market boundary;
- carryover history and washout rule;
- primary estimand from this registry;
- estimator and uncertainty procedure;
- missing-data and attrition handling;
- cost and welfare definitions;
- interference, persistence, and noncompliance assumptions;
- planned falsification and sensitivity analyses.

Changing one of these fields after inspecting outcomes changes the question. Any such change should be logged and labeled exploratory.

## Generated versus pending quantities

The offline vertical slice now code-generates empirical descriptive moments, calibration targets/achieved control moments, and simulator ground-truth values. Their presence does not broaden their evidence label: fixture facts remain descriptive and simulator truth remains semi-synthetic.

The verified reproduction now code-generates the following benchmark and decision quantities;
they must still never be filled by hand:

- estimator bias, variance, RMSE, interval coverage, and power;
- policy value, incremental trips, spend, and efficiency;
- Monte Carlo standard errors and number of replications.

Current values live in the hashed artifact bundle. Missing cells remain unavailable rather than
zero, and the lack of a full-grid recommendation is an explicit gate result—not evidence of no
treatment effect.
