# Phase 88: Integration Testing & Go-Live - Research

**Researched:** 2026-03-24
**Domain:** Integration testing, smoke test scripting, paper trading validation, parity checking, release engineering
**Confidence:** HIGH

---

## Summary

Phase 88 is a validation and release phase, not a feature-building phase. The entire codebase for the v1.2.0 pipeline exists and is already wired; this phase confirms it all works together and ships it. The research investigated five areas: (1) the exact stage order and structure of `run_daily_refresh.py --all`, (2) the parity checker infrastructure and its current threshold behavior, (3) Telegram notification infrastructure, (4) the existing OPERATIONS_MANUAL.md structure and what sections need updating, and (5) the project's established milestone audit/release process.

The core finding: no new infrastructure needs to be invented. The smoke test is a new script (`scripts/integration/smoke_test.py`) that queries existing tables stage-by-stage. The burn-in is literally `run_daily_refresh.py --all --paper-start <DATE>` run daily for 7 days. The parity check already exists at `scripts/executor/run_parity_check.py --bakeoff-winners` and needs only a threshold extension. The runbooks require incremental updates to existing `docs/guides/operations/` parts. The release is a standard git tag on main.

**Primary recommendation:** Build the smoke test script first (it is the sole net-new script), then run burn-in and parity check using existing tooling, then update docs, then tag.

---

## Standard Stack

### The Complete `--all` Pipeline Stage Order

`run_daily_refresh.py --all` runs stages in this exact order. Each stage is a subprocess call:

| Order | Stage | CLI Module | Timeout | Tables Written |
|-------|-------|-----------|---------|----------------|
| 1 | sync_fred_vm | `ta_lab2.scripts.etl.sync_fred_from_vm` | 5 min | `fred.series_values` |
| 2 | sync_hl_vm | `ta_lab2.scripts.etl.sync_hl_from_vm` | 10 min | `hyperliquid.*` |
| 3 | bars | `scripts/bars/run_all_bar_builders.py` | 2 hr | `price_bars_multi_tf_u` |
| 4 | emas | `scripts/emas/run_all_ema_refreshes.py` | 1 hr | `ema_multi_tf_u` |
| 5 | amas | `scripts/amas/run_all_ama_refreshes.py` | 1 hr | `ama_multi_tf_u` |
| 6 | desc_stats | `ta_lab2.scripts.desc_stats.run_all_desc_stats_refreshes` | 1 hr | `asset_stats`, `cross_asset_corr` |
| 7 | macro_features | `ta_lab2.scripts.macro.refresh_macro_features` | 5 min | `fred.fred_macro_features` |
| 8 | macro_regimes | `ta_lab2.scripts.macro.refresh_macro_regimes` | 5 min | `macro_regimes` |
| 9 | macro_analytics | `ta_lab2.scripts.macro.refresh_macro_analytics` | 15 min | `hmm_regimes`, `macro_lead_lag_results` |
| 10 | cross_asset_agg | `ta_lab2.scripts.macro.refresh_cross_asset_agg` | 10 min | `cross_asset_agg`, `funding_rate_agg` |
| 11 | macro_gates (sub) | `ta_lab2.scripts.risk.evaluate_macro_gates` | 2 min | `dim_risk_state` (gate state) |
| 12 | macro_alerts (sub) | `ta_lab2.scripts.macro.run_macro_alerts` | 1 min | Telegram + `pipeline_alert_log` |
| 13 | regimes | `scripts/regimes/refresh_regimes.py` | 30 min | `regimes` |
| 14 | features | `ta_lab2.scripts.features.run_all_feature_refreshes` | 30 min | `features` |
| 15 | garch | `scripts/garch/refresh_garch_forecasts.py` | 30 min | `garch_forecasts`, `garch_diagnostics` |
| 16 | signals | `ta_lab2.scripts.signals.run_all_signal_refreshes` | 30 min | `signals_ema_crossover`, `signals_rsi`, `signals_atr` |
| 17 | calibrate_stops | `ta_lab2.scripts.portfolio.calibrate_stops` | 5 min | `stop_calibrations` |
| 18 | portfolio | `ta_lab2.scripts.portfolio.refresh_portfolio_allocations` | 10 min | `portfolio_allocations` |
| 19 | executor | `ta_lab2.scripts.executor.run_paper_executor` | 5 min | `orders`, `fills`, `positions`, `order_events` |
| 20 | drift_monitor (conditional) | `ta_lab2.scripts.drift.run_drift_monitor` | 10 min | `drift_metrics` (requires `--paper-start`) |
| 21 | stats | `ta_lab2.scripts.stats.run_all_stats_runners` | 1 hr | `*_stats` tables |

