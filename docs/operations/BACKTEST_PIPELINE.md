# Backtest Pipeline Operations Guide

This guide covers signal generation, backtest execution, and result interpretation for the backtest pipeline. An operator can generate signals, run backtests, query results, and interpret metrics without reading source code.

## Quick Start

```bash
# Generate all signals (incremental, all 3 signal types in parallel)
python -m ta_lab2.scripts.signals.run_all_signal_refreshes

# Run a backtest for one signal type (EMA crossover, signal id=1, BTC, full year 2023)
python -m ta_lab2.scripts.backtests.run_backtest_signals \
    --signal-type ema_crossover \
    --signal-id 1 \
    --asset-id 1 \
    --start 2023-01-01 \
    --end 2023-12-31 \
    --save-results

# Validate reproducibility only (no signal generation)
python -m ta_lab2.scripts.signals.run_all_signal_refreshes --validate-only
```

## Prerequisites

Before running signals or backtests, confirm:

1. **Database reachable** — `TARGET_DB_URL` must be set:
   ```bash
   export TARGET_DB_URL="postgresql://user:pass@host:5432/dbname"
   ```
2. **`features` populated** — Features refresh must have run for the target assets and `tf='1D'`. Signals read bar-level features from this table.
3. **`ema_multi_tf_u` populated** — EMA values must be fresh. Each signal type joins this table directly for EMA data.
4. **`dim_signals` seeded** — Signal configurations (RSI thresholds, EMA periods, etc.) must exist in `dim_signals`. This is seeded by `sql/signals/030_dim_signals.sql`.
5. **Regime data available (optional)** — If regime context is enabled (default), `regimes` should be fresh. Signals fall back gracefully to NULL regime_key if the table is empty.

See [DAILY_REFRESH.md](DAILY_REFRESH.md) for how to refresh bars and EMAs. See [REGIME_PIPELINE.md](REGIME_PIPELINE.md) for how to refresh regimes.

## Pipeline Overview

```
features (tf='1D')         ema_multi_tf_u
     |                                |
     +----------[LEFT JOIN]----------+
                    |
         signal generators
      (RSI / EMA crossover / ATR)
                    |
          cmc_signals_* tables
                    |
     SignalBacktester (vectorbt 0.28.1)
                    |
          +----+----+----+
          |         |         |
  backtest_runs  backtest_trades  backtest_metrics
```

features provides bar-level features (RSI, ATR, Bollinger Bands, close price). ema_multi_tf_u is joined separately because EMA data has a different granularity dimension (period). The signal generators produce discrete buy/sell signals; vectorbt runs the portfolio simulation.

## Signal Generation

### Orchestrated Run (Recommended)

`run_all_signal_refreshes` runs all 3 signal types in parallel.

```bash
# Incremental refresh (default — only new signals since last run)
python -m ta_lab2.scripts.signals.run_all_signal_refreshes

# Full refresh — regenerate all signals from scratch
python -m ta_lab2.scripts.signals.run_all_signal_refreshes --full-refresh

# Skip reproducibility validation
python -m ta_lab2.scripts.signals.run_all_signal_refreshes --skip-validation

# Validate only — no signal generation, just check reproducibility
python -m ta_lab2.scripts.signals.run_all_signal_refreshes --validate-only

# Exit on first failure (default: continue partial results)
python -m ta_lab2.scripts.signals.run_all_signal_refreshes --fail-fast

# Specific assets only
python -m ta_lab2.scripts.signals.run_all_signal_refreshes --ids 1 2 52

# Disable regime context (A/B comparison mode)
python -m ta_lab2.scripts.signals.run_all_signal_refreshes --no-regime

# Verbose output
python -m ta_lab2.scripts.signals.run_all_signal_refreshes -v
```

If one signal type fails, the others continue by default. Use `--fail-fast` to abort on first failure.

### Individual Signal Type Scripts

Use for debugging a specific signal type or running with custom flags.

```bash
# RSI mean reversion
python -m ta_lab2.scripts.signals.refresh_signals_rsi_mean_revert

# RSI — full refresh for specific assets
python -m ta_lab2.scripts.signals.refresh_signals_rsi_mean_revert --ids 1 52 --full-refresh

# RSI — dry run with verbose
python -m ta_lab2.scripts.signals.refresh_signals_rsi_mean_revert --dry-run --verbose

# RSI — specific signal config from dim_signals
python -m ta_lab2.scripts.signals.refresh_signals_rsi_mean_revert --signal-id 4

# EMA crossover
python -m ta_lab2.scripts.signals.refresh_signals_ema_crossover

# ATR breakout
python -m ta_lab2.scripts.signals.refresh_signals_atr_breakout
```

