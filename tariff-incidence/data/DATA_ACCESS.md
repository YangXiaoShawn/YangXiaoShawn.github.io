# Data access

Every source, its access status **as verified at build time**, and what to do
about it.

## Status summary

| Source | Key needed | Verified status | Used for |
|---|---|---|---|
| Federal Register API + GPO PDFs | no | **working** | Section 301 actions, effective dates, annexes |
| USITC HTS `reststop/exportList` | no | **working** | MFN baseline rates, HS6→HS8 child map |
| BEA Supply-Use static files | no | **working** | Input-output requirements |
| U.S. Census intl. trade API | **yes** | **WORKING (key supplied 2026-08-09)** | Monthly imports by HS10 × country |
| BLS PPI API | v1 keyless | **down for maintenance** at build time | Domestic producer prices |
| Census HS→NAICS concordance | no | **404/403** | Industry mapping |

---

## A. U.S. Census international trade — **WORKING**

**Endpoint.** `https://api.census.gov/data/timeseries/intltrade/imports/hs`

**The problem.** Keyless access has been retired. An unauthenticated request
returns HTTP **200** with an HTML page titled "Missing Key". A pipeline that
checks status codes will happily ingest that HTML as data. The adapter therefore
validates the payload shape, not the status code.

A key was supplied on 2026-08-09 and verified against the live endpoint (15/15
variables confirmed against the endpoint's own `variables.json`). The panel is
built from official data and carries provenance `OFFICIAL`.

**Critical finding from the first live pull: no quantity at HS6.** At
`COMM_LVL=HS6` the endpoint returns `CON_QY1_MO = 0` and `UNIT_QY1 = "-"` for
every line, because the underlying 10-digit lines carry different units of
measure. Unit values therefore cannot be constructed at HS6 at all, which is why
the panel is built at HS10 (see docs/DECISION_LOG.md D-019). Census also emits
explicit zero rows for country-product combinations with no trade, so the
extensive margin is observed rather than inferred.

Retrieval: chapter-prefix wildcard (`I_COMMODITY=84*`), one partition per
chapter-month, 320 requests for 10 chapters x 32 months, about 9 minutes, 18 MB.

**If you need to set up a key elsewhere:**

1. Register at https://api.census.gov/data/key_signup.html
2. Export the key:

```bash
export CENSUS_API_KEY=your_key_here
```

3. Re-run the pipeline:

```bash
make build-trade-panel estimate-incidence estimate-diversion report
```

Every artefact's provenance flips from `MIXED` to `OFFICIAL` automatically. No
estimation code changes.

**Without a key** the pipeline falls back to `tariff_incidence.panel.synthetic`,
a documented generator with declared parameters, and tags every derived artefact
so nothing can be mistaken for evidence. That path is still exercised by the
test suite and by `--force-synthetic`.

**Variables retrieved** (verified against the endpoint's own `variables.json` at
runtime, not hard-coded): `CON_VAL_MO`, `GEN_VAL_MO`, `DUT_VAL_MO`,
`CAL_DUT_MO`, `CON_CHA_MO`, `CON_QY1_MO`, `UNIT_QY1`, `CON_QY2_MO`, `UNIT_QY2`,
`CTY_CODE`, `CTY_NAME`, `I_COMMODITY`, `COMM_LVL`, `SUMMARY_LVL`.

**Rate limits.** Fetched one month at a time, cached on disk, capped by
`sample.max_api_calls`. Re-runs cost nothing.

---

## B. Tariff actions — Federal Register (working, no key)

**Metadata.** `https://www.federalregister.gov/api/v1/documents/{id}.json`

**Annexes.** Only in the GPO typeset PDF:
`https://www.govinfo.gov/content/pkg/FR-{date}/pdf/{id}.pdf`

The federalregister.gov XML and plain-text renderings **omit the annex tables** —
they appear as `<GPH>` graphic references. The 219-page List 3 PDF does contain
extractable text. Documents used:

| Document | Citation | Size |
|---|---|---|
| 2018-13248 | 83 FR 28710 (List 1) | 2.4 MB, 47 pp |
| 2018-17709 | 83 FR 40823 (List 2) | 1.0 MB, 16 pp |
| 2018-20610 | 83 FR 47974 (List 3) | 14.1 MB, 219 pp |
| 2019-09681 | 84 FR 20459 (List 3 → 25%) | 0.2 MB, 2 pp |

All cached under `data/raw/federal_register/` with checksums.

---

## C. Harmonized tariff schedule — USITC (working, no key)

`https://hts.usitc.gov/reststop/exportList?from=...&to=...&format=JSON`

Serves the **current** schedule; no 2018 vintage is available through this
interface. Vintage mismatch documented in D-010.

Compound and specific rates ("2.5 cents/kg", "7.5% + 1.4 cents/kg") are returned
as `None` with the original string kept. They are **not** converted to an ad
valorem equivalent, because that requires unit values and would mix a measured
quantity into what is presented as a statutory rate.

---

## D. Input-output — BEA (working, no key)

`https://apps.bea.gov/industry/iTables Static Files/AllTablesSUP.zip` (20 MB)

Used: `Use_Tables_Supply-Use_Framework_1997-2023_Summary.xlsx` and
`IxC_TR_1997-2023_Summary.xlsx`, year 2017 (pre-treatment).

Total requirements come from BEA's published IxC table rather than being
re-derived, so the Leontief convention matches BEA's exactly. Final-demand
columns (codes beginning `F` or `T`) are filtered out — they are uses, not
producing industries.

The BEA **API** (`apps.bea.gov/api`) requires a key; the static files do not, and
are used instead.

---

## E. Domestic prices — BLS (deferred)

`https://api.bls.gov/publicAPI/v1/timeseries/data/` (v1 is keyless, 25
series/request, 10 years). Returned HTTP 503 "Temporarily Down for Maintenance"
at build time, so M9 is deferred.

When implemented: PPI commodity series are far broader than HS6 lines. The
adapter must record the aggregation loss rather than silently matching a
high-frequency product classification to a broad price index.

---

## F. Replication packages

No third-party replication package is redistributed in this repository. Where a
package is publicly available under a licence permitting it, the adapter would
download to `data/raw/replication/` at run time and never commit the contents.
Published estimates are cited by value and source in
`reports/replication_comparison.md`, which is fair use of a factual figure.

---

## What is committed to Git

Committed: schemas, manifests, configuration, download scripts, small test
fixtures, generated reports and small result tables.

Not committed: raw PDFs (17 MB), the BEA zip (20 MB), staged/normalized/
analytical Parquet. `data/raw/**` and the intermediate layers are gitignored.
Everything is reproducible with `make download-sample`.

One fixture is committed deliberately:
`tests/fixtures/fr_2018-17709_annexA_excerpt.pdf` (270 KB), a four-page excerpt
of 83 FR 40823 that reproduces the exact 279-line parse offline. U.S. government
works are not subject to copyright.
