"""Override manager for discretionary position overrides.

Provides full CRUD operations on cmc_risk_overrides with dual audit trail:
every action writes to both cmc_risk_overrides (state) and cmc_risk_events
(immutable log). Supports sticky (persists until reverted) and non-sticky
(auto-revert after one signal cycle) modes.

Usage example::

    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool
    from ta_lab2.risk.override_manager import OverrideManager

    engine = create_engine(db_url, poolclass=NullPool)
    mgr = OverrideManager(engine)

    # Create a non-sticky override
    override_id = mgr.create_override(
        asset_id=1,
        strategy_id=2,
        operator="asafi",
        reason="Weekend liquidity concern",
        system_signal="long",
        override_action="flat",
        sticky=False,
    )

    # Mark as applied by the executor
    mgr.apply_override(override_id)

    # Identify non-sticky overrides that should be auto-reverted
    pending = mgr.get_pending_non_sticky_overrides()
    for o in pending:
        mgr.revert_override(o.override_id, reason="Auto-revert after signal cycle", operator="system")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy import text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)


@dataclass
class OverrideInfo:
    """Snapshot of a single cmc_risk_overrides row."""

    override_id: str
    asset_id: int
    strategy_id: int
    operator: str
    reason: str
    system_signal: str
    override_action: str
    sticky: bool
    created_at: datetime
    applied_at: Optional[datetime] = None
    reverted_at: Optional[datetime] = None
    revert_reason: Optional[str] = None


def _row_to_override_info(row) -> OverrideInfo:
    """Convert a SQLAlchemy Row to an OverrideInfo dataclass."""
    m = row._mapping
    return OverrideInfo(
        override_id=str(m["override_id"]),
        asset_id=m["asset_id"],
        strategy_id=m["strategy_id"],
        operator=m["operator"],
        reason=m["reason"],
        system_signal=m["system_signal"],
        override_action=m["override_action"],
        sticky=m["sticky"],
        created_at=m["created_at"],
        applied_at=m.get("applied_at"),
        reverted_at=m.get("reverted_at"),
        revert_reason=m.get("revert_reason"),
    )


class OverrideManager:
    """CRUD operations for discretionary position overrides.

    Every write operation touches both cmc_risk_overrides (state) and
    cmc_risk_events (immutable audit log) in a single transaction, ensuring
    the audit trail can never be out of sync with override state.
    """

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def create_override(
        self,
        asset_id: int,
        strategy_id: int,
        operator: str,
        reason: str,
        system_signal: str,
        override_action: str,
        sticky: bool = False,
    ) -> str:
        """Insert a new override and log override_created event.

        Args:
            asset_id: CMC asset identifier.
            strategy_id: Strategy identifier.
            operator: Username of the person creating the override.
            reason: Mandatory justification string.
            system_signal: What the system signal said (e.g. "long", "flat").
            override_action: The operator's decision (e.g. "flat", "long_10_pct").
            sticky: If True the override persists until explicitly reverted.
                If False the executor should auto-revert after one signal cycle.

        Returns:
            override_id as a string (UUID).
        """
        with self._engine.begin() as conn:
            result = conn.execute(
                text(
                    """
                    INSERT INTO public.cmc_risk_overrides
                        (asset_id, strategy_id, operator, reason,
                         system_signal, override_action, sticky)
                    VALUES
                        (:asset_id, :strategy_id, :operator, :reason,
                         :system_signal, :override_action, :sticky)
                    RETURNING override_id
                    """
                ),
                {
                    "asset_id": asset_id,
                    "strategy_id": strategy_id,
                    "operator": operator,
                    "reason": reason,
                    "system_signal": system_signal,
                    "override_action": override_action,
                    "sticky": sticky,
                },
            )
            override_id = str(result.scalar())

            conn.execute(
                text(
                    """
                    INSERT INTO public.cmc_risk_events
                        (event_type, trigger_source, reason, operator,
                         asset_id, strategy_id, override_id)
                    VALUES
                        ('override_created', 'manual', :reason, :operator,
                         :asset_id, :strategy_id, :override_id)
                    """
                ),
                {
                    "reason": reason,
                    "operator": operator,
                    "asset_id": asset_id,
                    "strategy_id": strategy_id,
                    "override_id": override_id,
                },
            )

        logger.info(
            "Override created: id=%s asset=%s strategy=%s action=%s sticky=%s operator=%s",
            override_id,
            asset_id,
            strategy_id,
            override_action,
            sticky,
            operator,
        )
        return override_id

    def apply_override(self, override_id: str) -> None:
        """Mark override as applied and log override_applied event.

        This is called by the executor when it acts on the override.
        If the override is already applied (applied_at IS NOT NULL), the
        call is a no-op (logs a warning and returns without inserting an event).

        Args:
            override_id: UUID string of the override to apply.
        """
        with self._engine.begin() as conn:
            result = conn.execute(
                text(
                    """
                    UPDATE public.cmc_risk_overrides
                    SET applied_at = now()
                    WHERE override_id = :override_id
                      AND applied_at IS NULL
                    """
                ),
                {"override_id": override_id},
            )
            if result.rowcount == 0:
                logger.warning(
                    "apply_override: no rows updated for override_id=%s "
                    "(already applied or not found)",
                    override_id,
                )
                return

            conn.execute(
                text(
                    """
                    INSERT INTO public.cmc_risk_events
                        (event_type, trigger_source, reason, override_id)
                    VALUES
                        ('override_applied', 'system',
                         'Override applied by executor', :override_id)
                    """
                ),
                {"override_id": override_id},
            )

        logger.info("Override applied: id=%s", override_id)

    def revert_override(
        self,
        override_id: str,
        reason: str,
        operator: str,
    ) -> None:
        """Revert an active override and log override_reverted event.

        If the override is already reverted (reverted_at IS NOT NULL), the
        call is a no-op (logs a warning and returns without inserting an event).

        Args:
            override_id: UUID string of the override to revert.
            reason: Why the override is being reverted.
            operator: Username performing the revert.
        """
        with self._engine.begin() as conn:
            result = conn.execute(
                text(
                    """
                    UPDATE public.cmc_risk_overrides
                    SET reverted_at = now(),
                        revert_reason = :reason
                    WHERE override_id = :override_id
                      AND reverted_at IS NULL
                    """
                ),
                {"override_id": override_id, "reason": reason},
            )
            if result.rowcount == 0:
                logger.warning(
                    "revert_override: no rows updated for override_id=%s "
                    "(already reverted or not found)",
                    override_id,
                )
                return

            conn.execute(
                text(
                    """
                    INSERT INTO public.cmc_risk_events
                        (event_type, trigger_source, reason, operator, override_id)
                    VALUES
                        ('override_reverted', 'manual', :reason, :operator, :override_id)
                    """
                ),
                {
                    "reason": reason,
                    "operator": operator,
                    "override_id": override_id,
                },
            )

        logger.info(
            "Override reverted: id=%s reason=%s operator=%s",
            override_id,
            reason,
            operator,
        )

    def get_active_overrides(
        self,
        asset_id: Optional[int] = None,
        strategy_id: Optional[int] = None,
    ) -> list[OverrideInfo]:
        """Return overrides that have not yet been reverted.

        Args:
            asset_id: Filter to a specific asset (optional).
            strategy_id: Filter to a specific strategy (optional).

        Returns:
            List of OverrideInfo ordered by created_at DESC.
        """
        filters = "WHERE reverted_at IS NULL"
        params: dict = {}

        if asset_id is not None:
            filters += " AND asset_id = :asset_id"
            params["asset_id"] = asset_id
        if strategy_id is not None:
            filters += " AND strategy_id = :strategy_id"
            params["strategy_id"] = strategy_id

        sql = text(
            f"""
            SELECT override_id, asset_id, strategy_id, operator, reason,
                   system_signal, override_action, sticky, created_at,
                   applied_at, reverted_at, revert_reason
            FROM public.cmc_risk_overrides
            {filters}
            ORDER BY created_at DESC
            """
        )

        with self._engine.connect() as conn:
            rows = conn.execute(sql, params).fetchall()

        return [_row_to_override_info(r) for r in rows]

    def get_pending_non_sticky_overrides(self) -> list[OverrideInfo]:
        """Return non-sticky overrides that have been applied but not yet reverted.

        These are the overrides the executor should auto-revert at the end of
        the current signal cycle (sticky=FALSE AND applied_at IS NOT NULL AND
        reverted_at IS NULL).

        Returns:
            List of OverrideInfo for auto-revert candidates.
        """
        sql = text(
            """
            SELECT override_id, asset_id, strategy_id, operator, reason,
                   system_signal, override_action, sticky, created_at,
                   applied_at, reverted_at, revert_reason
            FROM public.cmc_risk_overrides
            WHERE sticky = FALSE
              AND applied_at IS NOT NULL
              AND reverted_at IS NULL
            ORDER BY created_at DESC
            """
        )

        with self._engine.connect() as conn:
            rows = conn.execute(sql).fetchall()

        return [_row_to_override_info(r) for r in rows]

    def get_override(self, override_id: str) -> Optional[OverrideInfo]:
        """Fetch a single override by ID.

        Args:
            override_id: UUID string.

        Returns:
            OverrideInfo if found, None otherwise.
        """
        sql = text(
            """
            SELECT override_id, asset_id, strategy_id, operator, reason,
                   system_signal, override_action, sticky, created_at,
                   applied_at, reverted_at, revert_reason
            FROM public.cmc_risk_overrides
            WHERE override_id = :override_id
            """
        )

        with self._engine.connect() as conn:
            row = conn.execute(sql, {"override_id": override_id}).fetchone()

        if row is None:
            return None
        return _row_to_override_info(row)
