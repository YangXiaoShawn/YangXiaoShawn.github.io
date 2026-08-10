from __future__ import annotations

from datetime import date

import pytest

from macro_nowcast.regimes import nber_regime


@pytest.mark.parametrize(
    ("period", "expected"),
    [
        (date(2007, 12, 1), "nber_expansion"),
        (date(2008, 1, 1), "nber_recession"),
        (date(2009, 6, 1), "nber_recession"),
        (date(2009, 7, 1), "nber_expansion"),
        (date(2020, 2, 1), "nber_expansion"),
        (date(2020, 3, 1), "nber_recession"),
        (date(2020, 4, 1), "nber_recession"),
        (date(2020, 5, 1), "nber_expansion"),
    ],
)
def test_monthly_nber_regime_respects_peak_and_trough_convention(
    period: date,
    expected: str,
) -> None:
    assert nber_regime(period, "monthly") == expected


@pytest.mark.parametrize(
    ("period", "expected"),
    [
        (date(2007, 10, 1), "nber_expansion"),
        (date(2008, 1, 1), "nber_recession"),
        (date(2009, 4, 1), "nber_recession"),
        (date(2009, 7, 1), "nber_expansion"),
        (date(2019, 10, 1), "nber_expansion"),
        (date(2020, 1, 1), "nber_recession"),
        (date(2020, 4, 1), "nber_recession"),
        (date(2020, 7, 1), "nber_expansion"),
    ],
)
def test_quarterly_nber_regime_uses_quarterly_turning_points(
    period: date,
    expected: str,
) -> None:
    assert nber_regime(period, "quarterly") == expected


def test_nber_regime_rejects_out_of_scope_or_unaligned_periods() -> None:
    with pytest.raises(ValueError, match="scoped"):
        nber_regime(date(2001, 10, 1), "monthly")
    with pytest.raises(ValueError, match="quarterly period"):
        nber_regime(date(2020, 2, 1), "quarterly")
    with pytest.raises(ValueError, match="unsupported"):
        nber_regime(date(2020, 1, 1), "weekly")
