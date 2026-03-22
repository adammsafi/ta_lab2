---
phase: 81-garch-conditional-volatility
verified: 2026-03-22T17:20:18Z
status: gaps_found
score: 19/21 must-haves verified
gaps:
  - truth: Blended vol DB lookup via get_blended_vol works correctly
    status: failed
    reason: get_blended_vol() SQL queries column h1_vol which does not exist in garch_forecasts_latest (view has cond_vol). Also missing horizon=1 filter. Raises ProgrammingError at runtime.
    artifacts:
      - path: src/ta_lab2/analysis/garch_blend.py
        issue: SQL line 297 queries h1_vol; view has cond_vol; no AND horizon=1 filter
    missing:
      - Fix SQL to: SELECT model_type, cond_vol ... AND horizon = 1
      - Rename h1_vol to cond_vol at lines 326-328 of garch_blend.py
  - truth: vol_sizer.py imports blend_vol_simple from garch_blend (plan key link)
    status: partial
    reason: vol_sizer.py does not import from garch_blend; inline blend with identical math. get_blended_vol never called by any consumer.
    artifacts:
      - path: src/ta_lab2/analysis/vol_sizer.py
        issue: No import from ta_lab2.analysis.garch_blend; inline blend used instead
    missing:
      - Add import and use blend_vol_simple, or document inline as approved design
---

# Phase 81: GARCH Conditional Volatility Verification Report

**Phase Goal:** Build GARCH conditional volatility forecasting system with 4 model variants (GARCH, GJR-GARCH, EGARCH, FIGARCH), integrated into position sizing and risk management, with comparison report and daily refresh wiring.
**Verified:** 2026-03-22T17:20:18Z
**Status:** gaps_found
**Re-verification:** No -- initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | garch_forecasts table with PK (id, venue_id, ts, tf, model_type, horizon) | VERIFIED | Composite PK, model_type CHECK 4 values, horizon IN (1,5) CHECK, forecast_source CHECK |
| 2 | garch_diagnostics with BIGSERIAL run_id PK and convergence tracking | VERIFIED | BIGSERIAL PRIMARY KEY; converged BOOLEAN; convergence_flag SMALLINT; aic/bic/loglikelihood/ljung_box_pvalue |
| 3 | garch_forecasts_latest materialized view with unique index | VERIFIED | DISTINCT ON (id,venue_id,tf,model_type,horizon); uix_garch_forecasts_latest unique index |
| 4 | All four GARCH variants fitted and produce h1/h5 forecasts | VERIFIED | MODEL_SPECS has all 4; fit_all_variants iterates all; h1_vol/h5_vol populated on convergence |
| 5 | FIGARCH gated at 200-obs, others at 126-obs minimum | VERIFIED | FIGARCH_MIN_OBS=200, DEFAULT_MIN_OBS=126; per-model min_req check in fit_single_variant |
| 6 | GARCH forecasts generated for assets with sufficient history | VERIFIED | refresh_garch_forecasts.py: skips with logger.warning if len(ret_df) < min_obs |
| 7 | Forecasts stored via temp-table batch upsert | VERIFIED | CREATE TEMP TABLE + ON CONFLICT (id,venue_id,ts,tf,model_type,horizon) DO UPDATE SET cond_vol |
| 8 | Diagnostics stored for every fit attempt | VERIFIED | _insert_diagnostics() per model_type; INSERT ... RETURNING run_id |
| 9 | Assets with less than 126 obs skipped with log warning | VERIFIED | logger.warning lines 336-344; stats[skipped] incremented |
| 10 | Convergence failure falls back to GK/carry-forward, non-fatal | VERIFIED | 5-day exp half-life carry_forward then fallback_gk; per-asset exceptions caught |
| 11 | garch_forecasts_latest refreshed CONCURRENTLY after upsert | VERIFIED | REFRESH MATERIALIZED VIEW CONCURRENTLY public.garch_forecasts_latest at end of main() |
| 12 | RMSE and QLIKE loss computed against realized vol proxy | VERIFIED | rmse_loss clips to 1e-8; qlike_loss clips sigma^2/realized^2 to 1e-16; 5-day rolling std proxy |
| 13 | Mincer-Zarnowitz R-squared measures forecast calibration | VERIFIED | sm.OLS with add_constant; handles less than 3 obs and missing statsmodels |
| 14 | Rolling OOS evaluation produces per-asset accuracy metrics | VERIFIED | rolling_oos_evaluate() expanding window; evaluate_all_models() for all 4 models |
| 15 | QLIKE clips to 1e-8 minimum to avoid NaN/inf | VERIFIED | sigma^2 and realized^2 clipped to 1e-16 (equivalent to 1e-8 vol floor) |
| 16 | Inverse-RMSE blend weights over trailing 63-day window | VERIFIED | compute_blend_weights() iterative min-weight floor; BlendConfig.eval_window=63 |
| 17 | Blended vol DB lookup via get_blended_vol works correctly | FAILED | SQL queries h1_vol column which does not exist in garch_forecasts_latest (view has cond_vol); missing horizon=1 filter |
| 18 | Position sizing uses GARCH forecast; three modes supported | VERIFIED | compute_realized_vol_position(): garch_vol/garch_mode/blend_weight; advisory mode logs and falls back |
| 19 | GARCH-VaR available alongside existing VaR methods | VERIFIED | garch_var() with student_t.ppf; VaRResult.garch_var_value; compute_var_suite garch_sigma; garch_95/99 in _VALID_METHODS |
| 20 | Daily refresh includes GARCH stage after features, before signals | VERIFIED | TIMEOUT_GARCH=1800; run_garch_forecasts(); --garch/--no-garch; stage lines 3149-3157 |
| 21 | Comparison report shows GARCH vs estimator accuracy per asset | VERIFIED | run_garch_comparison.py 729 lines; imports 6 evaluator functions; markdown + 2 CSVs |

