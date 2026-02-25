---
phase: 42-strategy-bake-off
verified: 2026-02-25T03:15:29Z
status: passed
score: 20/20 must-haves verified
---

# Phase 42: Strategy Bake-Off Verification Report

**Phase Goal:** Run IC feature ranking, walk-forward backtests with purged K-fold CV, composite scoring, strategy selection, and produce a formal bake-off scorecard.
**Verified:** 2026-02-25T03:15:29Z
**Status:** PASSED
**Re-verification:** No - initial verification

---

## Goal Achievement

**Score:** 20/20 must-haves verified

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | IC scores computed for cmc_features columns across qualifying asset-TF pairs | VERIFIED | run_ic_sweep.py calls batch_compute_ic + save_ic_results per (asset_id, tf) pair; 47,614 IC rows in cmc_ic_results |
| 2 | IC scores computed for AMA indicator columns with graceful degradation when absent | VERIFIED | _discover_ama_combos() uses table_exists() pre-check; returns empty list when cmc_ama_multi_tf_u absent; 0 AMA rows, no crash |
| 3 | Features ranked by IC and IC-IR; top features identified | VERIFIED | feature_ic_ranking.csv (98 rows); top: vol_rs_126_is_outlier (IC-IR=1.41), bb_ma_20 (0.97) |
| 4 | Regime-conditional IC breakdown for BTC/ETH 1D | VERIFIED | _REGIME_ASSET_IDS = frozenset([1, 1027]); compute_ic_by_regime called for BTC/ETH + 1D |
| 5 | Sparse asset-TF combinations logged and skipped | VERIFIED | _discover_cmc_features_pairs() queries asset_data_coverage with n_rows >= min_bars; fallback to direct GROUP BY |
| 6 | Walk-forward OOS metrics for all 3 signal types on BTC/ETH 1D | VERIFIED | 3 strategies (ema_trend, rsi_mean_revert, breakout_atr) x KRAKEN_COST_MATRIX; 480 rows in strategy_bakeoff_results |
| 7 | PurgedKFold 10-fold 20-bar embargo and CPCV 45 combos both run | VERIFIED | BakeoffConfig(n_folds=10, embargo_bars=20, cpcv_n_test_splits=2); PurgedKFoldSplitter + CPCVSplitter both wired |
| 8 | Cost matrix covers 6 spot + 6 perps scenarios | VERIFIED | KRAKEN_COST_MATRIX: spot-maker/taker x 3 slippage + perps-maker/taker + funding_bps_day=3.0 x 3 slippage = 12 |
| 9 | PSR per strategy; DSR across all strategies | VERIFIED | compute_psr(all_oos) per strategy; _compute_and_attach_dsr() groups by (asset, tf, cost, cv_method), divides by sqrt(365) |
| 10 | No data leakage: parameters fixed, evaluated on test fold | VERIFIED | Fixed-parameter walk-forward; EMA signals use pre-computed DB columns; restricted to test_idx for evaluation |
| 11 | Results persisted to strategy_bakeoff_results DB table | VERIFIED | Alembic migration e74f5622e710; _persist_results() INSERT ON CONFLICT DO UPDATE; UNIQUE on 6 columns |
| 12 | Composite scores under 4 weighting schemes | VERIFIED | WEIGHT_SCHEMES: balanced(30/30/25/15), risk_focus(20/45/25/10), quality_focus(35/20/35/10), low_cost(30/25/20/25) |
| 13 | V1 hard gates applied: Sharpe < 1.0 or MaxDD > 15% flagged | VERIFIED | apply_v1_gates() with min_sharpe=1.0, max_drawdown_pct=15.0; gate_failures column in composite_scores.csv |
| 14 | Sensitivity analysis shows robust top-2 across 3 of 4 schemes | VERIFIED | n_times_top2 + robust columns; ema_trend(17,77) robust=True 4/4; ema_trend(21,50) robust=True 3/4 |
| 15 | Turnover metric incorporated into composite score | VERIFIED | norm_turnover = _minmax_norm(df["turnover"], invert=True); weight=0.15/0.10/0.10/0.25 across schemes |
| 16 | 2 strategies selected with walk-forward OOS parameters and explicit rationale | VERIFIED | STRATEGY_SELECTION.md 430 lines; ema_trend(17,77) + ema_trend(21,50); walk-forward fixed parameter methodology |
| 17 | Ensemble blending attempted and documented | VERIFIED | _attempt_ensemble_blend() in select_strategies.py; documented as failing V1 gates in both output documents |
| 18 | Expected performance range and cost sensitivity documented | VERIFIED | mean +/- std from OOS folds; 12-scenario cost sensitivity per strategy with break-even analysis |
| 19 | Formal scorecard with IC rankings, strategy comparison, selection rationale, Plotly charts | VERIFIED | BAKEOFF_SCORECARD.md 443 lines; 6 sections; 5 HTML charts each ~4.8MB |
| 20 | Scorecard self-contained with structured data sources for reproducibility | VERIFIED | Self-contained declaration; Section 6 Appendix lists CSV sources, DB tables, and scripts |

