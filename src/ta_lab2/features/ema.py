# src/ta_lab2/features/ema.py
from __future__ import annotations

from typing import Iterable, Optional, Sequence

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from ta_lab2.config import TARGET_DB_URL
from ta_lab2.io import load_cmc_ohlcv_daily

__all__ = [
    "compute_ema",
    "add_ema_columns",
    "add_ema_d1",
    "add_ema_d2",
    "prepare_ema_helpers",
    "add_ema_diffs_longform",
]

# ---------------------------------------------------------------------------
# Core EMA helper
# ---------------------------------------------------------------------------


def compute_ema(
    s: pd.Series,
    period: int | None = None,
    *,
    adjust: bool = False,
    min_periods: Optional[int] = None,
    name: Optional[str] = None,
    window: int | None = None,
    **kwargs,
) -> pd.Series:
    """
    Series EMA with a Pandas-backed implementation.

    Parameters
    ----------
    s : pd.Series
        Input series.
    period : int | None
        EMA period. Canonical argument.
    window : int | None
        Backwards-compatible alias for `period`.
    adjust, min_periods, name :
        Passed through to `Series.ewm`.

    Any extra **kwargs are accepted for backward-compatibility and ignored.
    """
    # Allow either `period` or `window`
    if period is None and window is None:
        raise TypeError("compute_ema() requires either `period` or `window`")

    if period is None:
        period = int(window)
    else:
        period = int(period)

    out = (
        s.astype(float)
        .ewm(span=period, adjust=adjust, min_periods=min_periods)
        .mean()
    )
    if name is not None:
        out = out.rename(name)
    return out


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _flip_for_direction(obj: pd.DataFrame | pd.Series, direction: str):
    """
    If data are newest-first, flip to chronological for diff/EMA, and tell caller
    to flip back afterwards.
    """
    if direction not in ("oldest_top", "newest_top"):
        return obj, False
    if direction == "newest_top":
        return obj.iloc[::-1], True
    return obj, False


def _maybe_round(s: pd.Series, round_places: Optional[int]) -> pd.Series:
    return s.round(round_places) if round_places is not None else s


def _ensure_list(x: Sequence[str] | Iterable[str]) -> list[str]:
    return list(x) if not isinstance(x, list) else x


# ---------------------------------------------------------------------------
# Column builders (in-place, return df)
# ---------------------------------------------------------------------------


def add_ema_columns(
    df: pd.DataFrame,
    base_price_cols: Sequence[str] | None,
    ema_periods: Sequence[int] | None,
    *,
    direction: str = "oldest_top",
    overwrite: bool = False,
    round_places: Optional[int] = None,
    adjust: bool = False,
    min_periods: Optional[int] = None,
    # legacy alias
    price_cols: Sequence[str] | None = None,
    **kwargs,
) -> pd.DataFrame:
    """
    For each `col` in base_price_cols and each `w` in ema_periods, add:
      `{col}_ema_{w}`

    Accepts legacy kwargs and aliases but ignores them.
    """
    if base_price_cols is None:
        base_price_cols = price_cols or []
    if ema_periods is None:
        ema_periods = ema_periods or []

    base_price_cols = _ensure_list(base_price_cols)
    ema_periods = [int(w) for w in ema_periods]

    work, flipped = _flip_for_direction(df, direction)

    new_cols: dict[str, pd.Series] = {}
    for col in base_price_cols:
        if col not in work.columns:
            continue
        s = work[col].astype(float)
        for w in ema_periods:
            out_name = f"{col}_ema_{w}"
            if not overwrite and out_name in df.columns:
                continue
            ema = compute_ema(
                s,
                w,
                adjust=adjust,
                min_periods=min_periods,
                name=out_name,
            )
            if flipped:
                ema = ema.iloc[::-1]
            ema = _maybe_round(ema, round_places)
            new_cols[out_name] = ema

    if new_cols:
        df[list(new_cols.keys())] = pd.DataFrame(new_cols, index=df.index)
    return df


