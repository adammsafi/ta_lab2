# Part 7: Path to Production

## Overview

This part covers the journey from research to live trading. It is organized as a sequence of gates: you must pass each gate before proceeding to the next. The gates exist to protect you from deploying strategies that look good in backtests but fail in real markets.

The path is: Research → Paper Trading → Live Trading. Each transition has explicit go/no-go criteria.

---

## 7.1 The Journey: Research → Paper → Live

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        THE PRODUCTION PATH                               │
│                                                                         │
│  PHASE 1: RESEARCH                        PHASE 2: PAPER TRADING       │
│  ┌───────────────────────┐                ┌───────────────────────┐    │
│  │ ✓ IC Analysis         │                │ ✓ Executor configured │    │
│  │ ✓ Feature Experiments │                │ ✓ Risk gates active   │    │
│  │ ✓ Triple Barrier      │    GATE 1      │ ✓ Kill switch tested  │    │
│  │ ✓ Meta-Labeling       │───────────────►│ ✓ Drift < 3% TE      │    │
│  │ ✓ Optuna Sweep        │  "Backtest     │ ✓ 30+ days running    │    │
│  │ ✓ CPCV (PBO < 0.10)  │   Parity OK"   │ ✓ Weekly reports OK   │    │
│  │ ✓ Monte Carlo CI > 0  │                │ ✓ Telegram alerts on  │    │
│  └───────────────────────┘                └───────────┬───────────┘    │
│                                                        │                │
│                                                    GATE 2              │
│  PHASE 3: LIVE TRADING                    "Paper Sharpe               │
│  ┌───────────────────────┐                 within MC CI"              │
│  │ ✓ Exchange API keys   │                     │                      │
│  │ ✓ Sandbox tested      │◄────────────────────┘                      │
│  │ ✓ Min allocation      │                                            │
│  │ ✓ Real fills verified │                                            │
│  │ ✓ Gradual ramp-up     │                                            │
│  └───────────────────────┘                                            │
└─────────────────────────────────────────────────────────────────────────┘
```

**Gate 1 (Research → Paper):** Your backtest results are statistically valid, not overfit, the paper executor produces identical results to the backtest (parity check with zero slippage or r >= 0.90 with slippage), and the v1.2.0 smoke test passes. See also: v1.2.0 additions to Gate 1 below.

**Gate 2 (Paper → Live):** Paper trading has been running for 30+ days (7-day burn-in passed + 23+ additional days), the Sharpe ratio is within the Monte Carlo confidence interval from research, drift is under control, and all monitoring systems are working.

### Gate 1 (v1.2.0) -- Additional Criteria

In v1.2.0, Gate 1 (Research → Paper) was extended with three additional checks:

| Check | Threshold | Command |
|-------|-----------|---------|
| Smoke test passing | All 26 checks pass (exit 0) | `python -m ta_lab2.scripts.integration.smoke_test` |
| Parity check (bakeoff winners) | r >= 0.90 (burn-in soft gate) | See Section 4.9a in Part 4 |
| GARCH forecasts | No persistent convergence failures (< 3 consecutive days failed per asset) | Check `garch_diagnostics` table |

---

## 7.1a v1.2.0 Burn-In Protocol

Before transitioning to full paper trading, complete a 7-day burn-in to validate the entire v1.2.0 pipeline under real market conditions.

### Purpose

The burn-in validates that all 21 pipeline stages operate correctly over multiple days, that GARCH convergence is stable, that the signal anomaly gate does not produce false positives, and that paper fills are being generated at expected rates.

### Pre-Burn-In Setup

**Step 1: Run the smoke test** to verify all data prerequisites are met before starting:

```bash
python -m ta_lab2.scripts.integration.smoke_test
```

All 26 checks must pass (exit 0) before starting the burn-in. If any check fails, resolve the issue and re-run.

**Step 2: Verify parity** with bakeoff winners at the relaxed 0.90 threshold:

```bash
python -m ta_lab2.scripts.executor.run_parity_check \
    --bakeoff-winners --start 2025-01-01 --end 2025-12-31 \
    --slippage-mode fixed --pnl-correlation-threshold 0.90
