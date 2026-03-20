# Phase 74: Foundation & Shared Infrastructure - Research

**Researched:** 2026-03-19
**Domain:** Shared psycopg helpers, data-driven SourceSpec registry (dim_data_sources), alignment_source constants
**Confidence:** HIGH

## Summary

This phase extracts duplicated infrastructure from three existing 1D bar builders (CMC, TVC, Hyperliquid) into shared modules and creates a `dim_data_sources` table that captures per-source differences as data rather than code. Research involved reading all three 1D builder scripts, the base bar builder hierarchy, sync utilities, existing dim table DDL, and the recent venue_id migration.

The three builders share ~200 lines of identical psycopg helper code (`_normalize_db_url`, `_connect`, `_exec`, `_fetchone`, `_fetchall`) copied verbatim across files. They each have source-specific SQL CTEs with structurally similar patterns but different source tables, JOIN patterns, column mappings, and OHLC repair logic. The user decision is to store these SQL templates in a `dim_data_sources` table (not Python), making the system fully data-driven.

Five alignment_source values (`multi_tf`, `multi_tf_cal_us`, `multi_tf_cal_iso`, `multi_tf_cal_anchor_us`, `multi_tf_cal_anchor_iso`) are used across 25+ files but are never validated by CHECK constraints -- they're derived from table name string manipulation at sync time. Adding CHECK constraints to the 6 `_u` tables would prevent silent failures from typos.

**Primary recommendation:** Extract psycopg helpers to `src/ta_lab2/db/psycopg_helpers.py`, create `dim_data_sources` via Alembic migration with seed data for CMC/TVC/HL, and add CHECK constraints on `alignment_source` in all 6 `_u` tables.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| psycopg (v3) | 3.x | Raw SQL execution for CTE-heavy bar building | Already used, preferred over SQLAlchemy for CTE performance |
| psycopg2 | 2.9.x | Fallback driver | Already used, dual-driver pattern established |
| SQLAlchemy | 2.x | Alembic migrations, state management, ORM operations | Already used for all non-CTE DB operations |
| Alembic | 1.x | Schema migrations | Already used, 33 existing revisions |
| dataclasses | stdlib | Frozen config objects (BarBuilderConfig pattern) | Already used project-wide |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| argparse | stdlib | CLI for any new scripts | Only if new CLI entry points needed |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| dim_data_sources (DB table) | Python dict/YAML | User decided DB table -- locked decision |
| SQL templates in DB | Python CTE builder modules | User decided SQL-in-DB -- locked decision |

## Architecture Patterns

### Existing Project Structure (relevant subset)
```
src/ta_lab2/
  scripts/
    bars/
      base_bar_builder.py          # ABC Template Method pattern
      bar_builder_config.py        # Frozen dataclass config
      common_snapshot_contract.py  # 1700+ lines shared utilities
      refresh_price_bars_1d.py     # CMC 1D builder (822 lines)
      refresh_tvc_price_bars_1d.py # TVC 1D builder (511 lines)
      refresh_hl_price_bars_1d.py  # HL 1D builder (585 lines)
      sync_price_bars_multi_tf_u.py  # _u sync script
    sync_utils.py                  # Generic sync logic
    setup/
      ensure_dim_tables.py         # dim_timeframe/dim_sessions setup
```

### Recommended New Module Location
```
src/ta_lab2/
  db/
    __init__.py
    psycopg_helpers.py    # _normalize_db_url, _connect, _exec, _fetchone, _fetchall
```

**Rationale:** The helpers are general-purpose DB utilities, not specific to bars. Placing them in `ta_lab2.db` makes them importable by any module. The `scripts/bars/` directory is script-specific; a `db/` package is the proper home for shared database utilities.

### Pattern 1: Duplicated psycopg Helpers (extract target)

**What:** Five functions copied identically across 3 files (refresh_price_bars_1d.py, refresh_tvc_price_bars_1d.py, refresh_hl_price_bars_1d.py), totaling ~200 duplicated lines.

