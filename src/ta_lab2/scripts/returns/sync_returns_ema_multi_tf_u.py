from __future__ import annotations

"""
sync_returns_ema_multi_tf_u.py

Incrementally sync EMA returns from 5 source tables into:
  public.returns_ema_multi_tf_u

Replaces the old refresh_returns_ema_multi_tf_u.py which recomputed
returns from ema_multi_tf_u. Since returns are already computed in
the 5 base EMA returns tables, we just union/sync them.

alignment_source derived from table name:
  returns_ema_multi_tf          -> multi_tf
  returns_ema_multi_tf_cal_us   -> multi_tf_cal_us
  ...etc

Run:
  python -m ta_lab2.scripts.returns.sync_returns_ema_multi_tf_u
  python -m ta_lab2.scripts.returns.sync_returns_ema_multi_tf_u --dry-run
"""

import argparse
import os

from sqlalchemy import create_engine

from ta_lab2.scripts.sync_utils import add_sync_cli_args, sync_sources_to_unified

U_TABLE = "public.returns_ema_multi_tf_u"
PK_COLS = ["id", "venue_id", "ts", "tf", "period", "alignment_source"]
SOURCE_PREFIX = "returns_ema_"

SOURCES = [
    "public.returns_ema_multi_tf",
    "public.returns_ema_multi_tf_cal_us",
    "public.returns_ema_multi_tf_cal_iso",
    "public.returns_ema_multi_tf_cal_anchor_us",
    "public.returns_ema_multi_tf_cal_anchor_iso",
]


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Sync EMA returns tables into public.returns_ema_multi_tf_u."
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
        log_prefix="ret_ema_u",
        dry_run=args.dry_run,
        only=only,
    )


if __name__ == "__main__":
    main()
