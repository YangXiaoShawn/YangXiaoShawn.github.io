"""BEA detail-level input-output tables and the official NAICS hierarchy.

The detail level exists for one reason: the summary level gives 22 industries
with a matched producer-price series, and 22 clusters cannot separate the
exposure channels from noise. These tests cover the parsing hazards that stand
between the published workbook and a usable industry axis.
"""

from __future__ import annotations

import polars as pl
import pytest

from tariff_incidence.adapters import bea_io
from tariff_incidence.adapters.base import RAW
from tariff_incidence.adapters.bls_ppi import BEA_TO_NAICS

BEA_ZIP = RAW / "bea" / "AllTablesSUP.zip"
needs_zip = pytest.mark.skipif(not BEA_ZIP.exists(), reason="BEA AllTablesSUP.zip not cached")


def test_code_row_is_identified_by_content_not_position():
    """Summary writes codes above names; detail writes them below.

    Keying on position silently transposed the two in the detail workbook,
    producing an industry axis labelled "Abrasive product manufacturing"
    instead of "327910". Nothing downstream would have failed -- the join would
    simply have matched nothing.
    """
    codes = (None, None, "1111A0", "1111B0", "111200")
    names = (None, None, "Oilseed farming", "Grain farming", "Vegetable and melon farming")
    assert bea_io._looks_like_code_row(codes)
    assert not bea_io._looks_like_code_row(names)


def test_footnote_rows_are_not_industries():
    """A trailing note sat in the code column and became a 72nd 'industry'."""
    assert not bea_io._plausible_code("Note.  Detail may not add to total due to rounding.")
    assert not bea_io._plausible_code("")
    assert bea_io._plausible_code("1111A0")
    assert bea_io._plausible_code("111CA")


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("311111", ["311111"]),
        ("1112", ["1112"]),
        ("311511-2", ["311511", "311512"]),
        ("11113-6", ["11113", "11114", "11115", "11116"]),
        ("213112-5", ["213112", "213113", "213114", "213115"]),
        ("23*", ["23"]),
        ("n.a.", []),
        ("", []),
    ],
)
def test_naics_relation_tokens_expand_to_exactly_what_bea_wrote(token, expected):
    assert bea_io._expand_naics_token(token) == expected


def test_unrecognised_token_is_dropped_rather_than_guessed():
    """An unfamiliar form must not be turned into a plausible-looking code."""
    assert bea_io._expand_naics_token("see note 4") == []
    assert bea_io._expand_naics_token("3AB") == []


@needs_zip
def test_summary_and_detail_both_parse_with_codes_as_codes():
    summary = bea_io.load_tables(2017, level="summary")
    detail = bea_io.load_tables(2017, level="detail")

    for tables, floor in ((summary, 60), (detail, 350)):
        inds = tables.direct_requirements["industry_code"].unique().to_list()
        assert len(inds) >= floor
        # Codes, not titles: no spaces, short.
        assert all(bea_io._plausible_code(i) for i in inds)

    assert detail.direct_requirements["industry_code"].n_unique() > 5 * (
        summary.direct_requirements["industry_code"].n_unique()
    )


@needs_zip
def test_direct_requirements_are_shares_that_sum_to_one():
    for level in ("summary", "detail"):
        t = bea_io.load_tables(2017, level=level)
        sums = (
            t.direct_requirements.group_by("industry_code")
            .agg(pl.col("direct_requirement").sum().alias("s"))["s"]
            .to_list()
        )
        assert all(abs(s - 1.0) < 1e-9 for s in sums)


def test_detail_tables_refuse_a_non_benchmark_year():
    """BEA publishes detail only for 2007/2012/2017; interpolating invents weights."""
    with pytest.raises(ValueError, match="benchmark"):
        bea_io.load_tables(2018, level="detail")


@needs_zip
def test_hierarchy_covers_every_detail_industry_with_a_parent():
    h = bea_io.load_naics_hierarchy()
    assert h.height > 500
    assert h["bea_detail"].n_unique() == h.height
    assert h.filter(pl.col("bea_summary") == "").height == 0


@needs_zip
def test_hand_coded_summary_map_agrees_with_bea_published_hierarchy():
    """The summary NAICS map was hand-written before BEA's own sheet was found.

    If the two disagreed, every exposure result built on the hand-coded version
    would need restating. They agree, and this test is what keeps that true.
    """
    h = bea_io.load_naics_hierarchy()
    implied: dict[str, set[str]] = {}
    for r in h.iter_rows(named=True):
        code = r["bea_detail"]
        if code[:3].isdigit():
            implied.setdefault(r["bea_summary"], set()).add(code[:3])

    for summary, comps in BEA_TO_NAICS.items():
        if summary not in implied:
            continue
        hand = {c[:3] for c in comps}
        assert hand == implied[summary], (
            f"{summary}: hand-coded {sorted(hand)} vs BEA hierarchy {sorted(implied[summary])}"
        )


@needs_zip
def test_naics_is_assigned_to_the_narrowest_claiming_industry():
    """A NAICS code claimed by both a broad and a narrow industry goes narrow."""
    res = bea_io.naics_to_bea_detail(["311511", "111200"])
    by_naics = {r["naics"]: r for r in res.mapping.iter_rows(named=True)}
    assert by_naics["311511"]["match_depth"] == 6
    assert by_naics["311511"]["bea_detail"] == "31151A"
    # 111200's relation is written at four digits, so that is the depth used.
    assert by_naics["111200"]["match_depth"] == 4


@needs_zip
def test_equal_depth_ties_are_reported_not_broken_arbitrarily():
    hierarchy = pl.DataFrame(
        [
            {"bea_sector": "31", "bea_summary": "311FT", "bea_u_summary": "311",
             "bea_detail": "311AAA", "industry_title": "A", "related_naics": "311111"},
            {"bea_sector": "31", "bea_summary": "311FT", "bea_u_summary": "311",
             "bea_detail": "311BBB", "industry_title": "B", "related_naics": "311111"},
        ]
    )
    res = bea_io.naics_to_bea_detail(["311111"], hierarchy=hierarchy)
    assert res.mapping.height == 0
    assert res.ambiguous.height == 1
    assert res.ambiguous["candidates"][0] == "311AAA|311BBB"


@needs_zip
def test_industries_without_a_naics_relation_get_no_components():
    """Owner-occupied housing and scrap have no NAICS counterpart at all."""
    comps = bea_io.detail_naics_components(["531HSO", "1111A0"])
    assert "531HSO" not in comps
    assert comps["1111A0"] == ("11111", "11112")
