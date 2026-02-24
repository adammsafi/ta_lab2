"""
Load scraped companiesmarketcap.com assets into PostgreSQL.

Upserts into `companiesmarketcap_assets` (preserving created_at on existing rows)
and logs each run in `companiesmarketcap_assets_runs`.

Usage:
    python -m ta_lab2.scripts.etl.load_companiesmarketcap_assets --csv assets_by_market_cap.csv
"""

import argparse
import csv
import json
import logging
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text

from ta_lab2.config import load_local_env
from ta_lab2.io import get_engine

logger = logging.getLogger(__name__)

UPSERT_SQL = text("""
    INSERT INTO companiesmarketcap_assets
        (ticker, asset_type, rank, name, market_cap, price, change_pct,
         country, url, scraped_at, created_at, updated_at)
    VALUES
        (:ticker, :asset_type, :rank, :name, :market_cap, :price, :change_pct,
         :country, :url, :scraped_at, NOW(), NOW())
    ON CONFLICT (ticker, asset_type) DO UPDATE SET
        rank        = EXCLUDED.rank,
        name        = EXCLUDED.name,
        market_cap  = EXCLUDED.market_cap,
        price       = EXCLUDED.price,
        change_pct  = EXCLUDED.change_pct,
        country     = EXCLUDED.country,
        url         = EXCLUDED.url,
        scraped_at  = EXCLUDED.scraped_at,
        updated_at  = NOW()
""")


def read_csv(path: Path) -> list[dict]:
    """Read the scraper CSV into a list of dicts."""
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def deduplicate(rows: list[dict]) -> list[dict]:
    """Keep only the lowest-rank (highest mcap) row per (ticker, asset_type)."""
    best: dict[tuple, dict] = {}
    for row in rows:
        key = (row["ticker"], row["asset_type"])
        rank = int(row["rank"])
        if key not in best or rank < int(best[key]["rank"]):
            best[key] = row
    dropped = len(rows) - len(best)
    if dropped:
        logger.info(
            "Deduplicated %d rows (kept lowest rank per ticker+asset_type).", dropped
        )
    return list(best.values())


def _coerce_row(row: dict, scraped_at: datetime) -> dict:
    """Coerce CSV string values to proper types for SQL binding."""

    def _float_or_none(val):
        if not val:
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None

    def _int_or_none(val):
        if not val:
            return None
        try:
            return int(float(val))
        except (ValueError, TypeError):
            return None

    return {
        "ticker": row["ticker"],
        "asset_type": row["asset_type"],
        "rank": int(row["rank"]),
        "name": row["name"],
        "market_cap": _int_or_none(row.get("market_cap")),
        "price": _float_or_none(row.get("price")),
        "change_pct": _float_or_none(row.get("change_pct")),
        "country": row.get("country") or None,
        "url": row.get("url") or None,
        "scraped_at": scraped_at,
    }


def start_run(engine, scraped_at: datetime, min_mcap_floor: float | None) -> int:
    """Insert a new run record and return its run_id."""
    with engine.begin() as conn:
        result = conn.execute(
            text("""
                INSERT INTO companiesmarketcap_assets_runs
                    (started_at, status, min_mcap_floor)
                VALUES (:started_at, 'running', :min_mcap_floor)
                RETURNING run_id
            """),
            {"started_at": scraped_at, "min_mcap_floor": min_mcap_floor},
        )
        return result.scalar_one()


def finish_run(
    engine,
    run_id: int,
    *,
    rows_scraped: int,
    rows_loaded: int,
    pages_fetched: int | None,
    asset_type_counts: dict,
    status: str = "completed",
    error_message: str | None = None,
):
    """Update the run record with final metrics."""
    with engine.begin() as conn:
        conn.execute(
            text("""
                UPDATE companiesmarketcap_assets_runs SET
                    finished_at       = NOW(),
                    status            = :status,
                    rows_scraped      = :rows_scraped,
                    rows_loaded       = :rows_loaded,
                    pages_fetched     = :pages_fetched,
                    error_message     = :error_message,
                    asset_type_counts = :asset_type_counts
                WHERE run_id = :run_id
            """),
            {
                "run_id": run_id,
                "status": status,
                "rows_scraped": rows_scraped,
                "rows_loaded": rows_loaded,
                "pages_fetched": pages_fetched,
                "error_message": error_message,
                "asset_type_counts": json.dumps(asset_type_counts),
            },
        )


