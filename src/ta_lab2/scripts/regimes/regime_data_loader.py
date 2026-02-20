"""
Regime Data Loader - DB data loading and EMA pivot utilities.

Bridges the PostgreSQL feature pipeline to the regime labeler interface.

The regime labelers (labels.py) expect wide-format DataFrames with columns
like close_ema_20, close_ema_50, close_ema_200. The DB stores EMAs in
long format with a ``period`` column. This module provides the critical
pivot/rename step that is the primary integration risk.

Key Design Decisions:
- Calendar bar tables use ``time_close`` (not ``ts``) -- always aliased in queries
- Daily EMAs in cmc_ema_multi_tf_u require ``alignment_source = 'multi_tf'`` filter
  to prevent duplicate rows per (id, ts, tf, period)
- Period column values are INTEGER in DB but may vary -- cast to int before renaming
  to ensure numeric sort order (20 < 50 < 200), not alphabetic ('200' < '50')
- Empty result handling returns correctly-typed empty DataFrames, not crashes

EMA Period Mapping (confirmed from RESEARCH.md):
    L0 Monthly: periods [12, 24, 48] -> close_ema_12, close_ema_24, close_ema_48
    L1 Weekly:  periods [20, 50, 200] -> close_ema_20, close_ema_50, close_ema_200
    L2 Daily:   periods [20, 50, 100] -> close_ema_20, close_ema_50, close_ema_100

Exports:
    pivot_emas_to_wide: Convert long-format (id, ts, period, ema) to wide-format
    load_bars_for_tf: Load OHLCV bars for a single asset and timeframe
    load_emas_for_tf: Load raw long-format EMAs for a single asset and timeframe
    load_and_pivot_emas: Load EMAs and pivot to wide format in one step
    load_regime_input_data: Load all 3 TF datasets for a single asset
"""

from __future__ import annotations

import logging

import pandas as pd
from sqlalchemy import Engine, text

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# EMA Period Mapping
# ---------------------------------------------------------------------------

#: Default EMA periods for each timeframe layer.
#: Confirmed against DEFAULT_PERIODS in refresh_cmc_ema_multi_tf_from_bars.py
#: and feature_utils.py add_ema_pack() conventions.
DEFAULT_MONTHLY_PERIODS: list[int] = [12, 24, 48]
DEFAULT_WEEKLY_PERIODS: list[int] = [20, 50, 200]
DEFAULT_DAILY_PERIODS: list[int] = [20, 50, 100]

#: Empty OHLCV column spec for consistent empty DataFrame shape
_OHLCV_COLS = ["id", "ts", "open", "high", "low", "close", "volume"]


# ---------------------------------------------------------------------------
# Core Pivot Utility
# ---------------------------------------------------------------------------


