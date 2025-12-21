from __future__ import annotations

"""
Multi-timeframe EMA builder for cmc_ema_multi_tf (tf_day family), redesigned to:

1) Leverage dim_timeframe as the source of truth for timeframes (NO hardcoding).
2) Consume persisted tf_day bars (public.cmc_price_bars_multi_tf) for canonical TF closes
   WHEN AVAILABLE, but FALL BACK to synthetic tf_day bars computed from daily closes if
   the bars table does not contain the TF yet.
3) Use daily closes to compute preview EMA values between canonical closes.

Semantics (unchanged conceptually):

For each (id, tf, period=p):

- Canonical EMA is computed ONLY on TRUE TF closes using period=p TF bars:

      ema_bar_k = alpha_bar * close_bar_k + (1 - alpha_bar) * ema_bar_{k-1}
      alpha_bar = 2 / (p + 1)

  Canonical values appear on rows with roll = FALSE.

- On daily rows between TF closes, compute preview EMA:

      ema_preview_t = alpha_bar * close_t + (1 - alpha_bar) * ema_prev_bar

  where ema_prev_bar is the EMA of the last completed TF bar.
  Preview values do NOT feed into future canonical EMA updates.

Derivatives (per doc):

- d1 / d2: DAILY derivatives computed for ALL rows (roll TRUE and FALSE).
- d1_roll / d2_roll: derivatives computed ONLY across canonical endpoints (roll=FALSE).
"""

from typing import Iterable, Dict, List

import numpy as np
import pandas as pd
from sqlalchemy import text

from ta_lab2.io import _get_marketdata_engine as _get_engine, load_cmc_ohlcv_daily
from ta_lab2.features.ema import compute_ema
from ta_lab2.time.dim_timeframe import list_tfs, get_tf_days