```

A majority (> 50%) of discovered strategies should pass at r >= 0.90 to proceed.

### Daily Burn-In Command

Run the full 21-stage pipeline every day during the burn-in period:

```bash
python -m ta_lab2.scripts.run_daily_refresh \
    --all --ids all --paper-start YYYY-MM-DD --continue-on-error
```

Replace `YYYY-MM-DD` with the actual date paper trading started (first day of burn-in). Use the same `--paper-start` value every day.

### Daily Status Report

After each pipeline run, generate the burn-in status report:

```bash
python -m ta_lab2.scripts.integration.daily_burn_in_report \
    --burn-in-start YYYY-MM-DD
```

This report queries 8 health metrics and produces one of three verdicts:
- **ON TRACK** -- All metrics within bounds, continue burn-in
- **WARNING** -- Tracking error > 5% or other soft threshold crossed; investigate but continue
- **STOP** -- Kill switch triggered or drift pause active; halt and resolve before continuing

The report is also sent to Telegram (if configured) for passive monitoring.

### Burn-In Success Criteria

To declare burn-in successful and transition to full paper trading:

```
[ ] 7 consecutive days of pipeline completion without manual intervention
[ ] Kill switch: Never triggered (or if triggered, resolved and burn-in restarted)
[ ] Drift pause: Never triggered (or if triggered, resolved and burn-in restarted)
[ ] Paper PnL: Not catastrophically negative (not -20% or worse cumulative)
[ ] Daily burn-in report: ON TRACK verdict on at least 5 of 7 days
[ ] GARCH forecasts: Generating for all 7+ main assets every day
[ ] Signal anomaly gate: No false BLOCK verdicts (check signal_anomaly_log)
```

### Early Stop Criteria

Halt the burn-in (restart from Day 1 after resolution) ONLY if:
- Kill switch fires automatically (Gate 1 risk engine activation)
- Drift monitor pauses execution (`run_drift_monitor` returns drift pause)

Do NOT stop burn-in for:
- Poor PnL (unless catastrophically negative at -20% or worse)
- GARCH convergence failures for individual assets (these are expected)
- WARNING verdicts on individual daily reports (investigate but continue)

### Monitoring During Burn-In

| Tool | Purpose | Frequency |
|------|---------|-----------|
| `daily_burn_in_report` | Status summary + verdict | Daily (after pipeline run) |
| Streamlit dashboard | Deep dives into fills, positions, risk | Daily (morning review) |
| Telegram alerts | Critical events (kill switch, drift pause) | Real-time (passive) |
| `run_drift_report` | Weekly drift analysis | Weekly (end of burn-in) |

---

## 7.2 Wiring Telegram Alerts

Telegram integration is the primary alerting mechanism. It is used by the paper executor, weekly QC digest, stats runners, and macro gate system.

### Current Alert Sources

| Source | Trigger | Severity |
|--------|---------|----------|
| Stats runner | FAIL status detected | CRITICAL |
| Paper executor | Stale signal (> 48h) | WARNING |
| Kill switch | Activated/deactivated | CRITICAL |
| Drift monitor | TE > threshold | WARNING |
| Macro gates | Regime shift detected | INFO |
| Weekly digest | Scheduled delivery | INFO |

### Setup Steps

**1. Create a Telegram Bot:**
- Message `@BotFather` on Telegram
- Send `/newbot`
- Name it (e.g., "ta_lab2_alerts")
- Save the bot token (looks like `123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11`)

**2. Get Your Chat ID:**
- Send any message to your new bot
- Visit `https://api.telegram.org/bot<TOKEN>/getUpdates`
- Find your `chat_id` in the response JSON (a numeric ID like `123456789`)

**3. Configure Environment:**
```env
# Add to db_config.env or set as environment variables
TELEGRAM_BOT_TOKEN=<your-bot-token>
TELEGRAM_CHAT_ID=<your-chat-id>
```

