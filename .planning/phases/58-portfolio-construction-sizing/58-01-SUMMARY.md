---
phase: 58-portfolio-construction-sizing
plan: 01
subsystem: portfolio
tags: [portfolio, alembic, postgres, pypfopt, yaml-config, optimization, stop-laddering]

# Dependency graph
requires:
  - phase: 57-advanced-labeling-cv
    provides: Alembic migration chain head (e5f6a1b2c3d4) that this plan extends
provides:
  - cmc_portfolio_allocations PostgreSQL table (UUID PK, optimizer weights, bet-sized final weights, JSONB config snapshot)
  - Alembic migration f6a7b8c9d0e1 creating cmc_portfolio_allocations + 2 indexes
  - configs/portfolio.yaml with 9 sections: optimizer, regime_routing, rebalancing, bet_sizing, topk_selection, black_litterman, risk_integration, cash_management, stop_laddering
  - src/ta_lab2/portfolio/__init__.py with load_portfolio_config() helper
  - PyPortfolioOpt>=1.5.6 as [portfolio] optional dependency in pyproject.toml
affects:
  - 58-02 (optimizer wrappers read configs/portfolio.yaml via load_portfolio_config())
  - 58-03 (bet_sizing, topk_selector read from same config)
  - 58-04 (rebalancer reads rebalancing section)
  - 58-05 (stop_ladder reads stop_laddering section)
  - All Phase 58 plans write to cmc_portfolio_allocations

# Tech tracking
tech-stack:
  added:
    - "PyPortfolioOpt>=1.5.6 (installed: 1.6.0) with transitive deps: cvxpy, clarabel, osqp, scs, highspy, scikit-base"
  patterns:
    - "Portfolio config loading: load_portfolio_config() opens configs/portfolio.yaml via pathlib.Path"
    - "Alembic migration pattern: down_revision points to actual alembic heads output (e5f6a1b2c3d4)"
    - "Windows line ending: pre-commit mixed-line-ending hook fixes CRLF->LF; requires re-stage after hook run"

key-files:
  created:
    - alembic/versions/f6a7b8c9d0e1_portfolio_tables.py
    - configs/portfolio.yaml
    - src/ta_lab2/portfolio/__init__.py
  modified:
    - pyproject.toml

key-decisions:
  - "down_revision = e5f6a1b2c3d4 (Phase 57-01 migration: triple_barrier_meta_label_tables) — verified via alembic heads before authoring migration"
  - "UUID PK with gen_random_uuid() server default: consistent with cmc_triple_barrier_labels and cmc_meta_label_results pattern"
  - "UNIQUE constraint on (ts, optimizer, asset_id): enables upsert semantics for future ON CONFLICT DO UPDATE"
  - "Partial index idx_portfolio_alloc_active WHERE is_active: efficient lookup without full table scan"
  - "config_snapshot JSONB column: full config at run-time stored per allocation for reproducibility"
  - "stop_laddering.defaults: sl_sizes and tp_sizes both [0.33, 0.33, 0.34] so each sums to 1.0"
  - "Portfolio optional dep group: separate from 'all' group to avoid forcing cvxpy on all users"

patterns-established:
  - "load_portfolio_config() is the canonical entry point for all Phase 58 modules"
  - "ta_lab2.portfolio package follows existing src-layout convention under src/ta_lab2/"

# Metrics
duration: 4min
completed: 2026-02-28
---

# Phase 58 Plan 01: Portfolio Construction Foundation Summary

**Alembic migration creating cmc_portfolio_allocations (UUID PK, optimizer weights, JSONB config snapshot) + 9-section configs/portfolio.yaml with stop-laddering tiers + PyPortfolioOpt installed as optional dependency group**

## Performance

- **Duration:** ~4 min
- **Started:** 2026-02-28T07:45:48Z
- **Completed:** 2026-02-28T07:49:35Z
- **Tasks:** 2/2
- **Files modified:** 4

## Accomplishments

- Created `cmc_portfolio_allocations` PostgreSQL table via Alembic migration f6a7b8c9d0e1 (extends e5f6a1b2c3d4 chain)
- Added `configs/portfolio.yaml` with all 9 required sections including stop_laddering with sl/tp tiers
- Added `[project.optional-dependencies] portfolio = ["PyPortfolioOpt>=1.5.6"]` to pyproject.toml
- Installed PyPortfolioOpt 1.6.0 with full solver stack (cvxpy 1.8.1, clarabel, osqp, scs)
- Created `src/ta_lab2/portfolio/__init__.py` with `load_portfolio_config()` and submodule docstring listing all 7 planned modules

## Task Commits

Each task was committed atomically:

1. **Task 1: Alembic migration, portfolio.yaml config, PyPortfolioOpt dep** - `532dacd7` (feat)
2. **Task 2: Portfolio package skeleton with config loader** - `5f662950` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified

- `alembic/versions/f6a7b8c9d0e1_portfolio_tables.py` - Alembic migration creating cmc_portfolio_allocations (12 columns, UNIQUE constraint, 2 indexes)
- `configs/portfolio.yaml` - Full portfolio config: optimizer, regime_routing, rebalancing, bet_sizing, topk_selection, black_litterman, risk_integration, cash_management, stop_laddering
- `src/ta_lab2/portfolio/__init__.py` - Package init with load_portfolio_config() helper
- `pyproject.toml` - Added portfolio optional dependency group with PyPortfolioOpt>=1.5.6

## Decisions Made

1. **down_revision = e5f6a1b2c3d4**: Verified via `alembic heads` at execution time. Plan used `XXXX` as placeholder; actual head was Phase 57-01's triple barrier migration.

2. **UUID PK pattern**: Matches Phase 57 convention (`cmc_triple_barrier_labels`, `cmc_meta_label_results`). `gen_random_uuid()` server default avoids Python-side UUID generation.

3. **Partial index WHERE is_active**: Active allocations are a small fraction of all rows. A partial index makes "get current portfolio" queries fast without index overhead on historical rows.

4. **stop_laddering sizes sum to 1.0**: Each tier's sl_sizes/tp_sizes are [0.33, 0.33, 0.34] — the 0.34 in the last tier ensures full position exit. This is a constraint future code must validate.

5. **Portfolio optional dep group**: Keeping PyPortfolioOpt (+ heavy solver stack: cvxpy, clarabel, osqp, scs) out of the `all` group so existing users don't pull 6 extra packages. Install with `pip install -e ".[portfolio]"`.

## Deviations from Plan

None - plan executed exactly as written. The only operational detail was discovering `down_revision` from `alembic heads` rather than using the placeholder `XXXX`, which is the standard procedure.

## Issues Encountered

- Pre-commit `mixed-line-ending` hook converted CRLF to LF on newly created files. Required re-staging and second commit attempt (standard Windows workflow, consistent with prior phases).

## User Setup Required

None - PyPortfolioOpt is installed, migration applied, config loadable. All subsequent Phase 58 plans can import directly.

## Next Phase Readiness

- `cmc_portfolio_allocations` table exists with correct schema for Phase 58-02..05 to write allocations
- `load_portfolio_config()` is the single entry point for all portfolio config reads
- `from pypfopt import EfficientFrontier, EfficientCVaR, HRPOpt, BlackLittermanModel` all importable
- No blockers for Phase 58-02 (optimizer wrappers)

---
*Phase: 58-portfolio-construction-sizing*
*Completed: 2026-02-28*
