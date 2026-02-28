# -*- coding: utf-8 -*-
"""
MAE/MFE (Maximum Adverse Excursion / Maximum Favorable Excursion) computation.

MAE measures the worst intra-trade drawdown (how far against you the trade moved).
MFE measures the best intra-trade gain (how far in your favor the trade moved).
Both are expressed as decimal fractions relative to entry_price.

Interpretation:
    - MAE close to 0  : trade never moved much against you (tight stop potential)
    - MAE very negative: trade suffered large drawdown before recovering (wide stop needed)
    - MFE close to 0  : trade never moved much in your favor (signal may be weak)
    - MFE large positive: trade had large unrealized gain (consider trailing stop)

Public API:
    compute_mae_mfe     -- MAE/MFE per trade, appended as columns to trades_df
    _load_close_prices  -- helper to load close price Series from cmc_features

Usage:
    from ta_lab2.analysis.mae_mfe import compute_mae_mfe, _load_close_prices

    close = _load_close_prices(engine, asset_id=1, start_ts=t0, end_ts=t1, tf='1D')
    trades_with_mfe = compute_mae_mfe(trades_df, close)
"""

from __future__ import annotations

import logging
from typing import Optional

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)


def compute_mae_mfe(
    trades_df: pd.DataFrame,
    close_series: pd.Series,
) -> pd.DataFrame:
    """
    Compute Maximum Adverse Excursion (MAE) and Maximum Favorable Excursion (MFE)
    for each trade using intra-trade close prices.

    MAE and MFE are expressed as decimal fractions of entry_price:
        Long  MAE = min(window) / entry_price - 1.0   (negative = adverse)
        Long  MFE = max(window) / entry_price - 1.0   (positive = favorable)
        Short MAE = entry_price / max(window) - 1.0   (negative = adverse)
        Short MFE = entry_price / min(window) - 1.0   (positive = favorable)

    Parameters
    ----------
    trades_df : pd.DataFrame
        DataFrame with at minimum these columns:
        - entry_ts   : entry timestamp (tz-aware or tz-naive)
        - exit_ts    : exit timestamp (tz-aware or tz-naive; NaT for open trades)
        - entry_price: float, the price at trade entry
        - direction  : str, 'long' or 'short' (case-insensitive)
    close_series : pd.Series
        Close prices indexed by tz-naive timestamps, sorted ascending.
        Must cover the time range of all closed trades for accurate results.

    Returns
    -------
    pd.DataFrame
        Copy of trades_df with two new columns appended:
        - mae : float or None (None for open trades or empty price windows)
        - mfe : float or None (None for open trades or empty price windows)

    Notes
    -----
    Trades with NULL/NaT exit_ts are treated as open positions — their mae/mfe
    are set to None. The function does NOT modify trades_df in place.
    """
    result = trades_df.copy()
    mae_values: list[Optional[float]] = []
    mfe_values: list[Optional[float]] = []

    for _, row in result.iterrows():
        exit_ts = row.get("exit_ts")

        # Skip open trades (exit_ts is NaT or None)
        if exit_ts is None or (hasattr(exit_ts, "isnot") or pd.isnull(exit_ts)):
            mae_values.append(None)
            mfe_values.append(None)
            continue

        entry_ts = row["entry_ts"]
        entry_price = float(row["entry_price"])
        direction = str(row["direction"]).lower()

        # Normalize to tz-naive Timestamps for .loc[] slicing against close_series
        entry_ts_naive = _to_naive_timestamp(entry_ts)
        exit_ts_naive = _to_naive_timestamp(exit_ts)

        # Slice the window of prices for this trade
        try:
            window = close_series.loc[entry_ts_naive:exit_ts_naive]
        except Exception as exc:
            logger.debug(
                "compute_mae_mfe: window slice failed for entry=%s exit=%s: %s",
                entry_ts_naive,
                exit_ts_naive,
                exc,
            )
            mae_values.append(None)
            mfe_values.append(None)
            continue

        if window.empty:
            logger.debug(
                "compute_mae_mfe: empty window for entry=%s exit=%s",
                entry_ts_naive,
                exit_ts_naive,
            )
            mae_values.append(None)
            mfe_values.append(None)
            continue

        if direction == "long":
            mae = float(window.min() / entry_price - 1.0)
            mfe = float(window.max() / entry_price - 1.0)
        elif direction == "short":
            mae = float(entry_price / window.max() - 1.0)
            mfe = float(entry_price / window.min() - 1.0)
        else:
            logger.warning(
                "compute_mae_mfe: unknown direction '%s' — setting mae/mfe to None",
                direction,
            )
            mae_values.append(None)
            mfe_values.append(None)
            continue

        mae_values.append(mae)
        mfe_values.append(mfe)

    result["mae"] = mae_values
    result["mfe"] = mfe_values
    return result


