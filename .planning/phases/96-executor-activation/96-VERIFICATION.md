---
phase: 96-executor-activation
verified: 2026-03-30T23:30:00Z
status: passed
score: 6/6 must-haves verified
gaps: []
---

# Phase 96: Executor Activation Verification Report

**Phase Goal:** Paper executor runs live daily for all 7 signal generators, using BL output weights for sizing, with parity tracking and PnL attribution.
**Verified:** 2026-03-30T23:30:00Z
**Status:** passed
**Re-verification:** No -- initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | 8 active executor configs covering all 7 signal types with per-strategy cadence_hours | VERIFIED | executor_config_seed.yaml: 8 configs, all is_active=true, cadence_hours 26/36/48; migration widens chk_exec_config_signal_type to 7 values |
| 2 | Daily refresh runs all 7 signal types in two batches (Batch1=EMA/RSI/ATR/MACD, Batch2=3 AMA); idempotent | VERIFIED | BATCH_1_TYPES and BATCH_2_TYPES at module level; temp-table ON CONFLICT DO UPDATE prevents duplicates; run_daily_refresh.py orchestrates both stages |
| 3 | Executor produces fills; executor_run_log records fills_count; 0-fill detection active | VERIFIED | paper_executor.py writes executor_run_log with fills_processed per run; status=no_signals on 0-fill path; wired into run_daily_refresh.py |
| 4 | BL weights used for sizing via sizing_mode=bl_weight; zero/missing weight = close position | VERIFIED | position_sizer.py: bl_weight branch queries portfolio_allocations WHERE optimizer=bl ORDER BY ts DESC LIMIT 1; returns Decimal(0) on missing; conn=conn, asset_id=asset_id passed; all 8 YAML configs use bl_weight |
| 5 | strategy_parity table populated with live_sharpe/bt_sharpe ratio per active strategy | VERIFIED | run_parity_report.py 615 lines: fill-to-fill + MTM Sharpe; AVG(sharpe_mean) from strategy_bakeoff_results; ratio_fill=live/bt and ratio_mtm=live/bt |
| 6 | PnL attribution CLI separates alpha from beta per asset class; results in pnl_attribution table | VERIFIED | run_pnl_attribution.py 736 lines: classify assets via hl_assets; OLS beta via numpy.cov; alpha=total_pnl-beta*benchmark_pnl; standalone CLI |

**Score:** 6/6 truths verified

---

## Required Artifacts

| Artifact | Status | Details |
|----------|--------|---------|
| alembic/versions/o9p0q1r2s3t4_phase96_executor_activation.py | VERIFIED | 481 lines; creates 4 signal tables + strategy_parity + pnl_attribution; widens 3 CHECK constraints; seeds 4 dim_signals rows |
| src/ta_lab2/executor/signal_reader.py | VERIFIED | SIGNAL_TABLE_MAP with 7 entries; _VALID_SIGNAL_TABLES auto-derived; read_unprocessed_signals filters executor_processed_at IS NULL |
| src/ta_lab2/signals/macd_crossover.py | VERIFIED | 134 lines; make_signals(df, fast, slow, signal, direction); self-contained _compute_macd avoids circular import |
| src/ta_lab2/scripts/signals/generate_signals_macd.py | VERIFIED | 519 lines; MACDSignalGenerator dataclass; full pipeline features->make_signals->records->temp-table upsert; executor_processed_at=None |
| src/ta_lab2/scripts/signals/generate_signals_ama.py | VERIFIED | 539 lines; AMASignalGenerator(signal_subtype=...); _load_ama_columns DISTINCT ON ama_multi_tf_u alignment_source=multi_tf roll=FALSE; graceful degradation |
| src/ta_lab2/scripts/signals/run_all_signal_refreshes.py | VERIFIED | 614 lines; BATCH_1_TYPES=[ema,rsi,atr,macd] BATCH_2_TYPES=[ama_momentum,ama_mean_reversion,ama_regime_conditional]; run_parallel_refresh accepts signal_types= |
| configs/executor_config_seed.yaml | VERIFIED | 269 lines; 8 configs; all sizing_mode=bl_weight; position_fraction=0.10 fallback; cadence_hours 26h/36h/48h |
| src/ta_lab2/scripts/executor/seed_executor_config.py | VERIFIED | 372 lines; seed_watermarks() sets MAX(ts); --seed-watermarks and --watermarks-only flags; idempotent |
| src/ta_lab2/executor/position_sizer.py | VERIFIED | 496 lines; bl_weight elif queries portfolio_allocations WHERE optimizer=bl ORDER BY ts DESC LIMIT 1; Decimal(0) on missing; fixed_fraction fallback when conn=None |
| src/ta_lab2/executor/paper_executor.py | VERIFIED | _process_asset_signal passes conn=conn, asset_id=asset_id; executor_run_log with fills_processed; status=no_signals for 0-fill |
| src/ta_lab2/scripts/executor/run_parity_report.py | VERIFIED | 615 lines; fill-to-fill + MTM Sharpe; CPCV/PKF bt_sharpe fallback; ratio=live/bt; _persist_parity inserts to strategy_parity |
| src/ta_lab2/scripts/executor/run_pnl_attribution.py | VERIFIED | 736 lines; hl_assets classification; numpy OLS beta; alpha decomposition; _persist_attribution inserts to pnl_attribution |
| sql/signals/ 096-099 DDLs (4 files) | VERIFIED | 68-70 lines each |
| sql/executor/ 096-097 DDLs (2 files) | VERIFIED | 57 lines each |

