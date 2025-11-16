# src/ta_lab2/features/resample.py
from __future__ import annotations
from pathlib import Path
from typing import Dict, Iterable, Optional
import pandas as pd
import numpy as np

from ta_lab2.features.calendar import expand_datetime_features_inplace

# Default OHLCV aggregations for downsampling
_DEFAULT_AGG = {
    "open":   "first",
    "high":   "max",
    "low":    "min",
    "close":  "last",
    "volume": "sum",
}


def _validate_ohlcv_columns(df: pd.DataFrame) -> None:
    """
    Ensure that a DataFrame has the standard OHLCV columns.
    """
    required = {"open", "high", "low", "close", "volume"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"DataFrame is missing required OHLCV columns: {missing}")


def _ensure_ts_index(
    df: pd.DataFrame,
    ts_col: str = "ts",
    copy: bool = True,
) -> pd.DataFrame:
    """
    Ensure df has a DatetimeIndex based on ts_col.
    """
    if copy:
        df = df.copy()

    if ts_col not in df.columns and not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError(
            f"_ensure_ts_index(): expected '{ts_col}' column "
            "or a DatetimeIndex."
        )

    if not isinstance(df.index, pd.DatetimeIndex):
        df[ts_col] = pd.to_datetime(df[ts_col], utc=True)
        df = df.set_index(ts_col)

    if df.index.tz is None:
        # Coerce to UTC if naive
        df.index = df.index.tz_localize("UTC")

    df = df.sort_index()
    return df


def resample_ohlcv(
    df: pd.DataFrame,
    freq: str,
    agg: Optional[Dict[str, str]] = None,
    label: str = "right",
    closed: str = "right",
    strict: bool = True,
) -> pd.DataFrame:
    """
    Generic OHLCV resampler.

    Parameters
    ----------
    df :
        DataFrame with DatetimeIndex and columns: open, high, low, close, volume.
    freq :
        Resample frequency (e.g. '2D', '1W', '3M').
    agg :
        Optional custom aggregation mapping. If None, uses _DEFAULT_AGG.
    label, closed :
        Passed to pandas.DataFrame.resample.
    strict :
        If True, drop any buckets whose end is after the max input timestamp.

    Returns
    -------
    DataFrame
        Resampled OHLCV with DatetimeIndex.
    """
    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError("resample_ohlcv(): df must have a DatetimeIndex")

    _validate_ohlcv_columns(df)

    agg = agg or _DEFAULT_AGG

    r = (
        df.resample(freq, label=label, closed=closed)
        .agg(agg)
        .dropna(how="any")
    )

    if strict:
        max_ts = df.index.max()
        r = r[r.index <= max_ts]

    return r


# ---------------------------------------------------------------------
# Timeframe normalization helpers
# ---------------------------------------------------------------------


TIMEFRAME_FREQS: Dict[str, str] = {
    # Daily-ish
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

    # Weekly-ish
    "1W": "1W",
    "2W": "2W",
    "3W": "3W",
    "4W": "28D",
    "6W": "42D",
    "8W": "56D",
    "10W": "70D",

    # Monthly-ish
    "1M": "1ME",
    "2M": "2ME",
    "3M": "3ME",
    "6M": "6ME",
    "9M": "9ME",
    "12M": "12ME",
}


def normalize_timeframe_label(tf: str) -> str:
    """
    Normalize a human-readable timeframe key to a pandas offset alias.

    Examples
    --------
    '2D' -> '2D'
    '1W' -> '1W'
    '1M' -> '1ME'
    """
    key = tf.upper()
    if key not in TIMEFRAME_FREQS:
        raise KeyError(f"Unknown timeframe label: {tf}")
    return TIMEFRAME_FREQS[key]


def add_calendar_features(
    df: pd.DataFrame,
    ts_col: str = "ts",
    inplace: bool = False,
) -> pd.DataFrame:
    """
    Expand calendar features in-place using the shared calendar utilities.

    This is mostly a thin wrapper around expand_datetime_features_inplace.
    """
    if not inplace:
        df = df.copy()

    expand_datetime_features_inplace(df, ts_col=ts_col)
    return df


# ---------------------------------------------------------------------
# Simple file-based resample helper (not used by EMA, but kept)
# ---------------------------------------------------------------------


def resample_parquet_file(
    input_path: Path,
    output_path: Path,
    freq: str,
    *,
    ts_col: str = "ts",
    strict: bool = True,
    label: str = "right",
    closed: str = "right",
) -> None:
    """
    Load a parquet file, resample OHLCV, and write out another parquet file.
    """
    df = pd.read_parquet(input_path)
    df = _ensure_ts_index(df, ts_col=ts_col)
    df = resample_ohlcv(df, freq=freq, strict=strict, label=label, closed=closed)
    df.to_parquet(output_path)


# ---------------------------------------------------------------------
# Compatibility wrapper used by ema_multi_timeframe.py
# ---------------------------------------------------------------------


def resample_to_tf(
    df: pd.DataFrame,
    freq: str,
    *,
    strict: bool = True,
    label: str = "right",
    closed: str = "right",
) -> pd.DataFrame:
    """
    Compatibility wrapper used by ema_multi_timeframe.py.

    Expects `df` with columns:
        ts, open, high, low, close, volume

    Returns an OHLCV frame at the target frequency with:
        ts, open, high, low, close, volume

    If strict=True, drop any buckets whose end is after the max original ts
    (to avoid future extension).
    """
    required_cols = {"ts", "open", "high", "low", "close", "volume"}
    missing = required_cols - set(df.columns)
    if missing:
        raise ValueError(f"resample_to_tf(): missing required columns: {missing}")

    d = df.copy()
    d["ts"] = pd.to_datetime(d["ts"], utc=True)
    d = d.sort_values("ts").set_index("ts")

    agg_spec = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }

    out = (
        d.resample(freq, label=label, closed=closed)
        .agg(agg_spec)
        .dropna(how="any")
    )

    if strict:
        max_ts = d.index.max()
        out = out[out.index <= max_ts]

    out = out.reset_index()  # index name 'ts' becomes a column
    return out
