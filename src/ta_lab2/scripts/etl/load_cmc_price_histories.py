"""
Load CoinMarketCap CSV price data into cmc_price_histories7.

Reads semicolon-delimited CSV files exported from CoinMarketCap's historical
data download.  Each CSV has columns:

    timeOpen;timeClose;timeHigh;timeLow;name;open;high;low;close;
    volume;marketCap;circulatingSupply;timestamp

The ``name`` column in the export contains a CMC internal value (e.g. "2781"),
**not** the asset name or CMC id.  The real CMC id is resolved from the
filename prefix via ``cmc_da_ids`` (e.g. ``Bitcoin_...csv`` -> id 1).

Only rows **newer** than the current max timestamp per asset are inserted
(incremental mode).  Use ``--full`` to upsert all rows.

Usage:
    python -m ta_lab2.scripts.etl.load_cmc_price_histories \\
        --dir C:\\Users\\asafi\\Downloads\\cmc_price_histories7_11_1_2025-3_27_2026

    python -m ta_lab2.scripts.etl.load_cmc_price_histories --dir ... --dry-run
    python -m ta_lab2.scripts.etl.load_cmc_price_histories --dir ... --full
"""

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd
from sqlalchemy import text

from ta_lab2.config import load_local_env
from ta_lab2.io import get_engine

logger = logging.getLogger(__name__)

UPSERT_SQL = text("""
    INSERT INTO cmc_price_histories7
        (id, name, timeopen, timeclose, timehigh, timelow, timestamp,
         open, high, low, close, volume, marketcap, circulatingsupply,
         date, source_file, load_ts)
    VALUES
        (:id, :name, :timeopen, :timeclose, :timehigh, :timelow, :timestamp,
         :open, :high, :low, :close, :volume, :marketcap, :circulatingsupply,
         :date, :source_file, :load_ts)
    ON CONFLICT (id, timestamp) DO UPDATE SET
        name              = EXCLUDED.name,
        timeopen          = EXCLUDED.timeopen,
        timeclose         = EXCLUDED.timeclose,
        timehigh          = EXCLUDED.timehigh,
        timelow           = EXCLUDED.timelow,
        open              = EXCLUDED.open,
        high              = EXCLUDED.high,
        low               = EXCLUDED.low,
        close             = EXCLUDED.close,
        volume            = EXCLUDED.volume,
        marketcap         = EXCLUDED.marketcap,
        circulatingsupply = EXCLUDED.circulatingsupply,
        date              = EXCLUDED.date,
        source_file       = EXCLUDED.source_file,
        load_ts           = EXCLUDED.load_ts
""")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _float_or_none(val) -> float | None:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def load_name_to_id(engine) -> dict[str, int]:
    """Build a filename-prefix -> CMC id lookup from cmc_da_ids.

    Returns e.g. {"Bitcoin": 1, "Ethereum": 1027, ...}.
    Falls back to well-known hardcoded map if cmc_da_ids is unavailable.
    """
    HARDCODED = {
        "Bitcoin": 1,
        "Ethereum": 1027,
        "XRP": 52,
        "BNB": 1839,
        "Chainlink": 1975,
        "Solana": 5426,
        "Hyperliquid": 32196,
        "Tether": 825,
        "Dogecoin": 74,
        "Cardano": 2010,
        "TRON": 1958,
        "Avalanche": 5805,
        "Polkadot": 6636,
        "Litecoin": 2,
        "Polygon": 3890,
        "Shiba Inu": 5994,
    }
    try:
        with engine.connect() as conn:
            rows = conn.execute(text("SELECT id, name FROM cmc_da_ids")).fetchall()
        if rows:
            mapping = {r[1]: r[0] for r in rows}
            logger.info("Loaded %d name->id mappings from cmc_da_ids", len(mapping))
            return mapping
    except Exception:
        logger.debug("cmc_da_ids not available, using hardcoded map")
    return HARDCODED


def load_max_timestamps(engine) -> dict[int, pd.Timestamp]:
    """Return {id: max_timestamp_utc} from cmc_price_histories7."""
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT id, MAX(timestamp) FROM cmc_price_histories7 GROUP BY id")
        ).fetchall()
    return {
        r[0]: pd.Timestamp(r[1]).tz_convert("UTC") for r in rows if r[1] is not None
    }


