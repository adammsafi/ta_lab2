"""
Seed the data_sources registry with known sources.

Idempotent — uses INSERT ... ON CONFLICT DO UPDATE so it can be re-run safely.

Usage:
    python -m ta_lab2.scripts.etl.seed_data_sources
"""

import json
import logging

from sqlalchemy import text

from ta_lab2.config import load_local_env
from ta_lab2.io import get_engine

logger = logging.getLogger(__name__)

SOURCES = [
    {
        "source_key": "companiesmarketcap",
        "name": "CompaniesMarketCap Assets",
        "source_type": "scrape",
        "url": "https://companiesmarketcap.com/assets-by-market-cap/",
        "description": "Global assets ranked by market cap — equities, ETFs, crypto, precious metals.",
        "refresh_cadence": "daily",
        "target_table": "companiesmarketcap_assets",
        "run_log_table": "companiesmarketcap_assets_runs",
        "config": json.dumps({"min_mcap_default": 25_000_000}),
    },
    {
        "source_key": "cmc_price_histories",
        "name": "CMC Price Histories",
        "source_type": "file_load",
        "url": None,
        "description": "CoinMarketCap daily OHLCV loaded from JSON files into cmc_price_histories7.",
        "refresh_cadence": "manual",
        "target_table": "cmc_price_histories7",
        "run_log_table": None,
        "config": None,
    },
    {
        "source_key": "price_bars_1d",
        "name": "CMC 1D Price Bars",
        "source_type": "derived",
        "url": None,
        "description": "Canonical 1D OHLCV bars derived from cmc_price_histories7 with repair and validation.",
        "refresh_cadence": "daily",
        "target_table": "price_bars_1d",
        "run_log_table": "price_bars_1d_state",
        "config": None,
    },
    {
        "source_key": "tvc_price_histories",
        "name": "TradingView CSV Price Data",
        "source_type": "file_load",
        "url": None,
        "description": "TradingView CSV exports (equities, ETFs, crypto) loaded into tvc_price_histories.",
        "refresh_cadence": "manual",
        "target_table": "tvc_price_histories",
        "run_log_table": None,
        "config": None,
    },
    {
        "source_key": "fear_greed_index",
        "name": "Crypto Fear & Greed Index",
        "source_type": "api",
        "url": "https://api.alternative.me/fng/",
        "description": "Daily Crypto Fear & Greed Index (0-100) from alternative.me.",
        "refresh_cadence": "daily",
        "target_table": "alternative_me_fear_greed",
        "run_log_table": "alternative_me_fear_greed_state",
        "config": json.dumps({"api_hard_cap_entries": 1024, "value_range": [0, 100]}),
    },
]

UPSERT_SQL = text("""
    INSERT INTO data_sources
        (source_key, name, source_type, url, description,
         refresh_cadence, target_table, run_log_table, config)
    VALUES
        (:source_key, :name, :source_type, :url, :description,
         :refresh_cadence, :target_table, :run_log_table, :config)
    ON CONFLICT (source_key) DO UPDATE SET
        name            = EXCLUDED.name,
        source_type     = EXCLUDED.source_type,
        url             = EXCLUDED.url,
        description     = EXCLUDED.description,
        refresh_cadence = EXCLUDED.refresh_cadence,
        target_table    = EXCLUDED.target_table,
        run_log_table   = EXCLUDED.run_log_table,
        config          = EXCLUDED.config,
        updated_at      = NOW()
""")


def seed(engine) -> int:
    """Upsert all known sources. Returns count of rows upserted."""
    with engine.begin() as conn:
        for src in SOURCES:
            conn.execute(UPSERT_SQL, src)
            logger.info("Upserted source: %s", src["source_key"])
    return len(SOURCES)


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    load_local_env()
    engine = get_engine()

    count = seed(engine)
    logger.info("Done. %d sources seeded.", count)


if __name__ == "__main__":
    main()
