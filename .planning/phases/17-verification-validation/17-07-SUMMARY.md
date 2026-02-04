---
phase: 17-verification-validation
plan: 07
subsystem: validation
tags: [import-linter, layering, refactoring, gap-closure]

# Dependency graph
requires:
  - phase: 17-02
    provides: import-linter configuration detecting regimes<->pipelines circular dependency
provides:
  - Fixed regimes->pipelines layering violation by relocating run_btc_pipeline.py
  - Created scripts/pipelines package for pipeline runner scripts
  - Reduced import-linter violations from 2 to 0 (all contracts pass)
affects: [17-08, future-pipeline-development]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Scripts layer for CLI wrappers that orchestrate pipeline execution"
    - "New scripts/pipelines/ package for pipeline-related runners"

key-files:
  created:
    - "src/ta_lab2/scripts/pipelines/__init__.py"
    - "src/ta_lab2/scripts/pipelines/run_btc_pipeline.py"
  modified: []

key-decisions:
  - "Move run_btc_pipeline.py to scripts layer (it's a CLI wrapper, not core regime logic)"
  - "Create scripts/pipelines/ package for pipeline orchestration scripts"
  - "No backward compatibility re-exports needed (file wasn't exported from regimes/__init__.py)"

patterns-established:
  - "CLI wrappers live in scripts layer, not in domain layers (regimes, pipelines, features)"
  - "scripts/pipelines/ package for pipeline orchestration utilities"

# Metrics
duration: 3min
completed: 2026-02-03
---

# Phase 17 Plan 07: Regimes-Pipelines Circular Dependency Fix

**Relocated run_btc_pipeline.py from regimes to scripts/pipelines layer, breaking regimes<->pipelines circular dependency and achieving zero import-linter violations**

## Performance

- **Duration:** 3 min
- **Started:** 2026-02-03T23:56:18Z
- **Completed:** 2026-02-03T23:59:00Z
- **Tasks:** 3
- **Files modified:** 2

## Accomplishments
- Created new scripts/pipelines/ package for pipeline runner scripts
- Moved run_btc_pipeline.py from regimes/ to scripts/pipelines/
- Broke regimes->pipelines circular dependency (regimes no longer imports pipelines)
- Fixed all import-linter contracts: 5 kept, 0 broken (100% pass rate)

## Task Commits

Combined into single atomic commit:

1. **All Tasks** - `b6994ce` (refactor: move run_btc_pipeline + create scripts/pipelines)

## Files Created/Modified
- `src/ta_lab2/scripts/pipelines/__init__.py` - Pipeline runner scripts package marker
- `src/ta_lab2/scripts/pipelines/run_btc_pipeline.py` - BTC pipeline CLI wrapper (moved from regimes)

## Decisions Made

**Move to scripts/pipelines not scripts/regimes:**
- File orchestrates pipeline execution via CLI, not core regime logic
- Imports from ta_lab2.pipelines.btc_pipeline (valid for scripts layer)
- Creates logical scripts/pipelines/ package for future pipeline runners

**No backward compatibility needed:**
- run_btc_pipeline.py was not exported from regimes/__init__.py
- No internal imports found in src/ directory
- External users can update to new import path if needed (non-breaking for ta_lab2 internals)

**Updated file header and docstring:**
- Changed comment from "src/ta_lab2/regimes/run_btc_pipeline.py" to "src/ta_lab2/scripts/pipelines/run_btc_pipeline.py"
- Clarified docstring: "CLI wrapper provides file-based interface" (vs just "keeps CLI portable")
- Emphasizes the CLI/orchestration role of this file

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None - move executed cleanly via git mv, preserving history.

## Next Phase Readiness
- Ready for Plan 17-08 (verify all contracts pass)
- import-linter shows 0 violations (all 5 contracts pass)
- CI circular-dependencies job will now succeed

**No blockers or concerns.**

---
*Phase: 17-verification-validation*
*Completed: 2026-02-03*
