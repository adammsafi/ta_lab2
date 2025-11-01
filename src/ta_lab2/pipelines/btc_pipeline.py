# src/ta_lab2/pipelines/btc_pipeline.py
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Iterable, Mapping, Dict, Any
import inspect
import numpy as np
import pandas as pd

# --- Features / indicators ---
from ta_lab2.features.calendar import expand_datetime_features_inplace
from ta_lab2.features.ema import (
    add_ema_columns,
    add_ema_d1,
    add_ema_d2,
    prepare_ema_helpers,
)
from ta_lab2.features.indicators import rsi, macd, bollinger
from ta_lab2.features.returns import b2t_pct_delta, b2t_log_delta
from ta_lab2.features.vol import (
    add_volatility_features,            # single-bar + Parkinson/RS/GK + ATR
    add_rolling_vol_from_returns_batch, # realized vol from returns
)

# --- Regimes / segments ---
from ta_lab2.regimes.comovement import (
    compute_ema_comovement_stats,
    compute_ema_comovement_hierarchy,
)

# segments live under features
from ta_lab2.features.segments import build_flip_segments


# ===========================
# Signature-tolerant helpers
# ===========================
def _filter_kwargs(func, kwargs: Dict[str, Any]) -> Dict[str, Any]:
    sig = inspect.signature(func)
    return {k: v for k, v in kwargs.items() if k in sig.parameters}

def _try_call_with_windows(func, df: pd.DataFrame, ema_windows, **kwargs):
    """
    For comovement/hierarchy funcs that accept a windows argument.
    Tries periods=, windows=, ema_windows=, then positional.
    """
    fk = _filter_kwargs(func, kwargs)
    psig = inspect.signature(func).parameters

    for key in ("periods", "windows", "ema_windows"):
        try:
            if key in psig:
                return func(df, **{key: list(ema_windows)}, **fk)
        except TypeError:
            pass

    # Positional windows
    try:
        return func(df, list(ema_windows), **fk)
    except TypeError:
        return func(df, **fk)

def _call_ema_comovement(df: pd.DataFrame, ema_windows, **kwargs):
    func = compute_ema_comovement_stats
    try:
        return _try_call_with_windows(func, df, ema_windows, **kwargs)
    except TypeError:
        pass
    kw2 = dict(kwargs)
    if "close_col" in kw2 and "price_col" not in kw2:
        kw2["price_col"] = kw2.pop("close_col")
    return _try_call_with_windows(func, df, ema_windows, **kw2)

def _call_ema_hierarchy(df: pd.DataFrame, ema_windows, **kwargs):
    func = compute_ema_comovement_hierarchy
    try:
        return _try_call_with_windows(func, df, ema_windows, **kwargs)
    except TypeError:
        pass
    kw2 = dict(kwargs)
    if "close_col" in kw2 and "price_col" not in kw2:
        kw2["price_col"] = kw2.pop("close_col")
    return _try_call_with_windows(func, df, ema_windows, **kw2)

def _call_build_segments(df: pd.DataFrame, *, price_col="close", state_col="trend_state", date_col="timestamp"):
    """
    Robust caller for features.segments.build_flip_segments (no windows here).
    Only pass kwargs the function accepts; map alternate param names if present.
    """
    func = build_flip_segments
    psig = inspect.signature(func).parameters
    kwargs: Dict[str, Any] = {}

    # price column
    for k in ("price_col", "field", "col"):
        if k in psig:
            kwargs[k] = price_col
            break

    # state column
    for k in ("state_col", "label_col", "trend_col"):
        if k in psig:
            kwargs[k] = state_col
            break

    # timestamp column
    for k in ("timestamp_col", "date_col", "time_col", "ts_col"):
        if k in psig:
            kwargs[k] = date_col
            break

    kwargs = _filter_kwargs(func, kwargs)
    return func(df, **kwargs)


# ===========================
# Utility helpers
# ===========================
def _infer_timestamp_col(df: pd.DataFrame, fallback: str = "timestamp") -> str:
    if fallback in df.columns:
        return fallback
    for c in df.columns:
        cl = str(c).lower()
        if "time" in cl or "date" in cl:
            return c
    return fallback

def _coerce_df(df_or_path: str | pd.DataFrame) -> pd.DataFrame:
    if isinstance(df_or_path, pd.DataFrame):
        df = df_or_path.copy()
    else:
        df = pd.read_csv(df_or_path)
    df.columns = [str(c).strip().lower() for c in df.columns]
    ts = _infer_timestamp_col(df, "timestamp")
    if ts != "timestamp":
        df = df.rename(columns={ts: "timestamp"})
    return df

