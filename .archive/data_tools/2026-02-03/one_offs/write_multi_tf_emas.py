# -*- coding: utf-8 -*-
"""
Created on Sun Nov 16 08:53:23 2025

@author: asafi
"""

from ta_lab2.features.m_tf.ema_multi_timeframe import write_multi_timeframe_ema_to_db

ids = [1, 1027, 5426, 52, 32196, 1975, 1839]

total = write_multi_timeframe_ema_to_db(
    ids=ids,
    start="2010-01-01",
)

print("Rows written:", total)
