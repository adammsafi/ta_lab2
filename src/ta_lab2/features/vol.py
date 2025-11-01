from __future__ import annotations
import numpy as np
import pandas as pd
from typing import Sequence, Iterable, Literal

# =========================================================
# ---- Core Volatility Estimators (single-bar + rolling) ---
# =========================================================

def add_parkinson_vol(
    df: pd.DataFrame,
    high_col: str = "high",
    low_col: str = "low",
    windows: Sequence[int] = (20, 63, 126),
    annualize: bool = True,
    periods_per_year: int = 252,
) -> pd.DataFrame:
    """Parkinson (1980) range-based volatility estimator."""
    high, low = df[high_col].astype(float), df[low_col].astype(float)
    coef = 1.0 / (4.0 * np.log(2.0))
    hl = (np.log(high / low)) ** 2
    for w in windows:
        vol = np.sqrt(coef * hl.rolling(w, min_periods=w).mean())
        if annualize:
            vol *= np.sqrt(periods_per_year)
        df[f"vol_parkinson_{w}"] = vol
    return df


def add_garman_klass_vol(
    df: pd.DataFrame,
    open_col: str = "open",
    high_col: str = "high",
    low_col: str = "low",
    close_col: str = "close",
    windows: Sequence[int] = (20, 63, 126),
    annualize: bool = True,
    periods_per_year: int = 252,
) -> pd.DataFrame:
    """Garman–Klass (1980) volatility estimator."""
    o, h, l, c = [df[k].astype(float) for k in (open_col, high_col, low_col, close_col)]
    rs = 0.5 * (np.log(h/l))**2 - (2*np.log(2)-1) * (np.log(c/o))**2
    for w in windows:
        vol = np.sqrt(rs.rolling(w, min_periods=w).mean())
        if annualize:
            vol *= np.sqrt(periods_per_year)
        df[f"vol_gk_{w}"] = vol
    return df


def add_rogers_satchell_vol(
    df: pd.DataFrame,
    open_col: str = "open",
    high_col: str = "high",
    low_col: str = "low",
    close_col: str = "close",
    windows: Sequence[int] = (20, 63, 126),
    annualize: bool = True,
    periods_per_year: int = 252,
) -> pd.DataFrame:
    """Rogers–Satchell (1991) volatility estimator."""
    o, h, l, c = [df[k].astype(float) for k in (open_col, high_col, low_col, close_col)]
    rs = (np.log(h/c) * np.log(h/o) + np.log(l/c) * np.log(l/o))
    for w in windows:
        vol = np.sqrt(rs.rolling(w, min_periods=w).mean())
        if annualize:
            vol *= np.sqrt(periods_per_year)
        df[f"vol_rs_{w}"] = vol
    return df


def add_atr(
    df: pd.DataFrame,
    period: int = 14,
    open_col: str = "open",
    high_col: str = "high",
    low_col: str = "low",
    close_col: str = "close",
) -> pd.DataFrame:
    """Average True Range (Wilder)."""
    h, l, c = df[high_col].astype(float), df[low_col].astype(float), df[close_col].astype(float)
    prev_close = c.shift(1)
    tr = (h - l).abs()
    tr = np.maximum(tr, (h - prev_close).abs())
    tr = np.maximum(tr, (l - prev_close).abs())
    df[f"atr_{period}"] = tr.ewm(alpha=1/period, adjust=False).mean()
    return df


def add_logret_stdev_vol(
    df: pd.DataFrame,
    logret_cols: Sequence[str] = ("close_log_delta",),
    windows: Sequence[int] = (20, 63, 126),
    annualize: bool = True,
    periods_per_year: int = 252,
    ddof: int = 0,
    prefix: str = "vol",
) -> pd.DataFrame:
    """Rolling std of log returns."""
    for name in logret_cols:
        if name not in df.columns:
            continue
        r = df[name].astype(float)
        for w in windows:
            vol = r.rolling(w, min_periods=w).std(ddof=ddof)
            if annualize:
                vol *= np.sqrt(periods_per_year)
            df[f"{prefix}_{name}_stdev_{w}"] = vol
    return df


def add_rolling_realized_batch(
    df: pd.DataFrame,
    windows: Sequence[int] = (20, 63, 126),
    which: Iterable[Literal["parkinson", "rs", "gk"]] = ("parkinson", "rs", "gk"),
    annualize: bool = True,
    periods_per_year: int = 252,
    open_col: str = "open",
    high_col: str = "high",
    low_col: str = "low",
    close_col: str = "close",
) -> pd.DataFrame:
    """Compute realized vol (Parkinson, RS, GK) across windows."""
    if "parkinson" in which:
        add_parkinson_vol(df, high_col=high_col, low_col=low_col, windows=windows,
                          annualize=annualize, periods_per_year=periods_per_year)
    if "rs" in which:
        add_rogers_satchell_vol(df, open_col=open_col, high_col=high_col, low_col=low_col, close_col=close_col,
                                windows=windows, annualize=annualize, periods_per_year=periods_per_year)
    if "gk" in which:
        add_garman_klass_vol(df, open_col=open_col, high_col=high_col, low_col=low_col, close_col=close_col,
                             windows=windows, annualize=annualize, periods_per_year=periods_per_year)
    return df


