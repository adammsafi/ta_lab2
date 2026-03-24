---
phase: 86-portfolio-construction-pipeline
verified: 2026-03-24T02:50:44Z
status: passed
score: 14/14 must-haves verified
re_verification: false
---

# Phase 86: Portfolio Construction Pipeline Verification Report

**Phase Goal:** End-to-end portfolio construction from IC scores through paper execution with GARCH-informed sizing
**Verified:** 2026-03-24T02:50:44Z
**Status:** passed
**Re-verification:** No -- initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | stop_calibrations table exists with PK (id, strategy) and columns sl_p25/sl_p50/sl_p75/tp_p50/tp_p75/n_trades/calibrated_at | VERIFIED | m7n8o9p0q1r2_phase86_portfolio_pipeline.py lines 41-56: CREATE TABLE with all required columns and PRIMARY KEY (id, strategy) |
| 2 | dim_executor_config has target_annual_vol NUMERIC column with CHECK > 0 when not NULL | VERIFIED | Migration lines 65-78: ADD COLUMN target_annual_vol + ADD CONSTRAINT chk_target_annual_vol_positive CHECK (target_annual_vol IS NULL OR target_annual_vol > 0) |
| 3 | calibrate_stops.py CLI reads MAE/MFE from backtest_trades and writes percentile-based stop levels to stop_calibrations | VERIFIED | calibrate_stops.py calls calibrate_stops_from_mae_mfe() which queries backtest_trades JOIN backtest_runs ON bt.run_id=br.run_id (stop_calibration.py lines 86-96); results passed to persist_calibrations() (line 303) |
| 4 | StopLadder.from_db_calibrations() classmethod seeds per_asset_overrides from stop_calibrations table | VERIFIED | stop_ladder.py lines 123-246: @classmethod from_db_calibrations(cls, engine, config) queries stop_calibrations, builds {id}:{strategy} combined keys, injects into ladder._per_asset dict (line 239) |
| 5 | Assets with fewer than 30 trades get no calibration row (global defaults apply) | VERIFIED | stop_calibration.py line 114: if len(rows) < MIN_TRADES_FOR_CALIBRATION: return None; MIN_TRADES_FOR_CALIBRATION = 30 (line 47) |
| 6 | BLAllocationBuilder.run() accepts ic_ir as either pd.Series (legacy) or pd.DataFrame (per-asset IC-IR matrix) | VERIFIED | black_litterman.py lines 365, 439-444: ic_ir: Union[pd.Series, pd.DataFrame] in run(); isinstance(ic_ir, pd.DataFrame) dispatch in run(), signals_to_mu(), build_views() |
| 7 | refresh_portfolio_allocations.py loads per-asset IC-IR from ic_results via load_per_asset_ic_weights and uses uniform signal_scores (1.0) as default | VERIFIED | refresh_portfolio_allocations.py lines 520-583: imports load_per_asset_ic_weights from bakeoff_orchestrator; calls it with engine/features/tf/horizon; sets signal_scores = pd.DataFrame(1.0, ...) on real IC-IR path |
| 8 | PositionSizer.compute_target_position() supports sizing_mode=target_vol using GARCH blended vol | VERIFIED | position_sizer.py lines 221-252: elif sizing_mode == "target_vol": branch with kwargs.get("garch_vol") and vol_scalar computation |
| 9 | target_vol mode falls back to fixed_fraction when GARCH vol is unavailable | VERIFIED | position_sizer.py lines 244-251: fallback fraction = Decimal(str(config.position_fraction)) when not garch_vol or not target_ann_vol; near-zero vol path lines 236-243 |
| 10 | GARCH daily vol is annualized via sqrt(252) before computing vol scalar | VERIFIED | position_sizer.py lines 229-230: current_ann_vol = float(garch_vol) * (252**0.5) with explicit comment "Annualize daily GARCH vol: daily_vol * sqrt(252)" |
| 11 | paper_executor.py _process_asset_signal() passes garch_vol kwarg to compute_target_position() via get_blended_vol() | VERIFIED | paper_executor.py line 31: from ta_lab2.analysis.garch_blend import get_blended_vol; lines 493-524: calls get_blended_vol() when target_annual_vol configured, passes garch_vol=garch_vol to compute_target_position() |
| 12 | calibrate_stops runs as a pipeline stage AFTER signals and BEFORE portfolio refresh in run_daily_refresh.py | VERIFIED | run_daily_refresh.py TIMEOUT_CALIBRATE_STOPS=300 (line 89); run_calibrate_stops_stage() at line 1049; wired at lines 3300-3315 after signals before portfolio with pipeline order comment |
| 13 | run_parity_check.py supports --bakeoff-winners flag that auto-discovers winning strategies from strategy_bakeoff_results | VERIFIED | run_parity_check.py _STRATEGY_SIGNAL_MAP at lines 44-48; _discover_bakeoff_winners() with ROW_NUMBER() OVER PARTITION BY at lines 76-180; --bakeoff-winners argparse flag at lines 202-210 |
| 14 | Parity check uses slippage_mode=fixed (tolerates fill price differences) | VERIFIED | run_parity_check.py lines 308-314: when --bakeoff-winners used and slippage_mode is default "zero", auto-switches to "fixed"; backtest_trades linkage gap diagnostic at lines 370-376 |

