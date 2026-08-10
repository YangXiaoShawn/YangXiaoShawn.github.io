"""Fail-closed descriptive validation for a streamed NYC full-month build."""

from __future__ import annotations

import json
import platform
import tempfile
from calendar import monthrange
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

import duckdb
import numpy as np
import pyarrow.parquet as pq

from casuallab.analysis import write_descriptive_artifacts
from casuallab.data import (
    NYC_HVFHV_RAW_SCHEMA,
    REQUIRED_RAW_COLUMNS,
    DataConfig,
    load_data_config,
    nyc_hvfhv_urls,
    read_partitioned_parquet,
    sha256_file,
    write_manifest,
)

try:  # pragma: no cover - resource is unavailable only on non-POSIX platforms.
    import resource
except ImportError:  # pragma: no cover
    resource = None  # type: ignore[assignment]


@dataclass(frozen=True, slots=True)
class NYCFullAnalysisArtifacts:
    """Generated validation, report, tables, and lineage manifest."""

    validation_path: Path
    report_path: Path
    daily_path: Path
    hourly_path: Path
    weekday_path: Path
    zone_path: Path
    od_month_path: Path
    descriptive_paths: tuple[Path, ...]
    manifest_path: Path

    def paths(self) -> tuple[Path, ...]:
        return (
            self.validation_path,
            self.report_path,
            self.daily_path,
            self.hourly_path,
            self.weekday_path,
            self.zone_path,
            self.od_month_path,
            *self.descriptive_paths,
            self.manifest_path,
        )


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (np.integer, np.floating)):
        value = value.item()
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def _atomic_text(text: str, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        prefix=f".{destination.stem}-",
        suffix=destination.suffix,
        dir=destination.parent,
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        handle.write(text)
    temporary.replace(destination)
    return destination


def _atomic_json(payload: Mapping[str, Any], destination: Path) -> Path:
    return _atomic_text(
        json.dumps(_json_safe(payload), indent=2, sort_keys=True, allow_nan=False) + "\n",
        destination,
    )


def _write_descriptive_artifacts_atomically(
    panel: Any,
    output_directory: Path,
) -> dict[str, Path]:
    """Stage descriptive outputs before atomically promoting each file."""

    output_directory.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f".{output_directory.name}-",
        dir=output_directory.parent,
    ) as temporary_directory:
        staged = write_descriptive_artifacts(panel, Path(temporary_directory))
        output_directory.mkdir(parents=True, exist_ok=True)
        promoted: dict[str, Path] = {}
        for name, staged_path in staged.items():
            destination = output_directory / staged_path.name
            staged_path.replace(destination)
            promoted[name] = destination
    return promoted


def _sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _portable_path(path: Path, project_root: Path) -> str:
    try:
        return str(path.resolve().relative_to(project_root.resolve()))
    except ValueError:
        return str(path.resolve())


def _scan_sql(paths: Sequence[Path]) -> str:
    if not paths:
        raise FileNotFoundError("expected at least one Parquet file")
    rendered = ", ".join(_sql_string(str(path.resolve())) for path in paths)
    return f"read_parquet([{rendered}], hive_partitioning=false)"


def _row(connection: duckdb.DuckDBPyConnection, query: str) -> dict[str, Any]:
    result = connection.execute(query)
    values = result.fetchone()
    if values is None:
        raise RuntimeError("validation query returned no row")
    return {
        description[0]: value
        for description, value in zip(result.description, values, strict=True)
    }


def _copy_csv(
    connection: duckdb.DuckDBPyConnection,
    query: str,
    destination: Path,
) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    temporary.unlink(missing_ok=True)
    try:
        connection.execute(
            f"COPY ({query}) TO {_sql_string(str(temporary.resolve()))} "
            "(FORMAT CSV, HEADER true)"
        )
        temporary.replace(destination)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return destination


