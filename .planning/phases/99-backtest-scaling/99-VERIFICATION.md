---
phase: 99-backtest-scaling
verified: 2026-04-01T22:00:00Z
status: passed
score: 7/7 must-haves verified
gaps: []
resolved:
  - truth: LEAN_COST_MATRIX and --exchange lean flag exist in codebase for fast-screening
    resolution: Added LEAN_COST_MATRIX to costs.py and --exchange lean to run_mass_backtest.py (commit 9581c887)
  - truth: Strategy Leaderboard page renders with real data
    resolution: Human-verified 2026-04-01 — Sharpe bars with MC error bars, PBO heatmap, CTF lineage all render correctly
      - lean added to --exchange choices in run_mass_backtest.py argparse
---

# Phase 99: Backtest Scaling Verification Report

**Phase Goal:** A resume-safe orchestrator runs 460K+ backtest runs with Monte Carlo bands, CTF threshold signals, and expanded parameter grids; results visible in a strategy leaderboard dashboard.
**Verified:** 2026-04-01T22:00:00Z
**Status:** gaps_found
**Re-verification:** No - initial verification

## Goal Achievement

### Observable Truths

| #   | Truth | Status | Evidence |
| --- | ----- | ------ | -------- |
| 1   | run_mass_backtest.py resumes without re-running completed combinations | VERIFIED | mass_backtest_state has 65,780 done rows; UNIQUE constraint confirmed; --resume loads and skips done rows |
| 2   | backtest_trades is LIST-partitioned by strategy_name | VERIFIED | DB confirms LIST partition strategy; 8 named partitions + default in pg_class |
| 3   | Row count >= 113K for core bakeoff strategies | VERIFIED | 229,493 1D rows across 8 core strategies; exceeds 113K by 2x |
| 4   | Every eligible row has non-null mc_sharpe_lo/hi/median from 1,000 bootstrap samples | VERIFIED | 214,430 rows populated; 58,157 skipped (fewer than 3 valid fold Sharpes); 0 eligible rows remain unfilled |
| 5   | CTF threshold signals registered and producing backtest results | VERIFIED | ctf_threshold in REGISTRY (registry.py line 80); ctf_threshold.py 147 lines; 18,432 rows in strategy_bakeoff_results |
| 6   | Expanded parameter grids cover >= 3x baseline per strategy | VERIFIED | ema_trend 20 (5x), rsi 20 (6.7x), breakout_atr 12 (4x), macd_crossover 12 (4x), ama_momentum 12 (4x), ama_mean_reversion 12 (4x), ama_regime_conditional 12 (4x), ctf_threshold 18 (new); total 118 |
| 7   | LEAN_COST_MATRIX and --exchange lean exist for lean screening pathway | FAILED | costs.py has no LEAN_COST_MATRIX; run_mass_backtest.py choices=[kraken,hyperliquid,all] only; SUMMARY 99-05 claims these were added but they were never committed |

**Score:** 6/7 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| src/ta_lab2/scripts/backtests/run_mass_backtest.py | Resume-safe orchestrator | VERIFIED | 720 lines; --resume flag, _load_completed_keys(), _mark_done/error/running() wired to BakeoffOrchestrator |
| src/ta_lab2/scripts/backtests/backfill_mc_bands.py | MC bootstrap backfill | VERIFIED | 389 lines; vectorized numpy bootstrap; streaming cursor; 214,430 rows backfilled |
| alembic/versions/s3t4u5v6w7x8_phase99_backtest_scaling.py | Schema migration | VERIFIED | 446 lines; mass_backtest_state, partitioned backtest_trades, mc_sharpe_lo/hi/median; applied in migration chain |
| src/ta_lab2/signals/ctf_threshold.py | CTF signal adapter | VERIFIED | 147 lines; threshold-crossing logic; holding_bars exit; KeyError on missing feature_col |
| src/ta_lab2/signals/registry.py | ctf_threshold registered | VERIFIED | try/except import at line 53; REGISTRY entry at line 80; ensure_for clause; grid_for 18-combo grid |
| configs/mass_backtest_grids.yaml | Expanded param grids | VERIFIED | 238 lines; 118 total combos across 8 strategies; all >= 3x baseline |
| src/ta_lab2/dashboard/pages/18_strategy_leaderboard.py | Strategy Leaderboard page | VERIFIED | 498 lines; 3 tabs; Plotly bar chart with error_y CI bands; @st.fragment auto-refresh |
| src/ta_lab2/dashboard/queries/backtest.py | Leaderboard query functions | VERIFIED | load_leaderboard_with_mc(), load_pbo_heatmap_data(), load_ctf_lineage() present; real MC bands with sharpe_std fallback |
| src/ta_lab2/dashboard/app.py | Navigation registration | VERIFIED | Strategy Leaderboard in Research section at pages/18_strategy_leaderboard.py lines 52-56 |
| src/ta_lab2/backtests/costs.py | LEAN_COST_MATRIX | FAILED | File exists but no LEAN_COST_MATRIX or lean key in COST_MATRIX_REGISTRY |

### Key Link Verification

