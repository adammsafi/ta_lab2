---
phase: 87-live-pipeline-alert-wiring
plan: "03"
subsystem: pipeline
tags: [orchestration, pipeline, dead-man-switch, telegram, signal-gate, ic-staleness, stage-ordering, from-stage]

# Dependency graph
requires:
  - phase: 87-01
    provides: pipeline_run_log, signal_anomaly_log, pipeline_alert_log, dim_ic_weight_overrides, ICStalenessMonitor CLI
  - phase: 87-02
    provides: SignalAnomalyGate CLI (validate_signal_anomalies.py), exit codes 0/1/2
  - phase: 86-portfolio-pipeline
    provides: run_daily_refresh.py base structure, calibrate_stops, portfolio, executor stages

provides:
  - Extended run_daily_refresh.py with STAGE_ORDER constant and --from-stage resume flag
  - run_signal_validation_gate(): subprocess stage, hard-blocks executor when rc=2
  - run_ic_staleness_check_stage(): subprocess stage, non-blocking IC decay monitoring
  - run_pipeline_completion_alert(): inline daily digest Telegram alert with 20h cooldown
  - _start_pipeline_run() / _complete_pipeline_run(): pipeline_run_log start+complete tracking
  - _check_dead_man() / _fire_dead_man_alert(): CRITICAL alert when yesterday run missing
  - --no-signal-gate and --no-ic-staleness skip flags

affects:
  - 87-04: pipeline completion monitoring and daily ops use STAGE_ORDER and all 3 new stages
  - ops: --from-stage enables surgical re-runs after failures without full pipeline restart

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "STAGE_ORDER constant: canonical ordered list; --from-stage computes skip_idx = STAGE_ORDER.index(from_stage) then uses explicit if-statements to set run_* flags to False"
    - "Executor gate pattern: signal_gate_blocked bool computed from gate rc=2, checked before executor runs"
    - "pipeline_run_id lifecycle: _start_pipeline_run INSERT -> pipeline executes -> _complete_pipeline_run UPDATE with stages/duration/status"
    - "Dead-man switch: _check_dead_man() returns True if 0 rows in pipeline_run_log (first run) = False; checks for yesterday complete row"
    - "Throttle pattern via pipeline_alert_log: SELECT 1 WHERE alert_type+alert_key+sent_at within cooldown window AND throttled=FALSE"

key-files:
  created: []
  modified:
    - src/ta_lab2/scripts/run_daily_refresh.py

key-decisions:
  - "STAGE_ORDER includes macro_gates and macro_alerts as entries even though they are triggered conditionally via run_macro_regimes_flag -- their stage_flag_map entries are None to handle this cleanly"
  - "run_signal_gate / run_ic_staleness initialized from args.all (not args.all or args.signals) -- Phase 87 stages only active in full-pipeline mode, not standalone --signals runs"
  - "signal_gate_blocked does NOT return 1 immediately: pipeline continues to drift/stats/alerts before exiting -- ensures stats and completion alert always fire"
  - "pipeline_alerts component added to components list unconditionally (not guarded by run_* flag) -- always shown in --all runs"
  - "run_ic_staleness_check_stage (not run_ic_staleness_check) to avoid naming collision with plan attribute name from argparse"
  - "CAST(:stages AS JSONB) in _complete_pipeline_run: json.dumps() produces str, needs explicit CAST for psycopg2 JSONB binding"
  - "CAST(:run_id AS UUID): run_id stored as str in Python, needs UUID cast in PostgreSQL UPDATE WHERE clause"
  - "Lazy imports (from sqlalchemy import ...) in pipeline_run_log helpers: avoids top-level import overhead for rarely-used DB helpers"
  - "ruff-format reformatted file after initial write (long lines in stage runner functions) -- re-staged and committed clean"

patterns-established:
  - "Pattern: --from-stage flag with explicit if-statements per stage variable (not locals() mutation) for reliable Python variable assignment"
  - "Pattern: non-blocking stage result always returns ComponentResult(success=True) even on Telegram failure -- alert delivery never stops pipeline"
  - "Pattern: pipeline_run_id=None guard before _complete_pipeline_run: None when migration is pending or DB error on insert"

# Metrics
duration: 8min
completed: 2026-03-24
---

