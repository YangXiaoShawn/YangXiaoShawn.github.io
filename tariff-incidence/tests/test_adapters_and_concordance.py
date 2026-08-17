"""Adapter and concordance tests.

The Federal Register test runs against a committed excerpt of the real List 2
notice (83 FR 40823), so the parser is checked against genuine typeset output
rather than a hand-written mock. U.S. government works are not copyrighted.
"""

from __future__ import annotations

import pytest

from tariff_incidence.adapters.federal_register import (
    _normalize_page,
    _parse_partial_lines,
    parse_annex,
)
from tariff_incidence.adapters.usitc_hts import (
    HTSLine,
    baseline_source,
    hs6_children,
    parse_export_json,
    parse_rate,
    resolve_truncated_codes,
)
from tariff_incidence.concordance.hs import (
    ConcordanceLink,
    HSConcordance,
    MappingType,
    identity_concordance,
)
from tariff_incidence.paths import FIXTURES

FIXTURE = FIXTURES / "fr_2018-17709_annexA_excerpt.pdf"


# --------------------------------------------------------------------- #
# Federal Register annex parsing
# --------------------------------------------------------------------- #


@pytest.mark.skipif(not FIXTURE.exists(), reason="annex fixture not present")
def test_list2_annex_parses_to_the_count_stated_in_the_notice():
    """83 FR 40823 states 279 tariff lines; the parser must find exactly 279."""
    p = parse_annex(FIXTURE, "2018-17709")
    assert p.chapter99_heading == "9903.88.02"
    assert p.stated_line_count == 279
    assert p.parsed_line_count == 279
    assert p.count_matches_notice is True
    assert len(p.hts8_codes) == 279


@pytest.mark.skipif(not FIXTURE.exists(), reason="annex fixture not present")
def test_annex_parser_excludes_chapter_98_and_99_provisions():
    """9802.00.80 and 9903.88.02 are legal provisions, not covered product lines."""
    p = parse_annex(FIXTURE, "2018-17709")
    assert all(not c.startswith(("98", "99")) for c in p.hts8_codes)
    assert "98020080" in p.special_provision_codes
    assert "99038802" in p.special_provision_codes


@pytest.mark.skipif(not FIXTURE.exists(), reason="annex fixture not present")
def test_annex_codes_are_eight_digit_and_unique():
    p = parse_annex(FIXTURE, "2018-17709")
    assert all(len(c) == 8 and c.isdigit() for c in p.hts8_codes)
    assert len(set(p.hts8_codes)) == len(p.hts8_codes)


def test_parse_annex_rejects_a_document_without_the_operative_anchor(tmp_path):
    from pypdf import PdfWriter

    p = tmp_path / "empty.pdf"
    w = PdfWriter()
    w.add_blank_page(width=200, height=200)
    with p.open("wb") as fh:
        w.write(fh)
    with pytest.raises(ValueError, match="operative anchor sentence not found"):
        parse_annex(p, "FAKE")


def test_normalize_page_rejoins_a_code_split_across_a_line_break():
    assert "9401.71.0007" in _normalize_page("numbers 9401.\n71.0007;")
    assert "9401.71.0007" in _normalize_page("numbers 9401. 71.0007;")


def test_normalize_page_does_not_join_ordinary_sentence_punctuation():
    out = _normalize_page("effective in 2018. 5,745 lines were covered.")
    assert "2018. 5" in out


def test_partial_line_note_is_parsed_into_carve_outs():
    text = (
        "(g) For the purposes of heading 9903.88.04, products of China, as provided for in "
        "this note, shall be subject to an additional 10 percent ad valorem rate of duty. "
        "1. Other non-aromatic compounds, provided for in 2931.90.90, except for such "
        "compounds provided for in statistical reporting number 2931.90.9051; "
        "2. Other upholstered seats, provided for in 9401.71.00, except for such seats "
        "provided for in statistical reporting numbers 9401.71.0001, 9401.71.0005;"
    )
    out = _parse_partial_lines([text], 0)
    assert out["29319090"] == ["2931909051"]
    assert out["94017100"] == ["9401710001", "9401710005"]


def test_partial_line_parser_returns_nothing_without_the_note_header():
    assert _parse_partial_lines(["provided for in 2931.90.90, except for such"], 0) == {}


# --------------------------------------------------------------------- #
# USITC HTS
# --------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("text", "expected", "pure"),
    [
        ("Free", 0.0, True),
        ("4.4%", 0.044, True),
        ("  2.5 %  ", 0.025, True),
        ("2.5 cents/kg", None, False),
        ("7.5% + 1.4 cents/kg", None, False),
        ("", None, False),
    ],
)
def test_parse_rate_never_invents_an_ad_valorem_equivalent(text, expected, pure):
    rate, is_pure = parse_rate(text)
    assert rate == (pytest.approx(expected) if expected is not None else None)
    assert is_pure is pure


