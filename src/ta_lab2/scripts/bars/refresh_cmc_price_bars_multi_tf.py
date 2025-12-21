from __future__ import annotations

"""
Build tf_days-count "bar-state snapshots" into public.cmc_price_bars_multi_tf from public.cmc_price_histories7.

UPDATED SEMANTICS (append-only snapshots):
- For each (id, tf, bar_seq), emit ONE ROW PER DAILY CLOSE as the bar forms.
- The same bar_seq will therefore appear multiple times with different time_close values.
- is_partial_end = TRUE for in-progress snapshots (bar not yet complete).
- The snapshot where the bar completes (pos == tf_days) is_partial_end = FALSE.

Bar definition:
- tf_day style, row-count anchored to the FIRST available daily row per id (data-start anchoring).
- bar_seq increments every tf_days daily rows.
- There is ALWAYS a trailing partial bar if the series ends mid-bar (and it will have is_partial_end=TRUE).

NEW COMPLETENESS FLAGS (bar-quality metadata):
- is_partial_start: for this tf_day row-count series there is no external schedule window; always FALSE.
- is_partial_end: TRUE if snapshot position < tf_days (or bar is incomplete); FALSE only on the completion snapshot.
- is_missing_days: TRUE if within the included daily rows there is any gap > 1 day between consecutive timestamps.

Open-time continuity:
- For each daily row, define day_time_open = prior day close + 1ms
- For the first daily row in the series: day_time_open = ts - 1 day + 1ms (synthetic)
- For the first snapshot of a new bar, time_open = that day's day_time_open
- time_open remains constant across all snapshots within that bar_seq
- This ensures next bar opens exactly 1ms after prior bar close on the completion snapshot.

DB URL:
- Uses TARGET_DB_URL env var by default.
- Optional --db-url override is supported.

Ids:
- --ids all works (loads DISTINCT id from cmc_price_histories7)
- Or pass space / comma separated ids.

TF selection:
- Loaded from public.dim_timeframe:
    * alignment_type = 'tf_day'
    * calendar_scheme IS NULL
    * tf matches '^\\d+D$'
    * tf_qty >= 2 (so we do NOT emit 1D)
    * is_canonical = TRUE unless --include-non-canonical

INCREMENTAL (default):
- Backfill detection: if daily_min decreases vs stored state, rebuild that (id, tf) from scratch.
- Otherwise, append new snapshot rows for new daily closes after the last snapshot time_close.

IMPORTANT:
- Table must support multiple rows per (id, tf, bar_seq). Use a PK/unique key on:
    (id, tf, bar_seq, time_close)
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


def delete_bars_for_id_tf(db_url: str, bars_table: str, id_: int, tf: str) -> None:
    eng = get_engine(db_url)
    with eng.begin() as conn:
        conn.execute(
            text(f"DELETE FROM {bars_table} WHERE id=:id AND tf=:tf;"),
            {"id": int(id_), "tf": tf},
        )


def load_last_snapshot_info(db_url: str, bars_table: str, id_: int, tf: str) -> dict | None:
    """
    Returns the latest snapshot row for (id, tf), plus:
      - last_bar_seq
      - last_time_close (latest snapshot's time_close)
      - last_pos_in_bar = count of snapshots in that bar_seq (since one per day)
    """
    eng = get_engine(db_url)
    with eng.connect() as conn:
        row = conn.execute(
            text(
                f"""
                WITH last AS (
                  SELECT
                    id, tf,
                    MAX(bar_seq) AS last_bar_seq
                  FROM {bars_table}
                  WHERE id = :id AND tf = :tf
                  GROUP BY id, tf
                ),
                last_row AS (
                  SELECT b.*
                  FROM {bars_table} b
                  JOIN last l
                    ON b.id = l.id AND b.tf = l.tf AND b.bar_seq = l.last_bar_seq
                  ORDER BY b.time_close DESC
                  LIMIT 1
                ),
                pos AS (
                  SELECT COUNT(*)::int AS last_pos_in_bar
                  FROM {bars_table} b
                  JOIN last l
                    ON b.id = l.id AND b.tf = l.tf AND b.bar_seq = l.last_bar_seq
                )
                SELECT
                  (SELECT last_bar_seq FROM last) AS last_bar_seq,
                  (SELECT time_close FROM last_row) AS last_time_close,
                  (SELECT last_pos_in_bar FROM pos) AS last_pos_in_bar;
                """
            ),
            {"id": int(id_), "tf": tf},
        ).mappings().first()

    if not row or row["last_bar_seq"] is None or row["last_time_close"] is None:
        return None

    return {
        "last_bar_seq": int(row["last_bar_seq"]),
        "last_time_close": pd.to_datetime(row["last_time_close"], utc=True),
        "last_pos_in_bar": int(row["last_pos_in_bar"]) if row["last_pos_in_bar"] is not None else 0,
    }


def load_last_bar_snapshot_row(db_url: str, bars_table: str, id_: int, tf: str, bar_seq: int) -> dict | None:
    """
    Load the latest snapshot row for a specific bar_seq.
    Used to incrementally extend an in-progress bar.
    """
    eng = get_engine(db_url)
    with eng.connect() as conn:
        row = conn.execute(
            text(
                f"""
                SELECT *
                FROM {bars_table}
                WHERE id = :id AND tf = :tf AND bar_seq = :bar_seq
                ORDER BY time_close DESC
                LIMIT 1;
                """
            ),
            {"id": int(id_), "tf": tf, "bar_seq": int(bar_seq)},
        ).mappings().first()
    return dict(row) if row else None


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

    Guards (intent):
      - alignment_type = 'tf_day'
      - roll_policy    = 'multiple_of_tf'      (locks to the tf_day rolling family)
      - calendar_scheme IS NULL                (exclude calendar families)
      - tf_qty >= 2                            (so we don't emit 1D)
      - tf_days_nominal IS NOT NULL            (defensive)
      - is_intraday = FALSE                    (defensive; regex already excludes intraday)
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
          AND roll_policy = 'multiple_of_tf'
          AND calendar_scheme IS NULL
          AND tf_qty >= 2
          AND tf_days_nominal IS NOT NULL
          AND is_intraday = FALSE
        ORDER BY sort_order, tf;
        """
    )

    with eng.connect() as conn:
        rows = conn.execute(sql).mappings().all()

    out: list[tuple[int, str]] = []
    for r in rows:
        tf = str(r["tf"])

        # Final guardrail even though tf_day naming is enforced by dim_timeframe checks.
        if not _TF_DAY_LABEL_RE.match(tf):
            continue

        if (not include_non_canonical) and (not bool(r["is_canonical"])):
            continue

        tf_days_nominal = r["tf_days_nominal"]
        if tf_days_nominal is None:
            # Friendlier error if running against a stale/incorrect schema or bad data.
            raise RuntimeError(
                f"dim_timeframe.tf_days_nominal is NULL for tf={tf}. "
                "This script requires a positive integer day-count for tf_day rows."
            )

        tf_days = int(tf_days_nominal)
        out.append((tf_days, tf))

    if not out:
        raise RuntimeError(
            "No TFs selected from dim_timeframe for cmc_price_bars_multi_tf. "
            "Check dim_timeframe rows (alignment_type='tf_day', roll_policy='multiple_of_tf', "
            "calendar_scheme IS NULL, tf like '30D', tf_qty>=2, tf_days_nominal not null, is_intraday=FALSE)."
        )

    return out

