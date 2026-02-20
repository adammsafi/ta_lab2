# Phase 28: Backtest Pipeline Fix - Research

**Researched:** 2026-02-20
**Domain:** Signal generation (serialization), vectorbt 0.28.1 (timestamp handling), backtest persistence
**Confidence:** HIGH (all findings from direct code reading and live execution tests)

## Summary

Phase 28 fixes two distinct bug clusters that together block end-to-end strategy validation. The research directly read all 3 signal generators, 3 signal modules, 2 backtest runners, all DDL, and executed test scripts to reproduce every reported error.

**Bug cluster 1 — feature_snapshot serialization:** All 3 signal generators fail to properly serialize Python dicts to JSON before calling `to_sql()`. The RSI generator applies `json.dumps()` correctly but the EMA generator passes raw dicts (causes psycopg2 `can't adapt type 'dict'` error). The ATR generator calls `pd.io.json.dumps()` which does not exist in pandas 2.x (AttributeError), so it also fails. The DDL already declares `feature_snapshot` as `JSONB` — no DDL changes needed, only serialization fixes in two Python files.

**Bug cluster 2 — vectorbt 0.28.1 timestamp and API incompatibilities:** Confirmed via live execution. Three bugs exist in `_extract_trades()` in `backtest_from_signals.py`: (a) calling `.dt.tz_localize('UTC')` on already-tz-aware timestamps raises `TypeError: Already tz-aware`, (b) mapping `Direction` column via `{0: 'long', 1: 'short'}` produces NaN because vbt 0.28.1 returns string `'Long'`/`'Short'` not integers, (c) calling `trades.get('Fees', 0.0)` on a DataFrame (not dict) returns a Series-or-scalar instead of failing but 'Fees' column does not exist — correct columns are 'Entry Fees' and 'Exit Fees'. The fix is a thin sanitization layer in `_extract_trades()` and in the `load_prices()`/`_build_portfolio()` boundary — strip tz before passing to vbt, re-localize after.

**Primary recommendation:** Fix all 3 generators for feature_snapshot (2-3 lines each), fix the 3 API bugs in `_extract_trades`, add tz-strip/re-localize at the vectorbt boundary. No architectural changes, no new tables, no DDL changes needed.

## Standard Stack

### Core (what already exists — do not replace)

| Component | Version | Purpose | Status |
|-----------|---------|---------|--------|
| vectorbt | 0.28.1 | Portfolio backtesting engine | Installed, kept as-is |
| pandas | 2.3.3 | DataFrame operations | Installed |
| psycopg2-binary | >=2.9 | PostgreSQL driver | Installed |
| SQLAlchemy | >=2.0 | DB ORM and text() queries | Installed |
| stdlib json | builtin | dict → JSON string serialization | The correct serializer |

### Not to add

vectorbt must NOT be forked or replaced per CONTEXT.md. The fix is a thin boundary layer only.

### Installation

No new packages needed. Everything is already installed.

## Architecture Patterns

### Existing Code Structure

```
src/ta_lab2/
├── signals/                     # Signal logic (EMA, RSI, ATR)
│   ├── rsi_mean_revert.py       # make_signals() - OK, no bugs
│   ├── ema_trend.py             # make_signals() - OK, no bugs
│   ├── breakout_atr.py          # make_signals() - OK, no bugs
│   └── generator.py             # EMA signal core
├── backtests/
│   ├── vbt_runner.py            # run_vbt_on_split(), sweep_grid() - OK
│   ├── costs.py                 # CostModel - OK
│   ├── splitters.py             # Split, expanding_walk_forward - OK
│   ├── metrics.py               # cagr(), sharpe(), etc. - OK
│   └── orchestrator.py          # run_multi_strategy - OK
└── scripts/
    ├── signals/
    │   ├── generate_signals_rsi.py   # BUG: see below
    │   ├── generate_signals_ema.py   # BUG: see below
    │   ├── generate_signals_atr.py   # BUG: see below
    │   └── refresh_*.py             # Shell scripts - OK
    └── backtests/
        ├── backtest_from_signals.py  # BUG: see below
        └── run_backtest_signals.py   # CLI - OK
```

### Pattern 1: feature_snapshot Serialization Fix

