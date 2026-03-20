"""
Derive multi-timeframe bars from validated 1D bars.

This module provides functions to aggregate daily bars into longer timeframes
(2D, 3D, 5D, 1W, 2W, 4W, 1M, 3M, etc.) using standard OHLCV aggregation rules.

Design principles:
- 1D table is the single source of truth (validated, quality-flagged)
- Daily bars copied directly (no aggregation needed)
- Weekly/monthly bars aggregate from daily using deterministic rules
- Aggregation logic matches existing multi-TF builder (same OHLCV math)

Benefits:
- 1D validation rules propagate to all multi-TF bars automatically
- Unified backfill handling: fix 1D, all downstream rebuilds
- Trade-off: 2x slower refresh (12 min vs 6 min) for data consistency guarantees
"""

from __future__ import annotations

import re
from datetime import date, timedelta

import pandas as pd
import polars as pl
from sqlalchemy.engine import Engine
from sqlalchemy import text
from typing import Literal

from ta_lab2.scripts.bars.polars_bar_operations import (
    apply_ohlcv_cumulative_aggregations,
    compute_extrema_timestamps_with_new_extreme_detection,
    compute_missing_days_gaps,
)


def load_1d_bars_for_id(
    engine: Engine,
    id: int,
    start_date: str | None = None,
    end_date: str | None = None,
) -> pl.DataFrame:
    """
    Load validated 1D bars for a given ID.

    Args:
        engine: SQLAlchemy engine
        id: Asset ID
        start_date: Optional start date filter (inclusive)
        end_date: Optional end date filter (inclusive)

    Returns:
        Polars DataFrame with columns:
        - id, timestamp, tf, bar_seq
        - open, high, low, close, volume
        - time_high, time_low
        - venue, venue_id, venue_rank
        - quality flags (is_partial_start, is_partial_end, is_missing_days)
    """
    # Build WHERE clause with filters
    where_clauses = ["id = :id", "tf = '1D'"]
    params = {"id": int(id)}

    if start_date is not None:
        where_clauses.append('"timestamp" >= :start_date')
        params["start_date"] = start_date

    if end_date is not None:
        where_clauses.append('"timestamp" <= :end_date')
        params["end_date"] = end_date

    where_sql = " AND ".join(where_clauses)

    sql = text(
        f"""
        SELECT
            id,
            "timestamp",
            tf,
            bar_seq,
            time_open,
            time_high,
            time_low,
            open,
            high,
            low,
            close,
            volume,
            market_cap,
            is_partial_start,
            is_partial_end,
            is_missing_days,
            count_days,
            count_missing_days,
            venue,
            venue_id,
            venue_rank
        FROM public.price_bars_1d
        WHERE {where_sql}
        ORDER BY venue, "timestamp"
    """
    )

    with engine.connect() as conn:
        df_pd = pd.read_sql(sql, conn, params=params)

    if df_pd.empty:
        return pl.DataFrame()

    # Convert to Polars
    df_pl = pl.from_pandas(df_pd)

    return df_pl


def get_week_start_day(alignment: str) -> int:
    """
    Get ISO weekday for week start.

    Args:
        alignment: 'calendar_us' (Sunday=0) or 'calendar_iso' (Monday=1)

    Returns:
        ISO weekday number (1=Monday through 7=Sunday)
    """
    if alignment == "calendar_us":
        return 7  # Sunday
    elif alignment == "calendar_iso":
        return 1  # Monday
    else:
        raise ValueError(f"Unknown calendar alignment: {alignment}")


def _compute_bar_end_day(period_start: date, unit: str, qty: int) -> date:
    """Return last day (inclusive) of a calendar period starting at period_start."""
    if unit == "W":
        return period_start + timedelta(days=7 * qty - 1)
    if unit == "M":
        year = period_start.year + (period_start.month - 1 + qty) // 12
        month = (period_start.month - 1 + qty) % 12 + 1
        return date(year, month, 1) - timedelta(days=1)
    if unit == "Y":
        return date(period_start.year + qty, 1, 1) - timedelta(days=1)
    raise ValueError(f"Unsupported unit: {unit}")


