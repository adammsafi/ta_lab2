"""Refresh the public.table_summary table with current DB metadata and type labels.

Usage:
    python -m ta_lab2.scripts.setup.refresh_table_summary
    python -m ta_lab2.scripts.setup.refresh_table_summary --dry-run
"""
from __future__ import annotations

import argparse
import logging
import os

from sqlalchemy import create_engine, text

logger = logging.getLogger(__name__)

# ── Type classification rules ──────────────────────────────────────────
# Each rule is (substring_match, major, minor, sub) applied in order.
# First match wins. More specific patterns must come before general ones.
# sub_type is overridden later for SNAPSHOT/UNIFIED/BASE detection.

RULES: list[tuple[str, str, str | None, str | None]] = [
    # Staging
    ("_stg_", "STG", None, None),
    # table_summary itself
    ("table_summary", "META", None, None),
    # Backtest output
    ("cmc_backtest_metrics", "BACKTEST", "METRICS", None),
    ("cmc_backtest_runs", "BACKTEST", "RUNS", None),
    ("cmc_backtest_trades", "BACKTEST", "TRADES", None),
    # Signals
    ("cmc_signals_rsi", "SIGNAL", "RSI", None),
    ("cmc_signals_ema", "SIGNAL", "EMA", None),
    ("cmc_signals_atr", "SIGNAL", "ATR", None),
    ("cmc_signal_state", "STATE", "SIGNAL", None),
    # Regime tables
    ("cmc_regime_comovement", "REGIME", "COMOVEMENT", None),
    ("cmc_regime_flips", "REGIME", "FLIPS", None),
    ("cmc_regime_stats", "REGIME", "STATS", None),
    ("cmc_regimes", "REGIME", None, None),
    # QA / reject tables
    ("ema_rejects", "QA", "EMA", None),
    # Stats state tables (before generic state)
    ("returns_ema_stats_state", "STATE", "STATS", "EMA"),
    ("ema_multi_tf_cal_anchor_stats_state", "STATE", "STATS", "EMA"),
    ("ema_multi_tf_cal_stats_state", "STATE", "STATS", "EMA"),
    ("ema_multi_tf_stats_state", "STATE", "STATS", "EMA"),
    # Stats tables
    ("returns_ema_stats", "STATS", "RETURN", "EMA"),
    ("ema_multi_tf_cal_anchor_stats", "STATS", "EMA", None),
    ("ema_multi_tf_cal_stats", "STATS", "EMA", None),
    ("ema_multi_tf_stats", "STATS", "EMA", None),
    ("price_histories7_stats", "STATS", "PRICE", None),
    ("asset_data_coverage", "STATS", "COVERAGE", "ASSET"),
    ("cmc_price_ranges", "STATS", "PRICE", "RANGE"),
    # State tables — returns from bars
    (
        "cmc_returns_bars_multi_tf",
        "STATE",
        "RETURN",
        "BAR",
    ),  # matched by _state suffix below
    # State tables — returns from EMAs
    ("cmc_returns_ema_multi_tf", "STATE", "RETURN", "EMA"),
    # State tables — bars
    ("cmc_price_bars_multi_tf", "STATE", "BAR", None),
    ("cmc_price_bars_1d_state", "STATE", "BAR", None),
    # State tables — EMAs
    ("cmc_ema_multi_tf", "STATE", "EMA", None),
    # State tables — features/pipeline
    ("cmc_feature_state", "STATE", "FEATURE", None),
    ("ta_lab2_pipeline_state", "STATE", "PIPELINE", None),
    # Feature tables
    ("cmc_features", "FEATURE", None, None),
    ("cmc_ta", "FEATURE", "TA", None),
    ("cmc_vol", "FEATURE", "VOL", None),
    # Return tables (before EMA/BAR to catch returns first)
    ("cmc_returns_bars_multi_tf", "RETURN", "BAR", None),
    ("cmc_returns_ema_multi_tf", "RETURN", "EMA", None),
    # EMA tables
    ("cmc_ema_multi_tf", "EMA", None, None),
    # Bar tables
    ("cmc_price_bars_multi_tf", "BAR", None, None),
    ("cmc_price_bars_1d", "BAR", None, None),
    # Raw price data
    ("cmc_price_histories7", "PRICE", None, "BASE"),
    # Reference / dimension tables
    ("dim_timeframe_period", "REF", "TIME", None),
    ("dim_timeframe", "REF", "TIME", None),
    ("dim_sessions", "REF", "TIME", None),
    ("dim_period", "REF", "TIME", None),
    ("dim_indicators", "REF", "FEATURE", None),
    ("dim_features", "REF", "FEATURE", None),
    ("dim_signals", "REF", "SIGNAL", None),
    ("dim_assets", "REF", "ASSET", None),
    ("ema_alpha_lookup", "REF", "EMA", None),
    ("ema_alpha_lut_old", "REF", "EMA", None),
    ("cusip_ticker", "REF", "EQUITY", None),
    ("cmc_da_ids", "REF", "DA", "ASSET"),
    ("cmc_da_info", "REF", "DA", "ASSET"),
    ("cmc_exchange_map", "REF", "DA", "VENUE"),
    ("cmc_exchange_info", "REF", "DA", "VENUE"),
    ("stock_exchange_mic", "REF", "EQUITY", "VENUE"),
    ("stock_exchange_equity_derivatives", "REF", "EQUITY", "VENUE"),
    ("stock_exchange_non_equity_derivatives", "REF", "DERIV", "VENUE"),
]


