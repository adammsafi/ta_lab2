---
phase: 17-verification-validation
plan: 02
subsystem: testing
tags: [import-linter, pytest, circular-dependencies, architecture-validation]

# Dependency graph
requires:
  - phase: 16-repository-cleanup
    provides: Reorganized package structure ready for validation
provides:
  - import-linter configured with 5 contracts
  - pytest wrapper for CI integration
  - 3 architectural violations identified for gap closure
affects: [17-03-import-validation, 18-gap-closure]

# Tech tracking
tech-stack:
  added: [import-linter>=2.7]
  patterns: [layers-contract, forbidden-imports, pytest-subprocess-wrapper]

key-files:
  created:
    - tests/test_circular_deps.py
  modified:
    - pyproject.toml

key-decisions:
  - "Use layers contract instead of independence for proper layering validation"
  - "Use lint-imports command not python -m importlinter for subprocess calls"
  - "Document violations for gap closure rather than blocking deployment"

patterns-established:
  - "import-linter contracts: layers (4 tiers) + forbidden patterns"
  - "pytest subprocess wrapper with shell=True for Windows compatibility"
  - "Strict zero-cycle policy with no TYPE_CHECKING exceptions"

# Metrics
duration: 5min
completed: 2026-02-03
---

# Phase 17 Plan 02: Import-Linter Configuration Summary

**import-linter with layers contract detects 3 architectural violations: tools->features, regimes<->pipelines circular dependency**

## Performance

- **Duration:** 5 min
- **Started:** 2026-02-03T21:55:24Z
- **Completed:** 2026-02-03T22:00:24Z
- **Tasks:** 3
- **Files modified:** 2

## Accomplishments
- Configured import-linter with 5 contracts in pyproject.toml
- Created pytest wrapper for CI integration with proper Windows compatibility
- Identified 3 architectural violations requiring gap closure fixes

## Task Commits

Each task was committed atomically:

1. **Task 1: Configure import-linter in pyproject.toml** - `257f82d` (feat)
2. **Task 2: Create pytest wrapper for import-linter** - `8911d68` (test)
3. **Task 3: Run circular dependency check** - `a1b0d98` (fix)

## Files Created/Modified
- `pyproject.toml` - Added [tool.importlinter] section with 5 contracts
- `tests/test_circular_deps.py` - Pytest wrapper running lint-imports via subprocess

## Decisions Made

**Use layers contract not independence:**
- Initially tried independence contract (too strict - blocks all inter-module imports)
- Switched to layers contract defining proper layering hierarchy
- scripts > pipelines/backtests > signals/regimes/analysis > features/tools

**Document violations for gap closure:**
- import-linter detected 3 violations (not blocking deployment per plan)
- Documented for future gap closure: tools->features, regimes<->pipelines
- Test correctly fails with clear violation messages

**Use lint-imports command:**
- importlinter package lacks __main__ module
- Must use lint-imports command with shell=True for Windows PATH resolution
- subprocess.run(["lint-imports"], shell=True) works correctly

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Corrected contract type from acyclic_siblings to layers**
- **Found during:** Task 3 (running lint-imports)
- **Issue:** acyclic_siblings not a valid import-linter contract type
- **Fix:** Changed to layers contract with 4-tier hierarchy, added 4 forbidden contracts
- **Files modified:** pyproject.toml
- **Verification:** lint-imports runs successfully and detects violations
- **Committed in:** a1b0d98 (part of Task 3 commit)

**2. [Rule 1 - Bug] Fixed test subprocess invocation**
- **Found during:** Task 3 (running pytest test)
- **Issue:** python -m importlinter fails (no __main__ module)
- **Fix:** Changed to lint-imports command with shell=True for Windows
- **Files modified:** tests/test_circular_deps.py
- **Verification:** pytest test runs and correctly reports violations
- **Committed in:** a1b0d98 (part of Task 3 commit)

---

**Total deviations:** 2 auto-fixed (2 bugs - contract type and subprocess invocation)
**Impact on plan:** Both auto-fixes necessary for import-linter to work correctly. No scope creep.

## Issues Encountered

**Contract type research required:**
- Plan specified acyclic_siblings which doesn't exist in import-linter
- Researched import-linter contract types through trial and error
- Found layers contract provides proper layering validation

**Windows PATH resolution:**
- lint-imports command requires shell=True on Windows to resolve from PATH
- Without shell=True, subprocess.run() cannot find lint-imports executable

## Violations Detected

import-linter found 3 architectural violations requiring gap closure:

**1. tools -> features (Foundation layer violation)**
- ta_lab2.tools.data_tools.database_utils.ema_runners imports:
  - ta_lab2.features.ema (line 45)
  - ta_lab2.features.m_tf.ema_multi_timeframe (line 46)
  - ta_lab2.features.m_tf.ema_multi_tf_cal (line 47)
- Issue: Tools are foundational and shouldn't depend on features
- Fix: Move ema_runners or refactor to remove feature dependencies

**2. regimes <-> pipelines (Circular dependency)**
- ta_lab2.regimes.run_btc_pipeline -> ta_lab2.pipelines.btc_pipeline (line 8)
- ta_lab2.pipelines.btc_pipeline imports ta_lab2.regimes.comovement (line 27)
- Issue: Circular dependency between regimes and pipelines
- Fix: Refactor to break circular import (extract shared code or invert dependency)

**3. 2 contracts passing (correct layering)**
- Tools layer doesn't import from scripts layer: KEPT
- Features layer doesn't import from scripts layer: KEPT

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

**Ready for Phase 17-03 (Import Validation):**
- import-linter configured and working
- pytest wrapper integrated for CI
- Violations documented with line numbers

**Blockers/Concerns:**
- 3 violations require gap closure before full validation passes
- ema_runners in tools needs refactoring (foundation layer violation)
- regimes/pipelines circular dependency needs architectural fix

---
*Phase: 17-verification-validation*
*Completed: 2026-02-03*
