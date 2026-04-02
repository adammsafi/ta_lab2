from __future__ import annotations
import numpy as np
import pandas as pd

try:
    import polars as pl

    HAVE_POLARS = True
except ImportError:  # pragma: no cover
    pl = None  # type: ignore[assignment]
    HAVE_POLARS = False

__all__ = [
    "rsi",
    "macd",
    "stoch_kd",
    "bollinger",
    "atr",
    "adx",
    "obv",
    "mfi",
    # Polars variants
    "HAVE_POLARS",
    "rsi_polars",
    "macd_polars",
    "stoch_kd_polars",
    "bollinger_polars",
    "atr_polars",
    "adx_polars",
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
    period: int | None = None,  # alias for window
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
        out_cols = (
            f"macd_{fast}_{slow}",
            f"macd_signal_{signal}",
            f"macd_hist_{fast}_{slow}_{signal}",
        )

    s = _ensure_series(obj, col=price_col)
    ema_fast = _ema(s, fast)
    ema_slow = _ema(s, slow)
    macd_line = ema_fast - ema_slow
    signal_line = _ema(macd_line, signal)
    hist = macd_line - signal_line
    out = pd.DataFrame(
        {out_cols[0]: macd_line, out_cols[1]: signal_line, out_cols[2]: hist}
    )

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
        raise TypeError(
            "stoch_kd expects a DataFrame; pass high/low/close columns via high_col/low_col/close_col."
        )

    high = _ensure_series(obj, col=high_col)
    low = _ensure_series(obj, col=low_col)
    close = _ensure_series(obj, col=close_col)

    lowest = low.rolling(k, min_periods=k).min()
    highest = high.rolling(k, min_periods=k).max()
    k_line = 100.0 * (close - lowest) / (highest - lowest)
    d_line = k_line.rolling(d, min_periods=d).mean()

    out = pd.DataFrame(
        {out_cols[0]: k_line.astype(float), out_cols[1]: d_line.astype(float)}
    )
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
        out_cols = (
            f"bb_ma_{window}",
            f"bb_up_{window}_{n_sigma}",
            f"bb_lo_{window}_{n_sigma}",
            f"bb_width_{window}",
        )

    s = _ensure_series(obj, col=price_col)
    ma = _sma(s, window)
    std = s.astype(float).rolling(window, min_periods=window).std()
    upper = ma + n_sigma * std
    lower = ma - n_sigma * std
    bw = (upper - lower) / ma

    out = pd.DataFrame(
        {out_cols[0]: ma, out_cols[1]: upper, out_cols[2]: lower, out_cols[3]: bw}
    )
    if inplace and isinstance(obj, pd.DataFrame):
        for c in out.columns:
            obj[c] = out[c].astype(float)
        return obj
    return out


def atr(
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
        raise TypeError(
            "atr expects a DataFrame; pass high/low/close columns via high_col/low_col/close_col."
        )

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
        raise TypeError(
            "adx expects a DataFrame; pass high/low/close columns via high_col/low_col/close_col."
        )

    high = _ensure_series(obj, col=high_col)
    low = _ensure_series(obj, col=low_col)
    close = _ensure_series(obj, col=close_col)

    up = high.diff()
    dn = -low.diff()

    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)

    tr = _tr(high, low, close)
    atr_ = tr.rolling(window, min_periods=window).mean()

    plus_di = (
        100.0
        * pd.Series(plus_dm, index=high.index).rolling(window, min_periods=window).sum()
        / atr_
    )
    minus_di = (
        100.0
        * pd.Series(minus_dm, index=high.index)
        .rolling(window, min_periods=window)
        .sum()
        / atr_
    )

    dx = (
        (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0.0, np.nan)
    ) * 100.0
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
    period: int | None = None,  # alias for window
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
        raise TypeError(
            "mfi expects a DataFrame; pass high/low/close/volume via *_col params."
        )

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


# =============================================================================
# === Polars Variants =========================================================
# =============================================================================
# All functions below operate on a single-group pl.DataFrame (pre-sorted by ts)
# and return a pl.DataFrame with new columns appended.  Each function is a
# pure-polars equivalent of its pandas counterpart above.
#
# CRITICAL NOTES:
# - ALL rolling calls use min_samples= (NOT min_periods=). Renamed in polars 1.21+.
# - polars ewm_mean supports span= parameter directly (polars 1.36.1+).
# - For RSI Wilder smoothing: alpha=1/period. For MACD standard EMA: span=.
# - ATR uses rolling_mean (NOT ewm_mean) — matches indicators.py atr() which uses
#   rolling().mean(). This differs from vol.py add_atr_polars (which uses ewm).
# =============================================================================


def rsi_polars(
    pl_df: "pl.DataFrame",  # type: ignore[name-defined]
    period: int = 14,
    price_col: str = "close",
    out_col: str | None = None,
) -> "pl.DataFrame":  # type: ignore[name-defined]
    """RSI (Wilder smoothing) — polars-native.

    Uses alpha=1/period (Wilder EMA), matching the pandas rsi() function exactly.
    Verified exact match against pandas rsi() via synthetic unit tests.

    Args:
        pl_df: Single-group polars DataFrame sorted by ts.
        period: RSI look-back period (default 14).
        price_col: Close price column name.
        out_col: Output column name; defaults to ``rsi_{period}``.

    Returns:
        pl_df with ``rsi_{period}`` column appended.
    """
    if out_col is None:
        out_col = f"rsi_{period}"

    delta = pl.col(price_col).diff()
    gain = delta.clip(lower_bound=0.0)
    loss = (-delta).clip(lower_bound=0.0)

    avg_gain = gain.ewm_mean(alpha=1.0 / period, adjust=False, min_samples=1)
    avg_loss = loss.ewm_mean(alpha=1.0 / period, adjust=False, min_samples=1)

    # Replace zero avg_loss with null to avoid inf (matching pandas .replace(0, np.nan))
    avg_loss_safe = pl.when(avg_loss == 0.0).then(None).otherwise(avg_loss)
    rs = avg_gain / avg_loss_safe
    rsi_expr = (pl.lit(100.0) - pl.lit(100.0) / (pl.lit(1.0) + rs)).alias(out_col)

    return pl_df.with_columns([rsi_expr])


def macd_polars(
    pl_df: "pl.DataFrame",  # type: ignore[name-defined]
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
    price_col: str = "close",
    out_cols: tuple | None = None,
) -> "pl.DataFrame":  # type: ignore[name-defined]
    """MACD (12/26/9 by default) — polars-native.

    Uses span= parameter for EMA (polars 1.36.1+), matching pandas ewm(span=).
    Verified exact match against pandas macd() via synthetic unit tests.

    Args:
        pl_df: Single-group polars DataFrame sorted by ts.
        fast: Fast EMA span (default 12).
        slow: Slow EMA span (default 26).
        signal: Signal line EMA span (default 9).
        price_col: Close price column name.
        out_cols: Tuple of 3 output column names; defaults to
                  (macd_{fast}_{slow}, macd_signal_{signal}, macd_hist_{fast}_{slow}_{signal}).

    Returns:
        pl_df with 3 MACD columns appended.
    """
    if out_cols is None:
        out_cols = (
            f"macd_{fast}_{slow}",
            f"macd_signal_{signal}",
            f"macd_hist_{fast}_{slow}_{signal}",
        )

    # Intermediate column names (won't clash with existing columns)
    _fast_col = "__macd_ema_fast__"
    _slow_col = "__macd_ema_slow__"
    _macd_col = "__macd_line__"

    ema_fast_expr = pl.col(price_col).ewm_mean(span=fast, adjust=False).alias(_fast_col)
    ema_slow_expr = pl.col(price_col).ewm_mean(span=slow, adjust=False).alias(_slow_col)

    pl_df = pl_df.with_columns([ema_fast_expr, ema_slow_expr])

    macd_line_expr = (pl.col(_fast_col) - pl.col(_slow_col)).alias(_macd_col)
    pl_df = pl_df.with_columns([macd_line_expr])

    signal_line_expr = (
        pl.col(_macd_col).ewm_mean(span=signal, adjust=False).alias(out_cols[1])
    )
    pl_df = pl_df.with_columns([signal_line_expr])

    # Build final columns
    macd_out = pl.col(_macd_col).alias(out_cols[0])
    hist_out = (pl.col(_macd_col) - pl.col(out_cols[1])).alias(out_cols[2])
    pl_df = pl_df.with_columns([macd_out, hist_out])

    # Drop intermediate columns
    pl_df = pl_df.drop([_fast_col, _slow_col, _macd_col])

    return pl_df


def stoch_kd_polars(
    pl_df: "pl.DataFrame",  # type: ignore[name-defined]
    k: int = 14,
    d: int = 3,
    high_col: str = "high",
    low_col: str = "low",
    close_col: str = "close",
    out_cols: tuple | None = None,
) -> "pl.DataFrame":  # type: ignore[name-defined]
    """Stochastic %K/%D — polars-native.

    Args:
        pl_df: Single-group polars DataFrame sorted by ts.
        k: %K look-back period (default 14).
        d: %D smoothing period (default 3).
        high_col: High price column name.
        low_col: Low price column name.
        close_col: Close price column name.
        out_cols: Tuple of 2 output column names; defaults to
                  (stoch_k_{k}, stoch_d_{d}).

    Returns:
        pl_df with stoch_k and stoch_d columns appended.
    """
    if out_cols is None:
        out_cols = (f"stoch_k_{k}", f"stoch_d_{d}")

    _k_col = "__stoch_k__"

    lowest = pl.col(low_col).rolling_min(window_size=k, min_samples=k)
    highest = pl.col(high_col).rolling_max(window_size=k, min_samples=k)

    # Avoid division by zero: replace (highest - lowest) == 0 with null
    denom = pl.when(highest - lowest == 0.0).then(None).otherwise(highest - lowest)
    k_line = (pl.lit(100.0) * (pl.col(close_col) - lowest) / denom).alias(_k_col)

    pl_df = pl_df.with_columns([k_line])

    d_line = (
        pl.col(_k_col).rolling_mean(window_size=d, min_samples=d).alias(out_cols[1])
    )
    k_out = pl.col(_k_col).alias(out_cols[0])
    pl_df = pl_df.with_columns([k_out, d_line])

    pl_df = pl_df.drop([_k_col])

    return pl_df


def bollinger_polars(
    pl_df: "pl.DataFrame",  # type: ignore[name-defined]
    window: int = 20,
    price_col: str = "close",
    n_sigma: float = 2.0,
    out_cols: tuple | None = None,
) -> "pl.DataFrame":  # type: ignore[name-defined]
    """Bollinger Bands — polars-native.

    Args:
        pl_df: Single-group polars DataFrame sorted by ts.
        window: Rolling window (default 20).
        price_col: Close price column name.
        n_sigma: Band width in standard deviations (default 2.0).
        out_cols: Tuple of 4 output column names; defaults to
                  (bb_ma_{window}, bb_up_{window}_{n_sigma}, bb_lo_{window}_{n_sigma},
                   bb_width_{window}).

    Returns:
        pl_df with 4 Bollinger columns appended.
    """
    if out_cols is None:
        sigma_str = str(int(n_sigma)) if n_sigma == int(n_sigma) else str(n_sigma)
        out_cols = (
            f"bb_ma_{window}",
            f"bb_up_{window}_{sigma_str}",
            f"bb_lo_{window}_{sigma_str}",
            f"bb_width_{window}",
        )

    _ma_col = "__bb_ma__"
    _std_col = "__bb_std__"

    ma_expr = (
        pl.col(price_col)
        .rolling_mean(window_size=window, min_samples=window)
        .alias(_ma_col)
    )
    std_expr = (
        pl.col(price_col)
        .rolling_std(window_size=window, min_samples=window)
        .alias(_std_col)
    )

    pl_df = pl_df.with_columns([ma_expr, std_expr])

    upper = (pl.col(_ma_col) + pl.lit(n_sigma) * pl.col(_std_col)).alias(out_cols[1])
    lower = (pl.col(_ma_col) - pl.lit(n_sigma) * pl.col(_std_col)).alias(out_cols[2])
    pl_df = pl_df.with_columns([upper, lower])

    # bw = (upper - lower) / ma — avoid division by zero
    ma_safe = pl.when(pl.col(_ma_col) == 0.0).then(None).otherwise(pl.col(_ma_col))
    bw = ((pl.col(out_cols[1]) - pl.col(out_cols[2])) / ma_safe).alias(out_cols[3])
    ma_out = pl.col(_ma_col).alias(out_cols[0])
    pl_df = pl_df.with_columns([ma_out, bw])

    pl_df = pl_df.drop([_ma_col, _std_col])

    return pl_df


def atr_polars(
    pl_df: "pl.DataFrame",  # type: ignore[name-defined]
    period: int = 14,
    high_col: str = "high",
    low_col: str = "low",
    close_col: str = "close",
    out_col: str | None = None,
) -> "pl.DataFrame":  # type: ignore[name-defined]
    """Average True Range (simple rolling mean of TR) — polars-native.

    IMPORTANT: This matches indicators.py atr() which uses rolling().mean().
    It does NOT use EWM/Wilder smoothing.  This is distinct from vol.py
    add_atr_polars (which uses Wilder EWM for a different use case).

    Because TR at row 0 is undefined (prev_close is null), we set TR to null
    at row 0 so rolling_mean skips it — matching pandas behavior where
    np.maximum with NaN propagates NaN.

    Args:
        pl_df: Single-group polars DataFrame sorted by ts.
        period: ATR rolling window (default 14).
        high_col: High price column name.
        low_col: Low price column name.
        close_col: Close price column name.
        out_col: Output column name; defaults to ``atr_{period}``.

    Returns:
        pl_df with ``atr_{period}`` column appended.
    """
    if out_col is None:
        out_col = f"atr_{period}"

    prev_close = pl.col(close_col).shift(1)

    # TR = max(h-lo, |h-prev_close|, |lo-prev_close|)
    # Null when prev_close is null (row 0) — matches pandas np.maximum with NaN
    tr_expr = (
        pl.when(prev_close.is_null())
        .then(None)
        .otherwise(
            pl.max_horizontal(
                (pl.col(high_col) - pl.col(low_col)),
                (pl.col(high_col) - prev_close).abs(),
                (pl.col(low_col) - prev_close).abs(),
            )
        )
    )

    atr_expr = tr_expr.rolling_mean(window_size=period, min_samples=period).alias(
        out_col
    )

    return pl_df.with_columns([atr_expr])


def adx_polars(
    pl_df: "pl.DataFrame",  # type: ignore[name-defined]
    period: int = 14,
    high_col: str = "high",
    low_col: str = "low",
    close_col: str = "close",
    out_col: str | None = None,
) -> "pl.DataFrame":  # type: ignore[name-defined]
    """ADX (Average Directional Index) — polars-native.

    Uses pl.when/otherwise for conditional DM logic matching np.where in
    the pandas adx() function.  TR uses rolling_mean (not EWM).

    Args:
        pl_df: Single-group polars DataFrame sorted by ts.
        period: ADX period (default 14).
        high_col: High price column name.
        low_col: Low price column name.
        close_col: Close price column name.
        out_col: Output column name; defaults to ``adx_{period}``.

    Returns:
        pl_df with ``adx_{period}`` column appended.
    """
    if out_col is None:
        out_col = f"adx_{period}"

    # Directional movement
    up = pl.col(high_col).diff()
    dn = -(pl.col(low_col).diff())

    plus_dm = pl.when((up > dn) & (up > pl.lit(0.0))).then(up).otherwise(pl.lit(0.0))
    minus_dm = pl.when((dn > up) & (dn > pl.lit(0.0))).then(dn).otherwise(pl.lit(0.0))

    # True range (null on row 0, matching pandas np.maximum with NaN)
    prev_close = pl.col(close_col).shift(1)
    tr_expr = (
        pl.when(prev_close.is_null())
        .then(None)
        .otherwise(
            pl.max_horizontal(
                (pl.col(high_col) - pl.col(low_col)),
                (pl.col(high_col) - prev_close).abs(),
                (pl.col(low_col) - prev_close).abs(),
            )
        )
    )

    # Intermediate column names
    _tr_col = "__adx_tr__"
    _atr_col = "__adx_atr__"
    _plus_dm_col = "__adx_plus_dm__"
    _minus_dm_col = "__adx_minus_dm__"
    _plus_di_col = "__adx_plus_di__"
    _minus_di_col = "__adx_minus_di__"
    _dx_col = "__adx_dx__"

    pl_df = pl_df.with_columns(
        [
            tr_expr.alias(_tr_col),
            plus_dm.alias(_plus_dm_col),
            minus_dm.alias(_minus_dm_col),
        ]
    )

    atr_ = pl.col(_tr_col).rolling_mean(window_size=period, min_samples=period)
    pl_df = pl_df.with_columns([atr_.alias(_atr_col)])

    # +DI and -DI
    atr_safe = pl.when(pl.col(_atr_col) == 0.0).then(None).otherwise(pl.col(_atr_col))
    plus_di_expr = (
        pl.lit(100.0)
        * pl.col(_plus_dm_col).rolling_sum(window_size=period, min_samples=period)
        / atr_safe
    ).alias(_plus_di_col)
    minus_di_expr = (
        pl.lit(100.0)
        * pl.col(_minus_dm_col).rolling_sum(window_size=period, min_samples=period)
        / atr_safe
    ).alias(_minus_di_col)
    pl_df = pl_df.with_columns([plus_di_expr, minus_di_expr])

    # DX = |+DI - -DI| / (+DI + -DI) * 100
    di_sum = pl.col(_plus_di_col) + pl.col(_minus_di_col)
    di_sum_safe = pl.when(di_sum == 0.0).then(None).otherwise(di_sum)
    dx_expr = (
        (pl.col(_plus_di_col) - pl.col(_minus_di_col)).abs()
        / di_sum_safe
        * pl.lit(100.0)
    ).alias(_dx_col)
    pl_df = pl_df.with_columns([dx_expr])

    # ADX = rolling mean of DX
    adx_expr = (
        pl.col(_dx_col)
        .rolling_mean(window_size=period, min_samples=period)
        .alias(out_col)
    )
    pl_df = pl_df.with_columns([adx_expr])

    # Drop all intermediate columns
    pl_df = pl_df.drop(
        [
            _tr_col,
            _atr_col,
            _plus_dm_col,
            _minus_dm_col,
            _plus_di_col,
            _minus_di_col,
            _dx_col,
        ]
    )

    return pl_df
