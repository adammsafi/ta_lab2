---
phase: 112-pipeline-architecture-separation
plan: "04"
subsystem: infra
tags: [pipeline, sync, ssh, psql-copy, subprocess, oracle-vm, signals]

requires:
  - phase: 112-01
    provides: pipeline_utils.py with ComponentResult, _start_pipeline_run, print_combined_summary
  - phase: 112-02
    provides: run_data_pipeline.py and run_features_pipeline.py
  - phase: 112-03
    provides: run_signals_pipeline.py, run_execution_pipeline.py, run_monitoring_pipeline.py

provides:
  - sync_signals_to_vm.py — push signal + config tables to Oracle VM via SSH + psql COPY
  - run_full_chain.py — subprocess chain Data -> Features -> Signals -> sync
  - run_daily_refresh.py updated with deprecation notice on --all code path

affects:
  - 113-vm-execution-deployment (VM tables expected by sync_signals_to_vm)
  - run_daily_refresh.py consumers (deprecation notice informs migration to run_full_chain)

tech-stack:
  added: []
  patterns:
    - "Inverted SSH+psql COPY push: local export CSV -> stdin of remote psql COPY FROM STDIN"
    - "Subprocess chain with halt-on-failure: each pipeline unaware of chain, wrapper handles sequencing"
    - "Two sync modes: incremental (watermark-based, signal tables) vs full-replace (TRUNCATE+COPY, config tables)"

key-files:
  created:
    - src/ta_lab2/scripts/etl/sync_signals_to_vm.py
    - src/ta_lab2/scripts/pipelines/run_full_chain.py
  modified:
    - src/ta_lab2/scripts/run_daily_refresh.py

key-decisions:
  - "VM DB is hyperliquid (same as sync_hl_from_vm.py) — execution tables created in Phase 113"
  - "sync_signals_to_vm --dry-run works WITHOUT VM connectivity (local watermarks only)"
  - "sync_signals_to_vm failure is non-fatal in run_full_chain (local pipeline complete; VM sync best-effort)"
  - "Signal tables: incremental by ts watermark; config/dim tables: full-replace (small, stateless)"
  - "Telegram alert on chain halt (best-effort, never crashes chain script)"

patterns-established:
  - "Push sync: _local_export_csv(engine, table, since_ts) -> io.StringIO -> COPY TO STDOUT WITH CSV HEADER"
  - "Push to VM: subprocess SSH psql COPY FROM STDIN WITH CSV HEADER (parse COPY N from stdout for row count)"
  - "TableSpec NamedTuple: name, ts_col (None = config), full_replace flag"
  - "Chain builder pattern: _build_data_cmd / _build_features_cmd / _build_signals_cmd forward relevant args"

duration: 4min
completed: 2026-04-02
---

# Phase 112 Plan 04: Sync Push + Full Chain Summary

**sync_signals_to_vm.py (SSH+psql COPY push, watermark-incremental for signals, full-replace for config) and run_full_chain.py (Data -> Features -> Signals -> VM sync with halt-on-failure + Telegram alert)**

## Performance

- **Duration:** 4 min
- **Started:** 2026-04-02T03:23:00Z
- **Completed:** 2026-04-02T03:27:00Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

- Created `sync_signals_to_vm.py` mirroring `sync_hl_from_vm.py` SSH+psql COPY pattern in reverse (push not pull)
- Created `run_full_chain.py` as the recommended replacement for `run_daily_refresh.py --all`
- Verified `--dry-run` works without any VM connectivity (local watermark inspection only)
- Chain halts on pipeline failure and sends best-effort Telegram alert

## Task Commits

1. **Task 1: Create sync_signals_to_vm.py (push pattern)** - `dce8edf8` (feat)
2. **Task 2: Create run_full_chain.py and update run_daily_refresh.py** - `caee3a24` (feat)

## Files Created/Modified

- `src/ta_lab2/scripts/etl/sync_signals_to_vm.py` — Push 8 signal tables (incremental) + 3 config tables (full-replace) to Oracle VM
- `src/ta_lab2/scripts/pipelines/run_full_chain.py` — Subprocess chain Data -> Features -> Signals -> sync_signals_to_vm
- `src/ta_lab2/scripts/run_daily_refresh.py` — Added deprecation notice on `--all` code path; updated module docstring

## Decisions Made

- **VM DB stays `hyperliquid`**: same as sync_hl_from_vm.py; execution tables created in Phase 113
- **--dry-run requires no VM**: queries only local watermarks, prints table state with row counts and sync modes; no SSH attempt
- **sync failure non-fatal in chain**: local pipeline success is the goal; VM push is best-effort so a network blip doesn't fail the whole chain
- **Config tables use full-replace**: dim_executor_config, strategy_parity, risk_overrides are small and stateless — TRUNCATE + COPY all is simpler than watermark tracking
- **Missing VM tables handled gracefully**: script prints "run Phase 113 first" warning and continues to next table

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- ruff E741 (ambiguous variable `l` in list comprehension) — fixed immediately to `line`
- ruff format reformatted run_full_chain.py (trailing space in tuple alignment) — auto-fixed by pre-commit

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Phase 113 (VM Execution Deployment) can now create the VM tables that sync_signals_to_vm.py expects
- `python -m ta_lab2.scripts.pipelines.run_full_chain --ids all` is the new recommended daily driver
- `run_daily_refresh.py --all` continues to work for backward compatibility; shows deprecation notice

---
*Phase: 112-pipeline-architecture-separation*
*Completed: 2026-04-02*
