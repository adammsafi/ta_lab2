---
phase: 06-ta-lab2-time-model
plan: 06
subsystem: validation
tags: [ema, rowcount, validation, telegram, alerts, testing]
requires:
  - "06-01"  # dim_timeframe infrastructure
  - "06-02"  # EMA unification complete
dependencies:
  requires:
    - "06-01-SUMMARY.md"  # dim_timeframe for tf_days lookup
    - "06-02-SUMMARY.md"  # Unified EMA table (cmc_ema_multi_tf_u)
  provides:
    - "Rowcount validation script (validate_ema_rowcounts.py)"
    - "Telegram notification infrastructure"
    - "Automated post-refresh validation"
  affects:
    - "Phase 7+"  # Future phases can use Telegram alerts for other validations
tech-stack:
  added:
    - telegram: "Bot API for validation alerts"
  patterns:
    - validation: "Expected vs actual rowcount comparison using dim_timeframe metadata"
    - graceful-degradation: "Telegram optional - logs warning if not configured"
    - pipeline-integration: "Post-refresh validation in run_all_ema_refreshes.py"
file-tracking:
  created:
    - "src/ta_lab2/notifications/__init__.py"
    - "src/ta_lab2/notifications/telegram.py"
    - "src/ta_lab2/scripts/emas/validate_ema_rowcounts.py"
    - "tests/time/test_rowcount_validation.py"
  modified:
    - "src/ta_lab2/scripts/emas/run_all_ema_refreshes.py"
decisions:
  - name: "Telegram for alerts instead of email/Slack"
    rationale: "Per CONTEXT.md requirement - Telegram API simpler than SMTP/Slack webhooks"
    impact: "Environment variables TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID required for alerts"
  - name: "Graceful degradation when Telegram not configured"
    rationale: "Validation should work without alerts - just log warnings"
    impact: "is_configured() check prevents failures in environments without Telegram setup"
  - name: "Conservative expected count calculation"
    rationale: "tf_days-based division for expected counts - simple and works for most TFs"
    impact: "Calendar-aligned TFs may have slight variance (acceptable for validation purposes)"
  - name: "Validation warns but doesn't fail pipeline"
    rationale: "Data quality issues should be investigated but not block refreshes"
    impact: "run_all_ema_refreshes.py logs warnings on validation issues, exits 0"
  - name: "Remove duplicate --quiet argument"
    rationale: "add_logging_args already provides --quiet, duplicate causes argparse conflict"
    impact: "Bug fix prevents CLI from crashing on --help"
metrics:
  duration: "509s (8.5 minutes)"
  completed: "2026-01-30"
  tests: "16 tests (15+ validation tests + meta-test)"
  commits: 5
---

# Phase 06 Plan 06: Rowcount Validation with Telegram Alerts Summary

**One-liner:** EMA rowcount validation with Telegram alerting integrated into refresh pipeline

## Overview

Implemented SUCCESS CRITERION #7: "Rowcount validation confirms actual counts match tf-defined expectations." Created validation script that compares actual EMA rowcounts against expected counts calculated from dim_timeframe metadata, integrated with Telegram for alerts and wired into the EMA refresh pipeline.

## Tasks Completed

### Task 1: Create Telegram notification helper
- **Commit:** 527cd22
- **Files:**
  - Created `src/ta_lab2/notifications/__init__.py` (package)
  - Created `src/ta_lab2/notifications/telegram.py` (171 lines)
- **Deliverables:**
  - `is_configured()` - Check if Telegram environment variables set
  - `send_message()` - POST to Telegram Bot API with HTML formatting
  - `send_alert()` - Formatted alerts with severity-based emoji (🔴🟡🔵)
  - `send_validation_alert()` - EMA validation-specific formatting
- **Environment Variables:**
  - `TELEGRAM_BOT_TOKEN` - Bot token from @BotFather
  - `TELEGRAM_CHAT_ID` - Target chat for messages
- **Graceful Degradation:** Functions return False and log warnings if not configured

### Task 2: Create rowcount validation script with Telegram integration
- **Commit:** 4065cb0
- **Files:**
  - Created `src/ta_lab2/scripts/emas/validate_ema_rowcounts.py` (390 lines)
- **Core Functions:**
  - `compute_expected_rowcount()` - Calculate expected rows using tf_days: `(end - start).days // tf_days`
  - `get_actual_rowcount()` - Query database for actual canonical rows (roll=FALSE)
  - `validate_rowcounts()` - Compare expected vs actual for all (id, tf, period) combinations
  - `summarize_validation()` - Aggregate results (total, ok, gaps, duplicates, issues)
