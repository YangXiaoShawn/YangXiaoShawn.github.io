from pathlib import Path

import pandas as pd
import pytest

from casuallab.enrichments import EnrichmentAdapter, apply_optional_enrichments


def test_missing_optional_enrichment_leaves_core_panel_unchanged() -> None:
    panel = pd.DataFrame({"zone_id": [1, 2], "trip_count": [3, 4]})
    result = apply_optional_enrichments(
        panel,
        [EnrichmentAdapter("neighborhood", None, ("zone_id",))],
    )
    pd.testing.assert_frame_equal(result.panel, panel)
    assert result.diagnostics.loc[0, "status"] == "unavailable_optional"


def test_available_enrichment_preserves_missing_coverage(tmp_path: Path) -> None:
    panel = pd.DataFrame({"zone_id": [1, 2, 3], "trip_count": [3, 4, 5]})
    source_path = tmp_path / "income.csv"
    pd.DataFrame({"area": [1, 2], "income_index": [0.1, 0.8]}).to_csv(
        source_path, index=False
    )
    result = apply_optional_enrichments(
        panel,
        [
            EnrichmentAdapter(
                "neighborhood",
                source_path,
                ("zone_id",),
                source_keys=("area",),
                value_columns=("income_index",),
            )
        ],
    )
    assert result.panel["neighborhood__income_index"].isna().sum() == 1
    assert result.diagnostics.loc[0, "coverage_rate"] == pytest.approx(2 / 3)


def test_required_enrichment_fails_closed() -> None:
    panel = pd.DataFrame({"zone_id": [1], "trip_count": [3]})
    with pytest.raises(FileNotFoundError):
        apply_optional_enrichments(
            panel,
            [EnrichmentAdapter("events", None, ("zone_id",), required=True)],
        )

