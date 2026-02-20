---
phase: 28-backtest-pipeline-fix
verified: 2026-02-20T22:21:42Z
status: passed
score: 9/9 must-haves verified
---

# Phase 28: Backtest Pipeline Fix Verification Report

**Phase Goal:** Fix the signal generators (dict serialization bug in feature_snapshot) and backtest runner (vectorbt timestamp errors) so the full signal-to-backtest pipeline works end-to-end.
**Verified:** 2026-02-20T22:21:42Z
**Status:** passed
**Re-verification:** No - initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Signal generators write to DB without errors (feature_snapshot serialized) | VERIFIED | EMA: json.dumps at line 450; ATR: json.dumps at line 513; RSI: json.dumps at line 488 |
| 2 | All 3 signal refreshers (RSI, EMA, ATR) complete without crashes | VERIFIED | All 3 use isinstance(x, dict) guard; regime_utils.py ts coercion fixes dtype mismatch crash |
| 3 | Backtest runner reads signals and produces PnL without vectorbt timestamp errors | VERIFIED | _ensure_utc() at line 41; tz-strip block lines 307-315; signal ts normalization lines 181/187 |
| 4 | End-to-end pipeline works: cmc_features -> signals -> backtest -> PnL summary | VERIFIED | run_all_signal_refreshes.py imports all 3 generators + SignalBacktester; SUMMARY confirms 302/154/98 signals + 104-trade backtest |
| 5 | At least one signal type produces a complete backtest report | VERIFIED | EMA crossover: 104 trades, Sharpe 1.73; results written to all 3 cmc_backtest_* tables |

**Score:** 5/5 truths verified (9/9 must-haves verified across 3 plans)

## Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| src/ta_lab2/scripts/signals/generate_signals_ema.py | json.dumps for feature_snapshot | VERIFIED | 460 lines; import json at line 38; json.dumps at line 450 in _write_signals(); no stubs |
| src/ta_lab2/scripts/signals/generate_signals_atr.py | json.dumps for feature_snapshot | VERIFIED | 525 lines; import json at line 35; json.dumps at line 513 in _write_signals(); no stubs |
| src/ta_lab2/scripts/backtests/backtest_from_signals.py | _ensure_utc, Entry Fees, str.lower, tz_localize, json.dumps, _to_python | VERIFIED | 778 lines; all 6 fix patterns present and wired |
| src/ta_lab2/scripts/signals/regime_utils.py | ts dtype coercion in merge_regime_context | VERIFIED | 169 lines; three-branch coercion on both sides before merge |

## Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| generate_signals_ema.py | DB cmc_signals_ema_crossover | json.dumps(x) if isinstance(x, dict) else x | WIRED | Line 450 in _write_signals(); called at line 178 |
| generate_signals_atr.py | DB cmc_signals_atr_breakout | json.dumps(x) if isinstance(x, dict) else x | WIRED | Line 513 in _write_signals(); called at line 190 |
| backtest_from_signals.py | vectorbt timestamps | _ensure_utc() helper lines 41-47 | WIRED | Called at lines 473 and 475 inside _extract_trades() |
| backtest_from_signals.py | vectorbt fee columns | Entry Fees + Exit Fees with fallback to Fees | WIRED | Lines 486-492; guard on both columns present |
| backtest_from_signals.py | vectorbt direction column | .astype(str).str.lower() | WIRED | Line 479; converts Long->long, Short->short |
| backtest_from_signals.py | prices/entries/exits to vectorbt | tz_localize(None) strip in run_backtest() | WIRED | Lines 307-315; conditional strip on all three Series |
| backtest_from_signals.py | DB cmc_backtest_runs cost_model | json.dumps(result.cost_model) | WIRED | Line 695 in save_backtest_results() |
| backtest_from_signals.py | DB cmc_backtest_metrics | _to_python() numpy scalar normalizer | WIRED | Lines 765-772; hasattr(v, item) pattern |
| backtest_from_signals.py | vectorbt split boundaries | strftime date-string bounds | WIRED | Lines 322-323; triggers pandas partial-date matching |
| backtest_from_signals.py | load_prices tz-safe | Manual ts coerce post-load no index_col | WIRED | Lines 246-249; avoids inferred UTC-04:00 timezone |
| backtest_from_signals.py | load_signals_as_series tz-naive | tz_convert UTC replace(tzinfo=None) | WIRED | Lines 180-187; normalizes signal ts to tz-naive |
| backtest_from_signals.py | vbt column version detection | Avg Entry Price if in trades.columns else Entry Price | WIRED | Lines 463-468; handles vbt 0.28.1 renamed columns |

## Requirements Coverage

| Requirement | Status | Blocking Issue |
|-------------|--------|----------------|
| Signal generators write to DB without errors | SATISFIED | - |
| All 3 signal refreshers complete without crashes | SATISFIED | - |
| Backtest runner produces PnL without vectorbt timestamp errors | SATISFIED | - |
| End-to-end pipeline works cmc_features to PnL summary | SATISFIED | - |
| At least one signal type produces a complete backtest report | SATISFIED | - |

## Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| backtest_from_signals.py | 389 | signal_version hardcoded as v1.0 | Info | Cosmetic; does not affect pipeline correctness |

No blockers or warnings found.

## Human Verification Required

None. All success criteria are verifiable through code inspection. SUMMARY (28-03) documents a live DB run with human checkpoint approval confirming 302 EMA signals, 154 RSI signals, 98 ATR signals, and a complete EMA crossover backtest (104 trades, Sharpe 1.73, results in cmc_backtest_* tables).

## Gaps Summary

No gaps. All 9 must-haves across 3 plans are verified.

## Detailed Findings

Plan 01 (Signal serialization): Both EMA and ATR generators use json.dumps(x) if isinstance(x, dict) else x in their _write_signals() methods (lines 450 and 513 respectively), matching the RSI generator pattern. The import json statement is present at the top of each file. records.copy() in the EMA generator prevents SettingWithCopyWarning.

Plan 02 (vectorbt compatibility): backtest_from_signals.py contains all five documented fixes: _ensure_utc() module-level helper, .astype(str).str.lower() for direction, Entry Fees + Exit Fees fee extraction with backward-compat fallback, json.dumps(result.cost_model) for JSONB, and tz_localize(None) tz-strip block in run_backtest().

Plan 03 (End-to-end): Four additional runtime bugs discovered during live verification are present in the code: tz-safe load_prices (no index_col, manual post-hoc coerce), strftime date-string split bounds, replace(tzinfo=None) signal timestamp normalization, Avg Entry Price version detection, and _to_python() numpy scalar normalizer. regime_utils.py has the three-branch ts coercion in merge_regime_context. All fixes are wired into live execution paths.

---

_Verified: 2026-02-20T22:21:42Z_
_Verifier: Claude (gsd-verifier)_
