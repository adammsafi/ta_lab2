"""
Load TradingView CSV price data into tvc_price_histories.

Reads CSV files from a folder structure like:
    tvc_price_data/20260223/BATS_GOOGL, 1D.csv

Each CSV has columns: time,open,high,low,close,Volume
  - time = Unix epoch seconds
  - Volume is capitalized

Resolves asset IDs via dim_listings (must run seed_tvc_assets.py first).
Upserts into tvc_price_histories with ON CONFLICT.

Usage:
    python -m ta_lab2.scripts.etl.load_tvc_price_data \\
        --dir C:\\Users\\asafi\\Downloads\\tvc_price_data
    python -m ta_lab2.scripts.etl.load_tvc_price_data --dir ... --watermark 20260223
    python -m ta_lab2.scripts.etl.load_tvc_price_data --dir ... --dry-run
"""

import argparse
import csv
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text

from ta_lab2.config import load_local_env
from ta_lab2.io import get_engine
from ta_lab2.scripts.etl.seed_tvc_assets import parse_csv_filename

logger = logging.getLogger(__name__)

UPSERT_SQL = text("""
    INSERT INTO tvc_price_histories
        (id, venue, ts, open, high, low, close, volume, data_watermark, source_file)
    VALUES
        (:id, :venue, :ts, :open, :high, :low, :close, :volume, :data_watermark, :source_file)
    ON CONFLICT (id, venue, ts) DO UPDATE SET
        open         = EXCLUDED.open,
        high         = EXCLUDED.high,
        low          = EXCLUDED.low,
        close        = EXCLUDED.close,
        volume       = EXCLUDED.volume,
        data_watermark = EXCLUDED.data_watermark,
        source_file  = EXCLUDED.source_file,
        ingested_at  = NOW()
""")


def _float_or_none(val: str) -> float | None:
    if not val:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def load_listings_map(engine) -> dict[tuple[str, str], int]:
    """Load dim_listings into a (venue, ticker_on_venue) -> id lookup."""
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT id, venue, ticker_on_venue FROM dim_listings")
        ).fetchall()
    return {(r[1], r[2]): r[0] for r in rows}


def read_tvc_csv(path: Path) -> list[dict]:
    """Read a TVC CSV file into a list of row dicts."""
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def coerce_rows(
    raw_rows: list[dict],
    *,
    asset_id: int,
    venue: str,
    data_watermark: str | None,
    source_file: str,
) -> list[dict]:
    """Coerce raw CSV rows to typed dicts for SQL binding."""
    coerced = []
    for row in raw_rows:
        epoch = row.get("time")
        if not epoch:
            continue
        ts = datetime.fromtimestamp(int(epoch), tz=timezone.utc)

        o = _float_or_none(row.get("open"))
        h = _float_or_none(row.get("high"))
        lo = _float_or_none(row.get("low"))
        c = _float_or_none(row.get("close"))
        vol = _float_or_none(row.get("Volume") or row.get("volume"))

        if o is None or h is None or lo is None or c is None:
            logger.warning("Skipping row with NULL OHLC at ts=%s", ts)
            continue

        coerced.append(
            {
                "id": asset_id,
                "venue": venue,
                "ts": ts,
                "open": o,
                "high": h,
                "low": lo,
                "close": c,
                "volume": vol,
                "data_watermark": data_watermark,
                "source_file": source_file,
            }
        )
    return coerced


def load_folder(
    engine,
    folder: Path,
    listings_map: dict[tuple[str, str], int],
    *,
    dry_run: bool = False,
    chunk_size: int = 500,
) -> dict:
    """Load all CSV files from a single YYYYMMDD folder."""
    watermark = folder.name  # e.g., "20260223"

    stats = {"files": 0, "rows_loaded": 0, "skipped_files": []}

    csv_files = sorted(folder.glob("*.csv"))
    if not csv_files:
        logger.warning("No CSV files in %s", folder)
        return stats

    for csv_file in csv_files:
        parsed = parse_csv_filename(csv_file.name)
        if parsed is None:
            stats["skipped_files"].append(csv_file.name)
            continue

        venue = parsed["venue"]
        ticker_on_venue = parsed["ticker_on_venue"]
        key = (venue, ticker_on_venue)

        if key not in listings_map:
            logger.error(
                "No dim_listings entry for (%s, %s) — run seed_tvc_assets first. "
                "Skipping %s",
                venue,
                ticker_on_venue,
                csv_file.name,
            )
            stats["skipped_files"].append(csv_file.name)
            continue

        asset_id = listings_map[key]
        raw_rows = read_tvc_csv(csv_file)
        coerced = coerce_rows(
            raw_rows,
            asset_id=asset_id,
            venue=venue,
            data_watermark=watermark,
            source_file=csv_file.name,
        )

        if dry_run:
            logger.info(
                "  [DRY RUN] %s: %d rows (id=%d, venue=%s)",
                csv_file.name,
                len(coerced),
                asset_id,
                venue,
            )
            stats["files"] += 1
            stats["rows_loaded"] += len(coerced)
            continue

        # Chunked upsert
        loaded = 0
        with engine.begin() as conn:
            for i in range(0, len(coerced), chunk_size):
                chunk = coerced[i : i + chunk_size]
                conn.execute(UPSERT_SQL, chunk)
                loaded += len(chunk)

        stats["files"] += 1
        stats["rows_loaded"] += loaded
        logger.info(
            "  %s: %d rows loaded (id=%d, venue=%s)",
            csv_file.name,
            loaded,
            asset_id,
            venue,
        )

    return stats


