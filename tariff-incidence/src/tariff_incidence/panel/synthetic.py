"""Synthetic trade-flow generator for pipeline validation.

WHY THIS EXISTS
===============

The U.S. Census international-trade API requires an API key that is not present
in this environment. Rather than abandon the design or, far worse, invent
plausible-looking "results", this module generates a product x country x month
panel from a **fully specified, configuration-declared data-generating
process**.

WHAT IT IS FOR
==============

Exactly one thing: checking that the estimation code recovers parameters that
were put into the data on purpose. If the event study is asked to recover a
pass-through of -0.05 and returns -0.049 with a tight interval, the estimator
works. That is a statement about the **code**, not about the world.

WHAT IT IS NOT FOR
==================

Any estimate produced from this generator is tagged
``SYNTHETIC_PIPELINE_VALIDATION`` and is not evidence about U.S. trade, tariff
incidence, or anything else. The parameters below were chosen by the author to
exercise the code. They are **not** estimates, they are **not** taken from any
published paper, and reporting them as findings would be fabrication.

The moment ``CENSUS_API_KEY`` is set, ``scripts/build_trade_panel.py`` uses real
Census data and every downstream artefact is re-tagged ``OFFICIAL``. No
estimation code changes.

THE DATA-GENERATING PROCESS
===========================

For product :math:`i`, country :math:`c`, month :math:`t`, with
:math:`D_{ict}` the additional Section 301 ad valorem rate:

Log customs (tariff-exclusive) unit value::

    log p_ict = a_i + b_c + g_t + PASS_THROUGH_EXPORTER * D_ict + e_ict

Log quantity::

    log q_ict = m_i + n_c + h_t
                + ELASTICITY_OWN * log(1 + tau_base_i + D_ict)
                + DIVERSION_GAIN * exposure_i * 1{c is an alternative supplier}
                + u_ict

so the tariff-inclusive landed unit value is :math:`p_{ict}(1 + \\tau_i + D_{ict})`
by construction, and the exporter absorbs only ``PASS_THROUGH_EXPORTER``. The
"true" answers are therefore known exactly and are written alongside the panel
in ``ground_truth.json``.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

import numpy as np
import polars as pl


@dataclass(slots=True)
class GroundTruth:
    """Parameters deliberately injected into the synthetic panel."""

    pass_through_exporter: float = -0.05
    """Change in log customs unit value per unit of additional duty.

    Negative means the foreign exporter cuts its border price, i.e. bears part
    of the tariff. -0.05 means a 25pp duty lowers the customs unit value ~1.25%.
    """

    elasticity_own: float = -1.5
    """Elasticity of log quantity with respect to log(1 + total tariff)."""

    diversion_gain: float = 0.35
    """Log-quantity gain for alternative suppliers, scaled by product exposure."""

    anticipation_pull_forward: float = 0.12
    """Log-quantity bump in the month before an effective date (front-running)."""

    exit_hazard_treated: float = 0.015
    """Monthly probability a treated product-country flow drops to zero post-treatment."""

    sigma_price: float = 0.06
    sigma_qty: float = 0.18
    seed: int = 20180924

    def to_dict(self) -> dict[str, float | int]:
        return asdict(self)


@dataclass(slots=True)
class SyntheticSpec:
    hs6_treated: list[str]
    hs6_control: list[str]
    countries: dict[str, str]  # code -> name
    alternative_supplier_codes: list[str]
    treated_country_code: str
    start_month: str
    end_month: str
    treatment_effective: dict[str, str]  # hs6 -> ISO effective date
    baseline_mfn: dict[str, float]
    additional_rate_schedule: dict[str, dict[str, float]]
    """hs6 -> {"YYYY-MM": day-weighted additional rate for that month}.

    Supplied by the caller from the tariff engine via
    ``panel.build.month_average_additional_rate``, so the generator and the panel
    builder cannot disagree about the timing convention or about which action
    covers a product.
    """
    ground_truth: GroundTruth = field(default_factory=GroundTruth)


def _months(start: str, end: str) -> list[date]:
    sy, sm = (int(x) for x in start.split("-"))
    ey, em = (int(x) for x in end.split("-"))
    out: list[date] = []
    y, m = sy, sm
    while (y, m) <= (ey, em):
        out.append(date(y, m, 1))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def _days_in_month(month_start: date) -> int:
    nxt = (
        date(month_start.year + 1, 1, 1)
        if month_start.month == 12
        else date(month_start.year, month_start.month + 1, 1)
    )
    return (nxt - month_start).days


def _rate_on(schedule: dict[str, float], when: date) -> float:
    """Look up the day-weighted additional rate the tariff engine reported.

    The schedule is supplied by the caller from
    ``panel.build.month_average_additional_rate``, so the data-generating
    process and the estimation panel share one definition of treatment. An
    earlier version reimplemented the timing here and silently disagreed with
    the engine for products covered by List 1 or List 2, which the
    ``DUTY_VS_ENGINE`` quality check caught.
    """
    return float(schedule.get(f"{when.year:04d}-{when.month:02d}", 0.0))


def generate(spec: SyntheticSpec) -> tuple[pl.DataFrame, dict]:
    """Generate a synthetic product x country x month import panel.

    Returns the panel and a ground-truth dictionary. The panel mimics the Census
    column set (customs value, dutiable value, calculated duties, charges,
    quantity, quantity unit) so the downstream code path is identical to the one
    real data would take.
    """
    gt = spec.ground_truth
    rng = np.random.default_rng(gt.seed)
    months = _months(spec.start_month, spec.end_month)
    products = list(spec.hs6_treated) + list(spec.hs6_control)
    countries = list(spec.countries)

    # Fixed effects.
    a_i = {p: rng.normal(2.0, 0.7) for p in products}          # log price level
    m_i = {p: rng.normal(10.5, 1.1) for p in products}         # log quantity level
    b_c = {c: rng.normal(0.0, 0.25) for c in countries}
    n_c = {c: rng.normal(0.0, 0.9) for c in countries}
    # China is the dominant supplier pre-treatment.
    n_c[spec.treated_country_code] += 1.6

    g_t = {t: 0.0006 * i + rng.normal(0.0, 0.012) for i, t in enumerate(months)}
    h_t = {t: 0.0025 * i + rng.normal(0.0, 0.05) for i, t in enumerate(months)}
    # Common seasonality (calendar-month effects) shared across products.
    seas_p = {mm: rng.normal(0.0, 0.02) for mm in range(1, 13)}
    seas_q = {mm: rng.normal(0.0, 0.09) for mm in range(1, 13)}

    # Product exposure: share of pre-period imports from the treated country.
    exposure = {p: float(np.clip(rng.beta(2.4, 2.0), 0.02, 0.95)) for p in products}

    # Effective dates -> for the anticipation bump.
    eff_date: dict[str, date | None] = {}
    for p in products:
        iso = spec.treatment_effective.get(p)
        if iso:
            y, mm, _ = (int(x) for x in iso.split("-"))
            eff_date[p] = date(y, mm, 1)
        else:
            eff_date[p] = None

    dead: set[tuple[str, str]] = set()
    rows: list[dict] = []

    for t in months:
        for p in products:
            sched = spec.additional_rate_schedule.get(p, {})
            base = spec.baseline_mfn.get(p, 0.03)
            for c in countries:
                treated_flow = c == spec.treated_country_code
                addl = _rate_on(sched, t) if treated_flow else 0.0

                if (p, c) in dead:
                    continue

                # Extensive margin: treated flows can exit after treatment.
                ed = eff_date[p]
                if treated_flow and ed is not None and t > ed:
                    if rng.random() < gt.exit_hazard_treated:
                        dead.add((p, c))
                        continue

                log_p = (
                    a_i[p]
                    + b_c[c]
                    + g_t[t]
                    + seas_p[t.month]
                    + gt.pass_through_exporter * addl
                    + rng.normal(0.0, gt.sigma_price)
                )

                total_tau = base + addl
                is_alt = c in spec.alternative_supplier_codes
                alt_boost = 0.0
                if is_alt and ed is not None and t >= ed:
                    alt_boost = gt.diversion_gain * exposure[p]

                antic = 0.0
                if treated_flow and ed is not None:
                    gap = (t.year - ed.year) * 12 + (t.month - ed.month)
                    if gap == -1:
                        antic = gt.anticipation_pull_forward

                # Quantity responds to the *additional* duty. The MFN baseline is
                # time-invariant within a flow and is absorbed by flow fixed
                # effects, so it carries no identifying variation; making the
                # response depend on it would only introduce a dependence on
                # whether a single ad valorem baseline happens to exist for the
                # heading, which is a property of the tariff schedule rather
                # than of behaviour. The baseline still enters duty collection
                # below, as it does in reality.
                log_q = (
                    m_i[p]
                    + n_c[c]
                    + h_t[t]
                    + seas_q[t.month]
                    + gt.elasticity_own * np.log1p(addl)
                    + alt_boost
                    + antic
                    + rng.normal(0.0, gt.sigma_qty)
                )

                qty = float(np.exp(log_q))
                unit_value = float(np.exp(log_p))
                customs_value = unit_value * qty
                # Import charges (freight/insurance) are excluded from customs value.
                charges = customs_value * float(np.clip(rng.normal(0.055, 0.015), 0.005, 0.2))
                # Not every entry in a line is dutiable.
                dutiable_share = float(np.clip(rng.normal(0.94, 0.05), 0.0, 1.0))
                dutiable_value = customs_value * dutiable_share
                duties = dutiable_value * total_tau

                rows.append(
                    {
                        "hs6": p,
                        "country_code": c,
                        "country_name": spec.countries[c],
                        "month_date": t,
                        "con_val_mo": customs_value,
                        "gen_val_mo": customs_value * 1.015,
                        "dut_val_mo": dutiable_value,
                        "cal_dut_mo": duties,
                        "con_cha_mo": charges,
                        "con_qy1_mo": qty,
                        "unit_qy1": "NO",
                        "con_qy2_mo": None,
                        "unit_qy2": "",
                    }
                )

    df = pl.DataFrame(rows)
    truth = {
        "generator": "tariff_incidence.panel.synthetic",
        "warning": (
            "SYNTHETIC DATA. Parameters were chosen to exercise the estimation code. "
            "They are not estimates, are not drawn from any published study, and any "
            "number derived from this panel is a code check, not an empirical finding."
        ),
        "parameters": gt.to_dict(),
        "n_products": len(products),
        "n_treated_products": len(spec.hs6_treated),
        "n_control_products": len(spec.hs6_control),
        "n_countries": len(countries),
        "n_months": len(months),
        "n_rows": df.height,
        "treated_country_code": spec.treated_country_code,
        "alternative_supplier_codes": spec.alternative_supplier_codes,
        "product_exposure_treated_country": exposure,
    }
    return df, truth


def write_ground_truth(truth: dict, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(truth, indent=2, default=str) + "\n")
    return path
