# src/ta_lab2/regimes/labels.py
from __future__ import annotations
from typing import Optional
import numpy as np
import pandas as pd


# ---------- Core labelers (TF-agnostic) ----------
def label_trend_basic(
    df: pd.DataFrame,
    *,
    price_col: str = "close",
    ema_fast: str = "close_ema_20",
    ema_mid: str = "close_ema_50",
    ema_slow: str = "close_ema_200",
    adx_col: Optional[str] = None,
    adx_floor: float = 0.0,
    confirm_bars: int = 0,
) -> pd.Series:
    """
    Up if price>slow and fast>mid for confirm_bars; Down if inverse; else Sideways.
    If adx_col provided, require ADX > adx_floor to escape Sideways.
    """
    f = df.get(ema_fast, np.nan)
    m = df.get(ema_mid, np.nan)
    s = df.get(ema_slow, np.nan)
    px = df.get(price_col, np.nan)

    up = (px > s) & (f > m)
    dn = (px < s) & (f < m)
    if confirm_bars > 0:
        up = (
            up.rolling(confirm_bars)
            .apply(lambda x: float(np.all(x == 1.0)), raw=True)
            .astype(bool)
        )
        dn = (
            dn.rolling(confirm_bars)
            .apply(lambda x: float(np.all(x == 1.0)), raw=True)
            .astype(bool)
        )

    lab = np.where(up, "Up", np.where(dn, "Down", "Sideways"))
    if adx_col is not None and adx_col in df.columns and adx_floor > 0:
        weak = df[adx_col] <= adx_floor
        lab = np.where(weak & (lab == "Up"), "Sideways", lab)
        lab = np.where(weak & (lab == "Down"), "Sideways", lab)
    return pd.Series(lab, index=df.index, name="trend")


def _percentile_series(x: pd.Series) -> pd.Series:
    # Rolling rank percentile of latest value within window
    # Avoids scipy; simple and robust.
    return x.rolling(len(x)).apply(
        lambda w: (pd.Series(w).rank().iloc[-1] / max(len(w), 1)) * 100, raw=False
    )


