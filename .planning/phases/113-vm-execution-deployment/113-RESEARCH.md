# Phase 113: VM Execution Deployment - Research

**Researched:** 2026-04-01
**Domain:** WebSocket price feeds, systemd services, SSH+COPY sync, async/sync bridge, VM PostgreSQL setup
**Confidence:** HIGH (most areas verified against official docs or codebase; LOW for TVC/CMC rate limits)

## Summary

Phase 113 deploys the paper executor on the Oracle Singapore VM (161.118.209.59) as a 24/7 systemd service with real-time WebSocket price feeds from Hyperliquid, Kraken, and Coinbase. The local machine pushes signals to the VM after daily refresh; the VM pulls fills/positions back to local every 4-6 hours. Both sync directions use the proven SSH+psql COPY pattern already in the codebase.

The executor code is synchronous (SQLAlchemy, psycopg2). WebSocket feeds are async. The integration pattern is: run asyncio event loop in a background thread, push tick prices into a thread-safe `asyncio.Queue` (or plain `queue.Queue`), and have the synchronous executor drain the queue on each cycle. `asyncio.to_thread()` is the correct way to call synchronous DB operations from inside an async context. The Hyperliquid official Python SDK has a built-in `WebsocketManager` (threading-based, not asyncio) that ping-keepalives every 50 seconds and dispatches callbacks — this may be simpler than raw `websockets` for HL. For Kraken and Coinbase, the `websockets 16.0` library with the `async for websocket in connect(...)` infinite-iterator pattern handles reconnection with exponential backoff automatically.

VM PostgreSQL table creation uses `pg_dump --schema-only -t tablename` from local, piped to `psql` on the VM via SSH — identical infrastructure to existing deploy scripts. No Alembic on VM; SQL scripts only. The `exchange_price_feed` table has a CHECK constraint that must be updated to allow 'hyperliquid' as an exchange value.

**Primary recommendation:** Use the Hyperliquid Python SDK's `WebsocketManager` for HL WebSocket (already thread-based, proven), and `websockets 16.0` async client for Kraken and Coinbase. Run all three in separate threads/coroutines feeding a shared thread-safe price dict. Systemd unit with `Restart=on-failure`, `RestartSec=30`, and `StartLimitBurst=5 / StartLimitIntervalSec=300` in `[Unit]` section for crash-loop protection.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| hyperliquid-python-sdk | latest (pip) | HL WebSocket subscription | Official SDK, `WebsocketManager` handles ping/reconnect, already threading-based |
| websockets | 16.0 | Kraken + Coinbase WebSocket | Most mature async WS library, built-in reconnection via infinite iterator |
| psycopg2-binary | existing | VM PostgreSQL driver | Already in project, used in deploy scripts |
| SQLAlchemy + NullPool | existing | Synchronous DB access | Project standard; NullPool required for long-running process + multiproc |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| logging-journald | 0.x (PyPI) | Structured journald logging | Allows `journalctl -u executor -f` to show structured fields |
| requests | existing | Telegram alerts, CMC/TVC REST polling | Already in notifications/telegram.py |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| hyperliquid-python-sdk WebsocketManager | raw websockets asyncio | SDK is simpler but threading-based (not asyncio). For production simplicity, SDK wins for HL |
| websockets 16.0 | websocket-client (sync) | websockets has better reconnection primitives; websocket-client is what the HL SDK uses internally |

**Installation (on VM, inside executor venv):**
```bash
pip install hyperliquid-python-sdk websockets psycopg2-binary requests
```

## Architecture Patterns

### Recommended Project Structure
```
deploy/executor/
├── executor_service.py      # main entry point, starts all threads
├── price_feed/
│   ├── hl_feed.py           # HL WebSocket via hyperliquid-python-sdk
│   ├── kraken_feed.py       # Kraken WS v2 via websockets asyncio
│   └── coinbase_feed.py     # Coinbase Advanced Trade WS via websockets asyncio
├── stop_monitor.py          # continuous position monitoring loop
├── sync_signals_to_vm.py    # local→VM signal push (runs on local, not VM)
├── sync_results_to_local.py # VM→local results pull (runs on local)
└── setup_vm.sh              # one-time VM setup (venv, tables, systemd unit)
```