| From | To | Via | Status | Details |
| ---- | -- | --- | ------ | ------- |
| run_mass_backtest.py | mass_backtest_state | ON CONFLICT DO UPDATE upsert | WIRED | _mark_running/_mark_done/_mark_error SQL at lines 139-230 |
| run_mass_backtest.py | BakeoffOrchestrator.run() | orchestrator.run() call at line 523 | WIRED | Passes signal_fn, param_grid, asset_ids, data_loader_fn |
| run_mass_backtest.py | ctf_threshold signal | get_strategy + partial(load_strategy_data_with_ctf) | WIRED | Lines 458-481; data_loader_fn built from ctf_cols |
| bakeoff_orchestrator.py | load_strategy_data_with_ctf | data_loader_fn priority branch | WIRED | Lines 1470-1472; data_loader_fn takes priority over ama_features |
| backfill_mc_bands.py | strategy_bakeoff_results | streaming SELECT + batch UPDATE | WIRED | stream_results=True; _commit_batch UPDATE on mc_sharpe_lo/hi/median |
| 18_strategy_leaderboard.py | load_leaderboard_with_mc() | import from queries.backtest | WIRED | Lines 22-25; imported and called with engine, tf, cv_method, min_trades |
| load_leaderboard_with_mc() | strategy_bakeoff_results | SQL AVG(mc_sharpe_lo/hi) | WIRED | GROUP BY strategy/cost/cv; ci_lo/ci_hi/ci_source computed at query level |
| 18_strategy_leaderboard.py | app.py navigation | st.Page() in Research section | WIRED | app.py lines 52-56; registered as Strategy Leaderboard in Research |
| costs.py LEAN_COST_MATRIX | run_mass_backtest.py --exchange lean | COST_MATRIX_REGISTRY[lean] | NOT WIRED | LEAN_COST_MATRIX does not exist; lean not in --exchange choices |

### Requirements Coverage

| Requirement | Status | Blocking Issue |
| ----------- | ------ | -------------- |
| BT-01: Resume-safe state table with --resume flag skipping done rows | SATISFIED | mass_backtest_state with UNIQUE constraint; 65,780 done rows confirmed |
| BT-02: backtest_trades partitioned by strategy_name | SATISFIED | LIST partition confirmed; 8 named partitions + default; migration s3t4u5v6w7x8 applied |
| BT-03: >= 113K distinct result rows | SATISFIED | 229,493 1D rows across 8 core strategies (2x the threshold) |
| BT-04: mc_sharpe_lo/hi/median from 1,000 bootstrap samples | SATISFIED | 214,430 rows populated; n_samples=1000 default in backfill_mc_bands.py |
| BT-05: CTF signals registered and produce backtest results | SATISFIED | ctf_threshold in registry.py; 18,432 rows in strategy_bakeoff_results |
| BT-06: >= 3x parameter grid expansion | SATISFIED | ema_trend 5x, rsi 6.7x, breakout_atr 4x confirmed in YAML |
| BT-07: Strategy Leaderboard page accessible in dashboard | SATISFIED | 18_strategy_leaderboard.py in Research section of app.py |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| ---- | ---- | ------- | -------- | ------ |
| src/ta_lab2/backtests/costs.py | N/A | LEAN_COST_MATRIX missing (described in SUMMARY 99-05 but never committed) | Warning | Future lean screening cannot use --exchange lean |
| src/ta_lab2/scripts/backtests/run_mass_backtest.py | 632 | --exchange choices missing lean | Warning | Cosmetic inconsistency with SUMMARY; does not affect current functionality |

### Human Verification Required

1. **Dashboard visual rendering**
   Test: Open Streamlit dashboard, navigate Research > Strategy Leaderboard, verify bar chart renders with CI error bars.
   Expected: Plotly bar chart with visible CI bands; table shows ci_source = MC bootstrap for backfilled rows.
   Why human: Visual layout and Plotly rendering cannot be verified programmatically.

2. **PBO heatmap tab empty-state handling**
   Test: Select PBO Heatmap tab.
   Expected: May show informational message because cpcv_top_n=-1 was used; acceptable per Phase 99 scope.
   Why human: Needs visual confirmation of empty-state message vs. error.

## Gaps Summary

One gap exists against a claimed deliverable in SUMMARY 99-05 but does not prevent core phase goal achievement.

**LEAN_COST_MATRIX absent from codebase.** SUMMARY 99-05 states LEAN_COST_MATRIX was added to costs.py (3 representative costs: HL maker ~7.41bps, Kraken spot mid ~26bps, Kraken taker high ~46bps) and --exchange lean was added to run_mass_backtest.py. Neither change exists in committed code. The last commit to costs.py predates Phase 99 (Phase 82 commit). run_mass_backtest.py was committed only once in Phase 99-03 with choices=[kraken,hyperliquid,all].

The actual mass backtest ran with 16 cost scenarios (combined Kraken+HL matrix), exceeding all row count requirements. This gap affects only the future deferred Pass 2 lean screening pathway. The lean cost matrix was a convenience artifact for fast re-runs; its absence means the next screening pass must use --exchange hyperliquid (6 costs) or --exchange all (16 costs).

All six other success criteria are fully satisfied with strong DB evidence:
- 65,780 done rows in mass_backtest_state confirming resume capability
- 8 named LIST partitions confirmed on backtest_trades
- 229,493 1D rows across 8 core strategies (2x the 113K threshold)
- 214,430 MC bands populated (all eligible rows with >= 3 fold Sharpes)
- 18,432 CTF threshold rows confirm signal integration
- 118 YAML param combos with all strategies >= 3x baseline

---
_Verified: 2026-04-01T22:00:00Z_
_Verifier: Claude (gsd-verifier)_