# =============================================================================
# Bar building (snapshots)
# =============================================================================

def _make_day_time_open(ts: pd.Series) -> pd.Series:
    one_ms = pd.Timedelta(milliseconds=1)
    day_open = ts.shift(1) + one_ms
    if len(ts) > 0:
        day_open.iloc[0] = ts.iloc[0] - pd.Timedelta(days=1) + one_ms
    return day_open


def _has_missing_days(ts: pd.Series) -> bool:
    if ts is None or len(ts) <= 1:
        return False
    t = pd.to_datetime(ts, utc=True).sort_values()
    return bool((t.diff() > pd.Timedelta(days=1)).any())

def _count_missing_days(ts: pd.Series) -> int:
    """Count missing *interior* days based on >1-day gaps between observed timestamps.

    For example, if consecutive observed days differ by 3 days, that implies 2 missing days.
    This matches _has_missing_days(), but returns the magnitude instead of a boolean.
    """
    if ts is None or len(ts) <= 1:
        return 0
    t = pd.to_datetime(ts, utc=True).sort_values()
    gaps = t.diff()
    if gaps is None:
        return 0
    # How many whole days are between stamps, minus the 1 day we expected
    gap_days = (gaps / pd.Timedelta(days=1)).fillna(0).astype(int) - 1
    return int(gap_days[gap_days > 0].sum())



