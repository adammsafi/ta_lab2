# Phase 96: Executor Activation - Research

**Researched:** 2026-03-30
**Domain:** Paper executor activation, signal wiring, BL integration, parity tracking, PnL attribution
**Confidence:** HIGH (all findings from direct codebase inspection)

---

## Summary

Phase 96 activates the paper executor for all 7 signal generators and wires BL output weights into position sizing. The codebase has substantial infrastructure already built (executor, signal generators, BL) but four blocking gaps must be closed before the executor can run with all 7 strategies.

The most critical finding is that `SIGNAL_TABLE_MAP` in `signal_reader.py` and the `chk_exec_config_signal_type` CHECK constraint in `dim_executor_config` both hard-code only the original 3 signal types (`ema_crossover`, `rsi_mean_revert`, `atr_breakout`). Adding 4 more strategies requires: new signal tables, new generator scripts, a new migration to widen both constraints, and updates to `run_all_signal_refreshes.py`. The BL integration is already partially wired in `refresh_portfolio_allocations.py` but the executor does not read from `portfolio_allocations` at all — it uses `position_fraction` from `dim_executor_config` exclusively.

**Primary recommendation:** Close the signal-infrastructure gap first (plan 96-01), then add BL-weight reading to the executor (plan 96-02 or 96-03), and handle parity/attribution as new tables/scripts (plan 96-03/04).

---

## Standard Stack

All work is in-project. No new libraries needed.

### Core (existing)
| Component | File | Status |
|-----------|------|--------|
| Paper executor | `src/ta_lab2/executor/paper_executor.py` | Exists, works for 3 signal types |
| Signal reader | `src/ta_lab2/executor/signal_reader.py` | Exists, SIGNAL_TABLE_MAP is 3-entry |
| Position sizer | `src/ta_lab2/executor/position_sizer.py` | Exists, 4 sizing modes (no BL mode) |
| Parity checker | `src/ta_lab2/executor/parity_checker.py` | Exists, backtest replay only |
| Signal refresh | `src/ta_lab2/scripts/signals/run_all_signal_refreshes.py` | Exists, 3 signal types hardcoded |
| Seed script | `src/ta_lab2/scripts/executor/seed_executor_config.py` | Exists, idempotent YAML-based |
| BL builder | `src/ta_lab2/portfolio/black_litterman.py` | Exists, already per-asset IC-IR |
| Portfolio refresh | `src/ta_lab2/scripts/portfolio/refresh_portfolio_allocations.py` | Exists, writes `portfolio_allocations` |

### What Does Not Yet Exist
| Gap | Needs Creating |
|-----|---------------|
| `signals_macd_crossover` table | New DDL + Alembic migration |
| `signals_ama_momentum` table | New DDL + Alembic migration |
| `signals_ama_mean_reversion` table | New DDL + Alembic migration |
| `signals_ama_regime_conditional` table | New DDL + Alembic migration |
| `generate_signals_macd.py` | New script, follow EMA/RSI/ATR pattern |
| `generate_signals_ama.py` | New script wrapping 3 AMA generators |
| `refresh_signals_macd_crossover.py` | New script (or expand run_all) |
| `refresh_signals_ama_*.py` | New scripts (or expand run_all) |
| `strategy_parity` table | New DDL + migration |
| `pnl_attribution` table | New DDL + migration |
| BL-weight sizing in executor | New `sizing_mode='bl_weight'` or runtime lookup |
| Parity report script | New CLI |
| PnL attribution report script | New CLI |

---

## Architecture Patterns

### Signal Infrastructure Pattern (replicate for each new type)
The 3 existing signal types follow a uniform pattern. Each new type needs:

1. **Signal table** — same schema as `signals_ema_crossover`:
   - PK: `(id, ts, signal_id)`
   - Columns: `direction`, `position_state`, `entry_price`, `entry_ts`, `exit_price`, `exit_ts`, `pnl_pct`, `feature_snapshot JSONB`, `signal_version`, `feature_version_hash`, `params_hash`, `created_at`
   - Extra column: `executor_processed_at TIMESTAMPTZ NULL` (the replay guard — added by migration 225bf8646f03 to the 3 existing tables; must also be added to new tables)
   - FK: `signal_id REFERENCES dim_signals(signal_id)`

