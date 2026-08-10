# Original-provider data access

This project can retrieve current observations directly from the U.S. Bureau of Labor
Statistics (BLS) and the U.S. Bureau of Economic Analysis (BEA). The ordinary agency APIs
are **current-data sources**, not historical-vintage sources. API rows are therefore always
stored with `provenance_label = "latest_revised"`; the adapters do not accept
`first_release`, `vintage_aware`, or similar labels.

Facts below are drawn only from the agencies' official pages. Statements marked
**project policy/inference** describe this repository's conservative implementation.

## Current API access

| Provider | Official interface | Authentication and published limits | Vintage implication |
| --- | --- | --- | --- |
| BLS | [Public Data API v2 signature](https://www.bls.gov/developers/api_signature_v2.htm) | A registered v2 request carries a registration key. BLS documents up to 50 series and 20 years per query, 500 queries per day, and 50 queries per 10 seconds for registered users in its [API FAQ](https://www.bls.gov/developers/api_faqs.htm). Registration keys are renewed annually. | **Project inference:** the v2 time-series request has no publication-vintage or as-of parameter. Its historical values must not be treated as the values known on past dates. |
| BEA | [BEA Data API](https://apps.bea.gov/api/signup/) and [API user guide](https://apps.bea.gov/api/_pdf/bea_web_service_api_user_guide.pdf) | Every request needs a registered `UserID`. The guide documents thresholds of 100 requests per minute, 100 MB per minute, and 30 errors per minute; throttled responses use HTTP 429 and `Retry-After`. | BEA's [citation guidance](https://www.bea.gov/help/guidelines-for-citing-bea) says its interactive data application shows the most recently released data and does not identify an estimate's vintage. **Project inference:** NIPA API results likewise cannot reconstruct historical as-of GDP because `GetData` has no vintage parameter. |

Live access is fail-closed:

- `terms_authorized=True` must be explicit for each adapter instance.
- The BLS adapter looks up only `BLS_REGISTRATION_KEY`.
- The BEA adapter looks up only `BEA_API_KEY`.
- Credentials are never loaded from a repository file and are excluded from request,
  response, client, and exception representations.
- Tests inject a transport and make no network calls.
- Throttling, timeout, attempt count, exponential backoff, and maximum accepted
  `Retry-After` delay are configurable. The defaults space BLS calls by 0.2 seconds and
  BEA calls by 0.6 seconds. A valid `Retry-After` value is honored subject to the configured
  safety cap.
- There is no persistent API-response cache in this layer.

On successful parsing, `realtime_start`, `availability_date`,
`availability_timestamp`, and `download_timestamp` are based on the UTC retrieval time.
`release_timestamp` remains null. This is deliberate: a current API response does not prove
when each returned value was first published. Such rows can support a latest-revised
benchmark but cannot enter a historical as-of matrix as if downloaded earlier.

## Initial source identifiers and target definitions

The typed defaults in `agency_adapters.py` use these original-provider identifiers:

| Research input | Original-provider selection | Canonical interpretation |
| --- | --- | --- |
| Total nonfarm payroll employment | BLS CES `CES0000000001` | Monthly, seasonally adjusted, thousands of persons, level. Payroll change must be derived later and explicitly named. |
| Civilian unemployment rate | BLS CPS `LNS14000000` | Monthly U-3 unemployment rate, seasonally adjusted, percent. Historical rows come from Employment Situation table A-1 release snapshots, not a current API history. |
| Initial unemployment insurance claims | DOL ETA weekly claims release | Seasonally adjusted weekly initial claims (`DOL_UI_INITIAL_CLAIMS_SA`) plus the directly published four-week moving average (`DOL_UI_INITIAL_CLAIMS_4WMA_SA`). These are parsed from historical release documents, not relabeled current history. |
| Total industrial production | Federal Reserve G.17 dated ASCII releases | Seasonally adjusted total-IP index (`FED_G17_TOTAL_IP_SA`) plus the directly published monthly percent change (`FED_G17_TOTAL_IP_MOM_PCT`). The percent-change series is retained separately so historical index rebasing cannot contaminate the change feature. |
| Advance retail and food-services sales | Census MARTS historical releases | Seasonally adjusted total level (`CENSUS_MARTS_RETAIL_FOOD_SERVICES_SA`) plus the directly published monthly percent change (`CENSUS_MARTS_RETAIL_FOOD_SERVICES_MOM_PCT`). The published change is retained separately and is not recomputed from the narrative level rounded to one decimal billion dollars. |
| Privately-owned housing starts | Census/HUD New Residential Construction historical releases | Headline total starts at a seasonally adjusted annual rate, stored as `CENSUS_NRC_HOUSING_STARTS_SAAR` in thousands of units. Log changes are computed only after as-of selection. |
| Core CPI | BLS CPI `CUSR0000SA0L1E` | Monthly, seasonally adjusted, index (1982–84 = 100), level. Month-over-month or year-over-year inflation must be derived later and explicitly named. |
| Headline CPI | BLS CPI `CUSR0000SA0` | Monthly, seasonally adjusted, index (1982–84 = 100), level. |
| Real GDP level used by the configured target | BEA NIPA table `T10106` (table 1.1.6), line 1 | Quarterly real-GDP chained-dollar level at a seasonally adjusted annual rate. Canonical ID: `GDPC1`. The target layer computes the explicitly named q/q SAAR formula from two levels selected from one snapshot. |
| Published real GDP growth cross-check | BEA NIPA table `T10101`, line 1 (API series code commonly returned as `A191RL`) | Already-transformed quarterly percent change from the preceding period at a seasonally adjusted annual rate. Canonical ID: `BEA_REAL_GDP_GROWTH_QOQ_SAAR`; it must not be annualized a second time. |

BLS publishes the CES and CPI series catalogs in its official
[CES flat files](https://download.bls.gov/pub/time.series/ce/ce.series) and
[CPI-U flat files](https://download.bls.gov/pub/time.series/cu/cu.series). BEA documents the
NIPA table request parameters and result fields in its official
[API user guide](https://apps.bea.gov/api/_pdf/bea_web_service_api_user_guide.pdf), and its
[NIPA table guide](https://www.bea.gov/help/faq/125) identifies table 1.1.6 as the
chained-dollar counterpart to the current-dollar GDP table.

## Historical archive contracts

`agency_adapters.py` provides guarded live adapters and archive contracts;
`archive_ingestion.py` implements offline production parsers. Archive ingestion requires:
source-terms authorization, operator opt-in, and a recorded coverage/layout audit.

| Manifest | Official facts and coverage limit | Repository status |
| --- | --- | --- |
| BLS CES vintage | BLS's [vintage information](https://www.bls.gov/web/empsit/cesvininfo.htm) says the tables show published values beginning with the first preliminary estimates for May 2003. Total-nonfarm reference observations extend back to 1939, but an older reference date inside the May 2003 sheet is not an older publication snapshot. The [download page](https://www.bls.gov/web/empsit/cesvindata.htm) offers XLSX plus zipped CSV data for supersectors and industries. | Official raw CSV ZIP acquired and audited. Total nonfarm contributes 247,115 canonical rows. Eight sector series contribute another 331,864 rows, restricted to reference periods from 2002 onward while retaining all publication vintages. All 273 target months are mapped to official release dates; 272 source snapshots remain because October/November 2025 shared one release. |
| BLS Employment Situation TXT clocks | The official [Employment Situation archive](https://www.bls.gov/bls/news-release/empsit.htm) links the original historical TXT releases. Each release header prints the embargo weekday, date, time, and `EST` or `EDT`. | Acquired all 56 TXT releases needed by the pre-2008 portion of the CES target window, from 2003-06-06 through 2008-01-04. The audit verifies every printed weekday/date, 8:30 a.m. clock, and New York offset; it preserves each direct byte stream, URL, encoding, size, and SHA-256. The set contains 32 `EDT` and 24 `EST` releases; 52 decode as UTF-8 and four as `cp1252`. |
| BLS Employment Situation / CPS | The official [Employment Situation archive](https://www.bls.gov/bls/news-release/empsit.htm) exposes historical HTML/PDF releases. Table A-1 reports the seasonally adjusted civilian unemployment rate and visible recent-month history as it appeared in that release; the page header prints the embargo clock. | Acquired 221 complete browser-rendered DOM exports for HTML releases from 2008-02-01 through 2026-07-02. The audit verifies unique SHA-256 hashes, 24 preformatted and 197 structured A-1 layouts, and 220 internally consistent exact release clocks. The 2012-12-07 header prints `EDT` during New York standard time and is explicitly excluded from exact-clock use. The parser retains 1,322 genuine release-vintage rows across 233 observation months for `LNS14000000`. A DOM export is explicitly not claimed to be the server's original response bytes. |
| DOL UI weekly claims | DOL's official [claims archive](https://oui.doleta.gov/unemploy/claims_arch.asp) states that prior weekly news releases are available and that the release is normally published at 8:30 a.m. Eastern on Thursday, with listed holiday exceptions. DOL's [seasonal-adjustment Q&A](https://oui.doleta.gov/unemploy/wksaqna.asp) confirms that the method and factors can change. DOL-created materials are generally public domain under its [copyright policy](https://www.dol.gov/general/aboutdol/copyright), without implying endorsement. | Acquired 1,238 enumerated links from 2002–2026 and retained 1,235 actual releases: 105 HTML, 494 ASP, and 636 PDF files. Two byte-identical cross-year aliases and one official dummy placeholder are preserved but excluded. The parser retains 2,470 current/prior reported weekly vintage rows and 1,235 directly published four-week averages, all with 8:30 a.m. `America/New_York` availability timestamps. |
| Federal Reserve G.17 | The Board's official [G.17 release index](https://www.federalreserve.gov/releases/g17/default.htm) exposes dated monthly ASCII releases from December 1997 onward and separate annual revisions. Its [download documentation](https://www.federalreserve.gov/releases/g17/download.htm) identifies the related real-time estimates and revisions. | Acquired 367 dated snapshots through 2026-07-17: 343 monthly releases and 24 annual revisions. All hashes are unique. The parser retains 4,306 total-IP levels and 4,306 directly published monthly changes, six historical base periods, and exact header clocks. One 2000 URL-path/header-date mismatch and three 2026 AM/PM zone-label inferences remain explicit audit fields. |
| U.S. Treasury 10-year CMT | Treasury's [daily-rate archive](https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rate-archives) and [XML-feed documentation](https://home.treasury.gov/treasury-daily-interest-rate-xml-feed) expose official daily par-yield-curve observations. Treasury says the indicative bid quotations are obtained at approximately 3:30 p.m. each business day and the 10-year CMT is read from the fitted par curve. | Acquired and hashed 25 year-specific original XML responses covering 2002-01-02 through 2026-08-07, yielding 6,154 10-year observations. These are daily point-in-time market observations, not successive correction vintages. Because the source does not state an exact publication clock, rows become eligible only at source-date New York EOD; the canonical UTC availability date follows that timestamp. Later correction history is unavailable and explicitly recorded. |
| University of Michigan consumer sentiment | The official [historical release-date document](https://data.sca.isr.umich.edu/technical-docs.php) lists preliminary/final dates from 1991 onward. The [FAQ](https://data.sca.isr.umich.edu/faq.php) requests citation for publicly available data, while the linked [usage agreement](https://data.sca.isr.umich.edu/agreement.php) restricts reproduction, retransmission, distribution, publication, and broadcast without express written consent. | **Disabled pending written permission.** Public visibility is not treated as authority to build or distribute a historical release archive. The source-specific code gate requires a written-permission reference, organization-scope confirmation, opt-in, and coverage audit. A reviewable request template is in [UMICH_SENTIMENT_PERMISSION_REQUEST.md](UMICH_SENTIMENT_PERMISSION_REQUEST.md). |
| Census MARTS retail sales | Census's [historical MARTS releases](https://www.census.gov/retail/marts/historic_releases.html) are explicitly historical publications rather than current data. Release PDFs publish the advance adjusted retail/food-services level, its monthly percent change, and a header clock; the official [release schedule](https://www.census.gov/retail/release_schedule.html) identifies the normal 8:30 a.m. publication time. | Enumerated 281 reference-month PDFs from 2003-01 through 2026-05 and parsed 273. The parser retains 273 published levels and 273 published changes with exact header timestamps. Eight early scanned PDFs lack a machine-readable text layer and remain explicit exclusions; no OCR, interpolation, or current-history substitution is performed. Twenty headers print `ET`, which is recorded as an `America/New_York` zone inference. |
| Census/HUD New Residential Construction | Census's [historical NRC releases](https://www.census.gov/construction/nrc/data/releases.html) explicitly provide historic reports and retain a release-header clock. The narrative identifies preliminary total privately-owned housing starts at SAAR. | Enumerated 278 PDFs from 2003-01 through 2026-06 and parsed 276. Six reference months remain gaps. The September/October 2013 entries preserve the official funding-lapse/link-mismatch evidence; four other months were not separately listed during combined-release periods. The April 2009 anchor's literal `fhttps` scheme typo is repaired to the otherwise printed Census URL and logged. |
| BLS CPI supplemental | The [official archive](https://www.bls.gov/cpi/tables/supplemental-files/home.htm) lists annual ZIP files starting in 2012 and current-year monthly XLSX files. BLS cautions that archived files may have been revised in later editions, especially the five years of seasonally adjusted indexes revised with each January release. The listing can contain missing months (for example, it identifies October 2025 as unavailable). | The complete listed inventory through June 2026 was acquired and parsed into 2,241 canonical rows: 138 modern XLSX plus 35 legacy XLS snapshots. The documented October 2025 gap remains missing. |
| BLS CPI release clocks | The official [CPI news-release archive](https://www.bls.gov/bls/news-release/cpi.htm) links historical release pages whose embargo headers print the release date, weekday, time, and `EST`, `EDT`, or `ET`. | All 221 linked events from 2008-02-20 through 2026-07-14 are inventoried and hashed at the header-text level. The evidence contains 220 browser-rendered HTML header extracts and one official-PDF extract for a blank rendered HTML page. It explicitly does not claim complete DOM capture or original server bytes. Printed dates, weekdays, and zones verify; all 173 acquired CPI target snapshots map to an exact clock. |
| BEA GDP archive | BEA provides a [data archive](https://apps.bea.gov/histdata/), a [news archive](https://www.bea.gov/news/archive), and a GDP/GDI vintage-history workbook from its [GDP page](https://www.bea.gov/data/gdp/gross-domestic-product). Products and coverage differ. BEA warns on archive pages that previously published estimates have since been revised. | All 1,053 published growth estimates across 98 quarters are parsed, and 98 official news pages prove each initial-release clock. The NIPA directory supplies 96 initial-release Section 1 workbooks for 2002Q3–2026Q2; 2002Q1/Q2 are explicit prearchive gaps. These yield 23,416 `GDPC1` levels and 96 same-snapshot growth validations. The stable pilot still uses published q/q SAAR values; the level-derived layer remains a separately labeled validation. |

## Completed acquisition and content/release-date verification (2026-08-10)

The operator explicitly requested acquisition and verification. The audit records the
official-source URLs, hashes, sizes, container checks, identifiers, and content findings in
`data/generated/agency_vintages/audit_manifest.json`. It uses no API credential and did not
read `api.txt`. Raw files and derived artifacts are local and Git-ignored. Production
parsing retains source hashes, release mappings, and download timestamps.

Run the same offline audit with:

```bash
make acquire-dol-claims
make acquire-fed-g17
make acquire-treasury-rates
make acquire-census-retail
make acquire-census-housing
make index-empsit-clocks
make acquire-bea-nipa-levels
make audit-bea-nipa-levels
make audit-agency-vintages
make ingest-agency-vintages
make reproduce-official-pilot
```

| Evidence file | Verified content | SHA-256 |
| --- | --- | --- |
| `cesvinall.zip` | CRC-valid BLS archive with 226 members. `tri_000000_SA.csv`, which maps to `CES0000000001`, has 273 vintage rows and 1,045 reference-month columns, from May 2003 through January 2026. Those rows map to 272 official release dates; October and November 2025 share the December 16 release. | `c8a0d98cecd10d1ed35097d75a9c07344c2f15abb472d9d0164a2a164e4ab9fc` |
| `bls-empsit-clock-txt/` | Fifty-six direct official TXT releases cover every pre-2008 Employment Situation event needed by the acquired CES target window. All headers verify against `America/New_York`; the files are indexed offline after ordinary browser download because automated command-line retrieval receives BLS access denial. The indexer performs no network request. | `release-index.json`: `e467b402c6cf15309b07aefc2f5a58a85cf607c4d9f61f2cd3902ad73c19f5f0`; per-release byte hashes are embedded in that index. |
| `bls-empsit-html/` | 221 complete official-page DOM exports. The first is `empsit_02012008.htm` (January 2008 results) and the last is `empsit_07022026.htm` (June 2026 results). All contain table A-1 and all content hashes are unique. The audit extracts 220 exact embargo clocks and retains one date-only conflict. | Per-file hashes and parsed timestamps are recorded in the manifest. The first hash is `4eaad38dc640c1e02e9b93ecd0a8cc330516462a84230e7bed448abd9e9e7cc6`; the last is `10aa16be74ccdf5c88abf75025c7f8ad947ef7620096c7f62664a7b435e148a2`; the conflicting 2012-12-07 page is `c76eb66a9e8cabf5055283b85cfc9acc755cdc5c539c635f51590dd5d2b495f2`. |
| `dol-ui-claims/` | 1,235 actual official weekly releases from 2002-10-17 through 2026-08-06, with 1,238 raw links retained. The audit validates every file hash, parses current and prior reported initial claims plus the directly published four-week average, and verifies release lags of four or five days. | Per-file hashes and the three explicit exclusions are recorded in `release-index.json`; that manifest's SHA-256 is `77925e9b29279e02a9545080ada335eec5b625ad4ad17a1287debc3606ec4c4c`. |
| `fed-g17/` | 367 original ASCII snapshots from 1997-12-15 through 2026-07-17. The audit verifies 343 monthly releases, 24 annual revisions, 367 unique content hashes, 8,612 canonical rows, exact file-header clocks, and six historical index base periods. | Per-release hashes are recorded in `release-index.json`; that manifest's SHA-256 is `18ab87588d5f6d70e00306591dbdb76eee9b629a01e333db9819970dbaa87a70`. |
| `treasury-yield-curve/` | Twenty-five original Treasury XML responses cover 2002–2026 and contain 6,154 unique 10-year CMT observations through 2026-08-07. The audit verifies every year, feed identity/update timestamp, value, count, and file hash. Availability is conservatively source-date New York EOD; no exact publication clock or correction-vintage dimension is claimed. | Per-year SHA-256 values, byte counts, feed-update timestamps, and coverage are pinned in `release-index.json`; the combined audit is recorded under `treasury_10y_daily_rates`. |
| `census-marts/` | 281 official reference-month PDFs were enumerated; 273 parseable releases span 2003-01 through 2026-05 and yield 546 canonical rows. All accepted hashes/keys and exact 8:30 a.m. clocks verify. Eight scanned PDFs without a text layer are preserved and explicitly excluded. | Per-release hashes and exclusions are recorded in `release-index.json`; that manifest's SHA-256 is `38344c2cee55879fd54e4f95557867f14f0e94f63f23040b148270ce742755a0`. |
| `census-nrc/` | 278 official housing-release PDFs were enumerated; 276 parseable releases span 2003-01 through 2026-06 and yield 276 canonical housing-start rows. Exact EST/EDT clocks verify. Six reference months remain explicit gaps, including two 2013 funding-lapse exclusions; the April 2009 `fhttps` index typo is logged. | Per-release hashes and exclusions are recorded in `release-index.json`; that manifest's SHA-256 is `b9334952c7f922591bf0b71873039d43b8530b80a3c9f37c092241f86e6b80a7`. |
| CPI annual/current collection | Thirteen CRC-valid annual ZIPs cover 2012–2024; 17 individually listed files cover 2025-01 through 2026-06, with BLS's documented 2025-10 gap preserved. The audit inventories 173 monthly workbooks and verifies “All items less food and energy” in all of them; 35 legacy XLS files are converted only in an isolated temporary directory for this content check. | Per-archive and per-file hashes are recorded in the manifest; the 2024 ZIP is `e8eeaccce382d4378b837d38b0c32d86d8efb05d92ab6df0ea04c02e59dffdf7`. |
| `bls-cpi-html/clock-evidence.json` | Hashed release-header evidence for all 221 CPI archive events: 49 `EST`, 101 `EDT`, and 71 `ET`. All dates, optional weekdays, and named-zone offsets verify. It supplies exact clocks for all 173 acquired CPI target snapshots. One blank HTML page uses the official PDF; the other 220 are rendered HTML header-text extracts. | `5f0ccc7483e2687cec4dda3c58d1640fb83b6742abd41245860c3fa990de3579`; the referenced local release-index hash is `2b028d2510d3f110c6f50878220b7d21109a3eaaa8ea4fd7806a229f6728231a`. |
| `gdp-gdi-vintage-history.xlsx` | Valid BEA workbook with 98 quarterly sections from 2002Q1 through 2026Q2. Every quarter has exactly one dated initial estimate (96 `Advance`, 2 `Initial`); all 1,053 estimate/revision rows have numeric growth and release-date text. It supplies published growth summaries, not the real-GDP levels required by the configured target. | `1007c2656689eb9a9c864acb62ce8ff396766e7eab90e039ff2cd8194d00355e` |
| `bea-gdp-news/clock-evidence.json` | Hashed release-header text for all 98 GDP initial releases from 2002-04-26 through 2026-07-30: 70 `EDT`, 28 `EST`, all at 8:30 a.m. Eastern. The audit reconciles all dates and `Advance`/`Initial` types to the vintage workbook. It records four wire-transmission, one embargoed-for-release, and 93 embargoed-until-release styles. Two archive-list dates are one day early; the page headers and workbook agree on the following day. The artifact claims neither complete DOM capture nor original server bytes. | `f0c2d62add75f74d59e1bbe7394809b5ac65b62422fbcd6f0c37742d534aae48`; the selected-link inventory hash is `6321f5fa0af37ce48331a55069d5720f69f2f51233ca89fe4ff2f61584bde5da`. |
| `bea-nipa-levels/` | The official directory inventory expects 98 initial releases from 2002Q1 through 2026Q2 and supplies 96, with only 2002Q1/Q2 missing. Sixty original XLS and 36 XLSX Section 1 workbooks yield 23,416 canonical `GDPC1` level vintages. Every target and prior level is present, all workbook publication dates match the verified clocks, and all 96 level-derived growth values are within 0.06 percentage point of published growth (94 round exactly to the published tenth; maximum difference 0.0519308). Thirty-one directory-label dates conflict with verified dates and remain recorded. | `release-index.json`: `b95feb69dbc762c5c193440130ec3cfb85f5297fb0438c098a17214f06fabcd5`; all original workbook and per-quarter file-inventory hashes are embedded. |
| `gdp_level_target_validation.parquet` | Ninety-six first-release q/q SAAR targets built through the production target layer. Both adjacent levels always come from the same release snapshot. The artifact is a validation cross-check and does not replace the published-growth pilot target. | `02776f067264002a0d1ddde1f284b76b3c7c2eb4e7cf3de1b3eaec44d7750146` |

The directory-label mismatch is systematic rather than a single 2024Q4 anomaly: 31 of the
96 available directories differ from the independently verified workbook/news-release
date. For example, the 2024Q4 directory says January 31, 2025, while the workbook and
[official release](https://www.bea.gov/news/2025/gross-domestic-product-4th-quarter-and-year-2024-advance-estimate)
say January 30. The audit preserves both fields and makes the verified release clock
authoritative. Workbooks span chained-dollar reference years 1996, 2000, 2005, 2009, 2012,
and 2017 and use both billions and millions scales. Therefore raw levels are not comparable
across snapshots; only adjacent-level growth calculated within one snapshot is supported.

The source audit remains `verified_with_limitations` because one BLS header has an EST/EDT
conflict and the NIPA directory has two prearchive gaps. All 56 acquired pre-2008 PAYEMS
events now have locally audited direct-TXT clocks. Verified Employment Situation, CPI, and
GDP events use each printed release clock; DOL claims retains its official 8:30 a.m. Eastern availability,
G.17 retains each file-header clock, Treasury 10-year observations use source-date New
York EOD, and MARTS/NRC retain each release's Eastern header clock. The G.17 audit preserves
the `20000215` archive path whose header says 2000-02-16;
for three 2026 files the header prints AM/PM rather than EST/EDT, so the New York zone is a
documented continuity inference rather than a directly printed label. Production parsers
and regression fixtures are now implemented. The downstream ingestion manifest records
`historical_ingestion_ready = true` under a mixed rule: exact target events use T−1 second,
while a date-only release uses the previous calendar day at New York EOD. The official
empirical pilot persists a full date-only timing counterfactual, keeps its primary GDP
target explicitly already transformed, and reports zero strict feature-timing violations.
The parallel 96-quarter level-derived artifact validates target construction but is not yet
a separately modeled empirical tier. Broader model and policy conclusions remain outside scope.

An archive audit must, at minimum:

1. Record the official index URL, retrieval timestamp, filenames, hashes, and file formats.
2. Identify missing releases, corrections, broken links, and format or classification changes.
3. Map every snapshot to a separately verified release date and, where published, release
   time.
4. Reconcile source series/table identifiers, units, seasonal adjustment, transformations,
   and revision type.
5. Validate a small set of first and later releases manually against official releases.
6. Add offline fixtures and parser tests before enabling ingestion.
7. Assign `first_release` only to rows proven to be the initial publication. Ambiguous rows
   remain unlabeled for vintage research rather than being guessed.

## Official release calendars

Calendar dates and times must come from original-provider pages, not inferred lags:

- BLS [Consumer Price Index schedule](https://www.bls.gov/schedule/news_release/cpi.htm)
- BLS [Employment Situation schedule](https://www.bls.gov/schedule/news_release/empsit.htm)
- BEA [release schedule](https://www.bea.gov/news/schedule/)
- Federal Reserve [G.17 release index](https://www.federalreserve.gov/releases/g17/default.htm)
- Census [MARTS release schedule](https://www.census.gov/retail/release_schedule.html)
- Census [New Residential Construction historical releases](https://www.census.gov/construction/nrc/data/releases.html)

**Project policy/inference:** scheduled dates are not proof that a release occurred exactly
as planned. Historical work must reconcile the schedule against the official release or
archive, preserve postponements/corrections, and store the agency's published time zone. If
only a date is defensible, the canonical date-only rule is used rather than inventing an
intraday timestamp.

## Terms, attribution, and public-domain status

Authorization is a workflow gate, not legal advice. A maintainer must review the current
terms before enabling live or archive access.

### BLS

- Access or use constitutes acceptance of the [BLS terms of service](https://www.bls.gov/developers/termsOfService.htm).
- API users must cite the retrieval date and clearly include BLS's required warning that
  BLS.gov cannot vouch for data or analyses after retrieval. The BLS logo cannot be used on
  a non-BLS-sponsored product, and modified content must not be falsely represented as BLS
  content.
- BLS states that, except where otherwise identified, information disseminated on its site
  is in the public domain; see [BLS copyright information](https://www.bls.gov/opub/copyright-information.htm).

Every BLS-derived report should record “U.S. Bureau of Labor Statistics,” the series ID,
retrieval date, direct source link, transformation performed by this project, and the
required post-retrieval disclaimer.

### BEA

- Registration requires agreement to the official [BEA API terms](https://apps.bea.gov/api/_pdf/bea_api_tos.pdf).
- The API terms require this prominent notice: “This product uses the Bureau of Economic
  Analysis (BEA) Data API but is not endorsed or certified by BEA.”
- BEA's [citation guidance](https://www.bea.gov/help/guidelines-for-citing-bea) requests
  appropriate citations and prohibits wording that suggests BEA endorsement.
- BEA states that its statistics and other materials are generally public domain; see the
  official [copyright FAQ](https://www.bea.gov/help/faq/147). Third-party material must be
  checked separately.

Every BEA-derived report should record “U.S. Bureau of Economic Analysis,” the dataset,
table and line, retrieval date, direct source link, transformation performed by this
project, and the required non-endorsement notice.

### Federal Reserve

- The Board's [copyright and public-domain notice](https://www.federalreserve.gov/disclaimer.htm)
  says United States government materials are generally in the public domain while logos,
  third-party content, and endorsement remain restricted.
- G.17 reports must cite the Board, dated release URL, retrieval timestamp, retained base
  period, and project transformation. No Board logo or endorsement claim is used.
- The H.15 archive was evaluated but not adopted as a post-2016 publication-vintage source.
  Its dated weekly snapshots run through September 2016, while later DDP history is not a
  collection of dated snapshots. The official pilot instead uses Treasury's direct daily
  10-year CMT point observations with conservative EOD eligibility and does not claim a
  later-correction vintage dimension.

### University of Michigan Surveys of Consumers

- Website data are copyrighted. The official usage agreement restricts reproduction,
  retransmission, distribution, sale, publication, and broadcast without express written
  consent.
- The FAQ's public-display guidance does not erase that broader restriction for a stored
  historical-release collection. The project therefore requires written permission matched
  to the operator's legal organization and intended derived outputs.
- Until the source-specific gate passes, no sentiment source file or extracted value may be
  downloaded, stored, parsed, or used in an empirical artifact.

### Census

- Census requests citation of the agency as the source and prohibits use of its logos to
  imply endorsement; see the official [citation policy](https://www.census.gov/about/policies/citation.html).
- MARTS-derived reports record the reference month, dated release URL, retrieval timestamp,
  source hash, published transformation, and every archive exclusion. Published monthly
  changes are not represented as calculations from the rounded narrative level.
- NRC-derived reports record the reference month, exact release header, source URL/hash,
  preliminary-status label, stored SAAR unit conversion, and every missing or excluded
  release. Current revised housing history is never substituted for a missing snapshot.
