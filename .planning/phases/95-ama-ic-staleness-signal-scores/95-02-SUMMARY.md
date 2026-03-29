---
phase: 95-ama-ic-staleness-signal-scores
plan: 02
subsystem: portfolio
tags: [black-litterman, signal-scores, ama, features, portfolio-allocation]

# Dependency graph
requires:
  - phase: 87-ic-staleness-weight-decay
    provides: ic_ir_matrix and dim_ic_weight_overrides infrastructure
  - phase: 80-feature-selection
    provides: parse_active_features() and feature_selection.yaml
provides:
  - "Real per-asset signal_scores from features + ama_multi_tf_u.d1 for BL view construction"
  - "_load_signal_scores() reusable helper in refresh_portfolio_allocations.py"
affects: [portfolio-allocations, paper-executor, black-litterman]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "DISTINCT ON (id) ORDER BY ts DESC for latest-value-per-asset queries"
    - "information_schema column validation before dynamic SQL column reference"

key-files:
  created: []
  modified:
    - "src/ta_lab2/scripts/portfolio/refresh_portfolio_allocations.py"

key-decisions:
  - "Use d1 (first derivative) from ama_multi_tf_u as AMA signal value -- stationary momentum signal per research recommendation"
  - "Fill missing feature values with 0.0 (neutral signal) rather than dropping assets"
  - "Column alignment between signal_scores and ic_ir_matrix via common_features intersection"

patterns-established:
  - "Per-feature try/except in _load_signal_scores so one DB failure does not break all features"

# Metrics
duration: 5min
completed: 2026-03-28
---

# Phase 95 Plan 02: Real Signal Scores Summary

**Replaced uniform signal_scores=1.0 with real per-asset feature values from features table and ama_multi_tf_u.d1 for Black-Litterman view construction**

## Performance

- **Duration:** 5 min
- **Started:** 2026-03-29T03:02:58Z
- **Completed:** 2026-03-29T03:08:00Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments
- Built _load_signal_scores() helper that queries latest feature values per asset from both bar-level features table and AMA features from ama_multi_tf_u.d1
- Replaced uniform 1.0 signal_scores with real values; tested 20/20 features loaded successfully for BTC/ETH/USDT
- Added graceful fallback to uniform 1.0 when _load_signal_scores() fails or no common features exist
- Removed TODO(Phase 87) comment

## Task Commits

Each task was committed atomically:

1. **Task 1: Build _load_signal_scores() helper and wire into BL path** - `1d7b5bd8` (feat)

## Files Created/Modified
- `src/ta_lab2/scripts/portfolio/refresh_portfolio_allocations.py` - Added _load_signal_scores() helper, replaced uniform signal_scores block, removed TODO(Phase 87)

## Decisions Made
- Use d1 column (first derivative, stationary momentum signal) from ama_multi_tf_u for AMA features per Phase 95 research recommendation
- Fill NaN with 0.0 (neutral signal) so missing features do not crash BL optimization
- Pre-validate bar-level feature columns via information_schema to avoid SQL errors on nonexistent columns
- Align signal_scores columns with ic_ir_matrix via common_features intersection, with fallback to uniform 1.0 if no overlap

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

Pre-existing bug in _load_price_matrix() causes ValueError on --dry-run with --ids all (duplicate timestamps from multi-venue data). This is outside plan scope and does not affect the signal_scores changes. The _load_signal_scores() function was verified independently against the real database.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Phase 95 complete: both IC staleness AMA-awareness (plan 01) and real signal scores (plan 02) delivered
- Paper executor now receives non-uniform signal_scores through BLAllocationBuilder
- BL views now differentiated by actual feature momentum values per asset

---
*Phase: 95-ama-ic-staleness-signal-scores*
*Completed: 2026-03-28*