### Signal Types

| Signal Type | Generator Class | Configs in `dim_signals` | Output Table |
|-------------|----------------|--------------------------|--------------|
| `ema_crossover` | `EMASignalGenerator` | `ema_9_21_long`, `ema_21_50_long`, `ema_50_200_long` | `signals_ema_crossover` |
| `rsi_mean_revert` | `RSISignalGenerator` | `rsi_30_70_mr`, `rsi_25_75_mr` | `signals_rsi_mean_revert` |
| `atr_breakout` | `ATRSignalGenerator` | `atr_20_donchian` | `signals_atr_breakout` |

### Feature Sources per Signal Type

Each signal type reads from `features` and joins `ema_multi_tf_u` for EMA data:

| Signal Type | From `features` | EMA periods from `ema_multi_tf_u` |
|-------------|---------------------|---------------------------------------|
| `ema_crossover` | `close`, `rsi_14`, `atr_14` | 9, 10, 21, 50, 200 |
| `rsi_mean_revert` | `close`, `rsi_14`, `rsi_7`, `rsi_21`, `atr_14` | 21 |
| `atr_breakout` | `close`, `atr_14`, `bb_up_20_2`, `bb_lo_20_2`, `rsi_14` | 21 |

All three also read `regime_key` from `regimes` via `load_regime_context_batch` when regime context is enabled (default).

## Running Backtests

### Clean Mode (Reproducibility Testing)

Use `--clean-pnl` to run without transaction costs. Two identical clean runs must produce bit-for-bit identical results. This is the mode used by `validate_reproducibility.py`.

```bash
python -m ta_lab2.scripts.backtests.run_backtest_signals \
    --signal-type ema_crossover \
    --signal-id 1 \
    --asset-id 1 \
    --start 2023-01-01 \
    --end 2023-12-31 \
    --clean-pnl
```

### Realistic Mode (With Fees)

Specify transaction costs to simulate realistic trading performance.

```bash
python -m ta_lab2.scripts.backtests.run_backtest_signals \
    --signal-type rsi_mean_revert \
    --signal-id 2 \
    --asset-id 1 \
    --start 2023-01-01 \
    --end 2023-12-31 \
    --fee-bps 10 \
    --slippage-bps 5 \
    --save-results
```

`--fee-bps 10` = 10 basis points (0.10%) per trade. `--slippage-bps 5` = 5 bps slippage. Use `--save-results` to persist the run to `backtest_runs`, `backtest_trades`, and `backtest_metrics`.

### JSON Output Mode

Dump results to a file for external processing or comparison.

```bash
python -m ta_lab2.scripts.backtests.run_backtest_signals \
    --signal-type atr_breakout \
    --signal-id 3 \
    --asset-id 1 \
    --start 2023-01-01 \
    --end 2023-12-31 \
    --save-results \
    --output-json results.json
```

### All Flags for `run_backtest_signals`

| Flag | Purpose |
|------|---------|
| `--signal-type` | Signal type: `ema_crossover`, `rsi_mean_revert`, or `atr_breakout` |
| `--signal-id` | Signal configuration ID from `dim_signals` |
| `--asset-id` | Asset ID from `dim_assets` (e.g., 1 = BTC) |
| `--start YYYY-MM-DD` | Backtest start date |
| `--end YYYY-MM-DD` | Backtest end date |
| `--clean-pnl` | No transaction costs (reproducibility testing) |
| `--fee-bps N` | Fee per trade in basis points (e.g., 10 = 0.10%) |
| `--slippage-bps N` | Slippage per trade in basis points |
| `--save-results` | Persist run + trades + metrics to DB |
| `--output-json FILE` | Write JSON results to file |

## Result Tables

Three tables store backtest output. All three are written together when `--save-results` is used.

**`backtest_runs`** (PK: `run_id` UUID) — One row per backtest execution.

| Column | Purpose |
|--------|---------|
| `signal_type` | `ema_crossover`, `rsi_mean_revert`, or `atr_breakout` |
| `signal_id` | Foreign key to `dim_signals` |
| `asset_id` | Foreign key to `dim_assets` |
| `start_ts`, `end_ts` | Date range of the backtest |
| `cost_model` | JSONB: fee_bps, slippage_bps, clean_pnl flag |
| `signal_params_hash` | Hash of signal parameters for drift detection |
| `feature_hash` | Hash of feature data (changes if features updated) |
| `total_return`, `sharpe_ratio`, `max_drawdown`, `trade_count` | Summary metrics (denormalized for quick queries) |
| `run_timestamp` | When the run was executed |

