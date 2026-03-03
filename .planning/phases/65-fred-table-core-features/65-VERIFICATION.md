---
phase: 65-fred-table-core-features
verified: 2026-03-03T03:34:43Z
status: passed
score: 5/5 must-haves verified
re_verification: false
---

# Phase 65: FRED Table & Core Features Verification Report

**Phase Goal:** Macro features are available as a daily-aligned table in marketdata, covering rate spreads, yield curve, VIX regime, and dollar strength -- the foundation every downstream macro consumer reads from.
**Verified:** 2026-03-03T03:34:43Z
**Status:** passed
**Re-verification:** No -- initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | fred_macro_features table exists with PK (date) and can be queried for any calendar date in the FRED history range | VERIFIED | Alembic migration revision b3c4d5e6f7a8 (file a1b2c3d4e5f6_fred_macro_features.py) creates fred.fred_macro_features with PrimaryKeyConstraint(date), 27 columns, schema=fred. Migration is current alembic head. |
| 2 | Mixed-frequency FRED series (monthly, weekly) appear as daily rows with correct forward-fill limits and source_freq provenance | VERIFIED | forward_fill.py: FFILL_LIMITS has WALCL=10, WTREGEN=10 (weekly), IRSTCI01JPM156N=45, IRLTLT01JPM156N=45 (monthly). ffill_with_source_date() returns provenance dates. compute_macro_features() writes source_freq_walcl=weekly and source_freq_irstci01jpm156n=monthly columns. |
| 3 | Net liquidity proxy (WALCL - WTREGEN - RRPONTSYD) computes correctly with weekly forward-fill | VERIFIED | feature_computer.py lines 100-101: result[net_liquidity] = result[WALCL] - result[WTREGEN] - result[RRPONTSYD]. fred_reader.py SERIES_TO_LOAD includes WTREGEN (line 30). Bug fix 6d9866f8 corrects days_since from (df_derived.index - src).days to df_derived.index.to_series() - src then delta.dt.days. |
| 4 | Rate spread features (us_jp_rate_spread, us_ecb_rate_spread, us_jp_10y_spread) and yield curve features (T10Y2Y level, yc_slope_change_5d) are populated | VERIFIED | feature_computer.py: us_jp_rate_spread = DFF - IRSTCI01JPM156N (line 107), us_ecb_rate_spread = DFF - ECBDFR (line 113), us_jp_10y_spread = DGS10 - IRLTLT01JPM156N (line 119), yc_slope_change_5d = T10Y2Y.diff(5) (line 125). All columns in migration DDL. |
| 5 | VIX regime labels (calm/elevated/crisis) and dollar strength features (DTWEXBGS level, 5d/20d changes) are populated | VERIFIED | feature_computer.py lines 51-53: _VIX_BINS=[0.0,15.0,25.0,inf], _VIX_LABELS=[calm,elevated,crisis]. pd.cut() with astype(str) + explicit None replacement for NaN VIXCLS (line 139). dtwexbgs_5d_change=DTWEXBGS.diff(5), dtwexbgs_20d_change=DTWEXBGS.diff(20) at lines 146-147. |

