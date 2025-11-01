# src/ta_lab2/features/vol.py
import numpy as np
import pandas as pd
from typing import Iterable, Literal, Sequence


# =============================================================================
# Single-bar realized volatility estimators
# =============================================================================

def add_atr(
    df: pd.DataFrame,
    period: int = 14,
    high_col: str = "high",
    low_col: str = "low",
    close_col: str = "close",
) -> pd.DataFrame:
    """
    Average True Range (Wilder EMA smoothing).
    """
    high = df[high_col].astype(float)
    low = df[low_col].astype(float)
    close = df[close_col].astype(float)
    prev_close = close.shift(1)

    tr = (high - low).abs()
    tr = np.maximum(tr, (high - prev_close).abs())
    tr = np.maximum(tr, (low - prev_close).abs())

    df[f"atr_{period}"] = tr.ewm(alpha=1 / period, adjust=False).mean()
    return df


def add_parkinson_vol(
    df: pd.DataFrame,
    high_col: str = "high",
    low_col: str = "low",
    out_col: str = "vol_parkinson",
) -> pd.DataFrame:
    """
    σ_P = sqrt( (1 / (4 * ln(2))) * (ln(H/L))^2 )
    """
    hl2 = np.log(df[high_col] / df[low_col]) ** 2
    df[out_col] = np.sqrt((1.0 / (4.0 * np.log(2.0))) * hl2)
    return df


def add_rogers_satchell_vol(
    df: pd.DataFrame,
    open_col: str = "open",
    high_col: str = "high",
    low_col: str = "low",
    close_col: str = "close",
    out_col: str = "vol_rs",
) -> pd.DataFrame:
    """
    σ_RS = sqrt( ln(H/C)ln(H/O) + ln(L/C)ln(L/O) )
    """
    term = (
        np.log(df[high_col] / df[close_col]) * np.log(df[high_col] / df[open_col])
        + np.log(df[low_col] / df[close_col]) * np.log(df[low_col] / df[open_col])
    ).clip(lower=0)
    df[out_col] = np.sqrt(term)
    return df


def add_garman_klass_vol(
    df: pd.DataFrame,
    open_col: str = "open",
    high_col: str = "high",
    low_col: str = "low",
    close_col: str = "close",
    out_col: str = "vol_gk",
) -> pd.DataFrame:
    """
    σ_GK = sqrt( 0.5(ln(H/L))^2 - (2ln2 - 1)(ln(C/O))^2 )
    """
    term1 = 0.5 * (np.log(df[high_col] / df[low_col])) ** 2
    term2 = (2 * np.log(2) - 1) * (np.log(df[close_col] / df[open_col])) ** 2
    inner = term1 - term2
    df[out_col] = np.sqrt(np.abs(inner))
    return df


# =============================================================================
# Rolling volatility from returns (log / percent / both) — batch
# =============================================================================

def add_rolling_vol_from_returns_batch(
    df: pd.DataFrame,
    *,
    close_col: str = "close",
    windows: Sequence[int] = (20, 63, 126),
    types: Literal["log", "pct", "both"] = "log",
    annualize: bool = True,
    periods_per_year: int = 252,
    ddof: int = 0,
    prefix: str = "vol",
) -> pd.DataFrame:
    """
    Compute rolling historical volatility from (log|pct) returns
    for multiple windows and (optionally) both return types.

    Adds columns:
      - f"{prefix}_log_roll_{W}" for log returns (if types includes "log")
      - f"{prefix}_pct_roll_{W}" for pct returns (if types includes "pct")
    """
    px = df[close_col].astype(float)
    r_log = np.log(px / px.shift(1))
    r_pct = px.pct_change()

    need_log = types in ("log", "both")
    need_pct = types in ("pct", "both")

    for w in windows:
        if need_log:
            vol = r_log.rolling(w, min_periods=w).std(ddof=ddof)
            if annualize:
                vol = vol * np.sqrt(periods_per_year)
            df[f"{prefix}_log_roll_{w}"] = vol

        if need_pct:
            vol = r_pct.rolling(w, min_periods=w).std(ddof=ddof)
            if annualize:
                vol = vol * np.sqrt(periods_per_year)
            df[f"{prefix}_pct_roll_{w}"] = vol

    return df


# =============================================================================
# Rolling realized volatility (Parkinson / RS / GK) — batch
# =============================================================================

