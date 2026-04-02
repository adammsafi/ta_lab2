---
phase: 106-custom-composite-indicators
plan: 03
subsystem: analysis
tags: [composite-indicators, validation, permutation-ic, fdr, cpcv, dim_feature_registry]

# Dependency graph
requires:
  - phase: 106-02
    provides: run_composite_refresh.py + 22280 rows of tf_alignment_score in features table

provides:
  - run_composite_validation.py: 4-layer validation gauntlet (permutation IC, FDR, CPCV, held-out)
  - composite_validation_results.json: per-composite per-layer statistics
  - docs/COMPOSITES.md: full documentation of all 6 formulas, validation results, coverage notes
  - Finding: tf_alignment_score passed permutation+FDR+CPCV but failed held-out (sign flip in 2022-2025)

affects:
  - production server validation (run when ama_multi_tf + price_bars_multi_tf + HL sync available)
  - dim_feature_registry (promotion target when production run succeeds)
  - Phase 106 complete (all 3 plans done)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - 4-layer validation gauntlet: permutation IC -> FDR -> CPCV -> held-out (one-shot)
    - insufficient_data marker for composites with zero qualifying assets (not "failed")
    - CPCVSplitter with synthetic timeline for pooled cross-asset data
    - Fallback chain: Option A (strict) -> Option B (same-sign) -> Option C (strong IC+p)

key-files:
  created:
    - src/ta_lab2/scripts/analysis/run_composite_validation.py
    - docs/COMPOSITES.md

key-decisions:
  - "0 composites promoted on local DB: intellectually honest result (sign flip disqualifies tf_alignment_score)"
  - "5/6 composites marked insufficient_data not failed: reflects missing base tables locally, not formula errors"
  - "Synthetic monotonic timeline for pooled CPCV: CPCVSplitter needs monotonic DatetimeIndex; pooling across assets breaks chronology, so synthetic 1D range used"
  - "Option B fallback failed (sign flip, not marginal); Option C failed (IC=0.0300 not > 0.03); 0 promotions is correct"

patterns-established:
  - "Composite validation pattern: pool (composite, fwd_ret) pairs across qualifying assets -> permutation IC -> FDR -> per-composite CPCV -> one-shot held-out"
  - "insufficient_data handling: require MIN_VALID_PAIRS=100 non-null pairs; below threshold = insufficient_data (p=1.0 sentinel for FDR)"

# Metrics
duration: 30min
completed: 2026-04-02
---

# Phase 106 Plan 03: Composite Validation Gauntlet Summary

**4-layer validation gauntlet for 6 proprietary composites: tf_alignment_score passed permutation (IC=+0.030, p=0.000) + FDR + CPCV (15 paths, 86.7% positive) but failed held-out with sign flip (IC=-0.008, 2022-2025 regime shift); 0 promotions on local DB; 5/6 composites insufficient_data (missing base tables)**

## Performance

- **Duration:** 30 min
- **Started:** 2026-04-02T00:38:21Z
- **Completed:** 2026-04-02T01:08:00Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Created run_composite_validation.py (991 lines) implementing all 4 layers with fallback chain
- Ran validation end-to-end: tf_alignment_score is the only testable composite (22,280 rows), passed 3/4 layers
- Discovered held-out sign flip (training +0.030 vs held-out -0.008) indicating regime-dependent signal in 2022-2025
- Created COMPOSITES.md (328 lines) with all 6 formulas, actual validation numbers, coverage notes, and reproduction commands
- Confirmed CPCVSplitter API works correctly with pooled cross-asset data via synthetic timeline
- Results JSON saved to reports/composites/composite_validation_results.json

## Task Commits

Each task was committed atomically:

1. **Task 1: Build and run the 4-layer validation gauntlet** - `7529b271` (feat)
2. **Task 2: Create COMPOSITES.md documentation** - `41a2b86a` (docs)

## Files Created/Modified

- `src/ta_lab2/scripts/analysis/run_composite_validation.py` - Full 4-layer validation script: data loading, permutation IC, FDR, CPCV via CPCVSplitter, held-out gate, promotion to dim_feature_registry, JSON export
- `docs/COMPOSITES.md` - All 6 composite formulas, intuition, validation table with real numbers, sign flip analysis, coverage notes, reproduction commands

## Decisions Made

