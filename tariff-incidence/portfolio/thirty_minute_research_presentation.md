# Thirty-minute research presentation

Audience: an economics seminar or a research-team panel. Assumes familiarity
with difference-in-differences and gravity estimation.

---

## Part I — Motivation and setting (0:00–5:00)

### The question

Standard trade theory says a small country's tariff is borne by its own
consumers, while a large country can push part of the burden onto foreign
exporters through terms of trade. The 2018 U.S. tariffs are the natural test.

Three sub-questions that must be answered separately:

1. **Incidence** — does the foreign border price fall, or does the importer pay
   the duty on top of an unchanged price?
2. **Diversion** — where does sourcing go, and is a third-country increase
   really relocation?
3. **Propagation** — tariffs protect an industry's output and raise its input
   costs simultaneously. Which dominates, and for whom?

### Why Section 301 is a good setting

Staggered effective dates across product lines, a single targeted origin, a
common set of alternative suppliers, and monthly administrative data with
separately reported duties. That combination is rare.

### The constraint, stated up front

The Census trade API requires a key unavailable in this environment. **Nothing
in this presentation is an empirical finding about U.S. trade.** What follows is
(a) an exactly validated tariff schedule from official legal sources, (b) an
estimator validated against known parameters, and (c) a methodological result
that emerged from that validation.

---

## Part II — Building the treatment variable (5:00–12:00)

### The law is at HS8; the data is at HS6 or HS10

Section 301 lists enumerate 8-digit HTSUS subheadings. Trade panels are built at
HS6 (comparable across countries) or HS10 (U.S. statistical detail). Neither
aligns with the legal object.

**Design choice:** the tariff engine treats an HS6 query as a *coverage*
question, not a rate question. It returns a coverage share across the heading's
HS8 children and flags `PARTIAL_HS6_COVERAGE` whenever coverage is strictly
between 0 and 1. In this sample, **598 HS6 headings** are partly covered and are
excluded from both treatment groups.

The alternative — a coverage-weighted rate — invents precision the law does not
have and puts classical measurement error into the treatment.

### Parsing the annexes

The Federal Register XML renders the annexes as graphics. The GPO typeset PDF
carries extractable text: 219 pages for List 3.

The parser anchors on the **operative legal sentence**, not on page layout:

> "Heading 9903.88.03 applies to all products of China that are classified in
> the following 8-digit subheadings"

This matters because the same notice contains a descriptive annex that
explicitly disclaims delimiting the scope of the action. Anchoring on layout can
pick up the wrong list.

### Validation against the source's own count

| List | Notice states | First parse | Final |
|---|---|---|---|
| 1 | 818 | 817 | **818** ✅ |
| 2 | 279 | 280 | **279** ✅ |
| 3 | 5,745 | 5,734 | **5,745** ✅ |

Three distinct causes:

1. **Chapter 98/99 provisions.** `9802.00.80` is a legal provision, not a
   product.
2. **Partial lines.** U.S. note 20(g), heading 9903.88.04, covers 11 HS8 lines
   *except* named 10-digit statistical numbers — the "partial" in "full and
   partial tariff subheadings". Flagged `partial_line`, never treated as fully
   treated.
3. **Typesetting damage.** One code renders as `9033.00`. Not guessed. Resolved
   only because the HTS leaves exactly one unclaimed 8-digit line under that
   heading; marked `DERIVED`.

### Timing

Announcement and effective dates are separate fields throughout. The List 3
increase to 25% was announced for 1 Jan 2019, postponed to 2 March, postponed
"until further notice", and took effect **10 May 2019**.

Within-month timing matters too: List 3 took effect on 24 September, 7 of 30
days. The panel carries a **day-weighted** average statutory rate plus
month-start and month-end variants.

---

## Part III — Specification (12:00–18:00)

### The estimating equation

$$y_{ict} = \alpha_{ic} + \gamma_t + \beta D_{ict} + \varepsilon_{ict}$$

Flow effects $\alpha_{ic}$; month effects $\gamma_t$; $D_{ict}$ the day-weighted
additional duty. Clustered on product.

### Why not product-time effects

They would absorb the product-level tariff shock — the object of interest —
leaving only within-product reallocation across countries. That is a legitimate
but *different* estimand. Fixed effects are chosen to match the estimand, not to
maximise fit.

### Outcomes chosen so incidence is identified

| Outcome | Reads |
|---|---|
| `log_customs_unit_value` | exporter's border price (tariff-exclusive) |
| `log_landed_unit_value` | importer's border cost (duty-inclusive) |

Complete pass-through: zero on the first, positive on the second. Full exporter
absorption: negative on the first, zero on the second. **One outcome cannot
distinguish these.**

### The model ladder

