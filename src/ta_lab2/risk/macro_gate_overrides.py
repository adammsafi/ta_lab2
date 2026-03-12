"""GateOverrideManager: per-gate macro risk override CRUD with expiry.

Provides create/read/revert/expire operations on dim_macro_gate_overrides.
Every write also inserts an immutable record to risk_events, ensuring
a complete audit trail.

Override types:
    disable_gate  -- Prevent gate from triggering (treat as normal always)
    force_normal  -- Force gate to normal state (bypass active trigger)
    force_reduce  -- Force gate to reduce state (proactive risk reduction)

Usage::

    from sqlalchemy import create_engine
    from ta_lab2.risk.macro_gate_overrides import GateOverrideManager

    engine = create_engine(db_url)
    mgr = GateOverrideManager(engine)

    # Disable the VIX gate for 6 hours (e.g., during a known volatility event)
    override_id = mgr.create_override(
        gate_id="vix",
        operator="asafi",
        reason="Known vol event -- VOLMAGEDDON anniversary spike, not fundamental",
        override_type="disable_gate",
        expires_hours=6.0,
    )

    # Check if an active override exists before evaluating
    override_type = mgr.check_override("vix")  # returns "disable_gate" or None

    # Revert early
    mgr.revert_override(override_id, reason="Resolved", operator="asafi")

    # Auto-expire stale overrides (call in daily maintenance)
    expired_count = mgr.expire_stale_overrides()
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

# Valid override types (must match dim_macro_gate_overrides CHECK constraint)
_VALID_OVERRIDE_TYPES = frozenset({"disable_gate", "force_normal", "force_reduce"})


class GateOverrideManager:
    """CRUD operations for per-gate macro risk overrides.

    Every write touches both dim_macro_gate_overrides (state) and
    risk_events (immutable audit log) in a single transaction.
    Reads use engine.connect() (read-only).
    Writes use engine.begin() (transactional).
    """

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_override(
        self,
        gate_id: str,
        operator: str,
        reason: str,
        override_type: str,
        expires_hours: float = 24.0,
    ) -> str:
        """Create a new gate override and log macro_gate_override_created event.

        Args:
            gate_id: Gate identifier (e.g., 'vix', 'fomc', 'carry').
            operator: Username of the person creating the override.
            reason: Mandatory justification string.
            override_type: One of 'disable_gate', 'force_normal', 'force_reduce'.
            expires_hours: Hours until the override auto-expires (default 24.0).

        Returns:
            override_id as a string (UUID).

        Raises:
            ValueError: If override_type is not valid.
        """
        if override_type not in _VALID_OVERRIDE_TYPES:
            raise ValueError(
                f"Invalid override_type={override_type!r}. "
                f"Must be one of: {sorted(_VALID_OVERRIDE_TYPES)}"
            )

        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(hours=expires_hours)

        with self._engine.begin() as conn:
            result = conn.execute(
                text(
                    """
                    INSERT INTO public.dim_macro_gate_overrides
                        (gate_id, operator, reason, override_type, expires_at)
                    VALUES
                        (:gate_id, :operator, :reason, :override_type, :expires_at)
                    RETURNING override_id
                    """
                ),
                {
                    "gate_id": gate_id,
                    "operator": operator,
                    "reason": reason,
                    "override_type": override_type,
                    "expires_at": expires_at,
                },
            )
            override_id = str(result.scalar())

            conn.execute(
                text(
                    """
                    INSERT INTO public.risk_events
                        (event_type, trigger_source, reason, operator, metadata)
                    VALUES
                        ('macro_gate_override_created', 'manual',
                         :reason, :operator, :metadata)
                    """
                ),
                {
                    "reason": reason,
                    "operator": operator,
                    "metadata": json.dumps(
                        {
                            "override_id": override_id,
                            "gate_id": gate_id,
                            "override_type": override_type,
                            "expires_at": expires_at.isoformat(),
                            "expires_hours": expires_hours,
                        }
                    ),
                },
            )

        logger.info(
            "Gate override created: id=%s gate=%s type=%s expires_in=%.1fh operator=%s",
            override_id,
            gate_id,
            override_type,
            expires_hours,
            operator,
        )
        return override_id

    def get_active_overrides(self, gate_id: Optional[str] = None) -> list[dict]:
        """Return active (non-reverted, non-expired) overrides.

        Args:
            gate_id: Filter to a specific gate (optional). None = all gates.

        Returns:
            List of override dicts ordered by created_at DESC.
            Each dict has keys: override_id, gate_id, operator, reason,
            override_type, expires_at, created_at.
        """
        now = datetime.now(timezone.utc)
        base_sql = """
            SELECT override_id, gate_id, operator, reason,
                   override_type, expires_at, created_at
            FROM public.dim_macro_gate_overrides
            WHERE reverted_at IS NULL
              AND expires_at > :now
        """
        params: dict = {"now": now}

        if gate_id is not None:
            base_sql += " AND gate_id = :gate_id"
            params["gate_id"] = gate_id

        base_sql += " ORDER BY created_at DESC"

        with self._engine.connect() as conn:
            rows = conn.execute(text(base_sql), params).fetchall()

        results = []
        for row in rows:
            m = row._mapping
            results.append(
                {
                    "override_id": str(m["override_id"]),
                    "gate_id": str(m["gate_id"]),
                    "operator": str(m["operator"]),
                    "reason": str(m["reason"]),
                    "override_type": str(m["override_type"]),
                    "expires_at": m["expires_at"],
                    "created_at": m["created_at"],
                }
            )

        return results

    def revert_override(
        self,
        override_id: str,
        reason: str,
        operator: str,
    ) -> bool:
        """Revert an active override and log the revert event.

        If the override is already reverted or expired, this is a no-op
        (logs a warning and returns False).

        Args:
            override_id: UUID string of the override to revert.
            reason: Why the override is being reverted.
            operator: Username performing the revert.

        Returns:
            True if override was reverted, False if already reverted or not found.
        """
        now = datetime.now(timezone.utc)

        with self._engine.begin() as conn:
            result = conn.execute(
                text(
                    """
                    UPDATE public.dim_macro_gate_overrides
                    SET reverted_at = :now,
                        revert_reason = :reason
                    WHERE override_id = :override_id
                      AND reverted_at IS NULL
                    RETURNING gate_id, override_type
                    """
                ),
                {"override_id": override_id, "now": now, "reason": reason},
            )
            row = result.fetchone()

            if row is None:
                logger.warning(
                    "revert_override: no rows updated for override_id=%s "
                    "(already reverted or not found)",
                    override_id,
                )
                return False

            gate_id = str(row[0])
            override_type = str(row[1])

            conn.execute(
                text(
                    """
                    INSERT INTO public.risk_events
                        (event_type, trigger_source, reason, operator, metadata)
                    VALUES
                        ('macro_gate_override_expired', 'manual',
                         :reason, :operator, :metadata)
                    """
                ),
                {
                    "reason": reason,
                    "operator": operator,
                    "metadata": json.dumps(
                        {
                            "override_id": override_id,
                            "gate_id": gate_id,
                            "override_type": override_type,
                            "reverted_by": operator,
                        }
                    ),
                },
            )

        logger.info(
            "Gate override reverted: id=%s gate=%s type=%s reason=%s operator=%s",
            override_id,
            gate_id,
            override_type,
            reason,
            operator,
        )
        return True

    def check_override(self, gate_id: str) -> Optional[str]:
        """Return the active override_type for a gate, or None if no active override.

        Used by MacroGateEvaluator to check per-gate overrides during evaluate().
        Returns only the first (most recently created) active override.

        Args:
            gate_id: Gate identifier (e.g., 'vix', 'fomc').

        Returns:
            override_type string ('disable_gate', 'force_normal', 'force_reduce')
            or None if no active override exists.
        """
        now = datetime.now(timezone.utc)

        with self._engine.connect() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT override_type
                    FROM public.dim_macro_gate_overrides
                    WHERE gate_id = :gate_id
                      AND reverted_at IS NULL
                      AND expires_at > :now
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
                ),
                {"gate_id": gate_id, "now": now},
            ).fetchone()

        if row is None:
            return None

        return str(row[0])

    def expire_stale_overrides(self) -> int:
        """Auto-expire overrides that have passed their expires_at timestamp.

        Marks them as reverted by 'system' with reason 'auto-expired'.
        Also logs a macro_gate_override_expired event to risk_events.

        Returns:
            Count of overrides expired.
        """
        now = datetime.now(timezone.utc)

        with self._engine.begin() as conn:
            result = conn.execute(
                text(
                    """
                    UPDATE public.dim_macro_gate_overrides
                    SET reverted_at = :now,
                        revert_reason = 'auto-expired'
                    WHERE reverted_at IS NULL
                      AND expires_at <= :now
                    RETURNING override_id, gate_id, override_type
                    """
                ),
                {"now": now},
            )
            expired_rows = result.fetchall()

            if expired_rows:
                # Log a single risk event per batch
                for row in expired_rows:
                    override_id = str(row[0])
                    gate_id = str(row[1])
                    override_type = str(row[2])

                    conn.execute(
                        text(
                            """
                            INSERT INTO public.risk_events
                                (event_type, trigger_source, reason, operator, metadata)
                            VALUES
                                ('macro_gate_override_expired', 'system',
                                 'Override auto-expired', 'system', :metadata)
                            """
                        ),
                        {
                            "metadata": json.dumps(
                                {
                                    "override_id": override_id,
                                    "gate_id": gate_id,
                                    "override_type": override_type,
                                    "expired_at": now.isoformat(),
                                }
                            ),
                        },
                    )

        count = len(expired_rows)
        if count > 0:
            logger.info(
                "Expired %d stale gate override(s): %s",
                count,
                [str(r[0]) for r in expired_rows],
            )
        return count