Notes from source code:
- `sync_vms` failures are non-blocking (warns, continues with local data)
- `macro_gates` and `macro_alerts` always run when `macro_regimes` runs (non-blocking)
- `drift_monitor` is skipped unless `--paper-start DATE` is provided
- Each non-VM stage stops remaining stages on failure unless `--continue-on-error` is set
- Total wall time for `--all --ids all` is approximately 4-7 hours

### Key Tables for Smoke Test Verification

| Stage | Verify Table | Key Columns | Sanity Check |
|-------|-------------|-------------|--------------|
| bars | `price_bars_multi_tf_u` | `open, high, low, close` | No NaN close; close > 0 |
| emas | `ema_multi_tf_u` | `d1, d2` | Both non-NULL; d1 > 0 |
| features | `features` | any 10+ feature cols | No all-NULL rows |
| garch | `garch_forecasts` | `forecast_vol_1d` | > 0, < 5.0 (500% daily vol) |
| signals | `signals_ema_crossover` | `signal_value` | In [-1, 0, 1] |
| stop_calibrations | `stop_calibrations` | `sl_p50` | > 0, < 1.0 |
| portfolio_allocations | `portfolio_allocations` | `weight_mv` | Between -1 and 1 |
| executor | `orders`, `fills` | `fill_price` | fill_price > 0; filled_at valid TIMESTAMPTZ |
| drift | `drift_metrics` | `tracking_error_pct` | If exists: non-negative |

### Existing Validation Infrastructure (Build On, Do Not Duplicate)

`run_preflight_check.py` already checks 15 conditions including:
- DB connectivity
- `dim_executor_config` active rows
- `dim_risk_state` trading_state = 'active'
- drift_paused = false
- BTC price bars current (< 30h)
- `features` current (< 30h)
- EMA data current (< 30h)
- No orphaned orders
- `executor_run_log` accessible
- `drift_metrics` accessible

The smoke test script should call `run_preflight_check` as a first step (or inline equivalent checks), then layer on v1.2.0-specific table checks on top.

---

## Architecture Patterns

### Smoke Test Script Pattern

The smoke test must be a standalone CLI script at `src/ta_lab2/scripts/integration/smoke_test.py`. Follow the existing `run_preflight_check.py` pattern:

```python
# Source: src/ta_lab2/scripts/validation/run_preflight_check.py (existing pattern)

# 1. Named check results with PASS/WARN/FAIL
# 2. Query-then-validate (not assertion-based)
# 3. NullPool engine (project convention for CLI scripts)
# 4. Structured exit: 0 = all pass, 1 = any fail
# 5. Print to stdout; errors to stderr

_CheckResult = namedtuple("_CheckResult", ["name", "status", "detail"])

def run_checks(engine) -> list[_CheckResult]:
    results = []
    for check in _build_checks():
        try:
            row = conn.execute(text(check.query)).fetchone()
            passed, detail = check.validator(row)
            status = "PASS" if passed else "FAIL"
        except Exception as e:
            status = "FAIL"
            detail = str(e)
        results.append(_CheckResult(name=check.name, status=status, detail=detail))
    return results
```

Key design choices for Phase 88:
- Test 3-5 assets: BTC (id=1), ETH (id=52), a mid-cap alt, a small-cap alt, and one stablecoin proxy to catch edge cases in signal generation. Actual asset IDs to select at discretion (BTC=1, ETH=52 are confirmed from codebase).
- Use `--dry-run` flags on calibrate_stops and executor where supported
- Reads live DB, verifies rows exist and values are sane
- All file I/O uses `encoding='utf-8'` (Windows cp1252 safety per project MEMORY.md)

### Smoke Test Stage Structure

