from __future__ import annotations

"""
Calendar-aligned ISO price bars builder: public.cmc_price_bars_multi_tf_cal_iso
from public.cmc_price_histories7 (daily).

MATCHES cal_us_UPDATED FEATURES:
- Polars-backed full rebuild (fast path)
- Multiprocessing per-ID (each worker processes all specs for one id)
- CLI flag: --num-processes (default 6, capped)
- Pool(..., maxtasksperchild=50) under __main__
- Batch-load last snapshot info for (id, all tfs)
- Invariant post-fix for known timelow pathologies + OHLC clamps

ISO semantics:
- ISO week start is Monday (Mon..Sun).
"""

import argparse
import os
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from multiprocessing import Pool
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
)


# =============================================================================
# CONFIG
# =============================================================================

DEFAULT_TZ = "America/New_York"
DEFAULT_DAILY_TABLE = "public.cmc_price_histories7"
DEFAULT_BARS_TABLE = "public.cmc_price_bars_multi_tf_cal_iso"
DEFAULT_STATE_TABLE = "public.cmc_price_bars_multi_tf_cal_iso_state"


# =============================================================================
# Multiprocessing helpers
# =============================================================================

# =============================================================================
# DB helpers
# =============================================================================

def load_daily_prices_for_id(
    *,
    db_url: str,
    daily_table: str,
    id_: int,
    ts_start: pd.Timestamp | None = None,
    tz: str = DEFAULT_TZ,
) -> pd.DataFrame:
    if ts_start is None:
        where = 'WHERE id = :id'
        params = {"id": int(id_)}
    else:
        where = 'WHERE id = :id AND "timestamp" >= :ts_start'
        params = {"id": int(id_), "ts_start": ts_start}

    sql = text(f"""
      SELECT
        id,
        "timestamp" AS ts,
        timehigh,
        timelow,
        open,
        high,
        low,
        close,
        volume,
        marketcap AS market_cap
      FROM {daily_table}
      {where}
      ORDER BY "timestamp";
    """)

    eng = get_engine(db_url)
    with eng.connect() as conn:
        df = pd.read_sql(sql, conn, params=params)

    if df.empty:
        return df

    # Timestamp normalization: keep tz-aware UTC so tz_convert(tz) works downstream.
    df["ts"] = pd.to_datetime(df["ts"], utc=True, errors="raise")

    for col in ["timehigh", "timelow", "timeopen", "timeclose", "timestamp"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], utc=True, errors="coerce")

    # Hard invariant (shared contract)
    assert_one_row_per_local_day(df, ts_col="ts", tz=tz, id_col="id")

    return df


def delete_bars_for_id_tf(db_url: str, bars_table: str, id_: int, tf: str) -> None:
    sql = text(f"DELETE FROM {bars_table} WHERE id = :id AND tf = :tf;")
    eng = get_engine(db_url)
    with eng.begin() as conn:
        conn.execute(sql, {"id": int(id_), "tf": tf})


def load_last_snapshot_info_for_id_tfs(
    db_url: str,
    bars_table: str,
    id_: int,
    tfs: list[str],
) -> dict[str, dict]:
    """Batch-load latest snapshot row for a single id across multiple tfs."""
    if not tfs:
        return {}

    sql = text(f"""
      SELECT DISTINCT ON (tf)
        tf,
        bar_seq AS last_bar_seq,
        time_close AS last_time_close
      FROM {bars_table}
      WHERE id = :id AND tf = ANY(:tfs)
      ORDER BY tf, time_close DESC;
    """)
    eng = get_engine(db_url)
    with eng.connect() as conn:
        rows = conn.execute(sql, {"id": int(id_), "tfs": list(tfs)}).mappings().all()

    out: dict[str, dict] = {}
    for r in rows:
        tf = str(r["tf"])
        out[tf] = {
            "last_bar_seq": int(r["last_bar_seq"]),
            "last_time_close": pd.to_datetime(r["last_time_close"], utc=True),
        }
    return out


def load_last_snapshot_row(db_url: str, bars_table: str, id_: int, tf: str) -> dict | None:
    sql = text(f"""
      SELECT *
      FROM {bars_table}
      WHERE id = :id AND tf = :tf
      ORDER BY time_close DESC
      LIMIT 1;
    """)
    eng = get_engine(db_url)
    with eng.connect() as conn:
        row = conn.execute(sql, {"id": int(id_), "tf": tf}).mappings().first()
    return dict(row) if row else None


# =============================================================================
# dim_timeframe-driven TF specs (ISO)
# =============================================================================

@dataclass(frozen=True)
class CalIsoSpec:
    n: int
    unit: str  # 'W','M','Y'
    tf: str

CalSpec = CalIsoSpec


def load_cal_specs_from_dim_timeframe(db_url: str):
    """
    Load calendar-aligned, FULL-PERIOD (non-anchor) ISO timeframes.
    - ISO weeks: *_CAL_ISO$
    - M/Y: scheme-agnostic *_CAL (but not *_CAL_*)
    """
    sql = text(r"""
      SELECT tf, base_unit, tf_qty, sort_order
      FROM public.dim_timeframe
      WHERE alignment_type = 'calendar'
        AND allow_partial_start = FALSE
        AND allow_partial_end   = FALSE
        AND calendar_anchor     = FALSE
        AND tf NOT LIKE '%\_CAL\_ANCHOR\_%' ESCAPE '\'
        AND tf NOT LIKE '%\_ANCHOR%' ESCAPE '\'
        AND (
              (base_unit = 'W' AND tf ~ '_CAL_ISO$')
              OR
              (base_unit IN ('M','Y') AND tf ~ '_CAL$' AND tf !~ '_CAL_')
            )
      ORDER BY sort_order, tf;
    """)

    eng = get_engine(db_url)
    with eng.connect() as conn:
        rows = conn.execute(sql).mappings().all()

    if not rows:
        raise RuntimeError(
            "No CAL_ISO timeframes found in dim_timeframe. "
            "Expected ISO week CAL (_CAL_ISO) plus scheme-agnostic M/Y (_CAL) with calendar_anchor=FALSE."
        )

    return [
        CalSpec(n=int(r["tf_qty"]), unit=str(r["base_unit"]), tf=str(r["tf"]))
        for r in rows
    ]