def update_data_sources(engine, total_rows: int):
    """Update data_sources registry with load timestamp and row count."""
    try:
        with engine.begin() as conn:
            conn.execute(
                text("""
                    UPDATE data_sources SET
                        last_refreshed = NOW(),
                        last_row_count = :row_count,
                        updated_at     = NOW()
                    WHERE source_key = 'tvc_price_histories'
                """),
                {"row_count": total_rows},
            )
    except Exception:
        logger.debug("data_sources update skipped — table or entry may not exist")


def update_coverage(engine):
    """Update asset_data_coverage for all assets in tvc_price_histories."""
    try:
        with engine.begin() as conn:
            conn.execute(
                text("""
                INSERT INTO asset_data_coverage (id, source_table, granularity, n_rows, n_days, first_ts, last_ts)
                SELECT
                    id,
                    'tvc_price_histories' AS source_table,
                    '1D' AS granularity,
                    COUNT(*) AS n_rows,
                    COUNT(DISTINCT ts::date) AS n_days,
                    MIN(ts) AS first_ts,
                    MAX(ts) AS last_ts
                FROM tvc_price_histories
                GROUP BY id
                ON CONFLICT (id, source_table, granularity) DO UPDATE SET
                    n_rows     = EXCLUDED.n_rows,
                    n_days     = EXCLUDED.n_days,
                    first_ts   = EXCLUDED.first_ts,
                    last_ts    = EXCLUDED.last_ts,
                    updated_at = NOW()
            """)
            )
    except Exception:
        logger.debug("asset_data_coverage update skipped — table may not exist")


def main():
    parser = argparse.ArgumentParser(
        description="Load TradingView CSV price data into tvc_price_histories"
    )
    parser.add_argument(
        "--dir",
        type=Path,
        required=True,
        help="Root directory containing YYYYMMDD subfolders with CSVs",
    )
    parser.add_argument(
        "--watermark",
        type=str,
        default=None,
        help="Load only this YYYYMMDD subfolder (default: all subfolders)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be loaded without making DB changes",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    if not args.dir.exists():
        logger.error("Directory not found: %s", args.dir)
        sys.exit(1)

    load_local_env()
    engine = get_engine()

    listings_map = load_listings_map(engine)
    if not listings_map:
        logger.error("No listings found in dim_listings — run seed_tvc_assets first")
        sys.exit(1)

    logger.info("Loaded %d listings from dim_listings", len(listings_map))

    # Discover folders to process
    if args.watermark:
        folders = [args.dir / args.watermark]
        if not folders[0].exists():
            logger.error("Watermark folder not found: %s", folders[0])
            sys.exit(1)
    else:
        folders = sorted(
            d for d in args.dir.iterdir() if d.is_dir() and d.name.isdigit()
        )

    if not folders:
        logger.error("No YYYYMMDD subfolders found in %s", args.dir)
        sys.exit(1)

    total_files = 0
    total_rows = 0

    for folder in folders:
        logger.info("Processing folder: %s", folder.name)
        stats = load_folder(engine, folder, listings_map, dry_run=args.dry_run)
        total_files += stats["files"]
        total_rows += stats["rows_loaded"]
        if stats["skipped_files"]:
            logger.warning("  Skipped files: %s", stats["skipped_files"])

    if not args.dry_run:
        update_data_sources(engine, total_rows)
        update_coverage(engine)

    logger.info(
        "Done. %d files processed, %d total rows %s.",
        total_files,
        total_rows,
        "would be loaded" if args.dry_run else "loaded",
    )


if __name__ == "__main__":
    main()