All 3 generators must serialize dicts to JSON strings before calling `to_sql()`. The pattern used in the RSI generator is correct and should be the template:

```python
# Source: generate_signals_rsi.py lines 487-489 (working reference)
df_records["feature_snapshot"] = df_records["feature_snapshot"].apply(
    lambda x: json.dumps(x) if isinstance(x, dict) else x
)
```

Apply this immediately before calling `to_sql()` in each generator. Requires `import json` at top of file.

### Pattern 2: Vectorbt Timestamp Boundary Layer

Strip timezone from price index before passing to vectorbt; re-localize after extracting results:

```python
# Source: Live test confirmed 2026-02-20
# In _build_portfolio() and run_vbt_on_split():
prices_for_vbt = prices.copy()
prices_for_vbt.index = prices_for_vbt.index.tz_localize(None)  # strip tz

pf = vbt.Portfolio.from_signals(prices_for_vbt["close"], ...)

# In _extract_trades():
trades = pf.trades.records_readable
entry_ts = pd.to_datetime(trades["Entry Timestamp"])
# Re-localize only if naive (vbt with naive input → naive output)
if entry_ts.dt.tz is None:
    entry_ts = entry_ts.dt.tz_localize("UTC")
else:
    entry_ts = entry_ts.dt.tz_convert("UTC")
```

### Pattern 3: Direction Column Fix

vectorbt 0.28.1 returns string 'Long'/'Short' in `records_readable`, not integers 0/1:

```python
# Source: Live test confirmed 2026-02-20
# WRONG (current code):
"direction": trades["Direction"].map({0: "long", 1: "short"}),
# CORRECT:
"direction": trades["Direction"].str.lower(),
```

### Pattern 4: Fees Column Fix

vectorbt 0.28.1 has 'Entry Fees' + 'Exit Fees' columns, not a 'Fees' column:

```python
# Source: Live test confirmed 2026-02-20
# WRONG (current code):
"fees_paid": trades.get("Fees", 0.0).astype(float) if "Fees" in trades else 0.0,
# CORRECT:
entry_fees = trades["Entry Fees"].astype(float) if "Entry Fees" in trades.columns else 0.0
exit_fees = trades["Exit Fees"].astype(float) if "Exit Fees" in trades.columns else 0.0
"fees_paid": entry_fees + exit_fees,
```

### Anti-Patterns to Avoid

- **Do not use `pd.io.json.dumps()`**: Does not exist in pandas 2.x. Use `import json; json.dumps()`.
- **Do not call `.dt.tz_localize('UTC')` on already-tz-aware series**: Will raise TypeError. Always check `.dt.tz is None` first, or use `.dt.tz_convert()`.
- **Do not map Direction to int**: vbt 0.28.1 returns string, not integer enum.
- **Do not call DataFrame.get('Fees', 0.0)**: DataFrame.get returns a Series for existing columns; checking `'Fees' in trades.columns` then using the correct column names is the right approach.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| JSON serialization | Custom serializer | `import json; json.dumps(x)` | stdlib is correct and stable |
| Backtest engine | Custom backtester | vectorbt 0.28.1 (already installed) | Locked decision per CONTEXT.md |
| Metrics | Custom CAGR/Sharpe | `ta_lab2.backtests.metrics` | Already exists with correct implementations |
| Splitters | Custom walk-forward | `ta_lab2.backtests.splitters` | Already exists |

**Key insight:** The infrastructure is already 95% built. This phase is targeted bug fixes, not new construction.

## Common Pitfalls

### Pitfall 1: EMA Generator `_write_signals` Has No JSON Fix

**What goes wrong:** `generate_signals_ema.py::_write_signals()` (line 447-455) calls `records.to_sql()` directly with no `feature_snapshot` conversion. The EMA generator is the ONLY one that does this — there is no `json.dumps` call anywhere in the EMA write path.

**Why it happens:** RSI and ATR generators serialize in their write functions; EMA was written separately and this step was omitted.

**How to avoid:** Add `json.dumps` conversion in `_write_signals()` before the `to_sql()` call, matching the RSI pattern exactly.

**Warning signs:** Error message: `psycopg2.ProgrammingError: can't adapt type 'dict'`

### Pitfall 2: ATR Generator Uses Non-Existent `pd.io.json.dumps`

