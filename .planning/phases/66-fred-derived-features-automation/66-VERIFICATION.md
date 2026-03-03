---
phase: 66-fred-derived-features-automation
verified: 2026-03-03T05:00:00Z
status: passed
score: 5/5 must-haves verified
gaps: []
---

# Phase 66: FRED Derived Features and Automation -- Verification Report

**Phase Goal:** All remaining macro features -- credit stress, financial conditions, carry trade, fed regime classification, and CPI proxy -- are computed and the entire macro feature pipeline runs automatically in the daily refresh.
**Verified:** 2026-03-03T05:00:00Z
**Status:** PASSED
**Re-verification:** No -- initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Credit stress (HY OAS level, 5d change, 30d z-score), financial conditions (NFCI level, 4-week direction), and M2 YoY change are populated | VERIFIED | feature_computer.py:282-313 computes from BAMLH0A0HYM2/NFCI/M2SL. All columns in migration and whitelist. |
| 2 | Carry trade features and carry momentum indicator are populated | VERIFIED | feature_computer.py:316-374 computes from DEXJPUS with rolling(20, min_periods=16). Elevated 2.0 threshold when carry spread positive. |
| 3 | Net liquidity 365d rolling z-score and dual-window trend detection are populated | VERIFIED | feature_computer.py:335-349. _rolling_zscore(nl, 365) + ma30 vs ma150. WARMUP_DAYS=400. |
| 4 | Fed regime classification and TARGET_MID/TARGET_SPREAD are populated | VERIFIED | feature_computer.py:193-252. _compute_fed_regime() with data-driven thresholds. |
| 5 | run_daily_refresh.py runs macro after desc_stats and before regimes | VERIFIED | run_daily_refresh.py:2199-2213. desc_stats(2190) -> macro(2203) -> regimes(2213). |

**Score:** 5/5 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| alembic/versions/c4d5e6f7a8b9_fred_phase66_derived_columns.py | 25-column ALTER TABLE | VERIFIED | 213 lines. 25 add + 25 drop. Schema=fred. |
| src/ta_lab2/macro/fred_reader.py | 18 series in SERIES_TO_LOAD | VERIFIED | 165 lines. 11 Phase 65 + 7 Phase 66. |
| src/ta_lab2/macro/forward_fill.py | 18 FFILL_LIMITS entries | VERIFIED | 208 lines. daily=5, weekly=10, monthly=45. |
| src/ta_lab2/macro/feature_computer.py | compute_derived_features_66() | VERIFIED | 552 lines. 18 _RENAME_MAP entries. 25 Phase 66 db_columns. No stubs. |
| src/ta_lab2/scripts/macro/refresh_macro_features.py | WARMUP_DAYS=400 + summary log | VERIFIED | 522 lines. 13 feature groups. Staleness check. |
| src/ta_lab2/scripts/run_daily_refresh.py | Macro wired in pipeline | VERIFIED | Line 2203 between desc_stats and regimes. |

### Key Link Verification

| From | To | Via | Status |
|------|----|-----|--------|
| alembic migration | fred.fred_macro_features | op.add_column schema=fred | VERIFIED |
| SERIES_TO_LOAD | fred.series_values | load_series_wide() SQL | VERIFIED |
| compute_derived_features_66() | compute_macro_features() | Line 468 call | VERIFIED |
| _compute_fed_regime() | compute_derived_features_66() | Line 352 in-place call | VERIFIED |
| refresh_macro_features.py | compute_macro_features() | Import line 34 | VERIFIED |
| run_daily_refresh.py | refresh_macro_features.py | Subprocess line 1646 | VERIFIED |
| db_columns whitelist | 25 Phase 66 columns | Lines 512-530 | VERIFIED |

### Requirements Coverage

| Requirement | Status | Evidence |
|-------------|--------|----------|
| FRED-08: Credit stress | SATISFIED | hy_oas_level, 5d_change, 30d_zscore from BAMLH0A0HYM2 |
| FRED-09: Financial conditions | SATISFIED | nfci_level, nfci_4wk_direction from NFCI |
| FRED-10: M2 money supply | SATISFIED | m2_yoy_pct via pct_change(365) from M2SL |
| FRED-11: Carry trade | SATISFIED | dexjpus_level, 5d_pct_change, 20d_vol, daily_zscore |
| FRED-12: Net liquidity z-score | SATISFIED | 365d z-score + 30d/150d trend |
| FRED-13: Fed regime | SATISFIED | Structure + trajectory classification |
| FRED-14: Carry momentum | SATISFIED | Binary flag with elevated threshold |
| FRED-15: CPI surprise proxy | SATISFIED | MoM deviation from 3-month trend |
| FRED-16: TARGET_MID/SPREAD | SATISFIED | (upper+lower)/2 and upper-lower |
| FRED-17: Automation | SATISFIED | Wired in run_daily_refresh.py --all |

### Anti-Patterns Found

No TODO/FIXME/placeholder patterns found in any Phase 66 artifact.

### Human Verification Required

#### 1. Database Column Population
**Test:** Run refresh_macro_features --full --verbose
**Expected:** 13/13 feature groups [OK]
**Why human:** Requires live DB with FRED data

#### 2. Fed Regime Sanity
**Test:** Query fred.fred_macro_features for recent fed_regime_structure
**Expected:** target-range for 2024+, target_mid near FOMC midpoint
**Why human:** Requires live DB

#### 3. Daily Refresh E2E
**Test:** Run run_daily_refresh --all --ids 1 --dry-run
**Expected:** macro_features between desc_stats and regimes
**Why human:** Requires CLI execution

### Gaps Summary

No gaps found. All 5 observable truths verified. All 6 artifacts exist,
are substantive (552/165/208/522/213 lines), contain no stub patterns,
and are properly wired. All 10 FRED requirements (FRED-08 through FRED-17)
are satisfied.

Key highlights:
- _rolling_zscore() uses 80% min_periods
- M2 YoY uses pct_change(365) not pct_change(1)
- Fed regime uses data-driven thresholds
- carry_momentum elevated threshold when carry spread positive
- WARMUP_DAYS=400 for 365d z-score boundary
- 13-group summary log with staleness detection
- All columns in db_columns whitelist

---

_Verified: 2026-03-03T05:00:00Z_
_Verifier: Claude (gsd-verifier)_
