---
phase: 78-table-drops-script-cleanup
verified: 2026-03-21T14:52:36Z
status: passed
score: 14/14 must-haves verified
re_verification:
  previous_status: gaps_found
  previous_score: 9/14
  gaps_closed:
    - "No runtime Python code queries siloed data table names -- all queries use _u tables"
    - "No orchestrator references to deleted sync scripts remain"
  gaps_remaining: []
  regressions: []
---

# Phase 78: Table Drops and Script Cleanup Verification Report

**Phase Goal:** Drop 30 siloed data tables (~207 GB), delete deprecated sync/audit scripts, fix dependent views, and ensure zero runtime code references to dropped tables.
**Verified:** 2026-03-21T14:52:36Z
**Status:** passed
**Re-verification:** Yes -- after gap closure plans 78-04, 78-05, 78-06

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|---------|
| 1 | all_emas view points at ema_multi_tf_u | VERIFIED | views.py line 28: FROM public.ema_multi_tf_u |
| 2 | No runtime Python code queries siloed data table names | VERIFIED | All 5 executor/dashboard/drift/exchange/validation files redirect to price_bars_multi_tf_u; all AMA/EMA builders default to price_bars_multi_tf_u; zero FROM clauses against siloed cal/anchor tables |
| 3 | Category E files work against _u tables | VERIFIED | All 10 Category E files confirmed with alignment_source=multi_tf filters (unchanged from initial verification) |
| 4 | views.py contains ema_multi_tf_u in VIEW_ALL_EMAS_SQL | VERIFIED | Line 28: FROM public.ema_multi_tf_u |
| 5 | regime_data_loader.py contains price_bars_multi_tf_u | VERIFIED | Lines 194, 209 confirmed |
| 6 | refresh_asset_stats.py contains returns_bars_multi_tf_u | VERIFIED | Line 67: SOURCE_TABLE = returns_bars_multi_tf_u |
| 7 | 6 sync scripts no longer exist in the codebase | VERIFIED | All 6 confirmed absent from filesystem |
| 8 | 14 Category D audit scripts no longer exist | VERIFIED | All 14 confirmed absent from filesystem |
| 9 | No orchestrator references to deleted sync scripts remain | VERIFIED | run_all_audits.py now has exactly 3 AuditScript entries; all 14 deleted script paths removed; comment at lines 48-50 documents the cleanup |
| 10 | The dangerous _resync_u_tables() function is fully removed | VERIFIED | Zero grep matches for _resync_u_tables, _RESYNC_MODULES, skip_resync |
| 11 | run_all_bar_builders.py and run_daily_refresh.py have zero sync references | VERIFIED | Unchanged from initial verification |
| 12 | All 30 siloed data tables no longer exist in the database | VERIFIED | 0 of 30 found in pg_tables; DB = 177 GB (was 431 GB) |
| 13 | State tables (30 siloed-path) are preserved | VERIFIED | All 30 named siloed-path state tables confirmed present |
| 14 | 3 cmc_* _u-path state tables are preserved | VERIFIED | All 3 cmc_* state tables confirmed present |

