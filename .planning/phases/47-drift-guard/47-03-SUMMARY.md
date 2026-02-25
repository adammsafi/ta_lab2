---
phase: 47-drift-guard
plan: 03
subsystem: risk-monitoring
tags: [drift-guard, kill-switch, backtest-replay, risk-state, materialized-view, sqlalchemy, unit-tests]

# Dependency graph
requires:
  - phase: 47-01
    provides: "cmc_drift_metrics table, v_drift_summary view, dim_risk_state drift-pause columns, dim_risk_limits drift threshold columns, dim_executor_config.fee_bps"
  - phase: 47-02
    provides: "DriftMetrics frozen dataclass, compute_drift_metrics(), compute_rolling_tracking_error(), compute_sharpe()"
  - phase: 46-risk-controls
    provides: "activate_kill_switch(), dim_risk_state, cmc_risk_events, dim_risk_limits"
  - phase: 45-paper-executor
    provides: "SignalBacktester, CostModel, cmc_fills, cmc_orders, dim_executor_config"
provides:
  - "DriftMonitor class: daily drift comparison orchestrator with run(paper_start_date, dry_run) API"
  - "drift_pause.py: activate_drift_pause, disable_drift_pause, check_drift_threshold, check_drift_escalation"
  - "Tiered graduated response: Tier 1 WARNING (75% of threshold), Tier 2 PAUSE (100%), Tier 3 ESCALATE (auto after N days)"
  - "18 unit tests passing (10 drift_pause + 8 drift_monitor)"
  - "__init__.py exports all public functions: DriftMonitor, activate_drift_pause, disable_drift_pause, check_drift_threshold, check_drift_escalation"
affects:
  - 47-04 (attribution report reads cmc_drift_metrics written by DriftMonitor)
  - 47-05 (drift report CLI uses DriftMonitor.run() output)
  - 52-operational-dashboard (DriftMonitor feeds v_drift_summary)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Deferred SignalBacktester import via module-level _SignalBacktester cache to avoid circular imports"
    - "Tiered response via check_drift_threshold: WARNING at 75% threshold, PAUSE at 100% via activate_drift_pause()"
    - "Upsert to cmc_drift_metrics: INSERT ... ON CONFLICT (metric_date, config_id, asset_id) DO UPDATE SET"
    - "Materialized view refresh: non-concurrent for empty view, CONCURRENTLY for populated view"
    - "activate_kill_switch imported at module level in drift_pause.py (not deferred) to enable @patch in tests"
    - "All Telegram calls use send_alert(severity='warning') or send_critical_alert() -- no send_warning_alert"

key-files:
  created:
    - src/ta_lab2/drift/drift_pause.py
    - src/ta_lab2/drift/drift_monitor.py
    - tests/drift/test_drift_pause.py
    - tests/drift/test_drift_monitor.py
  modified:
    - src/ta_lab2/drift/__init__.py

key-decisions:
  - "activate_kill_switch imported at module level in drift_pause.py -- deferred import inside function body makes it un-patchable via @patch('ta_lab2.drift.drift_pause.activate_kill_switch')"
  - "Both PIT and current-data replays use current data in V1 (crypto data revisions rare); WARNING logged; data_revision_pnl_diff=0"
  - "Paper fill P&L uses signed cash flow proxy (buy=-1, sell=+1) because cmc_fills lacks explicit P&L column"
  - "SIGNAL_TABLE_MAP used to validate signal_type before constructing dynamic SQL (injection prevention)"
  - "_refresh_summary_view fallback: empty view cannot use CONCURRENTLY; COUNT(*) check selects the right REFRESH variant"

patterns-established:
  - "Drift pause is softer than kill switch: positions preserved, only new signal processing blocked (drift_paused=TRUE, trading_state unchanged)"
  - "All drift events logged to cmc_risk_events with event_type in: drift_pause_activated, drift_pause_disabled, drift_escalated"
  - "DriftMonitor.run() per-asset try/except: one failing asset does not abort others"

# Metrics
duration: 8min
completed: 2026-02-25
---

# Phase 47 Plan 03: DriftMonitor and Drift Pause Summary

**DriftMonitor orchestrator + tiered drift pause system: WARNING/PAUSE/ESCALATE graduated response with cmc_drift_metrics upserts, v_drift_summary refresh, and activate_kill_switch escalation path; 29 total drift tests passing.**

## Performance

- **Duration:** 8 min
- **Started:** 2026-02-25T19:19:59Z
- **Completed:** 2026-02-25T19:27:59Z
- **Tasks:** 2
- **Files modified:** 4 created + 1 modified

