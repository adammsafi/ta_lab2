from __future__ import annotations

"""
Build tf_days-count price bars into public.cmc_price_bars_multi_tf from public.cmc_price_histories7.

Rules:
- Bars are defined purely by tf_days (fixed number of daily rows), NOT calendar aligned.
- Origin is the first available daily row per id (anchored to data start).
- No partial bars: trailing remainder rows are dropped; every bar has exactly tf_days rows.

Timestamps:
- Source daily close timestamp is cmc_price_histories7."timestamp" (aliased to ts).

- time_high / time_low use intraday timestamps from the source table:
    * time_high comes from cmc_price_histories7.timehigh on the row where the bar's HIGH occurs
    * time_low  comes from cmc_price_histories7.timelow  on the row where the bar's LOW occurs

CORE FIX (bar continuity + correct open-time semantics):
- Bars previously had time_open == first day CLOSE timestamp (wrong).
- Correct is:
      day_time_open[t] = lag(day_time_close) + 1ms
      bar_time_open    = first(day_time_open)
  so that:
      next_bar.time_open == prev_bar.time_close + 1ms

- For the first daily row per id:
      day_time_open[0] = ts[0] - 1 day + 1ms
  (synthetic; there is no prior close inside the series)

DB URL:
- Uses TARGET_DB_URL env var by default.
- Optional --db-url override is supported.

Ids:
- --ids all works (loads DISTINCT id from cmc_price_histories7)
- Or pass space / comma separated ids.

TF selection (UPDATED):
- No TF_LIST in code.
- We load TF-day timeframes from public.dim_timeframe:
    * alignment_type = 'tf_day'
    * calendar_scheme IS NULL (so no calendar semantics leak in)
    * tf matches '^\\d+D$' (hard guard: only pure day-count labels like 30D, 360D, 365D)
    * is_canonical = TRUE by default (override with --include-non-canonical)
    * tf_qty >= 2 (so we do NOT emit 1D bars)

INCREMENTAL (NEW, default):
- Append-only when new daily data extends later than last completed bar close for (id, tf).
- No partial bars at end: only write new COMPLETE tf_days bars.
- Backfill-aware: if earlier daily data appears (daily_min decreases vs stored), we rebuild that (id, tf),
  because bar_seq anchoring to the first day shifts.

State table (NEW, default):
  public.cmc_price_bars_multi_tf_state stores per (id, tf):
    - daily_min_seen, daily_max_seen
    - last_bar_seq, last_time_close
    - updated_at
"""

import argparse
import os
import re
from typing import Iterable, Sequence

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


# =============================================================================
# DB helpers
# =============================================================================

def resolve_db_url(db_url: str | None) -> str:
    if db_url and db_url.strip():
        print("[bars_multi_tf] Using DB URL from --db-url arg.")
        return db_url.strip()

    env_url = os.getenv("TARGET_DB_URL")
    if not env_url:
        raise SystemExit("No DB URL provided. Set TARGET_DB_URL env var or pass --db-url.")
    print("[bars_multi_tf] Using DB URL from TARGET_DB_URL env.")
    return env_url.strip()


def get_engine(db_url: str) -> Engine:
    return create_engine(db_url, future=True)


def load_all_ids(db_url: str) -> list[int]:
    sql = text("SELECT DISTINCT id FROM public.cmc_price_histories7 ORDER BY id;")
    eng = get_engine(db_url)
    with eng.connect() as conn:
        rows = conn.execute(sql).fetchall()
    return [int(r[0]) for r in rows]


def parse_ids(values: Sequence[str], db_url: str) -> list[int]:
    if len(values) == 1 and values[0].strip().lower() == "all":
        ids = load_all_ids(db_url)
        print(f"[bars_multi_tf] Loaded ALL ids from cmc_price_histories7: {len(ids)}")
        return ids

    out: list[int] = []
    for v in values:
        parts = [p.strip() for p in v.split(",") if p.strip()]
        out.extend(int(p) for p in parts)

    # dedupe but keep order
    seen: set[int] = set()
    ids2: list[int] = []
    for x in out:
        if x not in seen:
            seen.add(x)
            ids2.append(x)
    return ids2


