"""Vintage selection with strict, auditable information boundaries."""

from __future__ import annotations

from datetime import UTC, datetime

import polars as pl

from macro_nowcast.schema import validate_canonical_frame

AS_OF_MODE = "as_of"
LATEST_SAME_MASK_MODE = "latest_values_same_eligibility_mask"
NAIVE_LATEST_MODE = "naive_latest_revised"


def _coerce_as_of(value: datetime | str) -> datetime:
    if isinstance(value, str):
        normalized = f"{value[:-1]}+00:00" if value.endswith("Z") else value
        try:
            value = datetime.fromisoformat(normalized)
        except ValueError as exc:
            raise ValueError("as_of must be an ISO datetime with a timezone") from exc
    if not isinstance(value, datetime):
        raise TypeError("as_of must be a timezone-aware datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("as_of must include an explicit timezone")
    return value.astimezone(UTC)


def _effective_availability() -> pl.Expr:
    """Use exact timing when present and conservative UTC end-of-day otherwise."""

    end_of_day = pl.col("availability_date").cast(pl.Datetime("us", "UTC")) + pl.duration(
        hours=23,
        minutes=59,
        seconds=59,
        microseconds=999_999,
    )
    return pl.coalesce(pl.col("availability_timestamp"), end_of_day).alias(
        "effective_availability_timestamp"
    )


def _validated_observations(observations: pl.DataFrame) -> pl.DataFrame:
    frame = validate_canonical_frame(observations)
    timestamp_date_mismatch = frame.filter(
        pl.col("availability_timestamp").is_not_null()
        & (pl.col("availability_timestamp").dt.date() != pl.col("availability_date"))
    )
    if timestamp_date_mismatch.height:
        raise ValueError("availability_timestamp must fall on availability_date in UTC")
    duplicate_vintages = (
        frame.group_by(["series_id", "observation_date", "realtime_start"])
        .len()
        .filter(pl.col("len") > 1)
    )
    if duplicate_vintages.height:
        raise ValueError(
            "series_id, observation_date, and realtime_start must identify one vintage"
        )
    return frame.with_columns(_effective_availability())


def _latest_per_observation(frame: pl.DataFrame) -> pl.DataFrame:
    """Rank every row, including null values, before selecting the latest vintage."""

    return (
        frame.sort(
            [
                "series_id",
                "observation_date",
                "effective_availability_timestamp",
                "realtime_start",
                "download_timestamp",
            ]
        )
        .unique(subset=["series_id", "observation_date"], keep="last", maintain_order=True)
        .sort(["series_id", "observation_date"])
    )


def select_as_of(
    observations: pl.DataFrame,
    as_of: datetime | str,
) -> pl.DataFrame:
    """Select the latest vintage actually available at ``as_of``.

    Missing latest rows are intentionally retained.  Filtering nulls before the
    vintage rank would resurrect stale values and is therefore forbidden.
    """

    cutoff = _coerce_as_of(as_of)
    frame = _validated_observations(observations)
    eligible = frame.filter(pl.col("effective_availability_timestamp") <= pl.lit(cutoff))
    snapshot = _latest_per_observation(eligible).with_columns(
        pl.lit(AS_OF_MODE).alias("information_set_mode"),
        pl.lit(False).alias("is_counterfactual"),
        pl.lit(cutoff).cast(pl.Datetime("us", "UTC")).alias("as_of_timestamp"),
        pl.col("effective_availability_timestamp").alias("eligibility_timestamp"),
        pl.col("effective_availability_timestamp").alias(
            "selected_vintage_availability_timestamp"
        ),
    )
    assert_no_future_information(snapshot, cutoff)
    return snapshot


def select_latest_values_same_eligibility_mask(
    observations: pl.DataFrame,
    as_of: datetime | str,
) -> pl.DataFrame:
    """Substitute latest values only for observation cells eligible at ``as_of``.

    This intentionally counterfactual view isolates value-revision leakage from
    release-timing leakage.  ``eligibility_timestamp`` records when the cell first
    entered the information set; ``selected_vintage_availability_timestamp`` records
    when the substituted value actually became available.
    """

    cutoff = _coerce_as_of(as_of)
    frame = _validated_observations(observations)
    eligible_cells = (
        frame.filter(pl.col("effective_availability_timestamp") <= pl.lit(cutoff))
        .group_by(["series_id", "observation_date"])
        .agg(
            pl.col("effective_availability_timestamp")
            .min()
            .alias("eligibility_timestamp")
        )
    )
    latest = _latest_per_observation(frame).rename(
        {"effective_availability_timestamp": "selected_vintage_availability_timestamp"}
    )
    counterfactual = (
        latest.join(
            eligible_cells,
            on=["series_id", "observation_date"],
            how="inner",
            validate="1:1",
        )
        .with_columns(
            pl.col("selected_vintage_availability_timestamp").alias(
                "effective_availability_timestamp"
            ),
            pl.lit(LATEST_SAME_MASK_MODE).alias("information_set_mode"),
            pl.lit(True).alias("is_counterfactual"),
            pl.lit(cutoff).cast(pl.Datetime("us", "UTC")).alias("as_of_timestamp"),
        )
        .sort(["series_id", "observation_date"])
    )
    if counterfactual.filter(pl.col("eligibility_timestamp") > pl.col("as_of_timestamp")).height:
        raise AssertionError("counterfactual eligibility mask contains future information")
    return counterfactual


def select_naive_latest_revised(
    observations: pl.DataFrame,
    as_of: datetime | str,
) -> pl.DataFrame:
    """Return the latest row for every cell, ignoring historical eligibility.

    This is an intentionally leaky research benchmark.  Callers should first
    restrict ``observations`` to a declared fixed evaluation vintage.  The
    historical ``as_of`` timestamp is retained so downstream audits can count
    cells whose first availability occurred after the forecast origin.
    """

    cutoff = _coerce_as_of(as_of)
    frame = _validated_observations(observations)
    first_availability = frame.group_by(["series_id", "observation_date"]).agg(
        pl.col("effective_availability_timestamp")
        .min()
        .alias("eligibility_timestamp")
    )
    latest = _latest_per_observation(frame).rename(
        {"effective_availability_timestamp": "selected_vintage_availability_timestamp"}
    )
    return (
        latest.join(
            first_availability,
            on=["series_id", "observation_date"],
            how="inner",
            validate="1:1",
        )
        .with_columns(
            pl.col("selected_vintage_availability_timestamp").alias(
                "effective_availability_timestamp"
            ),
            pl.lit(NAIVE_LATEST_MODE).alias("information_set_mode"),
            pl.lit(True).alias("is_counterfactual"),
            pl.lit(cutoff).cast(pl.Datetime("us", "UTC")).alias("as_of_timestamp"),
        )
        .sort(["series_id", "observation_date"])
    )


def assert_no_future_information(
    frame: pl.DataFrame,
    as_of: datetime | str | None = None,
) -> None:
    """Raise if a valid as-of frame contains information from after its cutoff."""

    if frame.is_empty():
        return
    if "is_counterfactual" in frame.columns and frame["is_counterfactual"].any():
        raise ValueError("strict no-future validation does not accept counterfactual rows")

    if "effective_availability_timestamp" in frame.columns:
        availability = pl.col("effective_availability_timestamp")
    elif "availability_timestamp" in frame.columns and "availability_date" in frame.columns:
        availability = _effective_availability()
        frame = frame.with_columns(availability)
        availability = pl.col("effective_availability_timestamp")
    else:
        raise ValueError("frame lacks auditable availability columns")

    if as_of is None:
        if "as_of_timestamp" not in frame.columns:
            raise ValueError("as_of is required when frame has no as_of_timestamp")
        violations = frame.filter(availability > pl.col("as_of_timestamp"))
    else:
        cutoff = _coerce_as_of(as_of)
        violations = frame.filter(availability > pl.lit(cutoff))
    if violations.height:
        raise AssertionError(
            f"future information detected in {violations.height} row(s)"
        )


# Descriptive compatibility alias for callers that prefer noun-first naming.
as_of_snapshot = select_as_of


__all__ = [
    "AS_OF_MODE",
    "LATEST_SAME_MASK_MODE",
    "NAIVE_LATEST_MODE",
    "as_of_snapshot",
    "assert_no_future_information",
    "select_as_of",
    "select_latest_values_same_eligibility_mask",
    "select_naive_latest_revised",
]
