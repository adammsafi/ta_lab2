---
phase: 47-drift-guard
verified: 2026-02-25T19:58:04Z
status: gaps_found
score: 4/5 must-haves verified
gaps:
  - truth: "DriftAttributor and ReportGenerator integration: --with-attribution path produces correct output"
    status: partial
    reason: "run_drift_report.py --with-attribution SQL references non-existent columns (dm.as_of_date, dm.signal_id, dm.paper_pnl) and non-existent AttributionResult.te_delta; report threshold uses wrong column name; breach count silently skipped"
    artifacts:
      - path: 'src/ta_lab2/scripts/drift/run_drift_report.py'
        issue: 'Lines 168-204: SQL uses dm.as_of_date (should be metric_date), dm.signal_id (not in cmc_drift_metrics), dm.paper_pnl (should be paper_cumulative_pnl); line 204 logs result.te_delta which does not exist on AttributionResult'
      - path: 'src/ta_lab2/drift/drift_report.py'
        issue: '_load_te_threshold queries tracking_error_threshold (actual: drift_tracking_error_threshold_5d); _render_markdown uses threshold_breach_5d (actual: threshold_breach) causing breach count section always empty'
    missing:
      - Fix SQL: dm.as_of_date -> dm.metric_date; remove dm.signal_id; dm.paper_pnl -> dm.paper_cumulative_pnl; result.te_delta -> valid AttributionResult field
      - Fix _load_te_threshold: query drift_tracking_error_threshold_5d not tracking_error_threshold
      - Fix _render_markdown: threshold_breach_5d -> threshold_breach
---

# Phase 47: Drift Guard Verification Report

**Phase Goal:** Continuous drift monitoring between paper executor and backtest replay -- daily metrics computation, tiered graduated response (WARNING/PAUSE/ESCALATE), 6-source attribution decomposition, and weekly Markdown + Plotly reports.
**Verified:** 2026-02-25T19:58:04Z
**Status:** gaps_found
**Re-verification:** No -- initial verification

## Goal Achievement

### Observable Truths

| #   | Truth | Status | Evidence |
| --- | ----- | ------ | -------- |
| 1   | DriftMonitor runs PIT and current-data replays, computes drift metrics, writes to cmc_drift_metrics | VERIFIED | drift_monitor.py 638 lines: _check_strategy_drift calls SignalBacktester.run_backtest(), _write_metrics uses INSERT ON CONFLICT DO UPDATE; 8 unit tests pass |
| 2   | Tiered graduated response: WARNING at 75%, PAUSE at 100%, ESCALATE to kill switch after N days | VERIFIED | drift_pause.py 392 lines: check_drift_threshold (Tier 1 send_alert severity=warning, Tier 2 activate_drift_pause); check_drift_escalation calls activate_kill_switch; 10 unit tests pass |
| 3   | DriftAttributor decomposes drift into 6 sources via sequential OAT | VERIFIED | attribution.py 509 lines: 7-step OAT (baseline + fees + slippage + timing + data_revision + sizing + regime); minimum 10-trade guard; 8 unit tests pass |
| 4   | ReportGenerator produces weekly Markdown report with 3 Plotly HTML charts | VERIFIED | drift_report.py 641 lines: equity_overlay, tracking_error, attribution_waterfall via plotly.graph_objects; reports/drift/ output; 11 unit tests pass |
| 5   | Drift monitor wired into run_daily_refresh.py; weekly report CLI produces correct output | PARTIAL | Pipeline wiring correct (TIMEOUT_DRIFT=600, stage after executor); --with-attribution has 3 wrong SQL column names and 1 wrong AttributionResult attribute -- fails at runtime |

**Score:** 4/5 truths fully verified (Truth 5 is partial)

| src/ta_lab2/scripts/run_daily_refresh.py | VERIFIED | TIMEOUT_DRIFT=600, run_drift_monitor_stage, --drift/--no-drift/--paper-start, positioned after executor before stats |
| tests/drift/ (6 test files) | VERIFIED | 58 tests pass; no test covers --with-attribution execution path |

### Key Link Verification

