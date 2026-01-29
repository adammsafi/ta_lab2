from __future__ import annotations
"""
# ======================================================================================
# refresh_cmc_price_bars_multi_tf_cal_anchor_us.py (UPDATED)
#
# US calendar-ANCHORED price bars builder (append-only DAILY SNAPSHOTS):
#   public.cmc_price_bars_multi_tf_cal_anchor_us
# from daily source:
#   public.cmc_price_histories7
#
# UPDATED FEATURES (matching cal_us improvements):
# - Polars-backed full rebuild (fast path)
# - Multiprocessing per-ID (each worker processes all specs for one id)
# - CLI flag: --num-processes (default 6, capped)
# - Pool(..., maxtasksperchild=50) under __main__
# - Batch-load last snapshot info for (id, all tfs)
# - Invariant post-fix for known timelow pathologies + OHLC clamps
#
# US SEMANTICS:
# - US week start is Sunday (Sun..Sat).
# - Anchored windows are calendar-defined (NOT data-aligned)
# - Partial bars allowed at BOTH ends for *_CAL_ANCHOR_* families
# - tf_days is the underlying window width (calendar days), regardless of partial start
# - Missing-days detection computed within [bar_start_effective .. snapshot_day]
# ======================================================================================
"""

import argparse
import os
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Sequence

import numpy as np
import pandas as pd
import polars as pl
from sqlalchemy import text
from ta_lab2.scripts.bars.common_snapshot_contract import (
    assert_one_row_per_local_day,
    compute_time_high_low,
    compute_missing_days_diagnostics,
    normalize_output_schema,
    resolve_db_url,
    get_engine,
    resolve_num_processes,
    load_all_ids,
    parse_ids,
    load_daily_min_max,
    ensure_state_table,
    load_state,
    upsert_state,
    upsert_bars,
    load_daily_prices_for_id,
    delete_bars_for_id_tf,
    load_last_snapshot_row,
    load_last_snapshot_info_for_id_tfs,
    create_bar_builder_argument_parser,
)
from ta_lab2.orchestration import (
    MultiprocessingOrchestrator,
    OrchestratorConfig,
    ProgressTracker,
)



# =============================================================================
# CONFIG
# =============================================================================

DEFAULT_TZ = "America/New_York"
DEFAULT_DAILY_TABLE = "public.cmc_price_histories7"
DEFAULT_BARS_TABLE = "public.cmc_price_bars_multi_tf_cal_anchor_us"
DEFAULT_STATE_TABLE = "public.cmc_price_bars_multi_tf_cal_anchor_us_state"

# Global reference for anchored N-week grouping (Sunday)
REF_SUNDAY = date(1970, 1, 4)

REQUIRED_DAILY_COLS = ["open", "high", "low", "close", "volume", "market_cap", "timehigh", "timelow"]


# =============================================================================
# Multiprocessing helpers
# =============================================================================






# =============================================================================
# Timeframe Spec
# =============================================================================

@dataclass
class TFSpec:
    tf: str
    n: int
    unit: str

def _coerce_to_date(x) -> date:
    """
    Coerce Polars/Pandas scalar outputs to a Python `date`.
    Handles: python date, pandas Timestamp, numpy datetime64.
    """
    if x is None or (isinstance(x, float) and np.isnan(x)):  # defensive
        raise ValueError("Cannot coerce None/NaN to date")

    if isinstance(x, date) and not isinstance(x, datetime):
        return x

    # pandas.Timestamp or numpy.datetime64 or string-like
    return pd.to_datetime(x).date()

def load_cal_anchor_specs_from_dim_timeframe(db_url: str) -> list[TFSpec]:
    """Load anchored week/month/year specs from dim_timeframe."""
    sql = text("""
      SELECT tf, tf_qty AS n, base_unit AS unit
      FROM public.dim_timeframe
      WHERE alignment_type = 'calendar'
        AND roll_policy = 'calendar_anchor'
        AND allow_partial_start = TRUE
        AND allow_partial_end = TRUE
        AND base_unit IN ('W','M','Y')
        AND (
          (base_unit = 'W' AND calendar_scheme = 'US' AND tf LIKE '%_CAL_ANCHOR_US')
          OR (base_unit IN ('M','Y') AND tf LIKE '%_CAL_ANCHOR%')
        )
      ORDER BY
        CASE base_unit
          WHEN 'W' THEN 1
          WHEN 'M' THEN 2
          WHEN 'Y' THEN 3
        END,
        tf_qty;
    """)

    eng = get_engine(db_url)
    with eng.connect() as conn:
        rows = conn.execute(sql).fetchall()

    specs = []
    for r in rows:
        tf = str(r[0])
        n = int(r[1])
        unit = str(r[2])
        specs.append(TFSpec(tf=tf, n=n, unit=unit))

    return specs


# =============================================================================
# Anchored window logic (US)
# =============================================================================

def _get_us_weekday(d: date) -> int:
    """US weekday: Sunday=0 .. Saturday=6."""
    return (d.isoweekday() % 7)


def _week_num_since_ref(d: date) -> int:
    """Number of full US weeks since REF_SUNDAY."""
    delta = (d - REF_SUNDAY).days
    return delta // 7


def _anchor_window_for_day_us_week(d: date, n: int) -> tuple[date, date]:
    """Return (window_start, window_end) for US N-week anchored window containing d."""
    ref_week = _week_num_since_ref(d)
    group = ref_week // n
    first_week_in_group = group * n
    window_start = REF_SUNDAY + timedelta(weeks=first_week_in_group)
    window_end = window_start + timedelta(weeks=n) - timedelta(days=1)
    return (window_start, window_end)