### Pattern 1: Thread-Safe Price Dictionary (Central Price Store)
**What:** A shared `dict` protected by a `threading.Lock` (or `threading.RLock`) stores the latest mid price per asset symbol. All three WebSocket feeds write to this dict. The stop monitor and executor read from it.
**When to use:** This is the right model when WebSocket callbacks fire in their own threads (HL SDK is threading-based) and the executor reads synchronously.

```python
# Source: codebase pattern + official threading docs
import threading
from decimal import Decimal

class PriceCache:
    """Thread-safe last-price cache for all assets."""
    def __init__(self):
        self._prices: dict[str, Decimal] = {}
        self._lock = threading.RLock()

    def update(self, symbol: str, price: float) -> None:
        with self._lock:
            self._prices[symbol] = Decimal(str(price))

    def get(self, symbol: str) -> Decimal | None:
        with self._lock:
            return self._prices.get(symbol)
```

### Pattern 2: Hyperliquid WebSocket via Official SDK
**What:** Use `WebsocketManager` from the official SDK. Subscribe to `allMids` for all mid prices. The SDK sends ping every 50 seconds, runs in its own thread.
**When to use:** HL is the primary exchange and already has collector tables on the VM.

```python
# Source: https://github.com/hyperliquid-dex/hyperliquid-python-sdk
from hyperliquid.info import Info
from hyperliquid.utils import constants

info = Info(constants.MAINNET_API_URL, skip_ws=False)

def on_all_mids(msg):
    # msg["data"]["mids"] is a dict: {"BTC": "95000.0", "ETH": "3200.0", ...}
    mids = msg["data"]["mids"]
    for symbol, price_str in mids.items():
        price_cache.update(symbol, float(price_str))

info.subscribe({"type": "allMids"}, on_all_mids)
# SDK WebsocketManager runs in background thread automatically
```

**IMPORTANT:** The SDK's `WebsocketManager` does NOT implement automatic reconnection at the application level — it relies on `websocket-client`'s built-in reconnect. If the SDK drops connection and doesn't reconnect, the service process will need its systemd restart to recover. Monitor for stale timestamps in PriceCache.

### Pattern 3: Kraken WebSocket v2 with Auto-Reconnect
**What:** Use `websockets 16.0` `async for websocket in connect(...)` infinite iterator. Subscribe to `ticker` channel. Run in asyncio event loop in dedicated thread.

```python
# Source: websockets docs + Kraken v2 API docs (wss://ws.kraken.com/v2)
import asyncio
import json
import websockets

KRAKEN_WS_URL = "wss://ws.kraken.com/v2"

async def kraken_feed(price_cache: PriceCache, symbols: list[str]):
    subscribe_msg = {
        "method": "subscribe",
        "params": {
            "channel": "ticker",
            "symbol": symbols,   # e.g. ["BTC/USD", "ETH/USD"]
        }
    }
    async for websocket in websockets.connect(KRAKEN_WS_URL):
        try:
            await websocket.send(json.dumps(subscribe_msg))
            async for message in websocket:
                data = json.loads(message)
                if data.get("channel") == "ticker":
                    for item in data.get("data", []):
                        price_cache.update(item["symbol"], item["last"])
        except websockets.ConnectionClosed:
            continue  # auto-reconnect via infinite iterator

def run_kraken_thread(price_cache, symbols):
    asyncio.run(kraken_feed(price_cache, symbols))
```

### Pattern 4: Coinbase Advanced Trade WebSocket
**What:** Public `ticker` channel on `wss://advanced-trade-ws.coinbase.com` — no auth needed for price data. Subscribe within 5 seconds of connect or server disconnects.

