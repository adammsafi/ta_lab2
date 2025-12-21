from __future__ import annotations

"""
ISO calendar-ANCHORED price bars builder (INCREMENTAL) with PARTIAL bars allowed.

Target table:
  public.cmc_price_bars_multi_tf_cal_anchor_iso

Source table:
  public.cmc_price_histories7  (daily)

This updates the previous full-rebuild implementation to match the incremental
patterns used by _multi_tf and the two _cal scripts:

Key behavior
------------
1) Timeframes are loaded from public.dim_timeframe (no hardcoded TF list):
   - alignment_type      = 'calendar'
   - calendar_scheme     = 'ISO'
   - allow_partial_start = TRUE
   - allow_partial_end   = TRUE
   - base_unit in ('W','M','Y')
   - tf_qty is the unit multiple (e.g., 2W, 3M, 1Y)
   - tf is the label (e.g., '2W_ISO_ANCHOR', '6M_ISO_ANCHOR')

2) Incremental refresh (per id, tf):
   - Backfill-aware: if daily_min decreases vs daily_min_seen -> REBUILD FULL id/tf.
     (Because bar_seq is generated from the first anchored window that intersects the
      first available day; adding earlier data adds bars at the front and shifts seq.)
   - Forward updates:
       * If new daily data arrives within the CURRENT last anchored window, we
         recompute (upsert) the LAST bar (same bar_seq).
       * If new data extends into new windows, we recompute last bar and append
         new bars after it.
     Implementation: delete bars with bar_seq >= last_bar_seq, then rebuild from the
     anchored window that contains last_time_close through the new last day.

3) State table:
   public.cmc_price_bars_multi_tf_cal_anchor_iso_state stores per (id, tf):
     - tz
     - daily_min_seen, daily_max_seen
     - last_bar_seq, last_time_close
     - updated_at

Anchored semantics (fixed endpoints, NOT data-aligned):
- Weeks: ISO weeks Monday..Sunday. Close is Sunday.
- n-Week: grouped on a global ISO-week grid (ref Monday = 1970-01-05), so boundaries are fixed.
- Months: month windows (calendar anchored).
- 3M: quarter windows (Jan-Mar, Apr-Jun, ...)
- 6M: half-year windows (Jan-Jun, Jul-Dec)
- 12M/1Y: calendar-year windows.

Partial bars allowed:
- If data starts mid-window, the first bar is partial (starts at first available day).
- If data ends mid-window, the last bar is partial (ends at last available day).
- Internal missing days inside a bar intersection raise an error by default
  (can be disabled with --fail-on-internal-gaps = false).

Continuity invariant:
- Synthetic day_time_open[t] = lag(ts) + 1ms
- bar.time_open = first(day_time_open) within the bar
- bar.time_close = last(ts) within the bar
- Enforce: next_bar.time_open == prev_bar.time_close + 1ms (per id, tf)
"""

import argparse
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Iterable, Sequence

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


# =============================================================================
# CONFIG
# =============================================================================

DEFAULT_TZ = "America/New_York"
DEFAULT_DAILY_TABLE = "public.cmc_price_histories7"
DEFAULT_BARS_TABLE = "public.cmc_price_bars_multi_tf_cal_anchor_iso"
DEFAULT_STATE_TABLE = "public.cmc_price_bars_multi_tf_cal_anchor_iso_state"

# Global reference for anchored N-week grouping (ISO Monday)
REF_MONDAY_ISO = date(1970, 1, 5)


# =============================================================================
# DB helpers
# =============================================================================

def resolve_db_url(db_url: str | None) -> str:
    if db_url and db_url.strip():
        print("[bars_anchor_iso] Using DB URL from --db-url arg.")
        return db_url.strip()

    env_url = os.getenv("TARGET_DB_URL")
    if not env_url:
        raise SystemExit("No DB URL provided. Set TARGET_DB_URL env var or pass --db-url.")
    print("[bars_anchor_iso] Using DB URL from TARGET_DB_URL env.")
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
        print(f"[bars_anchor_iso] Loaded ALL ids from {daily_table}: {len(ids)}")
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
        tz             = EXCLUDED.tz,
        daily_min_seen = EXCLUDED.daily_min_seen,
        daily_max_seen = EXCLUDED.daily_max_seen,
        last_bar_seq   = EXCLUDED.last_bar_seq,
        last_time_close= EXCLUDED.last_time_close,
        updated_at     = now();
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


