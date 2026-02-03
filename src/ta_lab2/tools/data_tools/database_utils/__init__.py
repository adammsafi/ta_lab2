"""
Database utilities migrated from Data_Tools.

EMA-related utilities for:
- Writing daily EMAs to cmc_ema_daily
- Writing multi-timeframe EMAs to cmc_ema_multi_tf
- Writing calendar-adjusted EMAs to cmc_ema_multi_tf_cal
- Upserting new EMA records with incremental refresh

Usage:
    These utilities complement ta_lab2.scripts.emas/ refresh scripts
    by providing convenient runner functions with CLI support.

    # Python API
    from ta_lab2.tools.data_tools.database_utils import (
        write_daily_emas,
        write_multi_tf_emas,
        write_ema_multi_tf_cal,
        upsert_new_emas,
    )

    rows = write_daily_emas(ids=[1, 1027], start="2010-01-01")

    # CLI
    python -m ta_lab2.tools.data_tools.database_utils.ema_runners daily --ids 1 1027

Note:
    All functions wrap existing ta_lab2 infrastructure. For direct access
    to underlying functionality, use ta_lab2.features.ema and
    ta_lab2.features.m_tf modules.
"""

from ta_lab2.tools.data_tools.database_utils.ema_runners import (
    write_daily_emas,
    write_multi_tf_emas,
    write_ema_multi_tf_cal,
    upsert_new_emas,
)

__all__ = [
    "write_daily_emas",
    "write_multi_tf_emas",
    "write_ema_multi_tf_cal",
    "upsert_new_emas",
]
