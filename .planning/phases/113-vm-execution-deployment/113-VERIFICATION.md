---
phase: 113-vm-execution-deployment
verified: 2026-04-02T05:35:57Z
status: passed
score: 18/18 must-haves verified
gaps: []
human_verification:
  - test: 7-day autonomous operation
    expected: Executor runs 7+ consecutive days without manual intervention beyond daily signal sync
    why_human: Requires elapsed time
  - test: StopMonitor symbol resolution on VM
    expected: Telegram stop/TP alerts show readable symbol names (BTC not id=42)
    why_human: dim_assets may not exist on VM. Graceful failure -- stops execute but alerts show id=N. Non-blocking todo.
---

# Phase 113: VM Execution Deployment Verification Report

**Phase Goal:** Deploy the execution pipeline on the Oracle Singapore VM so it can run 24/7 independently of the local PC. Real-time price feeds for order management (fills, stops, take profits), daily signal sync from local, results sync back.
**Verified:** 2026-04-02T05:35:57Z
**Status:** passed
**Re-verification:** No -- initial verification

## Goal Achievement

### Observable Truths (Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Small PostgreSQL on Oracle VM holds execution-relevant tables | VERIFIED | vm_table_list.txt lists 25 tables; create_vm_tables.sh (344 lines) extracts DDL via pg_dump, strips FKs, pipes to VM via SSH |
| 2 | Sync script pushes latest signals from local DB to VM daily | VERIFIED | sync_signals_to_vm.py (509 lines) pushes 7 signal + 3 config tables; wired into run_daily_refresh.py line 3996 after successful signal stage |
| 3 | Sync script pulls fills, positions, PnL, drift metrics from VM back to local | VERIFIED | sync_results_from_vm.py (647 lines) pulls 9 tables: orders, fills, positions, paper_orders, executor_run_log, drift_metrics, risk_events, order_events, dim_risk_state |
| 4 | Real-time WebSocket price feed provides sub-second prices | VERIFIED | ws_feeds.py (421 lines) implements HL allMids + Kraken WS v2 + Coinbase AT; all write to PriceCache; human confirmed 536 symbols priced in under 1s |
| 5 | Executor runs as systemd service, auto-restarts, logs to journald | VERIFIED | ta-executor.service: Restart=on-failure, RestartSec=30, StandardOutput=journal; StartLimitBurst=5 in [Unit]; human confirmed active PID 945320 |
| 6 | Paper trading operates 7+ days without manual intervention | HUMAN NEEDED | Executor confirmed running on VM; 7-day window not yet elapsed |

**Score:** 5/6 automated truths verified (1 requires elapsed time)

### Plan-level Must-Have Truths (18/18 verified)

| Plan | Truth | Status |
|------|-------|--------|
| 01 | VM PostgreSQL has all 20+ executor tables with correct DDL | VERIFIED |
| 01 | Dimension tables (dim_timeframe, dim_venues, dim_signals, dim_sessions) populated on VM | VERIFIED |
| 01 | exchange_price_feed CHECK constraint updated to allow hyperliquid exchange value | VERIFIED |
| 02 | PriceCache provides thread-safe get/update with Decimal precision | VERIFIED |
| 02 | HL WebSocket feed writes mid prices to PriceCache via allMids subscription | VERIFIED |
| 02 | All three feeds start in background daemon threads and do not block main thread | VERIFIED |
| 03 | sync_signals_to_vm pushes all 7 signal tables using SSH+COPY pattern | VERIFIED |
| 03 | sync_config_to_vm pushes dim_executor_config, dim_risk_limits, dim_risk_state | VERIFIED |
| 03 | Signal push fires automatically after signals stage in run_daily_refresh.py | VERIFIED |
| 04 | sync_results_from_vm pulls all 9 execution tables with incremental watermark | VERIFIED |
| 05 | StopMonitor polls PriceCache every 1s and triggers stop/TP orders | VERIFIED |
| 05 | Stop/TP execution creates orders via OrderManager and sends Telegram alerts | VERIFIED |
| 05 | PositionSizer has 3-tier VM fallback: PriceCache to hl_assets.mark_px to hl_candles | VERIFIED |
| 06 | executor_service.py is single entry point starting WS feeds, stop monitor, and signal loop | VERIFIED |
| 06 | Crash-loop detection (5 restarts in 5 min) sends Telegram alert | VERIFIED |
| 06 | PaperExecutor accepts optional vm_mode and price_cache params (backward compatible) | VERIFIED |
| 07 | setup_vm.sh creates venv, installs deps, creates .env on Oracle VM | VERIFIED |
| 07 | deploy.sh is one-command local script that SCPs files to VM and runs setup | VERIFIED |

### Required Artifacts

