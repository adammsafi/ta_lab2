# src/ta_lab2/__init__.py
from __future__ import annotations
import importlib, sys

# --- Expose feature submodules at top level for backward compatibility ---
# e.g., allow: from ta_lab2.calendar import expand_datetime_features_inplace
for _name in ("calendar", "ema", "returns", "indicators", "segments", "vol", "trend", "correlation"):
    try:
        _mod = importlib.import_module(f".features.{_name}", __name__)
        sys.modules[f"{__name__}.{_name}"] = _mod
    except Exception:
        # Some projects may not include all submodules; ignore missing ones
        pass

# -------- Calendar / datetime features --------
from .features.calendar import (
    expand_datetime_features_inplace,
    expand_multiple_timestamps,
)

# -------- EMA family --------
from .features.ema import (
    compute_ema,
    add_ema_columns,
    add_ema_d1,
    add_ema_d2,
    add_ema,  # legacy wrapper shim
)

# -------- Returns / deltas --------
from .features.returns import (
    add_returns,
    b2t_pct_delta,
    b2t_log_delta,
)

# -------- Rolling realized vol (robust import with shim) --------
_add_rv_from_returns = None
try:
    from .features.returns import add_rolling_vol_from_returns_batch as _add_rv_from_returns  # type: ignore
except Exception:
    try:
        from .features.vol import add_rolling_vol_from_returns_batch as _add_rv_from_returns  # type: ignore
    except Exception:
        _add_rv_from_returns = None

def add_rolling_vol_from_returns_batch(
    df,
    *,
    price_col: str = "close",
    modes=("log", "pct"),
    windows=(30, 60, 90),
    annualize: bool = True,
    direction: str = "oldest_top",
):
    """
    Fallback shim: delegates to the project implementation if present,
    otherwise computes rolling std on b2t returns and (optionally) annualizes.
    """
    import numpy as np
    if _add_rv_from_returns is not None:
        return _add_rv_from_returns(
            df, price_col=price_col, modes=tuple(modes),
            windows=tuple(windows), annualize=annualize, direction=direction
        )

    # Ensure needed return columns exist
    if "log" in modes and f"{price_col}_b2t_log" not in df.columns:
        b2t_log_delta(df, cols=[price_col], direction=direction)
    if "pct" in modes and f"{price_col}_b2t_pct" not in df.columns:
        b2t_pct_delta(df, cols=[price_col], direction=direction)

    for mode in modes:
        base = f"{price_col}_b2t_{mode}"
        if base not in df.columns:
            continue
        for w in windows:
            out = f"rv_{mode}_{int(w)}"
            s = df[base].astype(float).rolling(int(w), min_periods=int(w)).std()
            df[out] = s * (np.sqrt(252.0) if annualize else 1.0)
    return df

# -------- Single-bar vol --------
try:
    from .features.vol import add_atr
except Exception:
    # Optional: if vol module isn't present
    def add_atr(*args, **kwargs):
        raise ImportError("vol.add_atr not available in this build")

# -------- Indicators --------
try:
    from .features.indicators import (
        rsi, macd, stoch_kd, bollinger, atr, adx, obv, mfi
    )
except Exception:
    # make missing optional
    rsi = macd = stoch_kd = bollinger = atr = adx = obv = mfi = None

# -------- Correlation --------
try:
    from .features.correlation import (
        acf, pacf_yw, rolling_autocorr, xcorr
    )
except Exception:
    acf = pacf_yw = rolling_autocorr = xcorr = None

__all__ = [
    # Calendar/date features
    "expand_datetime_features_inplace", "expand_multiple_timestamps",

    # EMA family
    "compute_ema", "add_ema_columns", "add_ema_d1", "add_ema_d2", "add_ema",

    # Returns / deltas / rolling vol
    "add_returns", "b2t_pct_delta", "b2t_log_delta", "add_rolling_vol_from_returns_batch",

    # Single-bar vol
    "add_atr",

    # Indicators (if present)
    "rsi", "macd", "stoch_kd", "bollinger", "atr", "adx", "obv", "mfi",

    # Correlation (if present)
    "acf", "pacf_yw", "rolling_autocorr", "xcorr",
]
__version__ = "0.3.1" 
