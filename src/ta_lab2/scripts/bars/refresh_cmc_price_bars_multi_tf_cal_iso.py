from __future__ import annotations

"""
Calendar-aligned ISO price bars builder: public.cmc_price_bars_multi_tf_cal_iso
from public.cmc_price_histories7 (daily).

UPDATED (Append-only daily snapshots + incremental + dim_timeframe-driven):

- Timeframes loaded from public.dim_timeframe (no hardcoded TF list).
- Append-only snapshots:
    For each (id, tf, bar_seq), emit one row per day while the calendar bar is forming.
    Same bar_seq will appear multiple times with different time_close.
    is_partial_end = TRUE for in-progress snapshots; FALSE only on the scheduled final day.
- Full-period start policy preserved:
    First bar for each (id, tf) starts at the first FULL period boundary AFTER data begins.
    Partial-start bars are never emitted; is_partial_start is always FALSE in this module.
- Missing-days detection:
    is_missing_days = TRUE if any expected local dates in [bar_start, snapshot_day] are missing.
    Once TRUE within a bar, it remains TRUE for subsequent snapshots in that bar.
- Missing-days counters (NEW):
    count_days
    count_days_remaining
    count_missing_days + start/end/interior breakdown
    missing_days_where
- Incremental refresh:
    - Backfill-aware: if daily_min moves earlier than state, rebuild (id, tf) fully.
    - Forward: append new snapshot rows for new daily closes after the latest snapshot time_close.
- State table:
    public.cmc_price_bars_multi_tf_cal_iso_state stores per (id, tf):
      tz, daily_min_seen, daily_max_seen, last_bar_seq, last_time_close, updated_at

IMPORTANT TABLE KEYING:
- Bars table must allow multiple rows per (id, tf, bar_seq).
- Recommended PK / unique key: (id, tf, bar_seq, time_close)
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
DEFAULT_BARS_TABLE = "public.cmc_price_bars_multi_tf_cal_iso"
DEFAULT_STATE_TABLE = "public.cmc_price_bars_multi_tf_cal_iso_state"


# =============================================================================
# DB helpers
# =============================================================================

def resolve_db_url(db_url: str | None) -> str:
    if db_url and db_url.strip():
        print("[bars_cal_iso] Using DB URL from --db-url arg.")
        return db_url.strip()

    env_url = os.getenv("TARGET_DB_URL")
    if not env_url:
        raise SystemExit("No DB URL provided. Set TARGET_DB_URL env var or pass --db-url.")
    print("[bars_cal_iso] Using DB URL from TARGET_DB_URL env.")
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
        print(f"[bars_cal_iso] Loaded ALL ids from {daily_table}: {len(ids)}")
        return ids

    out: list[int] = []
    for v in values:
        parts = [p.strip() for p in v.split(",") if p.strip()]
        out.extend(int(p) for p in parts)

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
    Full latest snapshot row (needed for incremental aggregate carry-forward).
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
# dim_timeframe-driven TF specs (ISO)
# =============================================================================

@dataclass(frozen=True)
class CalIsoSpec:
    n: int
    unit: str  # 'W','M','Y'
    tf: str


def load_cal_specs_from_dim_timeframe(db_url: str):
    """
    Load calendar-aligned, FULL-PERIOD (non-anchor) ISO timeframes.

    dim_timeframe.calendar_anchor is boolean:
      - FALSE => CAL (non-anchor)
      - TRUE  => CAL_ANCHOR
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
              -- ISO weeks: e.g. 1W_CAL_ISO, 2W_CAL_ISO, ...
              (base_unit = 'W' AND tf ~ '_CAL_ISO$')
              OR
              -- Scheme-agnostic months/years: e.g. 1M_CAL, 2M_CAL, 1Y_CAL, ...
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

    specs = []
    for r in rows:
        specs.append(
            CalSpec(
                n=int(r["tf_qty"]),
                unit=str(r["base_unit"]),
                tf=str(r["tf"]),
            )
        )
    return specs


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
    # ISO week: Monday..Sunday
    return d - timedelta(days=d.weekday())


