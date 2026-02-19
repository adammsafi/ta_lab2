from __future__ import annotations

"""
Incremental builder for cmc_ema_multi_tf_v2

This implements the "v2" multi-timeframe EMA we discussed:

- One row per DAILY bar from cmc_price_histories7.
- For each (tf, period):
    * Compute a single, continuous DAILY EMA.
    * Alpha is based on a DAYS horizon: horizon_days = tf_days * period.
    * roll = FALSE on every tf_days-th day (per id, per tf), TRUE otherwise.
    * d1_roll, d2_roll are diffs on the full daily EMA series.
    * d1, d2 are diffs ONLY on roll = FALSE (canonical) rows.

INCREMENTAL BEHAVIOR (no TRUNCATE):

- For each id:
    * We compute the full v2 EMA in memory from the BEGINNING of its history.
    * We then only INSERT rows where ts > MAX(ts) already present in cmc_ema_multi_tf_v2
      for that id (or all rows if id is new).
- This avoids complex EMA state reconstruction while keeping the DB up to date.

You can safely run this repeatedly; it will append only new rows.

UPDATED TIMEFRAME SOURCE:

- By default, we now derive the timeframe set from dim_timeframe:

    * alignment_type = 'tf_day'
    * canonical_only = True
    * tf_days = get_tf_days(tf, db_url)
    * roll = FALSE every tf_days-th day per id, tf.

- The legacy TIMEFRAME_TF_DAYS dict is kept as a fallback and can still be
  used by explicitly passing timeframe_tf_days into the refresh function.
"""

import argparse
from dataclasses import dataclass
from typing import Dict, List, Sequence, Optional

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text

# NEW: dim_timeframe integration
from ta_lab2.time.dim_timeframe import list_tfs, get_tf_days


# ---------------------------------------------------------------------
# Config: timeframes and tf_days (legacy / fallback)
# ---------------------------------------------------------------------

TIMEFRAME_TF_DAYS: Dict[str, int] = {
    "2D": 2,
    "3D": 3,
    "4D": 4,
    "5D": 5,
    "10D": 10,
    "15D": 15,
    "20D": 20,
    "25D": 25,
    "45D": 45,
    "100D": 100,
    "1W": 7,
    "2W": 14,
    "3W": 21,
    "4W": 28,
    "6W": 42,
    "8W": 56,
    "10W": 70,
    "1M": 30,
    "2M": 60,
    "3M": 90,
    "6M": 180,
    "9M": 270,
    "12M": 360,
}

# For now, use the same period set for all timeframes.
# You can change this to be TF-specific if you want.
DEFAULT_PERIODS: List[int] = [5, 10, 20]


@dataclass
class CliArgs:
    db_url: str
    ids: Optional[Sequence[int]]


# ---------------------------------------------------------------------
# Timeframe resolution helpers
# ---------------------------------------------------------------------

def _resolve_timeframe_tf_days(
    db_url: Optional[str],
    timeframe_tf_days: Optional[Dict[str, int]],
) -> Dict[str, int]:
    """
    Resolve the mapping {tf: tf_days} to use for v2.

    Priority:

        1) If timeframe_tf_days is provided and non-empty, use it as-is.
           (Legacy behavior preserved for callers that explicitly pass it.)

        2) Else, if db_url is provided, load ALL canonical tf_day rows
           from dim_timeframe:

               tf_labels = list_tfs(db_url, alignment_type="tf_day", canonical_only=True)
               tf_days   = get_tf_days(tf, db_url)

        3) Else (no db_url, or dim_timeframe produced nothing), fall back
           to the legacy TIMEFRAME_TF_DAYS mapping.
    """
    # Case 1: explicit override passed in
    if timeframe_tf_days:
        return dict(timeframe_tf_days)

    # Case 2: use dim_timeframe as single source of truth for tf_day
    resolved: Dict[str, int] = {}
    if db_url is not None:
        tf_labels = list_tfs(
            db_url=db_url,
            alignment_type="tf_day",
            canonical_only=True,
        )
        for tf in tf_labels:
            try:
                days = get_tf_days(tf, db_url)
            except KeyError:
                # If somehow present in list_tfs but tf_days missing, skip
                continue
            resolved[tf] = days

        if resolved:
            return resolved

    # Case 3: fallback to legacy defaults
    return dict(TIMEFRAME_TF_DAYS)


# ---------------------------------------------------------------------
# EMA helpers
# ---------------------------------------------------------------------

