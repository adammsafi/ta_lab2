# Phase 67: Macro Regime Classifier - Context

**Gathered:** 2026-03-03
**Status:** Ready for planning

<domain>
## Phase Boundary

Rule-based macro regime labeler that reads daily macro features from `fred.fred_macro_features` (Phase 65-66) and produces 4-dimensional composite regime labels stored in `cmc_macro_regimes`. Dimensions: monetary policy, liquidity, risk appetite, carry. Labels include hysteresis to prevent flapping. YAML-configurable thresholds. Downstream consumers: L4 resolver (Phase 69), risk gates (Phase 71), dashboard (Phase 72).

Does NOT include: HMM secondary classifier (Phase 68), L4 resolver wiring (Phase 69), event-based gates (Phase 71), or dashboard display (Phase 72).

</domain>

<decisions>
## Implementation Decisions

### Dimension independence vs interaction
- Claude's discretion on whether dimensions are fully independent or selectively interacting
- Claude's discretion on conflict handling (no special handling vs conservative override)
- Additional inputs beyond MREG requirements are allowed if Phase 66 features improve classification (e.g., M2 for liquidity)
- **Strict dependency on Phase 66:** If a dimension's required inputs are missing, raise an error. No graceful fallback to degraded feature sets.

### Hysteresis across dimensions
- Claude's discretion on whether hysteresis applies per-dimension, composite-level, or both
- Claude's discretion on tighten-immediately vs hold-on-loosening semantics per dimension
- Claude's discretion on default min_bars_hold value (requirements say >= 5)
- **Persist hysteresis state in DB** so incremental runs resume from where they left off (adds a state table)

### YAML config design
- Claude's discretion on config file location (alongside regime configs or in macro/ package)
- Claude's discretion on threshold types (absolute vs z-score vs mix per requirement spec)
- **Named profiles supported:** Config supports multiple profiles (e.g., 'conservative', 'aggressive', 'default') with a selector, useful for backtesting different sensitivity levels
- **All-in-one YAML:** Thresholds + hysteresis params + profile selector all in one file. Single source of truth for macro regime behavior.

### Composite key semantics
- **Both: full key + bucketed state.** Store the full composite key (e.g., `Cutting-Expanding-RiskOn-Stable`) AND a bucketed `macro_state` column. Full key for analysis, bucketed state for policy lookups.
- **5 bucketed states:** favorable / constructive / neutral / cautious / adverse. Allows graduated position sizing.
- Claude's discretion on dimension ordering in the composite key (fixed vs severity-sorted)
- Claude's discretion on bucketing method (explicit YAML rules vs severity scoring)

### Claude's Discretion
- Dimension independence vs interaction approach
- Hysteresis scope (per-dimension vs composite vs both) and tighten direction semantics
- Default min_bars_hold value (>= 5 per requirements)
- Config file location and threshold types
- Composite key ordering and bucketing method
- Error state handling and logging patterns

</decisions>

<specifics>
## Specific Ideas

- Existing `HysteresisTracker` in `ta_lab2/regimes/hysteresis.py` already has tighten-immediately / hold-on-loosening semantics tracked per layer key. Reuse or extend this pattern.
- Existing `resolve_policy_from_table` in `ta_lab2/regimes/resolver.py` uses substring matching for composite keys. The macro composite key should be compatible with this pattern.
- The per-asset regime system uses L0/L1/L2 layers. Macro regime will feed into L4 slot (Phase 69). Keep the naming and patterns consistent.

</specifics>

<deferred>
## Deferred Ideas

None -- discussion stayed within phase scope.

</deferred>

---

*Phase: 67-macro-regime-classifier*
*Context gathered: 2026-03-03*
