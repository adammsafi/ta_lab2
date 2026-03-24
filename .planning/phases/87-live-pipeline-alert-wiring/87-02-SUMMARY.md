---
phase: 87-live-pipeline-alert-wiring
plan: 02
subsystem: signals
tags: [signal-gate, anomaly-detection, telegram, pipeline, zscore, crowded-signals, postgresql]

# Dependency graph
requires:
  - phase: 87-01
    provides: Phase 87 alembic migration (signal_anomaly_log, pipeline_alert_log tables)
  - phase: 83
    provides: signals_ema_crossover, signals_atr_breakout signal tables
  - phase: 72
    provides: MacroAlertManager throttled-alert pattern (macro_alert_log, telegram.send_alert)
provides:
  - SignalAnomalyGate: count anomaly z-score gate + crowded signal detector
  - CLI script: validate_signal_anomalies.py invokable as pipeline stage
  - Hard block via exit code 2 (not a soft warning)
  - Throttled CRITICAL Telegram alerts via pipeline_alert_log (4h cooldown)
affects:
  - 87-03 (run_daily_refresh.py stage integration uses this script via subprocess)
  - 87-04 (pipeline completion alerts wired after signal gate stage)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "SignalAnomalyGate class with run_gate() -> tuple[bool, list[dict]] orchestration"
    - "DB-persisted throttle log (pipeline_alert_log) for alert cooldown -- same pattern as macro_alert_log"
    - "try/except (OperationalError, ProgrammingError) on all log inserts -- pre-migration graceful degradation"
    - "Exit code 2 for blocked signals (hard gate) vs exit code 0 (clean) vs exit code 1 (error)"
    - "DATE(ts) < CURRENT_DATE baseline filter -- prevents partial-day inflation of rolling mean/std"
    - "Fallback to full history when baseline < 30 days (prevents cold-start false positives)"

key-files:
  created:
    - src/ta_lab2/scripts/signals/validate_signal_anomalies.py
  modified: []

key-decisions:
  - "Baseline uses DATE(ts) < CURRENT_DATE (not NOW() - INTERVAL) -- critical to exclude partial-day count inflation"
  - "signals_rsi table missing from this DB -- graceful warning+continue (not an error; table created by future migration)"
  - "std clamped to max(std, 1e-6) -- prevents ZeroDivisionError when all baseline days have equal counts"
  - "Crowded check uses UNION ALL across all 3 tables -- single SQL query, consistent total denominator"
  - "Clean checks also logged to signal_anomaly_log (not only anomalies) -- full audit trail for every gate run"
  - "Alert cooldown uses pipeline_alert_log (alert_type='signal_gate_blocked', alert_key=signal_type) -- matches plan spec"
  - "Local _resolve_db_url and _get_engine -- avoids circular import from common_snapshot_contract in scripts.bars"

patterns-established:
  - "Pattern: pre-execution signal gate as standalone CLI with exit code 2 for blocked state"
  - "Pattern: throttle check reads pipeline_alert_log WHERE alert_type+alert_key+sent_at within window"
  - "Pattern: dry_run=True skips all DB writes and Telegram sends but still computes and logs"

# Metrics
duration: 3min
completed: 2026-03-24
---

# Phase 87 Plan 02: Signal Anomaly Gate Summary

**SignalAnomalyGate CLI: z-score count anomaly + crowded-signal detector with hard exit-code-2 block and 4h-throttled CRITICAL Telegram alerts via pipeline_alert_log**

## Performance

- **Duration:** 3 min
- **Started:** 2026-03-24T13:12:56Z
- **Completed:** 2026-03-24T13:15:58Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments
- `SignalAnomalyGate` class implements `check_signal_count_anomalies()` (z-score vs 90-day rolling baseline) and `check_crowded_signals()` (>40% open signal agreement on same asset+direction)
- Baseline query uses `DATE(ts) < CURRENT_DATE` to exclude today's partial-day data -- prevents false positives from partial counts inflating the mean
- Hard gate: return code 2 when anomalies detected (not a soft warning) -- signals blocked from executor
- All gate decisions logged to `signal_anomaly_log`; throttled CRITICAL Telegram alerts via `pipeline_alert_log` with 4h cooldown
- Fallback to full history when fewer than 30 days of baseline data (cold-start protection)

## Task Commits

Each task was committed atomically:

1. **Task 1: Signal Anomaly Gate implementation** - `feff0978` (feat)

## Files Created/Modified
- `src/ta_lab2/scripts/signals/validate_signal_anomalies.py` - SignalAnomalyGate class + CLI entry point

## Decisions Made
- Baseline uses `DATE(ts) < CURRENT_DATE` (not `NOW() - INTERVAL`) -- critical distinction: prevents partial-day count from inflating rolling mean and triggering false z-score alerts
- `signals_rsi` table missing from this DB is handled as graceful warning+continue -- the table will be created by the relevant signal migration, not a gate blocker
- `std` clamped to `max(std, 1e-6)` -- prevents ZeroDivisionError when all baseline days have identical counts (e.g., new deployment)
- Crowded check uses single `UNION ALL` SQL across all 3 tables -- consistent total denominator, single query
- Clean (non-anomaly) checks also logged to `signal_anomaly_log` -- provides a complete audit trail for every gate run, not just anomalies
- Local `_resolve_db_url` and `_get_engine` helpers -- avoids circular import from `common_snapshot_contract` which lives in `scripts.bars` and imports bar-specific dependencies

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- `signals_rsi` table does not exist in the current DB (only `signals_ema_crossover` and `signals_atr_breakout` exist). The gate handles this via the `try/except` wrapper around each table check -- logs a warning and continues. This is expected behavior per the plan's DB safety spec.

## User Setup Required
None - no external service configuration required beyond the Phase 87 Alembic migration (Plan 01).

## Next Phase Readiness
- `validate_signal_anomalies.py` is ready to be wired into `run_daily_refresh.py` as the `signal_validation_gate` stage (Plan 03)
- Exit codes (0/1/2) are designed for subprocess integration in the `ComponentResult` pattern
- `--dry-run` and `--verbose` flags are wired for pipeline dry-run mode passthrough

---
*Phase: 87-live-pipeline-alert-wiring*
*Completed: 2026-03-24*
