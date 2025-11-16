from __future__ import annotations

"""
Multi-timeframe EMA builder for cmc_ema_multi_tf.

Behavior:

- EMA is a smooth, rolling series updated on EVERY daily ts.
- We approximate a "tf-period EMA" by scaling the period by tf_days:

      effective_period = period * tf_days[tf]

  e.g. 10-period 3D EMA ≈ 30-day EMA.

- `roll` flag:
    * roll = FALSE → this ts is a TRUE higher-TF close
                     (end of the 3D / 1W / 1M bar).
    * roll = TRUE  → intrabar / rolling value.

- `d1`, `d2` (closing-only):
    first and second differences of EMA, but only on rows where roll = FALSE.
    Non-closing rows get NULL for d1/d2.

- `d1_roll`, `d2_roll` (rolling per-day):
    first and second differences of EMA on the FULL daily grid
    (rolling series, step-free).

Expected schema for public.cmc_ema_multi_tf:

    id        int
    tf        text
    ts        timestamptz
    period    int
    ema       double precision
    tf_days   int
    roll      boolean               -- FALSE = true close, TRUE = rolling
    d1        double precision      -- closing-only
    d2        double precision      -- closing-only
    d1_roll   double precision      -- rolling per-day
    d2_roll   double precision      -- rolling per-day

UNIQUE (id, tf, ts, period)
"""

from typing import Iterable, Dict, List

import numpy as np
import pandas as pd
from sqlalchemy import text

from ta_lab2.io import _get_marketdata_engine as _get_engine, load_cmc_ohlcv_daily
from ta_lab2.features.ema import compute_ema

__all__ = [
    "TIMEFRAME_FREQS",
    "TF_DAYS",
    "build_multi_timeframe_ema_frame",
    "write_multi_timeframe_ema_to_db",
]


# ---------------------------------------------------------------------------
# Timeframe configuration
# ---------------------------------------------------------------------------

# Label → pandas resample frequency
TIMEFRAME_FREQS: Dict[str, str] = {
    "2D": "2D",
    "3D": "3D",
    "4D": "4D",
    "5D": "5D",
    "10D": "10D",
    "15D": "15D",
    "20D": "20D",
    "25D": "25D",
    "45D": "45D",
    "100D": "100D",
    "1W": "1W",
    "2W": "2W",
    "3W": "3W",
    "4W": "4W",
    "6W": "6W",
    "8W": "8W",
    "10W": "10W",
    # month-end anchored (use ME to avoid FutureWarning)
    "1M": "1ME",
    "2M": "2ME",
    "3M": "3ME",
    "6M": "6ME",
    "9M": "9ME",
    "12M": "12ME",
}

