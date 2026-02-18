"""
Polars-based EMA operations for high-performance feature computation.

Analogous to polars_bar_operations.py for bar builders. Pure, stateless
functions operating on numpy arrays and Polars DataFrames.

Functions:
- compute_ema_polars: Polars ewm_mean with group-by support
- add_derivatives_polars: d1_roll/d2_roll (all rows) + d1/d2 (canonical-only)
- add_dual_derivatives_polars: Same for dual EMA (ema + ema_bar)
- compute_roll_flags_modulo: Modulo-based roll flags (v2/multi_tf)
- compute_roll_flags_from_canonical: Set-based roll flags (cal/cal_anchor)
- compute_dual_ema_numpy: Pure numpy dual EMA with snap logic

Performance:
- Polars ewm_mean: 3-5x faster than pandas compute_ema for grouped data
- numpy dual EMA: ~100x faster than pd.Series.iloc[i] loops
- Vectorized derivatives: avoids Python-level groupby iteration
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import polars as pl


# =============================================================================
# EMA Computation
# =============================================================================


def compute_ema_polars(
    pl_df: pl.DataFrame,
    value_col: str,
    span: int,
    *,
    group_cols: Optional[list[str]] = None,
    min_periods: Optional[int] = None,
    out_col: str = "ema",
) -> pl.DataFrame:
    """
    Compute EMA using Polars ewm_mean.

    Matches compute_ema() semantics: adjust=False, SMA seed over min_periods.

    Args:
        pl_df: Input Polars DataFrame (must be sorted by time within groups)
        value_col: Column containing values to smooth
        span: EMA span (period)
        group_cols: Optional grouping columns (e.g., ["id"])
        min_periods: Minimum periods before producing a value (default: span)
        out_col: Output column name

    Returns:
        DataFrame with new EMA column
    """
    mp = min_periods if min_periods is not None else span

    ema_expr = pl.col(value_col).ewm_mean(span=span, adjust=False, min_periods=mp)

    if group_cols:
        ema_expr = ema_expr.over(group_cols)

    return pl_df.with_columns(ema_expr.alias(out_col))


# =============================================================================
# Roll Flag Computation
# =============================================================================


def compute_roll_flags_modulo(
    pl_df: pl.DataFrame,
    tf_days: int,
    *,
    group_cols: Optional[list[str]] = None,
    out_col: str = "roll",
) -> pl.DataFrame:
    """
    Compute roll flags using modulo logic (v2/multi_tf).

    roll = FALSE every tf_days-th row (per group), TRUE otherwise.
    Uses a row-number within group and checks (row_nr % tf_days == 0).

    Args:
        pl_df: Input DataFrame sorted by time within groups
        tf_days: Timeframe period in days
        group_cols: Optional group columns
        out_col: Output column name

    Returns:
        DataFrame with boolean roll column
    """
    if group_cols:
        row_nr_expr = pl.arange(0, pl.count()).over(group_cols)
    else:
        row_nr_expr = pl.arange(0, pl.count())

    # roll=FALSE when (pos+1) % tf_days == 0
    roll_expr = (row_nr_expr + 1) % tf_days != 0

    return pl_df.with_columns(roll_expr.alias(out_col))


def compute_roll_flags_from_canonical(
    pl_df: pl.DataFrame,
    canonical_ts: list | set | np.ndarray,
    *,
    ts_col: str = "ts",
    out_col: str = "roll",
) -> pl.DataFrame:
    """
    Compute roll flags from canonical timestamp set (cal/cal_anchor).

    roll = FALSE for timestamps in canonical_ts, TRUE otherwise.

    Args:
        pl_df: Input DataFrame
        canonical_ts: Collection of canonical timestamps
        ts_col: Timestamp column
        out_col: Output column name

    Returns:
        DataFrame with boolean roll column
    """
    canonical_series = pl.Series("_canonical_ts", list(canonical_ts))
    return pl_df.with_columns((~pl.col(ts_col).is_in(canonical_series)).alias(out_col))


# =============================================================================
# Derivative Computation
# =============================================================================


def add_derivatives_polars(
    pl_df: pl.DataFrame,
    ema_col: str = "ema",
    *,
    group_cols: Optional[list[str]] = None,
    roll_col: str = "roll",
) -> pl.DataFrame:
    """
    Add standard derivative columns for single-EMA feature classes.

    Adds:
    - d1_roll, d2_roll: derivatives across ALL rows (daily diffs)
    - d1, d2: derivatives across canonical rows only (roll=FALSE)

    Args:
        pl_df: Input DataFrame sorted by time within groups
        ema_col: EMA column name
        group_cols: Group columns for partitioned diff
        roll_col: Roll flag column (True=roll, False=canonical)

    Returns:
        DataFrame with d1_roll, d2_roll, d1, d2 columns
    """
    # Rolling derivatives (all rows)
    if group_cols:
        d1_roll_expr = pl.col(ema_col).diff().over(group_cols)
    else:
        d1_roll_expr = pl.col(ema_col).diff()

    result = pl_df.with_columns(d1_roll_expr.alias("d1_roll"))

    if group_cols:
        d2_roll_expr = pl.col("d1_roll").diff().over(group_cols)
    else:
        d2_roll_expr = pl.col("d1_roll").diff()

    result = result.with_columns(d2_roll_expr.alias("d2_roll"))

    # Canonical derivatives: diff only across canonical rows (roll=FALSE)
    # Strategy: mask non-canonical EMA values to null, then diff
    if group_cols:
        canon_ema = (
            pl.when(~pl.col(roll_col))
            .then(pl.col(ema_col))
            .otherwise(pl.lit(None, dtype=pl.Float64))
        )
        # Forward-fill nulls removed: we want null on non-canonical rows
        # diff() skips nulls naturally in Polars
        d1_canon = canon_ema.diff().over(group_cols)
    else:
        canon_ema = (
            pl.when(~pl.col(roll_col))
            .then(pl.col(ema_col))
            .otherwise(pl.lit(None, dtype=pl.Float64))
        )
        d1_canon = canon_ema.diff()

    result = result.with_columns(d1_canon.alias("d1"))

    # d2 canonical: diff of d1 at canonical points
    if group_cols:
        d1_canon_for_d2 = (
            pl.when(~pl.col(roll_col))
            .then(pl.col("d1"))
            .otherwise(pl.lit(None, dtype=pl.Float64))
        )
        d2_canon = d1_canon_for_d2.diff().over(group_cols)
    else:
        d1_canon_for_d2 = (
            pl.when(~pl.col(roll_col))
            .then(pl.col("d1"))
            .otherwise(pl.lit(None, dtype=pl.Float64))
        )
        d2_canon = d1_canon_for_d2.diff()

    result = result.with_columns(d2_canon.alias("d2"))

    return result


def add_dual_derivatives_polars(
    pl_df: pl.DataFrame,
    *,
    group_cols: Optional[list[str]] = None,
    ema_col: str = "ema",
    ema_bar_col: str = "ema_bar",
    roll_col: str = "roll",
    roll_bar_col: str = "roll_bar",
) -> pl.DataFrame:
    """
    Add derivative columns for dual-EMA feature classes (cal/cal_anchor).

    Adds for ema:
    - d1_roll, d2_roll (all rows), d1, d2 (canonical via roll)

    Adds for ema_bar:
    - d1_roll_bar, d2_roll_bar (all rows), d1_bar, d2_bar (canonical via roll_bar)

    Args:
        pl_df: Input DataFrame sorted by time within groups
        group_cols: Group columns for partitioned diffs
        ema_col, ema_bar_col: EMA column names
        roll_col, roll_bar_col: Roll flag column names

    Returns:
        DataFrame with 8 derivative columns
    """
    # ---- ema-space derivatives ----
    if group_cols:
        d1_roll = pl.col(ema_col).diff().over(group_cols)
    else:
        d1_roll = pl.col(ema_col).diff()
    result = pl_df.with_columns(d1_roll.alias("d1_roll"))

    if group_cols:
        d2_roll = pl.col("d1_roll").diff().over(group_cols)
    else:
        d2_roll = pl.col("d1_roll").diff()
    result = result.with_columns(d2_roll.alias("d2_roll"))

    # Canonical ema derivatives
    canon_ema = (
        pl.when(~pl.col(roll_col))
        .then(pl.col(ema_col))
        .otherwise(pl.lit(None, dtype=pl.Float64))
    )
    if group_cols:
        d1_canon = canon_ema.diff().over(group_cols)
    else:
        d1_canon = canon_ema.diff()
    result = result.with_columns(d1_canon.alias("d1"))

    d1_for_d2 = (
        pl.when(~pl.col(roll_col))
        .then(pl.col("d1"))
        .otherwise(pl.lit(None, dtype=pl.Float64))
    )
    if group_cols:
        d2_canon = d1_for_d2.diff().over(group_cols)
    else:
        d2_canon = d1_for_d2.diff()
    result = result.with_columns(d2_canon.alias("d2"))

    # ---- ema_bar-space derivatives ----
    if group_cols:
        d1_roll_bar = pl.col(ema_bar_col).diff().over(group_cols)
    else:
        d1_roll_bar = pl.col(ema_bar_col).diff()
    result = result.with_columns(d1_roll_bar.alias("d1_roll_bar"))

    if group_cols:
        d2_roll_bar = pl.col("d1_roll_bar").diff().over(group_cols)
    else:
        d2_roll_bar = pl.col("d1_roll_bar").diff()
    result = result.with_columns(d2_roll_bar.alias("d2_roll_bar"))

    # Canonical ema_bar derivatives
    canon_bar = (
        pl.when(~pl.col(roll_bar_col))
        .then(pl.col(ema_bar_col))
        .otherwise(pl.lit(None, dtype=pl.Float64))
    )
    if group_cols:
        d1_bar_canon = canon_bar.diff().over(group_cols)
    else:
        d1_bar_canon = canon_bar.diff()
    result = result.with_columns(d1_bar_canon.alias("d1_bar"))

    d1_bar_for_d2 = (
        pl.when(~pl.col(roll_bar_col))
        .then(pl.col("d1_bar"))
        .otherwise(pl.lit(None, dtype=pl.Float64))
    )
    if group_cols:
        d2_bar_canon = d1_bar_for_d2.diff().over(group_cols)
    else:
        d2_bar_canon = d1_bar_for_d2.diff()
    result = result.with_columns(d2_bar_canon.alias("d2_bar"))

    return result


# =============================================================================
# Dual EMA Computation (numpy - inherently sequential)
# =============================================================================


def compute_dual_ema_numpy(
    close_arr: np.ndarray,
    canonical_mask: np.ndarray,
    canonical_ema_values: np.ndarray,
    alpha_daily: float,
    alpha_bar: float,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Compute dual EMA arrays (ema_bar + ema) using pure numpy.

    ema_bar logic (bar alpha + reanchoring):
    - At canonical days (canonical_mask=True): snap to canonical_ema_values
    - At non-canonical days: alpha_bar * close + (1-alpha_bar) * last_canonical_ema
      Each preview is reanchored to the last canonical EMA (stateless between days).

    ema logic (continuous daily alpha):
    - Seeded at first valid ema_bar value
    - Then: alpha_daily * close + (1-alpha_daily) * prev_ema

    Args:
        close_arr: Daily close prices (float64 array, length N)
        canonical_mask: Boolean array, True = canonical day (length N)
        canonical_ema_values: Bar-EMA values at canonical days (float64, length N,
                              NaN for non-canonical or pre-seed days)
        alpha_daily: Daily-space alpha for ema (continuous)
        alpha_bar: Bar-space alpha for ema_bar previews (2/(period+1))

    Returns:
        Tuple of (ema_bar_arr, ema_arr), both float64 arrays of length N
    """
    n = len(close_arr)
    ema_bar = np.full(n, np.nan, dtype=np.float64)
    ema = np.full(n, np.nan, dtype=np.float64)

    one_minus_alpha_daily = 1.0 - alpha_daily
    one_minus_alpha_bar = 1.0 - alpha_bar

    # --- ema_bar: find first seed, then iterate with reanchoring ---
    seed_mask = canonical_mask & ~np.isnan(canonical_ema_values)
    seed_positions = np.where(seed_mask)[0]

    if len(seed_positions) == 0:
        return ema_bar, ema

    i0 = int(seed_positions[0])
    ema_bar[i0] = canonical_ema_values[i0]
    last_canonical_ema = canonical_ema_values[i0]

    for i in range(i0 + 1, n):
        x = close_arr[i]
        if canonical_mask[i] and not np.isnan(canonical_ema_values[i]):
            ema_bar[i] = canonical_ema_values[i]
            last_canonical_ema = canonical_ema_values[i]
        else:
            # Reanchor preview to last canonical EMA using bar-space alpha
            ema_bar[i] = alpha_bar * x + one_minus_alpha_bar * last_canonical_ema

    # --- ema: seeded at first canonical ema_bar, then continuous ---
    # Find first row where canonical AND ema_bar is valid
    ema_seed_mask = (~np.isnan(ema_bar)) & canonical_mask
    ema_seed_positions = np.where(ema_seed_mask)[0]

    if len(ema_seed_positions) == 0:
        return ema_bar, ema

    j0 = int(ema_seed_positions[0])
    ema[j0] = ema_bar[j0]

    for i in range(j0 + 1, n):
        prev = ema[i - 1]
        x = close_arr[i]
        ema[i] = alpha_daily * x + one_minus_alpha_daily * prev

    return ema_bar, ema


