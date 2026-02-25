---
phase: 49-tail-risk-policy
verified: 2026-02-25T21:47:26Z
status: passed
score: 12/12 must-haves verified
---

# Phase 49: Tail-Risk Policy Verification Report

**Phase Goal:** Build the tail-risk policy: hard stops vs vol-sizing comparison (TAIL-01), flatten triggers with calibrated thresholds and three-level escalation (TAIL-02), and comprehensive policy document with machine-readable config (TAIL-03).
**Verified:** 2026-02-25T21:47:26Z
**Status:** passed
**Re-verification:** No -- initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Alembic migration adds tail_risk_state (CHECK normal/reduce/flatten) and 3 audit columns to dim_risk_state | VERIFIED | a9ec3c00a54a_tail_risk_policy.py lines 31-62: op.add_column for all 4 columns + CHECK constraint |
| 2 | cmc_risk_events accepts tail_risk_escalated/tail_risk_cleared event types and tail_risk trigger source | VERIFIED | Migration lines 66-93: DROP + RECREATE constraints with both new event types and source value |
| 3 | vol_sizer library computes ATR-based and realized-vol-based position sizes with max_position_pct cap | VERIFIED | vol_sizer.py lines 40-108: compute_vol_sized_position + compute_realized_vol_position; 0.30 cap; guards for zero/None/negative |
| 4 | run_vol_sized_backtest returns vbt.Portfolio with entry-bar vol-sized positions | VERIFIED | vol_sizer.py lines 116-207: vol_type dispatch, size_array=np.where(entries), tz-strip for vbt 0.28.1, from_signals call |
| 5 | check_flatten_trigger evaluates 4 trigger types in priority order | VERIFIED | flatten_trigger.py lines 127-219: exchange halt > abs return > vol spike 3sig > corr breakdown > vol spike 2sig > normal |
| 6 | EscalationState enum has normal, reduce, flatten values | VERIFIED | flatten_trigger.py lines 47-59: EscalationState(str, Enum) with NORMAL/REDUCE/FLATTEN string values |
| 7 | RiskEngine.check_tail_risk_state reads tail_risk_state from dim_risk_state and returns (state, size_multiplier) | VERIFIED | risk_engine.py lines 357-387: SQL SELECT WHERE state_id=1, returns (normal,1.0)/(reduce,0.5)/(flatten,0.0) |
| 8 | RiskEngine.check_order includes Gate 1.5 that blocks FLATTEN and halves buy quantities in REDUCE | VERIFIED | risk_engine.py lines 234-255: Gate 1.5 after kill switch; FLATTEN returns allowed=False; REDUCE multiplies qty by Decimal(0.5) |
| 9 | evaluate_tail_risk_state with 21d/14d cooldown AND 3 consecutive vol-clear days de-escalation | VERIFIED | risk_engine.py lines 399-635: dual cooldown (21d flatten/14d reduce), LIMIT 23 for 3-window vol check, consecutive_clear >= 3 |
| 10 | run_tail_risk_comparison CLI runs 3 variants across strategies/assets with SIZING_COMPARISON.md, recovery_bars, composite score | VERIFIED | run_tail_risk_comparison.py (1380 lines): Variant A/B/C, composite score 0.4*sharpe+0.3*sortino+0.2*(1+calmar)+0.1*tail, Recovery Bars column |
| 11 | ETH signals generated on-the-fly since ETH has no signal rows in DB | VERIFIED | run_tail_risk_comparison.py lines 251-510: _generate_ema_signals_onthefly, _generate_rsi_signals_onthefly, _generate_atr_signals_onthefly |
| 12 | TAIL_RISK_POLICY.md covers all 3 TAIL requirements + tail_risk_config.yaml machine-readable config | VERIFIED | generate_tail_risk_policy.py (697 lines): 5 sections, SQL override appendix, COVID/FTX/May2021, YAML with vol_clear_consecutive_days=3 |

