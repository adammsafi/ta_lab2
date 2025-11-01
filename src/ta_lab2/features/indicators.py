from __future__ import annotations
import numpy as np
import pandas as pd

# ---- helpers ----
def _ema(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=span, adjust=False).mean()

def _sma(s: pd.Series, window: int) -> pd.Series:
    return s.rolling(window, min_periods=window).mean()

def _tr(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    prev_close = close.shift(1)
    return pd.concat([
        (high - low).abs(),
        (high - prev_close).abs(),
        (low - prev_close).abs()
    ], axis=1).max(axis=1)

# ---- indicators ----
def rsi(close: pd.Series, window: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/window, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/window, adjust=False).mean()
    rs = avg_gain / (avg_loss.replace(0, np.nan))
    out = 100 - (100 / (1 + rs))
    return out.rename(f"rsi_{window}")

def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    ema_fast = _ema(close, fast)
    ema_slow = _ema(close, slow)
    macd_line = ema_fast - ema_slow
    signal_line = _ema(macd_line, signal)
    hist = macd_line - signal_line
    return pd.DataFrame({
        f"macd_{fast}_{slow}": macd_line,
        f"macd_signal_{signal}": signal_line,
        f"macd_hist_{fast}_{slow}_{signal}": hist
    })

def stoch_kd(high: pd.Series, low: pd.Series, close: pd.Series, k: int = 14, d: int = 3) -> pd.DataFrame:
    lowest = low.rolling(k, min_periods=k).min()
    highest = high.rolling(k, min_periods=k).max()
    k_line = 100 * (close - lowest) / (highest - lowest)
    d_line = k_line.rolling(d, min_periods=d).mean()
    return pd.DataFrame({f"stoch_k_{k}": k_line, f"stoch_d_{d}": d_line})

def bollinger(close: pd.Series, window: int = 20, n_sigma: float = 2.0) -> pd.DataFrame:
    ma = _sma(close, window)
    std = close.rolling(window, min_periods=window).std()
    upper = ma + n_sigma * std
    lower = ma - n_sigma * std
    bw = (upper - lower) / ma
    return pd.DataFrame({
        f"bb_ma_{window}": ma,
        f"bb_up_{window}_{n_sigma}": upper,
        f"bb_lo_{window}_{n_sigma}": lower,
        f"bb_width_{window}": bw
    })

def atr(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 14) -> pd.Series:
    tr = _tr(high, low, close)
    out = tr.rolling(window, min_periods=window).mean()
    return out.rename(f"atr_{window}")

def adx(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 14) -> pd.Series:
    up = high.diff()
    dn = -low.diff()
    plus_dm  = np.where((up > dn) and isinstance(up, pd.Series) and (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) and isinstance(dn, pd.Series) and (dn > 0), dn, 0.0)
    tr = _tr(high, low, close)
    atr_ = tr.rolling(window, min_periods=window).mean()
    plus_di  = 100 * pd.Series(plus_dm, index=high.index).rolling(window, min_periods=window).sum() / atr_
    minus_di = 100 * pd.Series(minus_dm, index=high.index).rolling(window, min_periods=window).sum() / atr_
    dx = ((plus_di - minus_di).abs() / (plus_di + minus_di)) * 100
    adx_ = dx.rolling(window, min_periods=window).mean()
    return adx_.rename(f"adx_{window}")

def obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    direction = np.sign(close.diff().fillna(0))
    return (direction * volume).fillna(0).cumsum().rename("obv")

def mfi(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series, window: int = 14) -> pd.Series:
    tp = (high + low + close) / 3.0
    raw = tp * volume
    pos = raw.where(tp.diff() > 0, 0.0)
    neg = raw.where(tp.diff() < 0, 0.0)
    mr = pos.rolling(window, min_periods=window).sum() / (
        neg.rolling(window, min_periods=window).sum().replace(0, np.nan)
    )
    out = 100 - (100 / (1 + mr))
    return out.rename(f"mfi_{window}")