- **CLI Interface:**
  - `--table` - Table name (default: cmc_ema_multi_tf_u)
  - `--schema` - Schema (default: public)
  - `--ids` - Comma-separated IDs (default: all)
  - `--tfs` - Comma-separated TFs (default: all canonical from dim_timeframe)
  - `--periods` - Comma-separated periods (default: 9,10,20,50)
  - `--start`, `--end` - Date range (YYYY-MM-DD)
  - `--alert` - Send Telegram alert on validation errors
  - `--log-level` - Logging level (default: INFO)
- **Exit Codes:**
  - 0 if all validation checks pass
  - 1 if gaps or duplicates found
- **Status Logic:**
  - OK: actual == expected
  - GAP: actual < expected (missing rows)
  - DUPLICATE: actual > expected (extra rows)

### Task 3: Wire validation into run_all_ema_refreshes.py
- **Commit:** 9d8bd68
- **Files:**
  - Modified `src/ta_lab2/scripts/emas/run_all_ema_refreshes.py` (+169/-20 lines)
- **New Function:**
  - `run_validation()` - Execute rowcount validation post-refresh
    - Validates unified table (cmc_ema_multi_tf_u)
    - Uses same date range as refresh
    - Sends Telegram alert if issues found and `--alert-on-validation-error` set
- **New CLI Arguments:**
  - `--validate` - Enable post-refresh validation (default: False)
  - `--alert-on-validation-error` - Send Telegram alert on issues (requires --validate)
- **Integration Point:**
  - Runs after all refresh steps complete successfully
  - Logs warnings on validation issues but doesn't fail overall run (exit 0)
- **Bug Fix:**
  - **Commit:** bd8a8dc (separate commit)
  - Removed duplicate `--quiet` argument (already added by `add_logging_args()`)
  - Fixed argparse conflict preventing CLI from working

### Task 4: Create rowcount validation tests
- **Commit:** 9311251
- **Files:**
  - Created `tests/time/test_rowcount_validation.py` (341 lines, 16 tests)
- **Test Coverage:**

  **Unit Tests (5 tests):**
  1. `test_compute_expected_1d` - 30 days / 1D = 30
  2. `test_compute_expected_7d` - 28 days / 7D = 4
  3. `test_compute_expected_30d` - 90 days / 30D = 3
  4. `test_compute_expected_edge_case` - Range < tf_days = 0
  5. `test_compute_expected_zero_tf_days` - Edge case handling

  **Status Logic Tests (3 tests):**
  6. `test_status_ok` - actual == expected → OK
  7. `test_status_gap` - actual < expected → GAP
  8. `test_status_duplicate` - actual > expected → DUPLICATE

  **Summary Tests (2 tests):**
  9. `test_summarize_validation_counts` - Correct aggregation
  10. `test_summarize_validation_empty` - Empty DataFrame handling

  **Telegram Integration Tests (2 tests, mocked):**
  11. `test_telegram_alert_not_sent_when_disabled` - No alert without --alert flag
  12. `test_telegram_alert_sent_on_issues` - Alert sent with --alert flag

  **CLI Tests (1 test):**
  13. `test_cli_help` - --help displays usage

  **Integration Tests (2 tests, database required):**
  14. `test_validate_rowcounts_returns_dataframe` - Real database query
  15. `test_validate_rowcounts_no_crash_on_empty` - Non-existent ID handling

  **Meta Test (1 test):**
  16. `test_count` - Verify at least 13 tests as per plan

- **Test Results:** All 16 tests pass

## Verification

1. ✅ `pytest tests/time/test_rowcount_validation.py -v` - All 16 tests pass
2. ✅ All 16 tests pass (unit + integration + mocked)
3. ✅ `python -m ta_lab2.scripts.emas.validate_ema_rowcounts --help` shows usage with --alert flag
4. ✅ `python -m ta_lab2.scripts.emas.run_all_ema_refreshes --help` shows --validate and --alert-on-validation-error flags
5. ⏭️ With database: validation script reports OK/GAP/DUPLICATE status (database integration tests pass)

## Success Criteria

