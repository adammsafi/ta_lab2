# Phase 53: V1 Validation - Research

**Researched:** 2026-02-25
**Domain:** Paper trading validation, gate assessment, audit/log review, kill switch testing, automated report generation
**Confidence:** HIGH (codebase patterns, existing infrastructure), MEDIUM (PASS/CONDITIONAL/FAIL frameworks, MaxDD handling), LOW (external industry standards for crypto paper trading)

---

## Summary

Phase 53 is a pure measurement phase: run 2 weeks of paper trading, collect evidence, score against V1 success criteria, and produce a validation report. No new trading logic is built. The infrastructure from Phases 45-47 and 52 already does the heavy lifting; Phase 53 adds the validation scaffolding layered on top.

Six distinct deliverables emerge from the requirements: (1) a pre-validation go/no-go script, (2) a daily automated validation log generator, (3) a kill switch exercise protocol and evidence collector, (4) an audit/gap detection script, (5) an end-of-period validation report (Markdown + Plotly HTML + Jupyter notebook), and (6) a gate assessment framework that scores each V1 criterion PASS/CONDITIONAL/FAIL with documented evidence.

The codebase investigation reveals all DB tables needed are live, all query patterns exist, all report generation conventions (reports/ directory, Plotly HTML charts, Markdown with embedded links) are established in Phase 42 and Phase 47. The primary work is writing new scripts that query the existing tables and assemble outputs in the defined format.

**Key finding on MaxDD:** The MaxDD gate is structurally impossible to pass for long-only BTC strategies. Research and the existing BAKEOFF_SCORECARD.md confirm this. The correct approach is CONDITIONAL (mitigation documented), not FAIL (problem hidden). The report must state: original gate fails, deployed mitigation (10% sizing + circuit breaker), why this is considered adequate for V1.

**Key finding on Jupyter:** `jupyter` is NOT currently installed in the project. The Jupyter notebook deliverable requires `jupyter` and `nbformat` to be added to the project environment. The notebook can be generated programmatically via `nbformat` without launching a Jupyter server.

**Primary recommendation:** Use a 3-tier gate framework: PASS (criterion met at full threshold), CONDITIONAL (criterion failed but documented mitigation exists and was tested), FAIL (criterion failed with no adequate mitigation). For V1, Sharpe and operational criteria are expected to PASS; MaxDD is CONDITIONAL; tracking error and slippage are measured-and-reported.

---

## Standard Stack

### Core (No New Dependencies Except Jupyter)

| Library | Version | Purpose | Already Installed |
|---------|---------|---------|------------------|
| `sqlalchemy` | existing | All DB reads, audit queries | YES |
| `pandas` | existing | DataFrame ops for log analysis | YES |
| `numpy` | existing | Rolling stats, slippage computation | YES |
| `plotly` | existing | Equity curve, drawdown, slippage charts (write_html) | YES (Phase 42 + 47) |
| `argparse` | stdlib | CLI entry points for all validation scripts | YES |
| `dataclasses` | stdlib | GateResult, ValidationSummary data types | YES |
| `json` | stdlib | Gate scoring results serialization | YES |
| `datetime` | stdlib | Date range computations | YES |

### New Dependency: Jupyter Notebook Generation

| Library | Version | Purpose | Already Installed |
|---------|---------|---------|------------------|
| `nbformat` | 5.x | Programmatic notebook creation (cells, metadata) | NO |
| `jupyter` | 7.x or `notebook` 7.x | Notebook execution + rendering | NO |

**Verification step before planning:**
```bash
python -c "import nbformat; print(nbformat.__version__)"
python -c "import jupyter; print('jupyter ok')"
```

**Installation if missing:**
```bash
pip install nbformat jupyter
# Or add to pyproject.toml [project.optional-dependencies] validation = ["nbformat>=5.0", "jupyter>=7.0"]
```

**Alternative (no jupyter required):** Generate the notebook as a `.ipynb` file using `nbformat` alone — this creates a valid notebook file that can be opened in Jupyter without the library being installed at generation time. The notebook only needs to be _executed_ if someone wants to re-run queries interactively. For generation-only, `nbformat` is sufficient.

### No New Dependencies for Core Deliverables

Deliverables 1-5 (pre-validation check, daily log, kill switch protocol, audit script, report) use only existing project libraries.

---

## Architecture Patterns

### Recommended Project Structure

```
src/ta_lab2/
├── validation/                          # NEW package for Phase 53
│   ├── __init__.py
│   ├── gate_framework.py                # GateResult dataclass, score_gate(), aggregate_gates()
│   ├── daily_log.py                     # DailyValidationLog: query all tables, format log
│   ├── audit_checker.py                 # AuditChecker: gap detection queries, orphan detection
│   └── report_builder.py               # ValidationReportBuilder: Markdown + Plotly + notebook

scripts/
└── validation/                          # NEW scripts package
    ├── __init__.py
    ├── run_preflight_check.py           # CLI: pre-validation go/no-go checklist
    ├── run_daily_validation_log.py      # CLI: generate daily validation log file
    ├── run_kill_switch_exercise.py      # CLI: engineered kill switch test protocol
    ├── run_audit_check.py               # CLI: log gap detection + audit
    └── generate_validation_report.py   # CLI: end-of-period report (Markdown + notebook)

reports/validation/                      # Output directory (follows reports/ convention)
    ├── daily/
    │   └── validation_YYYY-MM-DD.md    # One per day, generated by daily log script
    ├── kill_switch_exercise/
    │   └── ks_exercise_YYYY-MM-DD.md   # Kill switch test evidence document
    ├── audit/
    │   └── audit_YYYY-MM-DD.md         # Gap detection findings
    └── V1_VALIDATION_REPORT.md          # Final end-of-period report
    └── V1_VALIDATION_REPORT.ipynb       # Executable notebook version
    └── charts/                          # Plotly HTML charts
        ├── equity_curve.html
        ├── drawdown.html
        ├── tracking_error.html
        └── slippage_distribution.html
```

### Pattern 1: PASS/CONDITIONAL/FAIL Gate Framework (RECOMMENDED)

**What:** A 3-tier assessment for each V1 criterion instead of binary PASS/FAIL.

**Why 3 tiers:** The MaxDD gate is known to fail structurally. Binary PASS/FAIL would require either lying (call it PASS at reduced sizing) or blocking (stop all V1 progress). Neither is honest. CONDITIONAL handles "gate failed, mitigation documented and tested, proceeding with documented risk" which is how quantitative trading firms actually handle known-fail situations.

