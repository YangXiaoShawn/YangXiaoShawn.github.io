from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import casuallab.equilibrium as equilibrium_module
from casuallab.config import TreatmentVersion
from casuallab.equilibrium import (
    CAUSAL_SCOPE,
    EMPIRICAL_STATUS,
    EVIDENCE_TYPE,
    EquilibriumConfig,
    EquilibriumConvergenceError,
    run_equilibrium_benchmark,
    solve_market_equilibrium,
    write_equilibrium_artifacts,
)


def _config(**overrides: object) -> EquilibriumConfig:
    return replace(
        EquilibriumConfig(
            n_zones=2,
            seed=4711,
            demand_shock_sd=0.04,
            supply_shock_sd=0.03,
            tolerance=1e-11,
        ),
        **overrides,
    )


def test_same_seed_reproduces_equilibria_truth_and_ledgers() -> None:
    first = run_equilibrium_benchmark(_config())
    second = run_equilibrium_benchmark(_config())

    pd.testing.assert_frame_equal(first.control.panel, second.control.panel)
    pd.testing.assert_frame_equal(first.treatment.panel, second.treatment.panel)
    pd.testing.assert_frame_equal(first.zone_effects, second.zone_effects)
    pd.testing.assert_frame_equal(first.ledger, second.ledger)
    assert first.ground_truth == second.ground_truth
    assert first.metadata == second.metadata

    changed = run_equilibrium_benchmark(_config(seed=4712))
    assert changed.metadata["state_id"] != first.metadata["state_id"]
    assert not np.allclose(
        changed.control.panel["baseline_rider_arrivals"],
        first.control.panel["baseline_rider_arrivals"],
    )


@pytest.mark.parametrize("scenario", ["control", "treatment"])
def test_reported_residual_recomputes_from_declared_fixed_point(scenario: str) -> None:
    config = _config(cross_zone_share=0.35)
    result = run_equilibrium_benchmark(config)
    outcome = result.control if scenario == "control" else result.treatment
    panel = outcome.panel.sort_values("zone_id")

    local_tightness = np.log(
        panel["latent_demand"].to_numpy()
        / (config.capacity_per_driver * panel["available_drivers"].to_numpy())
    )
    # With two zones the declared ring maps each zone to the other one.
    neighbor_tightness = local_tightness[::-1]
    target = config.congestion_elasticity * (
        (1.0 - config.cross_zone_share) * local_tightness
        + config.cross_zone_share * neighbor_tightness
    )
    recomputed = float(
        np.max(np.abs(target - panel["log_wait_ratio"].to_numpy()))
    )

    assert outcome.diagnostics.converged
    assert outcome.diagnostics.uniqueness_condition_satisfied
    assert outcome.diagnostics.contraction_bound < 1.0
    assert recomputed == pytest.approx(
        outcome.diagnostics.residual_sup_norm, abs=1e-14
    )
    assert recomputed <= config.tolerance


@pytest.mark.parametrize(
    ("version", "rider_spend_positive", "driver_spend_positive"),
    [
        (TreatmentVersion.RIDER_DISCOUNT, True, False),
        (TreatmentVersion.DRIVER_INCENTIVE, False, True),
        (TreatmentVersion.BUNDLED, True, True),
    ],
)
def test_declared_intervention_version_activates_only_its_market_side(
    version: TreatmentVersion,
    rider_spend_positive: bool,
    driver_spend_positive: bool,
) -> None:
    result = run_equilibrium_benchmark(_config(treatment_version=version))
    control = result.control.panel
    treated = result.treatment.panel

    assert (float(treated["rider_discount_spend"].sum()) > 0) is rider_spend_positive
    assert (float(treated["driver_incentive_spend"].sum()) > 0) is driver_spend_positive
    if rider_spend_positive:
        assert (treated["rider_price"] < control["rider_price"]).all()
        assert (treated["latent_demand"] > control["latent_demand"]).all()
    else:
        np.testing.assert_allclose(treated["rider_price"], control["rider_price"])
        assert np.allclose(treated["rider_treatment_dose"], 0.0)
    if driver_spend_positive:
        assert (treated["driver_incentive_per_driver"] > 0).all()
        assert (treated["available_drivers"] > control["available_drivers"]).all()
    else:
        assert np.allclose(treated["driver_treatment_dose"], 0.0)

    # Both a lower rider price and a positive supply incentive weakly relax the
    # matching constraint in this pre-specified model; each version raises trips.
    assert result.ground_truth["market_total_trip_effect"] > 0