```python
# One check group per pipeline stage
# Source: pattern from run_preflight_check.py

_STAGE_CHECKS = [
    # STAGE: price bars
    SmokeCheck(
        name="BTC price bars: non-zero row count",
        query="""
            SELECT COUNT(*) FROM price_bars_multi_tf_u
            WHERE id = 1 AND tf = '1D' AND ts >= NOW() - INTERVAL '2 days'
        """,
        validator=_val_count_gte(1, "recent BTC 1D bars"),
    ),
    SmokeCheck(
        name="BTC price bars: no NaN close",
        query="""
            SELECT COUNT(*) FROM price_bars_multi_tf_u
            WHERE id = 1 AND tf = '1D' AND close IS NULL
        """,
        validator=_val_count_zero("NULL close prices"),
    ),
    # ... continue for each stage
]
```

### Parity Check Extension

The parity checker at `executor/parity_checker.py` uses r >= 0.99 threshold for `fixed` slippage mode. Phase 88 requires r >= 0.90 (softer threshold). The `_evaluate_parity` method must be extended with a configurable threshold:

```python
# Source: src/ta_lab2/executor/parity_checker.py (existing)
# Current: pnl_correlation >= 0.99 for fixed/lognormal modes
# Phase 88 needs: --pnl-correlation-threshold 0.90 CLI flag

def _evaluate_parity(self, report: dict, slippage_mode: str,
                     pnl_correlation_threshold: float = 0.99) -> bool:
    ...
    if slippage_mode in ("fixed", "lognormal"):
        corr = report.get("pnl_correlation") or 0.0
        return corr >= pnl_correlation_threshold  # was 0.99, Phase 88 adds flag
```

The `run_parity_check.py` CLI should add:
```
--pnl-correlation-threshold FLOAT
    Minimum P&L correlation for PASS (default: 0.99; Phase 88 uses 0.90)
```

The bakeoff winner discovery already exists in `run_parity_check.py`:
- Queries `strategy_bakeoff_results` (CPCV first, falls back to PKF)
- Maps `strategy_name -> signal_type` via `_STRATEGY_SIGNAL_MAP`
- Resolves `signal_id` from `dim_signals`
- Runs `ParityChecker.check()` per winner

Known limitation: Phase 82 bake-off results land in `strategy_bakeoff_results`, not `backtest_trades`. The parity checker warns when `backtest_trade_count == 0`. A linking step (run backtest replay) may be needed before parity check is meaningful. This must be documented.

### Daily Burn-In Report Pattern

No daily status report script exists yet. Pattern to follow is `weekly_digest.py`:

```python
# Source: src/ta_lab2/scripts/stats/weekly_digest.py (pattern to follow)
# weekly_digest.py queries *_stats tables with PASS/WARN/FAIL counts
# daily_burn_in_report.py queries paper trading tables for burn-in metrics

# Burn-in report queries:
# - fills count today (paper executor ran)
# - last drift_metrics.tracking_error_pct (drift under control)
# - dim_risk_state.trading_state (not halted)
# - dim_risk_state.drift_paused (not paused)
# - orders count today (executor processed signals)
# - today's pipeline_run_log entry status (Phase 87 table)
# - paper PnL since burn-in start date (cumulative)
```

Telegram delivery follows the same pattern as `weekly_digest.py`:
- `send_message()` from `ta_lab2.notifications.telegram`
- HTML parse mode
- 4000 char limit

### Telegram Infrastructure (Confirmed Working)

`src/ta_lab2/notifications/telegram.py`:
- `is_configured()` -- checks `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` env vars
- `send_message(text, parse_mode="HTML")` -- raw send
- `send_alert(title, message, severity)` -- formatted with emoji prefix
- `send_critical_alert(error_type, error_message, context)` -- structured critical format
- Graceful degradation: if unconfigured, logs warning and returns False (never raises)
- Requires `requests` library (already installed per project deps)

For burn-in alerts, wire Telegram to:
1. Kill switch activation (already done in risk engine -- verify from Phase 87)
2. Drift pause activation (already done in drift monitor)
3. Daily burn-in status report (NEW in Phase 88 -- daily digest style)

### OPERATIONS_MANUAL.md Structure

