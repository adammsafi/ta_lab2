# -*- coding: utf-8 -*-
"""
Created on Sun Nov  2 21:48:50 2025

@author: asafi
"""

from pathlib import Path
import pandas as pd
from ta_lab2.features.resample import resample_many, seasonal_summary
from ta_lab2.features.feature_pack import attach_core_features

# 1) Load your daily BTC data
src_csv = Path("data/btc.csv")
if src_csv.exists():
    DF_DAILY = pd.read_csv(src_csv)
else:
    DF_DAILY = pd.read_parquet("artifacts/btc.parquet")

# 2) Define the timeframes you want
FREQS = ["2D","3D","4D","5D","10D","25D","45D","W","W-FRI","2W","3W","M","2M","3M","6M","A"]

# 3) Resample and persist the raw OHLCV frames
FRAMES = resample_many(DF_DAILY, FREQS, outdir="artifacts/frames", overwrite=True)

# 4) 🔥 Attach core features (returns, vol, EMAs, autocorr, etc.) to each frame
for freq, frame in FRAMES.items():
    FRAMES[freq] = attach_core_features(frame, freq=freq)
    # persist enriched frame
    try:
        FRAMES[freq].to_parquet(f"artifacts/frames/{freq}.parquet")
    except Exception:
        FRAMES[freq].to_csv(f"artifacts/frames/{freq}.csv", index=False)

# 5) (Optional) seasonal summary
SEASON_RET = seasonal_summary(DF_DAILY)