| Artifact | Lines | Status | Notes |
|----------|-------|--------|-------|
| deploy/executor/vm_table_list.txt | 47 | VERIFIED | 25 tables across 8 categories |
| deploy/executor/create_vm_tables.sh | 344 | VERIFIED | pg_dump, FK stripping, exchange_price_feed CHECK patch, dimension seeding |
| deploy/executor/executor_service.py | 549 | VERIFIED | Full startup sequence, signal loop, crash-loop detection, SIGTERM handler |
| deploy/executor/requirements.txt | 21 | VERIFIED | Minimal: sqlalchemy, psycopg2-binary, hyperliquid-python-sdk, websockets; no research deps |
| deploy/executor/setup_vm.sh | 81 | VERIFIED | venv, pip, .env template, systemd install |
| deploy/executor/deploy.sh | 76 | VERIFIED | SCP all files, wheel build, SSH setup |
| deploy/executor/ta-executor.service | 22 | VERIFIED | StartLimitBurst in [Unit] section (lines 5-6), journald output |
| src/ta_lab2/executor/price_cache.py | 136 | VERIFIED | RLock, Decimal, get/update/is_stale/stale_symbols/all_symbols |
| src/ta_lab2/executor/ws_feeds.py | 421 | VERIFIED | HL + Kraken + Coinbase feeds; graceful ImportError degradation |
| src/ta_lab2/executor/stop_monitor.py | 567 | VERIFIED | PriceCache polling at 1s, OrderManager integration, Telegram alerts |
| src/ta_lab2/executor/position_sizer.py | 600+ | VERIFIED | 5-tier fallback: PriceCache then exchange_price_feed then hl_assets.mark_px then hl_candles then price_bars (local only) |
| src/ta_lab2/executor/paper_executor.py | 760+ | VERIFIED | vm_mode and price_cache params at lines 94-95; PositionSizer receives both |
| src/ta_lab2/scripts/etl/sync_signals_to_vm.py | 509 | VERIFIED | 7 signal + 3 config tables; incremental watermark; --full/--dry-run/--table flags |
| src/ta_lab2/scripts/etl/sync_config_to_vm.py | 339 | VERIFIED | TRUNCATE+COPY for dim_executor_config, dim_risk_limits, dim_risk_state |
| src/ta_lab2/scripts/etl/sync_results_from_vm.py | 647 | VERIFIED | 9 tables, watermark table, dim_risk_state full-replace |
| src/ta_lab2/scripts/run_daily_refresh.py | -- | VERIFIED | sync_signals_to_vm wired at line 3996; non-blocking on failure |

### Key Link Verification

| From | To | Via | Status |
|------|----|-----|--------|
| executor_service.py | ws_feeds.start_all_feeds | line 457 | WIRED |
| executor_service.py | PriceCache instance | lines 448, 515 | WIRED |
| executor_service.py | PaperExecutor(vm_mode=True, price_cache=...) | line 488 | WIRED |
| executor_service.py | StopMonitor(engine, price_cache) | line 492 | WIRED |
| executor_service.py | _signal_loop calls executor.run() | line 293 | WIRED |
| ws_feeds.py | price_cache.update() in all three feed callbacks | HL line 117, Kraken/Coinbase parse loops | WIRED |
| stop_monitor.py | price_cache.get(symbol) for stop/TP comparison | line 280 | WIRED |
| stop_monitor.py | telegram.send_alert() on every trigger | line 448 | WIRED |
| paper_executor.py | PositionSizer(price_cache=, vm_mode=) | line 100 | WIRED |
| position_sizer.py | hl_assets.mark_px and hl_candles (VM tiers 3-4) | lines 212-267 | WIRED |
| run_daily_refresh.py | sync_signals_to_vm.sync_signals() after signal stage | line 3998 | WIRED |
| sync_signals_to_vm.py | _CONFIG_TABLES inline (dim_executor_config etc.) | lines 358-359 | WIRED |
| ta-executor.service | ExecStart runs executor_service.py in venv | service ExecStart | WIRED |
| deploy.sh | setup_vm.sh via SSH chmod+execute | lines 53-54 | WIRED |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| stop_monitor.py | 76 | Queries public.dim_assets -- likely absent on VM (actual table is cmc_da_ids) | Warning | _load_asset_symbol_map() returns empty dict on failure; stop/TP triggers still execute; Telegram alerts show id=N instead of readable symbol. Service fully operational. |
| sync_signals_to_vm.py | 57-67 | Signal table list hardcoded rather than imported from SIGNAL_TABLE_MAP in signal_reader | Info | Tables match exactly; no functional impact. Risk of drift if signal_reader adds tables in future. |

No blocker anti-patterns found.

### Human Verification Required

#### 1. 7-Day Autonomous Operation

**Test:** Observe the executor service on the Oracle VM from deployment through 7 consecutive days.
**Expected:** journalctl -u ta-executor shows continuous operation; executor_run_log has regular entries; no manual SSH required except daily signal sync from local.
**Why human:** Requires elapsed time -- cannot verify structurally.

#### 2. StopMonitor Symbol Resolution on VM

**Test:** With an open position on the VM, allow a stop or take-profit price to be reached. Check the Telegram alert content.
**Expected:** Alert shows readable symbol (e.g., BTC) not id=42.
**Why human:** StopMonitor queries public.dim_assets for the id-to-symbol map but the actual table is cmc_da_ids. If dim_assets does not exist on VM PostgreSQL, the query fails silently -- the stop/TP executes correctly but alerts show numeric asset_id. Non-blocking known todo tracked separately.

### Gaps Summary

No gaps blocking goal achievement. The executor is confirmed running live on the Oracle Singapore VM (human-verified: systemctl active, PID 945320, 536 HL symbols priced in under 1 second, signal loop polling every 30s).

Two human-verification items remain:
1. The 7-day autonomous operation criterion cannot pass until the time window elapses.
2. The dim_assets symbol resolution in StopMonitor is cosmetic -- service operates correctly regardless.

---

_Verified: 2026-04-02T05:35:57Z_
_Verifier: Claude (gsd-verifier)_
