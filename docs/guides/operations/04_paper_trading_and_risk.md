# Part 4: Paper Trading & Risk Management

## Overview

Paper trading in ta_lab2 simulates real trading without risking capital. It uses the same signal processing, position sizing, and risk management as live trading, but fills are simulated rather than sent to an exchange. This lets you validate your strategies in real-time market conditions before committing real money.

The paper trading system consists of three interacting components: the executor (signal processing + order generation), the risk engine (7 gates that can block or reduce orders), and the fill simulator (slippage injection). Understanding how these interact is essential for interpreting paper trading results.

---

## 4.1 Paper Trading Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                    PAPER TRADING FLOW                                 │
│                                                                      │
│  ┌──────────┐   ┌──────────────┐   ┌──────────────┐                │
│  │ Signals  ├──►│ SignalReader  ├──►│ PositionSizer│                │
│  │ (3 types)│   │ (watermark)  │   │ (fraction)   │                │
│  └──────────┘   └──────────────┘   └──────┬───────┘                │
│                                            │                         │
│                                     ┌──────▼───────┐                │
│                                     │  L4 Macro    │                │
│                                     │  Gross Cap   │                │
│                                     │  Scaling     │                │
│                                     └──────┬───────┘                │
│                                            │                         │
│                 ┌──────────────────────────▼──────────────────────┐ │
│                 │            RISK ENGINE (7 Gates)                │ │
│                 │                                                  │ │
│                 │  Gate 1:   Kill Switch (atomic halt)            │ │
│                 │  Gate 1.5: Tail Risk (flatten/reduce)           │ │
│                 │  Gate 1.6: Margin Guard (liquidation distance)  │ │
│                 │  Gate 1.7: Macro Gates (8 sub-gates)            │ │
│                 │  Gate 2:   Circuit Breaker (loss streak)        │ │
│                 │  Gate 3:   Position Cap (15% max per asset)     │ │
│                 │  Gate 4:   Portfolio Utilization (80% max)      │ │
│                 └──────────────────────────┬──────────────────────┘ │
│                                            │                         │
│                     ┌──────────────────────▼──────────────────────┐ │
│                     │  IF ALLOWED:                                │ │
│                     │                                              │ │
│                     │  CanonicalOrder ──► PaperOrderLogger        │ │
│                     │       │                  │                   │ │
│                     │       │            paper_orders (log)       │ │
│                     │       │                                      │ │
│                     │       ▼                                      │ │
│                     │  OrderManager.promote_paper_order            │ │
│                     │       │                                      │ │
│                     │       ▼                                      │ │
│                     │  FillSimulator (slippage injection)         │ │
│                     │       │                                      │ │
│                     │       ▼                                      │ │
│                     │  OrderManager.process_fill (atomic 4-table) │ │
│                     │    orders + fills + positions   │ │
│                     │    + order_events                       │ │
│                     └────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────┘
```

**The lifecycle of a paper order:**

1. **Signal generated:** A signal generator (EMA crossover, RSI, or ATR) writes a row to `cmc_signals_*` with `executor_processed_at = NULL`.
2. **SignalReader picks it up:** The executor's watermark-based reader finds unprocessed signals.
3. **PositionSizer calculates quantity:** Based on `position_fraction` from `dim_executor_config` and current portfolio value.
4. **Macro scaling adjusts:** L4 macro gate multiplier may reduce the size (e.g., 0.5x during "Cautious" macro regime).
5. **Risk engine evaluates 7 gates:** Each gate can ALLOW, REDUCE (adjust quantity down), or BLOCK the order.
6. **If allowed:** A `CanonicalOrder` is created and logged to `paper_orders`.
7. **Order promoted:** `OrderManager.promote_paper_order()` creates a real order in `orders`.
8. **Fill simulated:** `FillSimulator` injects slippage based on the configured mode.
9. **Atomic write:** `OrderManager.process_fill()` atomically updates 4 tables: `orders` (status → filled), `fills` (fill price + qty), `positions` (update position), `order_events` (audit trail).

---

## 4.2 Setting Up Paper Trading

### Step 1: Seed Executor Configurations

Executor configs define which signals to trade, position sizing, slippage model, and risk parameters:

```bash
# Load default configs from YAML
python -m ta_lab2.scripts.executor.seed_executor_config

# Or with custom YAML
python -m ta_lab2.scripts.executor.seed_executor_config \
    --config configs/executor_config_seed.yaml
```

### Step 2: Verify Active Configs

```sql
SELECT config_id, config_name, signal_type, is_active,
       exchange, sizing_mode, position_fraction,
       slippage_mode, slippage_base_bps