**Score:** 14/14 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| src/ta_lab2/features/m_tf/views.py | VIEW_ALL_EMAS_SQL pointing at ema_multi_tf_u | VERIFIED | Line 28 confirmed |
| src/ta_lab2/scripts/regimes/regime_data_loader.py | Uses price_bars_multi_tf_u | VERIFIED | Lines 194, 209 confirmed |
| src/ta_lab2/scripts/desc_stats/refresh_asset_stats.py | SOURCE_TABLE = returns_bars_multi_tf_u | VERIFIED | Line 67 confirmed |
| src/ta_lab2/executor/position_sizer.py | Fallback query uses price_bars_multi_tf_u + alignment_source | VERIFIED | Lines 381-386 confirmed |
| src/ta_lab2/dashboard/pages/10_macro.py | Overlay query uses price_bars_multi_tf_u + alignment_source | VERIFIED | Lines 199-203 confirmed |
| src/ta_lab2/drift/data_snapshot.py | Snapshot query uses price_bars_multi_tf_u + alignment_source | VERIFIED | Lines 44-46 confirmed |
| src/ta_lab2/scripts/exchange/refresh_exchange_price_feed.py | Last-bar query uses price_bars_multi_tf_u + alignment_source | VERIFIED | Lines 114-118 confirmed |
| src/ta_lab2/scripts/validation/run_preflight_check.py | Preflight check 9 uses price_bars_multi_tf_u + alignment_source | VERIFIED | Lines 256-257 confirmed |
| src/ta_lab2/scripts/amas/refresh_ama_multi_tf.py | get_bars_table() returns price_bars_multi_tf_u | VERIFIED | Line 80 confirmed |
| src/ta_lab2/scripts/amas/base_ama_refresher.py | bars_table default = price_bars_multi_tf_u | VERIFIED | Line 87 + line 323 confirmed |
| src/ta_lab2/scripts/amas/refresh_ama_multi_tf_cal_from_bars.py | SCHEME_MAP bars_table = price_bars_multi_tf_u | VERIFIED | Lines 63, 71 confirmed |
| src/ta_lab2/scripts/amas/refresh_ama_multi_tf_cal_anchor_from_bars.py | SCHEME_MAP bars_table = price_bars_multi_tf_u | VERIFIED | Lines 65, 73 confirmed |
| src/ta_lab2/features/ama/ama_multi_timeframe.py | bars_table default = price_bars_multi_tf_u + alignment_source filter | VERIFIED | Line 138 default + lines 180-182 filter confirmed |
| src/ta_lab2/features/ama/ama_multi_tf_cal.py | bars_table defaults = price_bars_multi_tf_u + alignment_source filter | VERIFIED | Lines 61, 279 defaults + lines 94-96, 148-150 filters confirmed |
| src/ta_lab2/features/ama/ama_multi_tf_cal_anchor.py | bars_table defaults = price_bars_multi_tf_u + alignment_source filter | VERIFIED | Lines 61, 286 defaults + lines 94-96, 148-150 filters confirmed |
| src/ta_lab2/features/m_tf/ema_multi_timeframe.py | bars_table default = price_bars_multi_tf_u + alignment_source filter | VERIFIED | Line 65 default + lines 440-442 filter confirmed |
| src/ta_lab2/features/m_tf/ema_multi_tf_cal.py | bars_table hardcoded = price_bars_multi_tf_u + alignment_source filter | VERIFIED | Line 83 hardcoded + lines 423-433 filter confirmed |
| src/ta_lab2/features/m_tf/ema_multi_tf_cal_anchor.py | bars_table hardcoded = price_bars_multi_tf_u + alignment_source filter | VERIFIED | Line 74 hardcoded + lines 282-295 filter confirmed |
| src/ta_lab2/scripts/emas/refresh_ema_multi_tf_from_bars.py | bars_table default = price_bars_multi_tf_u | VERIFIED | Line 71 default + lines 83, 247, 291, 294 confirmed |
| src/ta_lab2/scripts/emas/refresh_ema_multi_tf_cal_from_bars.py | bars_table hardcoded = price_bars_multi_tf_u | VERIFIED | Line 166 hardcoded + alignment_source per-scheme confirmed |
| src/ta_lab2/scripts/emas/refresh_ema_multi_tf_cal_anchor_from_bars.py | bars_table hardcoded = price_bars_multi_tf_u | VERIFIED | Line 170 hardcoded + alignment_source per-scheme confirmed |
| src/ta_lab2/scripts/emas/ema_state_manager.py | EMAStateConfig has alignment_source field | VERIFIED | Lines 72-73 confirmed |
| src/ta_lab2/scripts/run_all_audits.py | Exactly 3 valid AuditScript entries; 0 deleted paths | VERIFIED | Count=3; comment at lines 48-50 documents cleanup |
| 20 deleted scripts (6 sync + 14 audit) | DELETED | VERIFIED | All 20 confirmed absent |
| DB: 30 siloed tables | DROPPED | VERIFIED | 0 of 30 found in pg_tables |
| DB: 6 _u tables | INTACT | VERIFIED | All 6 queryable: 12M-170M rows each |
| DB: 33 state tables | PRESERVED | VERIFIED | All 30 named + 3 cmc_* confirmed present |
| DB: all_emas view | POINTS AT _u | VERIFIED | Definition confirmed from pg_views |
| DB size | REDUCED | VERIFIED | 431 GB -> 177 GB (-254 GB, -59%) |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| views.py VIEW_ALL_EMAS_SQL | public.ema_multi_tf_u | CREATE OR REPLACE VIEW | WIRED | Line 28: FROM public.ema_multi_tf_u |
| regime_data_loader.py | public.price_bars_multi_tf_u | SQL in load_bars_for_tf | WIRED | Both 1D (alignment_source=multi_tf) and cal variants confirmed |
| refresh_asset_stats.py | public.returns_bars_multi_tf_u | SOURCE_TABLE constant | WIRED | SOURCE_TABLE used in all SQL queries |
| executor/position_sizer.py | public.price_bars_multi_tf_u | SELECT fallback | WIRED | Lines 381-386: AND alignment_source = "multi_tf" |
| drift/data_snapshot.py | public.price_bars_multi_tf_u | SELECT MAX(ts) | WIRED | Lines 44-46: AND alignment_source = "multi_tf" |
| dashboard/pages/10_macro.py | public.price_bars_multi_tf_u | SELECT overlay | WIRED | Lines 199-203: pb.alignment_source = "multi_tf" |
| refresh_exchange_price_feed.py | public.price_bars_multi_tf_u | SELECT last bar | WIRED | Lines 114-118: AND b.alignment_source = "multi_tf" |
| run_preflight_check.py | public.price_bars_multi_tf_u | SELECT MAX(ts) | WIRED | Lines 256-257: AND alignment_source="multi_tf" |
| refresh_ama_multi_tf.py | public.price_bars_multi_tf_u | get_bars_table() | WIRED | Line 80: returns "price_bars_multi_tf_u" |
| AMA feature classes (x3) | public.price_bars_multi_tf_u | bars_table default + SQL filter | WIRED | Default bars_table=price_bars_multi_tf_u + alignment_source in all SQL |
| AMA cal builder SCHEME_MAP | public.price_bars_multi_tf_u | bars_table in SCHEME_MAP | WIRED | SCHEME_MAP entries for both us/iso schemes use price_bars_multi_tf_u |
| AMA cal-anchor builder SCHEME_MAP | public.price_bars_multi_tf_u | bars_table in SCHEME_MAP | WIRED | SCHEME_MAP entries for both us/iso schemes use price_bars_multi_tf_u |
| EMA feature classes (x3) | public.price_bars_multi_tf_u | bars_table default/hardcoded + SQL filter | WIRED | Default/hardcoded + alignment_source filter in all SQL |
| EMA base builder | public.price_bars_multi_tf_u | bars_table default | WIRED | Line 71 default price_bars_multi_tf_u, lines 83+291 confirmed |
| EMA cal/cal-anchor builders | public.price_bars_multi_tf_u | bars_table hardcoded | WIRED | Lines 166, 170 hardcoded to price_bars_multi_tf_u |
| run_all_audits.py ALL_AUDIT_SCRIPTS | 3 live audit scripts | AuditScript.script_path | WIRED | Only 3 entries remain; all 14 deleted paths removed |
| run_all_ama_refreshes.py POST_STEPS | sync scripts (deleted) | was: module reference | REMOVED | POST_STEPS has only 2 entries (returns + zscores) |
| refresh_returns_zscore.py | _resync_u_tables() | was: conditional call | REMOVED | Function, dict, and CLI arg all excised |

