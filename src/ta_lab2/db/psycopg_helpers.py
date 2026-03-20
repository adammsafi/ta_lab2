"""
Shared psycopg v3 / psycopg2 helper functions for raw-SQL bar builders.

Extracted from the CMC, TVC, and HL 1D bar builders (BAR-05) to eliminate
~200 lines of identical code duplicated across those files.  All raw-SQL
scripts that need a direct psycopg connection should import from here
instead of copying these helpers locally.

Public API
----------
PSYCOPG3          bool -- True if psycopg (v3) is importable
PSYCOPG2          bool -- True if psycopg2 is importable
normalize_db_url  str  -- strip SQLAlchemy dialect prefix from a DB URL
connect           conn -- open a psycopg connection with autocommit=True
execute           None -- execute a SQL statement
fetchall          list -- execute and return all rows
fetchone          row  -- execute and return the first row (or None)
"""

from __future__ import annotations

from typing import Any, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# Dual-driver detection (done once at import time)
# ---------------------------------------------------------------------------

# Prefer psycopg v3, fall back to psycopg2
try:
    import psycopg  # type: ignore

    PSYCOPG3 = True
except Exception:
    psycopg = None  # type: ignore
    PSYCOPG3 = False

try:
    import psycopg2  # type: ignore

    PSYCOPG2 = True
except Exception:
    psycopg2 = None  # type: ignore
    PSYCOPG2 = False


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def normalize_db_url(url: str) -> str:
    """Remove SQLAlchemy dialect prefix for psycopg connection."""
    if not url:
        return url
    for prefix in (
        "postgresql+psycopg2://",
        "postgresql+psycopg://",
        "postgresql+psycopg3://",
        "postgres+psycopg2://",
        "postgres+psycopg://",
        "postgres+psycopg3://",
    ):
        if url.startswith(prefix):
            return "postgresql://" + url[len(prefix) :]
    return url


def connect(db_url: str):
    """Create psycopg connection (v3 preferred, v2 fallback) with autocommit=True."""
    url = normalize_db_url(db_url)
    if PSYCOPG3:
        return psycopg.connect(url, autocommit=True)
    if PSYCOPG2:
        conn = psycopg2.connect(url)
        conn.autocommit = True
        return conn
    raise RuntimeError("Neither psycopg (v3) nor psycopg2 is installed.")


def execute(conn, sql: str, params: Optional[Sequence[Any]] = None) -> None:
    """Execute a SQL statement (no return value)."""
    params = params or []
    if PSYCOPG3:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return
    cur = conn.cursor()
    cur.execute(sql, params)
    cur.close()


def fetchall(
    conn, sql: str, params: Optional[Sequence[Any]] = None
) -> List[Tuple[Any, ...]]:
    """Execute SQL and fetch all rows."""
    params = params or []
    if PSYCOPG3:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()
    cur = conn.cursor()
    cur.execute(sql, params)
    rows = cur.fetchall()
    cur.close()
    return rows


def fetchone(
    conn, sql: str, params: Optional[Sequence[Any]] = None
) -> Optional[Tuple[Any, ...]]:
    """Execute SQL and fetch one row (returns None if no rows)."""
    params = params or []
    if PSYCOPG3:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()
    cur = conn.cursor()
    cur.execute(sql, params)
    row = cur.fetchone()
    cur.close()
    return row
