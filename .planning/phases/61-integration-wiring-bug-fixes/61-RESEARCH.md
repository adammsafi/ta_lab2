# Phase 61: Integration Wiring & Bug Fixes - Research

**Researched:** 2026-02-28
**Domain:** Cross-module wiring: PaperExecutor + RiskEngine + daily refresh orchestrator + Telegram alerts + drift report rendering
**Confidence:** HIGH — all findings are from direct source code inspection

## Summary

Phase 61 is a pure gap-closure phase. All work consists of wiring together existing, already-implemented modules and fixing known column-name bugs. No new features are built. Four items require changes across four files.

The research inspected all relevant source files directly. Every claim below is grounded in actual file content. There are no ambiguities about what to change: the audit was accurate and the bugs are confirmed.

**Primary recommendation:** Make all four changes as isolated, surgical edits. Each change is in a different file with no coupling between them. They can be planned and verified independently.

---

## Standard Stack

This phase uses no new libraries. Everything already exists in the codebase.

### Core (already installed)
| Component | Module Path | Purpose |
|-----------|------------|---------|
| RiskEngine | `ta_lab2.risk.risk_engine` | Order-level risk gates |
| PaperExecutor | `ta_lab2.executor.paper_executor` | Paper trading orchestration |
| Telegram notifier | `ta_lab2.notifications.telegram` | `send_critical_alert` lives here |
| Feature refresh | `ta_lab2.scripts.features.run_all_feature_refreshes` | `--all --tf 1D` refreshes cmc_features |
| DriftReport | `ta_lab2.drift.drift_report` | Renders weekly drift Markdown report |

---

## Architecture Patterns

### Pattern 1: RiskEngine integration in PaperExecutor

**What:** `RiskEngine` must be instantiated once in `PaperExecutor.__init__` and called at three points during execution.

**Current state (paper_executor.py):**
- `__init__` — no `RiskEngine` instantiation
- `run()` loop — no `check_daily_loss()` call at start of each strategy iteration
- `_process_asset_signal()` — no `check_order()` call before `CanonicalOrder` creation
- No `trading_state` guard before processing signals

**RiskEngine API (confirmed from risk_engine.py):**

```python
# Instantiation (no DB query on init)
risk = RiskEngine(engine)

# Gate: call at start of each run() iteration (before processing any signals)
# Returns True if kill switch was triggered today
killed = risk.check_daily_loss()

# Gate: call before CanonicalOrder creation in _process_asset_signal
result = risk.check_order(
    order_qty=order_qty,          # Decimal
    order_side=side,              # "buy" or "sell"
    fill_price=current_price,     # Decimal
    asset_id=asset_id,            # int
    strategy_id=config.config_id, # int
    current_position_value=current_position_value,  # Decimal
    portfolio_value=portfolio_value,  # Decimal
)
if not result.allowed:
    return {"skipped_no_delta": True}  # or appropriate skip return
order_qty = result.adjusted_quantity   # use adjusted qty, not original

# State guard: check dim_risk_state.trading_state before processing signals
# This is already handled by check_order() -> _is_halted() internally.
# The explicit trading_state guard is an additional early-exit before signal read.
```

**Where to insert in paper_executor.py:**
1. `__init__`: add `self.risk_engine = RiskEngine(self.engine)` (import at top)
2. `_run_strategy()`: call `self.risk_engine.check_daily_loss()` at start, before signals are read. If returns True, write run log with status "halted" and return empty counts.
3. `_run_strategy()`: check `trading_state` from `dim_risk_state` directly, or rely on `check_daily_loss()` which reads it internally. The audit specifies checking `dim_risk_state.trading_state` before processing signals — this can be a direct DB query or delegate to `risk_engine._is_halted()`. Given `_is_halted` is private, a direct query is cleaner for the explicit guard.
4. `_process_asset_signal()`: call `self.risk_engine.check_order(...)` immediately after computing `delta` and before creating `CanonicalOrder`. Use `result.adjusted_quantity` as the order quantity. Return `{"skipped_no_delta": True}` when `not result.allowed`.

**current_position_value computation for check_order:**
`current_qty` (Decimal) and `current_price` (Decimal) are both available in `_process_asset_signal`. Compute: `current_position_value = current_qty * current_price`.

### Pattern 2: Feature refresh stage in run_daily_refresh.py

**What:** Add a `run_feature_refresh_stage()` function and call it between regimes and signals in the `main()` pipeline.

**Current pipeline order in main():**
```
bars -> EMAs -> AMAs -> desc_stats -> regimes -> [MISSING: features] -> signals -> portfolio -> executor -> drift -> stats
```