```python
# Source: https://docs.cdp.coinbase.com/coinbase-app/advanced-trade-apis/guides/websocket
import asyncio
import json
import websockets

COINBASE_WS_URL = "wss://advanced-trade-ws.coinbase.com"

async def coinbase_feed(price_cache: PriceCache, product_ids: list[str]):
    subscribe_msg = {
        "type": "subscribe",
        "product_ids": product_ids,   # e.g. ["BTC-USD", "ETH-USD"]
        "channel": "ticker"
    }
    async for websocket in websockets.connect(COINBASE_WS_URL):
        try:
            await websocket.send(json.dumps(subscribe_msg))
            async for message in websocket:
                data = json.loads(message)
                if data.get("channel") == "ticker":
                    for event in data.get("events", []):
                        for ticker in event.get("tickers", []):
                            price_cache.update(ticker["product_id"], float(ticker["price"]))
        except websockets.ConnectionClosed:
            continue
```

### Pattern 5: Stop/TP Monitor Loop (Continuous Monitoring)
**What:** Synchronous loop (runs in its own thread) that polls PriceCache every N seconds for all open positions. For each position with a stop or TP price set, compare current price. If triggered, create stop/TP order via OrderManager and send Telegram alert.
**When to use:** This is the right pattern because we have at most dozens of positions (not thousands), so O(N) per-tick scan is fine.

```python
# Architectural pattern — not from a specific library
import time
import threading

class StopMonitor(threading.Thread):
    def __init__(self, engine, price_cache, poll_interval_secs=1.0):
        super().__init__(daemon=True)
        self.engine = engine
        self.price_cache = price_cache
        self.poll_interval = poll_interval_secs

    def run(self):
        while True:
            self._check_all_positions()
            time.sleep(self.poll_interval)

    def _check_all_positions(self):
        # Load open positions with stop_price and tp_price from DB
        # For each: compare PriceCache.get(symbol) against thresholds
        # If triggered: create order, log fill, send Telegram alert
        ...
```

**Key design point:** Open positions are loaded from DB on each iteration (or cached with a 10-second TTL to avoid DB hammering). A triggered stop creates an order record and immediately marks the position as flat — idempotent via a DB lock/UPDATE WHERE status='open'.

### Pattern 6: Local→VM Signal Push (Reversed SSH+COPY)
**What:** Mirror of `_vm_copy_to_stdout` but in reverse: run `psql COPY (SELECT...) TO STDOUT` locally, pipe the CSV via SSH to `psql COPY tablename FROM STDIN` on the VM.

```python
# Source: codebase pattern (sync_hl_from_vm.py reversed)
import subprocess, tempfile
from pathlib import Path

def _copy_local_to_vm(
    local_sql: str,
    vm_table: str,
    conflict_cols: list[str],
    ssh_key: str,
    vm_host: str,
    vm_user: str,
    vm_db_user: str,
    vm_db_pass: str,
    vm_db: str,
    timeout: int = 300,
) -> int:
    """Push local table rows to VM via SSH+COPY pipe."""
    # Step 1: export CSV from local DB
    local_csv = _local_copy_to_csv(local_sql)
    if not local_csv.strip():
        return 0
    # Step 2: write to temp file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
        f.write(local_csv)
        tmp_path = f.name
    # Step 3: pipe to VM via SSH + psql COPY FROM STDIN
    vm_cmd = (
        f"PGPASSWORD={vm_db_pass} psql -h 127.0.0.1 -U {vm_db_user} -d {vm_db} "
        f"-c \"COPY {vm_table} FROM STDIN WITH CSV\""
    )
    ssh_cmd = [
        "ssh", "-i", ssh_key, "-o", "StrictHostKeyChecking=accept-new",
        f"{vm_user}@{vm_host}", vm_cmd
    ]
    with open(tmp_path, 'r') as csv_file:
        result = subprocess.run(ssh_cmd, stdin=csv_file, capture_output=True,
                                text=True, timeout=timeout)
    Path(tmp_path).unlink(missing_ok=True)
    if result.returncode != 0:
        raise RuntimeError(f"SSH COPY TO VM failed: {result.stderr}")
    return local_csv.count('\n')
```

