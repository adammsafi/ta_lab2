# src/ta_lab2/signals/registry.py
# -*- coding: utf-8 -*-
from __future__ import annotations
"""
Strategy registry for ta_lab2.signals.

- Keeps backward compatibility: REGISTRY maps strategy name -> callable(df, **params)
  returning (entries: Series[bool], exits: Series[bool], size: Optional[Series[float]]).
- Adds convenience helpers:
    get_strategy(name)     -> fetch a callable with a nice error if missing
    ensure_for(name, df, params) -> compute-if-missing required columns for a strategy
    grid_for(name)         -> small default param grids for research scripts

You can add new adapters in signals/* and expose them here without breaking anything.
"""

from typing import Callable, Dict, Tuple, Optional, List, Any
import pandas as pd
import numpy as np

# --- Import your core EMA adapter (required) ---
from .ema_trend import make_signals as ema_trend_signal

# --- Optional adapters: import if present, ignore if not ---
try:
    from .rsi_mean_revert import make_signals as rsi_mean_revert_signal  # optional
except Exception:  # pragma: no cover
    rsi_mean_revert_signal = None

try:
    from .macd_crossover import make_signals as macd_crossover_signal  # optional
except Exception:  # pragma: no cover
    macd_crossover_signal = None

try:
    from .breakout_atr import make_signals as breakout_atr_signal  # optional (future)
except Exception:  # pragma: no cover
    breakout_atr_signal = None


# ---------------------------------------------------------------------------
# Backward-compatible core: simple name->callable registry
# ---------------------------------------------------------------------------
# Signature: (df, **params) -> (entries: Series[bool], exits: Series[bool], size: Optional[Series[float]])
REGISTRY: Dict[str, Callable[..., Tuple[pd.Series, pd.Series, Optional[pd.Series]]]] = {
    "ema_trend": ema_trend_signal,
    **({"rsi_mean_revert": rsi_mean_revert_signal} if rsi_mean_revert_signal else {}),
    **({"macd_crossover": macd_crossover_signal}   if macd_crossover_signal else {}),
    **({"breakout_atr": breakout_atr_signal}       if breakout_atr_signal else {}),
}


def get_strategy(name: str) -> Callable[..., Tuple[pd.Series, pd.Series, Optional[pd.Series]]]:
    """Safe getter used by research scripts; keeps existing orchestrator behavior intact."""
    fn = REGISTRY.get(name)
    if fn is None:
        available = [k for k, v in REGISTRY.items() if v]
        raise KeyError(f"Unknown or unavailable strategy '{name}'. Available: {available}")
    return fn


# ---------------------------------------------------------------------------
# Optional: compute-if-missing helpers so adapters are plug-and-play
# (keeps you independent of other modules if you prefer; minimal robust math)
# ---------------------------------------------------------------------------
def _ensure_close(df: pd.DataFrame) -> None:
    if "close" not in df.columns:
        # try to promote a likely close-like column
        for c in df.columns:
            lc = str(c).lower()
            if lc == "price" or lc == "last" or "close" in lc:
                df.rename(columns={c: "close"}, inplace=True)
                break
    if "close" not in df.columns:
        raise KeyError("DataFrame must contain a 'close' column.")

def _ensure_ema(df: pd.DataFrame, span: int) -> str:
    _ensure_close(df)
    col = f"ema_{span}"
    if col not in df:
        df[col] = df["close"].ewm(span=span, adjust=False).mean()
    return col

def _ensure_rsi(df: pd.DataFrame, n: int = 14) -> str:
    """Minimal Wilder-style RSI (EMA smoothing) on 'close'."""
    _ensure_close(df)
    col = f"rsi_{n}"
    if col not in df:
        ret = df["close"].diff()
        up = ret.clip(lower=0.0).ewm(alpha=1 / n, adjust=False).mean()
        dn = (-ret.clip(upper=0.0)).ewm(alpha=1 / n, adjust=False).mean()
        rs = up / dn.replace(0.0, np.nan)
        df[col] = 100.0 - (100.0 / (1.0 + rs))
    return col

def _ensure_macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[str, str, str]:
    _ensure_close(df)
    macd_col, sig_col, hist_col = "macd", "macd_signal", "macd_hist"
    if macd_col not in df or sig_col not in df or hist_col not in df:
        ema_f = df["close"].ewm(span=fast,  adjust=False).mean()
        ema_s = df["close"].ewm(span=slow,  adjust=False).mean()
        macd = ema_f - ema_s
        macd_sig = macd.ewm(span=signal, adjust=False).mean()
        df[macd_col] = macd
        df[sig_col] = macd_sig
        df[hist_col] = macd - macd_sig
    return macd_col, sig_col, hist_col

