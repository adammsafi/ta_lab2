"""
AMAReturnsFeature - Computes return columns for AMA value tables.

Reads AMA values from a source table (e.g. ama_multi_tf) and writes
return columns to a corresponding returns table (e.g. returns_ama_multi_tf).

Column pattern mirrors EMA returns tables but WITHOUT the _ema_bar family:

Roll columns (ALL rows, unified timeline sorted by ts):
    delta1_ama_roll, delta2_ama_roll,
    ret_arith_ama_roll, delta_ret_arith_ama_roll,
    ret_log_ama_roll, delta_ret_log_ama_roll

Canonical columns (roll=FALSE rows only, NULL for roll=TRUE rows):
    delta1_ama, delta2_ama,
    ret_arith_ama, delta_ret_arith_ama,
    ret_log_ama, delta_ret_log_ama

Gap columns:
    gap_days      (canonical subset only)
    gap_days_roll (all rows)

Z-score columns (12 total) are NOT computed here — they are handled by
refresh_returns_zscore.py in a later plan.

PK: (id, ts, tf, indicator, params_hash)
Grouping for LAG: (id, tf, indicator, params_hash)

Usage:
    from ta_lab2.features.ama.ama_returns import AMAReturnsFeature

    feature = AMAReturnsFeature(
        source_table="public.ama_multi_tf",
        returns_table="public.returns_ama_multi_tf",
        state_table="public.returns_ama_multi_tf_state",
    )
    feature.refresh(engine, asset_ids=[1, 52], tfs=["1D", "7D"])
"""

from __future__ import annotations

import logging
from datetime import datetime

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Column definitions (6 canonical + 6 roll = 12 return columns)
# ---------------------------------------------------------------------------

_ROLL_COLS = [
    "delta1_ama_roll",
    "delta2_ama_roll",
    "ret_arith_ama_roll",
    "delta_ret_arith_ama_roll",
    "ret_log_ama_roll",
    "delta_ret_log_ama_roll",
]

_CANON_COLS = [
    "delta1_ama",
    "delta2_ama",
    "ret_arith_ama",
    "delta_ret_arith_ama",
    "ret_log_ama",
    "delta_ret_log_ama",
]


# ---------------------------------------------------------------------------
# AMAReturnsFeature
# ---------------------------------------------------------------------------