| From | To | Via | Status | Details |
| ---- | -- | --- | ------ | ------- |
| drift_monitor.py | SignalBacktester | lazy import + run_backtest() | WIRED | _get_signal_backtester_class(); run_backtest called per asset |
| drift_monitor.py | cmc_drift_metrics | INSERT ON CONFLICT DO UPDATE | WIRED | _write_metrics() upserts all 22 DriftMetrics fields |
| drift_pause.py | dim_risk_state | UPDATE drift_paused=TRUE | WIRED | activate_drift_pause() atomic transaction |
| drift_pause.py | activate_kill_switch | module-level import + call | WIRED | imported at module level in drift_pause.py; called when escalation deadline exceeded |
| drift_monitor.py | v_drift_summary REFRESH | _refresh_summary_view() | WIRED | CONCURRENTLY for populated view, non-concurrent for empty |
| attribution.py | SignalBacktester | lazy import + _run_replay_with_cost() | WIRED | 7 OAT replays via SignalBacktester.run_backtest() |
| drift_report.py | plotly.graph_objects | import plotly.graph_objects as go | WIRED | go.Figure, go.Scatter, go.Waterfall, fig.write_html() |
| drift_report.py | reports/drift/ | os.makedirs + file write | WIRED | makedirs exist_ok=True, utf-8 Markdown write |
| run_drift_monitor.py | DriftMonitor | deferred import + call | WIRED | DriftMonitor(engine).run(paper_start_date, dry_run) |
| run_drift_report.py | ReportGenerator | deferred import + call | WIRED | ReportGenerator(engine).generate_weekly_report() |
| run_daily_refresh.py | run_drift_monitor | subprocess -m ta_lab2.scripts.drift.run_drift_monitor | WIRED | run_drift_monitor_stage() with TIMEOUT_DRIFT; --paper-start optional gate |

### Requirements Coverage

| Requirement | Status | Blocking Issue |
| ----------- | ------ | -------------- |
| DRIFT-01: Parallel backtest runner, PIT + current-data replays | SATISFIED | V1 both use current data; PIT deferred, logged as WARNING |
| DRIFT-02: Drift metrics computed daily | SATISFIED | None |
| DRIFT-03: Auto-pause trigger: 5-day TE > 1.5% | SATISFIED | None |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| ---- | ---- | ------- | -------- | ------ |
| src/ta_lab2/scripts/drift/run_drift_report.py | 171 | dm.as_of_date -- non-existent column (should be metric_date) | Blocker | --with-attribution raises ProgrammingError at runtime |
| src/ta_lab2/scripts/drift/run_drift_report.py | 168 | dm.signal_id -- column does not exist in cmc_drift_metrics | Blocker | --with-attribution SQL query fails |
| src/ta_lab2/scripts/drift/run_drift_report.py | 169 | dm.paper_pnl -- should be dm.paper_cumulative_pnl | Blocker | --with-attribution SQL query fails |
| src/ta_lab2/scripts/drift/run_drift_report.py | 204 | result.te_delta -- AttributionResult has no te_delta field | Blocker | AttributeError at runtime |
| src/ta_lab2/drift/drift_report.py | 232 | SELECT tracking_error_threshold -- column is drift_tracking_error_threshold_5d | Warning | TE chart threshold line uses 0.05 fallback; caught by try/except |
| src/ta_lab2/drift/drift_report.py | 530 | threshold_breach_5d -- actual column is threshold_breach | Warning | Breach count section always empty; no error thrown |

### Human Verification Required

None -- all critical behaviors are verifiable programmatically for this phase.

### Gaps Summary

Phase 47 achieves its core goal. DriftMonitor (DRIFT-01, DRIFT-02), tiered graduated response (DRIFT-03), DriftAttributor, and pipeline wiring are all implemented, substantive, and correctly wired. All 58 tests pass.

The single gap is in the --with-attribution integration path within run_drift_report.py (lines 168-204). Four bugs would cause runtime failures:

1. dm.as_of_date does not exist -- should be dm.metric_date
2. dm.signal_id does not exist in cmc_drift_metrics (no signal_id column in the table)
3. dm.paper_pnl does not exist -- should be dm.paper_cumulative_pnl
4. result.te_delta -- AttributionResult has no te_delta attribute

Additionally, drift_report.py has 2 column-name mismatches: threshold chart uses 0.05 fallback instead of configured 0.015, and breach count section is always empty.

The attribution module (attribution.py) and ReportGenerator class itself are correct and tested. Bugs are isolated to CLI glue code. The --with-attribution path has no execution test -- only a help-text check.

Root cause: The --with-attribution code in run_drift_report.py was written against a hypothetical schema rather than the actual DDL and AttributionResult dataclass.

---

_Verified: 2026-02-25T19:58:04Z_
_Verifier: Claude (gsd-verifier)_