def _anchor_window_for_day_month(d: date, n: int) -> tuple[date, date]:
    """Return (window_start, window_end) for N-month anchored window containing d."""
    year = d.year
    month = d.month
    group = (month - 1) // n
    first_month = group * n + 1
    window_start = date(year, first_month, 1)
    
    last_month = first_month + n - 1
    if last_month > 12:
        year += 1
        last_month -= 12
    
    next_month = last_month + 1
    next_year = year
    if next_month > 12:
        next_year += 1
        next_month = 1
    
    window_end = date(next_year, next_month, 1) - timedelta(days=1)
    return (window_start, window_end)


def _anchor_window_for_day_year(d: date, n: int) -> tuple[date, date]:
    """Return (window_start, window_end) for N-year anchored window containing d."""
    year = d.year
    group = year // n
    first_year = group * n
    window_start = date(first_year, 1, 1)
    window_end = date(first_year + n, 1, 1) - timedelta(days=1)
    return (window_start, window_end)


def _anchor_window_for_day(d: date, n: int, unit: str) -> tuple[date, date]:
    """Dispatch to appropriate window function."""
    if unit == "W":
        return _anchor_window_for_day_us_week(d, n)
    elif unit == "M":
        return _anchor_window_for_day_month(d, n)
    elif unit == "Y":
        return _anchor_window_for_day_year(d, n)
    else:
        raise ValueError(f"Unknown unit: {unit}")


def _anchor_start_for_first_day(first_day: date, n: int, unit: str) -> date:
    """Return the anchor window start that contains or precedes first_day."""
    window_start, _ = _anchor_window_for_day(first_day, n, unit)
    return window_start


def _lookback_days_for_spec(spec: TFSpec) -> int:
    """Conservative lookback for incremental slice."""
    if spec.unit == "W":
        return spec.n * 7 + 30
    elif spec.unit == "M":
        return spec.n * 31 + 30
    elif spec.unit == "Y":
        return spec.n * 366 + 30
    return 400


# =============================================================================
# DB helpers (now imported from common_snapshot_contract)
# =============================================================================

# =============================================================================
# Missing-days detection
# =============================================================================

def _compute_missing_days_breakdown(
    expected_dates: set[date],
    available_dates: set[date],
    bar_start_effective: date,
    snapshot_day: date,
) -> tuple[int, int, int, int, str | None]:
    """
    Compute missing days breakdown: start, interior, end.
    Returns: (count_missing_days, count_missing_days_start, count_missing_days_interior, 
              count_missing_days_end, missing_days_where)
    """
    missing = sorted(expected_dates - available_dates)
    if not missing:
        return (0, 0, 0, 0, None)

    # Count leading missing days
    count_start = 0
    curr = bar_start_effective
    while curr in missing:
        count_start += 1
        curr += timedelta(days=1)
        if curr > snapshot_day:
            break

    # Count trailing missing days
    count_end = 0
    curr = snapshot_day
    while curr in missing:
        count_end += 1
        curr -= timedelta(days=1)
        if curr < bar_start_effective:
            break

    count_interior = len(missing) - count_start - count_end

    where_parts = []
    if count_start > 0:
        where_parts.append("start")
    if count_interior > 0:
        where_parts.append("interior")
    if count_end > 0:
        where_parts.append("end")

    missing_days_where = ",".join(where_parts) if where_parts else None

    return (len(missing), count_start, count_interior, count_end, missing_days_where)


# =============================================================================
# Polars-based FULL rebuild
# =============================================================================