**4. Test:**
```python
from ta_lab2.notifications.telegram import send_critical_alert
send_critical_alert("test", "Telegram integration working!")
```

If you receive the message on Telegram, the integration is working.

### Using Telegram in the Pipeline

```bash
# Weekly digest with Telegram delivery (default)
python -m ta_lab2.scripts.stats.weekly_digest

# Weekly digest WITHOUT Telegram
python -m ta_lab2.scripts.stats.weekly_digest --no-telegram

# EMA refresh with Telegram alerts on validation errors
python -m ta_lab2.scripts.emas.run_all_ema_refreshes --ids all --validate --alert-on-validation-error
```

---

## 7.3 Running Experiments End-to-End

Here is the complete experiment workflow, from defining a new feature through to promoting it for paper trading. Each step builds on the output of the previous step.

### The Complete 11-Step Workflow

```bash
# Step 1: Ensure pipeline is current (features need fresh bars + EMAs)
python -m ta_lab2.scripts.run_daily_refresh --all --ids all

# Step 2: Define feature in YAML
# Edit configs/experiments/features.yaml (see Part 3 for YAML syntax)

# Step 3: Run experiment (dry-run first to verify configuration)
python -m ta_lab2.scripts.experiments.run_experiment \
    --feature my_new_feature \
    --train-start 2020-01-01 \
    --train-end 2025-12-31 \
    --tf 1D \
    --dry-run

# Step 4: Run for real and write to DB
python -m ta_lab2.scripts.experiments.run_experiment \
    --feature my_new_feature \
    --train-start 2020-01-01 \
    --train-end 2025-12-31 \
    --tf 1D \
    --yes

# Step 5: Check IC results (is the feature predictive?)
python -m ta_lab2.scripts.analysis.run_ic_eval \
    --asset-id 1 --tf 1D --feature my_new_feature \
    --train-start 2020-01-01 --train-end 2025-12-31
# Decision: IC > 0.03 on 3+ horizons with BH p < 0.05? → Continue
# Otherwise → Modify feature or discard

# Step 6: Generate triple barrier labels (ML target variable)
python -m ta_lab2.scripts.labeling.refresh_triple_barrier_labels \
    --all --tf 1D

# Step 7: Run meta-labeling (can the model improve on the signal?)
python -m ta_lab2.scripts.labeling.run_meta_labeling \
    --all --signal-type ema_crossover

# Step 8: ML hyperparameter sweep
python -m ta_lab2.scripts.ml.run_optuna_sweep \
    --asset-ids 1,2 --n-trials 100 --log-experiment
# Decision: Best Sharpe > 1.0? → Continue
# Sharpe 0.5-1.0? → Investigate improvements
# Sharpe < 0.5? → Strategy is too weak

# Step 9: Overfitting test
python -m ta_lab2.scripts.labeling.run_cpcv_backtest
# Decision: PBO < 0.10? → Continue
# PBO > 0.10? → Strategy is likely overfit, reject

# Step 10: Monte Carlo confidence interval
python -m ta_lab2.scripts.analysis.run_monte_carlo --run-id <uuid> --write
# Decision: 5th percentile Sharpe > 0? → Continue
# 5th percentile Sharpe < 0? → Strategy may not be truly profitable

# Step 11: If all pass, promote the feature
python -m ta_lab2.scripts.experiments.promote_feature --feature my_new_feature
```

---

## 7.4 Running and Analyzing Backtests

### Generate Backtest Runs

Backtests use vectorbt for vectorized simulation:

```bash
python -m ta_lab2.scripts.backtests.run_backtest
```

### Analyzing Results

```bash
# Monte Carlo on a backtest run
python -m ta_lab2.scripts.analysis.run_monte_carlo --run-id <uuid>

# QuantStats tear sheet (comprehensive performance report)
python -m ta_lab2.scripts.analysis.run_quantstats_report

# Bakeoff scoring (compare multiple strategies head-to-head)
python -m ta_lab2.scripts.analysis.run_bakeoff_scoring

# Strategy selection from bakeoff results
python -m ta_lab2.scripts.analysis.select_strategies

# Generate formatted scorecard
python -m ta_lab2.scripts.analysis.generate_bakeoff_scorecard
```