def test_parse_export_json_collapses_to_eight_digit_lines():
    payload = """[
      {"htsno":"8471.30.01.00","general":"Free","description":"Portable ADP","units":["No."]},
      {"htsno":"8471.30.01.20","general":"Free","description":"variant","units":["No."]},
      {"htsno":"8471.41.01.00","general":"4.4%","description":"Other","units":["No."]},
      {"htsno":"8471","general":"","description":"heading","units":[]}
    ]"""
    lines = parse_export_json(payload)
    assert [x.hts8 for x in lines] == ["84713001", "84714101"]
    assert lines[0].general_ad_valorem == 0.0
    assert lines[1].general_ad_valorem == pytest.approx(0.044)


def test_baseline_source_falls_back_to_the_nearest_earlier_vintage():
    src = baseline_source([HTSLine(None, "84713001", "d", "Free", 0.0, True)], 2018)
    assert src.get("84713001", 2020) == 0.0
    assert src.get("99999999", 2018) is None


def test_hs6_children_groups_by_heading():
    lines = [
        HTSLine(None, "84713001", "", "Free", 0.0, True),
        HTSLine(None, "84713002", "", "Free", 0.0, True),
        HTSLine(None, "84714101", "", "4.4%", 0.044, True),
    ]
    assert hs6_children(lines) == {"847130": ["84713001", "84713002"], "847141": ["84714101"]}


def test_truncated_code_resolves_only_when_the_deduction_is_unique():
    lines = [
        HTSLine(None, "90330020", "", "Free", 0.0, True),
        HTSLine(None, "90330030", "", "Free", 0.0, True),
        HTSLine(None, "90330090", "", "4.4%", 0.044, True),
    ]
    resolved, still = resolve_truncated_codes(
        ["9033.00"], {"90330020", "90330030"}, lines
    )
    assert resolved == {"9033.00": "90330090"}
    assert still == []


def test_truncated_code_stays_unresolved_when_two_candidates_remain():
    lines = [
        HTSLine(None, "90330020", "", "Free", 0.0, True),
        HTSLine(None, "90330030", "", "Free", 0.0, True),
        HTSLine(None, "90330090", "", "4.4%", 0.044, True),
    ]
    resolved, still = resolve_truncated_codes(["9033.00"], {"90330020"}, lines)
    assert resolved == {}
    assert still == ["9033.00"]


# --------------------------------------------------------------------- #
# HS concordance
# --------------------------------------------------------------------- #


def test_identity_concordance_marks_codes_stable():
    c = identity_concordance(["847130", "940161"], ["HS2017", "HS2018", "HS2019"])
    assert c.is_stable("847130", ["HS2017", "HS2018", "HS2019"])
    assert c.stable_codes(["847130", "940161"], ["HS2017", "HS2018"]) == ["847130", "940161"]


def test_one_to_many_split_is_detected_and_makes_a_code_unstable():
    c = HSConcordance(
        [
            ConcordanceLink("847130", "847130", "HS2017", "HS2018", 0.6),
            ConcordanceLink("847130", "847141", "HS2017", "HS2018", 0.4),
        ]
    )
    links = c.map_code("847130", "HS2017", "HS2018")
    assert len(links) == 2
    assert all(x.mapping_type is MappingType.ONE_TO_MANY for x in links)
    assert not c.is_stable("847130", ["HS2017", "HS2018"])


def test_many_to_one_merge_is_detected():
    c = HSConcordance(
        [
            ConcordanceLink("847130", "847199", "HS2017", "HS2018", 1.0),
            ConcordanceLink("847141", "847199", "HS2017", "HS2018", 1.0),
        ]
    )
    assert c.map_code("847130", "HS2017", "HS2018")[0].mapping_type is MappingType.MANY_TO_ONE


def test_renumbered_code_is_not_treated_as_stable():
    c = HSConcordance([ConcordanceLink("847130", "847131", "HS2017", "HS2018", 1.0)])
    assert not c.is_stable("847130", ["HS2017", "HS2018"])


def test_unmapped_code_is_reported_unresolved_not_silently_kept():
    c = HSConcordance([ConcordanceLink("847130", "847130", "HS2017", "HS2018", 1.0)])
    rep = c.report(["847130", "999999"], ["HS2017", "HS2018"])
    assert "999999" in rep.unresolved_from
    assert rep.stable_codes == ["847130"]


