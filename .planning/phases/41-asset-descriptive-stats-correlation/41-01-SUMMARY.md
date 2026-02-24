---
phase: 41-asset-descriptive-stats-correlation
plan: "01"
subsystem: database
tags: [alembic, postgresql, migrations, timeseries, correlation, statistics, materialized-view]

# Dependency graph
requires:
  - phase: 38-feature-experimentation
    provides: "6f82e9117c58 alembic head (feature_experiment_tables) that this chains from"
provides:
  - "cmc_asset_stats table: wide-format rolling stats per (id, ts, tf) with 32 stat columns"
  - "cmc_cross_asset_corr table: long-format pairwise correlation per (id_a, id_b, ts, tf, window) with CHECK(id_a < id_b)"
  - "cmc_asset_stats_state table: watermark tracking for incremental stats refresh"
  - "cmc_cross_asset_corr_state table: watermark tracking for incremental pair correlation refresh"
  - "cmc_corr_latest materialized view: DISTINCT ON latest correlation per pair/window for dashboards"
affects:
  - "41-02 and later plans that write to or read from these 5 objects"
  - "Streamlit dashboard (Phase 39) if extended to show correlation heatmaps"

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "window reserved word must be double-quoted in raw PostgreSQL SQL (op.execute); SQLAlchemy op.create_table handles quoting automatically"
    - "Materialized views created via op.execute() with raw SQL since Alembic has no native op"
    - "Unique index on materialized view enables REFRESH MATERIALIZED VIEW CONCURRENTLY"

key-files:
  created:
    - "alembic/versions/8d5bc7ee1732_asset_stats_and_correlation_tables.py"
  modified: []

key-decisions:
  - "window column kept as reserved word (not renamed) to match plan spec; handled via double-quoting in raw SQL"
  - "32 stat columns generated programmatically via _WINDOWS x _STAT_BASES lists to avoid typos in repetitive DDL"
  - "downgrade drops materialized view first (it depends on cmc_cross_asset_corr) then state tables then data tables"

patterns-established:
  - "Pattern: raw SQL op.execute() requires manual quoting of PostgreSQL reserved words (window, user, etc.)"
  - "Pattern: materialized view creation via op.execute() with companion CREATE UNIQUE INDEX for CONCURRENTLY support"

# Metrics
duration: 4min
completed: "2026-02-24"
---

# Phase 41 Plan 01: Asset Stats and Correlation Tables Summary

**Alembic migration 8d5bc7ee1732 creates 5 Phase 41 database objects: cmc_asset_stats (32 rolling stat cols, 4 windows), cmc_cross_asset_corr (CHECK id_a < id_b), 2 watermark state tables, and cmc_corr_latest materialized view**

## Performance

- **Duration:** 4 min
- **Started:** 2026-02-24T11:31:58Z
- **Completed:** 2026-02-24T11:35:54Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments

- Created Alembic migration `8d5bc7ee1732` chained from `6f82e9117c58` (feature_experiment_tables)
- All 5 database objects verified present: 4 tables + 1 materialized view with unique index
- CHECK constraint `chk_corr_pair_order` confirmed enforced: INSERT with id_a=5 > id_b=1 correctly rejected
- Downgrade cleanly drops all 5 objects; re-upgrade re-creates them all

## Task Commits

Each task was committed atomically:

1. **Task 1: Generate Alembic revision and implement migration** - `c2e6a9fe` (feat)

## Files Created/Modified

- `alembic/versions/8d5bc7ee1732_asset_stats_and_correlation_tables.py` - Full migration: upgrade() creates 5 objects, downgrade() drops in reverse order

## Decisions Made

- **window as reserved word**: The `window` column name is a PostgreSQL reserved word. SQLAlchemy's `op.create_table` handles quoting automatically, but raw `op.execute()` SQL must use `"window"` with double quotes. Kept the column name as specified in the plan rather than renaming to avoid a schema deviation.
- **Programmatic column generation**: 32 window stat columns (8 stats x 4 windows) are generated via `_window_stat_columns()` helper using `_WINDOWS=(30,60,90,252)` and `_STAT_BASES` tuples. Avoids copy-paste errors in repetitive DDL.
- **Materialized view via op.execute()**: Alembic has no native `op.create_materialized_view()`; using `op.execute()` with raw SQL is the established project pattern for DDL Alembic cannot natively handle.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Quoted PostgreSQL reserved word `window` in materialized view SQL**

- **Found during:** Task 1 (first upgrade attempt)
- **Issue:** `CREATE MATERIALIZED VIEW ... SELECT DISTINCT ON (id_a, id_b, tf, window)` raised `SyntaxError: syntax error at or near "window"` because `window` is a PostgreSQL reserved word in this context
- **Fix:** Changed all occurrences of bare `window` in the raw `op.execute()` SQL strings to `"window"` (double-quoted); SQLAlchemy `op.create_table` and `op.create_index` handle quoting automatically so no changes needed there
- **Files modified:** `alembic/versions/8d5bc7ee1732_asset_stats_and_correlation_tables.py`
- **Verification:** `alembic upgrade head` succeeded; `alembic current` returned `8d5bc7ee1732 (head)`
- **Committed in:** `c2e6a9fe` (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - Bug)
**Impact on plan:** Minimal — pure syntax fix for PostgreSQL reserved word, no schema or behavior change.

## Issues Encountered

- First upgrade attempt failed with `psycopg2.errors.SyntaxError: syntax error at or near "window"` because `window` is a PostgreSQL reserved word. Fixed by double-quoting `window` in raw SQL within `op.execute()` calls. SQLAlchemy's DDL layer handles quoting automatically for `op.create_table` and `op.create_index`.

## User Setup Required

None - no external service configuration required. Migration applies automatically via `alembic upgrade head`.

## Next Phase Readiness

- All 5 Phase 41 database objects are live at Alembic head `8d5bc7ee1732`
- Plans 41-02 through 41-N can proceed immediately; tables accept inserts
- `cmc_corr_latest` materialized view requires `REFRESH MATERIALIZED VIEW cmc_corr_latest` after data is written (Plan 41 compute plans should include this call)
- No blockers

---
*Phase: 41-asset-descriptive-stats-correlation*
*Completed: 2026-02-24*
