---
phase: 80-ic-analysis-feature-selection
plan: "02"
subsystem: analysis
tags: [statsmodels, feature-selection, stationarity, ljung-box, ic-analysis, spearman, quintile, yaml, postgres]

# Dependency graph
requires:
  - phase: 80-01
    provides: "statsmodels installed, dim_feature_selection table created"
  - phase: 80-ic-analysis-feature-selection
    provides: "ic_results table with IC/IC-IR data per feature/asset/regime"
provides:
  - "src/ta_lab2/analysis/feature_selection.py — 797-line library module with 9 public functions"
  - "test_stationarity: ADF+KPSS classification (STATIONARY/NON_STATIONARY/AMBIGUOUS/INSUFFICIENT_DATA)"
  - "test_ljungbox_on_ic: autocorrelation flag on rolling IC series"
  - "compute_monotonicity_score: Spearman Q1-Q5 terminal return Rho"
  - "load_ic_ranking + load_regime_ic: DB query helpers for IC data"
  - "classify_feature_tier: active/conditional/watch/archive with non-stationarity soft gate"
  - "build_feature_selection_config: full nested config dict with metadata + rationale strings"
  - "save_to_db: TRUNCATE + INSERT to dim_feature_selection"
  - "save_to_yaml: UTF-8 YAML with comment header"
affects:
  - "80-03: run_feature_selection.py CLI imports all 9 public functions"
  - "80-04: run_concordance.py uses classify_feature_tier and build_feature_selection_config"
  - "80-05: any downstream script reading from dim_feature_selection"

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Pattern: ADF and KPSS have opposing nulls — documented with CRITICAL comment in code"
    - "Pattern: Ljung-Box applied to IC series (not raw feature values) to detect inflated IC-IR"
    - "Pattern: Non-stationary features use 1.5x IC-IR cutoff (soft gate, not exclusion)"
    - "Pattern: Tier logic evaluated in priority order: active -> conditional -> watch -> archive"
    - "Pattern: _to_python() reused from ic.py pattern for numpy scalar SQL binding"

key-files:
  created:
    - "src/ta_lab2/analysis/feature_selection.py"
  modified: []

key-decisions:
  - "NON_STATIONARY uses 1.5x cutoff multiplier (0.45 vs 0.3) per CONTEXT.md soft-gate decision"
  - "compute_monotonicity_score returns absolute Spearman rho — both +1 and -1 indicate directional predictive power"
  - "Ljung-Box applied to IC series: detects serial correlation that could inflate IC-IR, per plan spec"
  - "build_feature_selection_config generates rationale strings for all tiers (shortfall, regime info, LB flag)"
  - "save_to_db uses TRUNCATE + INSERT (full replace) since dim_feature_selection is a snapshot dimension table"
  - "suppress_warnings=True wraps KPSS call to suppress statsmodels InterpolationWarning on boundary p-values"

patterns-established:
  - "Pattern: Statistical test functions return dicts with all raw stats + interpreted result string"
  - "Pattern: Config builder separates computation (classify_feature_tier) from formatting (_build_rationale)"

# Metrics
duration: 5min
completed: 2026-03-22
---

# Phase 80 Plan 02: feature_selection.py Library Module Summary

**797-line feature_selection.py library with 9 public functions: ADF+KPSS stationarity, Ljung-Box autocorrelation flag on IC series, Spearman quintile monotonicity, IC ranking queries, tier classification with non-stationarity soft gate, full config builder, DB TRUNCATE+INSERT, and UTF-8 YAML I/O**

## Performance

- **Duration:** 5min
- **Started:** 2026-03-22T03:06:54Z
- **Completed:** 2026-03-22T03:11:56Z
- **Tasks:** 2
- **Files modified:** 1 (created)

## Accomplishments

- Created `src/ta_lab2/analysis/feature_selection.py` with all 9 public functions, 797 lines
- Implemented ADF+KPSS stationarity test with correctly opposing nulls (ADF=unit root null, KPSS=stationary null), CRITICAL comment documenting the opposing-nulls trap
- Implemented Ljung-Box test on IC series (not raw feature values) to detect serial correlation inflating IC-IR
- Implemented `classify_feature_tier` with non-stationarity soft gate (1.5x cutoff) per CONTEXT.md decisions
- Implemented `build_feature_selection_config` producing metadata block + per-tier feature lists with auto-generated rationale strings
- Implemented `save_to_db` (TRUNCATE + INSERT pattern for snapshot dimension table) and `save_to_yaml` (UTF-8, comment header)

## Task Commits

Each task was committed atomically:

1. **Task 1 + Task 2: Create feature_selection.py with all functions** - `6ee1ba7f` (feat)

**Plan metadata:** (pending docs commit)

## Files Created/Modified

- `src/ta_lab2/analysis/feature_selection.py` - 797-line library module with 9 public functions for IC-based feature selection

## Decisions Made

- ADF+KPSS opposing nulls are documented with a CRITICAL comment in the function docstring to prevent future confusion
- NON_STATIONARY uses 1.5x IC-IR cutoff multiplier (effective_cutoff = ic_ir_cutoff * 1.5) so non-stationary features need 0.45 (not 0.30) to reach active tier
- `compute_monotonicity_score` accepts a single-row DataFrame (uses the terminal row's 5 quintile values for Spearmanr) — only empty DataFrames return 0.0
- `save_to_db` does a TRUNCATE before each INSERT batch — dim_feature_selection is a snapshot table, not append-only
- KPSS InterpolationWarning suppressed via `warnings.filterwarnings` inside a `catch_warnings()` context manager

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed compute_monotonicity_score minimum row guard**

- **Found during:** Task 1 smoke test verification
- **Issue:** Plan spec says "fewer than 2 rows, return 0.0" but the plan's smoke test passes a single-row DataFrame expecting > 0.9. The spearmanr over 5 quintile column values works correctly with 1 row.
- **Fix:** Changed guard to `len(quintile_cumulative) < 1` (empty check only) — a 1-row DataFrame correctly uses the terminal row's 5 quintile values
- **Files modified:** src/ta_lab2/analysis/feature_selection.py
- **Verification:** smoke test passes, single-row returns 1.0 for perfectly ordered quintiles
- **Committed in:** 6ee1ba7f (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (1 bug in guard condition)
**Impact on plan:** Minor spec conflict in the plan itself. Fix is correct per actual usage — quintile_cumulative always has >= 1 row from compute_quintile_returns().

## Issues Encountered

- ruff lint/format pre-commit hook modified the file (fixed indentation/whitespace). Re-staged and committed successfully.

## User Setup Required

None - no external service configuration required. Functions are pure library code; DB functions require active PostgreSQL connection at call time.

## Next Phase Readiness

- All 9 public functions importable and verified via smoke tests
- `classify_feature_tier` edge cases tested: active, archive, watch, conditional (borderline + regime specialist), NON_STATIONARY soft gate
- Ready for Plan 03: `run_feature_selection.py` CLI script that imports these functions and orchestrates the full IC sweep -> stationarity -> tier classification pipeline

---
*Phase: 80-ic-analysis-feature-selection*
*Completed: 2026-03-22*
