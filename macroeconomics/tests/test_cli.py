from __future__ import annotations

from pathlib import Path

from macro_nowcast import cli

LEGACY_COMMANDS = (
    "prepare-sample",
    "build-vintages",
    "validate-asof",
    "backtest",
    "policy-brief",
    "report",
    "reproduce-sample",
    "clean-generated",
)


def test_parser_preserves_legacy_commands_and_defaults() -> None:
    parser = cli.build_parser()

    for command in LEGACY_COMMANDS:
        args = parser.parse_args([command])
        assert args.command == command
        assert args.config == Path("config/sample.toml")


def test_multitarget_parser_uses_dedicated_default_config() -> None:
    args = cli.build_parser().parse_args(["reproduce-multitarget"])

    assert args.command == "reproduce-multitarget"
    assert args.config == Path("config/targets.toml")
    assert args.output_dir is None
    assert set(vars(args)) == {"command", "config", "output_dir"}


def test_multitarget_parser_accepts_config_and_output_overrides() -> None:
    args = cli.build_parser().parse_args(
        [
            "reproduce-multitarget",
            "--config",
            "custom/targets.toml",
            "--output-dir",
            "custom/artifacts",
        ]
    )

    assert args.config == Path("custom/targets.toml")
    assert args.output_dir == Path("custom/artifacts")


def test_agency_vintage_audit_parser_defaults() -> None:
    args = cli.build_parser().parse_args(["audit-agency-vintages"])

    assert args.command == "audit-agency-vintages"
    assert args.raw_dir == Path("data/raw/agency_vintages")
    assert args.output == Path("data/generated/agency_vintages/audit_manifest.json")


def test_empsit_clock_index_parser_defaults() -> None:
    args = cli.build_parser().parse_args(["index-empsit-clocks"])

    assert args.command == "index-empsit-clocks"
    assert args.source_dir == Path(
        "data/raw/agency_vintages/bls-empsit-clock-txt"
    )
    assert args.release_index == Path(
        "data/raw/agency_vintages/empsit-release-index.json"
    )
    assert args.overwrite is False


def test_dol_claims_acquisition_parser_defaults() -> None:
    args = cli.build_parser().parse_args(["acquire-dol-claims"])

    assert args.command == "acquire-dol-claims"
    assert args.output_dir == Path("data/raw/agency_vintages/dol-ui-claims")
    assert args.start_year == 2002
    assert args.end_year is None
    assert args.workers == 4


def test_fed_g17_acquisition_parser_defaults() -> None:
    args = cli.build_parser().parse_args(["acquire-fed-g17"])

    assert args.command == "acquire-fed-g17"
    assert args.output_dir == Path("data/raw/agency_vintages/fed-g17")
    assert args.start_year == 1997
    assert args.end_year is None
    assert args.workers == 4


def test_treasury_rates_acquisition_parser_defaults() -> None:
    args = cli.build_parser().parse_args(["acquire-treasury-rates"])

    assert args.command == "acquire-treasury-rates"
    assert args.output_dir == Path("data/raw/agency_vintages/treasury-yield-curve")
    assert args.start_year == 2002
    assert args.end_year is None


def test_bea_nipa_level_commands_use_audited_source_defaults() -> None:
    parser = cli.build_parser()
    acquisition = parser.parse_args(["acquire-bea-nipa-levels"])
    audit = parser.parse_args(["audit-bea-nipa-levels"])

    assert acquisition.output_dir == Path(
        "data/raw/agency_vintages/bea-nipa-levels"
    )
    assert acquisition.clock_evidence == Path(
        "data/raw/agency_vintages/bea-gdp-news/clock-evidence.json"
    )
    assert acquisition.published_growth == Path(
        "data/raw/agency_vintages/gdp-gdi-vintage-history.xlsx"
    )
    assert acquisition.workers == 4
    assert audit.source_dir == acquisition.output_dir
    assert audit.clock_evidence == acquisition.clock_evidence
    assert audit.published_growth == acquisition.published_growth


def test_census_retail_acquisition_parser_defaults() -> None:
    args = cli.build_parser().parse_args(["acquire-census-retail"])

    assert args.command == "acquire-census-retail"
    assert args.output_dir == Path("data/raw/agency_vintages/census-marts")
    assert args.start_year == 2003
    assert args.end_year is None
    assert args.workers == 4


def test_census_housing_acquisition_parser_defaults() -> None:
    args = cli.build_parser().parse_args(["acquire-census-housing"])

    assert args.command == "acquire-census-housing"
    assert args.output_dir == Path("data/raw/agency_vintages/census-nrc")
    assert args.start_year == 2003
    assert args.end_year is None
    assert args.workers == 4


def test_agency_vintage_ingestion_parser_defaults() -> None:
    args = cli.build_parser().parse_args(["ingest-agency-vintages"])

    assert args.command == "ingest-agency-vintages"
    assert args.raw_dir == Path("data/raw/agency_vintages")
    assert args.output_dir == Path("data/generated/official_vintages")
    assert args.overwrite is False


