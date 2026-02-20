# src/ta_lab2/scripts/regimes/regime_stats.py
"""
DB-backed regime statistics computation and writing.

Computes per-asset, per-regime summary statistics (n_bars, pct_of_history,
avg_ret_1d, std_ret_1d) and writes them to ``cmc_regime_stats``.

Table Schema (from sql/regimes/082_cmc_regime_stats.sql):
    PK: (id, tf, regime_key)
    Columns: n_bars, pct_of_history, avg_ret_1d, std_ret_1d, computed_at

The ``regime_df`` is expected to have a ``regime_key`` column (the composite key).
The optional ``returns_df`` provides 1D forward returns aligned on (id, ts, tf).
If returns_df is None or missing the required columns, return stats are NaN.

Exports:
    compute_regime_stats: Pure function, DataFrame in -> DataFrame out
    write_stats_to_db: Write stats to cmc_regime_stats with scoped DELETE + INSERT
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd
from sqlalchemy import Engine, text

logger = logging.getLogger(__name__)

# Column name for 1D forward return in the merged DataFrame
_RET_COL = "ret_1d"

# Possible return column names to auto-detect from the returns DataFrame
_RET_COL_CANDIDATES = [
    "ret_1d",
    "close_ret_1d",
    "close_ret_1",
    "ret_close_1d",
    "return_1d",
]


# ---------------------------------------------------------------------------
# Stats Computation (pure, no DB)
# ---------------------------------------------------------------------------


def compute_regime_stats(
    regime_df: pd.DataFrame,
    returns_df: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """
    Compute per-asset, per-regime summary statistics.

    Groups by (id, tf, regime_key) and computes:
    - n_bars: Total bars where this regime was active.
    - pct_of_history: Fraction of total bars for that (id, tf) in this regime.
    - avg_ret_1d: Mean 1D forward return (NaN if returns unavailable).
    - std_ret_1d: Std dev of 1D forward returns (NaN if returns unavailable).

    Args:
        regime_df: DataFrame with columns: id, ts, tf, regime_key.
                   Each row is one bar with a composite regime label assigned.
        returns_df: Optional DataFrame with columns: id, ts, tf, and a return
                    column (auto-detected from _RET_COL_CANDIDATES).
                    Joined onto regime_df by (id, ts, tf) before aggregation.
                    Pass None to compute stats without return metrics.

    Returns:
        DataFrame with columns:
            id (int), tf (str), regime_key (str),
            n_bars (int), pct_of_history (float),
            avg_ret_1d (float or NaN), std_ret_1d (float or NaN)
        One row per (id, tf, regime_key) combination.
        Empty DataFrame with these columns if regime_df is empty.

    Notes:
        - Rows with NaN regime_key are excluded before grouping.
        - pct_of_history sums to approximately 1.0 across all regime_keys
          for each (id, tf) pair.
        - std_ret_1d uses ddof=1 (sample std dev), matching pandas default.
        - If returns_df has no data or no matching (id, ts, tf) rows,
          avg_ret_1d and std_ret_1d will be NaN without error.
    """
    out_cols = [
        "id",
        "tf",
        "regime_key",
        "n_bars",
        "pct_of_history",
        "avg_ret_1d",
        "std_ret_1d",
    ]

    if regime_df.empty:
        return pd.DataFrame(columns=out_cols)

    required = ["id", "ts", "tf", "regime_key"]
    missing = [c for c in required if c not in regime_df.columns]
    if missing:
        logger.warning(
            "compute_regime_stats: missing required columns %s in regime_df", missing
        )
        return pd.DataFrame(columns=out_cols)

    # Drop rows with NaN regime_key
    df = regime_df[required].copy()
    df = df[df["regime_key"].notna()].reset_index(drop=True)

    if df.empty:
        return pd.DataFrame(columns=out_cols)

    # Merge returns if provided
    ret_col_used = None
    if returns_df is not None and not returns_df.empty:
        # Auto-detect return column
        for candidate in _RET_COL_CANDIDATES:
            if candidate in returns_df.columns:
                ret_col_used = candidate
                break

        if ret_col_used is not None:
            join_cols = ["id", "ts", "tf"]
            missing_join = [c for c in join_cols if c not in returns_df.columns]
            if missing_join:
                logger.warning(
                    "compute_regime_stats: returns_df missing join columns %s, "
                    "skipping return metrics",
                    missing_join,
                )
                ret_col_used = None
            else:
                ret_subset = returns_df[join_cols + [ret_col_used]].copy()
                df = df.merge(ret_subset, on=join_cols, how="left")
        else:
            logger.debug(
                "compute_regime_stats: no recognized return column in returns_df "
                "(checked %s), skipping return metrics",
                _RET_COL_CANDIDATES,
            )

    # Compute total bars per (id, tf) for pct_of_history denominator
    total_bars = (
        df.groupby(["id", "tf"], sort=False).size().rename("total_bars").reset_index()
    )

    # Group by (id, tf, regime_key)
    group_keys = ["id", "tf", "regime_key"]

    if ret_col_used is not None and ret_col_used in df.columns:
        agg = df.groupby(group_keys, sort=False, dropna=False).agg(
            n_bars=("ts", "count"),
            avg_ret_1d=(ret_col_used, "mean"),
            std_ret_1d=(
                ret_col_used,
                lambda x: float(np.std(x.dropna(), ddof=1))
                if len(x.dropna()) > 1
                else np.nan,
            ),
        )
    else:
        agg = df.groupby(group_keys, sort=False, dropna=False).agg(
            n_bars=("ts", "count"),
        )
        agg["avg_ret_1d"] = np.nan
        agg["std_ret_1d"] = np.nan

    stats = agg.reset_index()

    # Merge total_bars and compute pct_of_history
    stats = stats.merge(total_bars, on=["id", "tf"], how="left")
    stats["pct_of_history"] = stats["n_bars"] / stats["total_bars"]
    stats = stats.drop(columns=["total_bars"])

    # Cast types
    stats["id"] = stats["id"].astype(int)
    stats["n_bars"] = stats["n_bars"].astype(int)
    stats["regime_key"] = stats["regime_key"].astype(str)

    return stats[out_cols].reset_index(drop=True)


# ---------------------------------------------------------------------------
# DB Write
# ---------------------------------------------------------------------------


def write_stats_to_db(
    engine: Engine,
    stats_df: pd.DataFrame,
    ids: Optional[list[int]] = None,
    tf: Optional[str] = None,
) -> int:
    """
    Write regime stats to ``cmc_regime_stats`` using scoped DELETE + INSERT.

    Args:
        engine: SQLAlchemy engine connected to the PostgreSQL DB.
        stats_df: DataFrame output from ``compute_regime_stats``.
                  Columns: id, tf, regime_key, n_bars, pct_of_history,
                           avg_ret_1d, std_ret_1d.
        ids: Asset IDs to scope the DELETE to. If None, derived from stats_df.
        tf: Timeframe to scope the DELETE to. If None, derived from stats_df
            (requires a single unique tf value).

    Returns:
        Number of rows inserted.

    Raises:
        ValueError: If stats_df contains multiple tf values and tf param is None.
    """
    if stats_df.empty:
        logger.debug("write_stats_to_db: empty DataFrame, nothing to write")
        return 0

    if ids is None:
        ids = sorted(stats_df["id"].unique().tolist())
    if tf is None:
        unique_tfs = stats_df["tf"].unique()
        if len(unique_tfs) != 1:
            raise ValueError(
                f"write_stats_to_db: stats_df has multiple tf values {unique_tfs}. "
                "Pass tf= parameter explicitly."
            )
        tf = str(unique_tfs[0])

    def _nan_to_none(val):
        if val is None:
            return None
        try:
            if np.isnan(val):
                return None
        except (TypeError, ValueError):
            pass
        return float(val)

    records = []
    for _, row in stats_df.iterrows():
        records.append(
            {
                "id": int(row["id"]),
                "tf": str(row["tf"]),
                "regime_key": str(row["regime_key"]),
                "n_bars": int(row["n_bars"]),
                "pct_of_history": _nan_to_none(row.get("pct_of_history")),
                "avg_ret_1d": _nan_to_none(row.get("avg_ret_1d")),
                "std_ret_1d": _nan_to_none(row.get("std_ret_1d")),
            }
        )

    delete_sql = text(
        """
        DELETE FROM public.cmc_regime_stats
        WHERE id = ANY(:ids) AND tf = :tf
        """
    )

    insert_sql = text(
        """
        INSERT INTO public.cmc_regime_stats
            (id, tf, regime_key, n_bars, pct_of_history, avg_ret_1d, std_ret_1d, computed_at)
        VALUES
            (:id, :tf, :regime_key, :n_bars, :pct_of_history, :avg_ret_1d, :std_ret_1d, now())
        ON CONFLICT (id, tf, regime_key) DO UPDATE
            SET n_bars         = EXCLUDED.n_bars,
                pct_of_history = EXCLUDED.pct_of_history,
                avg_ret_1d     = EXCLUDED.avg_ret_1d,
                std_ret_1d     = EXCLUDED.std_ret_1d,
                computed_at    = now()
        """
    )

    with engine.begin() as conn:
        deleted = conn.execute(delete_sql, {"ids": ids, "tf": tf})
        logger.debug(
            "write_stats_to_db: deleted %d existing rows for ids=%s tf=%s",
            deleted.rowcount,
            ids,
            tf,
        )
        if records:
            conn.execute(insert_sql, records)

    n_written = len(records)
    logger.info(
        "write_stats_to_db: wrote %d stats rows for ids=%s tf=%s",
        n_written,
        ids,
        tf,
    )
    return n_written


__all__ = ["compute_regime_stats", "write_stats_to_db"]