def compute_bar_ema_numpy(
    close_prices: np.ndarray,
    period: int,
    min_periods: Optional[int] = None,
) -> np.ndarray:
    """
    Compute EMA on bar-space closes using numpy.

    Matches compute_ema() semantics: SMA seed, then EMA recursion.

    Args:
        close_prices: Close prices array
        period: EMA period (span)
        min_periods: Minimum periods for first value (default: period)

    Returns:
        EMA values array (NaN before seed)
    """
    mp = min_periods if min_periods is not None else period
    n = len(close_prices)
    result = np.full(n, np.nan, dtype=np.float64)

    if n < mp:
        return result

    alpha = 2.0 / (period + 1.0)

    # Find first valid window of mp non-NaN values
    first_valid_end = -1
    for i in range(mp - 1, n):
        window = close_prices[i - (mp - 1) : i + 1]
        if not np.isnan(window).any():
            first_valid_end = i
            break

    if first_valid_end == -1:
        return result

    # SMA seed
    seed_window = close_prices[first_valid_end - (mp - 1) : first_valid_end + 1]
    seed_val = np.mean(seed_window)
    result[first_valid_end] = seed_val

    # EMA recursion
    prev = seed_val
    for i in range(first_valid_end + 1, n):
        x = close_prices[i]
        if np.isnan(x):
            result[i] = prev
        else:
            prev = alpha * x + (1.0 - alpha) * prev
            result[i] = prev

    return result
