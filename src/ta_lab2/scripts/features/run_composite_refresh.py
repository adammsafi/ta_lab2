"""
Composite indicator refresh orchestrator.

Computes all 6 proprietary composite indicators for each active asset and
writes results to the public.features table using the UPDATE pattern
(preserving all other feature columns).

Usage
-----
    # Dry-run for BTC (id=1) on tf=1D -- compute but do not write:
    python -m ta_lab2.scripts.features.run_composite_refresh --dry-run --ids 1 --tf 1 --verbose

    # Write composites for a specific subset:
    python -m ta_lab2.scripts.features.run_composite_refresh --ids 1,52 --tf 1

    # Run all active assets on tf=1D (default):
    python -m ta_lab2.scripts.features.run_composite_refresh --tf 1 --verbose

    # Run only specific composites:
    python -m ta_lab2.scripts.features.run_composite_refresh --composites ama_er_regime_signal,volume_regime_gated_trend

Composites
----------
1. ama_er_regime_signal           -- KAMA ER rank x direction; range [-1, +1]
2. oi_divergence_ctf_agreement    -- OI div x CTF gate; HL perps only
3. funding_adjusted_momentum      -- Price mom - funding z-score; HL perps only
4. cross_asset_lead_lag_composite -- IC-weighted lead-lag signals
5. tf_alignment_score             -- Mean CTF agreement - 0.5; range [-0.5, +0.5]
6. volume_regime_gated_trend      -- ATR-normalised trend x tanh vol gate

Write pattern
-------------
UPDATE public.features SET {col} = :value
WHERE id = :id AND venue_id = :venue_id AND ts = :ts AND tf = :tf

Per-asset temp-table bulk UPDATE is used for performance.
DELETE+INSERT is NOT used -- other feature columns are preserved.

Notes
-----
- ASCII-only source; encoding='utf-8' on all file/SQL output.
- NullPool engine (no cross-process connection sharing).
- Per-asset errors are logged and skipped; one bad asset never aborts the run.
- HL composites (2, 3) return NaN Series for assets not on Hyperliquid --
  this is expected behaviour and not an error.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from typing import Optional

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from ta_lab2.config import TARGET_DB_URL
from ta_lab2.features.composite_indicators import (
    ALL_COMPOSITES,
    COMPOSITE_NAMES,
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Composite dispatch helpers
# ---------------------------------------------------------------------------

# Composites that require the cmc_symbol argument
_NEEDS_CMC_SYMBOL: frozenset[str] = frozenset(
    {
        "oi_divergence_ctf_agreement",
        "funding_adjusted_momentum",
    }
)

# Composite 5 (tf_alignment_score) has a different signature -- no tf arg.
_NO_TF_ARG: frozenset[str] = frozenset({"tf_alignment_score"})


def _call_composite(
    name: str,
    conn,
    asset_id: int,
    venue_id: int,
    tf: str,
    cmc_symbol: Optional[str] = None,
) -> pd.Series:
    """Dispatch to the correct composite compute function.

    Handles the different signatures across composites:
    - Most: (conn, asset_id, venue_id, tf)
    - OI/funding: (conn, asset_id, venue_id, tf, cmc_symbol)
    - TF alignment: (conn, asset_id, venue_id)  -- no tf arg

    Returns an empty Series (with correct .name) on any error.
    """
    fn = ALL_COMPOSITES[name]

    if name in _NEEDS_CMC_SYMBOL:
        # Composites 2 and 3 need cmc_symbol; return NaN if symbol unavailable.
        if not cmc_symbol:
            logger.debug(
                "%s: skipping asset_id=%d -- no cmc_symbol available",
                name,
                asset_id,
            )
            return pd.Series(dtype=float, name=name)
        return fn(conn, asset_id, venue_id, tf, cmc_symbol)

    if name in _NO_TF_ARG:
        # Composite 5: tf_alignment_score(conn, asset_id, venue_id)
        return fn(conn, asset_id, venue_id)

    # Default: (conn, asset_id, venue_id, tf)
    return fn(conn, asset_id, venue_id, tf)


# ---------------------------------------------------------------------------
# Asset / symbol discovery
# ---------------------------------------------------------------------------


def _discover_asset_ids(engine, tf: str, venue_id: int) -> list[int]:
    """Query DISTINCT id from public.features for the given tf / venue_id."""
    sql = text(
        """
        SELECT DISTINCT id
        FROM public.features
        WHERE tf = :tf
          AND venue_id = :venue_id
        ORDER BY id
        """
    )
    with engine.connect() as conn:
        rows = conn.execute(sql, {"tf": tf, "venue_id": venue_id}).fetchall()
    return [int(r[0]) for r in rows]


def _load_id_symbol_map(engine, ids: list[int]) -> dict[int, str]:
    """Query id -> symbol from cmc_da_ids for the given id list.

    Returns an empty dict if cmc_da_ids is not populated or all ids are
    absent.  The symbol is the CMC ticker (e.g. 'BTC', 'ETH').
    """
    if not ids:
        return {}
    sql = text(
        """
        SELECT id, symbol
        FROM public.cmc_da_ids
        WHERE id = ANY(:ids)
        """
    )
    with engine.connect() as conn:
        rows = conn.execute(sql, {"ids": ids}).fetchall()
    return {int(r[0]): str(r[1]) for r in rows}


# ---------------------------------------------------------------------------
# Write helpers
# ---------------------------------------------------------------------------


def _build_temp_table_and_update(
    conn,
    col_name: str,
    series: pd.Series,
    asset_id: int,
    venue_id: int,
    tf: str,
    dry_run: bool,
) -> int:
    """Write a composite column for one asset using temp-table bulk UPDATE.

    Creates a temporary table with (ts, val), then issues:
        UPDATE public.features AS f
        SET {col_name} = t.val
        FROM _tmp_composite AS t
        WHERE f.id = :id AND f.venue_id = :venue_id AND f.tf = :tf
          AND f.ts = t.ts AND t.val IS NOT NULL

    Returns the number of rows matched (updated).
    """
    # Drop NaN rows -- no point writing NULL over NULL.
    s_clean = series.dropna()
    if s_clean.empty:
        return 0

    if dry_run:
        return len(s_clean)

    # Create per-session temp table (dropped automatically at end of connection).
    conn.execute(
        text(
            """
            CREATE TEMP TABLE IF NOT EXISTS _tmp_composite (
                ts TIMESTAMPTZ NOT NULL,
                val DOUBLE PRECISION
            ) ON COMMIT DELETE ROWS
            """
        )
    )
    # Truncate in case table was reused from a previous composite in same conn.
    conn.execute(text("TRUNCATE _tmp_composite"))

    # Bulk-insert composite values into temp table.
    rows = [{"ts": ts.isoformat(), "val": float(val)} for ts, val in s_clean.items()]
    conn.execute(
        text("INSERT INTO _tmp_composite (ts, val) VALUES (:ts, :val)"),
        rows,
    )

    # Update features from temp table.
    result = conn.execute(
        text(
            f"""
            UPDATE public.features AS f
            SET {col_name} = t.val
            FROM _tmp_composite AS t
            WHERE f.id = :id
              AND f.venue_id = :venue_id
              AND f.tf = :tf
              AND f.ts = t.ts
            """
        ),
        {"id": asset_id, "venue_id": venue_id, "tf": tf},
    )
    return result.rowcount


# ---------------------------------------------------------------------------
# Per-asset computation and write
# ---------------------------------------------------------------------------


def _process_asset(
    engine,
    asset_id: int,
    venue_id: int,
    tf: str,
    cmc_symbol: Optional[str],
    composites: list[str],
    dry_run: bool,
    verbose: bool,
) -> dict[str, int]:
    """Compute and write all requested composites for a single asset.

    Each composite gets its own connection so that a failed SQL inside one
    composite's data loader does not abort the transaction and block all
    subsequent composites for the same asset.

    Returns a dict: composite_name -> rows_written (0 on error or no data).
    """
    rows_written: dict[str, int] = {c: 0 for c in composites}

    for name in composites:
        try:
            # Fresh connection per composite: isolates aborted-transaction state
            # from one composite's missing-table error from the next composite.
            with engine.connect() as conn:
                series = _call_composite(
                    name,
                    conn,
                    asset_id,
                    venue_id,
                    tf,
                    cmc_symbol=cmc_symbol,
                )

            # Write in a separate fresh connection to avoid temp-table collision.
            with engine.connect() as conn:
                with conn.begin():
                    n = _build_temp_table_and_update(
                        conn,
                        name,
                        series,
                        asset_id,
                        venue_id,
                        tf,
                        dry_run,
                    )

            rows_written[name] = n
            if verbose:
                sym_label = f"({cmc_symbol})" if cmc_symbol else ""
                logger.info(
                    "  asset_id=%-5d %s  %-40s  %d rows",
                    asset_id,
                    sym_label,
                    name,
                    n,
                )
        except Exception:
            logger.exception(
                "Composite %s failed for asset_id=%d -- skipping",
                name,
                asset_id,
            )

    return rows_written


# ---------------------------------------------------------------------------
# Coverage reporting
# ---------------------------------------------------------------------------


def _print_coverage_report(
    coverage: dict[
        str, dict
    ],  # composite -> {assets_with_data, total_assets, total_rows}
    composites: list[str],
    total_assets: int,
) -> None:
    """Print a per-composite coverage summary table."""
    print("\n" + "=" * 70, flush=True)
    print(
        f"{'Composite':<45} {'Assets w/data':>13} {'Coverage%':>9} {'Rows':>8}",
        flush=True,
    )
    print("-" * 70, flush=True)
    for name in composites:
        stats = coverage.get(name, {})
        n_assets = stats.get("assets_with_data", 0)
        n_rows = stats.get("total_rows", 0)
        pct = (n_assets / total_assets * 100) if total_assets > 0 else 0.0
        flag = " *** LOW COVERAGE" if pct < 30 and name not in _NEEDS_CMC_SYMBOL else ""
        print(
            f"  {name:<43} {n_assets:>13d} {pct:>8.1f}% {n_rows:>8d}{flag}",
            flush=True,
        )
    print("=" * 70 + "\n", flush=True)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Compute and write proprietary composite indicators "
            "to the public.features table."
        )
    )
    parser.add_argument(
        "--ids",
        type=str,
        default=None,
        help=(
            "Comma-separated CMC asset IDs to process. "
            "Default: all IDs with rows in features table."
        ),
    )
    parser.add_argument(
        "--tf",
        type=str,
        default="1",
        help="Timeframe filter (e.g. '1', '1D'). Default: '1'.",
    )
    parser.add_argument(
        "--venue-id",
        type=int,
        default=1,
        dest="venue_id",
        help="Venue ID (1=CMC_AGG). Default: 1.",
    )
    parser.add_argument(
        "--composites",
        type=str,
        default=None,
        help=(
            "Comma-separated composite names to compute. "
            f"Default: all ({', '.join(COMPOSITE_NAMES)})."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        dest="dry_run",
        help="Compute but do not write to the database.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        default=False,
        help="Print per-asset per-composite row counts.",
    )
    args = parser.parse_args()

    # Resolve composite list.
    if args.composites:
        requested = [c.strip() for c in args.composites.split(",")]
        invalid = [c for c in requested if c not in ALL_COMPOSITES]
        if invalid:
            print(
                f"ERROR: unknown composites: {invalid}. Valid: {COMPOSITE_NAMES}",
                file=sys.stderr,
            )
            sys.exit(1)
        composites = requested
    else:
        composites = list(COMPOSITE_NAMES)

    if args.dry_run:
        logger.info("DRY-RUN mode -- no writes to features table.")

    logger.info(
        "Composite refresh starting -- tf=%s venue_id=%d composites=%s",
        args.tf,
        args.venue_id,
        composites,
    )

    t0_total = time.time()

    engine = create_engine(TARGET_DB_URL, poolclass=NullPool, future=True)

    # Resolve asset IDs.
    if args.ids:
        asset_ids = [int(i.strip()) for i in args.ids.split(",")]
        logger.info("Using %d user-specified asset IDs.", len(asset_ids))
    else:
        logger.info("Discovering active asset IDs from features table...")
        asset_ids = _discover_asset_ids(engine, args.tf, args.venue_id)
        logger.info("Found %d active assets for tf=%s.", len(asset_ids), args.tf)

    if not asset_ids:
        logger.warning("No asset IDs found -- nothing to process.")
        sys.exit(0)

    # Build id -> symbol map (needed for HL composites).
    id_symbol_map = _load_id_symbol_map(engine, asset_ids)
    logger.info(
        "Symbol map loaded for %d/%d assets.", len(id_symbol_map), len(asset_ids)
    )

    # Per-composite coverage accumulators.
    coverage: dict[str, dict] = {
        name: {"assets_with_data": 0, "total_rows": 0} for name in composites
    }
    errors: list[int] = []

    # Main processing loop.
    for i, asset_id in enumerate(asset_ids, start=1):
        cmc_symbol = id_symbol_map.get(asset_id)
        if args.verbose:
            sym_label = cmc_symbol or "?"
            logger.info(
                "[%d/%d] Processing asset_id=%d (%s)",
                i,
                len(asset_ids),
                asset_id,
                sym_label,
            )

        try:
            rows = _process_asset(
                engine,
                asset_id,
                args.venue_id,
                args.tf,
                cmc_symbol,
                composites,
                args.dry_run,
                args.verbose,
            )
        except Exception:
            logger.exception("Unexpected error for asset_id=%d -- continuing", asset_id)
            errors.append(asset_id)
            continue

        for name, n in rows.items():
            if n > 0:
                coverage[name]["assets_with_data"] += 1
                coverage[name]["total_rows"] += n

    duration = time.time() - t0_total
    total_rows = sum(stats["total_rows"] for stats in coverage.values())

    logger.info(
        "Composite refresh complete -- %d assets, %d total rows, %.1fs",
        len(asset_ids),
        total_rows,
        duration,
    )
    if errors:
        logger.warning("Errors on %d asset(s): %s", len(errors), errors[:10])

    _print_coverage_report(coverage, composites, len(asset_ids))

    if args.dry_run:
        print("DRY-RUN complete -- no data written.", flush=True)


if __name__ == "__main__":
    main()
