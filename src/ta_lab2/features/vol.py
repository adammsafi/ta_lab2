from __future__ import annotations
import numpy as np
import pandas as pd
from typing import Sequence, Iterable, Literal

try:
    import polars as pl

    HAVE_POLARS = True
except ImportError:  # pragma: no cover
    pl = None  # type: ignore[assignment]
    HAVE_POLARS = False

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
    o, h, lo, c = [
        df[k].astype(float) for k in (open_col, high_col, low_col, close_col)
    ]
    rs = 0.5 * (np.log(h / lo)) ** 2 - (2 * np.log(2) - 1) * (np.log(c / o)) ** 2
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
    o, h, lo, c = [
        df[k].astype(float) for k in (open_col, high_col, low_col, close_col)
    ]
    rs = np.log(h / c) * np.log(h / o) + np.log(lo / c) * np.log(lo / o)
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
    h, lo, c = (
        df[high_col].astype(float),
        df[low_col].astype(float),
        df[close_col].astype(float),
    )
    prev_close = c.shift(1)
    tr = (h - lo).abs()
    tr = np.maximum(tr, (h - prev_close).abs())
    tr = np.maximum(tr, (lo - prev_close).abs())
    df[f"atr_{period}"] = tr.ewm(alpha=1 / period, adjust=False).mean()
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
        add_parkinson_vol(
            df,
            high_col=high_col,
            low_col=low_col,
            windows=windows,
            annualize=annualize,
            periods_per_year=periods_per_year,
        )
    if "rs" in which:
        add_rogers_satchell_vol(
            df,
            open_col=open_col,
            high_col=high_col,
            low_col=low_col,
            close_col=close_col,
            windows=windows,
            annualize=annualize,
            periods_per_year=periods_per_year,
        )
    if "gk" in which:
        add_garman_klass_vol(
            df,
            open_col=open_col,
            high_col=high_col,
            low_col=low_col,
            close_col=close_col,
            windows=windows,
            annualize=annualize,
            periods_per_year=periods_per_year,
        )
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
    returns_col: str | None = None,
    # Legacy API
    price_col: str | None = None,
    modes: Iterable[str] | None = None,
    direction: str | None = None,
) -> pd.DataFrame:
    """Rolling historical volatility (new + legacy API).

    If ``returns_col`` is provided and that column exists in *df*, use it
    directly as log returns instead of recomputing from ``close_col``.
    """
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

    # Use pre-computed log returns when available
    if returns_col and returns_col in df.columns:
        r_log = df[returns_col].astype(float)
    else:
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
        add_rogers_satchell_vol(
            df,
            open_col=open_col,
            high_col=high_col,
            low_col=low_col,
            close_col=close_col,
            windows=(1,),
        )
    if do_gk:
        add_garman_klass_vol(
            df,
            open_col=open_col,
            high_col=high_col,
            low_col=low_col,
            close_col=close_col,
            windows=(1,),
        )
    if do_atr:
        add_atr(
            df,
            period=atr_period,
            high_col=high_col,
            low_col=low_col,
            close_col=close_col,
        )

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


# =========================================================
# === Polars Variants =====================================
# =========================================================
# All functions below operate on a single-group pl.DataFrame
# (already sorted by ts) and return a pl.DataFrame with new
# columns appended.  Each function is a pure-polars equivalent
# of its pandas counterpart above.


