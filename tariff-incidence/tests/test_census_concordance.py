"""Census import-concordance adapter tests."""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from tariff_incidence.adapters.census_concordance import (
    ConcordanceLoad,
    _repair_retired_naics,
    build_hs10_to_bea,
    load_vintages,
    naics_to_bea_summary,
    parse_concordance,
)
from tariff_incidence.paths import RAW

REAL = RAW / "census_concordance" / "impconcord20.xlsx"


@pytest.mark.parametrize(
    ("naics", "expected"),
    [
        ("334413", "334"),      # semiconductors -> computer and electronic products
        ("332999", "332"),      # fabricated metal
        ("336111", "3361MV"),   # automobiles -> the motor-vehicle composite
        ("336411", "3364OT"),   # aircraft -> other transportation equipment
        ("311111", "311FT"),    # food -> food, beverage and tobacco
        ("313210", "313TT"),    # textile mills
        ("315220", "315AL"),    # apparel
        ("112920", "111CA"),    # animal production -> farms
        ("211120", "211"),      # oil and gas extraction
    ],
)
def test_naics_maps_to_the_documented_bea_summary_industry(naics, expected):
    assert naics_to_bea_summary(naics) == expected


def test_longer_composite_prefix_wins_over_the_three_digit_fallback():
    """3361 must resolve to the motor-vehicle composite, not to a bare 336."""
    assert naics_to_bea_summary("336112") == "3361MV"
    assert naics_to_bea_summary("336510") == "3364OT"


def test_unmappable_naics_returns_none_rather_than_a_guess():
    assert naics_to_bea_summary("999999") is None
    assert naics_to_bea_summary("") is None
    assert naics_to_bea_summary("541511") is None  # services, outside the IO groups used


def test_census_x_placeholder_still_maps_when_the_prefix_is_unambiguous():
    """Census writes X where it aggregates undisclosed detail."""
    assert naics_to_bea_summary("33251X") == "332"
    assert naics_to_bea_summary("11211X") == "111CA"


def test_a_corrupt_workbook_raises_rather_than_returning_an_empty_mapping(tmp_path: Path):
    """Legacy .xls is supported now, but a damaged file must still fail loudly:
    an empty concordance would silently drop every industry assignment."""
    p = tmp_path / "impconcord19.xls"
    p.write_bytes(b"not really a workbook")
    with pytest.raises(Exception, match="(?i)(corrupt|unsupported|BOF)"):
        parse_concordance(p, 2019)


@pytest.mark.skipif(not REAL.exists(), reason="concordance workbook not cached")
def test_official_concordance_is_keyed_on_ten_digit_lines():
    load = parse_concordance(REAL, 2020)
    assert load.n_rows > 15000
    codes = load.mapping["hs10"].to_list()
    assert all(len(c) == 10 and c.isdigit() for c in codes[:500])
    assert len(set(codes)) == len(codes), "one NAICS per commodity line, no duplicates"


@pytest.mark.skipif(not REAL.exists(), reason="concordance workbook not cached")
def test_official_concordance_reaches_a_bea_industry_for_almost_every_line():
    load = parse_concordance(REAL, 2020)
    _, q = build_hs10_to_bea(load)
    assert q["share_mapped"] > 0.95
    assert q["n_distinct_bea"] >= 20
    assert q["n_unmapped_to_bea"] > 0, "unmapped lines are counted, not hidden"
    assert any("outside the BEA summary" in w for w in q["warnings"])


@pytest.mark.skipif(not REAL.exists(), reason="concordance workbook not cached")
def test_aggregated_naics_codes_are_reported_not_truncated():
    load = parse_concordance(REAL, 2020)
    assert load.n_aggregated_naics > 0
    withx = load.mapping.filter(load.mapping["naics"].str.contains("X"))
    assert withx.height == load.n_aggregated_naics
    assert all("X" in n for n in withx["naics"].to_list()[:20])


# --------------------------------------------------------------------- #
# per-year vintages
# --------------------------------------------------------------------- #

XLS = RAW / "census_concordance" / "impconcord19.xls"


@pytest.mark.skipif(not XLS.exists(), reason="legacy .xls vintage not cached")
def test_legacy_xls_vintages_are_readable():
    """Census published .xls through 2019; refusing them forced a 2020 mapping
    onto a 2017-2019 panel, so both formats must load."""
    load = parse_concordance(XLS, 2019)
    assert load.n_rows > 15000
    codes = load.mapping["hs10"].to_list()
    assert all(len(c) == 10 and c.isdigit() for c in codes[:200])


@pytest.mark.skipif(not XLS.exists(), reason="legacy .xls vintage not cached")
def test_numeric_cells_do_not_lose_leading_zeros():
    """xlrd returns floats, so 0101210010 arrives as 101210010.0."""
    load = parse_concordance(XLS, 2019)
    assert "0101210010" in set(load.mapping["hs10"].to_list())


@pytest.mark.skipif(not XLS.exists(), reason="vintages not cached")
def test_vintage_stack_prefers_the_pre_treatment_assignment():
    from tariff_incidence.adapters.census_concordance import load_vintages

    st = load_vintages([2019, 2020], primary_year=2019)
    assert st.primary_year == 2019
    assert st.n_from_primary > st.n_from_fallback
    rows = st.mapping.filter(st.mapping["vintage_year"] == 2019)
    assert rows.height == st.n_from_primary