**Gotcha:** The existing pattern uses `capture_output=True` which collects all output in memory before writing. For large signal tables, stream via `stdin=` from file directly (shown above). The `ON CONFLICT DO NOTHING` clause must be added to the COPY destination or done via a staging-table upsert.

### Pattern 7: VM Table Creation via pg_dump --schema-only
**What:** Extract DDL from local DB for the execution tables, pipe to VM via SSH.

```bash
# Run from local machine
TABLES="-t orders -t fills -t positions -t paper_orders -t executor_run_log \
        -t dim_executor_config -t dim_risk_limits -t dim_risk_state \
        -t risk_events -t exchange_price_feed -t drift_metrics \
        -t dim_timeframe -t dim_venues -t dim_signals -t dim_sessions \
        -t signals_ema_crossover -t signals_rsi_mean_revert \
        -t signals_atr_breakout -t signals_macd_crossover \
        -t signals_ama_momentum -t signals_ama_mean_reversion \
        -t signals_ama_regime_conditional"

pg_dump --schema-only $TABLES \
    postgresql://user:pass@localhost/marketdata \
  | ssh -i ~/Downloads/oracle_sg_keys/ssh-key-2026-03-10.key \
        ubuntu@161.118.209.59 \
        "PGPASSWORD=hlpass psql -h 127.0.0.1 -U hluser -d hyperliquid"
```

**Note:** pg_dump will also dump FK constraints, CHECK constraints, and indexes. Review the dump before applying — FK constraints to tables NOT on the VM (e.g., references to price_bars_multi_tf) must be dropped from the DDL. The `exchange_price_feed` CHECK constraint `CHECK (exchange IN ('coinbase', 'kraken', 'binance', 'bitfinex', 'bitstamp'))` must be updated to add 'hyperliquid'.

### Pattern 8: Systemd Service Unit File
**What:** Standard systemd unit for a long-running Python async service.

```ini
# /etc/systemd/system/ta-executor.service
[Unit]
Description=TA Lab2 Paper Executor with WebSocket Price Feeds
After=network-online.target postgresql.service
Wants=network-online.target
# Crash-loop circuit breaker: stop after 5 failures in 5 minutes
StartLimitIntervalSec=300
StartLimitBurst=5

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/executor
EnvironmentFile=/home/ubuntu/executor/.env
ExecStart=/home/ubuntu/executor/venv/bin/python executor_service.py
Restart=on-failure
RestartSec=30
# journald logging: stdout/stderr captured automatically
StandardOutput=journal
StandardError=journal
SyslogIdentifier=ta-executor
# Give Python time to finish cleanup
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
```

**CRITICAL systemd gotcha:** `StartLimitBurst` and `StartLimitIntervalSec` MUST be in `[Unit]` section, NOT `[Service]`. If placed in `[Service]`, systemd silently ignores them and the service loops forever.

**After crash-loop triggers:** Send Telegram alert from an `ExecStopPost=` script, or use the `OnFailure=` directive to invoke a notifier unit.

### Pattern 9: PositionSizer Price Resolution — Third Tier for VM
**What:** Extend `get_current_price()` to check `hl_candles` (or `hl_assets.mark_px`) before falling back to daily bar close. On the VM, `price_bars_multi_tf_u` does NOT exist, so the current fallback chain is broken.

```python
# Three-tier chain for VM:
# 1. PriceCache (WebSocket live tick) — sub-second
# 2. hl_assets.mark_px (updated by HL collector every 6h) — fallback
# 3. hl_candles latest close — last resort (no price_bars_multi_tf_u on VM)
```

**Implication for planning:** `position_sizer.get_current_price()` needs a VM-aware version or a configurable fallback chain. The simplest approach: inject a `PriceCache` reference into `PositionSizer` and check it first.