The manual is organized as an index (`docs/guides/OPERATIONS_MANUAL.md`) pointing to 7 part files in `docs/guides/operations/`:
- Part 1: `01_setup_and_first_run.md`
- Part 2: `02_daily_pipeline.md` -- the most relevant part for Phase 88 updates
- Part 3: `03_research_and_experiments.md`
- Part 4: `04_paper_trading_and_risk.md`
- Part 5: `05_adding_assets_and_data.md`
- Part 6: `06_ai_memory_and_orchestration.md`
- Part 7: `07_path_to_production.md`

Parts 2 and 4 require updates for v1.2.0 components (GARCH, stop calibration, portfolio allocations, parity check extension, new dashboard pages). Part 7 already has paper-to-live criteria framework but needs burn-in protocol details.

### Release Process (Confirmed Pattern from Prior Milestones)

From MILESTONES.md and milestone audit files:
1. Run `/gsd:audit-milestone` to generate a MILESTONE-AUDIT.md
2. Update CHANGELOG.md with new version block
3. Merge working branch to main
4. Tag: `git tag v1.2.0` on main
5. Push tag (if pushing to remote)

Prior milestone audit structure (v1.1.0 example):
```yaml
milestone: v1.1.0
audited: 2026-03-21T17:30:00Z
status: tech_debt
scores:
  requirements: 26/26
  phases: 6/6
  integration: 5/6
  flows: 2/3
```

v1.2.0 requirements document should be created at `.planning/milestones/v1.2.0-REQUIREMENTS.md` to enable the audit.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Telegram alerts | Custom HTTP client | `ta_lab2.notifications.telegram.send_alert()` | Already handles token config, error gracefully, HTML format |
| Pipeline stage status | New state table | `pipeline_run_log` (Phase 87 table, already created) | Phase 87 created this table for exactly this purpose |
| Preflight DB checks | Duplicate check logic | Extend/call `run_preflight_check.py` | 15 checks already coded; adds BTC connectivity, risk state, executor config |
| Bakeoff winner discovery | SQL from scratch | `_discover_bakeoff_winners()` in `run_parity_check.py` | Already handles CPCV/PKF fallback, signal_id resolution |
| Weekly QC digest | Separate report | `ta_lab2.scripts.stats.weekly_digest` | Already sends via Telegram, covers all stats tables |
| Changelog generation | Manual parsing | `git log v1.1.0..HEAD --oneline` + manual curation | 170 commits since v1.1.0; git log provides raw material |
| DB URL resolution | Custom env reading | `ta_lab2.scripts.refresh_utils.resolve_db_url()` | Project convention; reads `TARGET_DB_URL`, `DATABASE_URL`, `db_config.env` |
| Engine creation | Custom connection | `create_engine(db_url, poolclass=NullPool)` | NullPool is project convention for CLI scripts |

---

## Common Pitfalls

### Pitfall 1: Parity Check Will Warn About Zero Backtest Trades

**What goes wrong:** `run_parity_check.py --bakeoff-winners` prints `[WARN] No backtest trades found for signal_id=N`. The parity check reports 0 backtest trades and fails.

**Why it happens:** Phase 82 bake-off results write to `strategy_bakeoff_results`, not `backtest_trades`. The parity checker queries `backtest_trades` via `backtest_runs`. These are different tables. The bakeoff never created `backtest_runs` rows.

**How to avoid:** Before running parity check, run the executor in replay mode for the bakeoff date range to populate `fills`, then the parity comparison between backtest signals and executor fills can proceed. Document this prerequisite clearly in the plan.

**Warning signs:** `[WARN] No backtest trades found` in parity check output.

### Pitfall 2: Drift Monitor Requires `--paper-start`

**What goes wrong:** `run_daily_refresh.py --all` silently skips the drift stage without error if `--paper-start` is not provided.

**Why it happens:** The drift stage has this guard:
```python
run_drift = (args.drift or args.all) and not getattr(args, "no_drift", False)
# but later: if run_drift and getattr(args, "paper_start", None):
```
No `--paper-start` = drift stage never runs even with `--all`.

**How to avoid:** Burn-in commands must always include `--paper-start YYYY-MM-DD`. Use burn-in start date as the paper-start date.

**Warning signs:** Drift monitor never appears in the run summary despite using `--all`.

### Pitfall 3: Smoke Test on Stale Data

