#!/usr/bin/env python
"""
Batch refresh script for triple barrier labels.

Loads close prices from cmc_price_bars_multi_tf_u, computes vol-scaled triple
barrier labels using AFML Ch.3 methodology, and persists to the
cmc_triple_barrier_labels table with upsert semantics.

Labels:
  bin = +1  profit target (upper barrier) hit first
  bin = -1  stop loss (lower barrier) hit first
  bin =  0  vertical barrier (timeout) or no barrier reached

Usage:
    python -m ta_lab2.scripts.labeling.refresh_triple_barrier_labels --ids 1,52 --tf 1D
    python -m ta_lab2.scripts.labeling.refresh_triple_barrier_labels --all --tf 1D
    python -m ta_lab2.scripts.labeling.refresh_triple_barrier_labels --ids 1 --tf 1D --cusum-filter
    python -m ta_lab2.scripts.labeling.refresh_triple_barrier_labels --ids 1 --tf 1D --dry-run
    python -m ta_lab2.scripts.labeling.refresh_triple_barrier_labels --ids 1 --tf 1D --full-refresh
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from ta_lab2.config import TARGET_DB_URL
from ta_lab2.labeling.cusum_filter import cusum_filter, get_cusum_threshold
from ta_lab2.labeling.triple_barrier import apply_triple_barriers, get_daily_vol

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Refresh triple barrier labels in cmc_triple_barrier_labels",
    )

    # Asset selection (mutually exclusive)
    id_group = parser.add_mutually_exclusive_group(required=True)
    id_group.add_argument(
        "--ids",
        help="Comma-separated asset IDs (e.g., '1,52,1027')",
    )
    id_group.add_argument(
        "--all",
        action="store_true",
        help="Process all assets found in cmc_price_bars_multi_tf_u for the given tf",
    )

    # Timeframe
    parser.add_argument(
        "--tf",
        default="1D",
        help="Timeframe string (default: '1D')",
    )

    # Barrier parameters
    parser.add_argument(
        "--pt",
        type=float,
        default=1.0,
        help="Profit-taking multiplier (default: 1.0)",
    )
    parser.add_argument(
        "--sl",
        type=float,
        default=1.0,
        help="Stop-loss multiplier (default: 1.0)",
    )
    parser.add_argument(
        "--vertical-bars",
        type=int,
        default=10,
        help="Vertical barrier bar count (default: 10)",
    )
    parser.add_argument(
        "--vol-span",
        type=int,
        default=100,
        help="EWM vol span for get_daily_vol (default: 100)",
    )

    # CUSUM filter
    parser.add_argument(
        "--cusum-filter",
        action="store_true",
        help="Use CUSUM filter to select events instead of every non-NaN vol bar",
    )
    parser.add_argument(
        "--cusum-multiplier",
        type=float,
        default=2.0,
        help="CUSUM threshold multiplier (default: 2.0, only used with --cusum-filter)",
    )

    # Refresh / execution control
    parser.add_argument(
        "--full-refresh",
        action="store_true",
        help="Delete existing labels for these params before inserting",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute labels but do NOT write to DB",
    )

    # Logging
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable debug logging",
    )

    # DB override
    parser.add_argument(
        "--db-url",
        help="Database URL (defaults to TARGET_DB_URL env var)",
    )

    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# Asset resolution
# ---------------------------------------------------------------------------


def load_asset_ids(engine, ids_arg: Optional[str], all_ids: bool, tf: str) -> list[int]:
    """Resolve the list of asset IDs to process."""
    if ids_arg:
        return [int(i.strip()) for i in ids_arg.split(",")]

    if all_ids:
        # cmc_price_bars_multi_tf_u uses 'id' as the asset identifier column
        q = text(
            "SELECT DISTINCT id FROM cmc_price_bars_multi_tf_u "
            "WHERE tf = :tf ORDER BY id"
        )
        with engine.connect() as conn:
            rows = conn.execute(q, {"tf": tf}).fetchall()
        return [r[0] for r in rows]

    return []


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def load_close(engine, asset_id: int, tf: str) -> pd.Series:
    """Load close price series as a tz-aware UTC DatetimeIndex pd.Series."""
    # Note: cmc_price_bars_multi_tf_u uses 'timestamp' (not 'ts') as the datetime column.
    q = text(
        "SELECT timestamp, close "
        "FROM cmc_price_bars_multi_tf_u "
        "WHERE id = :id AND tf = :tf "
        "ORDER BY timestamp"
    )
    with engine.connect() as conn:
        df = pd.read_sql(q, conn, params={"id": asset_id, "tf": tf})

    if df.empty:
        return pd.Series(dtype="float64")

    # Build tz-aware UTC DatetimeIndex without assuming the DB returns tz-naive or tz-aware.
    # pd.to_datetime with utc=True handles both forms safely.
    ts = pd.to_datetime(df["timestamp"], utc=True)
    close = pd.Series(df["close"].values, index=ts, name="close", dtype="float64")
    close = close.sort_index()
    return close


# ---------------------------------------------------------------------------
# DB write: upsert
# ---------------------------------------------------------------------------

_UPSERT_SQL = """
INSERT INTO cmc_triple_barrier_labels
    (label_id, asset_id, tf, t0, t1,
     pt_multiplier, sl_multiplier, vertical_bars,
     daily_vol, target, ret, bin, barrier_type, computed_at)
