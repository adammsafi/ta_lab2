"""
Derivatives-market indicator functions for crypto-native signals.

Computes 8 indicator functions that capture OI dynamics, funding sentiment,
and liquidation pressure -- signals unavailable in traditional TA.

All functions follow the indicators.py API convention:
  indicator(df, window/params, *, col_args, out_col=None, inplace=False)
  -> pd.Series (inplace=False) | pd.DataFrame (inplace=True)

Requires columns from DerivativesFrame (derivatives_input.py):
  oi, funding_rate, volume, close

Cross-asset indicators (oi_concentration_ratio) require the full multi-asset
DataFrame -- do NOT pass per-asset slices.

Note: ASCII-only comments throughout (Windows cp1252 compatibility).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ta_lab2.features.indicators import _ema

__all__ = [
    "oi_momentum",
    "oi_price_divergence",
    "funding_zscore",
    "funding_momentum",
    "vol_oi_regime",
    "force_index_deriv",
    "oi_concentration_ratio",
    "liquidation_pressure",
]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _return(obj, series: pd.Series, out_col: str, *, inplace: bool):
    """Mirror of indicators._return: inplace assigns column, else returns Series."""
    series = series.rename(out_col)
    if inplace and isinstance(obj, pd.DataFrame):
        obj[out_col] = series
        return obj
    return series


def _rolling_zscore(s: pd.Series, window: int) -> pd.Series:
    """Rolling z-score with min_periods=window."""
    mu = s.rolling(window, min_periods=window).mean()
    sd = s.rolling(window, min_periods=window).std(ddof=1)
    return (s - mu) / sd.replace(0.0, np.nan)


# ---------------------------------------------------------------------------
# 1. OI Momentum
# ---------------------------------------------------------------------------


def oi_momentum(
    df: pd.DataFrame,
    window: int = 14,
    *,
    oi_col: str = "oi",
    out_col: str | None = None,
    inplace: bool = False,
):
    """
    Percentage change of open interest over *window* bars.

    Formula: df[oi_col].pct_change(window)

    Args:
        df:      DataFrame containing oi_col.
        window:  Look-back period (default 14).
        oi_col:  Column name for open interest (default 'oi').
        out_col: Output column name (default f"oi_mom_{window}").
        inplace: If True, assign column to df and return df.

    Returns:
        pd.Series (inplace=False) or pd.DataFrame (inplace=True).
    """
    if out_col is None:
        out_col = f"oi_mom_{window}"

    if df.empty:
        result = pd.Series(dtype=float, name=out_col)
        if inplace:
            df[out_col] = result
            return df
        return result

    result = df[oi_col].pct_change(window, fill_method=None)
    return _return(df, result, out_col, inplace=inplace)


# ---------------------------------------------------------------------------
# 2. OI-Price Divergence (rolling z-score)
# ---------------------------------------------------------------------------


def oi_price_divergence(
    df: pd.DataFrame,
    window: int = 20,
    *,
    oi_col: str = "oi",
    close_col: str = "close",
    out_col: str | None = None,
    inplace: bool = False,
):
    """
    Z-score of the spread between single-bar OI change and price change.

    Formula:
      oi_change  = df[oi_col].pct_change(1)
      px_change  = df[close_col].pct_change(1)
      divergence = oi_change - px_change
      result     = rolling z-score of divergence over *window*

    Args:
        df:        DataFrame with oi_col and close_col.
        window:    Rolling window for z-score (default 20).
        oi_col:    Open interest column (default 'oi').
        close_col: Close price column (default 'close').
        out_col:   Output column name (default 'oi_price_div_z').
        inplace:   If True, assign column to df and return df.

    Returns:
        pd.Series or pd.DataFrame.
    """
    if out_col is None:
        out_col = "oi_price_div_z"

    if df.empty:
        result = pd.Series(dtype=float, name=out_col)
        if inplace:
            df[out_col] = result
            return df
        return result

    oi_change = df[oi_col].pct_change(1, fill_method=None)
    px_change = df[close_col].pct_change(1, fill_method=None)
    divergence = oi_change - px_change
    result = _rolling_zscore(divergence, window)
    return _return(df, result, out_col, inplace=inplace)


# ---------------------------------------------------------------------------
# 3. Funding Rate Z-Score
# ---------------------------------------------------------------------------


def funding_zscore(
    df: pd.DataFrame,
    window: int = 14,
    *,
    funding_col: str = "funding_rate",
    out_col: str | None = None,
    inplace: bool = False,
):
    """
    Rolling z-score of the funding rate.

    Formula: (funding - rolling_mean) / rolling_std over *window*

    Args:
        df:          DataFrame with funding_col.
        window:      Rolling window (default 14).
        funding_col: Funding rate column (default 'funding_rate').
        out_col:     Output column name (default f"funding_z_{window}").
        inplace:     If True, assign column to df and return df.

    Returns:
        pd.Series or pd.DataFrame.
    """
    if out_col is None:
        out_col = f"funding_z_{window}"

    if df.empty:
        result = pd.Series(dtype=float, name=out_col)
        if inplace:
            df[out_col] = result
            return df
        return result

    result = _rolling_zscore(df[funding_col], window)
    return _return(df, result, out_col, inplace=inplace)


# ---------------------------------------------------------------------------
# 4. Funding Momentum
# ---------------------------------------------------------------------------


def funding_momentum(
    df: pd.DataFrame,
    window: int = 14,
    *,
    funding_col: str = "funding_rate",
    out_col: str | None = None,
    inplace: bool = False,
):
    """
    Rate-of-change of funding z-score over *window* bars.

    Formula: funding_zscore(df, window).diff(window)

    Args:
        df:          DataFrame with funding_col.
        window:      Window for both z-score and diff (default 14).
        funding_col: Funding rate column (default 'funding_rate').
        out_col:     Output column name (default f"funding_mom_{window}").
        inplace:     If True, assign column to df and return df.

    Returns:
        pd.Series or pd.DataFrame.
    """
    if out_col is None:
        out_col = f"funding_mom_{window}"

    if df.empty:
        result = pd.Series(dtype=float, name=out_col)
        if inplace:
            df[out_col] = result
            return df
        return result

    fz = funding_zscore(df, window, funding_col=funding_col)
    result = fz.diff(window)
    return _return(df, result, out_col, inplace=inplace)


# ---------------------------------------------------------------------------
# 5. Volume-OI Regime (INTEGER 1-6)
# ---------------------------------------------------------------------------

# Regime classification based on Kaufman 4-quadrant matrix x price direction:
#
#   Regime 1: OI up, Vol up, Price up   -- accumulation / strong trend
#   Regime 2: OI up, Vol up, Price dn   -- distribution / reversal candidate
#   Regime 3: OI dn, Vol up, Price up   -- short covering / relief rally
#   Regime 4: OI dn, Vol up, Price dn   -- panic selling / capitulation
#   Regime 5: OI up, Vol dn, any price  -- positioning without conviction
#   Regime 6: OI dn, Vol dn, any price  -- low-activity consolidation
#
# Regimes 5 and 6 are independent of price direction (volume governs).

_VOL_OI_REGIMES = {
    1: "accumulation",
    2: "distribution",
    3: "short_covering",
    4: "capitulation",
    5: "positioning_low_vol",
    6: "consolidation",
}


def vol_oi_regime(
    df: pd.DataFrame,
    *,
    oi_col: str = "oi",
    volume_col: str = "volume",
    close_col: str = "close",
    out_col: str | None = None,
    inplace: bool = False,
):
    """
    Classify bars into one of 6 volume-OI-price regimes.

    Returns INTEGER values 1-6 (not float). Uses np.select.
    No window parameter -- instantaneous 1-bar direction classification.

    Args:
        df:         DataFrame with oi_col, volume_col, close_col.
        oi_col:     Open interest column (default 'oi').
        volume_col: Volume column (default 'volume').
        close_col:  Close price column (default 'close').
        out_col:    Output column name (default 'vol_oi_regime').
        inplace:    If True, assign column to df and return df.

    Returns:
        pd.Series[int] or pd.DataFrame.
    """
    if out_col is None:
        out_col = "vol_oi_regime"

    if df.empty:
        result = pd.Series(dtype="Int64", name=out_col)
        if inplace:
            df[out_col] = result
            return df
        return result

    oi_dir = np.sign(df[oi_col].diff(1))
    vol_dir = np.sign(df[volume_col].diff(1))
    px_dir = np.sign(df[close_col].diff(1))

    conditions = [
        (oi_dir > 0) & (vol_dir > 0) & (px_dir > 0),  # 1: accumulation
        (oi_dir > 0) & (vol_dir > 0) & (px_dir <= 0),  # 2: distribution
        (oi_dir <= 0) & (vol_dir > 0) & (px_dir > 0),  # 3: short covering
        (oi_dir <= 0) & (vol_dir > 0) & (px_dir <= 0),  # 4: capitulation
        (oi_dir > 0) & (vol_dir <= 0),  # 5: positioning low vol
        (oi_dir <= 0) & (vol_dir <= 0),  # 6: consolidation
    ]
    choices = [1, 2, 3, 4, 5, 6]

    # default=0 for the first bar (diff produces NaN -> sign produces NaN).
    raw = np.select(conditions, choices, default=0)
    # Convert 0 to NaN so first bar is null (consistent with warmup convention).
    result = pd.array(np.where(raw == 0, pd.NA, raw), dtype="Int64")
    result_series = pd.Series(result, index=df.index, name=out_col)
    return _return(df, result_series, out_col, inplace=inplace)


# ---------------------------------------------------------------------------
# 6. Force Index Derivatives (OI-weighted)
# ---------------------------------------------------------------------------


def force_index_deriv(
    df: pd.DataFrame,
    span: int = 13,
    *,
    oi_col: str = "oi",
    volume_col: str = "volume",
    close_col: str = "close",
    out_col: str | None = None,
    inplace: bool = False,
):
    """
    OI-weighted Force Index, smoothed via EMA.

    Adapted from Elder's Force Index with OI as conviction multiplier:
      raw_force = close.diff(1) * volume * (oi / oi.rolling(span).mean())
      result    = _ema(raw_force, span)

    Uses _ema() from indicators.py (not hand-rolled EWM).

    Args:
        df:         DataFrame with oi_col, volume_col, close_col.
        span:       EMA span and OI normalisation window (default 13).
        oi_col:     Open interest column (default 'oi').
        volume_col: Volume column (default 'volume').
        close_col:  Close price column (default 'close').
        out_col:    Output column name (default f"force_idx_deriv_{span}").
        inplace:    If True, assign column to df and return df.

    Returns:
        pd.Series or pd.DataFrame.
    """
    if out_col is None:
        out_col = f"force_idx_deriv_{span}"

    if df.empty:
        result = pd.Series(dtype=float, name=out_col)
        if inplace:
            df[out_col] = result
            return df
        return result

    close = df[close_col].astype(float)
    volume = df[volume_col].astype(float)
    oi = df[oi_col].astype(float)

    oi_mean = oi.rolling(span, min_periods=1).mean()
    oi_ratio = oi / oi_mean.replace(0.0, np.nan)

    raw_force = close.diff(1) * volume * oi_ratio
    result = _ema(raw_force, span)
    return _return(df, result, out_col, inplace=inplace)


# ---------------------------------------------------------------------------
# 7. OI Concentration Ratio (cross-asset)
# ---------------------------------------------------------------------------


def oi_concentration_ratio(
    df: pd.DataFrame,
    window: int = 30,
    *,
    oi_col: str = "oi",
    id_col: str = "id",
    ts_col: str = "ts",
    out_col: str | None = None,
    inplace: bool = False,
):
    """
    Cross-asset OI concentration: asset share of total OI, z-scored per asset.

    IMPORTANT: Pass the full multi-asset DataFrame, not per-asset slices.
    The cross-asset total_oi is computed via groupby(ts)[oi].transform('sum').

    Formula:
      total_oi = groupby(ts)[oi].transform('sum')
      ratio    = oi / total_oi           (division by zero -> NaN)
      z        = per-asset rolling z-score of ratio over *window*

    Args:
        df:     Full multi-asset DataFrame with id_col, ts_col, oi_col.
        window: Rolling window for z-score (default 30).
        oi_col: Open interest column (default 'oi').
        id_col: Asset id column (default 'id').
        ts_col: Timestamp column (default 'ts').
        out_col: Output column name (default 'oi_conc_ratio').
        inplace: If True, assign column to df and return df.

    Returns:
        pd.Series or pd.DataFrame.
    """
    if out_col is None:
        out_col = "oi_conc_ratio"

    if df.empty:
        result = pd.Series(dtype=float, name=out_col)
        if inplace:
            df[out_col] = result
            return df
        return result

    oi = df[oi_col].astype(float)
    total_oi = df.groupby(ts_col)[oi_col].transform("sum").astype(float)
    ratio = oi / total_oi.replace(0.0, np.nan)

    # Per-asset rolling z-score.
    def _per_asset_zscore(group: pd.Series) -> pd.Series:
        mu = group.rolling(window, min_periods=window).mean()
        sd = group.rolling(window, min_periods=window).std(ddof=1)
        return (group - mu) / sd.replace(0.0, np.nan)

    result = ratio.groupby(df[id_col]).transform(_per_asset_zscore)
    return _return(df, result, out_col, inplace=inplace)


# ---------------------------------------------------------------------------
# 8. Liquidation Pressure (composite)
# ---------------------------------------------------------------------------


def liquidation_pressure(
    df: pd.DataFrame,
    *,
    funding_z_col: str = "funding_z_14",
    oi_mom_col: str = "oi_mom_14",
    div_z_col: str = "oi_price_div_z",
    out_col: str | None = None,
    inplace: bool = False,
):
    """
    Composite liquidation pressure indicator.

    Requires funding_zscore, oi_momentum, and oi_price_divergence columns
    to be present in *df* before calling this function.

    Formula:
      |funding_z| * 0.4 + |oi_mom| * 0.3 + |oi_price_div_z| * 0.3

    Args:
        df:            DataFrame with funding_z_col, oi_mom_col, div_z_col.
        funding_z_col: Funding z-score column (default 'funding_z_14').
        oi_mom_col:    OI momentum column (default 'oi_mom_14').
        div_z_col:     OI-price divergence z-score column (default 'oi_price_div_z').
        out_col:       Output column name (default 'liq_pressure').
        inplace:       If True, assign column to df and return df.

    Returns:
        pd.Series or pd.DataFrame.
    """
    if out_col is None:
        out_col = "liq_pressure"

    if df.empty:
        result = pd.Series(dtype=float, name=out_col)
        if inplace:
            df[out_col] = result
            return df
        return result

    fz = (
        df[funding_z_col].astype(float).abs()
        if funding_z_col in df.columns
        else pd.Series(0.0, index=df.index)
    )
    om = (
        df[oi_mom_col].astype(float).abs()
        if oi_mom_col in df.columns
        else pd.Series(0.0, index=df.index)
    )
    dz = (
        df[div_z_col].astype(float).abs()
        if div_z_col in df.columns
        else pd.Series(0.0, index=df.index)
    )

    result = fz * 0.4 + om * 0.3 + dz * 0.3
    return _return(df, result, out_col, inplace=inplace)
