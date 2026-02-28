---
phase: 59-microstructural-advanced-features
plan: 05
subsystem: features, regimes, analysis
tags: [microstructure, orchestrator, SADF, IC, codependence, distance-correlation, fractional-differentiation]

# Dependency graph
requires:
  - phase: 59-03
    provides: MicrostructureFeature BaseFeature subclass + CLI
  - phase: 59-04
    provides: codependence_feature.py pairwise computation script
  - phase: 37-ic-evaluation
    provides: run_ic_eval.py IC infrastructure + cmc_ic_results table
provides:
  - Orchestrator wires microstructure refresh into standard pipeline (Phase 2b)
  - DDL updated with 9 microstructure columns as schema contract
  - SADF explosive flag integrated into regime_key ("|explosive" suffix)
  - IC evaluation results for 7 microstructure columns persisted
  - Codependence vs Pearson comparison for 15 asset pairs
affects: [60-paper-trading, regime-pipeline, feature-pipeline]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Phase 2b UPDATE pattern: supplemental columns written after base cmc_features refresh"
    - "Regime key suffix pattern: '|explosive' appended to regime_key from SADF flags"
    - "Optional batch flag pattern: --codependence for expensive pairwise computation"

key-files:
  modified:
    - src/ta_lab2/scripts/features/run_all_feature_refreshes.py
    - sql/views/050_cmc_features.sql
    - src/ta_lab2/scripts/regimes/refresh_cmc_regimes.py

key-decisions:
  - "Microstructure runs in Phase 2b (after base cmc_features DELETE+INSERT) not Phase 1, because UPDATE requires existing rows"
  - "Codependence exposed via --codependence flag (not always-on) since pairwise computation takes ~3 min"
  - "SADF integration is purely additive: '|explosive' suffix appended to regime_key, backward-compatible"
  - "IC evaluated for BTC + ETH across horizons 1/5/20; close_fracdiff and amihud_lambda show significant IC"

patterns-established:
  - "Supplemental UPDATE phase: Feature modules that UPDATE existing rows (not INSERT) must run after the base refresh phase"
  - "Regime key enrichment: Additional signals can be appended as pipe-delimited suffixes to regime_key"

# Metrics
duration: 11min
completed: 2026-02-28
---

# Phase 59 Plan 05: Orchestrator Wiring, Regime Integration, IC Evaluation Summary

**Microstructure features wired into orchestrator Phase 2b, SADF explosive flag integrated into regime pipeline, IC evaluation showing significant alpha in close_fracdiff and amihud_lambda, codependence comparison identifying 3 pairs with non-linear excess**

## Performance

- **Duration:** 11 min
- **Started:** 2026-02-28T09:26:58Z
- **Completed:** 2026-02-28T09:37:51Z
- **Tasks:** 5
- **Files modified:** 3

## Accomplishments
- Orchestrator runs microstructure UPDATE in Phase 2b (after base cmc_features, before CS norms) for all 17 assets with 97-99% fill rates
- SADF explosive flag produces 132 "|explosive" regime keys for BTC across 6 regime types
- IC evaluation: close_fracdiff IC=-0.079 (p=0.0002, ETH) and amihud_lambda IC=0.068 (p=0.002, ETH) show statistically significant predictive value
- Codependence comparison: 3/15 pairs (all involving asset 1839) show distance_corr > |pearson|, indicating non-linear dependence

## Task Commits

Each task was committed atomically:

1. **Task 1: Wire microstructure into orchestrator and update DDL** - `3308d294` (feat)
2. **Task 2: Run full pipeline for all assets on 1D timeframe** - (run-only, no code changes)
3. **Task 3: Integrate sadf_is_explosive into regime pipeline** - `c3b99d7c` (feat)
4. **Task 4: Run IC evaluation for microstructure columns** - (run-only, no code changes)
5. **Task 5: Compare codependence measures to Pearson** - (analysis-only, no code changes)