**Current state in each file:**
```python
# Identical in all 3 files:
def _normalize_db_url(url: str) -> str:
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
            return "postgresql://" + url[len(prefix):]
    return url

def _connect(db_url: str):
    """Create psycopg connection (v3 preferred, v2 fallback)."""
    url = _normalize_db_url(db_url)
    if PSYCOPG3:
        return psycopg.connect(url, autocommit=True)
    if PSYCOPG2:
        conn = psycopg2.connect(url)
        conn.autocommit = True
        return conn
    raise RuntimeError("Neither psycopg (v3) nor psycopg2 is installed.")

def _exec(conn, sql: str, params=None) -> None:
    """Execute SQL statement."""
    # ... psycopg v3/v2 branching

def _fetchone(conn, sql: str, params=None):
    """Execute SQL and return first row."""
    # ... psycopg v3/v2 branching

def _fetchall(conn, sql: str, params=None):
    """Execute SQL and return all rows."""
    # ... psycopg v3/v2 branching (only in CMC + HL builders)
```

**Subtle differences found:**
- CMC builder `_exec`/`_fetchone`/`_fetchall` have psycopg v3 vs v2 branching (using `with conn.cursor()` for v3)
- TVC and HL builders always use the simple `cur = conn.cursor()` pattern (no v3 context manager)
- CMC builder has `_fetchall`; TVC does not; HL has `_fetchall`
- The CMC version is the most complete -- use it as the canonical source

### Pattern 2: Source-Specific SQL CTE Differences

**What:** Each builder has a `_build_insert_bars_sql()` function that generates a source-specific SQL CTE.

**CMC (`refresh_price_bars_1d.py` lines 240-496):**
- Source: `cmc_price_histories7`
- JOINs: None (single source table)
- Columns: Has `s.name`, `s.source_file`, `s.load_ts`, `s.timeopen`, `s.timeclose`, `s.timehigh`, `s.timelow`, `s.marketcap`
- OHLC Repair: YES -- full repair pipeline with `base` -> `repaired` -> `final` CTEs
  - Detects `time_high`/`time_low` outside `[time_open, time_close]` range
  - Repairs by setting time_high_fix/time_low_fix based on close vs open relationship
  - Re-enforces OHLC invariants after repair
  - Returns repair counts (repaired_timehigh, repaired_timelow)
- Validation: 15 NOT NULL + sanity checks in WHERE clause
- ON CONFLICT: `(id, tf, bar_seq, "timestamp")` -- NOTE: no venue_id (legacy CMC)
- RETURNING: `repaired_timehigh, repaired_timelow, "timestamp"`
- Result: 4 columns (upserted, repaired_timehigh, repaired_timelow, max_src_ts)

**TVC (`refresh_tvc_price_bars_1d.py` lines 111-263):**
- Source: `tvc_price_histories`
- JOINs: `LEFT JOIN public.dim_listings dl ON dl.id = s.id AND dl.venue = s.venue`
- Columns: Has `s.venue`, `s.ts` (not `s.timestamp`), `s.source_file`, `s.ingested_at` (not `s.load_ts`), NO `s.name`, NO market_cap, NO timehigh/timelow
- OHLC Repair: NO -- sets all repair booleans to `false`, time_high/time_low = timestamp
- Venue: Multi-venue via `venue` column, optional `venue_filter` parameter
- Additional columns: `venue`, `venue_rank` in INSERT
- ON CONFLICT: `(id, tf, bar_seq, venue, "timestamp")` -- uses `venue` text
- RETURNING: `"timestamp"` only
- Result: 2 columns (upserted, max_src_ts)

**HL (`refresh_hl_price_bars_1d.py` lines 190-336):**
- Source: `hyperliquid.hl_candles` (cross-schema)
- JOINs: `JOIN dim_asset_identifiers dai ON dai.id_type = 'HL' AND dai.id_value::int = c.asset_id` + `LEFT JOIN public.dim_listings dl ON dl.id = dai.id AND dl.venue = 'HYPERLIQUID'`
- Columns: `c.open::double precision`, `c.high::double precision`, etc. (explicit casts), NO market_cap, NO timehigh/timelow
- OHLC Repair: NO -- same as TVC
- Venue: Hardcoded `'HYPERLIQUID'` text, `2::smallint` venue_id
- Filter: `c.interval = '1d'` (HL stores multiple intervals)
- Additional columns: `venue`, `venue_id`, `venue_rank` in INSERT
- ON CONFLICT: `(id, tf, bar_seq, venue_id, "timestamp")` -- uses `venue_id` SMALLINT
- RETURNING: `"timestamp"` only
- Result: 2 columns (upserted, max_src_ts)