def add_rolling_parkinson(
    df: pd.DataFrame,
    *,
    high_col: str = "high",
    low_col: str = "low",
    window: int = 20,
    annualize: bool = True,
    periods_per_year: int = 252,
    out_col: str | None = None,
) -> pd.DataFrame:
    if out_col is None:
        out_col = f"vol_parkinson_roll_{window}"
    hl2 = (np.log(df[high_col] / df[low_col])) ** 2
    base = (1.0 / (4.0 * np.log(2.0))) * hl2
    vol = base.rolling(window, min_periods=window).mean().pow(0.5)
    if annualize:
        vol = vol * np.sqrt(periods_per_year)
    df[out_col] = vol
    return df


def add_rolling_rogers_satchell(
    df: pd.DataFrame,
    *,
    open_col: str = "open",
    high_col: str = "high",
    low_col: str = "low",
    close_col: str = "close",
    window: int = 20,
    annualize: bool = True,
    periods_per_year: int = 252,
    out_col: str | None = None,
) -> pd.DataFrame:
    if out_col is None:
        out_col = f"vol_rs_roll_{window}"
    term = (
        np.log(df[high_col] / df[close_col]) * np.log(df[high_col] / df[open_col])
        + np.log(df[low_col] / df[close_col]) * np.log(df[low_col] / df[open_col])
    ).clip(lower=0)
    vol = term.rolling(window, min_periods=window).mean().pow(0.5)
    if annualize:
        vol = vol * np.sqrt(periods_per_year)
    df[out_col] = vol
    return df


def add_rolling_garman_klass(
    df: pd.DataFrame,
    *,
    open_col: str = "open",
    high_col: str = "high",
    low_col: str = "low",
    close_col: str = "close",
    window: int = 20,
    annualize: bool = True,
    periods_per_year: int = 252,
    out_col: str | None = None,
) -> pd.DataFrame:
    if out_col is None:
        out_col = f"vol_gk_roll_{window}"
    term1 = 0.5 * (np.log(df[high_col] / df[low_col])) ** 2
    term2 = (2 * np.log(2) - 1) * (np.log(df[close_col] / df[open_col])) ** 2
    inner = term1 - term2
    mean_inner = inner.rolling(window, min_periods=window).mean()
    vol = (mean_inner.clip(lower=0)).pow(0.5)
    if annualize:
        vol = vol * np.sqrt(periods_per_year)
    df[out_col] = vol
    return df


def add_rolling_realized_batch(
    df: pd.DataFrame,
    *,
    windows: Sequence[int] = (20, 63, 126),
    which: Iterable[Literal["parkinson", "rs", "gk"]] = ("parkinson", "rs", "gk"),
    annualize: bool = True,
    periods_per_year: int = 252,
    open_col: str = "open",
    high_col: str = "high",
    low_col: str = "low",
    close_col: str = "close",
) -> pd.DataFrame:
    """
    Batch helper for rolling realized-vol estimators across many windows.
    """
    for w in windows:
        if "parkinson" in which:
            add_rolling_parkinson(
                df, high_col=high_col, low_col=low_col,
                window=w, annualize=annualize, periods_per_year=periods_per_year,
            )
        if "rs" in which:
            add_rolling_rogers_satchell(
                df, open_col=open_col, high_col=high_col, low_col=low_col, close_col=close_col,
                window=w, annualize=annualize, periods_per_year=periods_per_year,
            )
        if "gk" in which:
            add_rolling_garman_klass(
                df, open_col=open_col, high_col=high_col, low_col=low_col, close_col=close_col,
                window=w, annualize=annualize, periods_per_year=periods_per_year,
            )
    return df


# =============================================================================
# One-call orchestrator (optional convenience)
# =============================================================================

def add_volatility_features(
    df: pd.DataFrame,
    *,
    # single-bar toggles
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
) -> pd.DataFrame:
    """
    Add single-bar and rolling volatility features in one call.
    """
    if do_parkinson:
        add_parkinson_vol(df, high_col=high_col, low_col=low_col)
    if do_rs:
        add_rogers_satchell_vol(df, open_col=open_col, high_col=high_col, low_col=low_col, close_col=close_col)
    if do_gk:
        add_garman_klass_vol(df, open_col=open_col, high_col=high_col, low_col=low_col, close_col=close_col)
    if do_atr:
        add_atr(df, period=atr_period, high_col=high_col, low_col=low_col, close_col=close_col)

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

    add_rolling_realized_batch(
        df,
        windows=rv_windows,
        which=rv_which,
        annualize=rv_annualize,
        periods_per_year=rv_periods_per_year,
        open_col=open_col, high_col=high_col, low_col=low_col, close_col=close_col,
    )

    return df
