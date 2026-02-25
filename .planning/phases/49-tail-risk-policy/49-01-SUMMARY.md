---
phase: 49-tail-risk-policy
plan: 01
subsystem: database
tags: [alembic, postgresql, vectorbt, position-sizing, tail-risk, vol-sizing]

# Dependency graph
requires:
  - phase: 48-loss-limits-policy
    provides: Alembic chain head (328fdc315e1b loss_limits_policy); dim_risk_state and cmc_risk_events tables established
  - phase: 46-risk-controls
    provides: dim_risk_state and cmc_risk_events DDL definitions
provides:
  - Alembic migration a9ec3c00a54a extending dim_risk_state with tail_risk_state column (CHECK normal/reduce/flatten)
  - tail_risk_triggered_at, tail_risk_trigger_reason, tail_risk_cleared_at audit columns on dim_risk_state
  - Extended cmc_risk_events event_type CHECK including tail_risk_escalated, tail_risk_cleared
  - Extended cmc_risk_events trigger_source CHECK including tail_risk
  - vol_sizer library: ATR-based and realized-vol-based position sizing primitives
  - run_vol_sized_backtest: vectorbt wrapper with integrated vol-sizing at entry bars
  - worst_n_day_returns: flat dict of worst-N-day mean returns for tail characterization
  - compute_comparison_metrics: flat metrics dict with sharpe/sortino/calmar/max_dd/win_rate/recovery_bars/worst_N
affects:
  - 49-02 (flatten trigger logic uses tail_risk_state schema)
  - 49-03 (vol-sized backtest comparison CLI uses run_vol_sized_backtest)
  - 49-04 (policy document references these building blocks)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Vol-sizing: position_pct = min(risk_budget / vol_pct, max_position_pct); units = pct * cash / price"
    - "Flat metrics dict: worst_n_day_returns merged via **unpacking into top-level result dict"
    - "Alembic CHECK extension: DROP CONSTRAINT IF EXISTS then ADD CONSTRAINT to extend enum-like checks"
    - "vbt tz strip: price.index.tz_localize(None) before from_signals to avoid 0.28.1 boundary issue"

key-files:
  created:
    - alembic/versions/a9ec3c00a54a_tail_risk_policy.py
    - src/ta_lab2/analysis/vol_sizer.py
  modified:
    - src/ta_lab2/analysis/__init__.py

key-decisions:
  - "max_position_pct=0.30 default: 30% NAV cap prevents over-leverage when vol is very low"
  - "size_array = np.where(entries, position_units, np.nan): NaN on non-entry bars so vbt holds existing position"
  - "worst_n_day_returns returns flat dict (not nested) to allow direct merge into comparison metrics via **unpacking"
  - "recovery_bars uses groupby(cumsum) pattern to find longest consecutive in-drawdown streak"
  - "compute_comparison_metrics uses hit_rate on trade returns (not bar returns) for win_rate"

patterns-established:
  - "Vol-sizer guard pattern: if vol <= 0 or None, return 0.0 immediately"
  - "Flat metrics pattern: all sub-metrics merged at top level, no nested dicts"
  - "Alembic CHECK extension: always DROP IF EXISTS before ADD to avoid duplicate constraint errors"

# Metrics
duration: 18min
completed: 2026-02-25
---

# Phase 49 Plan 01: Tail-Risk Policy Foundation Summary

**Alembic migration a9ec3c00a54a adds three-level escalation schema (normal/reduce/flatten) to dim_risk_state, plus vol_sizer library with ATR-based and realized-vol-based position sizing integrated into vectorbt backtests**

## Performance

- **Duration:** 18 min
- **Started:** 2026-02-25T16:10:00Z
- **Completed:** 2026-02-25T16:28:00Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

- Alembic migration extends dim_risk_state with tail_risk_state TEXT column (CHECK normal/reduce/flatten, default 'normal'), plus three audit columns (tail_risk_triggered_at, tail_risk_trigger_reason, tail_risk_cleared_at)
- cmc_risk_events constraints extended to accept tail_risk_escalated, tail_risk_cleared event types and tail_risk trigger source -- round-trip downgrade/upgrade verified
- vol_sizer library provides compute_vol_sized_position (ATR-dollar) and compute_realized_vol_position (rolling std), both with max_position_pct cap and zero/negative/None guards
- run_vol_sized_backtest wraps vectorbt with per-entry vol-sized position_units, tz-strip for 0.28.1 compat, and optional sl_stop
- compute_comparison_metrics returns flat dict with 12 top-level keys including worst_1/3/5/10_day_mean and recovery_bars

## Task Commits

Each task was committed atomically:

1. **Task 1: Alembic migration for tail_risk_state and extended event types** - `584b0692` (feat)
2. **Task 2: Vol-sizer library module** - `a7a1070b` (feat)

**Plan metadata:** (docs commit below)

## Files Created/Modified

- `alembic/versions/a9ec3c00a54a_tail_risk_policy.py` - Migration: tail_risk_state column + audit columns + extended CHECK constraints on cmc_risk_events
- `src/ta_lab2/analysis/vol_sizer.py` - Vol-sizing library: ATR + realized-vol position sizing, vbt backtest wrapper, worst-N-day returns, comparison metrics
- `src/ta_lab2/analysis/__init__.py` - Added try/except import block for vol_sizer exports

## Decisions Made

- max_position_pct defaults to 0.30 (30% NAV): prevents over-leverage when vol is extremely low (vol = 0.001% would yield 1000x leverage uncapped)
- size_array uses np.nan on non-entry bars: vbt interprets NaN as "hold existing position", which is correct for sizing only at entry
- worst_n_day_returns returns a flat dict so it can be merged into compute_comparison_metrics via ** unpacking without nesting
- recovery_bars uses groupby(cumsum of ~in_drawdown) pattern -- finds longest run of consecutive True in the in_drawdown boolean Series
- compute_comparison_metrics uses trade-level returns for win_rate (hit_rate), not bar-level returns, which is more meaningful for strategy evaluation

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- Pre-commit hook (ruff-format + mixed-line-ending) required staging vol_sizer.py after auto-fix on first commit attempt. Resolved by re-staging after hooks ran cleanly.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Schema foundation ready: 49-02 can implement flatten trigger logic against tail_risk_state column
- Vol-sizer library ready: 49-03 can call run_vol_sized_backtest directly for TAIL-01 comparison
- Both building blocks independently tested and committed
- No blockers for 49-02 or 49-03

---
*Phase: 49-tail-risk-policy*
*Completed: 2026-02-25*