def test_official_pilot_parser_defaults() -> None:
    args = cli.build_parser().parse_args(["reproduce-official-pilot"])

    assert args.command == "reproduce-official-pilot"
    assert args.source_dir == Path("data/generated/official_vintages")
    assert args.output_dir == Path("data/generated/official_pilot")
    assert args.overwrite is False


def test_multitarget_main_dispatches_without_running_workflow(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    calls: list[tuple[Path, Path | None]] = []

    def fake_reproduce_multitarget(
        config_path: Path,
        *,
        output_dir: Path | None = None,
    ) -> dict[str, object]:
        calls.append((config_path, output_dir))
        return {
            "status": "complete",
            "network_used": False,
            "forecasts": 0,
        }

    monkeypatch.setattr(
        cli,
        "_reproduce_multitarget",
        fake_reproduce_multitarget,
    )
    monkeypatch.chdir(tmp_path)

    result = cli.main(
        [
            "reproduce-multitarget",
            "--config",
            "config/targets.toml",
            "--output-dir",
            "artifacts/multitarget",
        ]
    )

    assert result == 0
    assert calls == [
        (
            (tmp_path / "config/targets.toml").resolve(),
            (tmp_path / "artifacts/multitarget").resolve(),
        )
    ]
    assert capsys.readouterr().out.splitlines() == [
        "status: complete",
        "network_used: False",
        "forecasts: 0",
    ]


def test_multitarget_main_passes_none_for_default_output_dir(
    monkeypatch,
    tmp_path: Path,
) -> None:
    calls: list[tuple[Path, Path | None]] = []

    def fake_reproduce_multitarget(
        config_path: Path,
        *,
        output_dir: Path | None = None,
    ) -> dict[str, object]:
        calls.append((config_path, output_dir))
        return {"status": "complete"}

    monkeypatch.setattr(
        cli,
        "_reproduce_multitarget",
        fake_reproduce_multitarget,
    )
    monkeypatch.chdir(tmp_path)

    assert cli.main(["reproduce-multitarget"]) == 0
    assert calls == [((tmp_path / "config/targets.toml").resolve(), None)]


def test_legacy_main_dispatch_remains_unchanged(monkeypatch, tmp_path: Path) -> None:
    calls: list[Path] = []

    def fake_prepare_sample(config_path: Path) -> dict[str, object]:
        calls.append(config_path)
        return {"fixture_label": "synthetic_fixture"}

    monkeypatch.setattr(cli.pipeline, "prepare_sample", fake_prepare_sample)
    monkeypatch.chdir(tmp_path)

    assert cli.main(["prepare-sample"]) == 0
    assert calls == [(tmp_path / "config/sample.toml").resolve()]


def test_agency_vintage_audit_main_dispatches_paths(monkeypatch, tmp_path: Path) -> None:
    calls: list[tuple[Path, Path]] = []

    def fake_audit(raw_dir: Path, output: Path) -> int:
        calls.append((raw_dir, output))
        return 0

    monkeypatch.setattr(cli, "_run_agency_vintage_audit", fake_audit)
    monkeypatch.chdir(tmp_path)

    assert cli.main(["audit-agency-vintages"]) == 0
    assert calls == [
        (
            Path("data/raw/agency_vintages"),
            Path("data/generated/agency_vintages/audit_manifest.json"),
        )
    ]


def test_empsit_clock_index_main_dispatches_paths(monkeypatch) -> None:
    calls: list[tuple[Path, Path, bool]] = []

    def fake_index(
        source_dir: Path,
        release_index: Path,
        *,
        overwrite: bool,
    ) -> int:
        calls.append((source_dir, release_index, overwrite))
        return 0

    monkeypatch.setattr(cli, "_run_empsit_clock_index", fake_index)

    assert cli.main(["index-empsit-clocks", "--overwrite"]) == 0
    assert calls == [
        (
            Path("data/raw/agency_vintages/bls-empsit-clock-txt"),
            Path("data/raw/agency_vintages/empsit-release-index.json"),
            True,
        )
    ]


def test_agency_vintage_ingestion_main_dispatches_paths(monkeypatch) -> None:
    calls: list[tuple[Path, Path, bool]] = []

    def fake_ingestion(raw_dir: Path, output_dir: Path, *, overwrite: bool) -> int:
        calls.append((raw_dir, output_dir, overwrite))
        return 0

    monkeypatch.setattr(cli, "_run_official_vintage_ingestion", fake_ingestion)

    assert cli.main(["ingest-agency-vintages", "--overwrite"]) == 0
    assert calls == [
        (
            Path("data/raw/agency_vintages"),
            Path("data/generated/official_vintages"),
            True,
        )
    ]


def test_dol_claims_acquisition_main_dispatches(monkeypatch) -> None:
    calls: list[tuple[Path, int, int | None, int]] = []

    def fake_acquisition(
        output_dir: Path,
        *,
        start_year: int,
        end_year: int | None,
        workers: int,
    ) -> int:
        calls.append((output_dir, start_year, end_year, workers))
        return 0

    monkeypatch.setattr(cli, "_run_dol_claims_acquisition", fake_acquisition)

    assert cli.main(
        [
            "acquire-dol-claims",
            "--output-dir",
            "raw/claims",
            "--start-year",
            "2010",
            "--end-year",
            "2020",
            "--workers",
            "2",
        ]
    ) == 0
    assert calls == [(Path("raw/claims"), 2010, 2020, 2)]


def test_fed_g17_acquisition_main_dispatches(monkeypatch) -> None:
    calls: list[tuple[Path, int, int | None, int]] = []

    def fake_acquisition(
        output_dir: Path,
        *,
        start_year: int,
        end_year: int | None,
        workers: int,
    ) -> int:
        calls.append((output_dir, start_year, end_year, workers))
        return 0

    monkeypatch.setattr(cli, "_run_fed_g17_acquisition", fake_acquisition)

    assert cli.main(
        [
            "acquire-fed-g17",
            "--output-dir",
            "raw/g17",
            "--start-year",
            "2000",
            "--end-year",
            "2024",
            "--workers",
            "3",
        ]
    ) == 0
    assert calls == [(Path("raw/g17"), 2000, 2024, 3)]


def test_treasury_rates_acquisition_main_dispatches(monkeypatch) -> None:
    calls: list[tuple[Path, int, int | None]] = []

    def fake_acquisition(
        output_dir: Path,
        *,
        start_year: int,
        end_year: int | None,
    ) -> int:
        calls.append((output_dir, start_year, end_year))
        return 0

    monkeypatch.setattr(cli, "_run_treasury_rates_acquisition", fake_acquisition)

    assert cli.main(
        [
            "acquire-treasury-rates",
            "--output-dir",
            "raw/treasury",
            "--start-year",
            "2002",
            "--end-year",
            "2024",
        ]
    ) == 0
    assert calls == [(Path("raw/treasury"), 2002, 2024)]


def test_bea_nipa_level_acquisition_main_dispatches(monkeypatch) -> None:
    calls: list[tuple[Path, Path, Path, int]] = []

    def fake_acquisition(
        output_dir: Path,
        clock_evidence: Path,
        published_growth: Path,
        *,
        workers: int,
    ) -> int:
        calls.append((output_dir, clock_evidence, published_growth, workers))
        return 0

    monkeypatch.setattr(cli, "_run_bea_nipa_level_acquisition", fake_acquisition)

    assert cli.main(
        [
            "acquire-bea-nipa-levels",
            "--output-dir",
            "raw/nipa",
            "--clock-evidence",
            "raw/clocks.json",
            "--published-growth",
            "raw/growth.xlsx",
            "--workers",
            "3",
        ]
    ) == 0
    assert calls == [
        (
            Path("raw/nipa"),
            Path("raw/clocks.json"),
            Path("raw/growth.xlsx"),
            3,
        )
    ]


def test_census_retail_acquisition_main_dispatches(monkeypatch) -> None:
    calls: list[tuple[Path, int, int | None, int]] = []

    def fake_acquisition(
        output_dir: Path,
        *,
        start_year: int,
        end_year: int | None,
        workers: int,
    ) -> int:
        calls.append((output_dir, start_year, end_year, workers))
        return 0

    monkeypatch.setattr(cli, "_run_census_retail_acquisition", fake_acquisition)

    assert cli.main(
        [
            "acquire-census-retail",
            "--output-dir",
            "raw/marts",
            "--start-year",
            "2012",
            "--end-year",
            "2024",
            "--workers",
            "3",
        ]
    ) == 0
    assert calls == [(Path("raw/marts"), 2012, 2024, 3)]


def test_census_housing_acquisition_main_dispatches(monkeypatch) -> None:
    calls: list[tuple[Path, int, int | None, int]] = []

    def fake_acquisition(
        output_dir: Path,
        *,
        start_year: int,
        end_year: int | None,
        workers: int,
    ) -> int:
        calls.append((output_dir, start_year, end_year, workers))
        return 0

    monkeypatch.setattr(cli, "_run_census_housing_acquisition", fake_acquisition)

    assert cli.main(
        [
            "acquire-census-housing",
            "--output-dir",
            "raw/nrc",
            "--start-year",
            "2003",
            "--end-year",
            "2024",
            "--workers",
            "3",
        ]
    ) == 0
    assert calls == [(Path("raw/nrc"), 2003, 2024, 3)]


def test_official_pilot_main_dispatches_paths(monkeypatch) -> None:
    calls: list[tuple[Path, Path, bool]] = []

    def fake_pilot(source_dir: Path, output_dir: Path, *, overwrite: bool) -> int:
        calls.append((source_dir, output_dir, overwrite))
        return 0

    monkeypatch.setattr(cli, "_run_official_pilot", fake_pilot)

    assert cli.main(["reproduce-official-pilot", "--overwrite"]) == 0
    assert calls == [
        (
            Path("data/generated/official_vintages"),
            Path("data/generated/official_pilot"),
            True,
        )
    ]
