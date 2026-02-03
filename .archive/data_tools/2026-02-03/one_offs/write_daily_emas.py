# -*- coding: utf-8 -*-
"""
Created on Thu Nov 13 16:20:00 2025

@author: asafi
"""
from ta_lab2.features.ema import write_daily_ema_to_db

ids = [1, 1027, 5426, 52, 32196, 1975, 1839]

rows = write_daily_ema_to_db(
    ids=ids,
    start="2010-01-01",
)

print("Daily EMA rows written:", rows)
