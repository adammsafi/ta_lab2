# Technology Stack: v1.1.0 Pipeline Consolidation & Storage Optimization

**Project:** ta_lab2
**Milestone:** v1.1.0 -- Pipeline Consolidation
**Researched:** 2026-03-19
**Overall confidence:** HIGH (existing stack verified from codebase; PostgreSQL migration strategies verified via official docs)

---

## Scope: What This Document Covers

This STACK.md covers ONLY the technology decisions for consolidating 6 table families (36 siloed tables down to 6 unified _u tables), rewriting ~30 scripts to write directly to _u tables, building a source registry for the 3 source-specific 1D bar builders (CMC, TVC, HL), and safely dropping 30 large tables (50M-91M+ rows) to reclaim 100GB+ storage.

**The question:** What stack additions or changes are needed for safe pipeline consolidation and large-table migration in PostgreSQL?

**Answer: Almost nothing new.** The existing stack (Python 3.12, PostgreSQL, SQLAlchemy 2.0+, Alembic 1.18+, psycopg2, pandas, Polars) already has everything needed. This milestone is a code refactoring and data migration exercise, not a technology adoption exercise. The recommendations below focus on patterns, PostgreSQL-native strategies, and one optional dev dependency.

---

## Confirmed Existing Stack (All Sufficient)

| Package | Version (pyproject.toml) | Role in This Milestone |
|---------|-------------------------|----------------------|
| PostgreSQL | 14+ (server) | Transactional DDL for safe migrations, DROP TABLE, VACUUM |
| SQLAlchemy | >=2.0 | Engine management, text() for raw SQL, Alembic integration |
| Alembic | >=1.18 | Migration scripts for dropping FKs, tables, and rebuilding PKs |
| psycopg2-binary | >=2.9 | Raw SQL execution in bar builders (performance-critical CTEs) |
| pandas | (unpinned) | DataFrame operations in sync_utils, audit scripts |
| Polars | >=0.19.0 | Used by derive_multi_tf_from_1d.py for aggregation |
| PyYAML | (unpinned) | Could be used for source registry config (already installed) |
| pytest | >=8.0 (dev) | Migration validation test suite |
| pytest-cov | >=4.0.0 (dev) | Coverage for new tests |

**Key insight:** This milestone is infrastructure surgery on an existing system, not a greenfield build. Every tool needed is already installed and battle-tested across 290+ scripts. The risk is in the migration strategy, not in the tooling.

---

## Decision 1: Source Registry Pattern for 1D Bar Builders

### Question: How to consolidate 3 source-specific 1D builders (CMC, TVC, HL) into one generic builder?

**Recommendation: Python-native class registry using BaseBarBuilder inheritance + a dataclass-based SourceConfig registry. No new libraries needed.**

**Confidence: HIGH**

### Current State

Three separate files with massive code duplication:
- `refresh_price_bars_1d.py` (OneDayBarBuilder) -- 822 lines, reads from `cmc_price_histories7`
- `refresh_tvc_price_bars_1d.py` (TvcOneDayBarBuilder) -- 510 lines, reads from `tvc_price_histories`
- `refresh_hl_price_bars_1d.py` (HlOneDayBarBuilder) -- 584 lines, reads from `hyperliquid.hl_candles`

All three share: psycopg connection management, `_normalize_db_url()`, `_connect()`, `_exec()`, `_fetchone()`, `_fetchall()`, state table DDL, coverage tracking, CLI argument parsing. The only real differences are:
1. Source table and JOIN logic (e.g., HL needs `dim_asset_identifiers` JOIN)
2. Column mapping (e.g., TVC has no `market_cap`, HL synthesizes `time_high/time_low`)
3. OHLC repair (CMC needs repair, TVC/HL do not)
4. ID loading strategy (CMC from `cmc_price_histories7`, TVC from `tvc_price_histories`, HL from `HL_YN.csv` + `dim_asset_identifiers`)

### Recommended Pattern