def add_ema_d1(
    df: pd.DataFrame,
    base_price_cols: Sequence[str] | None,
    ema_periods: Sequence[int] | None,
    *,
    direction: str = "oldest_top",
    overwrite: bool = False,
    round_places: Optional[int] = None,
    price_cols: Sequence[str] | None = None,
    **kwargs,
) -> pd.DataFrame:
    """
    First difference of EMA:
      `{col}_ema_{w}_d1 = diff({col}_ema_{w})`
    """
    if base_price_cols is None:
        base_price_cols = price_cols or []
    if ema_periods is None:
        ema_periods = ema_periods or []

    base_price_cols = _ensure_list(base_price_cols)
    ema_periods = [int(w) for w in ema_periods]

    work, flipped = _flip_for_direction(df, direction)

    new_cols: dict[str, pd.Series] = {}
    for col in base_price_cols:
        for w in ema_periods:
            ema_col = f"{col}_ema_{w}"
            if ema_col not in work.columns:
                if col in work.columns:
                    work[ema_col] = compute_ema(work[col].astype(float), w)
                else:
                    continue
            d1_name = f"{ema_col}_d1"
            if not overwrite and d1_name in df.columns:
                continue
            d1 = work[ema_col].astype(float).diff()
            if flipped:
                d1 = d1.iloc[::-1]
            d1 = _maybe_round(d1.rename(d1_name), round_places)
            new_cols[d1_name] = d1

    if new_cols:
        df[list(new_cols.keys())] = pd.DataFrame(new_cols, index=df.index)
    return df


def add_ema_d2(
    df: pd.DataFrame,
    base_price_cols: Sequence[str] | None,
    ema_periods: Sequence[int] | None,
    *,
    direction: str = "oldest_top",
    overwrite: bool = False,
    round_places: Optional[int] = None,
    price_cols: Sequence[str] | None = None,
    **kwargs,
) -> pd.DataFrame:
    """
    Second difference of EMA:
      `{col}_ema_{w}_d2 = diff(diff({col}_ema_{w}))`
    """
    if base_price_cols is None:
        base_price_cols = price_cols or []
    if ema_periods is None:
        ema_periods = ema_periods or []

    base_price_cols = _ensure_list(base_price_cols)
    ema_periods = [int(w) for w in ema_periods]

    work, flipped = _flip_for_direction(df, direction)

    new_cols: dict[str, pd.Series] = {}
    for col in base_price_cols:
        for w in ema_periods:
            ema_col = f"{col}_ema_{w}"
            if ema_col not in work.columns:
                if col in work.columns:
                    work[ema_col] = compute_ema(work[col].astype(float), w)
                else:
                    continue
            d2_name = f"{ema_col}_d2"
            if not overwrite and d2_name in df.columns:
                continue
            d2 = work[ema_col].astype(float).diff().diff()
            if flipped:
                d2 = d2.iloc[::-1]
            d2 = _maybe_round(d2.rename(d2_name), round_places)
            new_cols[d2_name] = d2

    if new_cols:
        df[list(new_cols.keys())] = pd.DataFrame(new_cols, index=df.index)
    return df


# legacy wrapper


def add_ema(
    df: pd.DataFrame,
    col: str = "close",
    periods: Sequence[int] = (21, 50, 100, 200),
    prefix: str = "ema",
):
    """
    Legacy wrapper: adds EMA columns for one price column.
    """
    cols = [col]
    add_ema_columns(df, cols, list(periods))
    return df


# -----------------------------------------------------------------------------
# EMA helper scalers/normalizers
# -----------------------------------------------------------------------------


