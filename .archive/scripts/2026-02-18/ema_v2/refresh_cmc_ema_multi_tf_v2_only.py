from __future__ import annotations

import argparse
from typing import Sequence

from ta_lab2.scripts.emas.refresh_cmc_emas import (
    refresh,
    _load_all_ids,
    _parse_ids,
)


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Refresh ONLY cmc_ema_multi_tf_v2 "
            "(no daily, no v1 multi_tf, no cal, no views)."
        )
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
        update_cal_multi_tf=False,
        update_multi_tf_v2=True,
        refresh_all_emas_view=False,
        refresh_price_emas_view=False,
        refresh_price_emas_d1d2_view=False,
    )


if __name__ == "__main__":
    main()

"""
Example usage (Spyder):

runfile(
    'C:/Users/asafi/Downloads/ta_lab2/src/ta_lab2/scripts/emas/refresh_cmc_ema_multi_tf_v2_only.py',
    wdir='C:/Users/asafi/Downloads/ta_lab2',
    args='--ids all'
)
"""