### Anti-Patterns to Avoid
- **Calling synchronous SQLAlchemy from asyncio event loop directly:** Blocks the event loop. Use `asyncio.to_thread()` or run sync code in dedicated threads outside the event loop.
- **Placing StartLimitBurst in [Service] section:** Silently ignored by systemd; service restarts forever.
- **Using COPY without staging table for conflict resolution on VM:** Direct COPY to a table with conflicts will error. Use temp-table + INSERT...ON CONFLICT pattern as in `_upsert_from_csv()`.
- **Hardcoding HL API URL without checking mainnet vs testnet:** Use `constants.MAINNET_API_URL` from the SDK.
- **Expecting SDK auto-reconnect to be reliable:** The HL SDK `WebsocketManager` has no application-level reconnection logic; it relies on `websocket-client` internals. Monitor PriceCache staleness explicitly.
- **Writing WebSocket tick prices to `exchange_price_feed` at full tick rate:** This table was designed for REST snapshots. Write to it at a rate-limited interval (e.g., 1 update/minute per asset) or use a separate `ws_price_cache` table.

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| HL WebSocket subscription | Custom WS client | hyperliquid-python-sdk WebsocketManager | Official SDK has ping logic, subscription routing, callback dispatch |
| Kraken/Coinbase WS reconnect | Manual backoff loop | `websockets.connect()` infinite iterator | Built-in exponential backoff, handles network errors and 5xx HTTP errors |
| Thread-safe price storage | Custom lock patterns | `threading.RLock` + plain dict | Standard library, no external deps, proven pattern |
| Async/sync bridge | asyncio.run_until_complete hacks | `asyncio.to_thread()` (Python 3.9+) | Clean, standard, properly handles thread pool lifecycle |
| SSH pipe direction (local→VM) | SCP + psql import | `psql COPY FROM STDIN` piped via SSH subprocess | Exact mirror of existing sync pattern, zero new infrastructure |
| VM table DDL | Write DDL by hand | `pg_dump --schema-only -t table` | Guaranteed to match local schema including indexes, constraints |
| Crash-loop detection | Python-side counter | systemd `StartLimitBurst/StartLimitIntervalSec` | OS-level, works even if Python crashes before starting |

**Key insight:** Three-quarters of this phase reuses existing infrastructure — the sync pattern, executor code, Telegram notifications, and Hyperliquid collector tables. The genuinely new work is: WebSocket feeds + PriceCache + StopMonitor + systemd unit + reversed sync direction.

## Common Pitfalls

### Pitfall 1: exchange_price_feed CHECK Constraint Missing 'hyperliquid'
**What goes wrong:** WebSocket feed writer tries to INSERT into `exchange_price_feed` with `exchange='hyperliquid'`. Fails with CHECK constraint violation.
**Why it happens:** The table was designed for REST exchanges (coinbase, kraken, binance, bitfinex, bitstamp). Hyperliquid was WebSocket-only from the start and was never added to the allowed list.
**How to avoid:** Before deploying, ALTER TABLE to add 'hyperliquid' to the exchange CHECK constraint, both on local DB and on VM.
**Warning signs:** `psycopg2.errors.CheckViolation` on exchange_price_feed insert.

### Pitfall 2: price_bars_multi_tf_u Does Not Exist on VM
**What goes wrong:** `position_sizer.get_current_price()` fallback path queries `price_bars_multi_tf_u`. On the VM, this table does not exist (too large to sync, not in the minimal table subset). Returns `ValueError: No price available`.
**Why it happens:** The executor was designed for local use where this table exists. VM has only the minimal subset.
**How to avoid:** Override the fallback chain on VM to use `hl_assets.mark_px` (or `hl_candles` latest close). Pass a `PriceCache` reference as the primary source.
**Warning signs:** Executor fails on signal processing immediately after deployment.

### Pitfall 3: systemd StartLimit Parameters in Wrong Section
**What goes wrong:** Service restarts indefinitely despite `StartLimitBurst=5`, crash-looping forever.
**Why it happens:** `StartLimitBurst` and `StartLimitIntervalSec` in `[Service]` section are silently ignored by systemd. They must be in `[Unit]`.
**How to avoid:** Always place `StartLimitIntervalSec=300` and `StartLimitBurst=5` in `[Unit]` section. Verify with `systemctl show ta-executor | grep StartLimit`.
**Warning signs:** Service shows 10, 20, 30 restart attempts in `journalctl`.

