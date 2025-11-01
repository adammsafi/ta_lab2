from .calendar import (
    expand_datetime_features_inplace,
    expand_multiple_timestamps,
)

from .ema import (
    compute_ema,
    add_ema_columns,
    add_ema_d1,
    add_ema_d2,
    add_ema,  # legacy wrapper shim
)

from .returns import (
    add_returns,
    b2t_pct_delta,
    b2t_log_delta,
    add_rolling_vol_from_returns_batch,
)

from .vol import add_atr

# Technical indicators
from .indicators import (
    rsi, macd, stoch_kd, bollinger, atr, adx, obv, mfi
)

# Correlation utilities
from .correlation import (
    acf, pacf_yw, rolling_autocorr, xcorr
)

__all__ = [
    # Calendar/date features
    "expand_datetime_features_inplace",
    "expand_multiple_timestamps",

    # EMA family
    "compute_ema",
    "add_ema_columns",
    "add_ema_d1",
    "add_ema_d2",
    "add_ema",  # legacy

    # Returns / deltas / rolling vol
    "add_returns",
    "b2t_pct_delta",
    "b2t_log_delta",
    "add_rolling_vol_from_returns_batch",

    # Single-bar vol
    "add_atr",

    # Indicators
    "rsi", "macd", "stoch_kd", "bollinger", "atr", "adx", "obv", "mfi",

    # Correlation helpers
    "acf", "pacf_yw", "rolling_autocorr", "xcorr",
]