def _compute_anchor_start(first_day: date, unit: str) -> date:
    """
    First FULL period start AFTER the data begins (full-period policy).
    """
    if unit == "W":
        ws = _week_start_monday(first_day)
        if first_day == ws:
            return ws
        return ws + timedelta(days=7)

    if unit == "M":
        ms = _month_start(first_day)
        if first_day == ms:
            return ms
        return _add_months(ms, 1)

    if unit == "Y":
        ys = _year_start(first_day)
        if first_day == ys:
            return ys
        return date(first_day.year + 1, 1, 1)

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
    """months from a -> b (a and b assumed at first-of-month boundaries)"""
    return (b.year - a.year) * 12 + (b.month - a.month)


def _bar_index_for_day(anchor_start: date, d: date, n: int, unit: str) -> int:
    """
    0-based bar index within this spec, anchored at anchor_start.
    anchor_start MUST be aligned to the unit boundary for this spec.
    """
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


def _bar_start_for_index(anchor_start: date, idx: int, n: int, unit: str) -> date:
    if unit == "W":
        return anchor_start + timedelta(days=7 * n * idx)
    if unit == "M":
        return _add_months(anchor_start, n * idx)
    if unit == "Y":
        return date(anchor_start.year + n * idx, 1, 1)
    raise ValueError(f"Unsupported unit: {unit}")


# =============================================================================
# Missing-days diagnostics helpers (NEW)
# =============================================================================

def _missing_days_metrics(
    *,
    bar_start: date,
    snap_day: date,
    avail_dates: set[date],
    max_list: int = 200,
) -> dict:
    """
    Compute missing-day diagnostics for expected local dates in [bar_start, snap_day].

    Notes:
      - snap_day SHOULD be present in avail_dates (caller skips missing snapshot days).
      - 'end' run will be 0 when snap_day exists; computed generically anyway.
    """
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

    # start-run missing
    start_run = 0
    for k in range(exp_to_date):
        d = bar_start + timedelta(days=k)
        if d in avail_dates:
            break
        start_run += 1

    # end-run missing
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


# =============================================================================
# Bar building helpers
# =============================================================================

def _make_day_time_open(ts: pd.Series) -> pd.Series:
    one_ms = pd.Timedelta(milliseconds=1)
    day_open = ts.shift(1) + one_ms
    if len(ts) > 0:
        day_open.iloc[0] = ts.iloc[0] - pd.Timedelta(days=1) + one_ms
    return day_open


def _assert_one_row_per_local_day(df: pd.DataFrame, *, id_: int, tf: str, tz: str) -> None:
    if df.empty:
        return
    ts_local = df["ts"].dt.tz_convert(tz)
    day_date = ts_local.dt.date
    if day_date.duplicated().any():
        dups = day_date[day_date.duplicated()].astype(str).unique()[:10]
        raise ValueError(
            f"[bars_cal_iso] Duplicate local dates detected for id={id_}, tf={tf}, tz={tz}. "
            f"Examples={list(dups)}. This violates the 1-row-per-day assumption."
        )


