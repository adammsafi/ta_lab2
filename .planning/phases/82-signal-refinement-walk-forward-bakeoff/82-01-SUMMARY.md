---
phase: 82-signal-refinement-walk-forward-bakeoff
plan: "01"
subsystem: backtests
tags: [ama, cost-model, feature-selection, alembic, walk-forward, hyperliquid, kraken]

# Dependency graph
requires:
  - phase: 80-feature-selection-and-signal-refinement
    provides: "configs/feature_selection.yaml with 20 active features (17 AMA + 3 bar-level)"
  - phase: 42-backtest-infrastructure
    provides: "BakeoffOrchestrator, costs.py CostModel, bakeoff_orchestrator.py skeleton"
provides:
  - "load_strategy_data_with_ama(): joins AMA features from ama_multi_tf_u onto base OHLCV DataFrame"
  - "parse_active_features(): reads feature_selection.yaml into structured list with source classification"
  - "HYPERLIQUID_COST_MATRIX: 6 scenarios (maker/taker x 3 slippage levels)"
  - "COST_MATRIX_REGISTRY: maps 'kraken' and 'hyperliquid' to their cost matrices"
  - "get_cost_matrix_for_exchange(): registry lookup helper"
  - "experiment_name column in strategy_bakeoff_results via Alembic migration 440fdfb3e8e1"
affects:
  - 82-02-signal-generators
  - 82-03-walk-forward-engine
  - 82-04-composite-scoring
  - 82-05-reporting

# Tech tracking
tech-stack:
  added: [yaml (PyYAML, already in deps)]
  patterns:
    - "COST_MATRIX_REGISTRY pattern: exchange name -> List[CostModel] for extensible multi-venue bake-offs"
    - "AMA feature naming convention: {INDICATOR}_{PARAMS_HASH}_ama parsed by rfind('_')"
    - "AMA data loading: separate SQL per feature to avoid column name collisions in SQL"
    - "Re-export pattern: KRAKEN_COST_MATRIX moved to costs.py, re-exported from orchestrator for backward compat"

key-files:
  created:
    - alembic/versions/440fdfb3e8e1_add_experiment_name_to_strategy_bakeoff_.py
  modified:
    - src/ta_lab2/backtests/costs.py
    - src/ta_lab2/backtests/bakeoff_orchestrator.py

key-decisions:
  - "KRAKEN_COST_MATRIX moved to costs.py (proper home for cost constants); re-exported from orchestrator for zero breaking changes"
  - "Hyperliquid slippage 3/5/10 bps (vs Kraken 5/10/20): tighter CLOB spreads justify lower range"
  - "Separate SQL query per AMA feature (not massive JOIN): avoids column name collisions and is easier to debug"
  - "experiment_name VARCHAR(128) nullable default NULL: backward-compatible; NULL means legacy/untagged run"

patterns-established:
  - "AMA feature naming: {INDICATOR}_{8-char-hash}_ama -> rfind('_') splits indicator from hash"
  - "Multi-exchange cost registry: COST_MATRIX_REGISTRY['exchange'] -> List[CostModel]"

# Metrics
duration: 8min
completed: 2026-03-22
---

# Phase 82 Plan 01: Bakeoff Data Infrastructure Summary

**AMA data loader joins 17 ama_multi_tf_u features onto OHLCV DataFrame; Hyperliquid 6-scenario cost matrix and COST_MATRIX_REGISTRY added to costs.py; experiment_name lineage column migrated into strategy_bakeoff_results**

## Performance

- **Duration:** 8 min
- **Started:** 2026-03-22T19:50:48Z
- **Completed:** 2026-03-22T19:58:30Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- Extended bake-off data infrastructure to support AMA-derived features: `load_strategy_data_with_ama()` joins 17 AMA features from `ama_multi_tf_u` using separate SQL queries per feature (avoids column collision)
- Added Hyperliquid cost matrix (6 scenarios: maker 1.5bps + taker 4.5bps x slippage 3/5/10 bps, avg BTC funding 2.91 bps/day from Coinalyze Q3-2025) and `COST_MATRIX_REGISTRY` for extensible multi-exchange bake-offs
- Alembic migration 440fdfb3e8e1 adds `experiment_name VARCHAR(128)` to `strategy_bakeoff_results` for Phase 82 lineage tracking

## Task Commits

Each task was committed atomically:

1. **Task 1: Extended AMA data loader and Hyperliquid cost matrix** - `d5f286d6` (feat)
2. **Task 2: Alembic migration for experiment_name column** - `3f8642dc` (feat)

**Plan metadata:** committed with SUMMARY.md below

## Files Created/Modified
- `src/ta_lab2/backtests/costs.py` - Added KRAKEN_COST_MATRIX (moved from orchestrator), HYPERLIQUID_COST_MATRIX (6 scenarios), COST_MATRIX_REGISTRY
- `src/ta_lab2/backtests/bakeoff_orchestrator.py` - Added parse_active_features(), load_strategy_data_with_ama(), get_cost_matrix_for_exchange(), experiment_name param in _persist_results(), exchange field in BakeoffConfig
- `alembic/versions/440fdfb3e8e1_add_experiment_name_to_strategy_bakeoff_.py` - Manual migration: ADD COLUMN experiment_name VARCHAR(128) NULL

## Decisions Made
- **KRAKEN_COST_MATRIX moved to costs.py**: Cost constants belong in the cost module, not the orchestrator. Re-exported from orchestrator for zero breaking changes.
- **Hyperliquid slippage range 3/5/10 bps** (vs Kraken 5/10/20): HL CLOB has tighter spreads, lower slippage range is realistic.
- **Separate SQL per AMA feature**: Avoids SQL column name collisions; simpler query pattern; each feature independently debuggable with clear warning on empty result.
- **experiment_name NULL default**: Backward-compatible; existing rows get NULL; Phase 82 runs will set meaningful names for lineage tracking.

## Deviations from Plan

None - plan executed exactly as written. The plan specified moving KRAKEN_COST_MATRIX to costs.py and this was done cleanly.

## Issues Encountered
- Autogenerate alembic revision failed (env.py has no MetaData configured) - expected for this project; created manual migration as the plan anticipated.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- `load_strategy_data_with_ama()` + `parse_active_features()` ready for Phase 82 Plans 02-06 to use
- `COST_MATRIX_REGISTRY` ready for `--exchange hyperliquid` CLI flag in run_bakeoff.py
- `experiment_name` column in DB, `_persist_results(experiment_name=...)` wired up
- No blockers for Plans 02-06

---
*Phase: 82-signal-refinement-walk-forward-bakeoff*
*Completed: 2026-03-22*