**Score:** 5/5 truths verified
---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| alembic/versions/a1b2c3d4e5f6_fred_macro_features.py | Alembic migration creating fred.fred_macro_features | VERIFIED | EXISTS. Internal revision=b3c4d5e6f7a8, down_revision=a1b2c3d4e5f7. 27 columns defined. Current alembic head. Symmetric downgrade: drops index then table. 119 lines. |
| src/ta_lab2/macro/__init__.py | Package init re-exporting public API | VERIFIED | EXISTS. Exports load_series_wide, forward_fill_with_limits, compute_macro_features. 19 lines. Imported by refresh_macro_features.py line 34. |
| src/ta_lab2/macro/fred_reader.py | SERIES_TO_LOAD (11 series), load_series_wide() | VERIFIED | EXISTS. 151 lines. SERIES_TO_LOAD lists all 11 FRED series including WTREGEN (line 30). load_series_wide() queries fred.series_values, pivots wide, reindexes to freq=D calendar-daily. |
| src/ta_lab2/macro/forward_fill.py | FFILL_LIMITS, SOURCE_FREQ, ffill_with_source_date(), forward_fill_with_limits() | VERIFIED | EXISTS. 194 lines. FFILL_LIMITS: weekly=10, monthly=45, daily=5. ffill_with_source_date() returns (filled_values, source_observation_dates) tuple. |
| src/ta_lab2/macro/feature_computer.py | compute_derived_features(), compute_macro_features() with bug fix | VERIFIED | EXISTS. 285 lines. Bug fix 6d9866f8: delta = df_derived.index.to_series() - src; days = delta.dt.days at lines 247-248. All FRED-03 through FRED-07 derivations implemented. |
| src/ta_lab2/scripts/macro/__init__.py | Scripts macro package init | VERIFIED | EXISTS. 4 lines (non-empty docstring). |
| src/ta_lab2/scripts/macro/refresh_macro_features.py | CLI with watermark/warmup/upsert | VERIFIED | EXISTS. 438 lines. WARMUP_DAYS=60, get_compute_window() queries MAX(date) watermark, check_fred_staleness() warns at 48h (never blocks), upsert_macro_features() uses temp table + ON CONFLICT (date) DO UPDATE. Argparse: --dry-run/--full/--verbose/--start-date/--end-date. |
| src/ta_lab2/scripts/run_daily_refresh.py | --macro flag, run_macro_features(), positioned after desc_stats before regimes | VERIFIED | MODIFIED. TIMEOUT_MACRO=300 (line 89). run_macro_features() at line 1629 invokes ta_lab2.scripts.macro.refresh_macro_features subprocess. run_macro=(args.macro or args.all) and not args.no_macro (line 2072). Execution order: desc_stats block (line 2190) -> macro block (line 2203) -> regimes block (line 2213). |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| refresh_macro_features.py | ta_lab2.macro.feature_computer | from ta_lab2.macro.feature_computer import compute_macro_features (line 34) | WIRED | Direct import, called at line 386 inside main(). |
| compute_macro_features() | fred.series_values | load_series_wide() -> pd.read_sql(SELECT series_id, date, value FROM fred.series_values) | WIRED | fred_reader.py lines 102-110: parameterized query with series_id=ANY(:ids). Result is full pipeline input. |
| upsert_macro_features() | fred.fred_macro_features | temp table + ON CONFLICT (date) DO UPDATE | WIRED | refresh_macro_features.py lines 249-276: CREATE TEMP TABLE _macro_staging (LIKE fred.fred_macro_features INCLUDING DEFAULTS), then INSERT INTO fred.fred_macro_features ... ON CONFLICT (date) DO UPDATE SET ... |
| run_daily_refresh.py --macro/--all | refresh_macro_features.py | subprocess.run([sys.executable, -m, ta_lab2.scripts.macro.refresh_macro_features]) | WIRED | run_macro_features() lines 1643-1647. |
| Pipeline: macro stage position | After desc_stats, before regimes | Execution order in run_daily_refresh.py | WIRED | desc_stats block at line 2190, macro block at line 2203, regimes block at line 2213. |
| days_since computation | .dt.days accessor | Bug fix commit 6d9866f8 | WIRED | feature_computer.py lines 247-248: delta = df_derived.index.to_series() - src; days = delta.dt.days. Prevents AttributeError on Series. |
---

### Requirements Coverage

| Requirement | Status | Evidence |
|-------------|--------|----------|
| FRED-01: fred_macro_features table with PK(date) | SATISFIED | Migration b3c4d5e6f7a8 creates table with PrimaryKeyConstraint(date). 27 columns. Current alembic head. |
| FRED-02: Mixed-frequency ffill with source_freq provenance and limit guards | SATISFIED | FFILL_LIMITS: weekly=10, monthly=45. source_freq_* columns populated in compute_macro_features(). ffill_with_source_date() tracks provenance for days_since_*. |
| FRED-03: Net liquidity = WALCL - WTREGEN - RRPONTSYD, WTREGEN in VM collection | SATISFIED | Formula at feature_computer.py line 100-101. WTREGEN in SERIES_TO_LOAD at fred_reader.py line 30. Graceful NaN degradation if WTREGEN missing. |
| FRED-04: Rate spread features (us_jp, us_ecb, us_jp_10y) | SATISFIED | Three spread computations at lines 106-121 of feature_computer.py. All in migration DDL. |
| FRED-05: T10Y2Y level stored, yc_slope_change_5d as 5-day delta | SATISFIED | t10y2y raw column in DDL. yc_slope_change_5d = T10Y2Y.diff(5) at line 125. |
| FRED-06: VIX regime (calm < 15, elevated 15-25, crisis > 25) | SATISFIED | _VIX_BINS=[0.0,15.0,25.0,inf], _VIX_LABELS=[calm,elevated,crisis] at lines 52-53. None substitution for NaN VIXCLS at line 139. |
| FRED-07: DTWEXBGS level, 5d/20d changes | SATISFIED | dtwexbgs raw column in DDL. dtwexbgs_5d_change = DTWEXBGS.diff(5), dtwexbgs_20d_change = DTWEXBGS.diff(20) at lines 146-147. |

