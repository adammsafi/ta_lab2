from __future__ import annotations

"""
Calendar-aligned price bars builder: public.cmc_price_bars_multi_tf_cal_us
from public.cmc_price_histories7 (daily).

UPDATED (Incremental + dim_timeframe-driven):

1) Timeframes are loaded from public.dim_timeframe (no TF_LIST_CAL hardcoding):

   IMPORTANT (matches your dim_timeframe as shown):
   - alignment_type   = 'calendar'   (NOT 'cal')
   - calendar_scheme  = 'CAL'        (full-period calendar-aligned set)
   - allow_partial_start = FALSE
   - allow_partial_end   = FALSE
   - base_unit in ('W','M','Y')
   - tf_qty is the unit multiple (e.g. 2W, 3M, 1Y)
   - tf is the label (e.g. '1W_CAL', '3M_CAL')

2) Incremental refresh:
   - Append-only: If new daily data arrives after the last completed bar close,
     we build only new FULL calendar bars and upsert them.
   - No partial bars: if we don't have a full next period yet, we do nothing.
   - Backfill-aware: If earlier daily data arrives (daily_min decreases vs what
     we previously observed for that id/tf), we REBUILD that id/tf completely,
     because calendar anchoring for "first full period" can shift bar_seq.

3) State table:
   public.cmc_price_bars_multi_tf_cal_us_state stores per (id, tf):
     - tz
     - daily_min_seen, daily_max_seen
     - last_bar_seq, last_time_close
     - updated_at

Semantics preserved:
- Bars are calendar aligned (US week rules in this module are Sunday-start weeks).
- First bar requires FULL periods only (no partial first bar).
- Every bar requires ALL daily rows in its calendar span.
- Continuity time_open: first day uses lag(ts)+1ms (and across bars, time_open == prev_close + 1ms).
- Stored timestamps remain tz-aware (UTC in DB); calendar math in tz (default America/New_York).

Quality-of-life improvements vs previous version:
- Correct last-bar retrieval (no MAX(bar_seq), MAX(time_close) mismatch).
- Batch-load last-bar info for all tfs per id (fewer DB roundtrips).
- Guard against duplicate local dates (violates 1-row-per-day assumption).
- Per-(id,tf) exception handling so one failure doesn’t stop the whole run.
- Incremental slice start derived from next_bar_start (cleaner boundary behavior).
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
DEFAULT_BARS_TABLE = "public.cmc_price_bars_multi_tf_cal_us"
DEFAULT_STATE_TABLE = "public.cmc_price_bars_multi_tf_cal_us_state"


# =============================================================================
# DB helpers
# =============================================================================

def resolve_db_url(db_url: str | None) -> str:
    if db_url and db_url.strip():
        print("[bars_cal_us] Using DB URL from --db-url arg.")
        return db_url.strip()

    env_url = os.getenv("TARGET_DB_URL")
    if not env_url:
        raise SystemExit("No DB URL provided. Set TARGET_DB_URL env var or pass --db-url.")
    print("[bars_cal_us] Using DB URL from TARGET_DB_URL env.")
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
        print(f"[bars_cal_us] Loaded ALL ids from {daily_table}: {len(ids)}")
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


def load_last_bar_info(db_url: str, bars_table: str, id_: int, tf: str) -> dict | None:
    """
    Return dict with last_bar_seq, last_time_close for existing bars, or None if none.

    NOTE: Must select the row with the max bar_seq (avoid MAX() mismatch).
    """
    sql = text(f"""
      SELECT bar_seq AS last_bar_seq, time_close AS last_time_close
      FROM {bars_table}
      WHERE id = :id AND tf = :tf
      ORDER BY bar_seq DESC
      LIMIT 1;
    """)
    eng = get_engine(db_url)
    with eng.connect() as conn:
        row = conn.execute(sql, {"id": int(id_), "tf": tf}).mappings().first()

    if row is None or row["last_bar_seq"] is None or row["last_time_close"] is None:
        return None

    return {
        "last_bar_seq": int(row["last_bar_seq"]),
        "last_time_close": pd.to_datetime(row["last_time_close"], utc=True),
    }


def load_last_bar_info_for_id_tfs(
    db_url: str,
    bars_table: str,
    id_: int,
    tfs: list[str],
) -> dict[str, dict]:
    """
    Batch-load last bar info for a single id across multiple tfs.
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