def load_last_bar_info_for_id_tfs(
    db_url: str,
    bars_table: str,
    id_: int,
    tfs: list[str],
) -> dict[str, dict]:
    if not tfs:
        return {}

    sql = text(f"""
      SELECT DISTINCT ON (tf)
        tf,
        bar_seq AS last_bar_seq,
        time_close AS last_time_close
      FROM {bars_table}
      WHERE id = :id AND tf = ANY(:tfs)
      ORDER BY tf, bar_seq DESC;
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


def load_time_close_for_bar_seq(db_url: str, bars_table: str, id_: int, tf: str, bar_seq: int) -> pd.Timestamp | None:
    sql = text(f"""
      SELECT time_close
      FROM {bars_table}
      WHERE id = :id AND tf = :tf AND bar_seq = :bar_seq
      LIMIT 1;
    """)
    eng = get_engine(db_url)
    with eng.connect() as conn:
        row = conn.execute(sql, {"id": int(id_), "tf": tf, "bar_seq": int(bar_seq)}).first()
    if row is None or row[0] is None:
        return None
    return pd.to_datetime(row[0], utc=True)


def delete_bars_for_id_tf(db_url: str, bars_table: str, id_: int, tf: str) -> None:
    sql = text(f"DELETE FROM {bars_table} WHERE id = :id AND tf = :tf;")
    eng = get_engine(db_url)
    with eng.begin() as conn:
        conn.execute(sql, {"id": int(id_), "tf": tf})


def delete_bars_for_id_tf_from_seq(db_url: str, bars_table: str, id_: int, tf: str, bar_seq_from: int) -> None:
    sql = text(f"DELETE FROM {bars_table} WHERE id = :id AND tf = :tf AND bar_seq >= :bar_seq_from;")
    eng = get_engine(db_url)
    with eng.begin() as conn:
        conn.execute(sql, {"id": int(id_), "tf": tf, "bar_seq_from": int(bar_seq_from)})


# =============================================================================
# dim_timeframe-driven Anchor specs
# =============================================================================

@dataclass(frozen=True)
class AnchorSpec:
    n: int
    unit: str  # 'W','M','Y'
    tf: str


def load_anchor_specs_from_dim_timeframe(db_url: str) -> list[AnchorSpec]:
    """
    Load ISO anchored timeframes (partial start/end allowed) from dim_timeframe.

    Expected conventions:
      - alignment_type      = 'calendar'
      - calendar_scheme     = 'ISO'
      - allow_partial_start = TRUE
      - allow_partial_end   = TRUE
      - base_unit in ('W','M','Y')
      - tf_qty is integer multiple
      - tf is label to emit (e.g. '2W_ISO_ANCHOR', '6M_ISO_ANCHOR', '1Y_ISO_ANCHOR')
    """
    sql = text("""
      SELECT tf, base_unit, tf_qty, sort_order
      FROM public.dim_timeframe
      WHERE alignment_type = 'calendar'
        AND calendar_scheme = 'ISO'
        AND allow_partial_start = TRUE
        AND allow_partial_end   = TRUE
        AND base_unit IN ('W','M','Y')
      ORDER BY sort_order, tf;
    """)
    eng = get_engine(db_url)
    with eng.connect() as conn:
        rows = conn.execute(sql).mappings().all()

    specs: list[AnchorSpec] = []
    for r in rows:
        specs.append(AnchorSpec(n=int(r["tf_qty"]), unit=str(r["base_unit"]), tf=str(r["tf"])))

    if not specs:
        raise RuntimeError(
            "No ISO anchored (partial allowed) timeframes found in dim_timeframe "
            "(alignment_type='calendar', calendar_scheme='ISO', allow_partial_* = true)."
        )
    return specs


# =============================================================================
# Calendar helpers (ISO anchored windows)
# =============================================================================

def _last_day_of_month(d: date) -> date:
    if d.month == 12:
        return date(d.year, 12, 31)
    return date(d.year, d.month + 1, 1) - timedelta(days=1)


def _month_start(d: date) -> date:
    return date(d.year, d.month, 1)


def _add_months(month_start: date, months: int) -> date:
    y = month_start.year + (month_start.month - 1 + months) // 12
    m = (month_start.month - 1 + months) % 12 + 1
    return date(y, m, 1)


def _week_start_iso_monday(d: date) -> date:
    # ISO week: Monday..Sunday
    return d - timedelta(days=d.weekday())


def _week_index_iso(d: date) -> int:
    ws = _week_start_iso_monday(d)
    return (ws - REF_MONDAY_ISO).days // 7


def _week_group_bounds_iso(d: date, n_weeks: int) -> tuple[date, date]:
    widx = _week_index_iso(d)
    gidx = widx // n_weeks
    group_start = REF_MONDAY_ISO + timedelta(days=7 * n_weeks * gidx)
    group_end = group_start + timedelta(days=7 * n_weeks - 1)  # ends Sunday
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


def _bounds_for_date(d: date, spec: AnchorSpec) -> tuple[date, date]:
    if spec.unit == "W":
        return _week_group_bounds_iso(d, spec.n)
    if spec.unit == "M":
        return _month_group_bounds_anchored(d, spec.n)
    if spec.unit == "Y":
        return _year_group_bounds_anchored(d, spec.n)
    raise ValueError(f"Unsupported unit: {spec.unit}")


def _iter_anchor_windows_from(start_day: date, last_day: date, spec: AnchorSpec) -> list[tuple[date, date]]:
    """
    Generate anchored windows starting from the window containing start_day.
    """
    windows: list[tuple[date, date]] = []

    if spec.unit == "W":
        ws, we = _week_group_bounds_iso(start_day, spec.n)
        cur_s, cur_e = ws, we
        while cur_s <= last_day:
            windows.append((cur_s, cur_e))
            cur_s = cur_s + timedelta(days=7 * spec.n)
            cur_e = cur_e + timedelta(days=7 * spec.n)
        return windows

    if spec.unit == "M":
        # Step month-by-month, but only keep unique anchored group starts.
        cur = _month_start(start_day)
        seen: set[tuple[int, int]] = set()
        while cur <= last_day:
            s, e = _month_group_bounds_anchored(cur, spec.n)
            key = (s.year, s.month)
            if key not in seen:
                seen.add(key)
                windows.append((s, e))
            cur = _add_months(cur, 1)
        return sorted(set(windows))

    if spec.unit == "Y":
        cur = date(start_day.year, 1, 1)
        seen2: set[int] = set()
        while cur <= last_day:
            s, e = _year_group_bounds_anchored(cur, spec.n)
            if s.year not in seen2:
                seen2.add(s.year)
                windows.append((s, e))
            cur = date(cur.year + 1, 1, 1)
        return sorted(set(windows))

    raise ValueError(f"Unsupported unit: {spec.unit}")


# =============================================================================
# Bars (build)
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
            f"[bars_anchor_iso] Duplicate local dates detected for id={id_}, tf={tf}, tz={tz}. "
            f"Examples={list(dups)}. This violates the 1-row-per-day assumption."
        )


def _build_bars_from_windows(
    df_slice: pd.DataFrame,
    *,
    spec: AnchorSpec,
    tz: str,
    windows: list[tuple[date, date]],
    start_bar_seq: int,
    prev_close_for_first: pd.Timestamp | None,
    fail_on_internal_gaps: bool,
) -> pd.DataFrame:
    """
    Build bars for df_slice over provided windows. Bars are assigned sequential bar_seq
    starting at start_bar_seq+1. If prev_close_for_first is provided, force the first
    bar's time_open to prev_close + 1ms (boundary continuity).
    """
    if df_slice.empty or not windows:
        return pd.DataFrame()

    df = df_slice.sort_values("ts").reset_index(drop=True).copy()
    _assert_one_row_per_local_day(df, id_=int(df["id"].iloc[0]), tf=spec.tf, tz=tz)

    ts_local = df["ts"].dt.tz_convert(tz)
    df["day_date"] = ts_local.dt.date
    df["day_time_open"] = _make_day_time_open(df["ts"])

    first_day: date = df["day_date"].iloc[0]
    last_day: date = df["day_date"].iloc[-1]

    idx_by_day = {d: i for i, d in enumerate(df["day_date"].tolist())}

    out_rows: list[dict] = []
    bar_seq = int(start_bar_seq)

    for win_start, win_end in windows:
        # intersect with slice range
        s = max(win_start, first_day)
        e = min(win_end, last_day)
        if s > e:
            continue

        exp_days = (e - s).days + 1
        idxs: list[int] = []
        cur = s
        for _ in range(exp_days):
            j = idx_by_day.get(cur)
            if j is None:
                if fail_on_internal_gaps:
                    raise ValueError(
                        f"[bars_anchor_iso] Missing daily row(s) inside bar: "
                        f"id={int(df['id'].iloc[0])}, tf={spec.tf}, "
                        f"anchor_window={win_start}..{win_end}, intersect={s}..{e}."
                    )
                idxs = []
                break
            idxs.append(j)
            cur = cur + timedelta(days=1)

        if not idxs:
            continue

        g = df.iloc[idxs]
        bar_seq += 1

        high_val = g["high"].max()
        low_val = g["low"].min()

        # default time_open from day_time_open
        time_open = g["day_time_open"].iloc[0]
        if bar_seq == start_bar_seq + 1 and prev_close_for_first is not None:
            time_open = prev_close_for_first + pd.Timedelta(milliseconds=1)

        out_rows.append(
            {
                "id": int(g["id"].iloc[0]),
                "tf": spec.tf,
                "tf_days": int(len(g)),  # actual days in this (possibly partial) bar
                "bar_seq": int(bar_seq),
                "time_open": time_open,
                "time_close": g["ts"].iloc[-1],
                "time_high": g.loc[g["high"] == high_val, "timehigh"].iloc[0],
                "time_low": g.loc[g["low"] == low_val, "timelow"].iloc[0],
                "open": float(g["open"].iloc[0]) if pd.notna(g["open"].iloc[0]) else np.nan,
                "high": float(high_val) if pd.notna(high_val) else np.nan,
                "low": float(low_val) if pd.notna(low_val) else np.nan,
                "close": float(g["close"].iloc[-1]) if pd.notna(g["close"].iloc[-1]) else np.nan,
                "volume": float(g["volume"].sum(skipna=True)),
                "market_cap": float(g["market_cap"].iloc[-1]) if pd.notna(g["market_cap"].iloc[-1]) else np.nan,
            }
        )

    out = pd.DataFrame.from_records(out_rows)
    if out.empty:
        return out

    # continuity check within produced series
    out = out.sort_values(["bar_seq"]).reset_index(drop=True)
    one_ms = pd.Timedelta(milliseconds=1)
    prev_close = out["time_close"].shift(1)
    expected_open = prev_close + one_ms
    mismatch = (out["bar_seq"] > out["bar_seq"].min()) & (out["time_open"] != expected_open)
    if mismatch.any():
        bad = out.loc[mismatch, ["id", "tf", "bar_seq", "time_open", "time_close"]].head(10)
        raise ValueError(
            "Continuity check failed: bar.time_open != prev_bar.time_close + 1ms.\n"
            f"Examples:\n{bad.to_string(index=False)}"
        )

    out["bar_seq"] = out["bar_seq"].astype(np.int32)
    out["tf_days"] = out["tf_days"].astype(np.int32)
    return out


def _build_full_history_for_id_spec(
    df_id: pd.DataFrame,
    *,
    spec: AnchorSpec,
    tz: str,
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

    idx_by_day = {d: i for i, d in enumerate(df["day_date"].tolist())}

    # windows from the first day onward
    windows = _iter_anchor_windows_from(first_day, last_day, spec)

    out_rows: list[dict] = []
    bar_seq = 0

    for win_start, win_end in windows:
        s = max(win_start, first_day)
        e = min(win_end, last_day)
        if s > e:
            continue

        exp_days = (e - s).days + 1
        idxs: list[int] = []
        cur = s
        for _ in range(exp_days):
            j = idx_by_day.get(cur)
            if j is None:
                if fail_on_internal_gaps:
                    raise ValueError(
                        f"[bars_anchor_iso] Missing daily row(s) inside bar: "
                        f"id={int(df['id'].iloc[0])}, tf={spec.tf}, "
                        f"anchor_window={win_start}..{win_end}, intersect={s}..{e}."
                    )
                idxs = []
                break
            idxs.append(j)
            cur = cur + timedelta(days=1)

        if not idxs:
            continue

        g = df.iloc[idxs]
        bar_seq += 1

        high_val = g["high"].max()
        low_val = g["low"].min()

        out_rows.append(
            {
                "id": int(g["id"].iloc[0]),
                "tf": spec.tf,
                "tf_days": int(len(g)),
                "bar_seq": int(bar_seq),
                "time_open": g["day_time_open"].iloc[0],
                "time_close": g["ts"].iloc[-1],
                "time_high": g.loc[g["high"] == high_val, "timehigh"].iloc[0],
                "time_low": g.loc[g["low"] == low_val, "timelow"].iloc[0],
                "open": float(g["open"].iloc[0]) if pd.notna(g["open"].iloc[0]) else np.nan,
                "high": float(high_val) if pd.notna(high_val) else np.nan,
                "low": float(low_val) if pd.notna(low_val) else np.nan,
                "close": float(g["close"].iloc[-1]) if pd.notna(g["close"].iloc[-1]) else np.nan,
                "volume": float(g["volume"].sum(skipna=True)),
                "market_cap": float(g["market_cap"].iloc[-1]) if pd.notna(g["market_cap"].iloc[-1]) else np.nan,
            }
        )

    out = pd.DataFrame.from_records(out_rows)
    if out.empty:
        return out

    # continuity check
    out = out.sort_values(["bar_seq"]).reset_index(drop=True)
    one_ms = pd.Timedelta(milliseconds=1)
    prev_close = out["time_close"].shift(1)
    expected_open = prev_close + one_ms
    mismatch = (out["bar_seq"] > 1) & (out["time_open"] != expected_open)
    if mismatch.any():
        bad = out.loc[mismatch, ["id", "tf", "bar_seq", "time_open", "time_close"]].head(10)
        raise ValueError(
            "Continuity check failed: bar.time_open != prev_bar.time_close + 1ms.\n"
            f"Examples:\n{bad.to_string(index=False)}"
        )

    out["bar_seq"] = out["bar_seq"].astype(np.int32)
    out["tf_days"] = out["tf_days"].astype(np.int32)
    return out


# =============================================================================
# Upsert
# =============================================================================

def upsert_bars(df_bars: pd.DataFrame, db_url: str, bars_table: str, batch_size: int = 25_000) -> None:
    if df_bars.empty:
        return

    upsert_sql = f"""
    INSERT INTO {bars_table} (
      id, tf, tf_days, bar_seq,
      time_open, time_close, time_high, time_low,
      open, high, low, close, volume, market_cap
    )
    VALUES (
      :id, :tf, :tf_days, :bar_seq,
      :time_open, :time_close, :time_high, :time_low,
      :open, :high, :low, :close, :volume, :market_cap
    )
    ON CONFLICT (id, tf, bar_seq) DO UPDATE SET
      tf_days     = EXCLUDED.tf_days,
      time_open   = EXCLUDED.time_open,
      time_close  = EXCLUDED.time_close,
      time_high   = EXCLUDED.time_high,
      time_low    = EXCLUDED.time_low,
      open        = EXCLUDED.open,
      high        = EXCLUDED.high,
      low         = EXCLUDED.low,
      close       = EXCLUDED.close,
      volume      = EXCLUDED.volume,
      market_cap  = EXCLUDED.market_cap,
      ingested_at = now();
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
    fail_on_internal_gaps: bool,
) -> None:
    ensure_state_table(db_url, state_table)

    specs = load_anchor_specs_from_dim_timeframe(db_url)
    tfs = [s.tf for s in specs]
    print(f"[bars_anchor_iso] tz={tz}")
    print(f"[bars_anchor_iso] specs size={len(specs)}: {tfs}")

    daily_mm = load_daily_min_max(db_url, daily_table, ids)
    if daily_mm.empty:
        print("[bars_anchor_iso] No daily data found for requested ids.")
        return

    state_df = load_state(db_url, state_table, ids)
    state_map: dict[tuple[int, str], dict] = {}
    if not state_df.empty:
        for r in state_df.to_dict(orient="records"):
            state_map[(int(r["id"]), str(r["tf"]))] = r

    # per-id daily min/max
    mm_map = {int(r["id"]): r for r in daily_mm.to_dict(orient="records")}

    state_updates: list[dict] = []
    total_upsert = 0
    total_rebuild = 0
    total_update_tail = 0
    total_noop = 0
    total_errors = 0

    for id_ in ids:
        mm = mm_map.get(int(id_))
        if mm is None:
            continue

        daily_min_ts: pd.Timestamp = mm["daily_min_ts"]
        daily_max_ts: pd.Timestamp = mm["daily_max_ts"]

        # last bars for this id across all specs
        last_bar_map = load_last_bar_info_for_id_tfs(db_url, bars_table, id_=int(id_), tfs=tfs)

        for spec in specs:
            key = (int(id_), spec.tf)
            st = state_map.get(key)
            last_bar = last_bar_map.get(spec.tf)

            try:
                # brand new id/tf => full build
                if st is None and last_bar is None:
                    df_full = load_daily_prices_for_id(db_url=db_url, daily_table=daily_table, id_=int(id_))
                    bars = _build_full_history_for_id_spec(
                        df_full, spec=spec, tz=tz, fail_on_internal_gaps=fail_on_internal_gaps
                    )
                    if not bars.empty:
                        upsert_bars(bars, db_url, bars_table)
                        total_upsert += len(bars)
                        total_rebuild += 1
                        last_bar_seq = int(bars["bar_seq"].max())
                        last_time_close = pd.to_datetime(bars.loc[bars["bar_seq"].idxmax(), "time_close"], utc=True)
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

                # hydrate state min/max
                daily_min_seen = (
                    pd.to_datetime(st["daily_min_seen"], utc=True)
                    if st is not None and st.get("daily_min_seen") is not None
                    else daily_min_ts
                )
                daily_max_seen = (
                    pd.to_datetime(st["daily_max_seen"], utc=True)
                    if st is not None and st.get("daily_max_seen") is not None
                    else daily_max_ts
                )

                # state exists but bars missing => rebuild
                if last_bar is None:
                    df_full = load_daily_prices_for_id(db_url=db_url, daily_table=daily_table, id_=int(id_))
                    bars = _build_full_history_for_id_spec(
                        df_full, spec=spec, tz=tz, fail_on_internal_gaps=fail_on_internal_gaps
                    )
                    if not bars.empty:
                        upsert_bars(bars, db_url, bars_table)
                        total_upsert += len(bars)
                        total_rebuild += 1
                        last_bar_seq = int(bars["bar_seq"].max())
                        last_time_close = pd.to_datetime(bars.loc[bars["bar_seq"].idxmax(), "time_close"], utc=True)
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

                last_bar_seq = int(last_bar["last_bar_seq"])
                last_time_close: pd.Timestamp = last_bar["last_time_close"]

                # BACKFILL => full rebuild (bar_seq shifts)
                if daily_min_ts < daily_min_seen:
                    print(
                        f"[bars_anchor_iso] Backfill detected: id={id_}, tf={spec.tf}, "
                        f"daily_min moved earlier {daily_min_seen} -> {daily_min_ts}. Rebuilding id/tf."
                    )
                    delete_bars_for_id_tf(db_url, bars_table, id_=int(id_), tf=spec.tf)
                    df_full = load_daily_prices_for_id(db_url=db_url, daily_table=daily_table, id_=int(id_))
                    bars = _build_full_history_for_id_spec(
                        df_full, spec=spec, tz=tz, fail_on_internal_gaps=fail_on_internal_gaps
                    )
                    if not bars.empty:
                        upsert_bars(bars, db_url, bars_table)
                        total_upsert += len(bars)
                        last_bar_seq = int(bars["bar_seq"].max())
                        last_time_close = pd.to_datetime(bars.loc[bars["bar_seq"].idxmax(), "time_close"], utc=True)
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

                # NOOP
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

                # Incremental forward update:
                # Rebuild from the anchored window that contains last_time_close (local date).
                last_close_day_local = last_time_close.tz_convert(tz).date()
                win_start, _win_end = _bounds_for_date(last_close_day_local, spec)

                # Load slice from (win_start - 1 day) so day_time_open shift is defined, but we
                # force boundary continuity using prev_close_for_first.
                ts_start_local = pd.Timestamp(
                    datetime.combine(win_start - timedelta(days=1), datetime.min.time()),
                    tz=tz,
                )
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

                slice_last_day = df_slice["ts"].max().tz_convert(tz).date()
                new_last_day = daily_max_ts.tz_convert(tz).date()
                last_day = min(slice_last_day, new_last_day)

                windows = _iter_anchor_windows_from(win_start, last_day, spec)

                # Delete tail from last_bar_seq; we will recompute last bar and any new bars.
                delete_bars_for_id_tf_from_seq(db_url, bars_table, id_=int(id_), tf=spec.tf, bar_seq_from=last_bar_seq)

                prev_close_for_first = None
                start_bar_seq = last_bar_seq - 1
                if start_bar_seq >= 1:
                    prev_close_for_first = load_time_close_for_bar_seq(
                        db_url, bars_table, id_=int(id_), tf=spec.tf, bar_seq=start_bar_seq
                    )

                new_bars = _build_bars_from_windows(
                    df_slice,
                    spec=spec,
                    tz=tz,
                    windows=windows,
                    start_bar_seq=start_bar_seq,
                    prev_close_for_first=prev_close_for_first,
                    fail_on_internal_gaps=fail_on_internal_gaps,
                )

                if new_bars.empty:
                    total_noop += 1
                    state_updates.append(
                        {
                            "id": int(id_),
                            "tf": spec.tf,
                            "tz": tz,
                            "daily_min_seen": min(daily_min_seen, daily_min_ts),
                            "daily_max_seen": max(daily_max_seen, daily_max_ts),
                            "last_bar_seq": start_bar_seq if start_bar_seq >= 1 else last_bar_seq,
                            "last_time_close": prev_close_for_first if prev_close_for_first is not None else last_time_close,
                        }
                    )
                    continue

                upsert_bars(new_bars, db_url, bars_table)
                total_upsert += len(new_bars)
                total_update_tail += 1

                last_bar_seq2 = int(new_bars["bar_seq"].max())
                last_time_close2 = pd.to_datetime(new_bars.loc[new_bars["bar_seq"].idxmax(), "time_close"], utc=True)

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
                print(f"[bars_anchor_iso] ERROR id={id_} tf={spec.tf}: {type(e).__name__}: {e}")

                # keep state min/max; do not advance last_* on error
                last_bar_keep = last_bar_map.get(spec.tf)
                state_updates.append(
                    {
                        "id": int(id_),
                        "tf": spec.tf,
                        "tz": tz,
                        "daily_min_seen": daily_min_ts if st is None else min(
                            pd.to_datetime(st["daily_min_seen"], utc=True) if st.get("daily_min_seen") is not None else daily_min_ts,
                            daily_min_ts,
                        ),
                        "daily_max_seen": daily_max_ts if st is None else max(
                            pd.to_datetime(st["daily_max_seen"], utc=True) if st.get("daily_max_seen") is not None else daily_max_ts,
                            daily_max_ts,
                        ),
                        "last_bar_seq": int(last_bar_keep["last_bar_seq"]) if last_bar_keep is not None else (st.get("last_bar_seq") if st is not None else None),
                        "last_time_close": pd.to_datetime(last_bar_keep["last_time_close"], utc=True) if last_bar_keep is not None else (pd.to_datetime(st["last_time_close"], utc=True) if st is not None and st.get("last_time_close") is not None else None),
                    }
                )
                continue

    upsert_state(db_url, state_table, state_updates)
    print(
        f"[bars_anchor_iso] Done. upserted_rows={total_upsert:,} "
        f"rebuilds={total_rebuild} tail_updates={total_update_tail} noops={total_noop} errors={total_errors}"
    )


# =============================================================================
# CLI
# =============================================================================

def main(argv: Sequence[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description="Build ISO calendar-anchored price bars into public.cmc_price_bars_multi_tf_cal_anchor_iso (incremental)."
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
        help="Fail if any daily row is missing inside a bar intersection (recommended).",
    )
    args = ap.parse_args(list(argv) if argv is not None else None)

    db_url = resolve_db_url(args.db_url)
    ids = parse_ids(args.ids, db_url, args.daily_table)

    print(f"[bars_anchor_iso] daily_table={args.daily_table}")
    print(f"[bars_anchor_iso] bars_table={args.bars_table}")
    print(f"[bars_anchor_iso] state_table={args.state_table}")

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