### Pattern 3: ID Loading Patterns

**CMC:** `load_all_ids(db_url, daily_table)` via `common_snapshot_contract` -- `SELECT DISTINCT id FROM {daily_table}`
**TVC:** `_load_tvc_ids(db_url)` -- `SELECT DISTINCT id FROM tvc_price_histories`
**HL:** `_load_hl_ids(db_url, csv_path)` -- Reads HL_YN.csv for Y-marked asset_ids, then JOINs `dim_asset_identifiers WHERE id_type='HL'` to translate to dim_assets.id

### Pattern 4: dim Table Creation (established pattern)

**dim_venues (from Alembic migration a0b1c2d3e4f5):**
```sql
CREATE TABLE public.dim_venues (
    venue_id    SMALLINT PRIMARY KEY,
    venue       TEXT NOT NULL UNIQUE,
    description TEXT
);
INSERT INTO public.dim_venues (venue_id, venue, description) VALUES
    (1, 'CMC_AGG',      'CoinMarketCap aggregate'),
    (2, 'HYPERLIQUID',  'Hyperliquid DEX'),
    ...
```
- Simple 3-column design: surrogate PK, natural key (UNIQUE), description
- Seed data in the same Alembic migration
- No separate seed script

**dim_timeframe (from SQL files + ensure_dim_tables.py):**
```sql
CREATE TABLE IF NOT EXISTS public.dim_timeframe (
    tf text NOT NULL PRIMARY KEY,
    ...
    CONSTRAINT dim_timeframe_alignment_type_check CHECK (alignment_type = ANY (ARRAY['tf_day','calendar'])),
    CONSTRAINT dim_timeframe_roll_policy_check CHECK (roll_policy = ANY (ARRAY['multiple_of_tf','calendar_anchor'])),
    ...
);
```
- Natural PK (tf text)
- Multiple CHECK constraints on enumerated values
- Separate SQL seed files executed in order (010_create, 011_insert_daily, 012_insert_weekly, etc.)
- Has an `ensure_dim_tables.py` setup script for idempotent creation

### Pattern 5: alignment_source Value Derivation

**Current mechanism:** String manipulation at sync time, different per sync script:

```python
# sync_utils.py (used by sync_price_bars_multi_tf_u.py)
def alignment_source_from_table(full_name: str, prefix: str) -> str:
    _, table = split_schema_table(full_name)
    if table.startswith(prefix):
        return table[len(prefix):]
    return table
# Called with prefix="price_bars_" -> strips to get "multi_tf", "multi_tf_cal_us", etc.

# sync_ema_multi_tf_u.py (its own copy)
def alignment_source_from_table(full_name: str) -> str:
    _, table = split_schema_table(full_name)
    if table.startswith("cmc_ema_"):   # legacy prefix check
        return table.replace("cmc_ema_", "", 1)
    if table.startswith("ema_"):
        return table.replace("ema_", "", 1)
    return table
```

**Values used downstream:** `alignment_source` appears in 25+ files, used for:
- Filtering `_u` tables in feature computation
- Scoped DELETE in feature writes
- Daily features view JOIN conditions
- Feature config dataclass default: `alignment_source: str = "multi_tf"`

### Anti-Patterns to Avoid
- **String-based alignment_source derivation without validation:** Current approach derives values from table names -- a typo would create a silently wrong alignment_source with no error
- **Duplicating psycopg helpers in every new builder:** Three copies already exist; a fourth source would mean four copies
- **Hardcoding venue_id constants:** HL builder has `_HL_VENUE_ID = 2` as a module-level constant; should come from `dim_venues` or `dim_data_sources`
- **Mixing ON CONFLICT column sets:** CMC uses `(id, tf, bar_seq, "timestamp")`, TVC uses `(id, tf, bar_seq, venue, "timestamp")`, HL uses `(id, tf, bar_seq, venue_id, "timestamp")` -- the dim_data_sources table should specify which conflict columns apply

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| psycopg v3/v2 dual driver | Per-file import+fallback | Single module with PSYCOPG3/PSYCOPG2 flags | Already duplicated 3x, exact same logic |
| DB URL normalization | Per-file `_normalize_db_url` | Single `ta_lab2.db.psycopg_helpers.normalize_db_url` | 6 identical prefix checks across files |
| alignment_source values | String manipulation from table names | Constants + CHECK constraint | Typo-prevention, single source of truth |
| Source-specific SQL | Python CTE builder functions | SQL template TEXT columns in `dim_data_sources` | User decision: fully data-driven |

