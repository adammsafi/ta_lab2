from __future__ import annotations

import argparse
from typing import Sequence

from ta_lab2.scripts.emas.refresh_cmc_emas import (
    refresh,
    _load_all_ids,
    _parse_ids,
    _get_engine,
)


def main(argv: Sequence[str] | None = None) -> None:
    """
    Refresh ONLY cmc_ema_multi_tf_cal (calendar-aligned multi-TF EMAs).

    This runner:
      - Updates cmc_ema_multi_tf_cal for the requested ids and optional
        [start, end] window.
      - Does NOT update:
          * cmc_ema_daily
          * cmc_ema_multi_tf (non-calendar)
          * cmc_ema_multi_tf_v2
          * any views

    The underlying refresh() call will populate, for each (id, tf, period, ts):

      * ema, d1, d2, d1_roll, d2_roll
          - smooth daily EMA spine (daily-equivalent alpha),
            no resets at bar closes

      * ema_bar, d1_bar, d2_bar, roll_bar, d1_roll_bar, d2_roll_bar
          - bar-space EMA on TF closes, reset on bar closes and
            propagated between them with daily-equivalent alpha
    """

    parser = argparse.ArgumentParser(
        description="Refresh ONLY cmc_ema_multi_tf_cal."
    )

    parser.add_argument(
        "--ids",
        nargs="+",
        required=True,
        help="Asset ids to update (space- or comma-separated), or 'all'.",
    )
    parser.add_argument("--start", default=None)
    parser.add_argument("--end", default=None)

    # IMPORTANT:
    # default=None allows refresh() to fall back to TARGET_DB_URL or .env config.
    parser.add_argument(
        "--db-url",
        default=None,
        help="Optional DB override. If omitted, refresh() uses TARGET_DB_URL.",
    )

    args = parser.parse_args(list(argv) if argv is not None else None)

    # Expand ids
    if len(args.ids) == 1 and args.ids[0].strip().lower() == "all":
        ids = _load_all_ids(args.db_url)
    else:
        ids = _parse_ids(args.ids)

    # High-level info about what we're doing
    effective_label = args.db_url or "DEFAULT (TARGET_DB_URL / env)"
    print(
        "[refresh_cmc_ema_multi_tf_cal_only] Effective DB URL arg: "
        f"{effective_label}"
    )

    # Debug: resolve and log the actual SQLAlchemy URL we'll use
    # This makes it obvious if we're accidentally hitting postgres@localhost, etc.
    try:
        engine = _get_engine(args.db_url)
        print(
            "[refresh_cmc_ema_multi_tf_cal_only] Resolved DB URL: "
            f"{engine.url}"
        )
    finally:
        # Dispose immediately; refresh() will create its own engine again.
        engine.dispose()

    # Call main refresh engine
    refresh(
        ids=ids,
        start=args.start,
        end=args.end,
        db_url=args.db_url,  # None triggers fallback
        update_daily=False,
        update_multi_tf=False,
        update_cal_multi_tf=True,
        update_multi_tf_v2=False,
        refresh_all_emas_view=False,
        refresh_price_emas_view=False,
        refresh_price_emas_d1d2_view=False,
    )


if __name__ == "__main__":
    main()


"""
Usage examples:

Option 1: All assets
runfile(
    'C:/Users/asafi/Downloads/ta_lab2/src/ta_lab2/scripts/emas/refresh_cmc_ema_multi_tf_cal_only.py',
    wdir='C:/Users/asafi/Downloads/ta_lab2',
    args='--ids all'
)

Option 2: Specific assets
runfile(
    'C:/Users/asafi/Downloads/ta_lab2/src/ta_lab2/scripts/emas/refresh_cmc_ema_multi_tf_cal_only.py',
    wdir='C:/Users/asafi/Downloads/ta_lab2',
    args='--ids 1 52 1975 5426 32196'
)

Option 3: Recompute from a date
runfile(
    'C:/Users/asafi/Downloads/ta_lab2/src/ta_lab2/scripts/emas/refresh_cmc_ema_multi_tf_cal_only.py',
    wdir='C:/Users/asafi/Downloads/ta_lab2',
    args='--ids all --start 2020-01-01'
)
"""
