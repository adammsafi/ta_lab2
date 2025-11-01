# src/ta_lab2/pipelines/btc_pipeline.py
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Iterable, Mapping

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
    add_volatility_features,            # shim: single-bar + Parkinson/RS/GK + ATR
    add_rolling_vol_from_returns_batch, # shim: realized vol from returns
)

# --- Regimes / segments ---
from ta_lab2.regimes.comovement import (
    compute_ema_comovement_stats,
    compute_ema_comovement_hierarchy,
)
from ta_lab2.regimes.segments import build_flip_segments   # thin wrapper


def _infer_timestamp_col(df: pd.DataFrame, fallback: str = "timestamp") -> str:
    """Pick a timestamp column if callers didn’t normalize the name yet."""
    if fallback in df.columns:
        return fallback
    for c in df.columns:
        cl = str(c).lower()
        if "time" in cl or "date" in cl:
            return c
    return fallback


def _coerce_df(df_or_path: str | pd.DataFrame) -> pd.DataFrame:
    """Accept a CSV path or a DataFrame; return a normalized DataFrame."""
    if isinstance(df_or_path, pd.DataFrame):
        df = df_or_path.copy()
    else:
        df = pd.read_csv(df_or_path)
    # normalize header case/whitespace
    df.columns = [str(c).strip().lower() for c in df.columns]
    # standardize timestamp column name
    ts = _infer_timestamp_col(df, "timestamp")
    if ts != "timestamp":
        df = df.rename(columns={ts: "timestamp"})
    return df


def _maybe_from_config(value, default):
    """
    Helper: if value is a dataclass or mapping, convert to dict/tuple cleanly.
    Used to accept legacy 'config' objects without being strict about types.
    """
    if value is None:
        return default
    if is_dataclass(value):
        value = asdict(value)
    if isinstance(value, Mapping):
        return value
    return value


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

    # Feature-stage toggles (all True keeps full functionality)
    do_calendar: bool = True,
    do_indicators: bool = True,
    do_returns: bool = True,
    do_volatility: bool = True,
    do_ema: bool = True,
    do_regimes: bool = True,
    do_segments: bool = True,

    # Optional lenient config object (mapping/dataclass) to override any of the above
    config: Mapping | object | None = None,
) -> dict:
    """
    End-to-end, testable pipeline aligned to the modular ta_lab2 layout.

    Parameters
    ----------
    csv_path
        CSV path or a pre-built DataFrame with at least timestamp & OHLC(V).
    price_cols
        Which columns to treat as price fields. Default: ('open','high','low','close').
    ema_windows
        EMA periods. Default: (21,50,100,200).
    returns_modes
        Which return modes to compute realized volatility from. Default: ('log','pct').
    returns_windows
        Windows for returns/realized vol. Default: (30,60,90).
    resample
        Optional frequency (e.g. '1H', '1D'); when set, OHLCV is aggregated.
    do_* flags
        Feature-stage toggles. Leave True to keep full functionality.
    config
        Optional mapping/dataclass whose keys may include any of the parameters above.
        Values in `config` override the function defaults.

    Returns
    -------
    dict
        {
          "data": <pd.DataFrame>,
          "segments": <pd.DataFrame>,
          "segment_summary": <pd.DataFrame>,
          "segment_by_year": <pd.DataFrame>,
          "regime_major": <pd.DataFrame>,
          "regime_sub": <pd.DataFrame>,
          "summary": {...}
        }
    """
    # --- Optional config override (lenient) ---
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

    # --- Calendar features (full fidelity incl. season and moon if available) ---
    if do_calendar:
        expand_datetime_features_inplace(df, base_timestamp_col="timestamp")

    # --- Optional OHLCV resample ---
    if resample:
        agg = {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }
        have = {k: v for k, v in agg.items() if k in df.columns}
        if have:
            df = (
                df.set_index("timestamp")
                  .resample(resample)
                  .agg(have)
                  .dropna()
                  .reset_index()
            )
            if do_calendar:
                expand_datetime_features_inplace(df, base_timestamp_col="timestamp")

    # --- Lightweight indicators (kept for parity with older notebooks/pipeline) ---
    if do_indicators and "close" in df.columns:
        out = rsi(df, period=14, price_col="close")
        df[out.name] = out
        df = df.join(macd(df, price_col="close"))
        df = df.join(bollinger(df, price_col="close"))

    # --- Simple engineered columns used later ---
    if all(k in df.columns for k in ("high", "low", "close", "open")):
        df["close-open"] = df["close"].astype(float) - df["open"].astype(float)
        df["range"] = df["high"].astype(float) - df["low"].astype(float)

    # --- Bar-to-bar deltas (pct + log) with legacy-kw compatibility ---
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

    # --- Volatility: single-bar + realized from returns (shims keep legacy inputs) ---
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

    # --- EMAs + first/second differences + helpers (bps scaling) ---
    if do_ema:
        base_cols = list(price_cols)
        add_ema_columns(df, base_cols, list(ema_windows))
        # Keep legacy kwargs for callers that previously passed extras.
        add_ema_d1(df, base_cols, list(ema_windows), direction="newest_top", overwrite=False, round_places=6)
        add_ema_d2(df, base_cols, list(ema_windows), direction="newest_top", overwrite=False, round_places=6)
        prepare_ema_helpers(df, base_cols, list(ema_windows), direction="newest_top", scale="bps")

    # --- Regime detection (EMA co-movement) ---
    if do_regimes:
        _, labeled = compute_ema_comovement_stats(
            df.copy(),
            periods=list(ema_windows),
            direction="newest_top",
            close_col="close",
            return_col="close_pct_delta",
        )
        df["trend_state"] = labeled["regime_label"]

    # --- Segments (EMA-slope sign flips) ---
    segments = pd.DataFrame()
    seg_summary = pd.DataFrame()
    seg_by_year = pd.DataFrame()
    if do_segments:
        segments, seg_summary, seg_by_year = build_flip_segments(
            df,
            base_cols=("close",),
            periods=list(ema_windows),
            direction="newest_top",
            scale="bps",
            date_col="timestamp",
            ema_name_fmt="{field}_ema_{period}",
        )

    # --- Hierarchy stats (major/sub) for regimes ---
    major_stats = pd.DataFrame()
    sub_stats = pd.DataFrame()
    sub_stats_mixsum = pd.DataFrame()
    if do_regimes:
        major_stats, sub_stats, sub_stats_mixsum = compute_ema_comovement_hierarchy(
            df,
            periods=list(ema_windows),
            close_col="close",
            direction="newest_top",
            return_col="close_pct_delta",
        )

    # --- Compact high-level summary ---
    summary = {
        "n_rows": int(len(df)),
        "n_segments": int(len(segments)),
        "mean_seg_return": float(segments["ret_close_to_close"].mean()) if len(segments) else 0.0,
        "mean_seg_len": float(segments["bars"].mean()) if len(segments) else 0.0,
    }

    return {
        "data": df,
        "segments": segments,
        "segment_summary": seg_summary,
        "segment_by_year": seg_by_year,
        "regime_major": major_stats,
        "regime_sub": sub_stats_mixsum,
        "summary": summary,
    }
