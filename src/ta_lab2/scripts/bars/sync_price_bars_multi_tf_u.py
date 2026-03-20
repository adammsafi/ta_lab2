from __future__ import annotations

"""
sync_price_bars_multi_tf_u.py

Incrementally sync price bars from 5 source tables into:
  public.price_bars_multi_tf_u

alignment_source derived from table name:
  price_bars_multi_tf          -> multi_tf
  price_bars_multi_tf_cal_us   -> multi_tf_cal_us
  price_bars_multi_tf_cal_iso  -> multi_tf_cal_iso
  price_bars_multi_tf_cal_anchor_us  -> multi_tf_cal_anchor_us
  price_bars_multi_tf_cal_anchor_iso -> multi_tf_cal_anchor_iso

Run:
  python -m ta_lab2.scripts.bars.sync_price_bars_multi_tf_u
  python -m ta_lab2.scripts.bars.sync_price_bars_multi_tf_u --dry-run
  python -m ta_lab2.scripts.bars.sync_price_bars_multi_tf_u --only multi_tf_cal_us
"""

import argparse
import os

from sqlalchemy import create_engine

from ta_lab2.scripts.sync_utils import add_sync_cli_args, sync_sources_to_unified

U_TABLE = "public.price_bars_multi_tf_u"
PK_COLS = ["id", "tf", "bar_seq", "venue_id", "timestamp", "alignment_source"]
SOURCE_PREFIX = "price_bars_"

SOURCES = [
    "public.price_bars_multi_tf",
    "public.price_bars_multi_tf_cal_us",
    "public.price_bars_multi_tf_cal_iso",
    "public.price_bars_multi_tf_cal_anchor_us",
    "public.price_bars_multi_tf_cal_anchor_iso",
]


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Sync price bar tables into public.price_bars_multi_tf_u."
    )
    add_sync_cli_args(ap)
    args = ap.parse_args()

    db_url = os.environ.get("TARGET_DB_URL")
    if not db_url:
        raise RuntimeError("TARGET_DB_URL env var is required.")
    engine = create_engine(db_url, future=True)

    only = (
        set(s.strip() for s in args.only.split(",") if s.strip()) if args.only else None
    )

    sync_sources_to_unified(
        engine=engine,
        u_table=U_TABLE,
        sources=SOURCES,
        pk_cols=PK_COLS,
        source_prefix=SOURCE_PREFIX,
        log_prefix="price_bars_u",
        dry_run=args.dry_run,
        only=only,
    )


if __name__ == "__main__":
    main()