2. **Generator class** — dataclass with `engine`, `state_manager`, `signal_version`, `venue_id`. Implements `generate_for_ids(ids, signal_config, full_refresh, regime_enabled)`.

3. **Entry in `SIGNAL_TABLE_MAP`** in `signal_reader.py`:
   ```python
   SIGNAL_TABLE_MAP: dict[str, str] = {
       "ema_crossover": "signals_ema_crossover",
       "rsi_mean_revert": "signals_rsi_mean_revert",
       "atr_breakout": "signals_atr_breakout",
       "macd_crossover": "signals_macd_crossover",      # ADD
       "ama_momentum": "signals_ama_momentum",          # ADD
       "ama_mean_reversion": "signals_ama_mean_reversion",  # ADD
       "ama_regime_conditional": "signals_ama_regime_conditional",  # ADD
   }
   ```

4. **Entry in `run_all_signal_refreshes.py`** — add to the `generators` dict and `signal_types` list in `run_parallel_refresh`. Context: the AMA generators depend on fresh AMA values, so they should run in a second batch AFTER the first three complete (serial dependency on AMA refresh stage).

5. **Alembic migration** — widening two CHECK constraints and creating 4 new tables.

### BL Weight Integration Pattern

Current situation: the executor reads `position_fraction` from `dim_executor_config` and uses `PositionSizer.compute_target_position()` with `sizing_mode` from that same config. The `portfolio_allocations` table is written by `refresh_portfolio_allocations.py` but is never read by the executor.

Two options for integrating BL weights:

**Option A: New `sizing_mode='bl_weight'`** (more elegant, requires migration)
- Add `'bl_weight'` to the `chk_exec_config_sizing_mode` CHECK constraint.
- In `PositionSizer.compute_target_position()`, when `sizing_mode='bl_weight'`, look up the BL weight from `portfolio_allocations` (latest row for this asset_id and `optimizer='bl'`).
- Scale: `target_qty = portfolio_value * bl_weight / current_price`.
- Fallback: if no BL row exists or BL weight is 0, fall through to `fixed_fraction`.

**Option B: Inline lookup in `_process_asset_signal()`** (no migration needed)
- In `paper_executor.py::_process_asset_signal()`, before calling `compute_target_position()`, query `portfolio_allocations` for the most recent BL weight for this asset.
- Pass it as `signal_confidence` (already accepted, already scales fraction).
- Caveat: this repurposes `signal_confidence` for a different semantic purpose.

**Recommendation: Option A** — explicit `sizing_mode='bl_weight'` is cleaner and queryable. Update `chk_exec_config_sizing_mode` in the same migration that widens `chk_exec_config_signal_type`.

The `portfolio_allocations` query pattern for executor use:
```sql
SELECT DISTINCT ON (asset_id)
    asset_id, final_weight, weight
FROM portfolio_allocations
WHERE optimizer = 'bl'
ORDER BY asset_id, ts DESC
```
Use `final_weight` if not null, else `weight`. A `final_weight` of 0.0 means BL de-selected that asset — treat as zero target.

### Signal Batch Split (Two-Batch Architecture)

The CONTEXT.md decision is:
- Batch 1: `ema_crossover`, `rsi_mean_revert`, `atr_breakout`, `macd_crossover` — no AMA dependency, run in parallel.
- Batch 2: `ama_momentum`, `ama_mean_reversion`, `ama_regime_conditional` — require fresh AMA values; run after Batch 1 completes.

In `run_all_signal_refreshes.py`, implement this as two sequential `run_parallel_refresh()` calls (within the same script, Batch 2 runs only after Batch 1 finishes successfully). The two-batch design also means the `run_daily_refresh.py` signal stage comment (line 984) needs updating to reflect 7 types rather than 3.

### Watermark Seed Pattern

On first activation with historical signals present, the `last_processed_signal_ts` in `dim_executor_config` is NULL, meaning the executor will attempt to process ALL historical signals. The context decision: watermark should be seeded to `MAX(signal_ts)` per strategy table before the first live run.

