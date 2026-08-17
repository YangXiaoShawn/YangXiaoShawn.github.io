"""Panel-construction and data-quality tests.

Covers acceptance criteria 4 (panel produced), 5 (quantity-unit inconsistencies
detected) and 6 (customs and tariff-inclusive unit values separately labelled).
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from tariff_incidence.panel.build import (
    _month_segments,
    add_event_time,
    add_extensive_margin,
    add_pretreatment_exposure,
    add_sourcing_measures,
    build_panel,
    construct_value_measures,
)
from tariff_incidence.quality import checks
from tariff_incidence.tariff.engine import BaselineRateSource, TariffEngine
from tariff_incidence.tariff.records import RecordType, SourceRef, TariffRecord

CHINA = "5700"
VIETNAM = "5520"


def _src() -> SourceRef:
    return SourceRef("2018-20610", "83 FR 47974", "t", "u", "2018-09-21", "0" * 64)


def _engine() -> TariffEngine:
    r = TariffRecord(
        record_id="r1", episode_id="e", action_id="SEC301_LIST3",
        record_type=RecordType.ADDITIONAL_DUTY, product_code="84713001",
        product_code_level=8, product_code_vintage="HTS2018",
        partner_country_code=CHINA, announcement_date=date(2018, 7, 17),
        effective_date=date(2018, 9, 24), expiry_date=None, ad_valorem_rate=0.10,
        source=_src(),
    )
    return TariffEngine(
        [r],
        baseline=BaselineRateSource({("84713001", 2018): 0.02, ("84714101", 2018): 0.02}),
        hs6_children={"847130": ["84713001"], "847141": ["84714101"]},
    )


def _staged() -> pl.DataFrame:
    months = [date(2018, m, 1) for m in range(1, 13)]
    rows = []
    for m in months:
        for hs6 in ["847130", "847141"]:
            for c in [CHINA, VIETNAM]:
                treated = hs6 == "847130" and c == CHINA and m >= date(2018, 10, 1)
                qty = 100.0 if not treated else 80.0
                val = 1000.0
                rows.append(
                    {
                        "hs6": hs6, "country_code": c, "country_name": c,
                        "month_date": m,
                        "con_val_mo": val, "gen_val_mo": val * 1.01,
                        "dut_val_mo": val, "cal_dut_mo": val * (0.12 if treated else 0.02),
                        "con_cha_mo": val * 0.05,
                        "con_qy1_mo": qty, "unit_qy1": "NO",
                        "con_qy2_mo": None, "unit_qy2": "",
                    }
                )
    return pl.DataFrame(rows)


# --------------------------------------------------------------------- #
# value concepts
# --------------------------------------------------------------------- #


def test_unit_value_concepts_are_separately_labelled_and_ordered():
    df = construct_value_measures(_staged())
    for col in [
        "customs_unit_value",
        "landed_unit_value_duty_inclusive",
        "landed_unit_value_full",
        "cif_value",
        "dutiable_value",
        "calculated_duties",
        "import_charges",
    ]:
        assert col in df.columns
    r = df.row(0, named=True)
    assert r["customs_unit_value"] < r["landed_unit_value_duty_inclusive"] < r["landed_unit_value_full"]


def test_customs_value_excludes_import_charges():
    df = construct_value_measures(_staged())
    r = df.row(0, named=True)
    assert r["cif_value"] == pytest.approx(r["customs_value"] + r["import_charges"])


def test_unit_value_is_null_when_quantity_is_zero():
    s = _staged().with_columns(pl.lit(0.0).alias("con_qy1_mo"))
    df = construct_value_measures(s)
    assert df["customs_unit_value"].null_count() == df.height


# --------------------------------------------------------------------- #
# within-month day weighting
# --------------------------------------------------------------------- #


def test_month_containing_the_effective_date_is_partially_treated():
    """List 3 took effect 24 September 2018: 7 of the month's 30 days."""
    e = _engine()
    segs = _month_segments(date(2018, 9, 1), e, "84713001", CHINA)
    assert sum(d for _, d in segs) == 30
    assert [d for _, d in segs] == [23, 7]


def test_month_without_a_regime_change_is_a_single_segment():
    e = _engine()
    assert len(_month_segments(date(2018, 11, 1), e, "84713001", CHINA)) == 1


def test_day_weighted_rate_is_between_zero_and_the_statutory_rate():
    panel = build_panel(
        _staged(), _engine(), treated_country_code=CHINA, pre_period_end=date(2018, 6, 30)
    )
    sep = panel.filter(
        (pl.col("hs6") == "847130")
        & (pl.col("country_code") == CHINA)
        & (pl.col("month_date") == date(2018, 9, 1))
    ).row(0, named=True)
    assert 0.0 < sep["additional_tariff_rate"] < 0.10
    assert sep["additional_tariff_rate"] == pytest.approx(0.10 * 7 / 30)
    assert sep["tariff_regime_changed_within_month"] is True
    assert sep["additional_tariff_rate_month_start"] == 0.0
    assert sep["additional_tariff_rate_month_end"] == pytest.approx(0.10)


