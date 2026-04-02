---
phase: 95-ama-ic-staleness-signal-scores
verified: 2026-03-28T22:00:00Z
status: passed
score: 8/8 must-haves verified
---

# Phase 95: AMA-Aware IC Staleness & Real Signal Scores Verification Report

**Phase Goal:** Make IC staleness monitor cover all 20 active features (including 18 AMA features in ama_multi_tf_u) and replace uniform signal_scores=1.0 with IC-weighted scores from feature values
**Verified:** 2026-03-28
**Status:** PASSED
**Re-verification:** No -- initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | ICStalenessMonitor.run() checks all 20 active features (18 AMA + 2 bar-level) | VERIFIED | `run()` calls `parse_active_features()` (line 593-595), slices to `MAX_ACTIVE_FEATURES=20` (line 51,600), iterates all features through `_check_one()` (line 621-622). Logs AMA vs bar-level counts (lines 605-613). |
| 2 | AMA features load from ama_multi_tf_u with correct filters (alignment_source, roll, venue_id) | VERIFIED | `_load_ama_feature()` (lines 146-221) queries `ama_multi_tf_u` with all critical filters: `alignment_source = 'multi_tf'`, `roll = FALSE`, `venue_id = :venue_id`, `indicator = :indicator`, `LEFT(params_hash, 8) = :params_hash` (lines 163-176). |
| 3 | BL weight-halving triggers correctly for decaying AMA features | VERIFIED | `_check_one()` calls `_write_weight_override()` on decay detection (lines 704-712), which inserts `multiplier=0.5` into `dim_ic_weight_overrides` (line 335). Works for any feature name including AMA features -- no source-specific branching in the weight override path. |
| 4 | signal_scores computed from per-asset latest feature values (not uniform 1.0) | VERIFIED | `_load_signal_scores()` (lines 182-310) queries latest values per asset per feature. Called at line 814 in the BL path. The old `pd.DataFrame(1.0, ...)` is replaced with real values. Remaining `1.0` references are only in fallback/error paths (lines 823-830, 837-845). |
| 5 | AMA feature values loaded from ama_multi_tf_u.d1 (stationary momentum signal) | VERIFIED | `_load_signal_scores()` AMA branch (lines 250-275) uses `a.d1 AS val` from `ama_multi_tf_u` with all critical filters (alignment_source, roll, venue_id, indicator, params_hash). |
| 6 | Bar-level feature values loaded from features table | VERIFIED | `_load_signal_scores()` bar-level branch (lines 228-248) uses `DISTINCT ON (f.id)` query with `information_schema` column validation (lines 206-218). |
| 7 | Fallback to uniform 1.0 with WARNING when feature values unavailable | VERIFIED | Two fallback paths: (1) `_load_signal_scores()` exception caught at lines 820-830, falls back to uniform 1.0 with WARNING. (2) No common features between signal_scores and ic_ir_matrix falls back at lines 836-845. |
| 8 | Paper executor receives non-uniform signal_scores for BL view construction | VERIFIED | `signal_scores` passed to `bl_builder.run(signal_scores=signal_scores, ...)` at line 861. BLAllocationBuilder uses these for view construction via `signals_to_mu()`. |

**Score:** 8/8 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/ta_lab2/scripts/analysis/run_ic_staleness_check.py` | AMA-aware IC staleness monitor | VERIFIED (827 lines) | Contains `ama_multi_tf_u` queries, `parse_active_features()` import, `_load_ama_feature()` helper, `MAX_ACTIVE_FEATURES=20`. No stubs, no TODOs. |
| `src/ta_lab2/scripts/portfolio/refresh_portfolio_allocations.py` | Real signal_scores from feature values | VERIFIED (1044 lines) | Contains `_load_signal_scores()` helper (lines 182-310) with dual-source loading, `ama_multi_tf_u.d1` queries, fallback logic. No stubs, no TODOs. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `_load_close_and_feature()` | `ama_multi_tf_u` | SQL query with indicator/params_hash | WIRED | Line 84 branches to `_load_ama_feature()` which queries `ama_multi_tf_u` (line 165) |
| `ICStalenessMonitor.run()` | `parse_active_features()` | Import from bakeoff_orchestrator | WIRED | Line 593 imports, line 595 calls. Returns list of dicts with name/indicator/params_hash/source keys. |
| `_load_signal_scores()` | `ama_multi_tf_u.d1` | SQL DISTINCT ON query | WIRED | Lines 253-263 query `a.d1 AS val FROM ama_multi_tf_u` with all required filters |
| `signal_scores DataFrame` | `BLAllocationBuilder.run()` | `signal_scores=` parameter | WIRED | Line 861 passes `signal_scores=signal_scores` to `bl_builder.run()` |

### Requirements Coverage (ROADMAP Success Criteria)

| Criterion | Status | Evidence |
|-----------|--------|----------|
| 1. IC staleness monitor loads AMA features from ama_multi_tf_u | SATISFIED | `_load_ama_feature()` queries `ama_multi_tf_u` with all critical filters |
| 2. ICStalenessMonitor.run() checks all 20 active features | SATISFIED | `parse_active_features()` returns all 20, `MAX_ACTIVE_FEATURES=20` |
| 3. BL weight-halving triggers correctly for decaying AMA features | SATISFIED | `_write_weight_override()` works identically for AMA and bar-level features |
| 4. signal_scores computed from per-asset IC-IR weights (not uniform 1.0) | SATISFIED | `_load_signal_scores()` loads real d1/feature values per asset |
| 5. Paper executor receives non-uniform signal_scores | SATISFIED | `bl_builder.run(signal_scores=signal_scores)` at line 861 |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| (none) | - | - | - | No TODOs, FIXMEs, placeholders, or stubs found in either modified file |

### Human Verification Required

### 1. End-to-end IC staleness dry-run
**Test:** Run `python -m ta_lab2.scripts.analysis.run_ic_staleness_check --dry-run --verbose --ids 1`
**Expected:** Logs should show checks for ~20 features (not 2), with AMA features showing "ama_multi_tf_u" in debug output
**Why human:** Requires live DB connection to verify actual data loading

### 2. End-to-end portfolio refresh dry-run
**Test:** Run `python -m ta_lab2.scripts.portfolio.refresh_portfolio_allocations --dry-run --verbose --ids 1,1027`
**Expected:** Log should show "loaded real signal_scores for N assets x M features" (not "uniform signal_scores")
**Why human:** Requires live DB connection and ic_results data

### 3. Signal score values are non-trivial
**Test:** Add a temporary debug log in `_load_signal_scores` to print the resulting DataFrame
**Expected:** Values should vary across assets and features (not all identical)
**Why human:** Need to inspect actual numeric values from DB

### Gaps Summary

No gaps found. All 8 must-haves are verified at all three levels (existence, substantive, wired). Both modified files contain real implementations with proper SQL queries, error handling, fallback paths, and correct wiring to upstream (parse_active_features, ama_multi_tf_u) and downstream (BLAllocationBuilder) components. The old `_load_active_features()` function and `_FEATURE_SELECTION_YAML` constant have been removed. The `TODO(Phase 87)` comment has been removed. All remaining references to "uniform signal_scores=1.0" are in error/fallback paths only.

---

_Verified: 2026-03-28_
_Verifier: Claude (gsd-verifier)_
