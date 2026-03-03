# Phase 71: Event Risk Gates - Context

**Gathered:** 2026-03-03
**Status:** Ready for planning

<domain>
## Phase Boundary

Scheduled macro events (FOMC, CPI, NFP) and acute stress indicators (VIX spikes, carry unwinds, credit stress) automatically reduce position sizing through the risk engine, with override capability. This phase creates the event calendar, individual stress gates, a composite stress score, data freshness gating, and per-gate override mechanism.

Requirements: GATE-01 through GATE-09

</domain>

<decisions>
## Implementation Decisions

### Event Calendar & Gate Windows
- **Calendar maintenance:** Auto-fetch event dates from API (FRED, BLS, or similar) rather than static migration seed. Calendar should self-update.
- **Event window duration:** Claude's discretion per event type -- FOMC, CPI, and NFP may warrant different pre/post buffers based on market impact.
- **Timing precision:** Use exact event timestamps (e.g., FOMC announcement at 2pm ET), not calendar-day approximation. Gate windows computed as offset from exact timestamp.
- **Asset scope:** Per-asset sensitivity -- higher-beta assets (altcoins) get more aggressive size_mult reduction than BTC during event windows.

### Stress Indicator Thresholds & Tiers
- **Threshold storage:** DB-configurable via dim_risk_limits (or similar). All VIX, carry, and credit thresholds stored in DB so they can be tuned without code changes.
- **Composite score weights:** VIX-heavy weighting (~40%), with remaining weight distributed across HY OAS, carry velocity, and NFCI.
- **Tier boundaries:** DB-configurable, consistent with threshold storage approach.
- **Carry scope:** Multi-currency carry -- include CHF and EUR alongside JPY (DEXJPUS) for broader carry unwind signal.
- **VIX > 40 FLATTEN behavior:** OPEN QUESTION -- user notes this needs backtesting study ("you could argue VIX > 40 is a good time to buy during panic"). Implementation should support configurable behavior at this level (FLATTEN vs reduced sizing vs contrarian signal). Do not hardcode the most aggressive behavior.
- **Cooldown:** Yes, configurable cooldown period per gate. Gate stays active for N hours after stress condition clears to prevent whipsaw.
- **Credit+Carry interaction:** Claude's discretion -- the composite stress score likely already captures correlated stress. Individual gates can remain independent.
- **Composite score persistence:** Yes, dedicated DB table storing composite score + component values with timestamps for historical analysis and backtesting.

### Gate Interaction & Override Behavior
- **Gate stacking:** Claude's discretion on how multiple gate size_mults combine (worst-of vs multiplicative), consistent with existing L4 tighten-only semantics.
- **Override capability:** Per-gate override -- operators can disable specific gates via CLI or DB flag, with expiry time.
- **Override storage:** New dedicated table for gate overrides (not extending cmc_risk_overrides).
- **Transition alerts:** Telegram alerts on ALL gate state transitions (both escalations and de-escalations).

### Freshness & Degradation Policy
- **Freshness granularity:** Per-series -- each FRED series checked independently. Stale VIX data disables the VIX gate but not the carry gate.
- **Recovery behavior:** Auto re-enable when fresh data arrives. No manual acknowledgment required.
- **Weekend/holiday awareness:** Business-day aware staleness calculation. Friday data is considered fresh through the weekend.
- **Evaluation timing:** Both -- daily refresh pipeline pre-computes freshness state and stores it; executor double-checks at run time for maximum safety.

### Claude's Discretion
- Event window durations per event type
- Gate stacking semantics (worst-of vs multiplicative)
- Credit+carry correlated boost logic
- Exact composite score component weights (VIX ~40%, others distributed)
- Cooldown duration defaults
- API source selection for event calendar auto-fetch

</decisions>

<specifics>
## Specific Ideas

- VIX > 40 FLATTEN needs backtesting study before locking behavior -- "you could argue when the VIX > 40 is a good time to buy during panic." Implementation should be configurable, not hardcoded to flatten.
- Per-asset sensitivity: altcoins should get more aggressive reduction than BTC during macro events (higher beta = more exposure reduction).
- Multi-currency carry: don't just use JPY -- include CHF and EUR carry pairs for broader signal.

</specifics>

<deferred>
## Deferred Ideas

None -- discussion stayed within phase scope.

</deferred>

---

*Phase: 71-event-risk-gates*
*Context gathered: 2026-03-03*
