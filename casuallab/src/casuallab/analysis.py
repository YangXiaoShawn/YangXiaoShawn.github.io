"""Descriptive marketplace analysis with explicit non-causal evidence labels."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


def _to_pandas(frame: Any) -> pd.DataFrame:
    if isinstance(frame, pd.DataFrame):
        return frame.copy()
    if hasattr(frame, "to_pandas"):
        return frame.to_pandas()
    raise TypeError("expected a pandas or Polars DataFrame")


def _first_column(frame: pd.DataFrame, candidates: tuple[str, ...], *, required: bool = True) -> str | None:
    for candidate in candidates:
        if candidate in frame.columns:
            return candidate
    if required:
        raise ValueError(f"none of the required columns are present: {list(candidates)}")
    return None


def _weighted_mean(values: pd.Series, weights: pd.Series) -> float:
    numeric_values = pd.to_numeric(values, errors="coerce")
    numeric_weights = pd.to_numeric(weights, errors="coerce")
    valid = numeric_values.notna() & numeric_weights.notna() & (numeric_weights > 0)
    if not valid.any():
        return float("nan")
    return float(np.average(numeric_values.loc[valid], weights=numeric_weights.loc[valid]))


def compute_descriptive_moments(panel: Any) -> dict[str, object]:
    """Compute transparent empirical moments from a compact zone-time panel.

    Returned correlations are labeled associations. No transformation in this
    function provides exogenous price variation or a causal identification strategy.
    """

    frame = _to_pandas(panel)
    if frame.empty:
        raise ValueError("panel must not be empty")
    zone = _first_column(frame, ("zone_id", "pickup_zone", "pickup_community_area", "zone"))
    period = _first_column(
        frame,
        ("period_start", "time_bin", "time_period", "hour", "trip_start_hour"),
    )
    demand = _first_column(frame, ("trip_count", "completed_trips", "demand", "outcome"))
    fare = _first_column(frame, ("average_fare", "avg_fare", "mean_fare", "fare"), required=False)
    pooled = _first_column(
        frame,
        (
            "pooled_trip_share",
            "pooled_share",
            "shared_trip_share",
            "shared_matched_share",
            "shared_requested_share",
        ),
        required=False,
    )

    demand_values = pd.to_numeric(frame[demand], errors="coerce")
    if demand_values.notna().sum() == 0:
        raise ValueError("demand column contains no numeric observations")

    moments: dict[str, object] = {
        "evidence_type": "empirical_association",
        "panel_rows": int(len(frame)),
        "zones": int(frame[zone].nunique(dropna=True)),
        "periods": int(frame[period].nunique(dropna=True)),
        "total_observed_trips": float(demand_values.sum()),
        "mean_trips_per_cell": float(demand_values.mean()),
        "p90_trips_per_cell": float(demand_values.quantile(0.90)),
        "price_endogeneity_warning": (
            "Observed fare and demand are jointly determined by marketplace state. "
            "Their correlation is descriptive and is not a causal elasticity."
        ),
    }
    if fare is not None:
        fare_values = pd.to_numeric(frame[fare], errors="coerce")
        moments["mean_observed_fare"] = _weighted_mean(fare_values, demand_values)
        moments["equal_observed_cell_mean_fare"] = float(fare_values.mean())
        moments["fare_demand_correlation_association"] = float(fare_values.corr(demand_values))
    if pooled is not None:
        moments["mean_pooled_trip_share"] = _weighted_mean(
            frame[pooled], demand_values
        )

    ordered = frame.assign(_demand=demand_values).sort_values([zone, period])
    previous_observed = ordered.groupby(zone, dropna=False)["_demand"].shift(1)
    moments["zone_previous_observed_cell_demand_correlation_association"] = float(
        ordered["_demand"].corr(previous_observed)
    )

    period_values = pd.to_datetime(ordered[period], errors="coerce")
    if period_values.notna().all():
        lag_minutes: int | None = None
        if "panel_grain" in ordered and ordered["panel_grain"].notna().any():
            match = re.search(r"_(\d+)([mh])$", str(ordered["panel_grain"].dropna().iloc[0]))
            if match:
                magnitude = int(match.group(1))
                lag_minutes = magnitude if match.group(2) == "m" else 60 * magnitude
        if lag_minutes is not None:
            exact = ordered[[zone, period, "_demand"]].copy()
            exact[period] = period_values
            prior = exact.rename(columns={"_demand": "_prior_demand"})
            prior[period] = prior[period] + pd.Timedelta(minutes=lag_minutes)
            pairs = exact.merge(prior, on=[zone, period], how="inner")
            correlation = float(pairs["_demand"].corr(pairs["_prior_demand"]))
            moments["zone_exact_lag_demand_correlation_association"] = (
                correlation if np.isfinite(correlation) else None
            )
            moments["zone_exact_lag_support_pairs"] = int(len(pairs))
            moments["zone_exact_lag_minutes"] = lag_minutes

    income_column = _first_column(
        frame,
        (
            "neighborhood_income_index",
            "neighborhood__income_index",
            "neighborhood__neighborhood_income_index",
        ),
        required=False,
    )
    if income_column is not None:
        income = pd.to_numeric(frame[income_column], errors="coerce")
        median_income = float(income.median())
        high = demand_values.loc[income >= median_income].mean()
        low = demand_values.loc[income < median_income].mean()
        moments["high_minus_low_income_mean_demand_association"] = float(high - low)
        moments["neighborhood_income_known_rows"] = int(income.notna().sum())
    weather_column = _first_column(
        frame,
        ("adverse_weather", "weather__adverse_weather", "weather__precipitation"),
        required=False,
    )
    if weather_column is not None:
        weather_values = pd.to_numeric(frame[weather_column], errors="coerce")
        known_weather = weather_values.notna()
        weather = weather_values > 0
        contrast = demand_values.loc[known_weather & weather].mean() - demand_values.loc[
            known_weather & ~weather
        ].mean()
        moments["adverse_weather_minus_other_mean_demand_association"] = (
            float(contrast) if np.isfinite(contrast) else None
        )
        moments["weather_known_rows"] = int(known_weather.sum())
    event_column = _first_column(
        frame,
        ("event_intensity", "events__event_intensity"),
        required=False,
    )
    if event_column is not None:
        event_values = pd.to_numeric(frame[event_column], errors="coerce")
        known_event = event_values.notna()
        events = event_values > 0
        contrast = demand_values.loc[known_event & events].mean() - demand_values.loc[
            known_event & ~events
        ].mean()
        moments["event_minus_nonevent_mean_demand_association"] = (
            float(contrast) if np.isfinite(contrast) else None
        )
        moments["event_known_rows"] = int(known_event.sum())
    return moments


def descriptive_tables(panel: Any) -> dict[str, pd.DataFrame]:
    """Return demand-by-time, demand-by-zone, and cross-zone co-movement tables."""

    frame = _to_pandas(panel)
    if frame.empty:
        raise ValueError("panel must not be empty")
    zone = _first_column(frame, ("zone_id", "pickup_zone", "pickup_community_area", "zone"))
    period = _first_column(
        frame,
        ("period_start", "time_bin", "time_period", "hour", "trip_start_hour"),
    )
    demand = _first_column(frame, ("trip_count", "completed_trips", "demand", "outcome"))
    frame[demand] = pd.to_numeric(frame[demand], errors="coerce")

    period_values = pd.to_datetime(frame[period], errors="coerce")
    if period_values.notna().any():
        frame["hour_of_day"] = period_values.dt.hour
    else:
        frame["hour_of_day"] = pd.to_numeric(frame[period], errors="coerce")

    by_hour = (
        frame.groupby("hour_of_day", dropna=False)[demand]
        .agg(mean_trip_count="mean", total_trip_count="sum", cells="size")
        .reset_index()
    )
    by_zone = (
        frame.groupby(zone, dropna=False)[demand]
        .agg(mean_trip_count="mean", total_trip_count="sum", periods_observed="size")
        .reset_index()
        .rename(columns={zone: "zone_id"})
    )
    wide = frame.pivot_table(index=period, columns=zone, values=demand, aggfunc="sum")
    correlation = wide.corr(min_periods=2)
    correlation.index.name = "origin_zone"
    correlation.columns.name = "comparison_zone"
    cross_zone = correlation.stack().rename("demand_correlation").reset_index()
    for table in (by_hour, by_zone, cross_zone):
        table["evidence_type"] = "empirical_association"
    return {"demand_by_hour": by_hour, "demand_by_zone": by_zone, "cross_zone": cross_zone}


def origin_destination_summary(trips: Any) -> pd.DataFrame:
    """Summarize observed flows without interpreting them as substitution effects."""

    frame = _to_pandas(trips)
    origin = _first_column(
        frame,
        (
            "pickup_zone",
            "pickup_zone_id",
            "pickup_community_area",
            "pickup_location_id",
            "origin_zone",
        ),
    )
    destination = _first_column(
        frame,
        (
            "dropoff_zone",
            "dropoff_zone_id",
            "dropoff_community_area",
            "dropoff_location_id",
            "destination_zone",
        ),
    )
    flows = (
        frame.groupby([origin, destination], dropna=False)
        .size()
        .rename("trip_count")
        .reset_index()
        .rename(columns={origin: "origin_zone", destination: "destination_zone"})
    )
    origin_totals = flows.groupby("origin_zone", dropna=False)["trip_count"].transform("sum")
    flows["origin_flow_share"] = flows["trip_count"] / origin_totals
    flows["evidence_type"] = "empirical_association"
    flows["interpretation_warning"] = (
        "Observed flows reveal connected markets but do not identify causal spatial substitution."
    )
    return flows.sort_values(["origin_zone", "trip_count"], ascending=[True, False]).reset_index(
        drop=True
    )


def write_descriptive_artifacts(
    panel: Any,
    output_directory: str | Path,
    *,
    trips: Any | None = None,
) -> dict[str, Path]:
    """Write deterministic JSON/CSV descriptive artifacts."""

    directory = Path(output_directory)
    directory.mkdir(parents=True, exist_ok=True)
    moments = compute_descriptive_moments(panel)

    # JSON has no portable NaN representation; unresolved compact-sample moments are
    # retained as null rather than converted to a made-up number.
    clean_moments = {
        key: (None if isinstance(value, float) and not np.isfinite(value) else value)
        for key, value in moments.items()
    }
    moments_path = directory / "descriptive_moments.json"
    moments_path.write_text(json.dumps(clean_moments, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    paths = {"moments": moments_path}
    for name, table in descriptive_tables(panel).items():
        path = directory / f"{name}.csv"
        table.to_csv(path, index=False)
        paths[name] = path
    if trips is not None:
        flow_path = directory / "origin_destination_flows.csv"
        origin_destination_summary(trips).to_csv(flow_path, index=False)
        paths["origin_destination_flows"] = flow_path
    return paths
