"""
BaseAMAFeature - Abstract base class for AMA feature computation modules.

Sibling of BaseEMAFeature (NOT a subclass). AMA tables use a different PK:
    (id, ts, tf, indicator, params_hash)
vs EMA tables which use:
    (id, ts, tf, period)

The single AMA table stores all indicator types (KAMA, DEMA, TEMA, HMA)
distinguished by the `indicator` + `params_hash` columns.

Design Pattern: Template Method
- Base class defines computation flow (load → compute → add derivatives → write)
- Subclasses implement specific data loading and TF discovery logic
- Standardises derivative computation, DB writing, column filtering

Subclasses must implement:
- _load_bars(engine, asset_id, tf, tf_days, start_ts)  -> DataFrame
- _get_timeframes(engine)                               -> list[TFSpec]
- _get_source_table_info()                              -> dict
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd
from sqlalchemy import Engine, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ta_lab2.features.ama.ama_computations import compute_ama
from ta_lab2.features.ama.ama_params import AMAParamSet

logger = logging.getLogger(__name__)


# =============================================================================
# Configuration & TFSpec
# =============================================================================


@dataclass(frozen=True)
class AMAFeatureConfig:
    """
    Configuration for AMA feature computation.

    Attributes:
        param_sets: List of AMAParamSet instances to compute.
        output_schema: Schema for the output table (e.g. "public").
        output_table: Output table name (e.g. "ama_multi_tf_u").
        alignment_source: Set for _u table writes to scope DELETE and PK.
            e.g. "multi_tf", "multi_tf_cal_us", "multi_tf_cal_iso",
                 "multi_tf_cal_anchor_us", "multi_tf_cal_anchor_iso".
            None means targeting a siloed table (no alignment_source column).
    """

    param_sets: list[AMAParamSet]
    output_schema: str
    output_table: str
    alignment_source: Optional[str] = None  # Set for _u table writes


@dataclass(frozen=True)
class TFSpec:
    """
    Timeframe specification.

    Attributes:
        tf: Timeframe label (e.g. "7D", "1M", "1D").
        tf_days: Nominal days for the timeframe (from dim_timeframe.tf_days_nominal).
    """

    tf: str
    tf_days: int


# =============================================================================
# Base AMA Feature Class
# =============================================================================


class BaseAMAFeature(ABC):
    """
    Abstract base class for AMA feature computation modules.

    Template Method Pattern:
    - Defines computation flow (load bars → compute AMAs → add derivatives → write)
    - Delegates data loading and TF discovery to subclasses
    - Standardises PK (id, ts, tf, indicator, params_hash) for all AMA tables

    Subclasses must implement:
    - _load_bars(): Load close prices for a single (asset_id, tf) slice
    - _get_timeframes(): Return the TF list relevant to this table variant
    - _get_source_table_info(): Metadata for logging/audit

    Common patterns provided by base:
    - compute_for_asset_tf(): Orchestrate AMA computation for all param_sets
    - add_derivatives(): Compute d1, d2, d1_roll, d2_roll per group
    - write_to_db(): Scoped DELETE + INSERT with column filtering
    - _pg_upsert(): ON CONFLICT DO UPDATE insert helper
    - _get_table_columns(): Query information_schema for actual columns
    - _get_pk_columns(): Returns AMA PK columns

    Windows tz pitfall: NEVER call .values on a tz-aware DatetimeIndex/Series.
    Use .tolist() or explicit tz handling instead.
    """

    def __init__(self, engine: Engine, config: AMAFeatureConfig):
        """
        Initialise AMA feature module.

        Args:
            engine: SQLAlchemy engine.
            config: Feature configuration (param_sets, output_schema, output_table).
        """
        self.engine = engine
        self.config = config
        self._bars_cache: Optional[pd.DataFrame] = None

    # =========================================================================
    # Abstract Methods (subclasses MUST override)
    # =========================================================================

    @abstractmethod
    def _load_bars(
        self,
        engine: Engine,
        asset_id: int,
        tf: str,
        tf_days: int,
        start_ts: Optional[pd.Timestamp],
        venue_id: int = 1,
    ) -> pd.DataFrame:
        """
        Load bar data (close prices) for a single (asset_id, tf, venue_id) slice.

        Args:
            engine: SQLAlchemy engine.
            asset_id: Asset primary key from dim_assets.
            tf: Timeframe label (e.g. "1D", "7D").
            tf_days: Nominal days for this TF (from dim_timeframe).
            start_ts: Optional incremental start; None means full history.
            venue_id: Venue identifier (FK to dim_venues). Default 1 (CMC_AGG).

        Returns:
            DataFrame with at minimum: ts (tz-aware TIMESTAMPTZ), close, venue_id.
            Sorted ascending by ts.
        """

    @abstractmethod
    def _get_timeframes(self, engine: Engine) -> list[TFSpec]:
        """
        Return the list of TFSpec instances to compute for this table variant.

        For multi_tf: load from dim_timeframe.
        For cal variants: derive from bars table structure.

        Args:
            engine: SQLAlchemy engine.

        Returns:
            List of TFSpec ordered however the subclass prefers.
        """

    @abstractmethod
    def _get_source_table_info(self) -> dict:
        """
        Return metadata about the source data used by this module.

        Used for logging and audit. At minimum include a "source_table" key.

        Returns:
            Dict with metadata keys (e.g. {"source_table": "price_bars_multi_tf_u"}).
        """

    # =========================================================================
    # Concrete: Computation Template
    # =========================================================================

    def compute_for_asset_tf(
        self,
        engine: Engine,
        asset_id: int,
        tf: str,
        tf_days: int,
        param_sets: list[AMAParamSet],
        start_ts: Optional[pd.Timestamp] = None,
        venue_id: int = 1,
    ) -> pd.DataFrame:
        """
        Compute AMA values + derivatives for all param_sets on one (asset_id, tf, venue_id).

        Flow:
        1. Load bars via _load_bars()
        2. For each param_set: compute_ama() -> build rows with id, venue_id, ts, tf,
           indicator, params_hash, tf_days, roll, ama, er
        3. Concatenate all param_set results
        4. Call add_derivatives() to compute d1, d2, d1_roll, d2_roll
        5. Return combined DataFrame

        Args:
            engine: SQLAlchemy engine.
            asset_id: Asset ID.
            tf: Timeframe label.
            tf_days: Nominal days for the timeframe.
            param_sets: Which AMAParamSet instances to compute.
            start_ts: Optional incremental start timestamp (inclusive).
            venue_id: Venue identifier (FK to dim_venues). Default 1 (CMC_AGG).

        Returns:
            DataFrame with columns: id, venue_id, ts, tf, indicator, params_hash,
            tf_days, roll, ama, er, d1, d2, d1_roll, d2_roll.
            Empty DataFrame if no bars or no param_sets.
        """
        if not param_sets:
            return pd.DataFrame()

        # Load bars
        bars = self._load_bars(
            engine, asset_id, tf, tf_days, start_ts, venue_id=venue_id
        )
        if bars.empty:
            logger.debug(
                "No bars for asset_id=%s tf=%s start_ts=%s — skipping",
                asset_id,
                tf,
                start_ts,
            )
            return pd.DataFrame()

        # Ensure ts is tz-aware datetime (Windows pitfall: use .tolist() if needed)
        if not hasattr(bars["ts"].dtype, "tz") or bars["ts"].dtype.tz is None:
            bars["ts"] = pd.to_datetime(bars["ts"], utc=True)

        # Sort ascending — required for correct diff() derivatives
        bars = bars.sort_values("ts").reset_index(drop=True)

        all_rows: list[pd.DataFrame] = []

        for ps in param_sets:
            try:
                ama_values, er_values = compute_ama(
                    bars["close"], ps.indicator, ps.params
                )
            except Exception as exc:
                logger.warning(
                    "compute_ama failed for asset_id=%s tf=%s indicator=%s params_hash=%s: %s",
                    asset_id,
                    tf,
                    ps.indicator,
                    ps.params_hash,
                    exc,
                )
                continue

            # ts column: use .tolist() to preserve tz-awareness on Windows
            ts_list = bars["ts"].tolist()

            # er column: NULL (NaN) for non-KAMA indicators
            if er_values is not None:
                er_list = er_values.tolist()
            else:
                er_list = [np.nan] * len(bars)

            df_ps = pd.DataFrame(
                {
                    "id": asset_id,
                    "venue_id": venue_id,
                    "ts": ts_list,
                    "tf": tf,
                    "indicator": ps.indicator,
                    "params_hash": ps.params_hash,
                    "tf_days": tf_days,
                    "roll": bars["roll"].tolist(),
                    "ama": ama_values.tolist(),
                    "er": er_list,
                }
            )

            all_rows.append(df_ps)

        if not all_rows:
            return pd.DataFrame()

        df_combined = pd.concat(all_rows, ignore_index=True)

        # Add derivatives
        df_combined = self.add_derivatives(df_combined)

        return df_combined

    # =========================================================================
    # Concrete: Derivative Computation
    # =========================================================================

    def add_derivatives(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Add derivative columns d1, d2, d1_roll, d2_roll to an AMA DataFrame.

        Groups by (id, tf, indicator, params_hash, roll) and computes:
        - d1      = ama.diff(1)          — first derivative
        - d2      = d1.diff(1)           — second derivative
        - d1_roll = ama.diff(1) over ALL rows (same as d1 for non-calendar AMAs)
        - d2_roll = d1_roll.diff(1)

        For non-calendar (multi_tf) AMAs there is no roll=TRUE variant so
        d1_roll == d1 and d2_roll == d2 within each group. The columns are
        kept for schema compatibility with the EMA table family.

        Mirrors the pattern in ema_operations.compute_derivatives() and
        compute_rolling_derivatives_canonical().

        Args:
            df: DataFrame with columns: id, ts, tf, indicator, params_hash, roll, ama.
                Must be sorted by ts within each group (guaranteed by compute_for_asset_tf).

        Returns:
            Copy of df with d1, d2, d1_roll, d2_roll columns added.
        """
        if df.empty:
            df = df.copy()
            for col in ("d1", "d2", "d1_roll", "d2_roll"):
                df[col] = np.nan
            return df

        result = df.copy()
        group_cols = ["id", "venue_id", "tf", "indicator", "params_hash", "roll"]

        # Sort by group then ts to guarantee temporal ordering
        result = result.sort_values(group_cols + ["ts"]).reset_index(drop=True)

        # d1 and d2: within each (id, venue_id, tf, indicator, params_hash, roll) group
        result["d1"] = result.groupby(group_cols, sort=False)["ama"].diff(1)
        result["d2"] = result.groupby(group_cols, sort=False)["d1"].diff(1)

        # d1_roll and d2_roll: computed across ALL rows in unified timeline
        # (id, venue_id, tf, indicator, params_hash) — without roll in group key.
        # Re-sort by unified_cols + ts so canonical and interstitial rows
        # interleave chronologically before computing diffs.
        unified_cols = ["id", "venue_id", "tf", "indicator", "params_hash"]
        result = result.sort_values(unified_cols + ["ts"]).reset_index(drop=True)
        result["d1_roll"] = result.groupby(unified_cols, sort=False)["ama"].diff(1)
        result["d2_roll"] = result.groupby(unified_cols, sort=False)["d1_roll"].diff(1)

        return result

    # =========================================================================
    # Concrete: Database Write
    # =========================================================================

    def write_to_db(
        self,
        engine: Engine,
        df: pd.DataFrame,
        schema: str,
        table: str,
    ) -> int:
        """
        Write AMA rows to database using scoped DELETE + INSERT per (ids, tf) batch.

        Pattern (matches MEMORY.md "Feature write pattern"):
        1. Filter df columns to actual DB columns via _get_table_columns()
        2. For each unique tf in the batch:
           a. DELETE WHERE id IN (...) AND tf = ...
           b. INSERT via _pg_upsert() with ON CONFLICT DO UPDATE as safety net

        This avoids UniqueViolation on re-runs while maintaining clean incremental
        writes (existing rows for newer ts not in this batch are NOT deleted).

        Args:
            engine: SQLAlchemy engine.
            df: DataFrame with AMA rows to write.
            schema: Target schema name.
            table: Target table name.

        Returns:
            Number of rows inserted/updated.
        """
        if df.empty:
            return 0

        # Get actual DB columns to avoid mismatch errors
        db_cols = self._get_table_columns(engine, schema, table)
        if not db_cols:
            # Table doesn't exist yet — write all columns
            df_write = df.copy()
        else:
            # Filter to columns present in both df and db
            overlap = [c for c in db_cols if c in df.columns]
            df_write = df[overlap].copy()

        if df_write.empty:
            return 0

        # Stamp alignment_source on df_write after column filtering.
        # The source DataFrame never has this column; we add it here so that
        # to_sql() includes it in the INSERT and the ON CONFLICT logic uses it.
        if self.config.alignment_source:
            df_write["alignment_source"] = self.config.alignment_source

        unique_ids = df_write["id"].unique().tolist()
        unique_tfs = df_write["tf"].unique().tolist()

        total_rows = 0

        with engine.begin() as conn:
            for tf in unique_tfs:
                tf_mask = df_write["tf"] == tf
                df_tf = df_write[tf_mask]
                ids_for_tf = df_tf["id"].unique().tolist()

                if not ids_for_tf:
                    continue

                # Scoped DELETE: remove existing rows for this (ids, venue_id, tf, ts>=min_ts) slice
                # Only delete rows from min_ts onwards to preserve older history
                # during incremental refreshes (where start_ts limits loaded bars).
                # CRITICAL for _u tables: scope by alignment_source to avoid wiping
                # rows from other alignment_sources in the shared table.
                ids_placeholder = ", ".join(str(i) for i in ids_for_tf)
                min_ts = df_tf["ts"].min()
                # Get distinct venue_ids in this batch
                venue_ids_for_tf = (
                    df_tf["venue_id"].unique().tolist()
                    if "venue_id" in df_tf.columns
                    else [1]
                )
                venue_ids_placeholder = ", ".join(str(v) for v in venue_ids_for_tf)
                if self.config.alignment_source:
                    delete_sql = text(
                        f"DELETE FROM {schema}.{table} "
                        f"WHERE id IN ({ids_placeholder}) AND venue_id IN ({venue_ids_placeholder}) "
                        f"AND tf = :tf AND ts >= :min_ts "
                        f"AND alignment_source = :alignment_source"
                    )
                    conn.execute(
                        delete_sql,
                        {
                            "tf": tf,
                            "min_ts": min_ts,
                            "alignment_source": self.config.alignment_source,
                        },
                    )
                else:
                    delete_sql = text(
                        f"DELETE FROM {schema}.{table} "
                        f"WHERE id IN ({ids_placeholder}) AND venue_id IN ({venue_ids_placeholder}) "
                        f"AND tf = :tf AND ts >= :min_ts"
                    )
                    conn.execute(delete_sql, {"tf": tf, "min_ts": min_ts})

            # INSERT the full batch (all tfs) using _pg_upsert safety net
            # We use to_sql with the custom _pg_upsert method
            _ = unique_ids  # referenced above to keep linter happy

        # Deduplicate on PK columns to prevent CardinalityViolation
        # ("ON CONFLICT DO UPDATE command cannot affect row a second time")
        pk_cols = self._get_pk_columns()
        pk_overlap = [c for c in pk_cols if c in df_write.columns]
        if pk_overlap:
            df_write = df_write.drop_duplicates(subset=pk_overlap, keep="last")

        # Now use to_sql for the actual insert (needs its own connection)
        rows = df_write.to_sql(
            table,
            engine,
            schema=schema,
            if_exists="append",
            index=False,
            method=self._pg_upsert,
            chunksize=10000,
        )
        total_rows = int(rows) if rows is not None else len(df_write)

        return total_rows

    def _pg_upsert(self, pd_table, conn, keys, data_iter):
        """
        Custom insert method for pandas to_sql: INSERT ... ON CONFLICT DO UPDATE.

        Used as the `method` argument to DataFrame.to_sql(). Provides a safety
        net for concurrent writes — the scoped DELETE in write_to_db handles
        most duplicates, but ON CONFLICT ensures correctness under any scenario.

        Args:
            pd_table: pandas SQLTable object (provides .table for reflected metadata).
            conn: SQLAlchemy connection (within transaction).
            keys: List of column names.
            data_iter: Iterator of row tuples.

        Returns:
            Number of rows affected.
        """
        data = [dict(zip(keys, row)) for row in data_iter]
        if not data:
            return 0

        stmt = pg_insert(pd_table.table).values(data)

        pk_cols = self._get_pk_columns()
        update_dict = {key: stmt.excluded[key] for key in keys if key not in pk_cols}

        if update_dict:
            upsert_stmt = stmt.on_conflict_do_update(
                index_elements=pk_cols,
                set_=update_dict,
            )
        else:
            upsert_stmt = stmt.on_conflict_do_nothing(index_elements=pk_cols)

        result = conn.execute(upsert_stmt)
        return result.rowcount

    # =========================================================================
    # Concrete: Helpers
    # =========================================================================

    def _get_pk_columns(self) -> list[str]:
        """
        Return AMA primary key columns.

        Siloed tables: (id, venue_id, ts, tf, indicator, params_hash)
        _u table:      (id, venue_id, ts, tf, indicator, params_hash, alignment_source)

        Returns:
            List of PK column names.
        """
        cols = ["id", "venue_id", "ts", "tf", "indicator", "params_hash"]
        if self.config.alignment_source:
            cols.append("alignment_source")
        return cols

    def _get_table_columns(
        self,
        engine: Engine,
        schema: str,
        table: str,
    ) -> list[str]:
        """
        Query information_schema for the actual columns of the target table.

        Returns an empty list if the table does not yet exist, allowing write_to_db
        to fall back to writing all df columns.

        Args:
            engine: SQLAlchemy engine.
            schema: Schema name.
            table: Table name.

        Returns:
            Ordered list of column names as they appear in the table, or [] if absent.
        """
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
                "Could not query columns for %s.%s: %s — proceeding without filtering",
                schema,
                table,
                exc,
            )
            return []

    def __repr__(self) -> str:
        n = len(self.config.param_sets)
        return (
            f"{self.__class__.__name__}("
            f"param_sets={n}, "
            f"output_table={self.config.output_schema}.{self.config.output_table})"
        )
