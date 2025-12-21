from __future__ import annotations

"""
Feature builder for cmc_ema_multi_tf_v2.

v2 semantics:
- One row per DAILY bar from cmc_price_histories7.
- For each (tf, period):
    * Compute a single, continuous DAILY EMA.
    * Alpha is based on a DAYS horizon: horizon_days = tf_days * period.
    * roll = FALSE on every tf_days-th day (per id, per tf), TRUE otherwise.

Derivatives (MATCH DOC):
- d1/d2 = daily derivatives for ALL rows (diff on full daily EMA series).
- d1_roll/d2_roll = derivatives ONLY across canonical endpoints (roll = FALSE).
    * These are populated ONLY on canonical rows; NULL on roll=TRUE rows.

Timeframes:
- NO HARDCODED TFs.
- TF universe + tf_days are sourced ONLY from public.dim_timeframe via:
    ta_lab2.time.dim_timeframe.list_tfs/get_tf_days

Incremental behavior (UPDATED):
- Watermark is per (id, tf, period), not per id.
- For each id:
    * Compute full v2 EMA in memory from the beginning of its history.
    * INSERT only rows where ts > MAX(ts) already present for that (id, tf, period).
    * If a (tf, period) is NEW (no rows exist yet), it backfills the full history
      for that (id, tf, period) even if there are no new timestamps.

NEW SEEDING RULE (THIS PATCH):
- We do NOT emit any rows for a given (tf, period) until a full
  horizon_days = tf_days * period daily observations have occurred.
- We do this by DROPPING the first (horizon_days - 1) daily rows for that
  (tf, period). No placeholder rows with NaN/NULL are written to the table.

Notes:
- This module is intentionally "library-like" (no CLI). Use the refresh runner script.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from sqlalchemy import Engine, text

from ta_lab2.time.dim_timeframe import get_tf_days, list_tfs


# ---------------------------------------------------------------------
# Public defaults / exports
# ---------------------------------------------------------------------

# Periods are NOT timeframes. Runner may override.
DEFAULT_PERIODS: List[int] = [6, 9, 10, 12, 14, 17, 20, 21, 26, 30, 50, 52, 77, 100, 200, 252, 365]

__all__ = [
    "DEFAULT_PERIODS",
    "resolve_tf_universe_v2",
    "compute_multi_tf_v2_for_asset",
    "refresh_cmc_ema_multi_tf_v2_incremental",
    "refresh_cmc_ema_multi_tf_v2",  # backwards-compatible alias
]


@dataclass(frozen=True)
class TfUniverse:
    """Resolved TF universe for v2."""
    tf_days_by_tf: Dict[str, int]
    alignment_type: str = "tf_day"
    canonical_only: bool = True


# ---------------------------------------------------------------------
# Timeframe resolution (NO HARDCODED TFs)
# ---------------------------------------------------------------------

def resolve_tf_universe_v2(
    *,
    db_url: str,
    alignment_type: str = "tf_day",
    canonical_only: bool = True,
) -> TfUniverse:
    """
    Resolve {tf: tf_days} from dim_timeframe.

    Soft D-only behavior:
      - If dim_timeframe returns non-day labels (e.g. 2W, 1M), we drop them.
      - We continue as long as at least one day-label TF remains.
    """
    tf_labels = list_tfs(
        db_url=db_url,
        alignment_type=alignment_type,
        canonical_only=canonical_only,
    )

    if not tf_labels:
        raise RuntimeError(
            "No timeframes returned from dim_timeframe. "
            f"alignment_type={alignment_type!r}, canonical_only={canonical_only}. "
            "Populate dim_timeframe or adjust filters."
        )

    def _is_day_label(tf: str) -> bool:
        tf = (tf or "").strip()
        return tf.endswith("D") and tf[:-1].isdigit()

    dropped = [tf for tf in tf_labels if not _is_day_label(str(tf))]
    tf_labels = [tf for tf in tf_labels if _is_day_label(str(tf))]

    if dropped:
        preview = ", ".join(sorted(set(map(str, dropped)))[:20])
        print(f"[ema_multi_tf_v2] NOTE: Dropping non-day TF labels (keeping only numeric+'D'): {preview}")

    if not tf_labels:
        raise RuntimeError(
            "dim_timeframe returned tf_day timeframes, but none matched numeric+'D' (e.g. '14D'). "
            "If you want W/M labels, remove this filter."
        )

    tf_map: Dict[str, int] = {}
    missing_days: List[str] = []

    for tf in tf_labels:
        try:
            days = get_tf_days(tf, db_url)
        except KeyError:
            missing_days.append(tf)
            continue

        if days is None:
            missing_days.append(tf)
            continue

        tf_map[str(tf)] = int(days)

    if not tf_map:
        raise RuntimeError(
            "dim_timeframe returned timeframes but none had tf_days populated. "
            f"Missing/invalid tf_days for: {missing_days[:20]}"
        )

    if missing_days:
        preview = ", ".join(missing_days[:20]) + (" ..." if len(missing_days) > 20 else "")
        print(f"[ema_multi_tf_v2] WARNING: skipping TFs with missing tf_days: {preview}")

    return TfUniverse(tf_days_by_tf=tf_map, alignment_type=alignment_type, canonical_only=canonical_only)

# ---------------------------------------------------------------------
# EMA helpers
# ---------------------------------------------------------------------

def compute_daily_ema(prices: pd.Series, *, horizon_days: int) -> pd.Series:
    """
    Standard daily EMA over `prices` with smoothing horizon `horizon_days`.

    alpha = 2 / (horizon_days + 1)
    """
    if horizon_days <= 0:
        raise ValueError(f"horizon_days must be positive, got {horizon_days}")

    alpha = 2.0 / (horizon_days + 1.0)
    return prices.ewm(alpha=alpha, adjust=False).mean()


def compute_multi_tf_v2_for_asset(
    *,
    df_id: pd.DataFrame,
    periods: Sequence[int],
    tf_days_by_tf: Dict[str, int],
) -> pd.DataFrame:
    """
    Compute the v2 multi-timeframe DAILY EMA for a single asset id.

    Input df_id columns: ["id", "ts", "close"], sorted by ts.
    Output columns:
        id, ts, tf, period, ema, tf_days, roll, d1, d2, d1_roll, d2_roll
    """
    df_id = df_id.sort_values("ts").reset_index(drop=True)

    out_cols = ["id", "ts", "tf", "period", "ema", "tf_days", "roll", "d1", "d2", "d1_roll", "d2_roll"]
    if df_id.empty:
        return pd.DataFrame(columns=out_cols)

    out_frames: List[pd.DataFrame] = []
    day_index = np.arange(len(df_id), dtype=int)

    for tf, tf_days in tf_days_by_tf.items():
        tf_days = int(tf_days)
        if tf_days <= 0:
            continue

        # roll = FALSE every tf_days-th day (1-based index)
        roll_false_mask = ((day_index + 1) % tf_days) == 0

        for period in periods:
            period_int = int(period)
            if period_int <= 0:
                continue

            horizon_days = tf_days * period_int
            ema = compute_daily_ema(df_id["close"], horizon_days=horizon_days)

            df_tf = pd.DataFrame(
                {
                    "id": df_id["id"].values,
                    "ts": df_id["ts"].values,
                    "tf": tf,
                    "period": period_int,
                    "tf_days": tf_days,
                    "ema": ema.values,
                }
            )

            # roll flag
            df_tf["roll"] = ~roll_false_mask

            # DOC-CORRECT:
            # d1/d2 = daily diffs for ALL rows (full daily EMA series)
            df_tf["d1"] = df_tf["ema"].diff()
            df_tf["d2"] = df_tf["d1"].diff()

            # DOC-CORRECT:
            # d1_roll/d2_roll = diffs only across canonical endpoints (roll=FALSE),
            # populated only on canonical rows.
            df_tf["d1_roll"] = np.nan
            df_tf["d2_roll"] = np.nan

            can_idx = (~df_tf["roll"]).to_numpy()
            if can_idx.any():
                can_ema = df_tf.loc[~df_tf["roll"], "ema"]
                can_d1 = can_ema.diff()
                can_d2 = can_d1.diff()
                df_tf.loc[~df_tf["roll"], "d1_roll"] = can_d1.values
                df_tf.loc[~df_tf["roll"], "d2_roll"] = can_d2.values

            # ----------------------------------------------------------
            # NEW: Seeding rule => DO NOT EMIT rows until horizon_days elapsed
            # Keep rows starting at the (horizon_days)-th observation (1-based),
            # i.e. index >= horizon_days - 1 (0-based).
            # ----------------------------------------------------------
            if horizon_days > 1 and len(df_tf) >= horizon_days:
                df_tf = df_tf.iloc[horizon_days - 1 :].reset_index(drop=True)
            else:
                # Not enough history to emit ANY rows for this (tf, period)
                continue

            out_frames.append(df_tf[out_cols])

    if not out_frames:
        return pd.DataFrame(columns=out_cols)

    return pd.concat(out_frames, ignore_index=True)


# ---------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------

def load_daily_prices(
    engine: Engine,
    *,
    ids: Optional[Sequence[int]],
    price_schema: str = "public",
    price_table: str = "cmc_price_histories7",
) -> pd.DataFrame:
    fq = f"{price_schema}.{price_table}"

    if ids is None:
        sql = text(
            f"""
            SELECT id,
                   timestamp AS ts,
                   close
            FROM {fq}
            ORDER BY id, timestamp
            """
        )
        return pd.read_sql(sql, engine)

    sql = text(
        f"""
        SELECT id,
               timestamp AS ts,
               close
        FROM {fq}
        WHERE id = ANY(:ids)
        ORDER BY id, timestamp
        """
    )
    return pd.read_sql(sql, engine, params={"ids": list(ids)})


def load_last_ts_by_key(
    engine: Engine,
    *,
    ids: Optional[Sequence[int]],
    tfs: Sequence[str],
    periods: Sequence[int],
    out_schema: str = "public",
    out_table: str = "cmc_ema_multi_tf_v2",
) -> Dict[Tuple[int, str, int], pd.Timestamp]:
    """
    Return {(id, tf, period): last_ts} for existing rows.
    Missing keys simply won't appear in the dict.
    """
    fq = f"{out_schema}.{out_table}"

    # Restrict to relevant universe to keep query reasonable.
    where_clauses = []
    params: Dict[str, object] = {"tfs": list(tfs), "periods": [int(p) for p in periods]}

    where_clauses.append("tf = ANY(:tfs)")
    where_clauses.append("period = ANY(:periods)")

    if ids is not None:
        where_clauses.append("id = ANY(:ids)")
        params["ids"] = list(ids)

    where_sql = " AND ".join(where_clauses)

    sql = text(
        f"""
        SELECT id, tf, period, MAX(ts) AS last_ts
        FROM {fq}
        WHERE {where_sql}
        GROUP BY id, tf, period
        """
    )

    df = pd.read_sql(sql, engine, params=params)

    out: Dict[Tuple[int, str, int], pd.Timestamp] = {}
    for _, row in df.iterrows():
        rid = int(row["id"])
        rtf = str(row["tf"])
        rper = int(row["period"])
        ts = row["last_ts"]
        if pd.isna(ts):
            continue
        out[(rid, rtf, rper)] = ts
    return out


# ---------------------------------------------------------------------
# Main incremental refresh entrypoint (called by runner)
# ---------------------------------------------------------------------

def refresh_cmc_ema_multi_tf_v2_incremental(
    *,
    engine: Engine,
    db_url: str,
    periods: Optional[Sequence[int]] = None,
    ids: Optional[Sequence[int]] = None,
    alignment_type: str = "tf_day",
    canonical_only: bool = True,
    price_schema: str = "public",
    price_table: str = "cmc_price_histories7",
    out_schema: str = "public",
    out_table: str = "cmc_ema_multi_tf_v2",
) -> None:
    """
    Incremental refresh of cmc_ema_multi_tf_v2.

    Watermark is per (id, tf, period). New TFs or new periods are backfilled.
    """
    if periods is None:
        periods = DEFAULT_PERIODS
    periods = [int(p) for p in periods if int(p) > 0]
    if not periods:
        raise ValueError("No valid periods provided.")

    tfu = resolve_tf_universe_v2(db_url=db_url, alignment_type=alignment_type, canonical_only=canonical_only)
    tf_map = tfu.tf_days_by_tf

    tf_labels = list(tf_map.keys())
    preview = ", ".join(tf_labels[:10]) + (" ..." if len(tf_labels) > 10 else "")
    print(f"[multi_tf_v2] Loaded {len(tf_map)} timeframes from dim_timeframe: {preview}")

    daily = load_daily_prices(engine, ids=ids, price_schema=price_schema, price_table=price_table)
    if daily.empty:
        print("[multi_tf_v2] No daily price data found; nothing to do.")
        return

    last_ts_by_key = load_last_ts_by_key(
        engine,
        ids=ids,
        tfs=tf_labels,
        periods=periods,
        out_schema=out_schema,
        out_table=out_table,
    )

    all_new_rows: List[pd.DataFrame] = []

    for asset_id, df_id in daily.groupby("id", sort=False):
        asset_id_int = int(asset_id)
        print(f"[multi_tf_v2] Processing id={asset_id_int}")

        df_v2 = compute_multi_tf_v2_for_asset(
            df_id=df_id,
            periods=periods,
            tf_days_by_tf=tf_map,
        )

        if df_v2.empty:
            print(f"[multi_tf_v2] id={asset_id_int}: no rows computed (likely insufficient history for all (tf,period)).")
            continue

        # Apply per-(id,tf,period) watermark.
        # Keep rows where ts > last_ts for that key; if key missing => keep all rows for that key.
        def _keep_row(row) -> bool:
            k = (asset_id_int, str(row["tf"]), int(row["period"]))
            last_ts = last_ts_by_key.get(k)
            if last_ts is None:
                return True
            return row["ts"] > last_ts

        keep_mask = df_v2.apply(_keep_row, axis=1)
        df_new = df_v2.loc[keep_mask].copy()

        if df_new.empty:
            print(f"[multi_tf_v2] id={asset_id_int}: no new rows to insert.")
            continue

        all_new_rows.append(df_new)

    if not all_new_rows:
        print("[multi_tf_v2] No new EMA rows to insert for any id.")
        return

    result = pd.concat(all_new_rows, ignore_index=True)
    result["ingested_at"] = pd.Timestamp.utcnow()

    # Match DB column order
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
        result.to_sql(
            out_table,
            con=conn,
            schema=out_schema,
            if_exists="append",
            index=False,
            method="multi",
            chunksize=10_000,
        )

    print(f"[multi_tf_v2] Inserted {len(result):,} new rows into {out_schema}.{out_table}.")


# Backwards-compatible name (matches what you tried to import)
def refresh_cmc_ema_multi_tf_v2(*, engine: Engine, db_url: str, **kwargs) -> None:
    """Alias for refresh_cmc_ema_multi_tf_v2_incremental."""
    refresh_cmc_ema_multi_tf_v2_incremental(engine=engine, db_url=db_url, **kwargs)
