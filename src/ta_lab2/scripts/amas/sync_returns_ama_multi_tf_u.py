from __future__ import annotations

"""
sync_returns_ama_multi_tf_u.py

Incrementally sync AMA returns records from 5 source AMA returns tables into:
  public.returns_ama_multi_tf_u

Rules:
- alignment_source = suffix after 'cmc_returns_ama_' in the source table name.
  e.g. public.returns_ama_multi_tf -> multi_tf
       public.returns_ama_multi_tf_cal_us -> multi_tf_cal_us

- Watermark per source:
  MAX(ingested_at) from _u for that alignment_source.

- Insert uses ON CONFLICT DO NOTHING on PK:
  (id, ts, tf, indicator, params_hash, alignment_source)

Run:
  python -m ta_lab2.scripts.amas.sync_returns_ama_multi_tf_u
  python -m ta_lab2.scripts.amas.sync_returns_ama_multi_tf_u --dry-run
  python -m ta_lab2.scripts.amas.sync_returns_ama_multi_tf_u --only multi_tf,multi_tf_cal_us
"""

import argparse

from sqlalchemy import create_engine

from ta_lab2.scripts.refresh_utils import resolve_db_url
from ta_lab2.scripts.sync_utils import add_sync_cli_args, sync_sources_to_unified

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

AMA_RETURNS_U_TABLE = "public.returns_ama_multi_tf_u"

AMA_RETURNS_SOURCES = [
    "public.returns_ama_multi_tf",
    "public.returns_ama_multi_tf_cal_us",
    "public.returns_ama_multi_tf_cal_iso",
    "public.returns_ama_multi_tf_cal_anchor_us",
    "public.returns_ama_multi_tf_cal_anchor_iso",
]

# PK of the _u table — alignment_source is part of PK
AMA_RETURNS_PK_COLS = [
    "id",
    "venue_id",
    "ts",
    "tf",
    "indicator",
    "params_hash",
    "alignment_source",
]

# Prefix stripped from source table name to derive alignment_source label
# returns_ama_multi_tf -> multi_tf
# returns_ama_multi_tf_cal_us -> multi_tf_cal_us
AMA_RETURNS_SOURCE_PREFIX = "returns_ama_"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser(
        description=(
            "Sync AMA returns source tables into "
            "public.returns_ama_multi_tf_u (incremental)."
        )
    )
    ap.add_argument(
        "--db-url",
        default="",
        help="Postgres DB URL. Falls back to db_config.env / TARGET_DB_URL.",
    )
    add_sync_cli_args(ap)
    args = ap.parse_args()

    db_url = resolve_db_url(args.db_url or None)
    engine = create_engine(db_url, future=True)

    only_set = (
        set(s.strip() for s in args.only.split(",") if s.strip()) if args.only else None
    )

    sync_sources_to_unified(
        engine=engine,
        u_table=AMA_RETURNS_U_TABLE,
        sources=AMA_RETURNS_SOURCES,
        pk_cols=AMA_RETURNS_PK_COLS,
        source_prefix=AMA_RETURNS_SOURCE_PREFIX,
        log_prefix="ama_returns_sync",
        dry_run=args.dry_run,
        only=only_set,
        batch_col="id",
    )


if __name__ == "__main__":
    main()