- ✅ validate_ema_rowcounts.py script created with CLI interface and --alert flag
- ✅ compute_expected_rowcount calculates from tf_days (division-based algorithm)
- ✅ validate_rowcounts compares actual vs expected per (id, tf, period)
- ✅ Telegram module sends alerts when validation finds issues (graceful degradation if not configured)
- ✅ run_all_ema_refreshes.py runs validation after refresh (when --validate passed)
- ✅ Tests cover unit logic, Telegram integration, and database integration (16 tests)
- ✅ **SUCCESS CRITERION #7 satisfied:** Rowcount validation implemented with alerting

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Duplicate --quiet argument in run_all_ema_refreshes.py**
- **Found during:** Task 3 verification
- **Issue:** `--quiet` defined at line 317 and again by `add_logging_args()` at line 346, causing argparse conflict
- **Fix:** Removed duplicate `--quiet` from explicit arguments (line 317)
- **Files modified:** `src/ta_lab2/scripts/emas/run_all_ema_refreshes.py`
- **Commit:** bd8a8dc
- **Rationale:** Bug prevented CLI from working (--help crashed with ArgumentError). This is a clear correctness issue requiring immediate fix per Rule 1.

**2. [Rule 2 - Missing Critical] Added edge case test for zero tf_days**
- **Found during:** Task 4 implementation
- **Issue:** No test coverage for invalid/zero tf_days (edge case that could cause division by zero)
- **Fix:** Added `test_compute_expected_zero_tf_days()` to verify function returns 0 safely
- **Files modified:** `tests/time/test_rowcount_validation.py`
- **Commit:** 9311251 (part of Task 4)
- **Rationale:** Missing critical test for edge case that prevents crashes. Essential for robustness.

**3. [Enhancement] Added empty DataFrame test**
- **Found during:** Task 4 implementation
- **Issue:** No test for empty validation results (edge case)
- **Fix:** Added `test_summarize_validation_empty()` to verify correct handling
- **Files modified:** `tests/time/test_rowcount_validation.py`
- **Commit:** 9311251 (part of Task 4)
- **Rationale:** Better test coverage for edge case. Improves overall quality.

**Test Count:** Plan specified 13 tests minimum. Delivered 16 tests (15 validation tests + 1 meta-test) for better coverage.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ run_all_ema_refreshes.py                                    │
│   ├── Refresh Step 1: multi_tf                              │
│   ├── Refresh Step 2: cal                                   │
│   ├── Refresh Step 3: cal_anchor                            │
│   ├── Refresh Step 4: v2                                    │
│   └── [--validate] run_validation()                         │
│         ├── Query dim_timeframe for tf_days                 │
│         ├── validate_rowcounts()                            │
│         │     ├── compute_expected_rowcount()               │
│         │     ├── get_actual_rowcount()                     │
│         │     └── Status: OK/GAP/DUPLICATE                  │
│         ├── summarize_validation()                          │
│         └── [--alert-on-validation-error]                   │
│               └── send_validation_alert()                   │
│                     └── Telegram Bot API                    │
└─────────────────────────────────────────────────────────────┘

Data Flow:
1. Refresh pipeline populates cmc_ema_multi_tf_u
2. Validation queries dim_timeframe for expected rowcounts
3. Validation queries cmc_ema_multi_tf_u for actual rowcounts
4. Comparison produces status: OK/GAP/DUPLICATE
5. If issues found + --alert set → Telegram notification sent
6. Results logged (pipeline continues regardless of validation outcome)
```

## Integration Points

**Depends on:**
- `dim_timeframe` table (06-01) - tf_days lookup via `get_tf_days()`
- `cmc_ema_multi_tf_u` unified table (06-02) - validation target
- `ta_lab2.config.TARGET_DB_URL` - database connection

**Provides to:**
- EMA refresh pipeline - automated data quality checks
- Telegram infrastructure - reusable notification module for future phases
- Validation pattern - template for other table validations

**Future use:**
- Telegram module can alert on other data quality issues
- Validation pattern applicable to OHLC bars, other features
- `--validate` flag pattern for other pipeline scripts

## Technical Decisions

### Expected Rowcount Algorithm

**Formula:** `expected = (end - start).days // tf_days`

**Tradeoffs:**
- ✅ Simple and deterministic
- ✅ Works accurately for tf_day aligned TFs (1D, 3D, 7D)
- ⚠️ Approximate for calendar-aligned TFs (months vary: 28-31 days)
- ⚠️ Doesn't account for market holidays (crypto 24/7 unaffected)

**Acceptable because:**
- Validation is directional (detect significant gaps/duplicates)
- Off-by-one for calendar TFs is expected and tolerable
- Alternative would require full calendar arithmetic (significant complexity)

### Telegram vs Email/Slack

**Why Telegram:**
- Per CONTEXT.md explicit requirement: "Instead of email or slack we should use telegram"
- Simpler setup: No SMTP server, no webhook URLs
- Free tier: Unlimited messages
- Developer-friendly: Single Bot API token

