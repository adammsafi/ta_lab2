from __future__ import annotations

import sys
from typing import Sequence

from ta_lab2.scripts.emas.stats.multi_tf_v2.refresh_ema_multi_tf_v2_stats import (
    main as _main,
)


def main(argv: Sequence[str] | None = None) -> None:
    """
    Thin wrapper so you can run the v2 stats refresh easily from Spyder,
    VS Code, or the command line.

    Example CLI usage (if you wire it up to `python -m`):
        python run_refresh_ema_multi_tf_v2_stats.py --db-url postgresql+psycopg2://...

    It simply forwards all args to refresh_ema_multi_tf_v2_stats.main().
    """
    if argv is None:
        argv = sys.argv[1:]
    _main(argv)


if __name__ == "__main__":
    main()
"""
runfile(
    'C:/Users/asafi/Downloads/ta_lab2/src/ta_lab2/scripts/emas/stats/multi_tf_v2/run_refresh_ema_multi_tf_v2_stats.py',
    wdir='C:/Users/asafi/Downloads/ta_lab2',
    args='--ids all --db-url postgresql+psycopg2://postgres:***@localhost:5432/marketdata'
)

"""