**Score:** 12/12 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| alembic/versions/a9ec3c00a54a_tail_risk_policy.py | Alembic migration for tail_risk_state + cmc_risk_events | VERIFIED | 137 lines, down_revision=328fdc315e1b (Phase 48 chain), upgrade/downgrade complete |
| src/ta_lab2/analysis/vol_sizer.py | Vol-sizing library: ATR + realized-vol + vbt wrapper | VERIFIED | 332 lines, 5 exported functions, no stubs, flat metrics dict with worst_N and recovery_bars |
| src/ta_lab2/risk/flatten_trigger.py | Flatten trigger evaluation: 4 triggers + EscalationState enum | VERIFIED | 219 lines, EscalationState(str,Enum), FlattenTriggerResult dataclass, calibrated BTC thresholds |
| src/ta_lab2/risk/risk_engine.py | Extended RiskEngine with Gate 1.5 and evaluate_tail_risk_state | VERIFIED | check_tail_risk_state + Gate 1.5 in check_order + evaluate_tail_risk_state all present |
| src/ta_lab2/risk/__init__.py | 13 exported symbols including 3 flatten_trigger symbols | VERIFIED | 32 lines, 13 exports in __all__, flatten_trigger imports at module level |
| src/ta_lab2/analysis/__init__.py | vol_sizer try/except exports | VERIFIED | Lines 30-39: try/except ImportError block with all 5 vol_sizer exports |
| src/ta_lab2/scripts/analysis/run_tail_risk_comparison.py | TAIL-01 comparison CLI + SIZING_COMPARISON.md + charts | VERIFIED | 1380 lines, --dry-run, Plotly write_html only (no kaleido), Summary Recommendations + Key Findings sections |
| src/ta_lab2/scripts/analysis/generate_tail_risk_policy.py | TAIL-03 policy generator CLI producing 3 output files | VERIFIED | 697 lines, 3 outputs (policy/yaml/chart), all 5 policy sections, SQL-based override, YAML with all required keys |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| a9ec3c00a54a migration | Phase 48 (328fdc315e1b) | down_revision | WIRED | down_revision = 328fdc315e1b, chained to loss_limits_policy migration |
| vol_sizer.py | vectorbt 0.28.1 | vbt.Portfolio.from_signals(size=size_array) | WIRED | Line 207: from_signals with tz-strip, size_array at entry bars, direction=longonly |
| risk_engine.py | flatten_trigger.py | from ta_lab2.risk.flatten_trigger import | WIRED | Deferred import inside evaluate_tail_risk_state; TYPE_CHECKING guard at module level |
| risk_engine.py | dim_risk_state.tail_risk_state | SQL SELECT/UPDATE | WIRED | Line 379 (read), lines 587/605 (write escalation/de-escalation), state_id=1 |
| risk/__init__.py | flatten_trigger.py | from ta_lab2.risk.flatten_trigger import | WIRED | Lines 3-7: module-level re-export of EscalationState, FlattenTriggerResult, check_flatten_trigger |
| run_tail_risk_comparison.py | vol_sizer.py | from ta_lab2.analysis.vol_sizer import | WIRED | Lines 45-47: compute_comparison_metrics and run_vol_sized_backtest imported and called |
| run_tail_risk_comparison.py | cmc_features | SQL SELECT ts, atr_14 | WIRED | _load_atr_data uses ts column (correct for cmc_features) |
| run_tail_risk_comparison.py | cmc_price_bars_multi_tf_u | SQL SELECT timestamp, close | WIRED | _load_price_data uses timestamp column (correct quoted reserved word) |
| run_tail_risk_comparison.py | cmc_returns_bars_multi_tf_u | SQL SELECT timestamp, ret_arith | WIRED | _load_realized_vol uses timestamp column (correct) |
| generate_tail_risk_policy.py | SIZING_COMPARISON.md | conditional read | WIRED | Lines 97-124: reads Summary Recommendations section; falls back to research defaults if absent |
| generate_tail_risk_policy.py | tail_risk_config.yaml | yaml.dump write | WIRED | Lines 648-654: _build_tail_risk_config() dict + yaml.dump to config_path |
| generate_tail_risk_policy.py | cmc_returns_bars_multi_tf_u | SQL SELECT timestamp | WIRED | Lines 72-80: timestamp column (correct) for vol chart data loading |

### Requirements Coverage

| Requirement | Status | Blocking Issue |
|-------------|--------|----------------|
| TAIL-01: Hard stops vs vol-sizing comparison backtest with Sharpe/MaxDD/recovery metrics | SATISFIED | None |
| TAIL-02: Flatten-all criteria, calibrated triggers, three-level escalation, cooldown de-escalation | SATISFIED | None |
| TAIL-03: Policy document with sizing/flatten/escalation/regime/override + machine-readable YAML | SATISFIED | None |

### Anti-Patterns Found

No TODO/FIXME/placeholder/stub patterns found in any of the 4 primary source artifacts. All files are fully implemented.

### Live Execution Confirmed

During verification, both CLIs were executed successfully against the live DB:

- run_tail_risk_comparison: 3 result rows produced (Variant A/B/C for ema_trend_17_77 on BTC). SIZING_COMPARISON.md written. Charts: sizing_sharpe_heatmap.html + sizing_maxdd_comparison.html saved.
- generate_tail_risk_policy: SIZING_COMPARISON.md embedded. TAIL_RISK_POLICY.md written. tail_risk_config.yaml written. Vol spike chart saved (5613 BTC daily return bars loaded).

DB migration a9ec3c00a54a confirmed applied (alembic context connected successfully).

## Gaps Summary

No gaps found. All 12 must-haves verified. Phase 49 goal fully achieved.

**TAIL-01** is fully implemented: vol_sizer library (332 lines, 5 functions including compute_vol_sized_position, compute_realized_vol_position, run_vol_sized_backtest, worst_n_day_returns, compute_comparison_metrics), run_tail_risk_comparison CLI (1380 lines, 3 variants A/B/C, composite scoring, Recovery Bars column, Plotly HTML charts without kaleido). Correct dual column convention: cmc_price_bars_multi_tf_u uses timestamp; cmc_features uses ts. Live execution produced 3 result rows for BTC ema_trend_17_77.

**TAIL-02** is fully implemented: flatten_trigger.py (219 lines) pure evaluation module with 4 priority-ordered triggers and BTC-calibrated thresholds (reduce=0.0923, flatten=0.1194, abs_return=0.15, corr=-0.20). RiskEngine Gate 1.5 blocks FLATTEN orders and halves REDUCE buy quantities via Decimal multiplication. evaluate_tail_risk_state enforces 21d/14d cooldown AND 3-consecutive-day vol-clear requirement (LIMIT 23 bars for 3 overlapping 20-bar windows). 13 symbols in risk package __all__. Tests updated with Gate 1.5 mocks.

**TAIL-03** is fully implemented: generate_tail_risk_policy.py (697 lines) producing TAIL_RISK_POLICY.md (5 sections + appendix with SQL override commands), tail_risk_config.yaml (8 sections: vol_sizing, escalation_thresholds, re_entry with vol_clear_consecutive_days=3, regime_interaction, trigger_priority list), vol_spike_history.html (BTC rolling vol chart with REDUCE/FLATTEN threshold dashed lines and COVID/FTX/May2021 vrect annotations). Live execution loaded 5613 BTC daily return bars and embedded SIZING_COMPARISON.md recommendations.

---

_Verified: 2026-02-25T21:47:26Z_
_Verifier: Claude (gsd-verifier)_