# Approximate number of days for ordering / scaling
TF_DAYS: Dict[str, int] = {
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


def _normalize_daily(daily: pd.DataFrame) -> pd.DataFrame:
    """
    Ensure daily OHLCV has columns: id, ts, open, high, low, close, volume
    with ts as tz-aware UTC.
    """
    df = daily.copy()

    # If id/ts are in the index, move them to columns
    if isinstance(df.index, pd.MultiIndex):
        idx_names = list(df.index.names or [])
        if "id" in idx_names and (
            "ts" in idx_names
            or "timeclose" in idx_names
            or "timestamp" in idx_names
        ):
            df = df.reset_index()

    # Standardize ts column name
    cols = {c.lower(): c for c in df.columns}
    if "ts" not in df.columns:
        if "timeclose" in cols:
            df = df.rename(columns={cols["timeclose"]: "ts"})
        elif "timestamp" in cols:
            df = df.rename(columns={cols["timestamp"]: "ts"})
        elif "date" in cols:
            df = df.rename(columns={cols["date"]: "ts"})
        else:
            raise ValueError("Could not find a timestamp-like column for daily data.")

    required = {"id", "ts", "close"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Daily OHLCV missing required columns: {missing}")

    # Open/high/low/volume are optional for EMA but required for resampling,
    # so we make sure they exist (fill with close/0 where needed).
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


def _resample_ohlcv_for_tf(
    df_id: pd.DataFrame,
    freq: str,
) -> pd.DataFrame:
    """
    Simple local OHLCV resampler for a single asset's daily data.

    Parameters
    ----------
    df_id : DataFrame with columns ts, open, high, low, close, volume
    freq : pandas offset alias, e.g. '2D','3D','1W','1ME', etc.

    Returns
    -------
    DataFrame with columns ts, open, high, low, close, volume
    at the higher timeframe, labeled at the bar end (right/closed-right),
    and not extending beyond the max ts in df_id.

    NOTE: This is kept for potential future use where you want actual
    higher-TF OHLC bars. For the roll/d1/d2 logic we instead rely on
    the original daily timestamps of the last bar in each group
    (see _compute_tf_closes_by_asset).
    """
    if df_id.empty:
        return df_id.head(0)

    d = df_id[["ts", "open", "high", "low", "close", "volume"]].copy()
    d["ts"] = pd.to_datetime(d["ts"], utc=True)
    d = d.set_index("ts").sort_index()

    agg = d.resample(freq, label="right", closed="right").agg(
        {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }
    )

    # Drop periods where we never had any data (close is NaN)
    agg = agg.dropna(subset=["close"])

    if agg.empty:
        return agg.reset_index().rename(columns={"index": "ts"})

    max_ts = d.index.max()
    agg = agg[agg.index <= max_ts]

    return agg.reset_index().rename(columns={"index": "ts"})


def _compute_tf_closes_by_asset(
    daily: pd.DataFrame,
    ids: Iterable[int],
    freq: str,
) -> Dict[int, pd.Series]:
    """
    For each asset id, compute the *actual daily timestamps* that are the
    last bar in each higher-TF resample bucket.

    This avoids relying on resample *labels* matching the daily grid exactly.
    """
    closes_by_asset: Dict[int, pd.Series] = {}

    for asset_id in ids:
        df_id = daily[daily["id"] == asset_id].copy()
        if df_id.empty:
            continue

        df_id = df_id.sort_values("ts")
        s = df_id.set_index("ts")["close"]

        # Resample and, for each group, take the last original ts (x.index.max()).
        grouped = s.resample(freq, label="right", closed="right")
        last_ts_per_group = grouped.apply(lambda x: x.index.max())

        # Drop any empty groups (shouldn't usually occur after resample+apply)
        last_ts_per_group = last_ts_per_group.dropna()
        if last_ts_per_group.empty:
            continue

        closes_ts = pd.to_datetime(last_ts_per_group.values, utc=True)
        closes_by_asset[asset_id] = closes_ts

    return closes_by_asset


def build_multi_timeframe_ema_frame(
    ids: Iterable[int],
    start: str = "2010-01-01",
    end: str | None = None,
    ema_periods: Iterable[int] = (10, 21, 50, 100, 200),
    tfs: Dict[str, str] | None = None,
    *,
    db_url: str | None = None,
) -> pd.DataFrame:
    """
    Build a longform DataFrame of multi-timeframe EMAs on a DAILY grid.

    For each (id, tf, period):

    - `ema` is a rolling EMA updated on *every* daily ts.
      We scale the effective period by tf_days:

          effective_period = period * tf_days[tf]

      so a "10-period 3D EMA" is approximately a 30-day EMA, etc.

    - `roll` is a boolean:
        * roll = FALSE → this ts is a TRUE higher-TF close
                         (end of the 3D / 1W / 1M bar)
        * roll = TRUE  → intrabar / rolling value

    - `d1`, `d2` (closing-only):
        changes between EMA values on closing rows only.

    - `d1_roll`, `d2_roll` (rolling per-day):
        differences on the full rolling EMA series.
    """
    tfs = tfs or TIMEFRAME_FREQS
    ema_periods = [int(p) for p in ema_periods]
    ids = list(ids)
    if not ids:
        raise ValueError("ids must be a non-empty iterable of asset ids")

    daily = load_cmc_ohlcv_daily(
        ids=ids,
        start=start,
        end=end,
        db_url=db_url,
        tz="UTC",
    )
    daily = _normalize_daily(daily)

    frames: List[pd.DataFrame] = []

    for tf_label, freq in tfs.items():
        print(f"Processing timeframe {tf_label} (freq={freq})...")

        if tf_label not in TF_DAYS:
            raise KeyError(f"No tf_days mapping defined for timeframe '{tf_label}'")

        tf_day_value = TF_DAYS[tf_label]

        # 1) Detect TRUE closes for this timeframe per asset id
        #    using the *actual daily timestamps* that are the last bar
        #    in each resample bucket.
        closes_by_asset = _compute_tf_closes_by_asset(daily, ids, freq=freq)

        # 2) Compute DAILY rolling EMAs with effective period
        for asset_id in ids:
            df_id = daily[daily["id"] == asset_id].copy()
            if df_id.empty:
                continue

            df_id = df_id.sort_values("ts").reset_index(drop=True)
            close = df_id["close"].astype(float)
            closes_ts = closes_by_asset.get(asset_id)

            for p in ema_periods:
                effective_period = p * tf_day_value

                ema_series = compute_ema(
                    close,
                    period=effective_period,
                    adjust=False,
                    min_periods=effective_period,
                )

                out = df_id[["ts"]].copy()
                out["ema"] = ema_series

                # drop rows where EMA isn't defined yet
                out = out[out["ema"].notna()]
                if out.empty:
                    continue

                out["id"] = asset_id
                out["tf"] = tf_label
                out["period"] = p
                out["tf_days"] = tf_day_value

                # roll flag:
                #   roll = FALSE → ts is a true higher-TF close
                #   roll = TRUE  → rolling / intrabar
                if closes_ts is not None and len(closes_ts) > 0:
                    is_close = out["ts"].isin(closes_ts)
                    out["roll"] = ~is_close
                else:
                    # If for some reason we have no detected closes, treat
                    # everything as rolling. (d1/d2 will remain NaN.)
                    out["roll"] = True

                frames.append(
                    out[
                        [
                            "id",
                            "tf",
                            "ts",
                            "period",
                            "ema",
                            "tf_days",
                            "roll",
                        ]
                    ]
                )

    if not frames:
        return pd.DataFrame(
            columns=[
                "id",
                "tf",
                "ts",
                "period",
                "ema",
                "tf_days",
                "roll",
                "d1",
                "d2",
                "d1_roll",
                "d2_roll",
            ]
        )

    result_df = pd.concat(frames, ignore_index=True)
    result_df["ts"] = pd.to_datetime(result_df["ts"], utc=True)

    # Sort for group-wise diffs
    sort_cols = ["id", "tf", "period", "ts"]
    result_df = result_df.sort_values(sort_cols)

    # 1) Rolling per-day diffs: d1_roll, d2_roll
    g_full = result_df.groupby(["id", "tf", "period"], sort=False)
    result_df["d1_roll"] = g_full["ema"].diff()
    result_df["d2_roll"] = g_full["d1_roll"].diff()

    # 2) Closing-only diffs: d1, d2 (only where roll = FALSE)
    result_df["d1"] = np.nan
    result_df["d2"] = np.nan

    mask_close = ~result_df["roll"]
    if mask_close.any():
        close_df = result_df.loc[mask_close].copy()
        g_close = close_df.groupby(["id", "tf", "period"], sort=False)
        close_df["d1"] = g_close["ema"].diff()
        close_df["d2"] = g_close["d1"].diff()

        # Write back only on closing rows
        result_df.loc[close_df.index, "d1"] = close_df["d1"]
        result_df.loc[close_df.index, "d2"] = close_df["d2"]

    return result_df[
        [
            "id",
            "tf",
            "ts",
            "period",
            "ema",
            "tf_days",
            "roll",
            "d1",
            "d2",
            "d1_roll",
            "d2_roll",
        ]
    ]


def write_multi_timeframe_ema_to_db(
    ids: Iterable[int],
    start: str = "2010-01-01",
    end: str | None = None,
    ema_periods: Iterable[int] = (10, 21, 50, 100, 200),
    tfs: Dict[str, str] | None = None,
    *,
    db_url: str | None = None,
    schema: str = "public",
    price_table: str = "cmc_price_histories7",  # kept for API compatibility; not used here
    out_table: str = "cmc_ema_multi_tf",
) -> int:
    """
    Compute rolling multi-timeframe EMAs and upsert into cmc_ema_multi_tf.

    Columns written:

        id, tf, ts, period, ema, tf_days, roll, d1, d2, d1_roll, d2_roll

    Assumes UNIQUE (id, tf, ts, period) on the target table.
    """
    engine = _get_engine(db_url=db_url)

    df = build_multi_timeframe_ema_frame(
        ids=ids,
        start=start,
        end=end,
        ema_periods=ema_periods,
        tfs=tfs,
        db_url=db_url,
    )

    if df.empty:
        print("No multi-timeframe EMA rows generated.")
        return 0

    tmp_table = f"{out_table}_tmp"

    with engine.begin() as conn:
        # Drop any leftover temp with same name
        conn.execute(text(f"DROP TABLE IF EXISTS {schema}.{tmp_table};"))

        # Create a TEMP table with the same structure as the target
        conn.execute(
            text(
                f"""
            CREATE TEMP TABLE {tmp_table} AS
            SELECT
                id, tf, ts, period,
                ema, tf_days,
                roll,
                d1, d2,
                d1_roll, d2_roll
            FROM {schema}.{out_table}
            LIMIT 0;
            """
            )
        )

        # Bulk insert into temp
        df.to_sql(
            tmp_table,
            conn,
            if_exists="append",
            index=False,
            method="multi",
        )

        # Upsert into real table
        sql = f"""
        INSERT INTO {schema}.{out_table} AS t
            (id, tf, ts, period, ema, tf_days, roll, d1, d2, d1_roll, d2_roll)
        SELECT
            id, tf, ts, period,
            ema, tf_days,
            roll,
            d1, d2,
            d1_roll, d2_roll
        FROM {tmp_table}
        ON CONFLICT (id, tf, ts, period)
        DO UPDATE SET
            ema      = EXCLUDED.ema,
            tf_days  = EXCLUDED.tf_days,
            roll     = EXCLUDED.roll,
            d1       = EXCLUDED.d1,
            d2       = EXCLUDED.d2,
            d1_roll  = EXCLUDED.d1_roll,
            d2_roll  = EXCLUDED.d2_roll;
        """
        res = conn.execute(text(sql))
        return res.rowcount
