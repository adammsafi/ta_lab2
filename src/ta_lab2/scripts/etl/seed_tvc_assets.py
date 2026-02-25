"""
Seed dim_assets, dim_listings, and dim_asset_identifiers for TradingView assets.

Scans a TVC CSV folder to discover assets from filenames, then:
  1. Inserts new assets into dim_assets (with auto-assigned IDs from sequence)
  2. Inserts listings into dim_listings (one per venue+ticker_on_venue)
  3. Cross-references cusip_ticker for CUSIP identifiers
  4. For crypto assets in cmc_da_ids, uses the CMC ID directly
  5. Backfills dim_asset_identifiers for existing 7 crypto with CMC id_type

Idempotent — uses ON CONFLICT for all upserts.

Usage:
    python -m ta_lab2.scripts.etl.seed_tvc_assets \\
        --dir C:\\Users\\asafi\\Downloads\\tvc_price_data
    python -m ta_lab2.scripts.etl.seed_tvc_assets --dir ... --dry-run
"""

import argparse
import logging
import re
from pathlib import Path

from sqlalchemy import text

from ta_lab2.config import load_local_env
from ta_lab2.io import get_engine

logger = logging.getLogger(__name__)

# Crypto exchanges — assets on these venues are classified as CRYPTO
CRYPTO_VENUES = {"BYBIT", "GATE", "KRAKEN", "BINANCE", "COINBASE", "OKX"}

# Known ETF tickers
ETF_TICKERS = {"IBIT", "FBTC", "BITO", "GBTC", "ETHE"}

# Quote currency suffixes to strip for canonical symbol
QUOTE_SUFFIXES = ("USDT", "USD", "BUSD", "USDC", "EUR", "BTC", "ETH")


def parse_csv_filename(filename: str) -> dict | None:
    """
    Parse a TVC CSV filename into venue, ticker_on_venue, and timeframe.

    Examples:
        "BATS_GOOGL, 1D.csv"  -> {venue: "BATS", ticker_on_venue: "GOOGL", tf: "1D"}
        "BYBIT_CPOOLUSDT, 1D.csv" -> {venue: "BYBIT", ticker_on_venue: "CPOOLUSDT", tf: "1D"}
    """
    m = re.match(r"^([A-Z0-9]+)_([A-Za-z0-9]+),\s*(\w+)\.csv$", filename)
    if not m:
        logger.warning("Could not parse filename: %s", filename)
        return None
    return {
        "venue": m.group(1),
        "ticker_on_venue": m.group(2),
        "tf": m.group(3),
    }


def derive_canonical_symbol(ticker_on_venue: str, venue: str) -> str:
    """
    Derive the canonical asset symbol from a venue-specific ticker.

    For crypto, strips quote currency suffixes:
        CPOOLUSDT -> CPOOL
        CPOOLUSD  -> CPOOL
    For equities/ETFs, returns ticker as-is:
        GOOGL -> GOOGL
    """
    if venue not in CRYPTO_VENUES:
        return ticker_on_venue

    for suffix in QUOTE_SUFFIXES:
        if ticker_on_venue.endswith(suffix) and len(ticker_on_venue) > len(suffix):
            return ticker_on_venue[: -len(suffix)]
    return ticker_on_venue


def classify_asset(symbol: str, venue: str) -> str:
    """Classify asset_class based on symbol and venue."""
    if venue in CRYPTO_VENUES:
        return "CRYPTO"
    if symbol in ETF_TICKERS:
        return "ETF"
    return "EQUITY"


def derive_currency(ticker_on_venue: str, venue: str) -> str | None:
    """Derive quote currency from venue-specific ticker."""
    if venue not in CRYPTO_VENUES:
        return "USD"
    for suffix in QUOTE_SUFFIXES:
        if ticker_on_venue.endswith(suffix):
            return suffix
    return None


def discover_assets(tvc_dir: Path) -> list[dict]:
    """
    Scan TVC folder for CSV files and return discovered asset info.

    Returns list of dicts with keys:
        venue, ticker_on_venue, symbol, asset_class, currency, tf, filename
    """
    assets = []
    for subfolder in sorted(tvc_dir.iterdir()):
        if not subfolder.is_dir():
            continue
        for csv_file in sorted(subfolder.glob("*.csv")):
            parsed = parse_csv_filename(csv_file.name)
            if parsed is None:
                continue
            symbol = derive_canonical_symbol(parsed["ticker_on_venue"], parsed["venue"])
            asset_class = classify_asset(symbol, parsed["venue"])
            currency = derive_currency(parsed["ticker_on_venue"], parsed["venue"])
            assets.append(
                {
                    "venue": parsed["venue"],
                    "ticker_on_venue": parsed["ticker_on_venue"],
                    "symbol": symbol,
                    "asset_class": asset_class,
                    "currency": currency,
                    "tf": parsed["tf"],
                    "filename": csv_file.name,
                }
            )
    return assets