def prepare_ema_helpers(
    df: pd.DataFrame,
    base_price_cols: Sequence[str] | None,
    ema_periods: Sequence[int] | None,
    *,
    direction: str = "oldest_top",
    scale: str = "bps",  # {"raw","pct","bps"}
    overwrite: bool = False,
    round_places: Optional[int] = 6,
    price_cols: Sequence[str] | None = None,
    periods: Sequence[int] | None = None,
    **kwargs,
) -> pd.DataFrame:
    """
    Ensure first/second EMA diffs exist, then add scaled helper columns for each
    <col, period> pair:

      - {col}_ema_{w}_d1   (1st diff)
      - {col}_ema_{w}_d2   (2nd diff)
      - {col}_ema_{w}_slope
      - {col}_ema_{w}_accel
    """
    if base_price_cols is None:
        base_price_cols = price_cols or []
    if ema_periods is None:
        ema_periods = periods or []

    base_price_cols = _ensure_list(base_price_cols)
    ema_periods = [int(w) for w in ema_periods]

    add_ema_columns(
        df,
        base_price_cols,
        ema_periods,
        direction=direction,
        overwrite=overwrite,
    )
    add_ema_d1(
        df,
        base_price_cols,
        ema_periods,
        direction=direction,
        overwrite=overwrite,
    )
    add_ema_d2(
        df,
        base_price_cols,
        ema_periods,
        direction=direction,
        overwrite=overwrite,
    )

    scale = (scale or "raw").lower()
    if scale not in {"raw", "pct", "bps"}:
        scale = "bps"

    new_cols: dict[str, pd.Series] = {}

    for col in base_price_cols:
        for w in ema_periods:
            ema_col = f"{col}_ema_{w}"
            d1_col = f"{ema_col}_d1"
            d2_col = f"{ema_col}_d2"

            if ema_col not in df.columns:
                if col in df.columns:
                    df[ema_col] = compute_ema(df[col].astype(float), w)
                else:
                    continue

            ema = df[ema_col].astype(float)
            d1 = df[d1_col].astype(float) if d1_col in df.columns else ema.diff()
            d2 = df[d2_col].astype(float) if d2_col in df.columns else ema.diff().diff()

            if scale == "raw":
                slope = d1
                accel = d2
            elif scale == "pct":
                slope = d1 / ema.replace(0.0, np.nan)
                accel = d2 / ema.replace(0.0, np.nan)
            else:  # "bps"
                slope = 1e4 * d1 / ema.replace(0.0, np.nan)
                accel = 1e4 * d2 / ema.replace(0.0, np.nan)

            slope_name = f"{col}_ema_{w}_slope"
            accel_name = f"{col}_ema_{w}_accel"

            if overwrite or slope_name not in df.columns:
                new_cols[slope_name] = _maybe_round(
                    slope.astype(float), round_places
                )
            if overwrite or accel_name not in df.columns:
                new_cols[accel_name] = _maybe_round(
                    accel.astype(float), round_places
                )

    if new_cols:
        df[list(new_cols.keys())] = pd.DataFrame(new_cols, index=df.index)

    return df


# -----------------------------------------------------------------------------
# Long-form EMA diffs
# -----------------------------------------------------------------------------


def add_ema_diffs_longform(
    df: pd.DataFrame,
    *,
    group_cols: Sequence[str] = ("id", "timeframe", "period"),
    ema_col: str = "ema",
    d1_col: str = "d1",
    d2_col: str = "d2",
    time_col: Optional[str] = None,
    round_places: Optional[int] = None,
) -> pd.DataFrame:
    """
    Compute d1 and d2 for a *long-form* EMA table and add them in-place.
    """
    group_cols = list(group_cols)

    missing = [c for c in group_cols if c not in df.columns]
    if missing:
        raise KeyError(f"Missing group_cols in df: {missing}")

    if ema_col not in df.columns:
        raise KeyError(f"EMA column '{ema_col}' not found in df")

    if time_col is None:
        for cand in ("timeopen", "ts", "time", "timestamp", "date"):
            if cand in df.columns:
                time_col = cand
                break
        if time_col is None:
            raise KeyError(
                "time_col not provided and no suitable default found. "
                "Pass time_col explicitly (e.g. 'timeopen' or 'ts')."
            )

    sort_cols = group_cols + [time_col]
    df.sort_values(sort_cols, inplace=True)

    g = df.groupby(group_cols, sort=False)

    d1 = g[ema_col].diff()
    d2 = d1.diff()

    if round_places is not None:
        d1 = d1.round(round_places)
        d2 = d2.round(round_places)

    df[d1_col] = d1
    df[d2_col] = d2

    return df


# -----------------------------------------------------------------------------
# Daily EMA → cmc_ema_daily with tf_days = 1
# -----------------------------------------------------------------------------


def _get_engine(db_url: str | None = None) -> Engine:
    url = db_url or TARGET_DB_URL
    if not url:
        raise RuntimeError("No DB URL provided AND TARGET_DB_URL missing in config.")
    return create_engine(url)


