---
phase: 45-paper-trade-executor
plan: "01"
subsystem: executor-schema
tags: [alembic, postgresql, ddl, migrations, executor, dim-tables, signal-seeding, positions-pk]

dependency_graph:
  requires: [44-order-fill-store]
  provides: [executor-config-schema, executor-run-log-schema, extended-positions-pk, executor-processed-at-columns, v1-signal-seeds]
  affects: [45-02-fill-simulator, 45-03-signal-reader, 45-04-executor-loop, 45-05-bootstrap]

tech_stack:
  added: []
  patterns:
    - alembic-hand-written-migration
    - drop-create-view-for-column-addition
    - serial-pk-config-table
    - uuid-pk-run-log
    - conditional-seed-insert-where-not-exists
    - json-array-string-for-config-ids

key_files:
  created:
    - alembic/versions/225bf8646f03_paper_trade_executor.py
    - sql/executor/088_dim_executor_config.sql
    - sql/executor/089_cmc_executor_run_log.sql
    - configs/executor_config_seed.yaml
  modified:
    - cmc_positions (strategy_id column added, PK extended)
    - v_cmc_positions_agg (strategy_id added)
    - cmc_signals_ema_crossover (executor_processed_at added)
    - cmc_signals_rsi_mean_revert (executor_processed_at added)
    - cmc_signals_atr_breakout (executor_processed_at added)
    - dim_signals (ema_17_77_long row seeded)

decisions:
  - "DROP + CREATE for view (not CREATE OR REPLACE) when adding columns -- PostgreSQL rejects column reorder in place"
  - "SERIAL PK on dim_executor_config (not UUID) -- config rows are few, human-readable IDs are useful"
  - "config_ids as TEXT JSON array string in run_log (not ARRAY) -- avoids sa.ARRAY PostgreSQL-specific dialect"
  - "ema_21_50_long pre-existing in dim_signals (signal_id=2) -- INSERT WHERE NOT EXISTS is idempotent"
  - "ema_17_77_long added as signal_id=7 -- V1 top-1 robust strategy from Phase 42 bakeoff"
  - "DEFAULT 0 on strategy_id so existing positions rows get strategy_id=0 without data migration"

metrics:
  duration: "5 min"
  completed: "2026-02-25"
  tasks_total: 2
  tasks_completed: 2
---

# Phase 45 Plan 01: Paper Trade Executor Schema Summary

**One-liner:** Alembic migration (225bf8646f03) creating dim_executor_config + cmc_executor_run_log, extending cmc_positions PK to (asset_id, exchange, strategy_id), adding executor_processed_at to all 3 signal tables, and seeding ema_17_77_long V1 strategy -- with reference DDL and YAML seed.

## What Was Built

Single Alembic migration (`225bf8646f03`) with full round-trip verified (upgrade/downgrade/upgrade). All Phase 45 schema prerequisites are in place before any executor code runs.

### New Tables

| Table | PK | Purpose |
|-------|----|---------|
| dim_executor_config | config_id SERIAL | Strategy execution parameters (22 columns, 9 CHECK constraints) |
| cmc_executor_run_log | run_id UUID | Audit log per executor invocation (12 columns) |

### Schema Modifications

| Object | Change |
|--------|--------|
| cmc_positions | Added strategy_id INTEGER NOT NULL DEFAULT 0; PK extended to (asset_id, exchange, strategy_id) |
| v_cmc_positions_agg | Rebuilt with strategy_id=0 column (required DROP + CREATE) |
| cmc_signals_ema_crossover | Added executor_processed_at TIMESTAMPTZ NULL |
| cmc_signals_rsi_mean_revert | Added executor_processed_at TIMESTAMPTZ NULL |
| cmc_signals_atr_breakout | Added executor_processed_at TIMESTAMPTZ NULL |
| dim_signals | Seeded ema_17_77_long (signal_id=7) with INSERT WHERE NOT EXISTS |

### Reference DDL

- `sql/executor/088_dim_executor_config.sql` -- full CREATE TABLE with COMMENTs
- `sql/executor/089_cmc_executor_run_log.sql` -- full CREATE TABLE with COMMENTs

### YAML Seed

