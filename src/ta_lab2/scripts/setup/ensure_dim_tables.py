#!/usr/bin/env python3
"""
Conditional dimension table setup script.

Creates dim_timeframe and dim_sessions tables if they don't exist,
using existing SQL seed files for dim_timeframe and inline SQL for dim_sessions.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Any, Dict

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from ta_lab2.config import TARGET_DB_URL

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def resolve_db_url() -> str:
    """Resolve database URL from config."""
    if not TARGET_DB_URL:
        raise RuntimeError(
            "TARGET_DB_URL not set. Set DB_URL or TARGET_DB_URL environment variable."
        )
    return TARGET_DB_URL


def table_exists(engine: Engine, schema: str, table_name: str) -> bool:
    """
    Check if a table exists in the database.

    Args:
        engine: SQLAlchemy engine
        schema: Schema name (e.g., 'public')
        table_name: Table name to check

    Returns:
        True if table exists, False otherwise
    """
    query = text(
        """
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = :schema
            AND table_name = :table_name
        )
    """
    )

    with engine.connect() as conn:
        result = conn.execute(query, {"schema": schema, "table_name": table_name})
        return result.scalar()


def execute_sql_file(engine: Engine, filepath: Path) -> None:
    """
    Execute SQL commands from a file.

    Args:
        engine: SQLAlchemy engine
        filepath: Path to SQL file
    """
    if not filepath.exists():
        raise FileNotFoundError(f"SQL file not found: {filepath}")

    logger.info(f"Executing SQL file: {filepath}")
    sql_content = filepath.read_text()

    with engine.begin() as conn:
        conn.execute(text(sql_content))

    logger.info(f"Successfully executed: {filepath.name}")


def get_row_count(engine: Engine, table_name: str) -> int:
    """
    Get row count for a table.

    Args:
        engine: SQLAlchemy engine
        table_name: Table name

    Returns:
        Row count
    """
    query = text(f"SELECT COUNT(*) FROM {table_name}")
    with engine.connect() as conn:
        result = conn.execute(query)
        return result.scalar()


def ensure_dim_timeframe(
    engine: Engine, sql_dir: Path, dry_run: bool = False
) -> Dict[str, Any]:
    """
    Ensure dim_timeframe table exists and is populated.

    Args:
        engine: SQLAlchemy engine
        sql_dir: Directory containing SQL seed files
        dry_run: If True, only check existence without creating

    Returns:
        Dict with keys: existed, created, rows
    """
    logger.info("Checking dim_timeframe table...")

    existed = table_exists(engine, "public", "dim_timeframe")
    created = False
    rows = 0

    if existed:
        logger.info("dim_timeframe table already exists")
        rows = get_row_count(engine, "public.dim_timeframe")
        logger.info(f"dim_timeframe has {rows} rows")
    elif not dry_run:
        logger.info("dim_timeframe table missing - creating and populating...")

        # Execute SQL seed files in order
        sql_files = [
            "010_dim_timeframe_create.sql",
            "011_dim_timeframe_insert_daily.sql",
            "012_dim_timeframe_insert_weekly.sql",
            "013_dim_timeframe_insert_monthly.sql",
        ]

        # Check for optional yearly file
        yearly_file = sql_dir / "014_dim_timeframe_insert_yearly.sql"
        if yearly_file.exists():
            sql_files.append("014_dim_timeframe_insert_yearly.sql")

        for sql_file in sql_files:
            filepath = sql_dir / sql_file
            execute_sql_file(engine, filepath)

        # Add missing columns that Python code expects
        logger.info("Adding optional columns for future compatibility...")
        with engine.begin() as conn:
            # Check if is_canonical column exists
            check_col = text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public'
                AND table_name = 'dim_timeframe'
                AND column_name = 'is_canonical'
            """
            )
            result = conn.execute(check_col)
            if not result.fetchone():
                conn.execute(
                    text(
                        """
                    ALTER TABLE dim_timeframe
                    ADD COLUMN IF NOT EXISTS is_canonical boolean NOT NULL DEFAULT true,
                    ADD COLUMN IF NOT EXISTS calendar_scheme text NULL,
                    ADD COLUMN IF NOT EXISTS allow_partial_start boolean NOT NULL DEFAULT false,
                    ADD COLUMN IF NOT EXISTS allow_partial_end boolean NOT NULL DEFAULT false,
                    ADD COLUMN IF NOT EXISTS tf_days_min integer NULL,
                    ADD COLUMN IF NOT EXISTS tf_days_max integer NULL
                """
                    )
                )
                logger.info(
                    "Added optional columns: is_canonical, calendar_scheme, allow_partial_*, tf_days_min/max"
                )

        created = True
        rows = get_row_count(engine, "public.dim_timeframe")
        logger.info(f"dim_timeframe created with {rows} rows")
    else:
        logger.info("dry_run=True - would create dim_timeframe")

    return {"existed": existed, "created": created, "rows": rows}