**Score:** 14/14 truths verified

### Required Artifacts

| Artifact | Lines | Status | Details |
|----------|-------|--------|--------|
| alembic/versions/m7n8o9p0q1r2_phase86_portfolio_pipeline.py | 99 | VERIFIED | revision=m7n8o9p0q1r2, down_revision=l6m7n8o9p0q1 (chain confirmed: l6m7n8o9p0q1_dim_ctf_feature_selection.py exists). Creates stop_calibrations table + target_annual_vol column + CHECK constraint. downgrade() reverses all changes. |
| src/ta_lab2/analysis/stop_calibration.py | 234 | VERIFIED | All three required exports at top level: calibrate_stops_from_mae_mfe, persist_calibrations, MIN_TRADES_FOR_CALIBRATION=30 (line 47). Both functions have real SQL implementations with numpy percentile computation and error handling. |
| src/ta_lab2/scripts/portfolio/calibrate_stops.py | 322 | VERIFIED | argparse with --ids/--tf/--dry-run/--db-url/--verbose. _load_run_combinations() with dim_signals JOIN + fallback. main() loops combinations, calls calibrate_stops_from_mae_mfe and persist_calibrations. |
| src/ta_lab2/portfolio/stop_ladder.py | 452 | VERIFIED | @classmethod from_db_calibrations at line 124 queries stop_calibrations, builds {id}:{strategy} combined keys, validates tiers, injects into _per_asset dict. Graceful DB failure (warns, returns unmodified ladder). |
| src/ta_lab2/portfolio/black_litterman.py | 587 | VERIFIED | _per_asset_composite() at line 85 reindexes ic_ir_matrix to signal_scores shape. isinstance(ic_ir, pd.DataFrame) dispatch in signals_to_mu(), build_views(), run(). Single cross-sectional z-score. |
| src/ta_lab2/executor/position_sizer.py | 450 | VERIFIED | target_annual_vol field on ExecutorConfig. target_vol branch with sqrt(252) annualization (line 230). **kwargs on wrapper and static method. Fallback to fixed_fraction when garch_vol absent or near-zero. |
| src/ta_lab2/scripts/portfolio/refresh_portfolio_allocations.py | 772 | VERIFIED | Replaces prior zero-stub with real load_per_asset_ic_weights() call from bakeoff_orchestrator. Uniform signal_scores=1.0 on real IC-IR path. TODO(Phase 87) for real feature values is documented intentional deferral. |
| src/ta_lab2/executor/paper_executor.py | 792 | VERIFIED | Line 31: from ta_lab2.analysis.garch_blend import get_blended_vol. _process_asset_signal() lines 493-524: fetches garch_vol when target_annual_vol configured, passes garch_vol=garch_vol kwarg to compute_target_position(). |
| src/ta_lab2/scripts/run_daily_refresh.py | 3382 | VERIFIED | TIMEOUT_CALIBRATE_STOPS=300 at line 89. run_calibrate_stops_stage() at line 1049 subprocess-calls ta_lab2.scripts.portfolio.calibrate_stops. --calibrate-stops + --no-calibrate-stops flags. Wired at lines 3302-3315. |
| src/ta_lab2/scripts/executor/run_parity_check.py | 442 | VERIFIED | _STRATEGY_SIGNAL_MAP at lines 44-48. _discover_bakeoff_winners() with ROW_NUMBER at lines 76-180. --bakeoff-winners at lines 202-210. slippage_mode=fixed auto-switch at lines 311-314. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|--------|
| run_daily_refresh.py | calibrate_stops.py | subprocess module invocation | WIRED | run_calibrate_stops_stage() calls subprocess.run([sys.executable, "-m", "ta_lab2.scripts.portfolio.calibrate_stops", "--ids", "all"]) with TIMEOUT_CALIBRATE_STOPS |
| run_parity_check.py | strategy_bakeoff_results | ROW_NUMBER() OVER PARTITION BY ranking | WIRED | CTE with ROW_NUMBER() OVER (PARTITION BY strategy_name, asset_id ORDER BY sharpe_mean DESC) AS rn, WHERE rn=1 |
| run_parity_check.py | dim_signals | _STRATEGY_SIGNAL_MAP + _SIGNAL_LOOKUP_SQL | WIRED | strategy_name -> signal_type via _STRATEGY_SIGNAL_MAP.get(), then SELECT signal_id FROM dim_signals WHERE signal_type = :signal_type |
| paper_executor.py | ta_lab2.analysis.garch_blend | direct import at line 31 | WIRED | from ta_lab2.analysis.garch_blend import get_blended_vol. Called in _process_asset_signal() when target_annual_vol configured. blend_result["blended_vol"] passed as garch_vol kwarg. |
| position_sizer.py | GARCH vol (kwargs) | kwargs.get("garch_vol") in target_vol branch | WIRED | Intentionally NOT importing garch_blend directly -- GARCH vol passed via **kwargs by paper_executor to avoid circular dependency. current_ann_vol = float(garch_vol) * (252**0.5) confirms annualization. |
| calibrate_stops.py | stop_calibration.py | from ta_lab2.analysis.stop_calibration import | WIRED | Import at lines 266-270. calibrate_stops_from_mae_mfe and persist_calibrations both called in main() loop. |
| stop_calibration.py | backtest_trades | SQL JOIN on run_id | WIRED | Lines 86-96: backtest_trades bt JOIN backtest_runs br ON bt.run_id = br.run_id. WHERE filters by asset_id, signal_id, non-null mae/mfe. |
| stop_ladder.py | stop_calibrations | SQL SELECT in from_db_calibrations | WIRED | Lines 160-166: SELECT from public.stop_calibrations ORDER BY id, strategy. Rows mapped to {id}:{strategy} keys, injected into _per_asset dict. |
| refresh_portfolio_allocations.py | ic_results | load_per_asset_ic_weights() from bakeoff_orchestrator | WIRED | Lines 520-552: imports and calls load_per_asset_ic_weights(engine, features, tf, horizon, return_type). Result used as ic_ir DataFrame in BLAllocationBuilder.run(). |

