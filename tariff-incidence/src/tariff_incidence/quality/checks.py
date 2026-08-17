"""Data-quality checks.

Two rules govern this module.

**Nothing is dropped silently.** Checks *flag*; they do not delete. Where an
exclusion rule is applied downstream, the original value, the rule, the reason
and a sensitivity result are all preserved so a reader can see what the estimate
would have been without the exclusion.

**A check that cannot run is reported as skipped**, never as passed. A green
report that hides three inapplicable checks is worse than a red one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

import polars as pl


class Severity(str, Enum):
    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"


@dataclass(slots=True)
class CheckResult:
    check_id: str
    description: str
    severity: Severity
    passed: bool | None  # None = skipped / not applicable
    n_flagged: int
    n_total: int
    detail: str = ""
    examples: list[dict] = field(default_factory=list)

    @property
    def share_flagged(self) -> float:
        return self.n_flagged / self.n_total if self.n_total else 0.0

    def to_row(self) -> dict:
        return {
            "check_id": self.check_id,
            "description": self.description,
            "severity": self.severity.value,
            "status": "SKIPPED" if self.passed is None else ("PASS" if self.passed else "FAIL"),
            "n_flagged": self.n_flagged,
            "n_total": self.n_total,
            "share_flagged": self.share_flagged,
            "detail": self.detail,
        }


def _ex(df: pl.DataFrame, cols: list[str], k: int = 3) -> list[dict]:
    keep = [c for c in cols if c in df.columns]
    return df.select(keep).head(k).to_dicts()


def run_all(
    panel: pl.DataFrame,
    *,
    product_col: str = "hs6",
    country_col: str = "country_code",
    month_col: str = "month_date",
    valid_country_codes: set[str] | None = None,
    unit_value_z_threshold: float = 5.0,
    jump_log_threshold: float = 2.5,
) -> list[CheckResult]:
    """Run the full data-quality battery over an analytical panel."""
    n = panel.height
    out: list[CheckResult] = []
    key = [product_col, country_col, month_col]
    ident = [*key, "customs_value", "quantity", "quantity_unit"]

    # 1. Duplicate keys ----------------------------------------------------
    dups = panel.group_by(key).len().filter(pl.col("len") > 1)
    out.append(
        CheckResult(
            "DUP_KEY",
            "duplicate product-country-month rows",
            Severity.ERROR,
            dups.height == 0,
            int(dups["len"].sum() - dups.height) if dups.height else 0,
            n,
            f"{dups.height} duplicated keys",
            _ex(dups, key),
        )
    )

    # 2. Country codes -----------------------------------------------------
    if valid_country_codes:
        bad = panel.filter(~pl.col(country_col).is_in(list(valid_country_codes)))
        out.append(
            CheckResult(
                "BAD_COUNTRY",
                "country code not in the configured universe",
                Severity.ERROR,
                bad.height == 0,
                bad.height,
                n,
                f"{bad[country_col].n_unique() if bad.height else 0} distinct bad codes",
                _ex(bad, ident),
            )
        )
    else:
        out.append(
            CheckResult(
                "BAD_COUNTRY", "country code validity", Severity.ERROR, None, 0, n,
                "skipped: no country-code universe supplied",
            )
        )

    # 3. Product codes -----------------------------------------------------
    badp = panel.filter(
        ~pl.col(product_col).str.contains(r"^\d{6}(\d{2})?(\d{2})?$")
    )
    out.append(
        CheckResult(
            "BAD_PRODUCT_CODE",
            "product code is not a 6-, 8- or 10-digit HS code",
            Severity.ERROR,
            badp.height == 0,
            badp.height,
            n,
            "",
            _ex(badp, ident),
        )
    )

    # 4. Quantity-unit changes within a product-country flow ---------------
    if "quantity_unit" in panel.columns:
        units = (
            panel.filter(pl.col("quantity_unit").is_not_null() & (pl.col("quantity_unit") != ""))
            .group_by([product_col, country_col])
            .agg(pl.col("quantity_unit").n_unique().alias("n_units"))
            .filter(pl.col("n_units") > 1)
        )
        out.append(
            CheckResult(
                "UNIT_CHANGE",
                "quantity unit changes within a product-country flow (unit values not comparable)",
                Severity.ERROR,
                units.height == 0,
                units.height,
                n,
                f"{units.height} flows change unit of measure",
                _ex(units, [product_col, country_col, "n_units"]),
            )
        )
    else:
        out.append(
            CheckResult("UNIT_CHANGE", "quantity-unit stability", Severity.ERROR, None, 0, n,
                        "skipped: no quantity_unit column")
        )

    # 5. Non-positive values ----------------------------------------------
    neg = panel.filter(
        (pl.col("customs_value") < 0)
        | (pl.col("quantity").fill_null(0) < 0)
        | (pl.col("calculated_duties").fill_null(0) < 0)
    )
    out.append(
        CheckResult(
            "NEGATIVE_VALUES",
            "negative customs value, quantity or duties",
            Severity.ERROR,
            neg.height == 0,
            neg.height,
            n,
            "",
            _ex(neg, ident),
        )
    )
    zero_q = panel.filter((pl.col("customs_value") > 0) & (pl.col("quantity").fill_null(0) <= 0))
    out.append(
        CheckResult(
            "ZERO_QUANTITY_POSITIVE_VALUE",
            "positive value with zero or missing quantity (unit value undefined)",
            Severity.WARN,
            zero_q.height == 0,
            zero_q.height,
            n,
            "unit values are null for these rows and they drop out of log-price regressions",
            _ex(zero_q, ident),
        )
    )

    # 6. Extreme unit values (within product-country, robust z) ------------
    if "log_customs_unit_value" in panel.columns:
        stats = (
            panel.filter(pl.col("log_customs_unit_value").is_finite())
            .group_by([product_col, country_col])
            .agg(
                pl.col("log_customs_unit_value").median().alias("_med"),
                pl.col("log_customs_unit_value").std().alias("_sd"),
            )
        )
        j = panel.join(stats, on=[product_col, country_col], how="left")
        ext = j.filter(
            pl.col("log_customs_unit_value").is_finite()
            & (pl.col("_sd") > 0)
            & (
                ((pl.col("log_customs_unit_value") - pl.col("_med")).abs() / pl.col("_sd"))
                > unit_value_z_threshold
            )
        )
        out.append(
            CheckResult(
                "EXTREME_UNIT_VALUE",
                f"customs unit value beyond {unit_value_z_threshold} SD of the flow median",
                Severity.WARN,
                ext.height == 0,
                ext.height,
                n,
                "flagged, NOT removed; winsorising sensitivity is reported separately",
                _ex(ext, [*ident, "customs_unit_value"]),
            )
        )

    # 7. Duties inconsistent with the policy engine ------------------------
    if {"realised_duty_rate_on_dutiable", "total_modeled_tariff_rate"} <= set(panel.columns):
        cmp_df = panel.filter(
            pl.col("realised_duty_rate_on_dutiable").is_not_null()
            & pl.col("total_modeled_tariff_rate").is_not_null()
            & (pl.col("customs_value") > 0)
        )
        if cmp_df.height:
            bad = cmp_df.filter(
                (
                    pl.col("realised_duty_rate_on_dutiable")
                    - pl.col("total_modeled_tariff_rate")
                ).abs()
                > 0.03
            )
            out.append(
                CheckResult(
                    "DUTY_VS_ENGINE",
                    "realised duty rate differs from the policy engine by more than 3pp",
                    Severity.WARN,
                    bad.height == 0,
                    bad.height,
                    cmp_df.height,
                    "expected for HS6 lines with partial coverage, exclusions, or preference "
                    "programmes; a large share indicates the treatment measure is mis-specified",
                    _ex(
                        bad,
                        [*key, "realised_duty_rate_on_dutiable", "total_modeled_tariff_rate",
                         "tariff_status"],
                    ),
                )
            )
        else:
            out.append(
                CheckResult("DUTY_VS_ENGINE", "duty consistency", Severity.WARN, None, 0, n,
                            "skipped: no comparable rows")
            )

    # 8. Missing duties on apparently dutiable flows -----------------------
    miss = panel.filter(
        (pl.col("total_modeled_tariff_rate").fill_null(0) > 0)
        & (pl.col("customs_value") > 0)
        & (pl.col("calculated_duties").fill_null(0) <= 0)
    )
    out.append(
        CheckResult(
            "MISSING_DUTIES",
            "positive modelled tariff but zero calculated duties",
            Severity.WARN,
            miss.height == 0,
            miss.height,
            n,
            "consistent with duty-free entry under a preference programme, an exclusion, or "
            "a data problem; not resolvable from trade data alone",
            _ex(miss, ident),
        )
    )

    # 9. Unexplained jumps -------------------------------------------------
    if "log_customs_value" in panel.columns:
        s = panel.sort([product_col, country_col, month_col]).with_columns(
            (
                pl.col("log_customs_value")
                - pl.col("log_customs_value").shift(1).over([product_col, country_col])
            ).alias("_dlog")
        )
        jumps = s.filter(pl.col("_dlog").is_finite() & (pl.col("_dlog").abs() > jump_log_threshold))
        out.append(
            CheckResult(
                "TRADE_JUMP",
                f"month-on-month change in log customs value exceeding {jump_log_threshold}",
                Severity.INFO,
                jumps.height == 0,
                jumps.height,
                n,
                "large jumps are common in narrow HS lines with lumpy shipments; flagged for "
                "inspection, not removed",
                _ex(jumps, [*key, "_dlog", "customs_value"]),
            )
        )

    # 10. Panel balance / truncation --------------------------------------
    months = panel[month_col].n_unique()
    per_flow = panel.group_by([product_col, country_col]).len()
    short = per_flow.filter(pl.col("len") < months)
    out.append(
        CheckResult(
            "PANEL_GAPS",
            "product-country flows observed in fewer than all sampled months",
            Severity.INFO,
            short.height == 0,
            short.height,
            per_flow.height,
            f"{months} distinct months in the panel; gaps are true zeros or absent records and "
            "the two are not distinguishable in aggregated trade data",
            _ex(short, [product_col, country_col, "len"]),
        )
    )

    # 11. Tariff-assessment ambiguity -------------------------------------
    if "tariff_usable_for_treatment" in panel.columns:
        amb = panel.filter(~pl.col("tariff_usable_for_treatment").fill_null(False))
        out.append(
            CheckResult(
                "TARIFF_AMBIGUOUS",
                "tariff assessment not usable as a scalar treatment without judgement",
                Severity.WARN,
                amb.height == 0,
                amb.height,
                n,
                "these are partial HS6 coverage, partial statutory lines, or conflicts; the "
                "main sample excludes them and a sensitivity includes them",
                _ex(amb, [*key, "tariff_status"]),
            )
        )
    return out


def to_frame(results: list[CheckResult]) -> pl.DataFrame:
    return pl.DataFrame([r.to_row() for r in results])


def summarize(results: list[CheckResult]) -> dict:
    return {
        "n_checks": len(results),
        "n_passed": sum(1 for r in results if r.passed is True),
        "n_failed": sum(1 for r in results if r.passed is False),
        "n_skipped": sum(1 for r in results if r.passed is None),
        "n_errors_failed": sum(
            1 for r in results if r.passed is False and r.severity is Severity.ERROR
        ),
        "blocking": [r.check_id for r in results if r.passed is False and r.severity is Severity.ERROR],
    }
