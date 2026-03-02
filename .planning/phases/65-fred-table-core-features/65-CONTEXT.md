# Phase 65: FRED Table & Core Features - Context

**Gathered:** 2026-03-02
**Status:** Ready for planning

<domain>
## Phase Boundary

Build the `fred_macro_features` table with daily-aligned macro values computed from the 39 FRED series in `fred.series_values`. Forward-fill mixed-frequency series (monthly, weekly) to daily cadence. Compute core derived features: net liquidity proxy, rate spreads, yield curve features, VIX regime, and dollar strength. Add WTREGEN (TGA) to VM collection. Wire macro feature computation into `run_daily_refresh.py`.

Requirements: FRED-01 through FRED-07 (7 requirements).

</domain>

<decisions>
## Implementation Decisions

### Table Schema Design
- **Claude's discretion** on wide vs long table structure — pick what fits existing patterns (cmc_features, cmc_regimes)
- **Derived features only** in fred_macro_features — raw FRED observations stay in `fred.series_values`. Consumers join if they need raw values.
- **Claude's discretion** on database/schema placement (marketdata public vs fred schema)
- **Alembic migration required** — proper migration tracked in version history, not DDL-in-code

### Forward-Fill Behavior
- Forward-fill monthly (limit=45) and weekly (limit=10) series to daily cadence
- **Track staleness** — include `days_since_publication` or equivalent provenance column so downstream consumers can assess trustworthiness
- Store `source_freq` column to distinguish daily/weekly/monthly provenance
- **Claude's discretion** on whether to fill calendar gaps (weekends/holidays) or keep business-days-only — pick based on how downstream consumers (regime labeler, risk gates running on crypto 24/7 data) need it
- **Claude's discretion** on where forward-fill logic lives (compute-time vs raw table)
- **Claude's discretion** on stale-input handling for derived features — pick the approach matching real-time trading conditions (traders work with last known values)

### Net Liquidity Formula
- **Add WTREGEN (TGA) to VM collection** — update .fred.env, backfill, sync. Full formula from day one: `WALCL - WTREGEN - RRPONTSYD`
- **Use last known (forward-fill)** when a component is temporarily missing — WALCL updates weekly, between updates last Wednesday's value is the best estimate
- **Claude's discretion** on whether Phase 65 includes the z-score/dual-window trend (FRED-12) or defers to Phase 66 per the roadmap assignment

### Refresh Pipeline Placement
- **Both** — FRED sync runs independently on its own schedule AND daily refresh triggers a sync if data looks stale. Belt and suspenders.
- **Claude's discretion** on failure handling — per project convention (warn-and-continue for non-critical, fail-hard for critical)
- **Claude's discretion** on pipeline ordering — macro features don't depend on bars/EMAs, but regimes depend on both
- **Incremental computation** — only compute features for dates after last computed_at. Handle z-score/rolling window warm-up correctly.

### Claude's Discretion
- Wide vs long table structure
- Database schema placement
- Weekend/holiday gap handling
- Pipeline ordering within run_daily_refresh.py
- Failure mode (warn-and-continue vs halt)
- Whether net liquidity z-score lands in Phase 65 or Phase 66

</decisions>

<specifics>
## Specific Ideas

- Net liquidity (WALCL - TGA - RRP) is the #1 macro-crypto correlation per research. Getting this right is the highest-value deliverable of the phase.
- The existing `sync_fred_from_vm.py` (SSH COPY, incremental, integrity verification) is the sync mechanism — extend it, don't replace it.
- 208K rows across 39 series (will be 40 with WTREGEN) — small enough that compute performance is not a concern.
- Research identified that VIX thresholds (calm <15, elevated 15-25, crisis >25) are consensus values.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 65-fred-table-core-features*
*Context gathered: 2026-03-02*
