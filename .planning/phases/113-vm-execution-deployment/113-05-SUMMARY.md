---
phase: 113-vm-execution-deployment
plan: 05
subsystem: executor
tags: [stop-monitor, take-profit, price-cache, websocket, vm-deployment, position-sizer, hyperliquid, threading]

# Dependency graph
requires:
  - phase: 113-02
    provides: PriceCache (thread-safe, Decimal, staleness), ws_feeds.py WebSocket daemon threads
  - phase: 96
    provides: OrderManager, FillData, CanonicalOrder, PaperExecutor executor infrastructure
provides:
  - StopMonitor daemon thread — polls PriceCache every 1s, auto-executes stops/TPs with Telegram alerts
  - PositionSizer.get_price() — VM-aware 5-tier price fallback (PriceCache -> exchange_price_feed -> hl_assets -> hl_candles -> price_bars)
  - PositionSizer.__init__(price_cache, vm_mode) — backward-compatible stateful constructor
affects:
  - 113-06 (executor service main entry point — will use both StopMonitor and PositionSizer.get_price)
  - 113-07 (systemd deploy — StopMonitor started from executor_service.py)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "threading.Thread daemon with stop event, pending_triggers set, 10s position cache TTL"
    - "5-tier price fallback chain: PriceCache -> REST snapshot -> HL mark_px -> HL candles -> local bars"
    - "dim_listings join for CMC asset_id -> HL asset_id symbol resolution (VM tiers)"
    - "Module-level tier helper functions (_get_from_*) for composability"

key-files:
  created:
    - src/ta_lab2/executor/stop_monitor.py
  modified:
    - src/ta_lab2/executor/position_sizer.py

key-decisions:
  - "StopMonitor queries orders JOIN positions (not positions alone) because stop_price/tp_price live on orders"
  - "Used orders.limit_price as tp_price — limit orders with limit_price serve as take-profit targets"
  - "10s position cache TTL balances DB load vs responsiveness for at most dozens of positions"
  - "pending_triggers set prevents double-trigger within a single scan cycle"
  - "Static get_current_price() preserved unchanged; new get_price() instance method added alongside it"
  - "vm_mode=False default ensures zero behavior change for all existing callers"
  - "dim_listings join used for HL tiers so CMC asset_id -> HL symbol resolution is consistent with codebase"

patterns-established:
  - "StopMonitor: threading.Thread daemon with _stop_event, _pending_lock, _open_orders TTL cache"
  - "PositionSizer dual-mode: stateless static methods (original) + stateful get_price() (new)"
  - "Module-level private helpers for each price tier enable unit testing without class instantiation"

# Metrics
duration: 5min
completed: 2026-04-02
---

# Phase 113 Plan 05: Stop/TP Monitor + VM Price Fallback Summary

**StopMonitor daemon thread auto-executes stop-loss and take-profit closes from live PriceCache ticks; PositionSizer extended with 5-tier VM-aware price chain (PriceCache -> exchange_price_feed -> hl_assets.mark_px -> hl_candles -> price_bars) with zero backward-compatibility impact**

## Performance

- **Duration:** 5 min
- **Started:** 2026-04-02T04:19:11Z
- **Completed:** 2026-04-02T04:23:27Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- `StopMonitor` — daemon thread polling PriceCache every 1s; creates market close order + processes fill + sends Telegram alert when stop or TP crosses; idempotent via pending_triggers set; cancels original order post-fill
- `PositionSizer.get_price()` — VM-aware 5-tier fallback resolves price from WebSocket cache, REST feed, HL mark_px, HL candles, or local bars depending on context; fixes the VM deployment blocker (Pitfall 2 from RESEARCH.md)
- Full backward compatibility: all existing callers using `PositionSizer.get_current_price(conn, asset_id)` are unaffected

## Task Commits

Each task was committed atomically:

1. **Task 1: Create StopMonitor real-time stop/TP monitor** - `c0c25542` (feat)
2. **Task 2: Extend PositionSizer with VM-aware price fallback** - `09daa665` (feat)

## Files Created/Modified

- `src/ta_lab2/executor/stop_monitor.py` — New: StopMonitor thread class with _load_asset_symbol_map, _apply_slippage, trigger detection, _create_close_order, _cancel_original_order
- `src/ta_lab2/executor/position_sizer.py` — Modified: added __init__, get_price(), 5 module-level tier helpers (_resolve_symbol, _get_from_exchange_price_feed, _get_from_hl_assets_mark_px, _get_from_hl_candles, _get_from_price_bars)

## Decisions Made

- **orders.limit_price as tp_price:** The positions table has no tp_price column. The plan says "stop_price IS NOT NULL OR tp_price IS NOT NULL". Existing schema stores TP targets as limit orders with a limit_price. StopMonitor reads `o.limit_price AS tp_price` for order types that include stop/limit/stop_limit/market, so the query finds relevant pending orders.
- **dim_assets for symbol resolution (not dim_listings):** StopMonitor uses `dim_assets.symbol` for PriceCache lookup (consistent with how HL feeds publish symbols). PositionSizer's VM tiers use `dim_listings` join for the CMC→HL asset_id mapping (consistent with `derivatives_input.py`).
- **Static get_current_price() preserved intact:** Refactored to delegate to `_get_price_from_feed_or_bars()` so behavior is byte-for-byte identical. New `get_price()` instance method is the entry point for the extended chain.
- **5 bps default slippage on stop/TP fills:** Conservative default matching typical paper trading assumptions.

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None — no external service configuration required. StopMonitor is wired into the VM executor service in plan 113-06.

## Next Phase Readiness

- StopMonitor ready for integration into `executor_service.py` (plan 113-06)
- PositionSizer.get_price() ready for use on VM where `price_bars_multi_tf_u` is absent
- Both components have clean import paths and verified with `python -c "from ... import ...; print('import OK')"`

---
*Phase: 113-vm-execution-deployment*
*Completed: 2026-04-02*