def pivot_emas_to_wide(
    ema_df: pd.DataFrame,
    periods: list[int],
    price_col: str = "close",
) -> pd.DataFrame:
    """
    Pivot long-format EMA rows to wide-format with close_ema_N column naming.

    The labelers (labels.py) call ``df.get("close_ema_20", np.nan)`` and similar.
    They require wide-format DataFrames. The DB stores EMAs in long format with
    a ``period`` column. This function performs the critical bridge transformation.

    Args:
        ema_df: Long-format DataFrame with columns: id, ts, period, ema.
                May come from cmc_ema_multi_tf_cal_iso/us or cmc_ema_multi_tf_u.
        periods: List of period values to include (e.g. [20, 50, 200]).
                 Rows with period not in this list are filtered out.
        price_col: Prefix for EMA column names. Default "close" produces
                   columns like ``close_ema_20``, ``close_ema_50``.

    Returns:
        Wide-format DataFrame with columns: id, ts, close_ema_N, ...
        Sorted by (id, ts). Returns empty DataFrame with [id, ts] columns
        if ema_df is empty or no matching periods exist.

    Raises:
        KeyError: If ema_df is missing required columns (id, ts, period, ema).

    Notes:
        - Periods are cast to int before renaming to ensure numeric sort order:
          20 < 50 < 200 (not alphabetic where '200' < '50').
        - The pivot uses pivot_table with aggfunc='first' to handle any
          unexpected duplicates gracefully.
    """
    if ema_df.empty:
        logger.debug(
            "pivot_emas_to_wide: empty input DataFrame, returning empty result"
        )
        empty_cols = ["id", "ts"] + [f"{price_col}_ema_{p}" for p in sorted(periods)]
        return pd.DataFrame(columns=empty_cols)

    # Filter to only the requested periods
    filtered = ema_df[ema_df["period"].isin(periods)].copy()

    if filtered.empty:
        logger.debug(
            "pivot_emas_to_wide: no rows matched periods=%s, returning empty result",
            periods,
        )
        empty_cols = ["id", "ts"] + [f"{price_col}_ema_{p}" for p in sorted(periods)]
        return pd.DataFrame(columns=empty_cols)

    # Normalize period column to int so sort is numeric (not lexicographic).
    # DB returns INTEGER type, but defensive cast handles any string leakage.
    filtered["period"] = filtered["period"].astype(int)

    # Pivot: long (id, ts, period, ema) -> wide (id, ts, ema_20, ema_50, ...)
    # aggfunc='first' silently handles duplicates if any slip through the filter
    pivot = filtered.pivot_table(
        index=["id", "ts"], columns="period", values="ema", aggfunc="first"
    ).reset_index()
    pivot.columns.name = None  # Remove the "period" axis name from MultiIndex

    # Build sorted column list using int comparison (not string comparison).
    # This ensures 20 < 50 < 200 -- not '200' < '50' (alphabetic).
    available_periods = sorted(int(c) for c in pivot.columns if c not in ("id", "ts"))

    # Rename numeric period columns to close_ema_N convention
    rename_map = {p: f"{price_col}_ema_{p}" for p in available_periods}
    pivot = pivot.rename(columns=rename_map)

    # Reorder columns: id, ts, then EMA columns in ascending period order
    ema_cols_ordered = [f"{price_col}_ema_{p}" for p in available_periods]
    result = pivot[["id", "ts"] + ema_cols_ordered]

    return result.sort_values(["id", "ts"]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Bar Loading
# ---------------------------------------------------------------------------


def load_bars_for_tf(
    engine: Engine,
    asset_id: int,
    tf: str,
    cal_scheme: str = "iso",
) -> pd.DataFrame:
    """
    Load OHLCV price bars from DB for a single asset and timeframe.

    Routes to the correct table based on timeframe:
    - Daily (``tf='1D'``): queries ``cmc_price_bars_multi_tf``
    - Weekly/Monthly (``tf='1W'`` or ``tf='1M'``): queries the calendar bar table
      (cmc_price_bars_multi_tf_cal_iso or _cal_us depending on cal_scheme)

    CRITICAL: Calendar bar tables use ``time_close`` (not ``ts``) as the timestamp
    column. This function always aliases it to ``ts`` so callers receive a
    consistent column name.

    Args:
        engine: SQLAlchemy engine connected to the PostgreSQL DB.
        asset_id: Integer asset ID (matches ``id`` in dim_assets).
        tf: Timeframe string. One of '1D', '1W', '1M'.
        cal_scheme: Calendar scheme for weekly/monthly bars. 'iso' (default) uses
                    Monday-anchored weeks and ISO months. 'us' uses US Sunday weeks.

    Returns:
        DataFrame sorted by ts with columns: id, ts, open, high, low, close, volume.
        ts is timezone-aware (UTC). Returns empty DataFrame with correct columns
        if no data found for the asset/tf combination.

    Raises:
        ValueError: If tf is not one of '1D', '1W', '1M'.
        ValueError: If cal_scheme is not 'iso' or 'us'.
    """
    if tf not in ("1D", "1W", "1M"):
        raise ValueError(f"Unsupported tf '{tf}'. Must be one of: '1D', '1W', '1M'")
    if cal_scheme not in ("iso", "us"):
        raise ValueError(
            f"Unsupported cal_scheme '{cal_scheme}'. Must be 'iso' or 'us'"
        )

    if tf == "1D":
        # Daily bars: standard multi-TF table, uses ts column directly
        sql = text(
            """
            SELECT id, time_close AS ts, open, high, low, close, volume
            FROM public.cmc_price_bars_multi_tf
            WHERE id = :id AND tf = '1D'
            ORDER BY time_close
        """
        )
        params = {"id": asset_id}
    else:
        # Weekly or monthly: calendar bar table, time_close aliased to ts
        # CRITICAL: PK uses bar_seq, not ts. time_close is the period-end timestamp.
        table_name = f"cmc_price_bars_multi_tf_cal_{cal_scheme}"
        sql = text(
            f"""
            SELECT id, time_close AS ts, open, high, low, close, volume
            FROM public.{table_name}
            WHERE id = :id AND tf = :tf
            ORDER BY time_close
        """
        )
        params = {"id": asset_id, "tf": tf}

    try:
        with engine.connect() as conn:
            df = pd.read_sql(sql, conn, params=params)
    except Exception as exc:
        logger.warning(
            "load_bars_for_tf: query failed for id=%s tf=%s cal_scheme=%s: %s",
            asset_id,
            tf,
            cal_scheme,
            exc,
        )
        return pd.DataFrame(columns=_OHLCV_COLS)

    if df.empty:
        logger.debug(
            "load_bars_for_tf: no data for id=%s tf=%s cal_scheme=%s",
            asset_id,
            tf,
            cal_scheme,
        )
        return pd.DataFrame(columns=_OHLCV_COLS)

    # Ensure ts is tz-aware UTC (guard against tz-naive returns from some drivers)
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df.sort_values("ts").reset_index(drop=True)


# ---------------------------------------------------------------------------
# EMA Loading
# ---------------------------------------------------------------------------


def load_emas_for_tf(
    engine: Engine,
    asset_id: int,
    tf: str,
    periods: list[int],
    cal_scheme: str = "iso",
) -> pd.DataFrame:
    """
    Load raw long-format EMAs from DB for a single asset and timeframe.

    Routes to the correct EMA table based on timeframe:
    - Daily (``tf='1D'``): queries ``cmc_ema_multi_tf_u`` with
      ``alignment_source = 'multi_tf'`` filter to prevent duplicate rows.
    - Weekly/Monthly (``tf='1W'`` or ``tf='1M'``): queries the calendar EMA table
      (cmc_ema_multi_tf_cal_iso or _cal_us depending on cal_scheme).

    CRITICAL: ``cmc_ema_multi_tf_u`` has an ``alignment_source`` column with values
    like 'multi_tf', 'multi_tf_cal_us'. For daily regime EMAs, always filter to
    'multi_tf' to avoid duplicate rows per (id, ts, period).

    Args:
        engine: SQLAlchemy engine connected to the PostgreSQL DB.
        asset_id: Integer asset ID.
        tf: Timeframe string. One of '1D', '1W', '1M'.
        periods: List of EMA periods to retrieve (e.g. [20, 50, 200]).
        cal_scheme: Calendar scheme for weekly/monthly. 'iso' or 'us'.

    Returns:
        Long-format DataFrame with columns: id, ts, period, ema.
        ts is timezone-aware (UTC). Returns empty DataFrame with correct columns
        if no data found.

    Raises:
        ValueError: If tf is not one of '1D', '1W', '1M'.
    """
    if tf not in ("1D", "1W", "1M"):
        raise ValueError(f"Unsupported tf '{tf}'. Must be one of: '1D', '1W', '1M'")

    empty_result = pd.DataFrame(columns=["id", "ts", "period", "ema"])

    if not periods:
        logger.debug("load_emas_for_tf: empty periods list, returning empty result")
        return empty_result

    if tf == "1D":
        # Daily EMAs from cmc_ema_multi_tf_u
        # CRITICAL: Filter alignment_source = 'multi_tf' to avoid duplicates.
        # The table has alignment_source in data but NOT in PK -- without this
        # filter, pivot_table may see duplicate (id, ts, period) combinations.
        sql = text(
            """
            SELECT id, ts, period, ema
            FROM public.cmc_ema_multi_tf_u
            WHERE id = :id
              AND tf = '1D'
              AND period = ANY(:periods)
              AND alignment_source = 'multi_tf'
            ORDER BY ts, period
        """
        )
        params = {"id": asset_id, "periods": periods}
    else:
        # Weekly/monthly EMAs from calendar EMA table
        # Calendar EMA table PK: (id, tf, ts, period)
        # No alignment_source filter needed -- unique by PK
        table_name = f"cmc_ema_multi_tf_cal_{cal_scheme}"
        sql = text(
            f"""
            SELECT id, ts, period, ema
            FROM public.{table_name}
            WHERE id = :id
              AND tf = :tf
              AND period = ANY(:periods)
            ORDER BY ts, period
        """
        )
        params = {"id": asset_id, "tf": tf, "periods": periods}

    try:
        with engine.connect() as conn:
            df = pd.read_sql(sql, conn, params=params)
    except Exception as exc:
        logger.warning(
            "load_emas_for_tf: query failed for id=%s tf=%s periods=%s: %s",
            asset_id,
            tf,
            periods,
            exc,
        )
        return empty_result

    if df.empty:
        logger.debug(
            "load_emas_for_tf: no data for id=%s tf=%s periods=%s",
            asset_id,
            tf,
            periods,
        )
        return empty_result

    # Ensure ts is tz-aware UTC
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Combined Load + Pivot
# ---------------------------------------------------------------------------


def load_and_pivot_emas(
    engine: Engine,
    asset_id: int,
    tf: str,
    periods: list[int],
    price_col: str = "close",
    cal_scheme: str = "iso",
) -> pd.DataFrame:
    """
    Load EMAs from DB and pivot to wide-format in one step.

    Combines ``load_emas_for_tf`` and ``pivot_emas_to_wide``. This is the
    primary function used by the regime refresh pipeline for EMA preparation.

    Args:
        engine: SQLAlchemy engine connected to the PostgreSQL DB.
        asset_id: Integer asset ID.
        tf: Timeframe string. One of '1D', '1W', '1M'.
        periods: List of EMA periods to retrieve and pivot.
        price_col: Prefix for EMA column names. Default "close" produces
                   columns like ``close_ema_20``, ``close_ema_50``.
        cal_scheme: Calendar scheme for weekly/monthly. 'iso' or 'us'.

    Returns:
        Wide-format DataFrame with columns: id, ts, close_ema_N, ...
        Ready for merging with bars and passing to labeler functions.
        Returns empty DataFrame with correct column names on failure.
    """
    long_df = load_emas_for_tf(engine, asset_id, tf, periods, cal_scheme=cal_scheme)
    return pivot_emas_to_wide(long_df, periods, price_col=price_col)


# ---------------------------------------------------------------------------
# Master Load Function
# ---------------------------------------------------------------------------


def load_regime_input_data(
    engine: Engine,
    asset_id: int,
    cal_scheme: str = "iso",
) -> dict[str, pd.DataFrame]:
    """
    Load all 3 TF datasets for a single asset, ready for regime labeling.

    Loads bars and EMAs for monthly, weekly, and daily timeframes, then
    merges each bar/EMA pair on (id, ts). Returns a dict keyed by TF name.

    EMA periods used (confirmed from RESEARCH.md and labels.py defaults):
    - Monthly: [12, 24, 48]  -> close_ema_12, close_ema_24, close_ema_48
    - Weekly:  [20, 50, 200] -> close_ema_20, close_ema_50, close_ema_200
    - Daily:   [20, 50, 100] -> close_ema_20, close_ema_50, close_ema_100

    The returned DataFrames are ready to pass directly to:
    - ``label_layer_monthly(result["monthly"], mode=mode)``
    - ``label_layer_weekly(result["weekly"], mode=mode)``
    - ``label_layer_daily(result["daily"], mode=mode)``

    Args:
        engine: SQLAlchemy engine connected to the PostgreSQL DB.
        asset_id: Integer asset ID.
        cal_scheme: Calendar scheme for weekly/monthly bars and EMAs.
                    'iso' (default) uses Monday-anchored weeks.
                    'us' uses US Sunday-anchored weeks.

    Returns:
        Dict with keys 'monthly', 'weekly', 'daily'. Each value is a DataFrame
        sorted by ts with columns: id, ts, open, high, low, close, volume,
        and close_ema_N columns for the respective layer.

        If data is missing for a TF, that DataFrame will have only bar columns
        (EMA columns will be absent or NaN depending on merge behavior).

    Example:
        >>> data = load_regime_input_data(engine, asset_id=1)
        >>> monthly = data["monthly"]   # columns: id, ts, open,..., close_ema_12,...
        >>> weekly  = data["weekly"]    # columns: id, ts, open,..., close_ema_20,...
        >>> daily   = data["daily"]     # columns: id, ts, open,..., close_ema_20,...
    """
    logger.info(
        "load_regime_input_data: loading data for asset_id=%s cal_scheme=%s",
        asset_id,
        cal_scheme,
    )

    # ------------------------------------------------------------------
    # Monthly (L0) -- cmc_price_bars_multi_tf_cal_{scheme} + cal EMA table
    # ------------------------------------------------------------------
    monthly_bars = load_bars_for_tf(engine, asset_id, tf="1M", cal_scheme=cal_scheme)
    monthly_emas = load_and_pivot_emas(
        engine,
        asset_id,
        tf="1M",
        periods=DEFAULT_MONTHLY_PERIODS,
        price_col="close",
        cal_scheme=cal_scheme,
    )

    if not monthly_bars.empty and not monthly_emas.empty:
        monthly = pd.merge(monthly_bars, monthly_emas, on=["id", "ts"], how="left")
    else:
        monthly = monthly_bars.copy()
        logger.debug(
            "load_regime_input_data: monthly EMA merge skipped (bars=%d, emas=%d)",
            len(monthly_bars),
            len(monthly_emas),
        )

    # ------------------------------------------------------------------
    # Weekly (L1) -- cmc_price_bars_multi_tf_cal_{scheme} + cal EMA table
    # ------------------------------------------------------------------
    weekly_bars = load_bars_for_tf(engine, asset_id, tf="1W", cal_scheme=cal_scheme)
    weekly_emas = load_and_pivot_emas(
        engine,
        asset_id,
        tf="1W",
        periods=DEFAULT_WEEKLY_PERIODS,
        price_col="close",
        cal_scheme=cal_scheme,
    )

    if not weekly_bars.empty and not weekly_emas.empty:
        weekly = pd.merge(weekly_bars, weekly_emas, on=["id", "ts"], how="left")
    else:
        weekly = weekly_bars.copy()
        logger.debug(
            "load_regime_input_data: weekly EMA merge skipped (bars=%d, emas=%d)",
            len(weekly_bars),
            len(weekly_emas),
        )

    # ------------------------------------------------------------------
    # Daily (L2) -- cmc_price_bars_multi_tf + cmc_ema_multi_tf_u
    # ------------------------------------------------------------------
    daily_bars = load_bars_for_tf(engine, asset_id, tf="1D", cal_scheme=cal_scheme)
    daily_emas = load_and_pivot_emas(
        engine,
        asset_id,
        tf="1D",
        periods=DEFAULT_DAILY_PERIODS,
        price_col="close",
        cal_scheme=cal_scheme,
    )

    if not daily_bars.empty and not daily_emas.empty:
        daily = pd.merge(daily_bars, daily_emas, on=["id", "ts"], how="left")
    else:
        daily = daily_bars.copy()
        logger.debug(
            "load_regime_input_data: daily EMA merge skipped (bars=%d, emas=%d)",
            len(daily_bars),
            len(daily_emas),
        )

    logger.info(
        "load_regime_input_data: done for asset_id=%s -- "
        "monthly=%d rows, weekly=%d rows, daily=%d rows",
        asset_id,
        len(monthly),
        len(weekly),
        len(daily),
    )

    return {
        "monthly": monthly.sort_values("ts").reset_index(drop=True),
        "weekly": weekly.sort_values("ts").reset_index(drop=True),
        "daily": daily.sort_values("ts").reset_index(drop=True),
    }
