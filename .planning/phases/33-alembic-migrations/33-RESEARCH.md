# Phase 33: Alembic Migrations - Research

**Researched:** 2026-02-23
**Domain:** Alembic 1.18.4 — database migration framework, existing PostgreSQL schema stamping
**Confidence:** HIGH

---

## Summary

Phase 33 bootstraps the Alembic migration framework on an existing 50+ table PostgreSQL database without executing any DDL on the live DB. The strategy is stamp-then-forward: create a no-op baseline revision, run `alembic stamp head` to mark the current schema as version zero, then all future schema changes go through `alembic revision` before any SQL runs.

Alembic 1.18.4 (current) is not installed in the project. The standard bootstrap workflow is `alembic init alembic` (generates `alembic/`, `alembic.ini`, `alembic/env.py`), then hand-write a no-op baseline revision, then `alembic stamp head`. The pyproject template (`alembic init --template pyproject alembic`) appends `[tool.alembic]` to the existing `pyproject.toml` and still generates `alembic.ini` for DB connectivity — this is the cleanest option for this project since pyproject.toml is already the config source of truth.

The key customization for this project is env.py: replace the `sqlalchemy.url` INI lookup with a call to `resolve_db_url()` from `refresh_utils`, use `NullPool` (already the project-wide pattern), and open any SQL files with `encoding='utf-8'` (Windows pitfall documented in MEMORY.md). Autogenerate is explicitly disabled — no `target_metadata` configuration, write all revisions by hand.

**Primary recommendation:** Use `alembic init --template pyproject alembic` to co-locate Alembic config in pyproject.toml, customize env.py to use `resolve_db_url()` + `NullPool`, create a no-op baseline revision, and run `alembic stamp head` on the live DB. Catalog all 17 migration files in `docs/operations/SCHEMA_MIGRATIONS.md`.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| alembic | 1.18.4 | Database migration framework | Official SQLAlchemy migration tool; project uses SQLAlchemy 2.0+ |

### Supporting (already in project)
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| sqlalchemy | >=2.0 | Engine creation in env.py | Already pinned in pyproject.toml |
| psycopg2-binary | >=2.9 | PostgreSQL DBAPI | Already pinned in pyproject.toml |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| alembic | flyway, liquibase | Java-based; don't fit Python-centric project |
| alembic | yoyo-migrations | Simpler but less ecosystem support |
| alembic | django migrations | Requires Django ORM; not applicable |

**Installation (add to pyproject.toml):**
```bash
# Add to [project.dependencies] in pyproject.toml
alembic>=1.18

# Install
pip install -e ".[dev]"
```

**Where to pin:** Add `alembic>=1.18` to the core `[project.dependencies]` list in `pyproject.toml` (not `[project.optional-dependencies]`), because alembic is a workflow tool needed by anyone doing schema work, not just optional feature users.

---

## Architecture Patterns

### Recommended Project Structure
```
ta_lab2/                     # project root
├── alembic.ini              # DB URL (gitignored or placeholder), logging config
├── alembic/
│   ├── env.py               # customized: resolve_db_url(), NullPool, no target_metadata
│   ├── script.py.mako       # revision file template
│   ├── README               # generated
│   └── versions/
│       └── <rev>_baseline.py  # single no-op baseline revision
├── pyproject.toml           # [tool.alembic] section added by init --template pyproject
└── sql/
    └── migration/           # legacy SQL files stay here (cataloged, not deleted)
```

### Pattern 1: Pyproject Template Init

**What:** `alembic init --template pyproject alembic` appends `[tool.alembic]` section to the existing `pyproject.toml` (with `script_location = "%(here)s/alembic"`) and still generates `alembic.ini` for the DB URL and logging.

**Why:** pyproject.toml is already the project's config source of truth (`importlib.metadata.version("ta_lab2")` uses it). Keeping alembic config in the same file is consistent.