def delete_bars_for_id_tf(db_url: str, bars_table: str, id_: int, tf: str) -> None:
    sql = text(f"DELETE FROM {bars_table} WHERE id = :id AND tf = :tf;")
    eng = get_engine(db_url)
    with eng.begin() as conn:
        conn.execute(sql, {"id": int(id_), "tf": tf})


# =============================================================================
# dim_timeframe-driven TF specs
# =============================================================================

@dataclass(frozen=True)
class CalSpec:
    n: int
    unit: str  # 'W','M','Y'
    tf: str


def load_cal_specs_from_dim_timeframe(db_url: str) -> list[CalSpec]:
    """
    Load calendar-aligned, full-period-only timeframes for _cal_us.

    For US _cal bars we want:
      - Weeks from *_CAL rows (1W_CAL..10W_CAL), which in your dim_timeframe
        are stored with base_unit='W' and typically calendar_anchor='ISO-WEEK'
        (calendar_scheme may be blank).
      - Months/Years from CAL scheme rows (1M_CAL..1Y_CAL), where calendar_scheme='CAL'.

    Requirements:
      - alignment_type = 'calendar'
      - allow_partial_start = false
      - allow_partial_end   = false
      - base_unit in ('W','M','Y')
    """
    sql = text("""
      SELECT tf, base_unit, tf_qty, sort_order
      FROM public.dim_timeframe
      WHERE alignment_type = 'calendar'
        AND allow_partial_start = FALSE
        AND allow_partial_end   = FALSE
        AND base_unit IN ('W','M','Y')
        AND (
              (base_unit = 'W' AND tf LIKE '%_CAL')
           OR (base_unit IN ('M','Y') AND calendar_scheme = 'CAL')
        )
      ORDER BY sort_order, tf;
    """)
    eng = get_engine(db_url)
    with eng.connect() as conn:
        rows = conn.execute(sql).mappings().all()

    specs: list[CalSpec] = []
    for r in rows:
        specs.append(
            CalSpec(
                n=int(r["tf_qty"]),
                unit=str(r["base_unit"]),
                tf=str(r["tf"]),
            )
        )

    if not specs:
        raise RuntimeError(
            "No calendar full-period timeframes found in dim_timeframe for _cal_us. "
            "Expected weeks as *_CAL and months/years as calendar_scheme='CAL'."
        )
    return specs


# =============================================================================
# Calendar math helpers (NY-local date logic)
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


def _week_start_sunday(d: date) -> date:
    # Sunday-based week: Sunday..Saturday
    days_since_sun = (d.weekday() + 1) % 7
    return d - timedelta(days=days_since_sun)


def _compute_anchor_start(first_day: date, unit: str) -> date:
    """
    First FULL period start AFTER the data begins (full-period policy).
    """
    if unit == "W":
        ws = _week_start_sunday(first_day)
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


def _advance_start(bar_start: date, n: int, unit: str) -> date:
    if unit == "W":
        return bar_start + timedelta(days=7 * n)
    if unit == "M":
        return _add_months(bar_start, n)
    if unit == "Y":
        return date(bar_start.year + n, 1, 1)
    raise ValueError(f"Unsupported unit: {unit}")


# =============================================================================
# Bar building
# =============================================================================

def _make_day_time_open(ts: pd.Series) -> pd.Series:
    one_ms = pd.Timedelta(milliseconds=1)
    day_open = ts.shift(1) + one_ms
    if len(ts) > 0:
        day_open.iloc[0] = ts.iloc[0] - pd.Timedelta(days=1) + one_ms
    return day_open