### Pitfall 4: HL SDK WebsocketManager Has No Application-Level Reconnect
**What goes wrong:** HL WebSocket silently drops after network interruption. PriceCache becomes stale. Stop orders never trigger. Executor keeps trading with stale prices.
**Why it happens:** The SDK's `WebsocketManager` pings every 50 seconds but does not have explicit reconnection logic at the application level beyond what `websocket-client` provides internally. No timeout checking is in the SDK layer.
**How to avoid:** Add a staleness check to PriceCache: if `last_update_time` for any tracked symbol is older than 120 seconds, log a warning and send a Telegram alert. Consider restarting the SDK subscription.
**Warning signs:** PriceCache last-update timestamps stop advancing.

### Pitfall 5: Signal Push Race Condition (Local Refresh Writes While Push Reads)
**What goes wrong:** Local daily refresh is writing new signals while the `sync_signals_to_vm` script is reading and pushing. VM receives a partial batch, misses some signals.
**Why it happens:** The push is triggered at end of daily refresh, but if triggered mid-write, signal rows in intermediate states (partially written) get pushed.
**How to avoid:** Push script should use a watermark: `WHERE ts > last_push_watermark AND executor_processed_at IS NULL`. The refresh writes signals atomically per-strategy batch. Ensure push fires AFTER the last strategy's signal commit.
**Warning signs:** Executor on VM sees signals but misses some assets.

### Pitfall 6: Coinbase WebSocket Disconnects if No Subscribe Within 5 Seconds
**What goes wrong:** Coinbase server closes connection if no subscription message sent within 5 seconds of connect.
**Why it happens:** Documented Coinbase behavior. Applies even to public (no-auth) channels.
**How to avoid:** In the `async for websocket in connect(...)` loop, send the subscribe message immediately before entering the message receive loop. Do not do any DB lookups between connect and subscribe.
**Warning signs:** Coinbase feed never receives any data, PriceCache always empty for Coinbase assets.

### Pitfall 7: psql COPY FROM STDIN Pipe with Large CSV Hits SSH Timeout
**What goes wrong:** Signal push of a large batch times out. SSH connection drops mid-pipe. VM table has partial data.
**Why it happens:** Signal tables can be large (7 strategies × hundreds of assets × multiple TFs). SSH `ConnectTimeout=15` only applies to connection setup, but `ServerAliveInterval` settings govern keepalive during data transfer.
**How to avoid:** Use `ServerAliveInterval=30 ServerAliveCountMax=5` in SSH options. Batch signals by strategy or by date chunk. Use the existing `timeout=300` parameter in `_vm_copy_to_stdout`.
**Warning signs:** `subprocess.TimeoutExpired` or `BrokenPipeError` during push.

## Code Examples

### Hyperliquid allMids Subscription
```python
# Source: https://github.com/hyperliquid-dex/hyperliquid-python-sdk
from hyperliquid.info import Info
from hyperliquid.utils import constants

# MAINNET_API_URL = "https://api.hyperliquid.xyz"
info = Info(constants.MAINNET_API_URL, skip_ws=False)

def on_all_mids(msg):
    # msg structure: {"channel": "allMids", "data": {"mids": {"BTC": "95000.0", ...}}}
    for symbol, price_str in msg["data"]["mids"].items():
        price_cache.update(symbol, float(price_str))

info.subscribe({"type": "allMids"}, on_all_mids)
# WebsocketManager runs in daemon thread; main thread continues
```

### Kraken WS v2 Ticker (Public, No Auth)
```python
# Source: https://docs.kraken.com/api/docs/websocket-v2/ticker
# Endpoint: wss://ws.kraken.com/v2  (public, no auth needed)
subscribe = {
    "method": "subscribe",
    "params": {"channel": "ticker", "symbol": ["BTC/USD", "ETH/USD"]}
}
# Subscribe response: {"method":"subscribe","result":{"channel":"ticker","snapshot":true,"symbol":"BTC/USD"},"success":true}
# Data message: {"channel":"ticker","data":[{"symbol":"BTC/USD","bid":95000,"ask":95001,"last":95000.5,...}],"type":"update"}
```