def _manifest_integrity(manifest_path: Path, project_root: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    mismatches: list[str] = []
    for entry in manifest.get("files", []):
        path = Path(entry["path"])
        resolved = path if path.is_absolute() else project_root / path
        if not resolved.is_file():
            mismatches.append(f"missing:{entry['path']}")
            continue
        if resolved.stat().st_size != int(entry["bytes"]):
            mismatches.append(f"bytes:{entry['path']}")
            continue
        if sha256_file(resolved) != entry["sha256"]:
            mismatches.append(f"sha256:{entry['path']}")
    return {
        "entries": len(manifest.get("files", [])),
        "mismatches": mismatches,
        "all_files_valid": not mismatches,
        "config_is_full_nyc": (
            manifest.get("config", {}).get("source") == "nyc_hvfhv"
            and manifest.get("config", {}).get("mode") == "full"
        ),
        "causal_claim": manifest.get("metadata", {}).get("causal_claim"),
        "sample_selection_present": "sample_selection"
        in manifest.get("metadata", {}),
    }


def _max_rss_bytes() -> int | None:
    if resource is None:
        return None
    raw = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return raw if platform.system() == "Darwin" else raw * 1024


def write_nyc_full_analysis(
    config: DataConfig | str | Path,
    output_directory: str | Path,
    *,
    started_at_monotonic: float | None = None,
    raw_cached: bool = True,
    command: str | None = None,
    resource_overrides: Mapping[str, Any] | None = None,
) -> NYCFullAnalysisArtifacts:
    """Validate and summarize one completed full-month NYC pipeline build.

    All trip-level scans stay in DuckDB. Only compact scalar results and CSV
    aggregates are materialized in Python.
    """

    cfg = load_data_config(config) if not isinstance(config, DataConfig) else config
    if cfg.source != "nyc_hvfhv" or cfg.mode != "full":
        raise ValueError("NYC full analysis requires source=nyc_hvfhv and mode=full")
    if len(cfg.nyc_months) != 1:
        raise ValueError("NYC full analysis currently requires exactly one month")
    output = Path(output_directory)
    output.mkdir(parents=True, exist_ok=True)
    manifest_path = output / "manifest.json"
    analysis_incomplete = output / "NYC_FULL_ANALYSIS_INCOMPLETE.json"
    manifest_path.unlink(missing_ok=True)
    _atomic_json(
        {
            "status": "incomplete",
            "started_at_utc": datetime.now(UTC).isoformat(),
            "config": cfg.as_serializable_dict(),
            "interpretation": (
                "The NYC full-month analysis outputs must not be treated as a "
                "successful run while this marker exists."
            ),
        },
        analysis_incomplete,
    )
    incomplete = cfg.manifest_path.with_name("NYC_FULL_INCOMPLETE.json")
    if incomplete.exists():
        raise RuntimeError("NYC full pipeline is marked incomplete")
    if not cfg.manifest_path.is_file() or not cfg.diagnostics_path.is_file():
        raise FileNotFoundError("NYC full manifest and diagnostics are required")

    month = cfg.nyc_months[0]
    month_start = date(cfg.nyc_year, month, 1)
    next_month_start = (
        date(cfg.nyc_year + 1, 1, 1)
        if month == 12
        else date(cfg.nyc_year, month + 1, 1)
    )
    raw_files = tuple(
        cfg.raw_dir / Path(url).name for url in nyc_hvfhv_urls(cfg)
    )
    clean_files = tuple(sorted((cfg.clean_dir / "trips").rglob("*.parquet")))
    zone_files = tuple(sorted((cfg.panel_dir / "zone_time").rglob("*.parquet")))
    od_files = tuple(sorted((cfg.panel_dir / "od_flow").rglob("*.parquet")))
    for path in (*raw_files, *clean_files, *zone_files, *od_files):
        if not path.is_file():
            raise FileNotFoundError(path)

    parquet = pq.ParquetFile(raw_files[0])
    raw_schema = parquet.schema_arrow
    actual_columns = raw_schema.names
    required = REQUIRED_RAW_COLUMNS["nyc_hvfhv"]
    expected = set(NYC_HVFHV_RAW_SCHEMA)
    diagnostics = json.loads(cfg.diagnostics_path.read_text(encoding="utf-8"))
    integrity = _manifest_integrity(cfg.manifest_path, cfg.project_root.resolve())

    connection = duckdb.connect()
    connection.execute("SET threads = 1")
    connection.execute("SET memory_limit = '1GB'")
    connection.execute(f"CREATE TEMP VIEW clean AS SELECT * FROM {_scan_sql(clean_files)}")
    connection.execute(f"CREATE TEMP VIEW zone AS SELECT * FROM {_scan_sql(zone_files)}")
    connection.execute(f"CREATE TEMP VIEW od AS SELECT * FROM {_scan_sql(od_files)}")
    try:
        coverage = _row(
            connection,
            f"""
            SELECT
                count(*)::BIGINT AS clean_rows,
                count(*) FILTER (WHERE pickup_datetime IS NULL)::BIGINT
                    AS pickup_null_count,
                min(pickup_datetime) AS pickup_min,
                max(pickup_datetime) AS pickup_max,
                count(DISTINCT service_date)::INTEGER AS service_dates,
                count(DISTINCT hour(pickup_datetime))::INTEGER AS hours_of_day,
                count(DISTINCT date_trunc('hour', pickup_datetime))::INTEGER
                    AS date_hours,
                count(*) FILTER (
                    WHERE pickup_datetime < TIMESTAMP '{month_start.isoformat()}'
                    OR pickup_datetime >= TIMESTAMP '{next_month_start.isoformat()}'
                )::BIGINT AS outside_month_count,
                count(*) FILTER (
                    WHERE dropoff_datetime < pickup_datetime
                )::BIGINT AS reverse_timestamp_count,
                count(*) FILTER (
                    WHERE abs(trip_seconds - date_diff('second', pickup_datetime,
                        dropoff_datetime)) > 60
                )::BIGINT AS trip_time_delta_mismatch_count,
                count(*) FILTER (
                    WHERE pickup_zone_id IS NOT NULL AND dropoff_zone_id IS NOT NULL
                )::BIGINT AS observed_od_pairs,
                count(DISTINCT pickup_zone_id)::INTEGER AS pickup_zones,
                count(DISTINCT dropoff_zone_id)::INTEGER AS dropoff_zones
            FROM clean
            """,
        )
        zone_stats = _row(
            connection,
            """
            SELECT
                count(*)::BIGINT AS zone_time_rows,
                count(*) FILTER (WHERE trip_count > 0)::BIGINT
                    AS observed_zone_time_rows,
                count(*) FILTER (WHERE trip_count = 0)::BIGINT
                    AS synthesized_zero_rows,
                coalesce(sum(trip_count), 0)::BIGINT AS zone_trip_sum,
                coalesce(sum(od_pair_observed_count), 0)::BIGINT
                    AS zone_observed_od_pair_sum,
                count(*) - count(DISTINCT (source, zone_type, zone_id, time_bin))
                    AS zone_key_duplicates,
                count(DISTINCT zone_id)::INTEGER AS zones,
                count(DISTINCT time_bin)::INTEGER AS periods
            FROM zone
            """,
        )
        od_stats = _row(
            connection,
            """
            SELECT
                count(*)::BIGINT AS od_rows,
                coalesce(sum(trip_count), 0)::BIGINT AS od_trip_sum,
                count(*) - count(DISTINCT (
                    source, zone_type, origin_zone_id, destination_zone_id, time_bin
                )) AS od_key_duplicates,
                count(*) FILTER (WHERE trip_count <= 0)::BIGINT
                    AS od_nonpositive_rows
            FROM od
            """,
        )
        descriptive = _row(
            connection,
            """
            SELECT
                count(*)::BIGINT AS trip_count,
                count(fare)::BIGINT AS fare_known,
                avg(fare) AS fare_mean,
                median(fare) AS fare_median,
                quantile_cont(fare, 0.10) AS fare_p10,
                quantile_cont(fare, 0.90) AS fare_p90,
                quantile_cont(fare, 0.99) AS fare_p99,
                count(*) FILTER (WHERE fare < 0)::BIGINT AS negative_fare,
                count(*) FILTER (WHERE fare = 0)::BIGINT AS zero_fare,
                count(trip_miles)::BIGINT AS miles_known,
                avg(trip_miles) AS miles_mean,
                median(trip_miles) AS miles_median,
                quantile_cont(trip_miles, 0.90) AS miles_p90,
                count(trip_seconds)::BIGINT AS duration_known,
                avg(trip_seconds) / 60.0 AS duration_minutes_mean,
                median(trip_seconds) / 60.0 AS duration_minutes_median,
                quantile_cont(trip_seconds, 0.90) / 60.0
                    AS duration_minutes_p90,
                count(airport_trip)::BIGINT AS airport_known,
                avg(airport_trip::DOUBLE) AS airport_share,
                count(shared_requested)::BIGINT AS shared_requested_known,
                avg(shared_requested::DOUBLE) AS shared_requested_share,
                count(shared_matched)::BIGINT AS shared_matched_known,
                avg(shared_matched::DOUBLE) AS shared_matched_share,
                avg(shared_matched::DOUBLE) FILTER (WHERE shared_requested)
                    AS shared_matched_given_requested
            FROM clean
            """,
        )

        daily_path = _copy_csv(
            connection,
            """
            SELECT
                service_date,
                isodow(service_date)::INTEGER AS iso_weekday,
                count(*)::BIGINT AS trip_count,
                count(*)::DOUBLE / sum(count(*)) OVER () AS month_share,
                count(DISTINCT pickup_zone_id)::INTEGER AS active_zones,
                avg(fare) AS avg_fare,
                avg(airport_trip::DOUBLE) AS airport_share,
                avg(shared_requested::DOUBLE) AS shared_requested_share,
                avg(shared_matched::DOUBLE) AS shared_matched_share,
                'descriptive_real_data' AS evidence_label
            FROM clean
            GROUP BY service_date
            ORDER BY service_date
            """,
            output / "daily_summary.csv",
        )
        hourly_path = _copy_csv(
            connection,
            """
            SELECT
                hour(pickup_datetime)::INTEGER AS hour,
                count(*)::BIGINT AS trip_count,
                count(*)::DOUBLE / sum(count(*)) OVER () AS month_share,
                count(DISTINCT service_date)::INTEGER AS dates_observed,
                count(*)::DOUBLE / count(DISTINCT service_date)
                    AS mean_trips_per_date,
                avg(fare) AS avg_fare,
                avg(airport_trip::DOUBLE) AS airport_share,
                avg(shared_requested::DOUBLE) AS shared_requested_share,
                avg(shared_matched::DOUBLE) AS shared_matched_share,
                'descriptive_real_data' AS evidence_label
            FROM clean
            GROUP BY hour
            ORDER BY hour
            """,
            output / "hourly_summary.csv",
        )
        weekday_path = _copy_csv(
            connection,
            """
            SELECT
                isodow(service_date)::INTEGER AS iso_weekday,
                count(DISTINCT service_date)::INTEGER AS dates_in_month,
                count(*)::BIGINT AS total_trips,
                count(*)::DOUBLE / count(DISTINCT service_date)
                    AS mean_trips_per_date,
                avg(fare) AS avg_fare,
                avg(airport_trip::DOUBLE) AS airport_share,
                'descriptive_real_data' AS evidence_label
            FROM clean
            GROUP BY iso_weekday
            ORDER BY iso_weekday
            """,
            output / "weekday_summary.csv",
        )
        zone_path = _copy_csv(
            connection,
            """
            SELECT
                pickup_zone_id AS zone_id,
                count(*)::BIGINT AS trip_count,
                count(*)::DOUBLE / sum(count(*)) OVER () AS month_share,
                count(DISTINCT date_trunc('hour', pickup_datetime))::INTEGER
                    AS occupied_hours,
                avg(fare) AS avg_fare,
                avg(trip_miles) AS avg_trip_miles,
                avg(airport_trip::DOUBLE) AS airport_share,
                'descriptive_real_data' AS evidence_label
            FROM clean
            GROUP BY pickup_zone_id
            ORDER BY trip_count DESC, zone_id
            """,
            output / "zone_summary.csv",
        )
        od_month_path = _copy_csv(
            connection,
            """
            SELECT
                origin_zone_id,
                destination_zone_id,
                sum(trip_count)::BIGINT AS trip_count,
                sum(avg_fare * trip_count) / sum(trip_count) AS avg_fare,
                sum(avg_trip_miles * trip_count) / sum(trip_count)
                    AS avg_trip_miles,
                sum(trip_count)::DOUBLE
                    / sum(sum(trip_count)) OVER (PARTITION BY origin_zone_id)
                    AS origin_flow_share,
                'descriptive_real_data' AS evidence_label,
                'Observed flow; not a causal spatial-substitution estimate.'
                    AS interpretation_warning
            FROM od
            GROUP BY origin_zone_id, destination_zone_id
            ORDER BY origin_zone_id, trip_count DESC, destination_zone_id
            """,
            output / "od_month_summary.csv",
        )
    finally:
        connection.close()

    panel = read_partitioned_parquet(cfg.panel_dir / "zone_time")
    descriptive_outputs = _write_descriptive_artifacts_atomically(
        panel,
        output / "marketplace_associations",
    )
    panel_associations = json.loads(
        descriptive_outputs["moments"].read_text(encoding="utf-8")
    )

    expected_dates = monthrange(cfg.nyc_year, month)[1]
    expected_date_hours = expected_dates * 24
    raw_rows = sum(int(pq.ParquetFile(path).metadata.num_rows) for path in raw_files)
    raw_bytes = sum(path.stat().st_size for path in raw_files)
    max_rss = _max_rss_bytes()
    effective_max_rss = int(
        (resource_overrides or {}).get("max_rss_bytes", max_rss or 0)
    )
    checks = {
        "raw_equals_clean": raw_rows == int(coverage["clean_rows"]),
        "zone_conserves_clean": int(zone_stats["zone_trip_sum"])
        == int(coverage["clean_rows"]) - int(coverage["pickup_null_count"]),
        "od_conserves_clean": int(od_stats["od_trip_sum"])
        == int(coverage["clean_rows"]) - int(coverage["pickup_null_count"]),
        "zone_od_coverage_matches_clean": int(zone_stats["zone_observed_od_pair_sum"])
        == int(coverage["observed_od_pairs"]),
        "calendar_complete": (
            int(coverage["service_dates"]) == expected_dates
            and int(coverage["hours_of_day"]) == 24
            and int(coverage["date_hours"]) == expected_date_hours
            and int(coverage["outside_month_count"]) == 0
        ),
        "zone_keys_unique": int(zone_stats["zone_key_duplicates"]) == 0,
        "od_keys_unique": int(od_stats["od_key_duplicates"]) == 0,
        "od_counts_positive": int(od_stats["od_nonpositive_rows"]) == 0,
        "complete_zone_grid": (
            not cfg.complete_panel_grid
            or int(zone_stats["zone_time_rows"])
            == int(zone_stats["zones"]) * expected_date_hours
        ),
        "diagnostics_rows_match": int(diagnostics["row_count"])
        == int(coverage["clean_rows"]),
        "manifest_files_valid": bool(integrity["all_files_valid"]),
        "manifest_scope_valid": bool(integrity["config_is_full_nyc"])
        and integrity["causal_claim"] is False
        and not bool(integrity["sample_selection_present"]),
        "resource_limit_passed": 0 < effective_max_rss < 16 * 1024**3,
    }
    resources = {
        "command": command,
        "raw_cached": raw_cached,
        "elapsed_seconds": (
            perf_counter() - started_at_monotonic
            if started_at_monotonic is not None
            else None
        ),
        "max_rss_bytes": max_rss,
        "memory_limit_bytes": 16 * 1024**3,
        "input_bytes": raw_bytes,
        "final_data_bytes": sum(
            path.stat().st_size
            for path in cfg.manifest_path.parent.rglob("*")
            if path.is_file()
        ),
        "exit_status": 0,
    }
    resources.update(_json_safe(resource_overrides or {}))
    validation = {
        "evidence_label": "descriptive_real_data",
        "causal_claim": False,
        "validation_passed": all(checks.values()),
        "checks": checks,
        "scope": {
            "source": "nyc_hvfhv",
            "pickup_month": f"{cfg.nyc_year}-{month:02d}",
            "unit": "published_completed_trip_record",
            "population_claim": False,
        },
        "provenance": {
            "source_urls": list(nyc_hvfhv_urls(cfg)),
            "local_paths": [
                _portable_path(path, cfg.project_root)
                for path in raw_files
            ],
            "sha256": [sha256_file(path) for path in raw_files],
            "bytes": raw_bytes,
            "parquet_num_rows": raw_rows,
            "num_row_groups": sum(
                int(pq.ParquetFile(path).metadata.num_row_groups) for path in raw_files
            ),
            "data_manifest": _portable_path(cfg.manifest_path, cfg.project_root),
            "data_manifest_sha256": sha256_file(cfg.manifest_path),
        },
        "schema": {
            "actual": [
                {"name": field.name, "dtype": str(field.type)} for field in raw_schema
            ],
            "missing_required": sorted(required - set(actual_columns)),
            "missing_optional": sorted(expected - set(actual_columns) - required),
            "unexpected": sorted(set(actual_columns) - expected),
        },
        "coverage": coverage,
        "conservation": {**zone_stats, **od_stats, "raw_rows": raw_rows},
        "quality": {
            "diagnostics": diagnostics,
            "reverse_timestamp_count": coverage["reverse_timestamp_count"],
            "trip_time_delta_mismatch_count": coverage[
                "trip_time_delta_mismatch_count"
            ],
        },
        "descriptive": {
            **descriptive,
            "pickup_zones": coverage["pickup_zones"],
            "dropoff_zones": coverage["dropoff_zones"],
            "airport_definition": (
                "airport_fee > 0 or pickup/dropoff zone in {1, 132, 138}"
            ),
        },
        "panel_associations": panel_associations,
        "manifest_integrity": integrity,
        "resources": resources,
        "limitations": [
            "Published completed-trip records exclude latent and unserved demand.",
            "Observed fare-demand relationships are endogenous associations, not elasticities.",
            "Observed OD flows are connections, not causal spatial-substitution effects.",
            "No treatment assignment exists in these records; no causal intervention effect is estimated.",
            "The complete grid uses zones observed at least once in this published month.",
        ],
    }
    validation_path = _atomic_json(validation, output / "validation.json")
    rss_label = f"{effective_max_rss / 1024**3:.3f} GiB"
    report = f"""# NYC January 2024 full-month validation

Evidence label: `descriptive_real_data`; causal claim: **false**.

- Published trip records: {raw_rows:,}
- Pickup coverage: {coverage['pickup_min']} through {coverage['pickup_max']}
- Complete zone-hour rows: {int(zone_stats['zone_time_rows']):,}
  ({int(zone_stats['observed_zone_time_rows']):,} occupied and
  {int(zone_stats['synthesized_zero_rows']):,} zero-trip grid cells)
- OD-hour rows: {int(od_stats['od_rows']):,}
- Zone and OD trip-count sums: {int(zone_stats['zone_trip_sum']):,} and {int(od_stats['od_trip_sum']):,}
- Fare mean/median: {float(descriptive['fare_mean']):.4f} / {float(descriptive['fare_median']):.4f}
- Mean distance: {float(descriptive['miles_mean']):.4f} miles
- Mean duration: {float(descriptive['duration_minutes_mean']):.4f} minutes
- Airport-trip share: {float(descriptive['airport_share']):.4%}
- Shared-request / shared-match shares: {float(descriptive['shared_requested_share']):.4%} / {float(descriptive['shared_matched_share']):.4%}
- Exact one-hour zone-demand association: {panel_associations['zone_exact_lag_demand_correlation_association']:.4f}
  across {int(panel_associations['zone_exact_lag_support_pairs']):,} adjacent-hour pairs;
  this is not a causal persistence parameter.
- Peak RSS: {rss_label}
- Validation passed: **{all(checks.values())}**

These are descriptive facts about the pinned published object. They are not a
population model of latent demand and do not identify fare elasticity, spatial
substitution, or the effect of any discount or incentive.
"""
    report_path = _atomic_text(report, output / "full_month_report.md")
    output_files = (
        validation_path,
        report_path,
        daily_path,
        hourly_path,
        weekday_path,
        zone_path,
        od_month_path,
        *descriptive_outputs.values(),
        cfg.manifest_path,
        cfg.diagnostics_path,
    )
    manifest_path = write_manifest(
        output_files,
        manifest_path,
        config=cfg,
        root=cfg.project_root,
        metadata={
            "evidence_label": "descriptive_real_data",
            "causal_claim": False,
            "validation_passed": all(checks.values()),
            "source_data_manifest_sha256": sha256_file(cfg.manifest_path),
        },
    )
    if not manifest_path.is_file():
        raise RuntimeError("NYC full analysis completed without a final hash manifest")
    analysis_incomplete.unlink(missing_ok=True)
    return NYCFullAnalysisArtifacts(
        validation_path=validation_path,
        report_path=report_path,
        daily_path=daily_path,
        hourly_path=hourly_path,
        weekday_path=weekday_path,
        zone_path=zone_path,
        od_month_path=od_month_path,
        descriptive_paths=tuple(descriptive_outputs.values()),
        manifest_path=manifest_path,
    )


__all__ = ["NYCFullAnalysisArtifacts", "write_nyc_full_analysis"]