**`backtest_trades`** (FK: `run_id`) — One row per trade.

| Column | Purpose |
|--------|---------|
| `entry_ts`, `entry_price` | Trade entry |
| `exit_ts`, `exit_price` | Trade exit |
| `direction` | `long` or `short` |
| `size` | Position size |
| `pnl_pct`, `pnl_dollars` | Trade P&L |

**`backtest_metrics`** (FK: `run_id`) — Full metrics for one run.

| Column | Purpose |
|--------|---------|
| `total_return`, `cagr` | Return metrics |
| `sharpe_ratio`, `sortino_ratio`, `calmar_ratio` | Risk-adjusted return |
| `max_drawdown`, `max_drawdown_duration_days` | Drawdown metrics |
| `trade_count`, `win_rate`, `profit_factor`, `avg_win`, `avg_loss` | Trade statistics |
| `avg_holding_period_days` | Holding period |
| `var_95`, `expected_shortfall` | Tail risk |

## Querying Results

```sql
-- 1. Latest runs per signal type
SELECT signal_type, signal_id, asset_id, total_return, sharpe_ratio,
       max_drawdown, trade_count, run_timestamp
FROM public.backtest_runs
ORDER BY run_timestamp DESC
LIMIT 20;

-- 2. Full metrics for a specific signal type (most recent runs)
SELECT r.signal_type, r.signal_id, r.asset_id,
       m.total_return, m.cagr, m.sharpe_ratio, m.sortino_ratio,
       m.max_drawdown, m.trade_count, m.win_rate, m.profit_factor
FROM public.backtest_runs r
JOIN public.backtest_metrics m ON r.run_id = m.run_id
WHERE r.signal_type = 'ema_crossover'
ORDER BY r.run_timestamp DESC
LIMIT 10;

-- 3. Trades for a specific run (replace uuid with actual run_id from query 1)
SELECT entry_ts, entry_price, exit_ts, exit_price, direction, pnl_pct
FROM public.backtest_trades
WHERE run_id = '[paste-run-id-uuid-here]'
ORDER BY entry_ts;

-- 4. Signal counts by type (sanity check that signals were generated)
SELECT signal_type, COUNT(*) as n_signals
FROM public.signals_ema_crossover
GROUP BY signal_type
UNION ALL
SELECT 'rsi_mean_revert', COUNT(*) FROM public.signals_rsi_mean_revert
UNION ALL
SELECT 'atr_breakout', COUNT(*) FROM public.signals_atr_breakout;
```

## Interpreting Metrics

Use these thresholds as a starting point. Context matters — a short date range with few trades has low statistical significance regardless of metrics.

| Metric | Good | Concerning | Notes |
|--------|------|------------|-------|
| `total_return` | Positive | Negative | Absolute return over the period |
| `sharpe_ratio` | > 1.0 | < 0 | Risk-adjusted return vs. volatility |
| `sortino_ratio` | > 1.5 | < 0 | Like Sharpe but penalizes downside vol only |
| `max_drawdown` | < 0.20 | > 0.40 | Maximum peak-to-trough decline (fractional) |
| `win_rate` | > 0.50 | < 0.35 | Fraction of trades that were profitable |
| `profit_factor` | > 1.5 | < 1.0 | Gross profit / gross loss ratio |
| `trade_count` | > 10 | < 5 | Low count = low statistical significance |

**Regime-aware interpretation:** Metrics computed with regime context (`regime_key` populated) reflect strategy performance conditioned on market regime. A lower Sharpe with regime filtering may indicate the signal underperforms in certain regimes — use the `--no-regime` flag to compare.

```bash
# Compare regime-aware vs. regime-disabled for same period
python -m ta_lab2.scripts.signals.run_all_signal_refreshes
python -m ta_lab2.scripts.backtests.run_backtest_signals --signal-type ema_crossover --signal-id 1 --asset-id 1 --start 2023-01-01 --end 2023-12-31 --save-results

python -m ta_lab2.scripts.signals.run_all_signal_refreshes --no-regime
python -m ta_lab2.scripts.backtests.run_backtest_signals --signal-type ema_crossover --signal-id 1 --asset-id 1 --start 2023-01-01 --end 2023-12-31 --save-results
```

