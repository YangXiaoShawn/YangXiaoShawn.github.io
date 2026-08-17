# Research design

## The four questions, kept separate

Tariff research goes wrong when distinct questions are answered with one number.
This project separates them by construction.

1. **Incidence.** Who pays? Does the foreign exporter cut its border price, or
   does the U.S. importer pay the duty on top of an unchanged price?
2. **Diversion.** Where did sourcing go? A contraction from the treated country
   and an expansion from third countries are two quantities, not one.
3. **Protection.** Which domestic industries face less import competition?
4. **Propagation.** Which domestic industries pay more for inputs?

## Setting

U.S. Section 301 tariffs on imports from China, 2018–2019. Three waves with
distinct effective dates, all read from the Federal Register:

| Action | Citation | Announced | Effective | Rate | Lines |
|---|---|---|---|---|---|
| List 1 | 83 FR 28710 | 2018-06-20 | 2018-07-06 | 25% | 818 |
| List 2 | 83 FR 40823 | 2018-06-20 (proposal) | 2018-08-23 | 25% | 279 |
| List 3 | 83 FR 47974 | 2018-07-17 (proposal) | 2018-09-24 | 10% | 5,745 |
| List 3 increase | 84 FR 20459 | 2018-09-21 | 2019-05-10 | 25% | 5,745 |

Staggered timing across products with a common set of alternative suppliers is
what makes the setting usable: it provides within-product, within-time variation
that a single-date shock would not.

## Identification

### Estimating equation

For product $i$, partner $c$, month $t$:

$$y_{ict} = \alpha_{ic} + \gamma_t + \beta \cdot D_{ict} + \varepsilon_{ict}$$

with $\alpha_{ic}$ product-country (flow) effects and $\gamma_t$ month effects.
$D_{ict}$ is the day-weighted additional statutory duty.

### Why these fixed effects

Flow effects absorb time-invariant differences in what a country ships and how
it is priced. Month effects absorb aggregate shocks common to all flows.

**Product-time effects are deliberately excluded** from level specifications.
They would absorb the product-level tariff shock — which is the object of
interest — leaving only within-product reallocation across countries. That is a
legitimate but *different* estimand, and conflating the two is a common error.
Where relative reallocation *is* the question, the diversion module addresses it
directly rather than by saturating the regression.

A related hazard is visible in this project's own validation runs: when the
treated country is the largest supplier, a common month effect partially absorbs
the shock, attenuating the estimate. Recorded in `reports/failed_hypotheses.md`.

### Identifying assumption

Conditional on flow and month effects, treated and untreated flows would have
followed parallel paths absent the tariff.

### What would falsify it

- Non-zero pre-period event-study coefficients that are large relative to the
  post-treatment coefficients.
- A significant placebo effect at a treatment date shifted 12 months earlier.
- A significant placebo effect on never-treated products labelled treated.
- Estimates that move materially when a single chapter or partner is dropped.

All four are estimated and reported whether or not they are favourable.

## The model ladder

Each rung is more structured than the last; each is reported.

1. **Descriptive event-time means.** No causal content. Shows the raw data.
2. **Two-way fixed effects.** One coefficient; assumes a constant effect.
3. **Event study.** Dynamic effects, and the pre-trend test that licenses
   everything above it. Two reference periods (−1 and −3).
4. **Staggered-treatment design.** Not yet needed: the vertical slice uses a
   single wave. With Lists 1–3 jointly, a stacked design is required because
   two-way fixed effects with staggered adoption uses already-treated units as
   controls. Flagged for the next iteration.
5. **PPML in levels.** Consistent under heteroskedasticity in levels and retains
   zero flows, which is where extensive-margin sourcing changes appear.
6. **Heterogeneity.** By pre-treatment dependence on the treated country.

## Outcome variables, and why the distinctions matter

| Outcome | Question it answers |
|---|---|
| `log_customs_unit_value` | Did the **exporter** cut its border price? Tariff-exclusive. |
| `log_landed_unit_value` | What does the **U.S. importer** pay at the border? Duty-inclusive. |
| `log_quantity` | Real trade response. |
| `log_customs_value` | Nominal response; moves with both price and quantity. |
| `customs_value` (PPML) | Level response including zeros. |

Complete pass-through to the importer with no exporter absorption appears as a
zero coefficient on the customs unit value and a positive one on the landed unit
value. Full exporter absorption appears as a negative customs coefficient and a
zero landed coefficient. Reporting only one of the two cannot distinguish these.

**A customs unit value is not a price.** It is value divided by quantity over a
heterogeneous bundle of transactions within an HS line, country and month, and
moves with product mix, quality and unit-of-measure changes. Every mention of it
in this repository is labelled.

## Treatment definition

Treatment is the day-weighted average additional statutory duty for the
product-country-month, from the point-in-time tariff engine.

Choices that follow from taking the law seriously:

- **HS6 headings with partial coverage are excluded from both groups.** Section
  301 lists are written at 8 digits. Assigning a coverage-weighted rate to a
  partly covered HS6 heading would invent precision the law does not have. 57
  headings were excluded on this ground in the current sample.
- **Partial statutory lines are flagged and excluded.** 11 HS8 lines are covered
  except for named 10-digit statistical numbers.
- **Mid-month effective dates are day-weighted.** A duty effective 24 September
  applies for 7 of 30 days.
- **Estimates are intention-to-treat** with respect to the statutory list,
  because product exclusions are not yet parsed.

## Diversion decomposition

The pre-to-post change is split into four margins that are never netted:

$$\Delta \text{Total} = \Delta_{\text{treated}}^{\text{int}} + \Delta_{\text{treated}}^{\text{ext}} + \Delta_{\text{alt}}^{\text{int}} + \Delta_{\text{alt}}^{\text{ext}}$$

Reported twice: raw, and net of the growth of never-treated products country by
country. The raw version credits ordinary trade growth to the tariff and its
replacement ratio is not interpretable alone.

**A third-country increase is not evidence of production relocation.** Rerouting
of treated-origin goods, redirection of existing capacity, and origin
misdeclaration all produce the same pattern in customs data.

## Industry exposure

Four channels from pre-treatment BEA input-output weights, kept separate:

- `output_protection_exposure` — tariffs on competing imports. Helps.
- `imported_input_cost_exposure` — tariffs on purchased inputs. Hurts.
- `downstream_total_requirements_exposure` — the full Leontief chain.
- `direct_import_competition_exposure` — import penetration in the industry's
  own commodity.

Pre-treatment weights are used so exposure cannot respond to the shock it
explains. Industries exposed through both channels are identified explicitly;
in the current run, 8 of 72.

## What this design cannot do

- Separate exporter price cuts from exchange-rate movements.
- Distinguish relocation from transshipment.
- Observe domestic substitution — a fall in imports not matched by third-country
  gains may be domestic production, weaker demand, or inventory drawdown.
- Measure treatment-on-the-treated while exclusions are unparsed.
- Support any welfare number. No structural module has been run, and the
  reporting guard blocks quantified welfare claims outright.