FROM dim_executor_config
WHERE is_active = TRUE;
```

Each active config defines one strategy-signal combination. You can have multiple active configs running simultaneously (e.g., EMA crossover on BTC + RSI mean revert on ETH).

### Step 3: Ensure Signals Exist

The executor only processes signals with `executor_processed_at IS NULL`:

```sql
-- Check for unprocessed signals by type
SELECT 'ema_crossover' as signal_type, count(*) as unprocessed
FROM signals_ema_crossover
WHERE executor_processed_at IS NULL
UNION ALL
SELECT 'rsi_mean_revert', count(*)
FROM signals_rsi_mean_revert
WHERE executor_processed_at IS NULL
UNION ALL
SELECT 'atr_breakout', count(*)
FROM signals_atr_breakout
WHERE executor_processed_at IS NULL;
```

### Step 4: Run Paper Executor

```bash
# Dry run first (see what would happen, no DB writes)
python -m ta_lab2.scripts.executor.run_paper_executor --dry-run --verbose

# Standard run
python -m ta_lab2.scripts.executor.run_paper_executor

# With debug logging
python -m ta_lab2.scripts.executor.run_paper_executor --verbose
```

### Step 5: Verify Orders and Fills

After the executor runs, check that orders, fills, and positions were created correctly:

```sql
-- Check recent orders
SELECT order_id, symbol, side, order_type, quantity, status, created_at
FROM orders
ORDER BY created_at DESC LIMIT 10;

-- Check fills (each order should have exactly one fill in paper mode)
SELECT f.fill_id, f.order_id, f.fill_qty, f.fill_price, f.slippage_bps, f.created_at
FROM fills f
ORDER BY f.created_at DESC LIMIT 10;

-- Check current positions (quantity != 0 means open position)
SELECT asset_id, strategy_id, quantity, avg_entry_price, unrealized_pnl, updated_at
FROM positions
WHERE quantity != 0;

-- Check order events audit trail
SELECT order_id, event_type, detail, created_at
FROM order_events
ORDER BY created_at DESC LIMIT 20;
```

---

## 4.3 Fill Simulation Modes

The fill simulator controls how realistic paper fills are. Choose a mode based on your goal:

| Mode | Slippage | Use Case |
|------|----------|----------|
| `zero` | None (exact fill at close price) | Backtest parity verification |
| `fixed` | Deterministic bps offset | Pessimistic uniform estimate |
| `lognormal` | Volume-adaptive + random noise | Realistic simulation (recommended for production) |

**Lognormal formula (the default for production):**
```
Slippage = base_bps * log-normal(sigma) * sqrt(order_size / bar_volume)
```

This means:
- Larger orders (relative to volume) get more slippage
- Slippage varies randomly around the base (more realistic than fixed)
- Low-volume bars get penalized more (as they would in real markets)

**Config parameters in `dim_executor_config`:**

```yaml
slippage_mode: "lognormal"
slippage_base_bps: 3.0          # Base slippage in basis points (0.03%)
slippage_noise_sigma: 0.5       # Log-normal noise parameter (higher = more variance)
volume_impact_factor: 0.1       # How much volume affects slippage (higher = more impact)
rejection_rate: 0.0             # Probability of order rejection (0.0 = never)
partial_fill_rate: 0.0          # Probability of partial fill (0.0 = always full fill)
execution_delay_bars: 0         # Bars of delay before fill (0 = immediate)
```

---

## 4.4 Risk Engine

The risk engine evaluates every order through 7 sequential gates. If any gate blocks the order, it is rejected. Gates are evaluated in order, and the first blocking gate's reason is recorded in `risk_events`.

### Gate Evaluation Order

```
Order ──► Gate 1: Kill Switch
              │ BLOCKED? ──► Order rejected, reason: "kill_switch_active"
              │ PASS ──► Gate 1.5: Tail Risk
                             │ BLOCKED? ──► Flatten or reduce position
                             │ PASS ──► Gate 1.6: Margin Guard
                                            │ BLOCKED? ──► Too close to liquidation
                                            │ PASS ──► Gate 1.7: Macro Gates (8 sub-gates)
                                                           │ BLOCKED/REDUCED? ──► Apply multiplier
                                                           │ PASS ──► Gate 2: Circuit Breaker
                                                                          │ BLOCKED? ──► Cooldown period
                                                                          │ PASS ──► Gate 3: Position Cap
                                                                                         │ REDUCED? ──► Trim to 15%
                                                                                         │ PASS ──► Gate 4: Portfolio Util
                                                                                                        │ REDUCED? ──► Trim to 80%
                                                                                                        │ PASS ──► ORDER ALLOWED
