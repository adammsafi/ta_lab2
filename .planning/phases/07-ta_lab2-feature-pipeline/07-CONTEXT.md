# Phase 7: ta_lab2 Feature Pipeline - Context

**Gathered:** 2026-01-30
**Status:** Ready for planning

<domain>
## Phase Boundary

Build financial feature tables (returns, volatility, technical indicators) that calculate correctly from the unified time model established in Phase 6. Features must respect trading sessions, handle missing data gracefully, and refresh incrementally. These features feed into signal generation (Phase 8).

Scope includes: cmc_returns_daily, cmc_vol_daily, cmc_ta_daily, cmc_daily_features (unified view).

</domain>

<decisions>
## Implementation Decisions

### Feature Calculation Design

**Lookback windows:**
- Determined from dim_timeframe - query for tf_days (e.g., 7D return uses 7 days from dim_timeframe)
- Centralized truth, consistent with Phase 6 patterns

**Trading day vs calendar day lookbacks:**
- Leverage **both dim_timeframe AND dim_sessions** for asset-specific lookback logic
- Claude decides exact implementation, but should vary by asset type (e.g., crypto uses calendar, equities use trading days)

**Session awareness:**
- **Hybrid approach:** Session-aware for daily+, calendar-based for intraday (when added later)
- Use dim_sessions to respect market holidays and non-trading hours for daily features
- Claude decides specific implementation based on financial accuracy

**Corporate actions:**
- Claude's discretion - determine best practice for handling splits/dividends in quant trading

**Volatility measures:**
- Use **OHLC from bars table** (standard for Parkinson/GK vol estimation)
- Implement **multiple vol estimators** (user chooses via query)
- Claude decides which specific estimators to include (Parkinson, GK, others)

**Calculation engine:**
- **Hybrid approach:** Simple features in SQL, complex ones in Python
- Claude decides split based on performance and maintainability

**cmc_daily_features view:**
- Implement as **feature store table** with incremental refresh (explicit state tracking)
- Claude decides exact refresh mechanics based on query patterns

**Indicator parameters:**
- **Multiple parameter sets** (e.g., RSI_14, RSI_21, MACD_12_26_9, MACD_8_17_9)
- **Configurable** via dim_indicators table defining which params to calculate
- Balances flexibility with storage

**Intraday support:**
- **Design for intraday now** - schema and code support intraday from start (future-proof)
- Don't populate intraday data in Phase 7, but structure allows it

**Asset/timeframe discovery:**
- **Query dim_timeframe** for canonical TFs
- **Auto-discover from bars** - calculate features for any (asset, TF) with price bars
- Claude decides exact discovery logic

**Feature dependencies:**
- **Dependency graph** - define dependencies, auto-calculate refresh order
- Claude decides simplest reliable approach for tracking dependencies

**Feature normalization/scaling:**
- **Include z-score or similar** in feature tables (store both raw and normalized)
- Claude decides which normalizations are valuable for quant workflows

### Null Handling Strategy

**Missing price data:**
- User **leans towards interpolation**
- **Research-driven approach:** Claude should research and propose strategy - may need more than one approach (duplication/variation acceptable if worthwhile)
- Different strategies for different scenarios acceptable

**Strategy configurability:**
- **Per-feature type** tailoring (returns skip NULLs, volatility forward-fills, indicators interpolate)
- **Configurable** via dim_features or similar metadata
- Claude decides exact configuration mechanism

**Data quality indication:**
- **Metadata table** tracking quality events per (asset, date, feature)
- Claude decides most queryable structure

**Validation enforcement:**
- **Both write and query time:** Strict checks at write (block critical errors), warnings in metadata (soft issues)
- Claude determines exact thresholds and criticality levels

**Minimum data points:**
- **Partial calculation** or Claude's discretion - calculate with available data, note actual window used
- Document when insufficient history used

**Documentation:**
- **All three:** Code comments (inline), dim_features metadata (database), central FEATURES.md
- Comprehensive documentation for maintainability

**Extreme outliers:**
- **Flag but keep** - mark as outlier in quality metadata, preserve original value
- No automatic capping or removal - transparency for analysis

### Data Quality Validation

**Gap detection:**
- **Validate vs expected schedule** - use dim_timeframe + dim_sessions to know expected dates
- Accurate but complex - worth it for financial data correctness

**Alert thresholds:**
- Claude's discretion - set reasonable thresholds based on Phase 6 patterns (e.g., rowcount validation experience)

**Cross-table consistency:**
- **Automated checks** - run validation queries comparing tables (e.g., returns match price changes)
- Comprehensive validation of critical relationships

**Validation timing:**
- **Hybrid approach:** Critical checks inline (block bad data during refresh), comprehensive checks as separate jobs (monitoring)
- Balance speed with safety

### Incremental Refresh Design

**State tracking:**
- **Reuse EMA pattern** - extend EMAStateManager to FeatureStateManager
- Leverage Phase 6 infrastructure, maintain consistency

**Lookback window (dirty window):**
- **Leverage Phase 6 and Phase 4** patterns for determining dirty window start
- Consistent with established incremental refresh logic

**Upstream data changes:**
- **Cascade refresh** - price changes trigger returns refresh automatically
- **Dependency tracking** - system tracks dependencies, schedules refreshes in correct order
- Claude decides automation vs control trade-off

**Parallel execution:**
- **Parallel by asset** - process multiple assets concurrently
- Faster refresh, leverages Phase 5 orchestration if applicable

**Existing script review:**
- Review existing bar and EMA refresh implementations as part of planning
- Claude decides if refactoring helps or hinders Phase 7 (follow patterns vs improve patterns)

### Claude's Discretion

- Corporate action handling (splits/dividends) - determine quant trading best practice
- Exact session awareness implementation for hybrid approach
- Specific volatility estimators to implement (beyond Parkinson/GK)
- SQL vs Python split for feature calculations
- Feature store table refresh mechanics
- Exact asset/timeframe discovery logic
- Dependency graph implementation details
- Which normalizations valuable for features (z-score, others)
- Null handling strategy research and proposal
- Data quality alert thresholds
- Whether to refactor existing bar/EMA refresh scripts

</decisions>

<specifics>
## Specific Ideas

- "It should depend on the asset, I feel like this should leverage dim_timeframe and dim_session" (lookback calculation)
- "I tend towards three [interpolation], but you should research and propose an approach" (null handling)
- "Leverage phase 6 and 4" (incremental refresh lookback windows)
- "Review existing bar and ema refresh as part of this phase" (before designing feature refresh)

</specifics>

<deferred>
## Deferred Ideas

None - discussion stayed within phase scope (feature pipeline implementation).

</deferred>

---

*Phase: 07-ta_lab2-feature-pipeline*
*Context gathered: 2026-01-30*