def load_to_db(
    rows: list[dict],
    engine,
    scraped_at: datetime,
    *,
    min_mcap_floor: float | None = None,
    pages_fetched: int | None = None,
    chunk_size: int = 500,
) -> int:
    """Upsert rows into companiesmarketcap_assets and log the run.

    Returns the number of rows loaded.
    """
    rows = deduplicate(rows)
    type_counts = dict(Counter(r["asset_type"] for r in rows))
    rows_scraped = len(rows)

    run_id = start_run(engine, scraped_at, min_mcap_floor)
    logger.info("Run %d started (%d rows to load).", run_id, rows_scraped)

    try:
        params = [_coerce_row(r, scraped_at) for r in rows]

        loaded = 0
        with engine.begin() as conn:
            for i in range(0, len(params), chunk_size):
                chunk = params[i : i + chunk_size]
                conn.execute(UPSERT_SQL, chunk)
                loaded += len(chunk)
                if loaded % 5000 < chunk_size:
                    logger.info("  ... %d / %d rows upserted", loaded, rows_scraped)

        finish_run(
            engine,
            run_id,
            rows_scraped=rows_scraped,
            rows_loaded=loaded,
            pages_fetched=pages_fetched,
            asset_type_counts=type_counts,
        )

        # Update data_sources registry (best-effort — table may not exist yet)
        try:
            with engine.begin() as conn:
                conn.execute(
                    text("""
                        UPDATE data_sources SET
                            last_refreshed = :scraped_at,
                            last_row_count = :row_count,
                            updated_at     = NOW()
                        WHERE source_key = 'companiesmarketcap'
                    """),
                    {"scraped_at": scraped_at, "row_count": loaded},
                )
        except Exception:
            logger.debug("data_sources table not available — skipping registry update.")

        logger.info("Run %d completed: %d rows loaded.", run_id, loaded)
        return loaded

    except Exception as e:
        finish_run(
            engine,
            run_id,
            rows_scraped=rows_scraped,
            rows_loaded=0,
            pages_fetched=pages_fetched,
            asset_type_counts=type_counts,
            status="failed",
            error_message=str(e),
        )
        raise


def main():
    parser = argparse.ArgumentParser(
        description="Load companiesmarketcap.com assets into PostgreSQL"
    )
    parser.add_argument(
        "--csv", type=Path, required=True, help="Path to scraped CSV file"
    )
    parser.add_argument(
        "--scraped-at",
        type=str,
        default=None,
        help="Override scraped_at timestamp (ISO format). Defaults to file mtime.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    if not args.csv.exists():
        logger.error("CSV file not found: %s", args.csv)
        sys.exit(1)

    # Determine scraped_at: explicit arg > file modification time
    if args.scraped_at:
        scraped_at = datetime.fromisoformat(args.scraped_at)
        if scraped_at.tzinfo is None:
            scraped_at = scraped_at.replace(tzinfo=timezone.utc)
    else:
        mtime = args.csv.stat().st_mtime
        scraped_at = datetime.fromtimestamp(mtime, tz=timezone.utc)

    rows = read_csv(args.csv)
    if not rows:
        logger.error("CSV is empty — nothing to load.")
        sys.exit(1)

    logger.info(
        "Read %d rows from %s (scraped_at=%s)",
        len(rows),
        args.csv,
        scraped_at.isoformat(),
    )

    load_local_env()
    engine = get_engine()

    loaded = load_to_db(rows, engine, scraped_at)
    logger.info("Done. %d rows in database.", loaded)


if __name__ == "__main__":
    main()