def compute_daily_ema(
    prices: pd.Series,
    horizon_days: int,
) -> pd.Series:
    """
    Compute a standard daily EMA over 'prices' with a smoothing horizon
    of `horizon_days` calendar days.

    alpha_daily = 2 / (horizon_days + 1)

    Uses pandas ewm with adjust=False so it matches recursive EMA:
        ema_t = alpha * price_t + (1 - alpha) * ema_{t-1}
    """
    if horizon_days <= 0:
        raise ValueError(f"horizon_days must be positive, got {horizon_days}")

    alpha = 2.0 / (horizon_days + 1.0)
    ema = prices.ewm(alpha=alpha, adjust=False).mean()
    return ema


def compute_multi_tf_v2_for_asset(
    df_id: pd.DataFrame,
    periods: Sequence[int],
    timeframe_tf_days: Dict[str, int],
) -> pd.DataFrame:
    """
    Compute the v2 multi-timeframe DAILY EMA for a single asset (one id).

    Input df_id columns: ["id", "ts", "close"], sorted by ts.
    Output columns:
        id, ts, tf, period, ema, tf_days, roll, d1_roll, d2_roll, d1, d2
    """
    df_id = df_id.sort_values("ts").reset_index(drop=True)
    out_frames: List[pd.DataFrame] = []

    # Day index for this asset: 0,1,2,... across *all* days for this id
    day_index = np.arange(len(df_id), dtype=int)

    for tf, tf_days in timeframe_tf_days.items():
        # roll = FALSE every tf_days-th day (1-based index)
        # Example: tf_days=5 → days 5,10,15,... are canonical.
        roll_false_mask = ((day_index + 1) % tf_days) == 0

        for period in periods:
            horizon_days = tf_days * period

            ema = compute_daily_ema(df_id["close"], horizon_days=horizon_days)

            df_tf = pd.DataFrame(
                {
                    "id": df_id["id"].values,
                    "ts": df_id["ts"].values,
                    "tf": tf,
                    "period": period,
                    "tf_days": tf_days,
                    "ema": ema.values,
                }
            )

            # roll flag: True = interior day, False = canonical boundary
            df_tf["roll"] = ~roll_false_mask

            # d1_roll / d2_roll: full series diffs for this (id, tf, period)
            df_tf["d1_roll"] = df_tf["ema"].diff()
            df_tf["d2_roll"] = df_tf["d1_roll"].diff()

            # d1 / d2: only defined on canonical (roll = False) rows
            canonical = df_tf.loc[~df_tf["roll"], ["ts", "ema"]].copy()
            canonical["d1"] = canonical["ema"].diff()
            canonical["d2"] = canonical["d1"].diff()

            df_tf = df_tf.merge(
                canonical[["ts", "d1", "d2"]],
                on="ts",
                how="left",
            )

            out_frames.append(df_tf)

    if not out_frames:
        return pd.DataFrame(
            columns=[
                "id",
                "ts",
                "tf",
                "period",
                "ema",
                "tf_days",
                "roll",
                "d1_roll",
                "d2_roll",
                "d1",
                "d2",
            ]
        )

    result = pd.concat(out_frames, ignore_index=True)
    return result


# ---------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------

def parse_args() -> CliArgs:
    parser = argparse.ArgumentParser(
        description="Incrementally refresh cmc_ema_multi_tf_v2 with pure daily EMA (tf_days-based)."
    )
    parser.add_argument(
        "--db-url",
        required=True,
        help="SQLAlchemy Postgres URL, e.g. postgresql://user:pass@host:5432/dbname",
    )
    parser.add_argument(
        "--ids",
        default="all",
        help="Comma-separated list of asset ids, or 'all' (default) for all ids.",
    )
    args = parser.parse_args()

    if args.ids == "all":
        ids: Optional[Sequence[int]] = None
    else:
        ids = [int(x.strip()) for x in args.ids.split(",") if x.strip()]

    return CliArgs(db_url=args.db_url, ids=ids)


def load_daily_prices(engine, ids: Optional[Sequence[int]]) -> pd.DataFrame:
    """
    Load daily price history from cmc_price_histories7.

    Expects at least (id, timestamp, close).
    """
    if ids is None:
        sql = text(
            """
            SELECT id,
                   timestamp as ts,
                   close
            FROM cmc_price_histories7
            ORDER BY id, timestamp
            """
        )
        df = pd.read_sql(sql, engine)
    else:
        sql = text(
            """
            SELECT id,
                   timestamp as ts,
                   close
            FROM cmc_price_histories7
            WHERE id = ANY(:ids)
            ORDER BY id, timestamp
            """
        )
        df = pd.read_sql(sql, engine, params={"ids": list(ids)})

    return df


