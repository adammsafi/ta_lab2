---
phase: 48-loss-limits-policy
plan: 01
subsystem: database, risk
tags: [alembic, postgresql, var, numpy, scipy, risk-management, migration]

# Dependency graph
requires:
  - phase: 46-risk-controls
    provides: dim_risk_limits and cmc_risk_overrides tables that this migration extends
  - phase: 47-drift-guard
    provides: current alembic head (ac4cf1223ec7) that this migration chains from
provides:
  - Alembic migration 328fdc315e1b adding pool_name to dim_risk_limits and
    reason_category/expires_at/extended_at to cmc_risk_overrides
  - VaR simulator library (var_simulator.py) with historical, parametric, CF, CVaR
  - analysis package re-export pattern for var_simulator and stop_simulator
affects:
  - 48-02: stop_simulator and CLI (48-02 already committed alongside this plan)
  - 48-03: loss limit calculation scripts that use var_simulator
  - 48-04: pool cap seeding uses pool_name column added here

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Cornish-Fisher VaR with reliability flag: cf_reliable=False when abs(excess_kurtosis) > 8"
    - "try/except re-export pattern in analysis/__init__.py for graceful missing module handling"
    - "**/__init__.py F401 ruff per-file-ignore for package re-export pattern"
    - "var_to_daily_cap sanity ceiling at 15% with WARNING logging when exceeded"

key-files:
  created:
    - alembic/versions/328fdc315e1b_loss_limits_policy.py
    - src/ta_lab2/analysis/var_simulator.py
  modified:
    - src/ta_lab2/analysis/__init__.py
    - pyproject.toml

key-decisions:
  - "down_revision = ac4cf1223ec7 (drift_guard): always detect actual head at migration time, never hardcode"
  - "Fisher/excess kurtosis (scipy default) for CF expansion: kurtosis(fisher=True) gives normal=0 baseline"
  - "CF fallback to historical_var when abs(excess_kurtosis) > 8: prevents non-monotonic CF expansion for extreme fat tails"
  - "var_to_daily_cap returns median not mean across strategies: robust to outlier strategies"
  - "var_to_daily_cap caps at 15%: prevents runaway cap values from extreme observations"
  - "try/except ImportError in __init__.py: both Wave 1 plans (48-01, 48-02) write to __init__.py safely"
  - "F401 per-file-ignore for __init__.py in pyproject.toml: standard ruff pattern for re-export modules"

patterns-established:
  - "Pure computation module pattern: var_simulator imports only numpy/scipy, no DB/pandas/vectorbt"
  - "VaRResult dataclass: immutable container for all 4 VaR metrics plus distribution stats"
  - "Graceful __init__.py re-exports with try/except: Wave 1 parallel plans write safely"

# Metrics
duration: 5min
completed: 2026-02-25
---

# Phase 48 Plan 01: Loss Limits Policy Schema + VaR Simulator Summary

**Alembic migration extending Phase 46 risk tables with pool_name and override governance columns, plus pure numpy/scipy VaR simulation library with historical, parametric, Cornish-Fisher, and CVaR methods.**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-02-25T20:25:56Z
- **Completed:** 2026-02-25T20:31:15Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- Alembic migration (328fdc315e1b) adds pool_name TEXT column to dim_risk_limits with CHECK constraint enforcing (conservative, core, opportunistic, aggregate, or NULL)
- Migration adds reason_category, expires_at, extended_at columns to cmc_risk_overrides with CHECK constraint enforcing 5 allowed reason categories
- VaR simulator library provides 4 computation methods: historical percentile, Gaussian parametric, Cornish-Fisher expansion (with fat-tail fallback), and CVaR/Expected Shortfall
- Downgrade round-trip verified (downgrade -1 then upgrade head)
- analysis/__init__.py updated with try/except re-export pattern for both var_simulator and stop_simulator

## Task Commits

Each task was committed atomically:

1. **Task 1: Alembic migration for pool_name and override governance columns** - `f458127a` (feat)
2. **Task 2: VaR simulator library module** - `2ac5708c` (feat) + `69955e6d` (chore - var_simulator.py bundled with stop_simulator by 48-02 parallel execution)

**Plan metadata:** committed with docs commit below

## Files Created/Modified

- `alembic/versions/328fdc315e1b_loss_limits_policy.py` - Migration: pool_name + override governance columns with CHECK constraints
- `src/ta_lab2/analysis/var_simulator.py` - VaR computation library: 6 functions + VaRResult dataclass
- `src/ta_lab2/analysis/__init__.py` - Re-exports for var_simulator and stop_simulator (try/except pattern)
- `pyproject.toml` - Added `**/__init__.py` to ruff F401 per-file-ignores

## Decisions Made

- **CF fallback threshold is 8.0 for excess kurtosis:** Values above 8 indicate distributions where the CF polynomial may have non-monotonic behavior; logging WARNING and falling back to historical VaR is the safe choice.
- **var_to_daily_cap uses median not mean:** Median is robust to outlier strategies that may have extreme VaR values; mean would be skewed by one bad strategy.
- **15% max daily cap ceiling:** Aligns with Phase 45 V1 deployment decision (circuit breaker at 15% portfolio DD). Any computed cap above 15% is capped and logged as WARNING.
- **try/except re-export pattern in __init__.py:** Plans 48-01 and 48-02 were executing in parallel; neither should break the other's __init__.py writes. Graceful ImportError handling ensures the module loads regardless of which plan ran first.
- **F401 per-file-ignore added to pyproject.toml:** Re-export pattern in `__init__.py` files triggers ruff F401 without `# noqa` inline comments. Adding the per-file-ignore config is the correct project-level solution.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Added F401 per-file-ignore to pyproject.toml ruff config**

- **Found during:** Task 2 (VaR simulator library module)
- **Issue:** Pre-commit ruff hook flagged F401 (imported but unused) on all re-export symbols in `__init__.py`. The plan's try/except re-export pattern is standard Python but triggers ruff without config suppression.
- **Fix:** Added `"**/__init__.py" = ["F401"]` to `[tool.ruff.lint.per-file-ignores]` in pyproject.toml
- **Files modified:** pyproject.toml
- **Verification:** `ruff check src/ta_lab2/analysis/__init__.py` passes with "All checks passed!"
- **Committed in:** `2ac5708c` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (blocking: ruff config)
**Impact on plan:** Necessary to allow re-export pattern in __init__ files. Applies project-wide, consistent with existing `"tests/*" = ["F841"]` pattern. No scope creep.

## Issues Encountered

- Plan 02 was already partially executed in parallel before Plan 01 completed. The `var_simulator.py` and `__init__.py` files were committed by Plan 02 (commit `69955e6d`) before Task 2 of this plan ran. Plan 01's Task 2 work (creating var_simulator.py) was committed by Plan 02 alongside stop_simulator.py. The pyproject.toml F401 fix was committed as part of Plan 01's second commit. All functionality is present and verified.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Schema foundation complete: pool_name and override governance columns are live in the database
- VaR simulator library is ready for use by the loss limits CLI (Plan 02) and pool cap seeding (Plan 04)
- Plan 02 (stop_simulator + CLI) is already complete and committed
- Plans 03 (loss limits calculation) and 04 (pool cap seeding) can proceed

---
*Phase: 48-loss-limits-policy*
*Completed: 2026-02-25*
