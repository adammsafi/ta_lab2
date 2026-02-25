# Phase 48: Loss Limits Policy - Context

**Gathered:** 2026-02-25
**Status:** Ready for planning

<domain>
## Phase Boundary

Define and validate the loss limit framework for V1 paper trading: day-level VaR simulation, intraday stop-loss scenario analysis (hard/trailing/time-stop), pool-level drawdown cap definition (Conservative/Core/Opportunistic), and override governance rules. This is Research Track #2 from the Vision Draft. Outputs are analysis scripts, policy documents, and configuration that feeds into Phase 46 risk controls. Live enforcement is Phase 46; tail-risk policy is Phase 49.

</domain>

<decisions>
## Implementation Decisions

### VaR Simulation Scope
- **Assets/strategies:** All backtested strategies (EMA 17,77; EMA 21,50; RSI; ATR breakout) on BTC/ETH -- not just the 2 selected V1 strategies
- **Methodology:** Both historical simulation AND parametric (Cornish-Fisher) VaR -- the gap between methods IS the tail risk insight
- **Confidence levels:** 95% and 99%
- **VaR-to-cap translation:** VaR directly sets the daily_loss_pct_threshold in dim_risk_limits by default, but with the option to manually override the cap value -- both modes supported, default to VaR-driven (mode 1)

### Intraday Stop Mechanics
- **Stop types to simulate:** All three -- hard stop, trailing stop, and time-stop (exit after N bars)
- **Threshold sweep:** Wide range: 1%, 3%, 5%, 7%, 10%, 15% -- captures crypto volatility where tight stops whipsaw
- **Comparison metrics:** Full performance comparison -- Sharpe, MaxDD, win rate, turnover, recovery time, opportunity cost
- **Output:** Report AND auto-configure -- write optimal stop parameters to dim_risk_limits based on simulation results (in addition to producing the analysis report)

### Pool-Level Cap Definition
- **Pool structure:** Define all 3 pools (Conservative/Core/Opportunistic) even though V1 runs a single portfolio -- ready for multi-pool when it comes
- **Cap targets:** Data-driven from Phase 42 backtest results, starting from Vision Draft targets but adjusted for actual strategy MaxDD (70-75% worst-fold drawdown)
- **Enforcement during V1:** Claude's discretion -- single-portfolio V1 may only enforce aggregate limits while defining pool-specific caps for documentation/future use

### Override Governance
- **Approval process:** Solo operator -- single operator can override caps via CLI with reason logged, no approval chain needed for prop trading
- **Override expiry:** Claude's discretion -- pick based on safety best practices (time-limited auto-expire vs manual-only)
- **Deliverable format:** Policy document AND validation code -- rules enforced in OverrideManager (e.g., max duration, reason categories)
- **Reason categories:** Claude's discretion -- pick between free-text or predefined categories based on audit trail usefulness

### Claude's Discretion
- Pool-level cap storage approach (new rows in dim_risk_limits vs separate dim_pools table)
- Whether pool caps are actively enforced during V1 or defined for documentation only
- Override auto-expire duration (time-limited vs manual-only)
- Override reason categories (free-text vs predefined enum)

</decisions>

<specifics>
## Specific Ideas

- VaR comparison between historical and parametric methods highlights where Gaussian assumptions fail for crypto -- this IS the analysis, not just a methodological choice
- Stop simulation should sweep a wide range (1-15%) because the V1 strategies have extreme drawdowns (70-75% worst fold) -- tight stops would whipsaw constantly in bear markets
- Pool definitions should be ready for multi-pool even though V1 is single-portfolio -- this avoids re-doing the analysis later
- Auto-configure capability means VaR and stop simulation results directly write to Phase 46 dim_risk_limits, making the analysis actionable immediately

</specifics>

<deferred>
## Deferred Ideas

- Multi-pool enforcement during paper trading -- V1 runs single portfolio, pool enforcement is post-V1
- Dynamic pool allocation (rebalancing between pools) -- separate from cap definition
- Dashboard visualization of pool-level risk status -- Phase 52 (DASH-L05)

</deferred>

---

*Phase: 48-loss-limits-policy*
*Context gathered: 2026-02-25*
