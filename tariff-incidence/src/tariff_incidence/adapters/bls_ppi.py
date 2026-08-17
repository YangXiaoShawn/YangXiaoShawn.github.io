"""BLS Producer Price Index adapter (NAICS industry classification).

Endpoint: ``https://api.bls.gov/publicAPI/v1/timeseries/data/`` (v1, no key,
25 series and 10 years per request).

Why the industry classification and not the commodity one
--------------------------------------------------------

The PPI is published under two systems: commodity codes (``WPU...``) and NAICS
industry codes (``PCU...``). This project's tariff exposure is built at NAICS
via the official Census import concordance, so the industry series match it
directly. Using the commodity series would mean a second, undocumented
crosswalk between two classifications that were never designed to align — the
exact "forcing a product classification onto a broad price series" that the
project's own data rules warn against.

Series ID construction
----------------------

An industry-level series is ``PCU`` + industry code + product code, each padded
to six characters with hyphens. For an industry index the two are the same
code::

    NAICS 325  ->  PCU325---325---
    NAICS 3361 ->  PCU3361--3361--

What is genuinely missing
-------------------------

Not every BEA summary industry has an industry-classification PPI, and the gaps
are recorded rather than papered over with a substitute from the commodity
system:

* **Agriculture, forestry and fishing** (NAICS 111-115, i.e. BEA ``111CA`` and
  ``113FF``) have no NAICS-industry PPI at all. They are reported as unmatched.
* **NAICS 316** (leather and allied products) has no series, so BEA ``315AL``
  is matched by its 315 component alone.

Where a BEA summary industry aggregates several NAICS groups, the available
component series are averaged **unweighted**, because the weights that would be
needed — output by NAICS component — are not available at that granularity in
the BEA summary tables. Every industry therefore carries a match-quality flag,
and a partial or composite match is never presented as an exact one.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Any

import polars as pl

from .base import SourceUnavailable

BLS_V1 = "https://api.bls.gov/publicAPI/v1/timeseries/data/"
MAX_SERIES_PER_REQUEST = 25
MAX_YEARS_PER_REQUEST = 10


class PPIMatchQuality(str, Enum):
    EXACT = "EXACT"
    """The BEA industry is one NAICS group and that group has a series."""

    COMPOSITE_UNWEIGHTED = "COMPOSITE_UNWEIGHTED"
    """Several NAICS components, all available, averaged without weights."""

    PARTIAL_COMPOSITE = "PARTIAL_COMPOSITE"
    """Several components, only some of which have a series."""

    NONE = "NONE"
    """No industry-classification PPI exists for this industry."""


#: BEA summary industry -> the NAICS groups it comprises.
#:
#: Originally hand-coded from BEA's published summary definitions. It has since
#: been checked against the ``NAICS Codes`` sheet that BEA ships in the detail
#: workbooks (``bea_io.load_naics_hierarchy``), which gives the same grouping;
#: see ``tests/test_ppi_propagation.py``. The detail level does not use this
#: dict at all -- it derives components from BEA's own sheet.
BEA_TO_NAICS: dict[str, tuple[str, ...]] = {
    "111CA": ("111", "112"),
    "113FF": ("113", "114", "115"),
    "211": ("211",),
    "212": ("212",),
    "213": ("213",),
    "311FT": ("311", "312"),
    "313TT": ("313", "314"),
    "315AL": ("315", "316"),
    "321": ("321",),
    "322": ("322",),
    "323": ("323",),
    "324": ("324",),
    "325": ("325",),
    "326": ("326",),
    "327": ("327",),
    "331": ("331",),
    "332": ("332",),
    "333": ("333",),
    "334": ("334",),
    "335": ("335",),
    "337": ("337",),
    "339": ("339",),
    "3361MV": ("3361", "3362", "3363"),
    "3364OT": ("3364", "3365", "3366", "3369"),
}


def series_id(naics: str) -> str:
    """PPI industry series ID for a NAICS group."""
    code = naics.strip()
    return f"PCU{code.ljust(6, '-')}{code.ljust(6, '-')}"


@dataclass(slots=True)
class PPILoad:
    """Fetched PPI series plus what could not be matched."""

    observations: pl.DataFrame
    """series_id, naics, year, month, month_date, index_value."""
    industry_match: pl.DataFrame
    """bea_industry, naics_components, matched_components, match_quality."""
    n_series_requested: int = 0
    n_series_returned: int = 0
    warnings: list[str] = field(default_factory=list)


def available() -> bool:
    """The v1 endpoint needs no key, but it has been down before."""
    try:
        _post(["PCU325---325---"], 2019, 2019, cache_tag="probe")
    except SourceUnavailable:
        return False
    return True


def _post(
    series: list[str], start_year: int, end_year: int, *, cache_tag: str = "", force: bool = False
) -> dict[str, Any]:
    """POST a series request, caching the raw response by content."""
    import hashlib

    payload = json.dumps(
        {
            "seriesid": series,
            "startyear": str(start_year),
            "endyear": str(end_year),
        },
        sort_keys=True,
    )
    tag = cache_tag or hashlib.sha256(payload.encode()).hexdigest()[:12]
    name = f"bls_ppi_{start_year}_{end_year}_{tag}.json"

    from .base import RAW, USER_AGENT

    dest = RAW / "bls" / name
    if dest.exists() and not force:
        cached: dict[str, Any] = json.loads(dest.read_text())
        return cached

    import httpx

    try:
        with httpx.Client(timeout=180.0, headers={"User-Agent": USER_AGENT}) as client:
            resp = client.post(
                BLS_V1, content=payload, headers={"Content-Type": "application/json"}
            )
            resp.raise_for_status()
            body = resp.text
    except (httpx.HTTPError, OSError) as exc:
        raise SourceUnavailable(f"BLS PPI request failed: {exc}") from None

    if body.lstrip().startswith("<"):
        raise SourceUnavailable(
            "BLS returned HTML rather than JSON; the service has previously been "
            "down for maintenance and answers with a status page"
        )
    doc: dict[str, Any] = json.loads(body)
    if doc.get("status") != "REQUEST_SUCCEEDED":
        raise SourceUnavailable(
            f"BLS request not succeeded: {doc.get('status')} {doc.get('message')}"
        )
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(body)
    return doc


def _series_cache_path(sid: str, year: int) -> Path:
    from .base import RAW

    return RAW / "bls" / "series" / f"{sid}_{year}.json"


def _load_cached_series(ids: list[str], y0: int, y1: int) -> tuple[dict[str, Any], list[str]]:
    """Split requested series into those already cached and those still needed.

    The v1 endpoint allows only a small number of requests per address per day,
    so the cache granularity decides how much of that allowance a re-run costs.
    Hashing the whole request payload meant one extra industry invalidated every
    chunk. Caching **per series and per year** means a run that already holds
    2019 and now wants 2017-2019 asks only for what it is missing -- BLS tags
    every observation with its year, so splitting a response is exact rather
    than an approximation.

    A year with no observations is cached as an empty list on purpose: "this
    series does not cover 2017" is a fact worth remembering, and re-asking for
    it every run would spend the allowance on a known answer.
    """
    have: dict[str, Any] = {}
    missing: list[str] = []
    for sid in ids:
        paths = [_series_cache_path(sid, y) for y in range(y0, y1 + 1)]
        if not all(p.exists() for p in paths):
            missing.append(sid)
            continue
        data: list[Any] = []
        for p in paths:
            data.extend(json.loads(p.read_text()))
        have[sid] = {"seriesID": sid, "data": data}
    return have, missing


def _write_cached_series(sid: str, y0: int, y1: int, payload: Any) -> None:
    """Split one series response into per-year files covering the whole window."""
    by_year: dict[int, list[Any]] = {y: [] for y in range(y0, y1 + 1)}
    for obs in payload.get("data", []):
        try:
            year = int(obs["year"])
        except (KeyError, TypeError, ValueError):
            continue
        if year in by_year:
            by_year[year].append(obs)
    for year, obs_list in by_year.items():
        p = _series_cache_path(sid, year)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(obs_list))


def seed_series_cache_from_raw_responses() -> int:
    """Populate the per-series cache from raw responses already on disk.

    Raw request/response bodies are kept for provenance; earlier runs and
    coverage probes left many of them. Reading them back costs no allowance and
    is exactly equivalent to having fetched those series-years today.
    """
    from .base import RAW

    n = 0
    for path in sorted((RAW / "bls").glob("bls_ppi_*.json")):
        stem = path.stem.split("_")
        try:
            y0, y1 = int(stem[2]), int(stem[3])
        except (IndexError, ValueError):
            continue
        try:
            doc = json.loads(path.read_text())
        except json.JSONDecodeError:
            continue
        for s in doc.get("Results", {}).get("series", []):
            sid = s.get("seriesID")
            if not sid:
                continue
            _write_cached_series(sid, y0, y1, s)
            n += 1
    return n


def fetch_industry_ppi(
    bea_industries: list[str],
    start_year: int,
    end_year: int,
    *,
    components: dict[str, tuple[str, ...]] | None = None,
    force: bool = False,
) -> PPILoad:
    """Fetch NAICS-industry PPI for the NAICS groups behind each BEA industry.

    ``components`` overrides the built-in summary map; the detail level passes
    the industry-to-NAICS relation read from BEA's own ``NAICS Codes`` sheet.
    """
    table = components if components is not None else BEA_TO_NAICS
    wanted: dict[str, list[str]] = {}
    for bea in bea_industries:
        defined = table.get(bea)
        if defined:
            wanted[bea] = list(defined)

    all_naics = sorted({n for comps in wanted.values() for n in comps})
    ids = [series_id(n) for n in all_naics]

    rows: list[dict[str, Any]] = []
    returned: set[str] = set()
    quota_exhausted = False
    for y0 in range(start_year, end_year + 1, MAX_YEARS_PER_REQUEST):
        y1 = min(y0 + MAX_YEARS_PER_REQUEST - 1, end_year)
        cached, missing = ({}, list(ids)) if force else _load_cached_series(ids, y0, y1)
        fetched: dict[str, Any] = dict(cached)
        for i in range(0, len(missing), MAX_SERIES_PER_REQUEST):
            chunk = missing[i : i + MAX_SERIES_PER_REQUEST]
            try:
                doc = _post(chunk, y0, y1, force=force)
            except SourceUnavailable as exc:
                # The daily request allowance is a hard external limit, not a
                # failure of this code. Estimating on the subset that happened
                # to be cached would silently change the sample, so the caller
                # is told and no partial panel is passed off as complete.
                if "threshold" in str(exc).lower() and fetched:
                    quota_exhausted = True
                    break
                raise
            by_id = {s["seriesID"]: s for s in doc.get("Results", {}).get("series", [])}
            for sid in chunk:
                payload = by_id.get(sid, {"seriesID": sid, "data": []})
                _write_cached_series(sid, y0, y1, payload)
                fetched[sid] = payload
        if quota_exhausted:
            raise SourceUnavailable(
                f"BLS daily request allowance reached with {len(ids) - len(fetched)} of "
                f"{len(ids)} series still unfetched for {y0}-{y1}. Cached series are kept, "
                "so a re-run after the allowance resets fetches only the remainder."
            )
        for sid, s in fetched.items():
            if not s.get("data"):
                continue
            returned.add(sid)
            naics = sid[3:9].replace("-", "")
            for obs in s["data"]:
                period = obs.get("period", "")
                if not period.startswith("M") or period == "M13":
                    continue  # M13 is the annual average, not a month
                month = int(period[1:])
                try:
                    value = float(obs["value"])
                except (TypeError, ValueError):
                    continue
                rows.append(
                    {
                        "series_id": sid,
                        "naics": naics,
                        "year": int(obs["year"]),
                        "month": month,
                        "month_date": date(int(obs["year"]), month, 1),
                        "index_value": value,
                    }
                )

    obs_df = (
        pl.DataFrame(rows).unique(subset=["series_id", "month_date"]).sort(["naics", "month_date"])
        if rows
        else pl.DataFrame(
            schema={
                "series_id": pl.String, "naics": pl.String, "year": pl.Int64,
                "month": pl.Int64, "month_date": pl.Date, "index_value": pl.Float64,
            }
        )
    )

    match_rows: list[dict[str, Any]] = []
    warnings: list[str] = []
    for bea, comps in wanted.items():
        got: list[str] = [n for n in comps if series_id(n) in returned]
        if not got:
            q = PPIMatchQuality.NONE
        elif len(comps) == 1:
            q = PPIMatchQuality.EXACT
        elif len(got) == len(comps):
            q = PPIMatchQuality.COMPOSITE_UNWEIGHTED
        else:
            q = PPIMatchQuality.PARTIAL_COMPOSITE
        match_rows.append(
            {
                "bea_industry": bea,
                "naics_components": "|".join(comps),
                "matched_components": "|".join(got),
                "n_components": len(comps),
                "n_matched": len(got),
                "match_quality": q.value,
            }
        )
        if q is PPIMatchQuality.NONE:
            warnings.append(
                f"{bea}: no NAICS-industry PPI exists for {'/'.join(comps)}; reported "
                "unmatched rather than substituted from the commodity classification"
            )
        elif q is PPIMatchQuality.PARTIAL_COMPOSITE:
            missing = [n for n in comps if n not in got]
            warnings.append(
                f"{bea}: matched by {'/'.join(got)} only; no series for {'/'.join(missing)}"
            )

    load = PPILoad(
        observations=obs_df,
        industry_match=pl.DataFrame(match_rows),
        n_series_requested=len(ids),
        n_series_returned=len(returned),
        warnings=warnings,
    )
    if len(returned) < len(ids):
        load.warnings.append(
            f"{len(ids) - len(returned)} of {len(ids)} requested series returned no data"
        )
    return load


def to_bea_panel(load: PPILoad) -> pl.DataFrame:
    """Collapse NAICS series to a BEA-summary industry x month price panel.

    Composite industries are averaged **unweighted** across their available
    components. Output weights by NAICS component would be preferable and are
    not available at that granularity in the BEA summary tables, so the choice
    is recorded on every row via ``match_quality`` rather than left implicit.
    """
    if load.observations.height == 0:
        return pl.DataFrame()

    pairs: list[dict[str, Any]] = []
    for r in load.industry_match.iter_rows(named=True):
        for n in (r["matched_components"] or "").split("|"):
            if n:
                pairs.append(
                    {"bea_industry": r["bea_industry"], "naics": n, "match_quality": r["match_quality"]}
                )
    if not pairs:
        return pl.DataFrame()

    link = pl.DataFrame(pairs)
    joined = load.observations.join(link, on="naics", how="inner")
    panel = (
        joined.group_by(["bea_industry", "month_date"])
        .agg(
            pl.col("index_value").mean().alias("ppi_index"),
            pl.col("naics").n_unique().alias("n_component_series"),
            pl.col("match_quality").first().alias("ppi_match_quality"),
        )
        .sort(["bea_industry", "month_date"])
    )
    return panel.with_columns(
        pl.col("ppi_index").log().alias("log_ppi"),
        (pl.col("month_date").dt.year() * 12 + pl.col("month_date").dt.month()).alias(
            "month_index"
        ),
    )
