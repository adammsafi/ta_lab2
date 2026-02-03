"""
Health check module for Kubernetes-style probes.

Provides:
- HealthStatus dataclass for health check results
- HealthChecker with liveness, readiness, and startup probes

Follows Kubernetes probe patterns:
- Liveness: Is process alive? (simple, fast, no dependencies)
- Readiness: Can process accept traffic? (checks dependencies)
- Startup: Has initialization completed? (one-time check)

Usage:
    from ta_lab2.observability.health import HealthChecker

    health = HealthChecker(engine, memory_client=mem_client)

    # Liveness probe (fast, no dependencies)
    liveness = health.liveness()
    if liveness.healthy:
        print("Process is alive")

    # Readiness probe (checks database, memory, etc.)
    readiness = health.readiness()
    if not readiness.healthy:
        print(f"Not ready: {readiness.message}")

    # Startup probe (checks initial data loaded)
    startup = health.startup()
    if startup.healthy:
        health.startup_complete = True
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import Engine, text

logger = logging.getLogger(__name__)


# =============================================================================
# Health Status
# =============================================================================


@dataclass
class HealthStatus:
    """
    Health check result.

    Attributes:
        healthy: True if check passed
        message: Human-readable status message
        checked_at: When check was performed
        details: Optional dict with check details (individual component status, metrics, etc.)
    """

    healthy: bool
    message: str
    checked_at: datetime
    details: Optional[dict[str, Any]] = None

    def __str__(self) -> str:
        """String representation for logging."""
        status = "HEALTHY" if self.healthy else "UNHEALTHY"
        return f"[{status}] {self.message}"


# =============================================================================
# Health Checker
# =============================================================================


class HealthChecker:
    """
    Health checker implementing Kubernetes-style probes.

    Three probe types:
    1. Liveness: Is process alive? Simple check, no dependencies.
    2. Readiness: Can process accept traffic? Checks database, memory, etc.
    3. Startup: Has initialization completed? Checks initial data loaded.

    Example:
        health = HealthChecker(engine, memory_client=mem_client)

        # Fast liveness check
        if not health.liveness().healthy:
            # Process unresponsive - restart container

        # Readiness check before accepting traffic
        if not health.readiness().healthy:
            # Dependencies not ready - remove from load balancer

        # Startup check before marking ready
        if health.startup().healthy:
            health.startup_complete = True
    """

    def __init__(
        self,
        engine: Engine,
        memory_client: Optional[Any] = None,
        config: Optional[dict[str, Any]] = None,
    ):
        """
        Initialize health checker.

        Args:
            engine: SQLAlchemy engine for database checks
            memory_client: Optional memory client for memory service checks
            config: Optional configuration dict
        """
        self.engine = engine
        self.memory_client = memory_client
        self.config = config or {}
        self._startup_complete = False

    @property
    def startup_complete(self) -> bool:
        """
        Whether startup probe has passed.

        Returns:
            True if startup completed
        """
        return self._startup_complete

    @startup_complete.setter
    def startup_complete(self, value: bool) -> None:
        """
        Set startup complete status.

        Args:
            value: New status
        """
        self._startup_complete = value

    def liveness(self) -> HealthStatus:
        """
        Liveness probe - is process alive?

        Simple check with NO external dependencies.
        Only checks that process can respond.

        Kubernetes uses this to restart unhealthy containers.

        Returns:
            HealthStatus with healthy=True (process responsive)
        """
        # Liveness is simple: if we can execute this code, process is alive
        return HealthStatus(
            healthy=True,
            message="Process is alive",
            checked_at=datetime.utcnow(),
            details={"probe_type": "liveness"},
        )

    def readiness(self) -> HealthStatus:
        """
        Readiness probe - can process accept traffic?

        Checks all dependencies:
        - Database connection
        - Memory service (if configured)

        Kubernetes uses this to add/remove pod from load balancer.

        Returns:
            HealthStatus with healthy=True only if ALL checks pass
        """
        checked_at = datetime.utcnow()
        details: dict[str, Any] = {
            "probe_type": "readiness",
            "checks": {},
        }

        # Check 1: Database connection
        db_healthy = self._check_database()
        details["checks"]["database"] = {
            "healthy": db_healthy,
            "message": "Connected" if db_healthy else "Connection failed",
        }

        # Check 2: Memory service (if configured)
        if self.memory_client:
            memory_healthy = self._check_memory_service()
            details["checks"]["memory"] = {
                "healthy": memory_healthy,
                "message": "Reachable" if memory_healthy else "Unreachable",
            }
        else:
            # Memory not required
            memory_healthy = True
            details["checks"]["memory"] = {
                "healthy": True,
                "message": "Not configured (optional)",
            }

        # Overall health: all checks must pass
        overall_healthy = db_healthy and memory_healthy

        if overall_healthy:
            message = "All dependencies healthy"
        else:
            failed = [
                name
                for name, check in details["checks"].items()
                if not check["healthy"]
            ]
            message = f"Dependencies unhealthy: {', '.join(failed)}"

        return HealthStatus(
            healthy=overall_healthy,
            message=message,
            checked_at=checked_at,
            details=details,
        )

    def startup(self) -> HealthStatus:
        """
        Startup probe - has initialization completed?

        Checks that initial data is loaded:
        - dim_timeframe has rows
        - dim_sessions has rows

        Kubernetes uses this to know when container finished initialization.
        Once passes, switches to liveness/readiness probes.

        Returns:
            HealthStatus with healthy=True if startup complete
        """
        checked_at = datetime.utcnow()
        details: dict[str, Any] = {
            "probe_type": "startup",
            "checks": {},
        }

        # Check 1: dim_timeframe populated
        timeframe_ok = self._check_table_populated("dim_timeframe")
        details["checks"]["dim_timeframe"] = {
            "healthy": timeframe_ok,
            "message": "Populated" if timeframe_ok else "Empty",
        }

        # Check 2: dim_sessions populated
        sessions_ok = self._check_table_populated("dim_sessions")
        details["checks"]["dim_sessions"] = {
            "healthy": sessions_ok,
            "message": "Populated" if sessions_ok else "Empty",
        }

        # Overall: both checks must pass
        overall_healthy = timeframe_ok and sessions_ok

        if overall_healthy:
            message = "Initialization complete"
        else:
            message = "Waiting for initial data"

        return HealthStatus(
            healthy=overall_healthy,
            message=message,
            checked_at=checked_at,
            details=details,
        )

    # -------------------------------------------------------------------------
    # Internal check methods
    # -------------------------------------------------------------------------

    def _check_database(self) -> bool:
        """
        Check database connection.

        Returns:
            True if SELECT 1 succeeds
        """
        try:
            query = text("SELECT 1")
            with self.engine.connect() as conn:
                result = conn.execute(query)
                result.fetchone()
            return True
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            return False

    def _check_memory_service(self) -> bool:
        """
        Check memory service health.

        Returns:
            True if memory service responds to health check
        """
        if not self.memory_client:
            return True  # Not configured, not required

        try:
            # Try calling health_check method if available
            if hasattr(self.memory_client, "health_check"):
                return self.memory_client.health_check()

            # Otherwise, try a simple search
            if hasattr(self.memory_client, "search"):
                self.memory_client.search("test", limit=1)
                return True

            # No health check method available
            logger.warning("Memory client has no health_check() method")
            return True  # Assume healthy if can't check

        except Exception as e:
            logger.error(f"Memory service health check failed: {e}")
            return False

    def _check_table_populated(self, table_name: str) -> bool:
        """
        Check if table exists and has at least one row.

        Args:
            table_name: Table name to check

        Returns:
            True if table exists and has rows
        """
        try:
            # Check existence
            exists_query = text(
                """
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_schema = 'public'
                    AND table_name = :table_name
                )
            """
            )

            with self.engine.connect() as conn:
                exists = conn.execute(exists_query, {"table_name": table_name}).scalar()

                if not exists:
                    logger.debug(f"Table {table_name} does not exist")
                    return False

                # Check has rows
                count_query = text(f"SELECT COUNT(*) FROM public.{table_name} LIMIT 1")
                count = conn.execute(count_query).scalar()

                return count > 0

        except Exception as e:
            logger.error(f"Failed to check table {table_name}: {e}")
            return False
