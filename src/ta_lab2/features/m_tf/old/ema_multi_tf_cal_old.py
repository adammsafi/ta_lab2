from __future__ import annotations

"""
Calendar-aligned multi-timeframe EMA builder for cmc_ema_multi_tf_cal.

This is a variant of ema_multi_timeframe.py that:

- Uses explicit calendar-aligned timeframes, especially for weeks:
    * 1W, 2W, 3W, 4W, 6W, 8W, 10W → W-SAT anchored
      (weeks end on Saturday; closes should be Saturday daily bars).

- Keeps the same preview-style roll semantics:

    * For each (id, tf, period=p):

        - Compute the canonical EMA on TRUE higher-TF closes using
          period = p TF bars. These rows have roll = FALSE.

        - On daily rows between closes, compute a preview EMA that
          uses the last completed TF-bar EMA but does NOT feed into
          future bar EMA. These rows have roll = TRUE.

- Output columns match cmc_ema_multi_tf, but this module is intended
  to write into a separate table: cmc_ema_multi_tf_cal.

Expected schema for public.cmc_ema_multi_tf_cal:

    id        int
    tf        text
    ts        timestamptz
    period    int
    ema       double precision
    tf_days   int
    roll      boolean               -- FALSE = true close, TRUE = preview
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
    "TIMEFRAME_FREQS_CAL",
    "TF_DAYS",
    "build_multi_timeframe_ema_cal_frame",
    "write_multi_timeframe_ema_cal_to_db",
]

# ---------------------------------------------------------------------------
# Timeframe configuration (calendar-aligned)
# ---------------------------------------------------------------------------

# Label → pandas resample frequency
# Weekly timeframes are anchored to SATURDAY ends: W-SAT, 2W-SAT, etc.
TIMEFRAME_FREQS_CAL: Dict[str, str] = {
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
    # week-end SATURDAY
    "1W": "W-SAT",
    "2W": "2W-SAT",
    "3W": "3W-SAT",
    "4W": "4W-SAT",
    "6W": "6W-SAT",
    "8W": "8W-SAT",
    "10W": "10W-SAT",
    # month-end anchored (use ME to avoid FutureWarning)
    "1M": "1ME",
    "2M": "2ME",
    "3M": "3ME",
    "6M": "6ME",
    "9M": "9ME",
    "12M": "12ME",
}

# Same tf_days mapping as the main EMA module
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


def _compute_monthly_canonical_closes(
    df_id: pd.DataFrame,
    tf_label: str,
) -> pd.DatetimeIndex:
    """
    Compute canonical close timestamps for month-based timeframes using
    full calendar blocks in *local* (America/New_York) calendar time.

    Bars:

    - Are defined on calendar months (or multi-month blocks).
    - Start at 1st of an anchored month (1, 2, 4, 7, etc. depending on tf).
    - Require that the entire calendar block lies after the asset's first
      local-date bar; partial initial blocks are skipped.
    - Canonical close is the last available trading *timestamp* in the block,
      but the block boundaries are defined on local dates.

    This fixes the off-by-one-day issue where 6M closes were landing on
    06-29 / 12-30 instead of 06-30 / 12-31.
    """
    if df_id.empty:
        return pd.DatetimeIndex([], tz="UTC")

    # Work on a copy, and define a local (ET) view for calendar math
    df = df_id.copy().sort_values("ts")
    df["ts_local"] = df["ts"].dt.tz_convert("America/New_York")
    df["date_local"] = df["ts_local"].dt.normalize()

    first_date_local = df["date_local"].min()
    last_date_local = df["date_local"].max()

    # How many calendar months each tf spans
    span_months = {
        "1M": 1,
        "2M": 2,
        "3M": 3,
        "6M": 6,
        "9M": 9,
        "12M": 12,
    }
    if tf_label not in span_months:
        raise ValueError(
            f"_compute_monthly_canonical_closes called for non-month tf: {tf_label}"
        )

    # Anchor start months for each tf (1-based month numbers)
    anchor_months = {
        "1M": list(range(1, 13)),     # any month
        "2M": [2, 4, 6, 8, 10, 12],   # even months (2M blocks)
        "3M": [1, 4, 7, 10],          # quarter starts
        "6M": [1, 7],                 # half-year starts
        "9M": [1, 4, 7, 10],          # simple 9M anchors (3M step)
        "12M": [1],                   # year start
    }

    span = span_months[tf_label]
    allowed_months = anchor_months[tf_label]

    # Generate all possible bar *starts* in local calendar
    starts_local: list[pd.Timestamp] = []
    start_year = first_date_local.year
    end_year = last_date_local.year + 1  # small buffer

    for y in range(start_year, end_year + 1):
        for m in allowed_months:
            start_local = pd.Timestamp(year=y, month=m, day=1, tz="America/New_York")
            if start_local.normalize() < first_date_local:
                continue
            if start_local.normalize() > last_date_local:
                continue
            starts_local.append(start_local)

    if not starts_local:
        return pd.DatetimeIndex([], tz="UTC")

    closes: list[pd.Timestamp] = []

    for start_local in sorted(starts_local):
        # End of the block in local calendar:
        # last local date before (start + span months)
        end_local = (start_local + pd.DateOffset(months=span)) - pd.Timedelta(days=1)
        end_date_local = end_local.normalize()

        if end_date_local > last_date_local:
            # We don't have a full block's worth of local calendar yet;
            # treat this and later starts as incomplete.
            continue

        # Rows whose *local* date is within [start_date_local, end_date_local]
        start_date_local = start_local.normalize()
        mask = (df["date_local"] >= start_date_local) & (
            df["date_local"] <= end_date_local
        )
        if not mask.any():
            continue

        # Canonical close: last actual timestamp in UTC, but within that local window
        block_close_ts = df.loc[mask, "ts"].max()
        closes.append(block_close_ts)

    if not closes:
        return pd.DatetimeIndex([], tz="UTC")

    return pd.DatetimeIndex(sorted(closes))



def _compute_tf_closes_by_asset(
    daily: pd.DataFrame,
    ids: Iterable[int],
    tf_label: str,
    freq: str,
) -> Dict[int, pd.DatetimeIndex]:
    """
    For each asset id, compute the *actual daily timestamps* that are the
    last bar in each higher-TF resample bucket, using the given frequency.

    This is updated to mirror the desired calendar logic for month-based
    timeframes:

        - For day/weekly tfs we use pandas resample on the daily grid,
          and drop the most recent (in-progress) bucket.
        - For month-based tfs (1M, 2M, 3M, 6M, 9M, 12M) we derive canonical
          calendar endpoints from the underlying daily series, skipping
          any partial initial or trailing blocks.

    As before, canonical closes (returned here) are where roll = False;
    all interior daily rows between these closes will be roll = True.
    """
    closes_by_asset: Dict[int, pd.DatetimeIndex] = {}

    is_month_tf = tf_label.endswith("M")

    for asset_id in ids:
        df_id = daily[daily["id"] == asset_id].copy()
        if df_id.empty:
            continue

        df_id = df_id.sort_values("ts")

        if is_month_tf:
            closes_ts = _compute_monthly_canonical_closes(df_id, tf_label)
            if len(closes_ts) == 0:
                continue
        else:
            # Non-monthly: retain the original resample-based logic,
            # but drop the last (in-progress) bucket.
            s = df_id.set_index("ts")["close"]
            grouped = s.resample(freq, label="right", closed="right")
            last_ts_per_group = grouped.apply(lambda x: x.index.max())

            last_ts_per_group = last_ts_per_group.dropna()
            if last_ts_per_group.empty:
                continue

            if len(last_ts_per_group) <= 1:
                continue  # no completed TF bars yet for this asset
            else:
                last_ts_per_group = last_ts_per_group.iloc[:-1]

            closes_ts = pd.to_datetime(last_ts_per_group.values, utc=True)

        closes_by_asset[asset_id] = closes_ts

    return closes_by_asset


def build_multi_timeframe_ema_cal_frame(
    ids: Iterable[int],
    start: str | None = "2010-01-01",
    end: str | None = None,
    ema_periods: Iterable[int] = (10, 21, 50, 100, 200),
    tfs: Dict[str, str] | None = None,
    *,
    db_url: str | None = None,
) -> pd.DataFrame:
    """
    Build a longform DataFrame of calendar-aligned multi-timeframe EMAs
    on a DAILY grid.

    We always load sufficient history for EMA stability, and only
    restrict the *output* to [start, end].
    """
    tfs = tfs or TIMEFRAME_FREQS_CAL
    ema_periods = [int(p) for p in ema_periods]
    ids = list(ids)
    if not ids:
        raise ValueError("ids must be a non-empty iterable of asset ids")

    # Decouple load vs output windows.
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
        print(f"[CAL] Processing timeframe {tf_label} (freq={freq})...")

        if tf_label not in TF_DAYS:
            raise KeyError(f"No tf_days mapping defined for timeframe '{tf_label}'")

        tf_day_value = TF_DAYS[tf_label]

        # 1) Detect TRUE closes for this calendar-aligned timeframe per asset id
        closes_by_asset = _compute_tf_closes_by_asset(daily, ids, tf_label, freq)

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

    # Output window restriction
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


def write_multi_timeframe_ema_cal_to_db(
    ids: Iterable[int],
    start: str = "2010-01-01",
    end: str | None = None,
    ema_periods: Iterable[int] = (10, 21, 50, 100, 200),
    tfs: Dict[str, str] | None = None,
    db_url: str | None = None,
    schema: str = "public",
    price_table: str = "cmc_price_histories7",  # kept for API compatibility; not used here
    out_table: str = "cmc_ema_multi_tf_cal",
    update_existing: bool = True,
) -> int:
    """
    Compute calendar-aligned multi-timeframe EMAs with preview-style roll
    and upsert into cmc_ema_multi_tf_cal.

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

    df = build_multi_timeframe_ema_cal_frame(
        ids=ids,
        start=start,
        end=end,
        ema_periods=ema_periods,
        tfs=tfs,
        db_url=db_url,
    )

    if df.empty:
        print("No calendar-aligned multi-timeframe EMA rows generated.")
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
