---
phase: 06-ta-lab2-time-model
plan: 03
subsystem: testing
tags: [validation, ema, dim_timeframe, state_management, static_analysis]

requires:
  - 06-01  # dim_timeframe and dim_sessions tables
  - 06-02  # EMA table validation infrastructure
  - 05-06  # Phase 5 complete (orchestrator coordination)

provides:
  - Static analysis tests for dim_timeframe usage across EMA scripts
  - EMAStateManager adoption validation tests
  - Confirmation of SUCCESS CRITERION #4 (dim_timeframe referenced)
  - Confirmation of blocker #6 resolution (EMAStateManager in production)

affects:
  - 06-04  # Ready for any additional time model validations

tech-stack:
  added: []
  patterns:
    - Static analysis for code validation
    - Parametrized pytest tests for script verification
    - Indirect dependency validation (calendar feature modules)

key-files:
  created:
    - tests/time/test_refresh_scripts_dim_usage.py
    - tests/time/test_refresh_scripts_state_usage.py
  modified: []

decisions:
  - decision: "Calendar scripts use dim_timeframe indirectly via feature modules"
    rationale: "Calendar EMAs query dim_timeframe via SQL in feature layer, not directly in refresh scripts. This is architecturally sound - feature modules own TF loading logic."
    date: 2026-01-30
    alternatives: ["Require direct imports in all scripts"]
    impact: "Tests check both direct imports (multi_tf/v2) and indirect usage (cal/cal_anchor feature modules)"

  - decision: "Test for evidence of state usage, not just imports"
    rationale: "Importing EMAStateManager without using it provides no incremental benefit. Tests check for method calls, config usage, and state table references as proof of usage."
    date: 2026-01-30
    alternatives: ["Only check for imports"]
    impact: "Higher confidence that incremental state is actually wired and functional"

  - decision: "Use static analysis for validation (no database required)"
    rationale: "File content inspection is fast, deterministic, and doesn't require database connection. Ideal for CI/CD validation of code patterns."
    date: 2026-01-30
    alternatives: ["Runtime integration tests", "Database schema inspection"]
    impact: "Tests run in <2 seconds, can run in any environment"

metrics:
  duration: 8min
  completed: 2026-01-30
  test_coverage:
    dim_usage_tests: 21
    state_usage_tests: 17
    total: 38
    pass_rate: 100%
---

# Phase 6 Plan 3: Validate EMA Script Integration Summary

**One-liner:** Static analysis validates all EMA scripts use dim_timeframe and EMAStateManager

## Objective

Validate EMA refresh scripts reference dim_timeframe and use EMAStateManager through static analysis tests.

Purpose: Confirm SUCCESS CRITERION #4 (dim_timeframe referenced instead of hardcoded values) and address blocker #6 (EMAStateManager used for incremental state). No database required.

## What Was Built

### dim_timeframe Usage Validation (21 tests)

**File:** `tests/time/test_refresh_scripts_dim_usage.py`

**Coverage:**
- **Direct imports (2 scripts):** multi_tf, multi_tf_v2 import `list_tfs()` from dim_timeframe
- **Indirect usage (2 scripts):** cal, cal_anchor use dim_timeframe via feature modules
- **Feature module validation:** Calendar feature modules query dim_timeframe via SQL
- **Hardcoded TF detection:** No hardcoded TF arrays found in any active script
- **Stats scripts (4):** All reference dim_timeframe for TF validation
- **Deprecation tracking:** 15 old scripts preserved, 8 active (1.9x code reduction)
- **Base class integration:** base_ema_refresher.py references dim_timeframe

**Key findings:**
- ✓ All active scripts use centralized TF definitions
- ✓ No hardcoded TF lists found
- ✓ Calendar scripts query dim_timeframe indirectly (architecturally sound)
- ✓ Refactoring reduced duplication successfully

### EMAStateManager Usage Validation (17 tests)

**File:** `tests/time/test_refresh_scripts_state_usage.py`

**Coverage:**
- **Import validation (4 scripts):** All production scripts import EMAStateManager
- **Method call validation:** Scripts use load_state, save_state, EMAStateConfig
- **Module existence:** ema_state_manager.py exists with substantial implementation
- **API surface:** load_state, save_state/update_state_from_output, EMAStateConfig exported
- **Base integration:** BaseEMARefresher integrates state management (DRY)
- **State table references:** All scripts configure state tables for persistence
- **Schema documentation:** Unified state schema documented in module
- **Adoption summary:** 100% coverage (4/4 production scripts use state manager)

