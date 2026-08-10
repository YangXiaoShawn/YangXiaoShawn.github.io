"""Ex-post NBER business-cycle labels for grouped forecast evaluation only."""

from __future__ import annotations

from datetime import date
from typing import Final, Literal

NBER_REGIME_SOURCE_URL: Final = (
    "https://www.nber.org/research/data/us-business-cycle-expansions-and-contractions"
)
NBER_REGIME_SOURCE_LAST_UPDATED: Final = "2023-03-14"
NBER_REGIME_VERIFIED_AT: Final = "2026-08-10"
NBER_REGIME_DEFINITION: Final = (
    "ex_post_NBER_peak_trough_chronology_not_a_forecast_input"
)

Regime = Literal["nber_expansion", "nber_recession"]

# NBER counts the peak month/quarter as the end of an expansion and the trough
# month/quarter as the end of a recession. These intervals cover the official
# pilot, whose first target period is 2002Q1.
_MONTHLY_RECESSIONS: Final = (
    (date(2008, 1, 1), date(2009, 6, 1)),
    (date(2020, 3, 1), date(2020, 4, 1)),
)
_QUARTERLY_RECESSIONS: Final = (
    (date(2008, 1, 1), date(2009, 4, 1)),
    (date(2020, 1, 1), date(2020, 4, 1)),
)
_COVERAGE_START: Final = date(2002, 1, 1)


def nber_regime(period: date, frequency: str) -> Regime:
    """Label a target period using the ex-post NBER chronology.

    The label is evaluation metadata, never a model feature. Monthly inputs
    must be month starts and quarterly inputs must be quarter starts.
    """

    normalized = frequency.strip().lower()
    if period < _COVERAGE_START:
        raise ValueError("NBER regime helper is scoped to the official pilot from 2002")
    if period.day != 1:
        raise ValueError("regime period must be normalized to a period start")
    if normalized == "monthly":
        if period.month not in range(1, 13):  # pragma: no cover - date guarantees this
            raise ValueError("monthly period has an invalid month")
        recessions = _MONTHLY_RECESSIONS
    elif normalized == "quarterly":
        if period.month not in {1, 4, 7, 10}:
            raise ValueError("quarterly period must start in January, April, July, or October")
        recessions = _QUARTERLY_RECESSIONS
    else:
        raise ValueError(f"unsupported regime frequency: {frequency!r}")
    return (
        "nber_recession"
        if any(start <= period <= end for start, end in recessions)
        else "nber_expansion"
    )


__all__ = [
    "NBER_REGIME_DEFINITION",
    "NBER_REGIME_SOURCE_LAST_UPDATED",
    "NBER_REGIME_SOURCE_URL",
    "NBER_REGIME_VERIFIED_AT",
    "Regime",
    "nber_regime",
]
