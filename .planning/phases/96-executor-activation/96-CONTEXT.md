# Phase 96: Executor Activation — Context

**Created:** 2026-03-29
**Phase Goal:** Paper executor runs live daily, generating real fills from IC-weighted signal scores with parity tracking and PnL attribution.

---

## 1. Strategy Selection & Config

### Decisions

- **All 7 signal generators** seeded in `dim_executor_config`: ema_trend (2 variants already in seed YAML), rsi_mean_revert, breakout_atr, macd_crossover, ama_momentum, ama_mean_reversion, ama_regime_conditional
- **Cadence_hours configurable per strategy** — each `dim_executor_config` row gets its own cadence value (some strategies are more time-sensitive than others)
- **BL decides all sizing** — executor uses Black-Litterman output weights for position sizing, not independent `position_fraction`. The executor becomes pure execution.
- **Asset universe = all unique IDs in `price_bars_multi_tf_u`** — not restricted to the 109 CMC assets. Includes Hyperliquid and any other venue data.

### Existing Infrastructure

- Seed YAML: `configs/executor_config_seed.yaml` (2 EMA strategies)
- Seed script: `src/ta_lab2/scripts/executor/seed_executor_config.py`
- Table DDL: `sql/executor/088_dim_executor_config.sql`

---

## 2. Signal Wiring & Replay Prevention

### Decisions

- **Two signal batches** in daily refresh:
  - Batch 1: EMA, RSI, ATR, MACD (no AMA dependency)
  - Batch 2: ama_momentum, ama_mean_reversion, ama_regime_conditional (depend on fresh AMA features)
- **Watermark set to `MAX(signal_ts)`** from each signals table on initial seed — prevents replay of historical signals on first activation
- **Stale threshold = 2x cadence_hours** per strategy — lenient enough to tolerate one missed run, strict enough to catch genuinely stale signals
- **Idempotent re-runs** — watermark-based: if signals already exist for a timestamp, skip. No duplicate fills on re-run.

### Existing Infrastructure

- Signal generators: `src/ta_lab2/signals/` (7 generators, 3 currently wired)
- Signal refresh orchestrator: `src/ta_lab2/scripts/signals/run_all_signal_refreshes.py`
- Daily refresh pipeline: `src/ta_lab2/scripts/run_daily_refresh.py` (signals stage at position 15/23)
- `SignalStateManager` handles per-signal-type watermarks

---

## 3. Scheduling & Burn-in Protocol

### Decisions

- **Manual execution only** — no Windows Task Scheduler. User manually triggers `run_daily_refresh --all` after loading data. OPS-03 requirement adjusted: "executor produces fills when manually triggered" rather than "runs daily via Task Scheduler."
- **7-day burn-in** before trusting executor output for parity tracking
- **Both alert mechanisms** for silent no-op detection:
  - `executor_run_log` records `fills_count` per run (monitoring query flags 0-fill runs)
  - Telegram alert via Phase 87 pipeline_alerts if executor ran and fills_count=0
- **Graduated rollback response**:
  - Minor issues (one strategy acting up): set `is_active=false` on that strategy's `dim_executor_config` row
  - Major issues (systemic problem across strategies): use existing `kill_switch_cli --flatten-all`
  - Thresholds to be defined during planning (e.g., >80% same-direction fills = minor, negative Sharpe after 7d = major)

---

## 4. Parity & Attribution Methodology

### Decisions

- **Live Sharpe computed two ways**, both compared to backtest:
  - Fill-to-fill returns (execution quality metric)
  - Mark-to-market daily returns (portfolio-level metric)
- **Beta benchmark at both levels**:
  - Per-asset-class drill-down: crypto positions benchmarked to BTC, equity positions to SPX, perps to underlying spot
  - Blended portfolio-level: single headline alpha number weighted by actual asset-class allocation
  - Framework must be extensible as new asset classes are added (equities, derivatives)
- **Dedicated `strategy_parity` table** for parity storage: (strategy, date, live_sharpe_fill, live_sharpe_mtm, bt_sharpe, ratio_fill, ratio_mtm)
- **PnL attribution persists to DB** — `pnl_attribution` table + CLI formatted output. Enables dashboarding and historical tracking.

### Critical Context

- **This is a multi-asset swing trading system**, not crypto-only. Crypto was the genesis, but the project targets swing opportunities across every asset class including equities and derivatives (options, leveraged perps).
- PnL attribution must NOT be framed as "alpha vs long-crypto bias" — it's "alpha vs market beta per asset class."
- Already have: crypto spot (CMC), crypto perps (Hyperliquid), equity indices (FRED: SPX, NASDAQ, DJIA coming in Phase 97).

---

## Deferred Ideas

- Automated Task Scheduler — revisit after manual workflow is proven stable
- Per-strategy asset-class restrictions — may be useful once equity/derivatives data is flowing
- Real-time intraday execution — out of scope per requirements (daily-batch system)

---

## Key Files Reference

| Component | Path |
|-----------|------|
| Executor config seed | `configs/executor_config_seed.yaml` |
| Executor config seeder | `src/ta_lab2/scripts/executor/seed_executor_config.py` |
| Executor config DDL | `sql/executor/088_dim_executor_config.sql` |
| Paper executor | `src/ta_lab2/scripts/executor/run_paper_executor.py` |
| Signal registry | `src/ta_lab2/signals/registry.py` |
| Signal refresh | `src/ta_lab2/scripts/signals/run_all_signal_refreshes.py` |
| Daily refresh pipeline | `src/ta_lab2/scripts/run_daily_refresh.py` |
| Black-Litterman | `src/ta_lab2/portfolio/black_litterman.py` |
| Kill switch CLI | `src/ta_lab2/scripts/risk/kill_switch_cli.py` |
| Pipeline alerts | Phase 87 Telegram integration |

---
*Created: 2026-03-29*
