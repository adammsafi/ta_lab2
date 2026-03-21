---
phase: 75-generalized-1d-bar-builder
plan: 02
subsystem: database
tags: [bars, orchestrator, run_all_bar_builders, run_daily_refresh, cmc, tvc, hyperliquid, cleanup]

# Dependency graph
requires:
  - phase: 75-01
    provides: Generic refresh_price_bars_1d.py with --source cmc|tvc|hl|all CLI

provides:
  - Updated run_all_bar_builders.py with 1d_cmc/1d_tvc/1d_hl entries all pointing to generic builder
  - Deleted refresh_tvc_price_bars_1d.py and refresh_hl_price_bars_1d.py
  - Updated run_daily_refresh.py --skip flags using "1d_cmc" (not stale "1d")
  - Row count parity verified: CMC=22,322 (exact), TVC=15,918 (exact), HL=96,740 (>=)

affects:
  - run_daily_refresh.py --bars --source flags now correctly skip
  - Any CI/ops scripts referencing builder name "1d" (now "1d_cmc")

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Unified 1D handler in build_command(): name.startswith('1d_') routes all 1D builders through same code path"
    - "custom_args dict on BuilderConfig carries --source flag value; --keep-rejects added only for CMC"

key-files:
  created: []
  modified:
    - src/ta_lab2/scripts/bars/run_all_bar_builders.py
    - src/ta_lab2/scripts/run_daily_refresh.py
  deleted:
    - src/ta_lab2/scripts/bars/refresh_tvc_price_bars_1d.py
    - src/ta_lab2/scripts/bars/refresh_hl_price_bars_1d.py

key-decisions:
  - "All three 1D builders use refresh_price_bars_1d.py; source differentiated by custom_args={'source': 'cmc/tvc/hl'}"
  - "Unified 1d_ prefix handler in build_command() replaces per-name if/elif branches"
  - "run_daily_refresh.py --skip flags updated from stale '1d' to '1d_cmc'"

patterns-established:
  - "custom_args dict on BuilderConfig: passes extra CLI flags to scripts; accessed via (builder.custom_args or {}).get('key')"
  - "name.startswith() prefix matching in build_command() for builder families (all 1D builders share same command structure)"

# Metrics
duration: 6min
completed: 2026-03-20
---

# Phase 75 Plan 02: Orchestrator Update and Old Script Deletion Summary

**Orchestrator updated to invoke generic refresh_price_bars_1d.py with --source cmc/tvc/hl; old TVC and HL source-specific scripts deleted; row count parity confirmed for all three sources**

## Performance

- **Duration:** 6 min
- **Started:** 2026-03-20T12:03:16Z
- **Completed:** 2026-03-20T12:09:18Z
- **Tasks:** 2
- **Files modified:** 2, deleted: 2

## Accomplishments
- Renamed `1d` builder entry to `1d_cmc` and updated both `1d_tvc` and `1d_hl` entries in `ALL_BUILDERS` to use `refresh_price_bars_1d.py` with `custom_args={"source": "..."}`
- Replaced per-name `if/elif` branches in `build_command()` with a single `name.startswith("1d_")` handler that reads `--source` from `custom_args`; `--keep-rejects` only added for CMC
- Deleted `refresh_tvc_price_bars_1d.py` (TvcOneDayBarBuilder, ~400 LOC) and `refresh_hl_price_bars_1d.py` (HlOneDayBarBuilder, ~567 LOC) via `git rm`
- Updated `run_daily_refresh.py` `--skip` flags from stale `"1d"` to `"1d_cmc"` for TVC/HL source filtering
- Row count parity verified: CMC 22,322 (exact match), TVC 15,918 (exact match), HL 96,740 (>= baseline, no scope expansion needed as data is current)
- Dry-run confirms all three 1d_ builders route to same script with correct `--source` flags

## Task Commits

Each task was committed atomically:

1. **Task 1: Update run_all_bar_builders.py orchestrator and run_daily_refresh.py** - `50345a7c` (feat)
2. **Task 2: Delete old scripts and verify row count parity** - `263745a6` (feat)

**Plan metadata:** (docs commit below)

## Files Created/Modified
- `src/ta_lab2/scripts/bars/run_all_bar_builders.py` - Renamed 1d->1d_cmc, updated 1d_tvc/1d_hl to use generic script, unified build_command() 1D handler, updated epilog help text
- `src/ta_lab2/scripts/run_daily_refresh.py` - Updated --skip flags from "1d" to "1d_cmc" in TVC and HL source filtering branches
- ~~`src/ta_lab2/scripts/bars/refresh_tvc_price_bars_1d.py`~~ - Deleted (BAR-07)
- ~~`src/ta_lab2/scripts/bars/refresh_hl_price_bars_1d.py`~~ - Deleted (BAR-07)

## Decisions Made
- **Unified 1d_ prefix handler:** Rather than extending the per-name `if/elif` chain with a third arm, the `build_command()` function now uses `name.startswith("1d_")` to handle all 1D builders uniformly. Source is read from `custom_args`. This pattern scales cleanly if new 1D sources are added (just add a `BuilderConfig` row, no code change needed).
- **--keep-rejects only for CMC:** Only CMC needs `--keep-rejects` (to preserve rows that fail the canonical filter for debugging). TVC and HL do not use this flag.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- None. The TVC/HL UniqueViolation warnings during smoke tests are expected (legacy data with old venue_ids, same issue noted in Plan 01 Summary). They don't cause non-zero exit codes and are a pre-existing concern tracked separately.

## User Setup Required
None - no external service configuration required. All changes are code-only.

## Next Phase Readiness
- BAR-06 complete: orchestrator uses generic builder with --source flag for all three 1D sources
- BAR-07 complete: old source-specific scripts deleted
- BAR-08 complete: CMC/TVC exact match; HL >= baseline
- Phase 75 objectives fully achieved
- Codebase now has one 1D builder script (`refresh_price_bars_1d.py`), invoked three times via orchestrator
- Note: Legacy TVC data with old venue_ids (8/9/10 from old builder) still exists in `price_bars_1d`; a future data migration phase can clean these up if needed

---
*Phase: 75-generalized-1d-bar-builder*
*Completed: 2026-03-20*
