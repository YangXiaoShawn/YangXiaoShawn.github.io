"""Revision measurement on canonical vintage rows."""

from __future__ import annotations

import polars as pl


def revision_details(observations: pl.DataFrame) -> pl.DataFrame:
    """Return first/latest values and revisions for every series-observation cell."""

    required = {
        "series_id",
        "observation_date",
        "availability_timestamp",
        "realtime_start",
        "value",
    }
    missing = required.difference(observations.columns)
    if missing:
        raise ValueError(f"observation frame lacks columns: {', '.join(sorted(missing))}")
    ordered = observations.sort(
        ["series_id", "observation_date", "availability_timestamp", "realtime_start"]
    )
    return (
        ordered.group_by(["series_id", "observation_date"], maintain_order=True)
        .agg(
            pl.col("value").first().alias("first_value"),
            pl.col("value").last().alias("latest_value"),
            pl.col("availability_timestamp").first().alias("first_availability_ts"),
            pl.col("availability_timestamp").last().alias("latest_availability_ts"),
            pl.len().alias("vintage_count"),
        )
        .with_columns(
            (pl.col("latest_value") - pl.col("first_value")).alias("revision"),
        )
        .with_columns(pl.col("revision").abs().alias("absolute_revision"))
        .sort(["series_id", "observation_date"])
    )


def revision_summary(observations: pl.DataFrame) -> pl.DataFrame:
    details = revision_details(observations).filter(
        pl.col("first_value").is_not_null() & pl.col("latest_value").is_not_null()
    )
    if details.is_empty():
        return pl.DataFrame(
            schema={
                "series_id": pl.String,
                "observation_count": pl.UInt32,
                "revision_count": pl.UInt32,
                "mean_revision": pl.Float64,
                "mean_abs_revision": pl.Float64,
                "max_abs_revision": pl.Float64,
            }
        )
    return (
        details.group_by("series_id")
        .agg(
            pl.len().alias("observation_count"),
            (pl.col("absolute_revision") > 0).sum().alias("revision_count"),
            pl.col("revision").mean().alias("mean_revision"),
            pl.col("absolute_revision").mean().alias("mean_abs_revision"),
            pl.col("absolute_revision").max().alias("max_abs_revision"),
        )
        .sort("series_id")
    )


def most_revised_series(summary: pl.DataFrame, limit: int = 5) -> pl.DataFrame:
    if limit < 1:
        raise ValueError("limit must be positive")
    return summary.sort("mean_abs_revision", descending=True).head(limit)