def resolve_cmc_id(filename: str, name_map: dict[str, int]) -> int | None:
    """Extract asset name from filename prefix and resolve to CMC id.

    Filenames look like:  Bitcoin_11_1_2025-3_27_2026_historical_data_coinmarketcap.csv
    The asset name is everything before the first ``_`` that is followed by a digit.
    Multi-word names like "Shiba Inu" use spaces in the CMC export.
    """
    stem = Path(filename).stem  # drop .csv
    # Walk underscores; the asset name ends where a numeric segment starts
    parts = stem.split("_")
    name_parts = []
    for p in parts:
        if p and p[0].isdigit():
            break
        name_parts.append(p)
    asset_name = " ".join(name_parts) if len(name_parts) > 1 else name_parts[0]

    # Try exact match first, then case-insensitive
    if asset_name in name_map:
        return name_map[asset_name]
    for k, v in name_map.items():
        if k.lower() == asset_name.lower():
            return v
    return None


def read_cmc_csv(path: Path) -> pd.DataFrame:
    """Read a CMC historical CSV (semicolon-delimited)."""
    return pd.read_csv(path, sep=";", encoding="utf-8-sig")


def coerce_dataframe(
    df: pd.DataFrame,
    *,
    cmc_id: int,
    source_file: str,
) -> list[dict]:
    """Convert raw DataFrame rows to typed dicts for SQL binding."""
    ts_cols = ["timeOpen", "timeClose", "timeHigh", "timeLow", "timestamp"]
    for col in ts_cols:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], utc=True, errors="coerce")

    now_utc = pd.Timestamp.now(tz="UTC")
    rows = []
    for _, r in df.iterrows():
        ts = r.get("timestamp")
        if pd.isna(ts):
            continue

        o = _float_or_none(r.get("open"))
        h = _float_or_none(r.get("high"))
        lo = _float_or_none(r.get("low"))
        c = _float_or_none(r.get("close"))
        if o is None or h is None or lo is None or c is None:
            logger.warning("Skipping row with NULL OHLC at ts=%s", ts)
            continue

        rows.append(
            {
                "id": cmc_id,
                "name": str(r.get("name", "")),
                "timeopen": r.get("timeOpen"),
                "timeclose": r.get("timeClose"),
                "timehigh": r.get("timeHigh"),
                "timelow": r.get("timeLow"),
                "timestamp": ts,
                "open": o,
                "high": h,
                "low": lo,
                "close": c,
                "volume": _float_or_none(r.get("volume")),
                "marketcap": _float_or_none(r.get("marketCap")),
                "circulatingsupply": _float_or_none(r.get("circulatingSupply")),
                "date": ts.date(),
                "source_file": source_file,
                "load_ts": now_utc,
            }
        )
    return rows


# ---------------------------------------------------------------------------
# Main loader
# ---------------------------------------------------------------------------


def load_folder(
    engine,
    folder: Path,
    name_map: dict[str, int],
    *,
    dry_run: bool = False,
    full: bool = False,
    chunk_size: int = 500,
) -> dict:
    """Load all CMC CSV files from *folder* into cmc_price_histories7."""
    stats = {
        "files": 0,
        "rows_loaded": 0,
        "rows_skipped_existing": 0,
        "skipped_files": [],
    }

    csv_files = sorted(folder.glob("*.csv"))
    if not csv_files:
        logger.warning("No CSV files in %s", folder)
        return stats

    max_ts_map = {} if full else load_max_timestamps(engine)

    for csv_file in csv_files:
        cmc_id = resolve_cmc_id(csv_file.name, name_map)
        if cmc_id is None:
            logger.error(
                "Cannot resolve CMC id for '%s' — add to cmc_da_ids or hardcoded map. Skipping.",
                csv_file.name,
            )
            stats["skipped_files"].append(csv_file.name)
            continue

        df = read_cmc_csv(csv_file)
        all_rows = coerce_dataframe(df, cmc_id=cmc_id, source_file=csv_file.name)

        # Filter to new rows only (unless --full)
        if not full and cmc_id in max_ts_map:
            cutoff = max_ts_map[cmc_id]
            before = len(all_rows)
            all_rows = [r for r in all_rows if r["timestamp"] > cutoff]
            stats["rows_skipped_existing"] += before - len(all_rows)

        if not all_rows:
            logger.info("  %s (id=%d): 0 new rows, skipping", csv_file.name, cmc_id)
            stats["files"] += 1
            continue

        if dry_run:
            logger.info(
                "  [DRY RUN] %s (id=%d): %d rows",
                csv_file.name,
                cmc_id,
                len(all_rows),
            )
            stats["files"] += 1
            stats["rows_loaded"] += len(all_rows)
            continue

        loaded = 0
        with engine.begin() as conn:
            for i in range(0, len(all_rows), chunk_size):
                chunk = all_rows[i : i + chunk_size]
                conn.execute(UPSERT_SQL, chunk)
                loaded += len(chunk)

        stats["files"] += 1
        stats["rows_loaded"] += loaded
        logger.info("  %s (id=%d): %d rows loaded", csv_file.name, cmc_id, loaded)

    return stats


