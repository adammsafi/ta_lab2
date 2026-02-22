---
phase: 29-stats-qa-orchestration
plan: 01
subsystem: infra
tags: [subprocess, timeout, windows, orchestration, hardening]

# Dependency graph
requires:
  - phase: 28-backtest-pipeline-fix
    provides: Completed signal/backtest pipeline -- subprocess orchestrators are production-ready
  - phase: 27-regime-integration
    provides: run_daily_refresh.py --regimes flag -- subprocess chain for bars->EMAs->regimes

provides:
  - Timeout safety on every subprocess.run() call across src/ta_lab2/ (30+ calls, 17 files)
  - Tiered timeout constants matching operation weight
  - TimeoutExpired exception handling in all 17 affected files

affects:
  - 29-02: stats runner subprocess calls added in 02 will also follow the same timeout pattern
  - 30-code-quality-tooling: ruff will sweep new code that follows this pattern

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Tiered subprocess timeouts: TIMEOUT_BARS=7200, TIMEOUT_EMAS=3600, TIMEOUT_REGIMES=1800, TIMEOUT_STATS=3600, TIMEOUT_AUDIT=1800, TIMEOUT_SYNC=600, TIMEOUT_GIT=30, TIMEOUT_BASELINE_BARS=7200, TIMEOUT_BASELINE_EMAS=3600, TIMEOUT_TOOL=300"
    - "TimeoutExpired except clause before generic Exception in try blocks"
    - "Module-level timeout constants with 'initial estimate' comment"

key-files:
  created: []
  modified:
    - src/ta_lab2/scripts/run_daily_refresh.py
    - src/ta_lab2/scripts/run_all_audits.py
    - src/ta_lab2/scripts/bars/run_all_bar_builders.py
    - src/ta_lab2/scripts/emas/run_all_ema_refreshes.py
    - src/ta_lab2/scripts/emas/stats/run_all_stats_refreshes.py
    - src/ta_lab2/scripts/returns/stats/run_all_returns_stats_refreshes.py
    - src/ta_lab2/scripts/baseline/capture_baseline.py
    - src/ta_lab2/scripts/baseline/metadata_tracker.py
    - src/ta_lab2/scripts/setup/ensure_ema_unified_table.py
    - src/ta_lab2/scripts/figure out.py
    - src/ta_lab2/tools/data_tools/memory/generate_memories_from_diffs.py
    - src/ta_lab2/tools/data_tools/generators/generate_commits_txt.py
    - src/ta_lab2/tools/data_tools/export/process_new_chatgpt_dump.py
    - src/ta_lab2/tools/data_tools/export/process_claude_history.py
    - src/ta_lab2/tools/data_tools/export/chatgpt_pipeline.py
    - src/ta_lab2/tools/ai_orchestrator/adapters.py
    - src/ta_lab2/tools/ai_orchestrator/memory/snapshot/report_dev_timeline.py

key-decisions:
  - "Tiered timeouts match operation weight (bars=2h, EMAs=1h, regimes=30m, stats=1h, audit=30m, sync=10m, git=30s, tools=5m)"
  - "TimeoutExpired as separate except clause before generic Exception -- not nested try"
  - "All timeout constants annotated with 'initial estimate, tune after observing actual runtimes'"

patterns-established:
  - "subprocess timeout pattern: add timeout=TIMEOUT_X, add except subprocess.TimeoutExpired before except Exception"
  - "Module-level TIMEOUT_X constants for discoverability and easy tuning"

# Metrics
duration: 6min
completed: 2026-02-22
---

# Phase 29 Plan 01: Subprocess Timeout Hardening Summary

**Zero subprocess.run() calls without timeout= -- 17 files hardened with tiered timeouts (7200s bars, 3600s EMAs/stats, 30s git) and TimeoutExpired exception handling to prevent silent hangs on Windows**

## Performance

- **Duration:** 6 min
- **Started:** 2026-02-22T21:52:59Z
- **Completed:** 2026-02-22T21:59:13Z
- **Tasks:** 2/2
- **Files modified:** 17

## Accomplishments
- Every subprocess.run() call across src/ta_lab2/ (30+ calls, 17 files) now has timeout= parameter
- Tiered timeout constants defined at module level with rationale comments for easy tuning
- TimeoutExpired exceptions caught and handled gracefully (ComponentResult with error_message) in all orchestrator files
- Tools/ scripts use simpler print+re-raise or RuntimeError pattern matching their non-orchestrator nature
- Also fixed pre-existing F841 lint violation (unused `here` variable in chatgpt_pipeline.py)

## Task Commits

Each task was committed atomically:

1. **Task 1: Add tiered timeouts to all subprocess.run calls in src/ta_lab2/scripts/** - `36b6e86b` (feat)
2. **Task 2: Add timeouts to subprocess.run calls in src/ta_lab2/tools/** - `83a4481c` (feat)

## Files Created/Modified
- `src/ta_lab2/scripts/run_daily_refresh.py` - TIMEOUT_BARS/EMAS/REGIMES constants, 6 subprocess calls with timeout+TimeoutExpired
- `src/ta_lab2/scripts/run_all_audits.py` - TIMEOUT_AUDIT constant, 2 subprocess calls with timeout+TimeoutExpired
- `src/ta_lab2/scripts/bars/run_all_bar_builders.py` - TIMEOUT_BARS constant, 2 subprocess calls with timeout+TimeoutExpired
- `src/ta_lab2/scripts/emas/run_all_ema_refreshes.py` - TIMEOUT_EMAS constant, 2 subprocess calls with timeout+TimeoutExpired
- `src/ta_lab2/scripts/emas/stats/run_all_stats_refreshes.py` - TIMEOUT_STATS constant, 2 subprocess calls with timeout+TimeoutExpired
- `src/ta_lab2/scripts/returns/stats/run_all_returns_stats_refreshes.py` - TIMEOUT_STATS constant, 2 subprocess calls with timeout+TimeoutExpired
- `src/ta_lab2/scripts/baseline/capture_baseline.py` - TIMEOUT_BASELINE_BARS/EMAS constants, 4 subprocess calls
- `src/ta_lab2/scripts/baseline/metadata_tracker.py` - TIMEOUT_GIT constant, 3 git subprocess calls (2 check_output + 1 run)
- `src/ta_lab2/scripts/setup/ensure_ema_unified_table.py` - TIMEOUT_SYNC constant, 1 subprocess call
- `src/ta_lab2/scripts/figure out.py` - TIMEOUT_SYNC constant, 1 subprocess call wrapped in try/except
- `src/ta_lab2/tools/data_tools/memory/generate_memories_from_diffs.py` - TIMEOUT_GIT constant, run_git() wrapped
- `src/ta_lab2/tools/data_tools/generators/generate_commits_txt.py` - TIMEOUT_GIT constant, run_git() wrapped
- `src/ta_lab2/tools/data_tools/export/process_new_chatgpt_dump.py` - TIMEOUT_TOOL constant, 2 subprocess calls wrapped
- `src/ta_lab2/tools/data_tools/export/process_claude_history.py` - TIMEOUT_TOOL constant, run_command() wrapped
- `src/ta_lab2/tools/data_tools/export/chatgpt_pipeline.py` - TIMEOUT_TOOL constant, _run() wrapped
- `src/ta_lab2/tools/ai_orchestrator/adapters.py` - timeout=30 added to gcloud --version check in _execute_cli
- `src/ta_lab2/tools/ai_orchestrator/memory/snapshot/report_dev_timeline.py` - TIMEOUT_GIT constant, module-level git log wrapped

## Decisions Made
- **Tiered timeouts match operation weight:** bars=2h, EMAs=1h, regimes=30m, stats=1h, audit=30m, sync=10m, git=30s, tools=5m -- rationale: prevents indefinite hangs while allowing realistic operation times
- **Separate TimeoutExpired except clause before generic Exception:** Keeps timeout error messages clear and distinct from other exceptions
- **'initial estimate' annotation on all constants:** Signals these are starting points, not precise measurements; tune based on observed runtimes
- **report_dev_timeline.py module-level handling:** Since git log runs at import/module level, use try/except at module scope with graceful fallback to empty list

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed pre-existing F841 lint violation in chatgpt_pipeline.py**
- **Found during:** Task 2 (ruff pre-commit hook failure)
- **Issue:** `here = Path(__file__).resolve().parent` variable was assigned but never used (dead code from an earlier refactor that switched to Python module invocations)
- **Fix:** Removed the unused `here` variable assignment (3 lines with comment)
- **Files modified:** src/ta_lab2/tools/data_tools/export/chatgpt_pipeline.py
- **Verification:** ruff lint passes, functionality unchanged (variable was never referenced)
- **Committed in:** 83a4481c (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - Bug/lint)
**Impact on plan:** Necessary fix to unblock commit. Pre-existing dead code, no behavior change.

## Issues Encountered
- ruff pre-commit hook failed on first commit attempt for both tasks (formatting differences + F841 lint). Re-staged after ruff auto-reformatted, then committed successfully on second attempt.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- STAT-04 requirement fully satisfied: zero subprocess.run() calls without timeout= across entire 408-file codebase
- Plan 29-02 can now safely add new subprocess.run() calls for stats runners -- pattern is established
- Timeout constants are in every orchestrator file -- follow TIMEOUT_STATS=3600 pattern for new stats runner subprocess calls

---
*Phase: 29-stats-qa-orchestration*
*Completed: 2026-02-22*