**What goes wrong:** Smoke test checks tables that haven't been refreshed today (bars still from yesterday), checks pass because rows exist but data is stale.

**Why it happens:** Row count checks pass if any rows exist, even old ones.

**How to avoid:** Use `ts >= NOW() - INTERVAL '48 hours'` for recency checks on key tables (bars, features, signals), not just `COUNT(*) > 0`. Pattern from `run_preflight_check.py` uses 30-hour staleness check with `_val_stale_check()`.

**Warning signs:** Smoke test PASS but pipeline clearly hasn't run recently.

### Pitfall 4: Windows UTF-8 Encoding in New Scripts

**What goes wrong:** Any file containing UTF-8 box-drawing characters (like `│`, `├`, `└`) causes `UnicodeDecodeError` on Windows (cp1252 encoding).

**Why it happens:** Project MEMORY.md explicitly calls this out: "SQL on Windows: UTF-8 box-drawing chars cause UnicodeDecodeError. Always encoding='utf-8'".

**How to avoid:** Use ASCII separators in new scripts (`=`, `-`, `|`). All existing smoke-test-style scripts (e.g., `run_preflight_check.py`, `calibrate_stops.py`) include the comment: "ASCII-only file -- no UTF-8 box-drawing characters."

**Warning signs:** `UnicodeDecodeError` on Windows when running the script.

### Pitfall 5: Missing `alembic upgrade head` Before Pipeline Run

**What goes wrong:** Phase 87 added 4 new tables (`pipeline_run_log`, `signal_anomaly_log`, `pipeline_alert_log`, `dim_ic_weight_overrides`). Phase 86 added `stop_calibrations`. If alembic is not at head, these tables don't exist and pipeline stages fail.

**Why it happens:** `run_daily_refresh.py` checks migration status with `check_migration_status()` but it is advisory, non-blocking.

**How to avoid:** Smoke test Step 0 should verify alembic is at head. Include in OPERATIONS_MANUAL runbook.

**Warning signs:** `relation "stop_calibrations" does not exist` or similar errors.

### Pitfall 6: Parity Check r >= 0.90 Threshold Not Enforced by Default

**What goes wrong:** Current `ParityChecker._evaluate_parity()` uses r >= 0.99 for fixed slippage mode. The Phase 88 decision is r >= 0.90. Without a code change, the parity check will fail when it should pass.

**Why it happens:** Threshold is hardcoded. The `run_parity_check.py --bakeoff-winners` defaults to `slippage_mode=fixed` which internally requires 0.99 correlation.

**How to avoid:** Add `--pnl-correlation-threshold` flag to `run_parity_check.py`, pass it through to `ParityChecker.check()`. This is the planned extension.

---

## Code Examples

### Smoke Test Check Definition (Verified Pattern)

```python
# Source: src/ta_lab2/scripts/validation/run_preflight_check.py

from collections import namedtuple
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool
from ta_lab2.scripts.refresh_utils import resolve_db_url

SmokeCheck = namedtuple("SmokeCheck", ["name", "query", "validator"])
SmokeResult = namedtuple("SmokeResult", ["name", "status", "detail"])

def _val_count_gte(expected: int, label: str):
    def validator(row):
        count = int(row[0]) if row else 0
        return count >= expected, f"{count} {label}"
    return validator

def _val_stale_check(label: str, hours: int = 48):
    from datetime import datetime, timedelta, timezone
    import pandas as pd
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    def validator(row):
        raw_ts = row[0] if row else None
        if raw_ts is None:
            return False, f"no rows for {label}"
        ts = pd.Timestamp(raw_ts)
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        return ts >= cutoff, f"latest {label} = {ts.isoformat()}"
    return validator

# GARCH check example (new for v1.2.0)
SmokeCheck(
    name="GARCH forecasts: BTC has recent forecast",
    query="""
        SELECT MAX(created_at) FROM garch_forecasts
        WHERE id = 1 AND horizon = 1
    """,
    validator=_val_stale_check("garch_forecasts BTC horizon-1"),
),
SmokeCheck(
    name="GARCH forecasts: BTC vol is sane (0 < vol < 500%)",
    query="""
        SELECT forecast_vol_1d FROM garch_forecasts_latest
        WHERE id = 1
    """,
    validator=lambda row: (
        row is not None and 0 < float(row[0]) < 5.0,
        f"BTC forecast_vol_1d = {row[0] if row else None}"
    ),
),

# Stop calibrations check (new for v1.2.0)
SmokeCheck(
    name="stop_calibrations: rows exist",
    query="SELECT COUNT(*) FROM stop_calibrations",
    validator=_val_count_gte(1, "stop calibration rows"),
),
```

