"""
regime_inspect.py - DB-backed regime inspection CLI tool.

Provides ad-hoc inspection of regime state for any asset, reading from the
cmc_regimes, cmc_regime_flips, and cmc_regime_stats tables.

Default mode queries the latest regime row from cmc_regimes and prints a
formatted summary of the active layers, labels, and resolved policy.

Optional modes:
  --live    Compute regime on-the-fly via compute_regimes_for_id (not stored)
  --history Show last N days of regime history as a table
  --flips   Show recent regime transitions from cmc_regime_flips

Usage:
    python -m ta_lab2.scripts.regimes.regime_inspect --id 1
    python -m ta_lab2.scripts.regimes.regime_inspect --id 1 --live
    python -m ta_lab2.scripts.regimes.regime_inspect --id 1 --history 30
    python -m ta_lab2.scripts.regimes.regime_inspect --id 1 --flips
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import Optional

import pandas as pd
from sqlalchemy import create_engine, text

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _fmt_label(label: Optional[str], enabled: Optional[bool]) -> str:
    """Format a layer label with enabled/disabled indicator."""
    if enabled is False:
        return "-                    [disabled]"
    if label is None or (isinstance(label, float) and pd.isna(label)):
        return "None                 [enabled]"
    return f"{label:<20} [enabled]"


def _fmt_bool(val) -> str:
    """Format a boolean or None value."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return "-"
    return str(bool(val))