def assign_calendar_periods(
    df_daily: pl.DataFrame,
    target_tf: str,
    alignment: str,
    anchor_mode: bool = False,
) -> pl.DataFrame:
    """
    Assign calendar periods to daily bars based on alignment.

    Args:
        df_daily: Daily bars with timestamp column
        target_tf: Target timeframe (1W_CAL, 2W_CAL, 1M_CAL, etc.)
        alignment: 'calendar_us' or 'calendar_iso'
        anchor_mode: If True, include partial periods at boundaries

    Returns:
        DataFrame with added 'period_start' column for grouping

    Calendar rules:
    - Weeks: Start on week_start_day, fixed 7-day periods
    - Months: Start on 1st, variable days
    - Quarters: Start on Jan/Apr/Jul/Oct 1st
    - Years: Start on Jan 1st

    Anchor mode:
    - If anchor_mode=True, first/last periods may be partial
    - is_partial_start/is_partial_end flags set accordingly
    """
    if df_daily.is_empty():
        return df_daily

    # Parse target_tf to determine period type
    # Calendar TF patterns: 1W_CAL, 2W_CAL, 1M_CAL, 3M_CAL, 1Y_CAL, etc.
    match = re.match(r"(\d+)([WMY])_CAL", target_tf)
    if not match:
        raise ValueError(
            f"Unsupported calendar timeframe format: {target_tf}. Expected format: N[W|M|Y]_CAL"
        )

    qty = int(match.group(1))
    unit = match.group(2)

    # Convert timestamp to date for calendar calculations
    df_with_date = df_daily.with_columns(
        [pl.col("timestamp").dt.date().alias("day_date")]
    )

    # Determine period_start based on unit and alignment
    if unit == "W":
        # Week-based periods
        # Calculate ISO week start (Monday) for each date
        df_with_date = df_with_date.with_columns(
            [
                (
                    pl.col("day_date")
                    - pl.duration(days=pl.col("day_date").dt.weekday() - 1)
                ).alias("iso_week_start")
            ]
        )

        # Adjust to calendar_us (Sunday) if needed
        if alignment == "calendar_us":
            df_with_date = df_with_date.with_columns(
                [
                    pl.when(pl.col("day_date").dt.weekday() == 7)  # Sunday
                    .then(pl.col("day_date"))
                    .otherwise(pl.col("iso_week_start") - pl.duration(days=1))
                    .alias("period_start_base")
                ]
            )
        else:
            df_with_date = df_with_date.with_columns(
                [pl.col("iso_week_start").alias("period_start_base")]
            )

        # For multi-week periods (qty > 1), group by qty weeks
        if qty > 1:
            # Count weeks since epoch and group by qty
            epoch_date = pl.date(1970, 1, 1)
            df_with_date = df_with_date.with_columns(
                [
                    (
                        epoch_date
                        + pl.duration(
                            days=(
                                (
                                    pl.col("period_start_base") - epoch_date
                                ).dt.total_days()
                                // 7
                                // qty
                                * qty
                                * 7
                            )
                        )
                    ).alias("period_start")
                ]
            )
        else:
            df_with_date = df_with_date.with_columns(
                [pl.col("period_start_base").alias("period_start")]
            )

    elif unit == "M":
        # Month-based periods
        df_with_date = df_with_date.with_columns(
            [
                pl.date(
                    pl.col("day_date").dt.year(),
                    ((pl.col("day_date").dt.month() - 1) // qty * qty + 1).cast(
                        pl.UInt32
                    ),
                    1,
                ).alias("period_start")
            ]
        )

    elif unit == "Y":
        # Year-based periods
        df_with_date = df_with_date.with_columns(
            [
                pl.date(
                    (pl.col("day_date").dt.year() // qty * qty).cast(pl.Int32), 1, 1
                ).alias("period_start")
            ]
        )

    return df_with_date


def aggregate_by_calendar_period(
    df_daily: pl.DataFrame,
    target_tf: str,
    period_col: str = "period_start",
) -> pl.DataFrame:
    """
    Build daily snapshot rows for calendar-aligned bars.

    Produces ONE ROW PER DAY per bar with running cumulative OHLCV,
    matching the direct-path builders' output format.
    """
    if df_daily.is_empty():
        return pl.DataFrame()

    # Parse target_tf for unit and qty (e.g. "1M_CAL" → M, 1)
    match = re.match(r"(\d+)([WMY])_CAL", target_tf)
    if not match:
        raise ValueError(f"Unsupported calendar tf: {target_tf}")
    qty = int(match.group(1))
    unit = match.group(2)

    df = df_daily.sort(["id", period_col, "timestamp"])

    # bar_seq: dense rank on period_start (per id)
    df = df.with_columns(
        pl.col(period_col).rank("dense").over("id").cast(pl.Int64).alias("bar_seq")
    )

    # pos_in_bar: cumulative count within each bar_seq
    df = df.with_columns(
        pl.col("bar_seq")
        .cum_count()
        .over(["id", "bar_seq"])
        .cast(pl.Int64)
        .alias("pos_in_bar"),
    )

    # Compute bar_end_day for each unique period_start via Python calendar math
    unique_periods = df.select(period_col).unique().to_series().to_list()
    period_end_map = {ps: _compute_bar_end_day(ps, unit, qty) for ps in unique_periods}
    end_df = pl.DataFrame(
        {
            period_col: list(period_end_map.keys()),
            "bar_end_day": list(period_end_map.values()),
        }
    )
    df = df.join(end_df, on=period_col, how="left")

    # tf_days: nominal width of the calendar period
    df = df.with_columns(
        (
            (pl.col("bar_end_day") - pl.col(period_col)).dt.total_days().cast(pl.Int64)
            + 1
        ).alias("tf_days")
    )

    # Rename columns for shared Polars helpers
    # timestamp→ts (main timestamp), time_high→timehigh, time_low→timelow
    # Drop original time_open (will compute snapshot-style time_open)
    drop_cols = [c for c in ["time_open"] if c in df.columns]
    if drop_cols:
        df = df.drop(drop_cols)
    df = df.rename({"timestamp": "ts", "time_high": "timehigh", "time_low": "timelow"})

    # Cast timestamps to tz-naive Datetime(us) for Polars window ops
    for col in ["ts", "timehigh", "timelow"]:
        if col in df.columns:
            dtype = df[col].dtype
            if dtype != pl.Datetime("us"):
                df = df.with_columns(pl.col(col).cast(pl.Datetime("us")).alias(col))

    # Cumulative OHLCV within each bar_seq
    df = apply_ohlcv_cumulative_aggregations(df, group_col="bar_seq")

    # Extrema timestamps with new-extreme reset
    df = compute_extrema_timestamps_with_new_extreme_detection(
        df,
        group_col="bar_seq",
        ts_col="ts",
        timehigh_col="timehigh",
        timelow_col="timelow",
    )

    # Missing days from timestamp gaps
    df = compute_missing_days_gaps(df, group_col="bar_seq", ts_col="ts")

    # Time columns
    df = df.with_columns(
        [
            # time_open: prev_ts + 1ms; first row: ts - 1day + 1ms
            (pl.col("ts").shift(1) + pl.duration(milliseconds=1))
            .fill_null(pl.col("ts") - pl.duration(days=1) + pl.duration(milliseconds=1))
            .alias("time_open"),
            # time_close = current day's timestamp
            pl.col("ts").alias("time_close"),
            # time_open_bar = period_start as datetime
            pl.col(period_col).cast(pl.Datetime("us")).alias("time_open_bar"),
            # time_close_bar = bar_end_day + 23:59:59.999
            (
                pl.col("bar_end_day").cast(pl.Datetime("us"))
                + pl.duration(hours=23, minutes=59, seconds=59, milliseconds=999)
            ).alias("time_close_bar"),
            # last_ts_half_open = ts + 1ms
            (pl.col("ts") + pl.duration(milliseconds=1)).alias("last_ts_half_open"),
        ]
    )

    # Bookkeeping columns
    df = df.with_columns(
        [
            pl.col("pos_in_bar").alias("count_days"),
            (pl.col("tf_days") - pl.col("pos_in_bar"))
            .cast(pl.Int64)
            .alias("count_days_remaining"),
            (pl.col("pos_in_bar") < pl.col("tf_days")).alias("is_partial_end"),
            pl.lit(False).alias("is_partial_start"),
            (pl.col("count_missing_days") > 0).alias("is_missing_days"),
        ]
    )

    # Select final output columns matching snapshot schema
    out = df.select(
        [
            pl.col("id"),
            pl.lit(target_tf).alias("tf"),
            pl.col("tf_days"),
            pl.col("bar_seq"),
            pl.col("time_open"),
            pl.col("time_close"),
            pl.col("time_high"),
            pl.col("time_low"),
            pl.col("time_open_bar"),
            pl.col("time_close_bar"),
            pl.col("open_bar").cast(pl.Float64).alias("open"),
            pl.col("high_bar").cast(pl.Float64).alias("high"),
            pl.col("low_bar").cast(pl.Float64).alias("low"),
            pl.col("close_bar").cast(pl.Float64).alias("close"),
            pl.col("vol_bar").cast(pl.Float64).alias("volume"),
            pl.col("mc_bar").cast(pl.Float64).alias("market_cap"),
            pl.col("ts").alias("timestamp"),
            pl.col("last_ts_half_open"),
            pl.col("pos_in_bar").cast(pl.Int64),
            pl.col("is_partial_start").cast(pl.Boolean),
            pl.col("is_partial_end").cast(pl.Boolean),
            pl.col("count_days_remaining"),
            pl.col("is_missing_days").cast(pl.Boolean),
            pl.col("count_days").cast(pl.Int64),
            pl.col("count_missing_days").cast(pl.Int64),
            pl.lit(None).cast(pl.Date).alias("first_missing_day"),
            pl.lit(None).cast(pl.Date).alias("last_missing_day"),
            pl.lit("price_bars_1d").alias("src_file"),
        ]
    )

    return out


# Mapping of builder type to alignment configuration
BUILDER_ALIGNMENT_MAP = {
    "multi_tf": ("tf_day", False),
    "cal_us": ("calendar_us", False),
    "cal_iso": ("calendar_iso", False),
    "cal_anchor_us": ("calendar_us", True),
    "cal_anchor_iso": ("calendar_iso", True),
}


def aggregate_daily_to_timeframe(
    df_daily: pl.DataFrame,
    target_tf: str,
    alignment: Literal["tf_day", "calendar_us", "calendar_iso"] = "tf_day",
    anchor_mode: bool = False,
) -> pl.DataFrame:
    """
    Aggregate daily bars into target timeframe with specified alignment.

    alignment modes:
    - tf_day: Fixed day-count windows (1D, 2D, 3D, 5D, 1W=7D, etc.)
    - calendar_us: Calendar-aligned with Sunday week start
    - calendar_iso: Calendar-aligned with Monday week start

    anchor_mode (only for calendar alignments):
    - False: Require complete periods (filter incomplete)
    - True: Allow partial periods at boundaries (with flags)

    Args:
        df_daily: Daily bars from load_1d_bars_for_id()
        target_tf: Target timeframe (2D, 3D, 5D, 1W, 2W, 4W, 1M, 3M, etc.)
        alignment: Calendar alignment mode
        anchor_mode: Allow partial periods at boundaries

    Returns:
        Polars DataFrame with aggregated bars:
        - id, timestamp (period start), tf, bar_seq
        - open (first day's open)
        - high (max of all days' highs)
        - low (min of all days' lows)
        - close (last day's close)
        - volume (sum of all days' volumes)
        - time_high, time_low (deterministic: earliest among ties)
        - Quality flags propagated from source days

    Aggregation rules (match existing multi-TF builder):
    - OHLCV: Standard candlestick aggregation
    - time_high/time_low: Use compute_time_high_low with tie-breaking
    - Quality flags: OR logic (if any source day has flag, bar has flag)
    """
    if df_daily.is_empty():
        return pl.DataFrame()

    # Route to calendar or tf_day aggregation
    if alignment in ["calendar_us", "calendar_iso"]:
        df_with_periods = assign_calendar_periods(
            df_daily, target_tf, alignment, anchor_mode
        )
        return aggregate_by_calendar_period(df_with_periods, target_tf=target_tf)

    # tf_day mode: Fixed day-count windows (daily snapshot pattern)
    if target_tf == "1D":
        return df_daily.with_columns(pl.lit(target_tf).alias("tf"))

    match = re.match(r"(\d+)D", target_tf)
    if not match:
        raise ValueError(
            f"Unsupported timeframe format: {target_tf}. Expected format: ND (e.g., 2D, 7D)"
        )

    tf_days = int(match.group(1))

    # Sort and assign bar_seq + pos_in_bar
    df = df_daily.sort("timestamp")
    df = df.with_row_count(name="_row_idx")
    df = df.with_columns(
        [
            (pl.col("_row_idx") // tf_days + 1).cast(pl.Int64).alias("bar_seq"),
            (pl.col("_row_idx") % tf_days + 1).cast(pl.Int64).alias("pos_in_bar"),
        ]
    ).drop("_row_idx")

    # Rename columns for shared helpers
    drop_cols = [c for c in ["time_open"] if c in df.columns]
    if drop_cols:
        df = df.drop(drop_cols)
    df = df.rename({"timestamp": "ts", "time_high": "timehigh", "time_low": "timelow"})

    # Cast timestamps to tz-naive Datetime(us)
    for col in ["ts", "timehigh", "timelow"]:
        if col in df.columns:
            dtype = df[col].dtype
            if dtype != pl.Datetime("us"):
                df = df.with_columns(pl.col(col).cast(pl.Datetime("us")).alias(col))

    # Cumulative OHLCV
    df = apply_ohlcv_cumulative_aggregations(df, group_col="bar_seq")

    # Extrema timestamps
    df = compute_extrema_timestamps_with_new_extreme_detection(
        df,
        group_col="bar_seq",
        ts_col="ts",
        timehigh_col="timehigh",
        timelow_col="timelow",
    )

    # Missing days
    df = compute_missing_days_gaps(df, group_col="bar_seq", ts_col="ts")

    # Time columns
    one_ms = pl.duration(milliseconds=1)
    df = df.with_columns(
        [
            (pl.col("ts").shift(1) + one_ms)
            .fill_null(pl.col("ts") - pl.duration(days=1) + one_ms)
            .alias("time_open"),
            pl.col("ts").alias("time_close"),
            (pl.col("ts").shift(1) + one_ms)
            .fill_null(pl.col("ts") - pl.duration(days=1) + one_ms)
            .first()
            .over("bar_seq")
            .alias("time_open_bar"),
            (
                (pl.col("ts").shift(1) + one_ms)
                .fill_null(pl.col("ts") - pl.duration(days=1) + one_ms)
                .first()
                .over("bar_seq")
                + pl.duration(days=tf_days)
            ).alias("time_close_bar"),
            (pl.col("ts") + one_ms).alias("last_ts_half_open"),
        ]
    )

    # Bookkeeping
    df = df.with_columns(
        [
            pl.col("pos_in_bar").alias("count_days"),
            pl.lit(tf_days).cast(pl.Int64).alias("tf_days"),
            (tf_days - pl.col("pos_in_bar"))
            .cast(pl.Int64)
            .alias("count_days_remaining"),
            (pl.col("pos_in_bar") < tf_days).alias("is_partial_end"),
            pl.lit(False).alias("is_partial_start"),
            (pl.col("count_missing_days") > 0).alias("is_missing_days"),
        ]
    )

    # Select final columns
    out = df.select(
        [
            pl.col("id"),
            pl.lit(target_tf).alias("tf"),
            pl.col("tf_days"),
            pl.col("bar_seq"),
            pl.col("time_open"),
            pl.col("time_close"),
            pl.col("time_high"),
            pl.col("time_low"),
            pl.col("time_open_bar"),
            pl.col("time_close_bar"),
            pl.col("open_bar").cast(pl.Float64).alias("open"),
            pl.col("high_bar").cast(pl.Float64).alias("high"),
            pl.col("low_bar").cast(pl.Float64).alias("low"),
            pl.col("close_bar").cast(pl.Float64).alias("close"),
            pl.col("vol_bar").cast(pl.Float64).alias("volume"),
            pl.col("mc_bar").cast(pl.Float64).alias("market_cap"),
            pl.col("ts").alias("timestamp"),
            pl.col("last_ts_half_open"),
            pl.col("pos_in_bar").cast(pl.Int64),
            pl.col("is_partial_start").cast(pl.Boolean),
            pl.col("is_partial_end").cast(pl.Boolean),
            pl.col("count_days_remaining"),
            pl.col("is_missing_days").cast(pl.Boolean),
            pl.col("count_days").cast(pl.Int64),
            pl.col("count_missing_days").cast(pl.Int64),
            pl.lit(None).cast(pl.Date).alias("first_missing_day"),
            pl.lit(None).cast(pl.Date).alias("last_missing_day"),
            pl.lit("price_bars_1d").alias("src_file"),
        ]
    )

    return out


def _min_days_for_tf(tf: str) -> int:
    """Minimum 1D bars needed before building a bar for this TF.

    Mirrors _nominal_tf_days() in the calendar builders — uses conservative
    lower bounds so we never create e.g. a 1Y_CAL bar from 2 days of data.

    Returns 1 for unrecognised formats (safe pass-through for 1D etc.).
    """
    # Calendar: "1W_CAL_US", "3M_CAL_ANCHOR_ISO", "1Y_CAL", etc.
    m = re.match(r"(\d+)([WMY])_", tf)
    if m:
        qty, unit = int(m.group(1)), m.group(2)
        if unit == "W":
            return qty * 7
        if unit == "M":
            return qty * 28
        if unit == "Y":
            return qty * 365

    # Rolling day-count: "2D", "7D", "14D", etc.
    m = re.match(r"(\d+)D", tf)
    if m:
        return int(m.group(1))

    return 1


def derive_multi_tf_bars(
    engine: Engine,
    id: int,
    timeframes: list[str],
    alignment: Literal["tf_day", "calendar_us", "calendar_iso"] = "tf_day",
    anchor_mode: bool = False,
    start_date: str | None = None,
) -> pl.DataFrame:
    """
    Derive all multi-TF bars for an ID from 1D source.

    Args:
        engine: SQLAlchemy engine
        id: Asset ID
        timeframes: List of target timeframes (e.g., ["1D", "2D", "1W", "1M"])
        alignment: Calendar alignment mode
        anchor_mode: Allow partial periods at boundaries (calendar modes only)
        start_date: Only process bars from this date (for incremental)

    Returns:
        Polars DataFrame with all derived bars, ready for upsert.
    """
    # Load 1D bars (includes venue, venue_id, venue_rank)
    df_1d = load_1d_bars_for_id(
        engine=engine,
        id=id,
        start_date=start_date,
    )

    if df_1d.is_empty():
        return pl.DataFrame()

    # Get unique venues; process each separately to avoid cross-venue aggregation
    venues = df_1d["venue"].unique().to_list()

    all_bars = []

    for venue in venues:
        df_venue = df_1d.filter(pl.col("venue") == venue)
        venue_id = df_venue["venue_id"].first()
        venue_rank = df_venue["venue_rank"].first()
        n_daily = len(df_venue)

        # Filter out TFs that require more daily bars than available
        applicable_tfs = [tf for tf in timeframes if _min_days_for_tf(tf) <= n_daily]
        if len(applicable_tfs) < len(timeframes):
            import logging

            logger = logging.getLogger(__name__)
            skipped = len(timeframes) - len(applicable_tfs)
            logger.info(
                f"ID={id}, venue={venue}: Skipping {skipped} TF(s) "
                f"(need more than {n_daily} daily bar(s))"
            )

        # Drop venue columns before aggregation (not needed in groupby)
        df_venue_clean = df_venue.drop(["venue", "venue_id", "venue_rank"])

        for tf in applicable_tfs:
            df_tf = aggregate_daily_to_timeframe(
                df_daily=df_venue_clean,
                target_tf=tf,
                alignment=alignment,
                anchor_mode=anchor_mode,
            )

            if not df_tf.is_empty():
                # Tag output with venue columns
                df_tf = df_tf.with_columns(
                    pl.lit(venue).alias("venue"),
                    pl.lit(venue_id).alias("venue_id"),
                    pl.lit(venue_rank).alias("venue_rank"),
                )
                all_bars.append(df_tf)

    # Concatenate all venues and timeframes
    if not all_bars:
        return pl.DataFrame()

    df_result = pl.concat(all_bars, how="vertical")

    return df_result


def validate_derivation_consistency(
    df_derived: pl.DataFrame,
    df_direct: pl.DataFrame,
    tolerance: float = 1e-10,
) -> tuple[bool, list[str]]:
    """
    Validate that derived bars match directly-computed bars.

    Used during migration to verify derivation logic is correct.

    Returns:
        (is_consistent, list_of_discrepancies)
    """
    if df_derived.is_empty() and df_direct.is_empty():
        return True, []

    if df_derived.is_empty() or df_direct.is_empty():
        return False, [
            f"One DataFrame is empty: derived={len(df_derived)}, direct={len(df_direct)}"
        ]

    # Convert to pandas for easier comparison
    derived_pd = df_derived.to_pandas()
    direct_pd = df_direct.to_pandas()

    # Check row counts
    if len(derived_pd) != len(direct_pd):
        return False, [
            f"Row count mismatch: derived={len(derived_pd)}, direct={len(direct_pd)}"
        ]

    # Sort both by (id, tf, bar_seq, time_close) for consistent comparison
    sort_cols = ["id", "tf", "bar_seq", "time_close"]
    derived_pd = derived_pd.sort_values(sort_cols).reset_index(drop=True)
    direct_pd = direct_pd.sort_values(sort_cols).reset_index(drop=True)

    discrepancies = []

    # Compare OHLCV columns
    ohlcv_cols = ["open", "high", "low", "close", "volume"]
    for col in ohlcv_cols:
        if col not in derived_pd.columns or col not in direct_pd.columns:
            continue

        # Compare with tolerance for floating point values
        diff = (derived_pd[col] - direct_pd[col]).abs()
        mismatches = diff > tolerance

        if mismatches.any():
            mismatch_count = mismatches.sum()
            max_diff = diff.max()
            discrepancies.append(
                f"{col}: {mismatch_count} mismatches (max diff: {max_diff:.10f})"
            )

    # Compare timestamps (should be exact)
    ts_cols = ["time_open", "time_close", "time_high", "time_low", "timestamp"]
    for col in ts_cols:
        if col not in derived_pd.columns or col not in direct_pd.columns:
            continue

        mismatches = derived_pd[col] != direct_pd[col]
        if mismatches.any():
            mismatch_count = mismatches.sum()
            discrepancies.append(f"{col}: {mismatch_count} timestamp mismatches")

    is_consistent = len(discrepancies) == 0

    return is_consistent, discrepancies