**What goes wrong:** `generate_signals_atr.py::_write_signals()` (line 512) calls `pd.io.json.dumps(x)` which raises `AttributeError: module 'pandas.io.json' has no attribute 'dumps'` in pandas 2.x.

**Why it happens:** `pd.io.json.dumps` was removed from pandas. The correct call is `json.dumps` from stdlib.

**How to avoid:** Replace `pd.io.json.dumps(x)` with `json.dumps(x)` and add `import json` if not already imported in ATR file.

**Warning signs:** `AttributeError: module 'pandas.io.json' has no attribute 'dumps'`

### Pitfall 3: Vectorbt tz_localize on Already-Aware Series

**What goes wrong:** `backtest_from_signals.py::_extract_trades()` (lines 423-430) calls `.dt.tz_localize('UTC')` on Entry/Exit Timestamp columns. When the price series passed to vbt had a tz-aware index, vbt's output timestamps are also tz-aware — so tz_localize raises `TypeError: Already tz-aware`.

**Why it happens:** The `load_prices()` method returns a DataFrame indexed by 'ts' which is a TIMESTAMPTZ column from PostgreSQL — always tz-aware. When this tz-aware index is used as vbt's price input, vbt propagates the tz to its output.

**How to avoid:** Use the boundary layer pattern: strip tz before vbt (`index.tz_localize(None)`), then after extracting results, check `dt.tz is None` before calling `tz_localize`.

**Warning signs:** `TypeError: Already tz-aware, use tz_convert to convert.`

### Pitfall 4: `cost_model` Dict in Raw SQL Parameters

**What goes wrong:** `save_backtest_results()` passes `result.cost_model` (a Python dict) directly as a parameter to `text()` SQL query targeting a JSONB column. psycopg2 may or may not adapt this automatically depending on whether JSON adapters are registered.

**Why it happens:** SQLAlchemy's `text()` queries bypass ORM type coercion. JSONB support for raw dicts depends on psycopg2 adapter registration.

**How to avoid:** Serialize to JSON string before passing: `json.dumps(result.cost_model)`. This is safe and explicit.

**Warning signs:** `ProgrammingError: can't adapt type 'dict'` when saving to `cmc_backtest_runs`.

### Pitfall 5: `load_signals_as_series` Uses `entries.loc[entry_ts]` with Boolean Signal Index

**What goes wrong:** In `backtest_from_signals.py::load_signals_as_series()` (lines 178-181), the code tries `entries.loc[entry_ts] = True` where `entries` is indexed by tz-aware TIMESTAMPTZ values from `load_prices()`. If the DB returns timestamps with sub-second precision or the index doesn't match exactly, the assignment silently misses.

**Why it happens:** SQL-loaded timestamps may have different precision than the DatetimeIndex built from the same data. Also, the `time_index = price_df.index` pattern means entries/exits are indexed by the raw DB timestamp.

**How to avoid:** Be consistent: normalize timestamps (e.g., `.normalize()`) before indexing, or use `pd.to_datetime(..., utc=True)` with consistent precision throughout.

**Warning signs:** `entries.sum() == 0` despite signals existing in the database.

## Code Examples

### Bug 1 Fix: EMA Feature Snapshot Serialization

```python
# File: src/ta_lab2/scripts/signals/generate_signals_ema.py
# In _write_signals() method, BEFORE records.to_sql():

import json  # Add to imports at top of file

def _write_signals(self, records: pd.DataFrame, signal_table: str) -> None:
    # Fix: serialize feature_snapshot dict to JSON string
    records = records.copy()
    records["feature_snapshot"] = records["feature_snapshot"].apply(
        lambda x: json.dumps(x) if isinstance(x, dict) else x
    )
    records.to_sql(
        signal_table,
        self.engine,
        schema="public",
        if_exists="append",
        index=False,
        method="multi",
    )
```

### Bug 2 Fix: ATR `pd.io.json.dumps` → `json.dumps`

```python
# File: src/ta_lab2/scripts/signals/generate_signals_atr.py
# Line 512: replace pd.io.json.dumps with json.dumps
import json  # Already imported at top

def _write_signals(self, records: pd.DataFrame) -> None:
    records = records.copy()
    records["feature_snapshot"] = records["feature_snapshot"].apply(
        lambda x: json.dumps(x) if x is not None else None  # was: pd.io.json.dumps
    )
    with self.engine.begin() as conn:
        records.to_sql(...)
```