Then compare the two runs in `backtest_metrics` ordered by `run_timestamp DESC`.

## Reproducibility Validation

`validate_reproducibility.py` runs the same backtest twice and checks that results are bit-for-bit identical. This catches non-deterministic data loading, floating-point ordering issues, or feature data changes between runs.

**What it checks:**
- `total_return` must match within tolerance `1e-10`
- All metrics must match within tolerance
- Trade count must be identical
- Feature hash: detects if `features` data changed between runs

**Modes:**
- `strict=True` — Raises `RuntimeError` on any difference
- `strict=False` (default in orchestrator) — Logs a warning but proceeds

**Run manually:**
```bash
# Validate-only mode (no signal generation)
python -m ta_lab2.scripts.signals.run_all_signal_refreshes --validate-only

# Validate with verbose output
python -m ta_lab2.scripts.signals.run_all_signal_refreshes --validate-only -v
```

If validation fails, the `feature_hash` column in `backtest_runs` tells you whether the underlying feature data changed between runs. A changed hash means `features` was updated, which is expected. Identical hash with different results indicates a non-determinism bug.

## Troubleshooting

### "TARGET_DB_URL environment variable not set"

```
TARGET_DB_URL environment variable not set
```

- **Fix:**
  ```bash
  export TARGET_DB_URL="postgresql://user:pass@host:5432/dbname"
  ```
  The script also checks `$DB_URL` and `$MARKETDATA_DB_URL` as fallbacks.

---

### "No asset IDs to process"

```
No asset IDs to process
```

- **Cause:** `features` is empty or contains no 1D data for the target assets.
- **Fix:** Run feature refresh first:
  ```bash
  python -m ta_lab2.scripts.features.run_all_feature_refreshes --all --tf 1D
  ```
  Then verify data exists:
  ```sql
  SELECT COUNT(*) FROM public.features WHERE tf = '1D';
  ```

---

### Signal generation fails for one type

- **Behavior:** By default, the orchestrator continues with partial results. Other signal types succeed.
- **To abort on first failure:** Use `--fail-fast`.
- **Debug the failing type:**
  ```bash
  # Run just the failing signal type with verbose
  python -m ta_lab2.scripts.signals.refresh_signals_ema_crossover --verbose
  ```
  Look for the specific error in the verbose output.

---

### "Reproducibility validation FAILED"

```
Reproducibility validation FAILED for signal_type=ema_crossover
```

- **Cause:** Two identical backtest runs produced different results. Usually a non-deterministic data loading issue or floating-point ordering problem.
- **Investigate:**
  ```bash
  python -m ta_lab2.scripts.signals.run_all_signal_refreshes --validate-only --verbose
  ```
  Check the `feature_hash` in `backtest_runs` — if it changed between runs, the underlying feature data was updated (expected). If hash is identical but results differ, there is a non-determinism bug.

---

### "Backtest run not found: [uuid]"

```
Backtest run not found: abc-123-...
```

- **Cause:** The `run_id` does not exist in `backtest_runs`, or `--save-results` was not passed when the run was executed.
- **Check:** Find recent run IDs:
  ```sql
  SELECT run_id, signal_type, run_timestamp
  FROM public.backtest_runs
  ORDER BY run_timestamp DESC
  LIMIT 5;
  ```

---

### Backtest produces 0 trades

- **Cause:** No signals in `cmc_signals_*` for the requested date range and asset.
- **Check signal count:**
  ```sql
  SELECT COUNT(*) FROM public.signals_ema_crossover
  WHERE id = 1 AND entry_ts BETWEEN '2023-01-01' AND '2023-12-31';
  ```
  If 0, run signal generation first:
  ```bash
  python -m ta_lab2.scripts.signals.refresh_signals_ema_crossover --ids 1
  ```

## See Also

- [DAILY_REFRESH.md](DAILY_REFRESH.md) — How to refresh bars and EMAs (prerequisite for feature refresh)
- [REGIME_PIPELINE.md](REGIME_PIPELINE.md) — How to refresh regime context (optional but recommended before signal generation)
- [STATE_MANAGEMENT.md](STATE_MANAGEMENT.md) — State table schemas
- `src/ta_lab2/scripts/signals/run_all_signal_refreshes.py` — Signal orchestrator
- `src/ta_lab2/scripts/backtests/run_backtest_signals.py` — Backtest runner
- `src/ta_lab2/scripts/signals/validate_reproducibility.py` — Reproducibility checker
- `sql/signals/030_dim_signals.sql` — Signal configuration seed data