def add_parkinson_vol_polars(
    lf: "pl.DataFrame",  # type: ignore[name-defined]
    high_col: str = "high",
    low_col: str = "low",
    windows: Sequence[int] = (20, 63, 126),
    annualize: bool = True,
    periods_per_year: int = 252,
) -> "pl.DataFrame":  # type: ignore[name-defined]
    """Parkinson (1980) range-based volatility — polars-native.

    Output column names match pandas: ``vol_parkinson_{w}``.

    Args:
        lf: Single-group polars DataFrame sorted by ts.
        high_col: High price column name.
        low_col: Low price column name.
        windows: Rolling windows (bars).
        annualize: Annualize the result.
        periods_per_year: Annualization factor.

    Returns:
        lf with ``vol_parkinson_{w}`` columns appended.
    """
    coef = 1.0 / (4.0 * np.log(2.0))
    ann_factor = np.sqrt(periods_per_year) if annualize else 1.0

    # hl_sq = ln(h/lo)^2
    hl_sq = (pl.col(high_col) / pl.col(low_col)).log(base=np.e).pow(2).mul(coef)

    new_cols = []
    for w in windows:
        expr = (
            hl_sq.rolling_mean(window_size=w, min_samples=w)
            .sqrt()
            .mul(ann_factor)
            .alias(f"vol_parkinson_{w}")
        )
        new_cols.append(expr)

    return lf.with_columns(new_cols)


def add_garman_klass_vol_polars(
    lf: "pl.DataFrame",  # type: ignore[name-defined]
    open_col: str = "open",
    high_col: str = "high",
    low_col: str = "low",
    close_col: str = "close",
    windows: Sequence[int] = (20, 63, 126),
    annualize: bool = True,
    periods_per_year: int = 252,
) -> "pl.DataFrame":  # type: ignore[name-defined]
    """Garman–Klass (1980) volatility estimator — polars-native.

    Output column names: ``vol_gk_{w}``.

    Args:
        lf: Single-group polars DataFrame sorted by ts.
        open_col: Open price column name.
        high_col: High price column name.
        low_col: Low price column name.
        close_col: Close price column name.
        windows: Rolling windows (bars).
        annualize: Annualize the result.
        periods_per_year: Annualization factor.

    Returns:
        lf with ``vol_gk_{w}`` columns appended.
    """
    coef_gk = 2.0 * np.log(2.0) - 1.0
    ann_factor = np.sqrt(periods_per_year) if annualize else 1.0

    # rs = 0.5 * ln(h/lo)^2 - (2*ln(2)-1) * ln(c/o)^2
    rs_expr = pl.lit(0.5) * (pl.col(high_col) / pl.col(low_col)).log(base=np.e).pow(
        2
    ) - pl.lit(coef_gk) * (pl.col(close_col) / pl.col(open_col)).log(base=np.e).pow(2)

    new_cols = []
    for w in windows:
        expr = (
            rs_expr.rolling_mean(window_size=w, min_samples=w)
            .sqrt()
            .mul(ann_factor)
            .alias(f"vol_gk_{w}")
        )
        new_cols.append(expr)

    return lf.with_columns(new_cols)


def add_rogers_satchell_vol_polars(
    lf: "pl.DataFrame",  # type: ignore[name-defined]
    open_col: str = "open",
    high_col: str = "high",
    low_col: str = "low",
    close_col: str = "close",
    windows: Sequence[int] = (20, 63, 126),
    annualize: bool = True,
    periods_per_year: int = 252,
) -> "pl.DataFrame":  # type: ignore[name-defined]
    """Rogers–Satchell (1991) volatility estimator — polars-native.

    Output column names: ``vol_rs_{w}``.

    Args:
        lf: Single-group polars DataFrame sorted by ts.
        open_col: Open price column name.
        high_col: High price column name.
        low_col: Low price column name.
        close_col: Close price column name.
        windows: Rolling windows (bars).
        annualize: Annualize the result.
        periods_per_year: Annualization factor.

    Returns:
        lf with ``vol_rs_{w}`` columns appended.
    """
    ann_factor = np.sqrt(periods_per_year) if annualize else 1.0

    # rs = ln(h/c)*ln(h/o) + ln(lo/c)*ln(lo/o)
    rs_expr = (pl.col(high_col) / pl.col(close_col)).log(base=np.e) * (
        pl.col(high_col) / pl.col(open_col)
    ).log(base=np.e) + (pl.col(low_col) / pl.col(close_col)).log(base=np.e) * (
        pl.col(low_col) / pl.col(open_col)
    ).log(base=np.e)

    new_cols = []
    for w in windows:
        expr = (
            rs_expr.rolling_mean(window_size=w, min_samples=w)
            .sqrt()
            .mul(ann_factor)
            .alias(f"vol_rs_{w}")
        )
        new_cols.append(expr)

    return lf.with_columns(new_cols)


