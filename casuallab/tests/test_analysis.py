import pandas as pd
import pytest

from casuallab.analysis import (
    compute_descriptive_moments,
    descriptive_tables,
    origin_destination_summary,
)


def _panel() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "zone_id": [1, 2, 1, 2, 1, 2],
            "period_start": pd.date_range("2025-01-01", periods=3, freq="h").repeat(2),
            "trip_count": [10, 8, 12, 7, 14, 6],
            "average_fare": [12.0, 11.0, 13.0, 11.5, 14.0, 12.0],
            "pooled_trip_share": [0.1, 0.2, 0.1, 0.2, 0.0, 0.1],
            "panel_grain": ["pickup_zone_x_1h"] * 6,
        }
    )


def test_descriptive_moments_label_correlations_as_associations() -> None:
    moments = compute_descriptive_moments(_panel())
    assert moments["evidence_type"] == "empirical_association"
    assert moments["total_observed_trips"] == 57.0
    assert moments["mean_observed_fare"] == pytest.approx(
        sum(_panel()["trip_count"] * _panel()["average_fare"]) / 57.0
    )
    assert moments["equal_observed_cell_mean_fare"] == pytest.approx(
        _panel()["average_fare"].mean()
    )
    assert "not a causal elasticity" in moments["price_endogeneity_warning"]
    assert moments["zone_exact_lag_support_pairs"] == 4
    assert moments["zone_exact_lag_minutes"] == 60


def test_descriptive_tables_cover_time_zone_and_comovement() -> None:
    tables = descriptive_tables(_panel())
    assert set(tables) == {"demand_by_hour", "demand_by_zone", "cross_zone"}
    assert set(tables["demand_by_zone"]["evidence_type"]) == {"empirical_association"}


def test_origin_destination_flows_are_normalized_within_origin() -> None:
    trips = pd.DataFrame(
        {
            "pickup_zone": [1, 1, 1, 2],
            "dropoff_zone": [2, 2, 3, 1],
        }
    )
    flows = origin_destination_summary(trips)
    shares = flows.groupby("origin_zone")["origin_flow_share"].sum()
    assert shares.round(10).eq(1.0).all()
    assert set(flows["evidence_type"]) == {"empirical_association"}
