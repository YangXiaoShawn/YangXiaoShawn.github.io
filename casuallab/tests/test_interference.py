import numpy as np
import pandas as pd
import pytest

from casuallab.interference import (
    ExposureMappingConfig,
    TwoStageSaturationConfig,
    add_mapped_exposures,
    estimate_exposure_response,
    two_stage_saturation_assignment,
)


def _units(n_zones: int = 12, n_periods: int = 8) -> pd.DataFrame:
    return pd.MultiIndex.from_product(
        [range(n_periods), range(n_zones)],
        names=["period_id", "zone_id"],
    ).to_frame(index=False)


def _ring_edges(n_zones: int) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "focal_zone_id": np.arange(n_zones),
            "neighbor_zone_id": np.roll(np.arange(n_zones), -1),
            "weight": 1.0,
        }
    )


def test_two_stage_saturation_is_deterministic_balanced_and_records_probabilities() -> None:
    config = TwoStageSaturationConfig(
        n_clusters=6,
        individuals_per_cell=40,
        saturation_levels=(0.0, 0.5, 1.0),
        seed=91,
    )
    first = two_stage_saturation_assignment(_units(), config)
    second = two_stage_saturation_assignment(_units(), config)
    pd.testing.assert_frame_equal(first, second)

    cluster_arms = first.groupby("cluster_id")["cluster_saturation"].nunique()
    assert cluster_arms.eq(1).all()
    assert (
        first[["cluster_id", "cluster_saturation"]]
        .drop_duplicates()["cluster_saturation"]
        .value_counts()
        .sort_index()
        .to_dict()
        == {0.0: 2, 0.5: 2, 1.0: 2}
    )
    assert set(first["saturation_assignment_probability"]) == {1 / 3}
    assert first.loc[first["cluster_saturation"] == 0, "treated_units"].eq(0).all()
    assert first.loc[first["cluster_saturation"] == 1, "treated_units"].eq(40).all()
    assert first["assigned_treatment"].between(0, 1).all()
    assert first["randomization_cluster"].nunique() == 6
    assert set(first["evidence_type"]) == {"randomized_design_assignment"}


def test_two_stage_saturation_config_rejects_unsupported_arm_geometry() -> None:
    with pytest.raises(ValueError, match="number of saturation levels"):
        TwoStageSaturationConfig(n_clusters=2, saturation_levels=(0.0, 0.5, 1.0))
    with pytest.raises(ValueError, match="sum to one"):
        TwoStageSaturationConfig(
            n_clusters=4,
            saturation_levels=(0.0, 1.0),
            saturation_probabilities=(0.2, 0.2),
        )


def test_mapped_exposure_uses_predeclared_neighbors_and_exact_time_lags() -> None:
    assignments = _units(n_zones=4, n_periods=4)
    assignments["treatment"] = (
        assignments["zone_id"] + assignments["period_id"]
    ) % 2
    mapped = add_mapped_exposures(
        assignments,
        _ring_edges(4),
        history_lags=1,
    )

    lookup = assignments.set_index(["zone_id", "period_id"])["treatment"]
    for row in mapped.itertuples(index=False):
        expected_neighbor = lookup.loc[((row.zone_id + 1) % 4, row.period_id)]
        assert row.neighbor_exposure == expected_neighbor
        if row.period_id == 0:
            assert np.isnan(row.history_exposure)
            assert row.history_support == 0
        else:
            assert row.history_exposure == lookup.loc[(row.zone_id, row.period_id - 1)]
            assert row.history_support == 1
    assert mapped["exposure_mapping_id"].nunique() == 1


def test_unmapped_focal_zone_remains_unknown_not_zero() -> None:
    assignments = _units(n_zones=3, n_periods=2)
    assignments["treatment"] = 0.0
    edges = pd.DataFrame(
        {
            "focal_zone_id": [0, 1],
            "neighbor_zone_id": [1, 2],
            "weight": [1.0, 1.0],
        }
    )
    mapped = add_mapped_exposures(assignments, edges)
    assert mapped.loc[mapped["zone_id"] == 2, "neighbor_exposure"].isna().all()
    assert mapped.loc[mapped["zone_id"].isin([0, 1]), "neighbor_exposure"].eq(0).all()