This is a one-time initialization step. Implementation: add a `--seed-watermarks` flag to `seed_executor_config.py` (or create a standalone `seed_executor_watermarks.py`) that runs:
```sql
UPDATE dim_executor_config
SET last_processed_signal_ts = (
    SELECT MAX(ts) FROM <signal_table>
    WHERE signal_id = dim_executor_config.signal_id
)
WHERE is_active = TRUE
AND last_processed_signal_ts IS NULL
```
This must run after seeding configs but before the first live executor run.

### Strategy Parity Table Schema

New table `strategy_parity`:
```sql
CREATE TABLE public.strategy_parity (
    parity_id   SERIAL          PRIMARY KEY,
    computed_at TIMESTAMPTZ     NOT NULL DEFAULT now(),
    strategy    TEXT            NOT NULL,  -- config_name from dim_executor_config
    window_days INTEGER         NOT NULL,  -- evaluation window (e.g. 7, 30, 90)
    live_sharpe_fill    NUMERIC,           -- fill-to-fill annualized Sharpe
    live_sharpe_mtm     NUMERIC,           -- mark-to-market daily Sharpe
    bt_sharpe           NUMERIC,           -- backtest Sharpe (from backtest_runs)
    ratio_fill          NUMERIC,           -- live_sharpe_fill / bt_sharpe
    ratio_mtm           NUMERIC,           -- live_sharpe_mtm / bt_sharpe
    n_fills             INTEGER,           -- fills in window
    n_mtm_days          INTEGER            -- mark-to-market days in window
);
CREATE INDEX idx_strategy_parity_strategy_ts
    ON strategy_parity (strategy, computed_at DESC);
```

### PnL Attribution Table Schema

New table `pnl_attribution`:
```sql
CREATE TABLE public.pnl_attribution (
    attr_id         SERIAL      PRIMARY KEY,
    computed_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    period_start    DATE        NOT NULL,
    period_end      DATE        NOT NULL,
    asset_class     TEXT        NOT NULL,  -- 'crypto', 'equity', 'perp', 'all'
    benchmark       TEXT        NOT NULL,  -- 'BTC', 'SPX', 'underlying', 'blended'
    total_pnl       NUMERIC,
    beta_pnl        NUMERIC,               -- market-beta component
    alpha_pnl       NUMERIC,               -- residual alpha (total - beta)
    beta            NUMERIC,               -- estimated beta to benchmark
    sharpe_alpha    NUMERIC,               -- Sharpe of alpha returns
    n_positions     INTEGER
);
CREATE INDEX idx_pnl_attr_period
    ON pnl_attribution (period_start, period_end, asset_class);
```

### Multi-Asset Beta Computation

Per-asset-class benchmarks (from CONTEXT.md decisions):
- Crypto positions (venue_id = 1 CMC_AGG, venue_id = 2 HYPERLIQUID): benchmark = BTC (id=1)
- Equity indices: benchmark = SPX (FRED series or TVC)
- Perps: benchmark = underlying spot price

Implementation approach:
1. Query `fills` + `orders` for the period, joined to `cmc_da_info` for asset_class metadata (or use a hardcoded mapping: all CMC + HL assets default to `crypto` class until equity data arrives).
2. For each asset_class: load daily returns for all positions + benchmark returns.
3. Beta = `cov(position_returns, benchmark_returns) / var(benchmark_returns)` using numpy/pandas.
4. `alpha_pnl = total_pnl - beta * benchmark_pnl_over_same_period`.
5. Store in `pnl_attribution` per asset_class per period.

### Fill-to-Fill vs Mark-to-Market Sharpe

**Fill-to-fill Sharpe:**
- Source: `fills` table joined to `orders`.
- Return per round-trip: `(exit_fill_price - entry_fill_price) / entry_fill_price`.
- Annualize: use actual hold time in days, assume 252 trading days.
- `sharpe = mean(returns) / std(returns) * sqrt(252 / mean_hold_days)`.
- Useful for execution quality (affected by slippage simulation).