```python
@dataclass(frozen=True)
class SourceConfig:
    """Configuration for a data source in the unified 1D bar builder."""
    source_name: str           # "CoinMarketCap", "TradingView", "Hyperliquid"
    source_table: str          # "public.cmc_price_histories7"
    venue_id: int              # 1 (CMC_AGG), 9 (TVC), 2 (HYPERLIQUID)
    needs_ohlc_repair: bool    # True for CMC, False for TVC/HL
    has_market_cap: bool       # True for CMC, False for TVC/HL
    has_intraday_timestamps: bool  # True for CMC, False for TVC/HL
    id_loader: Callable        # function(db_url) -> list[int]
    source_query_builder: Callable  # function(id_, start_ts, venue_filter) -> SQL

# Registry: dict keyed by source name
SOURCE_REGISTRY: dict[str, SourceConfig] = {}

def register_source(config: SourceConfig) -> None:
    SOURCE_REGISTRY[config.source_name] = config
```

### Why This Pattern

1. **Already fits BaseBarBuilder** -- The abstract class already defines `get_source_query()`, `build_bars_for_id()`, etc. The registry extends this by parameterizing what varies across sources.
2. **No new dependencies** -- Uses `@dataclass` (stdlib), `Callable` (typing), and a plain `dict`. The existing `BarBuilderConfig` dataclass is the proven pattern.
3. **Testable** -- Each `SourceConfig` is a frozen dataclass, easily constructed in tests without database access.
4. **Extensible** -- Adding a new source (e.g., Binance) means adding one `SourceConfig` instance and one SQL query builder function, not a new 500-line file.

### What NOT to Use

| Library | Why Not |
|---------|---------|
| `autoregistry` PyPI package | Overkill for 3-5 sources. A plain dict is clearer and debuggable. |
| Plugin directory auto-discovery | Only needed for 10+ plugins. With 3 sources, explicit registration is simpler. |
| YAML config for source definitions | SQL query builders need to be Python callables, not declarative config. PyYAML would add indirection without benefit. |
| Abstract factory with metaclass `__init_subclass__` | Clever but harder to grep/debug. Explicit registration is better for a team of 1. |

---

## Decision 2: Direct-Write to _u Tables (Eliminating Sync Scripts)

### Question: How to rewrite ~30 scripts to write directly to _u tables instead of siloed tables?

**Recommendation: Modify each builder/refresher to write directly to the _u table with an alignment_source literal. Use the existing `ON CONFLICT DO UPDATE` upsert pattern. No new tools needed.**

**Confidence: HIGH**

### Current Flow (6 families x 5 variants = 30 siloed writes + 6 sync scripts)

```
Builder writes to: price_bars_multi_tf_cal_us
                   price_bars_multi_tf_cal_iso
                   price_bars_multi_tf_cal_anchor_us
                   price_bars_multi_tf_cal_anchor_iso
                   price_bars_multi_tf
                              |
                              v
sync_price_bars_multi_tf_u.py ---> price_bars_multi_tf_u
  (INSERT...ON CONFLICT DO NOTHING, watermark-based)
```

### Target Flow (same builders write directly to _u)

```
Builder writes to: price_bars_multi_tf_u
  (with alignment_source = 'multi_tf_cal_us')
  (ON CONFLICT (id, tf, bar_seq, venue_id, timestamp, alignment_source) DO UPDATE)
```

### What Changes Per Script

Each of the ~30 builder/refresher scripts needs:
1. **Output table**: Change from `price_bars_multi_tf_cal_us` to `price_bars_multi_tf_u`
2. **INSERT column list**: Add `alignment_source` column with a literal value
3. **ON CONFLICT clause**: Include `alignment_source` in the PK columns
4. **State table**: Continue using the variant-specific state table (no change)

### Stack Implications

- **No new libraries.** The `ON CONFLICT DO UPDATE` upsert pattern is already used everywhere.
- **sync_utils.py becomes obsolete.** After all builders write directly to _u, the 6 sync scripts (`sync_price_bars_multi_tf_u.py`, `sync_ema_multi_tf_u.py`, etc.) can be deleted.
- **ingested_at watermark no longer needed for sync** (sync scripts used `MAX(ingested_at)` as watermark; direct writes eliminate this).