---

### Required Artifacts

| Artifact | Status | Details |
|----------|--------|---------|
| `src/ta_lab2/scripts/analysis/run_ic_sweep.py` | VERIFIED | 1,119 lines; batch_compute_ic + compute_ic_by_regime + save_ic_results wired; AMA graceful degradation via table_exists() |
| `src/ta_lab2/backtests/bakeoff_orchestrator.py` | VERIFIED | 1,000 lines; BakeoffConfig, KRAKEN_COST_MATRIX, run_purged_kfold_backtest, run_cpcv_backtest, _compute_and_attach_dsr |
| `src/ta_lab2/scripts/backtests/run_bakeoff.py` | VERIFIED | 492 lines; argparse --dry-run/--spot-only/--overwrite/--all-assets; BakeoffOrchestrator instantiated at line 467 |
| `src/ta_lab2/backtests/composite_scorer.py` | VERIFIED | 559 lines; WEIGHT_SCHEMES, V1_GATES, compute_composite_score, apply_v1_gates, sensitivity_analysis, blend_signals |
| `src/ta_lab2/scripts/analysis/run_bakeoff_scoring.py` | VERIFIED | 401 lines; all composite_scorer exports imported; writes composite_scores.csv + sensitivity_analysis.csv |
| `src/ta_lab2/scripts/analysis/select_strategies.py` | VERIFIED | 1,335 lines; _compute_cost_sensitivity, _attempt_ensemble_blend, _write_selection_document, _run_final_validation |
| `src/ta_lab2/scripts/analysis/generate_bakeoff_scorecard.py` | VERIFIED | 1,547 lines; 5 Plotly chart generators (go.Bar, go.Scatter, go.Heatmap); 6 section builders |
| `alembic/versions/e74f5622e710_add_strategy_bakeoff_results.py` | VERIFIED | Creates strategy_bakeoff_results with UNIQUE 6-column constraint + index |
| `reports/bakeoff/feature_ic_ranking.csv` | VERIFIED | 98 rows; feature, mean_abs_ic, mean_ic_ir, mean_abs_ic_ir, n_observations, n_asset_tf_pairs |
| `reports/bakeoff/composite_scores.csv` | VERIFIED | 41 rows (10 strategies x 4 schemes); gate_failures and passes_v1_gates columns populated |
| `reports/bakeoff/sensitivity_analysis.csv` | VERIFIED | 11 rows; n_times_top2 and robust columns confirmed; ema_trend(17,77) robust=True |
| `reports/bakeoff/final_validation.csv` | VERIFIED | 3 rows; Sharpe=1.647 and 1.705; v1_both_pass=False both rows |
| `reports/bakeoff/STRATEGY_SELECTION.md` | VERIFIED | 430 lines; executive summary, methodology, per-strategy sections, ensemble analysis, V1 deployment config |
| `reports/bakeoff/BAKEOFF_SCORECARD.md` | VERIFIED | 443 lines; 6 sections; table of contents; self-contained declaration |
| `reports/bakeoff/charts/` 5 HTML charts | VERIFIED | ic_ranking, strategy_comparison, sensitivity_heatmap, 2x cost_sensitivity; each ~4.8MB |