### Key Metrics to Evaluate

| Metric | Good | Warning | Reject |
|--------|------|---------|--------|
| Annualized Sharpe | > 1.0 | 0.5 - 1.0 | < 0.5 |
| Max Drawdown | < 15% | 15% - 25% | > 25% |
| Win Rate | > 45% | 35% - 45% | < 35% |
| Profit Factor | > 1.5 | 1.0 - 1.5 | < 1.0 |
| PBO (CPCV) | < 0.10 | 0.10 - 0.20 | > 0.20 |
| MC Sharpe 5th pct | > 0.3 | 0.0 - 0.3 | < 0.0 |
| Calmar Ratio | > 1.0 | 0.5 - 1.0 | < 0.5 |

### When a Backtest is "Good Enough" for Paper

All of these must be checked before enabling paper trading:

```
[ ] Sharpe > 1.0 (annualized, after costs)
[ ] Max drawdown < 20%
[ ] PBO < 0.10 (not overfit)
[ ] Monte Carlo 5th percentile Sharpe > 0
[ ] Win rate > 40% with profit factor > 1.3
[ ] Consistent across multiple assets (not just BTC)
[ ] Consistent across regimes (not just bull markets)
[ ] Reasonable trade frequency (not too few, not too many)
[ ] Slippage-adjusted returns still positive
[ ] Backtest parity check passes (paper executor matches backtest with zero slippage)
```

---

## 7.5 Wiring Up Exchanges

### Supported Exchanges

| Exchange | Auth Method | Status |
|----------|-------------|--------|
| Coinbase | JWT ES256 (EC private key) | Fully implemented |
| Kraken | HMAC-SHA512 | Fully implemented |
| Binance | API Key + Secret | Adapter exists |
| Bitfinex | API Key + Secret | Adapter exists |
| Bitstamp | API Key + Secret | Adapter exists |
| HyperLiquid | API Key + Secret | Adapter exists |

### Configuring Exchange Credentials

```python
from ta_lab2.connectivity.factory import get_exchange

# Coinbase (CDP format key with EC private key)
coinbase = get_exchange(
    "coinbase",
    api_key="organizations/<org_id>/apiKeys/<key_id>",
    api_secret="-----BEGIN EC PRIVATE KEY-----\n...",
    is_sandbox=True  # Always start with sandbox!
)

# Kraken
kraken = get_exchange(
    "kraken",
    api_key="your-api-key",
    api_secret="your-api-secret"
)
```

### Exchange Integration Phases

The path to live exchange integration follows four phases. Do not skip phases.

```
┌─────────────────────────────────────────────────────────┐
│ EXCHANGE INTEGRATION PHASES                              │
│                                                          │
│ Phase A: Sandbox Testing                                 │
│   [ ] Configure sandbox credentials                      │
│   [ ] Verify authentication works                        │
│   [ ] Place test orders on sandbox                       │
│   [ ] Verify fills match expected behavior               │
│   [ ] Accumulate 100+ sandbox fills                      │
│                                                          │
│ Phase B: Read-Only Production                            │
│   [ ] Configure production credentials (read-only keys)  │
│   [ ] Fetch live prices and compare to CMC data          │
│   [ ] Monitor orderbook depth                            │
│   [ ] Verify funding rate data (if perps)                │
│                                                          │
│ Phase C: Minimum Viable Live Trading                     │
│   [ ] Enable trading permissions on production keys      │
│   [ ] Start with 1% of intended allocation               │
│   [ ] Run paper executor in parallel with live           │
│   [ ] Compare fill prices (paper vs live)                │
│   [ ] Monitor for 2+ weeks                               │
│                                                          │
│ Phase D: Gradual Ramp-Up                                 │
│   [ ] Increase allocation: 1% → 10% → 25% → 50% → 100% │
│   [ ] Enable Telegram alerts for every live fill         │
│   [ ] Daily reconciliation (live vs paper)               │
│   [ ] Weekly Sharpe comparison (live vs paper vs MC CI)  │
│   [ ] Full allocation when live Sharpe within MC CI      │
└─────────────────────────────────────────────────────────┘
```

