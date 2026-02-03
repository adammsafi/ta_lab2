---
phase: 17-verification-validation
plan: 01
subsystem: testing
tags: [pytest, pkgutil, import-validation, parametrization, optional-dependencies]

# Dependency graph
requires:
  - phase: 16-repository-cleanup
    provides: Reorganized codebase structure ready for validation
provides:
  - Dynamic import validation test suite (368 parametrized tests)
  - Orchestrator pytest marker for optional dependency tests
  - Bug fix for module-level execution breaking imports
affects: [17-02-circular-dependency-detection, 17-03-ci-workflows]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "pkgutil.walk_packages for dynamic module discovery"
    - "pytest.mark.parametrize for per-module test generation"
    - "pytest.importorskip for optional dependency handling"

key-files:
  created:
    - tests/test_imports.py
  modified:
    - pyproject.toml
    - src/ta_lab2/regimes/old_run_btc_pipeline.py

key-decisions:
  - "Use pkgutil.walk_packages instead of manual module lists for automatic discovery"
  - "Separate orchestrator tests with pytest marker for optional dependency handling"
  - "Skip orchestrator modules in tools tests rather than use importorskip in every test"

patterns-established:
  - "Dynamic module discovery: Tests auto-update as modules are added/removed"
  - "Optional dependency separation: Core tests (-m 'not orchestrator') vs optional tests (-m 'orchestrator')"

# Metrics
duration: 5min
completed: 2026-02-03
---

# Phase 17 Plan 01: Import Validation Summary

**Dynamic import validation with 368 parametrized tests using pkgutil discovery, covering all ta_lab2 and test modules**

## Performance

- **Duration:** 5 min
- **Started:** 2026-02-03T21:27:48Z
- **Completed:** 2026-02-03T21:33:39Z
- **Tasks:** 3
- **Files modified:** 3

## Accomplishments
- Created dynamic import validation test suite with 368 parametrized tests
- Added orchestrator pytest marker for optional dependency tests (chromadb, mem0ai)
- Fixed module-level execution bug in old_run_btc_pipeline.py breaking imports
- 332 core module imports validated successfully (36 orchestrator modules skipped gracefully)

## Task Commits

Each task was committed atomically:

1. **Tasks 1-2: Create import tests + Add orchestrator marker** - `807dcff` (feat)
2. **Deviation: Fix old_run_btc_pipeline import bug** - `1d1f5bb` (fix)

## Files Created/Modified
- `tests/test_imports.py` - Dynamic import validation using pkgutil.walk_packages with parametrized tests for all modules
- `pyproject.toml` - Added orchestrator marker to pytest.ini_options.markers list
- `src/ta_lab2/regimes/old_run_btc_pipeline.py` - Wrapped script execution in if __name__ == "__main__" guard

## Decisions Made

**Use pkgutil.walk_packages instead of manual module lists**
- Rationale: Automatic discovery means tests stay current as modules are added/removed during reorganization

**Skip orchestrator modules in tools tests**
- Rationale: Simpler than using pytest.importorskip in every parametrized test case

**Separate test groups for optional dependencies**
- Rationale: Allows running core validation without installing chromadb/mem0ai (pytest -m "not orchestrator")

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed module-level execution in old_run_btc_pipeline.py**
- **Found during:** Task 3 (Running import validation tests)
- **Issue:** Module had module-level code that executed during import, attempting to read CSV file that didn't exist. Caused FileNotFoundError breaking all imports.
- **Fix:** Wrapped all script execution code (lines 58-197) in `if __name__ == "__main__":` block. Module can now be imported safely without executing script.
- **Files modified:** src/ta_lab2/regimes/old_run_btc_pipeline.py
- **Verification:** Import test passes, module can be imported without errors
- **Committed in:** 1d1f5bb

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** Essential bug fix - module-level code breaking imports is a correctness issue that must be fixed for import validation to succeed.

## Issues Encountered

None - plan executed smoothly after fixing the import-breaking bug.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Import validation test suite complete and passing (332/332 core modules)
- Orchestrator modules (36) skip gracefully when dependencies not installed
- Ready for circular dependency detection (Phase 17 Plan 02)
- Ready for CI workflow integration (Phase 17 Plan 03)
- Test discovery is dynamic - will automatically validate any new modules added

---
*Phase: 17-verification-validation*
*Completed: 2026-02-03*