**What init generates (pyproject template):**
- `alembic.ini` — DB URL + logging config only (slimmer than standard template)
- `pyproject.toml` — receives `[tool.alembic]` block with `script_location`, `file_template` options
- `alembic/env.py` — same default env.py as standard template
- `alembic/script.py.mako` — revision template
- `alembic/versions/` — empty; holds revision files

**Example command:**
```bash
alembic init --template pyproject alembic
```

### Pattern 2: Custom env.py for This Project

The default env.py uses `config.get_main_option("sqlalchemy.url")` which reads from `alembic.ini`. This project uses `resolve_db_url()` which reads from `db_config.env`, `TARGET_DB_URL` env var, or `MARKETDATA_DB_URL` env var. Override the URL lookup in env.py:

```python
# Source: verified by reading src/ta_lab2/scripts/refresh_utils.py
# alembic/env.py
from logging.config import fileConfig
from sqlalchemy import engine_from_config
from sqlalchemy import pool
from alembic import context
import sys
import os

# --- project-specific ---
# Allow import of refresh_utils from anywhere alembic is run
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.ta_lab2.scripts.refresh_utils import resolve_db_url

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name, encoding="utf-8")  # encoding= is MANDATORY on Windows

# No ORM models — autogenerate is disabled
target_metadata = None


def run_migrations_offline() -> None:
    """Offline mode: emit SQL to stdout, no live DB needed."""
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
    """Online mode: connect to DB and apply migrations."""
    url = resolve_db_url()
    # NullPool: avoids connection pooling issues (matches project-wide pattern)
    from sqlalchemy import create_engine
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
```

**Key details:**
- `fileConfig(..., encoding="utf-8")` — prevents `UnicodeDecodeError` on Windows when `alembic.ini` contains UTF-8 characters in comments
- `resolve_db_url()` — reads `db_config.env` by walking up the directory tree, falling back to env vars; same priority chain as all other scripts
- `pool.NullPool` — project-wide standard for avoiding pooling in one-shot scripts
- `target_metadata = None` — explicitly disables autogenerate

### Pattern 3: No-Op Baseline Revision

**What:** A revision that represents "current schema" with empty `upgrade()` and `downgrade()` bodies. Never executed — stamped only.

**Generate:**
```bash
alembic revision -m "baseline"
```

**Result file (`alembic/versions/<rev>_baseline.py`):**
```python
# Source: verified by generating baseline revision with alembic 1.18.4
"""baseline

Revision ID: <auto-generated-12-char-hex>
Revises:
Create Date: 2026-02-23 ...

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '<auto-generated>'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass  # baseline no-op — existing schema unchanged


def downgrade() -> None:
    """Downgrade schema."""
    pass  # no rollback defined for baseline
```

**The revision file must NOT be edited beyond the docstring.** Leave `upgrade()` and `downgrade()` as `pass`.

### Pattern 4: Stamp Existing Database

**What:** Writes the revision ID into the `alembic_version` table without executing any migration code.

```bash
# Run from project root (where alembic.ini lives)
alembic stamp head

# Verify
alembic current
# Expected output: <rev-id> (head)
```

**alembic_version table:** Alembic creates this table automatically during `stamp`. It has one column (`version_num VARCHAR(32)`) and one row per head revision.

**Verified behavior (tested with alembic 1.18.4):**
- `alembic stamp head` creates `alembic_version` table if it doesn't exist
- `alembic current` outputs `<rev-id> (head)` if stamped correctly
- `alembic history` reads from filesystem (no DB needed) — outputs `<base> -> <rev-id> (head), baseline`

### Pattern 5: Forward Migration Convention

For all future schema changes:
```bash
# 1. Create revision file first (before touching any SQL)
alembic revision -m "add_column_foo_to_bar_table"
# Generated: alembic/versions/<rev>_add_column_foo_to_bar_table.py

# 2. Write upgrade() and downgrade() by hand (no autogenerate)
# 3. Review, commit revision file
# 4. Apply on live DB
alembic upgrade head
# 5. Verify
alembic current
```