**Mark-to-market daily Sharpe:**
- Source: `positions` + `price_bars_multi_tf_u` (1D close).
- For each day the position is open: `daily_pnl = (today_close - prev_close) / prev_close * qty * entry_price`.
- Sum across all open positions per day -> daily_portfolio_return.
- `sharpe = mean(daily_portfolio_returns) / std(daily_portfolio_returns) * sqrt(252)`.
- Useful for portfolio-level performance.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| IC-IR weighting | Custom weight calculator | `BLAllocationBuilder._per_asset_composite()` | Already handles missing assets, col-mean fallback, clipping |
| Beta estimation | Numpy one-liner | `numpy.cov` / `pandas.DataFrame.cov()` | Standard OLS beta is 2 lines |
| Sharpe calculation | Custom function | `numpy`: `mean/std * sqrt(252)` | No library needed, but reuse the pattern in `parity_checker.py` |
| Signal watermark | Custom dedup logic | Existing `executor_processed_at IS NULL` + watermark | Already handles idempotency |
| Constraint migration | Manual ALTER TABLE | Alembic migration | DROP + CREATE constraint pattern already used in codebase |

---

## Common Pitfalls

### Pitfall 1: `SIGNAL_TABLE_MAP` Validation Blocks New Signal Types
**What goes wrong:** `SignalReader._validate_table()` uses `_VALID_SIGNAL_TABLES = frozenset(SIGNAL_TABLE_MAP.values())` to reject unknown tables. Adding a new `dim_executor_config` row with `signal_type='macd_crossover'` will cause `_run_strategy()` to raise `ValueError("Unknown signal_type=...")` at runtime because `SIGNAL_TABLE_MAP.get('macd_crossover')` returns None before the table map is expanded.
**How to avoid:** Update `SIGNAL_TABLE_MAP` in `signal_reader.py` before seeding new configs.

### Pitfall 2: `chk_exec_config_signal_type` CHECK Constraint Rejects Inserts
**What goes wrong:** `dim_executor_config` has a database-level CHECK constraint that only allows `('ema_crossover', 'rsi_mean_revert', 'atr_breakout')`. Any attempt to seed MACD or AMA configs via `seed_executor_config.py` will raise a `psycopg2.errors.CheckViolation` before inserting.
**How to avoid:** Write an Alembic migration that DROPs `chk_exec_config_signal_type` and recreates it with all 7 types. Apply BEFORE running seed. The same migration must also add the 4 new signal tables with `executor_processed_at` column.

### Pitfall 3: Historical Signal Replay on First Run
**What goes wrong:** If `last_processed_signal_ts IS NULL` in `dim_executor_config` for any active strategy, the executor will process every historical signal in that strategy's table going back to 2020+. This generates thousands of spurious orders and fills on the first live run.
**How to avoid:** Run the watermark-seed step (UPDATE `dim_executor_config` SET `last_processed_signal_ts = MAX(ts)`) BEFORE the first live executor run, after configs are seeded.

### Pitfall 4: AMA Signal Generators Require Pre-Loaded AMA Columns
**What goes wrong:** `ama_composite.py` explicitly states: "All three functions READ pre-computed AMA columns from the DataFrame. They do NOT re-compute AMA values from price." The generator script for AMA signals must load data from `ama_multi_tf_u` (joining on `indicator` + `params_hash`) and merge it into the feature DataFrame before calling the signal functions.
**How to avoid:** In `generate_signals_ama.py`, load AMA data via the same pattern used in `refresh_portfolio_allocations.py::_load_signal_scores()` (DISTINCT ON + `a.d1 AS val` query on `ama_multi_tf_u`). AMA batch must run after the AMA refresh stage in the pipeline.

### Pitfall 5: `chk_exec_config_sizing_mode` Also Needs Updating for BL Mode
**What goes wrong:** If implementing `sizing_mode='bl_weight'`, the same migration needs to update the `chk_exec_config_sizing_mode` CHECK constraint (currently allows only `'fixed_fraction', 'regime_adjusted', 'signal_strength'`). Forgetting this causes inserts to fail for the new sizing mode.
**How to avoid:** Include all constraint changes in a single Phase 96 migration.

