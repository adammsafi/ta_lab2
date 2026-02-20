"""
Regime context loading utilities for signal generators.

Provides batch loading of regime data from cmc_regimes and merging into
feature DataFrames for regime-aware signal generation.

Usage:
    from ta_lab2.scripts.signals.regime_utils import load_regime_context_batch

    regime_df = load_regime_context_batch(engine, ids, tf='1D')
    # Returns DataFrame with (id, ts, regime_key, size_mult, stop_mult, orders)
    # Empty DataFrame if cmc_regimes is empty or table doesn't exist.

Design:
    - Batch load: one SQL query for all IDs in the date range
    - Graceful fallback: if cmc_regimes is empty, returns empty DataFrame
      and callers add NULL regime columns so signals generate as before
    - No exception propagation: regime failure should never block signal generation
"""

from __future__ import annotations

import logging
from typing import Optional

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine


logger = logging.getLogger(__name__)

# Columns loaded from cmc_regimes (subset relevant for signal generation)
_REGIME_COLUMNS = [
    "id",
    "ts",
    "regime_key",
    "size_mult",
    "stop_mult",
    "orders",
]


def load_regime_context_batch(
    engine: Engine,
    ids: list[int],
    tf: str = "1D",
    start_ts: Optional[pd.Timestamp] = None,
) -> pd.DataFrame:
    """
    Batch-load regime context from cmc_regimes for all IDs in date range.

    Returns one row per (id, ts) with regime policy columns. If cmc_regimes
    is empty, or the table doesn't exist, returns an empty DataFrame so callers
    can fall back gracefully (NULL regime columns, signals generate as before).

    Args:
        engine: SQLAlchemy engine for database operations
        ids: List of asset IDs to load regime context for
        tf: Timeframe string (default: '1D')
        start_ts: Optional lower bound on ts (None = all history)

    Returns:
        DataFrame with columns: id, ts, regime_key, size_mult, stop_mult, orders
        Sorted by (id, ts). Empty DataFrame if no regime data available.
    """
    if not ids:
        return pd.DataFrame(columns=_REGIME_COLUMNS)

    columns_sql = ", ".join(_REGIME_COLUMNS)
    where_clauses = ["id = ANY(:ids)", "tf = :tf"]
    params: dict = {"ids": ids, "tf": tf}

    if start_ts is not None:
        where_clauses.append("ts >= :start_ts")
        params["start_ts"] = start_ts

    where_sql = " AND ".join(where_clauses)

    sql_text = f"""
        SELECT {columns_sql}
        FROM public.cmc_regimes
        WHERE {where_sql}
        ORDER BY id, ts
    """

    try:
        with engine.connect() as conn:
            df = pd.read_sql(text(sql_text), conn, params=params)

        if df.empty:
            logger.debug(
                f"load_regime_context_batch: no regime rows for {len(ids)} ids, tf={tf}"
            )
        else:
            logger.debug(
                f"load_regime_context_batch: loaded {len(df)} regime rows "
                f"for {df['id'].nunique()} ids, tf={tf}"
            )

        # Ensure ts is tz-aware UTC (matches feature DataFrame ts column)
        if "ts" in df.columns and not df.empty:
            df["ts"] = pd.to_datetime(df["ts"], utc=True)

        return df

    except Exception as exc:
        # Table may not exist in older environments; degrade gracefully
        logger.warning(
            f"load_regime_context_batch: failed to load regime context "
            f"(table may not exist): {exc}"
        )
        return pd.DataFrame(columns=_REGIME_COLUMNS)


def merge_regime_context(
    feature_df: pd.DataFrame,
    regime_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Left-join regime context into a feature DataFrame.

    Merges on (id, ts). Rows without a matching regime get NULL for
    regime_key, size_mult, stop_mult, orders — signals then generate
    with default sizing (no regime effect).

    Args:
        feature_df: Feature DataFrame with columns (id, ts, ...)
        regime_df: Regime DataFrame from load_regime_context_batch

    Returns:
        feature_df with added columns: regime_key, size_mult, stop_mult, orders
        If regime_df is empty, adds NULL columns and returns unchanged data.
    """
    if regime_df.empty:
        # Add NULL regime columns so downstream code can reference them safely
        result = feature_df.copy()
        result["regime_key"] = None
        result["size_mult"] = None
        result["stop_mult"] = None
        result["orders"] = None
        return result

    # Ensure ts columns are compatible types for merge
    merge_cols = ["id", "ts"]
    regime_subset = regime_df[
        merge_cols + ["regime_key", "size_mult", "stop_mult", "orders"]
    ].copy()

    merged = feature_df.merge(regime_subset, on=merge_cols, how="left")
    return merged