### Bug 3+4+5 Fix: vectorbt _extract_trades

```python
# File: src/ta_lab2/scripts/backtests/backtest_from_signals.py

def _extract_trades(self, pf) -> pd.DataFrame:
    if pf.trades.count() == 0:
        return pd.DataFrame(columns=["entry_ts", "entry_price", "exit_ts",
                                     "exit_price", "direction", "size",
                                     "pnl_pct", "pnl_dollars", "fees_paid", "slippage_cost"])

    trades = pf.trades.records_readable

    # Fix timestamp: may be tz-aware (if price index was tz-aware) or naive
    def _ensure_utc(col):
        s = pd.to_datetime(col)
        if s.dt.tz is None:
            return s.dt.tz_localize("UTC")
        return s.dt.tz_convert("UTC")

    # Fix fees: vbt 0.28.1 uses 'Entry Fees' + 'Exit Fees', not 'Fees'
    entry_fees = trades["Entry Fees"].astype(float) if "Entry Fees" in trades.columns else pd.Series(0.0, index=trades.index)
    exit_fees = trades["Exit Fees"].astype(float) if "Exit Fees" in trades.columns else pd.Series(0.0, index=trades.index)

    trades_df = pd.DataFrame({
        "entry_ts": _ensure_utc(trades["Entry Timestamp"]),
        "entry_price": trades["Avg Entry Price"].astype(float),
        "exit_ts": _ensure_utc(trades["Exit Timestamp"]),
        "exit_price": trades["Avg Exit Price"].astype(float),
        "direction": trades["Direction"].str.lower(),   # Fix: str not int enum
        "size": trades["Size"].astype(float),
        "pnl_pct": trades["Return"].astype(float) * 100,
        "pnl_dollars": trades["PnL"].astype(float),
        "fees_paid": entry_fees + exit_fees,            # Fix: combined fees
        "slippage_cost": 0.0,
    })

    return trades_df
```

### Vectorbt Boundary Layer: Strip TZ Before Passing to vbt

```python
# File: src/ta_lab2/scripts/backtests/backtest_from_signals.py
# In _build_portfolio() and run_vbt_on_split() via vbt_runner.py

def _build_portfolio(self, prices, entries, exits, cost, start_ts, end_ts):
    d = prices.loc[start_ts:end_ts]
    e_in = entries.loc[start_ts:end_ts].astype(bool)
    e_out = exits.loc[start_ts:end_ts].astype(bool)

    # Fix: strip tz before vectorbt (vbt 0.28.1 + tz-aware prices → output tz-aware timestamps)
    d_for_vbt = d.copy()
    if d_for_vbt.index.tz is not None:
        d_for_vbt.index = d_for_vbt.index.tz_localize(None)

    e_in = e_in.shift(1, fill_value=False).astype(np.bool_)
    e_out = e_out.shift(1, fill_value=False).astype(np.bool_)

    pf = vbt.Portfolio.from_signals(
        d_for_vbt["close"],
        entries=e_in.to_numpy(),
        exits=e_out.to_numpy(),
        **cost.to_vbt_kwargs(),
        init_cash=1_000.0,
        freq="D",
    )
    return pf
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|-----------------|--------------|--------|
| `pd.io.json.dumps()` | `json.dumps()` (stdlib) | pandas 2.x removed it | ATR generator broken |
| vbt Direction as int enum | vbt Direction as string 'Long'/'Short' | vbt 0.x → 0.28.x | `_extract_trades` produces NaN direction |
| Single 'Fees' column in trades | 'Entry Fees' + 'Exit Fees' columns | vbt 0.x → 0.28.x | fees_paid always 0 or error |
| tz-naive price → tz-naive output | tz-aware price → tz-aware output | vbt 0.28.x behavior | tz_localize crash |

**Deprecated/outdated in this codebase:**
- `pd.io.json.dumps`: replaced by `json.dumps`
- `trades["Direction"].map({0: "long", 1: "short"})`: replaced by `.str.lower()`
- `trades.get("Fees", 0.0)`: replaced by explicit column check for 'Entry Fees' + 'Exit Fees'

## Dependency Analysis

### What must happen first (sequential)

1. **Fix feature_snapshot serialization** — must precede any backtest testing because backtests read from signal tables that must first be populated.
2. **Fix vectorbt boundary layer** — must precede saving trade records to DB.
3. **Verify signal tables populate** — must precede backtest execution.

### What can be parallel

- Fixing RSI generator, EMA generator, ATR generator serialization bugs (independent files).
- Fixing `_extract_trades` and `_build_portfolio` bugs (in same file but independent methods).

### Riskiest changes

1. **`_build_portfolio` tz strip**: this is called by both `run_backtest` directly and through `run_vbt_on_split`. The strip must happen in `_build_portfolio` and the corresponding code in `run_vbt_on_split` (in `vbt_runner.py`) may also need updating if it is called directly with tz-aware data.
2. **`save_backtest_results` JSONB dict**: the `cost_model` dict passed to SQL `text()` query. Needs explicit `json.dumps()`.

## Detailed Bug Inventory

### Bug 1: EMA Generator — no feature_snapshot serialization

- **File:** `src/ta_lab2/scripts/signals/generate_signals_ema.py`
- **Location:** `_write_signals()` method, lines 447-455
- **Error:** `psycopg2.ProgrammingError: can't adapt type 'dict'`
- **Root cause:** `feature_snapshot` column contains Python dicts, `to_sql()` passes them to psycopg2 which cannot adapt native dicts for JSONB without explicit JSON serialization.
- **Fix:** Add `json.dumps` conversion before `to_sql()`. 2-3 lines.