## Accomplishments

- Created `drift_pause.py` (392 lines): atomic drift pause activation/disable, tiered threshold checking (hotloaded from dim_risk_limits), auto-escalation to kill switch after `drift_auto_escalate_after_days`
- Created `drift_monitor.py` (638 lines): DriftMonitor class with full daily drift pipeline -- config loading (fee_bps + slippage from dim_executor_config), SignalBacktester calls, paper fill aggregation, cmc_drift_metrics upserts, threshold checks, view refresh, escalation check
- 18 new unit tests passing (10 drift_pause + 8 drift_monitor); 29 total drift tests pass (11 plan-02 + 18 plan-03)
- All Telegram integrations use `send_alert(severity="warning")` for Tier 1 and `send_critical_alert()` for Tier 2 (no non-existent `send_warning_alert`)

## Task Commits

1. **Task 1: drift_pause.py -- tiered graduated response** - `69756a63` (feat)
2. **Task 2: drift_monitor.py -- daily drift comparison orchestrator** - `45668a2e` (feat)

## Files Created/Modified

- `src/ta_lab2/drift/drift_pause.py` - 4 public functions: activate/disable drift pause, check threshold (tiered), check escalation
- `src/ta_lab2/drift/drift_monitor.py` - DriftMonitor class orchestrating daily drift comparison pipeline
- `tests/drift/test_drift_pause.py` - 10 unit tests for all drift_pause functions with mocked DB
- `tests/drift/test_drift_monitor.py` - 8 unit tests for DriftMonitor with mocked DB and backtester
- `src/ta_lab2/drift/__init__.py` - Added exports for DriftMonitor + all 4 drift_pause functions

## Decisions Made

- **activate_kill_switch at module level in drift_pause.py**: Initially placed import inside `check_drift_escalation()` function body to avoid circular imports. This made it un-patchable via `@patch('ta_lab2.drift.drift_pause.activate_kill_switch')`. Fixed by importing at module level; no circular import issue exists since kill_switch.py does not import from drift.
- **V1 PIT replay uses current data**: PIT snapshots are not yet populated by the executor (cmc_executor_run_log.data_snapshot added by Plan 47-01 but not yet written). Both replays run with current data; `data_revision_pnl_diff` = 0. A WARNING is logged. The framework is ready for real PIT snapshots when executor is patched.
- **Paper fill P&L as signed cash flow**: `cmc_fills` table stores fill_price and fill_qty but no explicit P&L column. Used (buy=-1, sell=+1) * price * qty as daily cash flow proxy. This gives net signed position flow, not true realized P&L. Sufficient for V1 tracking error detection.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed un-patchable activate_kill_switch import in drift_pause.py**
- **Found during:** Task 1 (test execution)
- **Issue:** `from ta_lab2.risk.kill_switch import activate_kill_switch` inside function body made `@patch('ta_lab2.drift.drift_pause.activate_kill_switch')` fail with AttributeError -- the name doesn't exist at module level
- **Fix:** Moved import to module level (line 37 of drift_pause.py). No circular import issue present.
- **Files modified:** `src/ta_lab2/drift/drift_pause.py`
- **Verification:** `test_check_drift_escalation_within_window` and `test_check_drift_escalation_expired` both pass
- **Committed in:** `69756a63` (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - Bug)
**Impact on plan:** Fix was necessary for test correctness; no scope changes.

## Issues Encountered

- Pre-commit hooks (ruff-format + mixed-line-ending) reformatted files after first commit attempt (Windows CRLF). Standard workflow: re-stage reformatted files and commit again. Resolved on second commit attempt for each task.

## User Setup Required

None - no external service configuration required. DriftMonitor reads from existing DB tables (all created in Plan 47-01).

## Next Phase Readiness

- **Plan 47-04 ready**: DriftMonitor writes all attribution columns to cmc_drift_metrics; `attr_*` columns (attr_fee_delta, attr_slippage_delta, etc.) are currently NULL -- the attribution engine in Plan 47-04 will populate them
- **Plan 47-05 ready**: `v_drift_summary` is refreshed after each monitor run; drift report CLI can query it
- **Blocker**: V1 PIT snapshots not yet populated -- `check_drift_escalation` and tracking error work correctly, but `data_revision_pnl_diff` will always be 0 until executor is patched to write `data_snapshot` to `cmc_executor_run_log`

---
*Phase: 47-drift-guard*
*Completed: 2026-02-25*
