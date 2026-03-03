# Phase 68: HMM & Macro Analytics - Context

**Gathered:** 2026-03-02
**Status:** Ready for planning

<domain>
## Phase Boundary

Secondary analytical tools that assess macro regime quality and predictive power. Three components: (1) HMM regime confirmation against rule-based labels, (2) lead-lag quantification of macro features on crypto returns, (3) regime transition probability matrices. These are analytics -- they produce insight and confirmation signals, not direct trading decisions. Depends on Phase 67 macro regime labels and features.

</domain>

<decisions>
## Implementation Decisions

### HMM confirmation design
- Number of states: Claude's discretion (2 or 3, based on data characteristics)
- Confirmation approach: Both agreement percentage AND divergence alerts
  - Track rolling agreement % between HMM state and rule-based label
  - Alert on sustained divergence (consecutive days threshold -- Claude picks reasonable default, configurable in YAML)
- Retraining: Rolling retrain on each daily refresh (window size at Claude's discretion)
- Input features: net liquidity + VIX + HY OAS (per roadmap success criteria)

### Lead-lag output & scope
- Feature scope: All macro features in fred_macro_features (comprehensive)
- Asset scope: All traded assets (not just BTC/ETH)
- Storage: DB table for programmatic access and queryability
- Use case: Research insight now, structured so it can feed feature selection later
- Method: Existing `lead_lag_max_corr()` pattern at lags [-20..+20] days

### Transition matrix usage
- Window: Both static (all history) and rolling window for recent dynamics comparison
- Query interface: DB table + Python helper function (e.g., `get_transition_prob('RiskOff', 'RiskOn')`)
- Derived analytics: Regime duration estimates using transition probs (geometric distribution)
- Granularity: Per-dimension (monetary, liquidity, risk, carry) + composite regime key

### Refresh cadence & persistence
- All three tools integrated into daily refresh pipeline (after macro regime computation)
- Three separate DB tables (NO `cmc_` prefix): `hmm_regime_states`, `macro_lead_lag`, `regime_transitions`
- Schema management: Alembic migrations for all tables
- Transition matrix refresh cadence: Claude's discretion (daily vs weekly based on marginal information gain)

### Claude's Discretion
- HMM state count (2 vs 3)
- Divergence alert threshold (consecutive days)
- Rolling retrain window size for HMM
- Transition matrix refresh cadence (daily vs weekly)
- Exact table column designs
- Helper function API design
- Rolling window size for transition matrix

</decisions>

<specifics>
## Specific Ideas

- Table naming convention: drop the `cmc_` prefix for these analytics tables
- Lead-lag should reuse existing `lead_lag_max_corr()` pattern -- no new correlation method needed
- HMM trained on net liquidity + VIX + HY OAS (3 input features from success criteria)
- Transition matrix should support duration estimation (expected time in current regime)

</specifics>

<deferred>
## Deferred Ideas

None -- discussion stayed within phase scope

</deferred>

---

*Phase: 68-hmm-macro-analytics*
*Context gathered: 2026-03-02*