# --------------------------------------------------------------------- #
# panel structure
# --------------------------------------------------------------------- #


def test_build_panel_produces_a_product_country_month_panel():
    panel = build_panel(
        _staged(), _engine(), treated_country_code=CHINA, pre_period_end=date(2018, 6, 30)
    )
    assert panel.height == 12 * 2 * 2
    assert panel.select(["hs6", "country_code", "month_date"]).unique().height == panel.height


def test_event_time_is_defined_for_control_countries_of_a_treated_product():
    """Otherwise there is no comparison group within the treated product."""
    panel = build_panel(
        _staged(), _engine(), treated_country_code=CHINA, pre_period_end=date(2018, 6, 30)
    )
    vn = panel.filter((pl.col("hs6") == "847130") & (pl.col("country_code") == VIETNAM))
    assert vn["event_time"].null_count() == 0
    assert vn["ever_treated_product"].all()


def test_never_treated_product_has_no_event_time():
    panel = build_panel(
        _staged(), _engine(), treated_country_code=CHINA, pre_period_end=date(2018, 6, 30)
    )
    other = panel.filter(pl.col("hs6") == "847141")
    assert other["event_time"].null_count() == other.height
    assert not other["ever_treated_product"].any()


def test_sourcing_shares_sum_to_one_within_product_month():
    df = add_sourcing_measures(
        construct_value_measures(_staged()), treated_country_code=CHINA
    )
    tot = df.group_by(["hs6", "month_date"]).agg(pl.col("supplier_value_share").sum())
    assert all(abs(v - 1.0) < 1e-9 for v in tot["supplier_value_share"])


def test_pretreatment_exposure_uses_only_the_pre_window():
    df = add_pretreatment_exposure(
        construct_value_measures(_staged()),
        treated_country_code=CHINA,
        pre_period_end=date(2018, 6, 30),
    )
    assert df["pretreatment_treated_country_share"].max() == pytest.approx(0.5)


def test_extensive_margin_flags_entry_and_exit():
    s = _staged()
    s = s.with_columns(
        pl.when(
            (pl.col("hs6") == "847130")
            & (pl.col("country_code") == VIETNAM)
            & (pl.col("month_date") >= date(2018, 6, 1))
        )
        .then(0.0)
        .otherwise(pl.col("con_val_mo"))
        .alias("con_val_mo")
    )
    df = add_extensive_margin(
        add_event_time(construct_value_measures(s).with_columns(pl.lit(False).alias("treated")))
    )
    ex = df.filter(pl.col("flow_exit"))
    assert ex.height == 1
    assert ex.row(0, named=True)["month_date"] == date(2018, 6, 1)


# --------------------------------------------------------------------- #
# data-quality checks
# --------------------------------------------------------------------- #


def _panel() -> pl.DataFrame:
    return build_panel(
        _staged(), _engine(), treated_country_code=CHINA, pre_period_end=date(2018, 6, 30)
    )


def test_quality_battery_runs_and_reports_every_check():
    res = checks.run_all(_panel(), valid_country_codes={CHINA, VIETNAM})
    ids = {r.check_id for r in res}
    for expected in [
        "DUP_KEY", "BAD_COUNTRY", "BAD_PRODUCT_CODE", "UNIT_CHANGE",
        "NEGATIVE_VALUES", "MISSING_DUTIES", "PANEL_GAPS", "TARIFF_AMBIGUOUS",
    ]:
        assert expected in ids
    summary = checks.summarize(res)
    assert summary["n_checks"] == len(res)


def test_clean_panel_has_no_blocking_failures():
    res = checks.run_all(_panel(), valid_country_codes={CHINA, VIETNAM})
    assert checks.summarize(res)["blocking"] == []


def test_quantity_unit_change_is_detected():
    """Acceptance criterion 5."""
    s = _staged().with_columns(
        pl.when(pl.col("month_date") >= date(2018, 7, 1))
        .then(pl.lit("KG"))
        .otherwise(pl.lit("NO"))
        .alias("unit_qy1")
    )
    panel = build_panel(s, _engine(), treated_country_code=CHINA, pre_period_end=date(2018, 6, 30))
    res = {r.check_id: r for r in checks.run_all(panel, valid_country_codes={CHINA, VIETNAM})}
    assert res["UNIT_CHANGE"].passed is False
    assert res["UNIT_CHANGE"].n_flagged == 4


def test_duplicate_rows_are_detected():
    panel = pl.concat([_panel(), _panel().head(2)])
    res = {r.check_id: r for r in checks.run_all(panel)}
    assert res["DUP_KEY"].passed is False


def test_invalid_country_code_is_detected():
    panel = _panel()
    res = {r.check_id: r for r in checks.run_all(panel, valid_country_codes={CHINA})}
    assert res["BAD_COUNTRY"].passed is False


def test_check_without_inputs_is_reported_skipped_not_passed():
    res = {r.check_id: r for r in checks.run_all(_panel())}
    assert res["BAD_COUNTRY"].passed is None
    assert res["BAD_COUNTRY"].to_row()["status"] == "SKIPPED"


