---
phase: 27-regime-integration
plan: 01
subsystem: database
tags: [postgresql, ddl, regimes, signals, sql]

# Dependency graph
requires:
  - phase: 26-validation
    provides: validated bar/EMA/feature pipeline as foundation for regime tables
provides:
  - cmc_regimes table (PK id, ts, tf) with L0-L4 labels, policy fields, version_hash
  - cmc_regime_flips table (PK id, ts, tf, layer) for regime transition tracking
  - cmc_regime_stats table (PK id, tf, regime_key) for pre-computed summaries
  - cmc_regime_comovement table (PK id, tf, ema_a, ema_b, computed_at) for EMA alignment analytics
  - regime_key TEXT column on all 3 signal tables (ema_crossover, rsi_mean_revert, atr_breakout)
  - regime_enabled BOOLEAN column on dim_signals
affects:
  - 27-02 (regime module integration - writes to cmc_regimes)
  - 27-03 (regime stats refresh - writes to cmc_regime_stats, cmc_regime_comovement)
  - 27-04 (signal generator regime awareness - reads regime_key, writes to signal.regime_key)
  - 28 (backtest pipeline - reads regime_key from signals)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Regime table DDL follows project convention: numbered file (08x_), CREATE TABLE IF NOT EXISTS, named indexes, COMMENT ON TABLE/COLUMN"
    - "ALTER TABLE with ADD COLUMN IF NOT EXISTS for idempotent schema extension"

key-files:
  created:
    - sql/regimes/080_cmc_regimes.sql
    - sql/regimes/081_cmc_regime_flips.sql
    - sql/regimes/082_cmc_regime_stats.sql
    - sql/regimes/083_alter_signal_tables.sql
    - sql/regimes/084_cmc_regime_comovement.sql
    - sql/dim/010_dim_signals_regime_col.sql
  modified: []

key-decisions:
  - "cmc_regime_comovement uses (id, tf, ema_a, ema_b, computed_at) as PK to retain history across refreshes - each refresh snapshot is preserved"
  - "regime_enabled defaults to TRUE on dim_signals so all existing signals participate in regime-aware execution without manual opt-in"
  - "regime_key is nullable on signal tables (NULL = regime not computed at signal time) to avoid breaking existing rows"

patterns-established:
  - "Regime SQL files numbered 080-084 in sql/regimes/ directory, parallel to signals/ (060-063) and features/ (040-042)"
  - "dim_signals schema extension uses sql/dim/ directory with 010_ prefix for additive columns"

# Metrics
duration: 3min
completed: 2026-02-20
---

# Phase 27 Plan 01: Regime Integration Schema Summary

**PostgreSQL regime schema: 4 new tables (cmc_regimes, flips, stats, comovement) + regime_key on all 3 signal tables + regime_enabled on dim_signals - complete DDL foundation for regime integration**

## Performance

- **Duration:** 3 min
- **Started:** 2026-02-20T19:21:49Z
- **Completed:** 2026-02-20T19:24:14Z
- **Tasks:** 2
- **Files modified:** 6

## Accomplishments

- Created 4 regime tables in PostgreSQL with correct PKs verified via information_schema
- Extended all 3 signal tables with regime_key TEXT (NULL-safe, backward compatible)
- Extended dim_signals with regime_enabled BOOLEAN DEFAULT TRUE for per-signal opt-out
- All 6 SQL files are idempotent (IF NOT EXISTS) and follow project numbering/comment conventions

## Task Commits

Each task was committed atomically:

1. **Task 1: Create regime table DDL files** - `887d1079` (feat)
2. **Task 2: Extend signal and dimension tables** - `3f27176c` (feat)

## Files Created/Modified

- `sql/regimes/080_cmc_regimes.sql` - Main regime table: PK (id, ts, tf), L0-L4 labels, policy fields (size_mult, stop_mult, orders, gross_cap, pyramids), feature_tier, version_hash, 3 indexes
- `sql/regimes/081_cmc_regime_flips.sql` - Regime flip events: PK (id, ts, tf, layer), old/new regime, duration_bars
- `sql/regimes/082_cmc_regime_stats.sql` - Pre-computed stats: PK (id, tf, regime_key), n_bars, pct_of_history, avg/std 1D returns
- `sql/regimes/083_alter_signal_tables.sql` - ADD COLUMN regime_key TEXT to ema_crossover, rsi_mean_revert, atr_breakout
- `sql/regimes/084_cmc_regime_comovement.sql` - EMA comovement: PK (id, tf, ema_a, ema_b, computed_at), correlation, sign_agree_rate, best_lead_lag
- `sql/dim/010_dim_signals_regime_col.sql` - ADD COLUMN regime_enabled BOOLEAN DEFAULT TRUE to dim_signals

## Decisions Made

- **cmc_regime_comovement PK includes computed_at**: Retains historical snapshots across refreshes rather than upsert-overwrite. Future analytics can see how comovement evolved over time.
- **regime_key nullable on signal tables**: Existing signals have NULL regime_key. This avoids a backfill requirement and makes the column backward-compatible. Signal generators will populate it going forward.
- **regime_enabled defaults TRUE**: All existing signals automatically participate in regime-aware execution. Opt-out by setting FALSE is explicit and documented.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

Pre-commit hook corrected mixed line endings (CRLF/LF) on first commit attempt for each task. Required re-staging after hook auto-fixed files. Second commit succeeded cleanly. This is a known Windows/git interaction on this machine.

## User Setup Required

None - no external service configuration required. All DDL applied directly to TARGET_DB_URL.

## Next Phase Readiness

- All 4 regime tables exist in PostgreSQL and are ready for writes from the regime module
- Signal tables ready to receive regime_key from signal generators
- dim_signals ready for regime_enabled flag management
- Plan 27-02 can immediately begin wiring the Python regime module to write to cmc_regimes

---
*Phase: 27-regime-integration*
*Completed: 2026-02-20*