### Exchange Sandbox Testing Example

```python
from ta_lab2.connectivity.factory import get_exchange
from ta_lab2.connectivity.models import ExchangeConfig

# Step 1: Connect to sandbox
exchange = get_exchange("coinbase", config=ExchangeConfig(is_sandbox=True))

# Step 2: Verify authentication
balance = exchange.get_balance()
print(f"Sandbox balance: {balance}")

# Step 3: Place test order
order = exchange.place_order(
    symbol="BTC-USD",
    side="buy",
    type="market",
    quantity=0.001
)
print(f"Order placed: {order}")

# Step 4: Verify fill
fill = exchange.get_order(order.order_id)
print(f"Fill price: {fill.avg_fill_price}, Fill qty: {fill.filled_qty}")
```

### Parity Check (Paper vs Exchange)

```bash
python -m ta_lab2.scripts.executor.run_parity_check \
    --signal-id 1 --start 2025-01-01 --end 2025-02-01 \
    --slippage-mode zero
```

---

## 7.6 Paper → Live: Go/No-Go Criteria

### Mandatory (All Must Pass)

| Criterion | Threshold | How to Verify |
|-----------|-----------|---------------|
| Paper trading duration | >= 30 calendar days | Check `executor_run_log` earliest entry |
| Tracking Error (TE) | < 3% cumulative | Run `run_drift_report` |
| Kill switch tested | At least 1 activate/disable cycle | Check `risk_events` for kill_switch events |
| Macro gates tested | At least 1 gate trigger observed | Check `dim_macro_gate_state` |
| Circuit breaker tested | At least 1 trip + recovery | Check `risk_events` for circuit_breaker events |
| Paper Sharpe ratio | Within Monte Carlo 95% CI | Compare paper Sharpe to backtest MC CI bounds |
| Dead-letter queue | Empty (0 failed orders) | `SELECT count(*) FROM order_dead_letter` |
| Drift report | No persistent drift pauses | Check `cmc_drift_pause` table |
| Weekly QC digest | 4+ consecutive weeks all PASS | Review weekly digest history |
| Telegram alerts | Working and verified | Send test alert |

### Recommended (Strongly Advised)

| Criterion | Threshold | Notes |
|-----------|-----------|-------|
| Multiple strategies active | >= 2 strategies | Diversification reduces risk |
| Multiple assets | >= 3 assets trading | Not over-concentrated |
| Exchange sandbox tested | >= 100 sandbox fills | Verify API integration reliability |
| Regime coverage | Both bull and bear observed | Strategy not just tested in one regime |
| Override governance | At least 1 override cycle | Tested: create → monitor → revert |

---

## 7.7 Streamlit Dashboard

### Launch

```bash
streamlit run src/ta_lab2/dashboard/app.py
```

### Pages

| Page | Content | Primary Use |
|------|---------|-------------|
| 1. Landing | Dashboard home, system status | Quick health check |
| 2. Pipeline Monitor | Bars, EMAs, regimes, stats status | Pipeline verification |
| 3. Research Explorer | IC scoring, feature experiments | Research analysis |
| 4. Asset Stats | Asset statistics, correlation heatmaps | Cross-asset analysis |
| 5. Experiments | Feature experiment registry and results | Experiment tracking |
| 6. Trading | P&L, fills, positions | Paper trading monitoring |
| 7. Risk Controls | Risk limits, gates, overrides | Risk status |
| 8. Drift Monitor | Drift metrics, response tiers | Execution quality |
| 9. Executor Status | Paper executor run logs | Executor health |
| 10. Macro | Macro regimes, FRED features, HMM states | Macro environment |

### Cache

Default cache TTL: 300 seconds (5 minutes). Configurable via the sidebar widget. Lower the TTL during active trading monitoring.

---

## 7.8 Operational Runbook

### Daily Routine (Morning)

