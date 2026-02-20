# src/ta_lab2/scripts/regimes/regime_flips.py
"""
DB-backed regime flip detection and writing.

Detects regime transitions (flips) per (id, tf) group across the composite
regime key and individual L0/L1/L2 layer columns. Writes results to the
``cmc_regime_flips`` table using scoped DELETE + INSERT.

Table Schema (from sql/regimes/081_cmc_regime_flips.sql):
    PK: (id, ts, tf, layer)
    Columns: old_regime (TEXT NULL), new_regime (TEXT NOT NULL),
             duration_bars (INTEGER NULL), updated_at (TIMESTAMPTZ)

Layers detected:
    - 'composite': transitions in the composite regime_key column
    - 'L0': transitions in the l0_trend column (if present)
    - 'L1': transitions in the l1_trend or l1_vol column (if present)
    - 'L2': transitions in the l2_vol or l2_liquidity column (if present)

Exports:
    detect_regime_flips: Pure function, DataFrame in -> DataFrame out
    write_flips_to_db: Write flip records to cmc_regime_flips with scoped DELETE + INSERT
"""

from __future__ import annotations

import logging
from typing import Optional

import pandas as pd
from sqlalchemy import Engine, text

logger = logging.getLogger(__name__)

# Column candidates per layer -- checked in order, first found is used
_LAYER_COLUMN_CANDIDATES: dict[str, list[str]] = {
    "composite": ["regime_key"],
    "L0": ["l0_trend", "l0_key"],
    "L1": ["l1_trend", "l1_vol", "l1_key"],
    "L2": ["l2_vol", "l2_liquidity", "l2_key"],
}


# ---------------------------------------------------------------------------
# Flip Detection (pure, no DB)
# ---------------------------------------------------------------------------


def detect_regime_flips(regime_df: pd.DataFrame) -> pd.DataFrame:
    """
    Detect regime transitions (flips) per (id, tf) group across all layers.

    Processes each (id, tf) group independently. For each layer, detects rows
    where the regime key changed from the previous row. The first row in each
    group is recorded as an initial assignment (old_regime=None).

    Args:
        regime_df: DataFrame with columns: id, ts, tf, and at least one of
                   regime_key / l0_trend / l1_trend / l2_vol / etc.
                   Must be sorted by (id, tf, ts) for correct detection.

    Returns:
        DataFrame with columns:
            id (int), ts (Timestamp), tf (str), layer (str),
            old_regime (str or None), new_regime (str),
            duration_bars (int or None)
        One row per flip event. Empty DataFrame with these columns if no flips found.

    Notes:
        - duration_bars counts the bars the old_regime persisted before the flip.
          None for the first regime assignment (no prior regime to measure).
        - Skips NaN regime values (missing labels are not counted as flips).
        - Returns consistent column schema even when regime_df is empty.
    """
    out_cols = ["id", "ts", "tf", "layer", "old_regime", "new_regime", "duration_bars"]

    if regime_df.empty:
        return pd.DataFrame(columns=out_cols)

    # Ensure sorted for correct shift() behavior
    df = regime_df.sort_values(["id", "tf", "ts"]).reset_index(drop=True)

    all_flips: list[pd.DataFrame] = []

    for (asset_id, tf), group in df.groupby(["id", "tf"], sort=False):
        group = group.reset_index(drop=True)

        for layer, col_candidates in _LAYER_COLUMN_CANDIDATES.items():
            # Find the first column candidate that exists in the DataFrame
            col = None
            for candidate in col_candidates:
                if candidate in group.columns:
                    col = candidate
                    break
            if col is None:
                continue

            regime_series = group[col].copy()

            # Skip rows with NaN regime labels
            valid_mask = regime_series.notna()
            if not valid_mask.any():
                continue

            valid_group = group[valid_mask].reset_index(drop=True)
            valid_regimes = valid_group[col]

            # Detect changes: current != previous
            prev_regimes = valid_regimes.shift(1)
            changed = valid_regimes != prev_regimes

            # First row is always an initial assignment (changed=True but old=None)
            changed.iloc[0] = True

            flip_idx = changed[changed].index.tolist()
            if not flip_idx:
                continue

            rows = []
            for pos, idx in enumerate(flip_idx):
                new_regime = valid_regimes.iloc[idx]
                old_regime = None if pos == 0 else valid_regimes.iloc[flip_idx[pos - 1]]

                # duration_bars: bars old_regime persisted
                if pos == 0:
                    duration_bars = None
                else:
                    prev_flip_idx = flip_idx[pos - 1]
                    duration_bars = int(idx - prev_flip_idx)

                rows.append(
                    {
                        "id": int(asset_id),
                        "ts": valid_group["ts"].iloc[idx],
                        "tf": tf,
                        "layer": layer,
                        "old_regime": old_regime,
                        "new_regime": str(new_regime),
                        "duration_bars": duration_bars,
                    }
                )

            if rows:
                all_flips.append(pd.DataFrame(rows))

    if not all_flips:
        return pd.DataFrame(columns=out_cols)

    result = pd.concat(all_flips, ignore_index=True)
    result["ts"] = pd.to_datetime(result["ts"], utc=True)
    return result[out_cols].reset_index(drop=True)