### Run Parity Check with Custom Threshold

```bash
# Source: src/ta_lab2/scripts/executor/run_parity_check.py (with Phase 88 extension)

# Prerequisite: run executor in replay mode first
python -m ta_lab2.scripts.executor.run_paper_executor \
    --replay-historical \
    --start 2025-01-01 \
    --end 2025-12-31

# Then parity check with bakeoff winners and softer threshold
python -m ta_lab2.scripts.executor.run_parity_check \
    --bakeoff-winners \
    --start 2025-01-01 \
    --end 2025-12-31 \
    --slippage-mode fixed \
    --pnl-correlation-threshold 0.90
```

### Daily Burn-In Command

```bash
# Full pipeline with drift monitor (burn-in standard command)
python -m ta_lab2.scripts.run_daily_refresh \
    --all \
    --ids all \
    --paper-start 2026-03-24 \
    --continue-on-error

# Daily burn-in status report (new script)
python -m ta_lab2.scripts.integration.daily_burn_in_report \
    --burn-in-start 2026-03-24
```

### Telegram Alert for Burn-In Events

```python
# Source: src/ta_lab2/notifications/telegram.py (existing API)
from ta_lab2.notifications.telegram import send_alert, is_configured

# Critical burn-in event (kill switch trigger)
if kill_switch_triggered:
    send_alert(
        title="KILL SWITCH TRIGGERED - Burn-In STOP",
        message=(
            f"Kill switch activated during 7-day burn-in.\n"
            f"Reason: {reason}\n"
            f"Day: {burn_in_day}/7\n"
            f"Review dim_risk_state and risk_events tables."
        ),
        severity="critical",
    )
```

### v1.2.0 Release Tag

