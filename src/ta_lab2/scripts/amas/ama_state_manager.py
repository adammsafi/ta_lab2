"""
AMA State Manager - Incremental refresh state tracking for AMA tables.

Tracks watermarks per (id, tf, indicator, params_hash) so that AMA refresh
scripts can compute only the rows that have changed since the last run.

AMA tables use a 4-column PK:
    (id, tf, indicator, params_hash)

This is distinct from EMA state tables which use (id, tf, period).
Do NOT reuse EMAStateManager — the DDL and PK columns are different.

Usage:
    from ta_lab2.scripts.amas.ama_state_manager import AMAStateManager

    manager = AMAStateManager(engine, state_table="cmc_ama_multi_tf_state")
    manager.ensure_state_table()

    last_ts = manager.load_state(
        asset_id=1, tf="1D", indicator="KAMA", params_hash="abc123..."
    )
    if last_ts is None:
        start_ts = None  # full history
    else:
        start_ts = last_ts  # incremental from last canonical ts

    # ... compute and write rows ...

    manager.save_state(
        asset_id=1, tf="1D", indicator="KAMA", params_hash="abc123...",
        last_ts=most_recent_ts
    )
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)


# =============================================================================
# State Table DDL Template
# =============================================================================

_STATE_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS {state_table} (
    id               INTEGER     NOT NULL,
    tf               TEXT        NOT NULL,
    indicator        TEXT        NOT NULL,
    params_hash      TEXT        NOT NULL,
    last_canonical_ts TIMESTAMPTZ,
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (id, tf, indicator, params_hash)
);
"""


# =============================================================================
# AMAStateManager
# =============================================================================