# =============================================================================
# Calendar math helpers (ISO week = Monday..Sunday) in NY-local date logic
# =============================================================================

def _last_day_of_month(d: date) -> date:
    if d.month == 12:
        return date(d.year, 12, 31)
    first_next = date(d.year, d.month + 1, 1)
    return first_next - timedelta(days=1)


def _add_months(d: date, months: int) -> date:
    y = d.year + (d.month - 1 + months) // 12
    m = (d.month - 1 + months) % 12 + 1
    day = min(d.day, _last_day_of_month(date(y, m, 1)).day)
    return date(y, m, day)


def _month_start(d: date) -> date:
    return date(d.year, d.month, 1)


def _year_start(d: date) -> date:
    return date(d.year, 1, 1)


def _week_start_monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _anchor_start_for_first_day(first_day: date, n: int, unit: str) -> date:
    """
    First FULL period boundary at/after first_day (full-period policy).
    n is accepted for signature parity with cal_us_UPDATED.
    """
    if unit == "W":
        ws = _week_start_monday(first_day)
        return ws if first_day == ws else ws + timedelta(days=7)
    if unit == "M":
        ms = _month_start(first_day)
        return ms if first_day == ms else _add_months(ms, 1)
    if unit == "Y":
        ys = _year_start(first_day)
        return ys if first_day == ys else date(first_day.year + 1, 1, 1)
    raise ValueError(f"Unsupported unit: {unit}")


def _bar_end_for_start(bar_start: date, n: int, unit: str) -> date:
    if unit == "W":
        return bar_start + timedelta(days=7 * n - 1)
    if unit == "M":
        end_month_start = _add_months(bar_start, n - 1)
        return _last_day_of_month(end_month_start)
    if unit == "Y":
        return date(bar_start.year + n, 1, 1) - timedelta(days=1)
    raise ValueError(f"Unsupported unit: {unit}")


def _expected_days(bar_start: date, bar_end: date) -> int:
    return (bar_end - bar_start).days + 1


def _months_diff(a: date, b: date) -> int:
    return (b.year - a.year) * 12 + (b.month - a.month)


def _bar_start_for_index(anchor_start: date, idx: int, n: int, unit: str) -> date:
    if unit == "W":
        return anchor_start + timedelta(days=7 * n * idx)
    if unit == "M":
        return _add_months(anchor_start, n * idx)
    if unit == "Y":
        return date(anchor_start.year + n * idx, 1, 1)
    raise ValueError(f"Unsupported unit: {unit}")


# =============================================================================
# Data-quality fix + invariants (matches cal_us_UPDATED)
# =============================================================================

# =============================================================================
# Bar building helpers
# =============================================================================