### Pitfall 6: `executor_run_log.status` CHECK Constraint Missing 'halted'
**What goes wrong:** The executor calls `_write_run_log(config, status="halted")` (line 326 in paper_executor.py) but `executor_run_log` has `CHECK (status IN ('running', 'success', 'failed', 'stale_signal', 'no_signals'))`. This INSERT will silently fail (the method swallows exceptions). The status `'halted'` is not in the allowed set.
**How to avoid:** Add `'halted'` to `chk_exec_run_status` in the same migration. This is an existing bug uncovered during research.

### Pitfall 7: AMA Signal Tables Need `executor_processed_at` Column
**What goes wrong:** The `executor_processed_at` column was added to the 3 existing signal tables by migration `225bf8646f03`. New signal tables created in Phase 96 must include this column at table-creation time, not as a follow-up ALTER.
**How to avoid:** Include `executor_processed_at TIMESTAMPTZ NULL` in the CREATE TABLE DDL for all 4 new signal tables.

### Pitfall 8: BL Weights May Be Zero for Many Assets
**What goes wrong:** `portfolio_allocations` rows where `final_weight = 0` or `weight = 0` mean BL de-selected that asset. If the executor naively divides by weight = 0 or sets `position_fraction = 0`, it generates a flat position — which is correct, but must be handled explicitly (not silently produce a zero-division).
**How to avoid:** In the BL weight lookup, treat `weight <= 0` as a "close position" signal (same as `position_state='closed'`), not as a sizing error.

### Pitfall 9: `run_all_signal_refreshes.py` Hardcodes 3 Signal Types
**What goes wrong:** Line 176 hardcodes `signal_types = ["ema_crossover", "rsi_mean_revert", "atr_breakout"]`. Adding more types here without also adding them to the `generators` dict (line 110) causes `KeyError: "Unknown signal type"`. The two-batch architecture requires restructuring this list into two sequential groups.
**How to avoid:** Refactor `run_parallel_refresh` to accept an explicit `signal_types` list, then call it twice with Batch 1 and Batch 2.

---

## Code Examples

### Check Constraint Migration Pattern (from existing migrations)

```python
# Source: alembic/versions/225bf8646f03_paper_trade_executor.py pattern
# Drop old constraint, recreate with expanded set

def upgrade() -> None:
    # Widen signal_type constraint
    op.drop_constraint(
        "chk_exec_config_signal_type",
        "dim_executor_config",
        schema="public",
    )
    op.create_check_constraint(
        "chk_exec_config_signal_type",
        "dim_executor_config",
        "signal_type IN ('ema_crossover', 'rsi_mean_revert', 'atr_breakout', "
        "'macd_crossover', 'ama_momentum', 'ama_mean_reversion', 'ama_regime_conditional')",
        schema="public",
    )

    # Widen sizing_mode constraint (if adding bl_weight mode)
    op.drop_constraint(
        "chk_exec_config_sizing_mode",
        "dim_executor_config",
        schema="public",
    )
    op.create_check_constraint(
        "chk_exec_config_sizing_mode",
        "dim_executor_config",
        "sizing_mode IN ('fixed_fraction', 'regime_adjusted', 'signal_strength', "
        "'target_vol', 'bl_weight')",
        schema="public",
    )

    # Fix existing bug: add 'halted' to executor_run_log status
    op.drop_constraint("chk_exec_run_status", "executor_run_log", schema="public")
    op.create_check_constraint(
        "chk_exec_run_status",
        "executor_run_log",
        "status IN ('running', 'success', 'failed', 'stale_signal', 'no_signals', 'halted')",
        schema="public",
    )

    # Create 4 new signal tables (same schema as signals_ema_crossover)
    for tbl in [
        "signals_macd_crossover",
        "signals_ama_momentum",
        "signals_ama_mean_reversion",
        "signals_ama_regime_conditional",
    ]:
        op.create_table(
            tbl,
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("ts", sa.TIMESTAMP(timezone=True), nullable=False),
            sa.Column("signal_id", sa.Integer(), nullable=False),
            sa.Column("direction", sa.Text(), nullable=False),
            sa.Column("position_state", sa.Text(), nullable=False),
            sa.Column("entry_price", sa.Numeric(), nullable=True),
            sa.Column("entry_ts", sa.TIMESTAMP(timezone=True), nullable=True),
            sa.Column("exit_price", sa.Numeric(), nullable=True),
            sa.Column("exit_ts", sa.TIMESTAMP(timezone=True), nullable=True),
            sa.Column("pnl_pct", sa.Numeric(), nullable=True),
            sa.Column("feature_snapshot", sa.JSON(), nullable=True),
            sa.Column("signal_version", sa.Text(), nullable=True),
            sa.Column("feature_version_hash", sa.Text(), nullable=True),
            sa.Column("params_hash", sa.Text(), nullable=True),
            sa.Column("executor_processed_at",
                      sa.TIMESTAMP(timezone=True), nullable=True),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                      server_default=sa.text("now()")),
            sa.PrimaryKeyConstraint("id", "ts", "signal_id"),
            sa.ForeignKeyConstraint(["signal_id"], ["public.dim_signals.signal_id"]),
            schema="public",
        )
```

