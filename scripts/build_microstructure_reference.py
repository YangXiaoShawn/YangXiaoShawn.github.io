#!/usr/bin/env python3
"""Build a bounded public summary from the exploratory Microstructure run.

The source bundle remains local. This exporter whitelists only low-dimensional
scenario metrics and provenance needed by the website and static Space.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import tomllib
from pathlib import Path

import polars as pl


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUTS = (
    ROOT / "assets" / "data" / "microstructure_backtest_reference.json",
    ROOT / "apps" / "space" / "microstructure_backtest_reference.json",
)
DEFAULT_SCENARIO = "BTCUSDT::primary_test::clock_1000ms::d1::o1"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def distribution(values: list[float]) -> dict[str, float]:
    return {
        "min": round(min(values), 6),
        "median": round(statistics.median(values), 6),
        "max": round(max(values), 6),
    }


def verify_bundle(run_root: Path) -> tuple[int, int]:
    passed = 0
    failed = 0
    for line in (run_root / "CHECKSUMS.sha256").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        expected, relative = line.split(maxsplit=1)
        candidate = run_root / relative.lstrip("* ")
        if candidate.is_file() and sha256(candidate) == expected:
            passed += 1
        else:
            failed += 1
    return passed, failed


def build(run_root: Path) -> dict[str, object]:
    summary_path = run_root / "summary.json"
    report_path = run_root / "report.md"
    manifest_path = run_root / "manifest.json"
    checksums_path = run_root / "CHECKSUMS.sha256"
    metrics_path = run_root / "execution" / "scenario_metrics.parquet"
    config_path = run_root / "evidence" / "analysis_config.toml"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    metrics = pl.read_parquet(metrics_path).sort(
        ["symbol", "study_role", "endpoint_name", "decision_latency_events", "order_latency_events"]
    )

    if metrics.height != 144 or summary.get("execution_scenarios") != metrics.height:
        raise ValueError("Expected the complete 144-scenario execution grid")
    if sha256(metrics_path) != summary.get("execution_metrics_sha256"):
        raise ValueError("Scenario metrics checksum differs from the frozen summary")
    if not metrics["scenario_only"].all():
        raise ValueError("Every exported row must be scenario-only")
    for claim in ("capacity_claim_authorized", "realized_execution_claim_authorized", "profitability_claim_authorized"):
        if metrics[claim].any():
            raise ValueError(f"Unexpected authorized claim in {claim}")

    pnl_identity_error = (
        metrics["net_pnl"] - (metrics["gross_pnl"] - metrics["total_fees"])
    ).abs().max()
    if float(pnl_identity_error) > 1e-9:
        raise ValueError("Net P&L identity does not hold")
    fee_edges = (metrics["total_fees"] / metrics["turnover_notional"] * 10_000).to_list()
    if max(abs(float(value) - 4.0) for value in fee_edges) > 1e-9:
        raise ValueError("The exported scenarios do not share the frozen 4 bp fee")

    verified_files, failed_files = verify_bundle(run_root)
    if failed_files:
        raise ValueError(f"Bundle checksum verification failed for {failed_files} file(s)")

    scenario_fields = {
        "scenario_id": "scenario_id",
        "symbol": "symbol",
        "phase": "study_role",
        "endpoint": "endpoint_name",
        "decision_latency_events": "decision_latency_events",
        "order_latency_events": "order_latency_events",
        "orders": "strategy_orders",
        "fills": "strategy_fills",
        "forced_liquidation_fills": "forced_liquidation_fills",
        "fill_ratio_requested": "fill_ratio_requested",
        "gross_pnl_usdt": "gross_pnl",
        "fees_usdt": "total_fees",
        "net_pnl_usdt": "net_pnl",
        "turnover_usdt": "turnover_notional",
        "gross_edge_bps": "gross_edge_bps",
        "fee_edge_bps": None,
        "net_edge_bps": "net_edge_bps",
        "max_drawdown_usdt": "maximum_drawdown",
        "max_drawdown_bps_of_turnover": "maximum_drawdown_bps_of_turnover",
        "unliquidated_quantity": "unliquidated_quantity",
        "valuation": "unliquidated_valuation",
    }
    scenarios: list[dict[str, object]] = []
    for row, fee_edge in zip(metrics.to_dicts(), fee_edges, strict=True):
        public_row: dict[str, object] = {}
        for public_name, source_name in scenario_fields.items():
            value = fee_edge if source_name is None else row[source_name]
            if isinstance(value, float):
                value = round(value, 6)
            public_row[public_name] = value
        scenarios.append(public_row)

    default = next((row for row in scenarios if row["scenario_id"] == DEFAULT_SCENARIO), None)
    if default is None:
        raise ValueError(f"Default scenario missing: {DEFAULT_SCENARIO}")

    execution = config["execution"]
    endpoints = [item["name"] for item in config["endpoints"]]
    payload: dict[str, object] = {
        "schema_version": "microstructure-exploratory-public-summary-v1",
        "evidence_tier": summary["evidence_tier"],
        "status": summary["status"],
        "badge": "EXPLORATORY_SIMULATION_REFERENCE_ONLY",
        "run_id": run_root.name,
        "sample": {
            "start_utc": summary["phases"][0]["start_utc"],
            "end_utc": summary["phases"][-1]["end_utc"],
            "phases": summary["phases"],
        },
        "design": {
            "symbols": config["study"]["symbols"],
            "evaluation_phases": ["primary_test", "replication_test"],
            "endpoints": endpoints,
            "decision_latency_events": sorted(metrics["decision_latency_events"].unique().to_list()),
            "order_latency_events": sorted(metrics["order_latency_events"].unique().to_list()),
            "order_type": "market",
            "taker_fee_bps": 4.0,
            "extra_slippage_bps": execution["extra_slippage_bps"],
            "probability_threshold": execution["probability_threshold"],
            "reference_order_notional_usd": execution["order_notional_usd"],
            "max_l1_participation": execution["max_l1_participation"],
            "liquidate_at_end": execution["liquidate_at_end"],
        },
        "overview": {
            "aggregation_semantics": "distribution_across_counterfactual_scenarios_not_portfolio_sum",
            "scenario_count": metrics.height,
            "gross_positive_count": int((metrics["gross_pnl"] > 0).sum()),
            "net_positive_count": int((metrics["net_pnl"] > 0).sum()),
            "gross_pnl_usdt": distribution(metrics["gross_pnl"].to_list()),
            "fees_usdt": distribution(metrics["total_fees"].to_list()),
            "net_pnl_usdt": distribution(metrics["net_pnl"].to_list()),
            "gross_edge_bps": distribution(metrics["gross_edge_bps"].to_list()),
            "fee_edge_bps": distribution(fee_edges),
            "net_edge_bps": distribution(metrics["net_edge_bps"].to_list()),
            "max_drawdown_usdt": distribution(metrics["maximum_drawdown"].to_list()),
            "max_drawdown_bps_of_turnover": distribution(
                metrics["maximum_drawdown_bps_of_turnover"].to_list()
            ),
            "pnl_identity_max_error": round(float(pnl_identity_error), 12),
        },
        "default_scenario_id": DEFAULT_SCENARIO,
        "default_selection_rule": (
            "First configured symbol, first pseudo-heldout phase, the interpretable one-second "
            "endpoint, and the midpoint latency grid; not selected by performance."
        ),
        "default_scenario": default,
        "scenarios": scenarios,
        "provenance": {
            "source_commit": summary["source"]["commit"],
            "source_dirty": summary["source"]["dirty"],
            "scenario_metrics_sha256": sha256(metrics_path),
            "summary_sha256": sha256(summary_path),
            "report_sha256": sha256(report_path),
            "manifest_sha256": sha256(manifest_path),
            "checksums_sha256": sha256(checksums_path),
            "verified_files": verified_files,
            "failed_files": failed_files,
        },
        "claim_boundary": summary["claim_boundary"],
        "disclaimer": (
            "Research reference only. This is a deterministic market-order simulation from one "
            "four-hour nonconfirmatory L2 pilot, not live trading. The adjacent pseudo-heldout phases "
            "are not prospectively untouched or cross-day replication. The 144 scenarios reuse "
            "overlapping data and must not be summed. Drawdown is marked net equity from zero initial "
            "capital and normalized by turnover; it is not account return or capital-based drawdown."
        ),
    }
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-run", type=Path, required=True)
    parser.add_argument("--output", action="append", type=Path)
    args = parser.parse_args()
    payload = build(args.source_run.resolve())
    outputs = tuple(args.output) if args.output else DEFAULT_OUTPUTS
    encoded = json.dumps(payload, ensure_ascii=True, indent=2) + "\n"
    for output in outputs:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(encoded, encoding="utf-8")
        print(f"microstructure-reference-ok path={output.relative_to(ROOT)} scenarios=144")


if __name__ == "__main__":
    main()