def _build_snapshots_full_history_for_id_spec_polars(
    df_pandas: pd.DataFrame,
    *,
    spec: TFSpec,
    tz: str,
    fail_on_internal_gaps: bool = False,
) -> pd.DataFrame:
    """
    FAST PATH: Fully vectorized Polars-based full history builder for anchored bars.

    Uses cumulative operations (cum_max, cum_min, cum_sum) for O(N) performance
    instead of O(S×D) row-by-row iteration.
    """
    if df_pandas.empty:
        return pd.DataFrame()

    # Sort and prepare data
    df = df_pandas.sort_values("ts").reset_index(drop=True).copy()
    id_val = int(df["id"].iloc[0])

    # Get local dates for window assignment
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df["local_date"] = df["ts"].dt.tz_convert(tz).dt.date

    first_day = df["local_date"].iloc[0]
    last_day = df["local_date"].iloc[-1]
    anchor_start = _anchor_start_for_first_day(first_day, spec.n, spec.unit)

    # Vectorized window assignment based on unit type
    dates_dt = pd.to_datetime(df["local_date"])

    if spec.unit == "W":
        # US weeks: Sunday start, n-week windows
        ref = pd.Timestamp(REF_SUNDAY)
        days_since_ref = (dates_dt - ref).dt.days
        week_nums = days_since_ref // 7
        groups = week_nums // spec.n
        window_start_days = groups * spec.n * 7
        df["window_start"] = (ref + pd.to_timedelta(window_start_days, unit="D")).dt.date
        df["window_end"] = (ref + pd.to_timedelta(window_start_days + spec.n * 7 - 1, unit="D")).dt.date
        df["tf_days"] = spec.n * 7
    elif spec.unit == "M":
        # Month: start of N-month group
        years = dates_dt.dt.year.values
        months = dates_dt.dt.month.values
        groups = (months - 1) // spec.n
        first_months = groups * spec.n + 1
        # Build window_start dates
        ws_dates = [date(int(y), int(m), 1) for y, m in zip(years, first_months)]
        df["window_start"] = ws_dates
        # Compute window_end (last day of last month in group)
        we_dates = []
        tf_days_list = []
        for y, fm in zip(years, first_months):
            lm = fm + spec.n - 1
            ny, nm = y, lm
            if lm > 12:
                ny = y + 1
                nm = lm - 12
            # Next month's first day - 1
            next_m = nm + 1
            next_y = ny
            if next_m > 12:
                next_m = 1
                next_y = ny + 1
            we = date(next_y, next_m, 1) - timedelta(days=1)
            ws = date(int(y), int(fm), 1)
            we_dates.append(we)
            tf_days_list.append((we - ws).days + 1)
        df["window_end"] = we_dates
        df["tf_days"] = tf_days_list
    elif spec.unit == "Y":
        # Year: start of N-year group
        years = dates_dt.dt.year.values
        groups = years // spec.n
        first_years = groups * spec.n
        df["window_start"] = [date(int(fy), 1, 1) for fy in first_years]
        df["window_end"] = [date(int(fy) + spec.n, 1, 1) - timedelta(days=1) for fy in first_years]
        df["tf_days"] = [(date(int(fy) + spec.n, 1, 1) - date(int(fy), 1, 1)).days for fy in first_years]
    else:
        raise ValueError(f"Unknown unit: {spec.unit}")

    # Compute bar_anchor_offset (days from anchor_start to window_start)
    df["bar_anchor_offset"] = [(ws - anchor_start).days for ws in df["window_start"]]

    # Compute bar_start_eff (max of window_start and first_day)
    df["bar_start_eff"] = [max(ws, first_day) for ws in df["window_start"]]
    df["is_partial_start"] = df["bar_start_eff"] > df["window_start"]
    df["is_partial_end"] = df["local_date"] < df["window_end"]

    # Strip timezone for Polars processing
    df["ts"] = df["ts"].dt.tz_localize(None)
    df["timehigh"] = pd.to_datetime(df["timehigh"], utc=True, errors="coerce").dt.tz_localize(None)
    df["timelow"] = pd.to_datetime(df["timelow"], utc=True, errors="coerce").dt.tz_localize(None)
    
    # Add tf to the frame so Polars assertions / grouping can reference it
    df["tf"] = spec.tf

    # Convert to Polars for fast cumulative operations
    pl_df = pl.from_pandas(df).sort("ts")

    # Verify scope: must be single (id, tf) for correct bar_seq derivation
    assert pl_df.select(pl.col("id").n_unique()).item() == 1
    assert pl_df.select(pl.col("tf").n_unique()).item() == 1

    # Create sequential bar_seq from bar_anchor_offset (0, 1, 2, 3...)
    # bar_anchor_offset is canonical anchor identity; dense rank produces stable ordering
    pl_df = pl_df.with_columns([
        (pl.col("bar_anchor_offset")
            .rank(method="dense")
        )
        .cast(pl.Int64)
        .alias("bar_seq")
    ])

    one_day = pl.duration(days=1)
    from ta_lab2.scripts.bars.polars_bar_operations import (
        compute_day_time_open,
        apply_ohlcv_cumulative_aggregations,
        compute_extrema_timestamps_with_new_extreme_detection,
        compute_missing_days_gaps,
    )

    one_ms = pl.duration(milliseconds=1)

    # Use extracted utilities for common Polars operations
    pl_df = compute_day_time_open(pl_df)

    # Position and count within bar_seq
    pl_df = pl_df.with_columns([
        pl.int_range(1, pl.len() + 1).over("bar_seq").cast(pl.Int64).alias("pos_in_bar"),
        pl.int_range(1, pl.len() + 1).over("bar_seq").cast(pl.Int64).alias("count_days"),
    ])

    pl_df = pl_df.with_columns([
        pl.col("day_time_open").first().over("bar_seq").alias("time_open"),
        pl.col("ts").alias("time_close"),
        (pl.col("ts") + one_ms).alias("last_ts_half_open"),
    ])

    # Use extracted utilities
    pl_df = apply_ohlcv_cumulative_aggregations(pl_df)
    pl_df = compute_extrema_timestamps_with_new_extreme_detection(pl_df)
    pl_df = compute_missing_days_gaps(pl_df)

    # Count missing at start (days from bar_start_eff to first actual day in bar)
    pl_df = pl_df.with_columns([
        pl.col("local_date").first().over("bar_seq").alias("_first_local_date_in_bar"),
    ])

    # Convert bar_start_eff to Polars date for comparison
    pl_df = pl_df.with_columns([
        pl.col("bar_start_eff").cast(pl.Date).alias("bar_start_eff_dt"),
        pl.col("_first_local_date_in_bar").cast(pl.Date).alias("_first_local_dt"),
    ])

    pl_df = pl_df.with_columns([
        ((pl.col("_first_local_dt") - pl.col("bar_start_eff_dt")).dt.total_days().clip(lower_bound=0)).cast(pl.Int64).alias("count_missing_days_start"),
    ]).drop(["_first_local_date_in_bar", "bar_start_eff_dt", "_first_local_dt"])

    # Remaining missing days metrics
    pl_df = pl_df.with_columns([
        (pl.col("count_missing_days") > 0).alias("is_missing_days"),
        pl.lit(0).cast(pl.Int64).alias("count_missing_days_end"),  # snapshot_day always exists
        pl.max_horizontal(
            pl.col("count_missing_days") - pl.col("count_missing_days_start"),
            pl.lit(0, dtype=pl.Int64),
        ).cast(pl.Int64).alias("count_missing_days_interior"),
    ])

    # Expected days to date and remaining
    pl_df = pl_df.with_columns([
        pl.col("local_date").cast(pl.Date).alias("_local_dt"),
        pl.col("bar_start_eff").cast(pl.Date).alias("_bse_dt"),
    ])
    pl_df = pl_df.with_columns([
        ((pl.col("_local_dt") - pl.col("_bse_dt")).dt.total_days() + 1).cast(pl.Int64).alias("exp_to_date"),
    ]).drop(["_local_dt", "_bse_dt"])

    pl_df = pl_df.with_columns([
        (pl.col("tf_days").cast(pl.Int64) - pl.col("exp_to_date")).cast(pl.Int64).alias("count_days_remaining"),
        pl.when(pl.col("count_missing_days") > 0).then(pl.lit("interior")).otherwise(pl.lit(None)).alias("missing_days_where"),
        pl.lit(None).cast(pl.Date).alias("first_missing_day"),
        pl.lit(None).cast(pl.Date).alias("last_missing_day"),
    ])

    # Select final columns
    out_pl = pl_df.select([
        pl.lit(id_val).cast(pl.Int64).alias("id"),
        pl.lit(spec.tf).alias("tf"),
        pl.col("tf_days").cast(pl.Int64),
        pl.col("bar_seq").cast(pl.Int64),
        pl.col("bar_anchor_offset").cast(pl.Int64),

        pl.col("time_open"),
        pl.col("time_close"),
        pl.col("time_high"),
        pl.col("time_low"),

        pl.col("open_bar").cast(pl.Float64).alias("open"),
        pl.col("high_bar").cast(pl.Float64).alias("high"),
        pl.col("low_bar").cast(pl.Float64).alias("low"),
        pl.col("close_bar").cast(pl.Float64).alias("close"),

        pl.col("vol_bar").cast(pl.Float64).alias("volume"),
        pl.col("mc_bar").cast(pl.Float64).alias("market_cap"),

        pl.col("is_partial_start").cast(pl.Boolean),
        pl.col("is_partial_end").cast(pl.Boolean),
        pl.col("is_missing_days").cast(pl.Boolean),
        pl.col("count_days").cast(pl.Int64),
        pl.col("first_missing_day"),
        pl.col("last_missing_day"),
        pl.col("count_days_remaining").cast(pl.Int64),
        pl.col("count_missing_days").cast(pl.Int64),
        pl.col("count_missing_days_start").cast(pl.Int64),
        pl.col("count_missing_days_end").cast(pl.Int64),
        pl.col("count_missing_days_interior").cast(pl.Int64),
        pl.col("missing_days_where"),
    ])

    # Convert back to pandas and add UTC timezone to timestamps
    out = out_pl.to_pandas()

    if out.empty:
        return pd.DataFrame()

    from ta_lab2.scripts.bars.polars_bar_operations import restore_utc_timezone, compact_output_types

    # Use extracted utilities
    out = restore_utc_timezone(out)
    out = compact_output_types(out)

    return out

