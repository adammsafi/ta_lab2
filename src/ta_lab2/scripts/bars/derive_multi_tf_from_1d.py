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

import pandas as pd
import polars as pl
from sqlalchemy.engine import Engine
from sqlalchemy import text
from typing import Literal


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
        - quality flags (is_partial_start, is_partial_end, is_missing_days)
    """
    # Build WHERE clause with filters
    where_clauses = ["id = :id", "tf = '1D'"]
    params = {"id": int(id)}

    if start_date is not None:
        where_clauses.append("time_close >= :start_date")
        params["start_date"] = start_date

    if end_date is not None:
        where_clauses.append("time_close <= :end_date")
        params["end_date"] = end_date

    where_sql = " AND ".join(where_clauses)

    sql = text(
        f"""
        SELECT
            id,
            time_close AS timestamp,
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
            count_missing_days
        FROM public.cmc_price_bars_1d
        WHERE {where_sql}
        ORDER BY time_close
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
    import re

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
                        (pl.col("period_start_base") - epoch_date).dt.total_days()
                        // 7
                        // qty
                        * qty
                        * 7
                        + epoch_date
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
    period_col: str = "period_start",
) -> pl.DataFrame:
    """
    Aggregate daily bars by calendar period.

    Same OHLCV aggregation as tf_day mode, but grouped by period_col
    instead of fixed day counts.
    """
    if df_daily.is_empty():
        return pl.DataFrame()

    # Group by id and period_start, aggregate OHLCV
    df_agg = (
        df_daily.groupby(["id", period_col])
        .agg(
            [
                # Identity
                pl.col("tf").first(),
                # Timestamps
                pl.col("time_open").first(),
                pl.col("timestamp").last().alias("time_close"),
                # OHLCV aggregation
                pl.col("open").first(),
                pl.col("high").max(),
                pl.col("low").min(),
                pl.col("close").last(),
                pl.col("volume").sum(),
                pl.col("market_cap").last(),
                # Time extrema (earliest among ties)
                pl.col("time_high")
                .filter(pl.col("high") == pl.col("high").max())
                .min()
                .alias("time_high"),
                pl.col("time_low")
                .filter(pl.col("low") == pl.col("low").min())
                .min()
                .alias("time_low"),
                # Quality flags (OR logic)
                pl.col("is_partial_start").max(),
                pl.col("is_partial_end").max(),
                pl.col("is_missing_days").max(),
                # Counts
                pl.col("count_days").sum(),
                pl.col("count_missing_days").sum(),
                # Calculate tf_days from period
                pl.len().alias("actual_days"),
            ]
        )
        .sort([period_col])
    )

    # Add bar_seq
    df_agg = df_agg.with_columns(
        [pl.int_range(1, pl.len() + 1).over("id").cast(pl.Int64).alias("bar_seq")]
    )

    # Rename period_start to timestamp for consistency
    df_agg = df_agg.rename({period_col: "timestamp"})

    return df_agg


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
        return aggregate_by_calendar_period(df_with_periods)

    # tf_day mode: Fixed day-count windows
    # Parse target_tf to get tf_days count
    # Supports: 2D, 3D, 5D, 7D, etc.
    # For now, just handle simple "ND" format
    if target_tf == "1D":
        # Just return as-is with updated tf column
        return df_daily.with_columns(pl.lit(target_tf).alias("tf"))

    # Parse tf_days from target_tf (e.g., "2D" -> 2, "7D" -> 7)
    import re

    match = re.match(r"(\d+)D", target_tf)
    if not match:
        raise ValueError(
            f"Unsupported timeframe format: {target_tf}. Expected format: ND (e.g., 2D, 7D)"
        )

    tf_days = int(match.group(1))

    # Sort by timestamp
    df_sorted = df_daily.sort("timestamp")

    # Assign bar_seq based on row position (0-indexed division by tf_days)
    df_sorted = df_sorted.with_row_count(name="_row_idx")
    df_sorted = df_sorted.with_columns(
        [(pl.col("_row_idx") // tf_days + 1).cast(pl.Int64).alias("bar_seq_new")]
    )

    # Aggregate by bar_seq_new
    df_agg = (
        df_sorted.groupby("bar_seq_new")
        .agg(
            [
                # Identity
                pl.col("id").first().alias("id"),
                # Timestamps
                pl.col("time_open").first().alias("time_open"),
                pl.col("timestamp").last().alias("time_close"),
                # OHLCV aggregation
                pl.col("open").first().alias("open"),
                pl.col("high").max().alias("high"),
                pl.col("low").min().alias("low"),
                pl.col("close").last().alias("close"),
                pl.col("volume").sum().alias("volume"),
                pl.col("market_cap").last().alias("market_cap"),
                # Time extrema (earliest among ties)
                # For high: get timestamp where high == max(high), then take min timestamp
                pl.col("time_high")
                .filter(pl.col("high") == pl.col("high").max())
                .min()
                .alias("time_high"),
                pl.col("time_low")
                .filter(pl.col("low") == pl.col("low").min())
                .min()
                .alias("time_low"),
                # Quality flags (OR logic)
                pl.col("is_partial_start").max().alias("is_partial_start"),
                pl.col("is_partial_end").max().alias("is_partial_end"),
                pl.col("is_missing_days").max().alias("is_missing_days"),
                # Counts
                pl.col("count_days").sum().alias("count_days"),
                pl.col("count_missing_days").sum().alias("count_missing_days"),
            ]
        )
        .sort("bar_seq_new")
    )

    # Rename bar_seq_new to bar_seq and add tf metadata
    df_agg = df_agg.rename({"bar_seq_new": "bar_seq"})
    df_agg = df_agg.with_columns(
        [
            pl.lit(target_tf).alias("tf"),
            pl.lit(tf_days).cast(pl.Int64).alias("tf_days"),
            pl.col("time_close").alias(
                "timestamp"
            ),  # timestamp = time_close for consistency
        ]
    )

    # Reorder columns to match expected schema
    expected_cols = [
        "id",
        "tf",
        "tf_days",
        "bar_seq",
        "time_open",
        "time_close",
        "time_high",
        "time_low",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "market_cap",
        "timestamp",
        "is_partial_start",
        "is_partial_end",
        "is_missing_days",
        "count_days",
        "count_missing_days",
    ]

    df_result = df_agg.select([c for c in expected_cols if c in df_agg.columns])

    return df_result


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
    # Load 1D bars
    df_1d = load_1d_bars_for_id(
        engine=engine,
        id=id,
        start_date=start_date,
    )

    if df_1d.is_empty():
        return pl.DataFrame()

    # Derive each timeframe and collect results
    all_bars = []

    for tf in timeframes:
        df_tf = aggregate_daily_to_timeframe(
            df_daily=df_1d,
            target_tf=tf,
            alignment=alignment,
            anchor_mode=anchor_mode,
        )

        if not df_tf.is_empty():
            all_bars.append(df_tf)

    # Concatenate all timeframes
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
