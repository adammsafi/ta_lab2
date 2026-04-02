---
phase: 113-vm-execution-deployment
plan: "06"
subsystem: infra
tags: [executor, vm, systemd, websocket, price-cache, paper-executor, stop-monitor, sqlalchemy, nullpool, telegram]

# Dependency graph
requires:
  - phase: 113-01
    provides: VM provisioning and SSH setup
  - phase: 113-02
    provides: WebSocket feed infrastructure (ws_feeds.py, PriceCache)
  - phase: 113-03
    provides: DB schema and VM table creation scripts
  - phase: 113-04
    provides: Signal sync (local -> VM push)
  - phase: 113-05
    provides: StopMonitor daemon + PositionSizer 5-tier VM-aware price fallback

provides:
  - executor_service.py: long-lived VM process entry point (systemd-ready)
  - PaperExecutor.vm_mode + price_cache params for VM-aware price resolution
  - requirements.txt: minimal VM executor Python dependencies

affects: [113-07, systemd-unit-file, vm-deployment-scripts, paper-trading-operations]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "NullPool for long-lived executor processes (no idle connections held between runs)"
    - "threading.Event for graceful SIGTERM/SIGINT shutdown"
    - "Crash-loop detection via /tmp JSON file tracking start timestamps"
    - "TYPE_CHECKING import guard for optional/circular PriceCache dependency"

key-files:
  created:
    - deploy/executor/executor_service.py
    - deploy/executor/requirements.txt
  modified:
    - src/ta_lab2/executor/paper_executor.py

key-decisions:
  - "PaperExecutor stores vm_mode + price_cache and creates PositionSizer instance at init — cleaner than passing through every call"
  - "Consecutive error threshold = 10 before sys.exit(1): gives resilience to transient DB/network errors while ensuring systemd restarts on sustained failures"
  - "Crash loop detection via /tmp/executor_starts.json — persists across Python restarts, cleared on VM reboot (appropriate for ops use)"
  - "Staleness check every 5 min with 2 min HL threshold — matches HL allMids push frequency (sub-second) so 2 min means genuine connection loss"

patterns-established:
  - "Pattern: vm_mode flag in executor classes activates VM-specific code paths without breaking local behaviour"
  - "Pattern: shutdown_event = threading.Event() + signal.signal(SIGTERM/SIGINT) for systemd-compatible graceful shutdown"

# Metrics
duration: 4min
completed: "2026-04-02"
---

# Phase 113 Plan 06: Executor Service Entry Point Summary

**executor_service.py systemd-ready VM process: WebSocket feeds + StopMonitor + PaperExecutor (vm_mode) with crash-loop detection and graceful SIGTERM shutdown**

## Performance

- **Duration:** 4 min
- **Started:** 2026-04-02T04:26:51Z
- **Completed:** 2026-04-02T04:30:42Z
- **Tasks:** 3
- **Files modified/created:** 3

## Accomplishments

- Extended `PaperExecutor.__init__` with `vm_mode` and `price_cache` params; creates a `PositionSizer` instance at init and routes `get_price()` through the 5-tier VM-aware fallback chain when `vm_mode=True`
- Created `deploy/executor/executor_service.py`: full startup sequence (DB engine, PriceCache, WebSocket feeds, 30s price wait, PaperExecutor, StopMonitor), 30s signal poll loop with Telegram stale-signal alerts, 10-error crash threshold with exponential backoff, 5-min HL staleness check, crash-loop detection via `/tmp/executor_starts.json`, and SIGTERM/SIGINT graceful shutdown
- Created `deploy/executor/requirements.txt` with only the 7 runtime dependencies needed on the VM (no research/ML/dashboard bloat)

## Task Commits

1. **Task 1: Extend PaperExecutor with vm_mode and price_cache** - `cb0ac212` (feat)
2. **Task 2: Create executor_service.py VM service entry point** - `4c9a6ff7` (feat)
3. **Task 3: Create requirements.txt for VM executor** - `459f25e7` (chore)

## Files Created/Modified

- `src/ta_lab2/executor/paper_executor.py` - Added `vm_mode: bool = False`, `price_cache: PriceCache | None = None` to `__init__`; stores `self._sizer = PositionSizer(price_cache, vm_mode)`; routes `_process_asset_signal` price lookup through `self._sizer.get_price()` in vm_mode
- `deploy/executor/executor_service.py` - Long-lived VM process: startup sequence, signal loop, crash-loop detection, staleness checks, graceful shutdown
- `deploy/executor/requirements.txt` - Minimal 7-package dependency list (sqlalchemy, psycopg2-binary, hyperliquid-python-sdk, websockets, numpy, pandas, requests)

## Decisions Made

- `PaperExecutor` instantiates a `PositionSizer` at `__init__` time (stores as `self._sizer`) rather than passing params on each call — this is cleaner and consistent with how `RiskEngine` and `SignalReader` are already stored as instance attributes
- `TYPE_CHECKING` guard for `PriceCache` import in `paper_executor.py` — avoids circular import risk since `price_cache.py` doesn't import from `paper_executor.py` but this pattern is consistent with the existing `ws_feeds.py` guard
- Consecutive error threshold = 10 (not 3 or 5) — gives resilience to transient DB/network blips while still exiting for sustained failures that systemd should handle
- Crash-loop detection in `/tmp` (not DB) — simpler, no DB dependency during crash, appropriate scope (VM-local, cleared on reboot)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

Ruff auto-fixed 2 style issues in `executor_service.py` on first commit attempt (inline comment alignment and one line too long). Staged and committed on second attempt without manual changes needed.

## User Setup Required

None — no external service configuration required beyond the environment variables documented in `executor_service.py` (`EXECUTOR_DB_URL`, `KRAKEN_SYMBOLS`, `COINBASE_PRODUCT_IDS`).

## Next Phase Readiness

- Plan 06 delivers the executor service entry point — the main runnable for `systemd`
- Plan 07 (final plan in phase 113) should create the `systemd` unit file and deployment script that invokes `executor_service.py` on the VM
- All three components (ws_feeds + stop_monitor + executor_service) are now wired together and ready for systemd service deployment

---
*Phase: 113-vm-execution-deployment*
*Completed: 2026-04-02*
