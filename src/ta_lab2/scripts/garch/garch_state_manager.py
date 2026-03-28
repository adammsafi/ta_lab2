"""
GARCH State Manager - tracks refit timestamps and consecutive failures per asset.

Manages the garch_state table which records:
- When each (id, venue_id, tf, model_type) combination was last successfully refit
- How many consecutive convergence failures have occurred
- Refit cadence (daily / weekly / etc.)

Usage::

    from ta_lab2.scripts.garch.garch_state_manager import GARCHStateManager, GARCHStateConfig

    config = GARCHStateConfig()
    manager = GARCHStateManager(engine, config)
    manager.ensure_state_table()

    manager.update_state(
        id=1, venue_id=1, tf="1D", model_type="garch_1_1",
        converged=True, ts=datetime.now(tz=timezone.utc)
    )

    assets_due = manager.get_assets_needing_refit(current_ts=datetime.now(tz=timezone.utc))
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GARCHStateConfig:
    """Configuration for GARCH state management.

    Attributes:
        state_schema: Schema containing the state table (default: "public").
        state_table: Name of the state table (default: "garch_state").
    """

    state_schema: str = "public"
    state_table: str = "garch_state"


# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

_STATE_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS {schema}.{table} (
    id                      INTEGER         NOT NULL,
    venue_id                SMALLINT        NOT NULL,
    tf                      TEXT            NOT NULL,
    model_type              TEXT            NOT NULL,
    last_refit_ts           TIMESTAMPTZ,
    last_successful_ts      TIMESTAMPTZ,
    consecutive_failures    INTEGER         NOT NULL DEFAULT 0,
    refit_cadence           TEXT            NOT NULL DEFAULT 'daily',
    updated_at              TIMESTAMPTZ     NOT NULL DEFAULT now(),
    PRIMARY KEY (id, venue_id, tf, model_type)
);
"""


# ---------------------------------------------------------------------------
# State Manager
# ---------------------------------------------------------------------------