def _fmt_float(val, decimals: int = 2) -> str:
    """Format a float or None value."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return "-"
    return f"{float(val):.{decimals}f}"


def _lookup_asset_symbol(engine, asset_id: int) -> str:
    """Look up asset symbol from dim_assets, returns 'id=N' if not found."""
    try:
        with engine.connect() as conn:
            result = conn.execute(
                text("SELECT symbol FROM public.dim_assets WHERE id = :id LIMIT 1"),
                {"id": asset_id},
            )
            row = result.fetchone()
            if row:
                return str(row[0])
    except Exception:
        pass
    return f"id={asset_id}"


# ---------------------------------------------------------------------------
# Display modes
# ---------------------------------------------------------------------------


def show_latest(engine, asset_id: int, tf: str, verbose: bool) -> int:
    """
    Query and display the latest regime row from cmc_regimes.

    Returns 0 on success, 1 on error.
    """
    sql = text(
        """
        SELECT
            id, ts, tf,
            l0_label, l1_label, l2_label, l3_label, l4_label,
            l0_enabled, l1_enabled, l2_enabled,
            regime_key,
            size_mult, stop_mult, orders, gross_cap, pyramids,
            feature_tier,
            regime_version_hash,
            updated_at
        FROM public.cmc_regimes
        WHERE id = :id AND tf = :tf
        ORDER BY ts DESC
        LIMIT 1
        """
    )

    try:
        with engine.connect() as conn:
            result = conn.execute(sql, {"id": asset_id, "tf": tf})
            row = result.fetchone()
    except Exception as exc:
        print(f"[ERROR] Failed to query cmc_regimes: {exc}")
        return 1

    if row is None:
        print(f"[WARNING] No regime data found for id={asset_id} tf={tf}")
        print(
            "         Run: python -m ta_lab2.scripts.regimes.refresh_cmc_regimes --ids {asset_id}"
        )
        return 1

    # Map columns
    (
        _id,
        ts,
        _tf,
        l0_label,
        l1_label,
        l2_label,
        l3_label,
        l4_label,
        l0_enabled,
        l1_enabled,
        l2_enabled,
        regime_key,
        size_mult,
        stop_mult,
        orders,
        gross_cap,
        pyramids,
        feature_tier,
        version_hash,
        updated_at,
    ) = row

    symbol = _lookup_asset_symbol(engine, asset_id)
    ts_str = pd.Timestamp(ts).strftime("%Y-%m-%d") if ts else "-"
    updated_str = (
        pd.Timestamp(updated_at).strftime("%Y-%m-%d %H:%M:%S UTC")
        if updated_at
        else "-"
    )

    print(f"\nAsset: {symbol} (id={asset_id})")
    print(f"As of: {ts_str}")
    print(f"Feature tier: {feature_tier or '-'}")
    print()
    print(f"  L0 (Monthly):  {_fmt_label(l0_label, l0_enabled)}")
    print(f"  L1 (Weekly):   {_fmt_label(l1_label, l1_enabled)}")
    print(f"  L2 (Daily):    {_fmt_label(l2_label, l2_enabled)}")
    print(f"  L3 (Intra):    {_fmt_label(l3_label, False)}")
    print()
    print("Resolved Policy:")
    print(f"  regime_key = {regime_key or 'Unknown'}")
    print(f"  size_mult  = {_fmt_float(size_mult)}")
    print(f"  stop_mult  = {_fmt_float(stop_mult)}")
    print(f"  orders     = {orders or '-'}")
    print(f"  pyramids   = {_fmt_bool(pyramids)}")
    print(f"  gross_cap  = {_fmt_float(gross_cap)}")
    print()
    print(f"Version hash: {version_hash or '-'}")
    print(f"Last updated: {updated_str}")

    return 0


def show_live(engine, asset_id: int, tf: str, verbose: bool) -> int:
    """
    Compute regime on-the-fly using compute_regimes_for_id and display result.

    Returns 0 on success, 1 on error.
    """
    from ta_lab2.scripts.regimes.refresh_cmc_regimes import compute_regimes_for_id

    print(f"\n[LIVE] Computing regime for id={asset_id} tf={tf} (not stored)...")

    try:
        df = compute_regimes_for_id(engine, asset_id)
    except Exception as exc:
        print(f"[ERROR] compute_regimes_for_id failed: {exc}")
        return 1

    if df.empty:
        print(f"[WARNING] No regime data computed for id={asset_id}")
        return 1

    # Take the latest row
    row = df.iloc[-1]
    symbol = _lookup_asset_symbol(engine, asset_id)
    ts_str = (
        pd.Timestamp(row["ts"]).strftime("%Y-%m-%d") if pd.notna(row.get("ts")) else "-"
    )

    print(f"\nAsset: {symbol} (id={asset_id}) -- LIVE (not stored)")
    print(f"As of: {ts_str}")
    print(f"Feature tier: {row.get('feature_tier', '-')}")
    print()
    print(f"  L0 (Monthly):  {_fmt_label(row.get('l0_label'), row.get('l0_enabled'))}")
    print(f"  L1 (Weekly):   {_fmt_label(row.get('l1_label'), row.get('l1_enabled'))}")
    print(f"  L2 (Daily):    {_fmt_label(row.get('l2_label'), row.get('l2_enabled'))}")
    print(f"  L3 (Intra):    {_fmt_label(row.get('l3_label'), False)}")
    print()
    print("Resolved Policy:")
    print(f"  regime_key = {row.get('regime_key', 'Unknown')}")
    print(f"  size_mult  = {_fmt_float(row.get('size_mult'))}")
    print(f"  stop_mult  = {_fmt_float(row.get('stop_mult'))}")
    print(f"  orders     = {row.get('orders', '-')}")
    print(f"  pyramids   = {_fmt_bool(row.get('pyramids'))}")
    print(f"  gross_cap  = {_fmt_float(row.get('gross_cap'))}")
    print()
    print(f"Version hash: {row.get('regime_version_hash', '-')}")

    return 0


def show_history(engine, asset_id: int, tf: str, n_days: int, verbose: bool) -> int:
    """
    Show last N days of regime history from cmc_regimes as a table.

    Returns 0 on success, 1 on error.
    """
    sql = text(
        """
        SELECT ts, regime_key, size_mult, stop_mult, orders, gross_cap
        FROM public.cmc_regimes
        WHERE id = :id AND tf = :tf
        ORDER BY ts DESC
        LIMIT :n
        """
    )

    try:
        with engine.connect() as conn:
            df = pd.read_sql(sql, conn, params={"id": asset_id, "tf": tf, "n": n_days})
    except Exception as exc:
        print(f"[ERROR] Failed to query cmc_regimes history: {exc}")
        return 1

    if df.empty:
        print(f"[WARNING] No regime history found for id={asset_id} tf={tf}")
        return 1

    symbol = _lookup_asset_symbol(engine, asset_id)
    print(f"\nRegime history for {symbol} (id={asset_id}) -- last {n_days} days:")
    print()

    # Format for display
    df["ts"] = pd.to_datetime(df["ts"]).dt.strftime("%Y-%m-%d")
    df["size_mult"] = df["size_mult"].apply(lambda x: _fmt_float(x))
    df["stop_mult"] = df["stop_mult"].apply(lambda x: _fmt_float(x))
    df["gross_cap"] = df["gross_cap"].apply(lambda x: _fmt_float(x))
    df["orders"] = df["orders"].fillna("-")

    # Reverse so oldest first
    df = df.iloc[::-1].reset_index(drop=True)

    # Print as table
    col_widths = {
        "ts": 12,
        "regime_key": 28,
        "size_mult": 10,
        "stop_mult": 10,
        "gross_cap": 10,
        "orders": 10,
    }
    header = (
        f"{'Date':<{col_widths['ts']}}"
        f"{'Regime Key':<{col_widths['regime_key']}}"
        f"{'Size':<{col_widths['size_mult']}}"
        f"{'Stop':<{col_widths['stop_mult']}}"
        f"{'Cap':<{col_widths['gross_cap']}}"
        f"{'Orders':<{col_widths['orders']}}"
    )
    print(header)
    print("-" * len(header))

    for _, row in df.iterrows():
        regime_key = str(row.get("regime_key", "-") or "-")
        print(
            f"{str(row['ts']):<{col_widths['ts']}}"
            f"{regime_key:<{col_widths['regime_key']}}"
            f"{str(row['size_mult']):<{col_widths['size_mult']}}"
            f"{str(row['stop_mult']):<{col_widths['stop_mult']}}"
            f"{str(row['gross_cap']):<{col_widths['gross_cap']}}"
            f"{str(row['orders']):<{col_widths['orders']}}"
        )

    print(f"\n{len(df)} rows shown")
    return 0


def show_flips(engine, asset_id: int, tf: str, verbose: bool) -> int:
    """
    Show recent regime transitions from cmc_regime_flips.

    Returns 0 on success, 1 on error.
    """
    sql = text(
        """
        SELECT ts, layer, old_regime, new_regime, bars_held
        FROM public.cmc_regime_flips
        WHERE id = :id AND tf = :tf
        ORDER BY ts DESC
        LIMIT 20
        """
    )

    try:
        with engine.connect() as conn:
            df = pd.read_sql(sql, conn, params={"id": asset_id, "tf": tf})
    except Exception as exc:
        print(f"[ERROR] Failed to query cmc_regime_flips: {exc}")
        return 1

    if df.empty:
        print(f"[WARNING] No regime flips found for id={asset_id} tf={tf}")
        return 1

    symbol = _lookup_asset_symbol(engine, asset_id)
    print(f"\nRecent regime transitions for {symbol} (id={asset_id}) -- last 20:")
    print()

    df["ts"] = pd.to_datetime(df["ts"]).dt.strftime("%Y-%m-%d")
    df["old_regime"] = df["old_regime"].fillna("(initial)")
    df["bars_held"] = df["bars_held"].fillna("-").astype(str)

    # Reverse so oldest first
    df = df.iloc[::-1].reset_index(drop=True)

    col_widths = {
        "ts": 12,
        "layer": 7,
        "old_regime": 28,
        "new_regime": 28,
        "bars_held": 10,
    }
    header = (
        f"{'Date':<{col_widths['ts']}}"
        f"{'Layer':<{col_widths['layer']}}"
        f"{'Old Regime':<{col_widths['old_regime']}}"
        f"{'New Regime':<{col_widths['new_regime']}}"
        f"{'Bars Held':<{col_widths['bars_held']}}"
    )
    print(header)
    print("-" * len(header))

    for _, row in df.iterrows():
        print(
            f"{str(row['ts']):<{col_widths['ts']}}"
            f"{str(row.get('layer', '-')):<{col_widths['layer']}}"
            f"{str(row['old_regime']):<{col_widths['old_regime']}}"
            f"{str(row.get('new_regime', '-')):<{col_widths['new_regime']}}"
            f"{str(row['bars_held']):<{col_widths['bars_held']}}"
        )

    print(f"\n{len(df)} transitions shown")
    return 0


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------


def main(argv: Optional[list[str]] = None) -> int:
    """
    CLI entrypoint for regime inspection.

    Example usage:
        python -m ta_lab2.scripts.regimes.regime_inspect --id 1
        python -m ta_lab2.scripts.regimes.regime_inspect --id 1 --live
        python -m ta_lab2.scripts.regimes.regime_inspect --id 1 --history 30
        python -m ta_lab2.scripts.regimes.regime_inspect --id 1 --flips
    """
    parser = argparse.ArgumentParser(
        description="Inspect regime state for an asset from the DB.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument(
        "--id",
        type=int,
        required=True,
        metavar="ASSET_ID",
        help="Asset ID to inspect (e.g. 1 for BTC).",
    )
    parser.add_argument(
        "--tf",
        type=str,
        default="1D",
        metavar="TF",
        help="Timeframe to query (default: 1D).",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Compute regime on-the-fly via compute_regimes_for_id (not from DB).",
    )
    parser.add_argument(
        "--history",
        type=int,
        default=None,
        metavar="N",
        help="Show last N days of regime history from cmc_regimes.",
    )
    parser.add_argument(
        "--flips",
        action="store_true",
        help="Show recent regime transitions from cmc_regime_flips (last 20).",
    )
    parser.add_argument(
        "--db-url",
        type=str,
        default=None,
        metavar="URL",
        help="PostgreSQL connection URL. Defaults to TARGET_DB_URL env var.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable DEBUG logging.",
    )

    args = parser.parse_args(argv)

    # Logging
    log_level = logging.DEBUG if args.verbose else logging.WARNING
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)-7s %(name)s %(message)s",
        datefmt="%H:%M:%S",
    )

    # DB connection
    db_url = args.db_url or os.environ.get("TARGET_DB_URL")
    if not db_url:
        print("[ERROR] No DB URL provided. Set TARGET_DB_URL or pass --db-url.")
        return 1

    engine = create_engine(db_url)

    # Dispatch to the requested mode
    rc = 0

    if args.live:
        rc = show_live(engine, args.id, args.tf, args.verbose)
    elif args.history is not None:
        rc = show_history(engine, args.id, args.tf, args.history, args.verbose)
    elif args.flips:
        rc = show_flips(engine, args.id, args.tf, args.verbose)
    else:
        # Default: show latest from DB
        rc = show_latest(engine, args.id, args.tf, args.verbose)

    return rc


if __name__ == "__main__":
    sys.exit(main())
