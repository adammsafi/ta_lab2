---
phase: 105-parameter-optimization
plan: 01
subsystem: analysis
tags: [optuna, ic, spearman, parameter-optimization, alembic, trial_registry, gridsmapler, tpesampler]

# Dependency graph
requires:
  - phase: 102-indicator-research-framework
    provides: trial_registry table (Phase 102 plan 01)
  - phase: 104-crypto-native-indicators
    provides: current alembic HEAD revision x7y8z9a0b1c2

provides:
  - Alembic migration y8z9a0b1c2d3 adding 7 sweep columns to trial_registry
  - partial index ix_trial_registry_sweep_id (WHERE sweep_id IS NOT NULL)
  - param_optimizer.py with run_sweep(), _make_ic_objective(), _suggest_params(), _log_sweep_to_registry()
  - IC-based Optuna parameter optimization infrastructure (GridSampler + TPESampler)

affects:
  - 105-02 (sweep orchestration scripts that call run_sweep)
  - 105-03 (plateau detection reads sweep_id, plateau_score, rolling_stability_passes columns)
  - Any downstream indicator research that queries trial_registry.sweep_id

# Tech tracking
tech-stack:
  added: [optuna (GridSampler, TPESampler), scipy.stats.spearmanr]
  patterns:
    - IC-based objective (Spearman correlation vs fwd_ret) instead of Sharpe-based
    - GridSampler for grid_size <= 200 (explicit Python int/float value lists)
    - TPESampler(multivariate=True) for grid_size > 200
    - Boundary masking at train_end using tf_days_nominal to prevent lookahead
    - Temp table + ON CONFLICT DO UPDATE upsert for sweep logging

key-files:
  created:
    - alembic/versions/y8z9a0b1c2d3_phase105_sweep_columns.py
    - src/ta_lab2/analysis/param_optimizer.py
  modified: []

key-decisions:
  - "Revision ID y8z9a0b1c2d3 (not t4u5v6w7x8y9 from plan): t4u5v6w7x8y9 was already used by phase107 migration"
  - "GridSampler: explicit list(range(low, high+1)) for int params -- np.arange returns numpy scalars that fail GridSampler"
  - "TrialPruned raised on feature_fn exceptions (constraint violations like fast>=slow), not NaN return"
  - "NaN returned when valid obs < min_obs (50): Optuna treats NaN as failed trial, not pruned"

patterns-established:
  - "IC-based sweep objective: Spearman IC with boundary masking at tf_days_nominal before train_end"
  - "Sampler selection by grid_size product of param range sizes (threshold=200)"
  - "Sweep results grouped by sweep_id UUID for post-sweep analysis queries"

# Metrics
duration: 8min
completed: 2026-04-01
---

# Phase 105 Plan 01: Parameter Optimization Summary

**Alembic migration (y8z9a0b1c2d3) adding 7 sweep columns to trial_registry + param_optimizer.py with Spearman IC-based Optuna sweep using GridSampler or TPESampler based on grid size**

## Performance

- **Duration:** 8 min
- **Started:** 2026-04-01T22:38:54Z
- **Completed:** 2026-04-01T22:47:00Z
- **Tasks:** 2/2
- **Files modified:** 2

## Accomplishments

- Migration y8z9a0b1c2d3 applied: 7 nullable sweep columns added to trial_registry (sweep_id UUID, n_sweep_trials, plateau_score, rolling_stability_passes, ic_cv, sign_flips, dsr_adjusted_sharpe) plus partial index on sweep_id
- param_optimizer.py created with run_sweep() selecting GridSampler (<=200 grid points, exhaustive) or TPESampler (>200, seed=42, multivariate=True)
- IC-based Optuna objective using Spearman IC vs fwd_ret with boundary masking at train_end to prevent lookahead leakage
- Smoke test passed: 16 GridSampler trials (window 5..20), TPESampler mode verified with 20 trials

## Task Commits

Each task was committed atomically:

1. **Task 1: Alembic migration -- add sweep columns to trial_registry** - `d72efc48` (feat)
2. **Task 2: param_optimizer.py -- run_sweep with IC-based Optuna objective** - `0ae8ecb0` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified

- `alembic/versions/y8z9a0b1c2d3_phase105_sweep_columns.py` - Alembic migration adding 7 sweep columns and partial index to trial_registry
- `src/ta_lab2/analysis/param_optimizer.py` - IC-based Optuna parameter sweep with GridSampler/TPESampler selection, _make_ic_objective, _suggest_params, _log_sweep_to_registry, run_sweep

## Decisions Made

- **Revision ID changed from plan**: Plan specified `t4u5v6w7x8y9` but that ID was already used by phase107 (pipeline_stage_log). Used `y8z9a0b1c2d3` chaining from `x7y8z9a0b1c2` (phase104, current HEAD). No functional impact.
- **GridSampler value list construction**: `list(range(low, high+1))` for int params (NOT np.arange). np.arange returns numpy scalars which fail GridSampler type checks. This is a critical correctness detail noted in the plan.
- **TrialPruned vs NaN**: feature_fn exceptions (e.g. constraint violations like fast_period >= slow_period) raise TrialPruned(); insufficient observations (< min_obs) return NaN. Optuna handles both correctly but the distinction matters for trial state reporting.
- **Boundary masking**: fwd_ret set to NaN where feat.index > train_end - tf_days_nominal days. Prevents lookahead leakage at the train window boundary.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Migration revision ID conflict**

- **Found during:** Task 1 (Alembic migration creation)
- **Issue:** Plan specified revision `t4u5v6w7x8y9` which is already used by `t4u5v6w7x8y9_phase107_pipeline_stage_log.py`
- **Fix:** Used new revision `y8z9a0b1c2d3` chaining from actual current HEAD `x7y8z9a0b1c2`
- **Files modified:** `alembic/versions/y8z9a0b1c2d3_phase105_sweep_columns.py`
- **Verification:** `alembic history` showed correct chain; `alembic upgrade head` applied successfully; DB verification confirmed all 7 columns and index present
- **Committed in:** d72efc48 (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (1 bug -- revision ID conflict)
**Impact on plan:** Necessary correctness fix. No scope change.

## Issues Encountered

None beyond the revision ID conflict noted above.

## User Setup Required

None - migration applied automatically via `alembic upgrade head`. No external services required.

## Next Phase Readiness

- trial_registry has all sweep columns and index; ready for sweep orchestration scripts (105-02)
- run_sweep() exports the full sweep infrastructure; callers need only provide feature_fn and param_space_def
- _log_sweep_to_registry() is tested smoke-test only (without DB conn); full DB integration tested in 105-02
- Blockers: none

---
*Phase: 105-parameter-optimization*
*Completed: 2026-04-01*