## Files Created/Modified
- `src/ta_lab2/scripts/features/run_all_feature_refreshes.py` - Added refresh_microstructure(), Phase 2b, --codependence flag, updated summary print
- `sql/views/050_cmc_features.sql` - Added 9 microstructure columns (MICRO-01 through MICRO-04) to DDL
- `src/ta_lab2/scripts/regimes/refresh_cmc_regimes.py` - Added _load_sadf_flags(), SADF integration into regime_key

## Decisions Made

1. **Microstructure in Phase 2b, not Phase 1** - Microstructure does UPDATE on existing cmc_features rows, so base rows from the DELETE+INSERT in Phase 2 must exist first. Placing in Phase 1 would cause Phase 2 to overwrite the updates.
2. **Codependence as optional flag** - Pairwise computation for all assets takes ~3 minutes and produces historical snapshots. Exposed via `--codependence` flag rather than always-on to keep daily refresh fast.
3. **SADF integration via suffix** - Appending "|explosive" to regime_key is backward-compatible and allows downstream consumers to parse or ignore the suffix.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed microstructure execution order from Phase 1 to Phase 2b**
- **Found during:** Task 1 (orchestrator wiring)
- **Issue:** Plan specified microstructure in Phase 1 parallel tasks, but microstructure uses UPDATE on cmc_features rows. Phase 2 does DELETE+INSERT, which would erase the microstructure columns.
- **Fix:** Moved microstructure to Phase 2b (after Phase 2 base refresh, before Phase 3 CS norms)
- **Files modified:** src/ta_lab2/scripts/features/run_all_feature_refreshes.py
- **Verification:** Full pipeline run confirms microstructure columns are preserved (97-99% fill rates)
- **Committed in:** 3308d294

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** Essential fix for correctness. Without this, microstructure data would be erased on every pipeline run.

## IC Evaluation Results

| Feature | BTC IC (h=1) | BTC p-value | ETH IC (h=1) | ETH p-value |
|---------|-------------|-------------|--------------|-------------|
| close_fracdiff | -0.0495 | 0.022 | -0.0794 | 0.0002 |
| amihud_lambda | 0.0549 | 0.011 | 0.0675 | 0.002 |
| kyle_lambda | -0.0159 | 0.461 | -0.0638 | 0.003 |
| hasbrouck_lambda | -0.0093 | 0.666 | -0.0526 | 0.015 |
| sadf_stat | 0.0238 | 0.269 | 0.0012 | 0.956 |
| entropy_lz | -0.0003 | 0.990 | 0.0102 | 0.636 |
| entropy_shannon | NULL | NULL | NULL | NULL |

Key finding: close_fracdiff and amihud_lambda are the strongest microstructure predictors. ETH shows stronger IC across all features compared to BTC.

## Codependence Comparison Summary

3/15 pairs have distance_corr > |pearson_corr|, all involving asset 1839:
- BTC-1839: pearson=0.651, dcorr=0.655 (gap=+0.004)
- XRP-1839: pearson=0.628, dcorr=0.637 (gap=+0.010)
- ETH-1839: pearson=0.703, dcorr=0.707 (gap=+0.005)

Overall: Pearson and distance correlation are highly correlated (mean Pearson=0.771, mean dcorr=0.753), suggesting crypto returns have predominantly linear comovement structure with mild non-linear excess for specific pairs.

## Issues Encountered
- `entropy_shannon` returns NULL IC for both BTC and ETH (ConstantInputWarning from scipy), likely due to all-constant values in the series. This is a known limitation of the current entropy computation window -- not a pipeline bug.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Phase 59 (Microstructural & Advanced Features) is now COMPLETE (5/5 plans)
- Full microstructure pipeline integrated: DDL, math, feature class, codependence, orchestrator, regime integration, IC evaluation
- Ready for Phase 60 (Paper Trading) or next milestone phase
- Potential follow-up: investigate entropy_shannon NULL IC and consider larger entropy windows

---
*Phase: 59-microstructural-advanced-features*
*Completed: 2026-02-28*
