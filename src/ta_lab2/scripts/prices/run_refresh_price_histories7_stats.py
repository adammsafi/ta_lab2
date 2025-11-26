# -*- coding: utf-8 -*-
"""
Runner script to invoke ta_lab2.scripts.prices.refresh_price_histories7_stats from Spyder.

Usage in Spyder (IPython console)
---------------------------------

    %runfile C:/Users/asafi/Downloads/cmc_price_histories/run_refresh_price_histories7_stats.py \
        --wdir C:/Users/asafi/Downloads/ta_lab2
"""

from __future__ import annotations

import os
import sys

# Path to your ta_lab2 repo root
REPO_ROOT = r"C:/Users/asafi/Downloads/ta_lab2"

# Ensure repo root is on sys.path so `import ta_lab2` works
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

# Set working directory to repo root
try:
    os.chdir(REPO_ROOT)
except FileNotFoundError:
    # If the path is wrong, you'll see it and can adjust REPO_ROOT
    pass

# Import the main function from your stats script
from ta_lab2.scripts.prices.refresh_price_histories7_stats import main as refresh_price_histories7_stats_main


def main() -> None:
    """
    Wrapper around refresh_price_histories7_stats.main() for Spyder.

    Edit DB_URL if you want to override TARGET_DB_URL from ta_lab2.config.
    """
    # Leave as None to use TARGET_DB_URL (which now resolves to MARKETDATA_DB_URL)
    DB_URL = None
    # Or override explicitly:
    # DB_URL = "postgresql://postgres:password@localhost:5432/your_db"

    refresh_price_histories7_stats_main(db_url=DB_URL)


if __name__ == "__main__":
    main()
