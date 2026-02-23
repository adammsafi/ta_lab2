---
phase: 32-runbooks
plan: 01
subsystem: documentation
tags: [runbooks, operations, regime-pipeline, backtest-pipeline, signal-generation, vectorbt]

# Dependency graph
requires:
  - phase: 27-regime-integration
    provides: regime pipeline scripts, refresh_cmc_regimes, regime_inspect
  - phase: 28-backtest-pipeline-fix
    provides: backtest pipeline, run_backtest_signals, signal generators
  - phase: 31-documentation-freshness
    provides: DAILY_REFRESH.md format reference, mkdocs structure
provides:
  - docs/operations/REGIME_PIPELINE.md — complete operational runbook for regime refresh
  - docs/operations/BACKTEST_PIPELINE.md — complete operational runbook for backtest pipeline
affects: [32-02 (nav integration will add these to mkdocs)]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Quick Start up top — copy-paste commands first, then entry points table, then detail"
    - "Troubleshooting as subsections with error message in code block, then cause + fix"

key-files:
  created:
    - docs/operations/REGIME_PIPELINE.md
    - docs/operations/BACKTEST_PIPELINE.md
  modified: []

key-decisions:
  - "All 12 CLI flags for refresh_cmc_regimes in a flags table (verified from argparse)"
  - "regime_inspect documented with 4 modes: default, --history N, --flips, --live"
  - "Regime troubleshooting uses subsections with error message in code block for scanability"
  - "Backtest pipeline includes ASCII flow diagram for visual orientation"
  - "Metrics interpretation table includes Good/Concerning thresholds for 7 metrics"
  - "Regime A/B comparison workflow documented under State and Recovery"

patterns-established:
  - "Format: Quick Start -> Prerequisites -> Entry Points (flags table) -> Execution Flow -> Tables -> Debugging -> Verification SQL -> Troubleshooting -> Recovery -> See Also"
  - "Troubleshooting: each failure mode as a subsection with error in code block, cause, and fix command"

# Metrics
duration: 5min
completed: 2026-02-23
---

# Phase 32 Plan 01: Runbooks (RUNB-01 and RUNB-02) Summary

**REGIME_PIPELINE.md and BACKTEST_PIPELINE.md operational runbooks with all verified CLI flags, SQL queries, failure modes, and debugging workflows sourced from 32-RESEARCH.md**

## Performance

- **Duration:** 5 min
- **Started:** 2026-02-23T05:26:01Z
- **Completed:** 2026-02-23T05:31:16Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- `docs/operations/REGIME_PIPELINE.md` (RUNB-01): Complete regime pipeline runbook with Quick Start, all 12 CLI flags in a table, 10-step execution flow, 4 regime tables documented, 4 regime_inspect modes, 5 verification SQL queries, 6 troubleshooting failure modes, and manual reset queries.
- `docs/operations/BACKTEST_PIPELINE.md` (RUNB-02): Complete backtest pipeline runbook with Quick Start, ASCII flow diagram, 3 signal types with feature sources, 3 backtest modes (clean/realistic/JSON), all run_backtest_signals flags, 3 result tables documented, 4 SQL queries, metrics interpretation table with 7 thresholds, reproducibility validation explanation, and 5+ troubleshooting failure modes.
- Both runbooks include See Also cross-references meeting the plan's `key_links` requirement (REGIME_PIPELINE -> DAILY_REFRESH, BACKTEST_PIPELINE -> REGIME_PIPELINE).

## Task Commits

Each task was committed atomically:

1. **Task 1: Write REGIME_PIPELINE.md runbook (RUNB-01)** - `b4f99df6` (docs)
2. **Task 2: Write BACKTEST_PIPELINE.md runbook (RUNB-02)** - `d0431582` (docs)

**Plan metadata:** (committed with SUMMARY.md and STATE.md update)

## Files Created/Modified

- `docs/operations/REGIME_PIPELINE.md` — Regime pipeline operational runbook (308 lines)
- `docs/operations/BACKTEST_PIPELINE.md` — Backtest pipeline operational runbook (429 lines)

## Decisions Made

- Used subsection-per-failure-mode format (with error message in a code block) for Troubleshooting in both runbooks — scannable when operator is in the middle of debugging.
- Included ASCII flow diagram in BACKTEST_PIPELINE.md because the multi-source join (cmc_features + cmc_ema_multi_tf_u) is non-obvious without visual context.
- Documented regime A/B testing (`--no-regime` flag) under State and Recovery in REGIME_PIPELINE.md rather than as a separate section — it's a workflow variant, not a standard operation.
- Feature sources per signal type documented in a separate table in BACKTEST_PIPELINE.md — operators reproducing a run need to know exactly which columns each signal type reads.

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

- Pre-commit hook (mixed-line-ending) required two-pass commit cycle for each file (hook fixes then re-stage). Standard Windows behavior for new markdown files created with LF line endings.

## Next Phase Readiness

- REGIME_PIPELINE.md and BACKTEST_PIPELINE.md are ready for mkdocs nav integration (Plan 32-02).
- Both files follow the DAILY_REFRESH.md format spirit and will render correctly in mkdocs.
- No blockers for Plan 32-02 (nav integration + remaining runbooks).

---
*Phase: 32-runbooks*
*Completed: 2026-02-23*
