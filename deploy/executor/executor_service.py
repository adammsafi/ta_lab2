"""executor_service.py - VM Executor Service Entry Point.

Long-lived process that runs on the Oracle Singapore VM as a systemd service.
Orchestrates WebSocket price feeds, StopMonitor, and signal-driven order
execution via PaperExecutor.

Startup sequence
----------------
1. Parse args (--dry-run, --log-level)
2. Configure logging to stdout (captured by journald / systemd)
3. Create SQLAlchemy engine with NullPool (EXECUTOR_DB_URL env or default)
4. Initialize PriceCache
5. Start WebSocket feeds (HL always; Kraken/Coinbase via env vars)
6. Wait for initial prices (up to 30 s)
7. Initialize PaperExecutor(engine, vm_mode=True, price_cache=price_cache)
8. Initialize and start StopMonitor
9. Enter _signal_loop (polls every 30 s for unprocessed signals)
10. Handle SIGTERM/SIGINT via threading.Event for graceful shutdown

Signal loop
-----------
Polls dim_executor_config for rows with executor_processed_at IS NULL (or
signals with unprocessed watermark) every 30 s.  Calls executor.run().
On stale signal (cadence_hours threshold), sends Telegram alert.
Consecutive error counter: after 10 consecutive errors, exits with code 1
so systemd can restart (RestartSec=30s).

PriceCache staleness check: every 5 min.  Telegram alert if HL stale > 2 min.

Crash-loop detection
--------------------
Tracks process starts in /tmp/executor_starts.json.  Sends Telegram alert
if 5 starts occur within 5 minutes (crash loop detected).

Graceful shutdown
-----------------
SIGTERM/SIGINT set _shutdown Event.  Main loop exits, StopMonitor is stopped,
final state is logged, process exits with code 0.

Environment variables
---------------------
EXECUTOR_DB_URL      SQLAlchemy database URL (required on VM)
KRAKEN_SYMBOLS       Comma-separated Kraken v2 symbols, e.g. "BTC/USD,ETH/USD"
COINBASE_PRODUCT_IDS Comma-separated Coinbase product IDs, e.g. "BTC-USD,ETH-USD"

Usage
-----
python executor_service.py [--dry-run] [--log-level DEBUG|INFO|WARNING]
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
import threading
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Bootstrap: ensure ta_lab2 package is importable (pip install -e from repo)
# ---------------------------------------------------------------------------

# Attempt to import ta_lab2 early; fail fast with a clear message.
try:
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import NullPool
except ImportError as _exc:
    sys.exit(
        f"FATAL: sqlalchemy not installed — {_exc}\nRun: pip install sqlalchemy psycopg2-binary"
    )

try:
    from ta_lab2.executor.paper_executor import PaperExecutor
    from ta_lab2.executor.price_cache import PriceCache
    from ta_lab2.executor.stop_monitor import StopMonitor
    from ta_lab2.executor.ws_feeds import start_all_feeds
except ImportError as _exc:
    sys.exit(
        f"FATAL: ta_lab2 package not importable — {_exc}\n"
        "Run: pip install -e /path/to/ta_lab2 (from the repo root)"
    )

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_DB_URL = "postgresql://postgres:postgres@localhost:5432/hyperliquid"
_SIGNAL_POLL_INTERVAL_SECS = 30.0  # how often to poll for new signals
_PRICE_STALENESS_CHECK_SECS = 300.0  # how often to check HL price freshness
_HL_STALE_THRESHOLD_SECS = 120.0  # 2 min = HL price considered stale
_MAX_CONSECUTIVE_ERRORS = 10  # exit code 1 after this many errors in a row
_INITIAL_PRICE_WAIT_SECS = 30.0  # max wait for first prices from WS feeds
_CRASH_LOOP_WINDOW_SECS = 300.0  # 5 min window for crash-loop detection
_CRASH_LOOP_MAX_STARTS = 5  # alert if >= this many starts in window
_STARTS_FILE = Path("/tmp/executor_starts.json")

logger = logging.getLogger("executor_service")


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------


def _configure_logging(level_name: str) -> None:
    """Configure root logger to stdout with structured format.

    journald (systemd) captures stdout/stderr automatically, so no file
    handler is needed.  The timestamp is included for non-systemd runs.
    """
    numeric_level = getattr(logging, level_name.upper(), logging.INFO)
    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ",
        stream=sys.stdout,
    )
    # Reduce noise from third-party libraries
    logging.getLogger("websockets").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("hyperliquid").setLevel(logging.WARNING)


# ---------------------------------------------------------------------------
# Crash-loop detection
# ---------------------------------------------------------------------------


def _record_start_and_check_crash_loop() -> bool:
    """Record current start time and return True if a crash loop is detected.

    Persists start timestamps to /tmp/executor_starts.json (survives Python
    restarts but is cleared on VM reboot, which is appropriate).

    Returns True when >= _CRASH_LOOP_MAX_STARTS starts have occurred within
    _CRASH_LOOP_WINDOW_SECS.  The caller should send a Telegram alert.
    """
    now_epoch = time.time()
    starts: list[float] = []

    try:
        if _STARTS_FILE.exists():
            starts = json.loads(_STARTS_FILE.read_text())
    except Exception as exc:  # noqa: BLE001
        logger.warning("crash-loop tracker: could not read starts file: %s", exc)

    # Keep only starts within the detection window
    starts = [t for t in starts if now_epoch - t < _CRASH_LOOP_WINDOW_SECS]
    starts.append(now_epoch)

    try:
        _STARTS_FILE.write_text(json.dumps(starts))
    except Exception as exc:  # noqa: BLE001
        logger.warning("crash-loop tracker: could not write starts file: %s", exc)

    is_crash_loop = len(starts) >= _CRASH_LOOP_MAX_STARTS
    logger.info(
        "crash-loop check: %d starts in last %.0f s (threshold=%d) — crash_loop=%s",
        len(starts),
        _CRASH_LOOP_WINDOW_SECS,
        _CRASH_LOOP_MAX_STARTS,
        is_crash_loop,
    )
    return is_crash_loop


# ---------------------------------------------------------------------------
# Telegram helper (best-effort — never raises)
# ---------------------------------------------------------------------------


def _telegram(message: str, severity: str = "warning") -> None:
    """Send a Telegram alert, swallowing all errors."""
    try:
        from ta_lab2.notifications.telegram import send_alert  # noqa: PLC0415

        send_alert(title="ExecutorService", message=message, severity=severity)
    except Exception as exc:  # noqa: BLE001
        logger.debug("telegram unavailable: %s — message: %s", exc, message)


# ---------------------------------------------------------------------------
# Wait for initial prices
# ---------------------------------------------------------------------------


def _wait_for_initial_prices(
    price_cache: PriceCache,
    timeout_secs: float = _INITIAL_PRICE_WAIT_SECS,
) -> bool:
    """Block until PriceCache has at least one price or timeout elapses.

    Returns True when prices are available, False on timeout.
    """
    deadline = time.monotonic() + timeout_secs
    while time.monotonic() < deadline:
        if len(price_cache) > 0:
            logger.info(
                "executor_service: initial prices received (%d symbols in cache)",
                len(price_cache),
            )
            return True
        time.sleep(1.0)
    return False


# ---------------------------------------------------------------------------
# PriceCache staleness check
# ---------------------------------------------------------------------------


def _check_price_staleness(price_cache: PriceCache) -> None:
    """Check HL price staleness and alert via Telegram if stale > 2 min.

    Hyperliquid provides ``allMids`` (all symbols in a single push), so
    we check a representative symbol.  BTC is universally present on HL.
    """
    stale_symbols = price_cache.stale_symbols(max_age_seconds=_HL_STALE_THRESHOLD_SECS)
    if stale_symbols:
        msg = (
            f"PRICE FEED STALE: {len(stale_symbols)} HL symbols stale "
            f"> {_HL_STALE_THRESHOLD_SECS:.0f}s — "
            f"sample: {stale_symbols[:5]}"
        )
        logger.warning("executor_service: %s", msg)
        _telegram(msg, severity="critical")
    else:
        logger.debug(
            "executor_service: price staleness check OK (%d symbols active)",
            len(price_cache),
        )


# ---------------------------------------------------------------------------
# Main signal loop
# ---------------------------------------------------------------------------


def _signal_loop(
    engine,
    executor: PaperExecutor,
    stop_monitor: StopMonitor,
    price_cache: PriceCache,
    shutdown_event: threading.Event,
    dry_run: bool,
) -> None:
    """Event loop that polls for unprocessed signals and runs the executor.

    Exits when shutdown_event is set (SIGTERM/SIGINT) or after
    _MAX_CONSECUTIVE_ERRORS consecutive errors (causes sys.exit(1) so systemd
    restarts the service).

    Parameters
    ----------
    engine :
        SQLAlchemy engine.
    executor :
        Initialized PaperExecutor instance.
    stop_monitor :
        Running StopMonitor daemon thread.
    price_cache :
        Shared price cache (used for staleness checks).
    shutdown_event :
        Set by signal handler on SIGTERM/SIGINT.
    dry_run :
        Passed to executor.run().
    """
    consecutive_errors = 0
    last_staleness_check = 0.0

    logger.info(
        "executor_service: entering signal loop "
        "(poll_interval=%.0fs, max_errors=%d, dry_run=%s)",
        _SIGNAL_POLL_INTERVAL_SECS,
        _MAX_CONSECUTIVE_ERRORS,
        dry_run,
    )

    while not shutdown_event.is_set():
        loop_start = time.monotonic()

        # ----- Price staleness check (every 5 min) -----
        if loop_start - last_staleness_check >= _PRICE_STALENESS_CHECK_SECS:
            _check_price_staleness(price_cache)
            last_staleness_check = loop_start

        # ----- Executor run -----
        try:
            summary = executor.run(dry_run=dry_run)
            consecutive_errors = 0
            logger.info("executor_service: run complete — %s", json.dumps(summary))

            # Stale signal alert: executor itself raises StaleSignalError per
            # strategy, which run() catches and records in summary["errors"].
            # We send an additional service-level alert here if any errors present.
            if summary.get("errors"):
                for err_entry in summary["errors"]:
                    cfg_name = err_entry.get("config", "unknown")
                    error_text = err_entry.get("error", "")
                    if "stale" in error_text.lower():
                        _telegram(
                            f"STALE SIGNAL: {cfg_name} — {error_text}",
                            severity="warning",
                        )

        except Exception as exc:  # noqa: BLE001
            consecutive_errors += 1
            logger.exception(
                "executor_service: run() raised exception (%d/%d): %s",
                consecutive_errors,
                _MAX_CONSECUTIVE_ERRORS,
                exc,
            )
            if consecutive_errors >= _MAX_CONSECUTIVE_ERRORS:
                msg = (
                    f"EXECUTOR CRASH: {consecutive_errors} consecutive errors — "
                    f"exiting for systemd restart. Last error: {exc}"
                )
                logger.critical("executor_service: %s", msg)
                _telegram(msg, severity="critical")
                # Stop the monitor before exiting
                stop_monitor.stop()
                stop_monitor.join(timeout=5)
                sys.exit(1)

            # Exponential-ish back-off: wait longer on repeated errors, cap at 5 min
            backoff = min(30.0 * consecutive_errors, 300.0)
            logger.info(
                "executor_service: backing off %.0f s before next attempt", backoff
            )
            shutdown_event.wait(timeout=backoff)
            continue

        # ----- Poll sleep -----
        elapsed = time.monotonic() - loop_start
        remaining = max(0.0, _SIGNAL_POLL_INTERVAL_SECS - elapsed)
        logger.debug(
            "executor_service: loop took %.2f s, sleeping %.2f s", elapsed, remaining
        )
        shutdown_event.wait(timeout=remaining)

    logger.info("executor_service: shutdown_event set — exiting signal loop")


# ---------------------------------------------------------------------------
# Engine factory
# ---------------------------------------------------------------------------


def _create_db_engine(db_url: str):
    """Create a NullPool SQLAlchemy engine suitable for long-running processes.

    NullPool ensures no idle connections are held between executor.run() calls,
    which is important when running as a systemd service that may be suspended
    or paused for extended periods.
    """
    engine = create_engine(
        db_url,
        poolclass=NullPool,
        connect_args={"connect_timeout": 10},
    )
    # Quick connectivity check
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info(
            "executor_service: database connection OK (%s)", db_url.split("@")[-1]
        )
    except Exception as exc:
        logger.error("executor_service: database connection failed: %s", exc)
        raise
    return engine


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="VM Executor Service — runs PaperExecutor as a long-lived process",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Log decisions but do not write to DB (no orders, fills, or position updates).",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity (default: INFO).",
    )
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    """Main entry point for the VM executor service."""
    args = _parse_args(argv)

    # Step 1: configure logging
    _configure_logging(args.log_level)

    logger.info(
        "executor_service: starting (version=1.0, dry_run=%s, log_level=%s, pid=%d)",
        args.dry_run,
        args.log_level,
        os.getpid(),
    )

    # Step 2: crash-loop detection
    if _record_start_and_check_crash_loop():
        _telegram(
            f"CRASH LOOP DETECTED: executor_service started "
            f">= {_CRASH_LOOP_MAX_STARTS} times in {_CRASH_LOOP_WINDOW_SECS:.0f}s. "
            "Service may be stuck. Manual intervention required.",
            severity="critical",
        )
        logger.critical(
            "executor_service: crash loop detected — sending alert but continuing startup"
        )

    # Step 3: create database engine
    db_url = os.environ.get("EXECUTOR_DB_URL", _DEFAULT_DB_URL)
    logger.info("executor_service: connecting to database")
    try:
        engine = _create_db_engine(db_url)
    except Exception as exc:
        logger.critical("executor_service: cannot start without DB — %s", exc)
        _telegram(
            f"EXECUTOR STARTUP FAILED: DB connection error — {exc}", severity="critical"
        )
        sys.exit(1)

    # Step 4: initialize PriceCache
    price_cache = PriceCache()
    logger.info("executor_service: PriceCache initialized")

    # Step 5: start WebSocket feeds
    kraken_symbols_raw = os.environ.get("KRAKEN_SYMBOLS", "")
    coinbase_ids_raw = os.environ.get("COINBASE_PRODUCT_IDS", "")
    kraken_symbols = [s.strip() for s in kraken_symbols_raw.split(",") if s.strip()]
    coinbase_product_ids = [s.strip() for s in coinbase_ids_raw.split(",") if s.strip()]

    feed_threads = start_all_feeds(
        price_cache=price_cache,
        kraken_symbols=kraken_symbols or None,
        coinbase_product_ids=coinbase_product_ids or None,
        logger=logger,
    )
    logger.info(
        "executor_service: %d WebSocket feed thread(s) started", len(feed_threads)
    )

    # Step 6: wait for initial prices (up to 30 s)
    logger.info(
        "executor_service: waiting up to %.0f s for initial prices...",
        _INITIAL_PRICE_WAIT_SECS,
    )
    if not _wait_for_initial_prices(price_cache, timeout_secs=_INITIAL_PRICE_WAIT_SECS):
        logger.warning(
            "executor_service: no prices received after %.0f s — "
            "proceeding anyway (price fallback chain will handle it)",
            _INITIAL_PRICE_WAIT_SECS,
        )
        _telegram(
            "Executor startup: no WebSocket prices after 30s. "
            "Proceeding with DB fallback price sources.",
            severity="warning",
        )
    else:
        logger.info("executor_service: %d symbols priced at startup", len(price_cache))

    # Step 7: initialize PaperExecutor in vm_mode
    logger.info("executor_service: initializing PaperExecutor (vm_mode=True)")
    executor = PaperExecutor(engine, vm_mode=True, price_cache=price_cache)

    # Step 8: initialize and start StopMonitor
    logger.info("executor_service: starting StopMonitor")
    stop_monitor = StopMonitor(engine, price_cache)
    stop_monitor.start()

    # Step 9: set up graceful shutdown via threading.Event
    shutdown_event = threading.Event()

    def _handle_signal(signum: int, _frame) -> None:  # type: ignore[type-arg]
        sig_name = signal.Signals(signum).name
        logger.info(
            "executor_service: received %s — requesting graceful shutdown", sig_name
        )
        shutdown_event.set()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    logger.info(
        "executor_service: all components initialized. Entering signal loop. "
        "Send SIGTERM or SIGINT to shut down gracefully."
    )
    _telegram(
        f"Executor service started on VM "
        f"(dry_run={args.dry_run}, pid={os.getpid()}, "
        f"{len(price_cache)} symbols at startup)",
        severity="info",
    )

    # Step 10: enter signal loop
    try:
        _signal_loop(
            engine=engine,
            executor=executor,
            stop_monitor=stop_monitor,
            price_cache=price_cache,
            shutdown_event=shutdown_event,
            dry_run=args.dry_run,
        )
    finally:
        # Graceful shutdown
        logger.info("executor_service: shutting down StopMonitor...")
        stop_monitor.stop()
        stop_monitor.join(timeout=5)
        logger.info("executor_service: StopMonitor stopped")

        logger.info(
            "executor_service: final state — %d symbols in price cache at shutdown",
            len(price_cache),
        )
        _telegram(
            f"Executor service stopped (pid={os.getpid()}, "
            f"graceful_shutdown={shutdown_event.is_set()})",
            severity="info",
        )
        logger.info("executor_service: shutdown complete")


if __name__ == "__main__":
    main()
