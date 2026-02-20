---
phase: 27-regime-integration
verified: 2026-02-20T21:11:58Z
status: gaps_found
score: 6/7 must-haves verified
gaps:
  - truth: regime_inspect.py --flips mode correctly reads from cmc_regime_flips
    status: failed
    reason: show_flips() queries column bars_held; DDL defines duration_bars. PostgreSQL raises column-not-found at runtime.
    artifacts:
      - path: src/ta_lab2/scripts/regimes/regime_inspect.py
        issue: Line 312 SELECT includes bars_held, DDL column is duration_bars. Line 337 cascades.
    missing:
      - Line 312 change bars_held to duration_bars in SELECT
      - Line 337 update df column reference to duration_bars
---

# Phase 27: Regime Integration Verification Report

**Phase Goal:** Connect existing regime module to DB-backed feature pipeline.

**Verified:** 2026-02-20T21:11:58Z
**Status:** gaps_found
**Re-verification:** No -- initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|---------|
| 1 | DB schema tables exist with correct PKs | VERIFIED | All 5 SQL DDL files exist: cmc_regimes PK(id,ts,tf), cmc_regime_flips PK(id,ts,tf,layer), cmc_regime_stats PK(id,tf,regime_key), cmc_regime_comovement PK(id,tf,ema_a,ema_b,computed_at). Signal tables have regime_key. dim_signals has regime_enabled. |
| 2 | EMA pivot converts long-format DB rows to wide-format | VERIFIED | pivot_emas_to_wide() in regime_data_loader.py (520 lines total). Int period casting, close_ema_N naming, empty input handled. Monthly [12,24,48], Weekly [20,50,200], Daily [20,50,100]. |
| 3 | refresh_cmc_regimes.py loads bars+EMAs, runs L0-L2 labeling, writes 4 tables | VERIFIED | compute_regimes_for_id (945-line file) loads from DB, calls label_layer_monthly/weekly/daily, applies HysteresisTracker, resolves policy, writes all 4 regime tables. |
| 4 | Data budget auto-enables/disables layers based on bar history | VERIFIED | assess_data_budget() thresholds L0:60m L1:52w L2:120d. Wired in compute_regimes_for_id. Proxy fallback via infer_cycle_proxy and infer_weekly_macro_proxy. |
| 5 | All 3 signal generators accept regime context and write regime_key | VERIFIED | EMASignalGenerator, RSISignalGenerator, ATRSignalGenerator all have regime_enabled param, call load_regime_context_batch + merge_regime_context, write regime_key to signal records. |
| 6 | run_daily_refresh.py supports --regimes and --all in correct order | VERIFIED | --bars/--emas/--regimes/--all flags. Execution order: bars -> EMAs -> regimes. run_regime_refresher() subprocess with correct flag propagation. |
| 7 | regime_inspect.py reads DB by default, supports --live and --flips | PARTIAL | Default/--live/--history modes verified. --flips FAILS: queries bars_held at line 312 but DDL column is duration_bars. Runtime SQL error. |

**Score: 6/7 truths verified**

### Required Artifacts