### AMA Generator Pattern (adapter from EMA pattern)

```python
# Source: src/ta_lab2/scripts/signals/generate_signals_ema.py (adapted)
# Key difference: must load AMA columns from ama_multi_tf_u before calling signal fn

from dataclasses import dataclass
from sqlalchemy import text
from ta_lab2.signals.ama_composite import (
    ama_momentum_signal,
    ama_mean_reversion_signal,
    ama_regime_conditional_signal,
)

# AMA columns needed (from ama_composite.py _DEFAULT_AMA_COLS)
_AMA_COLS = [
    "TEMA_0fca19a1_ama",
    "KAMA_987fc105_ama",
    "HMA_514ffe35_ama",
    "TEMA_514ffe35_ama",
    "DEMA_0fca19a1_ama",
    "KAMA_de1106d5_ama",   # needed by ama_mean_reversion default
    "DEMA_d47fe5cc_ama",   # needed by ama_regime_conditional default
]

# Query pattern to load AMA values (from refresh_portfolio_allocations.py)
# Each indicator+params_hash pair is one AMA column
ama_query = text("""
    SELECT DISTINCT ON (a.id, a.ts)
        a.id, a.ts, a.indicator, LEFT(a.params_hash, 8) AS ph, a.ama
    FROM public.ama_multi_tf_u a
    WHERE a.id = ANY(:ids)
      AND a.tf = :tf
      AND a.venue_id = :venue_id
      AND a.alignment_source = 'multi_tf'
      AND a.roll = FALSE
    ORDER BY a.id, a.ts
""")
# Then pivot: for each id+ts row, create column "{INDICATOR}_{ph}_ama" = ama value
```

### Two-Batch Parallel Refresh Pattern

```python
# Source: run_all_signal_refreshes.py (refactored)
# Batch 1: no AMA dependency
BATCH_1 = ["ema_crossover", "rsi_mean_revert", "atr_breakout", "macd_crossover"]
# Batch 2: requires fresh AMA values
BATCH_2 = ["ama_momentum", "ama_mean_reversion", "ama_regime_conditional"]

batch1_results = run_parallel_refresh(engine, ids, full_refresh,
                                       signal_types=BATCH_1, max_workers=4)
# Check Batch 1 success before running Batch 2
if not args.fail_fast or all(r.success for r in batch1_results):
    batch2_results = run_parallel_refresh(engine, ids, full_refresh,
                                          signal_types=BATCH_2, max_workers=3)
```

### BL Weight Lookup in PositionSizer

