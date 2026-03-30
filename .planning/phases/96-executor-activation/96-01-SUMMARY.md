---
phase: 96-executor-activation
plan: 01
subsystem: database
tags: [alembic, postgresql, signals, executor, schema-migration, check-constraints]

# Dependency graph
requires:
  - phase: 87-pipeline-wiring
    provides: n8o9p0q1r2s3 migration (latest head before Phase 96)
  - phase: 45-paper-executor
    provides: dim_executor_config, executor_run_log tables with original CHECK constraints
provides:
  - Alembic migration o9p0q1r2s3t4 with all Phase 96 schema changes
  - 4 new signal tables (macd_crossover, ama_momentum, ama_mean_reversion, ama_regime_conditional)
  - 2 new reporting tables (strategy_parity, pnl_attribution)
  - Widened CHECK constraints on dim_executor_config (signal_type, sizing_mode) and executor_run_log (status)
  - dim_signals seed rows for 4 new signal types with JSONB params
  - SIGNAL_TABLE_MAP updated to 7 entries in signal_reader.py
  - 6 reference DDL files in sql/signals/ and sql/executor/
affects:
  - 96-02: signal generators (macd, ama) write to new signal tables
  - 96-03: seed_executor_config.py uses widened signal_type constraint + dim_signals rows
  - 96-04: strategy_parity and pnl_attribution populated by reporting scripts

# Tech tracking
tech-stack:
  added: []
  patterns:
    - CHECK constraint widening via DROP + ADD (not ALTER -- Postgres requires this pattern)
    - dim_signals seeding in Alembic migration (JSONB params required, no server default)
    - executor_processed_at as replay guard column in all signal tables

key-files:
  created:
    - alembic/versions/o9p0q1r2s3t4_phase96_executor_activation.py
    - sql/signals/096_signals_macd_crossover.sql
    - sql/signals/097_signals_ama_momentum.sql
    - sql/signals/098_signals_ama_mean_reversion.sql
    - sql/signals/099_signals_ama_regime_conditional.sql
    - sql/executor/096_strategy_parity.sql
    - sql/executor/097_pnl_attribution.sql
  modified:
    - src/ta_lab2/executor/signal_reader.py

key-decisions:
  - "Seed dim_signals in migration (not in seeder script) to prevent silent skips in seed_executor_config.py which resolves signal_name -> signal_id from dim_signals"
  - "Include executor_processed_at in all 4 new signal tables (replay guard requirement from plan)"
  - "Single migration file for all Phase 96 changes to ensure atomicity -- all-or-nothing upgrade/downgrade"

patterns-established:
  - "Signal table schema: id/ts/signal_id PK + direction/position_state + entry/exit tracking + executor_processed_at replay guard + feature_snapshot JSONB"
  - "Partial indexes on position_state='open' and position_state='closed' mirror signals_ema_crossover pattern"

# Metrics
duration: 7min
completed: 2026-03-30
---

# Phase 96 Plan 01: Schema Foundation Summary

**Alembic migration adding 6 tables (4 signal + 2 reporting), widening 3 CHECK constraints, and seeding 4 dim_signals rows enabling executor to pick up MACD and AMA signal types**

## Performance

- **Duration:** 7 min
- **Started:** 2026-03-30T22:13:43Z
- **Completed:** 2026-03-30T22:20:00Z
- **Tasks:** 2
- **Files modified:** 8

## Accomplishments

- Alembic migration o9p0q1r2s3t4 applied cleanly, single head maintained
- All 6 new tables queryable (signals_macd_crossover, signals_ama_momentum, signals_ama_mean_reversion, signals_ama_regime_conditional, strategy_parity, pnl_attribution)
- CHECK constraints widened: signal_type (3->7), sizing_mode (3->5, adds target_vol + bl_weight), executor_run_log status (5->6, adds halted bug fix)
- 4 dim_signals rows seeded with correct JSONB params (macd_12_26_9_long, ama_momentum_v1, ama_mean_reversion_v1, ama_regime_conditional_v1)
- SIGNAL_TABLE_MAP expanded from 3 to 7 entries; _VALID_SIGNAL_TABLES auto-derived, validates all 7
- 6 reference DDL files written matching migration columns exactly

## Task Commits

Each task was committed atomically:

1. **Task 1: Create Alembic migration for all Phase 96 schema changes** - `8c9d1911` (feat)
2. **Task 2: Update SIGNAL_TABLE_MAP and write reference DDL files** - `8f19e076` (feat)

## Files Created/Modified

- `alembic/versions/o9p0q1r2s3t4_phase96_executor_activation.py` - Migration: 6 tables, 3 constraints, 4 seed rows
- `src/ta_lab2/executor/signal_reader.py` - SIGNAL_TABLE_MAP expanded to 7 entries
- `sql/signals/096_signals_macd_crossover.sql` - Reference DDL for MACD signal table
- `sql/signals/097_signals_ama_momentum.sql` - Reference DDL for AMA momentum signal table
- `sql/signals/098_signals_ama_mean_reversion.sql` - Reference DDL for AMA mean-reversion signal table
- `sql/signals/099_signals_ama_regime_conditional.sql` - Reference DDL for AMA regime-conditional signal table
- `sql/executor/096_strategy_parity.sql` - Reference DDL for strategy parity reporting table
- `sql/executor/097_pnl_attribution.sql` - Reference DDL for PnL attribution reporting table

## Decisions Made

- **Seed dim_signals in migration, not in seeder script**: seed_executor_config.py resolves
  signal_name -> signal_id from dim_signals. If rows are missing, configs are silently skipped.
  Embedding the seed in the migration guarantees rows exist before any downstream script runs.

- **Single migration file for all Phase 96 changes**: Ensures all-or-nothing atomicity.
  If any step fails, the entire migration rolls back cleanly. Simpler than chaining migrations.

- **Include executor_processed_at in all 4 new signal tables**: Required by SignalReader's
  replay guard (read_unprocessed_signals filters on `executor_processed_at IS NULL`). Must
  exist before executor is started or all signals appear unprocessed.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- Initial `ta_lab2.db.get_engine` import failed (function lives in `ta_lab2.io`). Resolved by
  checking exports -- no code change needed, just used the correct import in verification commands.

## User Setup Required

None - no external service configuration required. Migration runs automatically via `alembic upgrade head`.

## Next Phase Readiness

- Schema foundation complete. All subsequent Phase 96 plans can proceed.
- Plan 96-02 (signal generators) can write to the 4 new signal tables immediately.
- Plan 96-03 (executor config seeding) can use widened signal_type constraint and dim_signals rows.
- Plan 96-04 (reporting scripts) can write to strategy_parity and pnl_attribution.
- No blockers.

---
*Phase: 96-executor-activation*
*Completed: 2026-03-30*