def _assert_one_row_per_local_day(df: pd.DataFrame, *, id_: int, tf: str, tz: str) -> None:
    """
    We assume one daily row per local calendar date. If duplicates exist,
    df_by_date mapping would silently overwrite; fail fast instead.
    """
    if df.empty:
        return
    ts_local = df["ts"].dt.tz_convert(tz)
    day_date = ts_local.dt.date
    if day_date.duplicated().any():
        dups = day_date[day_date.duplicated()].astype(str).unique()[:10]
        raise ValueError(
            f"[bars_cal_us] Duplicate local dates detected for id={id_}, tf={tf}, tz={tz}. "
            f"Examples={list(dups)}. This violates the 1-row-per-day assumption."
        )


def _build_full_history_for_id_spec(df_id: pd.DataFrame, *, spec: CalSpec, tz: str) -> pd.DataFrame:
    """
    Build bars from scratch for one id/spec (full history), full periods only.
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

    df["day_time_open"] = _make_day_time_open(df["ts"])

    # fast map: date -> row index (assumes 1 row per day)
    df_by_date = {d: i for i, d in enumerate(df["day_date"].tolist())}

    bars: list[dict] = []
    bar_seq = 0
    bar_start = anchor_start

    while True:
        bar_end = _bar_end_for_start(bar_start, spec.n, spec.unit)
        if bar_end > last_day:
            break

        exp_n = _expected_days(bar_start, bar_end)
        idxs: list[int] = []
        cur = bar_start
        for _ in range(exp_n):
            j = df_by_date.get(cur)
            if j is None:
                raise ValueError(
                    f"[bars_cal_us] Missing daily rows for id={int(df_id['id'].iloc[0])}, tf={spec.tf}, "
                    f"bar_start={bar_start}, bar_end={bar_end} (expected {exp_n} days)."
                )
            idxs.append(j)
            cur = cur + timedelta(days=1)

        g = df.iloc[idxs]
        bar_seq += 1

        high_val = g["high"].max()
        low_val = g["low"].min()

        bars.append(
            {
                "id": int(g["id"].iloc[0]),
                "tf": spec.tf,
                "tf_days": int(exp_n),
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

        bar_start = _advance_start(bar_start, spec.n, spec.unit)

    out = pd.DataFrame.from_records(bars)
    if out.empty:
        return out

    # Continuity check within (id, tf)
    one_ms = pd.Timedelta(milliseconds=1)
    out = out.sort_values(["bar_seq"]).reset_index(drop=True)
    prev_close = out["time_close"].shift(1)
    expected_open = prev_close + one_ms
    mismatch = (out["bar_seq"] > 1) & (out["time_open"] != expected_open)
    if mismatch.any():
        bad = out.loc[mismatch, ["id", "tf", "bar_seq", "time_open", "time_close"]].head(10)
        raise ValueError(
            "Continuity check failed in cal bars: time_open != prev_bar.time_close + 1ms.\n"
            f"Examples:\n{bad.to_string(index=False)}"
        )

    out["bar_seq"] = out["bar_seq"].astype(np.int32)
    out["tf_days"] = out["tf_days"].astype(np.int32)
    return out


def _build_incremental_new_bars_for_id_spec(
    df_slice: pd.DataFrame,
    *,
    spec: CalSpec,
    tz: str,
    next_bar_start: date,
    last_day: date,
    last_time_close: pd.Timestamp,
    last_bar_seq: int,
) -> pd.DataFrame:
    """
    Build ONLY new full bars starting at next_bar_start (already aligned),
    using df_slice which must include all needed days up to last_day.
    """
    if df_slice.empty:
        return pd.DataFrame()

    df = df_slice.sort_values("ts").reset_index(drop=True).copy()
    _assert_one_row_per_local_day(df, id_=int(df["id"].iloc[0]), tf=spec.tf, tz=tz)

    ts_local = df["ts"].dt.tz_convert(tz)
    df["day_date"] = ts_local.dt.date

    df["day_time_open"] = _make_day_time_open(df["ts"])
    df_by_date = {d: i for i, d in enumerate(df["day_date"].tolist())}

    bars: list[dict] = []
    bar_seq = last_bar_seq
    bar_start = next_bar_start

    while True:
        bar_end = _bar_end_for_start(bar_start, spec.n, spec.unit)
        if bar_end > last_day:
            break

        exp_n = _expected_days(bar_start, bar_end)
        idxs: list[int] = []
        cur = bar_start
        for _ in range(exp_n):
            j = df_by_date.get(cur)
            if j is None:
                raise ValueError(
                    f"[bars_cal_us] Missing daily rows for id={int(df['id'].iloc[0])}, tf={spec.tf}, "
                    f"bar_start={bar_start}, bar_end={bar_end} (expected {exp_n} days)."
                )
            idxs.append(j)
            cur = cur + timedelta(days=1)

        g = df.iloc[idxs]
        bar_seq += 1

        high_val = g["high"].max()
        low_val = g["low"].min()

        # time_open for the FIRST new bar must equal last_time_close + 1ms
        if bar_seq == last_bar_seq + 1:
            time_open = last_time_close + pd.Timedelta(milliseconds=1)
        else:
            time_open = g["day_time_open"].iloc[0]

        bars.append(
            {
                "id": int(g["id"].iloc[0]),
                "tf": spec.tf,
                "tf_days": int(exp_n),
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

        bar_start = _advance_start(bar_start, spec.n, spec.unit)

    out = pd.DataFrame.from_records(bars)
    if out.empty:
        return out

    # Continuity check within the newly produced series (boundary condition enforced above)
    one_ms = pd.Timedelta(milliseconds=1)
    out = out.sort_values(["bar_seq"]).reset_index(drop=True)
    prev_close = out["time_close"].shift(1)
    expected_open = prev_close + one_ms
    mismatch = (out["bar_seq"] > out["bar_seq"].min()) & (out["time_open"] != expected_open)
    if mismatch.any():
        bad = out.loc[mismatch, ["id", "tf", "bar_seq", "time_open", "time_close"]].head(10)
        raise ValueError(
            "Continuity check failed in incremental cal bars: time_open != prev_bar.time_close + 1ms.\n"
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
) -> None:
    ensure_state_table(db_url, state_table)

    specs = load_cal_specs_from_dim_timeframe(db_url)
    tfs = [s.tf for s in specs]
    print(f"[bars_cal_us] tz={tz}")
    print(f"[bars_cal_us] specs size={len(specs)}: {tfs}")

    daily_mm = load_daily_min_max(db_url, daily_table, ids)
    if daily_mm.empty:
        print("[bars_cal_us] No daily data found for requested ids.")
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

    # Pre-compute per-id daily min/max
    mm_map = {int(r["id"]): r for r in daily_mm.to_dict(orient="records")}

    for id_ in ids:
        mm = mm_map.get(int(id_))
        if mm is None:
            continue

        daily_min_ts: pd.Timestamp = mm["daily_min_ts"]
        daily_max_ts: pd.Timestamp = mm["daily_max_ts"]
        daily_max_day: date = daily_max_ts.tz_convert(tz).date()

        # Batch-load last bars for this id across all specs (fewer DB calls)
        last_bar_map = load_last_bar_info_for_id_tfs(db_url, bars_table, id_=int(id_), tfs=tfs)

        for spec in specs:
            try:
                key = (int(id_), spec.tf)
                st = state_map.get(key)
                last_bar = last_bar_map.get(spec.tf)

                if st is None and last_bar is None:
                    # First time ever: full build
                    df_full = load_daily_prices_for_id(db_url=db_url, daily_table=daily_table, id_=int(id_))
                    bars = _build_full_history_for_id_spec(df_full, spec=spec, tz=tz)
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

                # Hydrate state fields
                daily_min_seen = (
                    pd.to_datetime(st["daily_min_seen"], utc=True)
                    if st is not None and st["daily_min_seen"] is not None
                    else daily_min_ts
                )
                daily_max_seen = (
                    pd.to_datetime(st["daily_max_seen"], utc=True)
                    if st is not None and st["daily_max_seen"] is not None
                    else daily_max_ts
                )

                if last_bar is None:
                    # State exists but table has no bars (or tf missing) -> rebuild this id/tf
                    df_full = load_daily_prices_for_id(db_url=db_url, daily_table=daily_table, id_=int(id_))
                    bars = _build_full_history_for_id_spec(df_full, spec=spec, tz=tz)
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

                # BACKFILL DETECTION
                if daily_min_ts < daily_min_seen:
                    print(
                        f"[bars_cal_us] Backfill detected: id={id_}, tf={spec.tf}, "
                        f"daily_min moved earlier {daily_min_seen} -> {daily_min_ts}. Rebuilding id/tf."
                    )
                    delete_bars_for_id_tf(db_url, bars_table, id_=int(id_), tf=spec.tf)
                    df_full = load_daily_prices_for_id(db_url=db_url, daily_table=daily_table, id_=int(id_))
                    bars = _build_full_history_for_id_spec(df_full, spec=spec, tz=tz)
                    if not bars.empty:
                        upsert_bars(bars, db_url, bars_table)
                        total_upsert += len(bars)

                        # refresh last_* from rebuilt bars
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

                # APPEND CHECK
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

                # Determine the next bar start (local day after last close)
                next_bar_start = last_time_close.tz_convert(tz).date() + timedelta(days=1)

                # Load a minimal slice:
                # include prior local day so day_time_open shift is well-defined, but we still enforce
                # bar-level continuity using last_time_close.
                ts_start_local = pd.Timestamp(
                    datetime.combine(next_bar_start - timedelta(days=1), datetime.min.time()),
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
                last_day = min(slice_last_day, daily_max_day)

                new_bars = _build_incremental_new_bars_for_id_spec(
                    df_slice,
                    spec=spec,
                    tz=tz,
                    next_bar_start=next_bar_start,
                    last_day=last_day,
                    last_time_close=last_time_close,
                    last_bar_seq=last_bar_seq,
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
                            "last_bar_seq": last_bar_seq,
                            "last_time_close": last_time_close,
                        }
                    )
                    continue

                upsert_bars(new_bars, db_url, bars_table)
                total_upsert += len(new_bars)
                total_append += 1

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
                print(f"[bars_cal_us] ERROR id={id_} tf={spec.tf}: {type(e).__name__}: {e}")

                # Keep state at least reflecting min/max seen; do not advance last_* on error.
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
        f"[bars_cal_us] Done. upserted_rows={total_upsert:,} "
        f"rebuilds={total_rebuild} appends={total_append} noops={total_noop} errors={total_errors}"
    )


# =============================================================================
# CLI
# =============================================================================

def main(argv: Sequence[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description="Build calendar-aligned US price bars into public.cmc_price_bars_multi_tf_cal_us (incremental)."
    )
    ap.add_argument("--ids", nargs="+", required=True, help="'all' or list of ids (space/comma separated).")
    ap.add_argument("--db-url", default=None, help="Optional DB URL override. Defaults to TARGET_DB_URL env.")
    ap.add_argument("--daily-table", default=DEFAULT_DAILY_TABLE)
    ap.add_argument("--bars-table", default=DEFAULT_BARS_TABLE)
    ap.add_argument("--state-table", default=DEFAULT_STATE_TABLE)
    ap.add_argument("--tz", default=DEFAULT_TZ, help="Timezone for calendar alignment (default America/New_York).")
    args = ap.parse_args(list(argv) if argv is not None else None)

    db_url = resolve_db_url(args.db_url)
    ids = parse_ids(args.ids, db_url, args.daily_table)

    print(f"[bars_cal_us] daily_table={args.daily_table}")
    print(f"[bars_cal_us] bars_table={args.bars_table}")
    print(f"[bars_cal_us] state_table={args.state_table}")

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