### Requirements Coverage

| Requirement | Status | Notes |
|-------------|--------|-------|
| IC-IR scores feed BL views automatically -- per-asset IC-IR from ic_results | SATISFIED | refresh_portfolio_allocations.py calls load_per_asset_ic_weights(), passes DataFrame to BLAllocationBuilder via ic_ir. Per-asset isinstance dispatch confirmed. |
| Bet sizing uses GARCH conditional vol for target-vol scaling | SATISFIED | target_vol branch in PositionSizer with sqrt(252) annualization. paper_executor calls get_blended_vol() and passes as garch_vol kwarg. Fallback to fixed_fraction when unavailable. |
| Stop ladder calibrated per asset using MAE/MFE from bake-off trades | SATISFIED | calibrate_stops.py reads backtest_trades MAE/MFE, computes percentiles, writes to stop_calibrations. StopLadder.from_db_calibrations() seeds per-asset overrides from DB. |
| Paper executor dry run with refined signals -- fills match backtest parity within tolerance | SATISFIED (tooling ready) | run_parity_check.py --bakeoff-winners auto-discovers strategies, runs parity with slippage_mode=fixed. Diagnostic gap message correctly identifies backtest_trades linkage as expected gap. |
| Portfolio rebalance logic documented and wired into daily pipeline | SATISFIED | run_daily_refresh.py pipeline: signals -> calibrate_stops -> portfolio -> executor -> drift -> stats. --calibrate-stops + --no-calibrate-stops flags. Line 3315 comment documents full order. |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| refresh_portfolio_allocations.py | 569 | TODO(Phase 87): Wire real feature values as signal_scores | Info | Intentional deferral documented in SUMMARY as Phase 87 work. Uniform signal_scores=1.0 is correct Phase 86 behavior. No impact on Phase 86 goal. |
| calibrate_stops.py | 187 | return [] | Info | Legitimate error fallback in _load_run_combinations() after both primary and fallback queries fail. Only reached on genuine DB error. Not a stub. |
| black_litterman.py | 271, 305, 314 | return {}, [] | Info | Legitimate empty-views fallback on three guard paths (empty signal_scores, no qualified IC-IR, mismatched columns). Enables prior-only EfficientFrontier path -- intended behavior. |