### Requirements Coverage

| Requirement | Status | Blocking Issue |
|-------------|--------|---------------|
| 30 siloed data tables dropped from DB | SATISFIED | None -- confirmed 0 of 30 remain |
| ~207 GB storage reclaimed | SATISFIED | 254 GB reclaimed (59% reduction, exceeds 48% target) |
| 20 deprecated scripts deleted | SATISFIED | All 20 confirmed deleted |
| All orchestrator sync references removed | SATISFIED | run_all_audits.py now has 3 valid entries; all 14 deleted paths removed |
| Dependent views (all_emas) recreated pointing at _u | SATISFIED | all_emas view confirmed pointing at ema_multi_tf_u |
| All runtime code reads from _u tables only | SATISFIED | All 12 previously-broken links now wired to _u + alignment_source filter |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| src/ta_lab2/scripts/emas/base_ema_refresher.py | 231 | Docstring example references old table name | INFO | Documentation only; no runtime execution |
| src/ta_lab2/features/ama/base_ama_feature.py | 177 | Docstring example references old table name | INFO | Documentation only; no runtime execution |
| src/ta_lab2/scripts/emas/state_management.py | 136 | Docstring example references old cal table name | INFO | Documentation only; no runtime execution |
| src/ta_lab2/drift/data_snapshot.py | 16 | Module docstring references old table name | INFO | Documentation only; actual SQL at line 44 uses _u table correctly |
| src/ta_lab2/executor/position_sizer.py | 316 | Method docstring references old table name | INFO | Documentation only; actual SQL at lines 381-386 uses _u table correctly |

