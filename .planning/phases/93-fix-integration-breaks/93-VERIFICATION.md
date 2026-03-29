---
phase: 93-fix-integration-breaks
verified: 2026-03-29T01:12:11Z
status: passed
score: 4/4 must-haves verified
human_verification:
  - test: "Run python -m ta_lab2.scripts.integration.smoke_test and confirm all 26 checks PASS"
    expected: "Exit code 0, 26/26 PASS including both GARCH checks (no ProgrammingError)"
    why_human: "Requires live DB connection to execute SQL queries"
  - test: "Run python -m ta_lab2.scripts.executor.run_parity_check --bakeoff-winners --start 2025-01-01 --end 2025-12-31 --slippage-mode fixed --pnl-correlation-threshold 0.90"
    expected: "All strategies from strategy_bakeoff_results attempted (0 silently skipped). Strategies may fail parity but must be attempted and logged."
    why_human: "Requires live DB connection and strategy_bakeoff_results data"
---

# Phase 93: Fix Integration Breaks Verification Report

**Phase Goal:** Fix the two highest-priority integration breaks from v1.2.0 audit: smoke test GARCH column bug (REQ-15) and parity check strategy coverage (3/9 -> 9/9)
**Verified:** 2026-03-29T01:12:11Z
**Status:** passed
**Re-verification:** No -- initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Smoke test GARCH stage queries use `id` column (not `asset_id`) | VERIFIED | Lines 356 and 363 of smoke_test.py both use `WHERE id=1`. Zero `asset_id` references in GARCH section (lines 349-366). |
| 2 | All 26 smoke test checks pass including both GARCH checks | VERIFIED (structural) | 26 SmokeCheck instances counted. GARCH queries use correct column. Runtime pass requires DB (human verification). |
| 3 | _STRATEGY_SIGNAL_MAP has 7 explicit entries plus a fallback | VERIFIED | Lines 49-57: 7 entries (ama_momentum, ama_mean_reversion, ama_regime_conditional, ema_trend, macd_crossover, rsi_mean_revert, breakout_atr). Lines 152-159: fallback sets signal_type = strategy_name with INFO log. |
| 4 | Parity check attempts all strategies with 0 silently skipped | VERIFIED | Lines 152-159: unmapped strategies fall back to strategy_name as signal_type. Lines 171-178: only skips when dim_signals lookup returns None, logged at WARNING. No silent skip path exists. |

**Score:** 4/4 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/ta_lab2/scripts/integration/smoke_test.py` | Fixed GARCH queries using `id` | VERIFIED | 665 lines, substantive, no stubs, no TODO/FIXME. Contains `WHERE id=1` in both GARCH checks. |
| `src/ta_lab2/scripts/executor/run_parity_check.py` | Complete strategy-signal mapping with fallback | VERIFIED | 464 lines, substantive, no stubs, no TODO/FIXME. Contains all 7 strategy mappings plus fallback logic. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `smoke_test.py _build_garch_checks()` | `garch_forecasts` table | SQL with `WHERE id=1` | WIRED | Lines 354-358: `SELECT COUNT(*) FROM garch_forecasts WHERE id=1 AND created_at >= NOW() - INTERVAL '48 hours'` |
| `smoke_test.py _build_garch_checks()` | `garch_forecasts_latest` table | SQL with `WHERE id=1` | WIRED | Line 363: `SELECT cond_vol FROM garch_forecasts_latest WHERE id=1 LIMIT 1` |
| `run_parity_check.py _STRATEGY_SIGNAL_MAP` | `dim_signals` table | `signal_type` lookup | WIRED | Lines 121-126: `_SIGNAL_LOOKUP_SQL` queries dim_signals. Lines 162-168: executed per winner with caching. |

### Requirements Coverage

| Requirement | Status | Notes |
|-------------|--------|-------|
| REQ-15 (Integration smoke test) | UNBLOCKED | GARCH column bug fixed; all 26 checks structurally correct |
| Break 1 (HIGH): GARCH ProgrammingError | CLOSED | `asset_id` replaced with `id` in both queries |
| Break 3 (MEDIUM): Parity silent skip 6/9 | CLOSED | 7 explicit mappings + fallback; 0 silent skips |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| (none) | - | - | - | No anti-patterns detected in either modified file |

### Human Verification Required

### 1. Smoke Test End-to-End
**Test:** `python -m ta_lab2.scripts.integration.smoke_test --verbose`
**Expected:** Exit code 0, 26/26 PASS, both GARCH checks pass without ProgrammingError
**Why human:** Requires live PostgreSQL connection to execute SQL queries against garch_forecasts and garch_forecasts_latest

### 2. Parity Check Full Strategy Coverage
**Test:** `python -m ta_lab2.scripts.executor.run_parity_check --bakeoff-winners --start 2025-01-01 --end 2025-12-31 --slippage-mode fixed --pnl-correlation-threshold 0.90`
**Expected:** All strategies from strategy_bakeoff_results attempted (0 silently skipped). Output shows each strategy attempted with signal_id resolution. Parity pass/fail per strategy is acceptable; the key is that all are attempted.
**Why human:** Requires live DB with strategy_bakeoff_results data

### Gaps Summary

No gaps found. Both fixes are structurally verified:
1. The GARCH column bug is definitively fixed -- `id=1` replaces `asset_id=1` in both queries.
2. The strategy signal map expanded from 3 to 7 entries with a fallback that eliminates silent skipping.

Runtime verification (human) is needed only to confirm DB-level correctness (tables exist, data present, queries return expected results).

---

_Verified: 2026-03-29T01:12:11Z_
_Verifier: Claude (gsd-verifier)_