def build_daily_ema_frame(
    ids: Iterable[int],
    start: str = "2010-01-01",
    end: str | None = None,
    ema_periods: Iterable[int] = (10, 21, 50, 100, 200),
    *,
    db_url: str | None = None,
) -> pd.DataFrame:
    """
    Build a longform daily EMA DataFrame suitable for cmc_ema_daily:

        id, ts, period, ema, d1, d2, tf_days

    - Uses closing prices from the canonical daily OHLCV loader.
    - Drops initial NaN EMA values for each (id, period).
    - Sets tf_days = 1 for all rows (daily timeframe).
    - d1, d2 are first and second differences of ema per (id, period).
    """
    ema_periods = [int(p) for p in ema_periods]
    ids = list(ids)

    daily = load_cmc_ohlcv_daily(
        ids=ids,
        start=start,
        end=end,
        db_url=db_url,
    )

    # Normalize index to columns if needed
    if isinstance(daily.index, pd.MultiIndex):
        idx_names = list(daily.index.names or [])
        if "id" in idx_names and "ts" in idx_names:
            daily = daily.reset_index()

    if "timestamp" in daily.columns and "ts" not in daily.columns:
        daily = daily.rename(columns={"timestamp": "ts"})

    required = {"id", "ts", "close"}
    missing = required - set(daily.columns)
    if missing:
        raise ValueError(f"Daily OHLCV missing required columns: {missing}")

    daily["ts"] = pd.to_datetime(daily["ts"], utc=True)
    daily = daily.sort_values(["id", "ts"]).reset_index(drop=True)

    frames: list[pd.DataFrame] = []

    for asset_id in ids:
        df_id = daily[daily["id"] == asset_id].copy()
        if df_id.empty:
            continue

        close = df_id["close"].astype(float)

        for p in ema_periods:
            ema = compute_ema(
                close,
                period=p,
                adjust=False,
                min_periods=p,
            )

            d1 = ema.diff()
            d2 = d1.diff()

            out = df_id[["ts"]].copy()
            out["ema"] = ema
            out["d1"] = d1
            out["d2"] = d2

            # Keep only rows where EMA is defined
            out = out[out["ema"].notna()]
            if out.empty:
                continue

            out["id"] = asset_id
            out["period"] = p
            out["tf_days"] = 1  # daily timeframe

            frames.append(out[["id", "ts", "period", "ema", "d1", "d2", "tf_days"]])

    if not frames:
        return pd.DataFrame(
            columns=["id", "ts", "period", "ema", "d1", "d2", "tf_days"]
        )

    result = pd.concat(frames, ignore_index=True)
    result["ts"] = pd.to_datetime(result["ts"], utc=True)
    return result



def write_daily_ema_to_db(
    ids: Iterable[int],
    start: str = "2010-01-01",
    end: str | None = None,
    ema_periods: Iterable[int] = (10, 21, 50, 100, 200),
    *,
    db_url: str | None = None,
    schema: str = "public",
    out_table: str = "cmc_ema_daily",
) -> int:
    """
    Compute daily EMAs for the given ids and upsert into cmc_ema_daily
    with columns:

        id, ts, period, ema, d1, d2, tf_days

    Assumes UNIQUE (id, ts, period) on the target table.
    """
    engine = _get_engine(db_url)

    df = build_daily_ema_frame(
        ids=ids,
        start=start,
        end=end,
        ema_periods=ema_periods,
        db_url=db_url,
    )

    if df.empty:
        print("No daily EMA rows generated.")
        return 0

    tmp_table = f"{out_table}_tmp"

    with engine.begin() as conn:
        conn.execute(text(f"DROP TABLE IF EXISTS {schema}.{tmp_table};"))

        conn.execute(
            text(
                f"""
            CREATE TEMP TABLE {tmp_table} AS
            SELECT id, ts, period, ema, d1, d2, tf_days
            FROM {schema}.{out_table}
            LIMIT 0;
            """
            )
        )

        df.to_sql(
            tmp_table,
            conn,
            if_exists="append",
            index=False,
            method="multi",
        )

        sql = f"""
        INSERT INTO {schema}.{out_table} AS t (id, ts, period, ema, d1, d2, tf_days)
        SELECT id, ts, period, ema, d1, d2, tf_days
        FROM {tmp_table}
        ON CONFLICT (id, ts, period)
        DO UPDATE SET
            ema     = EXCLUDED.ema,
            d1      = EXCLUDED.d1,
            d2      = EXCLUDED.d2,
            tf_days = EXCLUDED.tf_days;
        """
        res = conn.execute(text(sql))
        return res.rowcount



# export legacy + new helpers
try:
    __all__.append("add_ema")
except NameError:
    __all__ = ["add_ema"]

try:
    __all__.extend(["build_daily_ema_frame", "write_daily_ema_to_db"])
except NameError:
    __all__ = ["build_daily_ema_frame", "write_daily_ema_to_db"]