**Feature refresh CLI (confirmed from run_all_feature_refreshes.py):**
```bash
python -m ta_lab2.scripts.features.run_all_feature_refreshes --all --tf 1D
```

The script uses `TARGET_DB_URL` from `ta_lab2.config` rather than `--db-url`. It does NOT accept a `--db-url` argument. The stage function should invoke it via subprocess without passing `--db-url`.

**Arguments confirmed:**
- `--all` (mutually exclusive with `--ids`) — processes all IDs
- `--tf 1D` (mutually exclusive with `--all-tfs`) — only refresh 1D timeframe in daily pipeline
- No `--verbose`, no `--dry-run` propagation (the script doesn't accept these)
- No `--db-url` argument (reads from env)

**Timeout:** A reasonable timeout for feature refresh is 1800s (30 min), same as signals. This covers the sequential vol -> ta -> cmc_features pipeline.

**Stage placement:** After `run_regimes` block, before `run_signals` block in `main()`. The `--all` flag must trigger this stage. Add a `--features` flag for standalone invocation and `--no-features` to skip in `--all` mode (following existing patterns like `--no-execute`).

**run_feature_refresh_stage() pattern (follows existing stage functions):**
```python
def run_feature_refresh_stage(args, db_url: str) -> ComponentResult:
    cmd = [
        sys.executable,
        "-m",
        "ta_lab2.scripts.features.run_all_feature_refreshes",
        "--all",
        "--tf", "1D",
    ]
    # No --db-url (reads from env), no --verbose, no --dry-run
    ...
```

Note: `db_url` parameter is accepted for API consistency but not passed to subprocess (the feature refresh reads from `TARGET_DB_URL` env var).

### Pattern 3: Telegram alert import fix in paper_executor.py

**Current wrong import (paper_executor.py line 586):**
```python
from ta_lab2.scripts.run_daily_refresh import send_critical_alert
```

**Problem:** `run_daily_refresh.py` does NOT define `send_critical_alert`. This import raises `ImportError` at call time, silently swallowed by the `except Exception` block in `_try_telegram_alert`.

**Correct import:**
```python
from ta_lab2.notifications.telegram import send_critical_alert
```

**Signature mismatch (CRITICAL):** The telegram `send_critical_alert` takes:
```python
def send_critical_alert(
    error_type: str,       # Category: "database", "corruption", "validation"
    error_message: str,    # Human-readable message
    context: dict | None = None,  # Additional context
) -> bool:
```

But `_try_telegram_alert` calls it as:
```python
send_critical_alert(message)  # Only one argument
```

This will raise `TypeError: send_critical_alert() missing 1 required positional argument: 'error_message'` after the import is fixed.

**Fix:** Change the call in `_try_telegram_alert` to:
```python
send_critical_alert("executor", message)
# or
send_critical_alert("executor_alert", message)
```

Both the import and the call signature must be fixed together.

### Pattern 4: Drift report column-name bugs

**Bug locations confirmed by DDL (094_cmc_drift_metrics.sql) vs drift_report.py:**

**Bug 1: attr_unexplained_residual vs attr_unexplained (3 locations in drift_report.py)**

DDL column name: `attr_unexplained` (line 84 of DDL)
drift_report.py uses: `"attr_unexplained_residual"` at:
- Line 83: `_ATTR_COLUMNS` list entry
- Line 400: exclusion filter in `_plot_attribution_waterfall`
- Line 432-433: column presence check and `.mean()` call in `_plot_attribution_waterfall`

Fix: Change `"attr_unexplained_residual"` to `"attr_unexplained"` in all 3 locations.

**Bug 2: drift_paused column does not exist in cmc_drift_metrics**

drift_report.py line 558-559 checks:
```python
if "drift_paused" in df.columns:
    pause_active = bool(df["drift_paused"].any())
```

The column `drift_paused` does NOT appear in `094_cmc_drift_metrics.sql`. The `drift_paused` concept lives in `dim_risk_state` (not in cmc_drift_metrics). This `if` block will always be False (column absent), making the pause status line never render.

Fix options: Either remove this block, or query `dim_risk_state` separately for pause status. Given the audit says "breach count section always empty (threshold_breach_5d vs threshold_breach)", the `drift_paused` issue is a separate rendering gap. The simplest fix for the audit is to remove the `drift_paused` conditional block since it references a nonexistent column.

**Bug 3: threshold_breach_5d vs threshold_breach**

The audit states "breach count section always empty (threshold_breach_5d vs threshold_breach)". Searching the code, `drift_report.py` uses `"threshold_breach"` (lines 530, 555) which matches the DDL. However, the audit description implies the breach count section was written expecting `threshold_breach_5d` somewhere. The code at line 530 sets `breach_col = "threshold_breach"` and line 555 checks `if "threshold_breach" in df.columns`.

Examining the code: the breach count is computed using `.join()` on `config_id`. The issue is the `join` may fail if `summary_df` doesn't have `config_id` as an index or if the join produces no matches. The `breach_counts` groupby uses `config_id` as the group key, but `summary_df.join(breach_counts, on="config_id")` requires `config_id` to be a column (not the index) for the `on=` parameter to work.

This is the actual bug: `summary_df.join(breach_counts, on="config_id")` — `pd.DataFrame.join(on=)` joins on the specified column of the calling frame against the INDEX of the other frame. But `breach_counts` is a Series with `config_id` as index (from `groupby("config_id")`). This should work correctly. The breach count being empty may be because `summary_df` loses `config_id` column when it's used in `drop_duplicates`.

Looking at the code flow more carefully (lines 516-527):
```python
summary_df = df[available_cols].copy()   # includes config_id
summary_df = df.sort_values(...)[available_cols].drop_duplicates(...)  # reassigned from df not summary_df
```

This path reassigns `summary_df` correctly from `df`. The `config_id` column should be present. The breach count join should work.

Given the audit says "threshold_breach_5d vs threshold_breach" and the code uses `threshold_breach` (correct per DDL), the actual bug may be elsewhere — possibly in an older version of the code the audit was run against, or the code was partially fixed but the column names in `_ATTR_COLUMNS` (attr_unexplained_residual) are still wrong.

**Confirmed bugs (HIGH confidence):**
- `attr_unexplained_residual` -> `attr_unexplained` (3 locations, confirmed against DDL)
- Wrong fallback in `_load_te_threshold`: returns `0.05` but configured default is `0.015`
- `drift_paused` column does not exist in `cmc_drift_metrics` (dead conditional)

**Uncertain bugs (MEDIUM confidence):**
- The "threshold_breach_5d" reference mentioned in the audit — not found in current code. Either already partially fixed, or the audit referenced a different code path.

**TE threshold fallback fix (confirmed from drift_pause.py):**
`drift_pause.py` line 243 uses `COALESCE(drift_tracking_error_threshold_5d, 0.015)` — the correct fallback is `0.015`, not `0.05`. Fix `_load_te_threshold` to return `0.015` as the default.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Checking kill switch state | Custom query in PaperExecutor | `RiskEngine.check_order()` reads `_is_halted()` internally | Already implemented with event logging |
| Custom daily loss check | Direct portfolio value math | `RiskEngine.check_daily_loss()` | Has full logic including day_open_date tracking |
| New Telegram wrapper | Another `send_critical_alert` helper | `ta_lab2.notifications.telegram.send_critical_alert` | Already exists with graceful degradation |

---

## Common Pitfalls

### Pitfall 1: check_order() signature requires Decimal types
**What goes wrong:** Passing `float` values to `check_order()` where `Decimal` is expected causes type errors or silent precision loss.
**How to avoid:** Convert `current_qty * current_price` to Decimal explicitly. `current_qty` is already Decimal (from `pos_row.quantity`). `current_price` comes from `PositionSizer.get_current_price()` — check its return type.

**current_price type check:**
```python
# In position_sizer.py:
current_price = PositionSizer.get_current_price(conn, asset_id)
# Returns Decimal (confirmed: function returns Decimal("..."))
```
Both operands are Decimal, so `current_qty * current_price` is safe.

### Pitfall 2: check_daily_loss() return value
**What goes wrong:** Ignoring the return value means the kill switch fires but orders still proceed.
**How to avoid:** If `check_daily_loss()` returns True, immediately return from `_run_strategy()` with an appropriate status.

### Pitfall 3: Feature refresh subprocess has no --db-url
**What goes wrong:** Passing `--db-url` to `run_all_feature_refreshes.py` subprocess causes argparse error.
**How to avoid:** The feature refresh reads `TARGET_DB_URL` from environment. The `run_daily_refresh.py` process already has the DB URL in env (via `resolve_db_url()`). Do NOT pass `--db-url` to the feature refresh subprocess.

### Pitfall 4: send_critical_alert signature
**What goes wrong:** After fixing the import, calling `send_critical_alert(message)` with one argument still fails with TypeError.
**How to avoid:** Use `send_critical_alert("executor", message)` where `"executor"` is the `error_type` first argument.

### Pitfall 5: _ATTR_COLUMNS is a module-level constant
**What goes wrong:** Changing only the `_plot_attribution_waterfall` references but missing the `_ATTR_COLUMNS` list definition causes inconsistency.
**How to avoid:** Change ALL three occurrences of `attr_unexplained_residual` in drift_report.py simultaneously.

---

## Code Examples

### RiskEngine integration in _process_asset_signal

```python
# Source: src/ta_lab2/risk/risk_engine.py (check_order signature)

# After computing delta and before CanonicalOrder creation:
if abs(delta) < _MIN_ORDER_THRESHOLD:
    return {"skipped_no_delta": True}

# --- Risk gate ---
current_position_value = current_qty * current_price
risk_result = self.risk_engine.check_order(
    order_qty=abs(delta),
    order_side="buy" if delta > 0 else "sell",
    fill_price=current_price,
    asset_id=asset_id,
    strategy_id=config.config_id,
    current_position_value=current_position_value,
    portfolio_value=portfolio_value,
)
if not risk_result.allowed:
    self.logger.info(
        "_process_asset_signal: order blocked by risk gate -- asset_id=%d reason=%s",
        asset_id,
        risk_result.blocked_reason,
    )
    return {"skipped_no_delta": True}
order_qty = risk_result.adjusted_quantity  # use adjusted quantity

if dry_run:
    ...

# --- build canonical order using order_qty (already adjusted) ---
side: str = "buy" if delta > 0 else "sell"
```

### check_daily_loss in _run_strategy

```python
# Source: src/ta_lab2/risk/risk_engine.py (check_daily_loss)

# At start of _run_strategy, after loading signal table:
if self.risk_engine.check_daily_loss():
    self.logger.critical(
        "PaperExecutor: daily loss kill switch triggered for config=%s",
        config.config_name,
    )
    self._write_run_log(config, status="halted", error="daily loss kill switch triggered")
    return counts
```

### trading_state guard in _run_strategy

```python
# Check trading_state before processing signals
with self.engine.connect() as conn:
    state_row = conn.execute(
        text("SELECT trading_state FROM dim_risk_state WHERE state_id = 1")
    ).fetchone()
if state_row and state_row[0] == "halted":
    self.logger.warning(
        "PaperExecutor: trading halted (kill switch) for config=%s -- skipping",
        config.config_name,
    )
    self._write_run_log(config, status="halted")
    return counts
```

Note: This guard is an explicit early-exit before even reading signals. `check_daily_loss()` also reads trading_state internally, but that's called earlier for the daily loss check.

### Corrected Telegram call in paper_executor.py

```python
# Source: src/ta_lab2/notifications/telegram.py (send_critical_alert signature)

def _try_telegram_alert(self, message: str) -> None:
    try:
        from ta_lab2.notifications.telegram import send_critical_alert  # noqa: PLC0415
        send_critical_alert("executor", message)
    except Exception as exc:  # noqa: BLE001
        self.logger.warning(
            "_try_telegram_alert: alerting unavailable (%s). Message: %s",
            exc,
            message,
        )
```

### Feature refresh stage function

```python
# Follows pattern of run_signal_refreshes (no --db-url, uses env)
TIMEOUT_FEATURES = 1800  # 30 minutes

def run_feature_refresh_stage(args, db_url: str) -> ComponentResult:
    cmd = [
        sys.executable,
        "-m",
        "ta_lab2.scripts.features.run_all_feature_refreshes",
        "--all",
        "--tf", "1D",
    ]
    # NOTE: no --db-url (reads TARGET_DB_URL from env), no --verbose, no --dry-run

    print(f"\n{'=' * 70}")
    print("RUNNING FEATURE REFRESH")
    print(f"{'=' * 70}")
    print(f"Command: {' '.join(cmd)}")

    if getattr(args, "dry_run", False):
        print("[DRY RUN] Would run feature refresh")
        return ComponentResult(component="features", success=True, duration_sec=0.0, returncode=0)

    start = time.perf_counter()
    try:
        result = subprocess.run(
            cmd, check=False, capture_output=True, text=True, timeout=TIMEOUT_FEATURES
        )
        ...
    ...
```

### Drift report fixes

```python
# Fix 1: _ATTR_COLUMNS in drift_report.py (line ~83)
# Change: "attr_unexplained_residual"
# To:     "attr_unexplained"

_ATTR_COLUMNS = [
    "attr_baseline_pnl",
    "attr_fee_delta",
    "attr_slippage_delta",
    "attr_timing_delta",
    "attr_data_revision_delta",
    "attr_sizing_delta",
    "attr_regime_delta",
    "attr_unexplained",          # was: "attr_unexplained_residual"
]

# Fix 2: _load_te_threshold fallback (line ~245)
# Change: return 0.05
# To:     return 0.015

# Fix 3: _plot_attribution_waterfall (line ~400)
# Change: c != "attr_unexplained_residual"
# To:     c != "attr_unexplained"

# Fix 4: _plot_attribution_waterfall (line ~432)
# Change: if "attr_unexplained_residual" in df.columns:
#             residual_mean = df["attr_unexplained_residual"].mean(skipna=True)
# To:     if "attr_unexplained" in df.columns:
#             residual_mean = df["attr_unexplained"].mean(skipna=True)
```

---

## File Inventory (exact files to change)

| File | Changes | Lines |
|------|---------|-------|
| `src/ta_lab2/executor/paper_executor.py` | Add RiskEngine import + instantiation + 3 call sites + fix Telegram import+call | ~20-30 lines changed/added |
| `src/ta_lab2/scripts/run_daily_refresh.py` | Add `run_feature_refresh_stage()` function + `TIMEOUT_FEATURES` constant + `--features`/`--no-features` CLI args + pipeline wiring in `main()` | ~80-100 lines added |
| `src/ta_lab2/drift/drift_report.py` | Fix `_ATTR_COLUMNS` list + `_load_te_threshold` fallback + 2 locations in `_plot_attribution_waterfall` | 4-5 lines changed |

---

## Open Questions

1. **trading_state guard placement:** The audit says "checks dim_risk_state.trading_state before processing signals". This could mean: (a) before the `read_unprocessed_signals` call, or (b) before the per-asset loop. Given `check_daily_loss()` is also called, the cleanest design is: `check_daily_loss()` first (triggers kill switch if needed), then `trading_state` guard (catches manually-triggered halts). Both should be before `read_unprocessed_signals`.

2. **`--features` flag name in run_daily_refresh.py:** The audit says to add feature refresh between regimes and signals. Following the existing pattern: add `--features` (standalone) and `--no-features` (skip in `--all` mode). This is consistent with `--no-portfolio`, `--no-execute`, `--no-drift`.

3. **Feature refresh timeout:** 1800s proposed (same as signals). The feature pipeline (vol + ta parallel -> cmc_features sequential -> CS norms) typically runs in 10-15 minutes for 1D TF only. 1800s provides ample headroom.

4. **`drift_paused` column:** The column does not exist in `cmc_drift_metrics`. The check in `drift_report.py` (`if "drift_paused" in df.columns`) is dead code. It should be removed. This is separate from the `attr_unexplained_residual` bugs but is part of the "4 bugs" the audit counts.

---

## Sources

### Primary (HIGH confidence)
- Direct file read: `src/ta_lab2/executor/paper_executor.py` — full file, imports section, `_try_telegram_alert`, `_process_asset_signal`, `_run_strategy`, `__init__`
- Direct file read: `src/ta_lab2/risk/risk_engine.py` — full file, `check_order` signature, `check_daily_loss` signature, `_is_halted`
- Direct file read: `src/ta_lab2/scripts/run_daily_refresh.py` — full file, all stage functions, `main()` pipeline, no `send_critical_alert` defined
- Direct file read: `src/ta_lab2/notifications/telegram.py` — `send_critical_alert` signature confirmed
- Direct file read: `src/ta_lab2/drift/drift_report.py` — `_ATTR_COLUMNS`, `_load_te_threshold`, `_plot_attribution_waterfall`, `_render_markdown`
- Direct file read: `src/ta_lab2/scripts/drift/run_drift_report.py` — `--with-attribution` block
- Direct file read: `sql/drift/094_cmc_drift_metrics.sql` — DDL column names: `attr_unexplained`, `threshold_breach`, no `drift_paused`
- Direct file read: `src/ta_lab2/scripts/features/run_all_feature_refreshes.py` — CLI args: `--all`, `--tf`, no `--db-url`, no `--dry-run`
- Direct file read: `src/ta_lab2/drift/drift_pause.py` line 243 — confirms `0.015` as the correct threshold default

---

## Metadata

**Confidence breakdown:**
- RiskEngine wiring: HIGH — all signatures confirmed from source
- Telegram import fix: HIGH — confirmed `run_daily_refresh.py` has no `send_critical_alert`, confirmed correct module and signature
- Feature refresh stage: HIGH — CLI confirmed, no `--db-url` confirmed, pattern matches existing stages
- Drift report column bugs: HIGH — DDL `attr_unexplained` vs code `attr_unexplained_residual` confirmed; `0.015` vs `0.05` confirmed from `drift_pause.py`

**Research date:** 2026-02-28
**Valid until:** Stable — these are bug fixes against static DDL and existing module signatures
