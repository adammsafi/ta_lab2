---
phase: 95-ama-ic-staleness-signal-scores
plan: 01
subsystem: analysis
tags: [ic, staleness, ama, feature-monitoring, alpha-decay]

# Dependency graph
requires:
  - phase: 80-feature-selection
    provides: feature_selection.yaml with active tier features
  - phase: 87-ic-staleness-weight-override
    provides: dim_ic_weight_overrides table, IC staleness monitor script
provides:
  - AMA-aware IC staleness monitoring for all 20 active features
  - Dual-source data loading (features table + ama_multi_tf_u)
affects: [95-02, signal-scores, daily-monitoring]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Dual-source feature loading: bar-level from features table, AMA from ama_multi_tf_u"
    - "parse_active_features() reuse from bakeoff_orchestrator for consistent feature parsing"

key-files:
  created: []
  modified:
    - src/ta_lab2/scripts/analysis/run_ic_staleness_check.py

key-decisions:
  - "Reuse parse_active_features() from bakeoff_orchestrator instead of duplicating YAML parsing"
  - "Separate _load_ama_feature() helper for clean separation of AMA query logic"

patterns-established:
  - "AMA feature queries always include alignment_source='multi_tf' AND roll=FALSE AND venue_id filters"

# Metrics
duration: 4min
completed: 2026-03-28
---

# Phase 95 Plan 01: AMA-aware IC Staleness Monitor Summary

**IC staleness monitor now loads all 20 active features (17 AMA from ama_multi_tf_u + 3 bar-level from features table) with correct multi-source branching**

## Performance

- **Duration:** 4 min
- **Started:** 2026-03-29T03:02:42Z
- **Completed:** 2026-03-29T03:07:00Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments
- IC staleness monitor checks all 20 active features instead of silently skipping 17 AMA features
- AMA features load from ama_multi_tf_u with correct filters (alignment_source, roll, venue_id, indicator, params_hash)
- Bar-level features continue to load from features table via existing information_schema validation
- BL weight-halving triggers correctly for decaying AMA features (verified in dry-run)

## Task Commits

Each task was committed atomically:

1. **Task 1: Add AMA-aware data loading to IC staleness monitor** - `76f06cb3` (feat)

## Files Created/Modified
- `src/ta_lab2/scripts/analysis/run_ic_staleness_check.py` - Dual-source feature loading, parse_active_features integration, _load_ama_feature helper

## Decisions Made
- Reuse parse_active_features() from bakeoff_orchestrator rather than duplicating YAML parsing logic -- single source of truth for feature name convention
- Separate _load_ama_feature() helper function for AMA query logic -- keeps _load_close_and_feature() branching clean
- Removed yaml and Path imports (no longer needed after removing _load_active_features)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- All 20 features monitored for IC decay, ready for 95-02 (signal scores)
- No blockers

---
*Phase: 95-ama-ic-staleness-signal-scores*
*Completed: 2026-03-28*
