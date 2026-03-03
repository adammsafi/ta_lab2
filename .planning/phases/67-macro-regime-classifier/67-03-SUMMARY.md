---
phase: 67-macro-regime-classifier
plan: 03
subsystem: macro
tags: [macro-regime, cli, pipeline, daily-refresh, FRED, cmc_macro_regimes]

# Dependency graph
requires:
  - phase: 67-02
    provides: MacroRegimeClassifier, load_macro_regime_config, macro_regime_config.yaml
  - phase: 66
    provides: fred.fred_macro_features (FRED-03 through FRED-16 features)
provides:
  - CLI entry point for macro regime classification (refresh_macro_regimes.py)
  - Daily pipeline integration with macro_regimes stage between macro_features and regimes
affects: [68-l4-integration, 69-risk-gates, 70-cross-asset-aggregation]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Subprocess pipeline stage pattern for daily refresh orchestration"
    - "Dry-run via internal method access when public API combines compute+write"

key-files:
  created:
    - src/ta_lab2/scripts/macro/refresh_macro_regimes.py
  modified:
    - src/ta_lab2/scripts/run_daily_refresh.py

key-decisions:
  - "Adapted CLI to actual MacroRegimeClassifier.classify() API which returns int (rows upserted) rather than DataFrame -- dry-run uses internal _load_features/_classify_dataframe to show results without writing"
  - "Pipeline ordering: macro_features -> macro_regimes -> regimes satisfies MREG-09 requirement"

patterns-established:
  - "Macro regime CLI follows refresh_macro_features.py pattern with same flag semantics"
  - "Pipeline stage wiring pattern: TIMEOUT constant + run_* function + CLI flags + component list + execution block"

# Metrics
duration: 5min
completed: 2026-03-03
---

# Phase 67 Plan 03: Macro Regime CLI & Pipeline Integration Summary

**CLI entry point for 4-dimensional macro regime classification with daily refresh pipeline integration (macro_features -> macro_regimes -> regimes ordering)**

## Performance

- **Duration:** 5 min
- **Started:** 2026-03-03T10:28:19Z
- **Completed:** 2026-03-03T10:33:16Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- Created refresh_macro_regimes.py with --full, --dry-run, --verbose, --profile, --start-date, --end-date, --config flags
- Wired macro_regimes stage into run_daily_refresh.py between macro_features and per-asset regimes (MREG-09)
- Verified dry-run produces correct output: 9558 regime rows classified across 5 macro states

## Task Commits

Each task was committed atomically:

1. **Task 1: Create refresh_macro_regimes.py CLI script** - `e11923d9` (feat)
2. **Task 2: Wire macro regime refresh into run_daily_refresh.py pipeline** - `ff9196da` (feat)

## Files Created/Modified
- `src/ta_lab2/scripts/macro/refresh_macro_regimes.py` - CLI entry point for macro regime classification (263 lines)
- `src/ta_lab2/scripts/run_daily_refresh.py` - Added run_macro_regimes() function, TIMEOUT_MACRO_REGIMES, --macro-regimes/--no-macro-regimes/--macro-regime-profile flags, and execution block

## Decisions Made
- Adapted CLI to use MacroRegimeClassifier internal methods for dry-run mode, since the public classify() API combines computation and upsert into a single call returning row count. For dry-run, we call _load_features() + _classify_dataframe() to get a DataFrame preview without DB writes.
- Used "run_macro_regimes_flag" variable name to avoid collision with function name "run_macro_regimes".

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Adapted CLI to actual MacroRegimeClassifier API**
- **Found during:** Task 1 (refresh_macro_regimes.py creation)
- **Issue:** Plan's pseudocode assumed classifier.classify() returns a DataFrame and classifier.upsert_results(df) handles writing. Actual API: classify() returns int (rows upserted) and handles both computation and upsert internally.
- **Fix:** For live mode, call classify() directly. For dry-run mode, use internal _load_features() + _classify_dataframe() to get DataFrame for preview without writing.
- **Files modified:** src/ta_lab2/scripts/macro/refresh_macro_regimes.py
- **Verification:** --dry-run successfully classified 9558 rows and printed macro state distribution without DB writes
- **Committed in:** e11923d9

---

**Total deviations:** 1 auto-fixed (1 bug - API mismatch)
**Impact on plan:** Necessary adaptation to match real API. No scope creep.

## Issues Encountered
- Git index.lock file left behind by failed pre-commit hook run -- removed manually and retried commit successfully.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Phase 67 complete: macro regime classifier infrastructure fully operational
- cmc_macro_regimes table populated with regime labels accessible to downstream phases
- Pipeline ordering ensures macro context is available before per-asset regime computation
- Ready for Phase 68 (L4 integration) to consume macro regime data

---
*Phase: 67-macro-regime-classifier*
*Completed: 2026-03-03*
