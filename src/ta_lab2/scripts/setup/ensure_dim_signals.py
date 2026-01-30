#!/usr/bin/env python
"""
Ensure dim_signals table exists and is populated.

Idempotent script to create dim_signals configuration table if it doesn't exist.
Safe to run multiple times.

Usage:
    python -m ta_lab2.scripts.setup.ensure_dim_signals
"""

import os
import sys
from pathlib import Path
from sqlalchemy import create_engine, text


def ensure_dim_signals() -> None:
    """
    Ensure dim_signals table exists and has seed data.

    Idempotent operation - safe to run multiple times.
    """
    # Get database URL from environment
    db_url = os.environ.get("TARGET_DB_URL")
    if not db_url:
        print("[ERROR] TARGET_DB_URL environment variable not set", file=sys.stderr)
        sys.exit(1)

    # Create engine
    engine = create_engine(db_url)

    # Check if table exists and has rows
    check_sql = text("""
        SELECT COUNT(*) as row_count
        FROM information_schema.tables
        WHERE table_schema = 'public'
            AND table_name = 'dim_signals'
    """)

    with engine.connect() as conn:
        result = conn.execute(check_sql)
        table_exists = result.fetchone()[0] > 0

    if table_exists:
        # Check row count
        count_sql = text("SELECT COUNT(*) FROM public.dim_signals")
        with engine.connect() as conn:
            result = conn.execute(count_sql)
            row_count = result.fetchone()[0]

        print(f"[OK] dim_signals exists with {row_count} rows")
        return

    # Table doesn't exist - execute DDL
    print("[INFO] dim_signals table not found, creating...")

    # Find DDL file
    project_root = Path(__file__).parent.parent.parent.parent.parent
    ddl_path = project_root / "sql" / "lookups" / "030_dim_signals.sql"

    if not ddl_path.exists():
        print(f"[ERROR] DDL file not found: {ddl_path}", file=sys.stderr)
        sys.exit(1)

    # Read and execute DDL
    with open(ddl_path, 'r') as f:
        ddl_sql = f.read()

    with engine.begin() as conn:
        conn.execute(text(ddl_sql))

    # Verify creation
    with engine.connect() as conn:
        result = conn.execute(count_sql)
        row_count = result.fetchone()[0]

    print(f"[OK] dim_signals created with {row_count} rows")


if __name__ == "__main__":
    ensure_dim_signals()