def test_negative_values_are_detected():
    s = _staged().with_columns(
        pl.when(pl.col("month_date") == date(2018, 3, 1))
        .then(-5.0)
        .otherwise(pl.col("con_val_mo"))
        .alias("con_val_mo")
    )
    panel = build_panel(s, _engine(), treated_country_code=CHINA, pre_period_end=date(2018, 6, 30))
    res = {r.check_id: r for r in checks.run_all(panel)}
    assert res["NEGATIVE_VALUES"].passed is False


# --------------------------------------------------------------------- #
# HS10 staging and HS6 aggregation
# --------------------------------------------------------------------- #


def _census_like() -> pl.DataFrame:
    """Mimics a raw Census HS10 payload, including its "no quantity" convention."""
    return pl.DataFrame(
        {
            "I_COMMODITY": ["8471300100", "8471300150", "8471410100", "8471410150"],
            "CTY_CODE": [CHINA] * 4,
            "CTY_NAME": ["CHINA"] * 4,
            "CON_VAL_MO": [1000.0, 500.0, 2000.0, 300.0],
            "GEN_VAL_MO": [1010.0, 505.0, 2020.0, 303.0],
            "DUT_VAL_MO": [1000.0, 500.0, 2000.0, 300.0],
            "CAL_DUT_MO": [20.0, 10.0, 40.0, 6.0],
            "CON_CHA_MO": [50.0, 25.0, 100.0, 15.0],
            # Census emits 0 with unit "-" when no quantity is collected.
            "CON_QY1_MO": [100.0, 0.0, 200.0, 40.0],
            "UNIT_QY1": ["NO", "-", "NO", "KG"],
            "CON_QY2_MO": [0.0, 0.0, 0.0, 0.0],
            "UNIT_QY2": ["-", "-", "-", "-"],
            "month_date": [date(2018, 10, 1)] * 4,
        }
    )


def test_stage_census_treats_uncollected_quantity_as_null_not_zero():
    """A unit of '-' means no quantity collected; zero would make unit values infinite."""
    from tariff_incidence.panel.build import stage_census

    s = stage_census(_census_like(), product_col="hs10")
    row = s.filter(pl.col("hs10") == "8471300150").row(0, named=True)
    assert row["con_qy1_mo"] is None
    assert row["unit_qy1"] == ""
    assert row["quantity_not_collected"] is True
    kept = s.filter(pl.col("hs10") == "8471300100").row(0, named=True)
    assert kept["con_qy1_mo"] == pytest.approx(100.0)
    assert kept["quantity_not_collected"] is False


def test_unit_value_is_null_where_quantity_was_not_collected():
    from tariff_incidence.panel.build import stage_census

    df = construct_value_measures(stage_census(_census_like(), product_col="hs10"))
    row = df.filter(pl.col("hs10") == "8471300150").row(0, named=True)
    assert row["customs_unit_value"] is None


def test_hs6_aggregation_sums_values_but_refuses_to_sum_mixed_units():
    """847141 mixes NO and KG, so its aggregate quantity has no meaning."""
    from tariff_incidence.panel.build import aggregate_to_hs6, stage_census

    agg = aggregate_to_hs6(stage_census(_census_like(), product_col="hs10"))
    clean = agg.filter(pl.col("hs6") == "847130").row(0, named=True)
    mixed = agg.filter(pl.col("hs6") == "847141").row(0, named=True)

    assert clean["con_val_mo"] == pytest.approx(1500.0)
    assert clean["con_qy1_mo"] == pytest.approx(100.0)  # only the NO-unit line contributes
    assert clean["hs6_units_mixed"] is False

    assert mixed["con_val_mo"] == pytest.approx(2300.0), "values always add"
    assert mixed["con_qy1_mo"] is None, "pieces and kilograms must not be summed"
    assert mixed["hs6_units_mixed"] is True


def test_tariff_assessment_is_keyed_on_hs8_so_hs10_siblings_agree():
    """HS10 nests exactly inside the HS8 line the statute names."""
    from tariff_incidence.panel.build import attach_tariff_treatment, stage_census

    staged = stage_census(_census_like(), product_col="hs10")
    out = attach_tariff_treatment(staged, _engine(), product_col="hs10")
    sibs = out.filter(pl.col("hs10").str.starts_with("84713001"))
    assert sibs.height == 2
    assert sibs["additional_tariff_rate"].n_unique() == 1
    assert sibs["tariff_status"].n_unique() == 1


def test_hs10_panel_has_no_partial_hs6_coverage_status():
    """The partial-coverage problem is an artefact of aggregating above the statute."""
    from tariff_incidence.panel.build import attach_tariff_treatment, stage_census

    out = attach_tariff_treatment(
        stage_census(_census_like(), product_col="hs10"), _engine(), product_col="hs10"
    )
    assert "PARTIAL_HS6_COVERAGE" not in set(out["tariff_status"])
    assert out["tariff_usable_for_treatment"].all()