```

### Using the Risk Engine Programmatically

```python
from sqlalchemy import create_engine
from ta_lab2.risk import RiskEngine, MacroGateEvaluator
from decimal import Decimal

engine = create_engine(db_url)
macro_eval = MacroGateEvaluator(engine)
risk = RiskEngine(engine, macro_gate_evaluator=macro_eval)

result = risk.check_order(
    order_qty=Decimal("0.5"),
    order_side="buy",
    fill_price=Decimal("50000"),
    asset_id=1,
    strategy_id=1,
    current_position_value=Decimal("5000"),
    portfolio_value=Decimal("100000"),
)

if result.allowed:
    print(f"Order allowed, adjusted qty: {result.adjusted_quantity}")
    # adjusted_quantity may be less than original if a gate reduced it
else:
    print(f"Order BLOCKED by gate: {result.blocked_by}")
    print(f"Reason: {result.blocked_reason}")
```

### Risk Limits (Configurable via dim_risk_limits)

| Parameter | Default | Description |
|-----------|---------|-------------|
| `max_position_pct` | 0.15 (15%) | Max single-asset exposure as % of portfolio |
| `max_portfolio_pct` | 0.80 (80%) | Max total capital utilization |
| `daily_loss_pct_threshold` | 0.03 (3%) | Daily loss that triggers tail risk gate |
| `cb_consecutive_losses_n` | 3 | Circuit breaker: N consecutive losing trades |
| `cb_cooldown_hours` | 24.0 | Circuit breaker cooldown period |
| `margin_alert_threshold` | 1.5 | Margin ratio warning level |
| `liquidation_kill_threshold` | 1.1 | Margin ratio that triggers kill switch |

---

## 4.5 Kill Switch

The kill switch is the nuclear option. When activated, it immediately blocks ALL new orders across ALL strategies and ALL assets. It is designed for genuine emergencies.

### Activate (Emergency Halt)

```bash
python -m ta_lab2.scripts.risk.kill_switch_cli activate \
    --reason "Unusual market volatility detected" \
    --operator "asafi"
```

Both `--reason` and `--operator` are mandatory. This creates an audit trail in `risk_events`.

### Check Status

```bash
python -m ta_lab2.scripts.risk.kill_switch_cli status
```

### Re-enable Trading

```bash
python -m ta_lab2.scripts.risk.kill_switch_cli disable \
    --reason "Volatility normalized -- resuming paper trading" \
    --operator "asafi"
```

**IMPORTANT:** Both `--reason` and `--operator` are mandatory for re-enabling. This is by design -- you cannot accidentally re-enable trading.

---

## 4.6 Macro Gates

The macro gate system monitors 8 economic indicators and adjusts position multipliers. Unlike the kill switch (binary on/off), macro gates are graduated: they reduce position sizes proportionally to the threat level.

| Gate | Trigger | Action |
|------|---------|--------|
| `fomc` | Within +/-24h of FOMC meeting | Reduce exposure |
| `cpi` | Within +/-24h of CPI release | Reduce exposure |
| `nfp` | Within +/-12h of NFP release | Reduce exposure |
| `vix` | VIX > 30 | Reduce; VIX > 35 = minimal exposure |
| `carry` | JPY z-score > 2 (carry unwind signal) | Reduce exposure |
| `credit` | HY OAS z-score elevated | Reduce exposure |
| `freshness` | FRED data > 48h stale | Warning only (non-blocking) |
| `composite` | Multi-factor stress score | Graduated reduction |

### Check Gate Status

```bash
python -m ta_lab2.scripts.risk.macro_gate_cli status
```

### Override a Gate

Sometimes you know more than the gate. For example, after an FOMC meeting with no surprises, you may want to override the post-meeting cooldown:

```bash
# Force VIX gate to normal (e.g., known vol spike, not fundamental)
python -m ta_lab2.scripts.risk.macro_gate_cli create \
    --gate-id vix \
    --type force_normal \
    --reason "Known vol spike from options expiry, not fundamental" \
    --operator asafi \
    --expires-hours 48

# Disable a gate entirely
python -m ta_lab2.scripts.risk.macro_gate_cli create \
    --gate-id fomc \
    --type disable_gate \
    --reason "Post-FOMC, no surprises, market absorbed it" \
    --operator asafi

# List all active overrides
python -m ta_lab2.scripts.risk.macro_gate_cli list
python -m ta_lab2.scripts.risk.macro_gate_cli list --gate-id vix

# Revert an override (restore automatic behavior)
python -m ta_lab2.scripts.risk.macro_gate_cli revert \
    --override-id <uuid> \
    --reason "Resolved -- restoring automatic gate behavior" \
    --operator asafi