def update_data_sources(engine, total_rows: int):
    """Best-effort update of data_sources registry."""
    try:
        with engine.begin() as conn:
            conn.execute(
                text("""
                    UPDATE data_sources SET
                        last_refreshed = NOW(),
                        last_row_count = :row_count,
                        updated_at     = NOW()
                    WHERE source_key = 'cmc_price_histories'
                """),
                {"row_count": total_rows},
            )
    except Exception:
        logger.debug("data_sources update skipped — table or entry may not exist")


def update_coverage(engine):
    """Update asset_data_coverage for all assets in cmc_price_histories7."""
    try:
        with engine.begin() as conn:
            conn.execute(
                text("""
                INSERT INTO asset_data_coverage
                    (id, source_table, granularity, n_rows, n_days, first_ts, last_ts)
                SELECT
                    id,
                    'cmc_price_histories7' AS source_table,
                    '1D' AS granularity,
                    COUNT(*) AS n_rows,
                    COUNT(DISTINCT date) AS n_days,
                    MIN(timestamp) AS first_ts,
                    MAX(timestamp) AS last_ts
                FROM cmc_price_histories7
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
        description="Load CoinMarketCap CSV price data into cmc_price_histories7",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python -m ta_lab2.scripts.etl.load_cmc_price_histories \\\n"
            "      --dir ~/Downloads/cmc_price_histories7_11_1_2025-3_27_2026\n"
            "  python -m ta_lab2.scripts.etl.load_cmc_price_histories --dir ... --dry-run\n"
            "  python -m ta_lab2.scripts.etl.load_cmc_price_histories --dir ... --full\n"
        ),
    )
    parser.add_argument(
        "--dir",
        type=Path,
        required=True,
        help="Directory containing CMC historical CSV files",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be loaded without making DB changes",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Upsert all rows (ignore existing max timestamp cutoff)",
    )
    parser.add_argument(
        "--db-url",
        default=None,
        help="Override database URL (default: TARGET_DB_URL from config)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )

    if not args.dir.exists():
        logger.error("Directory not found: %s", args.dir)
        sys.exit(1)

    load_local_env()
    engine = get_engine(args.db_url)

    name_map = load_name_to_id(engine)
    if not name_map:
        logger.error("No name->id mappings available — cannot resolve CSV filenames")
        sys.exit(1)

    logger.info("Loading CMC CSVs from %s", args.dir)
    stats = load_folder(
        engine, args.dir, name_map, dry_run=args.dry_run, full=args.full
    )

    if not args.dry_run and stats["rows_loaded"] > 0:
        update_data_sources(engine, stats["rows_loaded"])
        update_coverage(engine)

    logger.info(
        "Done. %d files, %d rows %s, %d rows skipped (already existed).",
        stats["files"],
        stats["rows_loaded"],
        "would be loaded" if args.dry_run else "loaded",
        stats["rows_skipped_existing"],
    )
    if stats["skipped_files"]:
        logger.warning("Skipped files: %s", stats["skipped_files"])


if __name__ == "__main__":
    main()
