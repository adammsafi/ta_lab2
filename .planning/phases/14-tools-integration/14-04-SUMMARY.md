---
phase: 14-tools-integration
plan: 04
subsystem: tools
tags: [data-tools, database-utils, ema, migration, consolidation, cli]

# Dependency graph
requires:
  - phase: 14-02
    provides: Empty data_tools package structure with 6 subdirectories ready for migration
  - phase: 14-01
    provides: Discovery manifest categorizing 51 Data_Tools scripts
provides:
  - Consolidated database_utils/ema_runners.py module with 4 EMA write functions
  - CLI interface for running EMA writes from command line
  - Python API for programmatic EMA database operations
  - No duplicate code - all functions wrap existing ta_lab2 infrastructure
affects: [14-05, 14-06]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Consolidation pattern for duplicate runner scripts - combine into single module with CLI"
    - "Wrapper functions with documentation pointing to canonical ta_lab2 implementations"

key-files:
  created:
    - "src/ta_lab2/tools/data_tools/database_utils/__init__.py"
    - "src/ta_lab2/tools/data_tools/database_utils/ema_runners.py"
  modified: []

key-decisions:
  - "Consolidated 4 runner scripts into single ema_runners.py module instead of migrating separately (user decision at checkpoint)"
  - "Added CLI support via argparse with subcommands (daily, multi-tf, multi-tf-cal, upsert) for convenience"
  - "All functions wrap existing ta_lab2.features infrastructure - no duplicate database logic"
  - "Docstrings reference canonical implementations in ta_lab2.features.ema and ta_lab2.features.m_tf"

patterns-established:
  - "Script consolidation: Combine duplicate runners into single module with CLI rather than migrate 1:1"
  - "Wrapper documentation: Point users to canonical implementations for direct access"

# Metrics
duration: 7min
completed: 2026-02-02
---

# Phase 14 Plan 04: Database Utils Consolidation Summary

**Consolidated 4 Data_Tools EMA runner scripts into single ema_runners.py module with CLI and Python API wrapping existing ta_lab2 infrastructure**

## Performance

- **Duration:** 7 min
- **Started:** 2026-02-03T01:15:00Z
- **Completed:** 2026-02-03T01:21:55Z
- **Tasks:** 3 (consolidated into single implementation)
- **Files modified:** 2 (2 created)

## Accomplishments
- Consolidated 4 duplicate runner scripts into single well-documented module
- Added CLI support with argparse subcommands (daily, multi-tf, multi-tf-cal, upsert)
- All functions wrap existing ta_lab2.features infrastructure - no code duplication
- Comprehensive docstrings with usage examples and table documentation
- Verified all imports work correctly from package level

## Task Commits

Tasks were consolidated into single implementation commit:

1. **Consolidated implementation** - `506964c` (feat)
   - Created database_utils/ema_runners.py with 4 functions
   - write_daily_emas: Wraps ta_lab2.features.ema.write_daily_ema_to_db
   - write_multi_tf_emas: Wraps ta_lab2.features.m_tf.ema_multi_timeframe.write_multi_timeframe_ema_to_db
   - write_ema_multi_tf_cal: Wraps ta_lab2.features.m_tf.ema_multi_tf_cal.write_multi_timeframe_ema_cal_to_db
   - upsert_new_emas: Wraps ta_lab2.scripts.emas.old.run_ema_refresh_examples.example_incremental_all_ids_all_targets
   - Added CLI with argparse (4 subcommands)
   - Created database_utils/__init__.py with exports

**Plan metadata:** Not yet committed (will commit with SUMMARY.md and STATE.md updates)

## Files Created/Modified
- `src/ta_lab2/tools/data_tools/database_utils/__init__.py` - Package exports for 4 functions
- `src/ta_lab2/tools/data_tools/database_utils/ema_runners.py` - Consolidated module with CLI (324 lines)

## Decisions Made

**1. Consolidation instead of separate migration (user decision at checkpoint)**
- **Context:** Plan 14-04 specified migrating 4 scripts separately, but discovery manifest (14-01) correctly categorized them as "archive - one_offs" because they're simple wrappers
- **Checkpoint:** Presented 3 options - archive (follow discovery), migrate separately (follow plan), or consolidate
- **User decision:** Option C - consolidate into single module with CLI
- **Rationale:** Preserves functionality, reduces duplication, adds value through unified CLI interface
- **Result:** Single well-documented module instead of 4 redundant files

**2. CLI support with argparse subcommands**
- Added main() function with 4 subcommands matching original script purposes
- Examples in docstring and --help output
- Enables command-line usage: `python -m ta_lab2.tools.data_tools.database_utils.ema_runners daily --ids 1 1027`

**3. Wrapper pattern with canonical implementation references**
- All functions are thin wrappers around existing ta_lab2 infrastructure
- Docstrings include "Note" sections pointing to canonical implementations
- No duplicate database logic - just convenience layer

**4. Comprehensive documentation**
- Each function documents target database table
- Parameter descriptions with types
- Usage examples in docstrings
- Module-level docstring explains relationship to ta_lab2.features

## Deviations from Plan

### Decision checkpoint reached

**Deviation: Plan-discovery conflict**
- **Found during:** Plan analysis before Task 1
- **Issue:** Plan 14-04 specified migrating 4 database scripts, but discovery manifest (14-01) correctly categorized all 4 as "archive - one_offs" because they just import and call existing ta_lab2 functions
- **Analysis:** Scripts are wrappers, not database utilities:
  - write_daily_emas.py: 18 lines, calls ta_lab2.features.ema.write_daily_ema_to_db
  - write_multi_tf_emas.py: 18 lines, calls ta_lab2.features.m_tf.ema_multi_timeframe.write_multi_timeframe_ema_to_db
  - write_ema_multi_tf_cal.py: 18 lines, calls ta_lab2.features.m_tf.ema_multi_tf_cal.write_multi_timeframe_ema_cal_to_db
  - upsert_new_emas_canUpdate.py: 43 lines, calls ta_lab2.scripts.emas.old.run_ema_refresh_examples.example_incremental_all_ids_all_targets
- **Checkpoint:** Applied Deviation Rule 4 (architectural decision needed) - presented 3 options to user
- **User decision:** Option C - consolidate into single module with CLI
- **Implementation:** Created database_utils/ema_runners.py combining all 4 functions with unified CLI
- **Files created:** 2 (ema_runners.py, __init__.py)
- **Verification:** All imports work, no hardcoded paths, CLI functional

---

**Total deviations:** 1 architectural decision checkpoint
**Impact on plan:** User-approved consolidation improves design - single well-documented module instead of 4 redundant files. Adds CLI value not in original scripts.

## Issues Encountered

None. Consolidation implementation proceeded smoothly:
- All source files found in Data_Tools directory
- All underlying ta_lab2 functions importable
- All wrapper functions work correctly
- CLI subcommands match original script purposes
- Import verification passed for all functions

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

**Ready for 14-05 (next migration plan):**
- database_utils module complete with 4 EMA convenience functions
- Pattern established for consolidating duplicate runners
- CLI pattern available for other tool categories if needed
- No hardcoded paths or credentials

**Remaining migration work:**
- Analysis tools (3 scripts from discovery manifest)
- Processing tools (1 script)
- Memory tools (16 scripts)
- Export tools (7 scripts)
- Context tools (5 scripts)
- Generators tools (6 scripts)

**No blockers.** Consolidation pattern successful, ready to apply to other tool categories.

---
*Phase: 14-tools-integration*
*Completed: 2026-02-02*