def test_budget_binds_with_a_re_solved_equilibrium_and_balanced_welfare_ledger() -> None:
    budget = 100.0
    result = run_equilibrium_benchmark(_config(budget=budget))
    treatment = result.treatment.panel
    diagnostics = result.metadata["budget_diagnostics"]

    assert diagnostics["binding"] is True
    assert diagnostics["budget_feasible"] is True
    assert 0 < diagnostics["budget_scale"] < 1
    assert float(treatment["treatment_spend"].sum()) <= budget + 1e-8
    np.testing.assert_allclose(
        treatment["treatment_spend"],
        treatment["rider_discount_spend"]
        + treatment["driver_incentive_spend"],
        atol=1e-12,
    )
    np.testing.assert_allclose(
        treatment["total_welfare"],
        treatment["rider_surplus"]
        + treatment["driver_surplus"]
        + treatment["platform_net_revenue"],
        atol=1e-10,
    )
    treatment_ledger = result.ledger.set_index("scenario").loc["treatment"]
    assert treatment_ledger["treatment_spend"] == pytest.approx(
        result.ground_truth["treatment_spend"]
    )
    assert abs(float(treatment_ledger["welfare_accounting_residual"])) < 1e-10


def test_solver_fails_closed_when_sufficient_uniqueness_condition_fails() -> None:
    config = _config(
        demand_wait_elasticity=0.80,
        supply_wait_elasticity=0.50,
        congestion_elasticity=0.90,
    )

    with pytest.raises(EquilibriumConvergenceError) as caught:
        solve_market_equilibrium(config, 1.0)

    diagnostics = caught.value.diagnostics
    assert not diagnostics.converged
    assert not diagnostics.uniqueness_condition_satisfied
    assert diagnostics.contraction_bound >= 1.0
    assert diagnostics.iterations == 0
    assert diagnostics.residual_sup_norm is None
    assert diagnostics.termination_reason == "sufficient_contraction_condition_failed"


def test_solver_fails_closed_when_iteration_cap_precedes_residual_tolerance() -> None:
    config = _config(max_iterations=1, tolerance=1e-15)

    with pytest.raises(EquilibriumConvergenceError) as caught:
        solve_market_equilibrium(config, 1.0)

    diagnostics = caught.value.diagnostics
    assert diagnostics.uniqueness_condition_satisfied
    assert not diagnostics.converged
    assert diagnostics.iterations == 1
    assert diagnostics.residual_sup_norm is not None
    assert diagnostics.residual_sup_norm > config.tolerance
    assert (
        diagnostics.termination_reason
        == "maximum_iterations_reached_before_residual_tolerance"
    )


def test_common_random_number_ground_truth_equals_paired_path_differences() -> None:
    result = run_equilibrium_benchmark(_config(), planned_treatment_intensity=[1.0, 0.5])
    control = result.control.panel.sort_values("zone_id").reset_index(drop=True)
    treatment = result.treatment.panel.sort_values("zone_id").reset_index(drop=True)

    assert result.metadata["common_random_numbers"] is True
    assert result.metadata["control_state_id"] == result.metadata["treatment_state_id"]
    np.testing.assert_array_equal(
        control["baseline_rider_arrivals"], treatment["baseline_rider_arrivals"]
    )
    np.testing.assert_array_equal(
        control["baseline_driver_pool"], treatment["baseline_driver_pool"]
    )
    expected_trip_effect = treatment["trips"].to_numpy() - control["trips"].to_numpy()
    expected_welfare_effect = (
        treatment["total_welfare"].to_numpy()
        - control["total_welfare"].to_numpy()
    )
    np.testing.assert_allclose(result.zone_effects["trip_effect"], expected_trip_effect)
    assert result.ground_truth["market_total_trip_effect"] == pytest.approx(
        expected_trip_effect.sum()
    )
    assert result.ground_truth["market_total_welfare_effect"] == pytest.approx(
        expected_welfare_effect.sum()
    )
    assert result.ground_truth["incremental_trips_per_dollar"] == pytest.approx(
        expected_trip_effect.sum() / result.ground_truth["treatment_spend"]
    )