@pytest.mark.skipif(not XLS.exists(), reason="vintages not cached")
def test_vintage_stack_counts_reclassification_rather_than_hiding_it():
    from tariff_incidence.adapters.census_concordance import load_vintages

    st = load_vintages([2017, 2020], primary_year=2017)
    assert st.n_reclassified_vs_primary > 0, "NAICS was revised between 2017 and 2020"
    assert st.reclassified_examples
    ex = st.reclassified_examples[0]
    assert ex["naics_2017"] != ex["naics_2020"]
    assert any("different NAICS in a later vintage" in w for w in st.warnings)


@pytest.mark.skipif(not XLS.exists(), reason="vintages not cached")
def test_later_vintages_only_add_codes_the_primary_lacks():
    from tariff_incidence.adapters.census_concordance import load_vintages

    st = load_vintages([2017, 2020], primary_year=2017)
    primary_codes = set(
        st.mapping.filter(st.mapping["vintage_year"] == 2017)["hs10"].to_list()
    )
    later_codes = set(
        st.mapping.filter(st.mapping["vintage_year"] != 2017)["hs10"].to_list()
    )
    assert primary_codes and later_codes
    assert not (primary_codes & later_codes), "a code takes its assignment from one vintage"


def test_vintage_stack_rejects_a_primary_outside_the_requested_years():
    from tariff_incidence.adapters.census_concordance import load_vintages

    with pytest.raises(ValueError, match="not among"):
        load_vintages([2019, 2020], primary_year=2015)


def test_vintage_stack_requires_at_least_one_year():
    from tariff_incidence.adapters.census_concordance import load_vintages

    with pytest.raises(ValueError, match="no concordance vintages"):
        load_vintages([])


def test_retired_naics_codes_are_repaired_from_the_same_line_not_by_hand():
    """Census moved this concordance to 2017 NAICS with the 2019 vintage.

    A 2017-vintage line can therefore carry a code that does not exist in 2017
    NAICS at all, while BEA's 2017 tables are on 2017 NAICS. "The primary
    vintage governs" has no meaning when the primary's answer is not a code in
    the target classification, so the successor is taken from the same HS line
    in the revised vintage -- one official source, nothing mapped by hand.
    """
    loads = {
        2017: ConcordanceLoad(
            vintage_year=2017,
            source_file="fixture-2017",
            mapping=pl.DataFrame(
                {
                    "hs10": ["8413600050", "8479899899", "8516604082"],
                    "naics": ["333911", "333999", "335221"],
                }
            ),
        ),
        2019: ConcordanceLoad(
            vintage_year=2019,
            source_file="fixture-2019",
            mapping=pl.DataFrame(
                {
                    "hs10": ["8413600050", "8479899899", "8516604082", "8479100000"],
                    "naics": ["333914", "333249", "335220", "333999"],
                }
            ),
        ),
    }
    combined = pl.DataFrame(
        {
            "hs10": ["8413600050", "8479899899", "8516604082"],
            "naics": ["333911", "333999", "335221"],
            "bea_summary": ["333", "333", "335"],
            "vintage_year": [2017, 2017, 2017],
        }
    )
    repaired, repairs = _repair_retired_naics(combined, loads, [2017, 2019])
    # 333999 is still in use in the latest vintage, just not on this line -- so
    # this is a reclassification, not a retirement, and the primary keeps governing.
    got = dict(zip(repaired["hs10"], repaired["naics"], strict=True))

    # Retired: 333911 and 335221 are absent from the 2019 code universe.
    assert got["8413600050"] == "333914"
    assert got["8516604082"] == "335220"
    # 333999 still exists in 2019, so this line is a genuine reclassification
    # and the pre-determined primary-vintage assignment keeps governing.
    assert got["8479899899"] == "333999"
    assert {r["retired_naics"] for r in repairs} == {"333911", "335221"}


def test_a_line_with_no_successor_is_left_alone_rather_than_guessed():
    """If the HS line itself is gone, there is nothing official to map to."""
    loads = {
        2017: ConcordanceLoad(
            vintage_year=2017,
            source_file="fixture-2017",
            mapping=pl.DataFrame({"hs10": ["8413600050"], "naics": ["333911"]}),
        ),
        2019: ConcordanceLoad(
            vintage_year=2019,
            source_file="fixture-2019",
            mapping=pl.DataFrame({"hs10": ["9999999999"], "naics": ["333914"]}),
        ),
    }
    combined = pl.DataFrame(
        {"hs10": ["8413600050"], "naics": ["333911"], "bea_summary": ["333"],
         "vintage_year": [2017]}
    )
    repaired, repairs = _repair_retired_naics(combined, loads, [2017, 2019])
    assert repaired["naics"][0] == "333911"
    assert repairs == []


def test_repairs_never_move_an_industry_across_a_three_digit_group():
    """Summary-level results aggregate at three digits and must not move.

    This is the property that makes the repair safe to apply everywhere rather
    than only at detail level: if it held only by accident, summary-level
    exposure would silently change under it.
    """
    stack = load_vintages([2017, 2018, 2019, 2020], primary_year=2017)
    for r in stack.naics_vintage_repairs:
        assert r["retired_naics"][:3] == r["successor_naics"][:3], r
