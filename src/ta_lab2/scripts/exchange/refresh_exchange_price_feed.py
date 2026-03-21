#!/usr/bin/env python
"""
Exchange price feed comparison script.

Fetches live spot prices from Coinbase and Kraken for configured pairs,
compares each live price against the most recent daily bar close stored in
price_bars_multi_tf, computes the discrepancy percentage, and writes
every snapshot to exchange_price_feed.

An adaptive threshold (3 * std_ret_30 * 100 from asset_stats) determines
whether a discrepancy is notable; a WARNING is logged when exceeded.

Usage
-----
    # Fetch BTC/USD and ETH/USD from both exchanges (production)
    python -m ta_lab2.scripts.exchange.refresh_exchange_price_feed

    # Dry run -- print what would be fetched/written without touching the DB
    python -m ta_lab2.scripts.exchange.refresh_exchange_price_feed --dry-run

    # Specific exchanges and pairs
    python -m ta_lab2.scripts.exchange.refresh_exchange_price_feed \\
        --exchanges coinbase kraken \\
        --pairs BTC/USD ETH/USD

    # Provide DB URL explicitly
    python -m ta_lab2.scripts.exchange.refresh_exchange_price_feed \\
        --db-url postgresql://user:pass@host/db
"""

from __future__ import annotations

import argparse
import logging
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from ta_lab2.connectivity.factory import get_exchange
from ta_lab2.scripts.refresh_utils import resolve_db_url

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_EXCHANGES: List[str] = ["coinbase", "kraken"]
DEFAULT_PAIRS: List[str] = ["BTC/USD", "ETH/USD"]
FALLBACK_THRESHOLD_PCT = 5.0  # percent; used when asset_stats has no data


# ---------------------------------------------------------------------------
# Data container
# ---------------------------------------------------------------------------


@dataclass
class PriceFeedRow:
    """One row destined for exchange_price_feed."""

    feed_id: str
    fetched_at: datetime
    exchange: str
    pair: str
    environment: str
    bid_price: Optional[float]
    ask_price: Optional[float]
    mid_price: Optional[float]
    last_price: Optional[float]
    bar_close: Optional[float]
    bar_ts: Optional[datetime]
    discrepancy_pct: Optional[float]
    threshold_pct: float
    exceeds_threshold: bool


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _get_latest_bar_close(
    conn,
    asset_symbol: str,
    tf: str = "1D",
) -> Tuple[Optional[float], Optional[datetime]]:
    """
    Return the (close, ts) of the most recent bar for the given asset and
    timeframe from price_bars_multi_tf.

    Parameters
    ----------
    conn : SQLAlchemy connection
    asset_symbol : str
        Asset symbol as stored in dim_assets, e.g. 'BTC', 'ETH'.
    tf : str
        Timeframe string, default '1D'.

    Returns
    -------
    (close, ts) or (None, None) when no bar exists.
    """
    # asset_symbol in the DB is the ticker/slug; dim_assets.symbol maps to it
    result = conn.execute(
        text(
            """
            SELECT b.close, b.ts
            FROM public.price_bars_multi_tf_u b
            JOIN public.dim_assets a ON a.id = b.id
            WHERE a.symbol = :symbol
              AND b.tf = :tf
              AND b.alignment_source = 'multi_tf'
            ORDER BY b.ts DESC
            LIMIT 1
            """
        ),
        {"symbol": asset_symbol, "tf": tf},
    ).fetchone()

    if result is None:
        return None, None
    return float(result[0]), result[1]


def _get_adaptive_threshold(conn, asset_symbol: str) -> float:
    """
    Return the adaptive discrepancy threshold (in percent) for an asset.

    Algorithm: 3 * std_ret_30 * 100 from asset_stats.
    Falls back to FALLBACK_THRESHOLD_PCT when no row exists or std_ret_30 is NULL.

    Parameters
    ----------
    conn : SQLAlchemy connection
    asset_symbol : str
        Asset symbol as stored in dim_assets.

    Returns
    -------
    float  Threshold in percent.
    """
    result = conn.execute(
        text(
            """
            SELECT s.std_ret_30
            FROM public.asset_stats s
            JOIN public.dim_assets a ON a.id = s.id
            WHERE a.symbol = :symbol
              AND s.std_ret_30 IS NOT NULL
            ORDER BY s.computed_at DESC
            LIMIT 1
            """
        ),
        {"symbol": asset_symbol},
    ).fetchone()

    if result is None or result[0] is None:
        logger.debug(
            "No std_ret_30 for %s, using fallback threshold %.1f%%",
            asset_symbol,
            FALLBACK_THRESHOLD_PCT,
        )
        return FALLBACK_THRESHOLD_PCT

    threshold = 3.0 * float(result[0]) * 100.0
    logger.debug("Adaptive threshold for %s: %.2f%%", asset_symbol, threshold)
    return threshold


