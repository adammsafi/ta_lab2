from __future__ import annotations
"""
Thin wrapper to run ema_multi_tf_cal_anchor stats refresh via `runfile` or CLI.

Examples
--------
In Spyder:

    runfile(
        'C:/Users/asafi/Downloads/ta_lab2/src/ta_lab2/scripts/emas/stats/multi_tf_cal_anchor/run_refresh_ema_multi_tf_cal_anchor_stats.py',
        wdir='C:/Users/asafi/Downloads/ta_lab2',
        args='--db-url postgresql+psycopg2://postgres:3400@localhost:5432/marketdata'
    )

From the shell:

    python -m ta_lab2.scripts.emas.stats.multi_tf_cal_anchor.run_refresh_ema_multi_tf_cal_anchor_stats \\
        --db-url postgresql+psycopg2://postgres:3400@localhost:5432/marketdata
"""

import sys

from ta_lab2.scripts.emas.stats.multi_tf_cal_anchor.refresh_ema_multi_tf_cal_anchor_stats import (  # noqa: E501
    main as _main,
)


def main(argv: list[str] | None = None) -> None:
    """Entry point that just forwards args to the real stats script."""
    if argv is None:
        argv = sys.argv[1:]
    _main(argv)


if __name__ == "__main__":
    main()

"""
runfile(
    'C:/Users/asafi/Downloads/ta_lab2/src/ta_lab2/scripts/emas/stats/multi_tf_cal_anchor/run_refresh_ema_multi_tf_cal_anchor_stats.py',
    wdir='C:/Users/asafi/Downloads/ta_lab2',
    args='--ids all'
)
"""