def add_atr_polars(
    lf: "pl.DataFrame",  # type: ignore[name-defined]
    period: int = 14,
    open_col: str = "open",
    high_col: str = "high",
    low_col: str = "low",
    close_col: str = "close",
) -> "pl.DataFrame":  # type: ignore[name-defined]
    """Average True Range (Wilder) — polars-native.

    CRITICAL ATR DIVERGENCE FIX:
    Pandas ``ewm`` skips NaN values.  The TR at row 0 is NaN (prev_close is
    NaN from shift).  In polars, ``max_horizontal`` ignores nulls and would
    return ``h - lo`` for row 0, producing a different starting value for the
    EWM recursion.  Fix:

    1. Use ``pl.when(prev_close.is_null()).then(None).otherwise(tr)`` so
       TR is null (not a real value) on row 0 — matching pandas NaN.
    2. Chain ``.ewm_mean(ignore_nulls=True)`` so the EWM recursion skips
       the null row, matching pandas behavior exactly.

    Output column: ``atr_{period}``.

    Args:
        lf: Single-group polars DataFrame sorted by ts.
        period: ATR smoothing period (Wilder alpha = 1/period).
        open_col: Unused (kept for API symmetry with pandas version).
        high_col: High price column name.
        low_col: Low price column name.
        close_col: Close price column name.

    Returns:
        lf with ``atr_{period}`` column appended.
    """
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

    atr_expr = tr_expr.ewm_mean(
        alpha=1.0 / period, adjust=False, min_samples=1, ignore_nulls=True
    ).alias(f"atr_{period}")

    return lf.with_columns([atr_expr])


def add_rolling_vol_from_returns_polars(
    lf: "pl.DataFrame",  # type: ignore[name-defined]
    close_col: str = "close",
    windows: Sequence[int] = (20, 63, 126),
    annualize: bool = True,
    periods_per_year: int = 252,
    ddof: int = 0,
    prefix: str = "vol",
    returns_col: str | None = None,
) -> "pl.DataFrame":  # type: ignore[name-defined]
    """Rolling log-return standard deviation — polars-native.

    If ``returns_col`` is provided and exists in ``lf``, use it directly as
    log returns.  Otherwise compute ``ln(close / prev_close)`` from
    ``close_col``.

    Output column names: ``{prefix}_log_roll_{w}``.

    Args:
        lf: Single-group polars DataFrame sorted by ts.
        close_col: Close price column name (used when returns_col absent).
        windows: Rolling windows (bars).
        annualize: Annualize the result.
        periods_per_year: Annualization factor.
        ddof: Degrees of freedom for std (0 = population std, 1 = sample std).
        prefix: Prefix for output column names.
        returns_col: Optional pre-computed log-return column name.

    Returns:
        lf with ``{prefix}_log_roll_{w}`` columns appended.
    """
    ann_factor = np.sqrt(periods_per_year) if annualize else 1.0

    # Resolve log-returns source
    col_names = lf.columns
    if returns_col and returns_col in col_names:
        r_log = pl.col(returns_col)
    else:
        r_log = (pl.col(close_col) / pl.col(close_col).shift(1)).log(base=np.e)

    new_cols = []
    for w in windows:
        expr = (
            r_log.rolling_std(window_size=w, min_samples=w, ddof=ddof)
            .mul(ann_factor)
            .alias(f"{prefix}_log_roll_{w}")
        )
        new_cols.append(expr)

    return lf.with_columns(new_cols)