**Score:** 19/21 truths verified (1 failed, 1 partial)

---

### Required Artifacts

| Artifact | Lines | Status | Details |
|----------|-------|--------|---------|
| alembic/versions/i3j4k5l6m7n8_garch_tables.py | 183 | VERIFIED | Correct PK, CHECK constraints, FK to garch_diagnostics.run_id, mat view with unique index; revises h2i3j4k5l6m7 |
| src/ta_lab2/analysis/garch_engine.py | 377 | VERIFIED | fit_all_variants, fit_single_variant, generate_forecasts, compute_ljung_box_pvalue, GARCHResult, MODEL_SPECS, FIGARCH_MIN_OBS=200 |
| src/ta_lab2/scripts/garch/__init__.py | - | VERIFIED | Package marker |
| src/ta_lab2/scripts/garch/garch_state_manager.py | 302 | VERIFIED | GARCHStateConfig frozen dataclass; GARCHStateManager with ensure_state_table/load_state/update_state/get_assets_needing_refit |
| src/ta_lab2/scripts/garch/refresh_garch_forecasts.py | 672 | VERIFIED | CLI with all specified args; NullPool; carry-forward decay; GK fallback; mat view refresh |
| src/ta_lab2/analysis/garch_evaluator.py | 423 | VERIFIED | rmse_loss, qlike_loss, mincer_zarnowitz_r2, compute_realized_vol_proxy, combined_score, rolling_oos_evaluate, evaluate_all_models |
| src/ta_lab2/analysis/garch_blend.py | 403 | PARTIAL | BlendConfig/compute_blend_weights/blend_vol_simple work correctly; get_blended_vol SQL bug: h1_vol vs cond_vol; missing horizon=1 filter |
| src/ta_lab2/analysis/vol_sizer.py | 409 | VERIFIED | garch_vol/garch_mode/blend_weight in compute_realized_vol_position; garch_vol_series/garch_mode/garch_blend_weight in run_vol_sized_backtest |
| src/ta_lab2/analysis/var_simulator.py | 398 | VERIFIED | garch_var with student_t; VaRResult.garch_var_value; compute_var_suite garch_sigma; var_to_daily_cap garch_95/garch_99 |
| src/ta_lab2/scripts/garch/run_garch_comparison.py | 729 | VERIFIED | CLI with all specified args; imports from garch_evaluator; markdown + 2 CSV outputs |
| src/ta_lab2/scripts/run_daily_refresh.py | - | VERIFIED | TIMEOUT_GARCH=1800; run_garch_forecasts(); --garch/--no-garch; GARCH after features before signals |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| i3j4k5l6m7n8_garch_tables.py | garch_forecasts table | CREATE TABLE SQL | WIRED | Composite PK (6 cols), 3 CHECK constraints, FK to garch_diagnostics.run_id |
| garch_engine.py | arch library | lazy import _arch_model | WIRED | try/except lines 38-41; returns error GARCHResult if arch not installed |
| refresh_garch_forecasts.py | garch_engine.py | from ta_lab2.analysis.garch_engine import | WIRED | Line 50: imports MODEL_SPECS, GARCHResult, fit_all_variants |
| refresh_garch_forecasts.py | garch_forecasts (upsert) | temp table + ON CONFLICT DO UPDATE | WIRED | _UPSERT_SQL lines 263-274 with correct PK conflict target |
| refresh_garch_forecasts.py | returns_bars_multi_tf | SELECT ts, ret_log WHERE roll=FALSE | WIRED | _load_returns() lines 94-122 |
| garch_blend.py | garch_evaluator.py | from ta_lab2.analysis.garch_evaluator import rmse_loss | WIRED | Line 37 |
| run_garch_comparison.py | garch_evaluator.py | import 6 evaluator functions | WIRED | Lines 43-50 |
| run_daily_refresh.py | refresh_garch_forecasts.py | subprocess.run via garch/ subdir | WIRED | run_garch_forecasts() line 838; path: script_dir/garch/refresh_garch_forecasts.py |
| vol_sizer.py | garch_blend.py | (plan: blend_vol_simple import) | NOT WIRED | No import from garch_blend; inline blend used; math is identical |
| var_simulator.py | scipy.stats.t | from scipy.stats import t as student_t | WIRED | Line 32 |
| garch_blend.get_blended_vol | garch_forecasts_latest | SQL SELECT h1_vol | BROKEN | h1_vol column does not exist in view (has cond_vol); missing horizon=1 filter |