__all__ = [
    "build_multi_timeframe_ema_frame",
    "write_multi_timeframe_ema_to_db",
]


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def _normalize_daily(daily: pd.DataFrame) -> pd.DataFrame:
    """
    Ensure daily OHLCV has columns: id, ts, close (and optionally open/high/low/volume).
    Normalize ts to tz-aware UTC and sort by (id, ts).
    """
    df = daily.copy()

    if isinstance(df.index, pd.MultiIndex):
        idx_names = list(df.index.names or [])
        if "id" in idx_names and ("ts" in idx_names or "timeclose" in idx_names or "timestamp" in idx_names):
            df = df.reset_index()

    cols_lower = {c.lower(): c for c in df.columns}
    if "ts" not in df.columns:
        if "timeclose" in cols_lower:
            df = df.rename(columns={cols_lower["timeclose"]: "ts"})
        elif "timestamp" in cols_lower:
            df = df.rename(columns={cols_lower["timestamp"]: "ts"})
        elif "date" in cols_lower:
            df = df.rename(columns={cols_lower["date"]: "ts"})
        else:
            raise ValueError("Could not find a timestamp-like column for daily data.")

    required = {"id", "ts", "close"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Daily OHLCV missing required columns: {missing}")

    if "open" not in df.columns:
        df["open"] = df["close"]
    if "high" not in df.columns:
        df["high"] = df["close"]
    if "low" not in df.columns:
        df["low"] = df["close"]
    if "volume" not in df.columns:
        df["volume"] = 0.0

    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df = df.sort_values(["id", "ts"]).reset_index(drop=True)
    return df


def _resolve_tf_day_timeframes(
    *,
    db_url: str | None,
    tf_subset: Iterable[str] | None,
) -> Dict[str, int]:
    """
    Return mapping: tf_label -> tf_days, sourced from dim_timeframe,
    but ONLY for explicit day-count TF labels (numeric + 'D').

    Soft behavior:
      - If tf_subset contains non-D labels (e.g., '2W', '1M'), they are dropped.
      - If tf_subset becomes empty after filtering, we fall back to ALL day-label TFs.
    """
    if db_url is None:
        raise ValueError("db_url is required because timeframes must come from dim_timeframe.")

    all_tf_day = list_tfs(db_url=db_url, alignment_type="tf_day", canonical_only=True)
    if not all_tf_day:
        raise ValueError("dim_timeframe returned no canonical tf_day timeframes.")

    def _is_day_label(tf: str) -> bool:
        tf = (tf or "").strip()
        return tf.endswith("D") and tf[:-1].isdigit()

    # Candidate universe: only numeric+D labels from dim_timeframe
    all_tf_day_d = [tf for tf in all_tf_day if _is_day_label(tf)]
    if not all_tf_day_d:
        raise ValueError(
            "dim_timeframe returned no canonical tf_day timeframes matching day-label format (e.g. '14D')."
        )

    if tf_subset is None:
        chosen = all_tf_day_d
    else:
        raw = [t.strip() for t in tf_subset if t is not None and str(t).strip()]

        dropped_non_d = [t for t in raw if not _is_day_label(t)]
        kept_d = [t for t in raw if _is_day_label(t)]

        if dropped_non_d:
            print(
                "[multi_tf_v2] NOTE: Dropping non-day TF labels from tf_subset "
                f"(only numeric+'D' allowed): {sorted(set(dropped_non_d))}"
            )

        # If user provided only non-D labels, fall back to ALL day-label TFs
        if not kept_d:
            print(
                "[multi_tf_v2] NOTE: tf_subset contained no valid day-label TFs; "
                "falling back to ALL day-label tf_day timeframes from dim_timeframe."
            )
            chosen = all_tf_day_d
        else:
            # Keep only those that actually exist in dim_timeframe's day-label set
            missing = sorted(set(kept_d) - set(all_tf_day_d))
            if missing:
                print(
                    "[multi_tf_v2] NOTE: Some requested day-label TFs were not found in dim_timeframe "
                    f"and will be ignored: {missing}"
                )
            chosen = [t for t in kept_d if t in set(all_tf_day_d)]

            # If everything got filtered out as "missing", also fall back
            if not chosen:
                print(
                    "[multi_tf_v2] NOTE: After filtering missing TFs, none remain; "
                    "falling back to ALL day-label tf_day timeframes from dim_timeframe."
                )
                chosen = all_tf_day_d

    tf_days_map: Dict[str, int] = {}
    for tf in chosen:
        tf_days_map[tf] = int(get_tf_days(tf, db_url=db_url))
        if tf_days_map[tf] <= 0:
            raise ValueError(f"Invalid tf_days={tf_days_map[tf]} for tf='{tf}' in dim_timeframe.")

    return tf_days_map


def _load_bar_closes(
    *,
    ids: list[int],
    tf: str,
    db_url: str | None,
    schema: str,
    bars_table: str,
    end: str | None,
) -> pd.DataFrame:
    """
    Load canonical TF closes from the persisted tf_day bars table.

    Required columns in {schema}.{bars_table}:
        id, tf, bar_seq, time_close, close, is_partial_end

    This script defines "canonical TF closes" as the **completion snapshots**:
        is_partial_end = FALSE

    Note: Because the bars table is append-only daily snapshots, there can be many rows
    per (id, tf, bar_seq). The completion snapshot is unique per bar_seq and is the
    canonical close for that bar.
    """
    engine = _get_engine(db_url)
    end_ts = pd.to_datetime(end, utc=True) if end is not None else None

    sql = f"""
    SELECT
      id,
      tf,
      bar_seq,
      time_close,
      close AS close_bar
    FROM {schema}.{bars_table}
    WHERE tf = :tf
      AND id = ANY(:ids)
      AND is_partial_end = FALSE
      {"" if end_ts is None else "AND time_close <= :end_ts"}
    ORDER BY id, bar_seq;
    """

    params = {"tf": tf, "ids": ids}
    if end_ts is not None:
        params["end_ts"] = end_ts

    with engine.begin() as conn:
        df = pd.read_sql(text(sql), conn, params=params)

    if df.empty:
        return df

    df["time_close"] = pd.to_datetime(df["time_close"], utc=True)
    return df.sort_values(["id", "bar_seq"]).reset_index(drop=True)


def _synthetic_tf_day_bars_from_daily(
    *,
    df_id_daily: pd.DataFrame,
    tf: str,
    tf_days: int,
) -> pd.DataFrame:
    """
    Fallback for v1 when persisted bars are missing.

    Build synthetic tf_day bars by selecting daily rows at canonical boundaries:

        canonical indices: (tf_days-1), (2*tf_days-1), ...

    Then exclude the last (incomplete) bar so synthetic output matches the persisted-bars behavior (no completion snapshot yet).
    """
    if df_id_daily.empty:
        return pd.DataFrame(columns=["id", "tf", "bar_seq", "time_close", "close_bar"])

    d = df_id_daily.sort_values("ts").reset_index(drop=True)
    n = len(d)
    if tf_days <= 0 or n < tf_days:
        return pd.DataFrame(columns=["id", "tf", "bar_seq", "time_close", "close_bar"])

    idx = np.arange(tf_days - 1, n, tf_days, dtype=int)
    if idx.size == 0:
        return pd.DataFrame(columns=["id", "tf", "bar_seq", "time_close", "close_bar"])

    bars = pd.DataFrame({
        "id": int(d.loc[0, "id"]),
        "tf": tf,
        "bar_seq": np.arange(1, idx.size + 1, dtype=int),
        "time_close": d.loc[idx, "ts"].to_numpy(),
        "close_bar": d.loc[idx, "close"].astype(float).to_numpy(),
    })

    # Exclude the last (incomplete) bar (matches _load_bar_closes behavior: only completion snapshots are canonical).
    if len(bars) >= 1:
        bars = bars.iloc[:-1].copy()

    return bars.reset_index(drop=True)


# -----------------------------------------------------------------------------
# Main builder
# -----------------------------------------------------------------------------

def build_multi_timeframe_ema_frame(
    ids: Iterable[int],
    start: str | None = "2010-01-01",
    end: str | None = None,
    ema_periods: Iterable[int] = (6, 9, 10, 12, 14, 17, 20, 21, 26, 30, 50, 52, 77, 100, 200, 252, 365),
    tf_subset: Iterable[str] | None = None,
    *,
    db_url: str | None = None,
    bars_schema: str = "public",
    bars_table_tf_day: str = "cmc_price_bars_multi_tf",
) -> pd.DataFrame:
    """
    Build longform EMAs on a DAILY grid for all canonical tf_day timeframes
    in dim_timeframe (or a validated subset).

    Canonical TF closes come from {bars_schema}.{bars_table_tf_day} when available;
    otherwise synthetic tf_day bars are derived from the daily series.
    """
    ids = list(ids)
    if not ids:
        raise ValueError("ids must be a non-empty iterable of asset ids")

    ema_periods = [int(p) for p in ema_periods]
    if any(p <= 0 for p in ema_periods):
        raise ValueError("ema_periods must be positive integers")

    tf_days_map = _resolve_tf_day_timeframes(db_url=db_url, tf_subset=tf_subset)

    # Load enough history for EMA stability; output is filtered to [start, end].
    daily = load_cmc_ohlcv_daily(
        ids=ids,
        start="2010-01-01",
        end=end,
        db_url=db_url,
        tz="UTC",
    )
    daily = _normalize_daily(daily)

    frames: List[pd.DataFrame] = []

    for tf, tf_days in tf_days_map.items():
        print(f"Processing tf={tf}, tf_days={tf_days} (tf_day from dim_timeframe).")

        # Try persisted bars first (fast / authoritative), but don't require them.
        bars_all = _load_bar_closes(
            ids=ids,
            tf=tf,
            db_url=db_url,
            schema=bars_schema,
            bars_table=bars_table_tf_day,
            end=end,
        )

        for asset_id in ids:
            df_id = daily[daily["id"] == asset_id].copy()
            if df_id.empty:
                continue

            # Bars for this asset+tf: persisted if present, else synthetic.
            if not bars_all.empty:
                bars_id = bars_all[bars_all["id"] == asset_id].copy()
            else:
                bars_id = pd.DataFrame()

            if bars_id.empty:
                bars_id = _synthetic_tf_day_bars_from_daily(df_id_daily=df_id, tf=tf, tf_days=tf_days)

            if bars_id.empty:
                continue

            df_id = df_id.sort_values("ts").reset_index(drop=True)
            df_id["close"] = df_id["close"].astype(float)

            closes = bars_id[["time_close", "close_bar", "bar_seq"]].copy()
            closes = closes.rename(columns={"time_close": "ts"})
            closes["ts"] = pd.to_datetime(closes["ts"], utc=True)

            # Daily grid with canonical close markers
            grid = df_id[["ts", "close"]].merge(
                closes[["ts", "close_bar", "bar_seq"]],
                on="ts",
                how="left",
            )

            # Bar-close series in bar order, for canonical EMA state updates
            df_closes = closes[["ts", "close_bar", "bar_seq"]].sort_values("bar_seq").reset_index(drop=True)

            for p in ema_periods:
                ema_bar = compute_ema(
                    df_closes["close_bar"].astype(float),
                    period=p,
                    adjust=False,
                    min_periods=p,
                )

                bar_df = df_closes[["ts"]].copy()
                bar_df["ema_bar"] = ema_bar
                bar_df = bar_df[bar_df["ema_bar"].notna()]
                if bar_df.empty:
                    continue

                alpha_bar = 2.0 / (p + 1.0)

                tmp = grid.merge(bar_df, on="ts", how="left")
                tmp["ema_prev_bar"] = tmp["ema_bar"].ffill().shift(1)

                tmp["ema_preview"] = alpha_bar * tmp["close"] + (1.0 - alpha_bar) * tmp["ema_prev_bar"]

                tmp["ema"] = tmp["ema_preview"]
                mask_bar = tmp["ema_bar"].notna()
                tmp.loc[mask_bar, "ema"] = tmp.loc[mask_bar, "ema_bar"]

                # drop until the first usable EMA exists
                tmp = tmp[tmp["ema"].notna()]
                if tmp.empty:
                    continue

                tmp["id"] = asset_id
                tmp["tf"] = tf
                tmp["period"] = p
                tmp["tf_days"] = tf_days

                is_close = tmp["ts"].isin(bar_df["ts"])
                tmp["roll"] = ~is_close

                frames.append(tmp[["id", "tf", "ts", "period", "ema", "tf_days", "roll"]])

    if not frames:
        return pd.DataFrame(
            columns=["id", "tf", "ts", "period", "ema", "tf_days", "roll", "d1", "d2", "d1_roll", "d2_roll"]
        )

    result = pd.concat(frames, ignore_index=True)
    result["ts"] = pd.to_datetime(result["ts"], utc=True)
    result = result.sort_values(["id", "tf", "period", "ts"])

    # ---------------------------------------------------------------------
    # Derivatives (FIXED to match doc)
    # - d1/d2: daily diffs for ALL rows
    # - d1_roll/d2_roll: diffs only across canonical endpoints (roll=FALSE)
    # ---------------------------------------------------------------------
    g_full = result.groupby(["id", "tf", "period"], sort=False)
    result["d1"] = g_full["ema"].diff()
    result["d2"] = g_full["d1"].diff()

    result["d1_roll"] = np.nan
    result["d2_roll"] = np.nan

    mask_close = ~result["roll"]
    if mask_close.any():
        close_df = result.loc[mask_close].copy()
        g_close = close_df.groupby(["id", "tf", "period"], sort=False)
        close_df["d1_roll"] = g_close["ema"].diff()
        close_df["d2_roll"] = g_close["d1_roll"].diff()
        result.loc[close_df.index, "d1_roll"] = close_df["d1_roll"]
        result.loc[close_df.index, "d2_roll"] = close_df["d2_roll"]

    if start is not None:
        start_ts = pd.to_datetime(start, utc=True)
        result = result[result["ts"] >= start_ts]
    if end is not None:
        end_ts = pd.to_datetime(end, utc=True)
        result = result[result["ts"] <= end_ts]

    return result[["id", "tf", "ts", "period", "ema", "tf_days", "roll", "d1", "d2", "d1_roll", "d2_roll"]]


def write_multi_timeframe_ema_to_db(
    ids: Iterable[int],
    start: str = "2010-01-01",
    end: str | None = None,
    ema_periods: Iterable[int] = (6, 9, 10, 12, 14, 17, 20, 21, 26, 30, 50, 52, 77, 100, 200, 252, 365),
    tf_subset: Iterable[str] | None = None,
    *,
    db_url: str | None = None,
    schema: str = "public",
    out_table: str = "cmc_ema_multi_tf",
    update_existing: bool = True,
    bars_schema: str = "public",
    bars_table_tf_day: str = "cmc_price_bars_multi_tf",
) -> int:
    """
    Compute multi-timeframe EMAs (tf_day family) using dim_timeframe and persisted bars
    (with synthetic fallback), then upsert into {schema}.{out_table}.
    """
    engine = _get_engine(db_url)

    df = build_multi_timeframe_ema_frame(
        ids=ids,
        start=start,
        end=end,
        ema_periods=ema_periods,
        tf_subset=tf_subset,
        db_url=db_url,
        bars_schema=bars_schema,
        bars_table_tf_day=bars_table_tf_day,
    )
    if df.empty:
        print("No multi-timeframe EMA rows generated.")
        return 0

    tmp_table = f"{out_table}_tmp"

    with engine.begin() as conn:
        conn.execute(text(f"DROP TABLE IF EXISTS {schema}.{tmp_table};"))

        conn.execute(
            text(
                f"""
                CREATE TEMP TABLE {tmp_table} AS
                SELECT
                    id, tf, ts, period,
                    ema, tf_days,
                    roll, d1, d2, d1_roll, d2_roll
                FROM {schema}.{out_table}
                LIMIT 0;
                """
            )
        )

        df.to_sql(tmp_table, conn, if_exists="append", index=False, method="multi")

        conflict_sql = (
            """
            DO UPDATE SET
                ema      = EXCLUDED.ema,
                tf_days  = EXCLUDED.tf_days,
                roll     = EXCLUDED.roll,
                d1       = EXCLUDED.d1,
                d2       = EXCLUDED.d2,
                d1_roll  = EXCLUDED.d1_roll,
                d2_roll  = EXCLUDED.d2_roll
            """
            if update_existing
            else "DO NOTHING"
        )

        sql = f"""
        INSERT INTO {schema}.{out_table} AS t
            (id, tf, ts, period, ema, tf_days, roll, d1, d2, d1_roll, d2_roll)
        SELECT
            id, tf, ts, period,
            ema, tf_days,
            roll, d1, d2, d1_roll, d2_roll
        FROM {tmp_table}
        ON CONFLICT (id, tf, ts, period)
        {conflict_sql};
        """

        res = conn.execute(text(sql))
        return int(res.rowcount or 0)