1. Descriptive event-time means (no causal content)
2. Two-way fixed effects
3. Event study, two reference periods (−1 and −3)
4. Stacked design — needed for multi-wave; the slice uses one wave deliberately
5. PPML in levels, retaining zeros
6. Heterogeneity by pre-treatment dependence

### Reference-period choice as a substantive decision

Event month −1 is the month most exposed to front-running ahead of a known
effective date. If importers pull shipments forward, the reference period is
itself treated and every coefficient shifts. Both −1 and −3 are always reported;
disagreement is diagnostic.

---

## Part IV — Estimator validation and the main methodological result (18:00–25:00)

### Setup

Data generated with a fully declared DGP so the right answer is known. The
generator shares its timing convention with the production panel builder — an
earlier version with two implementations disagreed and injected measurement
error, which the data-quality battery caught.

### Result 1: the price parameter is recovered

| | Injected | Recovered |
|---|---|---|
| Exporter pass-through | −0.050 | **−0.0485** [−0.102, +0.005] |

### Result 2: the quantity parameter is not — and the reason is interesting

Implied truth over the observed tariff range: **−1.339**. Estimate: **−1.686**.

Not attenuation. Overshoot.

**Diagnosis.** The control group included third-country suppliers of treated
products. Those suppliers are not untreated bystanders — the tariff pushes
demand toward them. This violates the no-interference (SUTVA) assumption: the
comparison group rises for the same reason the treated group falls, inflating
the estimated contraction.

**Test.** Re-estimate with a control group of treated-country flows of
never-treated products only:

| Control group | log quantity | log customs unit value |
|---|---|---|
| Incl. third-country flows | −1.686 | −0.0485 |
| Treated-country flows only | **−1.256** | −0.0515 |
| *Truth* | *−1.339* | *−0.050* |

The quantity estimate moves to the truth. The price estimate does not move —
exactly as predicted, since the generator has no third-country price spillover.

**Implication for applied work.** In tariff settings, the natural control group
is contaminated by the very reallocation the study measures. This is the rule,
not the exception. The pipeline now reports both control groups on every run as
a standing diagnostic.

### Result 3: pre-trend testing needs two criteria

At this sample size, standard errors are small enough that a pre-coefficient of
0.005 is "significant". A rule discarding any design with a significant
pre-coefficient discards good work; ignoring magnitude keeps bad work. The test
returns a verdict combining significance with magnitude relative to the mean
post-treatment coefficient.

---

## Part V — Propagation and closing (25:00–30:00)

### Four exposure channels, never netted

From **pre-treatment** BEA input-output weights (contemporaneous weights would
respond to the shock they explain):

- `output_protection_exposure` — helps
- `imported_input_cost_exposure` — hurts
- `downstream_total_requirements_exposure` — full Leontief chain
- `direct_import_competition_exposure` — import penetration

**8 of 72 industries face both channels at once**: primary metals, fabricated
metal products, machinery, motor vehicles, paper, plastics and rubber.

The netting column is named `net_contrast_do_not_use_alone`. A single number
hides the distributional question.

Concordance caveat: the Census HS→NAICS file was unreachable, so this uses a
coarse HS2-chapter map. The magnitudes are a qualitative ordering, not
elasticities, and are barred from any welfare calculation.

### What the design cannot do

- Separate exporter price cuts from RMB depreciation.
- Distinguish relocation from transshipment or origin misdeclaration.
- Observe domestic substitution — a fall in imports not matched by third-country
  gains could be domestic production, weaker demand, or inventory drawdown.
- Measure treatment-on-the-treated while exclusions are unparsed.
- Support any welfare number. No structural module exists, deliberately.

### Reproducibility as enforcement

Every result carries data period, config hash, Git commit and provenance tag.
`guard_language` fails the build on unsupported causal claims and on any
quantified welfare claim — it caught two of my own sentences.
`failed_hypotheses.md` is generated, not curated.

### Closing

I built the instrument and calibrated it against known answers. The calibration
produced a methodological result I did not expect and would not have found
without it. The measurement itself needs one free API key.

---

## Likely seminar questions

**"Isn't the SUTVA problem well known?"** The general point is. The
demonstration that it inflates the quantity elasticity by 34% while leaving the
price elasticity untouched — and that a simple control-group restriction fixes
it — is the useful part, and it required knowing the truth.

**"Why exclude 598 HS6 headings rather than weight them?"** Weighting requires
HS8 import weights I don't have without the Census key, and unweighted coverage
shares would be worse than exclusion. With HS10 data the question disappears.

**"Your event study shows significant pre-trends at reference −1."** Yes — the
generator includes deliberate front-running at −1. That the test detects it, and
that the −3 reference is clean, is the intended behaviour and the argument for
reporting both.

**"Intention-to-treat is a big caveat."** It is. Thousands of product exclusions
were granted from mid-2019 and are written as narrative descriptions, not code
lists. Parsing them is the second priority after the key.
