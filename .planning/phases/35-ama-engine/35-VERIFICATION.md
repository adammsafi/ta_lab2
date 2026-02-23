---
phase: 35-ama-engine
verified: 2026-02-23T22:38:58Z
status: passed
score: 8/8 must-haves verified
re_verification: false
---

# Phase 35: AMA Engine Verification Report

**Phase Goal:** Build the full AMA (Adaptive Moving Average) engine -- DDL, pure computations (KAMA, DEMA, TEMA, HMA), BaseAMAFeature infrastructure, refresher scripts for all 5 table variants, returns computation, _u sync, z-score extension, and daily refresh pipeline integration.
**Verified:** 2026-02-23T22:38:58Z
**Status:** passed
**Re-verification:** No -- initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | All 9 DDL files exist in sql/ddl/ | VERIFIED | 9 files confirmed: 4 value + 4 returns + 1 dim_ama_params |
| 2 | AMA value tables have PK (id, ts, tf, indicator, params_hash) | VERIFIED | PRIMARY KEY (id, ts, tf, indicator, params_hash) in create_cmc_ama_multi_tf.sql |
| 3 | _u tables include alignment_source in PK | VERIFIED | PRIMARY KEY (id, ts, tf, indicator, params_hash, alignment_source) in _u DDL |
| 4 | Returns tables have z-score columns | VERIFIED | 12 z-score columns (_zscore_30, _zscore_90, _zscore_365) in create_cmc_returns_ama_multi_tf.sql |
| 5 | dim_ama_params has (indicator, params_hash) PK with params_json JSONB | VERIFIED | Confirmed in create_dim_ama_params.sql |
| 6 | compute_kama() returns (kama, er) arrays with NaN warmup; DEMA/TEMA use ewm(alpha=2/(period+1), adjust=False); HMA uses rolling WMA | VERIFIED | All assertions pass; HMA uses _wma() with rolling().apply(); DEMA/TEMA use correct alpha |
| 7 | 18 parameter sets; compute_params_hash is deterministic | VERIFIED | len(ALL_AMA_PARAMS) == 18; hash stability test passes |
| 8 | BaseAMAFeature is abstract with 3 abstract methods; AMAStateManager uses (id, tf, indicator, params_hash) PK | VERIFIED | __abstractmethods__ confirmed; state DDL has 4-col PK |
| 9 | refresh_cmc_ama_multi_tf.py runnable; loads from cmc_price_bars_multi_tf; NullPool in workers | VERIFIED | --help shows all expected flags; poolclass=NullPool in _ama_worker |
| 10 | AMA returns have _ama suffix columns; grouped by (id, tf, indicator, params_hash) | VERIFIED | _ROLL_COLS and _CANON_COLS use _ama suffix; no _ema_bar in computation code |
| 11 | 4 calendar feature classes extend BaseAMAFeature; refreshers support --scheme us/iso/both | VERIFIED | 4 classes confirmed; --scheme flag in cal and cal_anchor refreshers |
| 12 | Two sync scripts use sync_sources_to_unified(); _AMA_TABLES has 6 configs; key_cols include indicator+params_hash | VERIFIED | Both sync scripts call sync_sources_to_unified(); 6 TableConfig objects confirmed |
| 13 | run_all_ama_refreshes.py references all 7 scripts; --amas in daily refresh; AMAs between EMAs and regimes | VERIFIED | All 7 scripts referenced; --amas flag present; order EMAs(1040)->AMAs(1083)->regimes(1095) |

**Score:** 8/8 plan must-haves verified (13 individual truth checks all pass)

---

## Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|----------|
| sql/ddl/create_cmc_ama_multi_tf.sql | Main AMA value table DDL | VERIFIED | PK (id, ts, tf, indicator, params_hash); er column; state table |
| sql/ddl/create_cmc_ama_multi_tf_cal.sql | Calendar AMA variants | VERIFIED | cal_us + cal_iso + state tables |
| sql/ddl/create_cmc_ama_multi_tf_cal_anchor.sql | Anchor AMA variants | VERIFIED | cal_anchor_us + cal_anchor_iso + state tables |
| sql/ddl/create_cmc_ama_multi_tf_u.sql | Unified AMA value table | VERIFIED | alignment_source in PK |
| sql/ddl/create_cmc_returns_ama_multi_tf.sql | Main AMA returns table | VERIFIED | _ama suffix columns; 12 z-score columns; state table |
| sql/ddl/create_cmc_returns_ama_multi_tf_cal.sql | Calendar returns | VERIFIED | Exists |
| sql/ddl/create_cmc_returns_ama_multi_tf_cal_anchor.sql | Anchor returns | VERIFIED | Exists |
| sql/ddl/create_cmc_returns_ama_multi_tf_u.sql | Unified returns table | VERIFIED | alignment_source in PK |
| sql/ddl/create_dim_ama_params.sql | Parameter lookup table | VERIFIED | (indicator, params_hash) PK; params_json JSONB; label column |
| src/ta_lab2/features/ama/ama_params.py | Parameter management | VERIFIED | 309 lines; 18 AMAParamSet constants; compute_params_hash; get_warmup |
| src/ta_lab2/features/ama/ama_computations.py | Pure computation functions | VERIFIED | 294 lines; 4 indicators + dispatcher; warmup guards |
| src/ta_lab2/features/ama/base_ama_feature.py | Abstract base class | VERIFIED | 523 lines; 3 abstract methods; correct PK; scoped DELETE+INSERT |
| src/ta_lab2/features/ama/ama_multi_timeframe.py | MultiTFAMAFeature | VERIFIED | 301 lines; extends BaseAMAFeature; loads from cmc_price_bars_multi_tf |
| src/ta_lab2/features/ama/ama_multi_tf_cal.py | Calendar feature classes | VERIFIED | CalUSAMAFeature + CalISOAMAFeature extending BaseAMAFeature |
| src/ta_lab2/features/ama/ama_multi_tf_cal_anchor.py | Anchor feature classes | VERIFIED | CalAnchorUS + CalAnchorISO extending BaseAMAFeature |
| src/ta_lab2/features/ama/ama_returns.py | AMA returns feature | VERIFIED | 514 lines; 12 return columns; canonical-only for roll=FALSE |
| src/ta_lab2/scripts/amas/ama_state_manager.py | State manager | VERIFIED | 337 lines; 5 methods; (id, tf, indicator, params_hash) PK |
| src/ta_lab2/scripts/amas/base_ama_refresher.py | Base refresher | VERIFIED | 679 lines; NullPool in workers; AMAStateManager (not EMAStateManager) |
| src/ta_lab2/scripts/amas/refresh_cmc_ama_multi_tf.py | Main refresher script | VERIFIED | Runnable; --help shows --ids, --tf, --all-tfs, --indicators, --full-rebuild |
| src/ta_lab2/scripts/amas/refresh_cmc_ama_multi_tf_cal_from_bars.py | Calendar refresher | VERIFIED | --scheme us/iso/both supported |
| src/ta_lab2/scripts/amas/refresh_cmc_ama_multi_tf_cal_anchor_from_bars.py | Anchor refresher | VERIFIED | --scheme us/iso/both supported |
| src/ta_lab2/scripts/amas/refresh_cmc_returns_ama.py | Returns refresher | VERIFIED | TABLE_MAP covers all 5 source tables |
| src/ta_lab2/scripts/amas/sync_cmc_ama_multi_tf_u.py | Value _u sync | VERIFIED | Uses sync_sources_to_unified(); 5 sources; PK includes indicator + params_hash |
| src/ta_lab2/scripts/amas/sync_cmc_returns_ama_multi_tf_u.py | Returns _u sync | VERIFIED | Uses sync_sources_to_unified(); 5 sources |
| src/ta_lab2/scripts/amas/run_all_ama_refreshes.py | AMA orchestrator | VERIFIED | 678 lines; all 7 pipeline scripts referenced; --only, --continue-on-error |
| src/ta_lab2/scripts/run_daily_refresh.py | Daily refresh (updated) | VERIFIED | --amas flag; TIMEOUT_AMAS=3600; correct pipeline order |
| src/ta_lab2/scripts/returns/refresh_returns_zscore.py | Z-score script (extended) | VERIFIED | _AMA_TABLES=6; amas in --tables choices; key_cols include indicator+params_hash |

---

## Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|----------|
| base_ama_feature.py | ama_computations.py | compute_ama() call | WIRED | from ta_lab2.features.ama.ama_computations import compute_ama |
| ama_multi_timeframe.py | base_ama_feature.py | MultiTFAMAFeature(BaseAMAFeature) | WIRED | Extends abstract base |
| base_ama_refresher.py | ama_state_manager.py | AMAStateManager(engine, state_table) | WIRED | Direct instantiation in run() and _ama_worker |
| base_ama_refresher.py | _ama_worker | poolclass=NullPool | WIRED | create_engine(task.db_url, poolclass=NullPool) |
| refresh_cmc_ama_multi_tf.py | base_ama_refresher.py | MultiTFAMARefresher(BaseAMARefresher) | WIRED | Inherits all CLI and execution logic |
| sync_cmc_ama_multi_tf_u.py | sync_utils.py | sync_sources_to_unified() | WIRED | Direct import and call; 5 sources |
| sync_cmc_returns_ama_multi_tf_u.py | sync_utils.py | sync_sources_to_unified() | WIRED | Direct import and call; 5 sources |
| refresh_returns_zscore.py | AMA returns tables | _AMA_TABLES (6 configs) | WIRED | Tables with indicator + params_hash in key_cols |
| run_all_ama_refreshes.py | 7 pipeline scripts | subprocess.run() / module references | WIRED | All 7 scripts in RefresherConfig/PostStep objects |
| run_daily_refresh.py | run_all_ama_refreshes.py | subprocess.run() in run_ama_refreshers() | WIRED | Referenced; EMAs->AMAs->regimes order confirmed |

---

## Requirements Coverage

| Requirement | Status | Blocking Issue |
|-------------|--------|----------------|
| AMA-01: KAMA computation with ER | SATISFIED | -- |
| AMA-02: DEMA/TEMA/HMA computation | SATISFIED | -- |
| AMA-03: AMA value tables + derivatives | SATISFIED | -- |
| AMA-04: Incremental refresh pipeline | SATISFIED | -- |
| AMA-05: AMA returns + z-scores | SATISFIED | -- |
| AMA-06: Calendar alignment parity | SATISFIED | -- |
| AMA-07: Daily refresh integration | SATISFIED | -- |

---

## Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| src/ta_lab2/features/ama/base_ama_feature.py | 397 | ids_placeholder variable name | Info | False positive -- legitimate SQL variable, not a stub |

No blockers or warnings found.

---

## Human Verification Required

### 1. End-to-End AMA Computation

**Test:** python -m ta_lab2.scripts.amas.refresh_cmc_ama_multi_tf --ids 1 --tf 1D
**Expected:** cmc_ama_multi_tf populated with 18 rows per bar (KAMA x3, DEMA x5, TEMA x5, HMA x5); KAMA rows have non-NULL er; DEMA/TEMA/HMA rows have er = NULL
**Why human:** Requires live DB with cmc_price_bars_multi_tf and dim_timeframe populated

### 2. Z-Score Computation on AMA Returns

**Test:** python -m ta_lab2.scripts.returns.refresh_returns_zscore --tables amas --ids 1
**Expected:** cmc_returns_ama_multi_tf rows have non-NULL _zscore_30/_zscore_90/_zscore_365 after sufficient history
**Why human:** Requires live DB with AMA returns data populated first

### 3. Full Pipeline Order Confirmation

**Test:** python -m ta_lab2.scripts.run_daily_refresh --all --ids 1 --dry-run
**Expected:** Output shows stages in order: bars, EMAs, AMAs, regimes, stats
**Why human:** Stage display requires human to inspect live output

---

## Gaps Summary

No gaps found. All 8 plan must-haves are verified against the actual codebase. All artifacts exist, are substantive (verified via line counts and content inspection), and are correctly wired into the pipeline.

The phase goal is achieved. The AMA engine is complete with: 9 DDL files (12 tables + state tables + dim_ama_params), pure computation functions with correct conventions, BaseAMAFeature/AMAStateManager infrastructure, refreshers for all 5 table variants, AMA returns with correct _ama column naming, _u sync via sync_sources_to_unified(), z-score extension with per-param-set grouping, and daily refresh integration with correct EMAs->AMAs->regimes ordering.

---

_Verified: 2026-02-23T22:38:58Z_
_Verifier: Claude (gsd-verifier)_