def _maybe_from_config(value, default):
    if value is None:
        return default
    if is_dataclass(value):
        value = asdict(value)
    if isinstance(value, Mapping):
        return value
    return value


# ===========================
# Main pipeline
# ===========================
def run_btc_pipeline(
    csv_path: str | pd.DataFrame,
    *,
    # Columns & windows
    price_cols: Iterable[str] = ("open", "high", "low", "close"),
    ema_windows: Iterable[int] = (21, 50, 100, 200),
    returns_modes: Iterable[str] = ("log", "pct"),
    returns_windows: Iterable[int] = (30, 60, 90),

    # Optional resample (e.g., "1H", "1D")
    resample: str | None = None,

    # Feature-stage toggles
    do_calendar: bool = True,
    do_indicators: bool = True,
    do_returns: bool = True,
    do_volatility: bool = True,
    do_ema: bool = True,
    do_regimes: bool = True,
    do_segments: bool = True,

    # Optional config override
    config: Mapping | object | None = None,
) -> dict:
    """End-to-end, testable pipeline aligned to the modular ta_lab2 layout."""
    # --- Config override ---
    if config is not None:
        cfg = _maybe_from_config(config, {})
        if isinstance(cfg, Mapping):
            price_cols      = tuple(cfg.get("price_cols",      price_cols))
            ema_windows     = tuple(cfg.get("ema_windows",     ema_windows))
            returns_modes   = tuple(cfg.get("returns_modes",   returns_modes))
            returns_windows = tuple(cfg.get("returns_windows", returns_windows))
            resample        = cfg.get("resample",              resample)

            do_calendar   = cfg.get("do_calendar",   do_calendar)
            do_indicators = cfg.get("do_indicators", do_indicators)
            do_returns    = cfg.get("do_returns",    do_returns)
            do_volatility = cfg.get("do_volatility", do_volatility)
            do_ema        = cfg.get("do_ema",        do_ema)
            do_regimes    = cfg.get("do_regimes",    do_regimes)
            do_segments   = cfg.get("do_segments",   do_segments)

    # --- Load / normalize ---
    df = _coerce_df(csv_path)

    # --- Calendar ---
    if do_calendar:
        expand_datetime_features_inplace(df, base_timestamp_col="timestamp")

    # --- Optional resample ---
    if resample:
        agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
        have = {k: v for k, v in agg.items() if k in df.columns}
        if have:
            df = (
                df.set_index("timestamp").resample(resample).agg(have).dropna().reset_index()
            )
            if do_calendar:
                expand_datetime_features_inplace(df, base_timestamp_col="timestamp")

    # --- Indicators ---
    if do_indicators and "close" in df.columns:
        out = rsi(df, period=14, price_col="close")
        df[out.name] = out
        df = df.join(macd(df, price_col="close"))
        df = df.join(bollinger(df, price_col="close"))

    # --- Engineered columns ---
    if all(k in df.columns for k in ("high", "low", "close", "open")):
        df["close-open"] = df["close"].astype(float) - df["open"].astype(float)
        df["range"] = df["high"].astype(float) - df["low"].astype(float)

    # --- Returns (pct + log) ---
    if do_returns:
        b2t_pct_delta(
            df,
            cols=list(price_cols) + (["close-open"] if "close-open" in df.columns else []),
            extra_cols=(["range"] if "range" in df.columns else []),
            round_places=6,
            direction="newest_top",
            open_col="open",
            close_col="close",
        )
        b2t_log_delta(
            df,
            cols=list(price_cols) + (["close-open"] if "close-open" in df.columns else []),
            extra_cols=(["range"] if "range" in df.columns else []),
            prefix="_log_delta",
            round_places=6,
            add_intraday=True,
            open_col="open",
            close_col="close",
        )

    # --- Volatility ---
    if do_volatility:
        df = add_volatility_features(
            df,
            do_atr=True,
            do_parkinson=True,
            do_rs=True,
            do_gk=True,
            rolling_windows=tuple(returns_windows),
            direction="newest_top",
        )
        df = add_rolling_vol_from_returns_batch(
            df,
            price_col="close",
            modes=tuple(returns_modes),
            windows=tuple(returns_windows),
            annualize=True,
            direction="newest_top",
        )

    # --- EMAs + diffs + helpers ---
    if do_ema:
        base_cols = list(price_cols)
        add_ema_columns(df, base_cols, list(ema_windows))
        add_ema_d1(df, base_cols, list(ema_windows), direction="newest_top", overwrite=False, round_places=6)
        add_ema_d2(df, base_cols, list(ema_windows), direction="newest_top", overwrite=False, round_places=6)
        prepare_ema_helpers(df, base_cols, list(ema_windows), direction="newest_top", scale="bps")

    # --- Regimes ---
    major_stats = None
    if do_regimes:
        res = _call_ema_comovement(
            df.copy(),
            ema_windows,
            direction="newest_top",
            close_col="close",
            return_col="close_pct_delta",
        )
        labeled = None
        if isinstance(res, tuple):
            if len(res) >= 2:
                major_stats, labeled = res[0], res[1]
            elif len(res) == 1:
                major_stats = res[0]
        elif isinstance(res, dict):
            major_stats = res  # dict (corr/agree/meta)

        # If no labeled regimes returned, synthesize a minimal trend_state from EMA slope
        if isinstance(labeled, pd.DataFrame) and "regime_label" in labeled.columns:
            df["trend_state"] = labeled["regime_label"]
        else:
            slope_col = "close_ema_21_slope"
            if slope_col in df.columns:
                df["trend_state"] = np.sign(pd.to_numeric(df[slope_col], errors="coerce")).fillna(0).astype(int)
            else:
                if "close_pct_delta" in df.columns:
                    df["trend_state"] = np.sign(pd.to_numeric(df["close_pct_delta"], errors="coerce")).fillna(0).astype(int)
                else:
                    df["trend_state"] = 0

    # --- Segments ---
    segments = pd.DataFrame()
    seg_summary = pd.DataFrame()
    seg_by_year = pd.DataFrame()
    if do_segments:
        seg_res = _call_build_segments(
            df,
            price_col="close",
            state_col="trend_state",
            date_col="timestamp",
        )
        # Accept DataFrame, (segments, summary), or (segments, summary, by_year)
        if isinstance(seg_res, pd.DataFrame):
            segments = seg_res
        elif isinstance(seg_res, tuple):
            if len(seg_res) >= 3:
                segments, seg_summary, seg_by_year = seg_res[:3]
            elif len(seg_res) == 2:
                segments, seg_summary = seg_res
            elif len(seg_res) == 1:
                segments = seg_res[0]
        elif isinstance(seg_res, dict):
            segments = seg_res.get("segments", pd.DataFrame())
            seg_summary = seg_res.get("summary", pd.DataFrame())
            seg_by_year = seg_res.get("by_year", pd.DataFrame())

    # --- Hierarchy (major/sub) ---
    h_major = pd.DataFrame()
    h_scores = pd.DataFrame()
    if do_regimes:
        hres = _call_ema_hierarchy(
            df,
            ema_windows,
            close_col="close",
            direction="newest_top",
            return_col="close_pct_delta",
        )
        if isinstance(hres, tuple):
            if len(hres) == 3:
                h_major, _, h_scores = hres
            elif len(hres) == 2:
                h_major, h_scores = hres
            elif len(hres) == 1:
                h_major = hres[0]
        elif isinstance(hres, dict):
            h_major = hres.get("corr", pd.DataFrame())
            h_scores = hres.get("scores", pd.DataFrame())

    # --- Summary (robust to different segment schemas) ---
    ret_col = next((c for c in ("ret_close_to_close", "seg_return", "return", "ret")
                    if c in segments.columns), None)
    len_col = next((c for c in ("bars", "seg_len", "length", "len")
                    if c in segments.columns), None)

    mean_seg_return = float(segments[ret_col].mean()) if ret_col else 0.0
    mean_seg_len    = float(segments[len_col].mean()) if len_col else 0.0

    summary = {
        "n_rows": int(len(df)),
        "n_segments": int(len(segments)),
        "mean_seg_return": mean_seg_return,
        "mean_seg_len": mean_seg_len,
    }

    return {
        "data": df,
        "segments": segments,
        "segment_summary": seg_summary,
        "segment_by_year": seg_by_year,
        "regime_major": (major_stats.get("corr") if isinstance(major_stats, dict) else major_stats),
        "regime_sub": h_scores,
        "summary": summary,
    }
