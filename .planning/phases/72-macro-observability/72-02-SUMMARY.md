---
phase: 72-macro-observability
plan: 02
subsystem: notifications
tags: [telegram, macro-regimes, alerting, throttling, postgresql, sqlalchemy]

# Dependency graph
requires:
  - phase: 72-01
    provides: cmc_macro_alert_log table (via Alembic migration)
  - phase: 67-macro-regime-classifier
    provides: cmc_macro_regimes table with per-dimension labels and composite regime_key
  - phase: 66-macro-features
    provides: fred.fred_macro_features table with vixcls, hy_oas_level, dff, net_liquidity_365d_zscore

provides:
  - MacroAlertManager class with per-dimension and composite transition detection
  - check_and_alert_transitions() module-level convenience wrapper
  - Throttled Telegram alerting with severity escalation for risk-off/carry-unwind
  - cmc_macro_alert_log persistence for audit trail and dashboard visibility
  - run_macro_alerts.py CLI for cron/pipeline integration

affects:
  - 72-03 (dashboard page -- may display cmc_macro_alert_log transition history)
  - Any pipeline/cron integration needing macro regime change notifications

# Tech tracking
tech-stack:
  added: []
  patterns:
    - MacroAlertManager with constructor injection (engine, cooldown_hours)
    - INTERVAL '1 hour' * :hours pattern (never INTERVAL ':N hours' -- PostgreSQL limitation)
    - OperationalError/ProgrammingError catch for missing table (Alembic migration pending)
    - Telegram monkeypatching in dry-run CLI (set is_configured -> False to suppress sends)
    - Severity escalation: risk_appetite->RiskOff and carry->Unwind use "critical"

key-files:
  created:
    - src/ta_lab2/notifications/macro_alerts.py
    - src/ta_lab2/scripts/macro/run_macro_alerts.py
  modified: []

key-decisions:
  - "Throttle window default 6 hours -- macro regimes are sticky (change ~1-3x/month), naturally low noise"
  - "Both per-dimension AND composite alerts fire independently -- gives operators per-dimension granularity"
  - "cmc_macro_alert_log write uses OperationalError/ProgrammingError guard -- handles Wave 1 parallel execution before Alembic migration runs"
  - "INTERVAL '1 hour' * :hours avoids parameterized literal bug in PostgreSQL INTERVAL syntax"
  - "Dry-run uses monkeypatch on telegram.is_configured rather than a flag parameter -- cleaner interface, no extra method signature complexity"

patterns-established:
  - "MacroAlertManager pattern: inject engine + cooldown, single check_and_alert() entrypoint returning list[dict]"
  - "Alert logging separates throttled=True records (still logged) from sent records for complete audit trail"
  - "Key metrics queried from fred.fred_macro_features per-alert (not cached) for freshest data in message"

# Metrics
duration: 3min
completed: 2026-03-03
---

# Phase 72 Plan 02: Macro Alert Notifications Summary

**Throttled MacroAlertManager detects per-dimension and composite macro regime transitions, dispatches Telegram alerts with severity escalation for risk-off/carry-unwind, and persists all alert activity to cmc_macro_alert_log**

## Performance

- **Duration:** 3 min
- **Started:** 2026-03-03T16:59:42Z
- **Completed:** 2026-03-03T17:02:36Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- MacroAlertManager with throttled per-dimension and composite regime transition detection
- Telegram severity escalation: risk_appetite->RiskOff and carry->Unwind use "critical", all other transitions use "warning"
- Alert messages enriched with key FRED metrics (VIX, HY OAS, Fed Funds, Net Liquidity Z-score)
- Graceful degradation: Telegram not configured logs warning and still persists to cmc_macro_alert_log
- cmc_macro_alert_log guard for missing table (OperationalError/ProgrammingError catch) handles Wave 1 parallel execution
- CLI script with --profile, --cooldown, --dry-run, --verbose flags for cron/pipeline integration
- Dry-run monkeypatches telegram.is_configured() to suppress sends while still running full detection logic

## Task Commits

Each task was committed atomically:

1. **Task 1: MacroAlertManager notification module** - `fd684160` (feat)
2. **Task 2: Macro alerts CLI script** - `0502d76d` (feat)

**Plan metadata:** (committed with SUMMARY.md) (docs)

## Files Created/Modified

- `src/ta_lab2/notifications/macro_alerts.py` - MacroAlertManager class and check_and_alert_transitions() wrapper
- `src/ta_lab2/scripts/macro/run_macro_alerts.py` - CLI entry point for macro alert checking

## Decisions Made

- **Cooldown 6 hours (default):** Macro regimes are sticky -- change maybe 1-3x per month. 6 hours is generous enough to prevent duplicate noise for rapid successive API runs while still capturing re-alerting after a full business day passes.
- **Both per-dimension AND composite alerts:** Per-dimension gives fine-grained visibility (e.g., "carry just moved to Unwind before the full regime key changed"). Composite fires additionally to summarize the overall picture.
- **INTERVAL '1 hour' * :hours:** PostgreSQL does not support parameterized literals inside INTERVAL string syntax. Multiplying a unit interval by a numeric parameter is the correct approach.
- **Monkeypatch for dry-run:** Simpler than adding a `dry_run` parameter to MacroAlertManager -- avoids leaking test concerns into the production class interface.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None. The cmc_macro_regimes table does not exist in the local dev environment (as expected -- integration with production DB), so dry-run produces "Fewer than 2 rows" gracefully. This is correct behavior.

## User Setup Required

None - no external service configuration required beyond what's already in place for Telegram (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`).

## Next Phase Readiness

- MacroAlertManager ready to integrate into daily pipeline after Plan 01 Alembic migration runs
- cmc_macro_alert_log will be available post-migration for dashboard to display transition history
- run_macro_alerts.py can be wired into daily cron alongside refresh_macro_regimes.py

---
*Phase: 72-macro-observability*
*Completed: 2026-03-03*
