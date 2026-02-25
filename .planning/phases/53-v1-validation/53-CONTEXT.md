# Phase 53: V1 Validation - Context

**Gathered:** 2026-02-25
**Status:** Ready for planning

<domain>
## Phase Boundary

Run 2+ weeks of live paper trading with both selected EMA strategies (ema_trend 17,77 and ema_trend 21,50) active simultaneously. Measure against V1 success criteria (Sharpe, MaxDD, tracking error, slippage). Test kill switch manually and automatically. Audit all operational logs for gaps or silent failures. Produce daily validation logs and a comprehensive end-of-period validation report.

Strategy selection (Phase 42), executor (Phase 45), risk controls (Phase 46), drift guard (Phase 47), and operational dashboard (Phase 52) are prerequisites -- this phase only runs and measures.

</domain>

<decisions>
## Implementation Decisions

### Validation window & protocol
- Clock runs for 14 calendar days (crypto trades 24/7, calendar days are natural unit)
- Both strategies active from day 1 -- no staggering
- Clock keeps running through interruptions (drift pause, bugs, restarts) -- halts are findings, not resets
- Claude's Discretion: whether to include a formal go/no-go burn-in before starting the clock, or start immediately and treat early issues as validation findings

### Gate disposition
- Claude's Discretion (research best practices): how to handle the known MaxDD gate failure (70-75% worst-fold drawdown for both EMA strategies). Options include: document as known risk, measure at reduced 10% sizing, or redefine gate. Claude should research quantitative fund validation practices and recommend the approach that best balances honesty with practicality
- Tracking error breaches handled by drift guard (Phase 47) -- auto-pause is the system's natural response; the fact that it triggered is a valid finding
- Claude's Discretion (research best practices): whether to use binary PASS/FAIL or graded PASS/CONDITIONAL/FAIL per gate. Research how quant funds typically report validation gate outcomes
- Claude's Discretion (research best practices): whether V1 ships with failing gates or blocks. Research how quantitative trading firms handle paper-to-live transitions when some gates fail but mitigations exist

### Kill switch exercise
- Claude's Discretion: scheduling the kill switch test to minimize disruption to validation metrics
- Automatic trigger test: engineer a scenario early (temporarily lower daily loss threshold), then restore real thresholds for remaining days. Covers both engineered and natural trigger scenarios
- Recovery: auto-resume after configurable cooldown period (not manual restart)
- Evidence collected: DB records (risk events, position changes, order log) + timing metrics (latency from trigger to flat, target < 5s) + Telegram alert verification

### Evidence & report format
- Daily automated validation log: signals generated, orders placed, fills executed, P&L, drift metrics, anomalies
- End-of-period report in two formats:
  - Markdown + Plotly HTML (consistent with Phase 42 scorecard and Phase 47 drift reports, stored in reports/)
  - Jupyter notebook (executable, reader can re-run queries to verify findings)
- Log review (VAL-05): full automated gap detection (missing days, orphaned orders, zero-fill days, silent failures) + human reviews each flagged exception and signs off
- Audience: semi-formal, self-contained for future self and potential collaborators -- someone unfamiliar should understand methodology and results

</decisions>

<specifics>
## Specific Ideas

- Kill switch test should produce full end-to-end evidence: trigger -> flatten -> Telegram alert -> cooldown -> auto-resume, all with timestamps
- Daily log should be lightweight automation, not manual work -- the DB already has all the data
- Validation report should feed directly into Phase 54 (V1 Results Memo) without needing re-analysis

</specifics>

<deferred>
## Deferred Ideas

None -- discussion stayed within phase scope

</deferred>

---

*Phase: 53-v1-validation*
*Context gathered: 2026-02-25*
