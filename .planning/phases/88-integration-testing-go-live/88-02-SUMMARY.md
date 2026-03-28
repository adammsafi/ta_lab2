---
phase: 88-integration-testing-go-live
plan: 02
subsystem: integration
tags: [paper-trading, burn-in, telegram, monitoring, cli, reporting]

# Dependency graph
requires:
  - phase: 87-live-pipeline-alert-wiring
    provides: pipeline_run_log, signal_anomaly_log tables; Telegram alert infrastructure
  - phase: 88-01
    provides: scripts/integration/__init__.py package init
provides:
  - daily_burn_in_report.py CLI: 8-metric daily health check for 7-day paper trading burn-in
  - Stdout + Telegram delivery with ON TRACK / WARNING / STOP verdict
affects:
  - 88-03 (smoke test or further burn-in plans that may reference or extend this script)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "NullPool SQLAlchemy engine for CLI scripts (project convention)"
    - "Per-query try/except with UNAVAILABLE fallback (never crash on partial data)"
    - "Conditional Telegram import inside no_telegram guard (graceful degrade)"
    - "ASCII-only output with HTML tags for Telegram formatting (Windows cp1252 safe)"

key-files:
  created:
    - src/ta_lab2/scripts/integration/daily_burn_in_report.py
  modified:
    - src/ta_lab2/scripts/integration/__init__.py (docstring extended in prior commit)

key-decisions:
  - "Telegram import is inside no_telegram guard block to avoid import-time side effects"
  - "positions.realized_pnl attempted first for PnL; falls back to orders.asset_id count"
  - "STOP verdict maps to 'critical' severity, WARNING to 'warning', ON TRACK to 'info'"
  - "Tracking error > 5% triggers WARNING (matches Phase 88 CONTEXT burn-in tolerance)"
  - "Each of 8 query sections independently wrapped in try/except; partial failures yield UNAVAILABLE not script failure"
  - "Day number calculated as (today - burn_in_start).days + 1, minimum 1"

patterns-established:
  - "Health report pattern: per-metric query -> dict -> build_report() assembler -> stdout + Telegram"
  - "Verdict logic: STOP takes precedence over WARNING takes precedence over ON TRACK"

# Metrics
duration: 3min
completed: 2026-03-24
---

# Phase 88 Plan 02: Daily Burn-In Status Report Summary

**ASCII-only daily paper trading health CLI querying 8 metrics (pipeline, orders, fills, risk state, drift, PnL, signal anomalies) with ON TRACK/WARNING/STOP verdict and conditional Telegram delivery**

## Performance

- **Duration:** 3 min
- **Started:** 2026-03-24T14:58:05Z
- **Completed:** 2026-03-24T15:01:14Z
- **Tasks:** 1
- **Files modified:** 2

## Accomplishments

- Created `daily_burn_in_report.py` CLI following `weekly_digest.py` pattern
- 8 health metrics queried: pipeline_run_log, orders, fills (today + cumulative), dim_risk_state, drift_metrics, positions/orders (PnL fallback), signal_anomaly_log
- Verdict logic: STOP (halted or drift_paused) > WARNING (tracking error > 5%) > ON TRACK
- Telegram delivery via `send_alert()` with severity mapping; graceful skip when unconfigured or `--no-telegram`

## Task Commits

Each task was committed atomically:

1. **Task 1: Create daily burn-in status report script** - `60ca0ec3` (feat)

**Plan metadata:** (included in task commit above)

## Files Created/Modified

- `src/ta_lab2/scripts/integration/daily_burn_in_report.py` - Daily burn-in CLI, 8 queries, stdout + Telegram delivery
- `src/ta_lab2/scripts/integration/__init__.py` - Updated docstring to list both modules

## Decisions Made

- `positions.realized_pnl` attempted first for PnL; falls back to `COUNT(DISTINCT asset_id)` from orders if `realized_pnl` column is absent -- avoids crashing on schema variations
- Tracking error > 5% threshold for WARNING matches Phase 88 CONTEXT burn-in protocol
- Each of 8 query sections independently wrapped in `try/except`; a single query failure yields `UNAVAILABLE` for that section, not a script failure
- `trading_state = 'halted'` maps to kill switch active (no `kill_switch_active` column in `dim_risk_state`)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required. Telegram delivery is conditional on `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` env vars being set.

## Next Phase Readiness

- Script is ready for use during the 7-day burn-in period
- Run daily: `python -m ta_lab2.scripts.integration.daily_burn_in_report --burn-in-start 2026-03-24`
- Telegram configured users get alerts with ON TRACK / WARNING / STOP verdict
- If `pipeline_run_log` table doesn't exist (alembic not at head), that section shows UNAVAILABLE -- reminder to run `alembic upgrade head` before burn-in

---
*Phase: 88-integration-testing-go-live*
*Completed: 2026-03-24*