```python
# Source: position_sizer.py (new branch in compute_target_position)
elif sizing_mode == "bl_weight":
    # Look up most recent BL weight from portfolio_allocations
    bl_sql = text(
        "SELECT DISTINCT ON (asset_id) "
        "COALESCE(final_weight, weight) AS bl_weight "
        "FROM public.portfolio_allocations "
        "WHERE asset_id = :asset_id AND optimizer = 'bl' "
        "ORDER BY asset_id, ts DESC"
    )
    conn = kwargs.get("conn")  # caller must pass conn
    if conn is not None:
        row = conn.execute(bl_sql, {"asset_id": kwargs.get("asset_id")}).fetchone()
        if row and row.bl_weight is not None and float(row.bl_weight) > 0:
            # Use BL weight directly as position fraction of portfolio
            fraction = Decimal(str(row.bl_weight))
        else:
            # BL de-selected this asset or no BL run yet: go flat
            return Decimal("0")
    else:
        # No connection available: fall back to fixed_fraction
        fraction = Decimal(str(config.position_fraction))
```

### Fill-to-Fill Sharpe Query

```python
# Source: standard pattern using fills + orders tables (no existing precedent)
# Computes fill-to-fill returns for closed positions
parity_sql = text("""
    WITH round_trips AS (
        SELECT
            o.asset_id,
            o.signal_id,
            MIN(f.filled_at) FILTER (WHERE o.side = 'buy') AS entry_ts,
            MAX(f.filled_at) FILTER (WHERE o.side = 'sell') AS exit_ts,
            AVG(f.fill_price) FILTER (WHERE o.side = 'buy') AS entry_price,
            AVG(f.fill_price) FILTER (WHERE o.side = 'sell') AS exit_price
        FROM fills f
        JOIN orders o ON f.order_id = o.order_id
        WHERE o.strategy_id = :strategy_id
          AND f.filled_at BETWEEN :start_date AND :end_date
        GROUP BY o.asset_id, o.signal_id, f.order_id
    )
    SELECT
        (exit_price - entry_price) / NULLIF(entry_price, 0) AS round_trip_return,
        EXTRACT(EPOCH FROM (exit_ts - entry_ts)) / 86400.0 AS hold_days
    FROM round_trips
    WHERE exit_price IS NOT NULL AND entry_price IS NOT NULL
""")
```

### YAML Seed Format for 7 Strategies

```yaml
# configs/executor_config_seed.yaml additions
# Cadence: EMA/RSI/ATR = 36h, MACD = 36h, AMA batch = 48h (slower, needs more buffer)

  - config_name: macd_crossover_12_26_paper_v1
    signal_type: macd_crossover
    signal_name: macd_12_26_9_long       # must exist in dim_signals
    is_active: true
    exchange: paper
    environment: sandbox
    sizing_mode: bl_weight               # or fixed_fraction until BL mode is ready
    position_fraction: 0.10              # fallback only
    max_position_fraction: 0.20
    fill_price_mode: next_bar_open
    slippage_mode: lognormal
    slippage_base_bps: 3.0
    slippage_noise_sigma: 0.5
    volume_impact_factor: 0.1
    rejection_rate: 0.0
    partial_fill_rate: 0.0
    execution_delay_bars: 0
    cadence_hours: 36.0

  - config_name: ama_momentum_paper_v1
    signal_type: ama_momentum
    signal_name: ama_momentum_v1         # must exist in dim_signals
    is_active: true
    exchange: paper
    environment: sandbox
    sizing_mode: bl_weight
    position_fraction: 0.10
    max_position_fraction: 0.20
    fill_price_mode: next_bar_open
    slippage_mode: lognormal
    slippage_base_bps: 3.0
    slippage_noise_sigma: 0.5
    volume_impact_factor: 0.1
    rejection_rate: 0.0
    partial_fill_rate: 0.0
    execution_delay_bars: 0
    cadence_hours: 48.0                  # AMA batch runs ~48h cadence

  # ... (ama_mean_reversion, ama_regime_conditional follow same pattern)
```

---

## State of the Art

| Old Pattern | Current Pattern | Impact for Phase 96 |
|-------------|-----------------|---------------------|
| 3 signal types only | Need 7 | Must extend SIGNAL_TABLE_MAP + 4 new tables + migration |
| `position_fraction` sizing | BL output weights | Add `sizing_mode='bl_weight'` + lookup from `portfolio_allocations` |
| No live parity tracking | `strategy_parity` table + CLI | New table + computation script |
| No PnL attribution | `pnl_attribution` table + CLI | New table + beta computation |
| Parity = backtest replay only | Live Sharpe both fill-to-fill and MTM | Dual computation in parity script |
| Executor_run_log missing 'halted' | Fix existing CHECK constraint bug | Include in migration |

