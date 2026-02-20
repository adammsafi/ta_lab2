"""
FeaturesStore - Unified multi-TF bar-level feature store management.

This module manages cmc_features, a materialized table joining all bar-level features:
- cmc_price_bars_multi_tf (OHLCV, all timeframes)
- cmc_returns_bars_multi_tf (bar returns, canonical + roll)
- cmc_vol (volatility estimators)
- cmc_ta (technical indicators)

EMAs are NOT included (different granularity with period dimension).
Query cmc_ema_multi_tf_u and cmc_returns_ema_multi_tf_u directly.

Design:
- Dynamic column matching: DDL is the contract, JOIN builder auto-discovers columns
- Incremental refresh based on source table watermarks
- Graceful degradation when source tables missing
- Multi-TF support via tf parameter

Usage:
    from ta_lab2.scripts.features.daily_features_view import FeaturesStore

    store = FeaturesStore(engine, state_manager)
    rows = store.refresh_for_ids(ids=[1, 52], tf='1D')
"""

from __future__ import annotations

from typing import Optional
import logging

import pandas as pd
from sqlalchemy import Engine, text

from ta_lab2.scripts.features.feature_state_manager import FeatureStateManager
from ta_lab2.scripts.sync_utils import get_columns, _q

logger = logging.getLogger(__name__)


# =============================================================================
# Source table configuration
# =============================================================================

# Columns to exclude when pulling from each source table.
# These are PK, metadata, or duplicates of price_bars columns.
_RETURNS_EXCLUDE = frozenset(
    {
        "id",
        "timestamp",
        "tf",
        "tf_days",
        "bar_seq",
        "pos_in_bar",
        "count_days",
        "count_days_remaining",
        "roll",
        "time_close",
        "time_close_bar",
        "time_open_bar",
        "ingested_at",
    }
)

_VOL_EXCLUDE = frozenset(
    {
        "id",
        "ts",
        "tf",
        "tf_days",
        "open",
        "high",
        "low",
        "close",
        "updated_at",
    }
)

_TA_EXCLUDE = frozenset(
    {
        "id",
        "ts",
        "tf",
        "tf_days",
        "close",
        "atr_14",
        "updated_at",
    }
)

# Columns that need renaming to avoid conflicts across sources.
_RENAMES = {
    "returns": {"is_outlier": "ret_is_outlier"},
    "ta": {"is_outlier": "ta_is_outlier"},
}

# Source table definitions: alias, join condition template, exclude set.
_SOURCE_DEFS = {
    "returns": {
        "table": "public.cmc_returns_bars_multi_tf",
        "alias": "r",
        "join_tmpl": (
            "LEFT JOIN public.cmc_returns_bars_multi_tf r"
            ' ON p.id = r.id AND p.time_close = r."timestamp"'
            " AND r.tf = '{tf}' AND r.roll = FALSE"
        ),
        "exclude": _RETURNS_EXCLUDE,
    },
    "vol": {
        "table": "public.cmc_vol",
        "alias": "v",
        "join_tmpl": (
            "LEFT JOIN public.cmc_vol v"
            " ON p.id = v.id AND p.time_close = v.ts AND v.tf = '{tf}'"
        ),
        "exclude": _VOL_EXCLUDE,
    },
    "ta": {
        "table": "public.cmc_ta",
        "alias": "t",
        "join_tmpl": (
            "LEFT JOIN public.cmc_ta t"
            " ON p.id = t.id AND p.time_close = t.ts AND t.tf = '{tf}'"
        ),
        "exclude": _TA_EXCLUDE,
    },
}


# =============================================================================
# FeaturesStore Class
# =============================================================================