**Industry basis (MEDIUM confidence):** QuantConnect's reconciliation approach emphasizes understanding deviation sources rather than pass/fail thresholds. The UK PRA Supervisory Statement SS5/18 on algorithmic trading requires firms to "document and manage risks arising from algorithmic trading" — this is the operational basis for CONDITIONAL gates. No published standard uses exactly this 3-tier nomenclature, but it maps directly to how risk committees at quant funds work: risks are ACCEPTED (with documentation), MITIGATED (with tested controls), or BLOCKED (no acceptable mitigation).

**Gate scoring logic:**
```python
# Source: pattern derived from Phase 42 gate_failures in generate_bakeoff_scorecard.py
# and from QuantConnect reconciliation philosophy (understanding, not pass/fail)

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

class GateStatus(str, Enum):
    PASS = "PASS"           # Criterion met at defined threshold
    CONDITIONAL = "CONDITIONAL"  # Criterion failed; documented mitigation exists and tested
    FAIL = "FAIL"           # Criterion failed; no adequate mitigation

@dataclass
class GateResult:
    """Assessment result for one V1 criterion."""
    gate_id: str             # e.g., "VAL-02", "SHARPE", "MAXDD"
    gate_name: str           # Human-readable name
    threshold: str           # What the criterion requires
    measured_value: str      # What was actually measured
    status: GateStatus       # PASS / CONDITIONAL / FAIL
    evidence_sources: list[str]   # DB tables / log files / scripts that support this
    mitigation: Optional[str] = None   # For CONDITIONAL: what mitigation was applied
    notes: str = ""

def score_gate(
    measured: float | None,
    threshold: float,
    direction: str,   # "above" (higher is better) or "below" (lower is better)
) -> GateStatus:
    """Score a single numeric gate. Returns PASS or FAIL (no CONDITIONAL for numeric)."""
    if measured is None:
        return GateStatus.FAIL
    if direction == "above":
        return GateStatus.PASS if measured >= threshold else GateStatus.FAIL
    else:
        return GateStatus.PASS if measured <= threshold else GateStatus.FAIL
```

**V1 gate scorecard structure:**
```python
# Scores for all 5 VAL requirements + 3 backtest gates

V1_GATES = [
    # Backtest gates (from Phase 42 BAKEOFF_SCORECARD.md)
    GateResult(
        gate_id="BT-01",
        gate_name="Backtest Sharpe",
        threshold=">= 1.0 (OOS walk-forward mean)",
        measured_value="ema_trend(17,77): 1.401 | ema_trend(21,50): 1.397",
        status=GateStatus.PASS,
        evidence_sources=["reports/bakeoff/BAKEOFF_SCORECARD.md", "cmc_backtest_metrics"],
    ),
    GateResult(
        gate_id="BT-02",
        gate_name="Backtest MaxDD",
        threshold="<= 15% (worst fold)",
        measured_value="ema_trend(17,77): 75.0% | ema_trend(21,50): 70.1%",
        status=GateStatus.CONDITIONAL,
        evidence_sources=["reports/bakeoff/BAKEOFF_SCORECARD.md"],
        mitigation=(
            "Structural: long-only BTC strategies face unavoidable 70-75% bear-market drawdowns. "
            "Mitigation: 10% position fraction (vs 50% in backtest) + 15% portfolio circuit breaker active. "
            "Deployed controls validated in Phase 46 and tested in kill switch exercise (Phase 53)."
        ),
    ),
    # Live paper gates (VAL requirements)
    # VAL-01, VAL-02, VAL-03, VAL-04, VAL-05 -- see Code Examples section
]
```

**When to apply CONDITIONAL vs FAIL:**
- CONDITIONAL: failure is known/structural, mitigation is documented, mitigation was tested (not just planned)
- FAIL: failure is unexpected, OR mitigation was not tested, OR failure is disqualifying for the specific purpose of V1

### Pattern 2: Daily Validation Log (Automated Query)

**What:** A script that runs once per day (added to `run_daily_refresh.py --all` or as a standalone post-pipeline step), queries all relevant tables, and writes a structured Markdown log file to `reports/validation/daily/`.

**Structure of daily log:**
```markdown
# Daily Validation Log: YYYY-MM-DD
**Day N of 14 validation period**
**Generated:** YYYY-MM-DDTHH:MM:SSZ

## Pipeline Status
- Executor run: [SUCCESS/FAILED/NO_SIGNALS] at HH:MM UTC (run_id: ...)
- Drift monitor run: [SUCCESS/FAILED] at HH:MM UTC
- Dashboard: [UP/DOWN]

## Signals Generated (Today)
| Strategy | Asset | Signal Direction | Signal TS |
|----------|-------|-----------------|-----------|

## Orders & Fills (Today)
| Strategy | Asset | Side | Qty | Fill Price | Slippage bps |
|----------|-------|------|-----|------------|--------------|

## Positions (Current)
| Strategy | Asset | Qty | Mark Price | Unrealized P&L |
|----------|-------|-----|------------|----------------|

## P&L Summary (Cumulative + Daily)
| Strategy | Daily P&L | Cumulative P&L | Daily Return % |
|----------|-----------|----------------|----------------|

## Drift Metrics (Today)
| Config | TE 5d | TE 30d | Threshold | Status |
|--------|-------|--------|-----------|--------|

## Risk State
- Kill switch: [ACTIVE/HALTED] (last event: ...)
- Daily loss stop: [% of threshold consumed]
- Circuit breaker: [per strategy state]

## Anomalies Detected (Automated)
[See Audit/Gap Detection Pattern below for what this checks]

## Notes
[Human-fillable section for manual observations]
```

**DB queries feeding the log:**
```python
# Source: patterns from Phase 52 queries/ modules (trading.py, risk.py, drift.py, executor.py)
# All tables are live. This is assembly of existing queries, not new DB work.

DAILY_LOG_QUERIES = {
    "executor_runs": """
        SELECT run_id, started_at, status, signals_read, orders_generated, fills_processed
        FROM cmc_executor_run_log
        WHERE started_at::date = CURRENT_DATE
        ORDER BY started_at DESC LIMIT 5
    """,
    "today_fills": """
        SELECT f.fill_id, f.filled_at, f.fill_qty, f.fill_price, f.side,
               o.asset_id, o.signal_id
        FROM cmc_fills f JOIN cmc_orders o ON f.order_id = o.order_id
        WHERE f.filled_at::date = CURRENT_DATE
    """,
    "positions": """
        SELECT asset_id, exchange, strategy_id, quantity, avg_entry_price
        FROM cmc_positions WHERE quantity != 0
    """,
    "risk_state": """
        SELECT trading_state, halted_at, halted_reason,
               day_open_portfolio_value, drift_paused, drift_paused_at
        FROM dim_risk_state WHERE state_id = 1
    """,
    "today_drift": """
        SELECT config_id, metric_date, tracking_error_5d, tracking_error_30d,
               threshold_breach, paper_cumulative_pnl
        FROM cmc_drift_metrics
        WHERE metric_date = CURRENT_DATE
    """,
}
```

