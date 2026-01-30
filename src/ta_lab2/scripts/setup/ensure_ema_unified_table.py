"""
ensure_ema_unified_table.py

Conditional setup script for cmc_ema_multi_tf_u unified EMA table.
Ensures table exists before running sync or validation tests.

Usage:
    python -m ta_lab2.scripts.setup.ensure_ema_unified_table [OPTIONS]

Options:
    --sql-dir PATH       Path to SQL DDL directory (default: sql/features)
    --dry-run           Check table status without creating
    --sync-after        Run sync script after ensuring table exists

Example:
    python -m ta_lab2.scripts.setup.ensure_ema_unified_table --sync-after
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


def _log(msg: str) -> None:
    """Log message with prefix."""
    print(f"[ensure_ema_u] {msg}")


def get_engine() -> Engine:
    """Create database engine from TARGET_DB_URL environment variable."""
    db_url = os.environ.get("TARGET_DB_URL")
    if not db_url:
        raise RuntimeError("TARGET_DB_URL environment variable is required")
    return create_engine(db_url, future=True)


def table_exists(engine: Engine, schema: str, table_name: str) -> bool:
    """
    Check if table exists in database.

    Args:
        engine: SQLAlchemy engine
        schema: Schema name (e.g., 'public')
        table_name: Table name (e.g., 'cmc_ema_multi_tf_u')

    Returns:
        True if table exists, False otherwise
    """
    q = text(
        """
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = :schema AND table_name = :table
        LIMIT 1
        """
    )
    df = pd.read_sql(q, engine, params={"schema": schema, "table": table_name})
    return not df.empty


def column_exists(engine: Engine, schema: str, table_name: str, column_name: str) -> bool:
    """
    Check if column exists in table.

    Args:
        engine: SQLAlchemy engine
        schema: Schema name
        table_name: Table name
        column_name: Column name to check

    Returns:
        True if column exists, False otherwise
    """
    q = text(
        """
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = :schema
          AND table_name = :table
          AND column_name = :column
        LIMIT 1
        """
    )
    df = pd.read_sql(
        q,
        engine,
        params={"schema": schema, "table": table_name, "column": column_name}
    )
    return not df.empty


def execute_sql_file(engine: Engine, filepath: Path) -> None:
    """
    Execute SQL file contents.

    Args:
        engine: SQLAlchemy engine
        filepath: Path to SQL file

    Raises:
        FileNotFoundError: If SQL file doesn't exist
        RuntimeError: If SQL execution fails
    """
    if not filepath.exists():
        raise FileNotFoundError(f"SQL file not found: {filepath}")

    _log(f"Executing SQL file: {filepath}")

    sql_content = filepath.read_text(encoding="utf-8")

    with engine.begin() as conn:
        conn.execute(text(sql_content))

    _log("SQL file executed successfully")


def ensure_cmc_ema_multi_tf_u(engine: Engine, sql_dir: Path, dry_run: bool = False) -> dict:
    """
    Ensure cmc_ema_multi_tf_u table exists with correct schema.

    Args:
        engine: SQLAlchemy engine
        sql_dir: Path to directory containing DDL files
        dry_run: If True, only check status without creating

    Returns:
        dict with keys:
            - existed: bool (table existed before this call)
            - created: bool (table was created by this call)
            - has_alignment_source: bool (table has alignment_source column)
    """
    schema = "public"
    table_name = "cmc_ema_multi_tf_u"

    result = {
        "existed": False,
        "created": False,
        "has_alignment_source": False,
    }

    # Check if table exists
    if table_exists(engine, schema, table_name):
        result["existed"] = True
        _log(f"Table {schema}.{table_name} exists")

        # Verify alignment_source column exists
        if column_exists(engine, schema, table_name, "alignment_source"):
            result["has_alignment_source"] = True
            _log("[OK] alignment_source column present")
        else:
            _log("[ERROR] alignment_source column MISSING")
            _log("  This is a schema defect - table needs migration")

        return result

    # Table doesn't exist
    _log(f"Table {schema}.{table_name} does NOT exist")

    if dry_run:
        _log("DRY RUN mode - would create table from DDL")
        return result

    # Create table from DDL
    ddl_file = sql_dir / "030_cmc_ema_multi_tf_u_create.sql"

    try:
        execute_sql_file(engine, ddl_file)
        result["created"] = True
        _log(f"[OK] Table {schema}.{table_name} created successfully")

        # Verify alignment_source column in newly created table
        if column_exists(engine, schema, table_name, "alignment_source"):
            result["has_alignment_source"] = True
            _log("[OK] alignment_source column present in new table")
        else:
            _log("[ERROR] alignment_source column MISSING in new table")
            _log("  DDL file may need updating")

    except Exception as e:
        _log(f"[ERROR] Failed to create table: {e}")
        raise RuntimeError(f"Table creation failed: {e}") from e

    return result


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Ensure cmc_ema_multi_tf_u unified EMA table exists",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Check if table exists (dry run)
  python -m ta_lab2.scripts.setup.ensure_ema_unified_table --dry-run

  # Create table if missing
  python -m ta_lab2.scripts.setup.ensure_ema_unified_table

  # Create table and populate from source tables
  python -m ta_lab2.scripts.setup.ensure_ema_unified_table --sync-after
        """
    )

    parser.add_argument(
        "--sql-dir",
        type=Path,
        default=Path("sql/features"),
        help="Directory containing DDL files (default: sql/features)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Check table status without creating"
    )
    parser.add_argument(
        "--sync-after",
        action="store_true",
        help="Run sync script after ensuring table exists"
    )

    args = parser.parse_args()

    # Ensure sql_dir is absolute
    if not args.sql_dir.is_absolute():
        args.sql_dir = Path.cwd() / args.sql_dir

    try:
        engine = get_engine()
    except RuntimeError as e:
        _log(f"Error: {e}")
        sys.exit(1)

    # Ensure table exists
    try:
        result = ensure_cmc_ema_multi_tf_u(engine, args.sql_dir, dry_run=args.dry_run)
    except Exception as e:
        _log(f"Error: {e}")
        sys.exit(1)

    # Print summary
    _log("=" * 60)
    _log("Summary:")
    _log(f"  Table existed before: {result['existed']}")
    _log(f"  Table created now:    {result['created']}")
    _log(f"  Has alignment_source: {result['has_alignment_source']}")
    _log("=" * 60)

    # Run sync if requested and table is ready
    if args.sync_after and not args.dry_run:
        if result["existed"] or result["created"]:
            _log("Running sync script to populate from source tables...")
            try:
                # Run sync_cmc_ema_multi_tf_u.py
                subprocess.run(
                    [sys.executable, "-m", "ta_lab2.scripts.emas.sync_cmc_ema_multi_tf_u"],
                    check=True,
                    cwd=Path.cwd()
                )
                _log("[OK] Sync completed successfully")
            except subprocess.CalledProcessError as e:
                _log(f"[ERROR] Sync failed: {e}")
                sys.exit(1)
        else:
            _log("Skipping sync - table was not created and did not exist")

    sys.exit(0)


if __name__ == "__main__":
    main()