### Coinbase Advanced Trade WS (Public Ticker)
```python
# Source: https://docs.cdp.coinbase.com/coinbase-app/advanced-trade-apis/guides/websocket
# Endpoint: wss://advanced-trade-ws.coinbase.com  (public, no auth)
subscribe = {
    "type": "subscribe",
    "product_ids": ["BTC-USD", "ETH-USD"],
    "channel": "ticker"
}
# Must send within 5 seconds of connect or server closes connection
# Data: {"channel":"ticker","events":[{"tickers":[{"product_id":"BTC-USD","price":"95000.00",...}]}]}
```

### Systemd Unit with Crash-Loop Protection
```ini
# /etc/systemd/system/ta-executor.service
[Unit]
Description=TA Lab2 Paper Executor
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=300
StartLimitBurst=5

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/executor
EnvironmentFile=/home/ubuntu/executor/.env
ExecStart=/home/ubuntu/executor/venv/bin/python executor_service.py
Restart=on-failure
RestartSec=30
StandardOutput=journal
StandardError=journal
SyslogIdentifier=ta-executor
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
```

### Reversed SSH+COPY (Local → VM)
```bash
# Pattern: local psql COPY TO STDOUT → SSH pipe → VM psql COPY FROM STDIN
# Source: mirror of _vm_copy_to_stdout pattern in sync_hl_from_vm.py

psql "$LOCAL_DB_URL" \
    -c "COPY (SELECT * FROM signals_ema_crossover WHERE ts > '2026-03-31') TO STDOUT WITH CSV" \
  | ssh -i ~/Downloads/oracle_sg_keys/ssh-key-2026-03-10.key \
        -o StrictHostKeyChecking=accept-new \
        -o ServerAliveInterval=30 \
        ubuntu@161.118.209.59 \
        "PGPASSWORD=hlpass psql -h 127.0.0.1 -U hluser -d hyperliquid \
         -c 'COPY signals_ema_crossover FROM STDIN WITH CSV'"
# For upsert: use staging table + INSERT...ON CONFLICT on VM side
```