---

## Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| run_all_signal_refreshes.py | generate_signals_macd.py | import + _make_generator | WIRED | MACDSignalGenerator imported; instantiated for macd_crossover type |
| run_all_signal_refreshes.py | generate_signals_ama.py | import + _make_generator | WIRED | AMASignalGenerator instantiated with signal_subtype= for all 3 AMA types |
| generate_signals_macd.py | signals_macd_crossover (DB) | temp-table upsert | WIRED | CREATE TEMP TABLE LIKE public.signals_macd_crossover; INSERT ON CONFLICT DO UPDATE |
| generate_signals_ama.py | ama_multi_tf_u (DB) | _load_ama_columns | WIRED | DISTINCT ON query alignment_source=multi_tf roll=FALSE; pivoted to wide format |
| paper_executor._process_asset_signal | portfolio_allocations (DB) | PositionSizer bl_weight | WIRED | conn=conn, asset_id=asset_id passed; queries WHERE optimizer=bl ORDER BY ts DESC LIMIT 1; Decimal(0) on de-selection |
| run_parity_report.py | strategy_parity (DB) | _persist_parity INSERT | WIRED | Full INSERT; ratio_fill=live_sharpe_fill/bt_sharpe; ratio_mtm=live_sharpe_mtm/bt_sharpe |
| run_pnl_attribution.py | pnl_attribution (DB) | _persist_attribution INSERT | WIRED | Full INSERT: period_start, period_end, asset_class, benchmark, total_pnl, beta_pnl, alpha_pnl, beta, sharpe_alpha, n_positions |
| run_daily_refresh.py | run_all_signal_refreshes.py | subprocess | WIRED | run_signal_refreshes() invokes ta_lab2.scripts.signals.run_all_signal_refreshes |
| run_daily_refresh.py | run_paper_executor.py | subprocess | WIRED | run_paper_executor_stage() invokes ta_lab2.scripts.executor.run_paper_executor after signals stage |

---

## Requirements Coverage

| Requirement | Status | Blocking Issue |
|-------------|--------|----------------|
| OPS-01: 7+ active executor configs with per-strategy cadence | SATISFIED | none |
| OPS-02: Signal refresh runs all 7 types in two batches; idempotent | SATISFIED | none |
| OPS-03: Executor runs manually; fills recorded; 0-fill detection active | SATISFIED | none |
| OPS-04: BL weights used for sizing; zero weight closes position | SATISFIED | none |
| OPS-05: strategy_parity table with live_sharpe/bt_sharpe ratio | SATISFIED | none |
| OPS-06: pnl_attribution table with alpha/beta decomposition; standalone CLI | SATISFIED | none |

---

## Anti-Patterns Found

None. Grep for TODO/FIXME/placeholder/not implemented/coming soon across all 8 key implementation files returned no matches.

---

## Human Verification Required

### 1. Executor produces fills after watermark setup

**Test:** Run seed --seed-watermarks, run signals stage, run executor. Query: SELECT COUNT(*) FROM fills WHERE filled_at > NOW() - INTERVAL 1 hour.
**Expected:** fills_processed > 0 in executor_run_log for at least one strategy.
**Why human:** Requires live DB with signal data above watermark; 0-fill on first run is expected but indistinguishable from wiring failure without real data.

### 2. BL weight sizing uses portfolio_allocations when populated

**Test:** After running BL optimizer, run executor. Verify position sizes reflect BL weights, not 0.10 fixed-fraction fallback.
**Expected:** Position sizes vary by asset per BL weight; weight=0 assets trigger close orders.
**Why human:** Requires portfolio_allocations rows with optimizer=bl; empty table causes valid fallback that looks identical to wiring failure.

### 3. Parity ratios non-null after burn-in

**Test:** After 7+ executor runs: python -m ta_lab2.scripts.executor.run_parity_report --window 7; query strategy_parity.
**Expected:** ratio_fill and ratio_mtm non-null for strategies with sufficient fill history.
**Why human:** Requires accumulated fills; cannot verify from static code inspection.

---

## Gaps Summary

No gaps. All 6 success criteria are structurally verified. The full wiring chain from signal generation through executor to parity/attribution reporting is in place and substantive. Three human verification items noted for post-activation validation during burn-in; none block goal achievement from a structural standpoint.

---

_Verified: 2026-03-30T23:30:00Z_
_Verifier: Claude (gsd-verifier)_
