from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from casuallab.config import DesignConfig
from casuallab.designs import ASSIGNMENT_COLUMNS, enforce_budget, generate_assignment


@pytest.mark.parametrize(
    "design",
    ["individual", "geo_cluster", "time_block", "switchback", "geo_time"],
)
def test_all_designs_are_deterministic_and_share_a_schema(design: str) -> None:
    config = DesignConfig(
        name=design,
        cluster_size=2,
        treatment_duration=3,
        washout_periods=1 if design in {"time_block", "switchback", "geo_time"} else 0,
    )
    first = generate_assignment(6, 18, config, seed=41, individuals_per_cell=60)
    second = generate_assignment(6, 18, config, seed=41, individuals_per_cell=60)

    pd.testing.assert_frame_equal(first, second)
    assert set(ASSIGNMENT_COLUMNS).issubset(first.columns)
    assert first[["zone_id", "period_id"]].duplicated().sum() == 0
    assert first["treatment"].between(0, 1).all()
    assert first["assigned_treatment"].between(0, 1).all()
    assert first["treatment_probability"].between(0, 1).all()
    assert set(first["analysis_eligible"].unique()).issubset({0, 1})
    assert set(first["assignment_seed"]) == {41}


def test_individual_design_is_a_partial_saturation_assignment() -> None:
    config = DesignConfig(name="individual", treatment_probability=0.4)
    assignment = generate_assignment(
        4,
        20,
        config,
        seed=7,
        individuals_per_cell=200,
    )

    assert assignment["assigned_treatment"].nunique() > 2
    assert np.isclose(assignment["treatment_probability"], 0.4).all()
    assert assignment["treated_units"].between(0, 200).all()
    assert np.isclose(
        assignment["assigned_treatment"], assignment["treated_units"] / 200
    ).all()


def test_geographic_assignment_is_constant_within_zone() -> None:
    config = DesignConfig(
        name="geo_cluster",
        treatment_probability=0.34,
        n_clusters=3,
    )
    assignment = generate_assignment(6, 8, config, seed=12)

    assert (assignment.groupby("zone_id")["assigned_treatment"].nunique() == 1).all()
    assert assignment["cluster_id"].nunique() == 3
    # Complete randomization has one of three clusters treated, so the exact
    # inclusion probability is 1/3 rather than the requested rounding target .34.
    assert np.isclose(assignment["treatment_probability"], 1 / 3).all()


def test_geo_design_never_mistakes_contemporaneous_arms_for_washout() -> None:
    assignment = generate_assignment(
        4,
        12,
        DesignConfig(name="geo_cluster", washout_periods=1, treatment_duration=4),
        seed=3,
    )

    assert assignment["analysis_eligible"].eq(1).all()
    assert assignment["washout"].eq(0).all()


def test_time_blocks_and_switchback_pairs_obey_schedule() -> None:
    block_config = DesignConfig(name="time_block", treatment_duration=2)
    blocks = generate_assignment(4, 12, block_config, seed=4)
    assert (blocks.groupby("period_id")["assigned_treatment"].nunique() == 1).all()
    assert (blocks.groupby("time_block")["assigned_treatment"].nunique() == 1).all()

    switch_config = DesignConfig(
        name="switchback",
        treatment_probability=0.7,
        treatment_duration=2,
        washout_periods=1,
    )
    switch = generate_assignment(3, 16, switch_config, seed=5)
    block_arms = switch.groupby("time_block")["assigned_treatment"].first().sort_index()
    for _, pair in block_arms.groupby(block_arms.index // 2):
        if len(pair) == 2:
            assert set(pair) == {0.0, 1.0}
    even_probability = switch.loc[switch["time_block"] % 2 == 0, "treatment_probability"]
    odd_probability = switch.loc[switch["time_block"] % 2 == 1, "treatment_probability"]
    assert np.isclose(even_probability, 0.7).all()
    assert np.isclose(odd_probability, 0.3).all()
    assert switch["washout"].sum() > 0
    assert (switch["analysis_eligible"] == 1 - switch["washout"]).all()


def test_geo_time_is_constant_within_randomization_cell() -> None:
    config = DesignConfig(name="geo_time", cluster_size=2, treatment_duration=3)
    assignment = generate_assignment(6, 12, config, seed=8)
    within_cell = assignment.groupby(["cluster_id", "time_block"])["assigned_treatment"]
    assert (within_cell.nunique() == 1).all()
    assert assignment["randomization_cluster"].nunique() == 3 * 4


def test_expected_budget_attenuation_preserves_assignment() -> None:
    assignment = generate_assignment(
        4,
        6,
        DesignConfig(name="geo_cluster"),
        seed=2,
    )
    constrained = enforce_budget(assignment, cost_per_full_treatment=10.0, budget=30.0)

    pd.testing.assert_series_equal(
        constrained["assigned_treatment"], assignment["assigned_treatment"]
    )
    assert constrained["expected_treatment_cost"].sum() <= 30.0 + 1e-10
    assert constrained["budget_scale"].iat[0] < 1.0


@pytest.mark.parametrize("design", ["individual", "geo_cluster", "time_block", "geo_time"])
def test_single_randomization_group_reports_bernoulli_probability_not_realized_arm(
    design: str,
) -> None:
    config = DesignConfig(name=design, treatment_probability=0.37)
    assignment = generate_assignment(1, 1, config, seed=4)

    assert np.isclose(assignment["treatment_probability"], 0.37).all()