def _fetch_live_price(
    exchange_name: str, pair: str
) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
    """
    Fetch bid, ask, mid, last_price from the exchange.

    Returns
    -------
    (bid, ask, mid, last_price) — all may be None on failure.
    """
    try:
        exchange = get_exchange(exchange_name)
        ticker = exchange.get_ticker(pair)
    except Exception as exc:
        logger.error(
            "Failed to fetch ticker for %s from %s: %s",
            pair,
            exchange_name,
            exc,
        )
        return None, None, None, None

    last_price = ticker.get("last_price")
    bid = ticker.get("bid")
    ask = ticker.get("ask")

    if bid is not None and ask is not None:
        mid = (float(bid) + float(ask)) / 2.0
    elif last_price is not None:
        # Many public ticker endpoints return only last_price
        mid = float(last_price)
        bid = None
        ask = None
    else:
        mid = None

    return (
        float(bid) if bid is not None else None,
        float(ask) if ask is not None else None,
        float(mid) if mid is not None else None,
        float(last_price) if last_price is not None else None,
    )


def _write_feed_row(conn, row: PriceFeedRow) -> None:
    """
    Insert one row into exchange_price_feed.

    Uses plain INSERT; feed_id is a UUID so collisions are impossible.
    """
    conn.execute(
        text(
            """
            INSERT INTO public.exchange_price_feed (
                feed_id, fetched_at, exchange, pair, environment,
                bid_price, ask_price, mid_price, last_price,
                bar_close, bar_ts,
                discrepancy_pct, threshold_pct, exceeds_threshold
            ) VALUES (
                :feed_id, :fetched_at, :exchange, :pair, :environment,
                :bid_price, :ask_price, :mid_price, :last_price,
                :bar_close, :bar_ts,
                :discrepancy_pct, :threshold_pct, :exceeds_threshold
            )
            """
        ),
        {
            "feed_id": row.feed_id,
            "fetched_at": row.fetched_at,
            "exchange": row.exchange,
            "pair": row.pair,
            "environment": row.environment,
            "bid_price": row.bid_price,
            "ask_price": row.ask_price,
            "mid_price": row.mid_price,
            "last_price": row.last_price,
            "bar_close": row.bar_close,
            "bar_ts": row.bar_ts,
            "discrepancy_pct": row.discrepancy_pct,
            "threshold_pct": row.threshold_pct,
            "exceeds_threshold": row.exceeds_threshold,
        },
    )


# ---------------------------------------------------------------------------
# Asset symbol extraction
# ---------------------------------------------------------------------------


def _base_symbol(pair: str) -> str:
    """
    Extract the base asset symbol from a trading pair string.

    Examples
    --------
    'BTC/USD' -> 'BTC'
    'ETH-USD' -> 'ETH'
    'BTCUSD'  -> 'BTC' (assumes 3-char base for standard pairs)
    """
    for sep in ("/", "-"):
        if sep in pair:
            return pair.split(sep)[0].upper()
    # Fallback: treat first 3 characters as base
    return pair[:3].upper()


# ---------------------------------------------------------------------------
# Main refresh function
# ---------------------------------------------------------------------------


