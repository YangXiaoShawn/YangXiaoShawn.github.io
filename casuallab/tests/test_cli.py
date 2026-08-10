from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd
import pytest

import casuallab.cli as cli_module
from casuallab.cli import (
    _run_reproduce,
    _write_hte_artifacts,
    build_parser,
    main,
    write_simulation_outputs,
)
from casuallab.config import DesignConfig, SimulationConfig
from casuallab.simulator import simulate_market


def test_cli_exposes_required_workflow_commands() -> None:
    parser = build_parser()
    actions = [action for action in parser._actions if action.dest == "command"]
    assert len(actions) == 1
    commands = set(actions[0].choices)
    assert {
        "download-sample",
        "build-panel",
        "validate-nyc-full",
        "simulate",
        "benchmark",
        "interference-benchmark",
        "nyc-simulation-anchor",
        "nyc-weather",
        "nyc-events",
        "nyc-income",
        "nyc-benchmark",
        "nyc-graph-benchmark",
        "equilibrium-benchmark",
        "report",
        "reproduce-sample",
    }.issubset(commands)
    report_args = parser.parse_args(["report"])
    reproduce_args = parser.parse_args(["reproduce-sample"])
    assert report_args.nyc_full_validation == "artifacts/nyc_full/validation.json"
    assert report_args.nyc_full_manifest == "artifacts/nyc_full/manifest.json"
    assert (
        report_args.treatment_version_policy
        == "artifacts/benchmarks/treatment_version_policy_results.csv"
    )
    assert (
        report_args.treatment_version_policy_manifest
        == "artifacts/benchmarks/treatment_version_policy_manifest.json"
    )
    assert reproduce_args.nyc_full_validation == "artifacts/nyc_full/validation.json"
    assert reproduce_args.nyc_full_manifest == "artifacts/nyc_full/manifest.json"
    assert report_args.interference_summary.endswith("interference_summary.csv")
    assert report_args.interference_manifest.endswith("interference_manifest.json")
    assert report_args.nyc_simulation_anchor.endswith("nyc_simulation_anchor.json")
    assert report_args.nyc_simulation_anchor_manifest.endswith("manifest.json")
    assert report_args.nyc_benchmark_manifest.endswith("nyc_informed/manifest.json")
    assert report_args.nyc_graph_benchmark_manifest.endswith("nyc_graph/manifest.json")
    assert report_args.equilibrium_manifest.endswith("equilibrium/manifest.json")
    assert report_args.nyc_weather_manifest.endswith("weather/manifest.json")
    assert report_args.nyc_events_manifest.endswith("events/manifest.json")
    assert report_args.nyc_income_manifest.endswith("income/manifest.json")
    weather_args = parser.parse_args(["nyc-weather"])
    assert weather_args.raw.endswith("noaa_central_park_2024-01.csv")
    assert weather_args.data_manifest == "data/nyc_full/manifest.json"
    event_args = parser.parse_args(["nyc-events"])
    assert event_args.events.endswith("nyc_permitted_events_overlap_2024-01.csv")
    assert event_args.holidays.endswith("official_holidays_2024-01.csv")
    income_args = parser.parse_args(["nyc-income"])
    assert income_args.taxi_zones.endswith("taxi_zones.zip")
    assert income_args.acs_b19001.endswith("acs_2022_5yr_b19001_nyc_tracts.dat")
    assert parser.parse_args(["nyc-benchmark"]).replications == 6
    assert parser.parse_args(["nyc-graph-benchmark"]).n_zones == 16
    assert parser.parse_args(["equilibrium-benchmark"]).treatment_version == "bundled"


