from __future__ import annotations

"""
Refresh cmc_ema_multi_tf using:

- dim_timeframe (alignment_type='tf_day', canonical_only=True) for which tfs to compute
- persisted tf_day bars (default public.cmc_price_bars_multi_tf) for canonical closes
- daily closes (cmc_price_histories7) for preview EMA between closes

MEMORY-SAFE VERSION:
- Executes per (id, tf) to avoid large in-memory DataFrames
- Safe for large TF sets, large period LUTs, long histories

UPDATED (2025-12-20):
- Chunked execution by (id, tf)
"""

import os
import argparse
from typing import List

from sqlalchemy import text

from ta_lab2.io import _get_marketdata_engine as _get_engine
from ta_lab2.features.m_tf.ema_multi_timeframe import write_multi_timeframe_ema_to_db


DEFAULT_PERIODS = "6,9,10,12,14,17,20,21,26,30,50,52,77,100,200,252,365"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Refresh cmc_ema_multi_tf from tf_day bars (memory-safe).")
    p.add_argument("--db-url", default=None, help="SQLAlchemy DB URL. Defaults to TARGET_DB_URL env.")
    p.add_argument("--ids", default="all", help="Comma list (e.g., 1,52) or 'all'. Default: all")
    p.add_argument("--start", default="2010-01-01", help="Output start (inclusive). Default: 2010-01-01")
    p.add_argument("--end", default=None, help="Output end (inclusive). Default: None")
    p.add_argument(
        "--periods",
        default=DEFAULT_PERIODS,
        help="EMA periods CSV, or 'lut' to load from public.ema_alpha_lookup",
    )
    p.add_argument("--tfs", default=None, help="Optional TF subset CSV (e.g., 2D,3D,5D). Default: all tf_day canonical")
    p.add_argument("--out-table", default="cmc_ema_multi_tf", help="Output table. Default: cmc_ema_multi_tf")
    p.add_argument("--schema", default="public", help="Schema for output table. Default: public")
    p.add_argument("--bars-schema", default="public", help="Schema for bars table. Default: public")
    p.add_argument(
        "--bars-table",
        default="cmc_price_bars_multi_tf",
        help="Bars table for tf_day closes. Default: cmc_price_bars_multi_tf",
    )
    p.add_argument("--no-update", action="store_true", help="If set, ON CONFLICT does nothing.")
    return p


def _resolve_db_url(args_db_url: str | None) -> str:
    resolved = args_db_url or os.environ.get("TARGET_DB_URL") or os.environ.get("MARKETDATA_DB_URL")
    if not resolved:
        raise ValueError("No db url provided and neither TARGET_DB_URL nor MARKETDATA_DB_URL is set.")
    return resolved


def _resolve_ids(engine, ids_arg: str) -> List[int]:
    if str(ids_arg).strip().lower() == "all":
        with engine.begin() as conn:
            rows = conn.execute(
                text("SELECT DISTINCT id FROM public.cmc_price_histories7 ORDER BY 1;")
            ).fetchall()
        return [int(r[0]) for r in rows]
    return [int(x.strip()) for x in str(ids_arg).split(",") if x.strip()]


def _load_periods(engine, periods_arg: str) -> List[int]:
    if periods_arg.strip().lower() == "lut":
        with engine.begin() as conn:
            rows = conn.execute(
                text("SELECT DISTINCT period FROM public.ema_alpha_lookup ORDER BY 1;")
            ).fetchall()
        if not rows:
            raise RuntimeError("No periods found in public.ema_alpha_lookup.")
        return [int(r[0]) for r in rows]
    return [int(x.strip()) for x in periods_arg.split(",") if x.strip()]


def _load_tf_day_canonical(engine) -> List[str]:
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT tf
                FROM public.dim_timeframe
                WHERE alignment_type = 'tf_day'
                  AND is_canonical = TRUE
                ORDER BY display_order, sort_order, tf;
                """
            )
        ).fetchall()
    return [r[0] for r in rows]


def main() -> None:
    args = build_parser().parse_args()

    engine = _get_engine(args.db_url)
    resolved_db_url = _resolve_db_url(args.db_url)

    ids = _resolve_ids(engine, args.ids)
    periods = _load_periods(engine, str(args.periods))

    if args.tfs is None:
        tf_list = _load_tf_day_canonical(engine)
    else:
        tf_list = [x.strip() for x in str(args.tfs).split(",") if x.strip()]

    print(
        "[ema_multi_tf_from_bars] Runner config (CHUNKED): "
        f"ids={ids if args.ids != 'all' else 'ALL'}, "
        f"periods={periods}, "
        f"tfs={tf_list}, "
        f"bars={args.bars_schema}.{args.bars_table}, "
        f"out={args.schema}.{args.out_table}"
    )

    total_rows = 0

    for id_ in ids:
        for tf in tf_list:
            print(f"[ema_multi_tf_from_bars] Processing id={id_}, tf={tf}")

            n = write_multi_timeframe_ema_to_db(
                ids=[id_],                     # 👈 single id
                start=args.start,
                end=args.end,
                ema_periods=periods,
                tf_subset=[tf],                # 👈 single tf
                db_url=resolved_db_url,
                schema=args.schema,
                out_table=args.out_table,
                update_existing=(not args.no_update),
                bars_schema=args.bars_schema,
                bars_table_tf_day=args.bars_table,
            )

            total_rows += int(n or 0)

    print(f"[ema_multi_tf_from_bars] Total upserted rows: {total_rows}")


if __name__ == "__main__":
    main()
