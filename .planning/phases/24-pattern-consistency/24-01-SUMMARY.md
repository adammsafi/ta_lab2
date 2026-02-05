---
phase: 24-pattern-consistency
plan: 01
subsystem: infrastructure
tags: [template-method, abc, bar-builders, code-reuse, pattern-extraction]

# Dependency graph
requires:
  - phase: 21-comprehensive-review
    provides: Gap analysis identifying 80% code duplication across bar builders
  - phase: 07-ta_lab2-feature-pipeline
    provides: BaseEMARefresher template method pattern to mirror
provides:
  - BaseBarBuilder abstract base class with template method pattern
  - BarBuilderConfig dataclass for type-safe configuration
  - Foundation for 70% LOC reduction across 6 bar builders
affects:
  - 24-02 (will subclass BaseBarBuilder for each variant)
  - future bar builder development (standard pattern established)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Template Method pattern for bar builders (mirrors BaseEMARefresher)
    - Abstract base class with 6 abstract methods for variant behavior
    - Concrete methods for shared infrastructure (DB, logging, CLI, state)

key-files:
  created:
    - src/ta_lab2/scripts/bars/bar_builder_config.py
    - src/ta_lab2/scripts/bars/base_bar_builder.py
  modified: []

key-decisions:
  - "Mirror BaseEMARefresher pattern exactly - proven success with 80% code sharing across 6 EMA variants"
  - "6 abstract methods define variant-specific behavior: state/output table names, source query, bar building logic, CLI factory"
  - "8 concrete methods provide shared infrastructure: run() template, incremental/full rebuild, logging, CLI parsing"
  - "BarBuilderConfig dataclass for type-safe configuration matching EMARefresherConfig structure"
  - "with_tz parameter detection from config.tz for calendar vs non-calendar builders"

patterns-established:
  - "BaseBarBuilder template method: run() orchestrates execution flow, delegates to abstract methods"
  - "Configuration via dataclass: frozen, type-safe, with post_init for defaults"
  - "Logging setup: console + optional file handler, formatted timestamps"
  - "CLI integration: create_base_argument_parser() wraps common_snapshot_contract helpers"
  - "State table management: with_tz parameter for calendar vs rolling window variants"

# Metrics
duration: 5min
completed: 2026-02-05
---

# Phase 24 Plan 01: Pattern Consistency Summary

**BaseBarBuilder template method base class with 6 abstract methods and 8 concrete shared methods, mirroring proven BaseEMARefresher pattern for 70% LOC reduction**

## Performance

- **Duration:** 5 min
- **Started:** 2026-02-05T22:01:41Z
- **Completed:** 2026-02-05T22:07:10Z
- **Tasks:** 3
- **Files modified:** 2

## Accomplishments
- Created BarBuilderConfig dataclass with 13 fields mirroring EMARefresherConfig
- Implemented BaseBarBuilder abstract base class with template method pattern
- Defined 6 abstract methods for variant-specific behavior (table names, source query, bar building, CLI factory)
- Implemented 8 concrete methods for shared infrastructure (run(), incremental/full rebuild, logging, CLI)
- Integration with common_snapshot_contract for DB, state, and CLI utilities
- Foundation ready for subclassing in subsequent plans

## Task Commits

Each task was committed atomically:

1. **Task 1: Analyze bar builder structure and design BaseBarBuilder interface** - `7bbb3f4a` (feat)
2. **Task 2: Implement abstract methods and concrete shared methods** - `abc9d647` (feat - empty, completed in Task 1)
3. **Task 3: Add CLI helpers, logging, and integration with existing infrastructure** - `13925e14` (feat - empty, completed in Task 1)

**Note:** Tasks 2 and 3 were completed as part of Task 1's comprehensive implementation following BaseEMARefresher pattern.

## Files Created/Modified
- `src/ta_lab2/scripts/bars/bar_builder_config.py` - Configuration dataclass with 13 fields for all bar builder variants
- `src/ta_lab2/scripts/bars/base_bar_builder.py` - Abstract base class with template method pattern, 6 abstract methods, 8 concrete methods

## Decisions Made
- **Mirror BaseEMARefresher exactly**: Proven pattern from Phase 7 achieved 80% code sharing across 6 EMA variants. Apply same architecture to bar builders.
- **6 abstract methods for variants**: get_state_table_name(), get_output_table_name(), get_source_query(), build_bars_for_id(), create_argument_parser(), from_cli_args(). Covers all variant-specific behavior.
- **8 concrete methods for infrastructure**: run() template method, _run_incremental(), _run_full_rebuild(), load_ids(), ensure_output_table_exists(), create_base_argument_parser(), main(), _setup_logging(). Standardizes execution flow.
- **BarBuilderConfig frozen dataclass**: Type-safe configuration matching EMARefresherConfig structure. Includes common fields (db_url, ids, tables) and variant-specific extras (tz for calendar builders).
- **with_tz detection from config.tz**: Calendar builders set config.tz, triggering state table with tz column. Rolling window builders leave it None.
- **Integration via common_snapshot_contract**: Reuse existing DB, state, and CLI utilities. No duplication with EMA infrastructure.

## Deviations from Plan

None - plan executed exactly as written. Tasks 2 and 3 were completed as part of Task 1's comprehensive implementation, following the BaseEMARefresher pattern closely.

## Issues Encountered

None - BaseEMARefresher provided clear template to follow, and common_snapshot_contract utilities were already in place from prior phases.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- BaseBarBuilder foundation complete and ready for subclassing
- All 6 bar builders can now inherit from BaseBarBuilder in 24-02
- Pattern proven with BaseEMARefresher (80% code sharing achieved)
- Integration with common_snapshot_contract confirmed via imports
- No blockers for next plan

---
*Phase: 24-pattern-consistency*
*Completed: 2026-02-05*
