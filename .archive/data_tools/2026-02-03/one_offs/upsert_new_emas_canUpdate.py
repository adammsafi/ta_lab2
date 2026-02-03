# c:\users\asafi\downloads\Data_Tools\upsert_new_emas_canUpdate.py
# -*- coding: utf-8 -*-
"""
Helper script to upsert new EMAs after fresh price data is loaded.

Behavior:
- Imports and runs example_incremental_all_ids_all_targets(), which:
    * Calls refresh_cmc_emas
    * Updates:
        - cmc_ema_daily
        - cmc_ema_multi_tf
        - cmc_ema_multi_tf_cal (via refresh_cmc_emas)
        - all_emas
        - cmc_price_with_emas
        - cmc_price_with_emas_d1d2

Usage examples (from CLI, if you ever want them directly):

  # Incremental insert-only update for a few ids:
  #   python -m ta_lab2.scripts.refresh_cmc_emas ^
  #       --ids 1 1027 1839 ^
  #       --update-daily ^
  #       --update-multi-tf

  # Recompute + update EMAs from a specific date:
  #   python -m ta_lab2.scripts.refresh_cmc_emas ^
  #       --ids 1 1027 ^
  #       --start 2025-10-26

Notes:
- In Spyder you can just run this file with:
    %runfile upsert_new_emas_canUpdate.py
"""

from ta_lab2.scripts.run_ema_refresh_examples import (
    example_incremental_all_ids_all_targets,
)


if __name__ == "__main__":
    # This is the "insert anything new for ALL ids into ALL targets" call.
    example_incremental_all_ids_all_targets()