def _to_naive_timestamp(ts) -> pd.Timestamp:
    """
    Convert a timestamp (tz-aware or tz-naive) to a tz-naive pd.Timestamp.

    CRITICAL: close_series is indexed by tz-naive timestamps. Slicing with
    tz-aware timestamps causes TypeError. This helper ensures compatibility.

    Parameters
    ----------
    ts : timestamp-like
        Any value accepted by pd.Timestamp(): datetime, string, numpy datetime64, etc.

    Returns
    -------
    pd.Timestamp
        Tz-naive Timestamp (UTC wall-clock time preserved; only tzinfo stripped).
    """
    ts_pd = pd.Timestamp(ts)
    if ts_pd.tzinfo is not None:
        ts_pd = ts_pd.tz_convert("UTC").tz_localize(None)
    return ts_pd


def _load_close_prices(
    engine: Engine,
    asset_id: int,
    start_ts: pd.Timestamp,
    end_ts: pd.Timestamp,
    tf: str = "1D",
) -> pd.Series:
    """
    Load close prices from cmc_features for a single asset and timeframe.

    The ``tf`` parameter is passed directly into the SQL query — it is NOT
    hardcoded. This allows callers to load intra-day or weekly close prices
    for MAE/MFE computation on non-daily trades.

    Parameters
    ----------
    engine : sqlalchemy.engine.Engine
        Active SQLAlchemy engine (connection pool).
    asset_id : int
        Asset ID (cmc_features.id).
    start_ts : pd.Timestamp
        Start of the range to load (inclusive).
    end_ts : pd.Timestamp
        End of the range to load (inclusive).
    tf : str
        Timeframe string (e.g. '1D', '4H', '1W'). Default '1D'.
        CRITICAL: Used in SQL WHERE clause — not hardcoded.

    Returns
    -------
    pd.Series
        Close prices indexed by tz-naive UTC timestamps, sorted ascending.
        Returns empty Series (with a logged warning) if no rows found.

    Notes
    -----
    Timestamps from pd.read_sql on PostgreSQL may have mixed timezone offsets
    on Windows. This function normalizes them to tz-naive UTC via
    pd.to_datetime(utc=True).tz_localize(None).
    """
    sql = text(
        """
        SELECT ts, close
        FROM public.cmc_features
        WHERE id    = :id
          AND tf    = :tf
          AND ts >= :start
          AND ts <= :end
        ORDER BY ts
        """
    )

    try:
        with engine.connect() as conn:
            df = pd.read_sql(
                sql,
                conn,
                params={
                    "id": asset_id,
                    "tf": tf,
                    "start": start_ts,
                    "end": end_ts,
                },
            )
    except Exception as exc:
        logger.error(
            "_load_close_prices: DB query failed for asset_id=%d tf=%s: %s",
            asset_id,
            tf,
            exc,
        )
        return pd.Series(dtype=float)

    if df.empty:
        logger.warning(
            "_load_close_prices: no rows found for asset_id=%d tf=%s start=%s end=%s",
            asset_id,
            tf,
            start_ts,
            end_ts,
        )
        return pd.Series(dtype=float)

    # CRITICAL: fix mixed-tz-offset object dtype from pd.read_sql on Windows
    # tz_localize(None) strips tzinfo after converting to UTC wall-clock time
    df["ts"] = pd.to_datetime(df["ts"], utc=True).dt.tz_localize(None)
    df = df.set_index("ts")

    close = df["close"].sort_index()

    logger.debug(
        "_load_close_prices: loaded %d rows for asset_id=%d tf=%s",
        len(close),
        asset_id,
        tf,
    )

    return close
