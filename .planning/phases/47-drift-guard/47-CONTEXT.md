# Phase 47: Drift Guard - Context

**Gathered:** 2026-02-25
**Status:** Ready for planning

<domain>
## Phase Boundary

Parallel backtest replay system that continuously compares paper trading execution against backtester predictions, computes drift metrics, triggers auto-pause on divergence, and generates attribution reports. Runs daily as part of the executor pipeline. Does NOT include the kill switch itself (Phase 46), risk limits (Phase 48), or the operational dashboard (Phase 52).

**Requirements:** DRIFT-01, DRIFT-02, DRIFT-03, DRIFT-04

**Upstream dependencies locked:**
- Phase 45: PaperExecutor, FillSimulator, SignalReader, PositionSizer, ParityChecker, ExecutorConfig, cmc_executor_run_log
- Phase 46: RiskEngine, KillSwitch, cmc_risk_events table, dim_risk_limits, dim_risk_state
- Phase 44: OrderManager, cmc_orders/cmc_fills/cmc_positions tables
- Phase 28: Backtest pipeline (run_backtest, cmc_backtest_runs/trades/metrics)
- Phase 29: Telegram alerting infrastructure (AlertSeverity, send_critical_alert)

</domain>

<decisions>
## Implementation Decisions

### Backtest replay data window
- **Both layers**: Point-in-time replay (using data available at paper execution time) AND current/latest data replay. The gap between them quantifies data revision drift as an attribution dimension
- **Point-in-time tracking via snapshot**: At each executor run, snapshot what data was visible (latest bar ts per asset, feature state). Stored in cmc_executor_run_log or a dedicated snapshot structure. More reliable than ingested_at watermarks
- **Cumulative from start**: Each daily replay re-runs from paper trading day 1 through today. Growing window ensures no drift accumulation is missed
- **Daily cadence**: Full cumulative replay runs after each executor cycle. At 1D cadence with 2 assets x 2 strategies, this adds ~1-5 minutes — trivially fast

### Comparison methodology
- **Per-signal fill matching + daily/cumulative P&L**: Two comparison layers. Per-signal for diagnosis (which trade diverged), daily P&L for trend monitoring (is overall drift growing)
- **Force same price mode**: Backtest replay uses the same fill_price_mode as paper executor. Isolates execution differences from price source differences
- **Signal matching strategy**: Researcher should investigate best practices for signal-to-trade matching in parallel execution systems. May use 1:1 strict, time-window, or position-state matching — or a combination. Defer to research
- **Metrics scope**: Per-strategy AND portfolio-level. Each strategy gets independent tracking error, Sharpe divergence, P&L diff. Plus aggregate portfolio drift for total exposure monitoring

### Auto-pause response behavior
- **Kill switch vs separate pause**: Researcher should investigate best practices for graduated vs unified response. Phase 46's kill switch may be the right mechanism, or a softer drift-specific pause may be appropriate. Defer to research
- **Manual resume only**: After drift triggers pause, human must investigate, diagnose cause, and explicitly re-enable. No auto-resume. Drift means something is wrong
- **Telegram + log alerting**: Drift warnings (approaching threshold) via WARNING severity, trigger events via CRITICAL severity. All events logged to cmc_risk_events for audit trail
- **DB table + materialized view**: Raw drift metrics in a new table (e.g., cmc_drift_metrics). Materialized view for aggregated trends. Enables Phase 52 dashboard integration and historical analysis

### Attribution granularity
- **6 drift sources tracked**: Slippage delta (paper vs backtest fill price), fee model delta, signal timing (execution delay effects), data revision (point-in-time vs current gap), position sizing drift (rounding, portfolio value changes, quantity divergence), and regime context (different regime label at execution vs replay time)
- **Summary + drill-down**: Weekly report has aggregate category totals for quick review, plus per-trade detail in appendix for deep investigation
- **Report format: Markdown + Streamlit**: Static .md report in reports/drift/ (gitignored, matches Phase 42 bakeoff pattern) AND Streamlit page for interactive analysis. Phase 52 will consume drift data from the DB table
- **Visualizations: Full suite**: Plotly HTML charts embedded in report (equity curve overlay, tracking error time series, attribution waterfall). Same charts available in Streamlit page. Text/tables in .md report alongside chart links

### Claude's Discretion
- Signal matching algorithm selection after research (1:1, window, state, or hybrid)
- Kill switch integration approach after research (unified vs graduated vs tiered)
- Drift metrics table DDL design (table name, columns, indexes)
- Materialized view definition (aggregation granularity, refresh strategy)
- Threshold defaults for DRIFT-03 (5-day window, 1.5% tracking error are from requirements but may need research validation)
- Attribution decomposition algorithm (sequential vs simultaneous decomposition)
- Report generation CLI design and flags

</decisions>

<specifics>
## Specific Ideas

- V1 paper trading uses 2 EMA strategies (17,77 and 21,50) on BTC/ETH at 1D cadence. That's 4 signal paths per day — replay compute is negligible
- Phase 45's ParityChecker already compares executor fills against cmc_backtest_trades — drift guard extends this from one-time validation to continuous monitoring
- cmc_executor_run_log from Phase 45 already tracks each run with timestamps — extend it to snapshot input data state for PIT replay
- Phase 46's cmc_risk_events table provides a natural home for drift trigger events alongside other risk events
- The "both layers" approach (PIT + current data) makes data revision drift an explicit, measurable category rather than a confounding variable
- Weekly drift report with 6 attribution sources on 4 signal paths produces a compact but information-dense diagnostic artifact

</specifics>

<deferred>
## Deferred Ideas

- Operational dashboard integration for real-time drift monitoring — Phase 52
- Advanced drift decomposition (Brinson-style attribution) — future enhancement
- Cross-strategy correlation drift (do strategies drift together?) — future research
- Automated drift diagnosis (ML-based root cause identification) — future enhancement
- Historical drift pattern recognition (seasonal drift patterns) — future research

</deferred>

---

*Phase: 47-drift-guard*
*Context gathered: 2026-02-25*
