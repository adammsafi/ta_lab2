from __future__ import annotations

import numpy as np
import pandas as pd

from ta_lab2.features.indicators import _ema, _sma, _tr, _ensure_series, _return

__all__ = [
    "ichimoku",
    "williams_r",
    "keltner",
    "cci",
    "elder_ray",
    "force_index",
    "vwap",
    "cmf",
    "chaikin_osc",
    "hurst",
    "vidya",
    "frama",
    "aroon",
    "trix",
    "ultimate_osc",
    "vortex",
    "emv",
    "mass_index",
    "kst",
    "coppock",
]


# -------------------------
# shared helpers
# -------------------------
def _tp(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    """Typical price (H+L+C)/3, used by CCI, CMF, VWAP."""
    return (high.astype(float) + low.astype(float) + close.astype(float)) / 3.0


def _wma(s: pd.Series, n: int) -> pd.Series:
    """Weighted moving average with linear weights 1..n."""
    weights = np.arange(1, n + 1, dtype=float)
    total = weights.sum()

    def _wma_window(x: np.ndarray) -> float:
        if len(x) < n:
            return np.nan
        return float(np.dot(x[-n:], weights) / total)

    return s.astype(float).rolling(n, min_periods=n).apply(_wma_window, raw=True)


# -------------------------
# Batch 1: ichimoku through hurst
# -------------------------


def ichimoku(
    obj,
    *,
    tenkan: int = 9,
    kijun: int = 26,
    senkou_b: int = 52,
    high_col: str = "high",
    low_col: str = "low",
    close_col: str = "close",
    out_cols: tuple[str, ...] | None = None,
    inplace: bool = False,
):
    """
    Ichimoku Cloud.
    Returns DataFrame with 5 columns: tenkan, kijun, span_a, span_b, chikou.
    Span A and Span B are NOT forward-shifted (no look-ahead).
    Chikou = close.shift(kijun) — gives close at T-kijun periods ago.
    """
    if out_cols is None:
        out_cols = (
            "ichimoku_tenkan",
            "ichimoku_kijun",
            "ichimoku_span_a",
            "ichimoku_span_b",
            "ichimoku_chikou",
        )

    if not isinstance(obj, pd.DataFrame):
        raise TypeError("ichimoku expects a DataFrame.")

    high = _ensure_series(obj, col=high_col).astype(float)
    low = _ensure_series(obj, col=low_col).astype(float)
    close = _ensure_series(obj, col=close_col).astype(float)

    tenkan_line = (
        high.rolling(tenkan, min_periods=tenkan).max()
        + low.rolling(tenkan, min_periods=tenkan).min()
    ) / 2.0

    kijun_line = (
        high.rolling(kijun, min_periods=kijun).max()
        + low.rolling(kijun, min_periods=kijun).min()
    ) / 2.0

    span_a = (tenkan_line + kijun_line) / 2.0

    span_b = (
        high.rolling(senkou_b, min_periods=senkou_b).max()
        + low.rolling(senkou_b, min_periods=senkou_b).min()
    ) / 2.0

    chikou = close.shift(kijun)

    out = pd.DataFrame(
        {
            out_cols[0]: tenkan_line.astype(float),
            out_cols[1]: kijun_line.astype(float),
            out_cols[2]: span_a.astype(float),
            out_cols[3]: span_b.astype(float),
            out_cols[4]: chikou.astype(float),
        }
    )

    if inplace and isinstance(obj, pd.DataFrame):
        for c in out.columns:
            obj[c] = out[c]
        return obj
    return out


def williams_r(
    obj,
    window: int = 14,
    *,
    high_col: str = "high",
    low_col: str = "low",
    close_col: str = "close",
    out_col: str | None = None,
    inplace: bool = False,
):
    """
    Williams %R.
    willr = -100 * (HH_N - close) / (HH_N - LL_N)
    Default: return Series; if `inplace=True`, assign and return df.
    """
    if out_col is None:
        out_col = f"willr_{window}"

    if not isinstance(obj, pd.DataFrame):
        raise TypeError("williams_r expects a DataFrame.")

    high = _ensure_series(obj, col=high_col).astype(float)
    low = _ensure_series(obj, col=low_col).astype(float)
    close = _ensure_series(obj, col=close_col).astype(float)

    hh = high.rolling(window, min_periods=window).max()
    ll = low.rolling(window, min_periods=window).min()
    denom = (hh - ll).replace(0.0, np.nan)
    out = (-100.0 * (hh - close) / denom).astype(float)
    return _return(obj, out, out_col, inplace=inplace)


def keltner(
    obj,
    *,
    ema_period: int = 20,
    atr_period: int = 10,
    multiplier: float = 2.0,
    high_col: str = "high",
    low_col: str = "low",
    close_col: str = "close",
    out_cols: tuple[str, ...] | None = None,
    inplace: bool = False,
):
    """
    Keltner Channels.
    Returns DataFrame with 4 columns: mid, upper, lower, width.
    """
    if out_cols is None:
        out_cols = (
            f"kc_mid_{ema_period}",
            f"kc_upper_{ema_period}",
            f"kc_lower_{ema_period}",
            f"kc_width_{ema_period}",
        )

    if not isinstance(obj, pd.DataFrame):
        raise TypeError("keltner expects a DataFrame.")

    high = _ensure_series(obj, col=high_col).astype(float)
    low = _ensure_series(obj, col=low_col).astype(float)
    close = _ensure_series(obj, col=close_col).astype(float)

    mid = _ema(close, ema_period)
    tr = _tr(high, low, close)
    atr_val = tr.rolling(atr_period, min_periods=atr_period).mean()
    upper = mid + multiplier * atr_val
    lower = mid - multiplier * atr_val
    mid_safe = mid.replace(0.0, np.nan)
    width = (upper - lower) / mid_safe

    out = pd.DataFrame(
        {
            out_cols[0]: mid.astype(float),
            out_cols[1]: upper.astype(float),
            out_cols[2]: lower.astype(float),
            out_cols[3]: width.astype(float),
        }
    )

    if inplace and isinstance(obj, pd.DataFrame):
        for c in out.columns:
            obj[c] = out[c]
        return obj
    return out


def cci(
    obj,
    window: int = 20,
    *,
    high_col: str = "high",
    low_col: str = "low",
    close_col: str = "close",
    out_col: str | None = None,
    inplace: bool = False,
):
    """
    Commodity Channel Index.
    CRITICAL: Uses mean absolute deviation (NOT rolling std).
    Default: return Series; if `inplace=True`, assign and return df.
    """
    if out_col is None:
        out_col = f"cci_{window}"

    if not isinstance(obj, pd.DataFrame):
        raise TypeError("cci expects a DataFrame.")

    high = _ensure_series(obj, col=high_col).astype(float)
    low = _ensure_series(obj, col=low_col).astype(float)
    close = _ensure_series(obj, col=close_col).astype(float)

    tp = _tp(high, low, close)
    sma_tp = _sma(tp, window)
    mean_dev = (tp - sma_tp).abs().rolling(window, min_periods=window).mean()
    out = ((tp - sma_tp) / (0.015 * mean_dev.replace(0.0, np.nan))).astype(float)
    return _return(obj, out, out_col, inplace=inplace)


def elder_ray(
    obj,
    *,
    period: int = 13,
    high_col: str = "high",
    low_col: str = "low",
    close_col: str = "close",
    out_cols: tuple[str, str] | None = None,
    inplace: bool = False,
):
    """
    Elder Ray Index.
    Returns DataFrame with 2 columns: bull power, bear power.
    """
    if out_cols is None:
        out_cols = (f"elder_bull_{period}", f"elder_bear_{period}")

    if not isinstance(obj, pd.DataFrame):
        raise TypeError("elder_ray expects a DataFrame.")

    high = _ensure_series(obj, col=high_col).astype(float)
    low = _ensure_series(obj, col=low_col).astype(float)
    close = _ensure_series(obj, col=close_col).astype(float)

    ema_close = _ema(close, period)
    bull = (high - ema_close).astype(float)
    bear = (low - ema_close).astype(float)

    out = pd.DataFrame({out_cols[0]: bull, out_cols[1]: bear})

    if inplace and isinstance(obj, pd.DataFrame):
        for c in out.columns:
            obj[c] = out[c]
        return obj
    return out


def force_index(
    obj,
    *,
    smooth: int = 13,
    close_col: str = "close",
    volume_col: str = "volume",
    out_cols: tuple[str, str] | None = None,
    inplace: bool = False,
):
    """
    Force Index.
    Returns DataFrame with 2 columns: fi_1 (raw) and fi_N (smoothed EMA).
    """
    if out_cols is None:
        out_cols = ("fi_1", f"fi_{smooth}")

    if not isinstance(obj, pd.DataFrame):
        raise TypeError("force_index expects a DataFrame.")

    close = _ensure_series(obj, col=close_col).astype(float)
    volume = _ensure_series(obj, col=volume_col).astype(float)

    fi_1 = (close.diff() * volume).astype(float)
    fi_smooth = _ema(fi_1, smooth).astype(float)

    out = pd.DataFrame({out_cols[0]: fi_1, out_cols[1]: fi_smooth})

    if inplace and isinstance(obj, pd.DataFrame):
        for c in out.columns:
            obj[c] = out[c]
        return obj
    return out


def vwap(
    obj,
    window: int = 14,
    *,
    high_col: str = "high",
    low_col: str = "low",
    close_col: str = "close",
    volume_col: str = "volume",
    out_cols: tuple[str, str] | None = None,
    inplace: bool = False,
):
    """
    Volume-Weighted Average Price (rolling window, NOT cumulative).
    Returns DataFrame with 2 columns: vwap_N and vwap_dev_N.
    """
    if out_cols is None:
        out_cols = (f"vwap_{window}", f"vwap_dev_{window}")

    if not isinstance(obj, pd.DataFrame):
        raise TypeError("vwap expects a DataFrame.")

    high = _ensure_series(obj, col=high_col).astype(float)
    low = _ensure_series(obj, col=low_col).astype(float)
    close = _ensure_series(obj, col=close_col).astype(float)
    volume = _ensure_series(obj, col=volume_col).astype(float)

    tp = _tp(high, low, close)
    tp_vol = tp * volume
    rolling_tp_vol = tp_vol.rolling(window, min_periods=window).sum()
    rolling_vol = volume.rolling(window, min_periods=window).sum().replace(0.0, np.nan)
    vwap_val = (rolling_tp_vol / rolling_vol).astype(float)
    vwap_dev = (close / vwap_val.replace(0.0, np.nan) - 1.0).astype(float)

    out = pd.DataFrame({out_cols[0]: vwap_val, out_cols[1]: vwap_dev})

    if inplace and isinstance(obj, pd.DataFrame):
        for c in out.columns:
            obj[c] = out[c]
        return obj
    return out


def cmf(
    obj,
    window: int = 20,
    *,
    high_col: str = "high",
    low_col: str = "low",
    close_col: str = "close",
    volume_col: str = "volume",
    out_col: str | None = None,
    inplace: bool = False,
):
    """
    Chaikin Money Flow.
    Default: return Series; if `inplace=True`, assign and return df.
    """
    if out_col is None:
        out_col = f"cmf_{window}"

    if not isinstance(obj, pd.DataFrame):
        raise TypeError("cmf expects a DataFrame.")

    high = _ensure_series(obj, col=high_col).astype(float)
    low = _ensure_series(obj, col=low_col).astype(float)
    close = _ensure_series(obj, col=close_col).astype(float)
    volume = _ensure_series(obj, col=volume_col).astype(float)

    hl_range = (high - low).replace(0.0, np.nan)
    mfm = ((close - low) - (high - close)) / hl_range
    mfv = mfm * volume

    rolling_mfv = mfv.rolling(window, min_periods=window).sum()
    rolling_vol = volume.rolling(window, min_periods=window).sum().replace(0.0, np.nan)
    out = (rolling_mfv / rolling_vol).astype(float)
    return _return(obj, out, out_col, inplace=inplace)


def chaikin_osc(
    obj,
    *,
    fast: int = 3,
    slow: int = 10,
    high_col: str = "high",
    low_col: str = "low",
    close_col: str = "close",
    volume_col: str = "volume",
    out_col: str | None = None,
    inplace: bool = False,
):
    """
    Chaikin Oscillator.
    Default: return Series; if `inplace=True`, assign and return df.
    """
    if out_col is None:
        out_col = f"chaikin_osc_{fast}_{slow}"

    if not isinstance(obj, pd.DataFrame):
        raise TypeError("chaikin_osc expects a DataFrame.")

    high = _ensure_series(obj, col=high_col).astype(float)
    low = _ensure_series(obj, col=low_col).astype(float)
    close = _ensure_series(obj, col=close_col).astype(float)
    volume = _ensure_series(obj, col=volume_col).astype(float)

    hl_range = (high - low).replace(0.0, np.nan)
    mfm = ((close - low) - (high - close)) / hl_range
    mfv = mfm * volume
    adl = mfv.cumsum()

    out = (_ema(adl, fast) - _ema(adl, slow)).astype(float)
    return _return(obj, out, out_col, inplace=inplace)


def _hurst_inner(x: np.ndarray, max_lag: int = 20) -> float:
    """Inner function for rolling Hurst exponent (variance-scaling method)."""
    lags = range(2, max_lag + 1)
    tau = []
    for lag in lags:
        diffs = x[lag:] - x[:-lag]
        if len(diffs) < 2:
            return np.nan
        tau.append(np.std(diffs))
    if len(tau) < 2:
        return np.nan
    log_lags = np.log(list(lags))
    log_tau = np.log(np.array(tau, dtype=float) + 1e-16)
    try:
        slope = np.polyfit(log_lags, log_tau, 1)[0]
    except (np.linalg.LinAlgError, ValueError):
        return np.nan
    return float(slope)


def hurst(
    obj,
    window: int = 100,
    *,
    max_lag: int = 20,
    close_col: str = "close",
    out_col: str | None = None,
    inplace: bool = False,
):
    """
    Hurst Exponent (variance-scaling method).
    Uses rolling(window, min_periods=window).apply with inner polyfit.
    Default: return Series; if `inplace=True`, assign and return df.
    """
    if out_col is None:
        out_col = f"hurst_{window}"

    s = _ensure_series(obj, col=close_col).astype(float)

    def _apply(x: np.ndarray) -> float:
        return _hurst_inner(x, max_lag=max_lag)

    out = s.rolling(window, min_periods=window).apply(_apply, raw=True).astype(float)
    return _return(obj, out, out_col, inplace=inplace)


# -------------------------
# Batch 2: vidya through coppock
# -------------------------


def vidya(
    obj,
    *,
    cmo_period: int = 9,
    vidya_period: int = 9,
    close_col: str = "close",
    out_col: str | None = None,
    inplace: bool = False,
):
    """
    Variable Index Dynamic Average (VIDYA).
    MUST use explicit Python loop (not vectorizable).
    Default: return Series; if `inplace=True`, assign and return df.
    """
    if out_col is None:
        out_col = f"vidya_{vidya_period}"

    s = _ensure_series(obj, col=close_col).astype(float)
    arr = s.to_numpy()
    n = len(arr)
    k = 2.0 / (vidya_period + 1)

    result = np.full(n, np.nan)

    # Compute CMO for each bar
    for i in range(cmo_period, n):
        # Rolling CMO over cmo_period bars (differences)
        window_slice = arr[i - cmo_period : i + 1]
        diffs = np.diff(window_slice)
        up_sum = np.sum(diffs[diffs > 0])
        dn_sum = np.sum(np.abs(diffs[diffs < 0]))
        denom = up_sum + dn_sum
        if denom == 0.0:
            cmo_val = 0.0
        else:
            cmo_val = (up_sum - dn_sum) / denom

        alpha = abs(cmo_val) * k

        if np.isnan(result[i - 1]):
            result[i] = arr[i]
        else:
            result[i] = alpha * arr[i] + (1.0 - alpha) * result[i - 1]

    out = pd.Series(result, index=s.index, dtype=float)
    return _return(obj, out, out_col, inplace=inplace)


def frama(
    obj,
    *,
    period: int = 16,
    close_col: str = "close",
    out_col: str | None = None,
    inplace: bool = False,
):
    """
    Fractal Adaptive Moving Average (FRAMA).
    MUST use explicit Python loop (not vectorizable).
    Period must be even.
    Default: return Series; if `inplace=True`, assign and return df.
    """
    if period % 2 != 0:
        period = period + 1  # Force even

    if out_col is None:
        out_col = f"frama_{period}"

    s = _ensure_series(obj, col=close_col).astype(float)
    arr = s.to_numpy()
    n = len(arr)
    half = period // 2

    result = np.full(n, np.nan)

    for i in range(period - 1, n):
        window = arr[i - period + 1 : i + 1]
        first_half = window[:half]
        second_half = window[half:]

        n1 = (np.max(first_half) - np.min(first_half)) / half
        n2 = (np.max(second_half) - np.min(second_half)) / half
        n3 = (np.max(window) - np.min(window)) / period

        if n1 + n2 <= 0 or n3 <= 0:
            d = 1.0
        else:
            denom = np.log(n1 + n2) - np.log(n3)
            if denom == 0.0:
                d = 1.0
            else:
                d = np.log(2.0) / denom

        alpha = np.exp(-4.6 * (d - 1.0))
        alpha = float(np.clip(alpha, 0.01, 1.0))

        if np.isnan(result[i - 1]):
            result[i] = arr[i]
        else:
            result[i] = alpha * arr[i] + (1.0 - alpha) * result[i - 1]

    out = pd.Series(result, index=s.index, dtype=float)
    return _return(obj, out, out_col, inplace=inplace)


def aroon(
    obj,
    window: int = 25,
    *,
    high_col: str = "high",
    low_col: str = "low",
    out_cols: tuple[str, str, str] | None = None,
    inplace: bool = False,
):
    """
    Aroon Indicator.
    CRITICAL: Uses N+1 rolling window.
    Returns DataFrame with 3 columns: aroon_up, aroon_dn, aroon_osc.
    """
    if out_cols is None:
        out_cols = (f"aroon_up_{window}", f"aroon_dn_{window}", f"aroon_osc_{window}")

    if not isinstance(obj, pd.DataFrame):
        raise TypeError("aroon expects a DataFrame.")

    high = _ensure_series(obj, col=high_col).astype(float)
    low = _ensure_series(obj, col=low_col).astype(float)

    roll_window = window + 1  # N+1 rolling window

    def _periods_since_max(x: np.ndarray) -> float:
        return float(len(x) - 1 - np.argmax(x))

    def _periods_since_min(x: np.ndarray) -> float:
        return float(len(x) - 1 - np.argmin(x))

    periods_since_high = high.rolling(roll_window, min_periods=roll_window).apply(
        _periods_since_max, raw=True
    )
    periods_since_low = low.rolling(roll_window, min_periods=roll_window).apply(
        _periods_since_min, raw=True
    )

    aroon_up = ((window - periods_since_high) / window * 100.0).astype(float)
    aroon_dn = ((window - periods_since_low) / window * 100.0).astype(float)
    aroon_osc = (aroon_up - aroon_dn).astype(float)

    out = pd.DataFrame(
        {out_cols[0]: aroon_up, out_cols[1]: aroon_dn, out_cols[2]: aroon_osc}
    )

    if inplace and isinstance(obj, pd.DataFrame):
        for c in out.columns:
            obj[c] = out[c]
        return obj
    return out


def trix(
    obj,
    *,
    period: int = 15,
    signal_period: int = 9,
    close_col: str = "close",
    out_cols: tuple[str, str] | None = None,
    inplace: bool = False,
):
    """
    TRIX (Triple Exponential Moving Average Oscillator).
    Returns DataFrame with 2 columns: trix and trix_signal.
    """
    if out_cols is None:
        out_cols = (f"trix_{period}", f"trix_signal_{signal_period}")

    s = _ensure_series(obj, col=close_col).astype(float)

    ema1 = _ema(s, period)
    ema2 = _ema(ema1, period)
    ema3 = _ema(ema2, period)

    ema3_prev = ema3.shift(1).replace(0.0, np.nan)
    trix_line = ((ema3 - ema3_prev) / ema3_prev * 100.0).astype(float)
    trix_signal = _ema(trix_line, signal_period).astype(float)

    out = pd.DataFrame({out_cols[0]: trix_line, out_cols[1]: trix_signal})

    if inplace and isinstance(obj, pd.DataFrame):
        for c in out.columns:
            obj[c] = out[c]
        return obj
    return out


def ultimate_osc(
    obj,
    *,
    p1: int = 7,
    p2: int = 14,
    p3: int = 28,
    high_col: str = "high",
    low_col: str = "low",
    close_col: str = "close",
    out_col: str | None = None,
    inplace: bool = False,
):
    """
    Ultimate Oscillator.
    Default: return Series; if `inplace=True`, assign and return df.
    """
    if out_col is None:
        out_col = f"uo_{p1}_{p2}_{p3}"

    if not isinstance(obj, pd.DataFrame):
        raise TypeError("ultimate_osc expects a DataFrame.")

    high = _ensure_series(obj, col=high_col).astype(float)
    low = _ensure_series(obj, col=low_col).astype(float)
    close = _ensure_series(obj, col=close_col).astype(float)

    prev_close = close.shift(1)
    true_low = pd.concat([low, prev_close], axis=1).min(axis=1)
    true_high = pd.concat([high, prev_close], axis=1).max(axis=1)

    bp = close - true_low
    tr = true_high - true_low

    def _avg(bp_s: pd.Series, tr_s: pd.Series, period: int) -> pd.Series:
        bp_sum = bp_s.rolling(period, min_periods=period).sum()
        tr_sum = tr_s.rolling(period, min_periods=period).sum().replace(0.0, np.nan)
        return bp_sum / tr_sum

    avg1 = _avg(bp, tr, p1)
    avg2 = _avg(bp, tr, p2)
    avg3 = _avg(bp, tr, p3)

    out = (100.0 * (4.0 * avg1 + 2.0 * avg2 + avg3) / 7.0).astype(float)
    return _return(obj, out, out_col, inplace=inplace)


def vortex(
    obj,
    window: int = 14,
    *,
    high_col: str = "high",
    low_col: str = "low",
    close_col: str = "close",
    out_cols: tuple[str, str] | None = None,
    inplace: bool = False,
):
    """
    Vortex Indicator.
    Returns DataFrame with 2 columns: vi_plus and vi_minus.
    """
    if out_cols is None:
        out_cols = (f"vi_plus_{window}", f"vi_minus_{window}")

    if not isinstance(obj, pd.DataFrame):
        raise TypeError("vortex expects a DataFrame.")

    high = _ensure_series(obj, col=high_col).astype(float)
    low = _ensure_series(obj, col=low_col).astype(float)
    close = _ensure_series(obj, col=close_col).astype(float)

    prev_high = high.shift(1)
    prev_low = low.shift(1)

    vm_plus = (high - prev_low).abs()
    vm_minus = (low - prev_high).abs()
    tr = _tr(high, low, close)

    sum_vm_plus = vm_plus.rolling(window, min_periods=window).sum()
    sum_vm_minus = vm_minus.rolling(window, min_periods=window).sum()
    sum_tr = tr.rolling(window, min_periods=window).sum().replace(0.0, np.nan)

    vi_plus = (sum_vm_plus / sum_tr).astype(float)
    vi_minus = (sum_vm_minus / sum_tr).astype(float)

    out = pd.DataFrame({out_cols[0]: vi_plus, out_cols[1]: vi_minus})

    if inplace and isinstance(obj, pd.DataFrame):
        for c in out.columns:
            obj[c] = out[c]
        return obj
    return out


def emv(
    obj,
    window: int = 14,
    *,
    high_col: str = "high",
    low_col: str = "low",
    volume_col: str = "volume",
    out_cols: tuple[str, str] | None = None,
    inplace: bool = False,
):
    """
    Ease of Movement (EMV).
    Returns DataFrame with 2 columns: emv_1 (raw) and emv_N (smoothed SMA).
    """
    if out_cols is None:
        out_cols = ("emv_1", f"emv_{window}")

    if not isinstance(obj, pd.DataFrame):
        raise TypeError("emv expects a DataFrame.")

    high = _ensure_series(obj, col=high_col).astype(float)
    low = _ensure_series(obj, col=low_col).astype(float)
    volume = _ensure_series(obj, col=volume_col).astype(float)

    midpoint_move = ((high + low) / 2.0) - ((high.shift(1) + low.shift(1)) / 2.0)
    hl_range = (high - low).replace(0.0, np.nan)
    box_ratio = (volume / 1e6) / hl_range
    emv_1 = (midpoint_move / box_ratio.replace(0.0, np.nan)).astype(float)
    emv_smooth = _sma(emv_1, window).astype(float)

    out = pd.DataFrame({out_cols[0]: emv_1, out_cols[1]: emv_smooth})

    if inplace and isinstance(obj, pd.DataFrame):
        for c in out.columns:
            obj[c] = out[c]
        return obj
    return out


def mass_index(
    obj,
    *,
    ema_period: int = 9,
    sum_period: int = 25,
    high_col: str = "high",
    low_col: str = "low",
    out_col: str | None = None,
    inplace: bool = False,
):
    """
    Mass Index.
    Default: return Series; if `inplace=True`, assign and return df.
    """
    if out_col is None:
        out_col = f"mass_index_{sum_period}"

    if not isinstance(obj, pd.DataFrame):
        raise TypeError("mass_index expects a DataFrame.")

    high = _ensure_series(obj, col=high_col).astype(float)
    low = _ensure_series(obj, col=low_col).astype(float)

    hl_range = high - low
    ema1 = _ema(hl_range, ema_period)
    ema2 = _ema(ema1, ema_period)
    ratio = ema1 / ema2.replace(0.0, np.nan)
    out = ratio.rolling(sum_period, min_periods=sum_period).sum().astype(float)
    return _return(obj, out, out_col, inplace=inplace)


def kst(
    obj,
    *,
    close_col: str = "close",
    out_cols: tuple[str, str] | None = None,
    inplace: bool = False,
):
    """
    Know Sure Thing (KST) oscillator with standard parameters.
    Returns DataFrame with 2 columns: kst and kst_signal.
    ROC periods: 10, 13, 14, 15; SMA periods: 10, 13, 14, 9.
    """
    if out_cols is None:
        out_cols = ("kst", "kst_signal")

    s = _ensure_series(obj, col=close_col).astype(float)

    # Standard KST parameters: (roc_period, sma_period, weight)
    params = [
        (10, 10, 1),
        (13, 13, 2),
        (14, 14, 3),
        (15, 9, 4),
    ]

    kst_line = pd.Series(0.0, index=s.index)
    for roc_period, sma_period, weight in params:
        roc = (
            (s - s.shift(roc_period)) / s.shift(roc_period).replace(0.0, np.nan) * 100.0
        )
        sma_roc = _sma(roc, sma_period)
        kst_line = kst_line + weight * sma_roc

    kst_signal = _sma(kst_line, 9)

    out = pd.DataFrame(
        {out_cols[0]: kst_line.astype(float), out_cols[1]: kst_signal.astype(float)}
    )

    if inplace and isinstance(obj, pd.DataFrame):
        for c in out.columns:
            obj[c] = out[c]
        return obj
    return out


def coppock(
    obj,
    *,
    roc_long: int = 14,
    roc_short: int = 11,
    wma_period: int = 10,
    close_col: str = "close",
    out_col: str | None = None,
    inplace: bool = False,
):
    """
    Coppock Curve.
    Default: return Series; if `inplace=True`, assign and return df.
    """
    if out_col is None:
        out_col = f"coppock_{wma_period}"

    s = _ensure_series(obj, col=close_col).astype(float)

    roc_l = (s - s.shift(roc_long)) / s.shift(roc_long).replace(0.0, np.nan) * 100.0
    roc_s = (s - s.shift(roc_short)) / s.shift(roc_short).replace(0.0, np.nan) * 100.0
    combined = roc_l + roc_s

    out = _wma(combined, wma_period).astype(float)
    return _return(obj, out, out_col, inplace=inplace)