- **0 promotions is the correct result:** tf_alignment_score has a genuine held-out sign flip. The signal is positive in 2010-2022 (training) and negative in 2022-2025 (held-out). Promoting it would be intellectually dishonest. The gauntlet worked as intended.
- **insufficient_data vs failed distinction:** 5 composites have p_value=1.0 sentinel for FDR but are marked `insufficient_data` in status. This preserves the distinction between "we couldn't test" (missing data) and "we tested and it failed". This matters for production revalidation.
- **Synthetic 1D timeline for CPCV:** CPCVSplitter requires monotonic DatetimeIndex. Pooling training data across 7 assets breaks chronological order. Solution: use a synthetic 1D date range matching the number of valid pairs. The CPCV purge+embargo logic still works because it uses positional splits, not calendar purge.
- **Option C threshold is exclusive (> 0.03):** tf_alignment_score has IC=0.0300 exactly, which fails `abs(ic) > 0.03`. This is correct — the plan specifies "greater than", not "greater than or equal to".

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] OutOfBoundsDatetime in synthetic CPCV timeline**

- **Found during:** Task 1 (first execution of validation script)
- **Issue:** `pd.date_range("2010-01-01", periods=17813, freq="10D", tz="UTC")` raised `OutOfBoundsDatetime` because 17813 * 10D > pandas datetime64 max (year 2259).
- **Fix:** Changed `freq="10D"` to `freq="1D"` — the frequency is irrelevant for CPCV since we use positional splits, not calendar-based purging.
- **Files modified:** `src/ta_lab2/scripts/analysis/run_composite_validation.py`
- **Verification:** Script ran to completion without datetime error.
- **Committed in:** `7529b271` (included in main task commit)

**2. [Rule 1 - Bug] Output path parents[5] was wrong (went one directory above project root)**

- **Found during:** Task 1 (first execution; JSON saved to `C:\Users\asafi\Downloads\reports\` instead of `ta_lab2\reports\`)
- **Issue:** `Path(__file__).parents[5]` resolved to `C:\Users\asafi\Downloads` (one level above project). The script is at `src/ta_lab2/scripts/analysis/run_composite_validation.py` = 5 segments from root, so `parents[4]` = project root.
- **Fix:** Changed `parents[5]` to `parents[4]`.
- **Files modified:** `src/ta_lab2/scripts/analysis/run_composite_validation.py`
- **Verification:** JSON now saves to `ta_lab2/reports/composites/composite_validation_results.json`.
- **Committed in:** `7529b271` (included in main task commit)

**3. [Rule 1 - Bug] ruff F841 unused variables (ts_arr, results: list[dict])**

- **Found during:** Task 1 (pre-commit hook caught during git commit)
- **Issue:** Two variables assigned but never used: `ts_arr = ts_valid.values` (leftover debug line) and `results: list[dict] = []` (intermediate accumulator replaced by direct `all_results` list).
- **Fix:** Removed both unused assignments.
- **Files modified:** `src/ta_lab2/scripts/analysis/run_composite_validation.py`
- **Verification:** `ruff lint` passes cleanly.
- **Committed in:** `7529b271` (re-staged after ruff fix)

---

**Total deviations:** 3 auto-fixed (all Rule 1 - Bug)
**Impact on plan:** All 3 auto-fixes necessary for correctness. No scope creep.

## Issues Encountered

- **Local DB missing ama_multi_tf and price_bars_multi_tf:** Only `_u` unified views exist. Affects 5/6 composites (all except tf_alignment_score). This is a known local DB limitation documented in 106-02 SUMMARY. The validation script handles it gracefully with `insufficient_data` status.
- **tf_alignment_score held-out sign flip:** The most interesting finding. Training IC = +0.030 (positive, statistically significant). Held-out IC = -0.008 (negative, sign flip). This suggests the composite's predictive power is regime-conditional — it worked in the 2010-2022 bull market but reversed during the 2022 bear market and subsequent recovery. This is a real signal about the composite's limitations, not a data quality issue.
- **reports/ directory is .gitignored:** The `reports/composites/composite_validation_results.json` output was produced and saved locally but cannot be committed to git. It is referenced in COMPOSITES.md and generated fresh each validation run.

## Next Phase Readiness

- Phase 106 is complete (all 3 plans: 106-01 formulas+migration, 106-02 refresh orchestrator, 106-03 validation+docs).
- Production server revalidation recommended once ama_multi_tf + price_bars_multi_tf + HL sync are available. Run `run_composite_validation.py` on Oracle VM to test all 6 composites.
- tf_alignment_score may be worth re-examining with regime conditioning (validate separately on bull/bear/recovery regimes). This is a potential Phase 112+ research question.
- dim_feature_registry is ready to receive promotions when production run succeeds.

---
*Phase: 106-custom-composite-indicators*
*Completed: 2026-04-02*