def test_optional_cross_zone_channel_transmits_a_local_policy_to_neighbor_wait() -> None:
    common = dict(
        treatment_version=TreatmentVersion.RIDER_DISCOUNT,
        cross_zone_share=0.40,
    )
    disconnected = run_equilibrium_benchmark(
        _config(cross_zone_enabled=False, **common),
        planned_treatment_intensity=[1.0, 0.0],
    )
    connected = run_equilibrium_benchmark(
        _config(cross_zone_enabled=True, **common),
        planned_treatment_intensity=[1.0, 0.0],
    )

    disconnected_neighbor = disconnected.zone_effects.set_index("zone_id").loc[1]
    connected_neighbor = connected.zone_effects.set_index("zone_id").loc[1]
    assert disconnected_neighbor["wait_effect_minutes"] == pytest.approx(0.0, abs=1e-10)
    assert abs(float(connected_neighbor["wait_effect_minutes"])) > 1e-4
    assert disconnected.metadata["cross_zone_channel"] is False
    assert connected.metadata["cross_zone_channel"] is True


def test_zero_policy_has_zero_known_effect_and_no_efficiency_ratio() -> None:
    result = run_equilibrium_benchmark(_config(), planned_treatment_intensity=0.0)

    assert result.ground_truth["market_total_trip_effect"] == pytest.approx(0.0)
    assert result.ground_truth["market_total_welfare_effect"] == pytest.approx(0.0)
    assert result.ground_truth["treatment_spend"] == pytest.approx(0.0)
    assert result.ground_truth["incremental_trips_per_dollar"] is None
    assert result.ground_truth["incremental_welfare_per_dollar"] is None


def test_evidence_labels_and_equations_prevent_empirical_overclaiming() -> None:
    result = run_equilibrium_benchmark(_config())

    assert result.metadata["evidence_type"] == EVIDENCE_TYPE
    assert result.metadata["causal_scope"] == CAUSAL_SCOPE
    assert result.metadata["empirical_calibration_status"] == EMPIRICAL_STATUS
    assert result.metadata["is_nyc_structural_estimate"] is False
    assert result.metadata["ground_truth_status"].startswith("known_exactly")
    assert "rider_demand" in result.metadata["equations"]
    assert "driver_supply" in result.metadata["equations"]
    assert "wait_fixed_point" in result.metadata["equations"]
    assert "service_probability" in result.metadata["equations"]
    assert any("not estimated from NYC" in item for item in result.metadata["limitations"])
    for panel in (result.control.panel, result.treatment.panel):
        assert set(panel["evidence_type"]) == {EVIDENCE_TYPE}
        assert set(panel["causal_scope"]) == {CAUSAL_SCOPE}
        assert set(panel["is_nyc_structural_estimate"]) == {False}


