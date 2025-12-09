from __future__ import annotations

"""
Multi-timeframe EMA builder for cmc_ema_multi_tf.

Behavior (updated to preview-style roll):

- We work on a DAILY grid, but the canonical EMA is defined on
  higher-timeframe (TF) closes (3D, 1W, 1M, etc).

- For each (id, tf, period=p):

    * We first compute the EMA on TRUE TF closes using `period=p` TF bars.
      This is the canonical series and is stored on rows where roll = FALSE.

          ema_bar_{k} = alpha_bar * close_bar_{k}
                        + (1 - alpha_bar) * ema_bar_{k-1}

      where alpha_bar = 2 / (p + 1).

    * On DAILY intraperiod rows, we compute a **preview** EMA:

          ema_preview_t = alpha_bar * close_t
                          + (1 - alpha_bar) * ema_prev_bar

      where ema_prev_bar is the EMA of the last completed TF bar.
      These preview values DO NOT feed into future bar EMA; only the
      canonical bar-closing EMA advances the state.

- The `ema` column therefore contains:
    * canonical TF-bar EMA on roll = FALSE rows
    * preview EMA on roll = TRUE rows

- `roll` flag:
    * roll = FALSE → this ts is a TRUE higher-TF close
                     (end of the 3D / 1W / 1M bar), canonical EMA
    * roll = TRUE  → intrabar / preview EMA

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
    roll      boolean               -- FALSE = true close, TRUE = preview / rolling
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
    # tf_day-style “months”: approximate by fixed-day windows
    "1M": "30D",
    "2M": "60D",
    "3M": "90D",
    "6M": "180D",
    "9M": "270D",
    "12M": "360D",
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
    last bar in each higher-TF resample bucket, using the given frequency.

    We *exclude* the most recent (current) bucket so that the in-progress
    TF bar is treated as preview-only (roll = TRUE) and does not get a
    canonical close (roll = FALSE) until a future bucket has formed.
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

        last_ts_per_group = last_ts_per_group.dropna()
        if last_ts_per_group.empty:
            continue

        # Drop the *current* (last) bucket so only completed higher-TF
        # bars get canonical closes. If there's only one bucket, we treat
        # everything as preview (no canonical closes yet).
        if len(last_ts_per_group) <= 1:
            continue  # no completed TF bars yet for this asset
        else:
            last_ts_per_group = last_ts_per_group.iloc[:-1]

        closes_ts = pd.to_datetime(last_ts_per_group.values, utc=True)
        closes_by_asset[asset_id] = closes_ts

    return closes_by_asset



def build_multi_timeframe_ema_frame(
    ids: Iterable[int],
    start: str | None = "2010-01-01",
    end: str | None = None,
    ema_periods: Iterable[int] = (10, 21, 50, 100, 200),
    tfs: Dict[str, str] | None = None,
    *,
    db_url: str | None = None,
) -> pd.DataFrame:
    """
    Build a longform DataFrame of multi-timeframe EMAs on a DAILY grid.

    UPDATED BEHAVIOR (preview-style roll + seeded history):

    - We always load *full* daily history (or at least from a fixed early
      date) so that EMA periods (10, 21, 50, 100, 200) have enough TF-bar
      history to be well-defined, even when `start` is near "today".

    - The `start` / `end` arguments now control the *output window* only:
        * we compute EMAs using full history
        * then filter the final result to ts in [start, end] if provided.
    """
    tfs = tfs or TIMEFRAME_FREQS
    ema_periods = [int(p) for p in ema_periods]
    ids = list(ids)
    if not ids:
        raise ValueError("ids must be a non-empty iterable of asset ids")

    # --- NEW: decouple load window from output window --------------------
    # We need enough historical daily data to compute higher-TF EMAs with
    # min_periods = p. If we only load from `start` (which in incremental
    # mode is often "last_multi_ts.date()"), we end up with too few TF bars
    # and all EMA values stay NaN.
    #
    # So we always load from a fixed early date (or None if you prefer),
    # and later restrict the *returned* frame to [start, end].
    load_start = "2010-01-01"
    daily = load_cmc_ohlcv_daily(
        ids=ids,
        start=load_start,
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
        closes_by_asset = _compute_tf_closes_by_asset(daily, ids, freq=freq)

        # 2) For each asset and EMA period, compute canonical TF-bar EMA
        #    and preview-style daily EMA.
        for asset_id in ids:
            df_id = daily[daily["id"] == asset_id].copy()
            if df_id.empty:
                continue

            df_id = df_id.sort_values("ts").reset_index(drop=True)
            df_id["close"] = df_id["close"].astype(float)
            closes_ts = closes_by_asset.get(asset_id)

            # If we have no detected closes for this asset/timeframe, skip it.
            if closes_ts is None or len(closes_ts) == 0:
                continue

            # Subset to the TRUE TF closes for canonical EMA
            df_closes = df_id[df_id["ts"].isin(closes_ts)].copy()
            if df_closes.empty:
                continue

            for p in ema_periods:
                # 2a) Canonical EMA on higher-TF closes using period=p TF bars
                ema_bar = compute_ema(
                    df_closes["close"],
                    period=p,
                    adjust=False,
                    min_periods=p,
                )

                bar_df = df_closes[["ts"]].copy()
                bar_df["ema_bar"] = ema_bar
                # Only keep rows where EMA is defined (after we have p bars)
                bar_df = bar_df[bar_df["ema_bar"].notna()]
                if bar_df.empty:
                    continue

                alpha_bar = 2.0 / (p + 1.0)

                # 2b) Build DAILY preview EMA driven only by last completed bar EMA
                out = df_id[["ts", "close"]].copy()

                # Attach canonical EMA at true closes
                out = out.merge(bar_df, on="ts", how="left")

                # ema_prev_bar: EMA of the last *completed* TF bar
                # We want the previous bar's EMA even on the bar-close row,
                # so we forward-fill and then shift by 1 row.
                out["ema_prev_bar"] = out["ema_bar"].ffill().shift(1)

                # Preview EMA for every daily row where we have a previous bar EMA
                out["ema_preview"] = alpha_bar * out["close"] + (1.0 - alpha_bar) * out[
                    "ema_prev_bar"
                ]

                # Final EMA:
                # - On TF closes: use canonical ema_bar (TF-bar EMA)
                # - On non-closes: use preview EMA
                out["ema"] = out["ema_preview"]
                mask_bar = out["ema_bar"].notna()
                out.loc[mask_bar, "ema"] = out.loc[mask_bar, "ema_bar"]

                # Drop rows where EMA is still undefined (before first valid bar EMA)
                out = out[out["ema"].notna()]
                if out.empty:
                    continue

                out["id"] = asset_id
                out["tf"] = tf_label
                out["period"] = p
                out["tf_days"] = tf_day_value

                # roll flag:
                #   roll = FALSE → ts is a true higher-TF close (canonical EMA)
                #   roll = TRUE  → preview / intrabar EMA
                is_close = out["ts"].isin(bar_df["ts"])
                out["roll"] = ~is_close

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

    # --- NEW: output window restriction ---------------------------------
    if start is not None:
        start_ts = pd.to_datetime(start, utc=True)
        result_df = result_df[result_df["ts"] >= start_ts]
    if end is not None:
        end_ts = pd.to_datetime(end, utc=True)
        result_df = result_df[result_df["ts"] <= end_ts]

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
    update_existing: bool = True,
) -> int:
    """
    Compute multi-timeframe EMAs with preview-style roll and upsert into
    cmc_ema_multi_tf.

    Columns written:

        id, tf, ts, period, ema, tf_days, roll, d1, d2, d1_roll, d2_roll

    Assumes UNIQUE (id, tf, ts, period) on the target table.

    Parameters
    ----------
    ids : iterable of int
        Asset ids to compute.
    start, end : str or None
        Date range passed through to the EMA builder.
    update_existing : bool, default True
        If True, existing EMA rows in [start, end] are UPDATED on conflict.
        If False, ON CONFLICT DO NOTHING is used, so only new timestamps
        are inserted and existing rows are left unchanged.
    """
    engine = _get_engine(db_url)

    df = build_multi_timeframe_ema_frame(
        ids=ids,
        start=start,
        end=end,
        ema_periods=ema_periods,
        tfs=tfs,
        db_url=db_url,
        # price_table is intentionally NOT passed; the builder uses load_cmc_ohlcv_daily
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
                id,
                tf,
                ts,
                period,
                ema,
                tf_days,
                roll,
                d1,
                d2,
                d1_roll,
                d2_roll
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
        if update_existing:
            conflict_sql = """
        DO UPDATE SET
            ema      = EXCLUDED.ema,
            tf_days  = EXCLUDED.tf_days,
            roll     = EXCLUDED.roll,
            d1       = EXCLUDED.d1,
            d2       = EXCLUDED.d2,
            d1_roll  = EXCLUDED.d1_roll,
            d2_roll  = EXCLUDED.d2_roll
        """
        else:
            conflict_sql = "DO NOTHING"

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
        {conflict_sql};
        """
        res = conn.execute(text(sql))
        return res.rowcount
