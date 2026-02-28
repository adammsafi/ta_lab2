---
phase: 59-microstructural-advanced-features
plan: 04
subsystem: features
tags: [codependence, distance-correlation, mutual-information, pairwise, microstructure]

# Dependency graph
requires:
  - phase: 59-01
    provides: "cmc_codependence table DDL with PK (id_a, id_b, tf, window_bars, computed_at)"
  - phase: 59-02
    provides: "microstructure.py math library: distance_correlation, pairwise_mi, variation_of_information, quantile_encode"
provides:
  - "codependence_feature.py standalone script for pairwise codependence computation"
  - "CLI for computing Pearson, distance correlation, MI, VI across all asset pairs"
  - "cmc_codependence table populated with historical snapshots"
affects:
  - 59-05 (orchestrator integration for full microstructure pipeline)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Standalone pairwise script pattern (not BaseFeature): load returns, generate pairs, compute sequentially, append to DB"
    - "Sequential pair processing to avoid OOM from O(n^2) distance matrices"
    - "computed_at batch timestamp for snapshot consistency"

key-files:
  created:
    - src/ta_lab2/scripts/features/codependence_feature.py
  modified: []

key-decisions:
  - "Standalone script pattern (not BaseFeature) because codependence is pairwise, not per-bar"
  - "Sequential pair processing instead of parallel to avoid OOM from distance matrices"
  - "Append-only writes (to_sql append) rather than scoped DELETE+INSERT, since computed_at in PK provides natural history"
  - "Minimum 30 overlapping observations threshold for valid codependence metrics"

patterns-established:
  - "Pairwise feature script: load_return_series -> generate_pairs -> compute_codependence -> write"

# Metrics
duration: 3min
completed: 2026-02-28
---

# Phase 59 Plan 04: Codependence Feature Script Summary

**Pairwise codependence computation script writing Pearson, distance correlation, mutual information, and variation of information to cmc_codependence for all asset pairs**

## Performance

- **Duration:** 3 min
- **Started:** 2026-02-28T09:17:17Z
- **Completed:** 2026-02-28T09:20:00Z
- **Tasks:** 1
- **Files created:** 1

## Accomplishments
- Created standalone `codependence_feature.py` (509 lines) computing 4 codependence metrics for all asset pairs
- CLI with --ids/--all, --tf, --window, --dry-run, --log-level, --db-url arguments
- Verified end-to-end: 3 pairs (BTC/XRP/ETH) computed and written to cmc_codependence with valid metrics (Pearson 0.78-0.82, dcorr 0.76-0.78)
- Uses microstructure.py math library (distance_correlation, pairwise_mi, variation_of_information, quantile_encode)

## Task Commits

Each task was committed atomically:

1. **Task 1: Implement codependence_feature.py pairwise computation** - `fd23d6f9` (feat)

## Files Created/Modified
- `src/ta_lab2/scripts/features/codependence_feature.py` - Standalone pairwise codependence computation script with CLI, data loading from cmc_returns_bars_multi_tf_u, pair generation, metric computation, and DB writing

## Decisions Made
- Used standalone script pattern (like refresh_cmc_regimes.py) rather than BaseFeature subclass, because codependence is pairwise (asset A vs asset B) rather than per-bar per-asset
- Sequential pair processing to avoid OOM from O(n^2) distance matrices -- each pair creates an n*n distance matrix in distance_correlation
- Append-only writes via pandas to_sql since computed_at in the PK naturally provides historical snapshots without needing scoped DELETE+INSERT
- Minimum 30 overlapping observations required for valid metrics; pairs below this threshold get NaN values with n_obs recorded

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- cmc_codependence table populated, ready for 59-05 orchestrator integration
- Script can be called from run_all_feature_refreshes.py or independently
- Historical snapshots preserved via computed_at in PK for tracking codependence evolution

---
*Phase: 59-microstructural-advanced-features*
*Completed: 2026-02-28*
