---
phase: 49
name: tail-risk-policy
status: context-gathered
depends_on: [48]
requirements: [TAIL-01, TAIL-02, TAIL-03]
---

# Phase 49: Tail-Risk Policy -- Implementation Context

## Phase Goal
Define when and how the system should respond to extreme market conditions. Compare risk mitigation approaches (hard stops vs vol-based sizing), define flatten-all criteria, and publish a comprehensive tail-risk policy.

---

## Area 1: Hard Stop vs Vol-Sizing Comparison Scope (TAIL-01)

### Decisions
- **Vol metrics**: Both ATR-14 (from cmc_features) AND realized vol (rolling std of daily returns). Compare outcomes of each.
- **Comparison variants**: All three -- (a) fixed size + stops, (b) vol-sized + no stops, (c) vol-sized + stops. Most comprehensive comparison.
- **Strategy/asset coverage**: All 4 bakeoff strategies (ema_trend_17_77, ema_trend_21_50, rsi_mean_revert, breakout_atr), BTC + ETH. Same scope as Phase 48.
- **Risk budget**: Claude's discretion -- pick sensible default and sweep range based on research.
- **Performance metrics**: Phase 48 metrics (Sharpe, MaxDD, recovery time, opportunity cost, win rate) PLUS tail-risk specific: Sortino ratio, Calmar ratio, worst-N-day returns.
- **Output**: Recommend a winner per strategy/asset combo, but present all data so operator can override.
- **Backtest engine**: Reuse vectorbt (Phase 42 pattern). Consistent with existing infrastructure.
- **Sizing integration**: Integrated sizing in backtest -- compute position size at entry time based on current vol. Not a post-hoc overlay.

### Claude's Discretion
- Risk budget default and sweep range (suggest 0.5%, 1%, 2% as starting point)
- Rolling window for realized vol calculation
- Recommendation criteria (how to pick "winner" among variants)

---

## Area 2: Flatten-All Trigger Definition (TAIL-02)

### Decisions
- **Trigger types**: All of the following plus custom:
  1. Vol spike (realized vol exceeds threshold)
  2. Correlation breakdown (BTC/ETH diverge abnormally)
  3. Exchange halt / API failure (infrastructure)
  4. Custom triggers (e.g., liquidity drought, funding rate extremes for future perps)
- **Vol spike calibration**: Both rolling lookback (vol > rolling_mean + N*rolling_std) AND fixed historical percentile (vol > 99th percentile all-time). Compare false positive rates.
- **Historical crash validation**: Claude's discretion -- determine if validating against known events (COVID March 2020, May 2021, FTX Nov 2022) adds value given available data.
- **Deliverable**: Both executable code (check_flatten_trigger() in RiskEngine) AND documented policy in Markdown. Code validates policy is implementable.

### Claude's Discretion
- Specific sigma thresholds for vol spike
- Correlation breakdown detection methodology
- Exchange halt detection approach (API health check vs external data)
- Whether to include custom triggers like liquidity/funding rate in V1 or defer
- Whether historical crash validation is worth the effort

---

## Area 3: Policy Document Structure and Tone (TAIL-03)

### Decisions
- **Audience**: Both machine (structured config YAML/JSON for RiskEngine) AND human (Markdown research memo with analysis and rationale). Two outputs.
- **Sections**: Comprehensive -- all three TAIL requirements PLUS:
  - Regime interaction: how tail-risk policy interacts with Phase 27 regime detection (bull/bear/sideways)
  - Historical context: analysis of past crypto tail events and what this policy would have done
- **Output location**: `reports/tail_risk/` -- separate directory from Phase 48 loss_limits
- **Specificity**: Superset -- specific numerical thresholds from backtests as defaults, framework/methodology for determining them, AND guidance on when/how to override. All three levels of detail.

### Claude's Discretion
- Config schema (YAML vs JSON) for machine-readable policy
- Memo organization and narrative flow
- Level of historical event analysis depth

---

## Area 4: Escalation and Re-Entry Procedure

### Decisions
- **Escalation levels**: Three levels, not binary:
  1. **Normal**: Full signal processing, standard position sizing
  2. **Reduce**: Intermediate risk reduction (e.g., halve position sizes). Triggered before full flatten.
  3. **Flatten**: Exit all positions, stop processing new entries
- **Re-entry**: Claude's discretion -- research and recommend the best approach (options: automatic after cooldown, manual approval, graduated re-entry).
- **Architecture**: Standalone RiskEngine check. PaperExecutor calls RiskEngine, which returns escalation state. Clean separation of concerns.
- **Alerting**: Log (WARNING/CRITICAL) AND write state changes to DB table. Auditable history of escalation events.

### Claude's Discretion
- Re-entry mechanism (automatic cooldown vs manual vs graduated)
- Thresholds for normal -> reduce transition vs reduce -> flatten transition
- DB table for escalation history (new table vs reuse cmc_risk_overrides)
- Cooldown duration / conditions for de-escalation

---

## Deferred Ideas
(None raised during discussion)

---

## Summary for Downstream Agents

Phase 49 produces:
1. **Backtest comparison** (TAIL-01): 3 variants x 4 strategies x 2 assets x 2 vol metrics. Metrics include Sortino/Calmar/worst-N-day beyond Phase 48 set. Vectorbt engine with integrated vol-sizing at entry. Recommendation + data.
2. **Flatten triggers** (TAIL-02): 4+ trigger types, both calibration approaches, executable RiskEngine code + policy doc. Three escalation levels (normal/reduce/flatten).
3. **Policy document** (TAIL-03): Machine config + human memo in `reports/tail_risk/`. Comprehensive sections including regime interaction and historical context. Specific defaults + framework + override guidance.
4. **Escalation system**: Standalone RiskEngine integration, DB-logged state changes, re-entry procedure (Claude's discretion on approach).
