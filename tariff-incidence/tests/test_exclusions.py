"""USTR product-exclusion adapter tests.

Exercised against the committed real notice where available, and against
synthetic text for the parsing rules themselves, so the suite runs offline.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from tariff_incidence.adapters.ustr_exclusions import (
    ExclusionNotice,
    coverage_summary,
    parse_notice,
    realised_vs_statutory_bound,
)
from tariff_incidence.paths import RAW

REAL = RAW / "federal_register" / "2018-28277.pdf"


@pytest.mark.skipif(not REAL.exists(), reason="exclusion notice PDF not cached")
def test_first_exclusion_notice_reports_its_own_split():
    """83 FR 67463 states seven 10-digit subheadings and 24 product descriptions."""
    n = parse_notice(REAL, "2018-28277", "2018-12-28")
    assert n.n_ten_digit_exclusions == 7
    assert n.n_prose_exclusions == 24
    assert n.n_total == 31


@pytest.mark.skipif(not REAL.exists(), reason="exclusion notice PDF not cached")
def test_exclusions_are_retroactive_to_the_action_not_the_publication():
    """The distinction that makes exclusion windows different from list windows."""
    n = parse_notice(REAL, "2018-28277", "2018-12-28")
    assert n.retroactive_to == "2018-07-06"
    assert n.retroactive_to < n.publication_date
    assert n.expires == "2019-12-28"  # one year after publication


@pytest.mark.skipif(not REAL.exists(), reason="exclusion notice PDF not cached")
def test_annex_is_detected_as_image_only_and_yields_no_codes():
    """The annex is a raster image; nothing is invented to fill the gap."""
    n = parse_notice(REAL, "2018-28277", "2018-12-28")
    assert n.annex_is_image_only
    assert n.parsed_ten_digit_codes == []
    assert any("no text layer" in w for w in n.warnings)


def test_coverage_summary_reports_the_mappable_share():
    notices = [
        ExclusionNotice(
            "a", "2018-12-28", n_ten_digit_exclusions=7, n_prose_exclusions=24
        ),
        ExclusionNotice(
            "b", "2019-03-25", n_ten_digit_exclusions=3, n_prose_exclusions=30
        ),
    ]
    s = coverage_summary(notices)
    assert s["n_ten_digit_exclusions"] == 10
    assert s["n_prose_exclusions"] == 54
    assert s["mappable_share"] == pytest.approx(10 / 64)


def test_coverage_summary_handles_a_notice_with_no_mappable_exclusions():
    s = coverage_summary(
        [
            ExclusionNotice(
                "a", "2019-04-18", n_ten_digit_exclusions=0, n_prose_exclusions=21
            )
        ]
    )
    assert s["mappable_share"] == 0.0
    assert s["n_total_exclusions"] == 21


def test_itt_bound_flags_only_flows_where_realised_falls_short():
    panel = pl.DataFrame(
        {
            "month_date": [
                __import__("datetime").date(2019, 1, 1),
                __import__("datetime").date(2019, 1, 1),
            ],
            "is_treated_country": [True, True],
            "total_modeled_tariff_rate": [0.25, 0.25],
            "additional_tariff_rate": [0.25, 0.25],
            "realised_duty_rate_on_dutiable": [0.25, 0.02],  # second is short
            "dutiable_value": [100.0, 100.0],
            "customs_value": [100.0, 300.0],
        }
    )
    out = realised_vs_statutory_bound(panel)
    row = out.row(0, named=True)
    assert row["n_short"] == 1
    assert row["share_value_short"] == pytest.approx(0.75)


def test_itt_bound_ignores_untreated_flows():
    import datetime as dt

    panel = pl.DataFrame(
        {
            "month_date": [dt.date(2019, 1, 1)],
            "is_treated_country": [False],
            "total_modeled_tariff_rate": [0.25],
            "additional_tariff_rate": [0.25],
            "realised_duty_rate_on_dutiable": [0.0],
            "dutiable_value": [100.0],
            "customs_value": [100.0],
        }
    )
    assert realised_vs_statutory_bound(panel) is None


def test_parse_notice_warns_when_the_form_sentence_is_absent(tmp_path: Path):
    from pypdf import PdfWriter

    p = tmp_path / "blank.pdf"
    w = PdfWriter()
    w.add_blank_page(width=200, height=200)
    with p.open("wb") as fh:
        w.write(fh)
    n = parse_notice(p, "FAKE", "2019-01-01")
    assert any("take the form of" in x for x in n.warnings)
    assert n.n_prose_exclusions is None


def test_itt_bound_excludes_flows_carrying_no_additional_duty():
    """MFN-dutiable trade with no Section 301 duty is not part of this bound.

    The filter conditioned on `total_modeled_tariff_rate > 0`, which includes
    the baseline MFN rate, so ordinary MFN-dutiable imports entered the
    denominator. They can never fall short of a Section 301 duty, because none
    applies, so they contributed zero to the numerator and halved the apparent
    pre-exclusion baseline -- the exact quantity the bound decomposes against.
    """
    import datetime as dt

    panel = pl.DataFrame(
        {
            "month_date": [dt.date(2018, 3, 1), dt.date(2019, 1, 1)],
            "is_treated_country": [True, True],
            # First flow: MFN duty only, no Section 301 action in force yet.
            "total_modeled_tariff_rate": [0.044, 0.294],
            "additional_tariff_rate": [0.0, 0.25],
            "realised_duty_rate_on_dutiable": [0.044, 0.02],
            "dutiable_value": [100.0, 100.0],
            "customs_value": [900.0, 100.0],
        }
    )
    out = realised_vs_statutory_bound(panel)

    # Only the Section 301 month survives; the MFN-only month is not a period
    # in which an exclusion could have applied.
    assert out.height == 1
    assert out["month_date"][0] == dt.date(2019, 1, 1)
    # Had the MFN-only flow been admitted its $900 would have sat in the
    # denominator alone and driven the shortfall share to 0.1 instead of 1.0.
    assert out["share_value_short"][0] == pytest.approx(1.0)
