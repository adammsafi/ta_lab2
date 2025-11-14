from __future__ import annotations

from typing import Sequence, Mapping
import pandas as pd
from sqlalchemy import text

from ta_lab2.io import (
    load_cmc_ohlcv_daily,
    _get_marketdata_engine,
    _get_marketdata_schema_and_tables,
)
from ta_lab2.features.resample import resample_one

# ---------------------------------------------------------------------
# 1) Define the timeframes you care about
#    label -> pandas offset alias used by resample_one
# ---------------------------------------------------------------------
TIMEFRAMES: Mapping[str, str] = {
    "2D":  "2D",
    "3D":  "3D",
    "4D":  "4D",
    "5D":  "5D",
    "1W":  "W",    # weekly (Sun-end by default; can change to 'W-FRI' later)
    "10D": "10D",
    "2W":  "2W",
    "3W":  "3W",
    "25D": "25D",
    "1M":  "M",    # month-end; resample_one normalizes this internally
    "45D": "45D",
    "2M":  "2M",
    "10W": "10W",
    "3M":  "3M",
    "100D": "100D",
    "6M":  "6M",
    "9M":  "9M",
    "12M": "12M",
}

# EMA lengths in *bars* of the resampled timeframe
EMA_PERIODS = [10, 21, 50, 100]


def _resample_asset_daily_to_tf(
    daily: pd.DataFrame,
    asset_id: int,
    freq: str,
) -> pd.DataFrame:
    """
    Use ta_lab2.features.resample.resample_one to resample a single asset's daily OHLCV.

    daily: MultiIndex (id, ts) with columns [open, high, low, close, volume]
    freq : pandas offset alias like '2D','3D','W','M','2M',...
    """
    # Slice single id from the multi-index and convert to the schema resample_one expects
    d = daily.xs(asset_id, level="id").reset_index()  # columns: ts, open, high, low, close, volume
    d = d.rename(columns={"ts": "timestamp"})

    # Let resample_one handle OHLCV aggregation & calendar fields
    resampled = resample_one(d, freq=freq)

    # Keep just what we really need for EMAs + DB
    # (timestamp + close + optional other OHLCV fields for future)
    cols = [c for c in ["timestamp", "open", "high", "low", "close", "volume"] if c in resampled.columns]
    resampled = resampled[cols].copy()
    resampled["id"] = asset_id
    return resampled


def _compute_ema_for_tf(
    resampled: pd.DataFrame,
    ema_periods: Sequence[int],
) -> pd.DataFrame:
    """
    Given resampled OHLCV for one tf and many assets, compute EMAs on 'close'.

    resampled: columns: ['timestamp', 'open','high','low','close','volume','id']
    Returns: long df with cols ['id','ts','period','ema'].
    """
    if resampled.empty:
        return pd.DataFrame(columns=["id", "ts", "period", "ema"])

    df = resampled.copy()
    df = df.rename(columns={"timestamp": "ts"})
    df = df.set_index(["ts", "id"]).sort_index()

    # wide panel: index ts, columns id
    close_panel = df["close"].unstack("id")
    frames = []

    for p in ema_periods:
        ema_wide = close_panel.ewm(span=p, adjust=False).mean()
        ema_long = ema_wide.stack().rename("ema").reset_index()  # ['ts','id','ema']
        ema_long["period"] = int(p)
        frames.append(ema_long[["id", "ts", "period", "ema"]])

    out = pd.concat(frames, ignore_index=True)
    out.sort_values(["id", "ts", "period"], inplace=True)
    return out


def _upsert_multi_tf_ema_to_db(
    ema_long: pd.DataFrame,
    tf_label: str,
    *,
    db_url: str | None = None,
    chunksize: int = 10_000,
) -> int:
    """
    Write EMAs for a single timeframe into cmc_ema_multi_tf via UPSERT.

    Assumes table:

        CREATE TABLE IF NOT EXISTS public.cmc_ema_multi_tf (
            id          INTEGER         NOT NULL,
            ts          TIMESTAMPTZ     NOT NULL,
            tf          TEXT            NOT NULL,
            period      INTEGER         NOT NULL,
            ema         DOUBLE PRECISION NOT NULL,
            ingested_at TIMESTAMPTZ     NOT NULL DEFAULT now(),
            PRIMARY KEY (id, ts, tf, period)
        );
    """
    if ema_long.empty:
        return 0

    ema_long = ema_long.copy()
    ema_long["tf"] = tf_label

    records = ema_long.to_dict(orient="records")
    total = len(records)
    if total == 0:
        return 0

    engine = _get_marketdata_engine(db_url=db_url)
    schema, tables = _get_marketdata_schema_and_tables()
    table_name = tables.get("ema_multi_tf", "cmc_ema_multi_tf")
    full_table = f"{schema}.{table_name}" if schema else table_name

    stmt = text(
        f"""
        INSERT INTO {full_table} (id, ts, tf, period, ema)
        VALUES (:id, :ts, :tf, :period, :ema)
        ON CONFLICT (id, ts, tf, period) DO UPDATE
        SET ema = EXCLUDED.ema
        """
    )

    with engine.begin() as conn:
        for i in range(0, total, chunksize):
            batch = records[i : i + chunksize]
            conn.execute(stmt, batch)

    return total


def write_multi_timeframe_ema_to_db(
    ids: Sequence[int],
    *,
    start: str = "2010-01-01",
    end: str | None = None,
    ema_periods: Sequence[int] = EMA_PERIODS,
    db_url: str | None = None,
) -> int:
    """
    End-to-end:
      - Load daily OHLCV for ids from marketdata DB
      - For each timeframe in TIMEFRAMES:
          * resample using ta_lab2.features.resample.resample_one
          * compute EMAs on resampled close
          * UPSERT into cmc_ema_multi_tf

    Returns total rows written/updated.
    """
    if not ids:
        raise ValueError("ids must be a non-empty sequence of CMC IDs")
    if not ema_periods:
        raise ValueError("ema_periods must be a non-empty sequence of EMA lengths (in bars)")

    # 1) Load daily once
    daily = load_cmc_ohlcv_daily(ids, start=start, end=end, db_url=db_url)
    if daily.empty:
        return 0

    total_rows = 0

    for tf_label, freq in TIMEFRAMES.items():
        print(f"Processing timeframe {tf_label} (freq={freq})...")

        # Per-asset resample using resample_one
        frames = []
        for asset_id in ids:
            rs = _resample_asset_daily_to_tf(daily, asset_id, freq=freq)
            frames.append(rs)

        if not frames:
            continue

        resampled_all = pd.concat(frames, ignore_index=True)

        # Compute EMAs for this timeframe
        ema_long = _compute_ema_for_tf(resampled_all, ema_periods=ema_periods)

        # UPSERT into DB
        written = _upsert_multi_tf_ema_to_db(
            ema_long,
            tf_label=tf_label,
            db_url=db_url,
        )

        print(f"  -> wrote/updated {written} rows for tf={tf_label}")
        total_rows += written

    print("Total EMA rows written/updated across all timeframes:", total_rows)
    return total_rows


if __name__ == "__main__":
    ids = [1, 1027, 5426, 52, 32196, 1975]  # BTC, ETH, SOL, XRP, HYPE, LINK etc.

    total = write_multi_timeframe_ema_to_db(
        ids=ids,
        start="2010-01-01",
        ema_periods=[10, 21, 50, 100],  # EMA lengths in bars of each tf
    )
    print("DONE, total rows:", total)