# Phase 87 Plan 03: Pipeline Orchestration Wiring Summary

**run_daily_refresh.py extended with STAGE_ORDER + --from-stage resume, 3 Phase 87 stages (signal gate, IC staleness, completion alert), pipeline_run_log lifecycle logging, and dead-man switch CRITICAL alert**

## Performance

- **Duration:** 8 min
- **Started:** 2026-03-24T13:24:53Z
- **Completed:** 2026-03-24T13:32:53Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments

- Added `STAGE_ORDER` constant (25 stages) as single source of truth for pipeline ordering; `--from-stage` computes skip index and zeroes prior `run_*` flags via explicit if-statements
- Wired `run_signal_validation_gate()` subprocess stage after signals, before calibrate_stops: exit code 2 sets `signal_gate_blocked=True` which skips executor (but pipeline continues to stats and alerts)
- Wired `run_ic_staleness_check_stage()` subprocess stage after signal gate: non-blocking, RC=2 logs `[WARN]` and pipeline continues
- Wired `run_pipeline_completion_alert()` inline function after stats: builds digest (stages OK/failed/duration), sends Telegram INFO/WARNING, 20h cooldown via `pipeline_alert_log`
- Added `_start_pipeline_run()` / `_complete_pipeline_run()` for `pipeline_run_log` lifecycle: INSERT on entry, UPDATE with `stages_completed` JSONB + `total_duration_sec` + status on exit
- Added `_check_dead_man()` + `_fire_dead_man_alert()`: checks for yesterday's complete row (skips false alarm when 0 rows), sends CRITICAL Telegram with 12h throttle

## Task Commits

Each task was committed atomically:

1. **Task 1: Add STAGE_ORDER, --from-stage flag, and new stage functions** - `0aad7f74` (feat)

**Plan metadata:** `(pending)` (docs: complete plan)

## Files Created/Modified

- `src/ta_lab2/scripts/run_daily_refresh.py` -- Extended with STAGE_ORDER, --from-stage, --no-signal-gate, --no-ic-staleness, 3 new stage runners, 4 pipeline_run_log helpers, dead-man switch

## Decisions Made

- `run_signal_gate = args.all and not getattr(args, "no_signal_gate", False)`: Phase 87 stages active only in `--all` mode; standalone `--signals` runs do not trigger the gate
- `signal_gate_blocked` does NOT trigger `return 1` immediately: pipeline continues to drift, stats, and completion alert before exiting -- ensures daily digest always fires even on blocked runs
- Explicit if-statement chain for `--from-stage` skip logic (not `locals()` mutation): Python `locals()` dict is read-only for assignment; explicit per-variable pattern is correct and readable
- `CAST(:stages AS JSONB)` in `_complete_pipeline_run`: psycopg2 sends `json.dumps(stages)` as a plain string; PostgreSQL needs explicit CAST to store as JSONB
- `run_ic_staleness_check_stage` function name (with `_stage` suffix) avoids collision with `run_ic_staleness` boolean variable in `main()`
- Lazy imports inside DB helper functions (`from sqlalchemy import ...`): avoids top-level import overhead; these functions are called infrequently and gracefully degrade on import failure
- `pipeline_alerts` component unconditionally added to the displayed components list so it always appears in `--all` mode output

## Deviations from Plan

None - plan executed exactly as written. ruff-format reformatted the file after initial write (standard long-line wrapping); re-staged and committed clean.

## Issues Encountered

- ruff-format reformatted `run_daily_refresh.py` after initial write (long lines in stage runner functions, multi-argument call wrapping) -- standard pattern; re-staged and committed clean after format pass

## User Setup Required

None - existing `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` env vars used. All helpers gracefully degrade when Telegram is not configured. `pipeline_run_log` helpers catch `OperationalError` / `ProgrammingError` if the Phase 87 migration is pending.

## Next Phase Readiness

- `run_daily_refresh.py` now has full Phase 87 orchestration glue: all 3 new stages wired, pipeline health monitoring operational
- `--from-stage` enables surgical re-runs after failure at any named stage
- `pipeline_run_log` records every run's start/complete/stages/duration -- ready for dead-man monitoring
- Plan 04 can proceed with final integration testing and documentation

---
*Phase: 87-live-pipeline-alert-wiring*
*Completed: 2026-03-24*