def _build_snapshots_full_history_for_id_spec_polars(
    df_id: pd.DataFrame,
    *,
    spec: CalIsoSpec,
    tz: str,
) -> pd.DataFrame:
    """
    Full rebuild (POLARS): emit one snapshot row per available local day from anchor_start onward.
    Incremental append logic remains pandas-based.
    """
    if df_id.empty:
        return pd.DataFrame()

    df = df_id.sort_values("ts").reset_index(drop=True).copy()
    assert_one_row_per_local_day(df, ts_col="ts", tz=tz)

    ts_local = df["ts"].dt.tz_convert(tz)
    df["day_date"] = ts_local.dt.date

    first_day: date = df["day_date"].iloc[0]
    last_day: date = df["day_date"].iloc[-1]

    anchor_start = _anchor_start_for_first_day(first_day, spec.n, spec.unit)

    df = df[df["day_date"] >= anchor_start].copy()
    if df.empty:
        return pd.DataFrame()

    # Vectorized bar index -> bar_seq
    day_dt = pd.to_datetime(df["day_date"])
    if spec.unit == "W":
        span = 7 * int(spec.n)
        bar_idx = ((day_dt - pd.Timestamp(anchor_start)).dt.days // span).astype("int64")
    elif spec.unit == "M":
        a = pd.Timestamp(_month_start(anchor_start))
        y = pd.DatetimeIndex(day_dt).year
        mo = pd.DatetimeIndex(day_dt).month
        am = a.year * 12 + a.month
        bar_idx = (((y * 12 + mo) - am) // int(spec.n)).astype("int64")
    elif spec.unit == "Y":
        y = pd.DatetimeIndex(day_dt).year
        bar_idx = (((y - anchor_start.year) // int(spec.n))).astype("int64")
    else:
        raise ValueError(f"Unsupported unit: {spec.unit}")

    df["bar_seq"] = (bar_idx + 1).astype("int64")

    # Precompute per-bar boundaries + expected length
    uniq = np.sort(df["bar_seq"].unique())
    bar_rows = []
    for bar_seq in uniq:
        idx0 = int(bar_seq) - 1
        bar_start = _bar_start_for_index(anchor_start, idx0, spec.n, spec.unit)
        bar_end = _bar_end_for_start(bar_start, spec.n, spec.unit)
        tf_days = _expected_days(bar_start, bar_end)
        bar_rows.append((int(bar_seq), bar_start, bar_end, int(tf_days)))
    df_bar = pd.DataFrame(bar_rows, columns=["bar_seq", "bar_start", "bar_end", "tf_days"])
    df = df.merge(df_bar, on="bar_seq", how="left")

    df["exp_to_date"] = (pd.to_datetime(df["day_date"]) - pd.to_datetime(df["bar_start"])).dt.days + 1
    df["exp_to_date"] = df["exp_to_date"].astype("int64")

    # Start-run missing (constant per bar)
    min_day = df.groupby("bar_seq")["day_date"].transform("min")
    df["count_missing_days_start"] = (
        (pd.to_datetime(min_day) - pd.to_datetime(df["bar_start"])).dt.days.clip(lower=0).astype("int64")
    )

    from ta_lab2.scripts.bars.polars_bar_operations import (
        compute_day_time_open,
        apply_ohlcv_cumulative_aggregations,
    )

    pl_df = pl.from_pandas(df).sort("ts")

    # Strip timezone info for Polars processing (avoid DST ambiguity issues)
    timestamp_cols = ["ts", "timehigh", "timelow"]
    pl_df = pl_df.with_columns([
        pl.col(col).dt.replace_time_zone(None)
        for col in timestamp_cols
        if col in pl_df.columns
    ])

    one_ms = pl.duration(milliseconds=1)

    # Use extracted utility for day_time_open
    pl_df = compute_day_time_open(pl_df)

    pl_df = pl_df.with_columns([
        (pl.col("bar_seq").cum_count().over("bar_seq") + 1).cast(pl.Int64).alias("count_days"),
        (pl.col("bar_seq").cum_count().over("bar_seq") + 1).cast(pl.Int64).alias("pos_in_bar"),
    ])

    pl_df = pl_df.with_columns([
        pl.col("day_time_open").first().over("bar_seq").alias("time_open"),
        pl.col("ts").alias("time_close"),
        (pl.col("ts") + one_ms).alias("last_ts_half_open"),
    ])

    # Use extracted utility for OHLCV aggregations
    pl_df = apply_ohlcv_cumulative_aggregations(pl_df)

    # -----------------------------------------------------------------------------
    # CORRECT extrema timestamps:
    # - Fallback to ts when timehigh/timelow is null (contract requirement)
    # - Must reset when a NEW running extreme occurs (new high/new low).
    # - Within the current "extreme segment", choose earliest timestamp among ties.
    #
    # We do this by:
    #   1) Detect when high_bar/low_bar changes vs previous row in bar_seq
    #   2) Build a segment id via cumulative sum of "new extreme" flags
    #   3) For each segment, take min(candidate_time) among rows that hit the extreme
    #   4) Forward-fill within bar_seq
    # -----------------------------------------------------------------------------

    pl_df = pl_df.with_columns([
        pl.when(pl.col("timehigh").is_null()).then(pl.col("ts")).otherwise(pl.col("timehigh")).alias("timehigh_actual"),
        pl.when(pl.col("timelow").is_null()).then(pl.col("ts")).otherwise(pl.col("timelow")).alias("timelow_actual"),
    ])

    prev_high_bar = pl.col("high_bar").shift(1).over("bar_seq")
    prev_low_bar  = pl.col("low_bar").shift(1).over("bar_seq")

    pl_df = pl_df.with_columns([
        (prev_high_bar.is_null() | (pl.col("high_bar") != prev_high_bar)).alias("_new_high"),
        (prev_low_bar.is_null()  | (pl.col("low_bar")  != prev_low_bar)).alias("_new_low"),
    ])

    pl_df = pl_df.with_columns([
        pl.col("_new_high").cast(pl.Int64).cum_sum().over("bar_seq").alias("_high_seg"),
        pl.col("_new_low").cast(pl.Int64).cum_sum().over("bar_seq").alias("_low_seg"),
    ])

    # candidate timestamps on rows that match the CURRENT running extreme
    pl_df = pl_df.with_columns([
        pl.when(pl.col("high") == pl.col("high_bar"))
        .then(pl.col("timehigh_actual"))
        .otherwise(pl.lit(None))
        .alias("_th_cand"),

        pl.when(pl.col("low") == pl.col("low_bar"))
        .then(pl.col("timelow_actual"))
        .otherwise(pl.lit(None))
        .alias("_tl_cand"),
    ])

    # earliest among ties inside the current extreme segment, then forward-fill
    pl_df = pl_df.with_columns([
        pl.col("_th_cand").min().over(["bar_seq", "_high_seg"]).alias("_time_high_seg"),
        pl.col("_tl_cand").min().over(["bar_seq", "_low_seg"]).alias("_time_low_seg"),
    ])

    pl_df = pl_df.with_columns([
        pl.col("_time_high_seg").forward_fill().over("bar_seq").alias("time_high"),
        pl.col("_time_low_seg").forward_fill().over("bar_seq").alias("time_low"),
    ]).drop([
        "timehigh_actual", "timelow_actual",
        "_new_high", "_new_low",
        "_high_seg", "_low_seg",
        "_th_cand", "_tl_cand",
        "_time_high_seg", "_time_low_seg",
    ])

    pl_df = pl_df.with_columns([
        (pl.col("exp_to_date").cast(pl.Int64) - pl.col("count_days").cast(pl.Int64)).clip(0, None).alias("count_missing_days"),
    ])

    pl_df = pl_df.with_columns([
        pl.lit(0).cast(pl.Int64).alias("count_missing_days_end"),
        (pl.col("count_missing_days") - pl.col("count_missing_days_start")).clip(0, None).cast(pl.Int64).alias("count_missing_days_interior"),
        (pl.col("count_missing_days") > 0).alias("is_missing_days"),
        pl.lit(False).alias("is_partial_start"),
        (pl.col("day_date") < pl.col("bar_end")).alias("is_partial_end"),
        (pl.col("tf_days").cast(pl.Int64) - pl.col("exp_to_date").cast(pl.Int64)).cast(pl.Int64).alias("count_days_remaining"),
        pl.when(pl.col("count_missing_days") > 0).then(pl.lit("interior")).otherwise(pl.lit(None)).alias("missing_days_where"),
    ])

    out_pl = pl_df.select([
        pl.col("id").cast(pl.Int64),
        pl.lit(spec.tf).alias("tf"),
        pl.col("tf_days").cast(pl.Int64),
        pl.col("bar_seq").cast(pl.Int64),

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
        pl.col("count_days_remaining").cast(pl.Int64),

        pl.col("count_missing_days").cast(pl.Int64),
        pl.col("count_missing_days_start").cast(pl.Int64),
        pl.col("count_missing_days_end").cast(pl.Int64),
        pl.col("count_missing_days_interior").cast(pl.Int64),

        pl.col("missing_days_where"),
    ])

    from ta_lab2.scripts.bars.polars_bar_operations import compact_output_types

    out = out_pl.to_pandas()

    # Use extracted utility for type compaction
    out = compact_output_types(out)

    return out


# =============================================================================
# Incremental builder (pandas; same behavior as your existing ISO version)
# =============================================================================

def _make_day_time_open(ts: pd.Series) -> pd.Series:
    one_ms = pd.Timedelta(milliseconds=1)
    day_open = ts.shift(1) + one_ms
    if len(ts) > 0:
        day_open.iloc[0] = ts.iloc[0] - pd.Timedelta(days=1) + one_ms
    return day_open


def _missing_days_metrics(
    *,
    bar_start: date,
    snap_day: date,
    avail_dates: set[date],
    max_list: int = 200,
) -> dict:
    exp_to_date = (snap_day - bar_start).days + 1
    missing: list[date] = []
    have_to_date = 0

    for k in range(exp_to_date):
        d = bar_start + timedelta(days=k)
        if d in avail_dates:
            have_to_date += 1
        else:
            missing.append(d)

    count_missing_days = exp_to_date - have_to_date

    start_run = 0
    for k in range(exp_to_date):
        d = bar_start + timedelta(days=k)
        if d in avail_dates:
            break
        start_run += 1

    end_run = 0
    for k in range(exp_to_date - 1, -1, -1):
        d = bar_start + timedelta(days=k)
        if d in avail_dates:
            break
        end_run += 1

    interior = max(0, count_missing_days - start_run - end_run)

    if not missing:
        missing_where = None
    else:
        missing_strs = [d.isoformat() for d in missing[:max_list]]
        suffix = "" if len(missing) <= max_list else f"...(+{len(missing) - max_list})"
        missing_where = ",".join(missing_strs) + suffix

    return {
        "count_days": int(have_to_date),
        "count_missing_days": int(count_missing_days),
        "count_missing_days_start": int(start_run),
        "count_missing_days_end": int(end_run),
        "count_missing_days_interior": int(interior),
        "missing_days_where": missing_where,
        "exp_to_date": int(exp_to_date),
    }


def _bar_index_for_day(anchor_start: date, d: date, n: int, unit: str) -> int:
    if d < anchor_start:
        raise ValueError("day before anchor_start")
    if unit == "W":
        span = 7 * n
        return (d - anchor_start).days // span
    if unit == "M":
        a = _month_start(anchor_start)
        m = _month_start(d)
        return _months_diff(a, m) // n
    if unit == "Y":
        return (d.year - anchor_start.year) // n
    raise ValueError(f"Unsupported unit: {unit}")


def _build_incremental_snapshots_for_id_spec(
    df_slice: pd.DataFrame,
    *,
    spec: CalIsoSpec,
    tz: str,
    anchor_start: date,
    start_day: date,
    end_day: date,
    last_snapshot_row: dict | None,
) -> pd.DataFrame:
    if df_slice.empty or start_day > end_day:
        return pd.DataFrame()

    df = df_slice.sort_values("ts").reset_index(drop=True).copy()
    assert_one_row_per_local_day(df, ts_col="ts", tz=tz)

    ts_local = df["ts"].dt.tz_convert(tz)
    df["day_date"] = ts_local.dt.date
    df["day_time_open"] = _make_day_time_open(df["ts"])

    df_by_date = {d: i for i, d in enumerate(df["day_date"].tolist())}
    avail_dates = set(df_by_date.keys())
    id_val = int(df["id"].iloc[0])

    rows: list[dict] = []

    carry = None
    if last_snapshot_row is not None:
        carry = {
            "bar_seq": int(last_snapshot_row["bar_seq"]) if last_snapshot_row.get("bar_seq") is not None else None,
            "time_open": (
                pd.to_datetime(last_snapshot_row["time_open"], utc=True)
                if last_snapshot_row.get("time_open") is not None
                else None
            ),
            "open": float(last_snapshot_row["open"]) if last_snapshot_row.get("open") is not None else np.nan,
            "high": float(last_snapshot_row["high"]) if last_snapshot_row.get("high") is not None else np.nan,
            "low": float(last_snapshot_row["low"]) if last_snapshot_row.get("low") is not None else np.nan,
            "volume": float(last_snapshot_row["volume"]) if last_snapshot_row.get("volume") is not None else 0.0,
            "time_high": (
                pd.to_datetime(last_snapshot_row["time_high"], utc=True)
                if last_snapshot_row.get("time_high") is not None
                else pd.NaT
            ),
            "time_low": (
                pd.to_datetime(last_snapshot_row["time_low"], utc=True)
                if last_snapshot_row.get("time_low") is not None
                else pd.NaT
            ),
        }
        last_close_local_day = pd.to_datetime(last_snapshot_row["time_close"], utc=True).tz_convert(tz).date()
        carry["last_day"] = last_close_local_day
        carry["is_missing_days"] = bool(last_snapshot_row.get("is_missing_days", False))

        carry["count_days"] = int(last_snapshot_row.get("count_days") or 0)
        carry["count_days_remaining"] = int(last_snapshot_row.get("count_days_remaining") or 0)
        carry["count_missing_days"] = int(last_snapshot_row.get("count_missing_days") or 0)
        carry["count_missing_days_start"] = int(last_snapshot_row.get("count_missing_days_start") or 0)
        carry["count_missing_days_end"] = int(last_snapshot_row.get("count_missing_days_end") or 0)
        carry["count_missing_days_interior"] = int(last_snapshot_row.get("count_missing_days_interior") or 0)
        carry["missing_days_where"] = last_snapshot_row.get("missing_days_where")
    else:
        carry = None

    cur_day = start_day
    while cur_day <= end_day:
        j = df_by_date.get(cur_day)
        if j is None:
            cur_day = cur_day + timedelta(days=1)
            continue

        bar_idx = _bar_index_for_day(anchor_start, cur_day, spec.n, spec.unit)
        bar_start = _bar_start_for_index(anchor_start, bar_idx, spec.n, spec.unit)
        bar_end = _bar_end_for_start(bar_start, spec.n, spec.unit)
        bar_seq = bar_idx + 1
        tf_days = _expected_days(bar_start, bar_end)

        can_carry = (
            carry is not None
            and carry.get("bar_seq") == bar_seq
            and carry.get("last_day") is not None
            and carry["last_day"] == (cur_day - timedelta(days=1))
        )

        m = _missing_days_metrics(bar_start=bar_start, snap_day=cur_day, avail_dates=avail_dates)
        count_days_remaining = int(tf_days - m["exp_to_date"])
        is_missing_days_today = (m["count_missing_days"] > 0)

        if not can_carry:
            idxs: list[int] = []
            for k in range(m["exp_to_date"]):
                d = bar_start + timedelta(days=k)
                jj = df_by_date.get(d)
                if jj is not None:
                    idxs.append(jj)

            g = df.iloc[idxs]
            if g.empty:
                cur_day = cur_day + timedelta(days=1)
                continue

            high_val = g["high"].max()
            low_val = g["low"].min()

            time_open = g["day_time_open"].iloc[0]
            open_ = float(g["open"].iloc[0]) if pd.notna(g["open"].iloc[0]) else np.nan
            volume_ = float(g["volume"].sum(skipna=True))

            time_high, time_low = compute_time_high_low(g)

            carry = {
                "bar_seq": bar_seq,
                "time_open": time_open,
                "open": open_,
                "high": float(high_val) if pd.notna(high_val) else np.nan,
                "low": float(low_val) if pd.notna(low_val) else np.nan,
                "volume": volume_,
                "time_high": time_high,
                "time_low": time_low,
                "last_day": cur_day,
                "is_missing_days": bool(is_missing_days_today),
                "count_days": int(m["count_days"]),
                "count_days_remaining": int(count_days_remaining),
                "count_missing_days": int(m["count_missing_days"]),
                "count_missing_days_start": int(m["count_missing_days_start"]),
                "count_missing_days_end": int(m["count_missing_days_end"]),
                "count_missing_days_interior": int(m["count_missing_days_interior"]),
                "missing_days_where": m["missing_days_where"],
            }
        else:
            carry["is_missing_days"] = bool(carry.get("is_missing_days", False) or is_missing_days_today)

            day_high = float(df.loc[j, "high"]) if pd.notna(df.loc[j, "high"]) else np.nan
            day_low = float(df.loc[j, "low"]) if pd.notna(df.loc[j, "low"]) else np.nan

            # Fallback to ts when timehigh/timelow is null (contract requirement)
            day_th_raw = df.loc[j, "timehigh"]
            day_th = day_th_raw if pd.notna(day_th_raw) else df.loc[j, "ts"]

            if pd.isna(carry["high"]) or (pd.notna(day_high) and day_high > carry["high"]):
                carry["high"] = day_high
                carry["time_high"] = day_th
            elif pd.notna(day_high) and pd.notna(carry["high"]) and day_high == carry["high"]:
                if pd.notna(day_th) and (pd.isna(carry["time_high"]) or day_th < carry["time_high"]):
                    carry["time_high"] = day_th

            day_tl_raw = df.loc[j, "timelow"]
            day_tl = day_tl_raw if pd.notna(day_tl_raw) else df.loc[j, "ts"]

            if pd.isna(carry["low"]) or (pd.notna(day_low) and day_low < carry["low"]):
                carry["low"] = day_low
                carry["time_low"] = day_tl
            elif pd.notna(day_low) and pd.notna(carry["low"]) and day_low == carry["low"]:
                if pd.notna(day_tl) and (pd.isna(carry["time_low"]) or day_tl < carry["time_low"]):
                    carry["time_low"] = day_tl

            carry["volume"] = float(carry["volume"]) + (float(df.loc[j, "volume"]) if pd.notna(df.loc[j, "volume"]) else 0.0)
            carry["last_day"] = cur_day

            carry["count_days"] = int(m["count_days"])
            carry["count_days_remaining"] = int(count_days_remaining)
            carry["count_missing_days"] = int(m["count_missing_days"])
            carry["count_missing_days_start"] = int(m["count_missing_days_start"])
            carry["count_missing_days_end"] = int(m["count_missing_days_end"])
            carry["count_missing_days_interior"] = int(m["count_missing_days_interior"])
            carry["missing_days_where"] = m["missing_days_where"]

        is_partial_end = (cur_day < bar_end)
        is_partial_start = False

        rows.append(
            {
                "id": id_val,
                "tf": spec.tf,
                "tf_days": int(tf_days),
                "bar_seq": int(bar_seq),
                "time_open": carry["time_open"],
                "time_close": df.loc[j, "ts"],
                "last_ts_half_open": df.loc[j, "ts"] + pd.Timedelta(milliseconds=1),
                "timestamp": df.loc[j, "ts"],
                "pos_in_bar": int(carry.get("count_days", 0)),
                "time_high": carry["time_high"],
                "time_low": carry["time_low"],
                "open": float(carry["open"]) if pd.notna(carry["open"]) else np.nan,
                "high": float(carry["high"]) if pd.notna(carry["high"]) else np.nan,
                "low": float(carry["low"]) if pd.notna(carry["low"]) else np.nan,
                "close": float(df.loc[j, "close"]) if pd.notna(df.loc[j, "close"]) else np.nan,
                "volume": float(carry["volume"]),
                "market_cap": float(df.loc[j, "market_cap"]) if pd.notna(df.loc[j, "market_cap"]) else np.nan,
                "is_partial_start": bool(is_partial_start),
                "is_partial_end": bool(is_partial_end),
                "is_missing_days": bool(carry.get("is_missing_days", False)),
                "count_days": int(carry.get("count_days", 0)),
                "count_days_remaining": int(carry.get("count_days_remaining", 0)),
                "count_missing_days": int(carry.get("count_missing_days", 0)),
                "count_missing_days_start": int(carry.get("count_missing_days_start", 0)),
                "count_missing_days_end": int(carry.get("count_missing_days_end", 0)),
                "count_missing_days_interior": int(carry.get("count_missing_days_interior", 0)),
                "missing_days_where": carry.get("missing_days_where"),
            }
        )

        cur_day = cur_day + timedelta(days=1)

    out = pd.DataFrame.from_records(rows)
    if out.empty:
        return out

    out["bar_seq"] = out["bar_seq"].astype(np.int32)
    out["tf_days"] = out["tf_days"].astype(np.int32)
    out["count_days"] = out["count_days"].astype(np.int32)
    out["count_days_remaining"] = out["count_days_remaining"].astype(np.int32)
    out["count_missing_days"] = out["count_missing_days"].astype(np.int32)
    out["count_missing_days_start"] = out["count_missing_days_start"].astype(np.int32)
    out["count_missing_days_end"] = out["count_missing_days_end"].astype(np.int32)
    out["count_missing_days_interior"] = out["count_missing_days_interior"].astype(np.int32)
    out["is_partial_start"] = out["is_partial_start"].astype(bool)
    out["is_partial_end"] = out["is_partial_end"].astype(bool)
    out["is_missing_days"] = out["is_missing_days"].astype(bool)
    return out


# =============================================================================
# Upsert (append-only snapshots)
# =============================================================================

# =============================================================================
# Multiprocessing worker: process one ID across all specs
# =============================================================================

def _process_single_id_with_all_specs(args: tuple) -> tuple[list[dict], dict[str, int]]:
    """
    Worker returns: (state_updates, stats)
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
        state_map_for_id,  # dict[(id,tf)] -> state row dict
    ) = args

    state_updates: list[dict] = []
    stats = {"id": int(id_), "upserted": 0, "rebuilds": 0, "appends": 0, "noops": 0, "errors": 0}

    try:
        daily_max_day: date = pd.to_datetime(daily_max_ts, utc=True).tz_convert(tz).date()
        tfs = [s.tf for s in specs]
        last_snap_map = load_last_snapshot_info_for_id_tfs(db_url, bars_table, id_=int(id_), tfs=tfs)

        for spec in specs:
            st = state_map_for_id.get((int(id_), spec.tf))
            last_snap = last_snap_map.get(spec.tf)

            daily_min_seen = (
                pd.to_datetime(st["daily_min_seen"], utc=True)
                if st is not None and pd.notna(st.get("daily_min_seen"))
                else pd.to_datetime(daily_min_ts, utc=True)
            )
            daily_max_seen = (
                pd.to_datetime(st["daily_max_seen"], utc=True)
                if st is not None and pd.notna(st.get("daily_max_seen"))
                else pd.to_datetime(daily_max_ts, utc=True)
            )

            # 1) No state + no bars => full rebuild (POLARS)
            if st is None and last_snap is None:
                df_full = load_daily_prices_for_id(db_url=db_url, daily_table=daily_table, id_=int(id_))
                bars = _build_snapshots_full_history_for_id_spec_polars(df_full, spec=spec, tz=tz)
                if not bars.empty:
                    upsert_bars(bars, db_url=db_url, bars_table=bars_table)
                    stats["upserted"] += len(bars)
                    stats["rebuilds"] += 1
                    last_bar_seq = int(bars["bar_seq"].max())
                    last_time_close = pd.to_datetime(bars["time_close"].max(), utc=True)
                else:
                    last_bar_seq = None
                    last_time_close = None

                state_updates.append(
                    {
                        "id": int(id_),
                        "tf": spec.tf,
                        "tz": tz,
                        "daily_min_seen": pd.to_datetime(daily_min_ts, utc=True),
                        "daily_max_seen": pd.to_datetime(daily_max_ts, utc=True),
                        "last_bar_seq": last_bar_seq,
                        "last_time_close": last_time_close,
                    }
                )
                continue

            # 2) State exists but bars missing => rebuild (POLARS)
            if last_snap is None:
                df_full = load_daily_prices_for_id(db_url=db_url, daily_table=daily_table, id_=int(id_))
                bars = _build_snapshots_full_history_for_id_spec_polars(df_full, spec=spec, tz=tz)
                if not bars.empty:
                    upsert_bars(bars, db_url=db_url, bars_table=bars_table)
                    stats["upserted"] += len(bars)
                    stats["rebuilds"] += 1
                    last_bar_seq = int(bars["bar_seq"].max())
                    last_time_close = pd.to_datetime(bars["time_close"].max(), utc=True)
                else:
                    last_bar_seq = None
                    last_time_close = None

                state_updates.append(
                    {
                        "id": int(id_),
                        "tf": spec.tf,
                        "tz": tz,
                        "daily_min_seen": pd.to_datetime(daily_min_ts, utc=True),
                        "daily_max_seen": pd.to_datetime(daily_max_ts, utc=True),
                        "last_bar_seq": last_bar_seq,
                        "last_time_close": last_time_close,
                    }
                )
                continue

            last_time_close: pd.Timestamp = last_snap["last_time_close"]
            last_bar_seq = int(last_snap["last_bar_seq"])

            # 3) Backfill detection => delete + rebuild (POLARS)
            if pd.to_datetime(daily_min_ts, utc=True) < daily_min_seen:
                print(
                    f"[bars_cal_iso] Backfill detected: id={id_}, tf={spec.tf}, "
                    f"daily_min moved earlier {daily_min_seen} -> {pd.to_datetime(daily_min_ts, utc=True)}. Rebuilding id/tf."
                )
                delete_bars_for_id_tf(db_url, bars_table, id_=int(id_), tf=spec.tf)

                df_full = load_daily_prices_for_id(db_url=db_url, daily_table=daily_table, id_=int(id_))
                bars = _build_snapshots_full_history_for_id_spec_polars(df_full, spec=spec, tz=tz)
                if not bars.empty:
                    upsert_bars(bars, db_url=db_url, bars_table=bars_table)
                    stats["upserted"] += len(bars)
                    last_bar_seq = int(bars["bar_seq"].max())
                    last_time_close = pd.to_datetime(bars["time_close"].max(), utc=True)

                stats["rebuilds"] += 1
                state_updates.append(
                    {
                        "id": int(id_),
                        "tf": spec.tf,
                        "tz": tz,
                        "daily_min_seen": pd.to_datetime(daily_min_ts, utc=True),
                        "daily_max_seen": pd.to_datetime(daily_max_ts, utc=True),
                        "last_bar_seq": last_bar_seq,
                        "last_time_close": last_time_close,
                    }
                )
                continue

            # 4) No forward data => noop
            if pd.to_datetime(daily_max_ts, utc=True) <= last_time_close:
                stats["noops"] += 1
                state_updates.append(
                    {
                        "id": int(id_),
                        "tf": spec.tf,
                        "tz": tz,
                        "daily_min_seen": min(daily_min_seen, pd.to_datetime(daily_min_ts, utc=True)),
                        "daily_max_seen": max(daily_max_seen, pd.to_datetime(daily_max_ts, utc=True)),
                        "last_bar_seq": last_bar_seq,
                        "last_time_close": last_time_close,
                    }
                )
                continue

            # 5) Forward incremental (pandas)
            df_head = load_daily_prices_for_id(db_url=db_url, daily_table=daily_table, id_=int(id_))
            if df_head.empty:
                stats["noops"] += 1
                continue

            first_day = df_head["ts"].min().tz_convert(tz).date()
            anchor_start = _anchor_start_for_first_day(first_day, spec.n, spec.unit)

            start_day = last_time_close.tz_convert(tz).date() + timedelta(days=1)
            end_day = daily_max_day
            if start_day > end_day:
                stats["noops"] += 1
                continue

            slice_start_day = max(anchor_start, start_day - timedelta(days=400))
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
                anchor_start=anchor_start,
                start_day=start_day,
                end_day=end_day,
                last_snapshot_row=last_row,
            )

            if new_rows.empty:
                stats["noops"] += 1
                state_updates.append(
                    {
                        "id": int(id_),
                        "tf": spec.tf,
                        "tz": tz,
                        "daily_min_seen": min(daily_min_seen, pd.to_datetime(daily_min_ts, utc=True)),
                        "daily_max_seen": max(daily_max_seen, pd.to_datetime(daily_max_ts, utc=True)),
                        "last_bar_seq": last_bar_seq,
                        "last_time_close": last_time_close,
                    }
                )
                continue

            upsert_bars(new_rows, db_url=db_url, bars_table=bars_table)
            stats["upserted"] += len(new_rows)
            stats["appends"] += 1

            last_bar_seq2 = int(new_rows["bar_seq"].max())
            last_time_close2 = pd.to_datetime(new_rows["time_close"].max(), utc=True)

            state_updates.append(
                {
                    "id": int(id_),
                    "tf": spec.tf,
                    "tz": tz,
                    "daily_min_seen": min(daily_min_seen, pd.to_datetime(daily_min_ts, utc=True)),
                    "daily_max_seen": max(daily_max_seen, pd.to_datetime(daily_max_ts, utc=True)),
                    "last_bar_seq": last_bar_seq2,
                    "last_time_close": last_time_close2,
                }
            )

        return (state_updates, stats)

    except Exception as e:
        stats["errors"] += 1
        print(f"[bars_cal_iso] ERROR id={id_}: {type(e).__name__}: {e}")
        # return no state updates on catastrophic worker failure
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
    num_processes: int | None = None,
) -> None:
    start_time = time.time()

    ensure_state_table(db_url, state_table, with_tz=False)

    specs = load_cal_specs_from_dim_timeframe(db_url)
    tfs = [s.tf for s in specs]
    total_combinations = len(ids) * len(specs)
    print(f"[bars_cal_iso] Incremental: {len(ids)} IDs × {len(specs)} TFs = {total_combinations:,} combinations (tz={tz})")

    daily_mm = load_daily_min_max(db_url, daily_table, ids)
    if daily_mm.empty:
        print("[bars_cal_iso] No daily data found for requested ids.")
        return

    mm_map = {int(r["id"]): r for r in daily_mm.to_dict(orient="records")}

    state_df = load_state(db_url, state_table, ids, with_tz=False)
    state_map: dict[tuple[int, str], dict] = {}
    if not state_df.empty:
        for r in state_df.to_dict(orient="records"):
            state_map[(int(r["id"]), str(r["tf"]))] = r

    # Build per-id state submaps to reduce pickled payload size
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
        args_list.append(
            (
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
            )
        )

    nproc = resolve_num_processes(num_processes)

    all_state_updates: list[dict] = []
    totals = {"upserted": 0, "rebuilds": 0, "appends": 0, "noops": 0, "errors": 0}

    if not args_list:
        print("[bars_cal_iso] Nothing to do (no ids with daily data).")
        return

    with Pool(processes=nproc, maxtasksperchild=50) as pool:
        for state_updates, stats in pool.imap_unordered(_process_single_id_with_all_specs, args_list):
            all_state_updates.extend(state_updates)
            totals["upserted"] += int(stats.get("upserted", 0))
            totals["rebuilds"] += int(stats.get("rebuilds", 0))
            totals["appends"] += int(stats.get("appends", 0))
            totals["noops"] += int(stats.get("noops", 0))
            totals["errors"] += int(stats.get("errors", 0))

    upsert_state(db_url, state_table, all_state_updates, with_tz=False)

    total_time = time.time() - start_time
    minutes = int(total_time // 60)
    seconds = total_time % 60
    print(
        f"[bars_cal_iso] Incremental complete: upserted={totals['upserted']:,} "
        f"rebuilds={totals['rebuilds']} appends={totals['appends']} noops={totals['noops']} "
        f"errors={totals['errors']} [time: {minutes}m {seconds:.1f}s]"
    )


# =============================================================================
# CLI
# =============================================================================

def main(argv: Sequence[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description="Build calendar-aligned ISO price bars into public.cmc_price_bars_multi_tf_cal_iso (append-only snapshots, incremental)."
    )
    ap.add_argument("--ids", nargs="+", required=True, help="'all' or list of ids (space/comma separated).")
    ap.add_argument("--db-url", default=None, help="Optional DB URL override. Defaults to TARGET_DB_URL env.")
    ap.add_argument("--daily-table", default=DEFAULT_DAILY_TABLE)
    ap.add_argument("--bars-table", default=DEFAULT_BARS_TABLE)
    ap.add_argument("--state-table", default=DEFAULT_STATE_TABLE)
    ap.add_argument("--tz", default=DEFAULT_TZ, help="Timezone for calendar alignment (default America/New_York).")
    ap.add_argument("--num-processes", type=int, default=6, help="Worker processes (default 6; capped to CPU count).")
    ap.add_argument("--full-rebuild", action="store_true", help="If set, delete+rebuild snapshots for all requested ids/tfs.")
    ap.add_argument("--parallel", action="store_true", help="(Legacy/no-op) Kept for pipeline compatibility")
    args = ap.parse_args(list(argv) if argv is not None else None)

    db_url = resolve_db_url(args.db_url)
    ids = parse_ids(args.ids)
    if ids == "all":
        ids = load_all_ids(db_url, args.daily_table)

    print(f"[bars_cal_iso] daily_table={args.daily_table}")
    print(f"[bars_cal_iso] bars_table={args.bars_table}")
    print(f"[bars_cal_iso] state_table={args.state_table}")

    if args.full_rebuild:
        start_time = time.time()
        specs = load_cal_specs_from_dim_timeframe(db_url)
        total_combinations = len(ids) * len(specs)
        running_total = 0
        combo_count = 0

        print(f"[bars_cal_iso] Full rebuild: {len(ids)} IDs × {len(specs)} TFs = {total_combinations:,} combinations")

        # Ensure state table exists (with tz column)
        ensure_state_table(db_url, args.state_table, with_tz=True)

        for id_ in ids:
            df_full = load_daily_prices_for_id(db_url=db_url, daily_table=args.daily_table, id_=int(id_))
            for spec in specs:
                combo_count += 1
                delete_bars_for_id_tf(db_url, args.bars_table, id_=int(id_), tf=spec.tf)
                bars = _build_snapshots_full_history_for_id_spec_polars(df_full, spec=spec, tz=args.tz)

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
                        f"[bars_cal_iso] ID={id_}, TF={spec.tf}, period={period_start} to {period_end}: "
                        f"upserted {num_rows:,} rows ({running_total:,} total, {pct:.1f}%) [elapsed: {elapsed:.1f}s]"
                    )

        total_time = time.time() - start_time
        minutes = int(total_time // 60)
        seconds = total_time % 60
        print(f"[bars_cal_iso] Full rebuild complete: {running_total:,} total rows [time: {minutes}m {seconds:.1f}s]")
        return

    refresh_incremental(
        db_url=db_url,
        ids=ids,
        tz=args.tz,
        daily_table=args.daily_table,
        bars_table=args.bars_table,
        state_table=args.state_table,
        num_processes=args.num_processes,
    )


if __name__ == "__main__":
    main()