## Common Pitfalls

### Pitfall 1: ON CONFLICT Column Mismatch Between Sources
**What goes wrong:** CMC 1D bars use `ON CONFLICT (id, tf, bar_seq, "timestamp")` but the current PK after the venue_id migration is `(id, tf, bar_seq, venue_id, "timestamp")`. The SQL template stored in dim_data_sources must match the actual table PK.
**Why it happens:** The ON CONFLICT sets in the three builders were written at different times and some predate the venue_id migration.
**How to avoid:** The `dim_data_sources` table should store the ON CONFLICT column list, or the generic builder should always use the full PK from the target table's schema.
**Warning signs:** `ON CONFLICT DO UPDATE` silently inserts duplicates when conflict columns don't match actual PK.

### Pitfall 2: psycopg v3 Context Manager Semantics
**What goes wrong:** The CMC builder wraps cursor operations in `with conn.cursor() as cur:` for psycopg v3 but not v2. If the shared module uses the context manager pattern, it must still handle v2 gracefully.
**Why it happens:** psycopg v3 cursors are context managers; psycopg2 cursors are not guaranteed to work the same way with `with`.
**How to avoid:** Use the CMC builder's dual-path pattern in the shared module (it already handles both correctly).
**Warning signs:** `AttributeError` on cursor close, or cursor not closed on v2.

### Pitfall 3: SQL Template Interpolation Safety
**What goes wrong:** SQL templates stored in the DB will need parameter interpolation (table names, WHERE clauses). Using `%s` for table names in psycopg is not supported -- `%s` only works for values.
**Why it happens:** Table names and column identifiers cannot be parameterized via psycopg's native parameter binding.
**How to avoid:** Use Python `.format()` or f-string for structural SQL elements (table names, column lists) but `%s` for data values. The SQL template should use placeholders like `{src_table}`, `{dst_table}` for structural elements and `%s` for runtime values.
**Warning signs:** `psycopg2.errors.SyntaxError` when table names are passed as parameters.

### Pitfall 4: _u Table PK Variations
**What goes wrong:** The 6 _u tables have slightly different PKs:
- `price_bars_multi_tf_u`: `(id, tf, bar_seq, venue_id, "timestamp", alignment_source)`
- `ema_multi_tf_u`: `(id, ts, tf, period, venue_id)` -- NO alignment_source in PK, only as data column
- `returns_bars_multi_tf_u`: `(id, "timestamp", tf, venue_id, alignment_source)`
- `returns_ema_multi_tf_u`: `(id, ts, tf, period, venue_id, alignment_source)`
**Why it happens:** The _u tables were created at different times with different design decisions about whether alignment_source should be part of the PK.
**How to avoid:** The CHECK constraint on alignment_source should be added to ALL _u tables regardless of whether it's in the PK.
**Warning signs:** CHECK constraint DDL fails if alignment_source column doesn't exist.

### Pitfall 5: HL Builder Uses venue_id While TVC Uses venue TEXT
**What goes wrong:** The TVC builder's ON CONFLICT uses `venue` (TEXT), while HL uses `venue_id` (SMALLINT). After the migration, the PK uses venue_id, but the TVC builder may not have been fully updated.
**Why it happens:** TVC builder predates the venue_id migration and still references `venue` text in some places.
**How to avoid:** The dim_data_sources registry should normalize this: every source maps to a venue_id, not a venue text string.
**Warning signs:** Unique constraint violations or data duplication on insert.

## Code Examples

### Exact Functions to Extract (from refresh_price_bars_1d.py, lines 78-148)
```python
# Source: src/ta_lab2/scripts/bars/refresh_price_bars_1d.py

# These 5 functions are the extraction targets:

def _normalize_db_url(url: str) -> str:  # Lines 78-92
def _connect(db_url: str):                # Lines 95-104
def _exec(conn, sql, params=None):        # Lines 107-116
def _fetchall(conn, sql, params=None):    # Lines 119-132
def _fetchone(conn, sql, params=None):    # Lines 135-148
```

