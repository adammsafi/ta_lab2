# Phase 113: VM Execution Deployment - Context

**Gathered:** 2026-04-01
**Status:** Ready for planning

<domain>
## Phase Boundary

Deploy the execution pipeline on the Oracle Singapore VM so it can run 24/7 independently of the local PC. Real-time price feeds for order management (fills, stops, take profits), daily signal sync from local, results sync back. Executor as systemd service with auto-restart.

Depends on: Phase 112 (pipeline separation), Phase 96 (executor activation).

</domain>

<decisions>
## Implementation Decisions

### Sync direction & payload
- **Signals (not features) pushed local->VM** after daily refresh completes -- signal generation stays on local as part of the daily refresh pipeline; VM executor is a pure signal consumer
- **Full execution state synced VM->local** -- orders, fills, positions, executor_run_log, drift_metrics, risk_events, dim_risk_state, paper_orders
- **SSH+COPY pattern reversed** -- reuse the proven SSH+psql COPY infrastructure (sync_hl_from_vm etc.), just flip direction. Consistent with existing codebase.
- **Signal push is event-triggered** -- fires automatically at end of daily refresh
- **Results pull on cron every 4-6 hours** -- keeps local dashboard fresh without complexity of on-demand triggers
- **Config tables (dim_executor_config, dim_risk_limits, dim_risk_state) auto-sync daily** with signal push, plus a manual `sync_config_to_vm` script for urgent changes (e.g., kill switch activation)

### Real-time price feeds
- **Real execution engine with live WebSocket prices** -- not bar-close simulation. Fill model upgraded to use live tick prices.
- **All three exchanges: Hyperliquid, Kraken, Coinbase** -- full WebSocket coverage
- **Stops and take profits auto-execute on live ticks** -- trigger fires, executor creates order at WebSocket tick price (plus slippage model), logged as stop/TP-triggered fill
- **Telegram alert on every stop/TP execution** -- auto-execute + notify for visibility

### VM database layout
- **Same `hyperliquid` DB, `public` schema** -- mirrors local DB structure. No schema-qualifying changes needed; executor code runs identical queries on VM and local.
- **Three-tier price resolution**: WebSocket feed (primary) -> HL collector tables (already on VM, second fallback) -> daily bar close (last resort)
- **Minimal executor table subset + dimension tables** (~20+ tables):
  - Signals: `signals_ema_crossover`, `signals_rsi_mean_revert`, `signals_atr_breakout`, `signals_macd_crossover`, `signals_ama_momentum`, `signals_ama_mean_reversion`, `signals_ama_regime_conditional`
  - Execution: `orders`, `fills`, `positions`, `paper_orders`, `executor_run_log`
  - Config: `dim_executor_config`, `dim_risk_limits`, `dim_risk_state`
  - Monitoring: `drift_metrics`, `risk_events`, `exchange_price_feed`
  - Dimensions: `dim_timeframe`, `dim_venues`, `dim_signals`, `dim_sessions`
  - Existing HL collector tables stay as-is (hl_candles, hl_assets, etc.)

### Executor autonomy & service model
- **Single systemd service, event-driven** -- WebSocket loop is the main event loop (always watching positions for stops/TPs). Signal processing triggers when new signals detected via watermark (`executor_processed_at IS NULL`).
- **Stale signal handling**: no new trades opened on stale signals; existing positions protected via WebSocket monitoring (stops/TPs continue). Telegram alert fired using existing `cadence_hours` threshold (default 26h) per strategy.
- **Auto-restart with backoff** -- `Restart=on-failure`, `RestartSec=30s` increasing to cap. Crash-loop circuit breaker (e.g., 5 restarts in 10 min) stops the service and sends Telegram alert.
- **No defensive mode / position reduction on stale signals** -- just halt new trades and alert. Manual decision from there.

### Claude's Discretion
- WebSocket client library choice (e.g., `websockets`, `aiohttp`)
- Async framework details (asyncio event loop structure)
- Exact crash-loop detection parameters (restart count, window)
- Systemd unit file specifics (environment, working directory, logging)
- Alembic migration strategy for VM DB table creation
- `exchange_price_feed` write frequency from WebSocket ticks (every tick vs. throttled)

</decisions>

<specifics>
## Specific Ideas

- Existing sync pattern (SSH + `psql COPY TO STDOUT` -> CSV pipe -> staging -> upsert) is the template for both directions
- `position_sizer.get_current_price()` already has a fallback chain (exchange_price_feed -> price_bars_multi_tf_u) -- extend it with HL collector tier
- Executor already uses NullPool (subprocess-safe) and watermark-based signal detection -- both carry over to VM deployment
- HL token-bucket rate limiter (1,200 weight/min, targets 1,000) is the reference pattern for TVC/CMC polling
- `cadence_hours` in `dim_executor_config` (default 26h) reused as staleness threshold -- no new config needed
- Existing Telegram notification infrastructure (`notifications/`) used for all alerts

</specifics>

<deferred>
## Deferred Ideas

- Feature generation on VM (would require full pipeline deployment -- much larger scope)
- Dashboard hosting on VM -- Phase 114
- Multi-VM executor redundancy / failover
- Exchange-side stop orders (placing stops on the exchange itself rather than monitoring locally)
- TVC/CMC REST polling for supplementary reference prices (RESEARCH.md correctly identifies this as non-essential for MVP; WebSocket feeds from HL/Kraken/Coinbase are sufficient for execution)

</deferred>

---

*Phase: 113-vm-execution-deployment*
*Context gathered: 2026-04-01*
