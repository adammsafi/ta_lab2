# -*- coding: utf-8 -*-
"""
Runner for calendar-aligned multi-timeframe EMAs.

Writes EMAs into public.cmc_ema_multi_tf_cal using ema_multi_tf_cal.py.
"""

from ta_lab2.features.m_tf.ema_multi_tf_cal import write_multi_timeframe_ema_cal_to_db

ids = [1, 1027, 5426, 52, 32196, 1975, 1839]

total = write_multi_timeframe_ema_cal_to_db(
    ids=ids,
    start="2010-01-01",
)

print("Rows written to cmc_ema_multi_tf_cal:", total)