All 7 FRED requirements (FRED-01 through FRED-07) satisfied by structural analysis.

---

### Anti-Patterns Found

None. Full scan of all Phase 65 source files (feature_computer.py, forward_fill.py, fred_reader.py, refresh_macro_features.py, a1b2c3d4e5f6_fred_macro_features.py) returned zero results for: TODO, FIXME, placeholder, coming soon, not implemented, stub, empty return patterns.

---

### Human Verification Required

The following items cannot be verified programmatically from the codebase structure alone:

#### 1. Live data query: fred_macro_features populated with correct row count

**Test:** Connect to marketdata database and run:

    SELECT COUNT(*), MIN(date), MAX(date) FROM fred.fred_macro_features;
    SELECT net_liquidity, vix_regime, us_jp_rate_spread, dtwexbgs
    FROM fred.fred_macro_features ORDER BY date DESC LIMIT 5;

**Expected:** ~9558 rows from 2000-01-01 to ~2026-03-02, non-NULL net_liquidity, vix_regime in (calm, elevated, crisis), non-NULL rate spreads.
**Why human:** Requires live DB access to verify data was actually inserted (migration applied + pipeline run).

#### 2. Incremental refresh idempotency

**Test:** Run python -m ta_lab2.scripts.macro.refresh_macro_features twice in succession.
**Expected:** Row count unchanged (9558) on second run. Second run processes ~60+N rows (watermark window), not full history.
**Why human:** Requires executing the script against live DB.

#### 3. days_since_walcl range validation

**Test:** SELECT AVG(days_since_walcl), MAX(days_since_walcl) FROM fred.fred_macro_features WHERE date >= CURRENT_DATE - 30
**Expected:** Values in 0-10 range reflecting weekly WALCL publication cadence. Bug fix 6d9866f8 ensures this is correct.
**Why human:** Requires live DB access and recent data.

---

### Gaps Summary

No gaps. All 5 must-have truths verified. All 8 required artifacts confirmed to exist, are substantive (4-438 lines, zero stubs), and are correctly wired. All 7 FRED requirements map to implemented code. The bug fix (.days -> .dt.days) is confirmed committed in 6d9866f8 and present in the current codebase at feature_computer.py lines 247-248.

---

## Artifact Line Counts

| File | Lines | Exists | Substantive | Wired |
|------|-------|--------|-------------|-------|
| alembic/versions/a1b2c3d4e5f6_fred_macro_features.py | 119 | YES | YES | YES (head migration) |
| src/ta_lab2/macro/__init__.py | 19 | YES | YES | YES (imported by refresh script) |
| src/ta_lab2/macro/fred_reader.py | 151 | YES | YES | YES (called by feature_computer) |
| src/ta_lab2/macro/forward_fill.py | 194 | YES | YES | YES (called by feature_computer) |
| src/ta_lab2/macro/feature_computer.py | 285 | YES | YES | YES (called by refresh script) |
| src/ta_lab2/scripts/macro/__init__.py | 4 | YES | YES (pkg init) | YES (enables module invocation) |
| src/ta_lab2/scripts/macro/refresh_macro_features.py | 438 | YES | YES | YES (invoked by run_daily_refresh) |
| src/ta_lab2/scripts/run_daily_refresh.py | (modified) | YES | YES | YES (--macro/--all wired) |

---

_Verified: 2026-03-03T03:34:43Z_
_Verifier: Claude (gsd-verifier)_