```bash
# 1. Check system health (is trading enabled?)
python -m ta_lab2.scripts.risk.kill_switch_cli status

# 2. Sync FRED data (get latest macro indicators)
python -m ta_lab2.scripts.etl.sync_fred_from_vm

# 3. Run full pipeline (all stages, all assets)
python -m ta_lab2.scripts.run_daily_refresh --all --ids all \
    --paper-start 2025-01-01 --continue-on-error --verbose

# 4. Check for failures (verify data quality)
python -m ta_lab2.scripts.stats.run_all_stats_runners --verbose

# 5. Review dashboard (visual check for anomalies)
streamlit run src/ta_lab2/dashboard/app.py
```

### Weekly Routine (End of Week)

```bash
# 1. Weekly QC digest (aggregate PASS/WARN/FAIL + Telegram)
python -m ta_lab2.scripts.stats.weekly_digest

# 2. Weekly drift report (paper vs backtest comparison)
python -m ta_lab2.scripts.drift.run_drift_report

# 3. Review macro regime shifts (any significant changes?)
python -m ta_lab2.scripts.risk.macro_gate_cli status

# 4. Review and clear any stale overrides
python -m ta_lab2.scripts.risk.override_cli list
```

### Monthly Routine

```bash
# 1. Full validation report (comprehensive period review)
python -m ta_lab2.scripts.validation.generate_validation_report \
    --start-date <month-start> --end-date <month-end>

# 2. IC re-evaluation (are features still predictive?)
python -m ta_lab2.scripts.analysis.run_ic_eval \
    --asset-id 1 --all-features \
    --train-start <rolling-3yr-start> --train-end <today>

# 3. Full stats rebuild (catch any accumulated drift)
python -m ta_lab2.scripts.stats.run_all_stats_runners --full-refresh

# 4. Memory health check (clean stale AI memories)
# Via MCP: memory_health tool with staleness_days=90

# 5. FRED VM purge (keep 60 days on VM to save disk)
python -m ta_lab2.scripts.etl.sync_fred_from_vm --purge-dry-run 60
python -m ta_lab2.scripts.etl.sync_fred_from_vm --purge 60
```

---

## 7.9 Next Steps Summary

### Immediate (Wire Now)

| Task | Difficulty | Impact | How |
|------|-----------|--------|-----|
| Configure Telegram bot token | Easy | Enables all alert channels | See Section 7.2 |
| Seed executor configs | Easy | Enables paper trading | `seed_executor_config` |
| Run first IC sweep | Medium | Identifies predictive features | See Part 3 |
| Generate first validation report | Medium | Establishes baseline | `generate_validation_report` |

### Short-Term (Week 1-2)

| Task | Difficulty | Impact | How |
|------|-----------|--------|-----|
| Run experiments on top IC features | Medium | Feature discovery | See Section 7.3 |
| Generate triple barrier labels | Medium | ML training targets | See Part 3 |
| Run Optuna sweep | Medium | Optimized model parameters | See Part 3 |
| Set up exchange sandbox | Medium | Pre-production testing | See Section 7.5 |
| Run CPCV on best strategy | Medium | Overfitting guard | See Part 3 |

### Medium-Term (Week 3-4)

| Task | Difficulty | Impact | How |
|------|-----------|--------|-----|
| Start paper trading | Low | Execution validation | See Part 4 |
| Daily pipeline automation (cron/Task Scheduler) | Medium | Hands-free operation | Schedule `run_daily_refresh` |
| Weekly drift reviews | Low | Quality assurance | See Section 7.8 |
| Build additional signal types | High | Strategy diversification | Define YAML features |

### Long-Term (Month 2+)

| Task | Difficulty | Impact | How |
|------|-----------|--------|-----|
| Exchange sandbox testing (100+ fills) | Medium | Live preparation | See Section 7.5 |
| Paper Sharpe vs backtest comparison | Low | Go/no-go decision | Compare metrics |
| Minimum viable live trading (1% allocation) | High | Real-world validation | See Section 7.5 Phase C |
| Gradual ramp-up to target allocation | Medium | Scale to full operation | See Section 7.5 Phase D |
