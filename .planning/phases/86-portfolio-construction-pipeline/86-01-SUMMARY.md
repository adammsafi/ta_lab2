---
phase: 86-portfolio-construction-pipeline
plan: "01"
subsystem: database, portfolio
tags: [alembic, stop-calibration, mae-mfe, stop-ladder, portfolio, backtest]

# Dependency graph
requires:
  - phase: 82-signal-refinement-walk-forward-bakeoff
    provides: backtest_trades with mae/mfe columns (migration b2c3d4e5f6a1)
  - phase: 58-portfolio-construction
    provides: StopLadder, portfolio.yaml, stop_laddering config section

provides:
  - stop_calibrations table (PK id+strategy, sl/tp percentile columns, n_trades, calibrated_at)
  - dim_executor_config.target_annual_vol column with positive CHECK constraint
  - analysis/stop_calibration.py (calibrate_stops_from_mae_mfe, persist_calibrations, MIN_TRADES_FOR_CALIBRATION=30)
  - scripts/portfolio/calibrate_stops.py CLI (--ids, --dry-run, --db-url, --verbose)
  - StopLadder.from_db_calibrations() classmethod (seeds _per_asset from stop_calibrations)

affects:
  - 86-02 (uses target_annual_vol in GARCH sizing mode)
  - 86-03 (calibrate_stops pipeline integration, StopLadder DB seeding)
  - scripts/run_daily_refresh.py (calibrate_stops.py added before portfolio refresh)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "stop calibration: MIN_TRADES_FOR_CALIBRATION=30 gate prevents noisy percentile computation"
    - "StopLadder DB-seeding pattern: from_db_calibrations() classmethod queries stop_calibrations, injects {id}:{strategy} combined keys into _per_asset dict"
    - "Alembic revision ID collision: plan specified l6m7n8o9p0q1 but that was already used by 89/CTF phase -- using m7n8o9p0q1r2 instead"

key-files:
  created:
    - alembic/versions/m7n8o9p0q1r2_phase86_portfolio_pipeline.py
    - src/ta_lab2/analysis/stop_calibration.py
    - src/ta_lab2/scripts/portfolio/calibrate_stops.py
  modified:
    - src/ta_lab2/portfolio/stop_ladder.py

key-decisions:
  - "Revision ID m7n8o9p0q1r2 used (not l6m7n8o9p0q1 as planned): l6m7n8o9p0q1 was already taken by dim_ctf_feature_selection migration from Phase 89"
  - "down_revision=l6m7n8o9p0q1 (dim_ctf_feature_selection): this is the actual current head"
  - "strategy column in stop_calibrations uses dim_signals.strategy_type via JOIN, falls back to signal_id::TEXT when dim_signals unavailable"
  - "equal-weight sl_sizes=[0.33,0.33,0.34] and tp_sizes=[0.50,0.50]: standard split for 3-tier SL and 2-tier TP"
  - "from_db_calibrations() uses TYPE_CHECKING guard for Engine import: avoids runtime sqlalchemy import at module level; text() imported inside method body"
  - "partial row guard: rows with any NULL sl or tp values are skipped with debug log (not silently using defaults)"

patterns-established:
  - "Calibration gate pattern: return None if len(rows) < MIN_TRADES_FOR_CALIBRATION; callers treat None as 'use global defaults'"
  - "DB-seeded override pattern: classmethod queries DB, validates tiers, merges into existing _per_asset dict without touching __init__ or existing methods"

# Metrics
duration: 5min
completed: 2026-03-24
---

# Phase 86 Plan 01: DB Schema Extensions and MAE/MFE Stop Calibration Pipeline Summary

**stop_calibrations table + dim_executor_config.target_annual_vol migration, MAE/MFE percentile calibration module, calibrate_stops CLI, and StopLadder.from_db_calibrations() for data-driven per-asset-strategy stop levels**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-03-24T02:25:23Z
- **Completed:** 2026-03-24T02:30:24Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- Alembic migration m7n8o9p0q1r2 creates stop_calibrations table (PK: id, strategy) and adds target_annual_vol to dim_executor_config with positive CHECK constraint
- analysis/stop_calibration.py provides calibrate_stops_from_mae_mfe() with MIN_TRADES_FOR_CALIBRATION=30 gate and persist_calibrations() for ON CONFLICT upsert
- scripts/portfolio/calibrate_stops.py CLI reads (asset_id, signal_id, strategy) from backtest_runs, calls calibration per combination, writes/skips to stop_calibrations
- StopLadder.from_db_calibrations() classmethod loads all stop_calibrations rows and seeds _per_asset["{id}:{strategy}"] overrides at runtime, overriding static YAML for calibrated assets

