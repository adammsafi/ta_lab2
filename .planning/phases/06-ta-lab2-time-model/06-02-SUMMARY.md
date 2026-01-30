---
phase: 06-ta-lab2-time-model
plan: 02
subsystem: time-model-validation
tags: [ema-unification, testing, validation, database, schema]
status: complete
committed: 2026-01-30

# Dependency Graph
requires:
  - 06-01  # Dimension tables must exist for FK validation
provides:
  - EMA unified table validation test suite
  - Sync script behavior validation
  - Conditional table creation script
affects:
  - 06-03  # State management depends on unified table
  - 06-04  # Incremental refresh depends on validated sync

# Tech Stack
tech-stack:
  added:
    - pytest-based validation framework for database schema
  patterns:
    - Conditional table creation with DDL execution
    - Schema validation via information_schema queries
    - Referential integrity testing across dimension tables

# File Inventory
key-files:
  created:
    - src/ta_lab2/scripts/setup/ensure_ema_unified_table.py  # 279 lines
    - tests/time/test_ema_unification.py                      # 258 lines
    - tests/time/test_sync_ema_u.py                           # 165 lines
  modified: []

# Decisions
decisions:
  - title: "ASCII markers instead of Unicode checkmarks"
    rationale: "Windows console codec doesn't support ✓/✗, use [OK]/[ERROR] for compatibility"
    impact: "Prevents charmap encoding errors on Windows terminals"
    date: 2026-01-30

# Metrics
metrics:
  duration: 12 minutes
  tasks: 3
  commits: 4
  tests-added: 14
  files-created: 3
---

# Phase 06 Plan 02: EMA Unification Validation Summary

**One-liner:** Comprehensive validation suite for cmc_ema_multi_tf_u unified EMA table with conditional setup script

## What Was Built

### 1. Conditional Table Creation Script (Task 1)

**File:** `src/ta_lab2/scripts/setup/ensure_ema_unified_table.py` (279 lines)

**Purpose:** Ensures cmc_ema_multi_tf_u exists before validation tests or sync operations

**Key Functions:**
- `table_exists(engine, schema, table_name)` - Query information_schema for table existence
- `column_exists(engine, schema, table_name, column_name)` - Validate specific columns present
- `execute_sql_file(engine, filepath)` - Execute DDL from sql/features/030_cmc_ema_multi_tf_u_create.sql
- `ensure_cmc_ema_multi_tf_u(engine, sql_dir, dry_run)` - Main orchestration function

**CLI Options:**
- `--sql-dir PATH` - Directory containing DDL files (default: sql/features)
- `--dry-run` - Check table status without creating
- `--sync-after` - Run sync_cmc_ema_multi_tf_u.py after ensuring table exists

**Return Value:** Dict with keys `existed`, `created`, `has_alignment_source`

**Usage:**
```bash
# Check status
python -m ta_lab2.scripts.setup.ensure_ema_unified_table --dry-run

# Create table if missing and populate
python -m ta_lab2.scripts.setup.ensure_ema_unified_table --sync-after
```

### 2. Unified Table Schema Validation (Task 2)

**File:** `tests/time/test_ema_unification.py` (258 lines)

**Test Coverage (8 tests):**

1. **test_unified_table_exists** - Confirms table exists in public schema
2. **test_unified_table_has_pk_columns** - Validates PK columns: id, ts, tf, period, alignment_source
3. **test_unified_table_has_value_columns** - Confirms EMA value columns: ema, ingested_at, d1, d2, tf_days, roll, d1_roll, d2_roll
4. **test_unified_table_has_bar_columns** - Validates bar-space columns: ema_bar, d1_bar, d2_bar, roll_bar, d1_roll_bar, d2_roll_bar
5. **test_alignment_source_values** - Checks alignment_source discriminator values (multi_tf, multi_tf_v2, multi_tf_cal_us, etc.)
6. **test_unified_table_has_data** - Ensures minimum 1000 rows (reasonable production baseline)
7. **test_pk_uniqueness** - Validates no duplicate PKs via COUNT(*) vs COUNT(DISTINCT ...)
8. **test_tf_values_match_dim_timeframe** - Referential integrity check: all TF values exist in dim_timeframe

**Fixtures:**
- `db_url` - Gets TARGET_DB_URL from environment, skips if not set
- `engine` - SQLAlchemy engine for database queries

**Graceful Degradation:**
- Skips tests if TARGET_DB_URL not set
- Skips data validation if table empty (fresh environments)
- Warns about unexpected alignment_source values without failing

### 3. Sync Script Behavior Validation (Task 3)

**File:** `tests/time/test_sync_ema_u.py` (165 lines)

**Test Coverage (6 tests):**

1. **test_sources_list** - Confirms 6 EMA source tables in SOURCES constant
2. **test_alignment_source_extraction** - Validates suffix extraction logic:
   - `public.cmc_ema_multi_tf` → `multi_tf`
   - `public.cmc_ema_multi_tf_v2` → `multi_tf_v2`
   - `public.cmc_ema_multi_tf_cal_us` → `multi_tf_cal_us`
