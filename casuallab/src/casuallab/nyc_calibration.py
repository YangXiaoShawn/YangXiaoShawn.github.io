"""Laptop-safe descriptive calibration and network inputs for NYC HVFHV data.

The public API in this module deliberately separates observed completed-trip
moments from causal or structural assumptions.  Trip-level Parquet is scanned by
DuckDB; only scalar results and compact aggregate CSVs cross into Python.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import duckdb
import numpy as np

from casuallab.config import SimulationConfig
from casuallab.data import DataConfig, load_data_config, sha256_file

EVIDENCE_LABEL = "descriptive_real_data"
CAUSAL_WARNING = (
    "Published completed-trip associations are descriptive and do not identify "
    "treatment response, spillovers, persistence, substitution, or welfare."
)


@dataclass(frozen=True, slots=True)
class NYCCalibrationSettings:
    """Runtime and design choices for a calibration bundle.

    ``target_cluster_count`` is a proposed experiment-design input.  It is not
    estimated by the observed OD graph.
    """

    memory_limit: str = "1GB"
    threads: int = 1
    exact_lag_hours: tuple[int, ...] = (1, 24, 168)
    target_cluster_count: int = 16
    verify_source_hashes: bool = True

    def __post_init__(self) -> None:
        if not self.memory_limit.strip():
            raise ValueError("memory_limit must not be empty")
        if self.threads < 1:
            raise ValueError("threads must be positive")
        if not self.exact_lag_hours or any(lag < 1 for lag in self.exact_lag_hours):
            raise ValueError("exact_lag_hours must contain positive integers")
        if len(set(self.exact_lag_hours)) != len(self.exact_lag_hours):
            raise ValueError("exact_lag_hours must not contain duplicates")
        if self.target_cluster_count < 2:
            raise ValueError("target_cluster_count must be at least two")

    def to_dict(self) -> dict[str, Any]:
        return {
            "memory_limit": self.memory_limit,
            "threads": self.threads,
            "exact_lag_hours": list(self.exact_lag_hours),
            "target_cluster_count": self.target_cluster_count,
            "verify_source_hashes": self.verify_source_hashes,
        }


@dataclass(frozen=True, slots=True)
class NYCCalibrationArtifacts:
    """Paths in one successfully published calibration/network bundle."""

    output_directory: Path
    calibration_path: Path
    hour_profile_path: Path
    zone_profile_path: Path
    edge_path: Path
    exposure_mapping_path: Path
    node_path: Path
    autocorrelation_path: Path
    manifest_path: Path

    def paths(self) -> tuple[Path, ...]:
        return (
            self.calibration_path,
            self.hour_profile_path,
            self.zone_profile_path,
            self.edge_path,
            self.exposure_mapping_path,
            self.node_path,
            self.autocorrelation_path,
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


def _atomic_json(payload: Mapping[str, Any], destination: Path) -> Path:
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
        json.dump(_json_safe(payload), handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
    temporary.replace(destination)
    return destination


def _sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _scan_sql(paths: Sequence[Path]) -> str:
    if not paths:
        raise FileNotFoundError("expected at least one Parquet input")
    rendered = ", ".join(_sql_string(str(path.resolve())) for path in paths)
    return (
        f"read_parquet([{rendered}], union_by_name=true, "
        "hive_partitioning=false)"
    )


def _parquet_files(directory: Path) -> tuple[Path, ...]:
    files = tuple(sorted(directory.rglob("*.parquet")))
    if not files:
        raise FileNotFoundError(f"no Parquet files found under {directory}")
    return files


def _portable_path(path: Path, project_root: Path) -> str:
    try:
        return str(path.resolve().relative_to(project_root.resolve()))
    except ValueError:
        # Never serialize a machine-specific absolute path.  External inputs remain
        # recognizable by filename and are explicitly flagged in provenance.
        return path.name


def _row(connection: duckdb.DuckDBPyConnection, query: str) -> dict[str, Any]:
    result = connection.execute(query)
    values = result.fetchone()
    if values is None:
        raise RuntimeError("calibration query returned no row")
    return {
        description[0]: value
        for description, value in zip(result.description, values, strict=True)
    }


def _copy_csv(
    connection: duckdb.DuckDBPyConnection,
    query: str,
    destination: Path,
) -> Path:
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


def _manifest_declared_digest(entries: Sequence[Mapping[str, Any]]) -> str:
    canonical = json.dumps(
        [
            {
                "path": str(entry.get("path")),
                "bytes": int(entry.get("bytes", -1)),
                "sha256": str(entry.get("sha256")),
            }
            for entry in entries
        ],
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def _verify_source_manifest(
    manifest_path: Path,
    project_root: Path,
    queried_files: Sequence[Path],
    *,
    verify_hashes: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = manifest.get("files", [])
    if not isinstance(entries, list):
        raise ValueError("source data manifest files must be a list")

    resolved_entries: dict[Path, Mapping[str, Any]] = {}
    mismatches: list[str] = []
    for entry in entries:
        if not isinstance(entry, Mapping) or "path" not in entry:
            mismatches.append("malformed_manifest_entry")
            continue
        entry_path = Path(str(entry["path"]))
        resolved = (
            entry_path.resolve()
            if entry_path.is_absolute()
            else (project_root / entry_path).resolve()
        )
        resolved_entries[resolved] = entry
        portable = _portable_path(resolved, project_root)
        if not resolved.is_file():
            mismatches.append(f"missing:{portable}")
            continue
        if resolved.stat().st_size != int(entry.get("bytes", -1)):
            mismatches.append(f"bytes:{portable}")
            continue
        if verify_hashes and sha256_file(resolved) != entry.get("sha256"):
            mismatches.append(f"sha256:{portable}")

    missing_queried = sorted(
        _portable_path(path, project_root)
        for path in queried_files
        if path.resolve() not in resolved_entries
    )
    mismatches.extend(f"not_in_manifest:{path}" for path in missing_queried)
    metadata = manifest.get("metadata", {})
    config = manifest.get("config", {})
    scope_valid = (
        isinstance(config, Mapping)
        and config.get("source") == "nyc_hvfhv"
        and config.get("mode") == "full"
        and isinstance(metadata, Mapping)
        and metadata.get("causal_claim") is False
    )
    validation = {
        "path": _portable_path(manifest_path, project_root),
        "sha256": sha256_file(manifest_path),
        "entries": len(entries),
        "declared_file_set_sha256": _manifest_declared_digest(entries),
        "hashes_recomputed": verify_hashes,
        "queried_files_listed": not missing_queried,
        "scope_is_full_nyc_descriptive": scope_valid,
        "mismatches": mismatches,
        "all_valid": not mismatches and scope_valid,
    }
    return manifest, validation


def _trip_moments(connection: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    values = _row(
        connection,
        """
        WITH trip_values AS (
            SELECT
                date_diff('second', request_datetime, pickup_datetime) / 60.0
                    AS wait_minutes,
                fare,
                driver_pay
            FROM clean
        )
        SELECT
            count(*)::BIGINT AS trip_rows,
            count(wait_minutes)::BIGINT AS wait_published_rows,
            count(*) FILTER (WHERE wait_minutes >= 0)::BIGINT AS wait_valid_rows,
            count(*) FILTER (WHERE wait_minutes < 0)::BIGINT AS wait_negative_rows,
            count(*) FILTER (WHERE wait_minutes = 0)::BIGINT AS wait_zero_rows,
            avg(wait_minutes) FILTER (WHERE wait_minutes >= 0) AS wait_mean,
            stddev_pop(wait_minutes) FILTER (WHERE wait_minutes >= 0) AS wait_stddev,
            min(wait_minutes) FILTER (WHERE wait_minutes >= 0) AS wait_min,
            approx_quantile(wait_minutes, 0.10) FILTER (WHERE wait_minutes >= 0)
                AS wait_p10,
            approx_quantile(wait_minutes, 0.25) FILTER (WHERE wait_minutes >= 0)
                AS wait_p25,
            approx_quantile(wait_minutes, 0.50) FILTER (WHERE wait_minutes >= 0)
                AS wait_p50,
            approx_quantile(wait_minutes, 0.75) FILTER (WHERE wait_minutes >= 0)
                AS wait_p75,
            approx_quantile(wait_minutes, 0.90) FILTER (WHERE wait_minutes >= 0)
                AS wait_p90,
            approx_quantile(wait_minutes, 0.95) FILTER (WHERE wait_minutes >= 0)
                AS wait_p95,
            approx_quantile(wait_minutes, 0.99) FILTER (WHERE wait_minutes >= 0)
                AS wait_p99,
            max(wait_minutes) FILTER (WHERE wait_minutes >= 0) AS wait_max,
            count(fare)::BIGINT AS fare_known_rows,
            count(*) FILTER (WHERE fare < 0)::BIGINT AS fare_negative_rows,
            count(*) FILTER (WHERE fare = 0)::BIGINT AS fare_zero_rows,
            sum(fare) AS fare_sum,
            avg(fare) AS fare_mean,
            stddev_pop(fare) AS fare_stddev,
            min(fare) AS fare_min,
            approx_quantile(fare, 0.10) AS fare_p10,
            approx_quantile(fare, 0.50) AS fare_p50,
            approx_quantile(fare, 0.90) AS fare_p90,
            approx_quantile(fare, 0.99) AS fare_p99,
            max(fare) AS fare_max,
            count(driver_pay)::BIGINT AS driver_pay_known_rows,
            count(*) FILTER (WHERE driver_pay < 0)::BIGINT
                AS driver_pay_negative_rows,
            count(*) FILTER (WHERE driver_pay = 0)::BIGINT AS driver_pay_zero_rows,
            sum(driver_pay) AS driver_pay_sum,
            avg(driver_pay) AS driver_pay_mean,
            stddev_pop(driver_pay) AS driver_pay_stddev,
            min(driver_pay) AS driver_pay_min,
            approx_quantile(driver_pay, 0.10) AS driver_pay_p10,
            approx_quantile(driver_pay, 0.50) AS driver_pay_p50,
            approx_quantile(driver_pay, 0.90) AS driver_pay_p90,
            approx_quantile(driver_pay, 0.99) AS driver_pay_p99,
            max(driver_pay) AS driver_pay_max,
            corr(fare, driver_pay) AS fare_driver_pay_correlation,
            sum(driver_pay) / nullif(sum(fare), 0) AS driver_pay_to_base_fare_ratio
        FROM trip_values
        """,
    )
    wait_keys = (
        "published_rows",
        "valid_rows",
        "negative_rows",
        "zero_rows",
        "mean",
        "stddev",
        "min",
        "p10",
        "p25",
        "p50",
        "p75",
        "p90",
        "p95",
        "p99",
        "max",
    )
    money_keys = (
        "known_rows",
        "negative_rows",
        "zero_rows",
        "sum",
        "mean",
        "stddev",
        "min",
        "p10",
        "p50",
        "p90",
        "p99",
        "max",
    )
    return {
        "trip_rows": values["trip_rows"],
        "request_to_pickup_wait_minutes": {
            "available": int(values["wait_published_rows"]) > 0,
            **{key: values[f"wait_{key}"] for key in wait_keys},
            "source_fields": ["request_datetime", "pickup_datetime"],
            "unit": "minutes",
            "validity_rule": "request_datetime and pickup_datetime published; nonnegative difference",
            "quantile_method": "duckdb_approx_quantile_tdigest",
            "interpretation": (
                "Request-to-pickup elapsed time is available only where both published "
                "timestamps are non-null. It is a service-process proxy, not latent "
                "rider utility or an intervention effect."
            ),
            "evidence_label": EVIDENCE_LABEL,
        },
        "fare": {
            **{key: values[f"fare_{key}"] for key in money_keys},
            "source_field": "base_passenger_fare normalized as fare",
            "unit": "nominal_usd_per_published_trip",
            "quantile_method": "duckdb_approx_quantile_tdigest",
            "evidence_label": EVIDENCE_LABEL,
        },
        "driver_pay": {
            **{key: values[f"driver_pay_{key}"] for key in money_keys},
            "source_field": "driver_pay",
            "unit": "nominal_usd_per_published_trip",
            "quantile_method": "duckdb_approx_quantile_tdigest",
            "interpretation": (
                "Published trip-level driver pay is not driver availability, opportunity "
                "cost, platform margin, or the causal effect of an incentive."
            ),
            "evidence_label": EVIDENCE_LABEL,
        },
        "fare_driver_pay_associations": {
            "pearson_correlation": values["fare_driver_pay_correlation"],
            "aggregate_driver_pay_to_base_fare_ratio": values[
                "driver_pay_to_base_fare_ratio"
            ],
            "interpretation": (
                "Both quantities are descriptive accounting associations. Base passenger "
                "fare is not total rider payment or platform revenue."
            ),
            "evidence_label": EVIDENCE_LABEL,
        },
    }


def _variance_decomposition(connection: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    values = _row(
        connection,
        """
        WITH cells AS (
            SELECT zone_id, time_bin, hour(time_bin)::INTEGER AS hour, trip_count::DOUBLE AS y
            FROM zone
        ),
        grand AS (
            SELECT count(*)::BIGINT AS n, avg(y) AS mean_y, var_pop(y) AS total_variance
            FROM cells
        ),
        zone_means AS (
            SELECT zone_id, count(*)::BIGINT AS n, avg(y) AS mean_y
            FROM cells GROUP BY zone_id
        ),
        hour_means AS (
            SELECT hour, count(*)::BIGINT AS n, avg(y) AS mean_y
            FROM cells GROUP BY hour
        ),
        zone_between AS (
            SELECT
                sum(z.n * power(z.mean_y - g.mean_y, 2)) / g.n
                    AS between_component
            FROM zone_means z
            CROSS JOIN grand g
            GROUP BY g.n
        ),
        zone_within AS (
            SELECT sum(power(c.y - z.mean_y, 2)) / g.n AS within_component
            FROM cells c
            JOIN zone_means z USING (zone_id)
            CROSS JOIN grand g
            GROUP BY g.n
        ),
        hour_between AS (
            SELECT
                sum(h.n * power(h.mean_y - g.mean_y, 2)) / g.n
                    AS between_component
            FROM hour_means h
            CROSS JOIN grand g
            GROUP BY g.n
        ),
        hour_within AS (
            SELECT sum(power(c.y - h.mean_y, 2)) / g.n AS within_component
            FROM cells c
            JOIN hour_means h USING (hour)
            CROSS JOIN grand g
            GROUP BY g.n
        )
        SELECT
            g.n AS panel_cells,
            (SELECT count(*) FROM zone_means)::INTEGER AS zones,
            count(DISTINCT c.time_bin)::INTEGER AS periods,
            g.mean_y AS mean_completed_trips_per_zone_hour,
            g.total_variance AS total_cell_variance,
            zb.between_component AS between_zone_component,
            zw.within_component AS within_zone_temporal_component,
            zb.between_component / nullif(g.total_variance, 0)
                AS icc_like_between_zone_share,
            zb.between_component + zw.within_component - g.total_variance
                AS zone_decomposition_residual,
            hb.between_component AS between_hour_of_day_component,
            hw.within_component AS within_hour_of_day_component,
            hb.between_component / nullif(g.total_variance, 0)
                AS between_hour_of_day_share,
            hb.between_component + hw.within_component - g.total_variance
                AS hour_decomposition_residual,
            count(*) FILTER (WHERE c.y > 0)::BIGINT AS occupied_cells,
            sum(c.y)::BIGINT AS total_completed_trips
        FROM cells c
        CROSS JOIN grand g
        CROSS JOIN zone_between zb
        CROSS JOIN zone_within zw
        CROSS JOIN hour_between hb
        CROSS JOIN hour_within hw
        GROUP BY ALL
        """,
    )
    return {
        **values,
        "variance_definition": "population variance across complete pickup-zone x hour cells",
        "icc_like_definition": (
            "weighted between-zone variance component divided by total cell variance"
        ),
        "interpretation": (
            "The ICC-like share is a descriptive variance decomposition, not a fitted "
            "random-effects ICC, a design effect, or evidence of causal interference."
        ),
        "evidence_label": EVIDENCE_LABEL,
    }


def _conservation(connection: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    clean = _row(
        connection,
        """
        SELECT
            count(*)::BIGINT AS clean_rows,
            count(*) FILTER (WHERE pickup_datetime IS NULL)::BIGINT
                AS pickup_datetime_null_rows,
            count(DISTINCT pickup_zone_id)::INTEGER AS pickup_zones,
            min(pickup_datetime) AS pickup_min,
            max(pickup_datetime) AS pickup_max
        FROM clean
        """,
    )
    zone = _row(
        connection,
        """
        SELECT
            count(*)::BIGINT AS zone_rows,
            sum(trip_count)::BIGINT AS zone_trip_sum,
            count(*) - count(DISTINCT (zone_id, time_bin)) AS zone_key_duplicates,
            count(DISTINCT zone_id)::INTEGER AS zones,
            count(DISTINCT time_bin)::INTEGER AS periods,
            count(*) FILTER (WHERE trip_count = 0)::BIGINT AS zero_trip_cells
        FROM zone
        """,
    )
    od = _row(
        connection,
        """
        SELECT
            count(*)::BIGINT AS od_hour_rows,
            sum(trip_count)::BIGINT AS od_trip_sum,
            count(*) - count(DISTINCT (origin_zone_id, destination_zone_id, time_bin))
                AS od_key_duplicates,
            count(*) FILTER (WHERE trip_count <= 0)::BIGINT AS nonpositive_od_rows
        FROM od
        """,
    )
    return {**clean, **zone, **od}


def _create_graph_tables(connection: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    connection.execute(
        """
        CREATE TEMP TABLE od_month AS
        SELECT
            origin_zone_id,
            destination_zone_id,
            sum(trip_count)::BIGINT AS trip_count
        FROM od
        GROUP BY origin_zone_id, destination_zone_id
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE od_edges AS
        SELECT
            least(origin_zone_id, destination_zone_id) AS zone_a,
            greatest(origin_zone_id, destination_zone_id) AS zone_b,
            sum(trip_count)::BIGINT AS edge_weight,
            sum(CASE
                WHEN origin_zone_id = least(origin_zone_id, destination_zone_id)
                    THEN trip_count ELSE 0 END)::BIGINT AS trips_a_to_b,
            sum(CASE
                WHEN origin_zone_id = greatest(origin_zone_id, destination_zone_id)
                    THEN trip_count ELSE 0 END)::BIGINT AS trips_b_to_a
        FROM od_month
        WHERE origin_zone_id <> destination_zone_id
        GROUP BY zone_a, zone_b
        """
    )
    return _row(
        connection,
        """
        WITH totals AS (
            SELECT
                count(*)::BIGINT AS directed_pairs,
                sum(trip_count)::BIGINT AS total_trips,
                sum(trip_count) FILTER (
                    WHERE origin_zone_id = destination_zone_id
                )::BIGINT AS intra_zone_trips,
                count(DISTINCT origin_zone_id)::INTEGER AS origin_nodes,
                count(DISTINCT destination_zone_id)::INTEGER AS destination_nodes
            FROM od_month
        ),
        edge_stats AS (
            SELECT
                count(*)::BIGINT AS undirected_cross_zone_edges,
                sum(edge_weight)::BIGINT AS cross_zone_trips,
                sum(power(edge_weight::DOUBLE, 2)) /
                    nullif(power(sum(edge_weight)::DOUBLE, 2), 0) AS edge_weight_hhi
            FROM od_edges
        ),
        ranked AS (
            SELECT edge_weight, row_number() OVER (
                ORDER BY edge_weight DESC, zone_a, zone_b
            ) AS rank
            FROM od_edges
        )
        SELECT
            t.directed_pairs,
            e.undirected_cross_zone_edges,
            greatest(t.origin_nodes, t.destination_nodes)::INTEGER AS nodes,
            t.total_trips,
            coalesce(t.intra_zone_trips, 0)::BIGINT AS intra_zone_trips,
            e.cross_zone_trips,
            e.cross_zone_trips::DOUBLE / nullif(t.total_trips, 0) AS cross_zone_share,
            e.undirected_cross_zone_edges::DOUBLE /
                nullif(greatest(t.origin_nodes, t.destination_nodes) *
                    (greatest(t.origin_nodes, t.destination_nodes) - 1) / 2, 0)
                AS undirected_density,
            e.edge_weight_hhi,
            (SELECT sum(edge_weight) FROM ranked WHERE rank <= 10)::DOUBLE /
                nullif(e.cross_zone_trips, 0) AS top_10_edge_weight_share
        FROM totals t CROSS JOIN edge_stats e
        """,
    )


def _edge_query() -> str:
    return f"""
        SELECT
            zone_a,
            zone_b,
            edge_weight,
            trips_a_to_b,
            trips_b_to_a,
            edge_weight::DOUBLE / sum(edge_weight) OVER () AS cross_zone_weight_share,
            '{EVIDENCE_LABEL}' AS evidence_label,
            'Undirected completed-trip flow weight; not a spillover estimate.'
                AS interpretation_warning
        FROM od_edges
        ORDER BY edge_weight DESC, zone_a, zone_b
    """


def _exposure_mapping_query() -> str:
    """Return the edge schema consumed by ``add_mapped_exposures``.

    Each monthly undirected flow edge is represented in both focal directions.
    Downstream exposure code row-normalizes the nonnegative raw weights.
    """

    return f"""
        WITH directed_mapping AS (
            SELECT
                zone_a AS focal_zone_id,
                zone_b AS neighbor_zone_id,
                edge_weight::DOUBLE AS weight
            FROM od_edges
            UNION ALL
            SELECT
                zone_b AS focal_zone_id,
                zone_a AS neighbor_zone_id,
                edge_weight::DOUBLE AS weight
            FROM od_edges
        )
        SELECT
            focal_zone_id,
            neighbor_zone_id,
            weight,
            '{EVIDENCE_LABEL}' AS evidence_label,
            'Symmetric monthly completed-trip flow; downstream row-normalizes weight.'
                AS weight_definition,
            'Pre-treatment exposure-map input; not an estimated spillover effect.'
                AS interpretation_warning
        FROM directed_mapping
        ORDER BY focal_zone_id, weight DESC, neighbor_zone_id
    """


def _node_query() -> str:
    return f"""
        WITH nodes AS (
            SELECT origin_zone_id AS zone_id FROM od_month
            UNION
            SELECT destination_zone_id AS zone_id FROM od_month
        ),
        out_shares AS (
            SELECT
                origin_zone_id AS zone_id,
                destination_zone_id,
                trip_count,
                trip_count::DOUBLE / sum(trip_count) OVER (PARTITION BY origin_zone_id)
                    AS destination_share
            FROM od_month
        ),
        outgoing AS (
            SELECT
                zone_id,
                sum(trip_count)::BIGINT AS outbound_trips,
                count(*)::INTEGER AS outbound_destinations_including_self,
                count(*) FILTER (WHERE destination_zone_id <> zone_id)::INTEGER
                    AS cross_zone_out_degree,
                sum(power(destination_share, 2)) AS outbound_destination_hhi,
                sum(trip_count) FILTER (WHERE destination_zone_id = zone_id)::BIGINT
                    AS self_loop_trips
            FROM out_shares
            GROUP BY zone_id
        ),
        incoming AS (
            SELECT
                destination_zone_id AS zone_id,
                sum(trip_count)::BIGINT AS inbound_trips,
                count(*) FILTER (WHERE origin_zone_id <> destination_zone_id)::INTEGER
                    AS cross_zone_in_degree
            FROM od_month
            GROUP BY destination_zone_id
        ),
        strength_rows AS (
            SELECT zone_a AS zone_id, edge_weight FROM od_edges
            UNION ALL
            SELECT zone_b AS zone_id, edge_weight FROM od_edges
        ),
        strength AS (
            SELECT
                zone_id,
                count(*)::INTEGER AS undirected_degree,
                sum(edge_weight)::BIGINT AS undirected_strength
            FROM strength_rows GROUP BY zone_id
        )
        SELECT
            n.zone_id,
            coalesce(o.outbound_trips, 0)::BIGINT AS outbound_trips,
            coalesce(i.inbound_trips, 0)::BIGINT AS inbound_trips,
            coalesce(o.self_loop_trips, 0)::BIGINT AS self_loop_trips,
            coalesce(o.cross_zone_out_degree, 0)::INTEGER AS cross_zone_out_degree,
            coalesce(i.cross_zone_in_degree, 0)::INTEGER AS cross_zone_in_degree,
            coalesce(s.undirected_degree, 0)::INTEGER AS undirected_degree,
            coalesce(s.undirected_strength, 0)::BIGINT AS undirected_strength,
            coalesce(s.undirected_strength, 0)::DOUBLE /
                nullif(2 * sum(coalesce(s.undirected_strength, 0)) OVER () / 2, 0)
                AS undirected_strength_share,
            o.outbound_destination_hhi,
            coalesce(o.self_loop_trips, 0)::DOUBLE / nullif(o.outbound_trips, 0)
                AS outbound_self_loop_share,
            '{EVIDENCE_LABEL}' AS evidence_label,
            'Node weights are clustering inputs from observed flows, not causal exposure.'
                AS interpretation_warning
        FROM nodes n
        LEFT JOIN outgoing o USING (zone_id)
        LEFT JOIN incoming i USING (zone_id)
        LEFT JOIN strength s USING (zone_id)
        ORDER BY outbound_trips DESC, n.zone_id
    """


def _autocorrelation_query(lags: Sequence[int]) -> str:
    pieces: list[str] = []
    for lag in lags:
        pieces.append(
            f"""(
            WITH zone_means AS (
                SELECT zone_id, avg(trip_count::DOUBLE) AS zone_mean
                FROM zone GROUP BY zone_id
            ),
            spans AS (
                SELECT
                    zone_id,
                    greatest(
                        date_diff('hour', min(time_bin), max(time_bin)) + 1 - {lag},
                        0
                    )::BIGINT AS possible_pairs
                FROM zone GROUP BY zone_id
            ),
            pairs AS (
                SELECT
                    current.trip_count::DOUBLE AS current_y,
                    previous.trip_count::DOUBLE AS previous_y,
                    means.zone_mean
                FROM zone current
                JOIN zone previous
                  ON current.zone_id = previous.zone_id
                 AND current.time_bin = previous.time_bin + INTERVAL '{lag} hours'
                JOIN zone_means means ON current.zone_id = means.zone_id
            )
            SELECT
                {lag}::INTEGER AS lag_hours,
                count(*)::BIGINT AS exact_lag_support_pairs,
                (SELECT sum(possible_pairs) FROM spans)::BIGINT
                    AS possible_pairs_on_hourly_span,
                count(*)::DOUBLE / nullif((SELECT sum(possible_pairs) FROM spans), 0)
                    AS support_share,
                corr(current_y, previous_y) AS pooled_trip_count_correlation,
                corr(current_y - zone_mean, previous_y - zone_mean)
                    AS within_zone_centered_correlation,
                avg(current_y) AS current_mean,
                avg(previous_y) AS lagged_mean,
                '{EVIDENCE_LABEL}' AS evidence_label,
                'Exact timestamp lag association; not a causal persistence parameter.'
                    AS interpretation_warning
            FROM pairs
            )"""
        )
    return " UNION ALL ".join(pieces) + " ORDER BY lag_hours"


def _hour_profile_query() -> str:
    return f"""
        SELECT
            hour(time_bin)::INTEGER AS hour_of_day,
            count(*)::BIGINT AS zone_hour_cells,
            count(DISTINCT zone_id)::INTEGER AS zones,
            count(DISTINCT time_bin::DATE)::INTEGER AS dates,
            sum(trip_count)::BIGINT AS completed_trips,
            avg(trip_count::DOUBLE) AS mean_trips_per_zone_hour,
            var_pop(trip_count::DOUBLE) AS cell_variance,
            stddev_pop(trip_count::DOUBLE) AS cell_stddev,
            approx_quantile(trip_count, 0.50) AS cell_p50,
            approx_quantile(trip_count, 0.90) AS cell_p90,
            '{EVIDENCE_LABEL}' AS evidence_label
        FROM zone
        GROUP BY hour_of_day
        ORDER BY hour_of_day
    """


def _zone_profile_query() -> str:
    return f"""
        SELECT
            zone_id,
            count(*)::BIGINT AS hourly_cells,
            count(*) FILTER (WHERE trip_count > 0)::BIGINT AS occupied_cells,
            sum(trip_count)::BIGINT AS completed_trips,
            sum(trip_count)::DOUBLE / sum(sum(trip_count)) OVER () AS month_trip_share,
            avg(trip_count::DOUBLE) AS mean_trips_per_hour,
            var_pop(trip_count::DOUBLE) AS temporal_variance,
            stddev_pop(trip_count::DOUBLE) AS temporal_stddev,
            approx_quantile(trip_count, 0.50) AS hourly_p50,
            approx_quantile(trip_count, 0.90) AS hourly_p90,
            max(trip_count)::BIGINT AS hourly_max,
            '{EVIDENCE_LABEL}' AS evidence_label
        FROM zone
        GROUP BY zone_id
        ORDER BY completed_trips DESC, zone_id
    """


def _raw_rows_declared(source_manifest: Mapping[str, Any]) -> int | None:
    metadata = source_manifest.get("metadata", {})
    if isinstance(metadata, Mapping):
        full = metadata.get("full_month_processing", {})
        if isinstance(full, Mapping) and full.get("raw_rows") is not None:
            return int(full["raw_rows"])
    config = source_manifest.get("config", {})
    if isinstance(config, Mapping) and config.get("nyc_expected_rows") is not None:
        return int(config["nyc_expected_rows"])
    return None


def _calibration_proposal(
    trip_moments: Mapping[str, Any],
    variance: Mapping[str, Any],
    template: SimulationConfig,
) -> dict[str, Any]:
    mean_completed = float(variance["mean_completed_trips_per_zone_hour"])
    assumed_ratio = template.base_supply / template.base_demand
    wait = trip_moments["request_to_pickup_wait_minutes"]
    fare = trip_moments["fare"]
    wait_anchor = wait.get("p50") if wait.get("available") else None
    patch = {
        "n_zones": int(variance["zones"]),
        "n_periods": int(variance["periods"]),
        "periods_per_day": 24,
        "base_demand": mean_completed,
        "base_supply": mean_completed * assumed_ratio,
        "base_fare": fare.get("mean"),
        "base_wait_minutes": wait_anchor,
    }
    return {
        "status": "transparent_initialization_proposal_not_fitted_structural_model",
        "suggested_simulation_config_patch": patch,
        "observed_control_target": {
            "quantity": "mean published completed trips per pickup-zone hour",
            "value": mean_completed,
            "evidence_label": EVIDENCE_LABEL,
        },
        "initialization_rules": [
            "Use the observed zone and hourly panel dimensions for simulation shape.",
            "Initialize fare scale from mean published base passenger fare.",
            "Use median nonnegative request-to-pickup elapsed time only as a wait proxy.",
            "Initialize latent demand at completed-trip scale, then jointly rescale demand and supply until the simulated control path matches the completed-trip target.",
            "Preserve the template supply-to-demand ratio during scale rescaling because available drivers are not published.",
            "Validate the simulated hourly and zone distributions against held-out descriptive cells before using it for design analysis.",
        ],
        "assumption_carried_from_template": {
            "baseline_supply_to_demand_ratio": assumed_ratio,
            "capacity_per_driver": template.capacity_per_driver,
            "matching_efficiency": template.matching_efficiency,
            "individuals_per_cell": template.individuals_per_cell,
            "treatment_version": template.treatment_version.value,
            "discount_rate": template.discount_rate,
            "incentive_per_driver": template.incentive_per_driver,
            "direct_demand_effect": template.direct_demand_effect,
            "direct_supply_effect": template.direct_supply_effect,
            "spillover_strength": template.spillover_strength,
            "persistence": template.persistence,
            "rider_substitution": template.rider_substitution,
            "driver_mobility": template.driver_mobility,
            "rider_value": template.rider_value,
            "operating_cost_per_trip": template.operating_cost_per_trip,
            "wait_disutility_per_minute": template.wait_disutility_per_minute,
        },
        "not_estimated_from_trip_records": [
            "latent_requests",
            "available_drivers",
            "baseline_supply_to_demand_ratio",
            "capacity_per_driver",
            "matching_efficiency",
            "direct_demand_effect",
            "direct_supply_effect",
            "spillover_strength",
            "persistence",
            "rider_substitution",
            "driver_mobility",
            "rider_value",
            "operating_cost_per_trip",
            "wait_disutility_per_minute",
            "platform_margin",
            "welfare_function_or_welfare_effect",
        ],
        "critical_warning": (
            "The proposed base_demand and base_supply values are initialization scales, "
            "not estimates of latent demand or driver supply. Autocorrelation is not "
            "mapped to persistence, and OD weights are not mapped to spillover effects."
        ),
    }


def _bundle_manifest(
    stage: Path,
    source_manifest_validation: Mapping[str, Any],
    config: DataConfig,
    settings: NYCCalibrationSettings,
) -> Path:
    paths = tuple(sorted(path for path in stage.iterdir() if path.is_file()))
    entries = [
        {
            "path": path.name,
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in paths
        if path.name != "manifest.json"
    ]
    return _atomic_json(
        {
            "schema_version": "1.0.0",
            "evidence_label": EVIDENCE_LABEL,
            "causal_claim": False,
            "portable_paths": True,
            "files": entries,
            "source_data_manifest": source_manifest_validation,
            "config": {
                "data": config.as_serializable_dict(),
                "calibration": settings.to_dict(),
            },
            "interpretation_warning": CAUSAL_WARNING,
        },
        stage / "manifest.json",
    )


def _publish_directory(stage: Path, destination: Path) -> None:
    backup = destination.with_name(f".{destination.name}.previous")
    if backup.exists():
        shutil.rmtree(backup)
    if destination.exists():
        destination.replace(backup)
    try:
        stage.replace(destination)
    except BaseException:
        if backup.exists() and not destination.exists():
            backup.replace(destination)
        raise
    if backup.exists():
        shutil.rmtree(backup)


def write_nyc_calibration_bundle(
    config: DataConfig | str | Path,
    output_directory: str | Path,
    *,
    settings: NYCCalibrationSettings | None = None,
    simulator_template: SimulationConfig | None = None,
) -> NYCCalibrationArtifacts:
    """Write a fail-closed descriptive NYC calibration and OD-network bundle.

    The function requires an already completed NYC full-mode data build.  It never
    converts the trip table to pandas or Polars; DuckDB performs every trip-level
    scan under the configured memory limit.
    """

    cfg = load_data_config(config) if not isinstance(config, DataConfig) else config
    if cfg.source != "nyc_hvfhv" or cfg.mode != "full":
        raise ValueError("NYC calibration requires source=nyc_hvfhv and mode=full")
    runtime = settings or NYCCalibrationSettings()
    template = simulator_template or SimulationConfig()
    output = Path(output_directory).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    marker = output.parent / f"{output.name}_INCOMPLETE.json"
    _atomic_json(
        {
            "status": "incomplete",
            "started_at_utc": datetime.now(UTC).isoformat(),
            "intended_output": output.name,
            "interpretation": (
                "Do not treat this calibration bundle as current while this marker exists."
            ),
        },
        marker,
    )

    pipeline_marker = cfg.manifest_path.with_name("NYC_FULL_INCOMPLETE.json")
    if pipeline_marker.exists():
        raise RuntimeError("NYC full data pipeline is marked incomplete")
    if not cfg.manifest_path.is_file():
        raise FileNotFoundError(cfg.manifest_path)
    clean_files = _parquet_files(cfg.clean_dir / "trips")
    zone_files = _parquet_files(cfg.panel_dir / "zone_time")
    od_files = _parquet_files(cfg.panel_dir / "od_flow")
    queried_files = (*clean_files, *zone_files, *od_files)
    source_manifest, manifest_validation = _verify_source_manifest(
        cfg.manifest_path,
        cfg.project_root,
        queried_files,
        verify_hashes=runtime.verify_source_hashes,
    )
    if not manifest_validation["all_valid"]:
        raise ValueError("source data manifest validation failed")

    temporary_root = Path(
        tempfile.mkdtemp(prefix=f".{output.name}-stage-", dir=output.parent)
    )
    stage = temporary_root / output.name
    stage.mkdir()
    duckdb_temp = temporary_root / "duckdb_temp"
    duckdb_temp.mkdir()
    try:
        connection = duckdb.connect()
        connection.execute(f"SET threads = {runtime.threads}")
        connection.execute(f"SET memory_limit = {_sql_string(runtime.memory_limit)}")
        connection.execute(
            f"SET temp_directory = {_sql_string(str(duckdb_temp.resolve()))}"
        )
        connection.execute(
            f"CREATE TEMP VIEW clean AS SELECT * FROM {_scan_sql(clean_files)}"
        )
        connection.execute(
            f"CREATE TEMP VIEW zone AS SELECT * FROM {_scan_sql(zone_files)}"
        )
        connection.execute(
            f"CREATE TEMP VIEW od AS SELECT * FROM {_scan_sql(od_files)}"
        )
        try:
            trip_moments = _trip_moments(connection)
            variance = _variance_decomposition(connection)
            conservation = _conservation(connection)
            graph_summary = _create_graph_tables(connection)
            hour_path = _copy_csv(
                connection, _hour_profile_query(), stage / "hour_of_day_profile.csv"
            )
            zone_path = _copy_csv(
                connection, _zone_profile_query(), stage / "zone_temporal_profile.csv"
            )
            edge_path = _copy_csv(
                connection, _edge_query(), stage / "od_weighted_edges.csv"
            )
            exposure_mapping_path = _copy_csv(
                connection,
                _exposure_mapping_query(),
                stage / "exposure_mapping_edges.csv",
            )
            node_path = _copy_csv(
                connection, _node_query(), stage / "zone_graph_nodes.csv"
            )
            autocorrelation_path = _copy_csv(
                connection,
                _autocorrelation_query(runtime.exact_lag_hours),
                stage / "temporal_autocorrelation.csv",
            )
        finally:
            connection.close()

        raw_rows = _raw_rows_declared(source_manifest)
        checks = {
            "source_manifest_valid": bool(manifest_validation["all_valid"]),
            "raw_rows_declared": raw_rows is not None,
            "raw_equals_clean": raw_rows == int(conservation["clean_rows"]),
            "zone_conserves_clean": int(conservation["zone_trip_sum"])
            == int(conservation["clean_rows"])
            - int(conservation["pickup_datetime_null_rows"]),
            "od_conserves_clean": int(conservation["od_trip_sum"])
            == int(conservation["clean_rows"])
            - int(conservation["pickup_datetime_null_rows"]),
            "graph_conserves_od": int(graph_summary["total_trips"])
            == int(conservation["od_trip_sum"]),
            "zone_keys_unique": int(conservation["zone_key_duplicates"]) == 0,
            "od_keys_unique": int(conservation["od_key_duplicates"]) == 0,
            "od_counts_positive": int(conservation["nonpositive_od_rows"]) == 0,
            "variance_trip_sum_conserves": int(variance["total_completed_trips"])
            == int(conservation["zone_trip_sum"]),
        }
        if not all(checks.values()):
            failed = ", ".join(name for name, passed in checks.items() if not passed)
            raise ValueError(f"NYC calibration conservation checks failed: {failed}")

        diagnostic_provenance: dict[str, Any] | None = None
        if cfg.diagnostics_path.is_file():
            diagnostic_provenance = {
                "path": _portable_path(cfg.diagnostics_path, cfg.project_root),
                "sha256": sha256_file(cfg.diagnostics_path),
            }
        calibration = {
            "schema_version": "1.0.0",
            "evidence_label": EVIDENCE_LABEL,
            "causal_claim": False,
            "bundle_valid": True,
            "scope": {
                "source": "nyc_hvfhv",
                "unit": "published_completed_trip_record_and_pickup_zone_hour",
                "population_claim": False,
                "pickup_min": conservation["pickup_min"],
                "pickup_max": conservation["pickup_max"],
            },
            "trip_level_descriptive_moments": trip_moments,
            "zone_hour_variance_decomposition": variance,
            "od_flow_graph": {
                **graph_summary,
                "representation": "undirected_monthly_completed_trip_flow_graph",
                "edge_file": edge_path.name,
                "exposure_mapping_file": exposure_mapping_path.name,
                "exposure_mapping_schema": [
                    "focal_zone_id",
                    "neighbor_zone_id",
                    "weight",
                ],
                "zone_id_semantics": (
                    "NYC TLC LocationID; align CSV loader dtype with assignment zone_id"
                ),
                "exposure_mapping_direction": (
                    "each undirected monthly edge is emitted in both focal directions"
                ),
                "node_file": node_path.name,
                "self_loops": "excluded from edges; retained as node attribute",
                "edge_weight": "sum of published completed trips in both directions",
                "cluster_input_proposal": {
                    "target_cluster_count": runtime.target_cluster_count,
                    "status": "experiment_design_assumption_not_estimate",
                    "suggested_objective": (
                        "minimize between-cluster completed-trip flow subject to balanced "
                        "pre-period volume and enough randomized clusters"
                    ),
                    "required_before_use": [
                        "pre-treatment-only graph construction",
                        "cluster-size and volume balance checks",
                        "between-cluster exposure diagnostics",
                        "randomization-inference power analysis",
                    ],
                },
                "interpretation": (
                    "Observed OD weights define a candidate exposure graph but do not "
                    "estimate interference, rider substitution, or driver movement."
                ),
                "evidence_label": EVIDENCE_LABEL,
            },
            "temporal_associations": {
                "file": autocorrelation_path.name,
                "lags_hours": list(runtime.exact_lag_hours),
                "support_definition": (
                    "same-zone pairs whose timestamps differ by exactly the declared lag"
                ),
                "interpretation": (
                    "Exact-lag autocorrelation summarizes observed completed trips; it is "
                    "not assigned to the simulator persistence parameter."
                ),
                "evidence_label": EVIDENCE_LABEL,
            },
            "simulator_scale_calibration_proposal": _calibration_proposal(
                trip_moments, variance, template
            ),
            "conservation": {"raw_rows_declared": raw_rows, **conservation},
            "checks": checks,
            "provenance": {
                "source_data_manifest": manifest_validation,
                "diagnostics": diagnostic_provenance,
                "queried_inputs": {
                    "clean_parts": len(clean_files),
                    "zone_parts": len(zone_files),
                    "od_parts": len(od_files),
                    "paths": [
                        _portable_path(path, cfg.project_root) for path in queried_files
                    ],
                },
                "config": {
                    "data": cfg.as_serializable_dict(),
                    "calibration": runtime.to_dict(),
                },
            },
            "limitations": [
                "Published completed trips exclude latent requests, unserved demand, and available drivers.",
                "Request-to-pickup elapsed time is a published timestamp difference, not a randomized wait outcome or a complete rider-experience measure.",
                "Base passenger fare and driver pay do not identify platform revenue, driver opportunity cost, price elasticity, or incentive response.",
                "The ICC-like between-zone share is descriptive and is not a fitted random-effects ICC or experiment design effect.",
                "OD edges are observed completed-trip connections, not causal spatial spillovers or equilibrium substitution parameters.",
                "Temporal autocorrelation is not a causal persistence estimate.",
                "Treatment response, spillover, persistence, substitution, compliance, and welfare remain explicit simulator assumptions.",
                "One month does not establish seasonality or transportability to other months, products, or cities.",
            ],
            "critical_warning": CAUSAL_WARNING,
        }
        calibration_path = _atomic_json(calibration, stage / "calibration.json")
        manifest_path = _bundle_manifest(
            stage, manifest_validation, cfg, runtime
        )
        _publish_directory(stage, output)
        marker.unlink(missing_ok=True)
    except BaseException:
        raise
    finally:
        if temporary_root.exists():
            shutil.rmtree(temporary_root)

    return NYCCalibrationArtifacts(
        output_directory=output,
        calibration_path=output / calibration_path.name,
        hour_profile_path=output / hour_path.name,
        zone_profile_path=output / zone_path.name,
        edge_path=output / edge_path.name,
        exposure_mapping_path=output / exposure_mapping_path.name,
        node_path=output / node_path.name,
        autocorrelation_path=output / autocorrelation_path.name,
        manifest_path=output / manifest_path.name,
    )


__all__ = [
    "NYCCalibrationArtifacts",
    "NYCCalibrationSettings",
    "write_nyc_calibration_bundle",
]