### Pattern 3: Kill Switch Exercise Protocol

**What:** A scripted end-to-end kill switch test that lowers the daily loss threshold temporarily, triggers the automatic stop, validates the response, then restores thresholds. Produces a timestamped evidence document.

**Protocol steps (to be run on Day 1 or Day 2 of validation):**

```
STEP 1: Pre-exercise snapshot (T-0)
  - Record current dim_risk_state (trading_state, halted_at=null)
  - Record current open orders count
  - Record current cmc_risk_events max(event_ts)
  - Record system time T0

STEP 2: Manual kill switch activation (T+1 minute)
  - Run: python -m ta_lab2.scripts.risk.kill_switch_cli activate --reason "V1 validation kill switch exercise - manual test"
  - Record T1 = time of activation
  - Latency(manual) = T1 - T0

STEP 3: Validate manual trigger effects (T+2 minutes)
  - Query dim_risk_state: trading_state='halted', halted_reason matches
  - Query cmc_orders: no orders in 'created' or 'submitted' status
  - Query cmc_risk_events: new row with event_type='kill_switch_activated'
  - Check Telegram: alert received (Y/N) with message text
  - Record evidence in exercise log

STEP 4: Manual re-enable (T+3 minutes)
  - Run: python -m ta_lab2.scripts.risk.kill_switch_cli disable --reason "V1 exercise: manual test complete" --operator "asafi"
  - Verify trading_state returns to 'active'

STEP 5: Engineer automatic trigger (T+10 minutes)
  - Lower daily_loss_pct_threshold in dim_risk_limits to 0.001 (0.1% -- almost immediate trigger)
  - Wait for RiskEngine to detect daily loss exceeds threshold on next check (max 5 min)
  - Record T5 = time trigger fires automatically
  - Latency(auto) = T5 - time of threshold change

STEP 6: Validate automatic trigger effects
  - Same checks as STEP 3
  - Confirm event_type='daily_loss_stop_triggered' in cmc_risk_events
  - Confirm Telegram alert received with trigger_source='daily_loss_stop'
  - Confirm cooldown period starts (cb_portfolio_breaker_tripped_at populated)

STEP 7: Restore thresholds + auto-resume (T+15 minutes)
  - Restore dim_risk_limits.daily_loss_pct_threshold to production value
  - Re-enable trading: kill_switch_cli disable --reason "V1 exercise: auto-trigger test complete"
  - Verify auto-resume: trading_state='active', no pending halts

STEP 8: Produce evidence document
  - Write timestamped Markdown to reports/validation/kill_switch_exercise/
  - Capture: all timestamps, latencies, DB state before/after, Telegram receipts
```

**Evidence document structure:**
```markdown
# Kill Switch Exercise: YYYY-MM-DD

## Summary
- Exercise type: Manual + Automatic (daily loss stop)
- Date: YYYY-MM-DD
- Operator: [name]
- Outcome: PASS / FAIL

## Manual Trigger Evidence
| Step | Timestamp | Result |
|------|-----------|--------|
| Pre-state captured | HH:MM:SS.ms | trading_state='active' |
| CLI activate executed | HH:MM:SS.ms | exit_code=0 |
| State confirmed halted | HH:MM:SS.ms | halted_reason verified |
| Orders cancelled | HH:MM:SS.ms | N cancelled orders |
| cmc_risk_events row | HH:MM:SS.ms | event_id=... |
| Telegram alert | HH:MM:SS.ms | text='...' (Y/N received) |
| CLI disable executed | HH:MM:SS.ms | trading re-enabled |

**Manual trigger latency (trigger -> halted state confirmed): Xms**
**Target: < 5 seconds | Actual: Xms | Status: PASS/FAIL**

## Automatic Trigger Evidence (Daily Loss Stop)
[Same table structure]

**Automatic trigger latency: Xms**

## Threshold Restoration Evidence
- Original threshold: X%
- Test threshold: 0.1%
- Restored at: HH:MM:SS
- Confirmed via: SELECT daily_loss_pct_threshold FROM dim_risk_limits

## VAL-04 Gate Assessment
- Manual trigger: PASS (tested and documented)
- Automatic trigger: PASS (tested and documented)
- Recovery: PASS (auto-resume via re-enable after cooldown)
- Overall VAL-04: PASS
```

**Key constraint from CONTEXT.md:** Engineer the auto-trigger test EARLY in the 14-day period (Day 1-2), then restore real thresholds. The 14-day clock keeps running through the test.

**Important:** The current `kill_switch.py` `re_enable_trading()` function requires operator + reason and is explicitly "NEVER automatic." The CONTEXT.md says "auto-resume after configurable cooldown." This means the kill switch exercise tests the MANUAL re-enable path, while the "auto-resume" concept from CONTEXT.md likely applies to the drift pause (which does have cooldown logic in Phase 47), not the kill switch itself. Clarify in planning: for the kill switch, re-enable is manual; for drift pause, auto-resume is possible. Do not try to add auto-resume to the kill switch.

### Pattern 4: Audit/Gap Detection Script

**What:** A script that queries all relevant tables for a date range and identifies: missing executor run days, orphaned orders (created/submitted with no fill), zero-fill days (pipeline ran but no fills for N consecutive days when positions exist), stale data (latest bar ts > N hours old), executor error runs.