def test_nyc_weather_command_reuses_pinned_raw_and_writes_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = tmp_path / "weather.csv"
    raw.write_text("pinned\n", encoding="utf-8")
    generated = tuple(tmp_path / f"weather-{index}.csv" for index in range(5))
    for path in generated:
        path.write_text("ok\n", encoding="utf-8")
    observed: dict[str, object] = {}

    def download(path: str, *, refresh: bool) -> Path:
        observed["download"] = (path, refresh)
        return raw

    def write_bundle(
        raw_path: Path,
        panel_dir: str,
        data_manifest: str,
        output_dir: str,
        *,
        project_root: Path,
    ) -> object:
        observed["writer"] = (
            raw_path,
            panel_dir,
            data_manifest,
            output_dir,
            project_root,
        )
        return argparse.Namespace(paths=lambda: generated)

    monkeypatch.setattr(cli_module, "download_noaa_daily_weather", download)
    monkeypatch.setattr(cli_module, "write_nyc_weather_bundle", write_bundle)
    outputs = cli_module._run_nyc_weather(
        argparse.Namespace(
            raw=str(raw),
            panel_dir="panel",
            data_manifest="data-manifest.json",
            output_dir="weather-output",
            refresh=False,
        )
    )

    assert outputs == list(generated)
    assert observed["download"] == (str(raw), False)
    assert observed["writer"][0] == raw


def test_nyc_events_and_income_commands_use_pinned_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generated = tuple(tmp_path / f"artifact-{index}.csv" for index in range(7))
    for path in generated:
        path.write_text("ok\n", encoding="utf-8")
    observed: dict[str, object] = {}

    def download(path: str, *, refresh: bool) -> Path:
        observed["event_download"] = (path, refresh)
        return Path(path)

    def event_writer(*args: object, project_root: Path) -> object:
        observed["event_writer"] = (*args, project_root)
        return argparse.Namespace(paths=lambda: generated)

    def income_writer(*args: object, project_root: Path) -> object:
        observed["income_writer"] = (*args, project_root)
        return argparse.Namespace(paths=lambda: generated)

    monkeypatch.setattr(cli_module, "download_nyc_permitted_events_snapshot", download)
    monkeypatch.setattr(cli_module, "write_nyc_events_bundle", event_writer)
    monkeypatch.setattr(cli_module, "write_nyc_income_bundle", income_writer)
    event_outputs = cli_module._run_nyc_events(
        argparse.Namespace(
            holidays="holidays.csv",
            events="events.csv",
            panel_dir="panel",
            data_manifest="manifest.json",
            output_dir="event-output",
            refresh=False,
        )
    )
    income_outputs = cli_module._run_nyc_income(
        argparse.Namespace(
            taxi_zones="taxi.zip",
            nta="nta.geojson",
            tract_to_nta="tract.csv",
            acs_b19001="acs.dat",
            panel_dir="panel",
            data_manifest="manifest.json",
            output_dir="income-output",
        )
    )

    assert event_outputs == list(generated)
    assert income_outputs == list(generated)
    assert observed["event_download"] == ("events.csv", False)
    assert observed["event_writer"][:5] == (
        "holidays.csv",
        Path("events.csv"),
        "panel",
        "manifest.json",
        "event-output",
    )
    assert observed["income_writer"][:7] == (
        "taxi.zip",
        "nta.geojson",
        "tract.csv",
        "acs.dat",
        "panel",
        "manifest.json",
        "income-output",
    )


def test_offline_enrichment_gate_distinguishes_absent_partial_and_complete(
    tmp_path: Path,
) -> None:
    nyc_manifest = tmp_path / "manifest.json"
    panel = tmp_path / "panel"
    source_a = tmp_path / "source-a.csv"
    source_b = tmp_path / "source-b.csv"

    assert (
        cli_module._offline_enrichment_ready(
            "fixture",
            nyc_dependencies=(nyc_manifest, panel),
            external_sources=(source_a, source_b),
        )
        is False
    )
    nyc_manifest.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="complete NYC dependencies"):
        cli_module._offline_enrichment_ready(
            "fixture",
            nyc_dependencies=(nyc_manifest, panel),
            external_sources=(source_a, source_b),
        )
    panel.mkdir()
    assert (
        cli_module._offline_enrichment_ready(
            "fixture",
            nyc_dependencies=(nyc_manifest, panel),
            external_sources=(source_a, source_b),
        )
        is False
    )
    source_a.write_text("a", encoding="utf-8")
    with pytest.raises(ValueError, match="every pinned external source"):
        cli_module._offline_enrichment_ready(
            "fixture",
            nyc_dependencies=(nyc_manifest, panel),
            external_sources=(source_a, source_b),
        )
    source_b.write_text("b", encoding="utf-8")
    assert cli_module._offline_enrichment_ready(
        "fixture",
        nyc_dependencies=(nyc_manifest, panel),
        external_sources=(source_a, source_b),
    )


