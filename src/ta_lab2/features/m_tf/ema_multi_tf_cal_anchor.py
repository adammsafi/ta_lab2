from __future__ import annotations

"""
Year-anchored calendar-aligned multi-timeframe EMA builder for
cmc_ema_multi_tf_cal_anchor.

This is a variant of ema_multi_tf_cal.py that:

- Uses the same calendar timeframes (W-SAT, 1M/2M/3M/6M/9M/12M, etc.)
- BUT allows **partial initial calendar blocks** for month-based
  timeframes, anchored to explicit month-end dates.

Example for an asset whose first bar is 2011-07-11:

    - 2M: closes at ~2011-08-31, 2011-10-31, 2011-12-31 (roll = FALSE)
    - 3M: closes at ~2011-09-30, 2011-12-31 (roll = FALSE)
    - 6M: closes at ~2011-12-31 (roll = FALSE)
    - 12M: closes at ~2011-12-31 (roll = FALSE)

i.e. the first year can have partial blocks that still produce
canonical closes aligned to month-ends / year-end.

Preview semantics are similar to cmc_ema_multi_tf_cal, but here:

    * ema      is a continuous DAILY-ALPHA EMA on the daily grid,
               seeded once the first canonical bar EMA exists and
               never reset at later bar closes.
    * ema_bar  is the anchored bar-space EMA with daily-equivalent
               propagation inside each anchor window.

Output columns match cmc_ema_multi_tf_cal, but we write into a
separate table: cmc_ema_multi_tf_cal_anchor.

Expected schema for public.cmc_ema_multi_tf_cal_anchor:

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
    "TIMEFRAME_FREQS_CAL_ANCHOR",
    "TF_DAYS",
    "build_multi_timeframe_ema_cal_anchor_frame",
    "write_multi_timeframe_ema_cal_anchor_to_db",
]

# ---------------------------------------------------------------------------
# Timeframe configuration (calendar-aligned)
# ---------------------------------------------------------------------------

# Label → pandas resample frequency
# Weekly timeframes are anchored to SATURDAY ends: W-SAT, 2W-SAT, etc.
TIMEFRAME_FREQS_CAL_ANCHOR: Dict[str, str] = {
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


# ---------------------------------------------------------------------------
# Month-based canonical closes (partial initial blocks, year-anchored)
# ---------------------------------------------------------------------------


def _compute_monthly_canonical_closes_anchor(
    df_id: pd.DataFrame,
    tf_label: str,
) -> pd.DatetimeIndex:
    """
    Compute canonical close timestamps for month-based timeframes using
    **partial** calendar blocks anchored to specific month-ends.

    Key differences vs the strict cal version:

    - We do NOT require that the full span of months lies _after_ the
      asset's first local calendar date.
    - Instead, we:

        * Generate all candidate local month-end dates whose months
          match the TF pattern (2M, 3M, 6M, 12M, etc.).
        * Keep those whose month-end is between [first_date_local,
          last_date_local].
        * For each month-end E_i, define a block (prev_E_i, E_i] in
          local calendar time and choose the last available timestamp
          in that block as the canonical close.

    This means for 2M with data starting 2011-07-11 we will get:

        - E_1 = 2011-08-31 → block [2011-07-11, 2011-08-31]
        - E_2 = 2011-10-31 → block (2011-08-31, 2011-10-31]
        - E_3 = 2011-12-31 → block (2011-10-31, 2011-12-31]

    yielding 2M closes at the last traded bar on/near those dates.
    """
    if df_id.empty:
        return pd.DatetimeIndex([], tz="UTC")

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
            f"_compute_monthly_canonical_closes_anchor called for non-month tf: {tf_label}"
        )

    # Month-ends we consider as anchors for each tf (1-based month numbers)
    end_months = {
        "1M": list(range(1, 13)),     # every month-end
        "2M": [2, 4, 6, 8, 10, 12],   # even month-ends
        "3M": [3, 6, 9, 12],          # quarter-ends
        "6M": [6, 12],                # half-year ends
        "9M": [9, 12],                # simple 9M pattern
        "12M": [12],                  # year-end
    }

    months_for_tf = end_months[tf_label]

    # Generate candidate month-end dates in local calendar
    candidates: list[pd.Timestamp] = []
    start_year = first_date_local.year
    end_year = last_date_local.year

    for y in range(start_year, end_year + 1):
        for m in months_for_tf:
            # month-end: take first of next month, subtract 1 day
            if m == 12:
                next_month = pd.Timestamp(
                    year=y + 1, month=1, day=1, tz="America/New_York"
                )
            else:
                next_month = pd.Timestamp(
                    year=y, month=m + 1, day=1, tz="America/New_York"
                )
            end_local = (next_month - pd.Timedelta(days=1)).normalize()

            if first_date_local <= end_local <= last_date_local:
                candidates.append(end_local)

    if not candidates:
        return pd.DatetimeIndex([], tz="UTC")

    candidates = sorted(set(candidates))

    closes: list[pd.Timestamp] = []
    prev_end: pd.Timestamp | None = None

    for end_date_local in candidates:
        if prev_end is None:
            # First block: [first_date_local, end_date_local]
            mask = (df["date_local"] >= first_date_local) & (
                df["date_local"] <= end_date_local
            )
        else:
            # Subsequent blocks: (prev_end, end_date_local]
            mask = (df["date_local"] > prev_end) & (
                df["date_local"] <= end_date_local
            )

        if not mask.any():
            prev_end = end_date_local
            continue

        block_close_ts = df.loc[mask, "ts"].max()
        closes.append(block_close_ts)
        prev_end = end_date_local

    if not closes:
        return pd.DatetimeIndex([], tz="UTC")

    return pd.DatetimeIndex(sorted(closes))


def _compute_tf_closes_by_asset_anchor(
    daily: pd.DataFrame,
    ids: Iterable[int],
    tf_label: str,
    freq: str,
) -> Dict[int, pd.DatetimeIndex]:
    """
    For each asset id, compute the *actual daily timestamps* that are the
    last bar in each higher-TF resample bucket, using the given frequency.

    - For day/weekly tfs we use pandas resample on the daily grid,
      and drop the most recent (in-progress) bucket.
    - For month-based tfs (1M, 2M, 3M, 6M, 9M, 12M) we derive canonical
      calendar endpoints from the underlying daily series using
      `_compute_monthly_canonical_closes_anchor`, which allows
      partial initial blocks.
    """
    closes_by_asset: Dict[int, pd.DatetimeIndex] = {}

    is_month_tf = tf_label.endswith("M")

    for asset_id in ids:
        df_id = daily[daily["id"] == asset_id].copy()
        if df_id.empty:
            continue

        df_id = df_id.sort_values("ts")

        if is_month_tf:
            closes_ts = _compute_monthly_canonical_closes_anchor(df_id, tf_label)
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


# ---------------------------------------------------------------------------
# Frame builder
# ---------------------------------------------------------------------------


def build_multi_timeframe_ema_cal_anchor_frame(
    ids: Iterable[int],
    start: str | None = "2010-01-01",
    end: str | None = None,
    ema_periods: Iterable[int] = (10, 21, 50, 100, 200),
    tfs: Dict[str, str] | None = None,
    *,
    db_url: str | None = None,
) -> pd.DataFrame:
    """
    Build a longform DataFrame of year-anchored, calendar-aligned
    multi-timeframe EMAs on a DAILY grid.

    We always load sufficient history for EMA stability, and only
    restrict the *output* to [start, end].

    Output columns (per id, tf, ts, period):

        ema         : continuous DAILY-ALPHA EMA on the daily grid
        tf_days     : effective days per bar
        roll        : FALSE at anchored closes, TRUE on preview days
        d1, d2      : closing-only diffs on ema   (roll = FALSE only)
        d1_roll     : per-day diffs on ema        (all rows)
        d2_roll     : per-day diffs of d1_roll    (all rows)

        ema_bar     : anchored bar-space EMA, propagated daily
        roll_bar    : FALSE at anchored bar closes, TRUE intra-bar
        d1_bar      : bar-to-bar diffs on ema_bar (roll_bar = FALSE)
        d2_bar      : second diff on bar closes
        d1_roll_bar : per-day diffs on ema_bar    (all rows)
        d2_roll_bar : per-day diffs of d1_roll_bar (all rows)
    """
    tfs = tfs or TIMEFRAME_FREQS_CAL_ANCHOR
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
        print(f"[CAL-ANCHOR] Processing timeframe {tf_label} (freq={freq}).")

        if tf_label not in TF_DAYS:
            raise KeyError(f"No tf_days mapping defined for timeframe '{tf_label}'")

        tf_day_value = TF_DAYS[tf_label]

        # 1) Detect TRUE closes for this calendar-aligned timeframe per asset id
        closes_by_asset = _compute_tf_closes_by_asset_anchor(
            daily, ids, tf_label, freq
        )

        # 2) For each asset and EMA period, compute canonical TF-bar EMA
        #    and daily-alpha ema + bar-space ema_bar.
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
                # 2a) Canonical EMA on higher-TF closes using period = p TF bars
                ema_bar_sparse = compute_ema(
                    df_closes["close"],
                    period=p,
                    adjust=False,
                    min_periods=p,
                )

                bar_df = df_closes[["ts"]].copy()
                bar_df["ema_bar_close"] = ema_bar_sparse
                # Only keep rows where EMA is defined (after we have p bars)
                bar_df = bar_df[bar_df["ema_bar_close"].notna()]
                if bar_df.empty:
                    continue

                # Daily-equivalent alpha for both ema (daily) and ema_bar intra-bar
                alpha_daily_eq = 2.0 / (tf_day_value * p + 1.0)

                # 2b) Build DAILY frame
                out = df_id[["ts", "close"]].copy()

                # Attach canonical bar-space EMA at true closes (for ema_bar & seeding)
                out = out.merge(bar_df, on="ts", how="left")
                mask_bar_close = out["ema_bar_close"].notna()

                # roll flag:
                #   roll = FALSE → ts is a true higher-TF close (canonical boundary)
                #   roll = TRUE  → interior / intrabar day
                is_close = out["ts"].isin(bar_df["ts"])
                out["roll"] = ~is_close

                # ---- ema: continuous DAILY-ALPHA EMA, seeded at first canonical bar EMA
                ema_full: list[float] = []
                ema_last: float | None = None

                bar_close_map = dict(
                    zip(
                        bar_df["ts"].to_numpy(),
                        bar_df["ema_bar_close"].to_numpy(),
                    )
                )

                for ts_val, close_val in zip(
                    out["ts"].to_numpy(), out["close"].to_numpy()
                ):
                    canonical = bar_close_map.get(ts_val)

                    if ema_last is None:
                        # Haven't started yet: seed only when we hit the first
                        # canonical bar EMA (partial first bar allowed).
                        if canonical is not None:
                            ema_last = float(canonical)
                            ema_full.append(ema_last)
                        else:
                            ema_full.append(np.nan)
                    else:
                        # Pure daily-alpha update, no reset at later bar closes
                        ema_today = float(
                            alpha_daily_eq * close_val
                            + (1.0 - alpha_daily_eq) * ema_last
                        )
                        ema_last = ema_today
                        ema_full.append(ema_today)

                out["ema"] = ema_full

                # Drop rows where EMA is still undefined (before the first bar EMA seed)
                out = out[out["ema"].notna()]
                if out.empty:
                    continue

                out["id"] = asset_id
                out["tf"] = tf_label
                out["period"] = p
                out["tf_days"] = tf_day_value

                # 2c) Anchored bar-space EMA: ema_bar, with intra-bar daily alpha
                ema_bar_full: list[float] = []
                ema_last_day: float | None = None

                bar_close_map_bar = dict(
                    zip(
                        bar_df["ts"].to_numpy(),
                        bar_df["ema_bar_close"].to_numpy(),
                    )
                )

                for ts_val, close_val in zip(
                    out["ts"].to_numpy(), out["close"].to_numpy()
                ):
                    canonical = bar_close_map_bar.get(ts_val)

                    if canonical is not None:
                        # Anchored bar close: jump to canonical bar EMA
                        ema_last_day = float(canonical)
                        ema_bar_full.append(ema_last_day)
                    elif ema_last_day is not None:
                        # Intra-bar day: propagate with daily-equivalent alpha
                        ema_today = float(
                            alpha_daily_eq * close_val
                            + (1.0 - alpha_daily_eq) * ema_last_day
                        )
                        ema_last_day = ema_today
                        ema_bar_full.append(ema_today)
                    else:
                        # Before first canonical bar EMA exists
                        ema_bar_full.append(np.nan)

                out["ema_bar"] = ema_bar_full

                # roll_bar semantics for _anchor_bar:
                #   roll_bar = FALSE → anchored bar close (canonical boundary)
                #   roll_bar = TRUE  → intra-bar day (daily alpha updates)
                out["roll_bar"] = True
                out.loc[out["ts"].isin(bar_df["ts"]), "roll_bar"] = False

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
                            "ema_bar",
                            "roll_bar",
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
                "ema_bar",
                "d1_bar",
                "d2_bar",
                "roll_bar",
                "d1_roll_bar",
                "d2_roll_bar",
            ]
        )

    result_df = pd.concat(frames, ignore_index=True)
    result_df["ts"] = pd.to_datetime(result_df["ts"], utc=True)

    # Sort for group-wise diffs
    sort_cols = ["id", "tf", "period", "ts"]
    result_df = result_df.sort_values(sort_cols)

    # 1) Rolling per-day diffs on ema: d1_roll, d2_roll
    g_full = result_df.groupby(["id", "tf", "period"], sort=False)
    result_df["d1_roll"] = g_full["ema"].diff()
    result_df["d2_roll"] = g_full["d1_roll"].diff()

    # 2) Closing-only diffs on ema: d1, d2 (only where roll = FALSE)
    result_df["d1"] = np.nan
    result_df["d2"] = np.nan

    mask_close = ~result_df["roll"]
    if mask_close.any():
        close_df = result_df.loc[mask_close].copy()
        g_close = close_df.groupby(["id", "tf", "period"], sort=False)
        close_df["d1"] = g_close["ema"].diff()
        close_df["d2"] = close_df["d1"].diff()

        # Write back only on closing rows
        result_df.loc[close_df.index, "d1"] = close_df["d1"]
        result_df.loc[close_df.index, "d2"] = close_df["d2"]

    # 3) BAR-SPACE derivatives for ema_bar
    result_df["d1_bar"] = np.nan
    result_df["d2_bar"] = np.nan
    result_df["d1_roll_bar"] = np.nan
    result_df["d2_roll_bar"] = np.nan

    # Bar closes (anchored boundaries)
    mask_bar_close_all = ~result_df["roll_bar"]

    if mask_bar_close_all.any():
        bar_close_df = result_df.loc[mask_bar_close_all].copy()
        g_bar = bar_close_df.groupby(["id", "tf", "period"], sort=False)

        # d1_bar / d2_bar: only bar-to-bar on those anchored closes
        bar_close_df["d1_bar"] = g_bar["ema_bar"].diff()
        bar_close_df["d2_bar"] = bar_close_df["d1_bar"].diff()

        result_df.loc[bar_close_df.index, "d1_bar"] = bar_close_df["d1_bar"]
        result_df.loc[bar_close_df.index, "d2_bar"] = bar_close_df["d2_bar"]

    # d1_roll_bar / d2_roll_bar: full daily diffs on ema_bar
    result_df["d1_roll_bar"] = g_full["ema_bar"].diff()
    result_df["d2_roll_bar"] = g_full["d1_roll_bar"].diff()

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
            "ema_bar",
            "d1_bar",
            "d2_bar",
            "roll_bar",
            "d1_roll_bar",
            "d2_roll_bar",
        ]
    ]


# ---------------------------------------------------------------------------
# DB writer
# ---------------------------------------------------------------------------


def write_multi_timeframe_ema_cal_anchor_to_db(
    ids: Iterable[int],
    start: str = "2010-01-01",
    end: str | None = None,
    ema_periods: Iterable[int] = (10, 21, 50, 100, 200),
    tfs: Dict[str, str] | None = None,
    db_url: str | None = None,
    schema: str = "public",
    price_table: str = "cmc_price_histories7",  # kept for API compatibility; not used here
    out_table: str = "cmc_ema_multi_tf_cal_anchor",
    update_existing: bool = True,
) -> int:
    """
    Compute year-anchored calendar-aligned multi-timeframe EMAs with
    preview-style roll + anchored bar-space EMA, and upsert into
    cmc_ema_multi_tf_cal_anchor.

    Columns written:

        id, tf, ts, period,
        ema, tf_days, roll,
        d1, d2, d1_roll, d2_roll,
        ema_bar, d1_bar, d2_bar,
        roll_bar, d1_roll_bar, d2_roll_bar

    Assumes UNIQUE (id, tf, ts, period) on the target table.
    """
    engine = _get_engine(db_url)

    df = build_multi_timeframe_ema_cal_anchor_frame(
        ids=ids,
        start=start,
        end=end,
        ema_periods=ema_periods,
        tfs=tfs,
        db_url=db_url,
    )

    if df.empty:
        print("No calendar-anchored multi-timeframe EMA rows generated.")
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
                d2_roll,
                ema_bar,
                d1_bar,
                d2_bar,
                roll_bar,
                d1_roll_bar,
                d2_roll_bar
            FROM {schema}.{out_table}
            LIMIT 0;
            """
                # If the out_table does not yet exist, create it first in SQL.
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
            ema          = EXCLUDED.ema,
            tf_days      = EXCLUDED.tf_days,
            roll         = EXCLUDED.roll,
            d1           = EXCLUDED.d1,
            d2           = EXCLUDED.d2,
            d1_roll      = EXCLUDED.d1_roll,
            d2_roll      = EXCLUDED.d2_roll,
            ema_bar      = EXCLUDED.ema_bar,
            d1_bar       = EXCLUDED.d1_bar,
            d2_bar       = EXCLUDED.d2_bar,
            roll_bar     = EXCLUDED.roll_bar,
            d1_roll_bar  = EXCLUDED.d1_roll_bar,
            d2_roll_bar  = EXCLUDED.d2_roll_bar
        """
        else:
            conflict_sql = "DO NOTHING"

        sql = f"""
        INSERT INTO {schema}.{out_table} AS t
            (id,
             tf,
             ts,
             period,
             ema,
             tf_days,
             roll,
             d1,
             d2,
             d1_roll,
             d2_roll,
             ema_bar,
             d1_bar,
             d2_bar,
             roll_bar,
             d1_roll_bar,
             d2_roll_bar)
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
            d2_roll,
            ema_bar,
            d1_bar,
            d2_bar,
            roll_bar,
            d1_roll_bar,
            d2_roll_bar
        FROM {tmp_table}
        ON CONFLICT (id, tf, ts, period)
        {conflict_sql};
        """
        res = conn.execute(text(sql))
        return res.rowcount