---

## Decision 3: PostgreSQL Migration Strategy for Dropping 30 Large Tables

### Question: How to safely drop 30 tables (50M-91M+ rows each) and reclaim 100GB+ disk space?

**Recommendation: Alembic migration with dependency-ordered drops, preceded by validation queries. Use DROP TABLE (not TRUNCATE), which immediately reclaims disk space. No new tools needed.**

**Confidence: HIGH**

### PostgreSQL Behavior: DROP TABLE vs DELETE + VACUUM

| Operation | Disk Reclamation | Locking | Speed |
|-----------|-----------------|---------|-------|
| `DROP TABLE tablename` | **Immediate** -- files removed from disk | Brief AccessExclusive lock | Seconds, regardless of row count |
| `TRUNCATE tablename` | **Immediate** -- files removed | AccessExclusive lock | Seconds |
| `DELETE FROM tablename` + `VACUUM FULL` | Requires VACUUM FULL for OS reclamation | VACUUM FULL: AccessExclusive lock | Hours for 50M+ rows |

**DROP TABLE is the correct choice here.** Once data is verified in the _u tables, the siloed tables are dead weight. DROP TABLE removes the heap files and all associated indexes from disk immediately. There is no need for VACUUM.

Source: [PostgreSQL DROP TABLE documentation](https://www.postgresql.org/docs/current/sql-droptable.html)

### Dependency Order

Tables must be dropped in the correct order to avoid FK constraint violations:

```
Phase 1: Drop state tables (no FKs reference them)
  - price_bars_multi_tf_state
  - price_bars_multi_tf_cal_us_state
  - price_bars_multi_tf_cal_iso_state
  - price_bars_multi_tf_cal_anchor_us_state
  - price_bars_multi_tf_cal_anchor_iso_state
  (repeat for EMA, AMA, returns_bars, returns_ema families)

Phase 2: Drop dependent views/matviews (if any reference siloed tables)
  - Check: SELECT * FROM pg_depend WHERE refobjid = 'tablename'::regclass

Phase 3: Drop data tables
  - price_bars_multi_tf
  - price_bars_multi_tf_cal_us
  - price_bars_multi_tf_cal_iso
  - price_bars_multi_tf_cal_anchor_us
  - price_bars_multi_tf_cal_anchor_iso
  (repeat for all 6 families)
```

### Alembic Migration Structure

```python
# alembic/versions/xxxx_drop_siloed_tables.py

def upgrade():
    # Phase 1: Validate data exists in _u tables (fail-fast)
    conn = op.get_bind()
    for family in FAMILIES:
        u_count = conn.execute(text(f"SELECT COUNT(*) FROM {family}_u")).scalar()
        if u_count == 0:
            raise RuntimeError(f"ABORT: {family}_u is empty, cannot drop siloed tables")

    # Phase 2: Drop FKs that reference siloed tables (if any)
    # Phase 3: Drop state tables
    for table in STATE_TABLES:
        op.drop_table(table)

    # Phase 4: Drop data tables
    for table in DATA_TABLES:
        op.drop_table(table)

def downgrade():
    # Downgrade: recreate table structure (data NOT recoverable)
    # This is a one-way migration. Document clearly.
    raise NotImplementedError(
        "Downgrade not supported: siloed table data was dropped. "
        "Restore from backup if needed."
    )
```

### Pre-Migration Validation (Run Before Alembic)

A standalone validation script (not part of Alembic) that compares row counts and checksums:

```sql
-- Row count validation per (family, alignment_source)
SELECT
    'price_bars' AS family,
    alignment_source,
    COUNT(*) AS u_rows
FROM price_bars_multi_tf_u
GROUP BY alignment_source

UNION ALL

SELECT
    'price_bars' AS family,
    'multi_tf' AS alignment_source,
    COUNT(*) AS siloed_rows
FROM price_bars_multi_tf
-- ... repeat for each siloed table
```

### Storage Estimation

Based on the project's table sizes (from MEMORY.md):

| Family | Siloed Table Rows | Tables | Estimated Storage |
|--------|-------------------|--------|-------------------|
| AMA values | ~91.3M | 5 | ~40-50 GB |
| AMA returns | ~91.3M | 5 | ~40-50 GB |
| EMA values | ~14.8M | 5 | ~8-10 GB |
| EMA returns | ~16M | 5 | ~8-10 GB |
| Price bars | ~4.1M | 5 | ~3-5 GB |
| Bar returns | ~4.1M | 5 | ~3-5 GB |
| **Total** | | **30 tables** | **~100-130 GB** |

All this storage is immediately reclaimable via DROP TABLE.

---

## Decision 4: Testing Strategy for Data Pipeline Migration

### Question: How to validate data integrity during and after the migration?

**Recommendation: Three-layer validation using pytest + raw SQL. One optional new dev dependency: `pytest-alembic`.**

**Confidence: HIGH**

### Layer 1: Pre-Migration Validation Script (Standalone)

Before running any Alembic migrations, a standalone Python script validates that _u tables contain all data from siloed tables:

```python
# Checks per family:
# 1. Row count: SUM(siloed) == COUNT(_u)
# 2. Aggregate checksum: SUM(close) per (id, tf) matches between siloed and _u
# 3. Min/max timestamp coverage: no data loss at boundaries
# 4. alignment_source completeness: all 5 variants present in _u
```

**No new libraries needed** -- uses SQLAlchemy `text()` and pandas for comparison DataFrames. This pattern already exists in `audit_price_bars_integrity.py` and `audit_price_bars_tables.py`.

### Layer 2: Alembic Migration Tests (pytest-alembic)

**Optional new dev dependency: `pytest-alembic>=0.12.1`**

This is the only new library recommendation for this milestone. It provides:
- `test_single_head_revision` -- Ensures migration history is linear
- `test_upgrade` -- Runs all migrations from base to head
- `test_model_definitions_match_ddl` -- Verifies models match DB state

**Why add it:** The project already has 33 Alembic migrations. This milestone adds at least 1 more (the drop migration). `pytest-alembic` catches common mistakes like broken revision chains or missing downgrade paths. The project already uses pytest extensively.

**Why it's optional:** The existing CI pipeline has an `alembic-history` job that likely covers the revision chain check. If that's sufficient, skip this.

```toml
# pyproject.toml addition (dev only)
[project.optional-dependencies]
dev = [
    # ... existing ...
    "pytest-alembic>=0.12.1",  # Optional: Alembic migration tests
]
```

Source: [pytest-alembic on PyPI](https://pypi.org/project/pytest-alembic/) -- v0.12.1 released May 2025, supports Python >=3.9

### Layer 3: Post-Migration Smoke Tests (pytest)

After migration, integration tests verify the pipeline still works end-to-end:

```python
@pytest.mark.integration
def test_bar_builder_writes_to_u_table(engine):
    """After consolidation, bar builder should write directly to _u table."""
    # Run builder for 1 ID, 1 TF
    # Assert rows exist in price_bars_multi_tf_u with correct alignment_source
    # Assert siloed table does NOT exist (post-drop)

@pytest.mark.integration
def test_downstream_reads_unaffected(engine):
    """Features, signals, regimes all read from _u tables already."""
    # Verify feature computation works with _u table as source
```

**No new libraries needed** -- uses existing pytest, pytest-mock, SQLAlchemy.

---

## Decision 5: Monitoring Table Sizes During Migration

### Question: How to track storage reclamation progress?

**Recommendation: PostgreSQL-native `pg_total_relation_size()` queries. No new tools.**

**Confidence: HIGH**

### Pre-Migration Size Capture

```sql
SELECT
    schemaname || '.' || relname AS table_name,
    pg_size_pretty(pg_total_relation_size(relid)) AS total_size,
    pg_total_relation_size(relid) AS size_bytes
FROM pg_stat_user_tables
WHERE relname LIKE '%multi_tf%'
   OR relname LIKE '%ema_multi_tf%'
   OR relname LIKE '%ama_multi_tf%'
   OR relname LIKE '%returns_%multi_tf%'
ORDER BY pg_total_relation_size(relid) DESC;
```

### Post-Migration Verification

```sql
-- After DROP TABLE: same query should show only _u tables
-- Total size should be ~50% of pre-migration (only _u tables remain)
SELECT
    pg_size_pretty(pg_database_size(current_database())) AS db_size;
```

Source: [PostgreSQL pg_total_relation_size](https://pgpedia.info/p/pg_total_relation_size.html)

---

## What NOT to Add (And Why)

| Candidate | Why NOT |
|-----------|---------|
| **pg_partman** (table partitioning) | The _u tables are not large enough to need partitioning. The biggest (_u table for AMA) will be ~91M rows. PostgreSQL handles this fine with proper indexes. Partitioning adds operational complexity. |
| **pgloader** (data migration tool) | We are not migrating data between databases. The sync scripts already moved data into _u tables. We are dropping source tables. |
| **Great Expectations** | Overkill for this milestone. The validation needs are simple (row counts, aggregate checksums) and well-served by raw SQL + pandas. |
| **dbt** (data build tool) | The project uses a Python-script pipeline, not a SQL-first pipeline. Introducing dbt for one milestone would create two paradigms. |
| **Any ORM models for the siloed tables** | The project uses raw SQL for performance-critical paths. Adding SQLAlchemy ORM models for tables about to be dropped is wasted effort. |
| **Database migration testing frameworks** (besides pytest-alembic) | `django-test-migrations` is Django-specific. Other frameworks are too heavy for this use case. |

---

## Installation

No new core dependencies. One optional dev dependency:

```bash
# Optional: Alembic migration tests
pip install pytest-alembic>=0.12.1
```

No changes to `pyproject.toml` core dependencies. The optional addition to dev dependencies:

```toml
# Only if pytest-alembic is adopted
dev = [
    # ... existing entries ...
    "pytest-alembic>=0.12.1",
]
```

---

## Summary: Stack Delta for v1.1.0

| Category | Additions | Removals |
|----------|-----------|----------|
| Core dependencies | **None** | None |
| Dev dependencies | `pytest-alembic>=0.12.1` (optional) | None |
| Python patterns | SourceConfig dataclass + registry dict | 3 duplicated builder files |
| PostgreSQL | DROP TABLE (already available) | 30 siloed tables + 30 state tables |
| Scripts | 1 unified builder, ~30 modified scripts | 6 sync scripts, 3 source-specific builders |

**The stack is already right. The work is in the code, not in the tooling.**

---

## Sources

- [PostgreSQL DROP TABLE Documentation](https://www.postgresql.org/docs/current/sql-droptable.html) -- Confirms immediate disk space reclamation
- [PostgreSQL VACUUM Documentation](https://www.postgresql.org/docs/current/sql-vacuum.html) -- Confirms VACUUM FULL not needed for DROP TABLE
- [PostgreSQL pg_total_relation_size](https://pgpedia.info/p/pg_total_relation_size.html) -- Table size monitoring
- [pytest-alembic on PyPI](https://pypi.org/project/pytest-alembic/) -- v0.12.1, May 2025
- [Alembic Operation Reference](https://alembic.sqlalchemy.org/en/latest/ops.html) -- `op.drop_table()` documentation
- [Python Registry Pattern](https://dev.to/dentedlogic/stop-writing-giant-if-else-chains-master-the-python-registry-pattern-ldm) -- Pattern reference
- [Data Migration Validation Best Practices](https://www.quinnox.com/blogs/data-migration-validation-best-practices/) -- Layered validation approach
- [Data Migration Testing Guide](https://datalark.com/blog/data-migration-testing-guide) -- Row count + checksum methodology