### Revision Naming Convention

**Recommended:** Descriptive slug only (no date prefix). Alembic's default `%%(rev)s_%%(slug)s` produces filenames like `a1b2c3d4e5f6_add_column_foo.py`. This is sufficient — git log provides the date context.

**Rationale:** Date-prefixed filenames (`2026_02_23_add_column_foo.py`) are redundant when using git. The revision chain in Alembic (`down_revision` pointer) already encodes ordering, regardless of filename.

**Slug truncation:** Default max 40 characters. Use underscores, lowercase. Examples:
- `add_is_outlier_to_cmc_vol`
- `drop_legacy_ema_columns_from_features`
- `add_alignment_source_to_feature_tables`

### downgrade() Policy

**Recommended:** Always implement `downgrade()` even if it's just `pass`. Reasons:
- `alembic downgrade -1` is the emergency rollback command
- For simple `ADD COLUMN` migrations, `downgrade()` is a trivial `drop_column()` call
- For complex migrations (column renames, data transforms), document why downgrade is unsafe rather than leaving it blank

**For baseline revision only:** `downgrade()` is `pass` because there's no "before baseline" state.

### Online vs Offline Mode

**Online mode** (default, connects to live DB): Use for all production operations.

**Offline mode** (generates SQL file without connecting): Useful for producing a migration script to hand to a DBA.

```bash
# Generate SQL script offline (no DB connection)
alembic upgrade head --sql > migration.sql
```

Keep offline support in env.py even if rarely used — it costs nothing to implement.