class AMAStateManager:
    """
    Manages incremental refresh state for AMA tables.

    Responsibilities:
    - Ensure state table exists with (id, tf, indicator, params_hash) PK
    - Load last_canonical_ts for a single (id, tf, indicator, params_hash) tuple
    - Save/update state after a successful refresh run
    - Load all states for a given asset (for bulk incremental decisions)
    - Clear state for --full-rebuild scenarios

    Thread-safety: Not thread-safe. Create separate instances per thread/worker.

    State table naming convention:
    - cmc_ama_multi_tf        → cmc_ama_multi_tf_state
    - cmc_ama_multi_tf_cal_us → cmc_ama_multi_tf_cal_us_state
    Callers specify the state_table name at construction time.
    """

    def __init__(self, engine: Engine, state_table: str) -> None:
        """
        Initialise the state manager.

        Args:
            engine: SQLAlchemy engine for database operations.
            state_table: Fully-unqualified table name (e.g. "cmc_ama_multi_tf_state").
                         Assumed to be in the "public" schema. Pass "public.table" if
                         a different schema is needed — the DDL uses the literal string.
        """
        self.engine = engine
        self.state_table = state_table

    # =========================================================================
    # DDL
    # =========================================================================

    def ensure_state_table(self) -> None:
        """
        Create the state table if it does not already exist.

        Idempotent — safe to call on every refresh run.
        """
        ddl = _STATE_TABLE_DDL.format(state_table=self.state_table)
        with self.engine.begin() as conn:
            conn.execute(text(ddl))
        logger.debug("Ensured state table: %s", self.state_table)

    # =========================================================================
    # Load
    # =========================================================================

    def load_state(
        self,
        asset_id: int,
        tf: str,
        indicator: str,
        params_hash: str,
    ) -> Optional[datetime]:
        """
        Load the last canonical timestamp for a single (id, tf, indicator, params_hash).

        Args:
            asset_id: Asset primary key.
            tf: Timeframe label (e.g. "1D").
            indicator: Indicator name (e.g. "KAMA").
            params_hash: MD5 hash of the canonical params dict.

        Returns:
            tz-aware datetime of the last canonical row, or None if no state exists.

        Windows tz pitfall: Uses explicit pd.Timestamp with utc=True coercion rather
        than relying on .values which strips tz on Windows.
        """
        sql = text(
            f"""
            SELECT last_canonical_ts
            FROM {self.state_table}
            WHERE id = :id
              AND tf = :tf
              AND indicator = :indicator
              AND params_hash = :params_hash
            """
        )
        params = {
            "id": asset_id,
            "tf": tf,
            "indicator": indicator,
            "params_hash": params_hash,
        }

        try:
            with self.engine.connect() as conn:
                result = conn.execute(sql, params)
                row = result.fetchone()
        except Exception as exc:
            logger.debug("load_state: could not query %s — %s", self.state_table, exc)
            return None

        if row is None or row[0] is None:
            return None

        # Coerce to tz-aware datetime safely (Windows pitfall: don't use .values)
        ts_raw = row[0]
        ts = pd.Timestamp(ts_raw)
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        else:
            ts = ts.tz_convert("UTC")
        return ts.to_pydatetime()

    def load_all_states(self, asset_id: int) -> pd.DataFrame:
        """
        Load all state rows for a given asset.

        Useful when deciding start_ts for all (tf, indicator, params_hash)
        combinations in a bulk refresh.

        Args:
            asset_id: Asset primary key.

        Returns:
            DataFrame with columns: tf, indicator, params_hash, last_canonical_ts,
            updated_at. Empty DataFrame if no state exists or table absent.
        """
        sql = text(
            f"""
            SELECT tf, indicator, params_hash, last_canonical_ts, updated_at
            FROM {self.state_table}
            WHERE id = :id
            ORDER BY tf, indicator, params_hash
            """
        )
        empty = pd.DataFrame(
            columns=[
                "tf",
                "indicator",
                "params_hash",
                "last_canonical_ts",
                "updated_at",
            ]
        )
        try:
            with self.engine.connect() as conn:
                return pd.read_sql(sql, conn, params={"id": asset_id})
        except Exception as exc:
            logger.debug(
                "load_all_states: could not query %s for id=%s — %s",
                self.state_table,
                asset_id,
                exc,
            )
            return empty

    # =========================================================================
    # Save
    # =========================================================================

    def save_state(
        self,
        asset_id: int,
        tf: str,
        indicator: str,
        params_hash: str,
        last_ts: datetime,
    ) -> None:
        """
        Upsert state for a single (id, tf, indicator, params_hash).

        Uses ON CONFLICT DO UPDATE so multiple runs are idempotent.

        Args:
            asset_id: Asset primary key.
            tf: Timeframe label.
            indicator: Indicator name.
            params_hash: MD5 hash of params dict.
            last_ts: Most recent canonical timestamp written to the AMA table.
        """
        sql = text(
            f"""
            INSERT INTO {self.state_table}
                (id, tf, indicator, params_hash, last_canonical_ts, updated_at)
            VALUES
                (:id, :tf, :indicator, :params_hash, :last_canonical_ts, NOW())
            ON CONFLICT (id, tf, indicator, params_hash) DO UPDATE SET
                last_canonical_ts = EXCLUDED.last_canonical_ts,
                updated_at        = NOW()
            """
        )
        params = {
            "id": asset_id,
            "tf": tf,
            "indicator": indicator,
            "params_hash": params_hash,
            "last_canonical_ts": last_ts,
        }
        with self.engine.begin() as conn:
            conn.execute(sql, params)
        logger.debug(
            "save_state: %s id=%s tf=%s indicator=%s params_hash=%s last_ts=%s",
            self.state_table,
            asset_id,
            tf,
            indicator,
            params_hash,
            last_ts,
        )

    # =========================================================================
    # Clear (full-rebuild)
    # =========================================================================

    def clear_state(
        self,
        asset_id: int,
        tf: Optional[str] = None,
        indicator: Optional[str] = None,
    ) -> int:
        """
        Delete state rows for an asset (used by --full-rebuild scenarios).

        Args:
            asset_id: Asset primary key. Always required.
            tf: Optional timeframe filter. If None, all TFs are cleared.
            indicator: Optional indicator filter. If None, all indicators are cleared.

        Returns:
            Number of rows deleted.
        """
        where_parts = ["id = :id"]
        params: dict = {"id": asset_id}

        if tf is not None:
            where_parts.append("tf = :tf")
            params["tf"] = tf

        if indicator is not None:
            where_parts.append("indicator = :indicator")
            params["indicator"] = indicator

        where_clause = " AND ".join(where_parts)
        sql = text(f"DELETE FROM {self.state_table} WHERE {where_clause}")

        try:
            with self.engine.begin() as conn:
                result = conn.execute(sql, params)
                deleted = result.rowcount
            logger.debug(
                "clear_state: deleted %d rows from %s for id=%s tf=%s indicator=%s",
                deleted,
                self.state_table,
                asset_id,
                tf,
                indicator,
            )
            return deleted
        except Exception as exc:
            logger.warning(
                "clear_state: could not delete from %s — %s", self.state_table, exc
            )
            return 0

    # =========================================================================
    # Repr
    # =========================================================================

    def __repr__(self) -> str:
        return f"AMAStateManager(state_table={self.state_table})"
