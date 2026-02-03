# -*- coding: utf-8 -*-
"""
Created on Sun Dec 28 14:11:21 2025

@author: asafi
"""

import csv
from pathlib import Path

manifest = Path(
    r"C:\Users\asafi\Documents\ProjectTT\ChatGPT\20251228\out\kept_manifest.csv"
)

missing = []
with manifest.open("r", encoding="utf-8") as f:
    r = csv.DictReader(f)
    for row in r:
        if row["status"] == "MISSING":
            missing.append(row)

print("Missing rows:", len(missing))
for m in missing:
    print("id:", m["id"])
    print("src_path:", m["src_path"])