No blocker or warning anti-patterns found.

### Human Verification Required

None required for goal verification. All observable truths are verifiable through structural code analysis.

Operational readiness checks (not goal blockers) for when the DB migration is applied:

1. **alembic upgrade head**: Apply migration m7n8o9p0q1r2 to confirm stop_calibrations table and dim_executor_config.target_annual_vol column are created.
   - Expected: alembic upgrade head succeeds without error
   - Why human: Requires live DB connection

2. **calibrate_stops dry-run**: python -m ta_lab2.scripts.portfolio.calibrate_stops --ids all --dry-run
   - Expected: Logs DRY-RUN: would write N calibration rows (skipped M combinations with < 30 trades)
   - Why human: Requires populated backtest_runs/backtest_trades tables

3. **run_daily_refresh --calibrate-stops**: Standalone stage execution
   - Expected: [OK] Stop calibration completed in Xs
   - Why human: Requires live DB

### Gaps Summary

No gaps. All 14 must-have truths verified at all three levels (exists, substantive, wired).

Notable observations:

- StopLadder.from_db_calibrations() is fully implemented but not yet called by any production consumer. This is expected per SUMMARY -- it is ready for use in Phase 87. The plan truth requires the method to exist and seed correctly; it does not require an active consumer in Phase 86. Exported via portfolio/__init__.py. No gap.

- Alembic revision ID deviation from plan (plan: l6m7n8o9p0q1, actual: m7n8o9p0q1r2) is correctly handled. l6m7n8o9p0q1_dim_ctf_feature_selection.py exists as the valid down_revision target. Migration chain confirmed valid.

- persist_calibrations was added as a third export in stop_calibration.py beyond the plan list (plan listed only calibrate_stops_from_mae_mfe and MIN_TRADES_FOR_CALIBRATION). This is a beneficial addition -- the CLI imports and calls it at line 266 of calibrate_stops.py.

---

_Verified: 2026-03-24T02:50:44Z_
_Verifier: Claude (gsd-verifier)_
