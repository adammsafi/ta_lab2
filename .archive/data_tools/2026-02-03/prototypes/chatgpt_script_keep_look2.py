# -*- coding: utf-8 -*-
"""
Created on Sun Dec 28 14:12:02 2025

@author: asafi
"""

import csv
from pathlib import Path

p = Path(r"C:\Users\asafi\Documents\ProjectTT\ChatGPT\20251228\out\kept_manifest.csv")

print("Reading:", p)
with p.open("r", encoding="utf-8") as f:
    first_line = f.readline().strip()
print("Header line:", first_line)