def load_last_ts_by_id(engine, ids: Optional[Sequence[int]]) -> Dict[int, pd.Timestamp]:
    """
    Look at cmc_ema_multi_tf_v2 and get the latest ts per id.

    Returns a dict: {id: last_ts}
    """
    if ids is None:
        sql = text(
            """
            SELECT id, MAX(ts) AS last_ts
            FROM cmc_ema_multi_tf_v2
            GROUP BY id
            """
        )
        df = pd.read_sql(sql, engine)
    else:
        sql = text(
            """
            SELECT id, MAX(ts) AS last_ts
            FROM cmc_ema_multi_tf_v2
            WHERE id = ANY(:ids)
            GROUP BY id
            """
        )
        df = pd.read_sql(sql, engine, params={"ids": list(ids)})

    last_ts_by_id: Dict[int, pd.Timestamp] = {}
    for _, row in df.iterrows():
        last_ts_by_id[int(row["id"])] = row["last_ts"]
    return last_ts_by_id


def refresh_cmc_ema_multi_tf_v2_incremental(
    engine,
    periods: Sequence[int],
    timeframe_tf_days: Optional[Dict[str, int]],
    ids: Optional[Sequence[int]],
    db_url: Optional[str] = None,
) -> None:
    """
    Incremental refresh of cmc_ema_multi_tf_v2.

    For each id:
      - Compute the full v2 EMA in memory across its entire daily history.
      - Insert only rows where ts > last_ts already present for that id.

    Timeframe resolution:

      - If timeframe_tf_days is provided, use it directly.
      - Else, if db_url is provided, use dim_timeframe (tf_day, canonical_only).
      - Else, fall back to legacy TIMEFRAME_TF_DAYS.
    """
    # Resolve the timeframe map up front
    tf_map = _resolve_timeframe_tf_days(db_url=db_url, timeframe_tf_days=timeframe_tf_days)

    print(f"[multi_tf_v2] Using {len(tf_map)} timeframes")

    daily = load_daily_prices(engine, ids)
    if daily.empty:
        print("No daily price data found; nothing to do.")
        return

    last_ts_by_id = load_last_ts_by_id(engine, ids)

    all_new_rows: List[pd.DataFrame] = []

    for asset_id, df_id in daily.groupby("id", sort=False):
        print(f"[multi_tf_v2] Processing id={asset_id}")

        df_v2 = compute_multi_tf_v2_for_asset(
            df_id=df_id,
            periods=periods,
            timeframe_tf_days=tf_map,
        )

        last_ts = last_ts_by_id.get(int(asset_id))
        if last_ts is not None:
            # Only keep rows strictly newer than last_ts
            mask_new = df_v2["ts"] > last_ts
            df_v2 = df_v2.loc[mask_new].copy()

        if df_v2.empty:
            print(f"[multi_tf_v2] id={asset_id}: no new rows to insert.")
            continue

        all_new_rows.append(df_v2)

    if not all_new_rows:
        print("[multi_tf_v2] No new EMA rows to insert for any id.")
        return

    result = pd.concat(all_new_rows, ignore_index=True)

    # Add ingested_at timestamp
    result["ingested_at"] = pd.Timestamp.utcnow()

    # Order columns to match the table definition
    result = result[
        [
            "id",
            "ts",
            "tf",
            "period",
            "ema",
            "ingested_at",
            "d1",
            "d2",
            "tf_days",
            "roll",
            "d1_roll",
            "d2_roll",
        ]
    ]

    with engine.begin() as conn:
        # Append rows; rely on primary key (id, ts, tf, period) to prevent duplicates
        result.to_sql(
            "cmc_ema_multi_tf_v2",
            con=conn,
            if_exists="append",
            index=False,
            method="multi",
            chunksize=10_000,
        )

    print(f"[multi_tf_v2] Inserted {len(result):,} new rows into cmc_ema_multi_tf_v2.")


def main() -> None:
    args = parse_args()
    engine = create_engine(args.db_url)

    refresh_cmc_ema_multi_tf_v2_incremental(
        engine=engine,
        periods=DEFAULT_PERIODS,
        timeframe_tf_days=None,         # use dim_timeframe by default
        ids=args.ids,
        db_url=args.db_url,
    )


if __name__ == "__main__":
    main()
