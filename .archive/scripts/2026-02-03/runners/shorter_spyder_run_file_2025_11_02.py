# -*- coding: utf-8 -*-
"""
Created on Sun Nov  2 21:46:52 2025

@author: asafi
"""

from pathlib import Path
import pandas as pd
from ta_lab2.features.resample import resample_many, seasonal_summary

# 1) load your daily input (CSV or artifacts/btc.parquet)
src_csv = Path("data/btc.csv")
if src_csv.exists():
    DF_DAILY = pd.read_csv(src_csv)
else:
    DF_DAILY = pd.read_parquet("artifacts/btc.parquet")

# 2) define the exact bins you want (calendar-day based)
FREQS = [
    "2D",
    "3D",
    "4D",
    "5D",
    "10D",
    "25D",
    "45D",  # calendar-day bins
    "W",
    "2W",
    "3W",  # weeks (Sunday-end)
    "W-FRI",  # market-friendly week
    "M",
    "2M",
    "3M",
    "6M",
    "A",  # month & annual (‘A’ ~ 1Yr)
]
# (Optional) business-day equivalents if you want “trading bar” versions:
FREQS_B = ["5B", "10B", "20B"]  # 5 business days ≈ trading week, etc.

# 3) build and persist
FRAMES = resample_many(DF_DAILY, FREQS, outdir="artifacts/frames", overwrite=True)
FRAMES_B = resample_many(DF_DAILY, FREQS_B, outdir="artifacts/frames_b", overwrite=True)

# 4) inspect
FRAMES["1M"].head()  # monthly OHLCV with calendar fields attached
FRAMES["W-FRI"].tail(3)  # market-aligned weekly
FRAMES["25D"].tail(3)  # 25-calendar-day bars

# 5) seasonal summaries on the original daily (or any frame)
SEASON_RET = seasonal_summary(DF_DAILY, price_col="close", ret_kind="arith")
SEASON_RET_G = seasonal_summary(DF_DAILY, price_col="close", ret_kind="geom")
