from __future__ import annotations

import pytest

from casuallab.estimands import identification_assessment


def test_identification_guard_enforces_design_compatibility() -> None:
    identified, reasons = identification_assessment(
        "direct_effect",
        design="geo_cluster",
        interference_present=False,
    )
    assert not identified
    assert any("not compatible" in reason for reason in reasons)

    identified, reasons = identification_assessment(
        "spillover_effect",
        design="geo_cluster",
        interference_present=True,
        exposure_mapped=True,
    )
    assert not identified
    assert any("not compatible" in reason for reason in reasons)


def test_identification_guard_rejects_unknown_design() -> None:
    with pytest.raises(ValueError, match="unknown design"):
        identification_assessment(
            "market_total_effect",
            design="bogus",
            interference_present=False,
        )