### dim_data_sources Table Schema (proposed)
```sql
-- Follows dim_venues pattern: Alembic migration + seed data
CREATE TABLE public.dim_data_sources (
    source_key        TEXT PRIMARY KEY,          -- e.g. 'cmc', 'tvc', 'hl'
    source_name       TEXT NOT NULL UNIQUE,       -- e.g. 'CoinMarketCap', 'TradingView', 'Hyperliquid'
    source_table      TEXT NOT NULL,              -- e.g. 'public.cmc_price_histories7'
    venue_id          SMALLINT NOT NULL REFERENCES dim_venues(venue_id),
    default_venue     TEXT NOT NULL,              -- e.g. 'CMC_AGG', 'HYPERLIQUID'
    ohlc_repair       BOOLEAN NOT NULL DEFAULT FALSE,
    has_market_cap    BOOLEAN NOT NULL DEFAULT FALSE,
    has_timehigh      BOOLEAN NOT NULL DEFAULT FALSE,  -- source has intraday H/L timestamps
    id_loader_sql     TEXT,                       -- SQL to load IDs (SELECT DISTINCT id FROM ...)
    src_cte_template  TEXT NOT NULL,              -- The WITH src_filtered AS (...) CTE
    join_clause       TEXT,                       -- Additional JOINs (e.g. dim_asset_identifiers for HL)
    id_filter_sql     TEXT NOT NULL,              -- WHERE clause fragment for filtering by id
    ts_column         TEXT NOT NULL DEFAULT 'timestamp',  -- Source timestamp column name
    src_name_label    TEXT NOT NULL,              -- Value for src_name in output (e.g. 'Hyperliquid')
    description       TEXT
);
```

### Seed Data for 3 Sources
```sql
INSERT INTO dim_data_sources (source_key, source_name, source_table, venue_id, ...) VALUES
  ('cmc', 'CoinMarketCap', 'public.cmc_price_histories7', 1, 'CMC_AGG', TRUE, TRUE, TRUE, ...),
  ('tvc', 'TradingView', 'public.tvc_price_histories', 9, 'TVC', FALSE, FALSE, FALSE, ...),
  ('hl',  'Hyperliquid', 'hyperliquid.hl_candles', 2, 'HYPERLIQUID', FALSE, FALSE, FALSE, ...);
```

### alignment_source CHECK Constraint
```sql
-- Applied to each of the 6 _u tables
ALTER TABLE public.price_bars_multi_tf_u
ADD CONSTRAINT chk_price_bars_u_alignment_source
CHECK (alignment_source IN (
    'multi_tf',
    'multi_tf_cal_us',
    'multi_tf_cal_iso',
    'multi_tf_cal_anchor_us',
    'multi_tf_cal_anchor_iso'
));
```

