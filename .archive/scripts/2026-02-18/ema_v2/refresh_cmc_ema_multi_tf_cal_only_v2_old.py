from __future__ import annotations

import os
import argparse
from pathlib import Path
from typing import Sequence

from dotenv import load_dotenv  # make sure python-dotenv is installed
# pip install python-dotenv

from ta_lab2.scripts.emas.refresh_cmc_emas import (
    refresh,
    _load_all_ids,
    _parse_ids,
)


# ------------------------------------------------------------
# LOAD db_config.env AUTOMATICALLY (ONE TIME AT IMPORT)
# ------------------------------------------------------------

# Determine project root:
# script path → /src/ta_lab2/scripts/emas → go up 4 levels to reach repo root
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[3]

ENV_PATH = PROJECT_ROOT / "db_config.env"

if not ENV_PATH.exists():
    raise FileNotFoundError(
        f"Could not find db_config.env at {ENV_PATH}. "
        f"Ensure it exists in the project root."
    )

# Load environment variables from db_config.env
load_dotenv(ENV_PATH)

# Pull the DB URL from environment
DEFAULT_DB_URL = os.getenv("MARKETDATA_DB_URL")

if not DEFAULT_DB_URL:
    raise RuntimeError(
        "MARKETDATA_DB_URL is not set in db_config.env. "
        "Please add MARKETDATA_DB_URL=... inside db_config.env"
    )


# ------------------------------------------------------------
# MAIN LOGIC
# ------------------------------------------------------------

def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Refresh ONLY cmc_ema_multi_tf_cal (no daily, no non-cal, no views)."
    )
    parser.add_argument(
        "--ids",
        nargs="+",
        required=True,
        help="Asset ids to update (space- or comma-separated), or 'all'.",
    )
    parser.add_argument("--start", default=None)
    parser.add_argument("--end", default=None)
    parser.add_argument(
        "--db-url",
        default=DEFAULT_DB_URL,
        help="Database URL. Defaults to MARKETDATA_DB_URL loaded from db_config.env",
    )

    args = parser.parse_args(list(argv) if argv is not None else None)

    db_url = args.db_url

    print(f"[refresh_cmc_ema_multi_tf_cal_only] Using DB URL: {db_url}")

    # Determine asset IDs
    if len(args.ids) == 1 and args.ids[0].strip().lower() == "all":
        ids = _load_all_ids(db_url)
    else:
        ids = _parse_ids(args.ids)

    # Run refresh
    refresh(
        ids=ids,
        start=args.start,
        end=args.end,
        db_url=db_url,
        update_daily=False,
        update_multi_tf=False,
        update_cal_multi_tf=True,
        refresh_all_emas_view=False,
        refresh_price_emas_view=False,
        refresh_price_emas_d1d2_view=False,
    )


if __name__ == "__main__":
    main()


"""
Example usage:

runfile(
    'C:/Users/asafi/Downloads/ta_lab2/src/ta_lab2/scripts/emas/refresh_cmc_ema_multi_tf_cal_only.py',
    wdir='C:/Users/asafi/Downloads/ta_lab2',
    args='--ids all'
)

runfile(
    'C:/Users/asafi/Downloads/ta_lab2/src/ta_lab2/scripts/emas/refresh_cmc_ema_multi_tf_cal_only.py',
    wdir='C:/Users/asafi/Downloads/ta_lab2',
    args='--ids 1 52 1975 5426'
)
"""
