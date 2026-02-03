# -*- coding: utf-8 -*-
"""
Created on Sun Dec 28 14:12:37 2025

@author: asafi
"""

import csv
from pathlib import Path

p = Path(r"C:\Users\asafi\Documents\ProjectTT\ChatGPT\20251228\out\kept_manifest.csv")

missing = []
with p.open("r", encoding="utf-8") as f:
    r = csv.DictReader(f)
    for row in r:
        if (row.get("status") or "").strip().upper() == "MISSING":
            missing.append(row)

print("Missing rows:", len(missing))
for m in missing:
    print("row:", m.get("row"))
    print("id:", m.get("id"))
    print("src_path:", m.get("src_path"))
    print("error:", m.get("error"))
    print("---")
