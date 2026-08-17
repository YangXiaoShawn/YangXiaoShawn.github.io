# AGENTS.md — persistent instructions for anyone (human or agent) working in this repository

Read this before changing anything.

## What this project is

A research system measuring how U.S. product-level tariffs affect import prices,
landed costs, quantities, sourcing countries, supplier concentration, domestic
producer prices and downstream industries. The historical setting is the
2018–2019 U.S. Section 301 actions against China.

## Non-negotiable rules

1. **Never fabricate a tariff rate, treatment date, trade value, elasticity or
   welfare number.** If a value is not in a source document or a dataset, it does
   not go in the repository. This includes "reasonable" placeholders.
2. **Never silently fill a null.** A missing MFN baseline is not zero. A missing
   month is not a zero trade flow. If a fill is genuinely required, add an
   explicit `*_imputed` flag column and record it in the manifest.
3. **Never call a customs unit value a price.** It is value divided by quantity
   over a heterogeneous bundle. Use the column names in
   `data/DATA_DICTIONARY.md` verbatim.
4. **Announcement dates and effective dates are different facts.** Never use one
   where the other belongs. Both are carried through the whole pipeline.
5. **Never net protection against input-cost exposure.** Report the two channels
   separately. An industry can be strongly exposed on both sides.
6. **Never present a structural counterfactual as observed evidence.** Model
   output is labelled model-implied everywhere it appears.
7. **Report results that do not work.** Insignificant, unstable and implausible
   findings go in `reports/failed_hypotheses.md`. Deleting an inconvenient
   specification is misconduct, not tidying.
8. **Every result carries a run stamp** — data period, configuration hash, Git
   commit, data provenance. `tariff_incidence.provenance.RunStamp` does this;
   use it.

## Data provenance discipline

Every artefact carries a `DataProvenance` tag:

| Tag | Meaning |
|---|---|
| `OFFICIAL` | Every input traces to an official statistical or legal source. |
| `MIXED` | Official policy/classification inputs, synthetic trade flows. |
| `SYNTHETIC_PIPELINE_VALIDATION` | Simulated data with a known DGP. |

Only `OFFICIAL` artefacts may support empirical claims. The reporting layer
enforces this: `tariff_incidence.reporting.render.guard_language` raises
`UnsupportedClaim` on causal assertions under non-official provenance and on
quantified welfare claims under any provenance. **Do not weaken the guard to
make a report render.** Change the claim.

## Repository layout

```
src/tariff_incidence/
  adapters/      one module per official source; fetch and parse are separate
  tariff/        records, point-in-time policy engine, schedule builder
  concordance/   versioned HS code mappings
  panel/         analytical panel construction; synthetic generator
  quality/       data-quality battery
  econ/          HDFE absorption, OLS, PPML, designs, diversion
  io_exposure/   BEA-based industry exposure
  reporting/     report rendering and the claim guard
scripts/         thin CLI wrappers; no analysis logic lives here
config/          episodes, samples, concordances — behaviour is configuration
data/            raw → staged → normalized → analytical → results
tests/           pytest; fixtures are real official excerpts where possible
reports/         GENERATED. Never edit by hand.
```

## Adding a new tariff episode

Add a YAML file under `config/episodes/`. Do not add code to the engine. If the
new episode's notices use a different annex construction, add a parser to
`adapters/` and reference it via the `parse.method` key. The parser must:

* anchor on the operative legal sentence, not on page numbers;
* validate its output against a count the source document states itself;
* surface, never repair by guessing, codes it cannot resolve.

## Adapter contract

* `available()` — can the source be reached right now?
* `fetch_*()` — bytes into `data/raw/`, checksummed and cached.
* `parse_*()` — pure function over local bytes. Runs offline. Tested against a
  committed fixture.

Splitting fetch from parse is what keeps the test suite runnable without
credentials or network.

## Before you commit

```bash
make test lint typecheck
```

Then update `STATUS.md`. Every working session ends with a STATUS update.

## When a source is unavailable

Implement and test the adapter against fixtures. Record the gap in
`docs/DECISION_LOG.md` and in the affected dataset's manifest
`known_limitations`. Do not abandon the design, and do not paper over the gap
with invented data — use the synthetic generator, which is tagged so no output
can be mistaken for evidence.