```bash
# After milestone audit passes and changelog updated
git checkout main
git merge refactor/strip-cmc-prefix-add-venue-id  # or current branch
git tag v1.2.0
git push origin v1.2.0
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| No smoke test script exists | New: `scripts/integration/smoke_test.py` | Phase 88 | Single-command pipeline validation |
| Parity threshold: r >= 0.99 (exact replay) | Phase 88: r >= 0.90 (allows slippage divergence) | Phase 88 | Soft gate -- structural signal bugs still caught |
| Weekly QC digest only | Add: daily burn-in status report | Phase 88 | Daily visibility during burn-in week |
| OPERATIONS_MANUAL.md covers v1.0.x | Update: add v1.2.0 components | Phase 88 | GARCH, stop calibration, portfolio, parity runbooks |
| `run_parity_check.py` uses fixed 0.99 threshold | Add: `--pnl-correlation-threshold` flag | Phase 88 | Configurable for burn-in vs strict replay |

**v1.2.0 new tables (added by phases 81-87):**
- `garch_forecasts` -- GARCH model forecasts (Phase 81)
- `garch_diagnostics` -- GARCH model fit diagnostics (Phase 81)
- `garch_forecasts_latest` -- materialized view of latest per asset (Phase 81)
- `stop_calibrations` -- MAE/MFE-based stop ladders (Phase 86, migration `m7n8o9p0q1r2`)
- `portfolio_allocations` -- MV/CVaR/HRP weights (Phase 86, migration `m7n8o9p0q1r2`)
- `pipeline_run_log` -- dead-man switch audit (Phase 87, migration `n8o9p0q1r2s3`)
- `signal_anomaly_log` -- signal validation gate events (Phase 87)
- `pipeline_alert_log` -- throttle table for IC decay alerts (Phase 87)
- `dim_ic_weight_overrides` -- BL weight overrides for decayed features (Phase 87)

---

## Open Questions

1. **Parity check data gap: backtest_trades vs strategy_bakeoff_results**
   - What we know: `run_parity_check.py --bakeoff-winners` will warn "No backtest trades found for signal_id=N" because Phase 82 bakeoff results are in `strategy_bakeoff_results`, not `backtest_trades`. The parity checker queries `backtest_trades`.
   - What's unclear: Does a replay run of the executor create `fills` from the historical signal period that can be compared? Or does the parity check require `backtest_trades` rows populated by a classical backtest run?
   - Recommendation: Treat the replay pathway as the Phase 88 parity mechanism. The planner should structure a task to: (a) run executor in `--replay-historical` mode over the bakeoff date range to populate `fills`, then (b) run parity check comparing those fills to signal timing. The `backtest_trades` dependency may require running a backtest first.

2. **Asset selection for smoke test (Claude's Discretion)**
   - What we know: BTC=id 1, ETH=id 52 confirmed in `run_preflight_check.py`. The plan specifies 3-5 assets.
   - Recommendation: BTC (id=1), ETH (id=52), plus 2-3 assets from the bakeoff universe to ensure signal generation covers more than just the majors. The specific IDs should be queried at runtime from `dim_executor_config` to pick assets that have active executor configs.

3. **Alembic status before Phase 88**
   - What we know: Latest migration is `m7n8o9p0q1r2` (Phase 86). Phase 87 added migration `n8o9p0q1r2s3` (Phase 87 plans show this). Current HEAD revision may or may not include Phase 87 migration.
   - What's unclear: Phase 87 plans exist but no verification evidence was found. The smoke test should check `alembic current` output to confirm all migrations are applied.
   - Recommendation: First task in Phase 88 is to verify `alembic upgrade head` completes cleanly.

---

## Sources

### Primary (HIGH confidence)
- `src/ta_lab2/scripts/run_daily_refresh.py` -- complete stage order, timeouts, CLI flags, dry-run behavior
- `src/ta_lab2/scripts/executor/run_parity_check.py` -- bakeoff winner discovery, parity check flow, slippage modes
- `src/ta_lab2/executor/parity_checker.py` -- threshold logic (r >= 0.99 for fixed), tables queried
- `src/ta_lab2/scripts/validation/run_preflight_check.py` -- smoke test pattern (namedtuple checks, validator functions, exit codes)
- `src/ta_lab2/notifications/telegram.py` -- Telegram API (send_message, send_alert, send_critical_alert)
- `src/ta_lab2/scripts/drift/run_drift_monitor.py` -- drift monitor CLI, paper_start requirement
- `docs/guides/OPERATIONS_MANUAL.md` -- manual structure (7 parts, 229 lines)
- `docs/guides/operations/04_paper_trading_and_risk.md` -- paper trading architecture
- `docs/guides/operations/07_path_to_production.md` -- Telegram setup, gate criteria
- `.planning/milestones/v1.1.0-MILESTONE-AUDIT.md` -- audit format reference
- `docs/CHANGELOG.md` -- changelog format (Keep a Changelog)
- `alembic/versions/m7n8o9p0q1r2_phase86_portfolio_pipeline.py` -- confirms `stop_calibrations` + `portfolio_allocations` tables

### Secondary (MEDIUM confidence)
- `.planning/phases/87-live-pipeline-alert-wiring/87-01-PLAN.md` -- confirms Phase 87 table names (`pipeline_run_log`, `pipeline_alert_log`, etc.) and migration ID `n8o9p0q1r2s3`
- `src/ta_lab2/scripts/stats/weekly_digest.py` -- daily report pattern to follow

### Tertiary (LOW confidence)
- Phase 87 execution state is unknown -- plans exist but verification was not found in the research window. Whether Phase 87 is complete must be confirmed before Phase 88 planning proceeds.

---

## Metadata

**Confidence breakdown:**
- Pipeline stage order: HIGH -- read directly from `run_daily_refresh.py` source
- Smoke test pattern: HIGH -- `run_preflight_check.py` is the verified pattern
- Parity check behavior: HIGH -- read from `parity_checker.py` and `run_parity_check.py`
- Telegram infrastructure: HIGH -- read from `telegram.py` source
- Operations manual structure: HIGH -- read the file directly
- Phase 87 completion status: LOW -- plans exist but execution not confirmed

**Research date:** 2026-03-24
**Valid until:** 2026-04-24 (stable infrastructure; 30-day window)
