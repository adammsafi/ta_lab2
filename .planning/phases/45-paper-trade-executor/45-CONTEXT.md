# Phase 45: Paper-Trade Executor - Context

**Gathered:** 2026-02-24
**Status:** Ready for planning

<domain>
## Phase Boundary

Engine that reads signals from `cmc_signals`, generates paper orders, simulates fills, tracks positions via Phase 44's `OrderManager`, and verifies backtest parity. Runs on a schedule (daily for 1D strategies) or on-demand. Supports multiple concurrent strategies. Does NOT include risk controls (Phase 46), drift guard (Phase 47), or live order submission.

**Requirements:** EXEC-01, EXEC-02, EXEC-03, EXEC-04, EXEC-05

**Upstream dependencies locked:**
- Phase 43: Two exchanges (Coinbase + Kraken), REST polling, `paper_orders` table, `ExchangeConfig`, exchange price feed
- Phase 44: 7-state order lifecycle (`created -> submitted -> partial_fill -> filled -> cancelled -> rejected -> expired`), `cmc_orders`/`cmc_fills`/`cmc_positions` tables, `OrderManager.process_fill()` atomic transactions, pessimistic locking, dead letter on failure, paper order promotion from `paper_orders` to `cmc_orders`

</domain>

<decisions>
## Implementation Decisions

### Execution scheduling & trigger
- **Invocation model:** Scheduled cron/task as primary execution model. Matches 1D strategy cadence
- **Dual entry point:** Both a stage in `run_daily_refresh.py` (after signals) AND a standalone CLI (`python -m ...`). Pipeline has `--no-execute` flag to skip executor stage
- **Signal deduplication:** Both watermark-based (last_processed_signal_ts) AND status flag on signals. Belt-and-suspenders: watermark for efficiency, status flag for correctness
- **Multi-strategy support:** Both V1 strategies run concurrently. Executor processes signals from all active strategies. Positions tracked per strategy independently
- **Stale signal guard:** Fail with Telegram alert if signals haven't been refreshed (latest signal older than expected cadence). Strict: no stale execution ever
- **Configuration:** DB-backed config table (`dim_executor_config` or similar) for active strategies, sizing rules, slippage model, execution parameters. Changeable without redeployment

### Fill simulation model
- **Fill pricing:** Configurable. Two modes: (1) next-bar open price (default, matches backtest convention), (2) exchange mid-price from `exchange_price_feed` when available. Strategy config selects mode
- **Slippage model:** Volume-adaptive base slippage + random noise from a researched distribution to simulate real-world variability. Researcher should investigate appropriate slippage distributions for crypto spot markets (e.g., log-normal, power-law)
- **Rejection/partial fills:** Configurable. Rejection rate (e.g., 1%) and partial fill probability can be set to stress-test the order lifecycle. Exercises Phase 44's edge case handling
- **Execution delay:** Configurable delay parameter (default 0). Fill timestamp = signal_ts + delay. Infrastructure for Phase 47 drift comparison

### Signal-to-order translation
- **Position sizing:** Three built-in modes plus custom:
  1. Fixed fraction of portfolio (e.g., 10%) — V1 default per bake-off recommendation
  2. Regime-adjusted — base fraction modified by regime context (reduce in high-vol regimes)
  3. Signal-strength scaled — size proportional to signal confidence score
  4. Custom — user-defined sizing function passed as config
  - CLI flags select mode; parameters in DB config
- **Strategy isolation:** Independent positions per strategy. Each strategy manages its own position. Total exposure = sum of all strategies. Clear P&L attribution per strategy
- **Directional support:** Both long AND short positions. Short = borrow-and-sell simulation for spot markets
- **Unchanged signals:** Rebalance to target. On every run, calculate target position from signal + sizing model and rebalance if current position has drifted (due to price movement changing position %). More active management, better tracking

### Backtest parity mode
- **Dual invocation:** `--replay-historical` flag on executor for quick checks, plus a dedicated parity report script for detailed comparison
- **Output layering:** Quick pass/fail with summary stats (max divergence, correlation, tracking error) for CI-friendly checks + detailed per-day comparison report with divergence time-series and attribution on demand (`--verbose` or separate script)

### Claude's Discretion
- Exact definition of "parity match" tolerance — likely mode-dependent: exact epsilon match when slippage=0 and delay=0 (pure next-bar-open), statistical match when simulation noise is enabled
- Whether parity check compares against existing `cmc_backtest_runs` DB results or re-runs backtester from scratch — choose based on Phase 47 drift guard needs and practical speed considerations
- DB-backed config seeding approach — YAML seeds DB (version-controlled defaults) vs DB-only management
- Executor config table DDL design (table name, columns, defaults)
- Fill simulation noise distribution — researcher investigates, Claude implements
- How short selling is represented in paper trading (margin tracking, borrow fees, or simplified)

</decisions>

<specifics>
## Specific Ideas

- V1 bake-off selected 2 EMA trend strategies: ema_trend(17,77) and ema_trend(21,50). Both fail MaxDD gate. V1 deployment at 10% position fraction (not 50% from backtest) + circuit breaker at 15% portfolio DD
- Volume-adaptive slippage + noise: user specifically wants the researcher to investigate the correct distribution for crypto spot slippage simulation
- Phase 44's two-phase simulation (paper orders go `created -> submitted`, then separate fill simulator processes them) fits naturally with configurable delay and rejection
- Multi-strategy with independent positions means cmc_positions needs (asset_id, exchange, strategy_id) granularity, extending Phase 44's (asset_id, exchange) design
- Rebalance-to-target on unchanged signals means every run generates orders even when signal hasn't changed — need to distinguish "rebalance" orders from "signal change" orders in logging

</specifics>

<deferred>
## Deferred Ideas

- Risk controls (kill switch, position caps, daily loss stops, circuit breaker) — Phase 46
- Drift guard (parallel backtest comparison, auto-pause) — Phase 47
- Live order submission to exchange — future phase
- WebSocket-triggered execution (event-driven mode) — future enhancement
- Multi-asset portfolio optimization (cross-asset sizing) — future enhancement

</deferred>

---

*Phase: 45-paper-trade-executor*
*Context gathered: 2026-02-24*
