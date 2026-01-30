#!/usr/bin/env python3
"""
Conditional dim_features table setup script.

Creates dim_features table if it doesn't exist, using SQL DDL file
for feature metadata and null handling configuration.
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
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
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
    query = text("""
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = :schema
            AND table_name = :table_name
        )
    """)

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


def ensure_dim_features(engine: Engine, sql_dir: Path, dry_run: bool = False) -> Dict[str, Any]:
    """
    Ensure dim_features table exists and is populated.

    Args:
        engine: SQLAlchemy engine
        sql_dir: Directory containing SQL seed files
        dry_run: If True, only check existence without creating

    Returns:
        Dict with keys: existed, created, rows
    """
    logger.info("Checking dim_features table...")

    existed = table_exists(engine, "public", "dim_features")
    created = False
    rows = 0

    if existed:
        logger.info("dim_features table already exists")
        rows = get_row_count(engine, "public.dim_features")
        logger.info(f"dim_features has {rows} rows")
    elif not dry_run:
        logger.info("dim_features table missing - creating and populating...")

        # Execute SQL DDL file
        sql_file = sql_dir / "020_dim_features.sql"
        execute_sql_file(engine, sql_file)

        created = True
        rows = get_row_count(engine, "public.dim_features")
        logger.info(f"dim_features created with {rows} rows")
    else:
        logger.info("dry_run=True - would create dim_features")

    return {"existed": existed, "created": created, "rows": rows}


def main() -> None:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Ensure dim_features table exists"
    )
    parser.add_argument(
        "--sql-dir",
        type=Path,
        default=Path("sql/lookups"),
        help="Directory containing SQL seed files (default: sql/lookups)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Check existence without creating table"
    )

    args = parser.parse_args()

    # Resolve paths
    sql_dir = args.sql_dir
    if not sql_dir.is_absolute():
        # Resolve relative to project root (4 levels up from this file)
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

    # Process table
    logger.info("=" * 60)
    logger.info("Starting dim_features table setup")
    logger.info(f"Database: {db_url.split('@')[-1]}")  # Hide credentials
    logger.info(f"SQL directory: {sql_dir}")
    logger.info(f"Dry run: {args.dry_run}")
    logger.info("=" * 60)

    result = ensure_dim_features(engine, sql_dir, args.dry_run)

    # Print summary
    logger.info("")
    logger.info("=" * 60)
    logger.info("Summary:")
    logger.info("-" * 60)
    logger.info(f"dim_features:")
    logger.info(f"  - Existed: {result['existed']}")
    logger.info(f"  - Created: {result['created']}")
    logger.info(f"  - Rows: {result['rows']}")
    logger.info("=" * 60)

    if result['created']:
        logger.info("Table created successfully!")
    elif result['existed']:
        logger.info("Table already exists - no action needed")

    exit(0)


if __name__ == "__main__":
    main()