---

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| src/ta_lab2/analysis/garch_blend.py | 297 | SQL column h1_vol not in garch_forecasts_latest (view has cond_vol) | BLOCKER | get_blended_vol raises ProgrammingError at runtime; currently dead code so no live failure |
| src/ta_lab2/analysis/garch_blend.py | 297 | Missing AND horizon=1 filter in get_blended_vol SQL | WARNING | Would return 2 rows per model_type (h=1 and h=5) once column name fixed |
| src/ta_lab2/scripts/garch/run_garch_comparison.py | 525 | tf = args.tf.lower() lowercases 1D to 1d | WARNING | Hardcoded tf=1d in asset-ID query (line 170); zero-row result if DB stores uppercase 1D |

---

### Human Verification Required

None. All structural checks are programmatically verifiable.

---

### Gaps Summary

Two gaps found, one blocker and one architectural deviation:

**Gap 1 (Blocker): garch_blend.py:get_blended_vol SQL column mismatch**

The `garch_forecasts_latest` materialized view exposes `cond_vol` (not `h1_vol`).
The SQL query on line 297 of garch_blend.py is:

```sql
SELECT model_type, h1_vol
FROM garch_forecasts_latest
WHERE id = :asset_id AND venue_id = :venue_id AND tf = :tf
```

This will raise ProgrammingError: column h1_vol does not exist. The view has
cond_vol. Additionally, no horizon=1 filter means the query would return 2 rows
per model_type (horizon=1 and horizon=5) once the column name is fixed.

Required fix: change SQL to:

```sql
SELECT model_type, cond_vol
FROM garch_forecasts_latest
WHERE id = :asset_id
  AND venue_id = :venue_id
  AND tf = :tf
  AND horizon = 1
```

Also update lines 326-328: rename the unpacking variable from h1_vol to cond_vol.

Note: get_blended_vol is currently dead code (no consumer calls it anywhere in
the codebase), so there is no live runtime failure today. The bug surfaces when
any caller is added.

**Gap 2 (Info): vol_sizer.py does not import from garch_blend**

Plan 04 key link specifies vol_sizer.py should import blend_vol_simple from garch_blend.py.
The actual implementation performs an identical blend inline without any garch_blend import.
The blend math is correct. get_blended_vol is unreachable from vol_sizer.py.
This is an architectural deviation, not a functional failure.

Resolution options: (a) add import and delegate to blend_vol_simple to satisfy plan
key link, or (b) document inline blend as the approved pattern for vol_sizer.py.

---

_Verified: 2026-03-22T17:20:18Z_
_Verifier: Claude (gsd-verifier)_
