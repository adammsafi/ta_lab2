"""
Refresh the Crypto Fear & Greed Index from alternative.me.

On first run (no state): fetches full history (limit=0, ~1024 entries).
On subsequent runs: fetches only days since last_ts.

Usage:
    python -m ta_lab2.scripts.etl.refresh_fear_greed
    python -m ta_lab2.scripts.etl.refresh_fear_greed --dry-run
    python -m ta_lab2.scripts.etl.refresh_fear_greed --full
"""

import argparse
import logging
import sys
from datetime import date, datetime, timezone

import requests
from sqlalchemy import text

from ta_lab2.config import load_local_env
from ta_lab2.io import get_engine

logger = logging.getLogger(__name__)

API_URL = "https://api.alternative.me/fng/"
REQUEST_TIMEOUT = 30  # seconds

# ---------------------------------------------------------------------------
# SQL
# ---------------------------------------------------------------------------

UPSERT_SQL = text("""
    INSERT INTO alternative_me_fear_greed (ts, value, value_classification, api_timestamp)
    VALUES (:ts, :value, :value_classification, :api_timestamp)
    ON CONFLICT (ts) DO UPDATE SET
        value                = EXCLUDED.value,
        value_classification = EXCLUDED.value_classification,
        api_timestamp        = EXCLUDED.api_timestamp,
        ingested_at          = NOW()
""")

UPSERT_STATE_SQL = text("""
    INSERT INTO alternative_me_fear_greed_state (singleton_key, last_ts, last_run_ts, rows_written)
    VALUES (TRUE, :last_ts, NOW(), :rows_written)
    ON CONFLICT (singleton_key) DO UPDATE SET
        last_ts      = EXCLUDED.last_ts,
        last_run_ts  = NOW(),
        rows_written = EXCLUDED.rows_written
""")


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


def fetch_fng(limit: int = 0) -> list[dict]:
    """Fetch Fear & Greed entries from alternative.me API.

    Args:
        limit: Number of entries to fetch. 0 = all available (~1024).

    Returns:
        List of dicts with keys: value, value_classification, timestamp.
    """
    params = {"limit": limit, "format": "json"}
    resp = requests.get(API_URL, params=params, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()

    body = resp.json()
    if body.get("metadata", {}).get("error"):
        raise ValueError(f"API returned error: {body['metadata']['error']}")

    data = body.get("data")
    if not isinstance(data, list):
        raise ValueError(f"Unexpected response format: 'data' is {type(data)}")

    return data


# ---------------------------------------------------------------------------
# Transform
# ---------------------------------------------------------------------------


def transform_entries(entries: list[dict]) -> list[dict]:
    """Convert raw API entries into database rows.

    Converts unix timestamp to UTC date, validates value range.
    """
    rows = []
    for entry in entries:
        unix_ts = int(entry["timestamp"])
        # Use UTC-aware conversion to avoid Windows local-tz pitfall
        ts = datetime.fromtimestamp(unix_ts, tz=timezone.utc).date()
        value = int(entry["value"])
        if not 0 <= value <= 100:
            logger.warning("Skipping out-of-range value %d for %s", value, ts)
            continue
        rows.append(
            {
                "ts": ts,
                "value": value,
                "value_classification": entry["value_classification"],
                "api_timestamp": unix_ts,
            }
        )
    return rows


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


def read_state(engine) -> date | None:
    """Read last_ts from state table. Returns None if no state exists."""
    with engine.connect() as conn:
        result = conn.execute(
            text(
                "SELECT last_ts FROM alternative_me_fear_greed_state WHERE singleton_key = TRUE"
            )
        )
        row = result.fetchone()
        return row[0] if row else None


def update_state(engine, last_ts: date, rows_written: int):
    """Upsert the singleton state row."""
    with engine.begin() as conn:
        conn.execute(
            UPSERT_STATE_SQL, {"last_ts": last_ts, "rows_written": rows_written}
        )


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------


def upsert_rows(engine, rows: list[dict]) -> int:
    """Upsert Fear & Greed rows. Returns count of rows written."""
    if not rows:
        return 0
    with engine.begin() as conn:
        conn.execute(UPSERT_SQL, rows)
    return len(rows)


def update_data_sources(engine, row_count: int):
    """Best-effort update of data_sources registry."""
    try:
        with engine.begin() as conn:
            conn.execute(
                text("""
                    UPDATE data_sources SET
                        last_refreshed = NOW(),
                        last_row_count = :row_count,
                        updated_at     = NOW()
                    WHERE source_key = 'fear_greed_index'
                """),
                {"row_count": row_count},
            )
    except Exception:
        logger.debug("data_sources table not available -- skipping registry update.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Refresh Crypto Fear & Greed Index from alternative.me",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
    python -m ta_lab2.scripts.etl.refresh_fear_greed            # incremental
    python -m ta_lab2.scripts.etl.refresh_fear_greed --full     # full history
    python -m ta_lab2.scripts.etl.refresh_fear_greed --dry-run  # no writes
""",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and transform data but do not write to DB",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Force full history fetch (ignore state)",
    )
    parser.add_argument(
        "--db-url",
        default=None,
        help="Database URL (default: from db_config.env or TARGET_DB_URL env)",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )

    load_local_env()
    engine = get_engine(args.db_url)

    # -- determine fetch scope --
    if args.full:
        last_ts = None
    else:
        last_ts = read_state(engine)

    if last_ts is None:
        logger.info("No state found -- fetching full history (limit=0).")
        limit = 0
    else:
        days_since = (date.today() - last_ts).days
        if days_since <= 0:
            logger.info("Already up to date (last_ts=%s). Nothing to fetch.", last_ts)
            return 0
        # fetch a few extra days as overlap buffer (upsert handles duplicates)
        limit = days_since + 3
        logger.info("Incremental fetch: last_ts=%s, fetching limit=%d.", last_ts, limit)

    # -- fetch --
    raw_entries = fetch_fng(limit=limit)
    logger.info("API returned %d entries.", len(raw_entries))

    # -- transform --
    rows = transform_entries(raw_entries)
    logger.info("Transformed %d valid rows.", len(rows))

    if not rows:
        logger.warning("No valid rows after transformation. Exiting.")
        return 0

    if args.dry_run:
        earliest = min(r["ts"] for r in rows)
        latest = max(r["ts"] for r in rows)
        logger.info(
            "[DRY RUN] Would upsert %d rows. Earliest=%s, Latest=%s",
            len(rows),
            earliest,
            latest,
        )
        return 0

    # -- upsert --
    written = upsert_rows(engine, rows)
    logger.info("Upserted %d rows into alternative_me_fear_greed.", written)

    # -- update state --
    max_ts = max(r["ts"] for r in rows)
    update_state(engine, last_ts=max_ts, rows_written=written)
    logger.info("State updated: last_ts=%s.", max_ts)

    # -- update data_sources registry (best-effort) --
    update_data_sources(engine, row_count=written)

    logger.info("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
