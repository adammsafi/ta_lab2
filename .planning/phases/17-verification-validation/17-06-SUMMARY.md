---
phase: 17-verification-validation
plan: 06
subsystem: validation
tags: [import-linter, layering, refactoring, gap-closure]

# Dependency graph
requires:
  - phase: 17-02
    provides: import-linter configuration detecting 3 architectural violations
provides:
  - Fixed tools->features layering violation by relocating ema_runners.py
  - Demonstrated proper layering: scripts layer allowed to import from features
  - Reduced import-linter violations from 4 to 2
affects: [17-08, future-scripts-development]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Scripts layer for feature-importing utilities (not tools layer)"
    - "Deprecation notices in __init__.py for moved modules"

key-files:
  created:
    - "src/ta_lab2/scripts/emas/ema_runners.py"
  modified:
    - "src/ta_lab2/tools/data_tools/database_utils/__init__.py"

key-decisions:
  - "Move ema_runners.py to scripts layer instead of refactoring to remove feature dependencies"
  - "Do not re-export from tools/__init__.py (would violate tools->scripts layering)"
  - "Provide deprecation notice in tools/__init__.py for migration path"

patterns-established:
  - "Gap closure pattern: Move violating modules to appropriate layer rather than complex refactoring"
  - "Backward compatibility via deprecation notices, not re-exports that violate layering"

# Metrics
duration: 5min
completed: 2026-02-03
---

# Phase 17 Plan 06: Tools Layer Violation Fix

**Relocated ema_runners.py from tools to scripts layer, fixing tools->features layering violation and reducing import-linter violations from 4 to 2**

## Performance

- **Duration:** 5 min
- **Started:** 2026-02-03T23:54:06Z
- **Completed:** 2026-02-03T23:56:18Z
- **Tasks:** 3
- **Files modified:** 2

## Accomplishments
- Moved ema_runners.py from tools/data_tools/database_utils/ to scripts/emas/
- Updated module docstrings and CLI examples to reflect new location
- Fixed import-linter "Tools layer doesn't import from features layer" contract (BROKEN → PASSES)
- Reduced total violations from 4 to 2 (50% reduction)

## Task Commits

Combined into single atomic commit:

1. **All Tasks** - `1491a55` (refactor: move ema_runners + update references)

## Files Created/Modified
- `src/ta_lab2/scripts/emas/ema_runners.py` - EMA database write utilities (moved from tools)
- `src/ta_lab2/tools/data_tools/database_utils/__init__.py` - Updated with deprecation notice and removed re-exports

## Decisions Made

**Move to scripts layer instead of refactoring dependencies:**
- ema_runners.py imports from ta_lab2.features.ema, features.m_tf - these are valid imports for scripts layer
- Alternative would be to extract interfaces or invert dependencies, but the file is fundamentally a runner script
- Scripts layer is the correct location for orchestration utilities that import from features

**No re-export for backward compatibility:**
- Initial attempt to re-export from tools/__init__.py created tools->scripts violation
- Layering rules take precedence over backward compatibility
- Provided deprecation notice in __init__.py instead

**Update docstrings in moved file:**
- Updated usage examples from `ta_lab2.tools.data_tools.database_utils.ema_runners` to `ta_lab2.scripts.emas.ema_runners`
- Updated CLI examples to reflect new module path
- Ensures documentation matches new location

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Removed re-export that violated layering**
- **Found during:** Task 2 (updating import references)
- **Issue:** Initial attempt to re-export ema_runners from tools/__init__.py created tools->scripts layering violation
- **Fix:** Removed re-exports, replaced with deprecation notice pointing to new location
- **Files modified:** src/ta_lab2/tools/data_tools/database_utils/__init__.py
- **Verification:** lint-imports shows tools->scripts contract PASSES
- **Committed in:** 1491a55 (same commit as file move)

---

**Total deviations:** 1 auto-fixed (1 blocking issue)
**Impact on plan:** Essential for correct layering. Re-export would have fixed one violation while creating another.

## Issues Encountered
None - move executed cleanly via git mv, preserving history.

## Next Phase Readiness
- Ready for Plan 17-07 (fix regimes->pipelines violation)
- import-linter violations reduced from 4 to 2
- After 17-07, Plan 17-08 can verify all contracts pass

**No blockers or concerns.**

---
*Phase: 17-verification-validation*
*Completed: 2026-02-03*