class FeaturesStore:
    """
    Manages cmc_features materialized table.

    Refresh pattern:
    1. Check which source tables exist and have data
    2. Identify dirty window (MIN of all source table watermarks)
    3. Delete rows in dirty window
    4. Re-materialize from source tables with JOIN query
    5. Update state

    Source tables (dependency order):
    1. cmc_price_bars_multi_tf (base - required)
    2. cmc_returns_bars_multi_tf (bar returns - optional)
    3. cmc_vol (depends on bars - optional)
    4. cmc_ta (depends on bars - optional)
    """

    SOURCE_TABLES = {
        "price_bars": {
            "table": "cmc_price_bars_multi_tf",
            "schema": "public",
            "required": True,
            "feature_type": "price_bars",
        },
        "returns": {
            "table": "cmc_returns_bars_multi_tf",
            "schema": "public",
            "required": False,
            "feature_type": "returns",
        },
        "vol": {
            "table": "cmc_vol",
            "schema": "public",
            "required": False,
            "feature_type": "vol",
        },
        "ta": {
            "table": "cmc_ta",
            "schema": "public",
            "required": False,
            "feature_type": "ta",
        },
    }

    def __init__(self, engine: Engine, state_manager: FeatureStateManager):
        self.engine = engine
        self.state_manager = state_manager

    def check_source_tables_exist(self) -> dict[str, bool]:
        """Check which source tables exist and have data."""
        result = {}

        for source_key, source_info in self.SOURCE_TABLES.items():
            table_name = source_info["table"]
            schema_name = source_info["schema"]

            try:
                sql = text(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM information_schema.tables
                        WHERE table_schema = :schema
                          AND table_name = :table
                    )
                """
                )

                with self.engine.connect() as conn:
                    exists = conn.execute(
                        sql, {"schema": schema_name, "table": table_name}
                    ).scalar()

                    if exists:
                        count_sql = text(
                            f"SELECT COUNT(*) FROM {schema_name}.{table_name} LIMIT 1"
                        )
                        has_data = conn.execute(count_sql).scalar() > 0
                        result[source_key] = has_data
                    else:
                        result[source_key] = False

            except Exception as e:
                logger.warning(f"Error checking source table {table_name}: {e}")
                result[source_key] = False

        return result

    def get_source_watermarks(self, ids: list[int]) -> dict[str, pd.Timestamp]:
        """Get last refresh timestamp for each source table."""
        watermarks = {}

        for source_key, source_info in self.SOURCE_TABLES.items():
            feature_type = source_info["feature_type"]

            try:
                state_df = self.state_manager.load_state(
                    ids=ids, feature_type=feature_type
                )

                if state_df.empty:
                    watermarks[source_key] = None
                    continue

                ts_series = pd.to_datetime(state_df["last_ts"], errors="coerce")
                ts_series = ts_series.dropna()

                if ts_series.empty:
                    watermarks[source_key] = None
                else:
                    watermarks[source_key] = ts_series.min()

            except Exception as e:
                logger.warning(f"Error getting watermark for {source_key}: {e}")
                watermarks[source_key] = None

        return watermarks

    def compute_dirty_window(
        self, ids: list[int], default_start: str = "2010-01-01"
    ) -> tuple[pd.Timestamp, pd.Timestamp]:
        """Compute dirty window requiring refresh."""
        watermarks = self.get_source_watermarks(ids)
        valid_watermarks = [ts for ts in watermarks.values() if ts is not None]

        if not valid_watermarks:
            start = pd.to_datetime(default_start, utc=True)
        else:
            start = min(valid_watermarks)

        end = pd.Timestamp.now(tz="UTC")
        return start, end

    def refresh_for_ids(
        self,
        ids: list[int],
        tf: str = "1D",
        start: Optional[str] = None,
        full_refresh: bool = False,
    ) -> int:
        """
        Refresh cmc_features for given IDs and timeframe.

        Args:
            ids: List of asset IDs to refresh
            tf: Timeframe code (e.g. '1D', '7D', '30D')
            start: Optional start date (ISO format)
            full_refresh: If True, delete all rows for IDs before refresh

        Returns:
            Number of rows inserted
        """
        if not ids:
            logger.warning("No IDs provided for refresh")
            return 0

        # 1. Check which source tables exist
        sources_available = self.check_source_tables_exist()
        logger.info(f"Source tables available: {sources_available}")

        if not sources_available.get("price_bars", False):
            logger.error(
                "Required table cmc_price_bars_multi_tf not available - cannot refresh"
            )
            return 0

        # 2. Compute dirty window
        if start is None:
            dirty_start, dirty_end = self.compute_dirty_window(ids)
        else:
            dirty_start = pd.to_datetime(start, utc=True)
            dirty_end = pd.Timestamp.now(tz="UTC")

        logger.info(f"Dirty window: {dirty_start} to {dirty_end}")

        # 3. Delete existing rows in dirty window
        self._delete_dirty_rows(ids, tf, dirty_start if not full_refresh else None)

        # 4. Insert refreshed data
        join_query = self._build_join_query(
            ids, tf, dirty_start.isoformat(), dirty_end.isoformat(), sources_available
        )

        with self.engine.begin() as conn:
            result = conn.execute(text(join_query))
            rows_inserted = result.rowcount

        logger.info(f"Inserted {rows_inserted} rows into cmc_features (tf={tf})")

        # 5. Update state
        self._update_state(ids)

        return rows_inserted

    def _delete_dirty_rows(
        self, ids: list[int], tf: str, start: Optional[pd.Timestamp] = None
    ) -> int:
        """Delete existing rows in dirty window for given tf."""
        where_clause = "id = ANY(:ids) AND tf = :tf"
        params = {"ids": ids, "tf": tf}

        if start is not None:
            where_clause += " AND ts >= :start"
            params["start"] = start

        delete_sql = f"""
            DELETE FROM public.cmc_features
            WHERE {where_clause}
        """

        with self.engine.begin() as conn:
            result = conn.execute(text(delete_sql), params)
            rows_deleted = result.rowcount

        logger.info(f"Deleted {rows_deleted} rows from dirty window (tf={tf})")
        return rows_deleted

    def _build_join_query(
        self,
        ids: list[int],
        tf: str,
        start: str,
        end: str,
        sources_available: dict[str, bool],
    ) -> str:
        """
        Build the JOIN query to materialize features.

        Uses dynamic column matching: queries cmc_features columns from
        information_schema, then maps each to the correct source table.
        """
        ids_list = ",".join(str(id_) for id_ in ids)

        # Discover target columns from cmc_features DDL
        target_cols = get_columns(self.engine, "public.cmc_features")

        # Discover source columns for each available source
        source_col_map: dict[str, set[str]] = {}
        for src_key, src_def in _SOURCE_DEFS.items():
            if sources_available.get(src_key, False):
                src_cols = set(get_columns(self.engine, src_def["table"]))
                source_col_map[src_key] = src_cols

        # Build column-to-source lookup (with renames)
        # For each target column, find which source provides it
        col_source: dict[str, tuple[str, str]] = {}  # target_col -> (alias, src_col)
        for src_key, src_def in _SOURCE_DEFS.items():
            if src_key not in source_col_map:
                continue
            alias = src_def["alias"]
            exclude = src_def["exclude"]
            renames = _RENAMES.get(src_key, {})

            for src_col in source_col_map[src_key]:
                if src_col in exclude:
                    continue
                # Determine target column name (after rename)
                target_name = renames.get(src_col, src_col)
                if target_name in target_cols and target_name not in col_source:
                    col_source[target_name] = (alias, src_col)

        # Explicit mappings for PK, OHLCV, derived columns
        explicit = {
            "id": "p.id",
            "ts": "p.time_close",
            "tf": f"'{tf}'",
            "tf_days": "p.tf_days",
            "asset_class": "'CRYPTO'::text",
            "open": "p.open",
            "high": "p.high",
            "low": "p.low",
            "close": "p.close",
            "volume": "p.volume",
            "updated_at": "now()",
        }

        # Build has_price_gap expression
        if sources_available.get("returns", False):
            explicit[
                "has_price_gap"
            ] = "CASE WHEN r.gap_bars > 1 THEN TRUE ELSE FALSE END"
        else:
            explicit["has_price_gap"] = "FALSE"

        # Build has_outlier expression (merged from all sources)
        outlier_parts = []
        if "ret_is_outlier" in col_source:
            outlier_parts.append("r.is_outlier")
        # Check individual vol outlier flags
        for vc in target_cols:
            if (
                vc.startswith("vol_")
                and vc.endswith("_is_outlier")
                and vc in col_source
            ):
                alias, src_col = col_source[vc]
                outlier_parts.append(f"{alias}.{_q(src_col)}")
                break  # Just need one vol outlier for the merged flag
        if "ta_is_outlier" in col_source:
            outlier_parts.append("t.is_outlier")

        if outlier_parts:
            explicit[
                "has_outlier"
            ] = f"CASE WHEN {' OR '.join(outlier_parts)} THEN TRUE ELSE FALSE END"
        else:
            explicit["has_outlier"] = "FALSE"

        # Build SELECT and INSERT column lists
        select_parts = []
        insert_cols = []

        for col in target_cols:
            if col in explicit:
                select_parts.append(f"{explicit[col]} as {_q(col)}")
                insert_cols.append(_q(col))
            elif col in col_source:
                alias, src_col = col_source[col]
                if src_col == col:
                    select_parts.append(f"{alias}.{_q(src_col)}")
                else:
                    select_parts.append(f"{alias}.{_q(src_col)} as {_q(col)}")
                insert_cols.append(_q(col))
            else:
                # Column not provided by any source — NULL
                select_parts.append(f"NULL as {_q(col)}")
                insert_cols.append(_q(col))

        # Build JOINs
        from_clause = "\n            FROM public.cmc_price_bars_multi_tf p"
        join_clauses = []
        for src_key, src_def in _SOURCE_DEFS.items():
            if sources_available.get(src_key, False):
                join_clauses.append(src_def["join_tmpl"].format(tf=tf))

        # WHERE clause
        where_clause = f"""
            WHERE p.id IN ({ids_list})
              AND p.tf = '{tf}'
              AND p.time_close >= '{start}'
              AND p.time_close <= '{end}'
        """

        # Build complete query
        query = f"""
            INSERT INTO public.cmc_features (
                {", ".join(insert_cols)}
            )
            SELECT
                {",\n                ".join(select_parts)}
            {from_clause}
                {chr(10) + '                '.join(join_clauses)}
            {where_clause}
        """

        return query

    def _update_state(self, ids: list[int]) -> None:
        """Update state after successful refresh."""
        try:
            self.state_manager.update_state_from_output(
                output_table="cmc_features",
                output_schema="public",
                feature_name="unified",
            )
            logger.info("Updated state for features")
        except Exception as e:
            logger.warning(f"Failed to update state: {e}")


# Backwards-compatible alias
DailyFeaturesStore = FeaturesStore


# =============================================================================
# Convenience Function
# =============================================================================


def refresh_features(
    engine: Engine,
    ids: list[int],
    tf: str = "1D",
    start: Optional[str] = None,
    full_refresh: bool = False,
) -> int:
    """
    Convenience function for CLI usage.

    Args:
        engine: SQLAlchemy engine
        ids: List of asset IDs to refresh
        tf: Timeframe code (e.g. '1D', '7D')
        start: Optional start date (ISO format)
        full_refresh: If True, delete all rows for IDs before refresh

    Returns:
        Number of rows inserted
    """
    from ta_lab2.scripts.features.feature_state_manager import (
        FeatureStateManager,
        FeatureStateConfig,
    )

    config = FeatureStateConfig(
        feature_type="daily_features",
        state_schema="public",
        state_table="cmc_feature_state",
    )
    state_manager = FeatureStateManager(engine, config)
    state_manager.ensure_state_table()

    store = FeaturesStore(engine, state_manager)
    return store.refresh_for_ids(ids, tf=tf, start=start, full_refresh=full_refresh)


# Backwards-compatible alias
refresh_daily_features = refresh_features