| Artifact | Status | Details |
|----------|--------|---------|
| sql/regimes/080_cmc_regimes.sql | VERIFIED | 69 lines. PK(id,ts,tf). l0-l4 labels, policy cols, feature_tier, layer-enabled flags, version hash. |
| sql/regimes/081_cmc_regime_flips.sql | VERIFIED | 38 lines. PK(id,ts,tf,layer). old_regime, new_regime, duration_bars. |
| sql/regimes/082_cmc_regime_stats.sql | VERIFIED | 38 lines. PK(id,tf,regime_key). n_bars, pct_of_history, avg_ret_1d, std_ret_1d. |
| sql/regimes/083_alter_signal_tables.sql | VERIFIED | Idempotent ADD COLUMN IF NOT EXISTS regime_key TEXT on all 3 signal tables. |
| sql/regimes/084_cmc_regime_comovement.sql | VERIFIED | 48 lines. PK(id,tf,ema_a,ema_b,computed_at). correlation, sign_agree_rate, best_lead_lag. |
| sql/dim/010_dim_signals_regime_col.sql | VERIFIED | Idempotent ADD COLUMN IF NOT EXISTS regime_enabled BOOLEAN DEFAULT TRUE on dim_signals. |
| src/ta_lab2/scripts/regimes/__init__.py | VERIFIED | Package init exists. |
| src/ta_lab2/scripts/regimes/regime_data_loader.py | VERIFIED | 520 lines. pivot_emas_to_wide, load_bars_for_tf (time_close AS ts alias for calendar tables, alignment_source filter for daily EMAs), load_regime_input_data. |
| src/ta_lab2/scripts/regimes/refresh_cmc_regimes.py | VERIFIED | 945 lines. compute_regimes_for_id, write_regimes_to_db. CLI: --all/--ids, --no-hysteresis, --min-hold-bars, --dry-run, --cal-scheme. |
| src/ta_lab2/regimes/hysteresis.py | VERIFIED | 229 lines. HysteresisTracker with update/get_current/reset. Tightening bypass. is_tightening_change uses resolve_policy_from_table. |
| src/ta_lab2/scripts/regimes/regime_flips.py | VERIFIED | 263 lines. Per-(id,tf,layer) flip detection via shift-compare. write_flips_to_db ON CONFLICT DO UPDATE. |
| src/ta_lab2/scripts/regimes/regime_stats.py | VERIFIED | 296 lines. n_bars, pct_of_history, avg_ret_1d, std_ret_1d. write_stats_to_db ON CONFLICT DO UPDATE. |
| src/ta_lab2/scripts/regimes/regime_comovement.py | VERIFIED | 367 lines. compute_ema_comovement_stats + lead_lag_max_corr. Scoped DELETE+INSERT. |
| src/ta_lab2/scripts/signals/regime_utils.py | VERIFIED | 151 lines. load_regime_context_batch with graceful fallback. merge_regime_context left-join on (id,ts). |
| src/ta_lab2/scripts/signals/generate_signals_ema.py | VERIFIED | regime_enabled param. Loads and merges regime context. regime_key in signal records. |
| src/ta_lab2/scripts/signals/generate_signals_rsi.py | VERIFIED | regime_enabled param. JSON serialization of feature_snapshot (pre-existing bug fixed). Post-hoc regime_key merge on entry_ts. |
| src/ta_lab2/scripts/signals/generate_signals_atr.py | VERIFIED | regime_enabled param. Loads and merges regime context. regime_key in signal records. |
| src/ta_lab2/scripts/signals/run_all_signal_refreshes.py | VERIFIED | --no-regime flag passes regime_enabled=False to all 3 generators. |
| src/ta_lab2/scripts/run_daily_refresh.py | VERIFIED | --regimes, --all flags. bars->EMAs->regimes order. Subprocess propagates --dry-run, --verbose, --no-hysteresis. |
| src/ta_lab2/scripts/regimes/regime_inspect.py | PARTIAL | Default/--live/--history modes verified. --flips queries bars_held (line 312); DDL column is duration_bars. Runtime SQL error. |


### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| refresh_cmc_regimes.py | cmc_price_bars_multi_tf | load_bars_for_tf tf=1D | VERIFIED | time_close AS ts alias correct. |
| refresh_cmc_regimes.py | cmc_price_bars_multi_tf_cal | load_bars_for_tf tf=1W/1M | VERIFIED | time_close AS ts alias; routes by cal_scheme. |
| refresh_cmc_regimes.py | cmc_ema_multi_tf_u | load_emas_for_tf tf=1D | VERIFIED | alignment_source filter prevents duplicate rows. |
| refresh_cmc_regimes.py | cmc_ema_multi_tf_cal | load_emas_for_tf tf=1W/1M | VERIFIED | Correct table routing by cal_scheme. |
| pivot_emas_to_wide | label_layer functions | close_ema_N naming | VERIFIED | Monthly [12,24,48], Weekly [20,50,200], Daily [20,50,100] match labeler expectations. |
| compute_regimes_for_id | cmc_regimes | write_regimes_to_db | VERIFIED | Scoped DELETE by (ids,tf) then to_sql append. |
| compute_regimes_for_id | cmc_regime_flips | detect_regime_flips + write_flips_to_db | VERIFIED | Composite and per-layer flip detection. ON CONFLICT DO UPDATE. |
| compute_regimes_for_id | cmc_regime_stats | compute_regime_stats + write_stats_to_db | VERIFIED | Groups by (id,tf,regime_key). Merges cmc_returns. |
| compute_regimes_for_id | cmc_regime_comovement | compute_and_write_comovement | VERIFIED | compute_ema_comovement_stats + lead_lag_max_corr. |
| assess_data_budget | L0/L1/L2 labelers | DataBudgetContext.enabled_layers | VERIFIED | Wired in compute_regimes_for_id. Proxy fallback for disabled layers. |
| HysteresisTracker | label smoothing | update per bar per layer | VERIFIED | is_tightening_change determines bypass. reset between assets. |
| EMA/RSI/ATR generators | cmc_regimes | load_regime_context_batch | VERIFIED | Batch query. Graceful fallback when table empty. |
| merge_regime_context | feature_df | left join on (id,ts) | VERIFIED | Adds regime_key, size_mult, stop_mult, orders. NULL when no data. |
| run_daily_refresh.py | refresh_cmc_regimes.py | subprocess call | VERIFIED | Propagates --dry-run, --verbose, --no-hysteresis. |
| regime_inspect.py show_flips | cmc_regime_flips | SQL SELECT | FAILED | Queries bars_held; DDL column is duration_bars. Runtime SQL error. |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| src/ta_lab2/scripts/regimes/regime_inspect.py | 312 | Wrong column bars_held in SQL (DDL: duration_bars) | Blocker | --flips fails at runtime |
| src/ta_lab2/scripts/regimes/regime_inspect.py | 337 | df reference to bars_held cascades from SQL bug | Blocker | Same --flips failure |
| src/ta_lab2/scripts/regimes/refresh_cmc_regimes.py | 780-784 | --min-bars overrides not passed to assess_data_budget | Warning | Flags have no effect |

### Human Verification Required

**1. EMA column mapping accuracy in practice**
Test: Run refresh_cmc_regimes.py --ids 1 --dry-run -v against populated DB
Expected: L0/L1/L2 label distributions are non-trivially diverse (not all Unknown)
Why human: Requires actual DB data to confirm EMA values reach labelers correctly

**2. Young asset proxy label population**
Test: Run against asset with under 52 weekly bars; inspect l1_label output
Expected: Proxy-inferred labels present rather than None
Why human: Requires DB with a genuinely young asset

**3. Signal regime_key population end-to-end**
Test: Run signal generators after regime refresh; query cmc_signals tables for regime_key
Expected: regime_key non-NULL for assets with regime data
Why human: Requires both cmc_regimes and cmc_signals tables populated in DB

### Gaps Summary

One gap blocks a specific inspection feature but does not affect the core pipeline.

The --flips mode in regime_inspect.py queries column bars_held at line 312.
The DDL file sql/regimes/081_cmc_regime_flips.sql defines this column as duration_bars.
PostgreSQL raises "column bars_held does not exist" at runtime when --flips is used.

Fix is 2 lines:
- Line 312: Change bars_held to duration_bars in SELECT
- Line 337: Change df["bars_held"] to df["duration_bars"]

Secondary observation (warning, not blocking): --min-bars-l0/l1/l2 CLI args are parsed
but never passed to assess_data_budget. The docstring documents this as reserved for future use.
These CLI flags silently have no effect.

All other must-haves from all 7 plans are verified at all three levels:
- All 5 SQL DDL files correct with proper PKs and columns
- Data loader bridges DB to labelers with correct close_ema_N column naming
- refresh_cmc_regimes.py is a 945-line implementation orchestrating all 4 table writes
- HysteresisTracker wired with tightening bypass and reset between assets
- Data budget gating functional with proxy fallback for young assets
- All 3 signal generators accept regime_enabled and record regime_key
- Daily refresh orchestrator runs bars -> EMAs -> regimes in correct order

---

_Verified: 2026-02-20T21:11:58Z_
_Verifier: Claude (gsd-verifier)_