def test_configuration_rejects_unknown_or_invalid_values() -> None:
    with pytest.raises(ValueError, match="unknown equilibrium"):
        EquilibriumConfig.from_mapping({"n_zonez": 2})
    with pytest.raises(ValueError, match="discount_rate"):
        EquilibriumConfig(discount_rate=1.1)
    with pytest.raises(ValueError, match="treatment_intensity"):
        solve_market_equilibrium(_config(), [0.0, 1.1])


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_artifact_writer_publishes_portable_hash_verified_bundle(tmp_path: Path) -> None:
    output = tmp_path / "artifacts/benchmarks/equilibrium"
    result = run_equilibrium_benchmark(_config(budget=100.0))

    artifacts = write_equilibrium_artifacts(result, output, tmp_path)

    assert {path.name for path in artifacts.paths()} == {
        "summary.json",
        "zone_effects.csv",
        "ledger.csv",
        "manifest.json",
    }
    assert all(path.is_file() for path in artifacts.paths())
    assert not (output / "EQUILIBRIUM_INCOMPLETE.json").exists()

    summary = json.loads(artifacts.summary_path.read_text(encoding="utf-8"))
    manifest = json.loads(artifacts.manifest_path.read_text(encoding="utf-8"))
    assert summary["evidence_type"] == EVIDENCE_TYPE
    assert summary["causal_scope"] == CAUSAL_SCOPE
    assert summary["empirical_calibration_status"] == EMPIRICAL_STATUS
    assert summary["is_nyc_structural_estimate"] is False
    assert summary["ground_truth"] == result.ground_truth
    assert manifest["portable_paths"] is True
    assert manifest["checks"] == {
        "budget_feasible": True,
        "common_random_numbers_verified": True,
        "control_equilibrium_converged": True,
        "ground_truth_recomputed": True,
        "hashes_recomputed": True,
        "residuals_within_tolerance": True,
        "sufficient_uniqueness_condition_satisfied": True,
        "treatment_equilibrium_converged": True,
        "welfare_accounting_balanced": True,
    }
    for entry in manifest["files"]:
        assert not Path(entry["path"]).is_absolute()
        path = tmp_path / entry["path"]
        assert path.is_file()
        assert entry["bytes"] == path.stat().st_size
        assert entry["sha256"] == _sha256(path)
    declared_digest = hashlib.sha256(
        json.dumps(
            manifest["files"], sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
    assert manifest["declared_file_set_sha256"] == declared_digest

    stored_effects = pd.read_csv(artifacts.zone_effects_path)
    stored_ledger = pd.read_csv(artifacts.ledger_path)
    pd.testing.assert_frame_equal(stored_effects, result.zone_effects)
    assert set(stored_ledger["scenario"]) == {"control", "treatment"}
    assert stored_ledger.loc[
        stored_ledger["scenario"] == "treatment", "treatment_spend"
    ].iloc[0] == pytest.approx(result.ground_truth["treatment_spend"])


def test_artifact_writer_is_byte_deterministic_across_project_roots(
    tmp_path: Path,
) -> None:
    result = run_equilibrium_benchmark(_config())
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_root.mkdir()
    second_root.mkdir()
    relative_output = Path("artifacts/benchmarks/equilibrium")

    first = write_equilibrium_artifacts(
        result, first_root / relative_output, first_root
    )
    second = write_equilibrium_artifacts(
        result, second_root / relative_output, second_root
    )

    first_by_name = {path.name: path.read_bytes() for path in first.paths()}
    second_by_name = {path.name: path.read_bytes() for path in second.paths()}
    assert first_by_name == second_by_name
    manifest = json.loads(first.manifest_path.read_text(encoding="utf-8"))
    assert all(
        entry["path"].startswith("artifacts/benchmarks/equilibrium/")
        for entry in manifest["files"]
    )


def test_artifact_writer_rejects_paths_outside_project_root(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    outside = tmp_path / "outside/equilibrium"

    with pytest.raises(ValueError, match="outside project_root"):
        write_equilibrium_artifacts(
            run_equilibrium_benchmark(_config()), outside, root
        )

    assert not outside.exists()


def test_artifact_writer_recomputes_truth_before_publishing(tmp_path: Path) -> None:
    result = run_equilibrium_benchmark(_config())
    altered_effects = result.zone_effects.copy()
    altered_effects.loc[0, "trip_effect"] += 1.0
    tampered = replace(result, zone_effects=altered_effects)
    output = tmp_path / "artifacts/benchmarks/equilibrium"

    with pytest.raises(ValueError, match="ground truth failed recomputation"):
        write_equilibrium_artifacts(tampered, output, tmp_path)

    assert not output.exists()


def test_artifact_writer_withholds_manifest_and_leaves_marker_on_write_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "artifacts/benchmarks/equilibrium"

    def fail_csv(_frame: pd.DataFrame, destination: Path) -> Path:
        raise OSError(f"injected failure for {destination.name}")

    monkeypatch.setattr(equilibrium_module, "_atomic_artifact_csv", fail_csv)
    with pytest.raises(OSError, match="injected failure"):
        write_equilibrium_artifacts(
            run_equilibrium_benchmark(_config()), output, tmp_path
        )

    assert (output / "EQUILIBRIUM_INCOMPLETE.json").is_file()
    assert not (output / "manifest.json").exists()
    assert not list(output.glob(".*-*.json"))
