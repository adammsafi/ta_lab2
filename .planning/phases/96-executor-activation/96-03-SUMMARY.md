---
phase: 96-executor-activation
plan: 03
subsystem: executor
tags: [paper-trading, executor, position-sizing, black-litterman, portfolio-allocation, signal-types, watermark]

# Dependency graph
requires:
  - phase: 96-01
    provides: dim_executor_config schema, dim_signals seeded with EMA entries, signal table DDL
  - phase: 96-02
    provides: signal generators for RSI, ATR, MACD, AMA types

provides:
  - 8-config executor_config_seed.yaml covering all 7 signal types in SIGNAL_TABLE_MAP
  - --seed-watermarks CLI flag preventing historical signal replay on first executor run
  - bl_weight sizing mode in PositionSizer reading from portfolio_allocations
  - paper_executor._process_asset_signal passes conn/asset_id for BL weight lookups

affects:
  - 96-04 (executor burn-in): relies on all 8 configs being seeded and watermarks set
  - portfolio/black_litterman: bl_weight closes positions when BL de-selects an asset

# Tech tracking
tech-stack:
  added: []
  patterns:
    - bl_weight sizing mode: flat return (Decimal 0) when BL de-selects; falls back to fixed_fraction when conn unavailable
    - Watermark seeding: MAX(ts) per signal table set atomically for all active configs with NULL watermark
    - SIGNAL_TABLE_MAP import in seed script: same dict as executor, ensures table resolution consistency

key-files:
  created: []
  modified:
    - configs/executor_config_seed.yaml
    - src/ta_lab2/scripts/executor/seed_executor_config.py
    - src/ta_lab2/executor/position_sizer.py
    - src/ta_lab2/executor/paper_executor.py

key-decisions:
  - "All 8 configs use sizing_mode='bl_weight' with position_fraction=0.10 as fallback"
  - "bl_weight returns Decimal('0') when BL de-selects asset (weight=0 or no row) -- executor closes position"
  - "seed_watermarks() imports SIGNAL_TABLE_MAP at call time (not module level) to avoid circular import"
  - "Added --watermarks-only flag for standalone watermark seeding without YAML re-seeding"

patterns-established:
  - "bl_weight mode: pass conn and asset_id as kwargs to compute_target_position for DB lookup"
  - "BL de-selection returns 0 (flat) -- executor will emit a sell order to close any open position"
  - "Watermark seeding is idempotent: skips configs where last_processed_signal_ts IS NOT NULL"

# Metrics
duration: 5min
completed: 2026-03-30
---

# Phase 96 Plan 03: Executor Config Expansion + BL Weight Sizing Summary

**8-config YAML covering all 7 signal types (2 EMA + RSI + ATR + MACD + 3 AMA), watermark seeding to prevent historical replay, and Black-Litterman weight integration as a new `bl_weight` sizing mode**

## Performance

- **Duration:** 5 min
- **Started:** 2026-03-30T22:24:18Z
- **Completed:** 2026-03-30T22:29:29Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- Expanded `executor_config_seed.yaml` from 2 EMA configs to 8 configs spanning all 7 signal types registered in `SIGNAL_TABLE_MAP` (ema_crossover x2, rsi_mean_revert, atr_breakout, macd_crossover, ama_momentum, ama_mean_reversion, ama_regime_conditional)
- Updated both existing EMA configs from `sizing_mode: fixed_fraction` to `sizing_mode: bl_weight` so all strategies use Black-Litterman portfolio optimization weights
- Added `--seed-watermarks` and `--watermarks-only` flags to the seed script: sets `last_processed_signal_ts = MAX(ts)` for active configs with NULL watermark, preventing all historical signals from being replayed on executor first run
- Added `bl_weight` sizing mode to `PositionSizer.compute_target_position`: reads `COALESCE(final_weight, weight)` from `portfolio_allocations WHERE optimizer='bl'` ORDER BY ts DESC; returns `Decimal('0')` (flat/close position) when BL de-selects the asset
- Wired `conn` and `asset_id` into `paper_executor._process_asset_signal`'s call to `compute_target_position` so the BL lookup has a live DB connection

## Task Commits

Each task was committed atomically:

1. **Task 1: Expand seed YAML + --seed-watermarks flag** - `bcd12461` (feat)
2. **Task 2: bl_weight sizing mode + executor wiring** - `f2990acc` (feat)

**Plan metadata:** (see final commit below)

## Files Created/Modified

- `configs/executor_config_seed.yaml` - Expanded from 2 to 8 strategy configs; all use `bl_weight` sizing; includes cadence_hours per strategy (26h EMA, 36h RSI/ATR/MACD, 48h AMA)
- `src/ta_lab2/scripts/executor/seed_executor_config.py` - Added `seed_watermarks()` function, `--seed-watermarks` and `--watermarks-only` CLI flags
- `src/ta_lab2/executor/position_sizer.py` - Added `bl_weight` branch to `compute_target_position`; returns 0 on BL de-selection; falls back to fixed_fraction when no conn
- `src/ta_lab2/executor/paper_executor.py` - `_process_asset_signal` now passes `conn=conn` and `asset_id=asset_id` to `PositionSizer.compute_target_position`

## Decisions Made

- **All configs use bl_weight:** Phase 96-03 decision follows the context guidance that "BL decides all sizing". The `position_fraction: 0.10` value is a fallback for when BL has no output for an asset (new asset, BL not yet run).
- **bl_weight returns 0 on de-selection:** When Black-Litterman excludes an asset (weight=0 or no row), the sizer returns `Decimal('0')`, causing the executor to emit a sell order closing any open position. This is the correct behavior -- BL's decision should override.
- **Fallback to fixed_fraction when no conn:** If `conn` is not provided (e.g., unit tests without mock), the mode gracefully falls back to fixed_fraction rather than crashing. Logged as a warning.
- **SIGNAL_TABLE_MAP import inside function:** Avoids potential circular import. The `seed_watermarks()` function imports from `ta_lab2.executor.signal_reader` at call time, consistent with how signal_reader is used elsewhere.
- **Added --watermarks-only flag:** Useful when configs already exist (ON CONFLICT DO NOTHING would skip all) but watermarks haven't been set -- user can run watermarks-only without re-running the full seed.

## Deviations from Plan

None - plan executed exactly as written. One additional `--watermarks-only` flag was added (complement to `--seed-watermarks`) as an obviously useful convenience with no scope cost.

## Issues Encountered

- Pre-commit ruff-format reformatted `position_sizer.py` on first commit attempt (minor formatting difference in the new bl_weight block). Re-staged and committed on second attempt.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `configs/executor_config_seed.yaml` is ready for `python -m ta_lab2.scripts.executor.seed_executor_config --seed-watermarks` to insert all 8 configs and set watermarks
- The 6 new configs (RSI, ATR, MACD, 3 AMA) will be skipped during seeding until their `signal_name` entries exist in `dim_signals` -- that is an expected dependency, documented in the YAML header
- `bl_weight` sizing is ready but requires `portfolio_allocations` to have BL output rows; without them the executor returns flat (0) for BL-mode assets -- this is correct behavior until Phase 96-04 BL integration runs
- Phase 96-04 (executor burn-in) can proceed: configs are seeded, watermarks can be set, and BL weight sizing will activate automatically once `portfolio_allocations` has `optimizer='bl'` rows

---
*Phase: 96-executor-activation*
*Completed: 2026-03-30*
