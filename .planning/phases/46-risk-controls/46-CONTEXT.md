# Phase 46: Risk Controls - Context

**Gathered:** 2026-02-24
**Status:** Ready for planning

<domain>
## Phase Boundary

Implement safety mechanisms for the V1 paper trading system: kill switch, position caps, daily loss stops, circuit breaker, and discretionary overrides. These controls wrap the paper-trade executor (Phase 45) and protect capital during the 2-week validation period (Phase 53). Live trading execution and dashboard visualization of risk status are separate phases (Phase 45, Phase 52).

</domain>

<decisions>
## Implementation Decisions

### Kill Switch Mechanics
- **Scope:** Claude's discretion on exact behavior (halt signals + cancel pending + flatten, or signals-only-then-flatten) — pick the safest default
- **Re-enable:** Claude's discretion — pick based on safety best practices (manual-only vs manual+cooldown)
- **State persistence:** Claude's discretion — pick the approach (DB vs file lock)
- **Notification:** Telegram alert + DB/file log — use existing Phase 23 Telegram alerting infrastructure
- Kill switch event must be logged with timestamp, reason, and trigger source (manual/auto)

### Position Cap Enforcement
- **Cap levels:** Both per-asset caps AND portfolio-level utilization cap (max invested %)
- **Overrides:** Both cap levels support overrides
- **Enforcement behavior:** Scale order down to fit (not reject entirely) — log the adjustment
- **Configuration source:** DB table (`dim_risk_limits`) — runtime changeable without restart, queryable
- **Relationship to Phase 42 sizing:** Claude's discretion on whether 10% position fraction is a hard cap here or a guideline for Phase 45

### Circuit Breaker Logic
- **Loss tracking:** Track both realized trade P&L and daily portfolio return — Claude decides which (or both) triggers the breaker
- **Scope:** Both per-strategy breakers AND a portfolio-wide breaker that overrides individual strategy breakers
- **Reset:** Claude's discretion — pick the approach (manual-only vs time-based cooldown vs configurable)
- **Notification:** Telegram + DB log — same pattern as kill switch
- Configurable N (consecutive losses) and loss threshold per RISK-05

### Override & Config Model
- **Override entry:** CLI command for Phase 46; dashboard integration deferred to Phase 52
- **Override persistence:** Configurable per override — each override specifies sticky=true/false (sticky holds until reverted; non-sticky snaps back on next signal cycle)
- **Override audit:** Every manual override logged with user, reason, timestamp, and diff from system signal
- **Hot reload:** Claude's discretion on whether risk thresholds are hot-reloadable from DB each cycle or require restart
- **Architecture:** Claude's discretion on library pattern (executor calls risk_engine.check_order) vs middleware/interceptor pattern

### Claude's Discretion
- Kill switch exact shutdown sequence (halt+cancel+flatten vs gradual)
- Kill switch re-enable mechanism (manual-only vs manual+cooldown)
- Kill switch state persistence mechanism (DB vs file lock)
- Whether 10% position fraction from Phase 42 is enforced as hard cap or delegated to Phase 45
- Which loss metric(s) trigger the circuit breaker (realized trade P&L, daily return, or both)
- Circuit breaker reset mechanism
- Hot-reload vs restart-required for config changes
- Risk engine architecture (library vs middleware pattern)

</decisions>

<specifics>
## Specific Ideas

- Telegram alerting for both kill switch and circuit breaker events — reuse Phase 23 `send_critical_alert()` infrastructure
- User wants per-override sticky flag: `--sticky` on CLI means override persists until manually reverted; without it, next signal cycle returns to system position
- Position caps should scale orders down rather than reject — preserve signal intent while respecting limits
- DB-based config (`dim_risk_limits`) chosen over YAML for runtime flexibility — important for the 2-week validation period where thresholds may need tuning without restarts
- Both per-strategy and portfolio-wide circuit breakers — portfolio breaker is the hard override

</specifics>

<deferred>
## Deferred Ideas

- Dashboard visualization of risk status (kill switch state, cap utilization, circuit breaker status) — Phase 52 (DASH-L05)
- Dashboard-based override entry form — Phase 52
- Pool-level cap definitions (Conservative/Core/Opportunistic) — Phase 48 (LOSS-03)

</deferred>

---

*Phase: 46-risk-controls*
*Context gathered: 2026-02-24*