class AMAReturnsFeature:
    """
    Computes AMA returns from a source AMA value table.

    This class reads AMA values and writes 12 return columns (+2 gap_days columns)
    to a returns table whose schema matches create_returns_ama_multi_tf.sql.

    The computation is grouped by (id, tf, indicator, params_hash) so that
    LAG (diff/pct_change) never crosses parameter-set boundaries.

    Roll columns are populated for ALL rows on the unified timeline.
    Canonical columns (without _roll suffix) are NULL for roll=TRUE rows.
    """

    def __init__(
        self,
        source_table: str,
        returns_table: str,
        state_table: str,
    ) -> None:
        """
        Initialise AMAReturnsFeature.

        Args:
            source_table: Fully-qualified source table, e.g. "public.ama_multi_tf".
            returns_table: Fully-qualified returns table, e.g. "public.returns_ama_multi_tf".
            state_table: Fully-qualified state table, e.g. "public.returns_ama_multi_tf_state".
        """
        self.source_table = source_table
        self.returns_table = returns_table
        self.state_table = state_table

    # =========================================================================
    # Core computation
    # =========================================================================

    def compute_returns(
        self,
        engine: Engine,
        asset_id: int,
        tf: str,
    ) -> pd.DataFrame:
        """
        Compute AMA return columns for one (asset_id, tf) slice.

        1. Loads AMA values from source_table for the given (id, tf).
        2. Groups by (id, tf, indicator, params_hash) for correct LAG.
        3. Computes roll columns on ALL rows (unified timeline by ts).
        4. Computes canonical columns on roll=FALSE rows only.
        5. Combines all groups into a single DataFrame.

        Args:
            engine: SQLAlchemy engine.
            asset_id: Asset primary key.
            tf: Timeframe label (e.g. "1D").

        Returns:
            DataFrame with PK columns + return columns. Empty if no source data.
        """
        # -- Load AMA values --------------------------------------------------
        sql = text(
            f"""
            SELECT id, ts, tf, tf_days, indicator, params_hash, roll, ama
            FROM {self.source_table}
            WHERE id = :id AND tf = :tf
            ORDER BY indicator, params_hash, ts
            """
        )
        with engine.connect() as conn:
            df_src = pd.read_sql(sql, conn, params={"id": asset_id, "tf": tf})

        if df_src.empty:
            logger.debug(
                "No AMA values in %s for id=%s tf=%s — skipping",
                self.source_table,
                asset_id,
                tf,
            )
            return pd.DataFrame()

        # Coerce ts to tz-aware UTC (Windows pitfall: use pd.to_datetime not .values)
        df_src["ts"] = pd.to_datetime(df_src["ts"], utc=True, errors="coerce")

        # -- Group by (id, tf, indicator, params_hash) ------------------------
        group_keys = ["id", "tf", "indicator", "params_hash"]
        all_groups: list[pd.DataFrame] = []

        for group_id, group_df in df_src.groupby(group_keys, sort=False):
            # group_id is a tuple: (id, tf, indicator, params_hash)
            gdf = group_df.copy().sort_values("ts").reset_index(drop=True)
            result_df = self._compute_group_returns(gdf)
            all_groups.append(result_df)

        if not all_groups:
            return pd.DataFrame()

        return pd.concat(all_groups, ignore_index=True)

    def _compute_group_returns(self, gdf: pd.DataFrame) -> pd.DataFrame:
        """
        Compute returns for a single (id, tf, indicator, params_hash) group.

        Args:
            gdf: DataFrame slice for one parameter set, sorted ascending by ts.

        Returns:
            DataFrame with all return columns added.
        """
        ama = gdf["ama"]

        # -- Roll columns: computed on ALL rows (unified timeline) ------------
        delta1_roll = ama.diff(1)
        delta2_roll = delta1_roll.diff(1)
        ret_arith_roll = ama.pct_change(1)
        delta_ret_arith_roll = ret_arith_roll.diff(1)
        # log return: log(ama[t] / ama[t-1])
        ret_log_roll = np.log(ama / ama.shift(1))
        delta_ret_log_roll = ret_log_roll.diff(1)

        # gap_days_roll: days elapsed since previous row (all rows)
        ts_series = gdf["ts"]
        gap_days_roll = (ts_series - ts_series.shift(1)).dt.total_seconds() / 86400

        gdf = gdf.copy()
        gdf["delta1_ama_roll"] = delta1_roll
        gdf["delta2_ama_roll"] = delta2_roll
        gdf["ret_arith_ama_roll"] = ret_arith_roll
        gdf["delta_ret_arith_ama_roll"] = delta_ret_arith_roll
        gdf["ret_log_ama_roll"] = ret_log_roll
        gdf["delta_ret_log_ama_roll"] = delta_ret_log_roll
        gdf["gap_days_roll"] = gap_days_roll

        # Initialise canonical columns to NaN (NULL for roll=TRUE rows)
        for col in _CANON_COLS:
            gdf[col] = np.nan
        gdf["gap_days"] = np.nan

        # -- Canonical columns: roll=FALSE rows only ---------------------------
        canon_mask = gdf["roll"] == False  # noqa: E712
        if canon_mask.any():
            canon_idx = gdf.index[canon_mask]
            canon_df = gdf.loc[canon_idx].copy()
            canon_ama = canon_df["ama"]

            c_delta1 = canon_ama.diff(1)
            c_delta2 = c_delta1.diff(1)
            c_ret_arith = canon_ama.pct_change(1)
            c_delta_ret_arith = c_ret_arith.diff(1)
            c_ret_log = np.log(canon_ama / canon_ama.shift(1))
            c_delta_ret_log = c_ret_log.diff(1)
            c_ts = canon_df["ts"]
            c_gap_days = (c_ts - c_ts.shift(1)).dt.total_seconds() / 86400

            gdf.loc[canon_idx, "delta1_ama"] = c_delta1.values
            gdf.loc[canon_idx, "delta2_ama"] = c_delta2.values
            gdf.loc[canon_idx, "ret_arith_ama"] = c_ret_arith.values
            gdf.loc[canon_idx, "delta_ret_arith_ama"] = c_delta_ret_arith.values
            gdf.loc[canon_idx, "ret_log_ama"] = c_ret_log.values
            gdf.loc[canon_idx, "delta_ret_log_ama"] = c_delta_ret_log.values
            gdf.loc[canon_idx, "gap_days"] = c_gap_days.values

        return gdf

    # =========================================================================
    # Write helpers
    # =========================================================================

    def _get_table_columns(self, engine: Engine) -> list[str]:
        """
        Query information_schema for actual columns of the returns table.

        Returns empty list if table does not exist (caller falls back to all df cols).
        """
        if "." in self.returns_table:
            schema, table = self.returns_table.split(".", 1)
        else:
            schema, table = "public", self.returns_table

        sql = text(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = :schema
              AND table_name   = :table
            ORDER BY ordinal_position
            """
        )
        try:
            with engine.connect() as conn:
                result = conn.execute(sql, {"schema": schema, "table": table})
                return [row[0] for row in result]
        except Exception as exc:
            logger.warning(
                "Could not query columns for %s: %s — proceeding without filtering",
                self.returns_table,
                exc,
            )
            return []

    def _write_returns(
        self,
        engine: Engine,
        df: pd.DataFrame,
    ) -> int:
        """
        Write returns DataFrame to the returns table using scoped DELETE + INSERT.

        Pattern (matches MEMORY.md "Feature write pattern"):
        1. Filter df columns to actual DB columns.
        2. DELETE WHERE id = :id AND tf = :tf.
        3. INSERT all rows (to_sql append with ON CONFLICT DO NOTHING as safety net).

        Args:
            engine: SQLAlchemy engine.
            df: DataFrame with returns rows for one (id, tf) slice.

        Returns:
            Number of rows written.
        """
        if df.empty:
            return 0

        # Resolve schema + table from fully-qualified returns_table
        if "." in self.returns_table:
            schema, table = self.returns_table.split(".", 1)
        else:
            schema, table = "public", self.returns_table

        # Filter to actual DB columns
        db_cols = self._get_table_columns(engine)
        if db_cols:
            overlap = [c for c in db_cols if c in df.columns]
            df_write = df[overlap].copy()
        else:
            df_write = df.copy()

        if df_write.empty:
            return 0

        asset_id = int(df_write["id"].iloc[0])
        tf = str(df_write["tf"].iloc[0])

        with engine.begin() as conn:
            conn.execute(
                text(f"DELETE FROM {self.returns_table} WHERE id = :id AND tf = :tf"),
                {"id": asset_id, "tf": tf},
            )

        # INSERT via to_sql append (ON CONFLICT DO NOTHING via method override)
        rows = df_write.to_sql(
            table,
            engine,
            schema=schema,
            if_exists="append",
            index=False,
            method=self._pg_insert_on_conflict_nothing,
            chunksize=10000,
        )
        return int(rows) if rows is not None else len(df_write)

    def _pg_insert_on_conflict_nothing(self, pd_table, conn, keys, data_iter):
        """
        Custom to_sql method: INSERT ... ON CONFLICT DO NOTHING.

        Safety net for concurrent writes; scoped DELETE in _write_returns handles
        most duplicates already.
        """
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        data = [dict(zip(keys, row)) for row in data_iter]
        if not data:
            return 0

        stmt = pg_insert(pd_table.table).values(data).on_conflict_do_nothing()
        result = conn.execute(stmt)
        return result.rowcount

    def _update_state(
        self,
        engine: Engine,
        asset_id: int,
        tf: str,
        indicator: str,
        params_hash: str,
        last_ts: datetime,
    ) -> None:
        """
        Upsert state row for one (id, tf, indicator, params_hash).

        State table DDL from create_returns_ama_multi_tf.sql:
            PK (id, tf, indicator, params_hash)
        """
        # Ensure state table exists
        self._ensure_state_table(engine)

        sql = text(
            f"""
            INSERT INTO {self.state_table}
                (id, tf, indicator, params_hash, last_ts, updated_at)
            VALUES
                (:id, :tf, :indicator, :params_hash, :last_ts, NOW())
            ON CONFLICT (id, tf, indicator, params_hash) DO UPDATE SET
                last_ts    = EXCLUDED.last_ts,
                updated_at = NOW()
            """
        )
        with engine.begin() as conn:
            conn.execute(
                sql,
                {
                    "id": asset_id,
                    "tf": tf,
                    "indicator": indicator,
                    "params_hash": params_hash,
                    "last_ts": last_ts,
                },
            )

    def _ensure_state_table(self, engine: Engine) -> None:
        """Create the state table if it does not exist."""
        ddl = text(
            f"""
            CREATE TABLE IF NOT EXISTS {self.state_table} (
                id          bigint      NOT NULL,
                tf          text        NOT NULL,
                indicator   text        NOT NULL,
                params_hash text        NOT NULL,
                last_ts     timestamptz,
                updated_at  timestamptz NOT NULL DEFAULT now(),
                PRIMARY KEY (id, tf, indicator, params_hash)
            )
            """
        )
        with engine.begin() as conn:
            conn.execute(ddl)

    # =========================================================================
    # Public refresh entry point
    # =========================================================================

    def refresh(
        self,
        engine: Engine,
        asset_ids: list[int],
        tfs: list[str],
    ) -> None:
        """
        Compute and write AMA returns for all (asset_id, tf) combinations.

        For each (asset_id, tf):
        1. compute_returns() -> DataFrame with 12 return columns + gap_days
        2. _write_returns()  -> scoped DELETE + INSERT into returns_table
        3. _update_state()   -> upsert watermark per (id, tf, indicator, params_hash)

        Args:
            engine: SQLAlchemy engine.
            asset_ids: List of asset IDs to refresh.
            tfs: List of timeframe labels to refresh.
        """
        total_processed = 0
        total_rows = 0

        for asset_id in asset_ids:
            for tf in tfs:
                try:
                    df = self.compute_returns(engine, asset_id, tf)
                    if df.empty:
                        logger.debug(
                            "No returns computed for id=%s tf=%s — skipping write",
                            asset_id,
                            tf,
                        )
                        continue

                    n_rows = self._write_returns(engine, df)
                    total_rows += n_rows
                    total_processed += 1

                    # Update state per (indicator, params_hash) combination
                    group_keys = ["indicator", "params_hash"]
                    for (indicator, params_hash), grp in df.groupby(group_keys):
                        # Get the max ts for this group (use canonical rows if possible)
                        canon_mask = grp["roll"] == False  # noqa: E712
                        if canon_mask.any():
                            last_ts = grp.loc[canon_mask, "ts"].max()
                        else:
                            last_ts = grp["ts"].max()

                        # Convert to tz-aware datetime safely (Windows pitfall)
                        if hasattr(last_ts, "to_pydatetime"):
                            last_ts_dt = last_ts.to_pydatetime()
                        else:
                            last_ts_dt = (
                                pd.Timestamp(last_ts).tz_localize("UTC").to_pydatetime()
                            )

                        self._update_state(
                            engine,
                            asset_id=asset_id,
                            tf=tf,
                            indicator=str(indicator),
                            params_hash=str(params_hash),
                            last_ts=last_ts_dt,
                        )

                    logger.info(
                        "id=%s tf=%s -> %d rows written to %s",
                        asset_id,
                        tf,
                        n_rows,
                        self.returns_table,
                    )

                except Exception as exc:
                    logger.error(
                        "Failed to compute/write returns for id=%s tf=%s: %s",
                        asset_id,
                        tf,
                        exc,
                        exc_info=True,
                    )

        logger.info(
            "refresh complete: %d (id, tf) pairs processed, %d rows written to %s",
            total_processed,
            total_rows,
            self.returns_table,
        )

    def __repr__(self) -> str:
        return (
            f"AMAReturnsFeature("
            f"source={self.source_table}, "
            f"returns={self.returns_table})"
        )