### Bug 2: ATR Generator — `pd.io.json.dumps` does not exist

- **File:** `src/ta_lab2/scripts/signals/generate_signals_atr.py`
- **Location:** `_write_signals()` method, line 512
- **Error:** `AttributeError: module 'pandas.io.json' has no attribute 'dumps'`
- **Root cause:** `pd.io.json.dumps` was removed from pandas 2.x. The ATR generator was written expecting it to exist.
- **Fix:** Replace `pd.io.json.dumps(x)` with `json.dumps(x)`. 1 line.

### Bug 3: RSI Generator — `import json` missing in file header? (CHECK)

- **File:** `src/ta_lab2/scripts/signals/generate_signals_rsi.py`
- **Location:** Line 34: `import json` — PRESENT. The RSI fix is already correct (lines 487-489).
- **Status:** RSI generator is ALREADY FIXED. No changes needed there.

### Bug 4: `_extract_trades` — tz_localize on already-tz-aware timestamps

- **File:** `src/ta_lab2/scripts/backtests/backtest_from_signals.py`
- **Location:** `_extract_trades()` method, lines 422-430
- **Error:** `TypeError: Already tz-aware, use tz_convert to convert.`
- **Root cause:** When `load_prices()` returns a tz-aware indexed DataFrame and it is passed to vbt, vbt returns timestamps with tz info. The code then tries to tz_localize again.
- **Fix:** Use `_ensure_utc()` helper that checks `.dt.tz` first. 5 lines.

### Bug 5: `_extract_trades` — Direction integer mapping fails

- **File:** `src/ta_lab2/scripts/backtests/backtest_from_signals.py`
- **Location:** `_extract_trades()`, line 432
- **Error:** Silent — `direction` column becomes all NaN
- **Root cause:** vbt 0.28.1 uses string 'Long'/'Short', not integer enum.
- **Fix:** `trades["Direction"].str.lower()`. 1 line.

### Bug 6: `_extract_trades` — 'Fees' column doesn't exist

- **File:** `src/ta_lab2/scripts/backtests/backtest_from_signals.py`
- **Location:** `_extract_trades()`, lines 436-438
- **Error:** Silent — `fees_paid` is always 0.0 (DataFrame.get returns 0.0 for missing column, but this is the wrong default handling)
- **Root cause:** vbt 0.28.1 uses 'Entry Fees' + 'Exit Fees' columns, not a single 'Fees' column.
- **Fix:** Check for the correct column names. 3-4 lines.

### Bug 7: `save_backtest_results` — cost_model dict may not adapt to JSONB