def classify_table(table_name: str) -> tuple[str | None, str | None, str | None]:
    """Return (major_type, minor_type, sub_type) for a table name."""
    # State tables: if name ends with _state, check state rules first
    is_state = table_name.endswith("_state")

    for pattern, major, minor, sub in RULES:
        if pattern in table_name:
            # For state tables, only match STATE rules
            if is_state and major != "STATE":
                continue
            # For non-state tables, skip STATE rules
            if not is_state and major == "STATE":
                continue
            # Detect sub_type overrides
            if sub is None:
                if "20260218" in table_name or "20251218" in table_name:
                    sub = "SNAPSHOT"
                elif (
                    "_u" in table_name
                    and not table_name.endswith("_us")
                    and "_us_" not in table_name
                ):
                    # _u suffix (unified) but not _us (US calendar)
                    if table_name.endswith("_u") or "_u_" in table_name:
                        sub = "UNIFIED"
                    else:
                        sub = "BASE"
                elif major not in (
                    "REF",
                    "STATS",
                    "STATE",
                    "STG",
                    "META",
                    "BACKTEST",
                    "SIGNAL",
                    "REGIME",
                    "QA",
                    "FEATURE",
                    "PRICE",
                ):
                    sub = "BASE"
            return major, minor, sub

    return None, None, None


def refresh(dry_run: bool = False) -> None:
    """Refresh table_summary from information_schema + row counts."""
    engine = create_engine(os.environ["TARGET_DB_URL"])

    with engine.connect() as conn:
        # Get all tables
        tables = conn.execute(
            text(
                """
            SELECT t.table_schema, t.table_name,
                   (SELECT count(*) FROM information_schema.columns c
                    WHERE c.table_schema = t.table_schema
                    AND c.table_name = t.table_name) as col_count
            FROM information_schema.tables t
            WHERE t.table_schema = 'public'
            AND t.table_type = 'BASE TABLE'
            ORDER BY t.table_name
        """
            )
        ).fetchall()

        rows_to_insert = []
        for schema, tname, col_count in tables:
            if tname == "table_summary":
                continue

            # Get row count
            try:
                row_count = conn.execute(
                    text(f'SELECT count(*) FROM public."{tname}"')
                ).scalar()
            except Exception:
                row_count = None

            cells = row_count * col_count if row_count is not None else None
            major, minor, sub = classify_table(tname)

            rows_to_insert.append(
                {
                    "schema_name": schema,
                    "table_name": tname,
                    "major_type": major,
                    "minor_type": minor,
                    "sub_type": sub,
                    "column_count": col_count,
                    "row_count": row_count,
                    "cells": cells,
                }
            )

        if dry_run:
            unclassified = [r for r in rows_to_insert if r["major_type"] is None]
            print(f"Total tables: {len(rows_to_insert)}")
            print(f"Classified: {len(rows_to_insert) - len(unclassified)}")
            if unclassified:
                print(f"Unclassified ({len(unclassified)}):")
                for r in unclassified:
                    print(f"  {r['table_name']}")

            # Print summary by major type
            from collections import Counter

            type_counts = Counter(r["major_type"] for r in rows_to_insert)
            print("\nBy Major Type:")
            for t, c in type_counts.most_common():
                total_rows = sum(
                    r["row_count"] or 0 for r in rows_to_insert if r["major_type"] == t
                )
                print(f"  {t or 'NULL':10s}  {c:3d} tables  {total_rows:>15,} rows")
            return

    # Write
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE public.table_summary"))
        for r in rows_to_insert:
            conn.execute(
                text(
                    """
                    INSERT INTO public.table_summary
                    (schema_name, table_name, major_type, minor_type, sub_type,
                     column_count, row_count, cells)
                    VALUES (:schema_name, :table_name, :major_type, :minor_type,
                            :sub_type, :column_count, :row_count, :cells)
                """
                ),
                r,
            )
        logger.info("Inserted %d rows into table_summary", len(rows_to_insert))
        print(f"Refreshed table_summary: {len(rows_to_insert)} tables")


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh table_summary")
    parser.add_argument("--dry-run", action="store_true", help="Print without writing")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    refresh(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