# =========================================================
# -------------- Compatibility Shims ----------------------
# =========================================================

def add_rolling_vol_from_returns_batch(
    df: pd.DataFrame,
    *,
    # New API
    close_col: str = "close",
    windows: Sequence[int] = (20, 63, 126),
    types: Literal["log", "pct", "both"] = "log",
    annualize: bool = True,
    periods_per_year: int = 252,
    ddof: int = 0,
    prefix: str = "vol",
    # Legacy API
    price_col: str | None = None,
    modes: Iterable[str] | None = None,
    direction: str | None = None,
) -> pd.DataFrame:
    """Rolling historical volatility (new + legacy API)."""
    # --- Backward compat mapping ---
    if price_col is not None:
        close_col = price_col
    if modes is not None:
        modes = tuple(str(m).lower() for m in modes)
        if "log" in modes and "pct" in modes:
            types = "both"
        elif "pct" in modes:
            types = "pct"
        else:
            types = "log"

    px = df[close_col].astype(float)
    r_log = np.log(px / px.shift(1))
    r_pct = px.pct_change()

    if types in ("log", "both"):
        for w in windows:
            vol = r_log.rolling(w, min_periods=w).std(ddof=ddof)
            if annualize:
                vol *= np.sqrt(periods_per_year)
            df[f"{prefix}_log_roll_{w}"] = vol

    if types in ("pct", "both"):
        for w in windows:
            vol = r_pct.rolling(w, min_periods=w).std(ddof=ddof)
            if annualize:
                vol *= np.sqrt(periods_per_year)
            df[f"{prefix}_pct_roll_{w}"] = vol

    return df


def add_volatility_features(
    df: pd.DataFrame,
    *,
    # single-bar
    do_atr: bool = True,
    do_parkinson: bool = True,
    do_rs: bool = True,
    do_gk: bool = True,
    atr_period: int = 14,
    # rolling returns vol
    ret_windows: Sequence[int] = (20, 63, 126),
    ret_types: Literal["log", "pct", "both"] = "both",
    ret_annualize: bool = True,
    ret_periods_per_year: int = 252,
    ret_ddof: int = 0,
    ret_prefix: str = "vol",
    # rolling realized vol
    rv_windows: Sequence[int] = (20, 63, 126),
    rv_which: Iterable[Literal["parkinson", "rs", "gk"]] = ("parkinson", "rs", "gk"),
    rv_annualize: bool = True,
    rv_periods_per_year: int = 252,
    # column names
    open_col: str = "open",
    high_col: str = "high",
    low_col: str = "low",
    close_col: str = "close",
    # Legacy API
    rolling_windows: Sequence[int] | None = None,
    direction: str | None = None,
) -> pd.DataFrame:
    """Unified volatility orchestrator with legacy support."""
    # ---- Backward compatibility ----
    if rolling_windows is not None:
        ret_windows = tuple(rolling_windows)
        rv_windows = tuple(rolling_windows)
    # (direction accepted but unused; kept for API continuity)

    # ---- Single-bar ----
    if do_parkinson:
        add_parkinson_vol(df, high_col=high_col, low_col=low_col, windows=(1,))
    if do_rs:
        add_rogers_satchell_vol(df, open_col=open_col, high_col=high_col, low_col=low_col,
                                close_col=close_col, windows=(1,))
    if do_gk:
        add_garman_klass_vol(df, open_col=open_col, high_col=high_col, low_col=low_col,
                             close_col=close_col, windows=(1,))
    if do_atr:
        add_atr(df, period=atr_period, high_col=high_col, low_col=low_col, close_col=close_col)

    # ---- Rolling from returns ----
    add_rolling_vol_from_returns_batch(
        df,
        close_col=close_col,
        windows=ret_windows,
        types=ret_types,
        annualize=ret_annualize,
        periods_per_year=ret_periods_per_year,
        ddof=ret_ddof,
        prefix=ret_prefix,
    )

    # ---- Rolling realized batch ----
    add_rolling_realized_batch(
        df,
        windows=rv_windows,
        which=rv_which,
        annualize=rv_annualize,
        periods_per_year=rv_periods_per_year,
        open_col=open_col,
        high_col=high_col,
        low_col=low_col,
        close_col=close_col,
    )

    return df
