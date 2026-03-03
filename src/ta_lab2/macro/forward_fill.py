"""forward_fill.py

Forward-fill FRED series with per-frequency limits and source-date provenance tracking.

Forward-fill fills calendar gaps (weekends, holidays) and temporary FRED API delays
using the last known observation value. Limits prevent stale fills from propagating
indefinitely:
  - Weekly series (WALCL, WTREGEN): limit=10 days (covers ~1.5 weeks of gaps)
  - Monthly series (IRSTCI01JPM156N, IRLTLT01JPM156N): limit=45 days (~1.5 months)
  - Daily series: limit=5 days (covers long weekends + short FRED delays)

Source-date tracking records which actual observation date provided the ffilled value,
enabling the days_since_* provenance columns in fred.fred_macro_features.

Usage:
    from ta_lab2.macro.forward_fill import (
        forward_fill_with_limits,
        ffill_with_source_date,
        FFILL_LIMITS,
        SOURCE_FREQ,
    )
"""

from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger(__name__)

# ── Per-series forward-fill limits ────────────────────────────────────────
# Limits are set by publication frequency:
#   weekly -> 10 days covers ~1.5 release cycles (published every Thursday)
#   monthly -> 45 days covers ~1.5 release cycles (published once per month)
#   daily -> 5 days covers long weekends and brief FRED server delays
FFILL_LIMITS: dict[str, int] = {
    # Net liquidity components (weekly, H.4.1 release)
    "WALCL": 10,
    "WTREGEN": 10,
    # Rate spread components (daily)
    "DFF": 5,
    "ECBDFR": 5,
    "DGS10": 5,
    # Yield curve (daily)
    "T10Y2Y": 5,
    # VIX (daily)
    "VIXCLS": 5,
    # Dollar strength (daily)
    "DTWEXBGS": 5,
    # Overnight reverse repo (daily)
    "RRPONTSYD": 5,
    # Japan rates (monthly)
    "IRSTCI01JPM156N": 45,
    "IRLTLT01JPM156N": 45,
}

# ── Source frequency metadata per series ──────────────────────────────────
# Used to populate source_freq_* provenance columns in fred.fred_macro_features.
# Only listed for non-daily series (daily is implied for everything else).
SOURCE_FREQ: dict[str, str] = {
    # Weekly series
    "WALCL": "weekly",
    "WTREGEN": "weekly",
    "NFCI": "weekly",  # Phase 66 addition; included for forward-compatibility
    "STLFSI4": "weekly",  # Phase 66 addition
    # Monthly series
    "IRSTCI01JPM156N": "monthly",
    "IRLTLT01JPM156N": "monthly",
    "CPIAUCSL": "monthly",  # Phase 66
    "M2SL": "monthly",  # Phase 66
}


def ffill_with_source_date(
    series: pd.Series,
    limit: int,
) -> tuple[pd.Series, pd.Series]:
    """Forward-fill a series and track the source observation date for each filled row.

    Parameters
    ----------
    series:
        Raw pandas Series (sparse: actual observations only, NaN for calendar gaps).
        Index should be a DatetimeIndex.
    limit:
        Maximum number of consecutive NaN rows to forward-fill.

    Returns
    -------
    tuple[pd.Series, pd.Series]
        (filled_values, source_observation_dates)

        filled_values:
            Forward-filled series values (float). NaN beyond the fill limit.
        source_observation_dates:
            DatetimeIndex-aligned Series of datetime64 values indicating which
            actual observation date provided each filled row's value. NaN where
            filled_values is also NaN.

    Notes
    -----
    This enables days_since computation:
        days_since = (df.index - source_observation_dates).dt.days

    Example
    -------
    If WALCL has an observation on 2026-02-26 and none on 2026-02-27 through
    2026-03-04, source_observation_dates for those filled days will all be
    2026-02-26, giving days_since_walcl = 1, 2, ..., 7 for those days.
    """
    # Build source_date series: only non-NaN positions get their own index label
    source_date: pd.Series = pd.Series(
        pd.NaT, index=series.index, dtype="datetime64[ns]"
    )
    non_null_mask = series.notna()
    if non_null_mask.any():
        # Assign the index date as the "source date" for actual observations
        source_date[non_null_mask] = series.index[non_null_mask]

    # Forward-fill both value and source date with the same limit
    filled_values = series.ffill(limit=limit)
    filled_source = source_date.ffill(limit=limit)

    return filled_values, filled_source


def forward_fill_with_limits(
    df_wide: pd.DataFrame,
    tracked_series: list[str] | None = None,
) -> tuple[pd.DataFrame, dict[str, pd.Series]]:
    """Apply per-series forward-fill with frequency-appropriate limits.

    For series in tracked_series (default: WALCL, WTREGEN), also tracks the
    source observation date to enable days_since_* provenance computation.

    Parameters
    ----------
    df_wide:
        Wide DataFrame from load_series_wide(). Index is DatetimeIndex (calendar-daily).
        Columns are uppercase FRED series IDs.
    tracked_series:
        Series IDs for which to return source_date provenance.
        Defaults to ["WALCL", "WTREGEN"] (the weekly net-liquidity components).

    Returns
    -------
    tuple[pd.DataFrame, dict[str, pd.Series]]
        (df_filled, source_dates)

        df_filled:
            Forward-filled wide DataFrame. Same shape as df_wide. NaN only where
            a column exhausted its fill limit (e.g., WALCL still NaN after 10 days).

        source_dates:
            Dict mapping series_id -> source_observation_date Series.
            Only populated for columns in tracked_series that exist in df_wide.
            Keys are uppercase FRED IDs (e.g. "WALCL").

    Notes
    -----
    - Non-tracked columns are forward-filled in-place using plain ffill(limit=N).
    - Unknown columns (not in FFILL_LIMITS) default to limit=5 (daily assumption).
    - Missing tracked series (not in df_wide columns) are silently skipped; the
      caller (feature_computer.py) handles the graceful-degradation case.
    """
    if tracked_series is None:
        tracked_series = ["WALCL", "WTREGEN"]

    tracked_set = set(tracked_series)
    source_dates: dict[str, pd.Series] = {}

    df_out = df_wide.copy()

    for col in df_out.columns:
        limit = FFILL_LIMITS.get(col, 5)

        if col in tracked_set:
            filled, src_date = ffill_with_source_date(df_out[col], limit=limit)
            df_out[col] = filled
            source_dates[col] = src_date
            logger.debug("ffill_with_source_date: %s (limit=%d)", col, limit)
        else:
            df_out[col] = df_out[col].ffill(limit=limit)

    missing_tracked = tracked_set - set(df_wide.columns)
    if missing_tracked:
        logger.warning(
            "Tracked series not present in df_wide: %s -- "
            "source_dates will be missing for these",
            sorted(missing_tracked),
        )

    return df_out, source_dates