def test_cli_help_exits_successfully(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as raised:
        main(["--help"])
    assert raised.value.code == 0
    assert "reproduce-sample" in capsys.readouterr().out


def test_full_data_requires_explicit_build_opt_in_and_cannot_reproduce(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "full.yaml"
    config_path.write_text(
        "\n".join(
            [
                "source: nyc_hvfhv",
                "mode: full",
                f"project_root: {tmp_path}",
                "raw_dir: raw",
                "clean_dir: clean",
                "panel_dir: panel",
                "nyc_months: [1]",
            ]
        ),
        encoding="utf-8",
    )

    def unexpected_pipeline(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("full pipeline ran before explicit opt-in")

    monkeypatch.setattr(cli_module, "run_data_pipeline", unexpected_pipeline)
    with pytest.raises(ValueError, match="--allow-full-download"):
        main(["build-panel", "--config", str(config_path)])
    with pytest.raises(ValueError, match="--allow-full-download"):
        main(["validate-nyc-full", "--config", str(config_path)])

    args = argparse.Namespace(
        output_root=str(tmp_path / "artifacts"),
        config=str(config_path),
        simulation_config="configs/simulation.yaml",
        benchmark_config="configs/benchmark.yaml",
        policy_config="configs/policy.yaml",
        refresh=False,
    )
    with pytest.raises(ValueError, match="bounded mode: sample"):
        _run_reproduce(args)
    assert not (tmp_path / "artifacts/REPRODUCE_INCOMPLETE.json").exists()


def test_validate_nyc_full_publishes_empirical_calibration_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = argparse.Namespace(
        source="nyc_hvfhv",
        mode="full",
        raw_dir=tmp_path / "raw",
    )
    config.raw_dir.mkdir()
    data_manifest = tmp_path / "data-manifest.json"
    diagnostics = tmp_path / "diagnostics.json"
    analysis_file = tmp_path / "analysis.json"
    calibration_file = tmp_path / "calibration.json"
    for path in (data_manifest, diagnostics, analysis_file, calibration_file):
        path.write_text("{}\n", encoding="utf-8")
    data_artifacts = argparse.Namespace(
        raw_files=(),
        diagnostics_path=diagnostics,
        manifest_path=data_manifest,
    )
    analysis = argparse.Namespace(paths=lambda: (analysis_file,))
    calibration = argparse.Namespace(paths=lambda: (calibration_file,))

    monkeypatch.setattr(cli_module, "load_data_config", lambda _path: config)
    monkeypatch.setattr(cli_module, "nyc_hvfhv_urls", lambda _config: ())
    monkeypatch.setattr(cli_module, "run_data_pipeline", lambda *_args, **_kwargs: data_artifacts)
    monkeypatch.setattr(cli_module, "write_nyc_full_analysis", lambda *_args, **_kwargs: analysis)
    observed_output: list[Path] = []

    def write_calibration(_config: object, output: Path) -> object:
        observed_output.append(output)
        return calibration

    monkeypatch.setattr(cli_module, "write_nyc_calibration_bundle", write_calibration)
    outputs = cli_module._run_validate_nyc_full(
        argparse.Namespace(
            config="configs/full.yaml",
            output_dir=str(tmp_path / "artifacts"),
            refresh=False,
            allow_full_download=True,
        )
    )

    assert observed_output == [tmp_path / "artifacts/calibration_network"]
    assert calibration_file in outputs


def test_simulation_writer_uses_strict_json_for_unavailable_truth(tmp_path: Path) -> None:
    config = SimulationConfig(
        n_zones=3,
        n_periods=8,
        spillover_strength=0.2,
        persistence=0.3,
        design=DesignConfig(name="geo_cluster", n_clusters=3, seed=8),
        seed=7,
    )
    outputs = write_simulation_outputs(simulate_market(config), tmp_path)
    metadata_text = outputs["metadata"].read_text(encoding="utf-8")
    metadata = json.loads(metadata_text)
    assert ": NaN" not in metadata_text
    assert metadata["ground_truth"]["direct_effect"] is None
    assert metadata["ground_truth"]["intent_to_treat"] is None
    assert all(path.is_file() for path in outputs.values())


def test_hte_artifact_uses_cluster_holdout_and_known_matching_truth(tmp_path: Path) -> None:
    outputs = _write_hte_artifacts(
        SimulationConfig(n_zones=4, n_periods=16, seed=19),
        tmp_path,
    )
    summary = json.loads(outputs["summary"].read_text(encoding="utf-8"))
    assert summary["target_estimand"] == "controlled_zone_direct_effect"
    assert summary["crossfit_group"] == "geographic_randomization_cluster"
    assert summary["interference"] == 0.0
    assert summary["persistence"] == 0.0
    assert summary["rows"] == 8 * 16
    calibration = pd.read_csv(outputs["calibration"])
    assert {
        "mean_predicted_cate",
        "mean_known_truth",
        "mean_error",
        "rmse",
        "rows",
    }.issubset(calibration.columns)
    subgroup = pd.read_csv(outputs["subgroup_recovery"])
    assert {"mean_predicted_cate", "mean_known_truth", "mean_error"}.issubset(
        subgroup.columns
    )
    stability = pd.read_csv(outputs["fold_stability"])
    assert stability["crossfit_fold"].nunique() == 4
    assert outputs["calibration_chart"].read_text(encoding="utf-8").startswith("<!DOCTYPE html>")
    assert all(path.is_file() for path in outputs.values())


def test_reproduce_marker_invalidates_old_manifest_and_survives_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_root = tmp_path / "artifacts"
    output_root.mkdir()
    old_manifest = output_root / "reproduce_manifest.json"
    old_manifest.write_text("{}", encoding="utf-8")

    def fail(_args: argparse.Namespace) -> list[Path]:
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(cli_module, "_run_reproduce_inner", fail)
    args = argparse.Namespace(
        output_root=str(output_root),
        config="configs/sample.yaml",
        simulation_config="configs/simulation.yaml",
        benchmark_config="configs/benchmark.yaml",
        policy_config="configs/policy.yaml",
    )
    with pytest.raises(RuntimeError, match="synthetic failure"):
        _run_reproduce(args)
    assert not old_manifest.exists()
    marker = output_root / "REPRODUCE_INCOMPLETE.json"
    assert marker.is_file()
    assert json.loads(marker.read_text(encoding="utf-8"))["status"] == "incomplete"


def test_reproduce_marker_is_removed_only_after_final_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_root = tmp_path / "artifacts"

    def succeed(args: argparse.Namespace) -> list[Path]:
        manifest = Path(args.output_root) / "reproduce_manifest.json"
        manifest.write_text('{"files": []}', encoding="utf-8")
        return [manifest]

    monkeypatch.setattr(cli_module, "_run_reproduce_inner", succeed)
    args = argparse.Namespace(
        output_root=str(output_root),
        config="configs/sample.yaml",
        simulation_config="configs/simulation.yaml",
        benchmark_config="configs/benchmark.yaml",
        policy_config="configs/policy.yaml",
    )
    outputs = _run_reproduce(args)
    assert outputs == [output_root / "reproduce_manifest.json"]
    assert not (output_root / "REPRODUCE_INCOMPLETE.json").exists()
