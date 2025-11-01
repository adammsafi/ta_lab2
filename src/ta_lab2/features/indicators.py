from __future__ import annotations
import numpy as np
import pandas as pd

__all__ = [
    "rsi",
    "macd",
    "stoch_kd",
    "bollinger",
    "atr",
    "adx",
    "obv",
    "mfi",
]

# -------------------------
# internal helpers
# -------------------------
def _ema(s: pd.Series, span: int) -> pd.Series:
    return s.astype(float).ewm(span=span, adjust=False).mean()

def _sma(s: pd.Series, window: int) -> pd.Series:
    return s.astype(float).rolling(window, min_periods=window).mean()

def _tr(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    high = high.astype(float)
    low = low.astype(float)
    close = close.astype(float)
    prev_close = close.shift(1)
    return pd.concat(
        [(high - low).abs(), (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)

def _ensure_series(obj, *, col: str | None = None) -> pd.Series:
    """Return a Series from either a Series or DataFrame+col."""
    if isinstance(obj, pd.Series):
        return obj
    if isinstance(obj, pd.DataFrame):
        if col is None:
            raise ValueError("Column name must be provided when passing a DataFrame.")
        if col not in obj.columns:
            raise KeyError(f"Column '{col}' not found in DataFrame.")
        return obj[col]
    raise TypeError("Expected a pandas Series or DataFrame.")

def _return(obj, series: pd.Series, out_col: str, *, inplace: bool):
    """
    Default behavior: return a **Series** (named).
    If inplace=True and obj is a DataFrame, assign column and return the df.
    """
    series = series.rename(out_col)
    if inplace and isinstance(obj, pd.DataFrame):
        obj[out_col] = series
        return obj
    return series

# -------------------------
# indicators
# -------------------------
def rsi(
    obj,  # Series or DataFrame
    window: int | None = 14,
    *,
    period: int | None = None,        # alias for window
    price_col: str = "close",
    out_col: str | None = None,
    inplace: bool = False,
):
    """
    RSI (Wilder). Back-compat:
      - Accepts Series or DataFrame.
      - `period` is an alias for `window`.
      - By default returns a **Series**; set `inplace=True` to assign to df and return df.
    """
    if window is None and period is not None:
        window = period
    if window is None:
        window = 14
    if out_col is None:
        out_col = f"rsi_{window}"

    s = _ensure_series(obj, col=price_col)
    delta = s.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1 / window, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / window, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    rsi_series = 100.0 - (100.0 / (1.0 + rs))
    return _return(obj, rsi_series.astype(float), out_col, inplace=inplace)

def macd(
    obj,  # Series or DataFrame
    *,
    price_col: str = "close",
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
    out_cols: tuple[str, str, str] | None = None,
    inplace: bool = False,
):
    """
    MACD (12/26/9 by default).
    Default: return DataFrame with 3 series (macd, signal, hist).
    If `inplace=True` and obj is a DataFrame, assign all three cols and return df.
    """
    if out_cols is None:
        out_cols = (f"macd_{fast}_{slow}", f"macd_signal_{signal}", f"macd_hist_{fast}_{slow}_{signal}")

    s = _ensure_series(obj, col=price_col)
    ema_fast = _ema(s, fast)
    ema_slow = _ema(s, slow)
    macd_line = ema_fast - ema_slow
    signal_line = _ema(macd_line, signal)
    hist = macd_line - signal_line
    out = pd.DataFrame({out_cols[0]: macd_line, out_cols[1]: signal_line, out_cols[2]: hist})

    if inplace and isinstance(obj, pd.DataFrame):
        for c in out.columns:
            obj[c] = out[c]
        return obj
    return out

def stoch_kd(
    obj,  # DataFrame
    *,
    high_col: str = "high",
    low_col: str = "low",
    close_col: str = "close",
    k: int = 14,
    d: int = 3,
    out_cols: tuple[str, str] | None = None,
    inplace: bool = False,
):
    """
    Stochastic %K/%D (df input expected).
    Default: return DataFrame with K and D. If `inplace=True`, assign and return df.
    """
    if out_cols is None:
        out_cols = (f"stoch_k_{k}", f"stoch_d_{d}")

    if not isinstance(obj, pd.DataFrame):
        raise TypeError("stoch_kd expects a DataFrame; pass high/low/close columns via high_col/low_col/close_col.")

    high = _ensure_series(obj, col=high_col)
    low = _ensure_series(obj, col=low_col)
    close = _ensure_series(obj, col=close_col)

    lowest = low.rolling(k, min_periods=k).min()
    highest = high.rolling(k, min_periods=k).max()
    k_line = 100.0 * (close - lowest) / (highest - lowest)
    d_line = k_line.rolling(d, min_periods=d).mean()

    out = pd.DataFrame({out_cols[0]: k_line.astype(float), out_cols[1]: d_line.astype(float)})
    if inplace:
        for c in out.columns:
            obj[c] = out[c]
        return obj
    return out

def bollinger(
    obj,  # Series or DataFrame
    window: int = 20,
    *,
    price_col: str = "close",
    n_sigma: float = 2.0,
    out_cols: tuple[str, str, str, str] | None = None,
    inplace: bool = False,
):
    """
    Bollinger Bands.
    Default: return DataFrame with ma/up/lo/width.
    If `inplace=True` and obj is a DataFrame, assign and return df.
    """
    if out_cols is None:
        out_cols = (f"bb_ma_{window}", f"bb_up_{window}_{n_sigma}", f"bb_lo_{window}_{n_sigma}", f"bb_width_{window}")

    s = _ensure_series(obj, col=price_col)
    ma = _sma(s, window)
    std = s.astype(float).rolling(window, min_periods=window).std()
    upper = ma + n_sigma * std
    lower = ma - n_sigma * std
    bw = (upper - lower) / ma

    out = pd.DataFrame({out_cols[0]: ma, out_cols[1]: upper, out_cols[2]: lower, out_cols[3]: bw})
    if inplace and isinstance(obj, pd.DataFrame):
        for c in out.columns:
            obj[c] = out[c].astype(float)
        return obj
    return out

def atr(
    obj,  # DataFrame
    window: int | None = 14,
    *,
    period: int | None = None,   # alias for window
    high_col: str = "high",
    low_col: str = "low",
    close_col: str = "close",
    out_col: str | None = None,
    inplace: bool = False,
):
    """
    Average True Range (simple rolling mean of TR, matching your original).
    Default: return Series; if `inplace=True`, assign to df and return df.
    """
    if window is None and period is not None:
        window = period
    if window is None:
        window = 14
    if out_col is None:
        out_col = f"atr_{window}"

    if not isinstance(obj, pd.DataFrame):
        raise TypeError("atr expects a DataFrame; pass high/low/close columns via high_col/low_col/close_col.")

    high = _ensure_series(obj, col=high_col)
    low = _ensure_series(obj, col=low_col)
    close = _ensure_series(obj, col=close_col)

    tr = _tr(high, low, close)
    out = tr.rolling(window, min_periods=window).mean().astype(float)
    return _return(obj, out, out_col, inplace=inplace)

def adx(
    obj,  # DataFrame
    window: int | None = 14,
    *,
    period: int | None = None,  # alias for window
    high_col: str = "high",
    low_col: str = "low",
    close_col: str = "close",
    out_col: str | None = None,
    inplace: bool = False,
):
    """
    ADX (vectorized conditions, preserves original behavior).
    Default: return Series; if `inplace=True`, assign and return df.
    """
    if window is None and period is not None:
        window = period
    if window is None:
        window = 14
    if out_col is None:
        out_col = f"adx_{window}"

    if not isinstance(obj, pd.DataFrame):
        raise TypeError("adx expects a DataFrame; pass high/low/close columns via high_col/low_col/close_col.")

    high = _ensure_series(obj, col=high_col)
    low = _ensure_series(obj, col=low_col)
    close = _ensure_series(obj, col=close_col)

    up = high.diff()
    dn = -low.diff()

    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)

    tr = _tr(high, low, close)
    atr_ = tr.rolling(window, min_periods=window).mean()

    plus_di = 100.0 * pd.Series(plus_dm, index=high.index).rolling(window, min_periods=window).sum() / atr_
    minus_di = 100.0 * pd.Series(minus_dm, index=high.index).rolling(window, min_periods=window).sum() / atr_

    dx = ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0.0, np.nan)) * 100.0
    adx_series = dx.rolling(window, min_periods=window).mean().astype(float)
    return _return(obj, adx_series, out_col, inplace=inplace)