## Task Commits

Each task was committed atomically:

1. **Task 1: Alembic migration + stop calibration analysis module** - `a756ed33` (feat)
2. **Task 2: calibrate_stops CLI script + StopLadder.from_db_calibrations()** - `2358cfde` (feat)

## Files Created/Modified

- `alembic/versions/m7n8o9p0q1r2_phase86_portfolio_pipeline.py` - Alembic migration: stop_calibrations table + target_annual_vol column on dim_executor_config with CHECK constraint
- `src/ta_lab2/analysis/stop_calibration.py` - MAE/MFE percentile stop level computation; exports calibrate_stops_from_mae_mfe, persist_calibrations, MIN_TRADES_FOR_CALIBRATION
- `src/ta_lab2/scripts/portfolio/calibrate_stops.py` - CLI script: reads backtest_runs combinations, calls calibration, writes to stop_calibrations; supports --ids, --dry-run, --verbose
- `src/ta_lab2/portfolio/stop_ladder.py` - Extended with from_db_calibrations() classmethod that queries stop_calibrations and seeds _per_asset overrides

## Decisions Made

- **Revision ID collision:** Plan specified `l6m7n8o9p0q1` as migration revision ID but that was already used by the CTF phase (dim_ctf_feature_selection, Phase 89). Used `m7n8o9p0q1r2` instead. down_revision correctly points at `l6m7n8o9p0q1` (current head).
- **strategy column resolution:** calibrate_stops.py joins dim_signals.strategy_type to get human-readable strategy names (e.g., "rsi", "ema_crossover"); falls back to signal_id::TEXT when dim_signals join fails. Keeps stop_calibrations rows human-auditable.
- **equal-weight sizes:** sl_sizes=[0.33,0.33,0.34] and tp_sizes=[0.50,0.50] for 3-tier SL and 2-tier TP respectively. Standard equal-weight split -- overrides can be applied at higher specificity layers.
- **TYPE_CHECKING guard for Engine:** from_db_calibrations uses `if TYPE_CHECKING: from sqlalchemy.engine import Engine` to avoid runtime import cycle risk; `text()` imported inline inside the method body following existing patterns in similar classmethods.
- **Graceful DB failure:** from_db_calibrations() catches query exceptions, logs a warning, and returns an unmodified ladder (global YAML defaults apply). Never raises -- executor startup must not fail because stop_calibrations is empty.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Used m7n8o9p0q1r2 instead of l6m7n8o9p0q1 for migration revision**

- **Found during:** Task 1 (Alembic migration)
- **Issue:** Plan specified revision ID `l6m7n8o9p0q1` but `alembic/versions/l6m7n8o9p0q1_dim_ctf_feature_selection.py` already exists (Phase 89 CTF work). Using the same revision ID would make alembic fail with a duplicate revision error.
- **Fix:** Used `m7n8o9p0q1r2` as revision ID, continuing the sequential naming convention. File named `m7n8o9p0q1r2_phase86_portfolio_pipeline.py`. down_revision remains `l6m7n8o9p0q1` (the actual current head).
- **Files modified:** alembic/versions/m7n8o9p0q1r2_phase86_portfolio_pipeline.py
- **Verification:** `python -c "import m7n8o9p0q1r2_phase86_portfolio_pipeline"` succeeds; revision/down_revision verified correct.
- **Committed in:** a756ed33 (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** Required rename of migration revision ID; no logic changes. All must_haves and success criteria remain satisfied.

## Issues Encountered

- ruff-format reformatted both calibrate_stops.py and stop_ladder.py on first commit attempt (standard pattern for multi-arg function calls). Re-staged and committed clean on second attempt.

## User Setup Required

None - no external service configuration required. DB migration must be run manually when ready:

```bash
alembic upgrade head
```

## Next Phase Readiness

- Plan 02 (GARCH target-vol sizing) can use `target_annual_vol` column from this migration
- Plan 03 (pipeline integration) can wire `calibrate_stops.py` into `run_daily_refresh.py` between signals and portfolio stages
- `StopLadder.from_db_calibrations(engine)` is ready for use in `refresh_portfolio_allocations.py` to replace YAML-only stop config
- stop_calibrations table will be empty until `calibrate_stops.py --ids all` is first run against populated backtest_trades

---
*Phase: 86-portfolio-construction-pipeline*
*Completed: 2026-03-24*