def _build_snapshots_full_history_for_id_spec(df_id: pd.DataFrame, *, spec: CalIsoSpec, tz: str) -> pd.DataFrame:
    """
    Full rebuild: emit one snapshot row per day from anchor_start onward.
    """
    if df_id.empty:
        return pd.DataFrame()

    df = df_id.sort_values("ts").reset_index(drop=True).copy()
    _assert_one_row_per_local_day(df, id_=int(df["id"].iloc[0]), tf=spec.tf, tz=tz)

    ts_local = df["ts"].dt.tz_convert(tz)
    df["day_date"] = ts_local.dt.date

    first_day: date = df["day_date"].iloc[0]
    last_day: date = df["day_date"].iloc[-1]

    anchor_start = _compute_anchor_start(first_day, spec.unit)

    df = df[df["day_date"] >= anchor_start].copy()
    if df.empty:
        return pd.DataFrame()

    # CRITICAL: reset index AFTER filtering so df.loc[j, ...] works with j from enumerate(...)
    df = df.reset_index(drop=True)

    df["day_time_open"] = _make_day_time_open(df["ts"])

    # Map local day -> row index (aligned with df index labels 0..n-1)
    df_by_date = {d: i for i, d in enumerate(df["day_date"].tolist())}
    avail_dates = set(df_by_date.keys())

    id_val = int(df["id"].iloc[0])
    rows: list[dict] = []

    cur_day = anchor_start
    while cur_day <= last_day:
        bar_idx = _bar_index_for_day(anchor_start, cur_day, spec.n, spec.unit)
        bar_start = _bar_start_for_index(anchor_start, bar_idx, spec.n, spec.unit)
        bar_end = _bar_end_for_start(bar_start, spec.n, spec.unit)
        bar_seq = bar_idx + 1
        tf_days = _expected_days(bar_start, bar_end)

        j = df_by_date.get(cur_day)
        if j is None:
            # missing daily row; skip emitting this day
            cur_day = cur_day + timedelta(days=1)
            continue

        m = _missing_days_metrics(bar_start=bar_start, snap_day=cur_day, avail_dates=avail_dates)
        count_days_remaining = int(tf_days - m["exp_to_date"])
        is_missing_days = (m["count_missing_days"] > 0)

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

        is_partial_end = (cur_day < bar_end)
        is_partial_start = False  # full-period start policy

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
                "is_missing_days": bool(is_missing_days),
                "count_days": int(m["count_days"]),
                "count_days_remaining": int(count_days_remaining),
                "count_missing_days": int(m["count_missing_days"]),
                "count_missing_days_start": int(m["count_missing_days_start"]),
                "count_missing_days_end": int(m["count_missing_days_end"]),
                "count_missing_days_interior": int(m["count_missing_days_interior"]),
                "missing_days_where": m["missing_days_where"],
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
    """
    Incremental: emit snapshot rows for local days in [start_day, end_day], inclusive.

    Uses last_snapshot_row to carry forward aggregates within the current bar where possible,
    but still safely recomputes from bar_start when we cross a bar boundary (or if we can't carry).

    IMPORTANT:
    - We carry forward `is_missing_days` from the last snapshot row so that if a bar has already
      been flagged missing-days in prior runs, it remains flagged for subsequent snapshots in
      that same bar after a restart.
    """
    if df_slice.empty or start_day > end_day:
        return pd.DataFrame()

    df = df_slice.sort_values("ts").reset_index(drop=True).copy()
    _assert_one_row_per_local_day(df, id_=int(df["id"].iloc[0]), tf=spec.tf, tz=tz)

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
            # missing daily row; skip emitting this day
            cur_day = cur_day + timedelta(days=1)
            continue

        bar_idx = _bar_index_for_day(anchor_start, cur_day, spec.n, spec.unit)
        bar_start = _bar_start_for_index(anchor_start, bar_idx, spec.n, spec.unit)
        bar_end = _bar_end_for_start(bar_start, spec.n, spec.unit)
        bar_seq = bar_idx + 1
        tf_days = _expected_days(bar_start, bar_end)

        # carry-forward only if same bar_seq AND last emitted day is yesterday
        can_carry = (
            carry is not None
            and carry.get("bar_seq") == bar_seq
            and carry.get("last_day") is not None
            and carry["last_day"] == (cur_day - timedelta(days=1))
        )

        # missing-day metrics (always recompute for the expanding window)
        m = _missing_days_metrics(bar_start=bar_start, snap_day=cur_day, avail_dates=avail_dates)
        count_days_remaining = int(tf_days - m["exp_to_date"])
        is_missing_days_today = (m["count_missing_days"] > 0)

        if not can_carry:
            # recompute aggregates from bar_start -> cur_day
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
            time_high = g.loc[g["high"] == high_val, "timehigh"].iloc[0]
            time_low = g.loc[g["low"] == low_val, "timelow"].iloc[0]

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
            # update carry with today's daily row only
            carry["is_missing_days"] = bool(carry.get("is_missing_days", False) or is_missing_days_today)

            day_high = float(df.loc[j, "high"]) if pd.notna(df.loc[j, "high"]) else np.nan
            day_low = float(df.loc[j, "low"]) if pd.notna(df.loc[j, "low"]) else np.nan

            if pd.isna(carry["high"]) or (pd.notna(day_high) and day_high > carry["high"]):
                carry["high"] = day_high
                carry["time_high"] = df.loc[j, "timehigh"]

            if pd.isna(carry["low"]) or (pd.notna(day_low) and day_low < carry["low"]):
                carry["low"] = day_low
                carry["time_low"] = df.loc[j, "timelow"]

            carry["volume"] = float(carry["volume"]) + (
                float(df.loc[j, "volume"]) if pd.notna(df.loc[j, "volume"]) else 0.0
            )
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
            conn.execute(text(upsert_sql), payload[i : i + batch_size])


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
) -> None:
    ensure_state_table(db_url, state_table)

    specs = load_cal_iso_specs_from_dim_timeframe(db_url)
    tfs = [s.tf for s in specs]
    print(f"[bars_cal_iso] tz={tz}")
    print(f"[bars_cal_iso] specs size={len(specs)}: {tfs}")

    daily_mm = load_daily_min_max(db_url, daily_table, ids)
    if daily_mm.empty:
        print("[bars_cal_iso] No daily data found for requested ids.")
        return

    state_df = load_state(db_url, state_table, ids)
    state_map: dict[tuple[int, str], dict] = {}
    if not state_df.empty:
        for r in state_df.to_dict(orient="records"):
            state_map[(int(r["id"]), str(r["tf"]))] = r

    state_updates: list[dict] = []
    total_upsert = 0
    total_rebuild = 0
    total_append = 0
    total_noop = 0
    total_errors = 0

    mm_map = {int(r["id"]): r for r in daily_mm.to_dict(orient="records")}

    for id_ in ids:
        mm = mm_map.get(int(id_))
        if mm is None:
            continue

        daily_min_ts: pd.Timestamp = mm["daily_min_ts"]
        daily_max_ts: pd.Timestamp = mm["daily_max_ts"]
        daily_max_day: date = daily_max_ts.tz_convert(tz).date()

        last_snap_map = load_last_snapshot_info_for_id_tfs(db_url, bars_table, id_=int(id_), tfs=tfs)

        for spec in specs:
            st = None
            daily_min_seen = daily_min_ts
            daily_max_seen = daily_max_ts
            try:
                key = (int(id_), spec.tf)
                st = state_map.get(key)
                last_snap = last_snap_map.get(spec.tf)

                # NaN-safe state hydration
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

                # if neither state nor table exists: full build
                if st is None and last_snap is None:
                    df_full = load_daily_prices_for_id(db_url=db_url, daily_table=daily_table, id_=int(id_))
                    bars = _build_snapshots_full_history_for_id_spec(df_full, spec=spec, tz=tz)
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

                # if state exists but table missing: rebuild
                if last_snap is None:
                    df_full = load_daily_prices_for_id(db_url=db_url, daily_table=daily_table, id_=int(id_))
                    bars = _build_snapshots_full_history_for_id_spec(df_full, spec=spec, tz=tz)
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

                # backfill detection
                if daily_min_ts < daily_min_seen:
                    print(
                        f"[bars_cal_iso] Backfill detected: id={id_}, tf={spec.tf}, "
                        f"daily_min moved earlier {daily_min_seen} -> {daily_min_ts}. Rebuilding id/tf."
                    )
                    delete_bars_for_id_tf(db_url, bars_table, id_=int(id_), tf=spec.tf)
                    df_full = load_daily_prices_for_id(db_url=db_url, daily_table=daily_table, id_=int(id_))
                    bars = _build_snapshots_full_history_for_id_spec(df_full, spec=spec, tz=tz)
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

                # forward check
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

                # compute anchor_start for this id/spec (depends on first day of full history)
                df_head = load_daily_prices_for_id(db_url=db_url, daily_table=daily_table, id_=int(id_))
                if df_head.empty:
                    total_noop += 1
                    continue
                first_day = df_head["ts"].min().tz_convert(tz).date()
                anchor_start = _compute_anchor_start(first_day, spec.unit)

                # build snapshots from next local day after last snapshot close to the latest daily day
                start_day = last_time_close.tz_convert(tz).date() + timedelta(days=1)
                end_day = daily_max_day
                if start_day > end_day:
                    total_noop += 1
                    continue

                # load slice back so we can recompute across bar boundaries safely
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
                    total_noop += 1
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

                upsert_bars(new_rows, db_url, bars_table)
                total_upsert += len(new_rows)
                total_append += 1

                last_bar_seq2 = int(new_rows["bar_seq"].max())
                last_time_close2 = pd.to_datetime(new_rows["time_close"].max(), utc=True)

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
                print(f"[bars_cal_iso] ERROR id={id_} tf={spec.tf}: {type(e).__name__}: {e}")
                # keep state updated for min/max only; do not advance last_* on error
                state_updates.append(
                    {
                        "id": int(id_),
                        "tf": spec.tf,
                        "tz": tz,
                        "daily_min_seen": daily_min_ts if st is None else min(daily_min_seen, daily_min_ts),
                        "daily_max_seen": daily_max_ts if st is None else max(daily_max_seen, daily_max_ts),
                        "last_bar_seq": (st.get("last_bar_seq") if st is not None else None),
                        "last_time_close": (
                            pd.to_datetime(st["last_time_close"], utc=True)
                            if st is not None and pd.notna(st.get("last_time_close"))
                            else None
                        ),
                    }
                )
                continue

    upsert_state(db_url, state_table, state_updates)
    print(
        f"[bars_cal_iso] Done. upserted_rows={total_upsert:,} "
        f"rebuilds={total_rebuild} appends={total_append} noops={total_noop} errors={total_errors}"
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
    ap.add_argument("--full-rebuild", action="store_true", help="If set, delete+rebuild snapshots for all requested ids/tfs.")
    args = ap.parse_args(list(argv) if argv is not None else None)

    db_url = resolve_db_url(args.db_url)
    ids = parse_ids(args.ids, db_url, args.daily_table)

    print(f"[bars_cal_iso] daily_table={args.daily_table}")
    print(f"[bars_cal_iso] bars_table={args.bars_table}")
    print(f"[bars_cal_iso] state_table={args.state_table}")

    if args.full_rebuild:
        specs = load_cal_iso_specs_from_dim_timeframe(db_url)
        for id_ in ids:
            df_full = load_daily_prices_for_id(db_url=db_url, daily_table=args.daily_table, id_=int(id_))
            for spec in specs:
                delete_bars_for_id_tf(db_url, args.bars_table, id_=int(id_), tf=spec.tf)
                bars = _build_snapshots_full_history_for_id_spec(df_full, spec=spec, tz=args.tz)
                if not bars.empty:
                    upsert_bars(bars, db_url, args.bars_table)
        return

    refresh_incremental(
        db_url=db_url,
        ids=ids,
        tz=args.tz,
        daily_table=args.daily_table,
        bars_table=args.bars_table,
        state_table=args.state_table,
    )


if __name__ == "__main__":
    main()