**Gap detection queries:**
```python
# Source: designed from codebase schemas (cmc_executor_run_log, cmc_orders, cmc_fills)

AUDIT_QUERIES = {
    # 1. Missing executor run days
    "missing_run_days": """
        WITH all_days AS (
            SELECT generate_series(
                :start_date::date,
                :end_date::date,
                '1 day'::interval
            )::date AS run_date
        )
        SELECT d.run_date
        FROM all_days d
        LEFT JOIN (
            SELECT started_at::date AS run_date, COUNT(*) AS run_count
            FROM cmc_executor_run_log
            WHERE status IN ('success', 'no_signals')
            GROUP BY 1
        ) r ON d.run_date = r.run_date
        WHERE r.run_date IS NULL
        ORDER BY d.run_date
    """,

    # 2. Executor error runs (failed or stale_signal)
    "error_runs": """
        SELECT run_id, started_at, status, error_message, config_ids
        FROM cmc_executor_run_log
        WHERE status IN ('failed', 'stale_signal')
          AND started_at::date BETWEEN :start_date AND :end_date
        ORDER BY started_at DESC
    """,

    # 3. Orphaned orders (never filled, not cancelled -- stuck in submitted state)
    "orphaned_orders": """
        SELECT o.order_id, o.asset_id, o.created_at, o.status, o.quantity, o.side
        FROM cmc_orders o
        WHERE o.status IN ('created', 'submitted')
          AND o.created_at < now() - interval '2 days'
          AND NOT EXISTS (
              SELECT 1 FROM cmc_fills f WHERE f.order_id = o.order_id
          )
        ORDER BY o.created_at
    """,

    # 4. Position/fill consistency: positions with no corresponding fill history
    "position_without_fills": """
        SELECT p.asset_id, p.strategy_id, p.quantity, p.avg_entry_price
        FROM cmc_positions p
        WHERE p.quantity != 0
          AND NOT EXISTS (
              SELECT 1 FROM cmc_fills f
              JOIN cmc_orders o ON f.order_id = o.order_id
              WHERE o.asset_id = p.asset_id
          )
    """,

    # 5. Stale bars (latest price bar older than 28 hours for 1D strategy)
    "stale_price_data": """
        SELECT id, MAX(ts) AS latest_bar_ts,
               EXTRACT(EPOCH FROM (now() - MAX(ts))) / 3600 AS hours_stale
        FROM cmc_price_bars_multi_tf
        WHERE tf = '1D'
        GROUP BY id
        HAVING MAX(ts) < now() - interval '28 hours'
    """,

    # 6. Drift metrics gaps (executor ran but no drift metrics for that day)
    "drift_gaps": """
        WITH exec_days AS (
            SELECT DISTINCT started_at::date AS run_date
            FROM cmc_executor_run_log
            WHERE status = 'success'
              AND started_at::date BETWEEN :start_date AND :end_date
        )
        SELECT e.run_date
        FROM exec_days e
        LEFT JOIN cmc_drift_metrics dm ON dm.metric_date = e.run_date
        WHERE dm.metric_date IS NULL
        ORDER BY e.run_date
    """,
}
```

**Output: anomaly-flagged log:**
```markdown
# Audit Report: YYYY-MM-DD (covering YYYY-MM-DD to YYYY-MM-DD)

## Summary
| Check | Status | Count |
|-------|--------|-------|
| Missing executor run days | PASS/FAIL | 0/N |
| Error runs | PASS/FAIL | 0/N |
| Orphaned orders | PASS/FAIL | 0/N |
| Position/fill consistency | PASS/FAIL | 0/N |
| Stale price data | PASS/FAIL | 0/N |
| Drift metric gaps | PASS/FAIL | 0/N |

**Overall VAL-05 status:** PASS (all checks pass) / FAIL (N anomalies require human review)

## Anomalies for Human Review
[Each anomaly flagged with date, type, affected records, and space for human sign-off]

## Sign-Off
[ ] All anomalies reviewed and explained
Operator: ___________  Date: ___________
```

### Pattern 5: End-of-Period Validation Report

**What:** A comprehensive Markdown + Plotly HTML report generated at the end of 14 days. Structure follows Phase 42 bakeoff scorecard and Phase 47 drift report conventions.

**Chart inventory (all Plotly HTML via `write_html`, with PNG fallback via kaleido):**

1. **Equity curve overlay** — Paper P&L vs backtest replay P&L over 14 days. One panel per strategy. Source: `cmc_fills` + `cmc_drift_metrics.replay_pit_cumulative_pnl`. Pattern: `drift_report.py _plot_equity_overlay()`.

2. **Drawdown chart** — Rolling drawdown from paper start. Computed from daily P&L series from fills. Source: `cmc_fills` aggregated by day. New chart, but uses same Plotly `go.Scatter` pattern.

3. **Tracking error time series** — 5d and 30d rolling TE over the period. Source: `cmc_drift_metrics`. Pattern: `drift_report.py _plot_tracking_error()`.

4. **Slippage distribution** — Histogram of fill-price slippage (bps) vs mid-price. Source: `cmc_fills` joined to price bars at fill time. New chart.

5. **Kill switch event timeline** — Bar chart or Gantt showing kill switch exercise events with timestamps. Source: `cmc_risk_events`. New chart.

**Report section structure:**
```markdown
# V1 Validation Report
**Period:** [start] to [end]  **Generated:** [timestamp]

## Executive Summary
[2-3 sentence summary of whether V1 gates pass]

## Gate Assessment
| Gate | Criterion | Threshold | Measured | Status | Notes |
|------|-----------|-----------|----------|--------|-------|

## VAL-01: Paper Trading Duration
...
## VAL-02: Tracking Error
...
## VAL-03: Slippage
...
## VAL-04: Kill Switch
...
## VAL-05: Log Audit
...
## Backtest Gates (from Phase 42)
...
## Operational Metrics
...
## Charts
...
## Methodology
...
## Appendix: Data Sources
```

### Pattern 6: Pre-Validation Go/No-Go Script

**What:** A checklist script run BEFORE starting the 14-day clock. Queries 12+ conditions and prints PASS/FAIL for each. Must all pass before starting.

**Checks:**
```python
PREFLIGHT_CHECKS = [
    # Infrastructure
    ("DB connectivity", "SELECT 1"),
    ("dim_executor_config has active rows", "SELECT COUNT(*) FROM dim_executor_config WHERE is_active=TRUE"),
    ("Both EMA configs active", "SELECT COUNT(*) FROM dim_executor_config WHERE is_active=TRUE AND signal_type='ema_crossover'"),
    ("dim_risk_state row exists", "SELECT COUNT(*) FROM dim_risk_state WHERE state_id=1"),
    ("trading_state is active", "SELECT trading_state FROM dim_risk_state WHERE state_id=1"),
    ("drift_paused is false", "SELECT drift_paused FROM dim_risk_state WHERE state_id=1"),
    ("dim_risk_limits row exists", "SELECT COUNT(*) FROM dim_risk_limits WHERE asset_id IS NULL"),
    ("daily_loss_pct_threshold set", "SELECT daily_loss_pct_threshold FROM dim_risk_limits WHERE asset_id IS NULL"),
    # Signal freshness
    ("BTC price bars current (< 30 hours)", "SELECT MAX(ts) FROM cmc_price_bars_multi_tf WHERE id=1 AND tf='1D'"),
    ("cmc_features current", "SELECT MAX(ts) FROM cmc_features WHERE id=1 AND tf='1D'"),
    ("EMA data current", "SELECT MAX(ts) FROM cmc_ema_multi_tf_u WHERE id=1 AND tf='1D'"),
    # Operational tables empty/healthy
    ("No orphaned orders", "SELECT COUNT(*) FROM cmc_orders WHERE status IN ('created','submitted')"),
    ("Executor run log accessible", "SELECT COUNT(*) FROM cmc_executor_run_log LIMIT 1"),
    ("cmc_drift_metrics accessible", "SELECT 1 FROM cmc_drift_metrics LIMIT 0"),
    # Telegram
    ("Telegram alerts configured", "[test send_test_alert()]"),
]
```