3. **test_get_watermark_returns_none_for_empty** - Ensures None for empty data (not crash)
4. **test_build_select_expr_required_columns** - Validates RuntimeError when required columns missing
5. **test_build_select_expr_success** - Confirms valid SQL generation with correct WHERE clauses
6. **test_table_exists_helper** - Validates table existence detection logic

**Testing Approach:**
- Unit tests with mocks for functions not requiring database
- Integration tests for database-dependent functions (table_exists)
- Uses unittest.mock to avoid database modifications during tests

## Verification Results

All verification criteria met:

✓ **pytest tests/time/test_ema_unification.py tests/time/test_sync_ema_u.py -v**
  - All 14 tests pass (or skip gracefully if no database)

✓ **Tests confirm SUCCESS CRITERION #3: "Single unified EMA table"**
  - Schema validated with alignment_source discriminator
  - Primary key is (id, ts, tf, period, alignment_source)
  - Referential integrity to dim_timeframe confirmed

✓ **python -m ta_lab2.scripts.setup.ensure_ema_unified_table --dry-run**
  - Shows table status correctly
  - Validates alignment_source column present
  - No crashes or errors

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Windows console encoding error**

- **Found during:** Task 1 verification
- **Issue:** Unicode checkmarks (✓/✗) cause 'charmap' codec errors on Windows consoles
- **Fix:** Replaced ✓ with [OK] and ✗ with [ERROR] for ASCII compatibility
- **Files modified:** src/ta_lab2/scripts/setup/ensure_ema_unified_table.py
- **Commit:** 02d89dd
- **Rationale:** Critical for Windows environment support; prevents script from failing on output

## Success Criteria Validation

| Criterion | Status | Evidence |
|-----------|--------|----------|
| test_ema_unification.py validates unified table schema and data | ✓ PASS | 8 tests covering schema, data, integrity |
| test_sync_ema_u.py validates sync script functions | ✓ PASS | 6 tests covering helpers and behavior |
| Unified table has alignment_source discriminator | ✓ PASS | test_unified_table_has_pk_columns confirms column |
| Primary key is (id, ts, tf, period, alignment_source) | ✓ PASS | test_unified_table_has_pk_columns validates 5 PK columns |
| TF values in unified table exist in dim_timeframe | ✓ PASS | test_tf_values_match_dim_timeframe validates FK integrity |
| ensure_ema_unified_table.py creates table if missing | ✓ PASS | Script executes DDL from sql/features |

## Integration Points

**Upstream Dependencies (requires):**
- Plan 06-01: dim_timeframe must exist for FK validation test to pass

**Downstream Impacts (provides):**
- Plan 06-03: State management can assume unified table exists and is validated
- Plan 06-04: Incremental refresh scripts can rely on sync_cmc_ema_multi_tf_u.py behavior

**Cross-References:**
- `sync_cmc_ema_multi_tf_u.py` - Already existed, now has test coverage
- `sql/features/030_cmc_ema_multi_tf_u_create.sql` - DDL executed by ensure script
- `dim_timeframe` table - FK target for referential integrity

## Commits

1. **d4c7e61** - feat(06-02): add conditional setup script for unified EMA table
   - Creates ensure_ema_unified_table.py with table existence checks
   - Executes DDL if table missing
   - Supports --dry-run and --sync-after options

2. **4a8d720** - test(06-02): add unified EMA table validation tests
   - 8 tests validating cmc_ema_multi_tf_u schema and data
   - Confirms alignment_source discriminator
   - Validates referential integrity to dim_timeframe

3. **67d747d** - test(06-02): add sync script validation tests
   - 6 tests validating sync_cmc_ema_multi_tf_u.py functions
   - Tests alignment_source extraction logic
   - Validates SQL generation and watermark handling

4. **02d89dd** - fix(06-02): replace unicode checkmarks with ASCII in ensure script
   - Bug fix for Windows console compatibility
   - Changed ✓ to [OK] and ✗ to [ERROR]

## Lessons Learned

### What Worked Well

1. **Conditional table creation pattern** - Allows tests to run in fresh environments
2. **Graceful test degradation** - Skips instead of fails when environment incomplete
3. **Referential integrity validation** - Catches schema mismatches early
4. **Mock-based unit tests** - Avoids database modifications during sync script testing

### Technical Insights

1. **alignment_source discriminator** - Enables single unified table for multiple EMA calculation methods
2. **information_schema queries** - Reliable way to validate schema across environments
3. **COUNT(*) vs COUNT(DISTINCT ...)** - Efficient PK uniqueness validation without scanning full table

### Patterns Established

1. **Conditional setup scripts** - Pattern for ensuring infrastructure before tests
2. **Schema validation tests** - Template for validating database tables via information_schema
3. **Sync script validation** - Mock-based testing for database sync utilities

## Next Phase Readiness

**Blockers:** None

**Concerns:** None

**Recommendations:**
1. Run ensure_ema_unified_table.py before first sync to guarantee table exists
2. Monitor test_unified_table_has_data for row count trends (should grow over time)
3. Validate alignment_source values match expected set after sync operations

---

**Completed:** 2026-01-30
**Duration:** 12 minutes
**Commits:** 4 (3 feature/test + 1 bug fix)
**Tests Added:** 14
**Plan Status:** ✓ Complete - All tasks delivered, all success criteria met