def seed_assets(engine, discovered: list[dict], dry_run: bool = False) -> dict:
    """
    Insert assets into dim_assets, dim_listings, dim_asset_identifiers.

    Returns summary dict with counts.
    """
    # Dedupe to unique symbols
    unique_symbols = {}
    for a in discovered:
        key = a["symbol"]
        if key not in unique_symbols:
            unique_symbols[key] = a

    # Build listings grouped by symbol
    listings_by_symbol: dict[str, list[dict]] = {}
    for a in discovered:
        listings_by_symbol.setdefault(a["symbol"], []).append(a)

    stats = {
        "assets_inserted": 0,
        "assets_existing": 0,
        "listings_inserted": 0,
        "identifiers_inserted": 0,
        "cmc_backfill": 0,
    }

    if dry_run:
        logger.info("DRY RUN — no database changes")
        for sym, info in unique_symbols.items():
            logger.info(
                "  Asset: %s (%s) — venues: %s",
                sym,
                info["asset_class"],
                [lst["venue"] for lst in listings_by_symbol[sym]],
            )
        return stats

    with engine.begin() as conn:
        # --- Load lookup tables ---
        cusip_map = {}
        try:
            rows = conn.execute(
                text("SELECT ticker, cusip FROM cusip_ticker")
            ).fetchall()
            cusip_map = {r[0]: r[1] for r in rows}
        except Exception:
            logger.warning(
                "cusip_ticker table not available — skipping CUSIP cross-reference"
            )

        cmc_map = {}
        try:
            rows = conn.execute(
                text("SELECT symbol, id FROM cmc_da_ids WHERE is_active = 1")
            ).fetchall()
            cmc_map = {r[0]: r[1] for r in rows}
        except Exception:
            logger.warning(
                "cmc_da_ids table not available — skipping CMC cross-reference"
            )

        # --- Insert assets into dim_assets ---
        for sym, info in sorted(unique_symbols.items()):
            asset_class = info["asset_class"]

            # For crypto that exists in CMC, use the CMC ID
            if asset_class == "CRYPTO" and sym in cmc_map:
                asset_id = cmc_map[sym]
                # Ensure it exists in dim_assets
                existing = conn.execute(
                    text("SELECT id FROM dim_assets WHERE id = :id"),
                    {"id": asset_id},
                ).fetchone()
                if existing:
                    # Update symbol if it was stored as CMC ID string
                    conn.execute(
                        text("""
                            UPDATE dim_assets
                            SET symbol = :symbol,
                                name = :name,
                                data_source = COALESCE(data_source, 'CMC'),
                                updated_at = NOW()
                            WHERE id = :id AND (symbol = :id_str OR symbol = :symbol)
                        """),
                        {
                            "id": asset_id,
                            "symbol": sym,
                            "name": sym,
                            "id_str": str(asset_id),
                        },
                    )
                    stats["assets_existing"] += 1
                    logger.info(
                        "  Asset %s (id=%d) already exists — updated symbol",
                        sym,
                        asset_id,
                    )
                else:
                    conn.execute(
                        text("""
                            INSERT INTO dim_assets (id, asset_class, symbol, name, data_source)
                            VALUES (:id, :asset_class, :symbol, :name, 'CMC')
                            ON CONFLICT (id) DO UPDATE SET
                                symbol = EXCLUDED.symbol,
                                name = EXCLUDED.name,
                                updated_at = NOW()
                        """),
                        {
                            "id": asset_id,
                            "asset_class": asset_class,
                            "symbol": sym,
                            "name": sym,
                        },
                    )
                    stats["assets_inserted"] += 1
                    logger.info("  Inserted asset %s with CMC id=%d", sym, asset_id)
            else:
                # Non-crypto or crypto not in CMC: auto-assign ID from sequence
                result = conn.execute(
                    text("""
                        INSERT INTO dim_assets (id, asset_class, symbol, name, data_source)
                        VALUES (nextval('dim_assets_id_seq'), :asset_class, :symbol, :name, 'TVC')
                        ON CONFLICT (id) DO NOTHING
                        RETURNING id
                    """),
                    {"asset_class": asset_class, "symbol": sym, "name": sym},
                )
                row = result.fetchone()
                if row:
                    asset_id = row[0]
                    stats["assets_inserted"] += 1
                    logger.info(
                        "  Inserted asset %s (%s) with id=%d",
                        sym,
                        asset_class,
                        asset_id,
                    )
                else:
                    # Check if it already exists by symbol
                    existing = conn.execute(
                        text(
                            "SELECT id FROM dim_assets WHERE symbol = :symbol AND asset_class = :ac"
                        ),
                        {"symbol": sym, "ac": asset_class},
                    ).fetchone()
                    if existing:
                        asset_id = existing[0]
                        stats["assets_existing"] += 1
                        logger.info(
                            "  Asset %s already exists with id=%d", sym, asset_id
                        )
                    else:
                        logger.error("  Failed to insert or find asset %s", sym)
                        continue

            # --- Insert listings ---
            sym_listings = sorted(
                listings_by_symbol[sym], key=lambda entry: entry["venue"]
            )
            for i, listing in enumerate(sym_listings):
                # Single-venue: always primary. Multi-venue: first alphabetically.
                is_primary = (len(sym_listings) == 1) or (i == 0)
                conn.execute(
                    text("""
                        INSERT INTO dim_listings
                            (id, venue, ticker_on_venue, asset_class, currency, is_primary)
                        VALUES (:id, :venue, :ticker_on_venue, :asset_class, :currency, :is_primary)
                        ON CONFLICT (id, venue, ticker_on_venue) DO UPDATE SET
                            asset_class = EXCLUDED.asset_class,
                            currency = EXCLUDED.currency
                    """),
                    {
                        "id": asset_id,
                        "venue": listing["venue"],
                        "ticker_on_venue": listing["ticker_on_venue"],
                        "asset_class": asset_class,
                        "currency": listing["currency"],
                        "is_primary": is_primary,
                    },
                )
                stats["listings_inserted"] += 1
                logger.info(
                    "    Listing: %s on %s (primary=%s)",
                    listing["ticker_on_venue"],
                    listing["venue"],
                    is_primary,
                )

            # --- Insert identifiers ---
            # CUSIP (for equities/ETFs)
            if sym in cusip_map:
                conn.execute(
                    text("""
                        INSERT INTO dim_asset_identifiers (id, id_type, id_value, is_primary)
                        VALUES (:id, 'CUSIP', :cusip, TRUE)
                        ON CONFLICT (id, id_type, id_value) DO NOTHING
                    """),
                    {"id": asset_id, "cusip": cusip_map[sym]},
                )
                stats["identifiers_inserted"] += 1
                logger.info("    Identifier: CUSIP=%s", cusip_map[sym])

            # CMC ID (for crypto)
            if sym in cmc_map:
                conn.execute(
                    text("""
                        INSERT INTO dim_asset_identifiers (id, id_type, id_value, is_primary)
                        VALUES (:id, 'CMC', :cmc_id, TRUE)
                        ON CONFLICT (id, id_type, id_value) DO NOTHING
                    """),
                    {"id": asset_id, "cmc_id": str(cmc_map[sym])},
                )
                stats["identifiers_inserted"] += 1
                logger.info("    Identifier: CMC=%d", cmc_map[sym])

        # --- Backfill CMC identifiers for existing 7 crypto ---
        existing_crypto = conn.execute(
            text("""
                SELECT d.id, c.symbol
                FROM dim_assets d
                JOIN cmc_da_ids c ON d.id = c.id
                WHERE d.asset_class = 'CRYPTO'
                  AND NOT EXISTS (
                    SELECT 1 FROM dim_asset_identifiers dai
                    WHERE dai.id = d.id AND dai.id_type = 'CMC'
                  )
            """)
        ).fetchall()
        for row in existing_crypto:
            conn.execute(
                text("""
                    INSERT INTO dim_asset_identifiers (id, id_type, id_value, is_primary)
                    VALUES (:id, 'CMC', :cmc_id, TRUE)
                    ON CONFLICT (id, id_type, id_value) DO NOTHING
                """),
                {"id": row[0], "cmc_id": str(row[0])},
            )
            stats["cmc_backfill"] += 1
            logger.info("  Backfilled CMC identifier for %s (id=%d)", row[1], row[0])

    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Seed dim_assets/dim_listings/dim_asset_identifiers for TradingView assets"
    )
    parser.add_argument(
        "--dir",
        type=Path,
        required=True,
        help="Root directory containing TVC CSV data (e.g., tvc_price_data/)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be inserted without making DB changes",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    if not args.dir.exists():
        logger.error("Directory not found: %s", args.dir)
        return

    discovered = discover_assets(args.dir)
    if not discovered:
        logger.error("No CSV files found in %s", args.dir)
        return

    logger.info(
        "Discovered %d CSV files (%d unique assets)",
        len(discovered),
        len({a["symbol"] for a in discovered}),
    )

    load_local_env()
    engine = get_engine()

    stats = seed_assets(engine, discovered, dry_run=args.dry_run)

    logger.info("Done. %s", stats)


if __name__ == "__main__":
    main()
