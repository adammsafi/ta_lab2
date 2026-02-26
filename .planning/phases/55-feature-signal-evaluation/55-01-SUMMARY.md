---
phase: 55-feature-signal-evaluation
plan: "01"
subsystem: analysis
tags: [ic, spearman, feature-ranking, ic-ir, cmc_ic_results, regime, methodology-verification]

# Dependency graph
requires:
  - phase: 37-ic-evaluation
    provides: IC computation library (ic.py), run_ic_eval.py, run_ic_sweep.py, cmc_ic_results table
  - phase: 27-regime-integration
    provides: cmc_regimes table with l2_label (trend_state, vol_state)
  - phase: 42-feature-bakeoff
    provides: 47,614 IC rows for 5 TFs (1D, 7D, 14D, 30D, 90D) as Phase 42 baseline
provides:
  - methodology_verification.csv confirming Phase 42 IC methodology identical to recomputed (9/9 MATCH, delta <1e-8)
  - reports/evaluation/ directory established as Phase 55 artifact home
  - cmc_ic_results extended to 82,110 rows (4 new TFs: 3D, 5D, 10D, 21D)
  - Regime-conditional IC for BTC+ETH 1D (trend_state x3 + vol_state x3 = 6 regime slices)
  - ic_ranking_full.csv: 97 features ranked by mean |IC-IR| at horizon=1 arith
  - Bug fix: 'venue' text column excluded from IC feature discovery in run_ic_sweep.py
affects:
  - phase: 55-02 (signal evaluation uses IC rankings and cmc_ic_results)
  - phase: 55-03 (regime-conditional IC breakdown feeds regime-aware signal ranking)
  - future dashboard pages (Research Explorer: IC data available for 9 TFs)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Methodology verification: recompute a sample of known values and compare delta < 1e-6"
    - "reports/evaluation/ directory: Phase 55 evaluation artifacts go here (gitignored, generated)"
    - "IC sweep extension: add new TFs via --tf flag, upsert with --no-overwrite to preserve history"

key-files:
  created:
    - reports/evaluation/methodology_verification.csv
    - reports/evaluation/ic_ranking_full.csv
    - reports/evaluation/feature_ic_ranking.csv
  modified:
    - src/ta_lab2/scripts/analysis/run_ic_sweep.py

key-decisions:
  - "Run key TFs only (3D, 5D, 10D, 21D) rather than all 109 TFs — full sweep estimated at 9-10 hours"
  - "Use --no-overwrite for new TFs to preserve Phase 42 history; use --overwrite for regime breakdown refresh"
  - "reports/evaluation/ is gitignored (generated artifacts) — CSV files live on disk only, not in git"
  - "Methodology verification uses full-range Phase 42 rows (not the earlier 2019-2023 range rows)"

patterns-established:
  - "EVAL artifact home: reports/evaluation/ for all Phase 55 output CSVs"
  - "Verification pattern: query existing DB rows, recompute with same inputs, compare delta < 1e-6"

# Metrics
duration: 14min
completed: 2026-02-26
---

# Phase 55 Plan 01: IC Baseline Extension Summary

**Phase 42 IC methodology verified (9/9 MATCH, delta <1e-8); cmc_ic_results extended from 47,614 to 82,110 rows across 9 TFs with regime-conditional breakdown for BTC/ETH 1D**

## Performance

- **Duration:** 14 min
- **Started:** 2026-02-26T19:55:23Z
- **Completed:** 2026-02-26T20:09:57Z
- **Tasks:** 2
- **Files modified:** 1 (run_ic_sweep.py)

## Accomplishments

- Created `reports/evaluation/` directory as Phase 55 artifact home; generated `methodology_verification.csv` (9/9 MATCH) and `ic_ranking_full.csv` (97 features)
- Extended cmc_ic_results from 47,614 rows (Phase 42 baseline, 5 TFs) to 82,110 rows (+72.4%) by adding 4 new TFs: 3D, 5D, 10D, 21D
- Ran regime-conditional IC sweep for BTC (id=1) and ETH (id=1027) on 1D: 6 regime slices (trend_state: Up/Down/Sideways; vol_state: High/Low/Normal) producing 8,316 regime-IC rows
- Fixed bug in run_ic_sweep.py: `venue` text column (value 'CMC_AGG') was not excluded from feature discovery, causing ValueError during IC computation