def test_exposure_mapped_regression_recovers_own_neighbor_and_history_slopes() -> None:
    assignment = two_stage_saturation_assignment(
        _units(n_zones=12, n_periods=40),
        TwoStageSaturationConfig(
            n_clusters=12,
            individuals_per_cell=80,
            saturation_levels=(0.0, 0.35, 0.7, 1.0),
            seed=81,
        ),
    )
    mapped = add_mapped_exposures(assignment, _ring_edges(12), history_lags=1)
    mapped["baseline"] = np.sin(mapped["zone_id"])
    rng = np.random.default_rng(719)
    mapped["outcome"] = (
        4.0
        + 2.0 * mapped["treatment"]
        + 1.5 * mapped["neighbor_exposure"]
        + 0.7 * mapped["history_exposure"]
        + 0.25 * mapped["baseline"]
        + rng.normal(0.0, 0.03, len(mapped))
    )
    result = estimate_exposure_response(
        mapped,
        ExposureMappingConfig(covariates=("baseline",)),
    ).set_index("exposure_term")

    assert result.loc["treatment", "estimate"] == pytest.approx(2.0, abs=0.05)
    assert result.loc["neighbor_exposure", "estimate"] == pytest.approx(1.5, abs=0.05)
    assert result.loc["history_exposure", "estimate"] == pytest.approx(0.7, abs=0.05)
    assert result["inference_valid"].all()
    assert set(result["target_estimand"]) == {
        "controlled_zone_direct_effect",
        "spillover_effect",
        "controlled_history_exposure_response",
    }
    assert result["effect_scale"].str.contains("not the full-policy").all()


def test_exposure_estimator_rejects_collinear_own_and_neighbor_exposure() -> None:
    frame = _units(n_zones=4, n_periods=4)
    frame["treatment"] = np.tile([0.0, 1.0, 0.0, 1.0], 4)
    frame["neighbor_exposure"] = frame["treatment"]
    frame["outcome"] = frame["treatment"]
    frame["randomization_cluster"] = "z_" + frame["zone_id"].astype(str)
    with pytest.raises(ValueError, match="rank deficient"):
        estimate_exposure_response(
            frame,
            ExposureMappingConfig(history_exposure=None),
        )


def test_exposure_estimator_fails_closed_when_configured_history_is_missing() -> None:
    frame = _units(n_zones=4, n_periods=4)
    frame["treatment"] = np.tile([0.0, 1.0, 0.0, 1.0], 4)
    frame["neighbor_exposure"] = np.tile([1.0, 0.0, 1.0, 0.0], 4)
    frame["outcome"] = frame["treatment"]
    frame["randomization_cluster"] = "z_" + frame["zone_id"].astype(str)

    with pytest.raises(ValueError, match="missing configured history column"):
        estimate_exposure_response(frame)


def test_exposure_estimator_rejects_mixed_mapping_versions() -> None:
    assignment = two_stage_saturation_assignment(
        _units(n_zones=8, n_periods=10),
        TwoStageSaturationConfig(
            n_clusters=8,
            individuals_per_cell=20,
            saturation_levels=(0.0, 0.5, 1.0),
            seed=18,
        ),
    )
    frame = add_mapped_exposures(assignment, _ring_edges(8), history_lags=1)
    frame["outcome"] = (
        2.0 * frame["treatment"]
        + frame["neighbor_exposure"]
        + 0.5 * frame["history_exposure"]
    )
    frame.loc[frame["period_id"] >= 5, "exposure_mapping_id"] = "second-map"

    with pytest.raises(ValueError, match="one predeclared exposure mapping"):
        estimate_exposure_response(frame)