# =============================================================================
# Incremental snapshots builder (pandas)
# =============================================================================

def _build_incremental_snapshots_for_id_spec(
    df: pd.DataFrame,
    *,
    spec: TFSpec,
    tz: str,
    daily_min_day: date,
    first_window_start: date,
    start_day: date,
    end_day: date,
    last_snapshot_row: dict | None,
    fail_on_internal_gaps: bool = False,
) -> pd.DataFrame:
    """Build incremental snapshots using pandas."""
    if df.empty:
        return pd.DataFrame()

    df = df.copy()
    df["ts"] = pd.to_datetime(df["ts"], utc=True).dt.tz_convert(tz)
    df["local_date"] = df["ts"].dt.date
    df = df.sort_values("ts").reset_index(drop=True)

    anchor_start = first_window_start

    results = []
    curr_day = start_day
    
    while curr_day <= end_day:
        window_start, window_end = _anchor_window_for_day(curr_day, spec.n, spec.unit)
        bar_start_eff = max(window_start, daily_min_day)
        is_partial_start = (bar_start_eff > window_start)
        
        snapshot_day = curr_day
        if snapshot_day < bar_start_eff:
            curr_day += timedelta(days=1)
            continue
        
        is_partial_end = (snapshot_day < window_end)
        
        # Filter data
        mask = (df["local_date"] >= bar_start_eff) & (df["local_date"] <= snapshot_day)
        df_window = df[mask].copy()
        
        if df_window.empty:
            curr_day += timedelta(days=1)
            continue

        bar_anchor_offset = int((window_start - anchor_start).days)
        tf_days = (window_end - window_start).days + 1

        # NOTE: bar_seq is temporarily set to bar_anchor_offset for incremental safety.
        # A full rebuild will recompute sequential bar_seq via dense rank.
        bar_seq = bar_anchor_offset

        # Check for carry-forward: support legacy rows without bar_anchor_offset
        last_off = None
        if last_snapshot_row:
            last_off = last_snapshot_row.get(
                "bar_anchor_offset",
                last_snapshot_row.get("bar_seq")
            )

        can_carry = False
        if last_snapshot_row and last_off is not None and bar_anchor_offset == last_off:
            last_time_close = pd.to_datetime(last_snapshot_row["time_close"], utc=True).tz_convert(tz)
            last_snap_day = last_time_close.date()
            yesterday = snapshot_day - timedelta(days=1)
            
            if last_snap_day == yesterday and not last_snapshot_row.get("is_missing_days", False):
                can_carry = True
        
        if can_carry:
            # Carry forward from last snapshot
            open_val = last_snapshot_row["open"]
            high_val = max(last_snapshot_row["high"], df_window["high"].max())
            low_val = min(last_snapshot_row["low"], df_window["low"].min())
            time_open = last_snapshot_row["time_open"]
            
            # Recompute time_high/low
            if df_window["high"].max() > last_snapshot_row["high"]:
                time_high, _ = compute_time_high_low(df_window, ts_col="ts", high_col="high", low_col="low", timehigh_col="timehigh", timelow_col="timelow")
            else:
                time_high = last_snapshot_row["time_high"]
            
            if df_window["low"].min() < last_snapshot_row["low"]:
                _, time_low = compute_time_high_low(df_window, ts_col="ts", high_col="high", low_col="low", timehigh_col="timehigh", timelow_col="timelow")
            else:
                time_low = last_snapshot_row["time_low"]
            
            volume_val = last_snapshot_row["volume"] + df_window["volume"].sum()
        else:
            # Fresh aggregation
            open_val = df_window.iloc[0]["open"]
            high_val = df_window["high"].max()
            low_val = df_window["low"].min()
            time_open = df_window.iloc[0]["ts"]
            
            time_high, time_low = compute_time_high_low(df_window, ts_col="ts", high_col="high", low_col="low", timehigh_col="timehigh", timelow_col="timelow")
            volume_val = df_window["volume"].sum()
        
        close_val = df_window.iloc[-1]["close"]
        market_cap_val = df_window.iloc[-1]["market_cap"]
        time_close = df_window.iloc[-1]["ts"]
        
        # Missing days
        expected_dates = {bar_start_eff + timedelta(days=i) 
                         for i in range((snapshot_day - bar_start_eff).days + 1)}
        available_dates = set(df_window["local_date"])
        
        count_missing, count_missing_start, count_missing_interior, count_missing_end, missing_where = \
            _compute_missing_days_breakdown(expected_dates, available_dates, bar_start_eff, snapshot_day)

        diag = compute_missing_days_diagnostics(
            bar_start_day_local=bar_start_eff,
            snapshot_day_local=snapshot_day,
            observed_days_local=available_dates,
        )

        is_missing_days = bool(diag['is_missing_days'])
        
        if fail_on_internal_gaps and count_missing_interior > 0:
            raise ValueError(
                f"Internal gap detected: {count_missing_interior} missing days in interior for "
                f"id={df_window.iloc[0]['id']}, tf={spec.tf}, bar_seq={bar_seq}"
            )
        
        count_days = len(available_dates)
        count_days_remaining = tf_days - count_days
        
        results.append({
            "id": int(df_window.iloc[0]["id"]),
            "tf": spec.tf,
            "tf_days": tf_days,
            "bar_seq": bar_seq,
            "bar_anchor_offset": bar_anchor_offset,
            "time_open": time_open.tz_convert("UTC"),
            "time_close": time_close.tz_convert("UTC"),
            "time_high": time_high.tz_convert("UTC"),
            "time_low": time_low.tz_convert("UTC"),
            "open": float(open_val),
            "high": float(high_val),
            "low": float(low_val),
            "close": float(close_val),
            "volume": float(volume_val),
            "market_cap": float(market_cap_val),
            "is_partial_start": is_partial_start,
            "is_partial_end": is_partial_end,
            "is_missing_days": is_missing_days,
            "count_days": int(diag["count_days"]),
            "first_missing_day": diag["first_missing_day"],
            "last_missing_day": diag["last_missing_day"],
            "count_days": count_days,
            "count_days_remaining": count_days_remaining,
            "count_missing_days": count_missing,
            "count_missing_days_start": count_missing_start,
            "count_missing_days_end": count_missing_end,
            "count_missing_days_interior": count_missing_interior,
            "missing_days_where": missing_where,
        })
        
        # Update last_snapshot_row for next iteration
        if results:
            last_snapshot_row = results[-1].copy()
        
        curr_day += timedelta(days=1)
    
    if not results:
        return pd.DataFrame()
    
    return pd.DataFrame(results)