## Task Commits

Each task was committed atomically:

1. **Task 1: Methodology verification + output directory setup** - `0470c806` (fix — includes bug fix for venue column)
2. **Task 2: Full IC sweep (key TFs) + ranking CSV** — no separate commit (sweep runs DB writes + CSV; plan metadata commit covers it)

**Plan metadata:** (this summary commit)

## Files Created/Modified

- `src/ta_lab2/scripts/analysis/run_ic_sweep.py` - Added 'venue' to _EXTRA_NON_FEATURE_COLS; already had --output-dir support
- `reports/evaluation/methodology_verification.csv` - Phase 42 vs recomputed IC comparison (9/9 MATCH, all delta <1e-8); gitignored
- `reports/evaluation/ic_ranking_full.csv` - 97 features ranked by mean |IC-IR| aggregated across all TFs; gitignored
- `reports/evaluation/feature_ic_ranking.csv` - Duplicate ranking CSV also written by run_ic_sweep --output-dir; gitignored

## Decisions Made

- **Staged sweep approach:** Per context note, ran key TFs (3D, 5D, 10D, 21D) rather than all 109 to complete within session. Full 109-TF sweep estimated at 9-10 hours; can be run as background job with `--no-overwrite` to preserve existing rows.
- **--no-overwrite for new TFs, --overwrite for regime refresh:** New TFs use append-only semantics to preserve Phase 42 rows unchanged; regime breakdown for BTC/ETH 1D used overwrite to refresh with updated 100-column feature set.
- **reports/evaluation/ is gitignored:** Consistent with reports/bakeoff/ which is also gitignored. Generated CSVs are disk artifacts, not source-controlled.
- **Methodology verification uses full-range rows:** The cmc_ic_results table has two sets of rows for some features (different train windows). Verification compared against the Phase 42 full-range rows (train_start ~2010), not earlier evaluation rows.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed 'venue' text column crashing IC computation**
- **Found during:** Task 1 (when running dry-run and first real sweep for 3D TF)
- **Issue:** `venue` column in `cmc_features` contains text string 'CMC_AGG' and was not excluded from feature discovery via `_EXTRA_NON_FEATURE_COLS`. This caused `ValueError: could not convert string to float: 'CMC_AGG'` during `std()` computation in `_compute_single_ic()`.
- **Fix:** Added `"venue"` to `_EXTRA_NON_FEATURE_COLS` frozenset in run_ic_sweep.py. Feature column count dropped from 101 to 100 (correct).
- **Files modified:** `src/ta_lab2/scripts/analysis/run_ic_sweep.py`
- **Verification:** 3D sweep completed successfully after fix: 2,464 IC rows written for BTC+ETH 3D.
- **Committed in:** `0470c806` (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - Bug)
**Impact on plan:** Fix necessary for correctness — sweep would fail for any TF with venue='CMC_AGG' data. No scope creep.

## Issues Encountered

- **methodology_verification.csv initial WARN:** First attempt compared `ret_arith` against the 2019-2023 range row (the wrong Phase 42 row). Fixed by explicitly selecting the full-range rows for comparison. Final result: 9/9 MATCH.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- cmc_ic_results has 82,110 rows covering 9 TFs (1D, 3D, 5D, 7D, 10D, 14D, 21D, 30D, 90D)
- Regime-conditional IC available for BTC+ETH 1D (trend_state + vol_state, 3 labels each)
- 97 features ranked by mean |IC-IR| in `reports/evaluation/ic_ranking_full.csv`
- Full 109-TF sweep can be run as background job: `python -m ta_lab2.scripts.analysis.run_ic_sweep --all --skip-ama --no-overwrite --output-dir reports/evaluation`
- Concern: only 2 assets (BTC, ETH) were swept on 3D — 8 qualifying assets exist for 5D/10D/21D; broader coverage may be needed for Phase 55-02 signal evaluation

---
*Phase: 55-feature-signal-evaluation*
*Completed: 2026-02-26*