def refresh_price_feed(
    db_url: str,
    exchanges: List[str] = None,
    pairs: List[str] = None,
    dry_run: bool = False,
) -> List[PriceFeedRow]:
    """
    Main loop: for every (exchange, pair) combination, fetch a live price,
    compare against the latest bar close, and write a row to exchange_price_feed.

    Parameters
    ----------
    db_url : str
        SQLAlchemy-compatible connection string.
    exchanges : list of str, optional
        Exchange names to query (default: coinbase + kraken).
    pairs : list of str, optional
        Trading pairs to fetch (default: BTC/USD + ETH/USD).
    dry_run : bool
        When True, perform all computations but skip the DB write.

    Returns
    -------
    List of PriceFeedRow objects that were (or would have been) written.
    """
    if exchanges is None:
        exchanges = DEFAULT_EXCHANGES
    if pairs is None:
        pairs = DEFAULT_PAIRS

    engine = create_engine(db_url, poolclass=NullPool)
    rows: List[PriceFeedRow] = []

    with engine.connect() as conn:
        for exchange_name in exchanges:
            for pair in pairs:
                fetched_at = datetime.now(tz=timezone.utc)
                asset_symbol = _base_symbol(pair)

                logger.info(
                    "Fetching %s from %s (asset=%s)...",
                    pair,
                    exchange_name,
                    asset_symbol,
                )

                # 1. Live price
                bid, ask, mid, last_price = _fetch_live_price(exchange_name, pair)

                if last_price is None and mid is None:
                    logger.warning(
                        "No price returned for %s from %s -- skipping row",
                        pair,
                        exchange_name,
                    )
                    continue

                # 2. Latest bar close
                bar_close, bar_ts = _get_latest_bar_close(conn, asset_symbol)

                if bar_close is None:
                    logger.warning(
                        "No bar close found for symbol=%s tf=1D -- comparison unavailable",
                        asset_symbol,
                    )

                # 3. Adaptive threshold
                threshold_pct = _get_adaptive_threshold(conn, asset_symbol)

                # 4. Discrepancy: compare last_price (or mid) against bar_close
                compare_price = last_price if last_price is not None else mid
                discrepancy_pct: Optional[float] = None
                exceeds_threshold = False

                if (
                    compare_price is not None
                    and bar_close is not None
                    and bar_close != 0
                ):
                    discrepancy_pct = abs(compare_price - bar_close) / bar_close * 100.0
                    exceeds_threshold = discrepancy_pct > threshold_pct

                    if exceeds_threshold:
                        logger.warning(
                            "DISCREPANCY ALERT: %s/%s live=%.4f bar_close=%.4f "
                            "discrepancy=%.2f%% threshold=%.2f%%",
                            exchange_name,
                            pair,
                            compare_price,
                            bar_close,
                            discrepancy_pct,
                            threshold_pct,
                        )
                    else:
                        logger.info(
                            "%s/%s live=%.4f bar_close=%.4f discrepancy=%.2f%% (OK)",
                            exchange_name,
                            pair,
                            compare_price,
                            bar_close if bar_close else 0.0,
                            discrepancy_pct if discrepancy_pct is not None else 0.0,
                        )

                feed_row = PriceFeedRow(
                    feed_id=str(uuid.uuid4()),
                    fetched_at=fetched_at,
                    exchange=exchange_name,
                    pair=pair,
                    environment="production",
                    bid_price=bid,
                    ask_price=ask,
                    mid_price=mid,
                    last_price=last_price,
                    bar_close=bar_close,
                    bar_ts=bar_ts,
                    discrepancy_pct=discrepancy_pct,
                    threshold_pct=threshold_pct,
                    exceeds_threshold=exceeds_threshold,
                )

                rows.append(feed_row)

                if dry_run:
                    logger.info(
                        "[DRY RUN] Would write row: exchange=%s pair=%s "
                        "last_price=%s bar_close=%s discrepancy_pct=%s exceeds=%s",
                        feed_row.exchange,
                        feed_row.pair,
                        feed_row.last_price,
                        feed_row.bar_close,
                        f"{feed_row.discrepancy_pct:.2f}%"
                        if feed_row.discrepancy_pct is not None
                        else "N/A",
                        feed_row.exceeds_threshold,
                    )
                else:
                    _write_feed_row(conn, feed_row)
                    logger.info(
                        "Wrote feed row: exchange=%s pair=%s feed_id=%s",
                        exchange_name,
                        pair,
                        feed_row.feed_id,
                    )

        if not dry_run:
            conn.commit()

    engine.dispose()
    return rows


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main(argv: List[str] | None = None) -> int:
    """CLI entry point for exchange price feed refresh."""
    p = argparse.ArgumentParser(
        description=(
            "Fetch live prices from configured exchanges and compare against "
            "the most recent bar close in price_bars_multi_tf. "
            "Writes snapshots to exchange_price_feed."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Default: BTC/USD + ETH/USD from Coinbase + Kraken
  python -m ta_lab2.scripts.exchange.refresh_exchange_price_feed

  # Dry run (no DB writes)
  python -m ta_lab2.scripts.exchange.refresh_exchange_price_feed --dry-run

  # Only Coinbase, only BTC/USD
  python -m ta_lab2.scripts.exchange.refresh_exchange_price_feed \\
      --exchanges coinbase --pairs BTC/USD
        """,
    )

    p.add_argument(
        "--exchanges",
        nargs="+",
        default=DEFAULT_EXCHANGES,
        metavar="EXCHANGE",
        help=f"Exchange names to fetch from (default: {' '.join(DEFAULT_EXCHANGES)})",
    )
    p.add_argument(
        "--pairs",
        nargs="+",
        default=DEFAULT_PAIRS,
        metavar="PAIR",
        help=f"Trading pairs to fetch (default: {' '.join(DEFAULT_PAIRS)})",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be written without touching the database",
    )
    p.add_argument(
        "--db-url",
        default=None,
        help="Database URL (default: resolved from db_config.env or env vars)",
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        help="Enable DEBUG-level logging",
    )

    args = p.parse_args(argv)

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)-8s %(name)s - %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ",
    )

    if args.dry_run:
        logger.info("[DRY RUN] Exchange price feed refresh (no DB writes)")

    # Resolve database URL
    try:
        db_url = resolve_db_url(args.db_url)
    except RuntimeError as exc:
        logger.error("DB URL resolution failed: %s", exc)
        return 1

    logger.info(
        "Starting price feed refresh: exchanges=%s pairs=%s",
        args.exchanges,
        args.pairs,
    )

    rows = refresh_price_feed(
        db_url=db_url,
        exchanges=args.exchanges,
        pairs=args.pairs,
        dry_run=args.dry_run,
    )

    # Summary
    alert_rows = [r for r in rows if r.exceeds_threshold]
    logger.info(
        "Price feed refresh complete: %d rows fetched, %d threshold alerts",
        len(rows),
        len(alert_rows),
    )

    if alert_rows:
        logger.warning(
            "Threshold exceeded for: %s",
            ", ".join(f"{r.exchange}/{r.pair}" for r in alert_rows),
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
