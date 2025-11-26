from __future__ import annotations

import argparse
from typing import Sequence

from ta_lab2.scripts.emas.refresh_cmc_emas import refresh, _load_all_ids, _parse_ids


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Refresh ONLY cmc_ema_multi_tf_cal (no daily, no non-cal, no views)."
    )
    parser.add_argument(
        "--ids",
        nargs="+",
        required=True,
        help="Asset ids to update (space- or comma-separated), or 'all'.",
    )
    parser.add_argument("--start", default=None)
    parser.add_argument("--end", default=None)
    parser.add_argument("--db-url", default=None)

    args = parser.parse_args(list(argv) if argv is not None else None)

    if len(args.ids) == 1 and args.ids[0].strip().lower() == "all":
        ids = _load_all_ids(args.db_url)
    else:
        ids = _parse_ids(args.ids)

    refresh(
        ids=ids,
        start=args.start,
        end=args.end,
        db_url=args.db_url,
        update_daily=False,
        update_multi_tf=False,
        update_cal_multi_tf=True,
        refresh_all_emas_view=False,
        refresh_price_emas_view=False,
        refresh_price_emas_d1d2_view=False,
    )


if __name__ == "__main__":
    main()
    
"""
Option 1: all assets

runfile(
    'C:/Users/asafi/Downloads/ta_lab2/src/ta_lab2/scripts/emas/refresh_cmc_ema_multi_tf_cal_only.py',
    wdir='C:/Users/asafi/Downloads/ta_lab2',
    args='--ids all'
)

Option 2: specific assets only

runfile(
    'C:/Users/asafi/Downloads/ta_lab2/src/ta_lab2/scripts/emas/refresh_cmc_ema_multi_tf_cal_only.py',
    wdir='C:/Users/asafi/Downloads/ta_lab2',
    args='--ids 1 52 1975 5426 32196'
)

You can also add --start / --end if you want to force a recompute from a specific date, for example:

args='--ids all --start 2020-01-01'
"""






