def build_snapshots_for_id(
    df_id: pd.DataFrame,
    *,
    tf_days: int,
    tf_label: str,
) -> pd.DataFrame:
    """
    Full build for a single id + tf_days, emitting ONE ROW PER DAY per bar_seq (append-only snapshots).
    """
    if df_id.empty:
        return pd.DataFrame()

    df_id = df_id.sort_values("ts").reset_index(drop=True).copy()
    df_id["day_time_open"] = _make_day_time_open(df_id["ts"])

    n = len(df_id)
    if n <= 0:
        return pd.DataFrame()

    # bar_seq by row-count anchoring to first row
    day_idx = np.arange(n, dtype=np.int64)
    df_id["bar_seq"] = (day_idx // tf_days) + 1
    df_id["pos_in_bar"] = (day_idx % tf_days) + 1

    rows: list[dict] = []
    id_val = int(df_id["id"].iloc[0])

    for bar_seq, g in df_id.groupby("bar_seq", sort=True):
        g = g.reset_index(drop=True)

        # Constant bar open = day_time_open of first day in the bar
        bar_time_open = g["day_time_open"].iloc[0]

        # Emit snapshots for k=1..len(g)
        for k in range(1, len(g) + 1):
            s = g.iloc[:k]

            time_close = s["ts"].iloc[-1]
            open_ = s["open"].iloc[0]
            close_ = s["close"].iloc[-1]
            high_val = s["high"].max()
            low_val = s["low"].min()

            time_high = s.loc[s["high"] == high_val, "timehigh"].iloc[0]
            time_low = s.loc[s["low"] == low_val, "timelow"].iloc[0]

            volume_ = s["volume"].sum(skipna=True)
            market_cap_ = s["market_cap"].iloc[-1]

            # Flags
            is_partial_start = False
            is_partial_end = (k < tf_days)  # completion snapshot only is false
            is_missing_days = _has_missing_days(s["ts"])

            # Formation counters (append-friendly)
            count_days = int(k)
            count_days_remaining = int(tf_days - k)

            # Missing-gap counters (interior-only for tf_day bars)
            count_missing_days_interior = _count_missing_days(s["ts"])
            count_missing_days_start = 0
            count_missing_days_end = 0
            count_missing_days = count_missing_days_interior
            missing_days_where = "interior" if count_missing_days_interior > 0 else None

            rows.append(
                {
                    "id": id_val,
                    "tf": tf_label,
                    "tf_days": int(tf_days),
                    "bar_seq": int(bar_seq),
                    "time_open": bar_time_open,
                    "time_close": time_close,
                    "time_high": time_high,
                    "time_low": time_low,
                    "open": float(open_) if pd.notna(open_) else np.nan,
                    "high": float(high_val) if pd.notna(high_val) else np.nan,
                    "low": float(low_val) if pd.notna(low_val) else np.nan,
                    "close": float(close_) if pd.notna(close_) else np.nan,
                    "volume": float(volume_) if pd.notna(volume_) else np.nan,
                    "market_cap": float(market_cap_) if pd.notna(market_cap_) else np.nan,
                    "is_partial_start": bool(is_partial_start),
                    "is_partial_end": bool(is_partial_end),
                    "is_missing_days": bool(is_missing_days),

                    # New columns
                    "count_days": count_days,
                    "count_days_remaining": count_days_remaining,
                    "count_missing_days": count_missing_days,
                    "count_missing_days_start": count_missing_days_start,
                    "count_missing_days_end": count_missing_days_end,
                    "count_missing_days_interior": count_missing_days_interior,
                    "missing_days_where": missing_days_where,
                }
            )

    out = pd.DataFrame.from_records(rows)
    if out.empty:
        return out

    out["bar_seq"] = out["bar_seq"].astype(np.int32)
    out["tf_days"] = out["tf_days"].astype(np.int32)

    # New counters
    out["count_days"] = out["count_days"].astype(np.int32)
    out["count_days_remaining"] = out["count_days_remaining"].astype(np.int32)
    out["count_missing_days"] = out["count_missing_days"].astype(np.int32)
    out["count_missing_days_start"] = out["count_missing_days_start"].astype(np.int32)
    out["count_missing_days_end"] = out["count_missing_days_end"].astype(np.int32)
    out["count_missing_days_interior"] = out["count_missing_days_interior"].astype(np.int32)
    # missing_days_where stays as nullable text

    out["is_partial_start"] = out["is_partial_start"].astype(bool)
    out["is_partial_end"] = out["is_partial_end"].astype(bool)
    out["is_missing_days"] = out["is_missing_days"].astype(bool)
    return out


def build_all_snapshots(daily: pd.DataFrame, tf_list: list[tuple[int, str]]) -> pd.DataFrame:
    if daily.empty:
        return pd.DataFrame()

    daily = daily.sort_values(["id", "ts"]).reset_index(drop=True)

    parts: list[pd.DataFrame] = []
    for _, df_id in daily.groupby("id", sort=True):
        df_id = df_id.reset_index(drop=True)
        for tf_days, tf_label in tf_list:
            b = build_snapshots_for_id(df_id, tf_days=tf_days, tf_label=tf_label)
            if not b.empty:
                parts.append(b)

    if not parts:
        return pd.DataFrame()

    out = pd.concat(parts, ignore_index=True)
    out["bar_seq"] = out["bar_seq"].astype(np.int32)
    out["tf_days"] = out["tf_days"].astype(np.int32)

    # New counters
    out["count_days"] = out["count_days"].astype(np.int32)
    out["count_days_remaining"] = out["count_days_remaining"].astype(np.int32)
    out["count_missing_days"] = out["count_missing_days"].astype(np.int32)
    out["count_missing_days_start"] = out["count_missing_days_start"].astype(np.int32)
    out["count_missing_days_end"] = out["count_missing_days_end"].astype(np.int32)
    out["count_missing_days_interior"] = out["count_missing_days_interior"].astype(np.int32)
    # missing_days_where stays as nullable text

    out["is_partial_start"] = out["is_partial_start"].astype(bool)
    out["is_partial_end"] = out["is_partial_end"].astype(bool)
    out["is_missing_days"] = out["is_missing_days"].astype(bool)
    return out


# =============================================================================
# Upsert (append-friendly)
# =============================================================================

def make_upsert_sql(bars_table: str) -> str:
    """
    IMPORTANT: conflict target includes time_close to support append-only snapshots.
    Requires a PK/unique index on (id, tf, bar_seq, time_close).
    """
    return f"""
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
      tf_days                     = EXCLUDED.tf_days,
      time_open                   = EXCLUDED.time_open,
      time_high                   = EXCLUDED.time_high,
      time_low                    = EXCLUDED.time_low,
      open                        = EXCLUDED.open,
      high                        = EXCLUDED.high,
      low                         = EXCLUDED.low,
      close                       = EXCLUDED.close,
      volume                      = EXCLUDED.volume,
      market_cap                  = EXCLUDED.market_cap,
      is_partial_start            = EXCLUDED.is_partial_start,
      is_partial_end              = EXCLUDED.is_partial_end,
      is_missing_days             = EXCLUDED.is_missing_days,

      count_days                  = EXCLUDED.count_days,
      count_days_remaining        = EXCLUDED.count_days_remaining,
      count_missing_days          = EXCLUDED.count_missing_days,
      count_missing_days_start    = EXCLUDED.count_missing_days_start,
      count_missing_days_end      = EXCLUDED.count_missing_days_end,
      count_missing_days_interior = EXCLUDED.count_missing_days_interior,
      missing_days_where          = EXCLUDED.missing_days_where,

      ingested_at                 = now();

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

    print(f"[bars_multi_tf] Upserted {len(df_bars):,} snapshot rows into {bars_table}.")


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

            last = load_last_snapshot_info(db_url, bars_table, id_=int(id_), tf=tf_label)

            if st is None and last is None:
                # first build for this (id, tf)
                df_full = load_daily_prices_for_id(db_url=db_url, id_=int(id_))
                bars = build_snapshots_for_id(df_full, tf_days=tf_days, tf_label=tf_label)
                if not bars.empty:
                    upsert_bars(bars, db_url=db_url, bars_table=bars_table)
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
                if st is not None and pd.notna(st.get("daily_min_seen"))
                else daily_min_ts
            )

            daily_max_seen = (
                pd.to_datetime(st["daily_max_seen"], utc=True)
                if st is not None and pd.notna(st.get("daily_max_seen"))
                else daily_max_ts
        )


            # Table exists but state missing -> seed state from table
            if st is None and last is not None:
                state_updates.append(
                    {
                        "id": int(id_),
                        "tf": tf_label,
                        "daily_min_seen": daily_min_ts,
                        "daily_max_seen": daily_max_ts,
                        "last_bar_seq": int(last["last_bar_seq"]),
                        "last_time_close": last["last_time_close"],
                    }
                )
                continue

            # Backfill detection: earlier history was added
            if daily_min_ts < daily_min_seen:
                print(
                    f"[bars_multi_tf] Backfill detected: id={id_}, tf={tf_label}, "
                    f"daily_min moved earlier {daily_min_seen} -> {daily_min_ts}. Rebuilding id/tf."
                )
                delete_bars_for_id_tf(db_url, bars_table, id_=int(id_), tf=tf_label)
                df_full = load_daily_prices_for_id(db_url=db_url, id_=int(id_))
                bars = build_snapshots_for_id(df_full, tf_days=tf_days, tf_label=tf_label)
                if not bars.empty:
                    upsert_bars(bars, db_url=db_url, bars_table=bars_table)
                    total_upsert += len(bars)
                total_rebuild += 1

                last_bar_seq = int(bars["bar_seq"].max()) if not bars.empty else None
                last_time_close = pd.to_datetime(bars["time_close"].max(), utc=True) if not bars.empty else None

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
            last_time_close = (
                pd.to_datetime(st["last_time_close"], utc=True)
                if st and pd.notna(st.get("last_time_close"))
                else None
            )

            last_bar_seq = (
                int(st["last_bar_seq"])
                if st and pd.notna(st.get("last_bar_seq"))
                else None
            )

            # If state missing close, fall back to table
            if last_time_close is None or last_bar_seq is None:
                last_tbl = load_last_snapshot_info(db_url, bars_table, id_=int(id_), tf=tf_label)
                if last_tbl is None:
                    total_noop += 1
                    continue
                last_time_close = last_tbl["last_time_close"]
                last_bar_seq = int(last_tbl["last_bar_seq"])

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

            # Load new daily rows strictly after last snapshot close
            df_new = load_daily_prices_for_id(db_url=db_url, id_=int(id_), ts_start=last_time_close - pd.Timedelta(days=2))
            if df_new.empty:
                total_noop += 1
                continue
            df_new = df_new[df_new["ts"] > last_time_close].copy()
            if df_new.empty:
                total_noop += 1
                continue

            # We need to extend either:
            # - current bar_seq (if incomplete), or
            # - start new bar_seq (if last_pos == tf_days)
            last_tbl = load_last_snapshot_info(db_url, bars_table, id_=int(id_), tf=tf_label)
            if last_tbl is None:
                total_noop += 1
                continue

            cur_bar_seq = int(last_tbl["last_bar_seq"])
            cur_pos = int(last_tbl["last_pos_in_bar"])

            # Load last snapshot row for current bar_seq to carry aggregates
            last_row = load_last_bar_snapshot_row(db_url, bars_table, id_=int(id_), tf=tf_label, bar_seq=cur_bar_seq)
            if last_row is None:
                total_noop += 1
                continue

            # Normalize timestamps from DB row
            prev_time_close = pd.to_datetime(last_row["time_close"], utc=True)
            prev_time_open = pd.to_datetime(last_row["time_open"], utc=True)
            prev_high = float(last_row["high"]) if last_row["high"] is not None else np.nan
            prev_low = float(last_row["low"]) if last_row["low"] is not None else np.nan
            prev_volume = float(last_row["volume"]) if last_row["volume"] is not None else 0.0
            prev_market_cap = float(last_row["market_cap"]) if last_row["market_cap"] is not None else np.nan
            prev_time_high = pd.to_datetime(last_row["time_high"], utc=True) if last_row.get("time_high") is not None else pd.NaT
            prev_time_low = pd.to_datetime(last_row["time_low"], utc=True) if last_row.get("time_low") is not None else pd.NaT

            new_rows: list[dict] = []

            # Build a rolling list of timestamps for missing-days detection within the active bar
            # We can reconstruct it from the DB snapshots count by querying the last bar snapshots' time_close series.
            eng = get_engine(db_url)
            with eng.connect() as conn:
                ts_series = pd.read_sql(
                    text(
                        f"""
                        SELECT time_close
                        FROM {bars_table}
                        WHERE id = :id AND tf = :tf AND bar_seq = :bar_seq
                        ORDER BY time_close;
                        """
                    ),
                    conn,
                    params={"id": int(id_), "tf": tf_label, "bar_seq": int(cur_bar_seq)},
                )
            cur_bar_closes = pd.to_datetime(ts_series["time_close"], utc=True).tolist()

            for _, d in df_new.iterrows():
                day_ts: pd.Timestamp = pd.to_datetime(d["ts"], utc=True)
                day_open = prev_time_close + pd.Timedelta(milliseconds=1)

                # Determine whether we are continuing current bar or starting a new one
                if cur_pos >= tf_days:
                    # start new bar
                    cur_bar_seq += 1
                    cur_pos = 0

                    prev_time_open = day_open
                    prev_high = float(d["high"]) if pd.notna(d["high"]) else np.nan
                    prev_low = float(d["low"]) if pd.notna(d["low"]) else np.nan
                    prev_volume = float(d["volume"]) if pd.notna(d["volume"]) else 0.0
                    prev_market_cap = float(d["market_cap"]) if pd.notna(d["market_cap"]) else np.nan
                    prev_time_high = pd.to_datetime(d["timehigh"], utc=True)
                    prev_time_low = pd.to_datetime(d["timelow"], utc=True)
                    cur_bar_closes = []

                # extend current bar
                cur_pos += 1
                cur_bar_closes.append(day_ts)

                day_high = float(d["high"]) if pd.notna(d["high"]) else np.nan
                day_low = float(d["low"]) if pd.notna(d["low"]) else np.nan

                # Update high/time_high
                new_high = prev_high
                new_time_high = prev_time_high
                if pd.isna(new_high) or (pd.notna(day_high) and day_high > new_high):
                    new_high = day_high
                    new_time_high = pd.to_datetime(d["timehigh"], utc=True)

                # Update low/time_low
                new_low = prev_low
                new_time_low = prev_time_low
                if pd.isna(new_low) or (pd.notna(day_low) and day_low < new_low):
                    new_low = day_low
                    new_time_low = pd.to_datetime(d["timelow"], utc=True)

                new_volume = prev_volume + (float(d["volume"]) if pd.notna(d["volume"]) else 0.0)
                new_market_cap = float(d["market_cap"]) if pd.notna(d["market_cap"]) else prev_market_cap

                # Flags
                is_partial_start = False
                is_partial_end = (cur_pos < tf_days)
                is_missing_days = _has_missing_days(pd.Series(cur_bar_closes))

                # Formation counters
                count_days = int(cur_pos)
                count_days_remaining = int(tf_days - cur_pos)

                # Missing-gap counters (interior-only for tf_day bars)
                count_missing_days_interior = _count_missing_days(pd.Series(cur_bar_closes))
                count_missing_days_start = 0
                count_missing_days_end = 0
                count_missing_days = count_missing_days_interior
                missing_days_where = "interior" if count_missing_days_interior > 0 else None

                new_rows.append(
                    {
                        "id": int(id_),
                        "tf": tf_label,
                        "tf_days": int(tf_days),
                        "bar_seq": int(cur_bar_seq),
                        "time_open": prev_time_open,
                        "time_close": day_ts,
                        "time_high": new_time_high,
                        "time_low": new_time_low,
                        "open": float(d["open"]) if pd.notna(d["open"]) and cur_pos == 1 else float(last_row["open"]) if cur_pos > 1 else float(d["open"]) if pd.notna(d["open"]) else np.nan,
                        "high": float(new_high) if pd.notna(new_high) else np.nan,
                        "low": float(new_low) if pd.notna(new_low) else np.nan,
                        "close": float(d["close"]) if pd.notna(d["close"]) else np.nan,
                        "volume": float(new_volume),
                        "market_cap": float(new_market_cap) if pd.notna(new_market_cap) else np.nan,
                        "is_partial_start": bool(is_partial_start),
                        "is_partial_end": bool(is_partial_end),
                        "is_missing_days": bool(is_missing_days),

                        # New columns
                        "count_days": count_days,
                        "count_days_remaining": count_days_remaining,
                        "count_missing_days": count_missing_days,
                        "count_missing_days_start": count_missing_days_start,
                        "count_missing_days_end": count_missing_days_end,
                        "count_missing_days_interior": count_missing_days_interior,
                        "missing_days_where": missing_days_where,
                    }
                )

                # advance prev pointers
                prev_time_close = day_ts
                prev_high = new_high
                prev_low = new_low
                prev_volume = new_volume
                prev_market_cap = new_market_cap
                prev_time_high = new_time_high
                prev_time_low = new_time_low

            if not new_rows:
                total_noop += 1
                continue

            df_out = pd.DataFrame(new_rows)
            upsert_bars(df_out, db_url=db_url, bars_table=bars_table)
            total_upsert += len(df_out)
            total_append += 1

            state_updates.append(
                {
                    "id": int(id_),
                    "tf": tf_label,
                    "daily_min_seen": min(daily_min_seen, daily_min_ts),
                    "daily_max_seen": max(daily_max_seen, daily_max_ts),
                    "last_bar_seq": int(df_out["bar_seq"].max()),
                    "last_time_close": pd.to_datetime(df_out["time_close"].max(), utc=True),
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
        description="Build tf_days-count bar-state snapshots into public.cmc_price_bars_multi_tf."
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
        help="If set, rebuild snapshots for all ids/tfs from full daily history.",
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
        print(f"[bars_multi_tf] Full rebuild: building snapshots for {len(ids)} ids ...")
        parts: list[pd.DataFrame] = []
        for id_ in ids:
            df_full = load_daily_prices_for_id(db_url=db_url, id_=int(id_))
            if df_full.empty:
                continue
            for tf_days, tf_label in tf_list:
                parts.append(build_snapshots_for_id(df_full, tf_days=tf_days, tf_label=tf_label))

        if not parts:
            print("[bars_multi_tf] No snapshots built; exiting.")
            return

        bars = pd.concat([p for p in parts if p is not None and not p.empty], ignore_index=True)
        print(f"[bars_multi_tf] Built {len(bars):,} snapshot rows.")
        upsert_bars(bars, db_url=db_url, bars_table=args.bars_table)
        return

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
