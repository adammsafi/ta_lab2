from __future__ import annotations

"""
# ======================================================================================
# refresh_cmc_price_bars_multi_tf_cal_anchor_us.py
#
# US calendar-ANCHORED price bars builder (append-only DAILY SNAPSHOTS):
#   public.cmc_price_bars_multi_tf_cal_anchor_us
# from daily source:
#   public.cmc_price_histories7
#
# Key semantics
# -------------
# - Timeframes sourced from public.dim_timeframe (no hard-coded TF list).
# - Bars emitted as APPEND-ONLY DAILY SNAPSHOTS per (id, tf, bar_seq, time_close).
# - Anchored windows are calendar-defined (NOT data-aligned):
#     * US weeks are Sunday..Saturday (close Saturday)
#     * N-week windows use REF_SUNDAY grid = 1970-01-04
#     * N-month windows are grouped within the year (quarters, half-years, etc.)
#     * N-year windows grouped deterministically
# - Partial bars allowed at BOTH ends for *_CAL_ANCHOR_* families:
#     * Partial START for the first intersecting window if data begins after window_start
#     * Partial END while window still forming OR if data ends mid-window
# - tf_days is the underlying window width (calendar days), regardless of partial start.
# - Missing-days detection is computed within [bar_start_effective .. snapshot_day].
#
# Columns written (must exist on bars table)
# ------------------------------------------
#   id, tf, tf_days, bar_seq,
#   time_open, time_close, time_high, time_low,
#   open, high, low, close, volume, market_cap,
#   ingested_at (default now() on insert; now() on conflict update),
#   is_partial_start, is_partial_end, is_missing_days,
#   count_days, count_days_remaining,
#   count_missing_days, count_missing_days_start, count_missing_days_end, count_missing_days_interior,
#   missing_days_where
#
# Notes on missing-days breakdown
# -------------------------------
# For the expected local-date range [bar_start_effective .. snapshot_day]:
# - count_missing_days_start:
#     number of missing days at the *beginning* of the expected range (contiguous run)
# - count_missing_days_end:
#     number of missing days at the *end* of the expected range (contiguous run)
#     (usually 0 because snapshot_day must exist to emit a row, but kept for symmetry)
# - count_missing_days_interior:
#     remaining missing days in the middle
# - missing_days_where:
#     comma-separated flags among: "start", "end", "interior" (or NULL if none)
# ======================================================================================
"""

import argparse
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Sequence

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


# =============================================================================
# CONFIG
# =============================================================================

DEFAULT_TZ = "America/New_York"
DEFAULT_DAILY_TABLE = "public.cmc_price_histories7"
DEFAULT_BARS_TABLE = "public.cmc_price_bars_multi_tf_cal_anchor_us"
DEFAULT_STATE_TABLE = "public.cmc_price_bars_multi_tf_cal_anchor_us_state"

# Global reference for anchored N-week grouping (Sunday)
REF_SUNDAY = date(1970, 1, 4)


# =============================================================================
# DB helpers
# =============================================================================

def resolve_db_url(db_url: str | None) -> str:
    if db_url and db_url.strip():
        print("[bars_anchor_us] Using DB URL from --db-url arg.")
        return db_url.strip()
    env_url = os.getenv("TARGET_DB_URL")
    if not env_url:
        raise SystemExit("No DB URL provided. Set TARGET_DB_URL env var or pass --db-url.")
    print("[bars_anchor_us] Using DB URL from TARGET_DB_URL env.")
    return env_url.strip()


def get_engine(db_url: str) -> Engine:
    return create_engine(db_url, future=True)


def load_all_ids(db_url: str, daily_table: str) -> list[int]:
    eng = get_engine(db_url)
    with eng.connect() as conn:
        rows = conn.execute(text(f"SELECT DISTINCT id FROM {daily_table} ORDER BY id;")).fetchall()
    return [int(r[0]) for r in rows]


def parse_ids(values: Sequence[str], db_url: str, daily_table: str) -> list[int]:
    if len(values) == 1 and values[0].strip().lower() == "all":
        ids = load_all_ids(db_url, daily_table)
        print(f"[bars_anchor_us] Loaded ALL ids from {daily_table}: {len(ids)}")
        return ids

    out: list[int] = []
    for v in values:
        for part in v.split(","):
            part = part.strip()
            if part:
                out.append(int(part))

    # dedupe keep order
    seen: set[int] = set()
    ids2: list[int] = []
    for x in out:
        if x not in seen:
            seen.add(x)
            ids2.append(x)
    return ids2


def ensure_state_table(db_url: str, state_table: str) -> None:
    eng = get_engine(db_url)
    ddl = f"""
    CREATE TABLE IF NOT EXISTS {state_table} (
      id               integer      NOT NULL,
      tf               text         NOT NULL,
      tz               text         NOT NULL,
      daily_min_seen   timestamptz  NULL,
      daily_max_seen   timestamptz  NULL,
      last_bar_seq     integer      NULL,
      last_time_close  timestamptz  NULL,
      updated_at       timestamptz  NOT NULL DEFAULT now(),
      PRIMARY KEY (id, tf)
    );
    """
    with eng.begin() as conn:
        conn.execute(text(ddl))


