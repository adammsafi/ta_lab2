"""
Macro event calendar seed script for Phase 71 Event Risk Gates.

Populates dim_macro_events with FOMC, CPI, and NFP dates.

Modes:
  --fomc-only   Seed only hardcoded FOMC dates (default if no flags given)
  --fetch-api   Also fetch CPI and NFP dates from FRED API
  --dry-run     Print events to stdout without writing to DB
  --year YYYY   Filter to a specific year (default: seed all years)

FRED API:
  Set FRED_API_KEY environment variable before using --fetch-api.
  CPI release_id=10 (Consumer Price Index for All Urban Consumers)
  NFP release_id=50 (Employment Situation -- includes Non-Farm Payrolls)

Upsert strategy:
  ON CONFLICT (event_type, event_ts) DO NOTHING
  Safe to run multiple times; existing rows are not modified.

Usage::

    python -m ta_lab2.scripts.risk.seed_macro_events --fomc-only --dry-run
    python -m ta_lab2.scripts.risk.seed_macro_events --fomc-only
    python -m ta_lab2.scripts.risk.seed_macro_events --fetch-api --year 2026

Environment / config:
    Database URL is resolved via resolve_db_url() which checks:
    1. --db-url CLI flag (if provided)
    2. db_config.env file (searched up to 5 dirs up)
    3. TARGET_DB_URL environment variable
    4. MARKETDATA_DB_URL environment variable
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import urllib.request
import json
from datetime import datetime, timezone
from typing import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from ta_lab2.scripts.refresh_utils import resolve_db_url

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Hardcoded FOMC dates 2026-2027
# ---------------------------------------------------------------------------
# FOMC meetings: announcement at 2:00 PM ET on the second day of each meeting.
# EST months (Nov-Mar): UTC offset -5h -> 14:00 ET = 19:00 UTC
# EDT months (Apr-Oct): UTC offset -4h -> 14:00 ET = 18:00 UTC
#
# Source: Federal Reserve FOMC meeting schedule (publicly available)
# 2026: 8 scheduled meetings
# 2027: 8 scheduled meetings (preliminary)

_FOMC_DATES: list[tuple[str, str]] = [
    # (announcement_date_ET, data_period)
    # -- 2026 --
    ("2026-01-28", "2026-01"),
    ("2026-03-18", "2026-03"),
    ("2026-04-29", "2026-04"),
    ("2026-06-17", "2026-06"),
    ("2026-07-29", "2026-07"),
    ("2026-09-16", "2026-09"),
    ("2026-10-28", "2026-10"),
    ("2026-12-09", "2026-12"),
    # -- 2027 --
    ("2027-01-27", "2027-01"),
    ("2027-03-17", "2027-03"),
    ("2027-04-28", "2027-04"),
    ("2027-06-09", "2027-06"),
    ("2027-07-28", "2027-07"),
    ("2027-09-15", "2027-09"),
    ("2027-10-27", "2027-10"),
    ("2027-12-08", "2027-12"),
]

# Months in EDT (Apr-Oct): announcement at 18:00 UTC
_EDT_MONTHS = {4, 5, 6, 7, 8, 9, 10}


def _fomc_utc(date_str: str) -> datetime:
    """Convert FOMC announcement date (ET) to UTC datetime.

    2:00 PM ET = 19:00 UTC in EST months (Jan, Feb, Mar, Nov, Dec)
    2:00 PM ET = 18:00 UTC in EDT months (Apr through Oct)
    """
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    hour_utc = 18 if dt.month in _EDT_MONTHS else 19
    return dt.replace(hour=hour_utc, tzinfo=timezone.utc)


def _iter_fomc_events(
    year_filter: int | None = None,
) -> Generator[dict, None, None]:
    """Yield FOMC event dicts ready for upsert."""
    for date_str, data_period in _FOMC_DATES:
        event_ts = _fomc_utc(date_str)
        if year_filter is not None and event_ts.year != year_filter:
            continue
        yield {
            "event_type": "fomc",
            "event_ts": event_ts,
            "data_period": data_period,
            "source": "hardcoded",
        }


# ---------------------------------------------------------------------------
# FRED API fetch for CPI and NFP
# ---------------------------------------------------------------------------

_FRED_RELEASES = {
    "cpi": 10,  # Consumer Price Index for All Urban Consumers
    "nfp": 50,  # Employment Situation (Non-Farm Payrolls)
}

# FRED API base URL
_FRED_API_BASE = "https://api.stlouisfed.org/fred"


def _fetch_fred_release_dates(
    release_id: int,
    event_type: str,
    api_key: str,
    year_filter: int | None = None,
) -> list[dict]:
    """Fetch release dates from FRED API for a given release_id.

    Returns a list of event dicts.
    Release dates are typically at 8:30 AM ET.
    8:30 AM EST = 13:30 UTC; 8:30 AM EDT = 12:30 UTC.
    """
    url = (
        f"{_FRED_API_BASE}/release/dates"
        f"?release_id={release_id}"
        f"&api_key={api_key}"
        f"&file_type=json"
        f"&include_release_dates_with_no_data=true"
        f"&limit=100"
    )
    if year_filter is not None:
        url += f"&realtime_start={year_filter}-01-01&realtime_end={year_filter}-12-31"

    logger.debug("FRED API request: %s", url)

    try:
        with urllib.request.urlopen(url, timeout=15) as resp:  # noqa: S310
            data = json.loads(resp.read().decode())
    except Exception as exc:
        logger.error("FRED API request failed for release_id=%d: %s", release_id, exc)
        raise

    events: list[dict] = []
    for item in data.get("release_dates", []):
        date_str = item.get("date", "")
        if not date_str:
            continue
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            logger.warning("Unparseable FRED date: %r", date_str)
            continue

        if year_filter is not None and dt.year != year_filter:
            continue

        # 8:30 AM ET: EST months = 13:30 UTC, EDT months = 12:30 UTC
        hour_utc = 12 if dt.month in _EDT_MONTHS else 13
        minute_utc = 30
        event_ts = dt.replace(hour=hour_utc, minute=minute_utc, tzinfo=timezone.utc)

        events.append(
            {
                "event_type": event_type,
                "event_ts": event_ts,
                "data_period": date_str[:7],  # YYYY-MM
                "source": "fred_api",
            }
        )

    return events


# ---------------------------------------------------------------------------
# Database upsert
# ---------------------------------------------------------------------------

_UPSERT_SQL = text(
    """
    INSERT INTO public.dim_macro_events
        (event_type, event_ts, data_period, source)
    VALUES
        (:event_type, :event_ts, :data_period, :source)
    ON CONFLICT (event_type, event_ts)
    DO NOTHING
    """
)


def _upsert_events(engine, events: list[dict], dry_run: bool) -> int:
    """Upsert events into dim_macro_events. Returns count of rows sent."""
    if not events:
        logger.info("No events to upsert.")
        return 0

    if dry_run:
        print(f"[dry-run] Would upsert {len(events)} events:")
        for ev in sorted(events, key=lambda e: (e["event_type"], e["event_ts"])):
            print(
                f"  {ev['event_type']:12s}  {ev['event_ts'].isoformat()}  "
                f"{ev['data_period']:8s}  [{ev['source']}]"
            )
        return len(events)

    with engine.begin() as conn:
        result = conn.execute(_UPSERT_SQL, events)
        inserted = result.rowcount

    logger.info(
        "Upserted %d events to dim_macro_events (%d new rows inserted).",
        len(events),
        inserted,
    )
    return len(events)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Seed dim_macro_events with FOMC, CPI, and NFP dates.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--fomc-only",
        action="store_true",
        help="Seed only hardcoded FOMC dates (no API calls).",
    )
    parser.add_argument(
        "--fetch-api",
        action="store_true",
        help=(
            "Fetch CPI and NFP dates from FRED API. "
            "Requires FRED_API_KEY environment variable."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print events to stdout without writing to database.",
    )
    parser.add_argument(
        "--year",
        type=int,
        default=None,
        metavar="YYYY",
        help="Filter to a specific year (default: all years).",
    )
    parser.add_argument(
        "--db-url",
        default=None,
        metavar="URL",
        help="Database URL (default: from config/env via resolve_db_url).",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable DEBUG-level logging.",
    )
    return parser


def main() -> int:
    """Entry point for seed_macro_events CLI."""
    parser = _build_parser()
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    # Default behaviour: if neither flag given, behave like --fomc-only
    if not args.fomc_only and not args.fetch_api:
        logger.info("No mode flag specified -- defaulting to --fomc-only.")
        args.fomc_only = True

    all_events: list[dict] = []

    # Collect FOMC events (always if --fomc-only; also if --fetch-api)
    if args.fomc_only or args.fetch_api:
        fomc_events = list(_iter_fomc_events(year_filter=args.year))
        logger.info("Collected %d FOMC events.", len(fomc_events))
        all_events.extend(fomc_events)

    # Fetch CPI and NFP from FRED API
    if args.fetch_api:
        api_key = os.environ.get("FRED_API_KEY", "").strip()
        if not api_key:
            logger.error(
                "FRED_API_KEY environment variable not set. "
                "Cannot use --fetch-api without it."
            )
            return 1

        for event_type, release_id in _FRED_RELEASES.items():
            logger.info(
                "Fetching %s dates from FRED API (release_id=%d)...",
                event_type.upper(),
                release_id,
            )
            try:
                api_events = _fetch_fred_release_dates(
                    release_id=release_id,
                    event_type=event_type,
                    api_key=api_key,
                    year_filter=args.year,
                )
            except Exception:
                logger.error(
                    "Failed to fetch %s dates -- aborting API fetch.",
                    event_type.upper(),
                )
                return 1

            logger.info("Collected %d %s events.", len(api_events), event_type.upper())
            all_events.extend(api_events)

    if not all_events:
        logger.warning("No events collected. Nothing to do.")
        return 0

    # Upsert (or dry-run print)
    if args.dry_run:
        _upsert_events(engine=None, events=all_events, dry_run=True)
        return 0

    db_url = resolve_db_url(getattr(args, "db_url", None))
    engine = create_engine(db_url, poolclass=NullPool)

    try:
        _upsert_events(engine=engine, events=all_events, dry_run=False)
    except Exception as exc:
        logger.error("Upsert failed: %s", exc)
        return 1
    finally:
        engine.dispose()

    logger.info("seed_macro_events complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
