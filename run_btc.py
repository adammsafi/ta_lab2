# -*- coding: utf-8 -*-
"""
Created on Fri Oct 31 16:20:11 2025

@author: asafi
"""

# -*- coding: utf-8 -*-
"""
Runner for the BTC pipeline (no install required).
"""

import sys, os

# 1) Point to the src directory that contains the 'ta_lab2' package
SRC_DIR = r"C:\Users\asafi\Downloads\ta_lab2\src"
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

# 2) (Optional) sanity check
if not os.path.isdir(SRC_DIR):
    raise RuntimeError(f"src directory not found: {SRC_DIR}")

# 3) Import and run
from ta_lab2.pipelines.btc_pipeline import main

main([
    "--csv", r"C:\Users\asafi\Downloads\ta_lab2\data\Bitcoin_01_1_2016-10_26_2025_historical_data_coinmarketcap.csv",
    "--check", "2015-01-01", "2015-02-01",
    "--outdir", r"C:\Users\asafi\Downloads\ta_lab2\out"
])