class GARCHStateManager:
    """Manages state tables for GARCH forecast refresh scripts.

    Responsibilities:
    - Ensure the garch_state table exists.
    - Load existing state for one or more assets.
    - Update state after a refit attempt (converged or failed).
    - Identify assets that are due for a refit based on cadence.

    Thread-safety: Not thread-safe. Create separate instances per thread.
    """

    def __init__(self, engine: Engine, config: GARCHStateConfig | None = None) -> None:
        """Initialise state manager.

        Args:
            engine: SQLAlchemy engine for database operations.
            config: State management configuration (defaults to GARCHStateConfig()).
        """
        self.engine = engine
        self.config = config if config is not None else GARCHStateConfig()

    # ------------------------------------------------------------------
    # DDL
    # ------------------------------------------------------------------

    def ensure_state_table(self) -> None:
        """Create garch_state table if it does not already exist.

        This method is idempotent -- safe to call every script run.
        """
        ddl = _STATE_TABLE_DDL.format(
            schema=self.config.state_schema,
            table=self.config.state_table,
        )
        with self.engine.begin() as conn:
            conn.execute(text(ddl))

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def load_state(self, ids: list[int] | None = None) -> pd.DataFrame:
        """Load state rows from the state table.

        Args:
            ids: Optional list of asset IDs to filter. Pass None to load all.

        Returns:
            DataFrame with columns:
                id, venue_id, tf, model_type, last_refit_ts,
                last_successful_ts, consecutive_failures, refit_cadence, updated_at.
            Returns empty DataFrame if the table does not exist or no rows match.
        """
        if ids is not None:
            where_sql = "WHERE id = ANY(:ids)"
            params: dict = {"ids": ids}
        else:
            where_sql = ""
            params = {}

        sql_text = f"""
            SELECT
                id,
                venue_id,
                tf,
                model_type,
                last_refit_ts,
                last_successful_ts,
                consecutive_failures,
                refit_cadence,
                updated_at
            FROM {self.config.state_schema}.{self.config.state_table}
            {where_sql}
            ORDER BY id, venue_id, tf, model_type
        """

        with self.engine.connect() as conn:
            try:
                return pd.read_sql(text(sql_text), conn, params=params)
            except Exception:
                # Table does not exist yet or no rows match
                return pd.DataFrame(
                    columns=[
                        "id",
                        "venue_id",
                        "tf",
                        "model_type",
                        "last_refit_ts",
                        "last_successful_ts",
                        "consecutive_failures",
                        "refit_cadence",
                        "updated_at",
                    ]
                )

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def update_state(
        self,
        id: int,
        venue_id: int,
        tf: str,
        model_type: str,
        converged: bool,
        ts: datetime,
    ) -> None:
        """Upsert state for one (id, venue_id, tf, model_type) combination.

        - Always updates last_refit_ts and updated_at.
        - If converged=True: resets consecutive_failures to 0 and sets last_successful_ts.
        - If converged=False: increments consecutive_failures.

        Args:
            id: Asset ID.
            venue_id: Venue ID.
            tf: Timeframe string (e.g. "1D").
            model_type: GARCH model type key (e.g. "garch_1_1").
            converged: Whether the fit converged.
            ts: Timestamp of this refit attempt.
        """
        if converged:
            sql = text(f"""
                INSERT INTO {self.config.state_schema}.{self.config.state_table}
                    (id, venue_id, tf, model_type,
                     last_refit_ts, last_successful_ts,
                     consecutive_failures, updated_at)
                VALUES
                    (:id, :venue_id, :tf, :model_type,
                     :ts, :ts,
                     0, now())
                ON CONFLICT (id, venue_id, tf, model_type) DO UPDATE SET
                    last_refit_ts       = EXCLUDED.last_refit_ts,
                    last_successful_ts  = EXCLUDED.last_successful_ts,
                    consecutive_failures = 0,
                    updated_at          = EXCLUDED.updated_at
            """)
            params: dict = {
                "id": id,
                "venue_id": venue_id,
                "tf": tf,
                "model_type": model_type,
                "ts": ts,
            }
        else:
            sql = text(f"""
                INSERT INTO {self.config.state_schema}.{self.config.state_table}
                    (id, venue_id, tf, model_type,
                     last_refit_ts,
                     consecutive_failures, updated_at)
                VALUES
                    (:id, :venue_id, :tf, :model_type,
                     :ts,
                     1, now())
                ON CONFLICT (id, venue_id, tf, model_type) DO UPDATE SET
                    last_refit_ts        = EXCLUDED.last_refit_ts,
                    consecutive_failures = {self.config.state_schema}.{self.config.state_table}.consecutive_failures + 1,
                    updated_at           = EXCLUDED.updated_at
            """)
            params = {
                "id": id,
                "venue_id": venue_id,
                "tf": tf,
                "model_type": model_type,
                "ts": ts,
            }

        with self.engine.begin() as conn:
            conn.execute(sql, params)

    # ------------------------------------------------------------------
    # Scheduling helper
    # ------------------------------------------------------------------

    def get_assets_needing_refit(
        self,
        current_ts: datetime,
    ) -> list[tuple[int, int, str]]:
        """Return a list of (id, venue_id, tf) tuples that need a refit.

        An asset/tf combination is considered due for a refit when:
        - It has no last_successful_ts (never successfully fit), OR
        - The calendar day of last_successful_ts is before the calendar day of
          current_ts (i.e. a new day has started).

        Only unique (id, venue_id, tf) tuples are returned; the calling script
        is responsible for iterating over model types.

        Args:
            current_ts: The reference timestamp (typically ``datetime.now(utc)``).

        Returns:
            Sorted list of (id, venue_id, tf) tuples.
        """
        current_date = current_ts.date() if hasattr(current_ts, "date") else current_ts

        sql = text(f"""
            SELECT DISTINCT id, venue_id, tf
            FROM {self.config.state_schema}.{self.config.state_table}
            WHERE last_successful_ts IS NULL
               OR DATE(last_successful_ts AT TIME ZONE 'UTC') < :current_date
            ORDER BY id, venue_id, tf
        """)

        with self.engine.connect() as conn:
            try:
                result = conn.execute(sql, {"current_date": current_date})
                return [(row[0], row[1], row[2]) for row in result.fetchall()]
            except Exception:
                return []

    # ------------------------------------------------------------------
    # Repr
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"GARCHStateManager("
            f"state_table={self.config.state_schema}.{self.config.state_table})"
        )
