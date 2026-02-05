# Phase 25: Baseline Capture - Context

**Gathered:** 2026-02-05
**Status:** Ready for planning

<domain>
## Phase Boundary

Capture current EMA outputs from all 6 variants to establish a baseline for validation testing. Ensures we can detect any calculation drift or silent regressions after the Phase 22-24 refactoring.

**Workflow:** Snapshot → Truncate → Rebuild → Compare

</domain>

<decisions>
## Implementation Decisions

### Capture Scope
- **Asset selection:** Create dim_assets table from dim_sessions WHERE asset_class = 'CRYPTO' (no dim_assets exists currently)
- **Timeframe coverage:** Representative timeframes (sample key timeframes to verify patterns without capturing everything) + all existing timeframes (Claude's discretion based on what exists in tables)
- **Date range for rebuild:** Intelligent sampling with randomness, focused on beginning and end of time series (Claude analyzes data volume and chooses appropriate range)
- **Context from user:** "Review phases 1-10 and 20-24" - understand existing work before designing capture strategy

### Storage Format
- **Snapshot table naming:** Timestamped pattern (e.g., `cmc_ema_v1_20260205`, `cmc_price_bars_1d_20260205`)
- **Comparison results:** Claude's discretion (user leans toward log files only, not persistent table)
- **Column capture:** Claude's discretion based on comparison needs (user leans toward all columns for completeness)
- **Organization:** Tables created with timestamp suffix for tracking baseline captures over time

### Comparison Strategy
- **Epsilon tolerance:** Claude decides based on data characteristics (analyze value ranges, set appropriate epsilon per data type)
- **Mismatch reporting:** Comprehensive - all three approaches
  - Severity levels (CRITICAL: >1% diff, WARNING: >epsilon but <1%, INFO: expected differences)
  - Statistical summary (match rate %, max diff, mean diff, std dev)
  - Pass/Fail binary (within epsilon = pass, outside = fail)
- **Failure handling:** Always run to completion, report only (never fail - generate detailed report for manual review)

### Reproducibility
- **Invocation:** Claude's discretion based on existing orchestration patterns (follow established patterns from Phase 23)
- **Metadata capture:** Full audit trail
  - Timestamp + git commit hash
  - Asset count + date range
  - Script versions + database state
  - Full context for debugging and reproducibility
- **Snapshot retention:** Manual cleanup only (keep snapshot tables until user explicitly drops them)

### Claude's Discretion
- Exact epsilon values per column type (OHLCV vs EMA values)
- Sampling strategy (randomness algorithm for beginning/end focus)
- Comparison results storage (table vs log file decision)
- Column selection for snapshots (all vs core only)
- Orchestration pattern (script vs Makefile vs both)

</decisions>

<specifics>
## Specific Ideas

**Core Strategy (from user):**
"We should probably create snapshots of current bar and EMA tables, truncate the existing tables, run the bar scripts then the EMA scripts and then compare samples of the snapshots and the updated tables."

**Key Insight:**
This validates the entire pipeline end-to-end: bars → EMAs. If rebuild produces identical results, we have high confidence the refactoring preserved correctness.

**Asset Context:**
dim_assets doesn't exist yet - needs to be created from dim_sessions filtering for asset_class = 'CRYPTO'.

**Historical Context:**
Review phases 1-10 and 20-24 to understand what was built and avoid duplicating work.

</specifics>

<deferred>
## Deferred Ideas

None - discussion stayed within phase scope.

</deferred>

---

*Phase: 25-baseline-capture*
*Context gathered: 2026-02-05*