### asyncio.to_thread for Sync DB Calls from Async Context
```python
# Source: Python 3.9+ standard library docs
import asyncio

async def async_price_monitor(engine, price_cache):
    while True:
        # Run synchronous DB call without blocking event loop
        positions = await asyncio.to_thread(load_open_positions, engine)
        for pos in positions:
            price = price_cache.get(pos.symbol)
            if price and price <= pos.stop_price:
                await asyncio.to_thread(trigger_stop, engine, pos, price)
        await asyncio.sleep(1.0)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Sync WebSocket (websocket-client) | Async WebSocket (websockets 16.0) | 2022-2024 | Auto-reconnect via infinite iterator pattern; cleaner asyncio integration |
| Cron-based executor | systemd service with auto-restart | Always best practice | Crash recovery without cron gaps; proper logging to journald |
| Bar-close fill prices | Live WebSocket tick prices | Phase 113 | Stops/TPs now trigger on real market prices, not delayed bar closes |
| REST price polling | WebSocket streaming | Phase 113 | Sub-second latency for stop/TP monitoring vs 1-5 minute polling lag |

**Deprecated/outdated:**
- websocket-client (sync library): Still works but has no built-in reconnect primitives; websockets 16.0 preferred for new code
- `exchange_price_feed` as price source for live monitoring: Was designed for periodic REST snapshots; not suitable for sub-second WebSocket prices

## Open Questions

1. **HL SDK thread safety with multiple subscriptions**
   - What we know: SDK uses threading.Thread with a single WebSocket connection per Info instance; callbacks dispatch in that thread
   - What's unclear: Is it safe to call `info.subscribe()` multiple times for different channels (allMids + trades) on the same Info instance?
   - Recommendation: Subscribe to `allMids` only (covers all assets in one subscription); avoid per-asset subscriptions which create O(N) subscriptions

2. **exchange_price_feed write frequency**
   - What we know: Currently written by REST price-check scripts at infrequent intervals. WebSocket gives sub-second ticks.
   - What's unclear: Should the WS price writer write every tick (potentially millions of rows/day) or throttle to 1/minute per asset?
   - Recommendation: Mark as Claude's discretion; write once per minute per asset as a heartbeat rather than every tick. Keep high-frequency price in PriceCache memory only.

3. **CMC REST polling rate limit on VM**
   - What we know: CMC free Basic plan = 30 calls/minute, 10,000 credits/month (~333/day). CMC already has a daily cron collector on the VM.
   - What's unclear: Is additional REST polling for reference prices needed given CMC collector already runs daily?
   - Recommendation: CMC is daily-bar reference data only; no additional polling needed. Existing daily collector is sufficient.

4. **TVC REST polling rate limit**
   - What we know: tvdatafeed is an unofficial wrapper. No documented rate limits. Existing collector uses 3-second delay between requests (`REQUEST_DELAY = 3`).
   - What's unclear: Exact rate limits; risk of IP ban with additional polling.
   - Recommendation: TVC is daily-bar reference data only; no additional polling needed. Existing daily collector is sufficient. Do not add real-time TVC polling.

5. **VM Python version**
   - What we know: VM runs Ubuntu. websockets 16.0 requires Python ≥ 3.10.
   - What's unclear: Current Python version on the Oracle VM (not checked).
   - Recommendation: Verify with `python3 --version` on VM in setup script. If < 3.10, install pyenv or use deadsnakes PPA.

## Sources

### Primary (HIGH confidence)
- Hyperliquid Python SDK: https://github.com/hyperliquid-dex/hyperliquid-python-sdk — WebsocketManager implementation, ping interval, subscription format
- Hyperliquid WebSocket docs: https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/subscriptions — allMids, trades, l2Book subscription types
- Kraken WebSocket v2 docs: https://docs.kraken.com/api/docs/websocket-v2/ticker — ticker channel subscription/response format, wss://ws.kraken.com/v2 endpoint
- Coinbase Advanced Trade WebSocket: https://docs.cdp.coinbase.com/coinbase-app/advanced-trade-apis/guides/websocket — endpoint URLs, public channels, 5-second subscribe requirement
- websockets 16.0 PyPI: https://pypi.org/project/websockets/ — current version, Python ≥ 3.10 requirement
- Project codebase: sync_hl_from_vm.py, deploy/tvc/setup_vm.sh, deploy/cmc/setup_vm.sh — established patterns for SSH+COPY, systemd cron, VM venv setup
- Python asyncio docs — `asyncio.to_thread()` for sync/async bridge

### Secondary (MEDIUM confidence)
- systemd StartLimitBurst placement: https://copyprogramming.com/howto/systemd-s-startlimitintervalsec-and-startlimitburst-never-work — verified against multiple sources that [Unit] section is required
- websockets reconnect pattern: https://websocket.org/guides/languages/python/ — `async for websocket in connect()` infinite iterator
- CMC rate limits: https://coinmarketcap.com/api/documentation/guides/errors-and-rate-limits — 30 calls/minute on free plan (verified via official CMC docs link)
- DeepWiki HL SDK analysis: https://deepwiki.com/hyperliquid-dex/hyperliquid-python-sdk/6.3-working-with-websockets — SDK architecture, 50-second ping, no application-level reconnect

### Tertiary (LOW confidence)
- TVC rate limits: No official documentation found. 3-second inter-request delay observed in existing tvc_collector.py; treat as empirical conservative bound.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — official SDK docs and PyPI verified
- Architecture: HIGH — patterns derived from existing codebase + official docs
- Pitfalls: HIGH for known gotchas (CHECK constraint, systemd section placement, Coinbase 5s timeout) verified against official docs; MEDIUM for HL SDK reconnect behavior (SDK source analyzed)
- Rate limits (TVC): LOW — no official documentation found

**Research date:** 2026-04-01
**Valid until:** 2026-05-01 (WebSocket API specs are stable; SDK versions may update)
