# -*- coding: utf-8 -*-
"""
Refresh ONLY cmc_ema_daily for a set of CMC asset ids.

This is a thin wrapper around ta_lab2.scripts.emas.refresh_cmc_emas.refresh,
configured to:
  - update_daily = True
  - update_multi_tf = False
  - update_cal_multi_tf = False
  - no view refresh

Usage examples (from Spyder or CLI):

  # All default tracked ids ("all")
  python refresh_cmc_ema_daily_only.py --ids all

  # Specific ids and optional start
  python refresh_cmc_ema_daily_only.py --ids 1 52 1027 --start 2015-01-01

"""

import argparse
from ta_lab2.scripts.emas.refresh_cmc_emas import refresh, _parse_ids


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(
        description="Refresh ONLY cmc_ema_daily for selected CMC asset ids."
    )
    parser.add_argument(
        "--ids",
        nargs="+",
        required=True,
        help='Asset ids or "all" to use the default id list configured in refresh_cmc_emas.',
    )
    parser.add_argument(
        "--start",
        type=str,
        default=None,
        help="Optional start date (YYYY-MM-DD). If omitted, runs in incremental/dirty-window mode.",
    )
    parser.add_argument(
        "--end",
        type=str,
        default=None,
        help="Optional end date (YYYY-MM-DD). If omitted, uses latest available price data.",
    )
    parser.add_argument(
        "--db-url",
        type=str,
        default=None,
        help="Optional explicit DB URL. If omitted, TARGET_DB_URL from ta_lab2.config is used.",
    )

    args = parser.parse_args(argv)

    ids = _parse_ids(args.ids)

    print(
        f"[daily-only] Refreshing cmc_ema_daily for ids={ids}, "
        f"start={args.start}, end={args.end}"
    )

    refresh(
        ids=ids,
        start=args.start,
        end=args.end,
        db_url=args.db_url,
        update_daily=True,
        update_multi_tf=False,
        update_cal_multi_tf=False,
        refresh_all_emas_view=False,
        refresh_price_emas_view=False,
        refresh_price_emas_d1d2_view=False,
    )

    print("[daily-only] Done.")


if __name__ == "__main__":
    main()


"""
runfile(
    'C:/Users/asafi/Downloads/ta_lab2/src/ta_lab2/scripts/emas/refresh_cmc_ema_daily_only.py',
    wdir='C:/Users/asafi/Downloads/ta_lab2',
    args='--ids all'
)
"""
