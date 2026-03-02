# Phase 66: FRED Derived Features & Automation - Context

**Gathered:** 2026-03-02
**Status:** Ready for planning

<domain>
## Phase Boundary

Compute all remaining macro features -- credit stress, financial conditions, carry trade, fed regime classification, CPI proxy -- and wire the entire macro feature pipeline into the daily refresh. Phase 65 provides the core feature table and base series; this phase adds derived/composite features and automation. Macro regime classification (Phase 67) and downstream integration are separate phases.

</domain>

<decisions>
## Implementation Decisions

### Gap filling policy
- Follow same pattern as Phase 65 for monthly series
- Weekly series: forward-fill up to 10 days, then NULL
- Monthly series: forward-fill up to 45 days, then NULL
- Z-score rolling windows: require minimum 80% fill before computing (e.g., 24/30 days for 30d z-score), NULL otherwise

### Fed regime classification
- Zero-bound defined as DFEDTARU <= 0.25%
- Single-target vs target-range distinction: Claude's discretion based on data availability (presence-based vs spread-based)
- Hiking/holding/cutting thresholds from 90d DFF trajectory: Claude's discretion to pick absolute change vs slope method based on historical label quality

### Refresh orchestration
- Summary log after macro feature refresh: feature groups computed, rows upserted, staleness warnings
- Standalone CLI command (`run_macro_features`) for ad-hoc runs AND integrated into `run_daily_refresh.py`

### Claude's Discretion
- Staleness warning logging behavior (warn vs silent when data goes NULL)
- Staleness caps storage format (hardcoded dict vs YAML config -- match codebase patterns)
- Refresh failure mode (skip-and-continue vs abort-all -- match existing daily refresh patterns)
- FRED sync retry behavior before macro feature computation
- Fed regime label storage format (text vs integer codes -- match existing regime label patterns)
- CPI surprise proxy fill behavior on non-release days (research best practices: ffill, NULL, or decay)
- CPI release day flag column inclusion (based on downstream Phase 67/71 needs)
- CPI baseline window configurability (lock at 3 months or make configurable)
- Carry momentum threshold configurability (lock at 2.0 or make configurable)

</decisions>

<specifics>
## Specific Ideas

No specific requirements -- open to standard approaches. Key constraint: follow whatever patterns Phase 65 establishes for the `fred_macro_features` table and feature computation.

</specifics>

<deferred>
## Deferred Ideas

None -- discussion stayed within phase scope.

</deferred>

---

*Phase: 66-fred-derived-features-automation*
*Context gathered: 2026-03-02*
