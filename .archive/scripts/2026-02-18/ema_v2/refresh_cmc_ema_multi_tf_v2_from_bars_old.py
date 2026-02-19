from __future__ import annotations

"""
Incremental refresh runner for public.cmc_ema_multi_tf_v2.

Key guarantee (with the UPDATED ema_multi_tf_v2 feature module):
- Incremental watermark is per (id, tf, period), not per id.
- Therefore this runner WILL pick up and backfill:
    * new periods (e.g., adding 10)
    * new TFs from dim_timeframe (e.g., adding 28D, 1D, etc.)
  even when there are no new daily timestamps.

Mirrors the style of other ta_lab2 refresh scripts:
- resolves DB URL from --db-url or TARGET_DB_URL
- supports --ids all / comma list
- supports --periods override
- delegates all EMA math to ta_lab2.features.m_tf.ema_multi_tf_v2

Example (Spyder):

    runfile(
      r"C:\\Users\\asafi\\Downloads\\ta_lab2\\src\\ta_lab2\\scripts\\emas\\refresh_cmc_ema_multi_tf_v2_from_bars.py",
      wdir=r"C:\\Users\\asafi\\Downloads\\ta_lab2",
      args="--ids all"
    )
"""

import argparse
import os
from typing import List, Optional, Sequence

from sqlalchemy import create_engine

from ta_lab2.features.m_tf.ema_multi_tf_v2 import (
    DEFAULT_PERIODS,
    refresh_cmc_ema_multi_tf_v2_incremental,
)


def _resolve_db_url(cli_db_url: Optional[str]) -> str:
    """Priority: --db-url, then TARGET_DB_URL env."""
    if cli_db_url and cli_db_url.strip():
        return cli_db_url.strip()

    env_db_url = os.getenv("TARGET_DB_URL")
    if env_db_url and env_db_url.strip():
        print("[multi_tf_v2] Using DB URL from TARGET_DB_URL env.")
        return env_db_url.strip()

    raise ValueError("No DB URL provided. Pass --db-url or set TARGET_DB_URL in your environment.")


def _parse_ids(ids_arg: str) -> Optional[Sequence[int]]:
    if ids_arg.strip().lower() == "all":
        return None
    out: List[int] = []
    for part in ids_arg.split(","):
        part = part.strip()
        if part:
            out.append(int(part))
    return out


def _parse_int_list(arg: Optional[str]) -> Optional[Sequence[int]]:
    if arg is None:
        return None
    arg = arg.strip()
    if not arg:
        return None
    out: List[int] = []
    for part in arg.split(","):
        part = part.strip()
        if part:
            out.append(int(part))
    return out


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Incrementally refresh cmc_ema_multi_tf_v2 (TFs from dim_timeframe).")
    p.add_argument("--db-url", default=None, help="SQLAlchemy DB URL (or TARGET_DB_URL env).")
    p.add_argument("--ids", default="all", help="Comma list of ids (e.g., 1,52) or 'all' (default).")
    p.add_argument(
        "--periods",
        default=None,
        help=f"Comma list of EMA periods (default: {','.join(map(str, DEFAULT_PERIODS))}).",
    )
    p.add_argument(
        "--alignment-type",
        default="tf_day",
        help="dim_timeframe.alignment_type used to select TFs (default: tf_day).",
    )
    p.add_argument(
        "--include-noncanonical",
        action="store_true",
        help="If set, include non-canonical TFs from dim_timeframe (canonical_only=False).",
    )
    p.add_argument("--price-schema", default="public")
    p.add_argument("--price-table", default="cmc_price_histories7")
    p.add_argument("--out-schema", default="public")
    p.add_argument("--out-table", default="cmc_ema_multi_tf_v2")
    return p


def main() -> None:
    args = build_parser().parse_args()

    db_url = _resolve_db_url(args.db_url)
    ids = _parse_ids(args.ids)

    periods = _parse_int_list(args.periods)
    if periods is None:
        periods = DEFAULT_PERIODS
    periods = [int(p) for p in periods if int(p) > 0]

    canonical_only = not args.include_noncanonical

    print(
        "[multi_tf_v2] Runner config:"
        f" ids={'ALL' if ids is None else ids},"
        f" periods={periods},"
        f" alignment_type={args.alignment_type!r},"
        f" canonical_only={canonical_only},"
        f" price={args.price_schema}.{args.price_table},"
        f" out={args.out_schema}.{args.out_table}"
    )
    print(
        "[multi_tf_v2] Incremental semantics: watermark is per (id, tf, period). "
        "New TFs or new periods will be backfilled even with no new daily timestamps."
    )

    engine = create_engine(db_url)

    try:
        refresh_cmc_ema_multi_tf_v2_incremental(
            engine=engine,
            db_url=db_url,
            periods=periods,
            ids=ids,
            alignment_type=args.alignment_type,
            canonical_only=canonical_only,
            price_schema=args.price_schema,
            price_table=args.price_table,
            out_schema=args.out_schema,
            out_table=args.out_table,
        )
    finally:
        # Ensure pooled connections are released in long Spyder sessions
        engine.dispose()


if __name__ == "__main__":
    main()