def load_state(db_url: str, state_table: str, ids: list[int]) -> pd.DataFrame:
    if not ids:
        return pd.DataFrame()

    sql = text(f"""
        SELECT id, tf, tz, daily_min_seen, daily_max_seen, last_bar_seq, last_time_close, updated_at
        FROM {state_table}
        WHERE id = ANY(:ids);
    """)

    eng = get_engine(db_url)
    with eng.connect() as conn:
        df = pd.read_sql(sql, conn, params={"ids": ids})

    if df.empty:
        return df

    df["daily_min_seen"] = pd.to_datetime(df["daily_min_seen"], utc=True)
    df["daily_max_seen"] = pd.to_datetime(df["daily_max_seen"], utc=True)
    df["last_time_close"] = pd.to_datetime(df["last_time_close"], utc=True)
    return df


def upsert_state(db_url: str, state_table: str, rows: list[dict]) -> None:
    if not rows:
        return
    sql = text(f"""
      INSERT INTO {state_table} (id, tf, tz, daily_min_seen, daily_max_seen, last_bar_seq, last_time_close, updated_at)
      VALUES (:id, :tf, :tz, :daily_min_seen, :daily_max_seen, :last_bar_seq, :last_time_close, now())
      ON CONFLICT (id, tf) DO UPDATE SET
        tz              = EXCLUDED.tz,
        daily_min_seen  = EXCLUDED.daily_min_seen,
        daily_max_seen  = EXCLUDED.daily_max_seen,
        last_bar_seq    = EXCLUDED.last_bar_seq,
        last_time_close = EXCLUDED.last_time_close,
        updated_at      = now();
    """)
    eng = get_engine(db_url)
    with eng.begin() as conn:
        conn.execute(sql, rows)


def load_daily_min_max(db_url: str, daily_table: str, ids: list[int]) -> pd.DataFrame:
    if not ids:
        return pd.DataFrame()
    sql = text(f"""
      SELECT id, MIN("timestamp") AS daily_min_ts, MAX("timestamp") AS daily_max_ts, COUNT(*) AS n_rows
      FROM {daily_table}
      WHERE id = ANY(:ids)
      GROUP BY id
      ORDER BY id;
    """)
    eng = get_engine(db_url)
    with eng.connect() as conn:
        df = pd.read_sql(sql, conn, params={"ids": ids})
    if df.empty:
        return df
    df["daily_min_ts"] = pd.to_datetime(df["daily_min_ts"], utc=True)
    df["daily_max_ts"] = pd.to_datetime(df["daily_max_ts"], utc=True)
    df["n_rows"] = df["n_rows"].astype(np.int64)
    return df