def label_vol_bucket(
    df: pd.DataFrame,
    *,
    atr_col: Optional[str] = None,
    price_col: str = "close",
    window: int = 100,
    mode: str = "full",  # "full" uses percentiles, "lite" uses fixed cutoffs
    low_cutoff: float = 0.015,  # ~1.5% ATR% fallback
    high_cutoff: float = 0.04,  # ~4.0% ATR% fallback
) -> pd.Series:
    if atr_col and atr_col in df.columns:
        atrp = df[atr_col] / df[price_col]
    else:
        # ATR% unavailable; fallback to close-to-close absolute return as proxy
        atrp = df[price_col].pct_change().abs().rolling(14).mean()

    if mode == "full" and len(df) >= window:
        pct = atrp.rolling(window, min_periods=max(20, window // 3)).apply(
            lambda w: (pd.Series(w).rank().iloc[-1] / max(len(w), 1)) * 100, raw=False
        )
        lab = np.where(pct < 33, "Low", np.where(pct < 67, "Normal", "High"))
    else:
        lab = np.where(
            atrp < low_cutoff, "Low", np.where(atrp > high_cutoff, "High", "Normal")
        )
    return pd.Series(lab, index=df.index, name="vol")


def label_liquidity_bucket(
    df: pd.DataFrame,
    *,
    spread_col: Optional[str] = None,
    slip_col: Optional[str] = None,
    window: int = 60,
) -> pd.Series:
    """
    If spread/slippage columns exist, compare to rolling medians.
    Otherwise default to 'Normal'.
    """
    if spread_col in df.columns and slip_col in df.columns:
        spr = df[spread_col]
        slp = df[slip_col]
        spr_med = spr.rolling(window, min_periods=max(10, window // 3)).median()
        slp_med = slp.rolling(window, min_periods=max(10, window // 3)).median()
        stressed = (spr > 2.0 * spr_med) | (slp > 2.0 * slp_med)
        easy = (spr < 0.8 * spr_med) & (slp < 0.8 * slp_med)
        lab = np.where(easy, "Easy", np.where(stressed, "Stressed", "Normal"))
    else:
        lab = np.full(len(df), "Normal", dtype=object)
    return pd.Series(lab, index=df.index, name="liq")


def compose_regime_key(trend: str, vol: str, liq: str) -> str:
    return f"{trend}-{vol}-{liq}"


# ---------- Layer wrappers (L0..L3) ----------
def label_layer_monthly(
    monthly: pd.DataFrame,
    *,
    mode: str = "full",
    price_col: str = "close",
    ema_fast: str = "close_ema_12",
    ema_mid: str = "close_ema_24",
    ema_slow: str = "close_ema_48",
) -> pd.Series:
    trend = label_trend_basic(
        monthly,
        price_col=price_col,
        ema_fast=ema_fast,
        ema_mid=ema_mid,
        ema_slow=ema_slow,
        confirm_bars=2,
    )
    vol = label_vol_bucket(
        monthly, price_col=price_col, window=60 if mode == "full" else 30, mode=mode
    )
    liq = label_liquidity_bucket(monthly)
    return pd.Series(
        [compose_regime_key(t, v, l) for t, v, l in zip(trend, vol, liq)],
        index=monthly.index,
        name="L0",
    )


def label_layer_weekly(
    weekly: pd.DataFrame,
    *,
    mode: str = "full",
    price_col: str = "close",
    ema_fast: str = "close_ema_20",
    ema_mid: str = "close_ema_50",
    ema_slow: str = "close_ema_200",
) -> pd.Series:
    trend = label_trend_basic(
        weekly,
        price_col=price_col,
        ema_fast=ema_fast,
        ema_mid=ema_mid,
        ema_slow=ema_slow,
        confirm_bars=2,
    )
    vol = label_vol_bucket(
        weekly, price_col=price_col, window=100 if mode == "full" else 50, mode=mode
    )
    liq = label_liquidity_bucket(weekly)
    return pd.Series(
        [compose_regime_key(t, v, l) for t, v, l in zip(trend, vol, liq)],
        index=weekly.index,
        name="L1",
    )


def label_layer_daily(
    daily: pd.DataFrame,
    *,
    mode: str = "full",
    price_col: str = "close",
    ema_fast: str = "close_ema_20",
    ema_mid: str = "close_ema_50",
    ema_slow: str = "close_ema_100",
) -> pd.Series:
    trend = label_trend_basic(
        daily,
        price_col=price_col,
        ema_fast=ema_fast,
        ema_mid=ema_mid,
        ema_slow=ema_slow,
        confirm_bars=2,
    )
    vol = label_vol_bucket(
        daily, price_col=price_col, window=250 if mode == "full" else 100, mode=mode
    )
    liq = label_liquidity_bucket(daily)
    return pd.Series(
        [compose_regime_key(t, v, l) for t, v, l in zip(trend, vol, liq)],
        index=daily.index,
        name="L2",
    )


def label_layer_intraday(
    intraday: pd.DataFrame,
    *,
    price_col: str = "close",
    ema_fast: str = "close_ema_34",
    ema_mid: str = "close_ema_55",
    ema_slow: str = "close_ema_89",
) -> pd.Series:
    # Intraday often runs "lite" style: short confirm and simple vol proxy
    trend = label_trend_basic(
        intraday,
        price_col=price_col,
        ema_fast=ema_fast,
        ema_mid=ema_mid,
        ema_slow=ema_slow,
        confirm_bars=1,
    )
    vol = label_vol_bucket(intraday, price_col=price_col, window=300, mode="lite")
    liq = label_liquidity_bucket(intraday)
    return pd.Series(
        [compose_regime_key(t, v, l) for t, v, l in zip(trend, vol, liq)],
        index=intraday.index,
        name="L3",
    )