VALUES
    (:label_id, :asset_id, :tf, :t0, :t1,
     :pt_multiplier, :sl_multiplier, :vertical_bars,
     :daily_vol, :target, :ret, :bin, :barrier_type, :computed_at)
ON CONFLICT ON CONSTRAINT uq_triple_barrier_key
DO UPDATE SET
    t1           = EXCLUDED.t1,
    ret          = EXCLUDED.ret,
    bin          = EXCLUDED.bin,
    barrier_type = EXCLUDED.barrier_type,
    daily_vol    = EXCLUDED.daily_vol,
    target       = EXCLUDED.target,
    computed_at  = EXCLUDED.computed_at
"""

_DELETE_SQL = """
DELETE FROM cmc_triple_barrier_labels
WHERE  asset_id      = :asset_id
  AND  tf            = :tf
  AND  pt_multiplier = :pt
  AND  sl_multiplier = :sl
  AND  vertical_bars = :vb
"""


def _to_python_float(v) -> Optional[float]:
    """Coerce numpy scalar or None to plain Python float (or None)."""
    if v is None:
        return None
    try:
        import math

        f = float(v)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


def write_labels(
    engine,
    asset_id: int,
    tf: str,
    labels: pd.DataFrame,
    vol: pd.Series,
    pt: float,
    sl: float,
    vertical_bars: int,
    full_refresh: bool,
) -> int:
    """
    Upsert a labels DataFrame into cmc_triple_barrier_labels.

    Returns number of rows written.
    """
    if labels.empty:
        return 0

    computed_at = datetime.now(timezone.utc)
    rows = []

    for t0, row in labels.iterrows():
        daily_vol_val = _to_python_float(vol.loc[t0] if t0 in vol.index else None)
        rows.append(
            {
                "label_id": str(uuid.uuid4()),
                "asset_id": int(asset_id),
                "tf": tf,
                "t0": t0.to_pydatetime(),
                "t1": row["t1"].to_pydatetime() if pd.notna(row["t1"]) else None,
                "pt_multiplier": float(pt),
                "sl_multiplier": float(sl),
                "vertical_bars": int(vertical_bars),
                "daily_vol": daily_vol_val,
                "target": daily_vol_val,  # vol-scaled target == daily_vol at t0
                "ret": _to_python_float(row["ret"]),
                "bin": int(row["bin"]),
                "barrier_type": str(row["barrier_type"]),
                "computed_at": computed_at,
            }
        )

    with engine.begin() as conn:
        if full_refresh:
            conn.execute(
                text(_DELETE_SQL),
                {
                    "asset_id": int(asset_id),
                    "tf": tf,
                    "pt": float(pt),
                    "sl": float(sl),
                    "vb": int(vertical_bars),
                },
            )
            logger.debug(
                f"  [full-refresh] Deleted existing labels for asset_id={asset_id}"
            )

        for row in rows:
            conn.execute(text(_UPSERT_SQL), row)

    return len(rows)


# ---------------------------------------------------------------------------
# Per-asset processing
# ---------------------------------------------------------------------------


def process_asset(
    engine,
    asset_id: int,
    tf: str,
    pt: float,
    sl: float,
    vertical_bars: int,
    vol_span: int,
    use_cusum: bool,
    cusum_multiplier: float,
    full_refresh: bool,
    dry_run: bool,
) -> dict:
    """
    Load, label, and (optionally) persist triple barrier labels for one asset.

    Returns a summary dict with keys: asset_id, n_events, dist, n_written.
    """
    close = load_close(engine, asset_id, tf)

    if close.empty or len(close) < vol_span + 5:
        logger.warning(
            f"  asset_id={asset_id}: insufficient data "
            f"({len(close)} bars, need >{vol_span + 5}). Skipping."
        )
        return {"asset_id": asset_id, "n_events": 0, "dist": {}, "n_written": 0}

    # 1. Compute daily vol
    vol = get_daily_vol(close, span=vol_span)

    # 2. Select events
    if use_cusum:
        threshold = get_cusum_threshold(
            close, multiplier=cusum_multiplier, vol_span=vol_span
        )
        events = cusum_filter(close, threshold)
        # Restrict events to bars where vol is available
        events = events[events.isin(vol.dropna().index)]
        logger.debug(
            f"  asset_id={asset_id}: CUSUM filter -> {len(events)} events "
            f"(threshold={threshold:.6f})"
        )
    else:
        events = vol.dropna().index

    if len(events) == 0:
        logger.warning(f"  asset_id={asset_id}: no events after filtering. Skipping.")
        return {"asset_id": asset_id, "n_events": 0, "dist": {}, "n_written": 0}

    # 3. Apply triple barriers
    labels = apply_triple_barriers(
        close=close,
        t_events=events,
        pt_sl=[pt, sl],
        target=vol,
        num_bars=vertical_bars,
    )

    # 4. Distribution log
    if not labels.empty:
        dist = labels["bin"].value_counts().to_dict()
    else:
        dist = {}

    n_events = len(labels)
    logger.info(f"  asset_id={asset_id}: {n_events} labels | dist={dist}")

    if dry_run:
        return {
            "asset_id": asset_id,
            "n_events": n_events,
            "dist": dist,
            "n_written": 0,
        }

    # 5. Write to DB
    n_written = write_labels(
        engine=engine,
        asset_id=asset_id,
        tf=tf,
        labels=labels,
        vol=vol,
        pt=pt,
        sl=sl,
        vertical_bars=vertical_bars,
        full_refresh=full_refresh,
    )

    logger.debug(f"  asset_id={asset_id}: {n_written} rows upserted")
    return {
        "asset_id": asset_id,
        "n_events": n_events,
        "dist": dist,
        "n_written": n_written,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: Optional[list[str]] = None) -> int:
    """Entry point."""
    args = parse_args(argv)

    # Logging setup
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    t_start = time.time()

    # DB URL
    db_url = args.db_url or TARGET_DB_URL
    if not db_url:
        logger.error("No database URL. Set TARGET_DB_URL or use --db-url.")
        return 1

    # Engine (NullPool for one-shot scripts)
    try:
        engine = create_engine(db_url, poolclass=NullPool)
    except Exception as exc:
        logger.error(f"Failed to create engine: {exc}")
        return 1

    # Resolve assets
    try:
        asset_ids = load_asset_ids(engine, args.ids, args.all, args.tf)
    except Exception as exc:
        logger.error(f"Failed to resolve asset IDs: {exc}")
        return 1

    if not asset_ids:
        logger.error("No asset IDs resolved. Provide --ids or --all.")
        return 1

    logger.info(
        f"Triple barrier refresh | tf={args.tf} | pt={args.pt} | sl={args.sl} | "
        f"vb={args.vertical_bars} | vol_span={args.vol_span} | "
        f"cusum={args.cusum_filter} | full_refresh={args.full_refresh} | "
        f"dry_run={args.dry_run} | n_assets={len(asset_ids)}"
    )

    if args.dry_run:
        logger.info("[DRY RUN MODE] -- no data will be written to the database")

    # Process each asset
    results = []
    for asset_id in asset_ids:
        logger.info(f"Processing asset_id={asset_id} ...")
        try:
            r = process_asset(
                engine=engine,
                asset_id=asset_id,
                tf=args.tf,
                pt=args.pt,
                sl=args.sl,
                vertical_bars=args.vertical_bars,
                vol_span=args.vol_span,
                use_cusum=args.cusum_filter,
                cusum_multiplier=args.cusum_multiplier,
                full_refresh=args.full_refresh,
                dry_run=args.dry_run,
            )
            results.append(r)
        except Exception as exc:
            logger.error(f"  asset_id={asset_id}: FAILED -- {exc}", exc_info=True)
            results.append(
                {"asset_id": asset_id, "n_events": 0, "dist": {}, "n_written": 0}
            )

    # Summary
    elapsed = time.time() - t_start
    total_events = sum(r["n_events"] for r in results)
    total_written = sum(r["n_written"] for r in results)

    # Aggregate bin distribution across all assets
    agg_dist: dict[int, int] = {}
    for r in results:
        for bin_val, cnt in r["dist"].items():
            agg_dist[bin_val] = agg_dist.get(bin_val, 0) + cnt

    logger.info(
        f"\n--- Summary ---\n"
        f"  assets processed : {len(results)}\n"
        f"  total events     : {total_events}\n"
        f"  rows written     : {total_written}\n"
        f"  label dist       : {dict(sorted(agg_dist.items()))}\n"
        f"  elapsed          : {elapsed:.1f}s"
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