def load_daily_prices_for_id(
    *,
    db_url: str,
    daily_table: str,
    id_: int,
    ts_start: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """
    Load daily rows for a single id, optionally from ts_start onward.
    """
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

    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df["timehigh"] = pd.to_datetime(df["timehigh"], utc=True)
    df["timelow"] = pd.to_datetime(df["timelow"], utc=True)
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
    """
    Batch-load latest snapshot row for a single id across multiple tfs.
    Returns: { tf: {"last_bar_seq": int, "last_time_close": Timestamp(utc)} }
    """
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
    """
    Full latest snapshot row for a given (id, tf) (used for carry-forward).
    """
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
# dim_timeframe-driven TF specs
# =============================================================================

@dataclass(frozen=True)
class AnchorSpec:
    n: int
    unit: str  # "W" | "M" | "Y"
    tf: str


def load_anchor_specs_from_dim_timeframe(db_url: str) -> list[AnchorSpec]:
    """
    Load US anchored timeframes (partial bars allowed) from dim_timeframe.

    IMPORTANT FIX:
    - Weekly anchored TFs are US-specific and must have calendar_scheme='US'.
    - Month/Year anchored TFs in your dim_timeframe are often "US anchored" semantically
      but have calendar_scheme NULL/empty. We include those as long as they are:
        alignment_type='calendar', roll_policy='calendar_anchor', allow_partial_* = true,
        base_unit in ('M','Y')
      and we exclude ISO-labeled TF names to avoid pulling ISO variants.
    """
    sql = text("""
      SELECT tf, base_unit, tf_qty, sort_order
      FROM public.dim_timeframe
      WHERE alignment_type = 'calendar'
        AND roll_policy = 'calendar_anchor'
        AND allow_partial_start = TRUE
        AND allow_partial_end   = TRUE
        AND base_unit IN ('W','M','Y')
        AND (
              -- US weeks only
              (base_unit = 'W' AND calendar_scheme = 'US')
              OR
              -- Month/year anchored families: scheme is often NULL/blank in your table
              (base_unit IN ('M','Y') AND COALESCE(NULLIF(calendar_scheme,''), 'US') = 'US')
            )
        -- Safety: do not accidentally pull ISO variants into the US builder
        AND tf NOT ILIKE '%ISO%'
      ORDER BY sort_order, tf;
    """)
    eng = get_engine(db_url)
    with eng.connect() as conn:
        rows = conn.execute(sql).mappings().all()

    specs: list[AnchorSpec] = []
    for r in rows:
        specs.append(
            AnchorSpec(
                n=int(r["tf_qty"]),
                unit=str(r["base_unit"]),
                tf=str(r["tf"]),
            )
        )

    if not specs:
        raise RuntimeError(
            "No US anchored timeframes found in dim_timeframe for this builder. "
            "Expected: weekly base_unit='W' + calendar_scheme='US', and month/year anchored families."
        )
    return specs


# =============================================================================
# Calendar helpers (US week + anchored multi-period)
# =============================================================================

def _last_day_of_month(d: date) -> date:
    if d.month == 12:
        return date(d.year, 12, 31)
    return date(d.year, d.month + 1, 1) - timedelta(days=1)


def _add_months(month_start: date, months: int) -> date:
    y = month_start.year + (month_start.month - 1 + months) // 12
    m = (month_start.month - 1 + months) % 12 + 1
    return date(y, m, 1)


def _week_start_us_sunday(d: date) -> date:
    days_since_sun = (d.weekday() + 1) % 7
    return d - timedelta(days=days_since_sun)


def _week_index_us(d: date) -> int:
    ws = _week_start_us_sunday(d)
    return (ws - REF_SUNDAY).days // 7


def _week_group_bounds_us(d: date, n_weeks: int) -> tuple[date, date]:
    widx = _week_index_us(d)
    gidx = widx // n_weeks
    group_start = REF_SUNDAY + timedelta(days=7 * n_weeks * gidx)
    group_end = group_start + timedelta(days=7 * n_weeks - 1)  # ends Saturday
    return group_start, group_end


def _month_group_bounds_anchored(d: date, n_months: int) -> tuple[date, date]:
    g0 = ((d.month - 1) // n_months) * n_months + 1
    start = date(d.year, g0, 1)
    end_month_start = _add_months(start, n_months - 1)
    end = _last_day_of_month(end_month_start)
    return start, end


def _year_group_bounds_anchored(d: date, n_years: int) -> tuple[date, date]:
    start_year = d.year - ((d.year - 1) % n_years)
    start = date(start_year, 1, 1)
    end = date(start_year + n_years, 1, 1) - timedelta(days=1)
    return start, end


def anchor_window_for_day(d: date, spec: AnchorSpec) -> tuple[date, date]:
    if spec.unit == "W":
        return _week_group_bounds_us(d, spec.n)
    if spec.unit == "M":
        return _month_group_bounds_anchored(d, spec.n)
    if spec.unit == "Y":
        return _year_group_bounds_anchored(d, spec.n)
    raise ValueError(f"Unsupported unit: {spec.unit}")


def _months_diff(a: date, b: date) -> int:
    return (b.year - a.year) * 12 + (b.month - a.month)


def bar_seq_for_window_start(first_window_start: date, window_start: date, spec: AnchorSpec) -> int:
    """
    Deterministic 1-based bar_seq for a window, relative to the first produced anchored window.
    first_window_start should be the anchored window start containing the dataset's daily_min_day.
    """
    if window_start < first_window_start:
        raise ValueError("window_start is earlier than first_window_start; backfill should trigger rebuild")

    if spec.unit == "W":
        step = 7 * spec.n
        return (window_start - first_window_start).days // step + 1

    if spec.unit == "M":
        return _months_diff(first_window_start, window_start) // spec.n + 1

    if spec.unit == "Y":
        return (window_start.year - first_window_start.year) // spec.n + 1

    raise ValueError(f"Unsupported unit: {spec.unit}")


def _expected_days(window_start: date, window_end: date) -> int:
    return (window_end - window_start).days + 1


def _lookback_days_for_spec(spec: AnchorSpec) -> int:
    """
    Conservative lookback window (in local calendar days) to guarantee we can recompute
    aggregates from bar_start_effective when needed during incremental runs.
    """
    if spec.unit == "W":
        return int(7 * spec.n + 7)     # +1 week buffer
    if spec.unit == "M":
        return int(31 * spec.n + 10)   # generous + buffer
    if spec.unit == "Y":
        return int(366 * spec.n + 10)  # leap-safe + buffer
    return 400


# =============================================================================
# Snapshot bar building helpers
# =============================================================================

def _make_day_time_open(ts: pd.Series) -> pd.Series:
    one_ms = pd.Timedelta(milliseconds=1)
    out = ts.shift(1) + one_ms
    if len(ts) > 0:
        out.iloc[0] = ts.iloc[0] - pd.Timedelta(days=1) + one_ms
    return out


def _assert_one_row_per_local_day(df: pd.DataFrame, *, id_: int, tf: str, tz: str) -> None:
    if df.empty:
        return
    ts_local = df["ts"].dt.tz_convert(tz)
    day_date = ts_local.dt.date
    if day_date.duplicated().any():
        dups = day_date[day_date.duplicated()].astype(str).unique()[:10]
        raise ValueError(
            f"[bars_anchor_us] Duplicate local dates detected for id={id_}, tf={tf}, tz={tz}. "
            f"Examples={list(dups)}. This violates the 1-row-per-day assumption."
        )


def _missing_days_stats(
    *,
    bar_start_eff: date,
    snapshot_day: date,
    idx_by_day: dict[date, int],
    id_val: int,
    tf: str,
    win_start: date,
    win_end: date,
    fail_on_internal_gaps: bool,
) -> dict:
    """
    Compute missing-day counts for expected range [bar_start_eff .. snapshot_day].
    """
    exp_n = (snapshot_day - bar_start_eff).days + 1
    if exp_n <= 0:
        return {
            "count_days": 0,
            "count_missing_days": 0,
            "count_missing_days_start": 0,
            "count_missing_days_end": 0,
            "count_missing_days_interior": 0,
            "missing_days_where": None,
        }

    missing_positions: list[int] = []
    for k in range(exp_n):
        d = bar_start_eff + timedelta(days=k)
        if d not in idx_by_day:
            missing_positions.append(k)

    if missing_positions and fail_on_internal_gaps:
        raise ValueError(
            f"[bars_anchor_us] Missing daily row(s) inside snapshot range: "
            f"id={id_val}, tf={tf}, window={win_start}..{win_end}, agg={bar_start_eff}..{snapshot_day}."
        )

    m_total = len(missing_positions)
    if m_total == 0:
        return {
            "count_days": int(exp_n),
            "count_missing_days": 0,
            "count_missing_days_start": 0,
            "count_missing_days_end": 0,
            "count_missing_days_interior": 0,
            "missing_days_where": None,
        }

    missing_set = set(missing_positions)

    # start run
    s = 0
    while s < exp_n and s in missing_set:
        s += 1

    # end run
    e = 0
    while e < exp_n and (exp_n - 1 - e) in missing_set:
        e += 1

    if s + e > m_total:
        e = max(0, m_total - s)

    interior = max(0, m_total - s - e)

    flags: list[str] = []
    if s > 0:
        flags.append("start")
    if e > 0:
        flags.append("end")
    if interior > 0:
        flags.append("interior")

    return {
        "count_days": int(exp_n),
        "count_missing_days": int(m_total),
        "count_missing_days_start": int(s),
        "count_missing_days_end": int(e),
        "count_missing_days_interior": int(interior),
        "missing_days_where": ",".join(flags) if flags else None,
    }


def _count_days_remaining(win_start: date, win_end: date, snapshot_day: date) -> int:
    if snapshot_day >= win_end:
        return 0
    return int((win_end - snapshot_day).days)


def _build_snapshots_full_history_for_id_spec(
    df_id: pd.DataFrame,
    *,
    spec: AnchorSpec,
    tz: str,
    daily_min_day: date,
    fail_on_internal_gaps: bool,
) -> pd.DataFrame:
    if df_id.empty:
        return pd.DataFrame()

    df = df_id.sort_values("ts").reset_index(drop=True).copy()
    _assert_one_row_per_local_day(df, id_=int(df["id"].iloc[0]), tf=spec.tf, tz=tz)

    ts_local = df["ts"].dt.tz_convert(tz)
    df["day_date"] = ts_local.dt.date
    df["day_time_open"] = _make_day_time_open(df["ts"])

    first_day: date = df["day_date"].iloc[0]
    last_day: date = df["day_date"].iloc[-1]

    first_window_start, _ = anchor_window_for_day(daily_min_day, spec)
    idx_by_day = {d: i for i, d in enumerate(df["day_date"].tolist())}

    id_val = int(df["id"].iloc[0])
    rows: list[dict] = []

    cur_day = first_day
    while cur_day <= last_day:
        j = idx_by_day.get(cur_day)
        if j is None:
            cur_day = cur_day + timedelta(days=1)
            continue

        win_start, win_end = anchor_window_for_day(cur_day, spec)
        bar_seq = bar_seq_for_window_start(first_window_start, win_start, spec)
        tf_days = _expected_days(win_start, win_end)

        bar_start_eff = max(win_start, daily_min_day)
        is_partial_start = (bar_start_eff > win_start)
        is_partial_end = (cur_day < win_end)

        stats = _missing_days_stats(
            bar_start_eff=bar_start_eff,
            snapshot_day=cur_day,
            idx_by_day=idx_by_day,
            id_val=id_val,
            tf=spec.tf,
            win_start=win_start,
            win_end=win_end,
            fail_on_internal_gaps=fail_on_internal_gaps,
        )

        exp_to_date = stats["count_days"]
        idxs: list[int] = []
        missing_any = False
        for k in range(exp_to_date):
            d = bar_start_eff + timedelta(days=k)
            jj = idx_by_day.get(d)
            if jj is None:
                missing_any = True
                continue
            idxs.append(jj)

        if not idxs:
            cur_day = cur_day + timedelta(days=1)
            continue

        g = df.iloc[idxs]
        high_val = g["high"].max()
        low_val = g["low"].min()

        rows.append(
            {
                "id": id_val,
                "tf": spec.tf,
                "tf_days": int(tf_days),
                "bar_seq": int(bar_seq),
                "time_open": g["day_time_open"].iloc[0],
                "time_close": df.loc[j, "ts"],
                "time_high": g.loc[g["high"] == high_val, "timehigh"].iloc[0],
                "time_low": g.loc[g["low"] == low_val, "timelow"].iloc[0],
                "open": float(g["open"].iloc[0]) if pd.notna(g["open"].iloc[0]) else np.nan,
                "high": float(high_val) if pd.notna(high_val) else np.nan,
                "low": float(low_val) if pd.notna(low_val) else np.nan,
                "close": float(df.loc[j, "close"]) if pd.notna(df.loc[j, "close"]) else np.nan,
                "volume": float(g["volume"].sum(skipna=True)),
                "market_cap": float(df.loc[j, "market_cap"]) if pd.notna(df.loc[j, "market_cap"]) else np.nan,
                "is_partial_start": bool(is_partial_start),
                "is_partial_end": bool(is_partial_end),
                "is_missing_days": bool(missing_any),
                "count_days": int(stats["count_days"]),
                "count_days_remaining": int(_count_days_remaining(win_start, win_end, cur_day)),
                "count_missing_days": int(stats["count_missing_days"]),
                "count_missing_days_start": int(stats["count_missing_days_start"]),
                "count_missing_days_end": int(stats["count_missing_days_end"]),
                "count_missing_days_interior": int(stats["count_missing_days_interior"]),
                "missing_days_where": stats["missing_days_where"],
            }
        )

        cur_day = cur_day + timedelta(days=1)

    out = pd.DataFrame.from_records(rows)
    if out.empty:
        return out

    out["bar_seq"] = out["bar_seq"].astype(np.int32)
    out["tf_days"] = out["tf_days"].astype(np.int32)

    out["is_partial_start"] = out["is_partial_start"].astype(bool)
    out["is_partial_end"] = out["is_partial_end"].astype(bool)
    out["is_missing_days"] = out["is_missing_days"].astype(bool)

    out["count_days"] = out["count_days"].astype("Int32")
    out["count_days_remaining"] = out["count_days_remaining"].astype("Int32")
    out["count_missing_days"] = out["count_missing_days"].astype("Int32")
    out["count_missing_days_start"] = out["count_missing_days_start"].astype("Int32")
    out["count_missing_days_end"] = out["count_missing_days_end"].astype("Int32")
    out["count_missing_days_interior"] = out["count_missing_days_interior"].astype("Int32")
    return out


def _build_incremental_snapshots_for_id_spec(
    df_slice: pd.DataFrame,
    *,
    spec: AnchorSpec,
    tz: str,
    daily_min_day: date,
    first_window_start: date,
    start_day: date,
    end_day: date,
    last_snapshot_row: dict | None,
    fail_on_internal_gaps: bool,
) -> pd.DataFrame:
    if df_slice.empty or start_day > end_day:
        return pd.DataFrame()

    df = df_slice.sort_values("ts").reset_index(drop=True).copy()
    _assert_one_row_per_local_day(df, id_=int(df["id"].iloc[0]), tf=spec.tf, tz=tz)

    ts_local = df["ts"].dt.tz_convert(tz)
    df["day_date"] = ts_local.dt.date
    df["day_time_open"] = _make_day_time_open(df["ts"])

    df_by_date = {d: i for i, d in enumerate(df["day_date"].tolist())}

    id_val = int(df["id"].iloc[0])
    rows: list[dict] = []

    carry = None
    if last_snapshot_row is not None:
        last_close_local_day = pd.to_datetime(last_snapshot_row["time_close"], utc=True).tz_convert(tz).date()
        carry = {
            "bar_seq": int(last_snapshot_row["bar_seq"]) if last_snapshot_row.get("bar_seq") is not None else None,
            "time_open": pd.to_datetime(last_snapshot_row["time_open"], utc=True) if last_snapshot_row.get("time_open") is not None else None,
            "open": float(last_snapshot_row["open"]) if last_snapshot_row.get("open") is not None else np.nan,
            "high": float(last_snapshot_row["high"]) if last_snapshot_row.get("high") is not None else np.nan,
            "low": float(last_snapshot_row["low"]) if last_snapshot_row.get("low") is not None else np.nan,
            "volume": float(last_snapshot_row["volume"]) if last_snapshot_row.get("volume") is not None else 0.0,
            "time_high": pd.to_datetime(last_snapshot_row["time_high"], utc=True) if last_snapshot_row.get("time_high") is not None else pd.NaT,
            "time_low": pd.to_datetime(last_snapshot_row["time_low"], utc=True) if last_snapshot_row.get("time_low") is not None else pd.NaT,
            "is_missing_days": bool(last_snapshot_row.get("is_missing_days", False)),
            "count_days": int(last_snapshot_row.get("count_days") or 0),
            "count_missing_days": int(last_snapshot_row.get("count_missing_days") or 0),
            "count_missing_days_start": int(last_snapshot_row.get("count_missing_days_start") or 0),
            "count_missing_days_end": int(last_snapshot_row.get("count_missing_days_end") or 0),
            "count_missing_days_interior": int(last_snapshot_row.get("count_missing_days_interior") or 0),
            "missing_days_where": last_snapshot_row.get("missing_days_where"),
            "last_day": last_close_local_day,
        }

    cur_day = start_day
    while cur_day <= end_day:
        j = df_by_date.get(cur_day)
        if j is None:
            cur_day = cur_day + timedelta(days=1)
            continue

        win_start, win_end = anchor_window_for_day(cur_day, spec)
        bar_seq = bar_seq_for_window_start(first_window_start, win_start, spec)
        tf_days = _expected_days(win_start, win_end)

        bar_start_eff = max(win_start, daily_min_day)
        is_partial_start = (bar_start_eff > win_start)

        can_carry = (
            carry is not None
            and carry.get("bar_seq") == bar_seq
            and carry.get("last_day") == (cur_day - timedelta(days=1))
            and not bool(carry.get("is_missing_days", False))
        )

        if not can_carry:
            stats = _missing_days_stats(
                bar_start_eff=bar_start_eff,
                snapshot_day=cur_day,
                idx_by_day=df_by_date,
                id_val=id_val,
                tf=spec.tf,
                win_start=win_start,
                win_end=win_end,
                fail_on_internal_gaps=fail_on_internal_gaps,
            )

            exp_to_date = stats["count_days"]
            idxs: list[int] = []
            missing_any = False
            for k in range(exp_to_date):
                d = bar_start_eff + timedelta(days=k)
                jj = df_by_date.get(d)
                if jj is None:
                    missing_any = True
                    continue
                idxs.append(jj)

            if not idxs:
                cur_day = cur_day + timedelta(days=1)
                continue

            g = df.iloc[idxs]
            high_val = g["high"].max()
            low_val = g["low"].min()

            carry = {
                "bar_seq": bar_seq,
                "time_open": g["day_time_open"].iloc[0],
                "open": float(g["open"].iloc[0]) if pd.notna(g["open"].iloc[0]) else np.nan,
                "high": float(high_val) if pd.notna(high_val) else np.nan,
                "low": float(low_val) if pd.notna(low_val) else np.nan,
                "volume": float(g["volume"].sum(skipna=True)),
                "time_high": g.loc[g["high"] == high_val, "timehigh"].iloc[0],
                "time_low": g.loc[g["low"] == low_val, "timelow"].iloc[0],
                "is_missing_days": bool(missing_any),
                "count_days": int(stats["count_days"]),
                "count_missing_days": int(stats["count_missing_days"]),
                "count_missing_days_start": int(stats["count_missing_days_start"]),
                "count_missing_days_end": int(stats["count_missing_days_end"]),
                "count_missing_days_interior": int(stats["count_missing_days_interior"]),
                "missing_days_where": stats["missing_days_where"],
                "last_day": cur_day,
            }
        else:
            day_high = float(df.loc[j, "high"]) if pd.notna(df.loc[j, "high"]) else np.nan
            day_low = float(df.loc[j, "low"]) if pd.notna(df.loc[j, "low"]) else np.nan

            if pd.isna(carry["high"]) or (pd.notna(day_high) and day_high > carry["high"]):
                carry["high"] = day_high
                carry["time_high"] = df.loc[j, "timehigh"]

            if pd.isna(carry["low"]) or (pd.notna(day_low) and day_low < carry["low"]):
                carry["low"] = day_low
                carry["time_low"] = df.loc[j, "timelow"]

            carry["volume"] = float(carry["volume"]) + (float(df.loc[j, "volume"]) if pd.notna(df.loc[j, "volume"]) else 0.0)
            carry["last_day"] = cur_day

            carry["count_days"] = int(carry.get("count_days", 0)) + 1
            carry["count_missing_days"] = 0
            carry["count_missing_days_start"] = 0
            carry["count_missing_days_end"] = 0
            carry["count_missing_days_interior"] = 0
            carry["missing_days_where"] = None
            carry["is_missing_days"] = False

        is_partial_end = (cur_day < win_end)

        rows.append(
            {
                "id": id_val,
                "tf": spec.tf,
                "tf_days": int(tf_days),
                "bar_seq": int(bar_seq),
                "time_open": carry["time_open"],
                "time_close": df.loc[j, "ts"],
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
                "count_days_remaining": int(_count_days_remaining(win_start, win_end, cur_day)),
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

    out["is_partial_start"] = out["is_partial_start"].astype(bool)
    out["is_partial_end"] = out["is_partial_end"].astype(bool)
    out["is_missing_days"] = out["is_missing_days"].astype(bool)

    out["count_days"] = out["count_days"].astype("Int32")
    out["count_days_remaining"] = out["count_days_remaining"].astype("Int32")
    out["count_missing_days"] = out["count_missing_days"].astype("Int32")
    out["count_missing_days_start"] = out["count_missing_days_start"].astype("Int32")
    out["count_missing_days_end"] = out["count_missing_days_end"].astype("Int32")
    out["count_missing_days_interior"] = out["count_missing_days_interior"].astype("Int32")
    return out


# =============================================================================
# Upsert (append-only snapshots)
# =============================================================================

def upsert_bars(df_bars: pd.DataFrame, db_url: str, bars_table: str, batch_size: int = 25_000) -> None:
    if df_bars.empty:
        return

    upsert_sql = f"""
    INSERT INTO {bars_table} (
      id, tf, tf_days, bar_seq,
      time_open, time_close, time_high, time_low,
      open, high, low, close, volume, market_cap,
      is_partial_start, is_partial_end, is_missing_days,
      count_days, count_days_remaining,
      count_missing_days, count_missing_days_start, count_missing_days_end, count_missing_days_interior,
      missing_days_where
    )
    VALUES (
      :id, :tf, :tf_days, :bar_seq,
      :time_open, :time_close, :time_high, :time_low,
      :open, :high, :low, :close, :volume, :market_cap,
      :is_partial_start, :is_partial_end, :is_missing_days,
      :count_days, :count_days_remaining,
      :count_missing_days, :count_missing_days_start, :count_missing_days_end, :count_missing_days_interior,
      :missing_days_where
    )
    ON CONFLICT (id, tf, bar_seq, time_close) DO UPDATE SET
      tf_days                    = EXCLUDED.tf_days,
      time_open                  = EXCLUDED.time_open,
      time_high                  = EXCLUDED.time_high,
      time_low                   = EXCLUDED.time_low,
      open                       = EXCLUDED.open,
      high                       = EXCLUDED.high,
      low                        = EXCLUDED.low,
      close                      = EXCLUDED.close,
      volume                     = EXCLUDED.volume,
      market_cap                 = EXCLUDED.market_cap,
      is_partial_start           = EXCLUDED.is_partial_start,
      is_partial_end             = EXCLUDED.is_partial_end,
      is_missing_days            = EXCLUDED.is_missing_days,
      count_days                 = EXCLUDED.count_days,
      count_days_remaining       = EXCLUDED.count_days_remaining,
      count_missing_days         = EXCLUDED.count_missing_days,
      count_missing_days_start   = EXCLUDED.count_missing_days_start,
      count_missing_days_end     = EXCLUDED.count_missing_days_end,
      count_missing_days_interior= EXCLUDED.count_missing_days_interior,
      missing_days_where         = EXCLUDED.missing_days_where,
      ingested_at                = now();
    """

    eng = get_engine(db_url)
    payload = df_bars.to_dict(orient="records")

    with eng.begin() as conn:
        for i in range(0, len(payload), batch_size):
            conn.execute(text(upsert_sql), payload[i: i + batch_size])


# =============================================================================
# Incremental driver
# =============================================================================

def refresh_incremental(
    *,
    db_url: str,
    ids: list[int],
    tz: str,
    daily_table: str,
    bars_table: str,
    state_table: str,
    fail_on_internal_gaps: bool,
) -> None:
    ensure_state_table(db_url, state_table)

    specs = load_anchor_specs_from_dim_timeframe(db_url)
    tfs = [s.tf for s in specs]
    print(f"[bars_anchor_us] tz={tz}")
    print(f"[bars_anchor_us] specs size={len(specs)}: {tfs}")

    daily_mm = load_daily_min_max(db_url, daily_table, ids)
    if daily_mm.empty:
        print("[bars_anchor_us] No daily data found for requested ids.")
        return

    state_df = load_state(db_url, state_table, ids)
    state_map: dict[tuple[int, str], dict] = {}
    if not state_df.empty:
        for r in state_df.to_dict(orient="records"):
            state_map[(int(r["id"]), str(r["tf"]))] = r

    mm_map = {int(r["id"]): r for r in daily_mm.to_dict(orient="records")}

    state_updates: list[dict] = []
    total_upsert = 0
    total_rebuild = 0
    total_append = 0
    total_noop = 0
    total_errors = 0

    for id_ in ids:
        mm = mm_map.get(int(id_))
        if mm is None:
            continue

        daily_min_ts: pd.Timestamp = mm["daily_min_ts"]
        daily_max_ts: pd.Timestamp = mm["daily_max_ts"]
        daily_min_day: date = daily_min_ts.tz_convert(tz).date()
        daily_max_day: date = daily_max_ts.tz_convert(tz).date()

        last_snap_map = load_last_snapshot_info_for_id_tfs(db_url, bars_table, id_=int(id_), tfs=tfs)

        for spec in specs:
            try:
                key = (int(id_), spec.tf)
                st = state_map.get(key)
                last_snap = last_snap_map.get(spec.tf)

                daily_min_seen = (
                    pd.to_datetime(st["daily_min_seen"], utc=True)
                    if st is not None and pd.notna(st.get("daily_min_seen"))
                    else daily_min_ts
                )
                daily_max_seen = (
                    pd.to_datetime(st["daily_max_seen"], utc=True)
                    if st is not None and pd.notna(st.get("daily_max_seen"))
                    else daily_max_ts
                )

                first_window_start, _ = anchor_window_for_day(daily_min_day, spec)

                if st is None and last_snap is None:
                    df_full = load_daily_prices_for_id(db_url=db_url, daily_table=daily_table, id_=int(id_))
                    bars = _build_snapshots_full_history_for_id_spec(
                        df_full,
                        spec=spec,
                        tz=tz,
                        daily_min_day=daily_min_day,
                        fail_on_internal_gaps=fail_on_internal_gaps,
                    )
                    if not bars.empty:
                        upsert_bars(bars, db_url, bars_table)
                        total_upsert += len(bars)
                        total_rebuild += 1
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
                            "daily_min_seen": daily_min_ts,
                            "daily_max_seen": daily_max_ts,
                            "last_bar_seq": last_bar_seq,
                            "last_time_close": last_time_close,
                        }
                    )
                    continue

                if last_snap is None:
                    df_full = load_daily_prices_for_id(db_url=db_url, daily_table=daily_table, id_=int(id_))
                    bars = _build_snapshots_full_history_for_id_spec(
                        df_full,
                        spec=spec,
                        tz=tz,
                        daily_min_day=daily_min_day,
                        fail_on_internal_gaps=fail_on_internal_gaps,
                    )
                    if not bars.empty:
                        upsert_bars(bars, db_url, bars_table)
                        total_upsert += len(bars)
                        total_rebuild += 1
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
                            "daily_min_seen": daily_min_ts,
                            "daily_max_seen": daily_max_ts,
                            "last_bar_seq": last_bar_seq,
                            "last_time_close": last_time_close,
                        }
                    )
                    continue

                last_time_close: pd.Timestamp = last_snap["last_time_close"]
                last_bar_seq = int(last_snap["last_bar_seq"])

                if daily_min_ts < daily_min_seen:
                    print(
                        f"[bars_anchor_us] Backfill detected: id={id_}, tf={spec.tf}, "
                        f"daily_min moved earlier {daily_min_seen} -> {daily_min_ts}. Rebuilding id/tf."
                    )
                    delete_bars_for_id_tf(db_url, bars_table, id_=int(id_), tf=spec.tf)
                    df_full = load_daily_prices_for_id(db_url=db_url, daily_table=daily_table, id_=int(id_))
                    bars = _build_snapshots_full_history_for_id_spec(
                        df_full,
                        spec=spec,
                        tz=tz,
                        daily_min_day=daily_min_day,
                        fail_on_internal_gaps=fail_on_internal_gaps,
                    )
                    if not bars.empty:
                        upsert_bars(bars, db_url, bars_table)
                        total_upsert += len(bars)
                        last_bar_seq = int(bars["bar_seq"].max())
                        last_time_close = pd.to_datetime(bars["time_close"].max(), utc=True)
                    total_rebuild += 1

                    state_updates.append(
                        {
                            "id": int(id_),
                            "tf": spec.tf,
                            "tz": tz,
                            "daily_min_seen": daily_min_ts,
                            "daily_max_seen": daily_max_ts,
                            "last_bar_seq": last_bar_seq,
                            "last_time_close": last_time_close,
                        }
                    )
                    continue

                if daily_max_ts <= last_time_close:
                    total_noop += 1
                    state_updates.append(
                        {
                            "id": int(id_),
                            "tf": spec.tf,
                            "tz": tz,
                            "daily_min_seen": min(daily_min_seen, daily_min_ts),
                            "daily_max_seen": max(daily_max_seen, daily_max_ts),
                            "last_bar_seq": last_bar_seq,
                            "last_time_close": last_time_close,
                        }
                    )
                    continue

                start_day = last_time_close.tz_convert(tz).date() + timedelta(days=1)
                end_day = daily_max_day

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
                    total_noop += 1
                    state_updates.append(
                        {
                            "id": int(id_),
                            "tf": spec.tf,
                            "tz": tz,
                            "daily_min_seen": min(daily_min_seen, daily_min_ts),
                            "daily_max_seen": max(daily_max_seen, daily_max_ts),
                            "last_bar_seq": last_bar_seq,
                            "last_time_close": last_time_close,
                        }
                    )
                    continue

                last_row = load_last_snapshot_row(db_url, bars_table, id_=int(id_), tf=spec.tf)

                bars_new = _build_incremental_snapshots_for_id_spec(
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

                if not bars_new.empty:
                    upsert_bars(bars_new, db_url, bars_table)
                    total_upsert += len(bars_new)
                    total_append += 1
                    last_bar_seq2 = int(bars_new["bar_seq"].max())
                    last_time_close2 = pd.to_datetime(bars_new["time_close"].max(), utc=True)
                else:
                    last_bar_seq2 = last_bar_seq
                    last_time_close2 = last_time_close

                state_updates.append(
                    {
                        "id": int(id_),
                        "tf": spec.tf,
                        "tz": tz,
                        "daily_min_seen": min(daily_min_seen, daily_min_ts),
                        "daily_max_seen": max(daily_max_seen, daily_max_ts),
                        "last_bar_seq": last_bar_seq2,
                        "last_time_close": last_time_close2,
                    }
                )

            except Exception as e:
                total_errors += 1
                print(f"[bars_anchor_us] ERROR id={id_} tf={spec.tf}: {type(e).__name__}: {e}")

                last_keep = last_snap_map.get(spec.tf)
                state_updates.append(
                    {
                        "id": int(id_),
                        "tf": spec.tf,
                        "tz": tz,
                        "daily_min_seen": daily_min_ts if st is None else min(
                            pd.to_datetime(st["daily_min_seen"], utc=True) if pd.notna(st.get("daily_min_seen")) else daily_min_ts,
                            daily_min_ts,
                        ),
                        "daily_max_seen": daily_max_ts if st is None else max(
                            pd.to_datetime(st["daily_max_seen"], utc=True) if pd.notna(st.get("daily_max_seen")) else daily_max_ts,
                            daily_max_ts,
                        ),
                        "last_bar_seq": int(last_keep["last_bar_seq"]) if last_keep is not None else (st.get("last_bar_seq") if st is not None else None),
                        "last_time_close": pd.to_datetime(last_keep["last_time_close"], utc=True) if last_keep is not None else (
                            pd.to_datetime(st["last_time_close"], utc=True) if st is not None and pd.notna(st.get("last_time_close")) else None
                        ),
                    }
                )
                continue

    upsert_state(db_url, state_table, state_updates)
    print(
        f"[bars_anchor_us] Done. upserted_rows={total_upsert:,} "
        f"rebuilds={total_rebuild} appends={total_append} noops={total_noop} errors={total_errors}"
    )


# =============================================================================
# CLI
# =============================================================================

def main(argv: Sequence[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description="Build US calendar-anchored price bars with partial bars allowed (append-only daily snapshots, incremental)."
    )
    ap.add_argument("--ids", nargs="+", required=True, help="'all' or list of ids (space/comma separated).")
    ap.add_argument("--db-url", default=None, help="Optional DB URL override. Defaults to TARGET_DB_URL env.")
    ap.add_argument("--daily-table", default=DEFAULT_DAILY_TABLE)
    ap.add_argument("--bars-table", default=DEFAULT_BARS_TABLE)
    ap.add_argument("--state-table", default=DEFAULT_STATE_TABLE)
    ap.add_argument("--tz", default=DEFAULT_TZ)
    ap.add_argument(
        "--fail-on-internal-gaps",
        action="store_true",
        help="Fail if any daily row is missing inside a snapshot aggregation range (recommended).",
    )
    args = ap.parse_args(list(argv) if argv is not None else None)

    db_url = resolve_db_url(args.db_url)
    ids = parse_ids(args.ids, db_url, args.daily_table)

    print(f"[bars_anchor_us] daily_table={args.daily_table}")
    print(f"[bars_anchor_us] bars_table={args.bars_table}")
    print(f"[bars_anchor_us] state_table={args.state_table}")

    refresh_incremental(
        db_url=db_url,
        ids=ids,
        tz=args.tz,
        daily_table=args.daily_table,
        bars_table=args.bars_table,
        state_table=args.state_table,
        fail_on_internal_gaps=args.fail_on_internal_gaps,
    )


if __name__ == "__main__":
    main()
