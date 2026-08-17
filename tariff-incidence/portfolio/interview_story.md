# Interview story

## The 90-second version

I built a system to measure who actually pays for tariffs, using the 2018–2019
Section 301 actions against China.

Partway in I hit the thing that decides whether a project like this is honest:
the Census trade API now needs a key I didn't have. There were three options —
abandon it, or generate plausible-looking numbers and describe them as findings,
or build everything and be exact about what each number is.

I took the third. Every artefact carries a provenance tag, and a guard in the
reporting layer **fails the build** if generated prose makes a causal claim the
data can't support. It caught two of my own sentences.

That constraint turned out to be productive, because it forced the work onto the
parts I could do properly with official sources — and those parts produced the
most interesting result in the project.

## The part I'd actually want to talk about

The Section 301 product lists live in Federal Register annexes. The XML doesn't
contain them — they're graphics. So the real source is a 219-page typeset PDF.

My first parse got 817 lines for List 1 where the notice says 818, 280 for List
2 where it says 279, and 5,734 for List 3 where it says 5,745.

The instinct is to shrug at 0.2%. I think that's exactly wrong: each gap was a
different substantive error.

- **List 2 was over by one** because I'd captured `9802.00.80` — a legal
  provision about goods assembled abroad from U.S. components, not a targeted
  product.
- **List 3 was short by 11** because U.S. note 20(g) covers eleven HS8 lines
  *except* for named 10-digit statistical numbers. Those are the "partial" in the
  notice's phrase "full and partial tariff subheadings." Treating them as fully
  treated puts measurement error straight into the treatment variable.
- **List 1 was short by one** because a code renders as `9033.00` with its last
  two digits lost in typesetting.

The first two I fixed. The third I deliberately did not guess at. I made the
parser report it as unresolved, then wrote a resolver that consults the USITC
HTS and fills it **only** when exactly one 8-digit line under that heading is
unclaimed. It was — 9033.00.90 — and the resulting record is marked `DERIVED`,
not `OFFICIAL_PARSED`, so anyone can see it was deduced rather than read.

All three lists now reconcile exactly. The check isn't against a number I
remembered; it's against the count each notice states in its own preamble.

## The methodological finding

To validate the estimators I generated data with a known data-generating
process. The price pass-through parameter came back essentially exact: −0.0485
against −0.050 injected.

The quantity elasticity didn't. It came back at −1.69 where the truth implied
−1.34 — a 26% overshoot, in the *wrong* direction for the usual suspects.

The cause is specific to trade. My control group included third-country
suppliers of treated products — Vietnam, Thailand, Mexico. But those suppliers
aren't untreated. The tariff pushes demand toward them. They're treated
*positively*. Using them as controls violates the no-interference assumption, and
it inflates the estimated contraction because the comparison group is rising for
the same reason the treated group is falling.

I tested it directly by re-estimating against a control group of treated-country
flows of never-treated products only. That gave −1.26, close to the −1.34 truth.
And the price parameter was unaffected under both control groups — exactly as
expected, since the generator has no third-country price spillover.

So the pipeline now reports both control groups on every run, as a standing
diagnostic. It's a good example of a bug in the *research design* that only
showed up because I'd built a case where I knew the right answer.

## If they push on the synthetic data

They should. It's the weakest thing about the project and I'd rather name it
first.

No number in the repository is currently evidence about U.S. trade. I'd say that
before showing anything. What I'd claim instead:

- The tariff schedule is real, official, and exactly reconciled.
- The MFN baselines and input-output tables are real.
- The estimators are validated against known answers.
- The whole thing flips to official data with an environment variable and no
  code change.

The honest summary is that I built the instrument and calibrated it. I haven't
taken the measurement.

## Three smaller things I'd mention if asked

**Mid-month effective dates.** List 3 took effect on 24 September — seven of
thirty days. Assessing at month start calls September untreated; month end calls
it fully treated. Both errors land on the event-time-zero coefficient, which is
the one people look at hardest. The panel carries a day-weighted rate and both
alternatives.

**A null that mattered.** 38% of rows had no single ad-valorem MFN baseline,
because those HS6 headings contain compound duty lines. An early version filled
the null with zero. That silently asserted "no tariff" across a third of the
sample and attenuated everything. Now the null propagates and those rows drop
out of total-rate specifications explicitly.

**Pre-trend tests.** I report statistical significance and economic magnitude
separately. In a panel this size the standard errors get small enough that a
pre-coefficient of 0.005 is "significant." A rule that kills any design with a
significant pre-coefficient throws away good work; a rule that ignores magnitude
keeps bad work. One number lets the reader pick whichever rule suits them.

## What I'd do next

Get the key. Everything else is second-order — but after that: parse List 4A to
extend the window past August 2019, and parse the product exclusions, which
would move the estimates from intention-to-treat to treatment-on-the-treated.
