# Résumé bullets

Five framings of the same work. Every claim below is checkable in the
repository. Nothing asserts an empirical finding about U.S. trade, because the
Census key gap means none exists yet — the bullets describe the system, the
validated components, and the methodological work, which is what is actually
true.

---

## International-trade economist

- Built a point-in-time tariff policy engine over U.S. Section 301 actions,
  parsing **12,587 tariff records** directly from Federal Register annexes and
  reconciling **exactly** against the line counts each notice states (818 / 279 /
  5,745), including 11 partially covered statutory lines carved out by U.S. note
  20(g) that a naive parse misses.
- Designed an incidence framework separating exporter absorption
  (tariff-exclusive customs unit values) from importer cost pass-through
  (duty-inclusive landed values), and demonstrated on simulated data with a known
  DGP that the estimator recovers the injected pass-through parameter to within
  0.002.
- Identified and quantified a **control-group contamination problem specific to
  trade settings**: third-country suppliers of a treated product gain from
  diversion, violating no-interference. Using them as controls biased the
  quantity elasticity by 34% (−1.69 vs −1.26 against a −1.34 truth); the price
  parameter was unaffected. The pipeline reports both control groups by default.
- Built a four-channel industry exposure map from pre-treatment BEA input-output
  tables, showing 8 of 72 industries face output protection and imported-input
  cost pressure simultaneously — deliberately never netted into one number.

## Policy research

- Constructed a fully sourced Section 301 treatment schedule in which every rate
  and date is traceable to a Federal Register citation, with the verbatim source
  sentence stored beside it, and announcement dates kept strictly distinct from
  effective dates (the List 3 increase to 25% was announced for 1 Jan 2019 and
  took effect 10 May 2019 — a seven-month gap that conflation would erase).
- Wrote an executive policy memo generated from result tables rather than by
  hand, answering who bears the tariff, which industries gained protection and
  which faced higher input costs, and stating explicitly which conclusions are
  causal, which are descriptive, and what evidence would change them.
- Implemented an automated claim guard that fails the build when generated prose
  makes a causal assertion the data cannot support, or any quantified welfare
  claim. It caught two of the project's own sentences during development.
- Documented every unresolved identification threat — policy endogeneity,
  anticipation, concurrent Section 232 actions, exchange rates, transshipment,
  reclassification — rather than listing only those the design handles.

## Economic consulting

- Delivered an end-to-end analytical pipeline reproducible from a single command
  (`make reproduce-sample`), where every result table carries its data period,
  configuration hash, Git commit and data-provenance tag.
- Built a 12-check data-quality battery covering duplicate keys, invalid codes,
  unit-of-measure breaks, extreme unit values, and duty rates inconsistent with
  the statutory schedule. The battery caught a genuine defect in the project's
  own pipeline (a timing mismatch between two components) that had been
  attenuating estimates.
- Established a defensible replication protocol that specifies targets in
  advance and records blocked targets as blocked rather than approximating them,
  on the reasoning that an approximation printed beside a published estimate
  invites a comparison that is not warranted.
- Designed exposure measures that resist mechanical endogeneity by using
  pre-treatment input shares throughout, and labelled magnitudes as a
  qualitative ordering where the underlying concordance is coarse.

## Applied scientist

- Implemented Poisson pseudo-maximum-likelihood with high-dimensional fixed
  effects from scratch — IRLS with alternating-projection absorption under
  Poisson weights, multi-way cluster-robust sandwich variance, convergence and
  separation diagnostics surfaced on every fit — validated against known Poisson
  coefficients and against an explicit dummy-variable regression to 1e-8.
- Built an event-study framework with binned window endpoints, dual reference
  periods, and a pre-trend test reporting statistical detectability and economic
  magnitude **separately**, because in a large panel significance alone flags
  economically trivial movement and discarding designs on that basis discards
  good work.
- Wrote a synthetic data generator with a fully declared DGP used strictly for
  estimator validation, wired so it shares its timing convention with the
  production panel builder — an earlier version with two implementations
  disagreed and injected measurement error.
- 60+ tests covering the tariff engine's date/rate/exclusion semantics,
  estimator correctness against analytic answers, and parser output against a
  committed excerpt of a real Federal Register notice.

## Data engineering

- Designed a five-layer data architecture (raw → staged → normalized →
  analytical → results) where every dataset carries a manifest recording source,
  vintage, checksum, row count, partition keys, transformation version and known
  limitations, and no downstream stage may write upstream.
- Built modular source adapters splitting `fetch` from `parse` so parsers run
  offline against committed fixtures — the test suite needs neither network nor
  credentials.
- Handled a silent-failure mode where the Census API returns **HTTP 200 with an
  HTML error page** for a missing key, by validating payload shape rather than
  status code.
- Extracted structured tariff data from a 219-page typeset PDF where the XML
  rendering omits the annexes entirely, anchoring on the operative legal sentence
  rather than page layout, and surfacing rather than guessing at codes damaged by
  typesetting.
- Kept the design within ~16 GB on Apple Silicon using partitioned Parquet,
  Polars lazy scans, per-month incremental fetch with on-disk caching, and
  fixed-effect absorption that is O(n) rather than O(n × groups).