def ensure_dim_sessions(
    engine: Engine, sql_dir: Path, dry_run: bool = False
) -> Dict[str, Any]:
    """
    Ensure dim_sessions table exists and is populated.

    Args:
        engine: SQLAlchemy engine
        sql_dir: Directory containing SQL seed files (unused for sessions)
        dry_run: If True, only check existence without creating

    Returns:
        Dict with keys: existed, created, rows
    """
    logger.info("Checking dim_sessions table...")

    existed = table_exists(engine, "public", "dim_sessions")
    created = False
    rows = 0

    if existed:
        logger.info("dim_sessions table already exists")
        rows = get_row_count(engine, "public.dim_sessions")
        logger.info(f"dim_sessions has {rows} rows")
    elif not dry_run:
        logger.info("dim_sessions table missing - creating and populating...")

        # Create table with schema matching dim_sessions.py
        create_table_sql = text(
            """
            CREATE TABLE IF NOT EXISTS dim_sessions (
                asset_class text NOT NULL,
                region text NOT NULL,
                venue text NOT NULL,
                asset_key_type text NOT NULL,
                asset_key text NOT NULL,
                session_type text NOT NULL DEFAULT 'PRIMARY',
                asset_id bigint NULL,
                timezone text NOT NULL,
                session_open_local time NOT NULL,
                session_close_local time NOT NULL,
                is_24h boolean NOT NULL DEFAULT false,
                PRIMARY KEY (asset_class, region, venue, asset_key_type, asset_key, session_type)
            )
        """
        )

        # Insert default sessions
        insert_defaults_sql = text(
            """
            INSERT INTO dim_sessions
            (asset_class, region, venue, asset_key_type, asset_key, session_type,
             asset_id, timezone, session_open_local, session_close_local, is_24h)
            VALUES
            -- Crypto: 24-hour trading in UTC
            ('CRYPTO', 'GLOBAL', 'DEFAULT', 'symbol', '*', 'RTH',
             NULL, 'UTC', '00:00:00', '23:59:59', TRUE),

            -- US Equity: NYSE regular trading hours with DST handling
            ('EQUITY', 'US', 'NYSE', 'symbol', '*', 'RTH',
             NULL, 'America/New_York', '09:30:00', '16:00:00', FALSE)
            ON CONFLICT (asset_class, region, venue, asset_key_type, asset_key, session_type)
            DO NOTHING
        """
        )

        with engine.begin() as conn:
            conn.execute(create_table_sql)
            logger.info("Created dim_sessions table")
            conn.execute(insert_defaults_sql)
            logger.info("Inserted default sessions (CRYPTO/EQUITY)")

        created = True
        rows = get_row_count(engine, "public.dim_sessions")
        logger.info(f"dim_sessions created with {rows} rows")
    else:
        logger.info("dry_run=True - would create dim_sessions")

    return {"existed": existed, "created": created, "rows": rows}


def main() -> None:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Ensure dimension tables exist (dim_timeframe, dim_sessions)"
    )
    parser.add_argument(
        "--sql-dir",
        type=Path,
        default=Path("sql/lookups"),
        help="Directory containing SQL seed files (default: sql/lookups)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Check existence without creating tables"
    )

    args = parser.parse_args()

    # Resolve paths
    sql_dir = args.sql_dir
    if not sql_dir.is_absolute():
        # Resolve relative to project root (3 levels up from this file)
        project_root = Path(__file__).resolve().parents[4]
        sql_dir = project_root / sql_dir

    if not sql_dir.exists():
        logger.error(f"SQL directory not found: {sql_dir}")
        exit(1)

    # Get database URL
    try:
        db_url = resolve_db_url()
    except RuntimeError as e:
        logger.error(str(e))
        exit(1)

    # Create engine
    engine = create_engine(db_url)

    # Process tables
    logger.info("=" * 60)
    logger.info("Starting dimension table setup")
    logger.info(f"Database: {db_url.split('@')[-1]}")  # Hide credentials
    logger.info(f"SQL directory: {sql_dir}")
    logger.info(f"Dry run: {args.dry_run}")
    logger.info("=" * 60)

    dim_timeframe_result = ensure_dim_timeframe(engine, sql_dir, args.dry_run)
    logger.info("")
    dim_sessions_result = ensure_dim_sessions(engine, sql_dir, args.dry_run)

    # Print summary
    logger.info("")
    logger.info("=" * 60)
    logger.info("Summary:")
    logger.info("-" * 60)
    logger.info("dim_timeframe:")
    logger.info(f"  - Existed: {dim_timeframe_result['existed']}")
    logger.info(f"  - Created: {dim_timeframe_result['created']}")
    logger.info(f"  - Rows: {dim_timeframe_result['rows']}")
    logger.info("dim_sessions:")
    logger.info(f"  - Existed: {dim_sessions_result['existed']}")
    logger.info(f"  - Created: {dim_sessions_result['created']}")
    logger.info(f"  - Rows: {dim_sessions_result['rows']}")
    logger.info("=" * 60)

    if dim_timeframe_result["created"] or dim_sessions_result["created"]:
        logger.info("Tables created successfully!")
    elif dim_timeframe_result["existed"] and dim_sessions_result["existed"]:
        logger.info("All tables already exist - no action needed")

    exit(0)


if __name__ == "__main__":
    main()
