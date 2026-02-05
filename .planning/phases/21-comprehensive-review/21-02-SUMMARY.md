---
phase: 21-comprehensive-review
plan: 02
subsystem: features
tags: [ema, multi-timeframe, calendar-alignment, state-management, incremental-refresh]

# Dependency graph
requires:
  - phase: 20-historical-context
    provides: Current state analysis identifying 6 EMA variants use validated bar tables
provides:
  - Comprehensive documentation of all 6 EMA variants (purpose, data sources, WHY each exists)
  - Side-by-side variant comparison matrix across all dimensions
  - Evidence-based analysis with line number citations throughout
affects: [22-critical-data-quality-fixes, 23-reliable-incremental-refresh, 24-pattern-consistency]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Template Method pattern (BaseEMARefresher)
    - Unified state schema (id, tf, period) PRIMARY KEY across all variants
    - Shared EMA calculation via compute_ema function

key-files:
  created:
    - .planning/phases/21-comprehensive-review/findings/ema-variants.md
    - .planning/phases/21-comprehensive-review/deliverables/variant-comparison.md
  modified: []

key-decisions:
  - "All 6 EMA variants exist for legitimate semantic differences (data source, calendar alignment, anchoring) - NOT code duplication"
  - "80%+ infrastructure shared (BaseEMARefresher, EMAStateManager, compute_ema) confirms intentional design"
  - "Questions flagged about similarities (v1 vs v2, cal_us vs cal_iso) but NO consolidation recommendations per 21-CONTEXT.md"

patterns-established:
  - "Evidence standard: Every claim cites file path and line number(s)"
  - "Equal weight on WHAT and WHY: Document both functionality AND justification"
  - "Questions flagged without recommendations: Raise similarities as questions, not consolidation proposals"

# Metrics
duration: 7min
completed: 2026-02-05
---

# Phase 21 Plan 02: EMA Variant Analysis Summary

**6 EMA variants documented with purpose, data sources, calendar semantics, and WHY each exists - all already using validated bar tables**

## Performance

- **Duration:** 7 minutes
- **Started:** 2026-02-05T23:59:07Z
- **Completed:** 2026-02-05T23:59:25Z
- **Tasks:** 2
- **Files created:** 2

## Accomplishments

- **RVWQ-01 Answered:** Documented all 6 EMA variants (v1, v2, cal_us, cal_iso, cal_anchor_us, cal_anchor_iso) with detailed analysis of purpose, data sources, timeframe handling, output, use cases, and WHY each exists
- **RVWD-03 Delivered:** Created side-by-side comparison matrix covering all 6 variants across data sources, timeframe handling, calendar alignment, refresh logic, and output schema
- **Key Finding:** Confirmed Phase 20 discovery - ALL 6 variants ALREADY USE validated bar tables (no migration needed)
- **Shared Infrastructure:** Documented 80%+ code sharing via BaseEMARefresher, EMAStateManager, and compute_ema - confirms intentional design with 20% legitimate differences

## Task Commits

Both tasks completed in single commit with comprehensive deliverables:

1. **Tasks 1+2: EMA variant analysis and comparison** - `a9ef615d` (feat)
   - Task 1: ema-variants.md (detailed analysis of all 6 variants)
   - Task 2: variant-comparison.md (side-by-side comparison matrix)

## Files Created/Modified

### Created
- `.planning/phases/21-comprehensive-review/findings/ema-variants.md` - Deep analysis answering RVWQ-01: What does each EMA variant do and WHY? Includes purpose, data sources, timeframe handling, output, use cases, and WHY each of 6 variants exists. Documents shared infrastructure (BaseEMARefresher, EMAStateManager, compute_ema). Cites line numbers throughout.

- `.planning/phases/21-comprehensive-review/deliverables/variant-comparison.md` - Side-by-side comparison matrix (RVWD-03) covering all 6 variants across all dimensions. Includes dimension-by-dimension analysis explaining WHY variants differ, key insights (80%+ shared, 20% intentionally different), and open questions flagged without consolidation recommendations.

## Decisions Made

**1. All 6 variants exist for legitimate reasons**
- Evidence: Shared infrastructure (80%+ via BaseEMARefresher, EMAStateManager, compute_ema) with intentional differences (20% in data source, calendar alignment, anchoring)
- Not code duplication - architectural choices for different use cases

**2. No consolidation recommendations**
- Per 21-CONTEXT.md: "Flag questions only, no consolidation recommendations"
- Similarities flagged as questions (v1 vs v2, cal_us vs cal_iso, anchor use case frequency, unified state table)
- Each question documents WHAT is similar and WHY separation may be justified

**3. Evidence standard maintained**
- Every claim cites file path and line number(s)
- Example: "v1 uses cmc_price_bars_multi_tf (line 61: `bars_table: str = "cmc_price_bars_multi_tf"`)"
- Enables verification and future reference

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None - code analysis proceeded smoothly with comprehensive source code access.

## Next Phase Readiness

**Ready for Phase 21 remaining plans:**
- Plan 03: Incremental refresh analysis (RVWQ-02)
- Plan 04: Validation points analysis (RVWQ-03)
- Plan 05: Script inventory (RVWD-01)
- Plan 06: Data flow diagram (RVWD-02)
- Plan 07: Gap analysis (RVWD-04)

**Context for Phase 22-24:**
- **Phase 22 (Critical Data Quality Fixes):** EMA data source migration ALREADY COMPLETE (all variants use validated bars). Phase 22 should focus on bar table validation, not EMA migration.
- **Phase 23 (Reliable Incremental Refresh):** State management infrastructure documented. All variants use unified (id, tf, period) state schema. Incremental refresh patterns ready for standardization analysis.
- **Phase 24 (Pattern Consistency):** Shared infrastructure documented (BaseEMARefresher template, EMAStateManager, compute_ema). 80%+ code sharing confirms pattern consistency already achieved.

**Key insight affecting v0.6.0 scope:**
Phase 20 finding confirmed: EMAs already migrated to validated bar tables. Original Phase 22 assumption ("migrate EMAs to bars") is invalid. Roadmap adjustment recommended.

---
*Phase: 21-comprehensive-review*
*Completed: 2026-02-05*