**Key findings:**
- ✓ All production scripts use EMAStateManager
- ✓ Incremental state configured for all refresh scripts
- ✓ Unified state schema documented: PRIMARY KEY (id, tf, period)
- ✓ Base refresher handles state management (no duplication)

## Deviations from Plan

None - plan executed exactly as written.

## Testing

**Test execution:**
```bash
pytest tests/time/test_refresh_scripts_dim_usage.py tests/time/test_refresh_scripts_state_usage.py -v
```

**Results:**
- 38 tests total (21 dim_usage + 17 state_usage)
- 100% pass rate
- Execution time: <2 seconds
- No database connection required

**Success criteria met:**
- ✓ All active scripts import dim_timeframe (directly or via features)
- ✓ Scripts call list_tfs() or query dim_timeframe via SQL
- ✓ No hardcoded TF arrays in active scripts
- ✓ Old scripts preserved but deprecated
- ✓ Active scripts don't import from old/
- ✓ All production scripts use EMAStateManager
- ✓ State management methods called (not just imported)

## Architecture Impact

### Centralized TF Definitions

**Before:** EMA scripts had hardcoded TF lists scattered across codebase
**After:** All scripts reference dim_timeframe table (directly or via features)

**Benefits:**
- Single source of truth for TF definitions
- Easy to add/modify timeframes without code changes
- Stats validation against same TF universe

### Incremental State Tracking

**Before:** No validation that state management was wired
**After:** Tests confirm all production scripts use EMAStateManager

**Benefits:**
- Fast incremental refreshes (only process new data)
- Dirty window detection (backfill detection)
- Unified state schema across all EMA types

## Next Phase Readiness

**Phase 6 Plan 4 (if exists):**
- All time model validation infrastructure complete
- dim_timeframe and EMA integration confirmed
- Ready for additional time model features

**Phase 7 (EMA features):**
- dim_timeframe integration validated
- EMAStateManager confirmed in use
- Safe to build new EMA features on this foundation

**No blockers.**

## Files Created

1. **tests/time/test_refresh_scripts_dim_usage.py** (21 tests)
   - Validates dim_timeframe usage patterns
   - Direct import tests for multi_tf/v2 scripts
   - Indirect usage tests for calendar feature modules
   - Hardcoded TF detection
   - Deprecation tracking

2. **tests/time/test_refresh_scripts_state_usage.py** (17 tests)
   - Validates EMAStateManager adoption
   - Import and usage verification
   - API surface validation
   - Base class integration check
   - State table configuration validation

## Key Lessons

1. **Indirect dependencies matter:** Calendar scripts don't import dim_timeframe directly, but feature modules do. Tests need to check the full dependency chain.

2. **Evidence of usage > imports:** Testing for method calls and config usage provides higher confidence than just checking imports.

3. **Static analysis is fast:** 38 tests run in <2 seconds. Perfect for CI/CD validation.

4. **Architecture validation through testing:** These tests document and enforce architectural decisions (centralized TFs, incremental state).

## Decision Log

### Calendar scripts use dim_timeframe indirectly

**Context:** Calendar EMAs (cal/cal_anchor) don't import `list_tfs()` directly

**Decision:** Accept indirect usage via feature modules as valid

**Rationale:**
- Feature modules own TF loading logic
- Scripts delegate to features for computation
- Feature modules query dim_timeframe via SQL
- Architecturally sound separation of concerns

**Impact:** Tests check both direct imports (multi_tf/v2) and indirect usage (calendar features)

### Test for evidence of state usage

**Context:** Import without usage provides no incremental benefit

**Decision:** Check for method calls, config usage, state table references

**Rationale:**
- Importing without using doesn't enable incremental refreshes
- Evidence of usage: load_state calls, EMAStateConfig, state_table references
- Higher confidence that state management is wired and functional

**Impact:** Tests verify actual usage, not just imports

## Performance Metrics

- **Execution time:** 8 minutes (test development + verification)
- **Test execution:** <2 seconds
- **Code coverage:** 4 main scripts + 4 stats scripts + 2 feature modules = 10 files validated
- **Pass rate:** 100% (38/38 tests)

---

*Completed: 2026-01-30*
*Duration: 8 minutes*
*Phase 6 Plan 3: SUCCESS CRITERION #4 and blocker #6 confirmed*