# =============================================================================
# Multiprocessing worker
# =============================================================================

def _process_single_id_with_all_specs(args: tuple) -> tuple[list[dict], dict]:
    """
    Process one ID across all specs.
    Returns: (state_updates, stats)
    """
    (
        id_,
        db_url,
        daily_table,
        bars_table,
        state_table,
        tz,
        specs,
        daily_min_ts,
        daily_max_ts,
        state_map_for_id,
        fail_on_internal_gaps,
    ) = args

    state_updates: list[dict] = []
    stats = {"upserted": 0, "rebuilds": 0, "appends": 0, "noops": 0, "errors": 0}

    try:
        daily_min_day = pd.to_datetime(daily_min_ts, utc=True).tz_convert(tz).date()
        daily_max_day = pd.to_datetime(daily_max_ts, utc=True).tz_convert(tz).date()

        # Process each spec
        for spec in specs:
            try:
                st = state_map_for_id.get((int(id_), spec.tf))

                # 1) No prior state => full rebuild (POLARS)
                if st is None:
                    df_full = load_daily_prices_for_id(db_url=db_url, daily_table=daily_table, id_=int(id_))
                    if df_full.empty:
                        stats["noops"] += 1
                        continue

                    bars = _build_snapshots_full_history_for_id_spec_polars(
                        df_full, 
                        spec=spec, 
                        tz=tz,
                        fail_on_internal_gaps=fail_on_internal_gaps
                    )
                    
                    if not bars.empty:
                        upsert_bars(bars, db_url=db_url, bars_table=bars_table)
                        stats["upserted"] += len(bars)
                        stats["rebuilds"] += 1
                        last_bar_seq = int(bars["bar_seq"].max())
                        last_time_close = pd.to_datetime(bars["time_close"].max(), utc=True)
                    else:
                        last_bar_seq = None
                        last_time_close = None

                    state_updates.append({
                        "id": int(id_),
                        "tf": spec.tf,
                        "daily_min": pd.to_datetime(daily_min_ts, utc=True),
                        "daily_max": pd.to_datetime(daily_max_ts, utc=True),
                        "last_bar_seq": last_bar_seq,
                        "last_time_close": last_time_close,
                    })
                    continue

                # 2) Have prior state
                daily_min = pd.to_datetime(st["daily_min"], utc=True) if pd.notna(st.get("daily_min")) else pd.to_datetime(daily_min_ts, utc=True)
                daily_max = pd.to_datetime(st["daily_max"], utc=True) if pd.notna(st.get("daily_max")) else pd.to_datetime(daily_max_ts, utc=True)
                last_bar_seq = int(st["last_bar_seq"]) if pd.notna(st.get("last_bar_seq")) else None
                last_time_close = pd.to_datetime(st["last_time_close"], utc=True) if pd.notna(st.get("last_time_close")) else None

                if last_bar_seq is None or last_time_close is None:
                    # Rebuild
                    df_full = load_daily_prices_for_id(db_url=db_url, daily_table=daily_table, id_=int(id_))
                    delete_bars_for_id_tf(db_url, bars_table, id_=int(id_), tf=spec.tf)
                    
                    bars = _build_snapshots_full_history_for_id_spec_polars(
                        df_full,
                        spec=spec,
                        tz=tz,
                        fail_on_internal_gaps=fail_on_internal_gaps
                    )
                    
                    if not bars.empty:
                        upsert_bars(bars, db_url=db_url, bars_table=bars_table)
                        stats["upserted"] += len(bars)
                        last_bar_seq = int(bars["bar_seq"].max())
                        last_time_close = pd.to_datetime(bars["time_close"].max(), utc=True)

                    stats["rebuilds"] += 1
                    state_updates.append({
                        "id": int(id_),
                        "tf": spec.tf,
                        "daily_min": pd.to_datetime(daily_min_ts, utc=True),
                        "daily_max": pd.to_datetime(daily_max_ts, utc=True),
                        "last_bar_seq": last_bar_seq,
                        "last_time_close": last_time_close,
                    })
                    continue

                # 3) Backfill detection => rebuild (POLARS)
                if pd.to_datetime(daily_min_ts, utc=True) < daily_min:
                    print(
                        f"[bars_anchor_us] Backfill detected: id={id_}, tf={spec.tf}, "
                        f"daily_min moved earlier {daily_min} -> {pd.to_datetime(daily_min_ts, utc=True)}. Rebuilding."
                    )
                    delete_bars_for_id_tf(db_url, bars_table, id_=int(id_), tf=spec.tf)
                    
                    df_full = load_daily_prices_for_id(db_url=db_url, daily_table=daily_table, id_=int(id_))
                    bars = _build_snapshots_full_history_for_id_spec_polars(
                        df_full,
                        spec=spec,
                        tz=tz,
                        fail_on_internal_gaps=fail_on_internal_gaps
                    )
                    
                    if not bars.empty:
                        upsert_bars(bars, db_url=db_url, bars_table=bars_table)
                        stats["upserted"] += len(bars)
                        last_bar_seq = int(bars["bar_seq"].max())
                        last_time_close = pd.to_datetime(bars["time_close"].max(), utc=True)

                    stats["rebuilds"] += 1
                    state_updates.append({
                        "id": int(id_),
                        "tf": spec.tf,
                        "daily_min": pd.to_datetime(daily_min_ts, utc=True),
                        "daily_max": pd.to_datetime(daily_max_ts, utc=True),
                        "last_bar_seq": last_bar_seq,
                        "last_time_close": last_time_close,
                    })
                    continue

                # 4) No forward data => noop
                if pd.to_datetime(daily_max_ts, utc=True) <= last_time_close:
                    stats["noops"] += 1
                    state_updates.append({
                        "id": int(id_),
                        "tf": spec.tf,
                        "daily_min": min(daily_min, pd.to_datetime(daily_min_ts, utc=True)),
                        "daily_max": max(daily_max, pd.to_datetime(daily_max_ts, utc=True)),
                        "last_bar_seq": last_bar_seq,
                        "last_time_close": last_time_close,
                    })
                    continue

                # 5) Forward incremental (pandas)
                df_head = load_daily_prices_for_id(db_url=db_url, daily_table=daily_table, id_=int(id_))
                if df_head.empty:
                    stats["noops"] += 1
                    continue

                first_day = df_head["ts"].min().tz_convert(tz).date()
                first_window_start = _anchor_start_for_first_day(first_day, spec.n, spec.unit)

                start_day = last_time_close.tz_convert(tz).date() + timedelta(days=1)
                end_day = daily_max_day

                if start_day > end_day:
                    stats["noops"] += 1
                    continue

                lookback = _lookback_days_for_spec(spec)
                slice_start_day = max(daily_min_day, start_day - timedelta(days=lookback))
                ts_start_local = pd.Timestamp(datetime.combine(slice_start_day, datetime.min.time()), tz=tz)
                ts_start = ts_start_local.tz_convert("UTC")

                df_slice = load_daily_prices_for_id(
                    db_url=db_url,
                    daily_table=daily_table,
                    id_=int(id_),
                    ts_start=ts_start,
                )
                if df_slice.empty:
                    stats["noops"] += 1
                    continue

                last_row = load_last_snapshot_row(db_url, bars_table, id_=int(id_), tf=spec.tf)

                new_rows = _build_incremental_snapshots_for_id_spec(
                    df_slice,
                    spec=spec,
                    tz=tz,
                    daily_min_day=daily_min_day,
                    first_window_start=first_window_start,
                    start_day=start_day,
                    end_day=end_day,
                    last_snapshot_row=last_row,
                    fail_on_internal_gaps=fail_on_internal_gaps,
                )

                if new_rows.empty:
                    stats["noops"] += 1
                    state_updates.append({
                        "id": int(id_),
                        "tf": spec.tf,
                        "daily_min": min(daily_min, pd.to_datetime(daily_min_ts, utc=True)),
                        "daily_max": max(daily_max, pd.to_datetime(daily_max_ts, utc=True)),
                        "last_bar_seq": last_bar_seq,
                        "last_time_close": last_time_close,
                    })
                    continue

                upsert_bars(new_rows, db_url=db_url, bars_table=bars_table)
                stats["upserted"] += len(new_rows)
                stats["appends"] += 1

                last_bar_seq2 = int(new_rows["bar_seq"].max())
                last_time_close2 = pd.to_datetime(new_rows["time_close"].max(), utc=True)

                state_updates.append({
                    "id": int(id_),
                    "tf": spec.tf,
                    "daily_min": min(daily_min, pd.to_datetime(daily_min_ts, utc=True)),
                    "daily_max": max(daily_max, pd.to_datetime(daily_max_ts, utc=True)),
                    "last_bar_seq": last_bar_seq2,
                    "last_time_close": last_time_close2,
                })

            except Exception as e:
                stats["errors"] += 1
                print(f"[bars_anchor_us] ERROR id={id_} tf={spec.tf}: {type(e).__name__}: {e}")
                # Preserve last known good state
                if st:
                    state_updates.append({
                        "id": int(id_),
                        "tf": spec.tf,
                        "daily_min": st.get("daily_min"),
                        "daily_max": st.get("daily_max"),
                        "last_bar_seq": st.get("last_bar_seq"),
                        "last_time_close": st.get("last_time_close"),
                    })

        return (state_updates, stats)

    except Exception as e:
        stats["errors"] += 1
        print(f"[bars_anchor_us] CATASTROPHIC ERROR id={id_}: {type(e).__name__}: {e}")
        return (state_updates, stats)