# ---------------------------------------------------------------------------
# DB Write
# ---------------------------------------------------------------------------


def write_flips_to_db(
    engine: Engine,
    flips_df: pd.DataFrame,
    ids: Optional[list[int]] = None,
    tf: Optional[str] = None,
) -> int:
    """
    Write flip records to ``cmc_regime_flips`` using scoped DELETE + INSERT.

    The scope is determined by ``ids`` and ``tf`` parameters. If not provided,
    they are derived from the DataFrame itself. The scoped DELETE ensures
    idempotent writes: re-running for the same (ids, tf) replaces previous results.

    Args:
        engine: SQLAlchemy engine connected to the PostgreSQL DB.
        flips_df: DataFrame output from ``detect_regime_flips``.
                  Columns: id, ts, tf, layer, old_regime, new_regime, duration_bars.
        ids: Asset IDs to scope the DELETE to. If None, derived from flips_df.
        tf: Timeframe to scope the DELETE to. If None, derived from flips_df
            (requires a single unique tf value).

    Returns:
        Number of rows inserted.

    Raises:
        ValueError: If flips_df contains multiple tf values and tf param is None.
    """
    if flips_df.empty:
        logger.debug("write_flips_to_db: empty DataFrame, nothing to write")
        return 0

    # Determine scope
    if ids is None:
        ids = sorted(flips_df["id"].unique().tolist())
    if tf is None:
        unique_tfs = flips_df["tf"].unique()
        if len(unique_tfs) != 1:
            raise ValueError(
                f"write_flips_to_db: flips_df has multiple tf values {unique_tfs}. "
                "Pass tf= parameter explicitly to scope the DELETE."
            )
        tf = str(unique_tfs[0])

    # Prepare records
    records = []
    for _, row in flips_df.iterrows():
        records.append(
            {
                "id": int(row["id"]),
                "ts": row["ts"],
                "tf": str(row["tf"]),
                "layer": str(row["layer"]),
                "old_regime": row["old_regime"]
                if pd.notna(row.get("old_regime"))
                else None,
                "new_regime": str(row["new_regime"]),
                "duration_bars": int(row["duration_bars"])
                if pd.notna(row.get("duration_bars"))
                else None,
            }
        )

    insert_sql = text(
        """
        INSERT INTO public.cmc_regime_flips
            (id, ts, tf, layer, old_regime, new_regime, duration_bars, updated_at)
        VALUES
            (:id, :ts, :tf, :layer, :old_regime, :new_regime, :duration_bars, now())
        ON CONFLICT (id, ts, tf, layer) DO UPDATE
            SET old_regime    = EXCLUDED.old_regime,
                new_regime    = EXCLUDED.new_regime,
                duration_bars = EXCLUDED.duration_bars,
                updated_at    = now()
        """
    )

    delete_sql = text(
        """
        DELETE FROM public.cmc_regime_flips
        WHERE id = ANY(:ids) AND tf = :tf
        """
    )

    with engine.begin() as conn:
        deleted = conn.execute(delete_sql, {"ids": ids, "tf": tf})
        logger.debug(
            "write_flips_to_db: deleted %d existing rows for ids=%s tf=%s",
            deleted.rowcount,
            ids,
            tf,
        )
        if records:
            conn.execute(insert_sql, records)

    n_written = len(records)
    logger.info(
        "write_flips_to_db: wrote %d flip rows for ids=%s tf=%s",
        n_written,
        ids,
        tf,
    )
    return n_written


__all__ = ["detect_regime_flips", "write_flips_to_db"]