### Shared Helper Module Pattern
```python
# src/ta_lab2/db/psycopg_helpers.py

"""Shared psycopg v3/v2 helper functions.

Extracted from bar builder scripts to eliminate ~200 lines of duplication.
All bar builders, EMA refreshers, and other raw-SQL scripts should import
from this module instead of defining their own helpers.
"""
from __future__ import annotations
from typing import Any, List, Optional, Sequence, Tuple

# Dual-driver detection (done once at import time)
try:
    import psycopg  # type: ignore
    PSYCOPG3 = True
except Exception:
    psycopg = None
    PSYCOPG3 = False

try:
    import psycopg2  # type: ignore
    PSYCOPG2 = True
except Exception:
    psycopg2 = None
    PSYCOPG2 = False


def normalize_db_url(url: str) -> str:
    """Remove SQLAlchemy dialect prefix for psycopg connection."""
    ...

def connect(db_url: str):
    """Create psycopg connection (v3 preferred, v2 fallback)."""
    ...

def execute(conn, sql: str, params: Optional[Sequence[Any]] = None) -> None:
    """Execute SQL statement (psycopg v3/v2 compatible)."""
    ...

def fetchone(conn, sql: str, params: Optional[Sequence[Any]] = None) -> Optional[Tuple[Any, ...]]:
    """Execute SQL and fetch one row."""
    ...

def fetchall(conn, sql: str, params: Optional[Sequence[Any]] = None) -> List[Tuple[Any, ...]]:
    """Execute SQL and fetch all rows."""
    ...
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `cmc_` prefix on all tables | No prefix (exceptions: cmc_da_ids, etc.) | Phase 73 (Mar 2026) | Table names changed, scripts updated |
| `venue` TEXT in PKs | `venue_id` SMALLINT in PKs | Phase 73 (Mar 2026) | All PKs rebuilt, FKs to dim_venues |
| Per-file psycopg helpers | Still per-file (this phase fixes it) | Not yet | ~200 lines duplicated x3 |
| String-derived alignment_source | Still string-derived (this phase fixes it) | Not yet | No validation, typo risk |

**Currently outdated patterns:**
- TVC builder ON CONFLICT still uses `venue` TEXT in some places (should be `venue_id`)
- ema_multi_tf_u PK does not include alignment_source (unlike price_bars_multi_tf_u and returns_*_u tables)
- HL builder hardcodes `_HL_VENUE_ID = 2` as module constant instead of looking up from dim_venues

## Open Questions

1. **dim_data_sources SQL template granularity**
   - What we know: The user wants SQL templates stored as TEXT columns. The three builders have different CTE structures (CMC has 5 CTEs for repair, TVC/HL have 3 CTEs without repair).
   - What's unclear: Should there be one template column for the entire CTE chain, or separate columns for each logical section (source query, repair, final, insert)?
   - Recommendation: Start with a single `src_cte_template` column containing the full CTE from `WITH src_filtered AS (...)` through the `ranked` CTE. The insert/upsert logic can be standardized in the generic builder since it's structurally identical across all sources.

2. **Alembic seeding strategy**
   - What we know: dim_venues was seeded inline in the Alembic migration. dim_timeframe uses separate SQL seed files loaded by ensure_dim_tables.py.
   - What's unclear: Which pattern to follow for dim_data_sources (SQL templates are large text blobs -- inline in migration or separate files?)
   - Recommendation: Seed inline in the Alembic migration, matching the dim_venues pattern. The SQL templates are source-specific constants, not user-configurable data. Keep it simple.

3. **CHECK constraint on ema_multi_tf_u**
   - What we know: ema_multi_tf_u has `alignment_source TEXT NOT NULL DEFAULT 'unknown'` but it's NOT in the PK. The column exists and holds the same 5 values.
   - What's unclear: Whether adding a CHECK constraint would break anything for the 'unknown' default rows.
   - Recommendation: Add CHECK constraint but include 'unknown' in the allowed values if any rows currently use it. Query the table first in the migration to check.

4. **TVC venue_id discrepancy**
   - What we know: TVC builder uses `venue` TEXT in ON CONFLICT, but the PK was migrated to use `venue_id`. The TVC builder also does not set `venue_id` explicitly.
   - What's unclear: Whether the TVC builder is currently broken or if PostgreSQL's DEFAULT 1 handles it.
   - Recommendation: Investigate at plan time. The dim_data_sources entry for TVC must specify venue_id = 9 (TVC in dim_venues).

## Sources

### Primary (HIGH confidence)
- `src/ta_lab2/scripts/bars/refresh_price_bars_1d.py` -- Full CMC 1D builder with OHLC repair (822 lines)
- `src/ta_lab2/scripts/bars/refresh_tvc_price_bars_1d.py` -- Full TVC 1D builder (511 lines)
- `src/ta_lab2/scripts/bars/refresh_hl_price_bars_1d.py` -- Full HL 1D builder (585 lines)
- `src/ta_lab2/scripts/bars/base_bar_builder.py` -- BaseBarBuilder ABC (557 lines)
- `src/ta_lab2/scripts/bars/common_snapshot_contract.py` -- Shared utilities (1813 lines)
- `src/ta_lab2/scripts/bars/bar_builder_config.py` -- BarBuilderConfig frozen dataclass
- `src/ta_lab2/scripts/bars/sync_price_bars_multi_tf_u.py` -- Sync script showing alignment_source derivation
- `src/ta_lab2/scripts/emas/sync_ema_multi_tf_u.py` -- EMA sync with alignment_source
- `src/ta_lab2/scripts/sync_utils.py` -- Generic sync utilities
- `sql/ddl/create_price_bars_multi_tf_u.sql` -- _u table DDL with PK
- `sql/features/030_ema_multi_tf_u_create.sql` -- EMA _u table DDL
- `sql/dim/010_dim_timeframe_create_v2.sql` -- dim_timeframe DDL with CHECK constraints
- `alembic/versions/a0b1c2d3e4f5_strip_cmc_prefix_add_venue_id.py` -- dim_venues + venue_id migration
- `.planning/phases/74-foundation-shared-infrastructure/74-CONTEXT.md` -- User decisions

### Secondary (MEDIUM confidence)
- `src/ta_lab2/scripts/setup/ensure_dim_tables.py` -- Pattern for idempotent dim table creation
- `src/ta_lab2/scripts/features/base_feature.py` -- alignment_source usage in features (line 54, 117-119)
- `src/ta_lab2/scripts/features/run_all_feature_refreshes.py` -- alignment_source propagation in feature pipeline

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all libraries already in use, no new dependencies
- Architecture (psycopg helpers extraction): HIGH -- exact code to extract is identified, line numbers documented
- Architecture (dim_data_sources schema): MEDIUM -- schema is proposed based on differences found; exact SQL template format needs planner validation
- Pitfalls: HIGH -- all from direct code reading, no inference
- alignment_source values: HIGH -- all 5 values confirmed across 25+ files

**Research date:** 2026-03-19
**Valid until:** 2026-04-19 (stable codebase, no external dependencies changing)

## Appendix: Detailed Duplication Inventory

### Functions duplicated across 3 builders

| Function | CMC (1d) | TVC | HL | Lines Each | Notes |
|----------|----------|-----|-----|------------|-------|
| psycopg import block | L56-70 | L39-54 | L45-60 | 14 | Identical |
| `_normalize_db_url` | L78-92 | L56-70 | L66-79 | 14 | Identical |
| `_connect` | L95-104 | L73-82 | L83-92 | 10 | Identical |
| `_exec` | L107-116 | L85-90 | L95-100 | 6-10 | CMC has v3/v2 branch, TVC/HL simple |
| `_fetchone` | L135-148 | L93-100 | L103-110 | 8-14 | CMC has v3/v2 branch |
| `_fetchall` | L119-132 | N/A | L113-120 | 8-14 | Missing from TVC |
| `_get_last_src_ts` | L232-238 | L103-108 | L126-135 | 6-10 | HL adds venue_id filter |
| **Total per file** | | | | **~65** | **~195 total duplicated** |

### Source CTE Structure Comparison

| CTE Name | CMC | TVC | HL | Purpose |
|----------|-----|-----|-----|---------|
| `ranked_all` | Yes | No | No | dense_rank for ALL rows (before filtering) |
| `src_filtered` | No | Yes | Yes | DISTINCT ON + JOINs |
| `src_rows` | Yes | No | No | Source rows with JOIN to ranked_all |
| `ranked` | No | Yes | Yes | dense_rank (after JOIN) |
| `base` | Yes | No | No | Detect repair needs |
| `repaired` | Yes | No | No | Apply OHLC time_high/time_low repair |
| `final` | Yes | Yes | Yes | Add constants (tf='1D', repair=false, etc.) |
| `ins` | Yes | Yes | Yes | INSERT ... ON CONFLICT ... RETURNING |

### _u Tables with alignment_source Column

| Table | alignment_source in PK? | Current values |
|-------|------------------------|----------------|
| `price_bars_multi_tf_u` | YES | multi_tf, multi_tf_cal_us, multi_tf_cal_iso, multi_tf_cal_anchor_us, multi_tf_cal_anchor_iso |
| `ema_multi_tf_u` | NO (data only) | Same 5 values + possibly 'unknown' |
| `ama_multi_tf_u` | YES (assumed) | Same 5 values |
| `returns_bars_multi_tf_u` | YES | Same 5 values |
| `returns_ema_multi_tf_u` | YES | Same 5 values |
| `returns_ama_multi_tf_u` | YES (assumed) | Same 5 values |
