# Sample Policy Brief

The versioned sample below remains synthetic acceptance evidence. Separate scoped official-
archive briefs are generated at
`data/generated/official_pilot/policy_briefs/{PAYEMS,CPILFESL,GDPC1}_official_policy_brief.md`.

> **Synthetic fixture demonstration.** All dates, releases, observations, forecasts, metrics, and model rankings below validate software behavior only. They are not empirical findings about the U.S. economy.

**Release:** Synthetic consumer sentiment initial release

**Release time:** 2024-12-15T15:00:00+00:00

**Target:** payems_change_mom_thousands

**Horizon:** 0

**Data mode:** vintage_aware

**Attribution:** exact

## What changed

The fixed model's nowcast moved from **163.224** to **161.374** thousand jobs, a revision of **-1.850**. The displayed interval is **[129.291, 205.024]**. This is a simulated information update, not a report about a real release.

## Contribution to the update

- `umcsent_change`: -1.850 thousand jobs (model units)
- `payems_change_lag1`: -0.000 thousand jobs (model units)
- `icsa_4w_mean`: 0.000 thousand jobs (model units)
- `ccsa_4w_mean`: -0.000 thousand jobs (model units)
- `unrate_level`: -0.000 thousand jobs (model units)
- `awhman_change`: -0.000 thousand jobs (model units)
- `indpro_pct_change`: 0.000 thousand jobs (model units)
- `rsafs_pct_change`: 0.000 thousand jobs (model units)
- `houst_log_change`: 0.000 thousand jobs (model units)
- `dgs10_20d_mean`: -0.000 thousand jobs (model units)

The contribution accounting is labeled **exact**. An exact label means a frozen linear model was scored before and after the release and its feature contributions sum to the prediction change within numerical tolerance. It does not imply causal identification.

## Assessment and uncertainty

The synthetic update demonstrates whether the release moved the configured employment signal up or down and by how much inside this fitted model. Sampling error, model instability, target revisions, missing predictors, and the deliberately artificial data-generating process limit interpretation.

## Historical context

No real historical analogue is asserted. Fixture-derived percentiles or episodes are not evidence about past U.S. business cycles.

## What would change the conclusion

- A subsequent release that materially reverses the changed input.
- A target revision large enough to alter the training relationship.
- A wider real-time sample in which the update is not stable across forecast origins.
- A genuine-vintage replication using data with documented usage permission and verified release timing.

## Risks to interpretation

This brief describes model arithmetic, not a causal policy shock. It does not predict monetary-policy or investment decisions. Date-only source releases require an explicit timing convention; this fixture uses exact synthetic timestamps.
