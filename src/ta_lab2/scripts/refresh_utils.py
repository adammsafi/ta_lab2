#!/usr/bin/env python
"""
Shared utilities for daily refresh orchestration.

Provides state checking, ID parsing, and database URL resolution.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from sqlalchemy import create_engine, text


@dataclass
class FreshnessResult:
    """Result of bar freshness check for a single ID."""

    id: int
    last_src_ts: datetime | None
    is_fresh: bool
    staleness_hours: float | None
    reason: Literal["fresh", "stale", "no_state"]


def check_bar_freshness(
    db_url: str,
    ids: list[int] | None = None,
    max_staleness_hours: float = 48.0,
) -> list[FreshnessResult]:
    """
    Check bar freshness by comparing last_src_ts to current time.

    Args:
        db_url: Database connection URL
        ids: Specific IDs to check (None = all with state)
        max_staleness_hours: Max hours since last update to consider fresh

    Returns:
        List of FreshnessResult for each ID
    """
    engine = create_engine(db_url)

    # Build query
    if ids is None:
        # All IDs with state
        query = text(
            """
            SELECT
                id,
                last_src_ts,
                EXTRACT(EPOCH FROM (NOW() - last_src_ts)) / 3600 AS staleness_hours
            FROM public.cmc_price_bars_1d_state
            ORDER BY id
        """
        )
        params = {}
    else:
        # Specific IDs
        query = text(
            """
            SELECT
                id,
                last_src_ts,
                EXTRACT(EPOCH FROM (NOW() - last_src_ts)) / 3600 AS staleness_hours
            FROM public.cmc_price_bars_1d_state
            WHERE id = ANY(:ids)
            ORDER BY id
        """
        )
        params = {"ids": ids}

    with engine.connect() as conn:
        result = conn.execute(query, params)
        rows = result.fetchall()

    # Convert to FreshnessResult
    results = []
    for row in rows:
        id_val, last_src_ts, staleness_hours = row

        if last_src_ts is None:
            # No bars ever processed
            results.append(
                FreshnessResult(
                    id=id_val,
                    last_src_ts=None,
                    is_fresh=False,
                    staleness_hours=None,
                    reason="no_state",
                )
            )
        elif staleness_hours is None or staleness_hours <= max_staleness_hours:
            # Fresh
            results.append(
                FreshnessResult(
                    id=id_val,
                    last_src_ts=last_src_ts,
                    is_fresh=True,
                    staleness_hours=staleness_hours,
                    reason="fresh",
                )
            )
        else:
            # Stale
            results.append(
                FreshnessResult(
                    id=id_val,
                    last_src_ts=last_src_ts,
                    is_fresh=False,
                    staleness_hours=staleness_hours,
                    reason="stale",
                )
            )

    # If specific IDs requested, also check for missing state
    if ids is not None:
        state_ids = {r.id for r in results}
        missing_ids = set(ids) - state_ids
        for missing_id in sorted(missing_ids):
            results.append(
                FreshnessResult(
                    id=missing_id,
                    last_src_ts=None,
                    is_fresh=False,
                    staleness_hours=None,
                    reason="no_state",
                )
            )

    return sorted(results, key=lambda r: r.id)


def get_fresh_ids(
    db_url: str,
    ids: list[int] | None = None,
    max_staleness_hours: float = 48.0,
) -> tuple[list[int], list[int]]:
    """
    Get IDs with fresh bars vs stale/missing bars.

    Returns:
        (fresh_ids, stale_ids) - IDs suitable for EMA refresh vs needing bar refresh
    """
    results = check_bar_freshness(db_url, ids, max_staleness_hours)
    fresh = [r.id for r in results if r.is_fresh]
    stale = [r.id for r in results if not r.is_fresh]
    return fresh, stale


def parse_ids(ids_arg: str, db_url: str | None = None) -> list[int] | None:
    """
    Parse --ids argument into list of integers.

    Args:
        ids_arg: "all" or comma-separated IDs like "1,52,825"
        db_url: If provided and ids_arg is "all", query dim_assets for valid IDs

    Returns:
        None for "all", list of ints otherwise
    """
    if ids_arg == "all":
        return None

    # Parse comma-separated IDs
    try:
        return [int(x.strip()) for x in ids_arg.split(",") if x.strip()]
    except ValueError as e:
        raise ValueError(
            f"Invalid --ids format: {ids_arg}. Expected 'all' or comma-separated integers."
        ) from e


def resolve_db_url(cli_db_url: str | None = None) -> str:
    """
    Resolve database URL from CLI arg, config file, or environment.

    Priority:
    1. CLI argument if provided
    2. db_config.env file (searched up to 5 dirs up)
    3. TARGET_DB_URL environment variable
    4. MARKETDATA_DB_URL environment variable

    Raises:
        RuntimeError if no database URL found
    """
    # Priority 1: CLI argument
    if cli_db_url:
        return cli_db_url

    # Priority 2: db_config.env file
    db_url = _load_db_url_from_config()
    if db_url:
        return db_url

    # Priority 3: TARGET_DB_URL env var
    db_url = os.environ.get("TARGET_DB_URL")
    if db_url:
        return db_url

    # Priority 4: MARKETDATA_DB_URL env var
    db_url = os.environ.get("MARKETDATA_DB_URL")
    if db_url:
        return db_url

    raise RuntimeError(
        "Database URL not found. Please provide via:\n"
        "  1. --db-url CLI argument, or\n"
        "  2. db_config.env file (TARGET_DB_URL=...), or\n"
        "  3. TARGET_DB_URL environment variable, or\n"
        "  4. MARKETDATA_DB_URL environment variable"
    )


def _load_db_url_from_config() -> str | None:
    """
    Search for db_config.env file up to 5 directories up.

    Returns:
        TARGET_DB_URL value if found, None otherwise
    """
    current = Path.cwd()

    # Search up to 5 directories up
    for _ in range(5):
        config_path = current / "db_config.env"
        if config_path.exists():
            # Parse file for TARGET_DB_URL
            with open(config_path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("TARGET_DB_URL="):
                        return line.split("=", 1)[1].strip()
        # Go up one level
        parent = current.parent
        if parent == current:
            # Reached filesystem root
            break
        current = parent

    return None
