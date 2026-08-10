"""Command-line entry points for the reproducible sample workflow."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path

from macro_nowcast import pipeline

Command = Callable[[Path], dict[str, object]]


def _reproduce_multitarget(
    config: Path,
    *,
    output_dir: Path | None,
) -> dict[str, object]:
    from macro_nowcast.multitarget_pipeline import reproduce_multitarget

    return reproduce_multitarget(config, output_dir=output_dir)


def _run(command: Command, config: Path) -> int:
    result = command(config.resolve())
    for key, value in result.items():
        print(f"{key}: {value}")
    return 0


def _run_multitarget(config: Path, output_dir: Path | None) -> int:
    result = _reproduce_multitarget(
        config.resolve(),
        output_dir=output_dir.resolve() if output_dir is not None else None,
    )
    for key, value in result.items():
        print(f"{key}: {value}")
    return 0


def _run_agency_vintage_audit(raw_dir: Path, output: Path) -> int:
    from macro_nowcast.archive_audit import write_agency_vintage_audit

    result = write_agency_vintage_audit(raw_dir.resolve(), output.resolve())
    for key, value in result.items():
        print(f"{key}: {value}")
    return 0


def _run_empsit_clock_index(
    source_dir: Path,
    release_index: Path,
    *,
    overwrite: bool,
) -> int:
    from macro_nowcast.bls_empsit_clock_archive import (
        write_empsit_text_clock_index,
    )

    result = write_empsit_text_clock_index(
        source_dir.resolve(),
        release_index.resolve(),
        overwrite=overwrite,
    )
    for key, value in result.items():
        print(f"{key}: {value}")
    return 0


def _run_dol_claims_acquisition(
    output_dir: Path,
    *,
    start_year: int,
    end_year: int | None,
    workers: int,
) -> int:
    from macro_nowcast.dol_claims_archive import acquire_dol_claims_archive

    result = acquire_dol_claims_archive(
        output_dir.resolve(),
        start_year=start_year,
        end_year=end_year,
        workers=workers,
    )
    for key, value in result.items():
        print(f"{key}: {value}")
    return 0


def _run_fed_g17_acquisition(
    output_dir: Path,
    *,
    start_year: int,
    end_year: int | None,
    workers: int,
) -> int:
    from macro_nowcast.fed_g17_archive import acquire_fed_g17_archive

    result = acquire_fed_g17_archive(
        output_dir.resolve(),
        start_year=start_year,
        end_year=end_year,
        workers=workers,
    )
    for key, value in result.items():
        print(f"{key}: {value}")
    return 0


def _run_treasury_rates_acquisition(
    output_dir: Path,
    *,
    start_year: int,
    end_year: int | None,
) -> int:
    from macro_nowcast.treasury_rates_archive import acquire_treasury_rates_archive

    result = acquire_treasury_rates_archive(
        output_dir.resolve(),
        start_year=start_year,
        end_year=end_year,
    )
    for key, value in result.items():
        print(f"{key}: {value}")
    return 0


def _run_bea_nipa_level_acquisition(
    output_dir: Path,
    clock_evidence: Path,
    published_growth: Path,
    *,
    workers: int,
) -> int:
    from macro_nowcast.bea_nipa_archive import acquire_bea_nipa_level_archive

    result = acquire_bea_nipa_level_archive(
        output_dir.resolve(),
        clock_evidence_path=clock_evidence.resolve(),
        published_growth_path=published_growth.resolve(),
        workers=workers,
    )
    for key, value in result.items():
        print(f"{key}: {value}")
    return 0


def _run_bea_nipa_level_audit(
    source_dir: Path,
    clock_evidence: Path,
    published_growth: Path,
) -> int:
    from macro_nowcast.bea_nipa_archive import audit_bea_nipa_level_archive

    result = audit_bea_nipa_level_archive(
        source_dir.resolve(),
        clock_evidence_path=clock_evidence.resolve(),
        published_growth_path=published_growth.resolve(),
    )
    for key, value in result.items():
        print(f"{key}: {value}")
    return 0


def _run_census_retail_acquisition(
    output_dir: Path,
    *,
    start_year: int,
    end_year: int | None,
    workers: int,
) -> int:
    from macro_nowcast.census_retail_archive import acquire_census_retail_archive

    result = acquire_census_retail_archive(
        output_dir.resolve(),
        start_year=start_year,
        end_year=end_year,
        workers=workers,
    )
    for key, value in result.items():
        print(f"{key}: {value}")
    return 0


def _run_census_housing_acquisition(
    output_dir: Path,
    *,
    start_year: int,
    end_year: int | None,
    workers: int,
) -> int:
    from macro_nowcast.census_housing_archive import acquire_census_housing_archive

    result = acquire_census_housing_archive(
        output_dir.resolve(),
        start_year=start_year,
        end_year=end_year,
        workers=workers,
    )
    for key, value in result.items():
        print(f"{key}: {value}")
    return 0


def _run_official_vintage_ingestion(
    raw_dir: Path,
    output_dir: Path,
    *,
    overwrite: bool,
) -> int:
    from macro_nowcast.archive_ingestion import write_official_archive_data

    result = write_official_archive_data(
        raw_dir.resolve(),
        output_dir.resolve(),
        overwrite=overwrite,
    )
    for key, value in result.items():
        print(f"{key}: {value}")
    return 0


def _run_official_pilot(
    source_dir: Path,
    output_dir: Path,
    *,
    overwrite: bool,
) -> int:
    from macro_nowcast.official_pipeline import reproduce_official_pilot

    result = reproduce_official_pilot(
        source_dir.resolve(),
        output_dir=output_dir.resolve(),
        overwrite=overwrite,
    )
    for key, value in result.items():
        print(f"{key}: {value}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="macro-nowcast",
        description="Vintage-aware real-time macro nowcasting research engine",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command, help_text in [
        ("prepare-sample", "Create deterministic, explicitly synthetic source fixtures"),
        ("build-vintages", "Build canonical Parquet and DuckDB vintage artifacts"),
        ("validate-asof", "Run strict as-of information-boundary validation"),
        ("backtest", "Run expanding-window model and revision comparisons"),
        ("policy-brief", "Generate the structured sample release policy brief"),
        ("report", "Generate reports and portfolio deliverables"),
        ("reproduce-sample", "Run the complete offline fixture workflow"),
        ("clean-generated", "Remove only reproducible files under configured output dirs"),
    ]:
        child = subparsers.add_parser(command, help=help_text)
        child.add_argument("--config", type=Path, default=Path("config/sample.toml"))

    multitarget = subparsers.add_parser(
        "reproduce-multitarget",
        help="Run the complete offline three-target workflow",
    )
    multitarget.add_argument(
        "--config",
        type=Path,
        default=Path("config/targets.toml"),
    )
    multitarget.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Override the configured multi-target artifact directory",
    )
    archive_audit = subparsers.add_parser(
        "audit-agency-vintages",
        help="Verify downloaded official BLS/BEA historical archive artifacts",
    )
    archive_audit.add_argument(
        "--raw-dir",
        type=Path,
        default=Path("data/raw/agency_vintages"),
    )
    archive_audit.add_argument(
        "--output",
        type=Path,
        default=Path("data/generated/agency_vintages/audit_manifest.json"),
    )
    empsit_clock_index = subparsers.add_parser(
        "index-empsit-clocks",
        help="Index and verify browser-downloaded official BLS text clock evidence",
    )
    empsit_clock_index.add_argument(
        "--source-dir",
        type=Path,
        default=Path("data/raw/agency_vintages/bls-empsit-clock-txt"),
    )
    empsit_clock_index.add_argument(
        "--release-index",
        type=Path,
        default=Path("data/raw/agency_vintages/empsit-release-index.json"),
    )
    empsit_clock_index.add_argument(
        "--overwrite",
        action="store_true",
        help="Explicitly replace a prior text-clock evidence index",
    )
    dol_claims = subparsers.add_parser(
        "acquire-dol-claims",
        help="Acquire and verify official DOL weekly-claims release vintages",
    )
    dol_claims.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/raw/agency_vintages/dol-ui-claims"),
    )
    dol_claims.add_argument("--start-year", type=int, default=2002)
    dol_claims.add_argument("--end-year", type=int, default=None)
    dol_claims.add_argument("--workers", type=int, default=4)
    fed_g17 = subparsers.add_parser(
        "acquire-fed-g17",
        help="Acquire and verify official Federal Reserve G.17 release vintages",
    )
    fed_g17.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/raw/agency_vintages/fed-g17"),
    )
    fed_g17.add_argument("--start-year", type=int, default=1997)
    fed_g17.add_argument("--end-year", type=int, default=None)
    fed_g17.add_argument("--workers", type=int, default=4)
    treasury_rates = subparsers.add_parser(
        "acquire-treasury-rates",
        help="Acquire and verify official daily Treasury 10-year CMT observations",
    )
    treasury_rates.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/raw/agency_vintages/treasury-yield-curve"),
    )
    treasury_rates.add_argument("--start-year", type=int, default=2002)
    treasury_rates.add_argument("--end-year", type=int, default=None)
    bea_nipa = subparsers.add_parser(
        "acquire-bea-nipa-levels",
        help="Acquire and verify official BEA NIPA real-GDP level snapshots",
    )
    bea_nipa.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/raw/agency_vintages/bea-nipa-levels"),
    )
    bea_nipa.add_argument(
        "--clock-evidence",
        type=Path,
        default=Path("data/raw/agency_vintages/bea-gdp-news/clock-evidence.json"),
    )
    bea_nipa.add_argument(
        "--published-growth",
        type=Path,
        default=Path("data/raw/agency_vintages/gdp-gdi-vintage-history.xlsx"),
    )
    bea_nipa.add_argument("--workers", type=int, default=4)
    bea_nipa_audit = subparsers.add_parser(
        "audit-bea-nipa-levels",
        help="Re-run the BEA NIPA level archive audit without network access",
    )
    bea_nipa_audit.add_argument(
        "--source-dir",
        type=Path,
        default=Path("data/raw/agency_vintages/bea-nipa-levels"),
    )
    bea_nipa_audit.add_argument(
        "--clock-evidence",
        type=Path,
        default=Path("data/raw/agency_vintages/bea-gdp-news/clock-evidence.json"),
    )
    bea_nipa_audit.add_argument(
        "--published-growth",
        type=Path,
        default=Path("data/raw/agency_vintages/gdp-gdi-vintage-history.xlsx"),
    )
    census_retail = subparsers.add_parser(
        "acquire-census-retail",
        help="Acquire and verify official Census MARTS release vintages",
    )
    census_retail.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/raw/agency_vintages/census-marts"),
    )
    census_retail.add_argument("--start-year", type=int, default=2003)
    census_retail.add_argument("--end-year", type=int, default=None)
    census_retail.add_argument("--workers", type=int, default=4)
    census_housing = subparsers.add_parser(
        "acquire-census-housing",
        help="Acquire and verify official Census NRC housing-start vintages",
    )
    census_housing.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/raw/agency_vintages/census-nrc"),
    )
    census_housing.add_argument("--start-year", type=int, default=2003)
    census_housing.add_argument("--end-year", type=int, default=None)
    census_housing.add_argument("--workers", type=int, default=4)
    archive_ingestion = subparsers.add_parser(
        "ingest-agency-vintages",
        help="Parse audited BLS/BEA archives into frozen Parquet and DuckDB artifacts",
    )
    archive_ingestion.add_argument(
        "--raw-dir",
        type=Path,
        default=Path("data/raw/agency_vintages"),
    )
    archive_ingestion.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/generated/official_vintages"),
    )
    archive_ingestion.add_argument(
        "--overwrite",
        action="store_true",
        help="Explicitly replace previously generated official-vintage artifacts",
    )
    official_pilot = subparsers.add_parser(
        "reproduce-official-pilot",
        help="Run the empirical target-archive pilot with audited mixed-precision timing",
    )
    official_pilot.add_argument(
        "--source-dir",
        type=Path,
        default=Path("data/generated/official_vintages"),
    )
    official_pilot.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/generated/official_pilot"),
    )
    official_pilot.add_argument(
        "--overwrite",
        action="store_true",
        help="Explicitly replace a prior official-pilot run",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "reproduce-multitarget":
        return _run_multitarget(args.config, args.output_dir)
    if args.command == "audit-agency-vintages":
        return _run_agency_vintage_audit(args.raw_dir, args.output)
    if args.command == "index-empsit-clocks":
        return _run_empsit_clock_index(
            args.source_dir,
            args.release_index,
            overwrite=args.overwrite,
        )
    if args.command == "acquire-dol-claims":
        return _run_dol_claims_acquisition(
            args.output_dir,
            start_year=args.start_year,
            end_year=args.end_year,
            workers=args.workers,
        )
    if args.command == "acquire-fed-g17":
        return _run_fed_g17_acquisition(
            args.output_dir,
            start_year=args.start_year,
            end_year=args.end_year,
            workers=args.workers,
        )
    if args.command == "acquire-treasury-rates":
        return _run_treasury_rates_acquisition(
            args.output_dir,
            start_year=args.start_year,
            end_year=args.end_year,
        )
    if args.command == "acquire-bea-nipa-levels":
        return _run_bea_nipa_level_acquisition(
            args.output_dir,
            args.clock_evidence,
            args.published_growth,
            workers=args.workers,
        )
    if args.command == "audit-bea-nipa-levels":
        return _run_bea_nipa_level_audit(
            args.source_dir,
            args.clock_evidence,
            args.published_growth,
        )
    if args.command == "acquire-census-retail":
        return _run_census_retail_acquisition(
            args.output_dir,
            start_year=args.start_year,
            end_year=args.end_year,
            workers=args.workers,
        )
    if args.command == "acquire-census-housing":
        return _run_census_housing_acquisition(
            args.output_dir,
            start_year=args.start_year,
            end_year=args.end_year,
            workers=args.workers,
        )
    if args.command == "ingest-agency-vintages":
        return _run_official_vintage_ingestion(
            args.raw_dir,
            args.output_dir,
            overwrite=args.overwrite,
        )
    if args.command == "reproduce-official-pilot":
        return _run_official_pilot(
            args.source_dir,
            args.output_dir,
            overwrite=args.overwrite,
        )
    commands: dict[str, Command] = {
        "prepare-sample": pipeline.prepare_sample,
        "build-vintages": pipeline.build_vintages,
        "validate-asof": pipeline.validate_asof,
        "backtest": pipeline.backtest,
        "policy-brief": pipeline.policy_brief,
        "report": pipeline.report,
        "reproduce-sample": pipeline.reproduce_sample,
        "clean-generated": pipeline.clean_generated,
    }
    return _run(commands[args.command], args.config)


if __name__ == "__main__":
    raise SystemExit(main())