**Deprecated/outdated:**
- `parity_checker.py`: Current parity checker is REPLAY-only (compares executor fills against backtest trades). Phase 96 needs LIVE parity (live Sharpe vs backtest Sharpe) — this is a different computation and should be in a NEW script, not modifying `parity_checker.py`.

---

## Open Questions

1. **dim_signals seed for new types**
   - What we know: `seed_executor_config.py` resolves `signal_name -> signal_id` from `dim_signals`. The seed will fail (`skipped_no_signal`) if `dim_signals` doesn't have rows for `macd_12_26_9_long`, `ama_momentum_v1`, etc.
   - What's unclear: Whether dim_signals already has MACD/AMA entries seeded, or whether they need to be created as part of Phase 96. This should be checked at plan time.
   - Recommendation: Plan 96-01 should include a verification step: `SELECT signal_type, signal_name FROM dim_signals WHERE signal_type IN ('macd_crossover', 'ama_momentum', 'ama_mean_reversion', 'ama_regime_conditional')`.

2. **BL weight timing relative to executor**
   - What we know: Pipeline order is `portfolio` -> `executor` (positions 18 and 19 in STAGE_ORDER).
   - What's unclear: The BL weights written during today's portfolio stage are what the executor uses today. If BL fails, executor has no weights. Need to decide: fail executor (no BL = no trades) or fallback to `fixed_fraction`.
   - Recommendation: Use `fixed_fraction` as fallback when BL weight is unavailable for a specific asset. This is the safer default.

3. **Asset class classification for pnl_attribution**
   - What we know: `cmc_da_info` has category data for CMC assets. HL assets have `asset_type` ('perp', 'spot') in `hl_assets`.
   - What's unclear: Equity assets (FRED macro data) don't have individual positions yet; Phase 97 adds them.
   - Recommendation: For Phase 96, implement two asset classes: `crypto` (all CMC + HL spot) and `perp` (all HL perps). Equity class is extensible later.

---

## Sources

### Primary (HIGH confidence)
- Direct inspection: `src/ta_lab2/executor/signal_reader.py` — SIGNAL_TABLE_MAP, stale guard logic
- Direct inspection: `src/ta_lab2/executor/paper_executor.py` — full execution flow, _write_run_log, BL gap
- Direct inspection: `src/ta_lab2/executor/position_sizer.py` — sizing modes, no bl_weight mode
- Direct inspection: `src/ta_lab2/scripts/signals/run_all_signal_refreshes.py` — hardcoded 3 signal types
- Direct inspection: `alembic/versions/225bf8646f03_paper_trade_executor.py` — constraint definitions
- Direct inspection: `src/ta_lab2/portfolio/black_litterman.py` — IC-IR weighting, per-asset path
- Direct inspection: `src/ta_lab2/scripts/portfolio/refresh_portfolio_allocations.py` — BL wiring, signal_scores
- Direct inspection: `src/ta_lab2/signals/ama_composite.py` — AMA generator, pre-loaded columns requirement
- Direct inspection: `configs/executor_config_seed.yaml` — current 2-strategy seed YAML
- Direct inspection: `sql/executor/088_dim_executor_config.sql` and `089_executor_run_log.sql` — DDL reference

### Secondary (MEDIUM confidence)
- Pattern inference: AMA generator architecture based on EMA/RSI/ATR generators and ama_composite.py commentary

---

## Metadata

**Confidence breakdown:**
- Signal infrastructure gaps: HIGH — all constraints and table maps confirmed from source
- BL integration gap: HIGH — confirmed executor never reads portfolio_allocations
- Parity/attribution: HIGH — no existing tables or scripts found, new work required
- dim_signals seed status for new types: MEDIUM — not verified against live DB

**Research date:** 2026-03-30
**Valid until:** 2026-04-30 (codebase is stable; constraints and file paths will not drift)
