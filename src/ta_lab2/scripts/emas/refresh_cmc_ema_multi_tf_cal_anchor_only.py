from __future__ import annotations

import argparse
from typing import Sequence

from ta_lab2.scripts.emas.refresh_cmc_emas import _load_all_ids, _parse_ids
from ta_lab2.features.m_tf.ema_multi_tf_cal_anchor import (
    write_multi_timeframe_ema_cal_anchor_to_db,
)


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Refresh ONLY cmc_ema_multi_tf_cal_anchor "
            "(year-anchored calendar multi-TF EMAs with ema / ema_bar and "
            "all derivative fields; no daily, no non-cal, no views)."
        )
    )
    parser.add_argument(
        "--ids",
        nargs="+",
        required=True,
        help="Asset ids to update (space- or comma-separated), or 'all'.",
    )
    parser.add_argument("--start", default="2010-01-01")
    parser.add_argument("--end", default=None)
    parser.add_argument("--db-url", default=None)
    parser.add_argument(
        "--no-update-existing",
        action="store_true",
        help="If set, ON CONFLICT DO NOTHING (do not update existing rows).",
    )

    args = parser.parse_args(list(argv) if argv is not None else None)

    if len(args.ids) == 1 and args.ids[0].strip().lower() == "all":
        ids = _load_all_ids(args.db_url)
    else:
        ids = _parse_ids(args.ids)

    update_existing = not args.no_update_existing

    rowcount = write_multi_timeframe_ema_cal_anchor_to_db(
        ids=ids,
        start=args.start,
        end=args.end,
        db_url=args.db_url,
        update_existing=update_existing,
    )

    print(
        f"Upserted {rowcount} rows into public.cmc_ema_multi_tf_cal_anchor "
        f"for ids={ids}, start={args.start}, end={args.end}."
    )


if __name__ == "__main__":
    main()

"""
Example usage:

Option 1: all assets

runfile(
    'C:/Users/asafi/Downloads/ta_lab2/src/ta_lab2/scripts/emas/refresh_cmc_ema_multi_tf_cal_anchor_only.py',
    wdir='C:/Users/asafi/Downloads/ta_lab2',
    args='--ids all'
)

Option 2: specific assets only

runfile(
    'C:/Users/asafi/Downloads/ta_lab2/src/ta_lab2/scripts/emas/refresh_cmc_ema_multi_tf_cal_anchor_only.py',
    wdir='C:/Users/asafi/Downloads/ta_lab2',
    args='--ids 1 52 1975 5426 32196'
)

You can also add --start / --end if you want to force a recompute from a
specific date, for example:

args='--ids all --start 2011-01-01 --end 2012-12-31'

If you want insert-only behavior (no update of existing rows):

args='--ids all --start 2011-01-01 --no-update-existing'
"""