---

### Key Link Verification

| From | To | Via | Status |
|------|-----|-----|--------|
| run_ic_sweep.py | cmc_ic_results DB | save_ic_results() per (asset_id, tf) at lines 534, 674 | WIRED |
| run_ic_sweep.py | regime-conditional IC | _REGIME_ASSET_IDS guard + compute_ic_by_regime at line 497 | WIRED |
| run_bakeoff.py | bakeoff_orchestrator.py | BakeoffOrchestrator(engine, config).run() at line 467 | WIRED |
| bakeoff_orchestrator.py | strategy_bakeoff_results | _persist_results() INSERT ON CONFLICT at line 783 | WIRED |
| bakeoff_orchestrator.py | PSR/DSR library | compute_psr() at line 571; _compute_and_attach_dsr() at line 997 with /sqrt(365) | WIRED |
| run_bakeoff_scoring.py | composite_scorer.py | from ta_lab2.backtests.composite_scorer import ... all exports | WIRED |
| select_strategies.py | composite CSVs | pd.read_csv(_COMPOSITE_CSV) + pd.read_csv(_SENSITIVITY_CSV) | WIRED |
| select_strategies.py | STRATEGY_SELECTION.md + final_validation.csv | _write_selection_document() + _run_final_validation() | WIRED |
| generate_bakeoff_scorecard.py | 4 CSV sources + DB | load_ic_ranking(), load_composite_scores(), load_sensitivity_analysis(), load_bakeoff_results() | WIRED |
| generate_bakeoff_scorecard.py | 5 Plotly HTML charts | go.Bar/Scatter/Heatmap + fig.write_html() confirmed at ~4.8MB each | WIRED |

---

### Requirements Coverage

| Requirement | Status | Notes |
|-------------|--------|-------|
| IC feature ranking sweep (cmc_features + AMA) | SATISFIED | cmc_features swept 47,614 rows; AMA gracefully skipped when table absent |
| Walk-forward backtest (10-fold purged KFold + CPCV) | SATISFIED | Both CV methods implemented; 480 OOS rows persisted |
| 12-scenario Kraken cost matrix | SATISFIED | 6 spot + 6 perps confirmed in KRAKEN_COST_MATRIX |
| PSR/DSR per strategy | SATISFIED | PSR per strategy + DSR cross-strategy with /sqrt(365) de-annualization fix |
| Composite scoring (4 schemes, V1 gates, sensitivity, turnover) | SATISFIED | All 4 weighting schemes; gates flag but do not eliminate; robust threshold 3/4; turnover inverted |
| Strategy selection (2 strategies, walk-forward params, ensemble, cost sensitivity, expected range) | SATISFIED | ema_trend(17,77) + ema_trend(21,50) selected with full documentation |
| Formal scorecard (6 sections, Plotly charts, self-contained) | SATISFIED | 443-line BAKEOFF_SCORECARD.md + 5 HTML charts |

---

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| bakeoff_orchestrator.py | 696 | pkf_result["dsr"] = float("nan")  # placeholder | INFO | Intentional: DSR computed cross-strategy after all per-strategy results collected; not a stub |
| run_ic_sweep.py | 161, 184 | return [] | INFO | Legitimate early returns from _discover_ama_combos() when table absent or query fails; graceful degradation |
| generate_bakeoff_scorecard.py | 175, 181, 184 | return [] | INFO | Legitimate early returns from CSV loaders when files absent; graceful degradation |

No blockers found. All patterns are intentional graceful degradation, not implementation stubs.

---

### Human Verification Required

None required to confirm goal achievement. Optional spot-checks:

**1. End-to-end pipeline execution**
- Test: Run `python -m ta_lab2.scripts.analysis.run_ic_sweep --dry-run --min-bars 500`
- Expected: Lists qualifying asset-TF pairs without computing IC
- Why human: Requires live DB connection with cmc_features populated

**2. Scorecard chart interactivity**
- Test: Open reports/bakeoff/charts/ic_ranking.html in browser
- Expected: Interactive Plotly bar chart showing top features by IC-IR
- Why human: Chart rendering requires visual inspection

---

## Detailed Findings by Plan

### Plan 01: IC Feature Sweep

All must-haves verified. run_ic_sweep.py (1,119 lines) fully wires batch_compute_ic, compute_ic_by_regime, and save_ic_results. Regime scope enforced via _REGIME_ASSET_IDS = frozenset([1, 1027]). Asset-TF pair discovery queries asset_data_coverage with min_bars filter and falls back to direct GROUP BY. AMA table absence handled via table_exists() pre-check. feature_ic_ranking.csv confirmed at 98 rows.

AMA IC sweep produced 0 rows because cmc_ama_multi_tf_u is not populated in this DB. This is the expected behavior per plan decisions and handled gracefully.

### Plan 02: Walk-Forward Backtest

All must-haves verified. Three signal types wired (ema_trend 4 combos, rsi_mean_revert 3 combos, breakout_atr 3 combos). BakeoffConfig confirms 10-fold + C(10,2)=45 CPCV. KRAKEN_COST_MATRIX has exactly 12 scenarios. PSR computed via compute_psr(all_oos); DSR computed cross-strategy via _compute_and_attach_dsr() with /sqrt(365) de-annualization fix at lines 967-968.

Data leakage analysis: Signals are generated on the full df then restricted to test_idx. Since EMA signals use pre-computed DB columns where each bar value is computed from historical data only, this does not introduce look-ahead bias. Parameters are fixed (not optimized on test fold). Documented: "Generate signals on full df (fixed params, no leakage in label generation)".

Expanding-window re-optimization deliberately deferred per plan decision; documented in module docstring.

### Plan 03: Composite Scoring

All must-haves verified. WEIGHT_SCHEMES confirms 4 scheme names and weights. V1_GATES applied as flags, not eliminators. sensitivity_analysis() produces n_times_top2 + robust (True if >= 3/4). composite_scores.csv (41 rows = 10 strategies x 4 schemes + header) and sensitivity_analysis.csv (11 rows) confirmed. ema_trend(17,77) robust=True 4/4; ema_trend(21,50) robust=True 3/4.

### Plan 04: Strategy Selection

All must-haves verified. select_strategies.py (1,335 lines) implements full pipeline. ema_trend(17,77) and ema_trend(21,50) selected. Parameters documented as walk-forward fixed. Ensemble blend attempted and documented as failing V1 gates (both strategies lose in same bear-market regimes). Expected performance range via mean +/- std. V1 deployment config: position_frac=0.10, circuit_breaker_dd=0.15. final_validation.csv: Sharpe=1.647 and 1.705.

### Plan 05: Bake-Off Scorecard

All must-haves verified. generate_bakeoff_scorecard.py (1,547 lines) implements 5 Plotly chart generators and 6 section builders. BAKEOFF_SCORECARD.md (443 lines) confirmed with all 6 sections. Five HTML charts at ~4.8MB each. Scorecard explicitly declares self-contained design. Section 6 Appendix documents all CSV sources, DB table references, and scripts for reproducibility.

---

## Overall Assessment

Phase 42 goal achieved in full. All 5 plans delivered working, wired implementations. The phase produced a complete IC sweep pipeline, walk-forward backtest engine with purged K-fold and CPCV, composite scoring framework, formal strategy selection document, and a self-contained scorecard with Plotly charts.

The two selected strategies have explicit documentation of OOS walk-forward parameters, expected performance ranges (mean +/- std across folds), cost sensitivity across 12 scenarios, ensemble analysis, and V1 deployment configuration for Phase 45.

---

_Verified: 2026-02-25T03:15:29Z_
_Verifier: Claude (gsd-verifier)_
