from __future__ import annotations

import os
import sys
from logging.config import fileConfig

from sqlalchemy import create_engine, pool

from alembic import context

# Add project root to sys.path so refresh_utils is importable
# regardless of whether the package is installed via pip install -e .
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.ta_lab2.scripts.refresh_utils import resolve_db_url  # noqa: E402

# This is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# encoding="utf-8" is MANDATORY on Windows -- default cp1252 raises
# UnicodeDecodeError when alembic.ini contains UTF-8 characters in comments.
if config.config_file_name is not None:
    fileConfig(config.config_file_name, encoding="utf-8")

# No ORM models -- autogenerate is intentionally disabled.
# Without a real MetaData object, autogenerate would compare the DB against an
# empty schema and emit op.create_table() for all 50+ existing tables.
# All revisions are written by hand; target_metadata = None enforces this.
target_metadata = None


def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting to the database.

    Useful for producing a migration script to review or hand to a DBA.
    Run with: alembic upgrade head --sql > migration.sql
    """
    url = resolve_db_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Connect to the database and run pending migrations.

    Uses NullPool to avoid connection-pooling issues -- matches the
    project-wide pattern for one-shot scripts (see refresh_utils.py).
    """
    url = resolve_db_url()
    connectable = create_engine(url, poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