def load_daily_min_max(db_url: str, ids: list[int]) -> pd.DataFrame:
    if not ids:
        return pd.DataFrame()

    sql = text(
        """
        SELECT
          id,
          MIN("timestamp") AS daily_min_ts,
          MAX("timestamp") AS daily_max_ts,
          COUNT(*)         AS n_rows
        FROM public.cmc_price_histories7
        WHERE id = ANY(:ids)
        GROUP BY id
        ORDER BY id;
        """
    )
    eng = get_engine(db_url)
    with eng.connect() as conn:
        df = pd.read_sql(sql, conn, params={"ids": ids})

    if df.empty:
        return df

    df["daily_min_ts"] = pd.to_datetime(df["daily_min_ts"], utc=True)
    df["daily_max_ts"] = pd.to_datetime(df["daily_max_ts"], utc=True)
    df["n_rows"] = df["n_rows"].astype(np.int64)
    return df


def load_daily_prices(ids: Iterable[int], db_url: str) -> pd.DataFrame:
    """
    Load daily rows from cmc_price_histories7 (full history for ids).
    """
    ids = list(ids)
    if not ids:
        return pd.DataFrame()

    sql = text(
        """
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
        FROM public.cmc_price_histories7
        WHERE id = ANY(:ids)
        ORDER BY id, "timestamp";
        """
    )

    eng = get_engine(db_url)
    with eng.connect() as conn:
        df = pd.read_sql(sql, conn, params={"ids": ids})

    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df["timehigh"] = pd.to_datetime(df["timehigh"], utc=True)
    df["timelow"] = pd.to_datetime(df["timelow"], utc=True)
    return df