**Output format:**
```
============================================================
V1 VALIDATION PRE-FLIGHT CHECKLIST
============================================================
  [PASS] DB connectivity
  [PASS] Both EMA configs active (2 found)
  [PASS] trading_state is active
  [FAIL] cmc_features current (latest: 2026-02-22, expected: within 30 hours)
  [PASS] No orphaned orders (0 found)
  ...
============================================================
Result: 1 FAIL(s) -- HOLD: resolve before starting 14-day clock
============================================================
```

### Anti-Patterns to Avoid

- **Don't start the clock before pre-flight passes.** The 14-day clock should start on the first day the executor runs successfully with all checks green.
- **Don't regenerate signals between kills switch exercise steps.** The exercise must not re-run signal refresh mid-test — only the kill switch mechanism is being tested.
- **Don't report slippage as 0 bps if fill simulator uses `slippage_mode='zero'`.** The slippage measurement for VAL-03 must use the lognormal fill simulator (non-zero slippage mode). Verify `dim_executor_config.slippage_mode` before reporting.
- **Don't generate the end-of-period report before audit is signed off.** The report includes the VAL-05 result, which requires human sign-off on each flagged exception.
- **Don't aggregate slippage across buys and sells without separating direction.** Buy slippage and sell slippage have opposite signs. Report them separately and as absolute values.
- **Don't assume Jupyter is installed.** Use `nbformat` to generate the `.ipynb` file programmatically; the notebook is for future readers to re-run, not for CI execution.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Kill switch activation | Custom state flip | `activate_kill_switch()` from `ta_lab2.risk.kill_switch` | Already atomic: state + cancel + audit event in one transaction |
| Kill switch re-enable | Custom enable | `re_enable_trading()` from `ta_lab2.risk.kill_switch` | Requires operator + reason; already validates not-double-enable |
| Equity curve chart | Custom trace builder | `drift_report._plot_equity_overlay()` pattern | Already handles multi-config, missing data, dates |
| Tracking error chart | Custom plot | `drift_report._plot_tracking_error()` pattern | Already handles threshold line, 5d+30d series, missing NaNs |
| Markdown table formatting | String concatenation | `_df_to_markdown()` from `drift_report.py` or `_format_table()` from `generate_bakeoff_scorecard.py` | Both exist, tested, handle NaN |
| Chart file saving | Custom file write | `_save_chart()` from `generate_bakeoff_scorecard.py` | PNG via kaleido + HTML fallback, relative path return |
| DB engine creation | Custom create_engine | `_get_engine()` + `NullPool` pattern | NullPool is project convention for subprocess workers |
| Report output path | Ad hoc | `reports/validation/` — follow `reports/bakeoff/` convention | Consistent with .gitignore, project structure |
| P&L by day aggregation | Custom loop | `pd.read_sql()` with GROUP BY fill date | Vectorized, handles timezone normalization |
| Slippage bps | Formula from scratch | `(fill_price - mid_price) / mid_price * 10000` where mid = open price from bars | Mid price = bar open at fill time (paper trading fills at next-bar-open) |

**Key insight:** Phase 53 is assembly work. All the data, all the DB functions, all the chart patterns already exist. The value-add is connecting them into validation-specific outputs with gate-scoring logic on top.

---

## Common Pitfalls

### Pitfall 1: Kill Switch Test Corrupts Validation Metrics

**What goes wrong:** The kill switch exercise (Step 5 — auto-trigger via lowered threshold) triggers the risk engine and may be counted as a "daily loss stop" event in the validation metrics. The test creates `cmc_risk_events` rows that look identical to real risk events.

**Why it happens:** The risk engine uses the same `activate_kill_switch()` function for both real and test triggers. The exercise produces real DB records.

**How to avoid:** Tag exercise events with a distinct operator and reason: `--reason "V1 EXERCISE: auto-trigger test"`. In the gate assessment, filter `cmc_risk_events` to exclude rows where `reason LIKE '%V1 EXERCISE%'` when counting real risk events for VAL-04. Keep exercise events in the audit trail — they are valid evidence, just not "real" incidents.

**Warning signs:** VAL-04 shows 2 kill switch activations when only 1 real activation occurred.

### Pitfall 2: Slippage Report Shows 0 bps Because Simulator is in Zero Mode

**What goes wrong:** VAL-03 reports slippage of 0 bps for all fills. Auditor concludes target met without realizing the fill simulator is configured with `slippage_mode='zero'` in `dim_executor_config`.

**Why it happens:** Paper trading started with `slippage_mode='zero'` (correct for parity testing), but the validation report doesn't check whether slippage was simulated realistically.