```

---

## 4.7 Position Overrides

Override specific asset/strategy positions when you need manual control:

```bash
# Flatten a position (close to zero)
python -m ta_lab2.scripts.risk.override_cli create \
    --asset-id 1 --strategy-id 2 --action flat \
    --reason "Weekend liquidity concern" --operator asafi

# Reduce a position (cut by 50%)
python -m ta_lab2.scripts.risk.override_cli create \
    --asset-id 1 --strategy-id 2 --action reduce \
    --reason "High correlation with other positions" --operator asafi

# Sticky override (persists until manually reverted, even across executor restarts)
python -m ta_lab2.scripts.risk.override_cli create \
    --asset-id 1 --strategy-id 2 --action flat \
    --reason "Long-term structural concern" --operator asafi --sticky

# List active overrides
python -m ta_lab2.scripts.risk.override_cli list

# Revert an override
python -m ta_lab2.scripts.risk.override_cli revert \
    --override-id <uuid> --reason "Concern resolved" --operator asafi
```

---

## 4.8 Drift Monitoring

Drift monitoring is the system that answers: "Is paper trading performing as expected, or is something going wrong?" It compares paper trading execution against a "perfect" backtest replay to detect execution decay.

### Daily Drift Check

```bash
python -m ta_lab2.scripts.drift.run_drift_monitor --paper-start 2025-01-01
```

### Weekly Drift Report

```bash
# Standard report (Markdown + 5 Plotly interactive charts)
python -m ta_lab2.scripts.drift.run_drift_report

# With full 6-source attribution decomposition
python -m ta_lab2.scripts.drift.run_drift_report --with-attribution
```

**The 6 drift attribution sources:**
1. **Signal timing drift:** Signals arrived at a different time than in backtest
2. **Fill price slippage:** Simulated fills differ from backtest assumed prices
3. **Position sizing delta:** Sizer produced different quantities
4. **Risk gate interventions:** Risk gates blocked or reduced orders
5. **Market microstructure:** Bid-ask spread, volume effects
6. **Execution latency:** Delay between signal generation and fill

### Drift Thresholds

| Metric | Normal | Warning | Halt Trading |
|--------|--------|---------|-------------|
| Tracking Error (TE) | < 0.03 | 0.03 - 0.05 | > 0.05 |
| Cumulative PnL divergence | < 5% | 5% - 10% | > 10% |
| Fill price drift | < 5 bps avg | 5 - 15 bps avg | > 15 bps avg |

---

## 4.9 Backtest Parity Verification

Before you trust paper trading, verify that the paper executor produces identical results to backtests when slippage is set to zero. If paper and backtest diverge with zero slippage, there is a bug in the executor.

### Step 1: Replay Historical Signals

```bash
python -m ta_lab2.scripts.executor.run_paper_executor \
    --replay-historical --start 2024-01-01 --end 2025-01-01
```

### Step 2: Run Parity Check

```bash
python -m ta_lab2.scripts.executor.run_parity_check \
    --signal-id 1 --start 2024-01-01 --end 2025-01-01 \
    --slippage-mode zero --verbose
```

**Pass criteria:**
- **Zero mode:** Trade count matches exactly AND max price divergence < 1.0 bps
- **Fixed/Lognormal:** Trade count matches AND P&L correlation >= 0.99

---

## 4.9a Parity Verification (v1.2.0 Bakeoff Mode)

In v1.2.0, the parity checker was extended with two new modes that are specifically designed for the burn-in phase: bakeoff-winners auto-discovery and a configurable P&L correlation threshold.

### Configurable PnL Correlation Threshold

The `--pnl-correlation-threshold` flag controls how close the paper executor's PnL must correlate with the backtest replay to pass the parity check:

| Mode | Threshold | Use Case |
|------|-----------|----------|
| Default (omit flag) | 0.99 | Strict production gate (no behavior change) |
| Burn-in soft gate | 0.90 | Phase 88 7-day burn-in (slippage and timing differences expected) |

The threshold is displayed in the parity report output alongside the actual correlation value.

### Bakeoff-Winners Mode

Use `--bakeoff-winners` to auto-discover strategies from `strategy_bakeoff_results` (Phase 82 CPCV results) instead of specifying a `--signal-id`:

```bash
# Phase 88 burn-in parity check (soft gate: r >= 0.90)
python -m ta_lab2.scripts.executor.run_parity_check \
    --bakeoff-winners --start 2025-01-01 --end 2025-12-31 \
    --slippage-mode fixed --pnl-correlation-threshold 0.90

