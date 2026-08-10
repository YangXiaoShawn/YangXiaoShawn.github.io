import pandas as pd
import pytest

from casuallab.calibration import calibrate_simulation
from casuallab.config import SimulationConfig


def test_calibration_updates_observed_moments_not_causal_assumptions() -> None:
    panel = pd.DataFrame(
        {
            "trip_count": [10, 20, 30],
            "average_fare": [8.0, 10.0, 12.0],
            "average_trip_seconds": [600, 900, 1200],
        }
    )
    template = SimulationConfig(direct_demand_effect=0.23, spillover_strength=0.4)
    result = calibrate_simulation(panel, template)
    assert result.config.base_demand > 20.0
    assert result.config.base_fare == pytest.approx(10.6666666667)
    assert result.config.base_supply / result.config.base_demand == (
        template.base_supply / template.base_demand
    )
    assert result.config.direct_demand_effect == 0.23
    assert result.config.spillover_strength == 0.4
    assert result.empirical_targets["mean_observed_trip_seconds"] == 1000.0
    assert result.empirical_targets["equal_observed_cell_mean_fare"] == 10.0
    assert abs(result.empirical_targets["completed_trip_calibration_error"]) < 1e-10
    assert "direct_demand_effect" in result.unchanged_structural_assumptions