`configs/executor_config_seed.yaml` contains 2 V1 strategy configurations:
- `ema_trend_17_77_paper_v1`: position_fraction=0.10, lognormal slippage, paper exchange, sandbox
- `ema_trend_21_50_paper_v1`: position_fraction=0.10, lognormal slippage, paper exchange, sandbox

Both deploy at 10% position fraction per Phase 42-04 decision (reduced from 50% backtest sizing due to MaxDD gate failure).

## Tasks Completed

| Task | Name | Commit | Key Files |
|------|------|--------|-----------|
| 1 | Create Alembic migration | 0cc87325 | alembic/versions/225bf8646f03_paper_trade_executor.py |
| 2 | Create reference DDL and YAML seed | 1f96f827 | sql/executor/088-089_*.sql, configs/executor_config_seed.yaml |

## Verification Results

- `alembic upgrade head` completed without error
- All schema changes verified via information_schema queries:
  - dim_executor_config: 22 columns present
  - cmc_executor_run_log: 12 columns present
  - cmc_positions PK: (asset_id, exchange, strategy_id) confirmed
  - executor_processed_at on all 3 signal tables: confirmed
  - v_cmc_positions_agg columns: includes strategy_id
  - dim_signals: ema_17_77_long seeded as signal_id=7
- `alembic downgrade -1` reversed all changes cleanly:
  - executor tables removed
  - cmc_positions PK restored to (asset_id, exchange)
  - executor_processed_at columns removed
  - v_cmc_positions_agg restored without strategy_id
  - ema_17_77_long removed from dim_signals
- `alembic upgrade head` re-applied successfully (full round-trip confirmed)
- YAML loads verified: 2 configs with correct signal_names and position_fraction=0.10

## Decisions Made

1. **DROP + CREATE for view (not CREATE OR REPLACE)**: PostgreSQL raises `InvalidTableDefinition: cannot change name of view column` when adding a new column before existing ones. Requires explicit DROP VIEW + CREATE VIEW. Applied in both upgrade and downgrade paths.

2. **SERIAL PK for dim_executor_config**: Config rows are few (tens, not millions). Human-readable integer IDs (1, 2, 3) are useful in run_log.config_ids and for CLI operations. UUID would be overkill.

3. **config_ids as TEXT JSON array**: SQLAlchemy `sa.ARRAY` is PostgreSQL-specific dialect. TEXT column storing `"[1,2]"` is portable and avoids array unnesting in application code.

4. **DEFAULT 0 on strategy_id**: Existing positions rows (if any) get strategy_id=0 without a data migration step. strategy_id=0 conventionally means "default/unassigned strategy."

5. **INSERT WHERE NOT EXISTS for signal seeding**: Idempotent -- running the migration on a DB that already has ema_17_77_long (e.g., from manual seeding) will skip the INSERT safely.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] CREATE OR REPLACE VIEW fails when adding column before existing columns**

- **Found during:** Task 1 upgrade execution
- **Issue:** PostgreSQL raises `InvalidTableDefinition: cannot change name of view column "quantity" to "strategy_id"` when CREATE OR REPLACE VIEW adds a column at position 3 (before quantity). PostgreSQL's CREATE OR REPLACE VIEW requires that new columns be added at the end of the column list only.
- **Fix:** Changed both upgrade and downgrade paths to use `DROP VIEW IF EXISTS` + `CREATE VIEW` (not `CREATE OR REPLACE`). The drop is safe because no other objects depend on this view.
- **Files modified:** alembic/versions/225bf8646f03_paper_trade_executor.py
- **Commit:** 0cc87325 (fix applied inline before final commit)

## Next Phase Readiness

Plan 45-03 (SignalReader + PositionSizer) can now:
- Read from cmc_signals_* tables with executor_processed_at watermark
- Write executor_processed_at on processed signals
- Read dim_executor_config for strategy parameters
- Write cmc_executor_run_log for audit

Plan 45-05 (Bootstrap) can now:
- INSERT into dim_executor_config from executor_config_seed.yaml
- Verify signal_names (ema_17_77_long, ema_21_50_long) exist in dim_signals

All schema prerequisites are in place.

---
*Phase: 45-paper-trade-executor*
*Completed: 2026-02-25*