def _ensure_atr(df: pd.DataFrame, n: int = 14) -> str:
    """Minimal ATR (Wilder). Requires high/low/close. If missing, silently skip."""
    col = f"atr_{n}"
    req = {"high", "low", "close"}
    if col in df.columns:
        return col
    if not req.issubset(set(df.columns)):
        # Can't compute; leave it absent (adapters should handle None gracefully)
        return col
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        (high - low),
        (high - prev_close).abs(),
        (low - prev_close).abs()
    ], axis=1).max(axis=1)
    df[col] = tr.ewm(alpha=1 / n, adjust=False).mean()
    return col


# ---------------------------------------------------------------------------
# Optional: per-strategy "ensure" and default grids for research scripts
# (These do not change orchestrator behavior; use only if you want.)
# ---------------------------------------------------------------------------
def ensure_for(name: str, df: pd.DataFrame, params: Dict[str, Any]) -> None:
    """Compute required columns for a given strategy+params, if missing."""
    if name == "ema_trend":
        fe = int(str(params.get("fast_ema", "ema_21")).split("_")[-1])
        se = int(str(params.get("slow_ema", "ema_77")).split("_")[-1])
        _ensure_ema(df, fe)
        _ensure_ema(df, se)
        _ensure_close(df)

    elif name == "rsi_mean_revert" and rsi_mean_revert_signal:
        n = int(params.get("rsi_n", 14)) if "rsi_n" in params else int(str(params.get("rsi_col", "rsi_14")).split("_")[-1])
        _ensure_rsi(df, n)
        # optional trend filter
        tf = params.get("trend_fast")
        ts = params.get("trend_slow")
        if tf:
            _ensure_ema(df, int(str(tf).split("_")[-1]))
        if ts:
            _ensure_ema(df, int(str(ts).split("_")[-1]))
        # optional ATR for sizing/stops
        ac = params.get("atr_col", "atr_14")
        if ac:
            try:
                n_atr = int(str(ac).split("_")[-1])
            except Exception:
                n_atr = 14
            _ensure_atr(df, n_atr)

    elif name == "macd_crossover" and macd_crossover_signal:
        f = int(params.get("fast", 12))
        s = int(params.get("slow", 26))
        sig = int(params.get("signal", 9))
        _ensure_macd(df, f, s, sig)
        _ensure_close(df)

    elif name == "breakout_atr" and breakout_atr_signal:
        # if your breakout adapter needs ATR/EMA/etc., compute here
        ac = params.get("atr_col", "atr_14")
        if ac:
            try:
                n_atr = int(str(ac).split("_")[-1])
            except Exception:
                n_atr = 14
            _ensure_atr(df, n_atr)
        _ensure_close(df)

    else:
        # Unknown or unavailable strategy: no-op to stay non-breaking for callers that ignore ensure
        pass


def grid_for(name: str) -> List[Dict[str, Any]]:
    """Small default grids to kick off coarse scans."""
    if name == "ema_trend":
        out: List[Dict[str, Any]] = []
        for f in range(5, 61, 5):
            for s in (80, 100, 120, 150, 200):
                if s >= f + 5:
                    out.append({"fast_ema": f"ema_{f}", "slow_ema": f"ema_{s}"})
        return out

    if name == "rsi_mean_revert" and rsi_mean_revert_signal:
        out: List[Dict[str, Any]] = []
        for n in (7, 14, 21):
            for lower, upper in ((25, 55), (30, 60), (35, 65)):
                # with trend filter
                out.append({
                    "rsi_n": n,
                    "rsi_buy": lower, "rsi_sell": upper,
                    "trend_fast": "ema_17", "trend_slow": "ema_77",
                    "use_trend": True,
                    "atr_col": "atr_14",   # optional for sizing/stops
                    "risk_pct": 0.5,
                    "atr_mult_stop": 1.5,
                    "max_leverage": 1.0,
                })
                # without trend filter
                out.append({
                    "rsi_n": n,
                    "rsi_buy": lower, "rsi_sell": upper,
                    "trend_fast": None, "trend_slow": None,
                    "use_trend": False,
                    "atr_col": "atr_14",
                    "risk_pct": 0.5,
                    "atr_mult_stop": 1.5,
                    "max_leverage": 1.0,
                })
        return out

    if name == "macd_crossover" and macd_crossover_signal:
        return [
            {"fast": 8,  "slow": 17, "signal": 9},
            {"fast": 12, "slow": 26, "signal": 9},
            {"fast": 19, "slow": 39, "signal": 9},
        ]

    if name == "breakout_atr" and breakout_atr_signal:
        # Fill with your preferred defaults when adapter is ready
        return [
            # {"lookback": 20, "atr_col": "atr_14", "atr_min_pct": 0.01, ...}
        ]

    raise KeyError(f"No default grid for strategy '{name}'")