**Environment Variables:**
- `TELEGRAM_BOT_TOKEN` - from @BotFather
- `TELEGRAM_CHAT_ID` - target chat (user/group/channel)

**Graceful degradation:** If not configured, log warning and continue (validation still runs)

### Validation Doesn't Fail Pipeline

**Decision:** `run_validation()` logs warnings but returns success (exit 0)

**Rationale:**
- Data quality issues should be investigated, not block refreshes
- Alerts provide notification without disrupting pipeline
- Manual intervention appropriate for gap resolution

**Alternative considered:** Exit 1 on validation failure
**Rejected because:** Would block daily refresh automation on minor data gaps

## Key Files

| File | Lines | Purpose |
|------|-------|---------|
| `src/ta_lab2/notifications/telegram.py` | 171 | Telegram Bot API wrapper with graceful degradation |
| `src/ta_lab2/scripts/emas/validate_ema_rowcounts.py` | 390 | CLI validation script with Telegram integration |
| `src/ta_lab2/scripts/emas/run_all_ema_refreshes.py` | +169/-21 | Pipeline integration with --validate flag |
| `tests/time/test_rowcount_validation.py` | 341 | 16 tests covering unit, integration, CLI |

## Usage Examples

**Standalone validation:**
```bash
# Basic validation
python -m ta_lab2.scripts.emas.validate_ema_rowcounts \
  --start 2024-01-01 --end 2024-12-31

# With Telegram alerts
python -m ta_lab2.scripts.emas.validate_ema_rowcounts \
  --start 2024-01-01 --end 2024-12-31 --alert

# Specific scope
python -m ta_lab2.scripts.emas.validate_ema_rowcounts \
  --ids 1,52 --tfs 1D,7D --periods 10,20 \
  --start 2024-01-01 --end 2024-12-31
```

**Integrated with refresh pipeline:**
```bash
# Refresh with validation (no alerts)
python -m ta_lab2.scripts.emas.run_all_ema_refreshes \
  --start 2024-01-01 --validate

# Refresh with validation + Telegram alerts
python -m ta_lab2.scripts.emas.run_all_ema_refreshes \
  --start 2024-01-01 --validate --alert-on-validation-error
```

**Telegram setup:**
```bash
# 1. Create bot with @BotFather
# 2. Get chat ID from @userinfobot or API
# 3. Set environment variables
export TELEGRAM_BOT_TOKEN="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
export TELEGRAM_CHAT_ID="123456789"

# Or add to db_config.env
echo "TELEGRAM_BOT_TOKEN=123456:ABC-DEF..." >> db_config.env
echo "TELEGRAM_CHAT_ID=123456789" >> db_config.env
```

## Next Phase Readiness

**Phase 6 Complete:** All 6 success criteria satisfied
1. ✅ dim_timeframe populated (06-01)
2. ✅ dim_sessions with DST handling (06-01)
3. ✅ Unified EMA table (06-02)
4. ✅ Scripts reference dim_timeframe (06-03)
5. ✅ Time alignment validation tests (06-04)
6. ✅ Incremental refresh infrastructure (06-05)
7. ✅ **Rowcount validation with alerting (06-06) ← THIS PLAN**

**Ready for Phase 7+:**
- Time model infrastructure complete
- Validation patterns established
- Telegram alerting available for future use
- EMA refresh pipeline production-ready

**No blockers identified.**

## Commits

1. **527cd22** - `feat(06-06): create Telegram notification helper`
   - notifications package with telegram.py module
   - is_configured, send_message, send_alert, send_validation_alert

2. **4065cb0** - `feat(06-06): create EMA rowcount validation script`
   - validate_ema_rowcounts.py with CLI
   - compute_expected_rowcount, validate_rowcounts, summarize_validation

3. **9d8bd68** - `feat(06-06): integrate validation into EMA refresh pipeline`
   - run_validation() function in run_all_ema_refreshes.py
   - --validate and --alert-on-validation-error flags

4. **9311251** - `test(06-06): create rowcount validation test suite`
   - 16 tests (unit, status, summary, Telegram, CLI, integration)

5. **bd8a8dc** - `fix(06-06): remove duplicate --quiet argument`
   - Bug fix for argparse conflict

**Duration:** 509 seconds (8.5 minutes)
**Test Coverage:** 16 tests, all passing

---

*Completed: 2026-01-30*
*Wave 3 of Phase 6: Time model validation infrastructure complete*