def load_daily_prices_for_id(
    *,
    db_url: str,
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

    sql = text(
        f"""
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
        FROM public.cmc_price_histories7
        {where}
        ORDER BY "timestamp";
        """
    )

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
    sql = text(
        f"""
        SELECT MAX(bar_seq) AS last_bar_seq, MAX(time_close) AS last_time_close
        FROM {bars_table}
        WHERE id = :id AND tf = :tf;
        """
    )
    eng = get_engine(db_url)
    with eng.connect() as conn:
        row = conn.execute(sql, {"id": int(id_), "tf": tf}).mappings().first()

    if row is None or row["last_bar_seq"] is None or row["last_time_close"] is None:
        return None

    return {
        "last_bar_seq": int(row["last_bar_seq"]),
        "last_time_close": pd.to_datetime(row["last_time_close"], utc=True),
    }


def delete_bars_for_id_tf(db_url: str, bars_table: str, id_: int, tf: str) -> None:
    eng = get_engine(db_url)
    with eng.begin() as conn:
        conn.execute(text(f"DELETE FROM {bars_table} WHERE id=:id AND tf=:tf;"), {"id": int(id_), "tf": tf})


# =============================================================================
# State table (incremental)
# =============================================================================

DEFAULT_BARS_TABLE = "public.cmc_price_bars_multi_tf"
DEFAULT_STATE_TABLE = "public.cmc_price_bars_multi_tf_state"


def ensure_state_table(db_url: str, state_table: str) -> None:
    ddl = f"""
    CREATE TABLE IF NOT EXISTS {state_table} (
      id               integer      NOT NULL,
      tf               text         NOT NULL,
      daily_min_seen   timestamptz  NULL,
      daily_max_seen   timestamptz  NULL,
      last_bar_seq     integer      NULL,
      last_time_close  timestamptz  NULL,
      updated_at       timestamptz  NOT NULL DEFAULT now(),
      PRIMARY KEY (id, tf)
    );
    """
    eng = get_engine(db_url)
    with eng.begin() as conn:
        conn.execute(text(ddl))


def load_state(db_url: str, state_table: str, ids: list[int]) -> pd.DataFrame:
    if not ids:
        return pd.DataFrame()

    sql = text(
        f"""
        SELECT id, tf, daily_min_seen, daily_max_seen, last_bar_seq, last_time_close, updated_at
        FROM {state_table}
        WHERE id = ANY(:ids);
        """
    )
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
    sql = text(
        f"""
        INSERT INTO {state_table} (
          id, tf, daily_min_seen, daily_max_seen, last_bar_seq, last_time_close, updated_at
        )
        VALUES (
          :id, :tf, :daily_min_seen, :daily_max_seen, :last_bar_seq, :last_time_close, now()
        )
        ON CONFLICT (id, tf) DO UPDATE SET
          daily_min_seen  = EXCLUDED.daily_min_seen,
          daily_max_seen  = EXCLUDED.daily_max_seen,
          last_bar_seq    = EXCLUDED.last_bar_seq,
          last_time_close = EXCLUDED.last_time_close,
          updated_at      = now();
        """
    )
    eng = get_engine(db_url)
    with eng.begin() as conn:
        conn.execute(sql, rows)


# =============================================================================
# TF selection (from dim_timeframe)
# =============================================================================

_TF_DAY_LABEL_RE = re.compile(r"^\d+D$")


def load_tf_list_from_dim_timeframe(
    *,
    db_url: str,
    include_non_canonical: bool = False,
) -> list[tuple[int, str]]:
    """
    Load the TF list for cmc_price_bars_multi_tf from public.dim_timeframe.

    Guards:
      - alignment_type = 'tf_day'
      - calendar_scheme IS NULL
      - tf matches '^\\d+D$'
      - tf_qty >= 2 (so we don't emit 1D)
      - is_canonical = TRUE unless include_non_canonical=True

    Returns list[(tf_days, tf_label)] sorted by sort_order then tf.
    """
    eng = get_engine(db_url)
    sql = text(
        """
        SELECT
            tf,
            tf_days_nominal,
            sort_order,
            is_canonical
        FROM public.dim_timeframe
        WHERE alignment_type = 'tf_day'
          AND calendar_scheme IS NULL
          AND tf_qty >= 2
        ORDER BY sort_order, tf;
        """
    )
    with eng.connect() as conn:
        rows = conn.execute(sql).mappings().all()

    out: list[tuple[int, str]] = []
    for r in rows:
        tf = str(r["tf"])
        if not _TF_DAY_LABEL_RE.match(tf):
            continue
        if (not include_non_canonical) and (not bool(r["is_canonical"])):
            continue
        tf_days = int(r["tf_days_nominal"])
        out.append((tf_days, tf))

    if not out:
        raise RuntimeError(
            "No TFs selected from dim_timeframe for cmc_price_bars_multi_tf. "
            "Check dim_timeframe rows (alignment_type='tf_day', calendar_scheme IS NULL, tf like '30D')."
        )
    return out


# =============================================================================
# Bar building
# =============================================================================

def _make_day_time_open(ts: pd.Series) -> pd.Series:
    one_ms = pd.Timedelta(milliseconds=1)
    day_open = ts.shift(1) + one_ms
    if len(ts) > 0:
        day_open.iloc[0] = ts.iloc[0] - pd.Timedelta(days=1) + one_ms
    return day_open


def _enforce_bar_continuity(out: pd.DataFrame) -> None:
    if out.empty:
        return
    out = out.sort_values(["bar_seq"]).reset_index(drop=True)

    one_ms = pd.Timedelta(milliseconds=1)
    prev_close = out["time_close"].shift(1)
    expected_open = prev_close + one_ms
    mismatch = (out["bar_seq"] > 1) & (out["time_open"] != expected_open)
    if mismatch.any():
        bad = out.loc[mismatch, ["id", "tf", "bar_seq", "time_open", "time_close"]].head(10)
        raise ValueError(
            "Continuity check failed: some bar.time_open != prev_bar.time_close + 1ms.\n"
            f"Examples:\n{bad.to_string(index=False)}"
        )


def build_bars_for_id(df_id: pd.DataFrame, tf_days: int, tf_label: str) -> pd.DataFrame:
    """
    Full build for a single id + tf_days. Drops partial trailing bars.
    """
    if df_id.empty:
        return pd.DataFrame()

    df_id = df_id.sort_values("ts").reset_index(drop=True)
    n = len(df_id)
    n_full = n // tf_days
    if n_full <= 0:
        return pd.DataFrame()

    df_use = df_id.iloc[: n_full * tf_days].copy()
    day_idx = np.arange(len(df_use), dtype=np.int64)
    df_use["bar_seq"] = (day_idx // tf_days) + 1

    df_use["day_time_open"] = _make_day_time_open(df_use["ts"])

    rows: list[dict] = []
    for bar_seq, g in df_use.groupby("bar_seq", sort=True):
        time_open = g["day_time_open"].iloc[0]
        time_close = g["ts"].iloc[-1]

        open_ = g["open"].iloc[0]
        close_ = g["close"].iloc[-1]
        high_val = g["high"].max()
        low_val = g["low"].min()

        time_high = g.loc[g["high"] == high_val, "timehigh"].iloc[0]
        time_low = g.loc[g["low"] == low_val, "timelow"].iloc[0]

        volume_ = g["volume"].sum(skipna=True)
        market_cap_ = g["market_cap"].iloc[-1]

        rows.append(
            {
                "id": int(df_id["id"].iloc[0]),
                "tf": tf_label,
                "tf_days": int(tf_days),
                "bar_seq": int(bar_seq),
                "time_open": time_open,
                "time_close": time_close,
                "time_high": time_high,
                "time_low": time_low,
                "open": float(open_) if pd.notna(open_) else np.nan,
                "high": float(high_val) if pd.notna(high_val) else np.nan,
                "low": float(low_val) if pd.notna(low_val) else np.nan,
                "close": float(close_) if pd.notna(close_) else np.nan,
                "volume": float(volume_) if pd.notna(volume_) else np.nan,
                "market_cap": float(market_cap_) if pd.notna(market_cap_) else np.nan,
            }
        )

    out = pd.DataFrame.from_records(rows)
    if out.empty:
        return out

    out["bar_seq"] = out["bar_seq"].astype(np.int32)
    out["tf_days"] = out["tf_days"].astype(np.int32)

    _enforce_bar_continuity(out)
    return out


def _build_incremental_new_bars_for_id(
    df_slice: pd.DataFrame,
    *,
    tf_days: int,
    tf_label: str,
    last_bar_seq: int,
    last_time_close: pd.Timestamp,
) -> pd.DataFrame:
    """
    Build only new COMPLETE tf_days bars after last_time_close, continuing bar_seq.
    No partial bar at end.

    We enforce boundary continuity:
      first_new_bar.time_open = last_time_close + 1ms
    """
    if df_slice.empty:
        return pd.DataFrame()

    df = df_slice.sort_values("ts").reset_index(drop=True).copy()
    df["day_time_open"] = _make_day_time_open(df["ts"])

    # Future rows strictly after last bar close
    df_future = df[df["ts"] > last_time_close].copy()
    if df_future.empty:
        return pd.DataFrame()

    n = len(df_future)
    n_full = n // tf_days
    if n_full <= 0:
        return pd.DataFrame()

    df_use = df_future.iloc[: n_full * tf_days].copy()
    day_idx = np.arange(len(df_use), dtype=np.int64)
    df_use["bar_seq"] = (day_idx // tf_days) + (last_bar_seq + 1)

    rows: list[dict] = []
    for bar_seq, g in df_use.groupby("bar_seq", sort=True):
        if int(bar_seq) == last_bar_seq + 1:
            time_open = last_time_close + pd.Timedelta(milliseconds=1)
        else:
            time_open = g["day_time_open"].iloc[0]

        time_close = g["ts"].iloc[-1]

        open_ = g["open"].iloc[0]
        close_ = g["close"].iloc[-1]
        high_val = g["high"].max()
        low_val = g["low"].min()

        time_high = g.loc[g["high"] == high_val, "timehigh"].iloc[0]
        time_low = g.loc[g["low"] == low_val, "timelow"].iloc[0]

        volume_ = g["volume"].sum(skipna=True)
        market_cap_ = g["market_cap"].iloc[-1]

        rows.append(
            {
                "id": int(g["id"].iloc[0]),
                "tf": tf_label,
                "tf_days": int(tf_days),
                "bar_seq": int(bar_seq),
                "time_open": time_open,
                "time_close": time_close,
                "time_high": time_high,
                "time_low": time_low,
                "open": float(open_) if pd.notna(open_) else np.nan,
                "high": float(high_val) if pd.notna(high_val) else np.nan,
                "low": float(low_val) if pd.notna(low_val) else np.nan,
                "close": float(close_) if pd.notna(close_) else np.nan,
                "volume": float(volume_) if pd.notna(volume_) else np.nan,
                "market_cap": float(market_cap_) if pd.notna(market_cap_) else np.nan,
            }
        )

    out = pd.DataFrame.from_records(rows)
    if out.empty:
        return out

    out["bar_seq"] = out["bar_seq"].astype(np.int32)
    out["tf_days"] = out["tf_days"].astype(np.int32)

    # Continuity check inside appended block (boundary is enforced)
    _enforce_bar_continuity(out)
    return out


def build_bars(daily: pd.DataFrame, tf_list: list[tuple[int, str]]) -> pd.DataFrame:
    """
    Full build for all ids and all (tf_days, tf) in tf_list.
    """
    if daily.empty:
        return pd.DataFrame()

    daily = daily.sort_values(["id", "ts"]).reset_index(drop=True)

    parts: list[pd.DataFrame] = []
    for _, df_id in daily.groupby("id", sort=True):
        df_id = df_id.reset_index(drop=True)
        for tf_days, tf_label in tf_list:
            b = build_bars_for_id(df_id, tf_days=tf_days, tf_label=tf_label)
            if not b.empty:
                parts.append(b)

    if not parts:
        return pd.DataFrame()

    out = pd.concat(parts, ignore_index=True)
    out["bar_seq"] = out["bar_seq"].astype(np.int32)
    out["tf_days"] = out["tf_days"].astype(np.int32)
    return out


# =============================================================================
# Upsert
# =============================================================================

def make_upsert_sql(bars_table: str) -> str:
    return f"""
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


def upsert_bars(df_bars: pd.DataFrame, db_url: str, bars_table: str, batch_size: int = 25_000) -> None:
    if df_bars.empty:
        print("[bars_multi_tf] No bars to write.")
        return

    eng = get_engine(db_url)
    payload = df_bars.to_dict(orient="records")
    sql = make_upsert_sql(bars_table)

    with eng.begin() as conn:
        for i in range(0, len(payload), batch_size):
            conn.execute(text(sql), payload[i : i + batch_size])

    print(f"[bars_multi_tf] Upserted {len(df_bars):,} bar rows into {bars_table}.")


# =============================================================================
# Incremental driver
# =============================================================================

def refresh_incremental(
    *,
    db_url: str,
    ids: list[int],
    tf_list: list[tuple[int, str]],
    bars_table: str,
    state_table: str,
) -> None:
    ensure_state_table(db_url, state_table)

    daily_mm = load_daily_min_max(db_url, ids)
    if daily_mm.empty:
        print("[bars_multi_tf] No daily data found for requested ids.")
        return

    mm_map = {int(r["id"]): r for r in daily_mm.to_dict(orient="records")}

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

    for id_ in ids:
        mm = mm_map.get(int(id_))
        if mm is None:
            continue

        daily_min_ts: pd.Timestamp = mm["daily_min_ts"]
        daily_max_ts: pd.Timestamp = mm["daily_max_ts"]

        for tf_days, tf_label in tf_list:
            key = (int(id_), tf_label)
            st = state_map.get(key)

            last_bar = load_last_bar_info(db_url, bars_table, id_=int(id_), tf=tf_label)

            if st is None and last_bar is None:
                # first build for this (id, tf)
                df_full = load_daily_prices_for_id(db_url=db_url, id_=int(id_))
                bars = build_bars_for_id(df_full, tf_days=tf_days, tf_label=tf_label)
                if not bars.empty:
                    upsert_bars(bars, db_url=db_url, bars_table=bars_table)
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
                        "tf": tf_label,
                        "daily_min_seen": daily_min_ts,
                        "daily_max_seen": daily_max_ts,
                        "last_bar_seq": last_bar_seq,
                        "last_time_close": last_time_close,
                    }
                )
                continue

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

            if last_bar is None:
                # state exists but table missing -> rebuild
                df_full = load_daily_prices_for_id(db_url=db_url, id_=int(id_))
                bars = build_bars_for_id(df_full, tf_days=tf_days, tf_label=tf_label)
                if not bars.empty:
                    upsert_bars(bars, db_url=db_url, bars_table=bars_table)
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
                        "tf": tf_label,
                        "daily_min_seen": daily_min_ts,
                        "daily_max_seen": daily_max_ts,
                        "last_bar_seq": last_bar_seq,
                        "last_time_close": last_time_close,
                    }
                )
                continue

            last_bar_seq = int(last_bar["last_bar_seq"])
            last_time_close: pd.Timestamp = last_bar["last_time_close"]

            # Backfill detection: earlier history was added
            if daily_min_ts < daily_min_seen:
                print(
                    f"[bars_multi_tf] Backfill detected: id={id_}, tf={tf_label}, "
                    f"daily_min moved earlier {daily_min_seen} -> {daily_min_ts}. Rebuilding id/tf."
                )
                delete_bars_for_id_tf(db_url, bars_table, id_=int(id_), tf=tf_label)
                df_full = load_daily_prices_for_id(db_url=db_url, id_=int(id_))
                bars = build_bars_for_id(df_full, tf_days=tf_days, tf_label=tf_label)
                if not bars.empty:
                    upsert_bars(bars, db_url=db_url, bars_table=bars_table)
                    total_upsert += len(bars)
                total_rebuild += 1

                if not bars.empty:
                    last_bar_seq = int(bars["bar_seq"].max())
                    last_time_close = pd.to_datetime(bars.loc[bars["bar_seq"].idxmax(), "time_close"], utc=True)

                state_updates.append(
                    {
                        "id": int(id_),
                        "tf": tf_label,
                        "daily_min_seen": daily_min_ts,
                        "daily_max_seen": daily_max_ts,
                        "last_bar_seq": last_bar_seq,
                        "last_time_close": last_time_close,
                    }
                )
                continue

            # If no later daily data, noop (but keep state fresh)
            if daily_max_ts <= last_time_close:
                total_noop += 1
                state_updates.append(
                    {
                        "id": int(id_),
                        "tf": tf_label,
                        "daily_min_seen": min(daily_min_seen, daily_min_ts),
                        "daily_max_seen": max(daily_max_seen, daily_max_ts),
                        "last_bar_seq": last_bar_seq,
                        "last_time_close": last_time_close,
                    }
                )
                continue

            # Load a slice around the boundary to safely compute day_time_open.
            # We include the last close day as well (lookback 2 days is plenty).
            ts_start = last_time_close - pd.Timedelta(days=2)
            df_slice = load_daily_prices_for_id(db_url=db_url, id_=int(id_), ts_start=ts_start)
            if df_slice.empty:
                total_noop += 1
                continue

            new_bars = _build_incremental_new_bars_for_id(
                df_slice,
                tf_days=tf_days,
                tf_label=tf_label,
                last_bar_seq=last_bar_seq,
                last_time_close=last_time_close,
            )

            if new_bars.empty:
                total_noop += 1
                state_updates.append(
                    {
                        "id": int(id_),
                        "tf": tf_label,
                        "daily_min_seen": min(daily_min_seen, daily_min_ts),
                        "daily_max_seen": max(daily_max_seen, daily_max_ts),
                        "last_bar_seq": last_bar_seq,
                        "last_time_close": last_time_close,
                    }
                )
                continue

            upsert_bars(new_bars, db_url=db_url, bars_table=bars_table)
            total_upsert += len(new_bars)
            total_append += 1

            last_bar_seq2 = int(new_bars["bar_seq"].max())
            last_time_close2 = pd.to_datetime(new_bars.loc[new_bars["bar_seq"].idxmax(), "time_close"], utc=True)

            state_updates.append(
                {
                    "id": int(id_),
                    "tf": tf_label,
                    "daily_min_seen": min(daily_min_seen, daily_min_ts),
                    "daily_max_seen": max(daily_max_seen, daily_max_ts),
                    "last_bar_seq": last_bar_seq2,
                    "last_time_close": last_time_close2,
                }
            )

    upsert_state(db_url, state_table, state_updates)
    print(
        f"[bars_multi_tf] Done. upserted_rows={total_upsert:,} "
        f"rebuilds={total_rebuild} appends={total_append} noops={total_noop}"
    )


# =============================================================================
# CLI
# =============================================================================

def main(argv: Sequence[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description="Build tf_days-count price bars into public.cmc_price_bars_multi_tf."
    )
    ap.add_argument(
        "--ids",
        nargs="+",
        required=True,
        help="Asset ids (space- or comma-separated), or 'all'.",
    )
    ap.add_argument(
        "--db-url",
        default=None,
        help="Optional DB URL override. Defaults to TARGET_DB_URL env.",
    )
    ap.add_argument(
        "--include-non-canonical",
        action="store_true",
        help="If set, include dim_timeframe rows where is_canonical = FALSE.",
    )
    ap.add_argument(
        "--bars-table",
        default=DEFAULT_BARS_TABLE,
        help=f"Bars output table (default {DEFAULT_BARS_TABLE}).",
    )
    ap.add_argument(
        "--state-table",
        default=DEFAULT_STATE_TABLE,
        help=f"State table for incremental refresh (default {DEFAULT_STATE_TABLE}).",
    )
    ap.add_argument(
        "--full-rebuild",
        action="store_true",
        help="If set, run the legacy full rebuild path (loads all daily rows for ids and rebuilds all bars).",
    )
    args = ap.parse_args(list(argv) if argv is not None else None)

    db_url = resolve_db_url(args.db_url)
    ids = parse_ids(args.ids, db_url)

    tf_list = load_tf_list_from_dim_timeframe(
        db_url=db_url,
        include_non_canonical=bool(args.include_non_canonical),
    )
    print(f"[bars_multi_tf] tf_list size={len(tf_list)}: {[tf for _, tf in tf_list]}")

    if args.full_rebuild:
        # Legacy behavior preserved
        print(f"[bars_multi_tf] Loading daily prices for {len(ids)} ids ...")
        daily = load_daily_prices(ids=ids, db_url=db_url)
        print(f"[bars_multi_tf] Loaded {len(daily):,} daily rows.")
        if daily.empty:
            print("[bars_multi_tf] No daily data returned; exiting.")
            return

        print("[bars_multi_tf] Building bars (no partial bars) ...")
        bars = build_bars(daily=daily, tf_list=tf_list)
        print(f"[bars_multi_tf] Built {len(bars):,} bar rows.")

        print("[bars_multi_tf] Writing bars ...")
        upsert_bars(bars, db_url=db_url, bars_table=args.bars_table)
        return

    # Incremental default
    print(f"[bars_multi_tf] bars_table={args.bars_table}")
    print(f"[bars_multi_tf] state_table={args.state_table}")
    refresh_incremental(
        db_url=db_url,
        ids=ids,
        tf_list=tf_list,
        bars_table=args.bars_table,
        state_table=args.state_table,
    )


if __name__ == "__main__":
    main()