### Anti-Patterns to Avoid
- **Running autogenerate without ORM metadata:** Without `target_metadata` set to a real `MetaData` object, autogenerate compares against an empty schema and emits `op.create_table()` for all 50+ tables. This would be catastrophic on a stamped-then-forward DB. `target_metadata = None` is the correct setting.
- **Putting the real DB URL in alembic.ini:** Commit `alembic.ini` with a placeholder URL; real URL comes via `resolve_db_url()` in env.py (reads `db_config.env` which is gitignored).
- **Editing baseline revision's upgrade/downgrade:** The baseline is a no-op reference point. Only `pass` in both functions.
- **Running `alembic upgrade head` instead of `alembic stamp head` on the existing DB:** `upgrade head` would try to execute the baseline revision — nothing happens (it's a no-op), but the intent is wrong.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Migration state tracking | Custom `schema_versions` table | `alembic_version` (auto-created by stamp) | Standard interface; tooling assumes this table |
| Revision ordering | Sequential filenames (001_, 002_) | Alembic's `down_revision` pointer chain | Filename ordering breaks when branches merge |
| Migration runner | Python subprocess calling psql | `alembic upgrade head` | Handles transaction management, error reporting |
| DB URL resolution | Duplicate `resolve_db_url()` in env.py | Import the existing `resolve_db_url()` from `refresh_utils` | Already handles all 4 priority sources |

**Key insight:** The project already has `resolve_db_url()` that handles all URL sources. env.py should import it, not re-implement it.

---

## Common Pitfalls

### Pitfall 1: autogenerate Without ORM Models
**What goes wrong:** Running `alembic revision --autogenerate` with `target_metadata = None` causes autogenerate to compare DB against an empty schema. It generates `op.create_table()` for every table. Running `alembic upgrade head` on this would attempt to recreate all 50+ tables (which already exist), causing errors.
**Why it happens:** autogenerate is designed for ORM-model-to-DB comparison. Without models, it has nothing to compare against.
**How to avoid:** Set `target_metadata = None` in env.py. Never run `--autogenerate`. All revisions are written by hand.
**Warning signs:** Generated revision file contains `op.create_table()` calls.

### Pitfall 2: Windows `fileConfig()` Encoding Error
**What goes wrong:** `fileConfig(config.config_file_name)` opens `alembic.ini` with the system default encoding (cp1252 on Windows). If `alembic.ini` contains UTF-8 characters (box-drawing chars in comments), this raises `UnicodeDecodeError`.
**Why it happens:** Python's `configparser.read()` uses locale encoding by default on Windows.
**How to avoid:** Always call `fileConfig(config.config_file_name, encoding="utf-8")` in env.py.
**Warning signs:** `UnicodeDecodeError: 'cp1252' codec can't decode byte 0xe2` when running any alembic command.

### Pitfall 3: Running from Wrong Directory
**What goes wrong:** Alembic looks for `alembic.ini` in the current working directory. If you run `alembic` from a subdirectory, it fails with `No config file 'alembic.ini' found, or file has no '[alembic]' section`.
**Why it happens:** Alembic searches CWD for the config file by default.
**How to avoid:** Always run alembic from the project root. Document this in the workflow guide. Add a `-c` flag option: `alembic -c /path/to/alembic.ini stamp head`.
**Warning signs:** `FAILED: No config file 'alembic.ini' found`.

### Pitfall 4: `sys.path` Missing for `resolve_db_url` Import
**What goes wrong:** env.py tries to import `resolve_db_url` from `ta_lab2.scripts.refresh_utils`, but the package isn't installed or `src/` isn't on `sys.path`.
**Why it happens:** Alembic runs env.py with CWD's Python environment. If alembic is run before `pip install -e .`, the import fails.
**How to avoid:** In env.py, use `sys.path.insert(0, ...)` to add the project root before the import, so the package import works regardless of install state. Or import it as a path-based relative import.
**Warning signs:** `ModuleNotFoundError: No module named 'ta_lab2'`.

### Pitfall 5: Putting Real DB URL in alembic.ini
**What goes wrong:** Committing `alembic.ini` with a real database URL exposes credentials in git history.
**Why it happens:** The default `alembic.ini` has a `sqlalchemy.url` key that developers fill in.
**How to avoid:** Keep `alembic.ini` with a placeholder (`sqlalchemy.url = driver://user:pass@localhost/dbname`). Override in env.py using `resolve_db_url()`. The `alembic.ini` is committed; the credentials are not.
**Warning signs:** Real credentials visible in `git log -- alembic.ini`.

### Pitfall 6: `alembic upgrade head` vs `alembic stamp head`
**What goes wrong:** On a fresh clone/restore, running `alembic upgrade head` instead of `alembic stamp head` attempts to run the baseline upgrade() function. For a true no-op baseline this is harmless, but semantically wrong and confusing.
**Why it happens:** Developers confuse "apply migrations" with "record current state."
**How to avoid:** Document clearly: `stamp` = "tell Alembic where we are NOW (no SQL)"; `upgrade` = "run pending migrations". Use `stamp` only once (on the existing production DB). Use `upgrade` for all future migrations.

---

## Code Examples

### Verified env.py for This Project

```python
# Source: verified against alembic 1.18.4 default template + project patterns
# alembic/env.py
from __future__ import annotations

import sys
import os
from logging.config import fileConfig

from sqlalchemy import create_engine, pool
from alembic import context

# Add project root to sys.path so refresh_utils is importable
# regardless of whether the package is installed
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.ta_lab2.scripts.refresh_utils import resolve_db_url  # noqa: E402

config = context.config

# fileConfig with explicit UTF-8 encoding prevents UnicodeDecodeError on Windows
if config.config_file_name is not None:
    fileConfig(config.config_file_name, encoding="utf-8")

# No ORM models — autogenerate is intentionally disabled
target_metadata = None


def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting to the database."""
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
    """Connect to the database and run pending migrations."""
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
```

### alembic.ini (committed with placeholder URL)

```ini
# A generic, single database configuration.
# NOTE: sqlalchemy.url is a placeholder. The real URL is loaded via
# resolve_db_url() in env.py (reads db_config.env or TARGET_DB_URL).
[alembic]
script_location = %(here)s/alembic

# Revision filename format: <12-char-rev>_<slug>.py (default)
# file_template = %%(rev)s_%%(slug)s

# Prepend project root to sys.path
prepend_sys_path = .

# path_separator uses os.pathsep (Windows/Unix compatible)
path_separator = os

# output_encoding must be utf-8 to support UTF-8 in migration file comments
output_encoding = utf-8

sqlalchemy.url = driver://user:pass@localhost/dbname

[post_write_hooks]
# Lint new revision files with ruff automatically
hooks = ruff
ruff.type = exec
ruff.executable = ruff
ruff.options = check --fix REVISION_SCRIPT_FILENAME

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARNING
handlers = console
qualname =

[logger_sqlalchemy]
level = WARNING
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
```

### Complete Bootstrap Sequence

```bash
# 1. Install alembic
pip install -e .   # after adding alembic>=1.18 to pyproject.toml

# 2. Initialize (from project root)
alembic init --template pyproject alembic
# Creates: alembic/, alembic.ini, adds [tool.alembic] to pyproject.toml

# 3. Customize alembic/env.py (replace default with project-specific version above)

# 4. Create no-op baseline revision
alembic revision -m "baseline"
# Creates: alembic/versions/<rev>_baseline.py

# 5. Stamp the live DB (DB must be accessible)
alembic stamp head
# Expected output: INFO [alembic.runtime.migration] Running stamp_revision -> <rev-id>

# 6. Verify
alembic current
# Expected output: <rev-id> (head)

alembic history
# Expected output: <base> -> <rev-id> (head), baseline
```

### Future Migration Workflow

```bash
# EVERY schema change follows this sequence:
# Step 1: Create revision BEFORE writing any SQL
alembic revision -m "add_foo_column_to_cmc_vol"
# Opens editor with template in alembic/versions/<rev>_add_foo_column_to_cmc_vol.py

# Step 2: Write upgrade() and downgrade() by hand
def upgrade() -> None:
    op.add_column(
        "cmc_vol",
        sa.Column("foo", sa.Double(), nullable=True),
        schema="public",
    )

def downgrade() -> None:
    op.drop_column("cmc_vol", "foo", schema="public")

# Step 3: Commit the revision file
git add alembic/versions/<rev>_add_foo_column_to_cmc_vol.py
git commit -m "feat: add foo column to cmc_vol"

# Step 4: Apply on live DB
alembic upgrade head

# Step 5: Verify
alembic current
```

---

## Legacy SQL File Catalog

All 17 files in `sql/migration/` ordered by git creation date. These are historical reference; they have already been applied to the live DB.

| # | Filename | Git Created | Purpose | Tables Affected |
|---|----------|-------------|---------|-----------------|
| 1 | `016_dim_timeframe_partial_bounds_and_calendar_families.sql` | 2025-12-20 | Add tf_days_min/max, allow_partial_start/end, calendar_scheme columns for variable-period TF support | `dim_timeframe` |
| 2 | `alter_cmc_ema_multi_tf_u_add_bar_cols.sql` | 2025-12-20 | Add ema_bar, d1_bar, d2_bar, roll_bar, d1_roll_bar, d2_roll_bar columns | `cmc_ema_multi_tf_u` |
| 3 | `alter_dim_timeframe_canonical_anchor_check.sql` | 2025-12-20 | Add is_canonical column; update calendar_anchor for ISO-WEEK TFs | `dim_timeframe` |
| 4 | `merge_cmc_ema_multi_tf_u_from_sources.sql` | 2025-12-20 | Data migration: populate cmc_ema_multi_tf_u from calendar and multi_tf source tables | `cmc_ema_multi_tf_u` |
| 5 | `rebuild_cmc_ema_multi_tf_u_from_sources.sql` | 2025-12-20 | Truncate + rebuild cmc_ema_multi_tf_u; restructure PK to include alignment_source | `cmc_ema_multi_tf_u` |
| 6 | `rebuild_dim_timeframe_from_backup_20251218.sql` | 2025-12-24 | Restore dim_timeframe from backup table after data loss | `dim_timeframe` |
| 7 | `rebuild_cmc_ema_multi_tf_u_from_all_sources.sql` | 2025-12-24 | Dynamic rebuild of EMA unified table from all source tables using pg catalog | `cmc_ema_multi_tf_u` |
| 8 | `017_alter_price_bars_anchor_add_offset.sql` | 2026-02-17 | Add bar_anchor_offset column + indexes to both anchor bar tables | `cmc_price_bars_multi_tf_cal_anchor_us`, `cmc_price_bars_multi_tf_cal_anchor_iso` |
| 9 | `018_refactor_dim_sessions.sql` | 2026-02-17 | Drop and recreate dim_sessions_pk constraint with new PK definition | `dim_sessions` |
| 10 | `019_unify_bar_table_schemas.sql` | 2026-02-17 | Unify all 6 bar tables to canonical PK=(id,tf,bar_seq,timestamp) + 37 base columns | All 6 `cmc_price_bars_*` tables |
| 11 | `020_add_bar_time_columns.sql` | 2026-02-17 | Add time_open_bar and time_close_bar columns to all 6 bar tables | All 6 `cmc_price_bars_*` tables |
| 12 | `021_reorder_bar_columns.sql` | 2026-02-17 | Drop all 6 bar tables for column reorder (data rebuilt via bar builders) | All 6 `cmc_price_bars_*` tables |
| 13 | `alter_cmc_ema_multi_tf_u_drop_derivatives.sql` | 2026-02-20 | Drop derivative columns (d1, d2, etc.) from EMA unified table; add is_partial_end | `cmc_ema_multi_tf_u` |
| 14 | `alter_cmc_features_redesign.sql` | 2026-02-20 | Major redesign: drop EMA + legacy return columns; add 46 bar returns + 36 vol + 18 TA columns | `cmc_features` |
| 15 | `alter_returns_tables_add_zscore.sql` | 2026-02-20 | Add z-score + is_outlier columns to all 11 returns tables (5 bar + 6 EMA) | All bar and EMA returns tables |
| 16 | `alter_returns_tables_multi_window_zscore.sql` | 2026-02-20 | Rename existing z-scores to _365 suffix; add _30 and _90 window variants | All bar and EMA returns tables |
| 17 | `alter_feature_tables_add_alignment_source.sql` | 2026-02-22 | Add alignment_source column to cmc_vol, cmc_ta, cmc_features for unified table sourcing | `cmc_vol`, `cmc_ta`, `cmc_features` |

**Catalog notes:**
- Files 1-5 (2025-12-20) were part of the v0.6.0 multi-TF feature pipeline build-out.
- Files 6-7 (2025-12-24) were emergency data recovery scripts.
- Files 8-12 (2026-02-17) were the Phase 26 unified bar schema migration.
- Files 13-17 (2026-02-20 to 2026-02-22) were the v0.7.0 cmc_features redesign.

**Classification of "rebuild" files:** Files 4, 5, 6, 7 are data migration scripts (TRUNCATE + INSERT), not pure schema changes. They are still part of the historical migration catalog because they changed the effective state of the DB and would need to be re-run on a clean build.

**Archive vs keep-in-place:** Keep files at `sql/migration/`. Do not move them. The DISASTER_RECOVERY.md references them. Add a `CATALOG.md` header comment explaining they are historical reference only.

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Raw SQL files in `sql/migration/` | Alembic revision files in `alembic/versions/` | Starting Phase 33 | All new schema changes tracked; DB state verifiable with `alembic current` |
| Manual `psql -f` execution | `alembic upgrade head` | Starting Phase 33 | Transaction management, error reporting, ordering guarantees |

**Not deprecated:**
- `sql/migration/` files remain as historical reference — do not delete
- `sql/ddl/` and `sql/features/` are initial creation scripts (used in DISASTER_RECOVERY rebuild), not migrations — separate concern from Alembic

---

## Workflow Document Location and Scope

**Recommendation:** Add a `## Schema Migrations (Alembic)` section to `CONTRIBUTING.md`. Do not create a separate `docs/operations/SCHEMA_MIGRATIONS.md`.

**Rationale:** CONTRIBUTING.md is the document a future developer reads when they need to make a change. That's exactly when they need migration instructions. Operations docs are for runtime operations, not development workflow.

**Required sections in CONTRIBUTING.md:**
1. Quick reference (the 5-step revision workflow)
2. Gotchas section (autogenerate trap, encoding pitfall, CWD requirement)
3. Reference to catalog (`sql/migration/` + the catalog table)

---

## CI Integration Scope

**Recommended for Phase 33:** Add `alembic history` check to `validation.yml` as a structural check (no DB needed).

```yaml
# In .github/workflows/validation.yml
alembic-history:
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4
    - uses: actions/setup-python@v5
      with:
        python-version: "3.12"
    - name: Install alembic
      run: pip install -e ".[dev]"   # alembic is in core deps
    - name: Verify alembic revision chain is valid
      run: alembic history
      # reads only filesystem — no DB connection needed
```

**Why `alembic history` in CI:** Catches corrupted revision chain, missing files, syntax errors in revision scripts. Does not require DB. Fast (reads filesystem only).

**Not in scope for Phase 33:** `alembic current` in CI (requires live DB). `alembic upgrade --sql` diff generation. These can be added in a later phase.

---

## DISASTER_RECOVERY.md Update

The file already mentions alembic at lines 95-103:

```markdown
### Alembic Migration State (if Phase 33 is complete)
If Alembic migrations have been set up, mark the migration state as current after restore to prevent Alembic from re-applying migrations:
```bash
alembic stamp head
```

This section is already correct. After Phase 33 completes, update it to remove the "if Phase 33 is complete" conditionality and add:
- Mention of `alembic_version` table (created by stamp, contains single row with current revision)
- Note that `alembic current` should show `<rev-id> (head)` after stamp
- Warning: if restore does NOT include the `alembic_version` table (e.g., table-by-table restore that skips it), run `alembic stamp head` to recreate it

---

## Open Questions

None that could not be resolved through research and testing. All key decisions are documented in CONTEXT.md and MEMORY.md.

---

## Sources

### Primary (HIGH confidence)
- Alembic 1.18.4 PyPI page — confirmed latest version
- `alembic init` generated files (verified locally with alembic 1.18.4) — default env.py, alembic.ini, script.py.mako
- `alembic revision`, `stamp`, `current`, `history` commands tested locally with SQLite — behavior verified
- `src/ta_lab2/scripts/refresh_utils.py` — `resolve_db_url()` signature and behavior read directly
- `CONTRIBUTING.md`, `docs/operations/DISASTER_RECOVERY.md`, `pyproject.toml`, `Makefile` — all read directly

### Secondary (MEDIUM confidence)
- Alembic 1.18.4 official docs (WebFetch): tutorial, cookbook, autogenerate limitations
- GitHub discussion on custom URL loading (#1043) — confirms env.py override pattern is standard

### Tertiary (LOW confidence)
- None — all findings verified against official docs or local testing

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — alembic 1.18.4 confirmed current; installed and tested locally
- Architecture: HIGH — env.py pattern verified by running alembic init and testing stamp/current/history
- Pitfalls: HIGH — encoding pitfall from MEMORY.md; autogenerate pitfall from official docs + verified understanding; others reasoned from codebase patterns
- Legacy catalog: HIGH — git dates and file purposes verified by reading actual files

**Research date:** 2026-02-23
**Valid until:** 2026-05-23 (alembic API is stable; minor versions unlikely to break patterns)