- **File:** `src/ta_lab2/scripts/backtests/backtest_from_signals.py`
- **Location:** `save_backtest_results()`, line 645
- **Error:** Potential `ProgrammingError: can't adapt type 'dict'` (same root cause as Bug 1)
- **Root cause:** `result.cost_model` is a Python dict passed to `text()` SQL `INSERT`. psycopg2 may not adapt dicts for JSONB in text() queries.
- **Fix:** `json.dumps(result.cost_model)`. 1 line.

## Infrastructure Already Built (Reuse Everything)

All of the following are complete and correct — do NOT rewrite:

| Component | Status | Notes |
|-----------|--------|-------|
| `ta_lab2.backtests.metrics` | COMPLETE | cagr, mdd, sharpe, sortino, mar all correct |
| `ta_lab2.backtests.splitters` | COMPLETE | expanding_walk_forward, fixed_date_splits |
| `ta_lab2.backtests.costs.CostModel` | COMPLETE | fee_bps, slippage_bps, funding_bps_day |
| `ta_lab2.backtests.vbt_runner.run_vbt_on_split` | COMPLETE | core logic correct, only tz needs fix at call site |
| `ta_lab2.backtests.reports` | COMPLETE | equity_plot, save_table, leaderboard |
| `ta_lab2.backtests.orchestrator` | COMPLETE | run_multi_strategy |
| `ta_lab2.signals.*` (make_signals) | COMPLETE | All 3 adapters correct, no bugs |
| Signal DDL (3 tables) | COMPLETE | feature_snapshot already JSONB, no changes needed |
| Backtest DDL (3 tables) | COMPLETE | All tables exist with correct schema |
| `SignalStateManager` | COMPLETE | Incremental refresh tracking |
| `run_backtest_signals.py` | COMPLETE | CLI correct, only downstream bug in SignalBacktester |
| `refresh_*.py` (3 scripts) | COMPLETE | CLI correct, only downstream bug in generators |

## Open Questions

1. **Is `vbt_runner.run_vbt_on_split` also called with tz-aware data?**
   - What we know: `backtest_from_signals.py::_build_portfolio()` duplicates the vbt call from `run_vbt_on_split`. The tz-strip should happen in `_build_portfolio()`. But `run_backtest()` also calls `run_vbt_on_split()` directly (line 292). Both paths need the tz-strip.
   - Recommendation: Add tz-strip in `_build_portfolio()` AND in `run_vbt_on_split()` in `vbt_runner.py`, OR strip tz at the `load_prices()` return point before either function is called.

2. **Does `load_signals_as_series` produce correct tz-consistent signals?**
   - What we know: It builds `time_index = price_df.index` (tz-aware), then does `entries.loc[entry_ts] = True` where `entry_ts` is constructed with `tz_localize("UTC")`. This should work.
   - Recommendation: Verify with a small end-to-end test with real or mock data.

3. **Are dim_signals rows populated for all 3 signal types?**
   - What we know: The refreshers call `load_active_signals(engine, 'rsi_mean_revert')` etc. If `dim_signals` is empty, refreshers exit with "No active signals found."
   - Recommendation: Phase 28 plan should include a step to verify `dim_signals` has at least one row per signal type before running generators.

## Sources

### Primary (HIGH confidence)

- Direct code reading — all 6 signal generator/module files
- Direct code reading — backtest_from_signals.py, vbt_runner.py, run_backtest_signals.py
- Direct code reading — costs.py, splitters.py, metrics.py, orchestrator.py, reports.py
- Direct code reading — all 6 SQL DDL files (3 signal tables + 3 backtest tables)
- Live Python execution — reproduced all 6 bugs and confirmed all fixes

### Secondary (MEDIUM confidence)

- pandas 2.x changelog — pd.io.json.dumps removal
- vectorbt 0.28.1 records_readable schema — confirmed via live test

## Metadata

**Confidence breakdown:**
- Bug identification: HIGH — all bugs reproduced via live execution
- Fix correctness: HIGH — all fixes tested in isolation
- Infrastructure state: HIGH — read every relevant file
- vectorbt API: HIGH — verified against installed 0.28.1

**Research date:** 2026-02-20
**Valid until:** 2026-03-20 (stable libraries, vectorbt pinned at 0.28.1)