# Strict production parity check (hard gate: r >= 0.99)
python -m ta_lab2.scripts.executor.run_parity_check \
    --bakeoff-winners --start 2025-01-01 --end 2025-12-31 \
    --slippage-mode fixed --pnl-correlation-threshold 0.99
```

**Known data gap:** Phase 82 strategy evaluation results are stored in `strategy_bakeoff_results`, not in `backtest_trades`. When using `--bakeoff-winners`, the parity checker will log "No backtest trades found for strategy X -- bakeoff results in strategy_bakeoff_results". This is expected and is NOT a bug. The bakeoff mode does a best-effort correlation check using available fill data.

**Pass criteria for v1.2.0 burn-in:**
- **Majority of bakeoff winners pass:** > 50% of discovered bakeoff strategies pass at r >= 0.90
- **Failed strategies:** Documented in parity report and excluded from live trading candidate list

---

## 4.9b Signal Anomaly Gate (v1.2.0)

The signal anomaly gate (Phase 87) is a pre-execution validation step that checks signal counts against a rolling 14-day baseline. It runs automatically as part of the `--all` pipeline between Signals (Stage 12) and Stats/QC (Stage 20).

### What It Does

For each signal table (`signals_ema_crossover`, `signals_rsi_mean_revert`, `signals_atr_breakout`), the gate:
1. Counts today's new signal rows
2. Computes the 14-day rolling mean and standard deviation of daily counts
3. Calculates a z-score: `(today - mean) / std`
4. Flags anomalies if `abs(z) > 3.0` (configurable)

Results are written to `signal_anomaly_log` with status CLEAN or ANOMALY.

### Gate Exit Codes

| Exit Code | Meaning | Pipeline Action |
|-----------|---------|-----------------|
| 0 | All clean (no anomalies) | Pipeline continues normally |
| 2 | Signal anomaly detected | Pipeline logs BLOCKED, skips executor stage |
| 1 | Script error | Logged as error, pipeline continues (non-fatal) |

**Note:** A blocked signal gate (exit 2) does NOT halt the entire pipeline. Stats/QC, IC staleness check, pipeline log, and the completion Telegram alert still fire. The daily digest always reports gate status.

### Checking Gate Results

```bash
# Check gate results after pipeline run
python -m ta_lab2.scripts.signals.run_signal_anomaly_gate --dry-run

# View today's anomaly log
```

```sql
SELECT signal_table, signal_count, baseline_mean, z_score, status, checked_at
FROM signal_anomaly_log
WHERE DATE(checked_at) = CURRENT_DATE
ORDER BY checked_at DESC;
```

---

## 4.10 Validation Reports

Generate end-of-period validation reports for audit and record-keeping:

```bash
# Full validation report (Markdown + Jupyter notebook + 5 charts)
python -m ta_lab2.scripts.validation.generate_validation_report \
    --start-date 2025-01-01 --end-date 2025-03-01

# Text only (no charts, faster)
python -m ta_lab2.scripts.validation.generate_validation_report \
    --start-date 2025-01-01 --end-date 2025-03-01 --no-charts

# Without Jupyter notebook
python -m ta_lab2.scripts.validation.generate_validation_report \
    --start-date 2025-01-01 --end-date 2025-03-01 --no-notebook
```

**Output:**
- `reports/validation/V1_VALIDATION_REPORT.md` -- Summary with key metrics
- `reports/validation/V1_VALIDATION_REPORT.ipynb` -- Interactive Jupyter notebook
- 5 Plotly charts: equity curve, tracking error over time, slippage distribution, fill quality histogram, PnL waterfall

---

## 4.11 Paper Trading Monitoring Checklists

### Daily Checklist

```
[ ] Pipeline completed without FAIL stats
[ ] Kill switch status = active (trading enabled)
[ ] Macro gate status reviewed (no unexpected blocks)
[ ] No new drift pauses triggered
[ ] Order dead-letter table empty: SELECT count(*) FROM order_dead_letter
[ ] Position sizes within expected ranges
[ ] Fill prices reasonable (slippage within configured bounds)
[ ] Risk events table reviewed for unexpected gate triggers
```

### Weekly Checklist

```
[ ] Weekly QC digest reviewed (all stats PASS)
[ ] Weekly drift report generated and reviewed
[ ] Tracking error within bounds (< 3% cumulative)
[ ] Sharpe ratio consistent with backtest (within Monte Carlo CI)
[ ] No persistent circuit breaker trips
[ ] Override list clean (no stale or forgotten overrides)
[ ] Dashboard reviewed for anomalies
[ ] Telegram alerts verified (send test alert if quiet week)
```
