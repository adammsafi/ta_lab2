# src/ta_lab2/scripts/regimes/regime_comovement.py
"""
DB-backed EMA comovement statistics computation and writing.

Computes pairwise EMA comovement metrics (correlation, sign agreement rate,
lead-lag) for a single asset/TF and writes them to ``cmc_regime_comovement``.

Uses the analytics functions from ta_lab2.regimes.comovement:
- ``compute_ema_comovement_stats``: correlation matrix + sign agreement rate per EMA pair
- ``lead_lag_max_corr``: cross-correlation over lag range to find best lead-lag relationship

Table Schema (from sql/regimes/084_cmc_regime_comovement.sql):
    PK: (id, tf, ema_a, ema_b, computed_at)
    Columns: correlation, sign_agree_rate, best_lead_lag, best_lead_lag_corr, n_obs

NOTE: ``computed_at`` is part of the PK, so each refresh inserts a new snapshot
row rather than overwriting. Scoped DELETE + INSERT uses the current timestamp
to create a fresh snapshot.

Exports:
    compute_and_write_comovement: Load stats and write to DB in one step
    write_comovement_to_db: Write pre-computed comovement records to DB
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import itertools
import numpy as np
import pandas as pd
from sqlalchemy import Engine, text

from ta_lab2.regimes.comovement import compute_ema_comovement_stats, lead_lag_max_corr

logger = logging.getLogger(__name__)

# Auto-detect EMA columns by this substring token (matches comovement.py convention)
_EMA_TOKEN = "_ema_"


# ---------------------------------------------------------------------------
# Comovement Computation (pure, no DB)
# ---------------------------------------------------------------------------


def _find_ema_columns(df: pd.DataFrame) -> list[str]:
    """
    Find EMA columns in the DataFrame sorted by period (ascending).
    Matches the convention: close_ema_20, close_ema_50, close_ema_100.
    """
    cols = [c for c in df.columns if _EMA_TOKEN in c]

    def _tail_int(name: str) -> int:
        try:
            return int(name.split("_")[-1])
        except Exception:
            return 10**9

    return sorted(cols, key=_tail_int)


def compute_comovement_records(
    asset_id: int,
    daily_df: pd.DataFrame,
    tf: str = "1D",
    computed_at: Optional[datetime] = None,
) -> pd.DataFrame:
    """
    Compute pairwise EMA comovement records for one asset/TF.

    Calls ``compute_ema_comovement_stats`` for correlation and sign agreement,
    then ``lead_lag_max_corr`` for each EMA pair to find the best lead-lag.

    Args:
        asset_id: Integer asset ID.
        daily_df: Wide-format DataFrame with EMA columns (close_ema_N) and ts.
                  Typically the output of load_and_pivot_emas() merged with bars.
        tf: Timeframe string (e.g. '1D', '1W', '1M').
        computed_at: Snapshot timestamp. Defaults to now() UTC.
                     Part of the PK -- each call creates a new snapshot row.

    Returns:
        DataFrame with columns:
            id, tf, ema_a, ema_b, correlation, sign_agree_rate,
            best_lead_lag, best_lead_lag_corr, n_obs, computed_at
        One row per (ema_a, ema_b) pair. Empty DataFrame if < 2 EMA columns found.

    Notes:
        - Uses Spearman correlation (rank-based, robust to outliers) matching
          ``compute_ema_comovement_stats`` default.
        - n_obs is the number of non-NaN rows in both EMA columns used for
          correlation (conservative: count of rows where both are valid).
    """
    out_cols = [
        "id",
        "tf",
        "ema_a",
        "ema_b",
        "correlation",
        "sign_agree_rate",
        "best_lead_lag",
        "best_lead_lag_corr",
        "n_obs",
        "computed_at",
    ]

    if computed_at is None:
        computed_at = datetime.now(timezone.utc)

    if daily_df.empty:
        logger.debug(
            "compute_comovement_records: empty DataFrame for id=%s tf=%s", asset_id, tf
        )
        return pd.DataFrame(columns=out_cols)

    ema_cols = _find_ema_columns(daily_df)
    if len(ema_cols) < 2:
        logger.debug(
            "compute_comovement_records: fewer than 2 EMA columns for id=%s tf=%s "
            "(found %s)",
            asset_id,
            tf,
            ema_cols,
        )
        return pd.DataFrame(columns=out_cols)

    # Compute correlation matrix and sign agreement using the analytics module
    stats = compute_ema_comovement_stats(daily_df, ema_cols=ema_cols)
    corr_matrix = stats["corr"]  # DataFrame indexed by ema column names
    agree_df = stats["agree"]  # DataFrame with cols: a, b, agree_rate

    # Build agree_rate lookup: (a, b) -> rate
    agree_lookup: dict[tuple[str, str], float] = {}
    if not agree_df.empty:
        for _, row in agree_df.iterrows():
            agree_lookup[(str(row["a"]), str(row["b"]))] = float(row["agree_rate"])

    records = []
    for ema_a, ema_b in itertools.combinations(ema_cols, 2):
        # Correlation from matrix
        if ema_a in corr_matrix.index and ema_b in corr_matrix.columns:
            corr_val = float(corr_matrix.loc[ema_a, ema_b])
        else:
            corr_val = np.nan

        # Sign agreement rate
        sign_rate = agree_lookup.get((ema_a, ema_b), np.nan)

        # Lead-lag cross-correlation
        df_pair = daily_df[[ema_a, ema_b]].dropna()
        n_obs = int(len(df_pair))
        if n_obs >= 3:
            ll_result = lead_lag_max_corr(df_pair, ema_a, ema_b)
            best_lag = int(ll_result["best_lag"])
            best_lag_corr = (
                float(ll_result["best_corr"])
                if not np.isnan(ll_result["best_corr"])
                else None
            )
        else:
            best_lag = None
            best_lag_corr = None

        records.append(
            {
                "id": int(asset_id),
                "tf": tf,
                "ema_a": ema_a,
                "ema_b": ema_b,
                "correlation": corr_val if not np.isnan(corr_val) else None,
                "sign_agree_rate": sign_rate if not np.isnan(sign_rate) else None,
                "best_lead_lag": best_lag,
                "best_lead_lag_corr": best_lag_corr,
                "n_obs": n_obs if n_obs > 0 else None,
                "computed_at": computed_at,
            }
        )

    if not records:
        return pd.DataFrame(columns=out_cols)

    return pd.DataFrame(records)[out_cols]


# ---------------------------------------------------------------------------
# DB Write
# ---------------------------------------------------------------------------


def write_comovement_to_db(
    engine: Engine,
    comovement_df: pd.DataFrame,
    ids: Optional[list[int]] = None,
    tf: Optional[str] = None,
) -> int:
    """
    Write comovement records to ``cmc_regime_comovement`` using scoped DELETE + INSERT.

    Because ``computed_at`` is part of the PK, each refresh appends a new
    snapshot. The scoped DELETE removes ALL prior snapshots for the given (ids, tf),
    preserving only the current one. This prevents unbounded table growth while
    retaining the "latest" snapshot.

    To retain historical snapshots (time-series of comovement), omit the DELETE
    and call only the INSERT (set retain_history=True in future extension).

    Args:
        engine: SQLAlchemy engine connected to the PostgreSQL DB.
        comovement_df: DataFrame from ``compute_comovement_records``.
        ids: Asset IDs to scope DELETE to. If None, derived from comovement_df.
        tf: Timeframe to scope DELETE to. If None, derived from comovement_df.

    Returns:
        Number of rows inserted.
    """
    if comovement_df.empty:
        logger.debug("write_comovement_to_db: empty DataFrame, nothing to write")
        return 0

    if ids is None:
        ids = sorted(comovement_df["id"].unique().tolist())
    if tf is None:
        unique_tfs = comovement_df["tf"].unique()
        if len(unique_tfs) != 1:
            raise ValueError(
                f"write_comovement_to_db: comovement_df has multiple tf values {unique_tfs}. "
                "Pass tf= parameter explicitly."
            )
        tf = str(unique_tfs[0])

    def _to_none_if_nan(val):
        if val is None:
            return None
        try:
            if np.isnan(val):
                return None
        except (TypeError, ValueError):
            pass
        return val

    records = []
    for _, row in comovement_df.iterrows():
        records.append(
            {
                "id": int(row["id"]),
                "tf": str(row["tf"]),
                "ema_a": str(row["ema_a"]),
                "ema_b": str(row["ema_b"]),
                "correlation": _to_none_if_nan(row.get("correlation")),
                "sign_agree_rate": _to_none_if_nan(row.get("sign_agree_rate")),
                "best_lead_lag": int(row["best_lead_lag"])
                if row.get("best_lead_lag") is not None
                else None,
                "best_lead_lag_corr": _to_none_if_nan(row.get("best_lead_lag_corr")),
                "n_obs": int(row["n_obs"]) if row.get("n_obs") is not None else None,
                "computed_at": row["computed_at"],
            }
        )

    delete_sql = text(
        """
        DELETE FROM public.cmc_regime_comovement
        WHERE id = ANY(:ids) AND tf = :tf
        """
    )

    insert_sql = text(
        """
        INSERT INTO public.cmc_regime_comovement
            (id, tf, ema_a, ema_b, correlation, sign_agree_rate,
             best_lead_lag, best_lead_lag_corr, n_obs, computed_at)
        VALUES
            (:id, :tf, :ema_a, :ema_b, :correlation, :sign_agree_rate,
             :best_lead_lag, :best_lead_lag_corr, :n_obs, :computed_at)
        ON CONFLICT (id, tf, ema_a, ema_b, computed_at) DO UPDATE
            SET correlation       = EXCLUDED.correlation,
                sign_agree_rate   = EXCLUDED.sign_agree_rate,
                best_lead_lag     = EXCLUDED.best_lead_lag,
                best_lead_lag_corr = EXCLUDED.best_lead_lag_corr,
                n_obs             = EXCLUDED.n_obs
        """
    )

    with engine.begin() as conn:
        deleted = conn.execute(delete_sql, {"ids": ids, "tf": tf})
        logger.debug(
            "write_comovement_to_db: deleted %d existing rows for ids=%s tf=%s",
            deleted.rowcount,
            ids,
            tf,
        )
        if records:
            conn.execute(insert_sql, records)

    n_written = len(records)
    logger.info(
        "write_comovement_to_db: wrote %d comovement rows for ids=%s tf=%s",
        n_written,
        ids,
        tf,
    )
    return n_written


# ---------------------------------------------------------------------------
# Combined: compute + write
# ---------------------------------------------------------------------------


def compute_and_write_comovement(
    engine: Engine,
    asset_id: int,
    daily_df: pd.DataFrame,
    tf: str = "1D",
    computed_at: Optional[datetime] = None,
) -> int:
    """
    Compute EMA comovement statistics and write them to DB in one step.

    Convenience wrapper combining ``compute_comovement_records`` and
    ``write_comovement_to_db``. Intended for use from the regime refresh pipeline.

    Args:
        engine: SQLAlchemy engine connected to the PostgreSQL DB.
        asset_id: Integer asset ID.
        daily_df: Wide-format DataFrame with EMA columns (close_ema_N) and ts.
                  Typically returned by ``load_and_pivot_emas``.
        tf: Timeframe string (default '1D').
        computed_at: Snapshot timestamp for the PK. Defaults to now() UTC.

    Returns:
        Number of rows inserted (0 if no EMA pairs found).
    """
    if computed_at is None:
        computed_at = datetime.now(timezone.utc)

    comovement_df = compute_comovement_records(
        asset_id=asset_id,
        daily_df=daily_df,
        tf=tf,
        computed_at=computed_at,
    )

    if comovement_df.empty:
        logger.info(
            "compute_and_write_comovement: no comovement records for id=%s tf=%s",
            asset_id,
            tf,
        )
        return 0

    return write_comovement_to_db(
        engine=engine,
        comovement_df=comovement_df,
        ids=[asset_id],
        tf=tf,
    )


__all__ = [
    "compute_comovement_records",
    "compute_and_write_comovement",
    "write_comovement_to_db",
]
