# -*- coding: utf-8 -*-
"""
Created on Sun Dec 28 14:17:16 2025

@author: asafi
"""

import shutil
from pathlib import Path

kept_dir = Path(r"C:\Users\asafi\Documents\ProjectTT\ChatGPT\20251228\out\kept")
zip_path = Path(r"C:\Users\asafi\Documents\ProjectTT\ChatGPT\20251228\out\kept_chats.zip")

base_name = str(zip_path)[:-4]  # remove ".zip"
shutil.make_archive(base_name, "zip", root_dir=str(kept_dir))

print("Wrote:", zip_path)
