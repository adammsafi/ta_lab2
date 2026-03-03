# Phase 69: L4 Resolver Integration - Context

**Gathered:** 2026-03-02
**Status:** Ready for planning

<domain>
## Phase Boundary

Wire the macro regime composite key into the existing tighten-only resolver chain as L4, adjusting position sizing for all assets based on macroeconomic state. L4 can only tighten (size_mult <= 1.0), never loosen. Includes policy table entries, YAML overlay support, executor logging, and adaptive gross_cap. Depends on Phase 67 (macro regime labels); Phase 68 is not required.

</domain>

<decisions>
## Implementation Decisions

### Policy table entries
- Size_mult mapping approach: Claude's discretion (per-dimension product, composite lookup, or worst-dimension rule -- whichever fits existing resolver pattern best)
- Entry source: Claude's discretion (hardcoded defaults + YAML override, or YAML-only -- based on existing policy_loader patterns)
- Tightening aggressiveness: Claude's discretion (reasonable defaults, user tunes via YAML after observing behavior)
- Pattern matching: Full glob patterns (e.g., `*-RiskOff-*`) for maximum flexibility in matching partial composite keys
- Tighten-only invariant: size_mult <= 1.0 enforced by assertion on ALL macro entries (MINT-02)

### Adaptive gross_cap behavior
- Cap style (tiered vs continuous): Claude's discretion based on existing risk limit patterns
- Cap interaction with per-asset limits: Claude's discretion based on RiskEngine gate architecture
- Timing of cap changes: Claude's discretion based on daily refresh cadence
- Active trimming vs new-orders-only: Claude's discretion based on existing risk gate enforcement

### Executor logging scope
- Log target: DB (cmc_executor_run_log) + console (INFO-level log line showing L4 alongside L0-L2)
- Log detail: Both the L4 regime label AND the resulting size_mult for full audit trail
- Transition logging: Claude's discretion on log level for L4 changes between runs
- Per-trade L4 on cmc_orders: Claude's discretion based on audit trail needs vs schema complexity

### Missing regime handling
- Stale regime: Fall back to L0-L2 only (disable L4 entirely when macro regime is stale)
- Staleness threshold: Claude's discretion based on FRED update frequency and existing freshness checks
- Telegram alert: Yes -- send alert when L4 is disabled due to staleness so operator knows macro layer is offline
- Missing table: Claude's discretion (graceful skip vs startup error based on existing executor behavior)

### Claude's Discretion
- Size_mult mapping approach (per-dimension product, composite lookup, or worst-dimension)
- Hardcoded defaults vs YAML-only for macro policy entries
- Tightening aggressiveness (specific size_mult values)
- Gross_cap style, interaction, timing, and trimming behavior
- Staleness threshold for L4 fallback
- Transition log level
- Per-trade L4 column on cmc_orders
- Missing table handling

</decisions>

<specifics>
## Specific Ideas

- Glob pattern matching for YAML overlays (e.g., `*-RiskOff-*` matches any composite key containing RiskOff)
- L4 is always tighten-only -- assertion-enforced, no exceptions
- Telegram alert on L4 fallback so operator is aware macro layer went offline
- Both label and size_mult logged per executor run for debugging

</specifics>

<deferred>
## Deferred Ideas

None -- discussion stayed within phase scope

</deferred>

---

*Phase: 69-l4-resolver-integration*
*Context gathered: 2026-03-02*