def test_apply_to_panel_splits_values_by_weight():
    import polars as pl

    panel = pl.DataFrame({"hs6": ["847130"], "customs_value": [100.0], "quantity": [10.0]})
    c = HSConcordance(
        [
            ConcordanceLink("847130", "847130", "HS2017", "HS2018", 0.6),
            ConcordanceLink("847130", "847141", "HS2017", "HS2018", 0.4),
        ]
    )
    out = c.apply_to_panel(panel, from_vintage="HS2017", to_vintage="HS2018")
    assert out.height == 2
    assert out["customs_value"].sum() == pytest.approx(100.0)
    assert set(out["concordance_mapping_type"]) == {"ONE_TO_MANY"}


# --------------------------------------------------------------------- #
# multi-annex notices and annex boundaries
# --------------------------------------------------------------------- #

LIST3 = FIXTURES.parent.parent / "data" / "raw" / "federal_register" / "2018-20610.pdf"
LIST4 = FIXTURES.parent.parent / "data" / "raw" / "federal_register" / "2019-17865.pdf"


@pytest.mark.skipif(not LIST3.exists(), reason="List 3 notice not cached")
def test_partial_line_note_spanning_the_next_annex_header_is_not_truncated():
    """List 3's note 20(g) runs onto the page that carries the ANNEX B header.

    Scoping the note to whole pages cuts three of its eleven carve-outs, which
    silently breaks the exact reconciliation against the notice's stated count.
    """
    p = parse_annex(LIST3, "2018-20610")
    assert len(p.partial_lines) == 11
    for code in ("94018060", "94037040", "94037080"):
        assert code in p.partial_lines, f"{code} sits above the ANNEX header on a shared page"
    assert p.parsed_line_count == p.stated_line_count == 5745
    assert p.count_matches_notice is True


@pytest.mark.skipif(not LIST4.exists(), reason="List 4 notice not cached")
def test_a_notice_carrying_two_actions_yields_one_annex_each():
    from tariff_incidence.adapters.federal_register import parse_all_annexes

    d = parse_all_annexes(LIST4, "2019-17865")
    headings = [a.chapter99_heading for a in d.annexes]
    assert headings == ["9903.88.15", "9903.88.16"], "List 4A then List 4B"
    assert d.by_heading("9903.88.15") is not None
    assert d.by_heading("9903.88.99") is None


@pytest.mark.skipif(not LIST4.exists(), reason="List 4 notice not cached")
def test_each_annex_keeps_its_own_carve_outs():
    """Unscoped, the first annex would absorb the second's partial lines."""
    from tariff_incidence.adapters.federal_register import parse_all_annexes

    d = parse_all_annexes(LIST4, "2019-17865")
    a, c = d.annexes[0].partial_lines, d.annexes[1].partial_lines
    assert a and c
    assert a != c, "the two annexes must not end up with the same carve-out set"
    assert set(a) & set(c) == {"94017100"}


@pytest.mark.skipif(
    not (LIST3.exists() and LIST4.exists()), reason="notices not cached"
)
def test_one_line_is_divided_across_three_actions_with_overlapping_carve_outs():
    """9401.71.00 is partial in Lists 3, 4A and 4B, and the carve-outs overlap.

    Each note excludes the statistical numbers that belong to the *other*
    actions, and because the actions were legislated at different times those
    exclusion sets are not a partition. An earlier version of this test assumed
    they were disjoint; they are not, and asserting a tidy partition would have
    encoded a guess as a fact.
    """
    from tariff_incidence.adapters.federal_register import parse_all_annexes

    code = "94017100"
    l3 = parse_annex(LIST3, "2018-20610").partial_lines[code]
    d4 = parse_all_annexes(LIST4, "2019-17865")
    l4a = d4.annexes[0].partial_lines[code]
    l4b = d4.annexes[1].partial_lines[code]

    assert set(l3) == {"9401710001", "9401710005", "9401710006", "9401710007"}
    assert set(l4a) == {
        "9401710001", "9401710005", "9401710006", "9401710008", "9401710011",
    }
    assert set(l4b) == {"9401710007", "9401710008", "9401710011", "9401710031"}
    assert set(l4a) & set(l4b), "the sets overlap; they do not partition the line"
    assert len(set(l3) | set(l4a) | set(l4b)) == 7


@pytest.mark.skipif(not LIST4.exists(), reason="List 4 notice not cached")
def test_multi_action_notice_defers_count_validation_to_the_document():
    """No figure in this notice's preamble refers to one annex alone."""
    from tariff_incidence.adapters.federal_register import parse_all_annexes

    d = parse_all_annexes(LIST4, "2019-17865")
    for a in d.annexes:
        assert a.stated_line_count is None
        assert any("deferred to the document level" in w for w in a.warnings)
    assert d.parsed_total == sum(a.parsed_line_count for a in d.annexes)