No BLOCKER or WARNING anti-patterns found. All 8 previous BLOCKERs are resolved.

### Human Verification Required

No items require human testing. All critical checks are verifiable programmatically.

### Re-Verification Summary

All 3 gaps from the initial verification are fully closed:

**Gap 1 (CRITICAL) -- CLOSED:** All 5 runtime files now query price_bars_multi_tf_u with alignment_source=multi_tf:
- executor/position_sizer.py (lines 381-386): confirmed _u + alignment_source filter
- dashboard/pages/10_macro.py (lines 199-203): confirmed _u + alignment_source filter
- drift/data_snapshot.py (lines 44-46): confirmed _u + alignment_source filter
- scripts/exchange/refresh_exchange_price_feed.py (lines 114-118): confirmed _u + alignment_source filter
- scripts/validation/run_preflight_check.py (lines 256-257): confirmed _u + alignment_source filter

**Gap 2 (CRITICAL) -- CLOSED:** All AMA and EMA builders now read from price_bars_multi_tf_u:
- refresh_ama_multi_tf.py: get_bars_table() returns price_bars_multi_tf_u (line 80)
- base_ama_refresher.py: bars_table default = price_bars_multi_tf_u (line 87)
- refresh_ama_multi_tf_cal_from_bars.py: SCHEME_MAP bars_table = price_bars_multi_tf_u for both us/iso
- refresh_ama_multi_tf_cal_anchor_from_bars.py: SCHEME_MAP bars_table = price_bars_multi_tf_u for both us/iso
- All 3 AMA feature classes: bars_table default = price_bars_multi_tf_u + alignment_source in SQL
- All 3 EMA feature classes: bars_table default/hardcoded = price_bars_multi_tf_u + alignment_source in SQL
- refresh_ema_multi_tf_from_bars.py: bars_table default = price_bars_multi_tf_u (line 71)
- refresh_ema_multi_tf_cal_from_bars.py: bars_table hardcoded = price_bars_multi_tf_u (line 166)
- refresh_ema_multi_tf_cal_anchor_from_bars.py: bars_table hardcoded = price_bars_multi_tf_u (line 170)
- ema_state_manager.py: EMAStateConfig.alignment_source field added (lines 72-73)

**Gap 3 (WARNING) -- CLOSED:** run_all_audits.py now has exactly 3 AuditScript entries
(returns_d1, returns_ema_multi_tf, returns_ema_multi_tf_u). All 14 deleted audit script
paths are removed. Comment at lines 48-50 documents that bar/EMA audit scripts were removed
in Phase 78. Zero regression on any of the 9 previously-passing truths.

**Broad siloed-table grep result:** Zero FROM clauses in src/ target any of the 30 dropped
siloed table names (price_bars_multi_tf_cal_*, ema_multi_tf_cal_*, ama_multi_tf_cal_*,
returns_*_cal_*, etc.). Remaining references to bare table names (price_bars_multi_tf,
ema_multi_tf, ama_multi_tf, returns_ama_multi_tf) are all either: (a) docstrings/comments,
(b) scripts that legitimately WRITE TO those STATE tables (which still exist), or
(c) the bar-builder scripts whose sole purpose is populating those state tables.

---

_Verified: 2026-03-21T14:52:36Z_
_Verifier: Claude (gsd-verifier)_