**How to avoid:** Pre-flight check must verify `slippage_mode != 'zero'` for production-mode paper trading. If zero mode is found, flag in pre-flight as WARN (not FAIL, since zero mode is fine for parity but means VAL-03 won't measure real slippage). In the report, document: "Slippage measurement requires lognormal or fixed mode in dim_executor_config."

**Warning signs:** All fill prices exactly equal the bar open price.

### Pitfall 3: Tracking Error Shows NULL for Entire 14-Day Period

**What goes wrong:** `cmc_drift_metrics.tracking_error_5d` is NULL for all 14 days. The VAL-02 assessment defaults to "N/A."

**Why it happens:** With 1D EMA strategies at ~3-4 trades/year, paper trading 14 days produces 0-1 fills total. The drift monitor's tracking error computation requires `min_periods=window` (5 days) with actual fills. If 0 fills occur, tracking error is NULL per the pitfall-avoidance design in Phase 47 (`tracking_error_5d = NULL` when insufficient trading days).

**How to avoid:** VAL-02 gate assessment must state: "With ~3 trades/year, 14-day tracking error may be NULL if no fills occurred. NULL is not a failure for sparse strategies." Gate logic: if `tracking_error_5d IS NULL` for ALL days and `paper_trade_count = 0`, report as "INSUFFICIENT DATA — strategies did not generate fills during this period" and assess VAL-02 as CONDITIONAL (not FAIL), since no drift can be measured without fills.

**Warning signs:** VAL-02 shows "target: < 1%, measured: N/A, status: FAIL" — this is incorrect; should be CONDITIONAL.

### Pitfall 4: Re-Enable After Kill Switch Exercise Requires Manual Intervention

**What goes wrong:** The kill switch exercise triggers auto-stop. The script then tries to auto-resume, but `re_enable_trading()` requires explicit `operator` and `reason` parameters and refuses automatic re-enable. The exercise script hangs waiting for input.

**Why it happens:** Phase 46 kill switch was designed to be "NEVER automatic" for re-enable. The CONTEXT.md says "auto-resume after cooldown" but this applies to drift pause (Phase 47 `drift_paused` flag), not the kill switch itself.

**How to avoid:** The kill switch exercise script must pause after triggering the auto-stop and prompt the operator: "Kill switch activated. Verify effects, then press ENTER to re-enable." Re-enable is a manual operator action, documented with timestamp. The "auto-resume after cooldown" phrase in CONTEXT.md is about drift pause; document this distinction clearly in the exercise protocol.

**Warning signs:** Exercise script errors with `ValueError: operator must be a non-empty string`.

### Pitfall 5: cmc_risk_events CHECK Constraint Blocks Exercise Event Type

**What goes wrong:** The kill switch exercise writes a new event_type (e.g., `kill_switch_exercise_start`) to `cmc_risk_events` and gets `ERROR: violates check constraint "chk_risk_events_type"`.

**Why it happens:** `cmc_risk_events` has a strict CHECK constraint on valid event types. Phase 47 already extended it (drift events). If any new exercise event types are needed, the constraint must be extended again.

**How to avoid:** Do NOT add new event types. Use existing `kill_switch_activated` / `kill_switch_disabled` event types with distinguishing reason strings containing "V1 EXERCISE". This avoids any migration.

### Pitfall 6: Windows Encoding Error When Writing Markdown Reports

**What goes wrong:** `open(report_path, "w")` fails with `UnicodeEncodeError` on Windows if the report contains any non-ASCII characters (em dashes, ellipsis, box-drawing chars).

**Why it happens:** Per MEMORY.md: Windows uses cp1252 as default encoding. The bakeoff scorecard and drift report already use `encoding="utf-8"` on all file writes.

**How to avoid:** ALL file writes in Phase 53 scripts must use `open(path, "w", encoding="utf-8")`. Never use default encoding. This is consistent with existing Phase 42 and Phase 47 code.

### Pitfall 7: Jupyter Notebook Not Installed

**What goes wrong:** `generate_validation_report.py` tries to `import jupyter` and fails because jupyter is not in the project environment.

**How to avoid:** Use `nbformat` only for notebook generation (creating the `.ipynb` file). `nbformat` doesn't require a Jupyter server. The notebook file is a JSON document; `nbformat` writes it directly without any Jupyter installation needed. Only `nbformat` needs to be installed. Verify: `python -c "import nbformat"`.

---

## Code Examples

### Gate Assessment - Full V1 Scorecard

```python
# Source: pattern from generate_bakeoff_scorecard.py _section_strategy_selection()
# This is how the Phase 42 scorecard handles the MaxDD gate failure -- same pattern here.

def build_gate_scorecard(engine) -> list[GateResult]:
    """Build the full V1 gate assessment from DB evidence."""

    # VAL-01: Duration (14 calendar days with both strategies active)
    run_days = query_distinct_executor_run_days(engine)
    val01 = GateResult(
        gate_id="VAL-01",
        gate_name="Paper Trading Duration",
        threshold="14 calendar days, both strategies active from day 1",
        measured_value=f"{len(run_days)} days ({min(run_days)} to {max(run_days)})",
        status=GateStatus.PASS if len(run_days) >= 14 else GateStatus.FAIL,
        evidence_sources=["cmc_executor_run_log"],
    )

    # VAL-02: Tracking Error (< 1% 5d rolling, or CONDITIONAL if no fills)
    max_te = query_max_tracking_error_5d(engine)  # From cmc_drift_metrics
    if max_te is None:
        val02 = GateResult(
            gate_id="VAL-02", gate_name="Tracking Error",
            threshold="< 1% (5-day rolling TE vs backtest)",
            measured_value="NULL -- no fills during period, TE cannot be computed",
            status=GateStatus.CONDITIONAL,
            evidence_sources=["cmc_drift_metrics"],
            mitigation="Sparse strategy (< 1 trade/month): 14-day window insufficient. Extend monitoring.",
        )
    else:
        val02 = GateResult(
            gate_id="VAL-02", gate_name="Tracking Error",
            threshold="< 1%",
            measured_value=f"{max_te:.2%} (max 5d rolling TE)",
            status=GateStatus.PASS if max_te < 0.01 else GateStatus.FAIL,
            evidence_sources=["cmc_drift_metrics"],
        )

    # VAL-03: Slippage (< 50 bps)
    mean_slippage_bps, n_fills = query_mean_slippage_bps(engine)
    if n_fills == 0:
        val03 = GateResult(
            gate_id="VAL-03", gate_name="Slippage",
            threshold="< 50 bps",
            measured_value="No fills -- slippage cannot be measured",
            status=GateStatus.CONDITIONAL,
            evidence_sources=["cmc_fills"],
            mitigation="No fills in 14-day period. Fill simulator config documented in dim_executor_config.",
        )
    else:
        val03 = GateResult(
            gate_id="VAL-03", gate_name="Slippage",
            threshold="< 50 bps",
            measured_value=f"{mean_slippage_bps:.1f} bps (mean, N={n_fills} fills)",
            status=GateStatus.PASS if mean_slippage_bps < 50 else GateStatus.FAIL,
            evidence_sources=["cmc_fills", "cmc_orders"],
        )

    # VAL-04: Kill Switch (tested manually + automatically)
    ks_events = query_kill_switch_events(engine)  # From cmc_risk_events
    has_manual = any(e["trigger_source"] == "manual" for e in ks_events)
    has_auto = any(e["trigger_source"] == "daily_loss_stop" for e in ks_events)
    val04 = GateResult(
        gate_id="VAL-04", gate_name="Kill Switch",
        threshold="Triggered manually AND automatically (daily loss stop)",
        measured_value=f"Manual: {'YES' if has_manual else 'NO'} | Auto: {'YES' if has_auto else 'NO'}",
        status=GateStatus.PASS if has_manual and has_auto else GateStatus.FAIL,
        evidence_sources=["cmc_risk_events", "reports/validation/kill_switch_exercise/"],
    )

    # VAL-05: Log Audit
    audit_result = run_full_audit(engine)
    val05 = GateResult(
        gate_id="VAL-05", gate_name="Log Audit",
        threshold="No unexplained gaps, no silent failures, full order/fill audit trail",
        measured_value=f"{audit_result.n_anomalies} anomalies ({audit_result.n_signed_off} signed off)",
        status=GateStatus.PASS if audit_result.all_signed_off else GateStatus.FAIL,
        evidence_sources=["cmc_executor_run_log", "cmc_orders", "cmc_fills", "reports/validation/audit/"],
    )

    return [val01, val02, val03, val04, val05]
```

### Slippage Measurement Query

```python
# Source: derived from cmc_fills + cmc_price_bars_multi_tf schema
# For paper trading: fill price vs open price of the bar at which fill occurs
# Open price = the price used as reference for next-bar-open fills

def query_mean_slippage_bps(engine) -> tuple[float, int]:
    """
    Compute mean absolute slippage in basis points across all fills.

    For paper trading fills:
      - Fill price = from cmc_fills.fill_price
      - Reference price = cmc_price_bars_multi_tf.open for the bar at fill time
      - Slippage bps = abs(fill_price - open_price) / open_price * 10000

    Returns (mean_slippage_bps, n_fills). Returns (0.0, 0) if no fills.
    """
    sql = """
        SELECT
            f.fill_id,
            f.fill_price,
            f.side,
            pb.open AS bar_open_price,
            ABS(f.fill_price::float - pb.open::float) / pb.open::float * 10000 AS slip_bps
        FROM cmc_fills f
        JOIN cmc_orders o ON f.order_id = o.order_id
        JOIN cmc_price_bars_multi_tf pb
            ON pb.id = o.asset_id
            AND pb.tf = '1D'
            AND pb.ts::date = f.filled_at::date
        WHERE f.filled_at::date BETWEEN :start_date AND :end_date
    """
    # ... execute query and compute mean
```

### Jupyter Notebook Generation via nbformat

```python
# Source: nbformat official API (no Jupyter server required, no Context7 entry for nbformat)
# Generate a .ipynb file that readers can open and re-run

import nbformat

def build_validation_notebook(
    engine,
    start_date: str,
    end_date: str,
    output_path: str,
) -> str:
    """
    Generate a Jupyter notebook for the V1 validation report.

    The notebook contains executable cells that re-query the DB and
    re-generate all charts. It is self-contained for future verification.
    """
    nb = nbformat.v4.new_notebook()

    # Cell 1: Setup
    nb.cells.append(nbformat.v4.new_code_cell(
        source=f"""
# V1 Validation Report Notebook
# Period: {start_date} to {end_date}
# Run all cells to regenerate findings from DB

from sqlalchemy import create_engine
from ta_lab2.db.config import resolve_db_url
import pandas as pd, plotly.graph_objects as go

db_url = resolve_db_url()
engine = create_engine(db_url)
print(f"Connected: {{db_url[:30]}}...")
START = '{start_date}'
END = '{end_date}'
"""
    ))

    # Cell 2: Gate assessment table
    nb.cells.append(nbformat.v4.new_markdown_cell(
        source="## V1 Gate Assessment\nRunning gate framework..."
    ))
    nb.cells.append(nbformat.v4.new_code_cell(
        source="""
from ta_lab2.validation.gate_framework import build_gate_scorecard
import pandas as pd

gates = build_gate_scorecard(engine)
gate_df = pd.DataFrame([{
    'Gate': g.gate_id,
    'Name': g.gate_name,
    'Threshold': g.threshold,
    'Measured': g.measured_value,
    'Status': g.status.value,
} for g in gates])
gate_df.style.applymap(lambda v: 'color: green' if v == 'PASS' else 'color: red' if v == 'FAIL' else 'color: orange')
"""
    ))

    # Additional cells for equity curve, slippage distribution, etc.
    # ... (same pattern per chart)

    # Write notebook file
    with open(output_path, "w", encoding="utf-8") as f:
        nbformat.write(nb, f)

    return output_path
```

### Daily Log Slippage Computation (Inline)

```python
# Source: standard formula, applied to cmc_fills data

def compute_fill_slippage_bps(fill_price: float, reference_price: float, side: str) -> float:
    """
    Compute signed slippage in bps.

    For buys: positive slippage = fill above reference (unfavorable)
    For sells: negative slippage = fill below reference (unfavorable)

    Absolute value for comparison against < 50 bps threshold.
    """
    raw = (fill_price - reference_price) / reference_price * 10000
    # Unfavorable slippage is always positive in our reporting
    if side == "buy":
        return raw   # positive = worse for buyer
    else:
        return -raw  # negative fill_price delta = worse for seller
```

---

## Gate Assessment Framework

### V1 Success Criteria Scoring Matrix

| Gate | ID | Threshold | Expected Outcome | Status Logic |
|------|----|-----------|------------------|--------------|
| Backtest Sharpe | BT-01 | >= 1.0 OOS | PASS (1.40 > 1.0) | PASS (pre-computed from Phase 42) |
| Backtest MaxDD | BT-02 | <= 15% worst fold | CONDITIONAL | Known failure; mitigation documented and tested |
| Paper Duration | VAL-01 | 14 calendar days | PASS if 14 days run | Measure from cmc_executor_run_log |
| Tracking Error | VAL-02 | < 1% 5d rolling TE | CONDITIONAL if no fills; PASS/FAIL if fills | From cmc_drift_metrics |
| Slippage | VAL-03 | < 50 bps mean | CONDITIONAL if no fills; PASS/FAIL if fills | From cmc_fills |
| Kill Switch | VAL-04 | Manual + auto tested | PASS only if both tested with DB evidence | From cmc_risk_events + exercise doc |
| Log Audit | VAL-05 | No unexplained gaps | PASS only if all anomalies signed off | From audit script + human sign-off |

**Overall V1 result:** Report all gate statuses. V1 is considered viable for Phase 54 (Results Memo) if: all PASS gates pass, CONDITIONAL gates have documented mitigations, and no unexpected FAIL gates.

---

## State of the Art

| Old Approach | Current Approach | Notes |
|--------------|------------------|-------|
| Manual equity curve comparison (monthly) | Automated daily drift metrics via DriftMonitor | Phase 47 already provides this |
| Binary PASS/FAIL on backtest gates | PASS/CONDITIONAL/FAIL with mitigation documentation | Matches quant fund risk committee practice |
| Jupyter notebooks for all reporting | Markdown + Plotly HTML as primary, notebook as reproducibility artifact | Markdown is immediately readable without runtime |
| Kill switch test: wait for real market event | Engineered test scenario (lower threshold, document, restore) | PRA SS5/18 recommends periodic testing |
| ad hoc log review at end of period | Automated daily anomaly detection + human exception review | VAL-05 requirement |

**Deprecated/outdated for this phase:**
- Using `--replay-historical` on paper executor to "replay" fills for validation: Not needed. The drift monitor already runs parallel replay backtests. Don't double-count.
- Generating static PNG charts only: Phase 42 uses PNG via kaleido + HTML fallback. Phase 47 uses HTML only. For Phase 53, use HTML as primary (interactive for notebook readers), with PNG for the Markdown embedded previews if kaleido is available.

---

## Open Questions

1. **Kill switch auto-resume vs manual re-enable**
   - What we know: `re_enable_trading()` in `kill_switch.py` is explicitly manual-only. The CONTEXT.md says "auto-resume after configurable cooldown."
   - What's unclear: Does CONTEXT.md's "auto-resume" refer to the drift pause (Phase 47) or the kill switch (Phase 46)?
   - Recommendation: Treat kill switch re-enable as manual for Phase 53. The "auto-resume" in CONTEXT.md almost certainly refers to the drift pause (which was designed with a cooldown). Confirm with context owner before implementing; do NOT add auto-resume to kill switch without explicit decision.

2. **Slippage mode configuration for production paper trading**
   - What we know: `dim_executor_config.slippage_mode` controls fill simulation. `'zero'` mode = exact fills = 0 bps slippage. VAL-03 requires < 50 bps measurement.
   - What's unclear: What slippage mode were the EMA configs deployed with? If `'zero'`, VAL-03 will be CONDITIONAL (no realistic slippage to measure).
   - Recommendation: Pre-flight check must verify `slippage_mode != 'zero'`. If zero mode, VAL-03 is CONDITIONAL with note: "Paper trading uses zero-slippage simulation for reproducibility; realistic slippage is in the fill simulator config but not applied in this period."

3. **Tracking error when no fills occur in 14 days**
   - What we know: EMA strategies generate ~3-4 trades/year = 0-1 fills in 14 days. Drift monitor returns NULL TE when `paper_trade_count < min_periods`.
   - Recommendation: VAL-02 gate should check for this case explicitly and report CONDITIONAL rather than FAIL when TE is NULL due to no fills. Include note: "For sparse trend-following strategies, 14-day tracking error is insufficient; extend monitoring window to 30-60 days for meaningful TE measurement."

4. **go/no-go burn-in (CONTEXT.md Claude's Discretion)**
   - What we know: CONTEXT.md leaves it to research to recommend whether to include a formal burn-in before starting the 14-day clock.
   - Recommendation: Do NOT add a formal burn-in period. The pre-flight checklist script IS the burn-in. If all 12+ checks pass, start the clock. If checks fail, fix them and re-run pre-flight. The clock starts when pre-flight passes. This is cleaner than a separate "burn-in period" that adds ambiguity about when the real clock starts.

---

## Sources

### Primary (HIGH confidence)
- Project codebase: `src/ta_lab2/risk/kill_switch.py` — `activate_kill_switch()`, `re_enable_trading()`, exact signature and contract
- Project codebase: `src/ta_lab2/drift/drift_report.py` — `ReportGenerator`: equity overlay chart, tracking error chart, attribution waterfall, Markdown rendering pattern
- Project codebase: `src/ta_lab2/scripts/analysis/generate_bakeoff_scorecard.py` — `build_scorecard()`: full Plotly HTML report generation pattern, `_save_chart()`, `_format_table()`, `_embed_chart()`
- Project codebase: `src/ta_lab2/executor/paper_executor.py` — `PaperExecutor`: run log writing pattern, executor flow
- Project codebase: `src/ta_lab2/executor/parity_checker.py` — `ParityChecker`: slippage measurement formula, parity check output structure
- Project codebase: `sql/risk/091_dim_risk_state.sql` — confirmed schema: no `drift_paused` in base DDL (added by Phase 47 migration)
- Project codebase: `sql/risk/092_cmc_risk_events.sql` — confirmed CHECK constraint on event_type; valid trigger_source values
- Project codebase: `sql/executor/089_cmc_executor_run_log.sql` — confirmed columns: no data_snapshot in base (added by Phase 47 migration)
- Project codebase: `reports/bakeoff/BAKEOFF_SCORECARD.md` — confirmed fold-level MaxDD data for both strategies; V1 gate assessment pattern
- Project codebase: `.planning/phases/47-drift-guard/47-RESEARCH.md` — drift metrics schema, tracking error formula, pitfall registry
- Project codebase: `.planning/phases/52-operational-dashboard/52-RESEARCH.md` — dashboard patterns, Streamlit 1.44.0 features

### Secondary (MEDIUM confidence)
- QuantConnect reconciliation docs (https://www.quantconnect.com/docs/v2/cloud-platform/live-trading/reconciliation) — OOS parallel backtest approach, four divergence categories (data, modeling, brokerage, implementation), no explicit pass/fail thresholds
- PRA Supervisory Statement SS5/18 on Algorithmic Trading — kill switch testing requirement: "periodic assessment of kill-switch controls to ensure they operate as intended, including assessment of the speed at which the procedure can be affected"
- FIA Automated Trading Risk Controls whitepaper (2024) — referenced but PDF not parseable; general best practice for pre-trade controls

### Tertiary (LOW confidence)
- WebSearch: "quant fund PASS CONDITIONAL FAIL validation gate framework" — no published standard using this exact terminology found; framework is reasoned from general risk management practice
- WebSearch: "kill switch latency < 5 seconds benchmark" — no specific benchmark found for paper trading systems; <5 seconds is CONTEXT.md's specification, not an industry standard
- WebSearch: "paper trading daily validation log content" — no standard format found; structure derived from Phase 47 drift reports and Phase 42 scorecard patterns

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new dependencies beyond nbformat/jupyter for notebook generation; all other libraries confirmed present
- Architecture patterns: HIGH — all patterns derived directly from existing project code (Phase 42, 47); no speculative patterns
- Gate framework (PASS/CONDITIONAL/FAIL): MEDIUM — logical derivation from project needs + general risk management practice; no published standard uses this exact 3-tier terminology
- Kill switch exercise protocol: HIGH — derived directly from existing kill_switch.py API; all DB tables confirmed
- Audit queries: HIGH — all tables confirmed (cmc_executor_run_log, cmc_orders, cmc_fills, cmc_drift_metrics); queries are standard SQL
- Jupyter notebook generation: MEDIUM — nbformat API is stable but not verified via Context7 (no Context7 entry); pattern is well-known
- MaxDD CONDITIONAL recommendation: MEDIUM — consistent with Phase 42 scorecard approach and general risk management practice; specific "CONDITIONAL" framing is this project's convention

**Research date:** 2026-02-25
**Valid until:** 2026-03-25 (30 days; domain is stable — new dependencies for Jupyter are the main thing to verify before planning)
