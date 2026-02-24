"""
Alembic migration status utilities for the ta_lab2 daily refresh pipeline.

Provides advisory migration checks that warn when the database is behind the
Alembic head revision.  All functions are wrapped in try/except so that
migration-check failures never crash the pipeline.

Usage::

    from ta_lab2.scripts.alembic_utils import check_migration_status

    ok = check_migration_status(db_url)
    # Returns True if at head, False otherwise.
    # Logs a warning with upgrade instructions when behind.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal helper: resolve alembic.ini path
# ---------------------------------------------------------------------------


def _default_ini_path() -> str:
    """Return the absolute path to alembic.ini at the project root."""
    # scripts/ -> ta_lab2/ -> src/ -> project root
    scripts_dir = os.path.dirname(__file__)
    project_root = os.path.abspath(os.path.join(scripts_dir, "..", "..", ".."))
    return os.path.join(project_root, "alembic.ini")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def is_alembic_head(db_url: str, ini_path: str | None = None) -> bool:
    """
    Return True when the database is at the Alembic head revision.

    Parameters
    ----------
    db_url:
        SQLAlchemy-compatible database URL.
    ini_path:
        Path to alembic.ini.  Defaults to ``<project_root>/alembic.ini``
        (auto-resolved relative to this module's location).

    Returns
    -------
    bool
        True  -- database is at head.
        False -- database is behind head, or the check could not be performed.
    """
    try:
        from alembic.config import Config
        from alembic.runtime.migration import MigrationContext
        from alembic.script import ScriptDirectory
        from sqlalchemy import create_engine, pool

        resolved_ini = os.path.abspath(ini_path or _default_ini_path())

        if not os.path.exists(resolved_ini):
            logger.warning(
                "[MIGRATION] alembic.ini not found at %s -- skipping migration check",
                resolved_ini,
            )
            return False

        cfg = Config(resolved_ini)
        script_dir = ScriptDirectory.from_config(cfg)
        head_rev = script_dir.get_current_head()

        # NullPool matches the project pattern for one-shot connections
        engine = create_engine(db_url, poolclass=pool.NullPool)
        try:
            with engine.connect() as conn:
                context = MigrationContext.configure(conn)
                current_rev = context.get_current_revision()
        finally:
            engine.dispose()

        return current_rev == head_rev

    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[MIGRATION] Could not determine Alembic revision: %s",
            exc,
        )
        return False


def check_migration_status(db_url: str, ini_path: str | None = None) -> bool:
    """
    Check Alembic migration status and log the result.

    Advisory only -- never raises, never blocks execution.

    Parameters
    ----------
    db_url:
        SQLAlchemy-compatible database URL.
    ini_path:
        Path to alembic.ini.  Defaults to ``<project_root>/alembic.ini``.

    Returns
    -------
    bool
        True  -- database is at head (or check was skipped gracefully).
        False -- database is behind head, alembic.ini missing, or DB unreachable.
    """
    try:
        from alembic.config import Config
        from alembic.runtime.migration import MigrationContext
        from alembic.script import ScriptDirectory
        from sqlalchemy import create_engine, pool

        resolved_ini = os.path.abspath(ini_path or _default_ini_path())

        if not os.path.exists(resolved_ini):
            logger.warning(
                "[MIGRATION] alembic.ini not found at %s -- skipping migration check",
                resolved_ini,
            )
            return False

        cfg = Config(resolved_ini)
        script_dir = ScriptDirectory.from_config(cfg)
        head_rev = script_dir.get_current_head()

        engine = create_engine(db_url, poolclass=pool.NullPool)
        try:
            with engine.connect() as conn:
                context = MigrationContext.configure(conn)
                current_rev = context.get_current_revision()
        finally:
            engine.dispose()

        if current_rev == head_rev:
            logger.info(
                "[MIGRATION] Database is at Alembic head: %s",
                head_rev,
            )
            return True
        else:
            logger.warning(
                "[MIGRATION] Database at revision %s, head is %s. "
                "Run: alembic upgrade head",
                current_rev,
                head_rev,
            )
            return False

    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[MIGRATION] Migration status check failed (non-fatal): %s",
            exc,
        )
        return False