def obv(
    obj,  # DataFrame
    *,
    price_col: str = "close",
    volume_col: str = "volume",
    out_col: str = "obv",
    inplace: bool = False,
):
    """
    On-Balance Volume.
    Default: return Series; if `inplace=True`, assign and return df.
    """
    if not isinstance(obj, pd.DataFrame):
        raise TypeError("obv requires a DataFrame with price_col and volume_col.")

    close = _ensure_series(obj, col=price_col)
    volume = _ensure_series(obj, col=volume_col).astype(float)

    direction = np.sign(close.diff().fillna(0.0))
    obv_series = (direction * volume).fillna(0.0).cumsum().astype(float)
    return _return(obj, obv_series, out_col, inplace=inplace)

def mfi(
    obj,  # DataFrame
    window: int | None = 14,
    *,
    period: int | None = None,   # alias for window
    high_col: str = "high",
    low_col: str = "low",
    close_col: str = "close",
    volume_col: str = "volume",
    out_col: str | None = None,
    inplace: bool = False,
):
    """
    Money Flow Index. Default: return Series; if `inplace=True`, assign and return df.
    """
    if window is None and period is not None:
        window = period
    if window is None:
        window = 14
    if out_col is None:
        out_col = f"mfi_{window}"

    if not isinstance(obj, pd.DataFrame):
        raise TypeError("mfi expects a DataFrame; pass high/low/close/volume via *_col params.")

    high = _ensure_series(obj, col=high_col)
    low = _ensure_series(obj, col=low_col)
    close = _ensure_series(obj, col=close_col)
    volume = _ensure_series(obj, col=volume_col).astype(float)

    tp = (high.astype(float) + low.astype(float) + close.astype(float)) / 3.0
    raw = tp * volume
    pos = raw.where(tp.diff() > 0, 0.0)
    neg = raw.where(tp.diff() < 0, 0.0)

    pmf = pos.rolling(window, min_periods=window).sum()
    nmf = (-neg).rolling(window, min_periods=window).sum()
    mr = pmf / nmf.replace(0.0, np.nan)

    out = (100.0 - (100.0 / (1.0 + mr))).astype(float)
    return _return(obj, out, out_col, inplace=inplace)