# =============================================================================
# Incremental driver (multiprocessing)
# =============================================================================

def refresh_incremental(
    *,
    db_url: str,
    ids: list[int],
    tz: str,
    daily_table: str,
    bars_table: str,
    state_table: str,
    fail_on_internal_gaps: bool = False,
    num_processes: int | None = None,
) -> None:
    start_time = time.time()

    ensure_state_table(db_url, state_table, with_tz=True)

    specs = load_cal_anchor_specs_from_dim_timeframe(db_url)
    tfs = [s.tf for s in specs]
    total_combinations = len(ids) * len(specs)
    print(f"[bars_anchor_us] Incremental: {len(ids)} IDs × {len(specs)} TFs = {total_combinations:,} combinations (tz={tz})")

    daily_mm = load_daily_min_max(db_url, daily_table, ids, ts_col='"timestamp"')
    if daily_mm.empty:
        print("[bars_anchor_us] No daily data found for requested ids.")
        return

    mm_map = {int(r["id"]): r for r in daily_mm.to_dict(orient="records")}

    state_df = load_state(db_url, state_table, ids, with_tz=True)
    state_map: dict[tuple[int, str], dict] = {}
    if not state_df.empty:
        for r in state_df.to_dict(orient="records"):
            state_map[(int(r["id"]), str(r["tf"]))] = r

    # Build per-id state submaps
    state_map_by_id: dict[int, dict[tuple[int, str], dict]] = {int(i): {} for i in ids}
    for (id_tf, row) in state_map.items():
        id_ = int(id_tf[0])
        if id_ in state_map_by_id:
            state_map_by_id[id_][id_tf] = row

    args_list = []
    for id_ in ids:
        mm = mm_map.get(int(id_))
        if mm is None:
            continue
        args_list.append((
            int(id_),
            db_url,
            daily_table,
            bars_table,
            state_table,
            tz,
            specs,
            mm["daily_min_ts"],
            mm["daily_max_ts"],
            state_map_by_id.get(int(id_), {}),
            fail_on_internal_gaps,
        ))

    nproc = resolve_num_processes(num_processes)

    if not args_list:
        print("[bars_anchor_us] Nothing to do (no ids with daily data).")
        return

    print(f"[bars_anchor_us] Processing {len(args_list)} IDs with {nproc} workers...")

    # Use orchestrator for parallel execution with progress tracking
    config = OrchestratorConfig(num_processes=nproc, maxtasksperchild=50, use_imap_unordered=True)
    progress = ProgressTracker(total=len(args_list), log_interval=5, prefix="[bars_anchor_us]")
    orchestrator = MultiprocessingOrchestrator(
        worker_fn=_process_single_id_with_all_specs,
        config=config,
        progress_callback=progress.update,
    )

    all_state_updates, totals = orchestrator.execute(
        args_list,
        stats_template={"upserted": 0, "rebuilds": 0, "appends": 0, "noops": 0, "errors": 0}
    )

    upsert_state(db_url, state_table, all_state_updates, with_tz=True)

    total_time = time.time() - start_time
    minutes = int(total_time // 60)
    seconds = total_time % 60
    print(
        f"[bars_anchor_us] Incremental complete: upserted={totals['upserted']:,} "
        f"rebuilds={totals['rebuilds']} appends={totals['appends']} noops={totals['noops']} "
        f"errors={totals['errors']} [time: {minutes}m {seconds:.1f}s]"
    )


# =============================================================================
# CLI
# =============================================================================

def main(argv: Sequence[str] | None = None) -> None:
    # Use shared CLI parser
    ap = create_bar_builder_argument_parser(
        description="Build US anchored weeks + calendar months/years (*_CAL_ANCHOR) price bars (UPDATED with multiprocessing).",
        default_daily_table=DEFAULT_DAILY_TABLE,
        default_bars_table=DEFAULT_BARS_TABLE,
        default_state_table=DEFAULT_STATE_TABLE,
        default_tz=DEFAULT_TZ,
        include_tz=True,
        include_fail_on_gaps=True,
    )
    args = ap.parse_args(list(argv) if argv is not None else None)

    db_url = resolve_db_url(args.db_url)
    ids = parse_ids(args.ids)
    if ids == "all":
        ids = load_all_ids(db_url, args.daily_table)

    print(f"[bars_anchor_us] daily_table={args.daily_table}")
    print(f"[bars_anchor_us] bars_table={args.bars_table}")
    print(f"[bars_anchor_us] state_table={args.state_table}")

    if args.full_rebuild:
        start_time = time.time()
        specs = load_cal_anchor_specs_from_dim_timeframe(db_url)
        total_combinations = len(ids) * len(specs)
        running_total = 0
        combo_count = 0

        print(f"[bars_anchor_us] Full rebuild: {len(ids)} IDs × {len(specs)} TFs = {total_combinations:,} combinations")

        # Ensure state table exists (with tz column)
        ensure_state_table(db_url, args.state_table, with_tz=True)

        for id_ in ids:
            df_full = load_daily_prices_for_id(db_url=db_url, daily_table=args.daily_table, id_=int(id_))
            for spec in specs:
                combo_count += 1
                delete_bars_for_id_tf(db_url, args.bars_table, id_=int(id_), tf=spec.tf)
                bars = _build_snapshots_full_history_for_id_spec_polars(
                    df_full, spec=spec, tz=args.tz, fail_on_internal_gaps=args.fail_on_internal_gaps
                )

                # Write state for this (id, tf) - ALWAYS if daily data exists
                if not df_full.empty:
                    state_row = {
                        "id": int(id_),
                        "tf": spec.tf,
                        "tz": args.tz,
                        "daily_min_seen": pd.to_datetime(df_full["ts"].min(), utc=True),
                        "daily_max_seen": pd.to_datetime(df_full["ts"].max(), utc=True),
                    }

                    # Only set last_bar_seq/time_close if bars exist
                    if not bars.empty:
                        state_row["last_bar_seq"] = int(bars["bar_seq"].max())
                        state_row["last_time_close"] = pd.to_datetime(bars["time_close"].max(), utc=True)

                    upsert_state(db_url, args.state_table, [state_row], with_tz=True)

                if not bars.empty:
                    num_rows = len(bars)
                    running_total += num_rows
                    upsert_bars(bars, db_url=db_url, bars_table=args.bars_table)

                    period_start = bars["time_open"].min().strftime("%Y-%m-%d")
                    period_end = bars["time_close"].max().strftime("%Y-%m-%d")
                    elapsed = time.time() - start_time
                    pct = (combo_count / total_combinations) * 100 if total_combinations > 0 else 0

                    print(
                        f"[bars_anchor_us] ID={id_}, TF={spec.tf}, period={period_start} to {period_end}: "
                        f"upserted {num_rows:,} rows ({running_total:,} total, {pct:.1f}%) [elapsed: {elapsed:.1f}s]"
                    )

        total_time = time.time() - start_time
        minutes = int(total_time // 60)
        seconds = total_time % 60
        print(f"[bars_anchor_us] Full rebuild complete: {running_total:,} total rows [time: {minutes}m {seconds:.1f}s]")
        return

    refresh_incremental(
        db_url=db_url,
        ids=ids,
        tz=args.tz,
        daily_table=args.daily_table,
        bars_table=args.bars_table,
        state_table=args.state_table,
        fail_on_internal_gaps=args.fail_on_internal_gaps,
        num_processes=args.num_processes,
    )


if __name__ == "__main__":
    main()
